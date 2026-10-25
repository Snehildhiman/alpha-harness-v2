"""Health, since yesterday, a check right before submitting, and backups.

* ``GET /api/overview/health``: BRAIN session, catalog sync, models, tasks, simulations, LLM
  keys, autopilot, disk and the last backup on one screen, each with a plain ok or not.
* ``GET /api/overview/since``: what the last 24 hours (or ``hours``) brought: new Alphas per
  type, new submittable ones, new near-misses, simulations by outcome.
* ``POST /api/overview/presubmit``: BRAIN's submission checks run again for one Alpha (its
  regions for an RA family) right before you submit it on BRAIN. Spends no simulations.
* ``POST /api/overview/backups`` and friends: a zip of the vault, the crowd history, the
  models and the app's database, kept in the data folder. The key that unlocks saved
  credentials is left out, so a backup on its own reveals no password or API key.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from .. import backup, workers
from ..db.models import (
    Preference,
    SimStatus,
    SimulationRecord,
    Study,
    StudyStatus,
    Trial,
    TrialState,
    utcnow,
)
from ..engine.slots import errored_for_good
from ..labs.params import TASK_SAMPLERS
from ..labs.theme_templates import TEMPLATES
from ..recent import Recent
from ..repair.rank import near_miss
from ..schemas import Out
from ..separation import Judged, Kind, Verdict
from ..vault import yields
from .deps import State, refuse
from .separation import figure, judge_vault

router = APIRouter(prefix="/api/overview", tags=["overview"])


# -- health -----------------------------------------------------------------------------------


class HealthItem(Out):
    key: str
    label: str
    ok: bool
    #: ``warn`` is not broken, but worth a look.
    level: str
    value: str
    detail: str | None = None
    #: The screen that fixes it.
    link: str | None = None


class AppHealth(Out):
    ok: bool
    items: list[HealthItem]


def _ago(when: datetime | None) -> str:
    if when is None:
        return "never"
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    seconds = (datetime.now(UTC) - when).total_seconds()
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400 * 2:
        return f"{seconds / 3600:.0f} h ago"
    return f"{seconds / 86400:.0f} days ago"


def _item(key: str, label: str, level: str, value: str, **extra: Any) -> HealthItem:
    return HealthItem(key=key, label=label, ok=level != "bad", level=level, value=value, **extra)


@router.get("/health")
async def health(state: State) -> AppHealth:
    """Everything that keeps the app finding alphas, each ok, worth a look, or broken."""
    items: list[HealthItem] = []
    session = state.auth.session
    if not session.authenticated:
        items.append(
            _item(
                "session",
                "BRAIN session",
                "bad",
                "Signed out",
                link="/dashboard",
                detail="Sign in: nothing simulates or syncs until you do.",
            )
        )
    else:
        left = (session.expires_at or 0) - datetime.now(UTC).timestamp()
        items.append(
            _item(
                "session",
                "BRAIN session",
                "warn" if 0 < left < 1800 else "ok",
                f"Signed in as {session.full_name or session.user_id}",
                detail=f"Expires in {int(left // 60)} min" if left > 0 else None,
            )
        )

    runs = await state.sync.runs(limit=20)
    failed = [r for r in runs[:10] if r.error]
    last = next((r.finished_at for r in runs if r.finished_at), None)
    ordinary, _ = await state.daily_sync.last_synced()
    stale = ordinary is None or (datetime.now(UTC).date() - ordinary).days > 2
    items.append(
        _item(
            "catalog",
            "Data catalog",
            "bad" if not runs else ("warn" if failed or stale else "ok"),
            f"Last sync {_ago(last)}" if runs else "Never synced",
            detail=(
                f"{len(failed)} of the last syncs failed: {failed[0].error}"[:300]
                if failed
                else (f"Crowd snapshot {ordinary}" if ordinary else "No crowd snapshot yet")
            ),
            link="/sync",
        )
    )

    models = await state.predictors.current()
    fresh = await state.predictors.new_since_training()
    if models is None:
        items.append(
            _item(
                "models",
                "Models",
                "warn",
                "Not trained",
                link="/models",
                detail=f"{fresh:,} Alphas to learn from. Train them on the Models screen.",
            )
        )
    else:
        trained = datetime.fromisoformat(models.trained_at)
        targets = sum(r.trained for r in models.reports)
        items.append(
            _item(
                "models",
                "Models",
                "warn" if fresh > 2000 else "ok",
                f"Trained {_ago(trained)} on {models.alphas:,} Alphas, {targets} targets",
                detail=f"{fresh:,} new results since" if fresh else None,
                link="/models",
            )
        )

    day_ago = utcnow() - timedelta(days=1)
    async with state.db.session() as db:
        statuses = dict(
            (await db.execute(select(Study.status, func.count()).group_by(Study.status)))
            .tuples()
            .all()
        )
        outcomes = dict(
            (
                await db.execute(
                    select(SimulationRecord.status, func.count())
                    .where(SimulationRecord.created_at >= day_ago)
                    .group_by(SimulationRecord.status)
                )
            )
            .tuples()
            .all()
        )
    running = int(statuses.get(StudyStatus.RUNNING, 0)) + int(statuses.get(StudyStatus.QUEUED, 0))
    broken = int(statuses.get(StudyStatus.FAILED, 0))
    items.append(
        _item(
            "tasks",
            "Tasks",
            "warn" if broken else "ok",
            f"{running} running, {int(statuses.get(StudyStatus.PAUSED, 0))} paused",
            detail=f"{broken} failed" if broken else None,
            link="/tasks",
        )
    )
    errors = int(outcomes.get(SimStatus.ERROR, 0)) + int(outcomes.get(SimStatus.FAILED, 0))
    done = int(outcomes.get(SimStatus.COMPLETE, 0)) + int(outcomes.get(SimStatus.WARNING, 0))
    share = errors / max(1, errors + done)
    items.append(
        _item(
            "simulations",
            "Simulations, last 24 h",
            "warn" if share > 0.2 and errors > 10 else "ok",
            f"{done:,} done, {errors:,} errored",
            detail=(
                f"{share:.0%} errored: open Tasks to see BRAIN's messages" if share > 0.2 else None
            ),
            link="/tasks",
        )
    )

    keys = [k for k in await state.llm.keys.list_keys() if k.enabled]
    items.append(
        _item(
            "llm",
            "LLM keys",
            "ok" if keys else "warn",
            f"{len(keys)} enabled" if keys else "None (the built-in labs need none)",
            link="/ai/keys",
        )
    )
    pilot = state.autopilot
    items.append(
        _item(
            "autopilot",
            "Autopilot",
            "ok",
            "On" if pilot.enabled else "Off",
            detail=pilot.last,
        )
    )

    worst = workers.watchdog.worst_last_minute()
    last = workers.watchdog.stalls[-1] if workers.watchdog.stalls else None
    items.append(
        _item(
            "responsive",
            "Responsiveness",
            "bad" if worst > 5 else ("warn" if worst > 1 else "ok"),
            f"Slowest answer delay in the last minute: {worst:.1f} s",
            detail=(
                f"Last stall {last['seconds']} s at {last['at']}"
                + (f" in {last['where'][0]}" if last["where"] else "")
                if last
                else None
            ),
        )
    )

    folder = state.settings.data_dir
    usage = await asyncio.to_thread(shutil.disk_usage, folder)
    free_gb = usage.free / 1e9
    items.append(
        _item(
            "disk",
            "Disk",
            "bad" if free_gb < 1 else ("warn" if free_gb < 5 else "ok"),
            f"{free_gb:.1f} GB free",
            detail=str(folder),
        )
    )
    backups = _backups(state)
    newest = backups[0][1] if backups else None
    items.append(
        _item(
            "backup",
            "Backup",
            "warn" if newest is None or datetime.now(UTC) - newest > timedelta(days=7) else "ok",
            f"Last {_ago(newest)}",
            detail="Make one from this screen." if newest is None else None,
        )
    )
    return AppHealth(ok=all(i.ok for i in items), items=items)


class Stall(Out):
    at: str
    seconds: float
    #: The app's own code the loop was in, innermost first; empty when it was waiting on
    #: worker threads rather than running code itself.
    where: list[str]


@router.get("/stalls")
async def stalls() -> list[Stall]:
    """The last times the app stopped answering for 2 s or more, newest first."""
    return [Stall.model_validate(s) for s in reversed(workers.watchdog.stalls)]


# -- since yesterday --------------------------------------------------------------------------


class SinceAlpha(Out):
    alpha_id: str
    kind: str
    region: str | None
    sharpe: float | None
    fitness: float | None
    expression: str | None


class SinceKind(Out):
    kind: str
    new: int
    submittable: int
    near_misses: int


class Since(Out):
    hours: int
    new: int
    submittable: int
    near_misses: int
    by_kind: list[SinceKind]
    simulations: dict[str, int]
    #: The best new submittable Alphas, strongest Sharpe first.
    best: list[SinceAlpha]


def _created(item: Judged) -> datetime | None:
    value = item.row.get("date_created")
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            found = datetime.fromisoformat(value)
        except ValueError:
            return None
        return found if found.tzinfo else found.replace(tzinfo=UTC)
    return None


@router.get("/since")
async def since(state: State, hours: Annotated[int, Query(ge=1, le=24 * 14)] = 24) -> Since:
    """What the last ``hours`` brought, by Alpha type. Reads only what is stored."""
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    vault = await judge_vault(state)

    def tally() -> tuple[list[Judged], list[Judged], list[Judged]]:
        new = [i for i in vault if (c := _created(i)) is not None and c >= cutoff]
        ready = [i for i in new if i.judgement.verdict in (Verdict.SUBMITTABLE, Verdict.RECHECK)]
        near = [
            i for i in new if i.judgement.verdict == Verdict.REFUSED and near_miss(i) is not None
        ]
        return new, ready, near

    new, ready, near = await asyncio.to_thread(tally)
    kinds = list(Kind)
    by_kind = [
        SinceKind(
            kind=k.value,
            new=sum(1 for i in new if i.judgement.kind == k),
            submittable=sum(1 for i in ready if i.judgement.kind == k),
            near_misses=sum(1 for i in near if i.judgement.kind == k),
        )
        for k in kinds
    ]
    async with state.db.session() as db:
        outcomes = dict(
            (
                await db.execute(
                    select(SimulationRecord.status, func.count())
                    .where(SimulationRecord.created_at >= cutoff)
                    .group_by(SimulationRecord.status)
                )
            )
            .tuples()
            .all()
        )
    ready.sort(key=lambda i: -(figure(i, "sharpe") or float("-inf")))
    return Since(
        hours=hours,
        new=len(new),
        submittable=len(ready),
        near_misses=len(near),
        by_kind=[k for k in by_kind if k.new],
        simulations={str(k): int(v) for k, v in outcomes.items()},
        best=[
            SinceAlpha(
                alpha_id=str(i.row.get("alpha_id")),
                kind=i.judgement.kind.value,
                region=i.row.get("region"),
                sharpe=figure(i, "sharpe"),
                fitness=figure(i, "fitness"),
                expression=i.row.get("expression"),
            )
            for i in ready[:10]
        ],
    )


# -- right before submitting ------------------------------------------------------------------


class CheckLine(Out):
    name: str
    result: str
    value: float | None = None
    limit: float | None = None


class Presubmit(Out):
    alpha_id: str
    #: Every checked Alpha passed every gating check just now.
    ok: bool
    #: ``submittable``, ``pending`` (BRAIN still computing a check) or ``refused``.
    verdict: str
    checked: list[str]
    failed: list[CheckLine]
    checks: list[CheckLine]
    checked_at: str
    #: Where it is submitted: on BRAIN, never from here.
    link: str


def _line(check: dict[str, Any]) -> CheckLine:
    def num(key: str) -> float | None:
        value = check.get(key)
        return float(value) if isinstance(value, int | float) else None

    return CheckLine(
        name=str(check.get("name") or ""),
        result=str(check.get("result") or ""),
        value=num("value"),
        limit=num("limit"),
    )


@router.post("/presubmit")
async def presubmit(
    state: State, alpha_id: Annotated[str, Body(alias="alphaId", embed=True)]
) -> Presubmit:
    """BRAIN's submission checks, run again now for one Alpha, so a correlation that rose
    since the last check is caught before you submit. Spends no simulations."""
    alpha_id = alpha_id.strip()
    vault = await judge_vault(state)
    item = next((i for i in vault if str(i.row.get("alpha_id")) == alpha_id), None)
    if item is None:
        raise refuse(404, "unknown_alpha", f"{alpha_id} is not in your vault. Sync it first.")
    ids = [str(c.get("alpha_id")) for c in item.children] or [alpha_id]
    results: list[tuple[str, list[dict[str, Any]], str | None]] = []
    for one in ids:
        try:
            body = await state.endpoints.check_alpha(one)
        except Exception as exc:
            raise refuse(502, "check_failed", f"BRAIN did not check {one}: {exc}") from exc
        checks = (body.get("is") or {}).get("checks") or []
        if checks:
            await state.alphas.save_checks(one, checks)
        mode = str((body.get("settings") or {}).get("simulationMode") or "") or None
        results.append((one, checks, mode))
    verdicts = [yields.verdict(yields.without_quota_checks(c), m) for _, c, m in results]
    if item.judgement.kind == Kind.RA:
        # A family is taken when two of its regions pass.
        passing = sum(1 for v in verdicts if v == "submittable")
        found = (
            "submittable" if passing >= 2 else ("pending" if "pending" in verdicts else "refused")
        )
    elif "refused" in verdicts or None in verdicts:
        found = "refused"
    elif "pending" in verdicts:
        found = "pending"
    else:
        found = "submittable"
    every = [_line(c) for _, checks, _ in results for c in checks]
    await _note_check(state, alpha_id, passed=found == "submittable")
    return Presubmit(
        alpha_id=alpha_id,
        ok=found == "submittable",
        verdict=found,
        checked=ids,
        failed=[c for c in every if c.result == "FAIL"],
        checks=every,
        checked_at=datetime.now(UTC).isoformat(timespec="seconds"),
        link=f"https://platform.worldquantbrain.com/alpha/{alpha_id}",
    )


# -- reminders: checked and passing, but not submitted ---------------------------------------

#: Where the last passing check of each Alpha is kept, in the preference table.
CHECKED_KEY = "_presubmit_passed"
#: A pass this old is stale: correlations only drift up, so check again before submitting.
REMIND_AFTER = timedelta(days=2)
#: Passing checks remembered, newest kept.
CHECKED_MAX = 500


async def _note_check(state: State, alpha_id: str, *, passed: bool) -> None:
    async with state.db.session() as db:
        row = await db.get(Preference, CHECKED_KEY)
        found: dict[str, str] = dict(row.value or {}) if row is not None else {}
        if passed:
            found[alpha_id] = datetime.now(UTC).isoformat(timespec="seconds")
        else:
            found.pop(alpha_id, None)
        kept = dict(sorted(found.items(), key=lambda kv: kv[1])[-CHECKED_MAX:])
        await db.merge(Preference(key=CHECKED_KEY, value=kept))


class Reminder(Out):
    alpha_id: str
    kind: str
    region: str | None
    sharpe: float | None
    checked_at: str
    days: float
    link: str


@router.get("/reminders")
async def reminders(state: State) -> list[Reminder]:
    """Alphas that passed *Check now* two or more days ago and are still not submitted."""
    async with state.db.session() as db:
        row = await db.get(Preference, CHECKED_KEY)
        found: dict[str, str] = dict(row.value or {}) if row is not None else {}
    if not found:
        return []
    by_id = {str(i.row.get("alpha_id")): i for i in await judge_vault(state)}
    now = datetime.now(UTC)
    out: list[Reminder] = []
    gone: list[str] = []
    for alpha_id, at in found.items():
        item = by_id.get(alpha_id)
        if item is None or item.judgement.verdict == Verdict.SUBMITTED:
            gone.append(alpha_id)
            continue
        when = datetime.fromisoformat(at)
        if now - when < REMIND_AFTER:
            continue
        out.append(
            Reminder(
                alpha_id=alpha_id,
                kind=item.judgement.kind.value,
                region=item.row.get("region"),
                sharpe=figure(item, "sharpe"),
                checked_at=at,
                days=round((now - when).total_seconds() / 86400, 1),
                link=f"https://platform.worldquantbrain.com/alpha/{alpha_id}",
            )
        )
    if gone:
        async with state.db.session() as db:
            await db.merge(
                Preference(key=CHECKED_KEY, value={k: v for k, v in found.items() if k not in gone})
            )
    return sorted(out, key=lambda r: -(r.sharpe or 0.0))


# -- why BRAIN refused simulations -----------------------------------------------------------

_DETAIL = re.compile(r"\"[^\"]*\"|'[^']*'|`[^`]*`|\b\d+(?:\.\d+)?\b")

#: Plain advice for the refusals seen most, matched on BRAIN's words.
_ADVICE: tuple[tuple[str, str], ...] = (
    (
        "unit[group",
        "A label (a cluster, sector or country code) used as a number. The labs now use such "
        "fields only as the group of a group_ operator, and refuse them anywhere else.",
    ),
    (
        "no longer waited on",
        "BRAIN failed on this one simulation for half an hour. Retried once; if it fails the "
        "same way twice, the app stops sending it (often a SuperAlpha combo BRAIN cannot run).",
    ),
    (
        "unknown variable",
        "A field this account cannot read, or one missing from that region or universe. "
        "Sync the catalog, and leave out the dataset if it keeps happening.",
    ),
    (
        "inaccessible",
        "An operator or field this account has no access to. Re-sync your operators (Sync with "
        "BRAIN) so the labs stop writing it.",
    ),
    (
        "input",
        "An operator given the wrong inputs: a template or LLM prompt writes it wrong. Fix the "
        "template, or tell the prompt the operator's inputs.",
    ),
    (
        "unit",
        "Values of different units added together (a price and a volume). Rank or z-score "
        "each side first.",
    ),
    ("timed out", "BRAIN took too long. These are retried; nothing to fix."),
    ("timeout", "BRAIN took too long. These are retried; nothing to fix."),
    ("concurrent", "Too many at once. The engine slows down by itself."),
    ("throttl", "Too many at once. The engine slows down by itself."),
    ("not sent again", "Refused before with these exact settings, so it was not spent again."),
)


def _advice(message: str) -> str | None:
    text = message.lower()
    return next((tip for word, tip in _ADVICE if word in text), None)


class ErrorGroup(Out):
    reason: str
    count: int
    #: BRAIN would refuse it again: worth fixing at the source.
    for_good: bool
    advice: str | None
    example: str
    expression: str | None
    tasks: list[str]
    last_at: str


class ErrorSummary(Out):
    days: int
    total: int
    groups: list[ErrorGroup]


@router.get("/errors")
async def errors(state: State, days: Annotated[int, Query(ge=1, le=90)] = 7) -> ErrorSummary:
    """Why BRAIN refused simulations lately, grouped by reason, most common first."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    async with state.db.session() as db:
        rows = (
            await db.execute(
                select(
                    SimulationRecord.message,
                    SimulationRecord.expression,
                    SimulationRecord.task,
                    SimulationRecord.created_at,
                )
                .where(
                    SimulationRecord.created_at >= cutoff,
                    SimulationRecord.status.in_(
                        (SimStatus.ERROR, SimStatus.FAILED, SimStatus.REJECTED)
                    ),
                    SimulationRecord.message.is_not(None),
                )
                .order_by(SimulationRecord.created_at.desc())
                .limit(20_000)
            )
        ).all()

    def group() -> list[ErrorGroup]:
        by: dict[str, dict[str, Any]] = {}
        for message, expression, task, at in rows:
            reason = _DETAIL.sub("…", str(message))[:200]
            g = by.setdefault(
                reason,
                {
                    "count": 0,
                    "example": str(message),
                    "expression": expression,
                    "tasks": {},
                    "last": at,
                },
            )
            g["count"] += 1
            g["tasks"][task] = g["tasks"].get(task, 0) + 1
        return [
            ErrorGroup(
                reason=reason,
                count=g["count"],
                for_good=errored_for_good(g["example"]),
                advice=_advice(g["example"]),
                example=g["example"][:500],
                expression=g["expression"],
                tasks=[t for t, _ in sorted(g["tasks"].items(), key=lambda kv: -kv[1])[:3]],
                last_at=g["last"].isoformat(timespec="seconds"),
            )
            for reason, g in sorted(by.items(), key=lambda kv: -kv[1]["count"])[:30]
        ]

    return ErrorSummary(days=days, total=len(rows), groups=await asyncio.to_thread(group))


# -- which templates pay ---------------------------------------------------------------------


class TemplateScore(Out):
    lab: str
    name: str
    #: Alphas BRAIN scored from it.
    simulated: int
    #: Of those, submittable, needing a re-check, or submitted.
    passed: int
    pass_rate: float
    mean_sharpe: float | None


#: Results needed before a template is ranked: fewer is luck.
MIN_RESULTS = 5
_PASSING = (Verdict.SUBMITTABLE, Verdict.RECHECK, Verdict.SUBMITTED)


def _template_of(
    sampler: str, name: str | None, label: str | None, source: str, params: Any
) -> tuple[str, str]:
    p = params if isinstance(params, dict) else {}
    if p.get("shape"):
        return "Region Agnostic shapes", str(p["shape"])
    if p.get("recipe"):
        return "Super Alpha", str(p["recipe"]).split(" · Decay")[0]
    if sampler == "search" and p.get("family") == "tpl":
        found = next((t.name for t in TEMPLATES if t.expression == p.get("template")), None)
        return "Theme template", found or str(p.get("template"))
    if sampler == "search" and p.get("family"):
        return "Search Lab shape", str(p["family"])
    first = next((line for line in source.splitlines() if line.strip()), "")
    return TASK_SAMPLERS.get(sampler, sampler), (name or label or first)[:160]


#: The leaderboard moves only as results arrive: read at most every ten minutes, and the
#: last answer shown at once meanwhile.
_boards = Recent(ttl=600)


@router.get("/templates")
async def templates(state: State) -> list[TemplateScore]:
    """Each template, shape or recipe by how often its Alphas pass, best first."""
    return await _boards.get("templates", lambda: _templates(state))


async def _templates(state: State) -> list[TemplateScore]:
    shape = func.json_extract(Trial.params, "$.shape")
    recipe = func.json_extract(Trial.params, "$.recipe")
    family = func.json_extract(Trial.params, "$.family")
    template = func.json_extract(Trial.params, "$.template")
    async with state.db.session() as db:
        rows = (
            await db.execute(
                # Only the three names, never whole rows: a long task holds 100,000 trials.
                select(Trial.study_id, shape, recipe, family, template, Trial.alpha_id)
                .where(Trial.state == TrialState.COMPLETE, Trial.alpha_id.is_not(None))
                .distinct()
            )
        ).all()
        studies = {
            sid: (sampler, name, label, source)
            for sid, sampler, name, label, source in (
                await db.execute(
                    select(
                        Study.id,
                        Study.sampler,
                        Study.template_name,
                        Study.label,
                        func.substr(Study.template_source, 1, 400),
                    )
                )
            ).all()
        }
    vault = await judge_vault(state)

    def score() -> list[TemplateScore]:
        verdict: dict[str, Verdict] = {}
        sharpe: dict[str, float | None] = {}
        for item in vault:
            v = item.judgement.verdict
            for row in [item.row, *item.children]:
                key = str(row.get("alpha_id"))
                verdict[key] = v
                sharpe[key] = figure(item, "sharpe")
        tally: dict[tuple[str, str], list[Any]] = {}
        seen: set[tuple[tuple[str, str], str]] = set()
        for study_id, shape_of, recipe_of, family_of, template_of, alpha_id in rows:
            sampler, name, label, source = studies.get(study_id, ("", None, None, ""))
            params = {
                "shape": shape_of,
                "recipe": recipe_of,
                "family": family_of,
                "template": template_of,
            }
            key = _template_of(str(sampler), name, label, str(source or ""), params)
            if (key, alpha_id) in seen or alpha_id not in verdict:
                continue
            seen.add((key, alpha_id))
            t = tally.setdefault(key, [0, 0, []])
            t[0] += 1
            t[1] += verdict[alpha_id] in _PASSING
            if (s := sharpe.get(alpha_id)) is not None:
                t[2].append(s)
        out = [
            TemplateScore(
                lab=lab,
                name=name,
                simulated=n,
                passed=p,
                pass_rate=p / n,
                mean_sharpe=sum(sh) / len(sh) if sh else None,
            )
            for (lab, name), (n, p, sh) in tally.items()
            if n >= MIN_RESULTS
        ]
        out.sort(key=lambda t: (-t.pass_rate, -(t.mean_sharpe or -9.0)))
        return out[:200]

    return await asyncio.to_thread(score)


# -- backups --------------------------------------------------------------------------------


class Backup(Out):
    name: str
    created_at: str
    bytes: int


class Restored(Out):
    #: Rows added back, per table: only what was missing here.
    added: dict[str, int]
    models: bool
    #: The app's database waits for the next start.
    database: bool


def _backups(state: State) -> list[tuple[Path, datetime]]:
    return backup.listed(state.settings)


def _row(path: Path, when: datetime) -> Backup:
    return Backup(
        name=path.name, created_at=when.isoformat(timespec="seconds"), bytes=path.stat().st_size
    )


@router.get("/backups")
async def backups(state: State) -> list[Backup]:
    return [_row(p, w) for p, w in _backups(state)]


@router.post("/backups", status_code=201)
async def make_backup(state: State) -> Backup:
    """Zip the vault, the crowd history, the models and the app's database."""
    try:
        path = await backup.create(state)
    except RuntimeError as exc:
        raise refuse(409, "busy", str(exc)) from exc
    return _row(path, datetime.now(UTC))


@router.post("/backups/{name}/restore")
async def restore_backup(
    name: str,
    state: State,
    models: Annotated[bool, Body(embed=True)] = False,
    database: Annotated[bool, Body(embed=True)] = False,
) -> Restored:
    """Merge a backup back in: what is missing here is added, nothing newer is replaced.
    ``models`` restores its models too; ``database`` its tasks and settings, at next start."""
    path = backup.path_of(state.settings, name)
    if path is None:
        raise refuse(404, "unknown_backup", "No such backup.")
    try:
        found = await backup.restore(state, path, models=models, database=database)
    except RuntimeError as exc:
        raise refuse(409, "busy", str(exc)) from exc
    except (OSError, zipfile.BadZipFile) as exc:
        raise refuse(422, "bad_backup", f"The backup could not be read: {exc}") from exc
    await judge_vault(state, force=True)
    return Restored.model_validate(found)


#: Largest backup accepted from another computer.
MAX_UPLOAD = 4 * 1024**3


@router.post("/backups/upload", status_code=201)
async def upload_backup(request: Request, state: State) -> Backup:
    """Take a backup made on another computer (the zip as the body), to restore here."""
    where = backup.folder(state.settings)
    where.mkdir(parents=True, exist_ok=True)
    target = where / f"backup-{datetime.now(UTC):%Y%m%d-%H%M%S}-uploaded.zip"
    partial = target.with_suffix(".partial")
    size = 0
    with partial.open("wb") as out:
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_UPLOAD:
                out.close()
                partial.unlink(missing_ok=True)
                raise refuse(413, "too_large", "That file is larger than any backup.")
            out.write(chunk)
    if not zipfile.is_zipfile(partial) or "README.txt" not in zipfile.ZipFile(partial).namelist():
        partial.unlink(missing_ok=True)
        raise refuse(422, "bad_backup", "That is not an Alpha Harness backup.")
    partial.replace(target)
    return _row(target, datetime.now(UTC))


@router.get("/backups/{name}")
async def download_backup(name: str, state: State) -> FileResponse:
    path = backup.path_of(state.settings, name)
    if path is None:
        raise refuse(404, "unknown_backup", "No such backup.")
    return FileResponse(path, media_type="application/zip", filename=name)
