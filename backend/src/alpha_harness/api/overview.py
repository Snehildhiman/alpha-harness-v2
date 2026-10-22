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
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from ..db.models import SimStatus, SimulationRecord, Study, StudyStatus, utcnow
from ..repair.rank import near_miss
from ..schemas import Out
from ..separation import Judged, Kind, Verdict
from ..vault import yields
from .deps import State, refuse
from .separation import figure, judge_vault

router = APIRouter(prefix="/api/overview", tags=["overview"])

#: Catalog tables rebuilt by a sync: left out of a backup, which keeps what cannot be.
RESYNCABLE = frozenset({"data_field", "data_set", "data_category"})
#: Backups kept; the oldest go first.
KEEP_BACKUPS = 10


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


# -- backups ----------------------------------------------------------------------------------


class Backup(Out):
    name: str
    created_at: str
    bytes: int


def _folder(state: State) -> Path:
    return state.settings.data_dir / "backups" / "full"


def _backups(state: State) -> list[tuple[Path, datetime]]:
    folder = _folder(state)
    if not folder.exists():
        return []
    found = [
        (p, datetime.fromtimestamp(p.stat().st_mtime, UTC)) for p in folder.glob("backup-*.zip")
    ]
    return sorted(found, key=lambda pw: pw[1], reverse=True)


def _row(path: Path, when: datetime) -> Backup:
    return Backup(
        name=path.name, created_at=when.isoformat(timespec="seconds"), bytes=path.stat().st_size
    )


@router.get("/backups")
async def backups(state: State) -> list[Backup]:
    return [_row(p, w) for p, w in _backups(state)]


_backing_up = asyncio.Lock()


@router.post("/backups", status_code=201)
async def make_backup(state: State) -> Backup:
    """Zip the vault (every Alpha and its daily PnL), the crowd history, the models and the
    app's database. The catalog's fields are left out (a sync rebuilds them), and so is the
    key to saved credentials."""
    if _backing_up.locked():
        raise refuse(409, "busy", "A backup is being made already.")
    async with _backing_up:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        folder = _folder(state)
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as work:
            staging = Path(work)
            tables = [
                str(r["table_name"])
                for r in await state.catalog.query(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'main' AND table_type = 'BASE TABLE'"
                )
            ]
            for table in tables:
                if table in RESYNCABLE:
                    continue
                target = staging / f"{table}.parquet"
                await state.catalog.execute(
                    f"COPY {table} TO '{target.as_posix()}' (FORMAT parquet)"
                )
            await asyncio.to_thread(
                _copy_sqlite, state.settings.sqlite_path, staging / "harness.db"
            )
            target = folder / f"backup-{stamp}.zip"
            await asyncio.to_thread(_zip, staging, state.settings.data_dir / "models", target)
        for old, _ in _backups(state)[KEEP_BACKUPS:]:
            old.unlink(missing_ok=True)
        return _row(target, datetime.now(UTC))


def _copy_sqlite(source: Path, target: Path) -> None:
    """SQLite's backup API, never a file copy, which can tear a database in use."""
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)


def _zip(staging: Path, models: Path, target: Path) -> None:
    partial = target.with_suffix(".partial")
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as out:
        for path in sorted(staging.iterdir()):
            out.write(path, f"vault/{path.name}" if path.suffix == ".parquet" else path.name)
        if models.exists():
            for path in sorted(models.rglob("*")):
                if path.is_file():
                    out.write(path, f"models/{path.relative_to(models).as_posix()}")
        out.writestr(
            "README.txt",
            "Alpha Harness backup.\n"
            "vault/*.parquet: your Alphas, their daily PnL and the crowd history (DuckDB tables).\n"
            "harness.db: tasks, trials, settings (saved credentials stay locked: their key is "
            "not in this file).\nmodels/: the trained models in use.\n",
        )
    partial.replace(target)


@router.get("/backups/{name}")
async def download_backup(name: str, state: State) -> FileResponse:
    path = _folder(state) / name
    if not name.startswith("backup-") or not name.endswith(".zip") or path.parent != _folder(state):
        raise refuse(404, "unknown_backup", "No such backup.")
    if not path.exists():
        raise refuse(404, "unknown_backup", "No such backup.")
    return FileResponse(path, media_type="application/zip", filename=name)
