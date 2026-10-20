"""Alpha types, and whether each Alpha is submittable under its own type's rules.

The vault's :func:`~alpha_harness.vault.yields.verdict` judges every Alpha the same way, and
it deliberately ignores ``PROD_CORRELATION``. That is wrong for this account's targets:

* **Regular** and **region-agnostic** Alphas must pass prod (broad) correlation.
* **Power Pool** Alphas answer to ``POWER_POOL_CORRELATION`` instead, and never to prod
  correlation.
* **Current-theme** Power Pool Alphas must also match the running theme (``MATCHES_THEMES``).
* **SuperAlphas** are judged on their own checks, prod correlation included.

Self-correlation gates every type, as it already does in the vault's rule.

A region-agnostic Alpha is a family: one ``RA_PARENT`` (no statistics of its own) and up to
four ``RA_CHILD`` Alphas, one per region. BRAIN takes a family when at least two regions pass,
so a family is judged by counting the regions whose child passes the regular rules.

Pure functions only: no database, no HTTP. :mod:`.api.separation` feeds them vault rows.
"""

import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from .brain.schemas import QUICK_MODE
from .vault.yields import IGNORED_CHECKS, POWER_POOL_CHECK, REFUSING, checks_of, is_power_pool


class Kind(StrEnum):
    REGULAR = "regular"
    RA = "ra"
    POWER_POOL = "power_pool"
    THEME = "theme"
    SUPER = "super"


class Verdict(StrEnum):
    SUBMITTED = "submitted"
    SUBMITTABLE = "submittable"
    #: Every check passes, but its correlation results are too old to trust: the pool has
    #: moved since, and prod and Power Pool correlation only drift up. Re-check before submitting.
    RECHECK = "recheck"
    PENDING = "pending"
    REFUSED = "refused"


@dataclass(frozen=True, slots=True)
class Freshness:
    """How old a passing correlation result may be and still count. ``now`` is naive UTC."""

    now: datetime
    max_age: timedelta

    def stale(self, row: dict[str, Any]) -> bool:
        checked = _when(row)
        return checked is None or self.now - checked > self.max_age


def _when(row: dict[str, Any]) -> datetime | None:
    """When BRAIN last judged this Alpha: its last ``/check``, else when it was simulated."""
    for key in ("checks_at", "date_created"):
        value = row.get(key)
        if isinstance(value, datetime):
            return value.replace(tzinfo=None) if value.tzinfo else value
        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                continue
            return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed
    return None


PROD_CORRELATION = "PROD_CORRELATION"
SELF_CORRELATION = "SELF_CORRELATION"
THEME_CHECK = "MATCHES_THEMES"

#: The classification BRAIN gives a submitted Power Pool Alpha (never an unsubmitted one).
POWER_POOL_CLASSIFICATION = "power pool"

#: Regions an RA family needs passing before BRAIN takes it.
RA_MIN_REGIONS = 2

#: Labels the vault ignores, minus the ones a type-aware rule reads itself.
_LABELS = IGNORED_CHECKS - {PROD_CORRELATION, THEME_CHECK}


@dataclass(frozen=True, slots=True)
class CheckIssue:
    """One check standing between an Alpha and submission."""

    name: str
    result: str
    value: Any = None
    limit: Any = None


@dataclass(slots=True)
class Judgement:
    """What the rules say about one Alpha (or one RA family)."""

    kind: Kind
    verdict: Verdict
    failed: list[CheckIssue] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    #: RA families only: regions whose child passes, and regions tried.
    regions_passing: list[str] = field(default_factory=list)
    regions_tried: list[str] = field(default_factory=list)
    #: Power Pool Alphas: how the running theme's rule reads this Alpha.
    theme_note: str | None = None
    #: When BRAIN last judged it (naive UTC): its last re-check, else its simulation.
    checked_at: datetime | None = None


def _name(check: dict[str, Any]) -> str:
    return str(check.get("name", "")).upper()


def _result(check: dict[str, Any]) -> str:
    return str(check.get("result", "")).upper()


def _numbers(check: dict[str, Any]) -> tuple[float, float] | None:
    value, limit = check.get("value"), check.get("limit")
    if isinstance(value, int | float) and isinstance(limit, int | float):
        return float(value), float(limit)
    return None


def _classifications(raw: Any) -> list[str]:
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str) and raw:
        try:
            items = json.loads(raw)
        except json.JSONDecodeError, TypeError:
            return []
    else:
        return []
    return [str(i.get("name") if isinstance(i, dict) else i).lower() for i in items]


def matches_theme(checks: list[dict[str, Any]]) -> bool:
    """Whether BRAIN says this Alpha matches a running theme."""
    for check in checks:
        if _name(check) != THEME_CHECK:
            continue
        if _result(check) == "PASS":
            return True
        matched = check.get("matched")
        if isinstance(matched, list) and matched:
            return True
    return False


def is_power_pool_row(row: dict[str, Any], checks: list[dict[str, Any]]) -> bool:
    """BRAIN's Power Pool eligibility check, or the classification on a submitted one."""
    return is_power_pool(checks) or any(
        POWER_POOL_CLASSIFICATION in c for c in _classifications(row.get("classifications"))
    )


def kind_of(row: dict[str, Any], checks: list[dict[str, Any]], *, in_theme: bool = False) -> Kind:
    """Which tab an Alpha belongs on. RA children are reported as ``RA``; callers group them.

    ``in_theme``: the running theme's rule, checked locally (:mod:`.themes`), accepts it.
    BRAIN's own ``MATCHES_THEMES`` counts too, where it has run.
    """
    sim_type = str(row.get("sim_type") or "REGULAR").upper()
    if sim_type == "SUPER":
        return Kind.SUPER
    if sim_type in ("RA_PARENT", "RA_CHILD", "REGION_AGNOSTIC"):
        return Kind.RA
    if is_power_pool_row(row, checks):
        return Kind.THEME if in_theme or matches_theme(checks) else Kind.POWER_POOL
    return Kind.REGULAR


def _correlation_issue(check: dict[str, Any]) -> tuple[str, CheckIssue | None]:
    """``("ok" | "pending" | "fail", issue)`` for a correlation check.

    BRAIN's result decides when it is PASS or FAIL. A ``WARNING`` or empty result is read from
    the numbers: above the limit is a failure (the Sharpe-10%-higher exception is BRAIN's to
    apply, and it reports PASS when it does), at or below is a pass, no numbers is pending.
    """
    result = _result(check)
    issue = CheckIssue(_name(check), result, check.get("value"), check.get("limit"))
    if result == "PASS":
        return "ok", None
    if result in REFUSING:
        return "fail", issue
    if result == "PENDING":
        return "pending", None
    numbers = _numbers(check)
    if numbers is None:
        return "pending", None
    value, limit = numbers
    return ("fail", issue) if value > limit else ("ok", None)


def judge_checks(
    kind: Kind,
    checks: list[dict[str, Any]],
    *,
    simulation_mode: str | None = None,
    submitted: bool = False,
) -> Judgement:
    """Judge one Alpha's checks under ``kind``'s rules. RA children use the regular rules."""
    if submitted:
        return Judgement(kind, Verdict.SUBMITTED)
    failed: list[CheckIssue] = []
    pending: list[str] = []
    gated = 0

    for check in checks:
        name, result = _name(check), _result(check)
        if name in _LABELS:
            continue
        if name == THEME_CHECK:
            # On the theme tab only BRAIN's outright refusal counts: an unmatched or absent
            # result is BRAIN not having run it, and the local rule already placed the Alpha.
            if kind == Kind.THEME and result in REFUSING:
                gated += 1
                failed.append(CheckIssue(name, result))
            continue
        if name == PROD_CORRELATION and kind in (Kind.POWER_POOL, Kind.THEME):
            continue
        if name in (PROD_CORRELATION, SELF_CORRELATION, POWER_POOL_CHECK):
            if name == POWER_POOL_CHECK and kind not in (Kind.POWER_POOL, Kind.THEME):
                continue
            gated += 1
            state, issue = _correlation_issue(check)
            if state == "fail" and issue is not None:
                failed.append(issue)
            elif state == "pending":
                pending.append(name)
            continue
        gated += 1
        if result in REFUSING:
            failed.append(CheckIssue(name, result, check.get("value"), check.get("limit")))
        elif result not in ("PASS", "WARNING"):
            pending.append(name)

    # Correlation checks BRAIN never attached are not yet run: the Alpha is not proven.
    names = {_name(c) for c in checks}
    needed = {SELF_CORRELATION}
    if kind in (Kind.REGULAR, Kind.RA, Kind.SUPER):
        needed.add(PROD_CORRELATION)
    if kind in (Kind.POWER_POOL, Kind.THEME):
        needed.add(POWER_POOL_CHECK)
    pending.extend(sorted(n for n in needed - names if gated))

    if simulation_mode == QUICK_MODE:
        # BRAIN omits every submission check on a Quick Alpha: it must run in Full first.
        quick = CheckIssue("QUICK_MODE", "NEEDS_FULL_RUN")
        return Judgement(kind, Verdict.REFUSED, [quick, *failed], pending)
    if not gated:
        return Judgement(kind, Verdict.PENDING, failed, pending)
    if failed:
        return Judgement(kind, Verdict.REFUSED, failed, pending)
    if pending:
        return Judgement(kind, Verdict.PENDING, failed, pending)
    return Judgement(kind, Verdict.SUBMITTABLE)


def is_submitted(row: dict[str, Any]) -> bool:
    status = row.get("status")
    return bool(status) and str(status).upper() != "UNSUBMITTED"


#: Reads a Power Pool row against the running theme: ``(matches, note)``.
ThemeCheck = Callable[[dict[str, Any]], tuple[bool, str]]


def _age_out(judgement: Judgement, rows: list[dict[str, Any]], fresh: Freshness | None) -> None:
    """Move a submittable judgement to RECHECK when any row behind it is stale."""
    judgement.checked_at = min((w for r in rows if (w := _when(r))), default=None)
    if (
        fresh is not None
        and judgement.verdict == Verdict.SUBMITTABLE
        and any(fresh.stale(r) for r in rows)
    ):
        judgement.verdict = Verdict.RECHECK


def judge(
    row: dict[str, Any], theme: ThemeCheck | None = None, fresh: Freshness | None = None
) -> Judgement:
    """Judge one stored, non-RA vault row (or an RA child on its own)."""
    checks = checks_of(row.get("checks"))
    in_theme, note = False, None
    if theme is not None and is_power_pool_row(row, checks):
        in_theme, note = theme(row)
    kind = kind_of(row, checks, in_theme=in_theme)
    judgement = judge_checks(
        kind,
        checks,
        simulation_mode=row.get("simulation_mode"),
        submitted=is_submitted(row),
    )
    if kind == Kind.THEME and not in_theme:
        # Placed by BRAIN's own MATCHES_THEMES; say so, with the local rule's view beside it.
        note = "BRAIN's theme check passed" + (f" (local rule: {note})" if note else "")
    judgement.theme_note = note
    _age_out(judgement, [row], fresh)
    return judgement


def family_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """What ties RA children to their parent: rows carry no parent id, but BRAIN writes a
    family in one second, from one expression and one set of settings (see ``vault.store``)."""
    return (
        row.get("expression"),
        str(row.get("date_created")),
        row.get("delay"),
        row.get("neutralization"),
        row.get("decay"),
        row.get("truncation"),
    )


def judge_family(parent: dict[str, Any], children: list[dict[str, Any]]) -> Judgement:
    """An RA family: submittable once at least two regions' children pass the regular rules.

    The parent's own checks (when BRAIN attached any) are judged too, prod correlation
    included, and refuse the family if they refuse.
    """
    if is_submitted(parent) or any(is_submitted(c) for c in children):
        return Judgement(Kind.RA, Verdict.SUBMITTED)

    passing: set[str] = set()
    hopeful: set[str] = set()
    failed: list[CheckIssue] = []
    pending: list[str] = []
    tried = sorted({str(c.get("region")) for c in children if c.get("region")})
    for child in children:
        verdict = judge_checks(
            Kind.RA, checks_of(child.get("checks")), simulation_mode=child.get("simulation_mode")
        )
        region = str(child.get("region"))
        if verdict.verdict == Verdict.SUBMITTABLE:
            passing.add(region)
        elif verdict.verdict == Verdict.PENDING:
            hopeful.add(region)
            pending.extend(f"{region}:{p}" for p in verdict.pending)
        else:
            failed.extend(
                CheckIssue(f"{region}:{i.name}", i.result, i.value, i.limit) for i in verdict.failed
            )

    parent_checks = checks_of(parent.get("checks"))
    if parent_checks:
        own = judge_checks(Kind.RA, parent_checks, simulation_mode=parent.get("simulation_mode"))
        failed.extend(own.failed)
        if own.verdict == Verdict.PENDING:
            pending.extend(own.pending)
        if own.verdict == Verdict.REFUSED:
            return Judgement(Kind.RA, Verdict.REFUSED, failed, pending, sorted(passing), tried)

    regions = sorted(passing)
    if len(passing) >= RA_MIN_REGIONS and not (parent_checks and pending):
        return Judgement(Kind.RA, Verdict.SUBMITTABLE, [], [], regions, tried)
    if len(passing | hopeful) >= RA_MIN_REGIONS:
        return Judgement(Kind.RA, Verdict.PENDING, failed, pending, regions, tried)
    return Judgement(Kind.RA, Verdict.REFUSED, failed, pending, regions, tried)


@dataclass(slots=True)
class Judged:
    """One row of a tab: the Alpha (or RA parent) and what the rules say about it."""

    row: dict[str, Any]
    judgement: Judgement
    children: list[dict[str, Any]] = field(default_factory=list)


def judge_all(
    rows: list[dict[str, Any]],
    theme: ThemeCheck | None = None,
    fresh: Freshness | None = None,
) -> list[Judged]:
    """Judge a whole vault. RA children are folded into their parent's row.

    A child whose parent is missing from the rows (an import that has not reached it yet)
    stands alone as a one-child family.
    """
    parents: dict[tuple[Any, ...], dict[str, Any]] = {}
    children: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    out: list[Judged] = []
    for row in rows:
        sim_type = str(row.get("sim_type") or "REGULAR").upper()
        if sim_type == "RA_PARENT":
            parents[family_key(row)] = row
        elif sim_type == "RA_CHILD":
            children[family_key(row)].append(row)
        else:
            out.append(Judged(row, judge(row, theme, fresh)))
    families = [(parent, children.pop(key, [])) for key, parent in parents.items()]
    families.extend((f[0], f) for f in children.values())
    for parent, family in families:
        judgement = judge_family(parent, family)
        # A family is as fresh as the children it passes on.
        passing = [c for c in family if str(c.get("region")) in judgement.regions_passing]
        _age_out(judgement, passing or family, fresh)
        out.append(Judged(parent, judgement, family))
    return out


def summary(judged: list[Judged]) -> dict[str, dict[str, int]]:
    """Counts per tab and verdict. A current-theme Alpha also counts under Power Pool."""
    counts: dict[str, dict[str, int]] = {k.value: {v.value: 0 for v in Verdict} for k in Kind}
    for item in judged:
        kind, verdict = item.judgement.kind, item.judgement.verdict
        counts[kind.value][verdict.value] += 1
        if kind == Kind.THEME:
            counts[Kind.POWER_POOL.value][verdict.value] += 1
    return counts


def in_tab(item: Judged, tab: Kind) -> bool:
    """The Power Pool tab lists current-theme Alphas too; every other tab is exact."""
    kind = item.judgement.kind
    return kind == tab or (tab == Kind.POWER_POOL and kind == Kind.THEME)
