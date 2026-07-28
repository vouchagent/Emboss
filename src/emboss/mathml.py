"""Presentation MathML parsing into the shared math AST.

Parses the presentation MathML subset (mi/mn/mo, mrow, mfrac, msqrt/mroot,
msup/msub/msubsup, munder/mover/munderover, mtable/mtr/mtd, mfenced, mtext,
mspace, mstyle, semantics) into the same AST nodes the LaTeX parser in
math_render produces, so layout and rendering are shared. Uses only the
standard library.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from html.entities import html5

from .math_render import (
    GREEK_LETTERS,
    MATH_SYMBOLS,
    AlignedNode,
    DelimiterNode,
    FractionNode,
    GroupNode,
    MathNode,
    MatrixNode,
    SpaceNode,
    SqrtNode,
    SubscriptNode,
    SuperscriptNode,
    SuperSubNode,
    SymbolNode,
    TextNode,
)

__all__ = ["parse_mathml"]

_XML_ENTITIES = frozenset({"lt", "gt", "amp", "quot", "apos"})
_NAMED_ENTITY = re.compile(r"&([A-Za-z][A-Za-z0-9.]*);")

# Display char -> LaTeX-side symbol name (first definition wins, deterministic).
_NAME_BY_DISPLAY: dict[str, str] = {}
for _name, _display in [*GREEK_LETTERS.items(), *MATH_SYMBOLS.items()]:
    _NAME_BY_DISPLAY.setdefault(_display, _name)

_FENCE_PAIRS = {"(": ")", "[": "]", "{": "}", "|": "|"}

_TOKEN_TRANSLATE: dict[int, str | None] = {
    0x2061: None,  # function application
    0x2062: None,  # invisible times
    0x2063: None,  # invisible separator
    0x2064: None,  # invisible plus
    0x2212: "-",  # minus sign -> hyphen-minus
    0x00A0: " ",  # no-break space
}


def _expand_entities(source: str) -> str:
    """Expand named (HTML5/MathML) entities, leaving XML predefined ones."""

    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in _XML_ENTITIES:
            return match.group(0)
        expansion = html5.get(name + ";")
        return expansion if expansion is not None else match.group(0)

    return _NAMED_ENTITY.sub(repl, source)


def _strip_namespaces(root: ET.Element) -> None:
    """Drop XML namespace qualifiers from every element tag."""
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _token_text(el: ET.Element) -> str:
    """Normalized text content of a token element."""
    text = "".join(el.itertext()).translate(_TOKEN_TRANSLATE)
    return " ".join(text.split())


def _wrap(nodes: list) -> MathNode:
    """Collapse a node list into a single AST node."""
    if not nodes:
        return GroupNode()
    if len(nodes) == 1:
        return nodes[0]
    return GroupNode(children=nodes)


def _fenced(left: str, right: str, inner: list) -> MathNode:
    """Wrap content in stretchy delimiters, folding onto bare matrices."""
    node = _wrap(inner)
    if isinstance(node, MatrixNode) and not node.left_delim and not node.right_delim:
        node.left_delim = left
        node.right_delim = right
        return node
    return DelimiterNode(left=left, right=right, content=node)


def _sequence(el: ET.Element) -> MathNode:
    """Convert an element's children to one node, folding matched mo fences."""
    items = [(child, _convert(child)) for child in el]
    items = [(child, node) for child, node in items if node is not None]
    nodes = [node for _child, node in items]
    if len(items) >= 2:
        first_el, first = items[0]
        last_el, last = items[-1]
        if (
            first_el.tag == "mo"
            and last_el.tag == "mo"
            and isinstance(first, TextNode)
            and isinstance(last, TextNode)
            and _FENCE_PAIRS.get(first.text) == last.text
        ):
            return _fenced(first.text, last.text, nodes[1:-1])
    return _wrap(nodes)


def _required_children(el: ET.Element, tag: str, count: int) -> list:
    """Convert children, requiring at least count of them."""
    nodes = [
        node if node is not None else GroupNode()
        for node in (_convert(child) for child in el)
    ]
    if len(nodes) < count:
        raise ValueError(
            f"Invalid MathML: <{tag}> requires {count} children, got {len(nodes)}"
        )
    return nodes[:count]


def _mi(el: ET.Element) -> MathNode | None:
    """Identifier: single-char italic variable or upright operator name."""
    text = _token_text(el)
    if not text:
        return None
    name = _NAME_BY_DISPLAY.get(text)
    if name is not None:
        return SymbolNode(symbol=name, display=text)
    variant = el.get("mathvariant", "")
    italic = len(text) == 1 and text.isalpha()
    if "italic" in variant:
        italic = True
    elif variant:
        italic = False
    return TextNode(text, italic=italic, bold="bold" in variant)


def _mn(el: ET.Element) -> MathNode | None:
    """Number: upright text."""
    text = _token_text(el)
    if not text:
        return None
    return TextNode(text, italic=False)


def _mo(el: ET.Element) -> MathNode | None:
    """Operator: Symbol-font symbol when known, else upright text."""
    text = _token_text(el)
    if not text:
        return None
    name = _NAME_BY_DISPLAY.get(text)
    if name is not None:
        return SymbolNode(symbol=name, display=text)
    return TextNode(text, italic=False)


def _mtext(el: ET.Element) -> MathNode | None:
    """Literal text: upright."""
    text = _token_text(el)
    if not text:
        return None
    return TextNode(text, italic=False)


def _space_width_em(width: str) -> float:
    """Best-effort width attribute to ems (default: thin space)."""
    value = width.strip()
    for suffix, scale in (("em", 1.0), ("ex", 0.5), ("pt", 0.1), ("px", 0.1)):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    else:
        scale = 1.0
    try:
        return float(value) * scale
    except ValueError:
        return 0.17


def _mspace(el: ET.Element) -> MathNode:
    """Explicit spacing."""
    return SpaceNode(width_em=_space_width_em(el.get("width", "")))


def _mfrac(el: ET.Element) -> MathNode:
    """Fraction."""
    numerator, denominator = _required_children(el, "mfrac", 2)
    return FractionNode(numerator=numerator, denominator=denominator)


def _msqrt(el: ET.Element) -> MathNode:
    """Square root over an implied row."""
    return SqrtNode(radicand=_sequence(el))


def _mroot(el: ET.Element) -> MathNode:
    """N-th root with its index."""
    radicand, index = _required_children(el, "mroot", 2)
    return SqrtNode(radicand=radicand, index=index)


def _msup(el: ET.Element) -> MathNode:
    """Superscript."""
    base, superscript = _required_children(el, "msup", 2)
    return SuperscriptNode(base=base, exponent=superscript)


def _msub(el: ET.Element) -> MathNode:
    """Subscript."""
    base, subscript = _required_children(el, "msub", 2)
    return SubscriptNode(base=base, subscript=subscript)


def _msubsup(el: ET.Element) -> MathNode:
    """Combined sub- and superscript."""
    base, subscript, superscript = _required_children(el, "msubsup", 3)
    return SuperSubNode(base=base, superscript=superscript, subscript=subscript)


def _mover(el: ET.Element) -> MathNode:
    """Overscript placed above the base via the limits machinery."""
    base, overscript = _required_children(el, "mover", 2)
    return SuperscriptNode(base=base, exponent=overscript, limits=True)


def _munder(el: ET.Element) -> MathNode:
    """Underscript placed below the base via the limits machinery."""
    base, underscript = _required_children(el, "munder", 2)
    return SubscriptNode(base=base, subscript=underscript, limits=True)


def _munderover(el: ET.Element) -> MathNode:
    """Under- and overscript pair (e.g. sum limits)."""
    base, underscript, overscript = _required_children(el, "munderover", 3)
    return SuperSubNode(
        base=base, superscript=overscript, subscript=underscript, limits=True
    )


def _mfenced(el: ET.Element) -> MathNode:
    """Fenced content with open/close delimiters and separators."""
    children = [node for node in (_convert(child) for child in el) if node is not None]
    separators = el.get("separators", ",").replace(" ", "")
    if separators and len(children) > 1:
        joined = [children[0]]
        for index, child in enumerate(children[1:]):
            sep = separators[min(index, len(separators) - 1)]
            joined.append(TextNode(sep, italic=False))
            joined.append(child)
        children = joined
    return _fenced(el.get("open", "("), el.get("close", ")"), children)


def _mtable(el: ET.Element) -> MathNode:
    """Table: matrix grid, or aligned rows when columnalign is right/left."""
    rows: list = []
    for tr in el:
        if tr.tag in ("mtr", "mlabeledtr"):
            cells = [_sequence(td) for td in tr if td.tag == "mtd"]
        elif tr.tag == "mtd":
            cells = [_sequence(tr)]
        else:
            converted = _convert(tr)
            cells = [converted if converted is not None else GroupNode()]
        rows.append(cells or [GroupNode()])
    if not rows:
        rows = [[GroupNode()]]
    aligns = (el.get("columnalign") or "").split()
    if aligns[:2] == ["right", "left"]:
        return AlignedNode(rows=rows, col_align="rl")
    col_align = "l" if aligns and aligns[0] == "left" else "c"
    return MatrixNode(rows=rows, col_align=col_align)


def _semantics(el: ET.Element) -> MathNode | None:
    """Take the first presentation child; ignore annotations."""
    for child in el:
        if child.tag not in ("annotation", "annotation-xml"):
            return _convert(child)
    return None


_HANDLERS: dict[str, Callable[[ET.Element], MathNode | None]] = {
    "mi": _mi,
    "mn": _mn,
    "mo": _mo,
    "mtext": _mtext,
    "mspace": _mspace,
    "mrow": _sequence,
    "mstyle": _sequence,
    "mpadded": _sequence,
    "merror": _sequence,
    "mfrac": _mfrac,
    "msqrt": _msqrt,
    "mroot": _mroot,
    "msup": _msup,
    "msub": _msub,
    "msubsup": _msubsup,
    "mover": _mover,
    "munder": _munder,
    "munderover": _munderover,
    "mfenced": _mfenced,
    "mtable": _mtable,
    "semantics": _semantics,
}


def _convert(el: ET.Element) -> MathNode | None:
    """Convert one MathML element; unknown wrappers are transparent."""
    handler = _HANDLERS.get(el.tag)
    if handler is not None:
        return handler(el)
    return _sequence(el)


def parse_mathml(source: str) -> MathNode:
    """Parse a presentation MathML string into the shared math AST."""
    try:
        root = ET.fromstring(_expand_entities(source))
    except ET.ParseError as exc:
        raise ValueError(f"Invalid MathML: {exc}") from exc
    _strip_namespaces(root)
    if root.tag != "math":
        raise ValueError(
            f"Invalid MathML: root element is <{root.tag}>, expected <math>"
        )
    return _sequence(root)
