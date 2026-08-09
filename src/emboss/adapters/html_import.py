"""Import a supported HTML/CSS subset into an EmbossSpec Document.

This is a migration path for HTML->PDF pipelines (WeasyPrint, headless
Chrome), not a browser engine. It compiles a bounded, report-template
subset of HTML/CSS into `Document` blocks so existing templates gain
Emboss's deterministic, PDF/UA-tagged output without a rewrite.

Supported:
  - Tags: html/head/body, h1-h6, p, div/section/article, ul/ol/li,
    table/thead/tbody/tr/th/td (colspan), img, a, strong/b/em/i/code/u/
    s/strike/del/br/hr/span, blockquote.
  - CSS: inline `style=`, `<style>` blocks with tag/class/id selectors
    and descendant combinators (`div.card p`), comma-separated selector
    lists, and CSS custom properties (`--x: ...` / `var(--x, fallback)`).
    Properties: color, text-align, font-family/size/weight/style,
    text-decoration, margin (shorthand + longhand), page-break-before,
    and on flex-row containers: display, flex-direction, gap, flex/
    flex-grow (drives `Columns` widths).
  - Units: px, pt, em, rem, %, and CSS hex/rgb()/rgba()/named colors.

Explicitly out of scope (no stub/partial rendering -- these are either
ignored or raise a clear error rather than silently misrendering):
  child/sibling/attribute/pseudo-class selectors beyond `:root`,
  `!important`, background/border on generic containers (no generic
  styled-container block exists in the spec model; use a real
  Callout in the source Document for that), flexbox wrapping/alignment
  beyond a single non-wrapping row, CSS Grid, positioning, and remote
  image URLs (fetch is not attempted; inline as a `data:` URI instead).
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field, replace
from html.parser import HTMLParser

from ..spec import (
    BlockQuote,
    BulletList,
    Columns,
    Document,
    Heading,
    HorizontalRule,
    Image,
    NumberedList,
    Paragraph,
    Table,
    TableCell,
    TextRun,
)
from ..styles import Style

__all__ = ["import_html"]

_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "source", "track", "wbr",
}
_SKIP_TAGS = {"script", "style", "head", "meta", "link", "title", "noscript", "template"}
_HEADING_TAGS = {f"h{n}" for n in range(1, 7)}


# -- HTML tree --


@dataclass
class _Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)  # str | _Node


class _TreeBuilder(HTMLParser):
    """Builds a lightweight DOM tree, tolerant of unbalanced end tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node(tag="html")
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list) -> None:
        node = _Node(tag=tag, attrs=dict(attrs))
        self._stack[-1].children.append(node)
        if tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        self._stack[-1].children.append(_Node(tag=tag, attrs=dict(attrs)))

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].children.append(data)


def _flatten_text(node: _Node) -> str:
    parts = []
    for child in node.children:
        parts.append(child if isinstance(child, str) else _flatten_text(child))
    return "".join(parts)


def _find_first(node: _Node, tag: str) -> _Node | None:
    for child in node.children:
        if isinstance(child, str):
            continue
        if child.tag == tag:
            return child
        found = _find_first(child, tag)
        if found is not None:
            return found
    return None


def _collect_style_text(node: _Node) -> list[str]:
    out = []
    for child in node.children:
        if isinstance(child, str):
            continue
        if child.tag == "style":
            out.append(_flatten_text(child))
        else:
            out.extend(_collect_style_text(child))
    return out


# -- CSS parsing --


@dataclass
class _SimpleSelector:
    tag: str | None
    classes: frozenset
    id: str | None


@dataclass
class _Rule:
    selectors: list  # list[list[_SimpleSelector]] (compound descendant chains)
    declarations: dict
    order: int


_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_SIMPLE_SELECTOR_RE = re.compile(r"^([a-zA-Z][\w-]*)?((?:[.#][-\w]+)*)$")
_CLASS_ID_RE = re.compile(r"[.#][-\w]+")


def _parse_declarations(body: str) -> dict:
    decls: dict = {}
    for stmt in body.split(";"):
        if ":" not in stmt:
            continue
        prop, _, value = stmt.partition(":")
        prop = prop.strip().lower()
        value = value.strip()
        if prop and value:
            decls[prop] = value
    return decls


def _parse_simple_selector(token: str) -> _SimpleSelector | None:
    token = token.strip()
    if not token:
        return None
    if token == ":root":
        return _SimpleSelector(tag="html", classes=frozenset(), id=None)
    if token == "*":
        return _SimpleSelector(tag=None, classes=frozenset(), id=None)
    match = _SIMPLE_SELECTOR_RE.match(token)
    if not match:
        return None
    tag = match.group(1)
    classes = set()
    ident = None
    for piece in _CLASS_ID_RE.findall(match.group(2) or ""):
        if piece[0] == ".":
            classes.add(piece[1:])
        else:
            ident = piece[1:]
    return _SimpleSelector(tag=tag, classes=frozenset(classes), id=ident)


def _parse_selector_chain(text: str) -> list | None:
    if any(c in text for c in ">+~[:") and not text.strip().startswith(":root"):
        return None
    if text.strip() == ":root":
        sel = _parse_simple_selector(":root")
        return [sel] if sel else None
    chain = []
    for part in text.split():
        sel = _parse_simple_selector(part)
        if sel is None:
            return None
        chain.append(sel)
    return chain or None


def _parse_css(css_text: str) -> list[_Rule]:
    css_text = _COMMENT_RE.sub("", css_text)
    rules: list[_Rule] = []
    order = 0
    pos = 0
    while True:
        brace = css_text.find("{", pos)
        if brace == -1:
            break
        end = css_text.find("}", brace)
        if end == -1:
            break
        selector_text = css_text[pos:brace].strip()
        declarations = _parse_declarations(css_text[brace + 1 : end])
        pos = end + 1
        if not selector_text or not declarations:
            continue
        chains = []
        for sel_text in selector_text.split(","):
            chain = _parse_selector_chain(sel_text.strip())
            if chain:
                chains.append(chain)
        if chains:
            rules.append(_Rule(selectors=chains, declarations=declarations, order=order))
            order += 1
    return rules


def _simple_matches(node: _Node, sel: _SimpleSelector) -> bool:
    if sel.tag is not None and node.tag != sel.tag:
        return False
    if sel.id is not None and node.attrs.get("id") != sel.id:
        return False
    if sel.classes:
        node_classes = set((node.attrs.get("class") or "").split())
        if not sel.classes.issubset(node_classes):
            return False
    return True


def _chain_matches(ancestors: list, chain: list) -> bool:
    idx = len(ancestors) - 1
    for sel in reversed(chain):
        matched = False
        while idx >= 0:
            if _simple_matches(ancestors[idx], sel):
                matched = True
                idx -= 1
                break
            idx -= 1
        if not matched:
            return False
    return True


def _chain_specificity(chain: list) -> tuple:
    ids = sum(1 for s in chain if s.id)
    classes = sum(len(s.classes) for s in chain)
    tags = sum(1 for s in chain if s.tag)
    return (ids, classes, tags)


def _resolve_declarations(ancestors: list, rules: list) -> dict:
    matched = []
    for rule in rules:
        best = None
        for chain in rule.selectors:
            if _chain_matches(ancestors, chain):
                spec = _chain_specificity(chain)
                if best is None or spec > best:
                    best = spec
        if best is not None:
            matched.append((best, rule.order, rule.declarations))
    matched.sort(key=lambda t: (t[0], t[1]))
    result: dict = {}
    for _, _, decls in matched:
        result.update(decls)
    node = ancestors[-1]
    inline = node.attrs.get("style")
    if inline:
        result.update(_parse_declarations(inline))
    return result


_VAR_RE = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^()]*(?:\([^()]*\)[^()]*)*))?\)")


def _substitute_vars(value: str, custom: dict, depth: int = 0) -> str:
    if depth > 4 or "var(" not in value:
        return value

    def repl(m: re.Match) -> str:
        name, fallback = m.group(1), m.group(2)
        if name in custom:
            return custom[name]
        return fallback if fallback is not None else ""

    substituted = _VAR_RE.sub(repl, value)
    if substituted != value:
        return _substitute_vars(substituted, custom, depth + 1)
    return substituted


def _resolve_node(ancestors: list, rules: list, parent_custom: dict) -> tuple:
    """Resolve one node's cascade: (regular properties, inherited + own custom props)."""
    raw = _resolve_declarations(ancestors, rules)
    own_custom = {k: v for k, v in raw.items() if k.startswith("--")}
    custom = {**parent_custom, **own_custom}
    props = {
        k: _substitute_vars(v, custom) for k, v in raw.items() if not k.startswith("--")
    }
    return props, custom


# -- CSS value parsing --

_LENGTH_RE = re.compile(r"^(-?[\d.]+)\s*(px|pt|em|rem|%)?$")

_CSS_NAMED_COLORS = {
    "black": "000000", "white": "ffffff", "red": "ff0000", "green": "008000",
    "blue": "0000ff", "yellow": "ffff00", "orange": "ffa500", "purple": "800080",
    "gray": "808080", "grey": "808080", "silver": "c0c0c0", "maroon": "800000",
    "navy": "000080", "teal": "008080", "olive": "808000", "lime": "00ff00",
    "aqua": "00ffff", "cyan": "00ffff", "magenta": "ff00ff", "fuchsia": "ff00ff",
    "pink": "ffc0cb", "brown": "a52a2a", "gold": "ffd700", "indigo": "4b0082",
    "violet": "ee82ee", "coral": "ff7f50", "salmon": "fa8072", "khaki": "f0e68c",
    "crimson": "dc143c", "chocolate": "d2691e", "darkgray": "a9a9a9",
    "darkgrey": "a9a9a9", "lightgray": "d3d3d3", "lightgrey": "d3d3d3",
    "steelblue": "4682b4", "skyblue": "87ceeb", "tomato": "ff6347",
    "orchid": "da70d6", "slategray": "708090", "slategrey": "708090",
    "dimgray": "696969", "dimgrey": "696969", "cornflowerblue": "6495ed",
    "royalblue": "4169e1", "seagreen": "2e8b57", "forestgreen": "228b22",
    "firebrick": "b22222", "beige": "f5f5dc", "ivory": "fffff0",
    "lavender": "e6e6fa", "plum": "dda0dd", "turquoise": "40e0d0",
    "darkblue": "00008b", "darkgreen": "006400", "darkred": "8b0000",
}


def _css_color(value: str) -> str | None:
    value = value.strip()
    if not value or value.lower() in ("transparent", "inherit", "initial", "unset", "currentcolor"):
        return None
    if value.startswith("#"):
        h = value[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) == 6 and re.match(r"^[0-9a-fA-F]{6}$", h):
            return h.lower()
        return None
    if value.startswith("rgb"):
        nums = re.findall(r"[\d.]+%?", value)
        if len(nums) < 3:
            return None
        channels = []
        for n in nums[:3]:
            num = float(n[:-1]) * 255.0 / 100.0 if n.endswith("%") else float(n)
            channels.append(min(255, max(0, int(round(num)))))
        return "".join(f"{c:02x}" for c in channels)
    return _CSS_NAMED_COLORS.get(value.lower())


def _css_length(
    value: str, base_size: float, parent_size: float, percent_base: float | None = None
) -> float | None:
    match = _LENGTH_RE.match(value.strip())
    if not match:
        return None
    num = float(match.group(1))
    unit = match.group(2) or "px"
    if unit == "px":
        return num * 0.75
    if unit == "pt":
        return num
    if unit == "em":
        return num * parent_size
    if unit == "rem":
        return num * base_size
    if unit == "%":
        return None if percent_base is None else num / 100.0 * percent_base
    return None


def _css_bold(value: str) -> bool | None:
    v = value.strip().lower()
    if v in ("bold", "bolder"):
        return True
    if v in ("normal", "lighter"):
        return False
    if v.isdigit():
        return int(v) >= 600
    return None


def _css_font_family(value: str) -> str | None:
    for token in value.split(","):
        fam = token.strip().strip("'\"").lower()
        if not fam:
            continue
        if fam in ("monospace", "courier", "courier new", "consolas", "menlo", "monaco"):
            return "Courier"
        if fam in ("serif", "times", "times new roman", "georgia", "garamond"):
            return "Times"
        if fam in ("sans-serif", "arial", "helvetica", "verdana", "calibri", "tahoma", "segoe ui"):
            return "Helvetica"
    return None


def _resolve_margins(props: dict, base_size: float, font_size: float) -> dict:
    result: dict = {"top": None, "right": None, "bottom": None, "left": None}
    if "margin" in props:
        parts = props["margin"].split()
        vals = [_css_length(p, base_size, font_size) for p in parts]
        if all(v is not None for v in vals):
            if len(vals) == 1:
                result["top"] = result["right"] = result["bottom"] = result["left"] = vals[0]
            elif len(vals) == 2:
                result["top"] = result["bottom"] = vals[0]
                result["right"] = result["left"] = vals[1]
            elif len(vals) == 3:
                result["top"], result["right"], result["bottom"] = vals
                result["left"] = vals[1]
            elif len(vals) == 4:
                result["top"], result["right"], result["bottom"], result["left"] = vals
    for side in ("top", "right", "bottom", "left"):
        key = f"margin-{side}"
        if key in props:
            v = _css_length(props[key], base_size, font_size)
            if v is not None:
                result[side] = v
    return result


def _style_from_props(props: dict, base_size: float, parent_size: float) -> tuple:
    """Resolve one node's Style overrides and its own (possibly new) font size."""
    kwargs: dict = {}
    font_size = parent_size
    if "font-size" in props:
        v = _css_length(props["font-size"], base_size, parent_size, percent_base=parent_size)
        if v and v > 0:
            font_size = v
            kwargs["font_size"] = v
    if "color" in props:
        c = _css_color(props["color"])
        if c:
            kwargs["color"] = c
    if "text-align" in props:
        v = props["text-align"].strip().lower()
        if v in ("left", "right", "center", "justify"):
            kwargs["align"] = v
    if "font-weight" in props:
        b = _css_bold(props["font-weight"])
        if b is not None:
            kwargs["bold"] = b
    if "font-style" in props:
        kwargs["italic"] = props["font-style"].strip().lower() in ("italic", "oblique")
    if "font-family" in props:
        fam = _css_font_family(props["font-family"])
        if fam:
            kwargs["font_family"] = fam
    margins = _resolve_margins(props, base_size, font_size)
    if margins["top"] is not None:
        kwargs["space_before"] = margins["top"]
    if margins["bottom"] is not None:
        kwargs["space_after"] = margins["bottom"]
    if margins["left"] is not None:
        kwargs["indent_left"] = margins["left"]
    if margins["right"] is not None:
        kwargs["indent_right"] = margins["right"]
    if props.get("page-break-before", "").strip().lower() in ("always", "page"):
        kwargs["page_break_before"] = True
    style = Style(**kwargs) if kwargs else None
    return style, font_size


def _is_flex_row(props: dict) -> bool:
    if props.get("display", "").strip().lower() != "flex":
        return False
    direction = props.get("flex-direction", "row").strip().lower()
    return direction in ("row", "row-reverse", "")


def _flex_weight(props: dict) -> float:
    if "flex" in props:
        try:
            return max(0.01, float(props["flex"].split()[0]))
        except (ValueError, IndexError):
            pass
    if "flex-grow" in props:
        try:
            return max(0.01, float(props["flex-grow"]))
        except ValueError:
            pass
    return 1.0


# -- inline runs --


@dataclass
class _RunState:
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False
    color: str | None = None
    font_family: str | None = None
    font_size: float | None = None
    link: str | None = None


def _apply_inline_props(state: _RunState, tag: str, props: dict, node: _Node) -> _RunState:
    new_state = replace(state)
    if tag in ("strong", "b"):
        new_state.bold = True
    if tag in ("em", "i"):
        new_state.italic = True
    if tag == "u":
        new_state.underline = True
    if tag in ("s", "strike", "del"):
        new_state.strikethrough = True
    if tag == "code":
        new_state.font_family = "Courier"
    if tag == "a":
        href = node.attrs.get("href")
        if href:
            new_state.link = href
    if "color" in props:
        c = _css_color(props["color"])
        if c:
            new_state.color = c
    if "font-weight" in props:
        b = _css_bold(props["font-weight"])
        if b is not None:
            new_state.bold = b
    if "font-style" in props:
        new_state.italic = props["font-style"].strip().lower() in ("italic", "oblique")
    if "font-family" in props:
        fam = _css_font_family(props["font-family"])
        if fam:
            new_state.font_family = fam
    if "text-decoration" in props:
        v = props["text-decoration"].lower()
        if "underline" in v:
            new_state.underline = True
        if "line-through" in v:
            new_state.strikethrough = True
    return new_state


#: Sentinel marking a `<br>` in a flattened run stream, at any nesting
#: depth (e.g. inside a `<span>`), so callers that care about line breaks
#: can split on it and callers that don't can filter it out. Never
#: constructed from user data, so identity comparison is safe.
_BR = object()


def _convert_inline(
    item, ancestors: list, rules: list, custom: dict, state: _RunState,
    base_size: float, parent_size: float, out: list,
) -> None:
    if isinstance(item, str):
        if item:
            out.append(
                TextRun(
                    item,
                    bold=state.bold,
                    italic=state.italic,
                    underline=state.underline,
                    strikethrough=state.strikethrough,
                    color=state.color,
                    font_family=state.font_family,
                    font_size=state.font_size,
                    link=state.link,
                )
            )
        return
    node = item
    if node.tag == "br":
        out.append(_BR)
        return
    if node.tag in _SKIP_TAGS:
        return
    node_ancestors = ancestors + [node]
    props, child_custom = _resolve_node(node_ancestors, rules, custom)
    new_state = _apply_inline_props(state, node.tag, props, node)
    for child in node.children:
        _convert_inline(
            child, node_ancestors, rules, child_custom, new_state, base_size, parent_size, out
        )


def _split_runs_on_br(items: list) -> list:
    """Split a flattened run stream (which may hold `_BR` sentinels) into groups."""
    groups: list = [[]]
    for item in items:
        if item is _BR:
            groups.append([])
        else:
            groups[-1].append(item)
    return groups


def _strip_br(items: list) -> list:
    """Drop `_BR` sentinels for callers with nowhere to put a line break."""
    return [item for item in items if item is not _BR]


def _runs_from(
    items: list, ancestors: list, rules: list, custom: dict, base_size: float, parent_size: float
) -> list:
    """Flatten inline content to TextRuns, preserving `_BR` sentinels for `<br>`."""
    runs: list = []
    state = _RunState()
    for item in items:
        _convert_inline(item, ancestors, rules, custom, state, base_size, parent_size, runs)
    return runs


# -- block conversion --


def _convert_paragraph(
    node: _Node, ancestors: list, rules: list, custom: dict,
    base_size: float, parent_size: float, style: Style | None,
) -> list:
    flat = _runs_from(node.children, ancestors, rules, custom, base_size, parent_size)
    blocks: list = []
    for group in _split_runs_on_br(flat):
        if any(r.text.strip() for r in group):
            blocks.append(Paragraph(content=group, style=style))
    return blocks


def _convert_list(
    node: _Node, ancestors: list, rules: list, custom: dict,
    base_size: float, parent_size: float, ordered: bool,
):
    items: list = []
    for child in node.children:
        if isinstance(child, str) or child.tag != "li":
            continue
        li_ancestors = ancestors + [child]
        _li_props, li_custom = _resolve_node(li_ancestors, rules, custom)
        nested = [
            c for c in child.children if not isinstance(c, str) and c.tag in ("ul", "ol")
        ]
        inline_children = [
            c for c in child.children
            if isinstance(c, str) or c.tag not in ("ul", "ol")
        ]
        runs = _strip_br(
            _runs_from(inline_children, li_ancestors, rules, li_custom, base_size, parent_size)
        )
        if runs:
            items.append(runs)
        for sub in nested:
            sub_ancestors = li_ancestors + [sub]
            _sub_props, sub_custom = _resolve_node(sub_ancestors, rules, li_custom)
            items.append(
                _convert_list(
                    sub, sub_ancestors, rules, sub_custom, base_size, parent_size,
                    ordered=sub.tag == "ol",
                )
            )
        if not runs and not nested:
            items.append([TextRun("")])
    cls = NumberedList if ordered else BulletList
    return cls(items=items)


def _table_cell(
    node: _Node, ancestors: list, rules: list, custom: dict,
    base_size: float, parent_size: float, bold: bool,
) -> TableCell:
    runs = _strip_br(_runs_from(node.children, ancestors, rules, custom, base_size, parent_size))
    props, _ = _resolve_node(ancestors, rules, custom)
    align = None
    if "text-align" in props and props["text-align"].strip().lower() in ("left", "right", "center"):
        align = props["text-align"].strip().lower()
    try:
        colspan = max(1, int(node.attrs.get("colspan", "1")))
    except ValueError:
        colspan = 1
    return TableCell(content=runs, align=align, bold=bold, colspan=colspan)


def _convert_table(
    node: _Node, ancestors: list, rules: list, custom: dict, base_size: float, parent_size: float
) -> Table | None:
    headers: list = []
    rows: list = []

    def walk_trs(tr_nodes: list, tr_container_ancestors: list, container_custom: dict, header: bool) -> None:
        for tr in tr_nodes:
            tr_ancestors = tr_container_ancestors + [tr]
            _tr_props, tr_custom = _resolve_node(tr_ancestors, rules, container_custom)
            row = []
            for cell in tr.children:
                if isinstance(cell, str) or cell.tag not in ("td", "th"):
                    continue
                cell_ancestors = tr_ancestors + [cell]
                row.append(
                    _table_cell(
                        cell, cell_ancestors, rules, tr_custom, base_size, parent_size,
                        bold=header or cell.tag == "th",
                    )
                )
            if not row:
                continue
            if header and not headers:
                headers.extend(row)
            else:
                rows.append(row)

    def direct_trs(container: _Node) -> list:
        return [c for c in container.children if not isinstance(c, str) and c.tag == "tr"]

    for child in node.children:
        if isinstance(child, str):
            continue
        if child.tag == "thead":
            child_ancestors = ancestors + [child]
            _p, child_custom = _resolve_node(child_ancestors, rules, custom)
            walk_trs(direct_trs(child), child_ancestors, child_custom, header=True)
        elif child.tag == "tbody":
            child_ancestors = ancestors + [child]
            _p, child_custom = _resolve_node(child_ancestors, rules, custom)
            walk_trs(direct_trs(child), child_ancestors, child_custom, header=False)
        elif child.tag == "tr":
            is_header_row = not headers and not rows and any(
                not isinstance(c, str) and c.tag == "th" for c in child.children
            )
            walk_trs([child], ancestors, custom, header=is_header_row)

    return Table(headers=headers, rows=rows) if (headers or rows) else None


def _convert_image(node: _Node, props: dict, base_size: float, parent_size: float) -> Image | None:
    src = node.attrs.get("src", "")
    if not src:
        return None
    source: str | bytes
    if src.startswith("data:"):
        header, _, b64data = src.partition(",")
        if ";base64" not in header:
            raise ValueError(f"unsupported data URI encoding for image: {header}")
        source = base64.b64decode(b64data)
    elif src.startswith(("http://", "https://")):
        raise ValueError(
            f"HTML import does not fetch remote images ({src}); inline as a "
            "data: URI or reference a local file path"
        )
    else:
        source = src

    width = _html_px_attr(node.attrs.get("width"))
    height = _html_px_attr(node.attrs.get("height"))
    if "width" in props:
        w = _css_length(props["width"], base_size, parent_size)
        if w:
            width = w
    if "height" in props:
        h = _css_length(props["height"], base_size, parent_size)
        if h:
            height = h
    return Image(source=source, alt_text=node.attrs.get("alt", ""), width=width, height=height)


def _html_px_attr(value) -> float | None:
    if not value:
        return None
    try:
        return float(value) * 0.75
    except ValueError:
        return None


def _convert_children(
    node: _Node, ancestors: list, rules: list, custom: dict, base_size: float, parent_size: float
) -> list:
    blocks: list = []
    for child in node.children:
        blocks.extend(_convert_block(child, ancestors, rules, custom, base_size, parent_size))
    return blocks


def _convert_flex_row(
    node: _Node, ancestors: list, rules: list, custom: dict,
    base_size: float, parent_size: float, props: dict, style: Style | None,
) -> list | None:
    candidates = [c for c in node.children if not isinstance(c, str) and c.tag not in _SKIP_TAGS]
    if len(candidates) < 2:
        return None
    gap = _css_length(props.get("gap", "0px"), base_size, parent_size) or 0.0
    weights: list = []
    col_blocks: list = []
    for col_node in candidates:
        col_ancestors = ancestors + [col_node]
        col_props, col_custom = _resolve_node(col_ancestors, rules, custom)
        weights.append(_flex_weight(col_props))
        col_blocks.append(
            _convert_children(col_node, col_ancestors, rules, col_custom, base_size, parent_size)
        )
    paired = [(w, cb) for w, cb in zip(weights, col_blocks) if cb]
    if len(paired) < 2:
        return None
    final_weights = [w for w, _ in paired]
    final_columns = [cb for _, cb in paired]
    use_widths = final_weights if any(abs(w - 1.0) > 1e-9 for w in final_weights) else None
    return [
        Columns(
            columns=final_columns,
            widths=use_widths,
            gap=gap if gap > 0 else 18.0,
            style=style,
        )
    ]


def _convert_block(
    item, ancestors: list, rules: list, custom: dict, base_size: float, parent_size: float
) -> list:
    if isinstance(item, str):
        if item.strip():
            return [Paragraph(item.strip())]
        return []

    node = item
    tag = node.tag
    if tag in _SKIP_TAGS:
        return []

    node_ancestors = ancestors + [node]
    props, node_custom = _resolve_node(node_ancestors, rules, custom)
    style, font_size = _style_from_props(props, base_size, parent_size)

    if tag in _HEADING_TAGS:
        text = _flatten_text(node).strip()
        return [Heading(text, level=int(tag[1]), style=style)] if text else []

    if tag == "p":
        return _convert_paragraph(node, node_ancestors, rules, node_custom, base_size, font_size, style)

    if tag in ("ul", "ol"):
        lst = _convert_list(
            node, node_ancestors, rules, node_custom, base_size, font_size, ordered=tag == "ol"
        )
        if style is not None:
            lst.style = style
        return [lst] if lst.items else []

    if tag == "table":
        table = _convert_table(node, node_ancestors, rules, node_custom, base_size, font_size)
        if table is not None and style is not None:
            table.style = style
        return [table] if table is not None else []

    if tag == "img":
        img = _convert_image(node, props, base_size, font_size)
        return [img] if img is not None else []

    if tag == "hr":
        return [HorizontalRule()]

    if tag == "blockquote":
        runs = _strip_br(
            _runs_from(node.children, node_ancestors, rules, node_custom, base_size, font_size)
        )
        return [BlockQuote(content=runs, style=style)] if runs else []

    if tag in ("div", "section", "article"):
        if _is_flex_row(props):
            row = _convert_flex_row(
                node, node_ancestors, rules, node_custom, base_size, font_size, props, style
            )
            if row is not None:
                return row
        return _convert_children(node, node_ancestors, rules, node_custom, base_size, font_size)

    # Unknown/unsupported tag: recurse rather than silently drop content.
    return _convert_children(node, node_ancestors, rules, node_custom, base_size, font_size)


# -- entry point --


def import_html(
    source: str,
    *,
    base_font_size: float = 12.0,
    title: str | None = None,
    language: str | None = None,
) -> Document:
    """Compile a supported HTML/CSS subset into a Document.

    `source` may be a full page or a bare fragment. `<style>` blocks and
    inline `style=` attributes are cascaded (tag/class/id specificity,
    descendant combinators, CSS custom properties); everything else in
    the module docstring's "out of scope" list is ignored or raises.
    """
    parser = _TreeBuilder()
    parser.feed(source)
    parser.close()
    root = parser.root
    # If the source declared its own <html>...</html>, adopt it as the root
    # instead of doubly-wrapping, so `lang` and `:root`/`html` selectors see
    # the real attributes rather than the synthetic parse-tree wrapper.
    element_children = [c for c in root.children if not isinstance(c, str)]
    if len(element_children) == 1 and element_children[0].tag == "html":
        root = element_children[0]

    rules = _parse_css("\n".join(_collect_style_text(root)))

    title_node = _find_first(root, "title")
    doc_title = title or (_flatten_text(title_node).strip() if title_node else "") or "Untitled"
    doc_lang = language or root.attrs.get("lang") or "en-US"

    body = _find_first(root, "body") or root
    ancestors = [root] if body is root else [root, body]

    props, custom = _resolve_node(ancestors, rules, {})
    _style, font_size = _style_from_props(props, base_font_size, base_font_size)

    doc = Document(title=doc_title, language=doc_lang)
    for block in _convert_children(body, ancestors, rules, custom, base_font_size, font_size):
        doc.add(block)
    return doc
