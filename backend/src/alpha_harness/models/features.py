"""What the models see of an Alpha, and what they learn to predict.

Everything is read from the vault row and the synced catalog, so it is known *before* a
simulation for any candidate expression, which is the point: the models are used to decide
what is worth simulating.

**Inputs** (one numeric row per Alpha):

* Settings: region, universe, neutralization, Power Pool or not, sim type (categorical);
  delay, decay, truncation.
* Structure: size, depth, operator count, data-field count, the numbers in the expression
  (lookbacks), how many times each common operator is called, and common parent-to-child
  operator pairs (``rank>ts_mean``), which is where structure lives.
* Data: which common datasets and data categories the fields come from, and how crowded the
  fields are (BRAIN's alpha and user counts per field), which is the strongest outside signal
  for prod correlation.
* Time: when it was simulated, so drift in the pool is learnable.

**Targets**: the prod, Power Pool and self-correlation *values* BRAIN reported (numbers, not
pass/fail, so a 0.86 failure teaches more than a 0.71 one), Sharpe, fitness and turnover, and
pass/fail for every check with enough examples of both.

The vocabularies (which operators, pairs, datasets) are fitted on the training rows and saved
with the model, so a prediction builds exactly the columns training did.
"""

import contextlib
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import numpy as np

from ..labs.fastexpr import GROUPING, Node, ParseError, children, data_fields, operator_count, parse
from ..vault.yields import checks_of

#: Settings read as categories.
CATEGORICAL = ("region", "universe", "neutralization", "sim_type")
#: Settings read as numbers.
NUMERIC = ("delay", "decay", "truncation")

#: A vocabulary entry must appear in this many training Alphas to earn a column.
MIN_COUNT = 20
#: Most columns per vocabulary, most common first.
MAX_OPERATORS, MAX_PAIRS, MAX_DATASETS = 120, 200, 120

#: Correlation checks whose reported value is a regression target.
CORRELATIONS = {
    "PROD_CORRELATION": "prod_corr",
    "POWER_POOL_CORRELATION": "power_pool_corr",
    "SELF_CORRELATION": "self_corr",
}
#: Results that count as passing a check.
PASSING = frozenset({"PASS", "WARNING"})
#: Checks that label rather than judge, never learned as pass/fail.
NOT_LEARNED = frozenset(
    {
        "MATCHES_COMPETITION",
        "MATCHES_PYRAMID",
        "MATCHES_THEMES",
        "POWER_POOL_DESCRIPTION_LENGTH",
        "POWER_POOL_DESCRIPTION_FORMAT",
        "REGULAR_SUBMISSION",
        "D0_SUBMISSION",
    }
)

_EPOCH = date(2015, 1, 1)


@dataclass(slots=True)
class FieldInfo:
    """What the catalog says about one data field."""

    dataset: str | None = None
    category: str | None = None
    alpha_count: int | None = None
    user_count: int | None = None


@dataclass(slots=True)
class Parsed:
    """One expression, read once."""

    ok: bool
    operators: Counter[str] = field(default_factory=Counter)
    pairs: Counter[str] = field(default_factory=Counter)
    fields: list[str] = field(default_factory=list)
    numbers: list[float] = field(default_factory=list)
    nodes: int = 0
    depth: int = 0
    operator_count: int = 0


def read_expression(expression: str | None) -> Parsed:
    if not expression:
        return Parsed(ok=False)
    try:
        tree = parse(expression)
    except ParseError, RecursionError:
        return Parsed(ok=False)
    out = Parsed(ok=True, fields=data_fields(tree))
    try:
        out.operator_count = operator_count(tree)
    except RecursionError:
        out.operator_count = 0

    def visit(node: Node, parent: str | None, depth: int) -> None:
        out.nodes += 1
        out.depth = max(out.depth, depth)
        name = None
        if node.kind == "call" or node.kind in ("binary", "unary"):
            name = node.value
        elif node.kind == "num":
            with contextlib.suppress(ValueError):
                out.numbers.append(float(node.value))
        if name is not None:
            out.operators[name] += 1
            if parent is not None:
                out.pairs[f"{parent}>{name}"] += 1
        for child in children(node):
            visit(child, name or parent, depth + 1)

    try:
        visit(tree, None, 0)
    except RecursionError:
        return Parsed(ok=False)
    return out


def date_of(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None
    return None


def _is_power_pool(checks: list[dict[str, Any]], row: dict[str, Any]) -> bool:
    if any(str(c.get("name", "")).upper() == "POWER_POOL_CORRELATION" for c in checks):
        return True
    return "power pool" in str(row.get("classifications") or "").lower()


def targets_of(row: dict[str, Any]) -> dict[str, float]:
    """Every target this Alpha has a label for. Pass/fail targets are ``check:NAME``."""
    out: dict[str, float] = {}
    for key in ("sharpe", "fitness", "turnover"):
        value = row.get(key)
        if isinstance(value, int | float) and math.isfinite(value):
            out[key] = float(value)
    if str(row.get("simulation_mode") or "").upper() == "QUICK":
        return out  # A Quick Alpha's checks omit everything that judges submission.
    for check in checks_of(row.get("checks")):
        name = str(check.get("name", "")).upper()
        result = str(check.get("result", "")).upper()
        value = check.get("value")
        if name in CORRELATIONS and isinstance(value, int | float) and math.isfinite(value):
            out[CORRELATIONS[name]] = float(value)
        if name in NOT_LEARNED or result in ("", "PENDING", "NONE"):
            continue
        if name in CORRELATIONS and result == "WARNING" and isinstance(value, int | float):
            # A WARNING correlation is decided by its numbers (see separation.py).
            limit = check.get("limit")
            if isinstance(limit, int | float):
                out[f"check:{name}"] = float(value <= limit)
            continue
        out[f"check:{name}"] = float(result in PASSING)
    return out


@dataclass(slots=True)
class Vocabulary:
    """Which columns exist: fitted on training rows, saved with every model."""

    categories: dict[str, list[str]] = field(default_factory=dict)
    operators: list[str] = field(default_factory=list)
    pairs: list[str] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)
    data_categories: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "categories": self.categories,
            "operators": self.operators,
            "pairs": self.pairs,
            "datasets": self.datasets,
            "data_categories": self.data_categories,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Vocabulary:
        return cls(
            categories={k: list(v) for k, v in (raw.get("categories") or {}).items()},
            operators=list(raw.get("operators") or []),
            pairs=list(raw.get("pairs") or []),
            datasets=list(raw.get("datasets") or []),
            data_categories=list(raw.get("data_categories") or []),
        )

    def columns(self) -> list[str]:
        return [
            *CATEGORICAL,
            *NUMERIC,
            "power_pool",
            "nodes",
            "depth",
            "operator_count",
            "field_count",
            "number_count",
            "number_min",
            "number_max",
            "number_median",
            "crowd_alpha_max",
            "crowd_alpha_mean",
            "crowd_user_max",
            "crowd_user_mean",
            "unknown_fields",
            "category_count",
            "days",
            *(f"op:{o}" for o in self.operators),
            *(f"pair:{p}" for p in self.pairs),
            *(f"dataset:{d}" for d in self.datasets),
            *(f"datacat:{c}" for c in self.data_categories),
        ]


def _top(counter: Counter[str], limit: int) -> list[str]:
    return [k for k, n in counter.most_common(limit) if n >= MIN_COUNT]


def fit_vocabulary(
    rows: list[dict[str, Any]], parsed: list[Parsed], fields: dict[str, FieldInfo]
) -> Vocabulary:
    """Columns from the training rows only, so a test row can never add one."""
    categories: dict[str, list[str]] = {}
    for key in CATEGORICAL:
        seen = Counter(str(r.get(key) or "") for r in rows)
        categories[key] = sorted(seen)
    operators: Counter[str] = Counter()
    pairs: Counter[str] = Counter()
    datasets: Counter[str] = Counter()
    data_categories: Counter[str] = Counter()
    for p in parsed:
        operators.update(set(p.operators))
        pairs.update(set(p.pairs))
        infos = [fields.get(f) for f in p.fields]
        datasets.update({i.dataset for i in infos if i and i.dataset})
        data_categories.update({i.category for i in infos if i and i.category})
    return Vocabulary(
        categories=categories,
        operators=_top(operators, MAX_OPERATORS),
        pairs=_top(pairs, MAX_PAIRS),
        datasets=_top(datasets, MAX_DATASETS),
        data_categories=_top(data_categories, 60),
    )


def _mean(values: list[float]) -> float:
    return float(sum(values) / len(values)) if values else math.nan


def matrix(
    rows: list[dict[str, Any]],
    parsed: list[Parsed],
    fields: dict[str, FieldInfo],
    vocab: Vocabulary,
) -> np.ndarray:
    """One float32 row per Alpha, columns as :meth:`Vocabulary.columns`. Missing is NaN;
    categories are integer codes (unknown: -1, which LightGBM reads as missing)."""
    columns = vocab.columns()
    index = {c: i for i, c in enumerate(columns)}
    out = np.full((len(rows), len(columns)), np.nan, dtype=np.float32)
    codes = {k: {v: i for i, v in enumerate(vs)} for k, vs in vocab.categories.items()}
    for r, (row, p) in enumerate(zip(rows, parsed, strict=True)):
        x = out[r]
        for key in CATEGORICAL:
            x[index[key]] = codes.get(key, {}).get(str(row.get(key) or ""), -1)
        for key in NUMERIC:
            value = row.get(key)
            if isinstance(value, int | float):
                x[index[key]] = float(value)
        checks = checks_of(row.get("checks")) if row.get("checks") else []
        x[index["power_pool"]] = float(bool(row.get("power_pool")) or _is_power_pool(checks, row))
        when = date_of(row.get("date_created"))
        if when is not None:
            x[index["days"]] = float((when - _EPOCH).days)
        if not p.ok:
            continue
        x[index["nodes"]] = p.nodes
        x[index["depth"]] = p.depth
        x[index["operator_count"]] = p.operator_count
        x[index["field_count"]] = len(p.fields)
        lookbacks = [n for n in p.numbers if math.isfinite(n)]
        x[index["number_count"]] = len(lookbacks)
        if lookbacks:
            x[index["number_min"]] = min(lookbacks)
            x[index["number_max"]] = max(lookbacks)
            x[index["number_median"]] = float(np.median(lookbacks))
        infos = [fields.get(f) for f in p.fields if f not in GROUPING]
        known = [i for i in infos if i is not None]
        x[index["unknown_fields"]] = len(infos) - len(known)
        alphas = [math.log1p(i.alpha_count) for i in known if i.alpha_count is not None]
        users = [math.log1p(i.user_count) for i in known if i.user_count is not None]
        if alphas:
            x[index["crowd_alpha_max"]] = max(alphas)
            x[index["crowd_alpha_mean"]] = _mean(alphas)
        if users:
            x[index["crowd_user_max"]] = max(users)
            x[index["crowd_user_mean"]] = _mean(users)
        cats = {i.category for i in known if i.category}
        x[index["category_count"]] = len(cats)
        for name, n in p.operators.items():
            if (i := index.get(f"op:{name}")) is not None:
                x[i] = n
        for name, n in p.pairs.items():
            if (i := index.get(f"pair:{name}")) is not None:
                x[i] = n
        for info in known:
            if info.dataset and (i := index.get(f"dataset:{info.dataset}")) is not None:
                x[i] = 1.0
            if info.category and (i := index.get(f"datacat:{info.category}")) is not None:
                x[i] = 1.0
    # Vocabulary columns that are absent mean "zero times", not "unknown".
    first_vocab = index["days"] + 1
    block = out[:, first_vocab:]
    block[np.isnan(block)] = 0.0
    return out


def categorical_columns(vocab: Vocabulary) -> list[int]:
    columns = vocab.columns()
    return [columns.index(k) for k in CATEGORICAL]


def today_days() -> float:
    return float((datetime.now(UTC).date() - _EPOCH).days)


def dumps(vocab: Vocabulary) -> str:
    return json.dumps(vocab.to_json())
