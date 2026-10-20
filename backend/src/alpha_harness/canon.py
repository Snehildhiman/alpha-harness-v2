"""One spelling per alpha: expressions normalised so equivalent ones hash the same.

Re-simulating an alpha BRAIN already scored spends a day's simulation for nothing. The exact
payload hash only catches byte-identical requests; written two ways, the same alpha is paid
for twice. :func:`canonical` rewrites an expression into one form, using only rewrites that
cannot change what BRAIN computes:

* layout: whitespace, redundant parentheses, ``;`` placement (via parse and render);
* numbers: ``20.0`` → ``20``, ``0.50`` → ``0.5``;
* ``add(a, b)`` written as ``a + b`` and ``multiply(a, b)`` as ``a * b`` (no keywords);
* commutative operands sorted: ``a + b`` / ``b + a``, ``a * b``, and positional arguments of
  ``max`` and ``min`` (chains are flattened first, so ``a + b + c``
  in any order is one form);
* idempotent wrappers collapsed: ``rank(rank(x))`` → ``rank(x)``, likewise ``abs``, ``sign``;
* double negation removed: ``-(-x)`` → ``x``;
* local variable names replaced by their order of assignment, so ``a = rank(x); a * 2`` and
  ``s = rank(x); s * 2`` match.

The canonical string is a hash key, never sent to BRAIN.
"""

from dataclasses import replace
from functools import reduce

from .labs.fastexpr import Node, ParseError, parse, render

#: Binary operators whose operands may be swapped.
_COMMUTATIVE_BINARY = frozenset({"+", "*"})
#: Calls whose positional arguments may be reordered. Keyword arguments (``filter=``) stay put.
_COMMUTATIVE_CALLS = frozenset({"add", "multiply", "max", "min"})
#: Calls that are the arithmetic operator by another name, when given no keywords.
_AS_BINARY = {"add": "+", "multiply": "*"}
#: f(f(x)) == f(x), given one positional argument and no keywords.
_IDEMPOTENT = frozenset({"rank", "abs", "sign"})


def _squash(text: str) -> str:
    return " ".join(text.split())


def _number(text: str) -> str:
    try:
        value = float(text)
    except ValueError:
        return text
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


def _flatten(node: Node, op: str) -> list[Node]:
    if node.kind == "binary" and node.value == op:
        return [part for arg in node.args for part in _flatten(arg, op)]
    return [node]


def _normalise(node: Node, names: dict[str, str]) -> Node:
    match node.kind:
        case "num":
            return replace(node, value=_number(node.value))
        case "name":
            return replace(node, value=names.get(node.value, node.value))
        case "str":
            return node
        case "assign":
            value = _normalise(node.args[0], names)
            names.setdefault(node.value, f"_v{len(names)}")
            return Node("assign", names[node.value], (value,))
        case "seq":
            return Node("seq", args=tuple(_normalise(s, names) for s in node.args))
        case _:
            pass

    if (
        node.kind == "call"
        and node.value.lower() in _AS_BINARY
        and len(node.args) >= 2
        and not (node.kwargs)
    ):
        # add(a, b) is a + b and multiply(a, b) is a * b: one spelling for both.
        op = _AS_BINARY[node.value.lower()]
        node = reduce(lambda left, right: Node("binary", op, (left, right)), node.args)

    if node.kind == "binary" and node.value in _COMMUTATIVE_BINARY:
        parts = sorted((_normalise(p, names) for p in _flatten(node, node.value)), key=render)
        return reduce(lambda left, right: Node("binary", node.value, (left, right)), parts)

    args = tuple(_normalise(a, names) for a in node.args)
    kwargs = tuple((k, _normalise(v, names)) for k, v in node.kwargs)

    if node.kind == "unary" and node.value == "-":
        inner = args[0]
        if inner.kind == "unary" and inner.value == "-":
            return inner.args[0]
    if node.kind == "call":
        name = node.value.lower()
        if name in _COMMUTATIVE_CALLS and not kwargs:
            args = tuple(sorted(args, key=render))
        if (
            name in _IDEMPOTENT
            and len(args) == 1
            and not kwargs
            and args[0].kind == "call"
            and args[0].value.lower() == name
            and len(args[0].args) == 1
            and not args[0].kwargs
        ):
            return args[0]
    return replace(node, args=args, kwargs=kwargs)


def canonical(expression: str | None) -> str | None:
    """The expression in its one canonical spelling; whitespace-collapsed text if unreadable."""
    if expression is None:
        return None
    try:
        tree = parse(expression)
    except ParseError, RecursionError:
        return _squash(expression)
    try:
        return render(_normalise(tree, {}))
    except RecursionError:
        return _squash(expression)
