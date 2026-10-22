"""Currency in region-agnostic Alphas: what the ARC webinar warns about, checked before sending.

One region-agnostic Alpha runs in Asia, Europe and Global, where companies report in many
currencies (dollars, yen, euros...). Ranking a raw amount (sales, a price, market cap) across
those stocks ranks the currencies as much as the companies. The webinar names two cures:
divide one amount by another (sales / assets: the currency cancels), or compare a stock with
its own history (ts_rank, ts_zscore, ts_scale: a change, not a level).

:func:`problem` says when an expression would rank an amount across stocks without either
cure. A field counts as an amount by its id and BRAIN's description of it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .fastexpr import Node, parse

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

#: Price-volume fields every market has, all in a local currency or share count.
AMOUNT_FIELDS = frozenset({"close", "open", "high", "low", "vwap", "cap", "adv20", "volume"})
_AMOUNT_WORDS = (
    "price",
    "sales",
    "revenue",
    "asset",
    "liabilit",
    "equity",
    "debt",
    "cash",
    "income",
    "earning",
    "eps",
    "ebit",
    "dividend",
    "book value",
    "market cap",
    "market value",
    "cost",
    "expense",
    "profit",
    "amount",
    "dollar",
    "currency",
    "turnover value",
)
#: Words that say a figure carries no unit even if it mentions an amount.
_FREE_WORDS = ("ratio", "percent", "%", "growth", "yield", "score", "rank", "margin", "return")

#: Operators whose output carries no unit, whatever goes in.
UNIT_FREE = frozenset(
    {
        "ts_rank",
        "ts_zscore",
        "ts_scale",
        "ts_quantile",
        "ts_corr",
        "ts_covariance",
        "ts_ir",
        "ts_arg_max",
        "ts_arg_min",
        "ts_count_nans",
        "sign",
        "rank",
        "zscore",
        "scale",
        "normalize",
        "quantile",
        "group_rank",
        "group_zscore",
        "group_scale",
        "group_normalize",
        "days_from_last_change",
    }
)
#: Operators that rank or score across stocks: an amount must not reach them raw.
CROSS_SECTIONAL = frozenset(
    {
        "rank",
        "zscore",
        "scale",
        "normalize",
        "quantile",
        "group_rank",
        "group_zscore",
        "group_scale",
        "group_normalize",
        "winsorize",
    }
)


def is_amount(field_id: str, description: str = "") -> bool:
    """Whether a field holds an amount in a local currency (or a share count)."""
    if field_id in AMOUNT_FIELDS:
        return True
    text = f"{field_id} {description}".lower()
    if any(w in text for w in _FREE_WORDS):
        return False
    return any(w in text for w in _AMOUNT_WORDS)


def amounts_in(fields: Iterable[Any]) -> Callable[[str], bool]:
    """``is_amount`` for a context's fields, read with BRAIN's descriptions of them."""
    described = {str(f.id): str(getattr(f, "description", "") or "") for f in fields}
    return lambda name: is_amount(name, described.get(name, ""))


def problem(expression: str, amount: Callable[[str], bool]) -> str | None:
    """Why ``expression`` would rank an amount across currencies, or ``None``."""
    try:
        tree = parse(expression)
    except Exception:  # noqa: BLE001 - unreadable expressions are refused elsewhere
        return None
    assigned: dict[str, bool] = {}
    found: list[str] = []

    def carries(node: Node) -> bool:
        if node.kind == "name":
            return assigned.get(node.value, amount(node.value))
        if node.kind in ("num", "str"):
            return False
        if node.kind == "unary":
            return carries(node.args[0]) if node.value == "-" else False
        if node.kind == "binary":
            left, right = carries(node.args[0]), carries(node.args[1])
            if node.value == "/":
                # An amount over an amount cancels the currency; over a plain number it stays.
                return left and not right
            if node.value in ("*", "+", "-"):
                return left or right
            return False  # comparisons and logic give 0 or 1
        if node.kind == "ternary":
            return carries(node.args[1]) or carries(node.args[2])
        if node.kind == "call":
            inside = [carries(a) for a in node.args]
            if node.value in CROSS_SECTIONAL and inside and inside[0]:
                found.append(node.value)
            if node.value in UNIT_FREE:
                return False
            if node.value == "divide" and len(inside) >= 2:
                return inside[0] and not inside[1]
            return bool(inside and inside[0])
        return False

    def visit(node: Node) -> bool:
        if node.kind == "seq":
            last = False
            for part in node.args:
                last = visit(part)
            return last
        if node.kind == "assign":
            assigned[node.value] = carries(node.args[0])
            return assigned[node.value]
        return carries(node)

    if visit(tree):
        return (
            "Its result is an amount in each stock's own currency, so stocks in different "
            "currencies are not comparable. Divide by another amount or compare with its own "
            "history (ts_rank, ts_zscore, ts_scale)."
        )
    if found:
        return (
            f"{found[0]} ranks an amount across stocks that report in different currencies. "
            "Divide it by another amount first, or compare it with its own history (ts_rank, "
            "ts_zscore, ts_scale)."
        )
    return None
