"""Mathematical notation rendering for PDF content streams.

Renders a LaTeX-like subset of math notation directly to PDF operators.
No external dependencies. Greek letters and math symbols use the PDF
Symbol font; regular text uses the document font.

Supported syntax:
  - Superscripts: x^{2}, e^{i\\pi}
  - Subscripts: a_{n}, x_{i,j}
  - Fractions: \\frac{a}{b}
  - Square roots: \\sqrt{x}
  - Greek letters: \\alpha, \\beta, \\gamma, ...
  - Operators: \\sum, \\prod, \\int, \\partial
  - Relations: \\leq, \\geq, \\neq, \\approx, \\equiv
  - Arrows: \\to, \\leftarrow, \\Rightarrow
  - Sets: \\in, \\notin, \\subset, \\cup, \\cap, \\emptyset
  - Misc: \\infty, \\pm, \\times, \\cdot, \\ldots, \\forall, \\exists
  - Delimiters: \\left( \\right), \\left[ \\right]
  - Text in math: \\text{word}
  - Spacing: \\quad, \\qquad, \\,
  - Accents: \\hat{x}, \\bar{x}, \\dot{x}, \\vec{x}
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "MathExpression", "parse_math", "render_math",
    "GREEK_LETTERS", "MATH_SYMBOLS",
]

GREEK_LETTERS: dict[str, str] = {
    "alpha": "α", "beta": "β", "gamma": "γ",
    "delta": "δ", "epsilon": "ε", "zeta": "ζ",
    "eta": "η", "theta": "θ", "iota": "ι",
    "kappa": "κ", "lambda": "λ", "mu": "μ",
    "nu": "ν", "xi": "ξ", "pi": "π",
    "rho": "ρ", "sigma": "σ", "tau": "τ",
    "upsilon": "υ", "phi": "φ", "chi": "χ",
    "psi": "ψ", "omega": "ω",
    "Alpha": "Α", "Beta": "Β", "Gamma": "Γ",
    "Delta": "Δ", "Epsilon": "Ε", "Zeta": "Ζ",
    "Eta": "Η", "Theta": "Θ", "Iota": "Ι",
    "Kappa": "Κ", "Lambda": "Λ", "Mu": "Μ",
    "Nu": "Ν", "Xi": "Ξ", "Pi": "Π",
    "Rho": "Ρ", "Sigma": "Σ", "Tau": "Τ",
    "Upsilon": "Υ", "Phi": "Φ", "Chi": "Χ",
    "Psi": "Ψ", "Omega": "Ω",
}

MATH_SYMBOLS: dict[str, str] = {
    "sum": "∑", "prod": "∏", "int": "∫",
    "partial": "∂", "nabla": "∇", "infty": "∞",
    "pm": "±", "mp": "∓", "times": "×",
    "div": "÷", "cdot": "·", "bullet": "•",
    "leq": "≤", "geq": "≥", "neq": "≠",
    "approx": "≈", "equiv": "≡", "sim": "∼",
    "propto": "∝",
    "to": "→", "leftarrow": "←", "rightarrow": "→",
    "Leftarrow": "⇐", "Rightarrow": "⇒",
    "leftrightarrow": "↔", "Leftrightarrow": "⇔",
    "uparrow": "↑", "downarrow": "↓",
    "in": "∈", "notin": "∉", "ni": "∋",
    "subset": "⊂", "supset": "⊃",
    "subseteq": "⊆", "supseteq": "⊇",
    "cup": "∪", "cap": "∩", "emptyset": "∅",
    "forall": "∀", "exists": "∃", "neg": "¬",
    "wedge": "∧", "vee": "∨",
    "ldots": "…", "cdots": "⋯", "vdots": "⋮",
    "prime": "′", "circ": "∘", "star": "⋆",
    "dagger": "†", "ddagger": "‡",
    "ell": "ℓ", "hbar": "ℏ", "Re": "ℜ", "Im": "ℑ",
    "aleph": "ℵ",
}

# Unicode codepoint -> Symbol font byte value
_UNICODE_TO_SYMBOL: dict[int, int] = {
    # Lowercase Greek
    0x03B1: 0x61, 0x03B2: 0x62, 0x03B3: 0x67, 0x03B4: 0x64,
    0x03B5: 0x65, 0x03B6: 0x7A, 0x03B7: 0x68, 0x03B8: 0x71,
    0x03B9: 0x69, 0x03BA: 0x6B, 0x03BB: 0x6C, 0x03BC: 0x6D,
    0x03BD: 0x6E, 0x03BE: 0x78, 0x03C0: 0x70, 0x03C1: 0x72,
    0x03C3: 0x73, 0x03C4: 0x74, 0x03C5: 0x75, 0x03C6: 0x66,
    0x03C7: 0x63, 0x03C8: 0x79, 0x03C9: 0x77,
    # Uppercase Greek
    0x0391: 0x41, 0x0392: 0x42, 0x0393: 0x47, 0x0394: 0x44,
    0x0395: 0x45, 0x0396: 0x5A, 0x0397: 0x48, 0x0398: 0x51,
    0x0399: 0x49, 0x039A: 0x4B, 0x039B: 0x4C, 0x039C: 0x4D,
    0x039D: 0x4E, 0x039E: 0x58, 0x03A0: 0x50, 0x03A1: 0x52,
    0x03A3: 0x53, 0x03A4: 0x54, 0x03A5: 0x55, 0x03A6: 0x46,
    0x03A7: 0x43, 0x03A8: 0x59, 0x03A9: 0x57,
    # Math operators and symbols
    0x2211: 0xE5,  # summation
    0x220F: 0xD5,  # product
    0x222B: 0xF2,  # integral
    0x2202: 0xB6,  # partial
    0x2207: 0xD1,  # nabla
    0x221E: 0xA5,  # infinity
    0x00B1: 0xB1,  # plus-minus
    0x00D7: 0xB4,  # times
    0x00F7: 0xB8,  # division
    0x00B7: 0xD7,  # middle dot
    0x2022: 0xB7,  # bullet
    0x2264: 0xA3,  # leq
    0x2265: 0xB3,  # geq
    0x2260: 0xB9,  # neq
    0x2248: 0xBB,  # approx
    0x2261: 0xBA,  # equiv
    0x223C: 0x7E,  # sim (tilde)
    0x221D: 0xB5,  # propto
    0x2192: 0xAE,  # rightarrow
    0x2190: 0xAC,  # leftarrow
    0x2191: 0xAD,  # uparrow
    0x2193: 0xAF,  # downarrow
    0x21D2: 0xDE,  # Rightarrow
    0x21D0: 0xDC,  # Leftarrow
    0x2194: 0xAB,  # leftrightarrow
    0x21D4: 0xDB,  # Leftrightarrow
    0x2208: 0xCE,  # element of
    0x2209: 0xCF,  # not element of
    0x220B: 0x27,  # contains
    0x2282: 0xCC,  # subset
    0x2283: 0xC9,  # superset
    0x2286: 0xCD,  # subset-eq
    0x2287: 0xCA,  # superset-eq
    0x222A: 0xC8,  # union
    0x2229: 0xC7,  # intersection
    0x2205: 0xC6,  # empty set
    0x2200: 0x22,  # forall
    0x2203: 0x24,  # exists
    0x00AC: 0xD8,  # not
    0x2227: 0xD9,  # logical and
    0x2228: 0xDA,  # logical or
    0x2026: 0xBC,  # ellipsis
    0x2032: 0xA2,  # prime
    0x2020: 0x86,  # dagger (use WinAnsi for this)
    0x2021: 0x87,  # double dagger
    0x2135: 0xC0,  # aleph
    0x221A: 0xD6,  # radical/sqrt
}


def _needs_symbol(text: str) -> bool:
    """Check if text contains characters that require the Symbol font."""
    for ch in text:
        if ord(ch) in _UNICODE_TO_SYMBOL and ord(ch) > 0xFF:
            return True
    return False


def _symbol_encode(text: str) -> bytes:
    """Encode text for the PDF Symbol font."""
    out = bytearray(b"(")
    for ch in text:
        code = ord(ch)
        sym_byte = _UNICODE_TO_SYMBOL.get(code)
        if sym_byte is not None:
            if sym_byte in (0x28, 0x29, 0x5C):  # ()\ need escaping
                out.append(0x5C)
            out.append(sym_byte)
        elif code < 128:
            if ch in "()\\":
                out.append(0x5C)
            out.append(code)
        else:
            out.append(0x3F)
    out.append(0x29)
    return bytes(out)


@dataclass
class MathNode:
    """Base AST node for math expressions."""
    pass


@dataclass
class TextNode(MathNode):
    text: str
    italic: bool = True


@dataclass
class SymbolNode(MathNode):
    symbol: str
    display: str


@dataclass
class SuperscriptNode(MathNode):
    base: MathNode
    exponent: MathNode


@dataclass
class SubscriptNode(MathNode):
    base: MathNode
    subscript: MathNode


@dataclass
class SuperSubNode(MathNode):
    base: MathNode
    superscript: MathNode
    subscript: MathNode


@dataclass
class FractionNode(MathNode):
    numerator: MathNode
    denominator: MathNode


@dataclass
class SqrtNode(MathNode):
    radicand: MathNode


@dataclass
class GroupNode(MathNode):
    children: list = field(default_factory=list)


@dataclass
class SpaceNode(MathNode):
    width_em: float


@dataclass
class AccentNode(MathNode):
    base: MathNode
    accent_type: str


@dataclass
class DelimiterNode(MathNode):
    left: str
    right: str
    content: MathNode


class MathParser:
    """Parse LaTeX-subset math into an AST."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.pos = 0

    def parse(self) -> MathNode:
        children = self._parse_sequence()
        if len(children) == 1:
            return children[0]
        return GroupNode(children=children)

    def _parse_sequence(self, stop_at: str = "") -> list:
        nodes = []
        while self.pos < len(self.source):
            ch = self.source[self.pos]
            if ch in stop_at:
                break
            if ch == '{':
                self.pos += 1
                inner = self._parse_sequence(stop_at="}")
                if self.pos < len(self.source) and self.source[self.pos] == '}':
                    self.pos += 1
                node = GroupNode(children=inner) if len(inner) != 1 else inner[0]
                nodes.append(node)
            elif ch == '^':
                self.pos += 1
                base = nodes.pop() if nodes else TextNode("")
                exp = self._parse_atom()
                if self.pos < len(self.source) and self.source[self.pos] == '_':
                    self.pos += 1
                    sub = self._parse_atom()
                    nodes.append(SuperSubNode(base=base, superscript=exp, subscript=sub))
                else:
                    nodes.append(SuperscriptNode(base=base, exponent=exp))
            elif ch == '_':
                self.pos += 1
                base = nodes.pop() if nodes else TextNode("")
                sub = self._parse_atom()
                if self.pos < len(self.source) and self.source[self.pos] == '^':
                    self.pos += 1
                    exp = self._parse_atom()
                    nodes.append(SuperSubNode(base=base, superscript=exp, subscript=sub))
                else:
                    nodes.append(SubscriptNode(base=base, subscript=sub))
            elif ch == '\\':
                nodes.append(self._parse_command())
            elif ch == ' ':
                self.pos += 1
                nodes.append(SpaceNode(width_em=0.15))
            else:
                start = self.pos
                while (self.pos < len(self.source)
                       and self.source[self.pos] not in stop_at
                       and self.source[self.pos] not in '{^_\\ '):
                    self.pos += 1
                nodes.append(TextNode(self.source[start:self.pos]))
        return nodes

    def _parse_atom(self) -> MathNode:
        if self.pos >= len(self.source):
            return TextNode("")
        ch = self.source[self.pos]
        if ch == '{':
            self.pos += 1
            inner = self._parse_sequence(stop_at="}")
            if self.pos < len(self.source) and self.source[self.pos] == '}':
                self.pos += 1
            return GroupNode(children=inner) if len(inner) != 1 else inner[0]
        elif ch == '\\':
            return self._parse_command()
        else:
            self.pos += 1
            return TextNode(ch)

    def _parse_command(self) -> MathNode:
        self.pos += 1  # skip backslash
        if self.pos >= len(self.source):
            return TextNode("\\")

        start = self.pos
        while self.pos < len(self.source) and self.source[self.pos].isalpha():
            self.pos += 1
        name = self.source[start:self.pos]

        if not name:
            ch = self.source[self.pos] if self.pos < len(self.source) else ""
            self.pos += 1
            if ch == ',':
                return SpaceNode(width_em=0.17)
            elif ch == ';':
                return SpaceNode(width_em=0.28)
            elif ch == '!':
                return SpaceNode(width_em=-0.17)
            elif ch == ' ':
                return SpaceNode(width_em=0.25)
            return TextNode(ch)

        if name == "frac":
            num = self._parse_atom()
            den = self._parse_atom()
            return FractionNode(numerator=num, denominator=den)
        elif name == "sqrt":
            radicand = self._parse_atom()
            return SqrtNode(radicand=radicand)
        elif name in ("hat", "bar", "dot", "vec", "tilde"):
            base = self._parse_atom()
            return AccentNode(base=base, accent_type=name)
        elif name == "text":
            content = self._parse_atom()
            if isinstance(content, TextNode):
                content.italic = False
            elif isinstance(content, GroupNode):
                for child in content.children:
                    if isinstance(child, TextNode):
                        child.italic = False
            return content
        elif name == "left":
            delim = self.source[self.pos] if self.pos < len(self.source) else "("
            self.pos += 1
            inner = self._parse_sequence(stop_at="\\")
            right_delim = ")"
            if self.pos < len(self.source) and self.source[self.pos] == '\\':
                self.pos += 1
                rstart = self.pos
                while self.pos < len(self.source) and self.source[self.pos].isalpha():
                    self.pos += 1
                rname = self.source[rstart:self.pos]
                if rname == "right" and self.pos < len(self.source):
                    right_delim = self.source[self.pos]
                    self.pos += 1
            content = GroupNode(children=inner) if len(inner) != 1 else inner[0]
            return DelimiterNode(left=delim, right=right_delim, content=content)
        elif name == "quad":
            return SpaceNode(width_em=1.0)
        elif name == "qquad":
            return SpaceNode(width_em=2.0)
        elif name == "lim":
            return TextNode("lim", italic=False)
        elif name == "sin":
            return TextNode("sin", italic=False)
        elif name == "cos":
            return TextNode("cos", italic=False)
        elif name == "tan":
            return TextNode("tan", italic=False)
        elif name == "log":
            return TextNode("log", italic=False)
        elif name == "ln":
            return TextNode("ln", italic=False)
        elif name == "exp":
            return TextNode("exp", italic=False)
        elif name == "det":
            return TextNode("det", italic=False)
        elif name == "max":
            return TextNode("max", italic=False)
        elif name == "min":
            return TextNode("min", italic=False)
        elif name in GREEK_LETTERS:
            return SymbolNode(symbol=name, display=GREEK_LETTERS[name])
        elif name in MATH_SYMBOLS:
            return SymbolNode(symbol=name, display=MATH_SYMBOLS[name])
        else:
            return TextNode(name, italic=False)


def parse_math(source: str) -> MathNode:
    """Parse a LaTeX math string into an AST."""
    return MathParser(source).parse()


@dataclass
class MathBox:
    """A positioned piece of the math layout."""
    text: str
    x: float
    y: float
    size: float
    italic: bool = False
    bold: bool = False
    symbol: bool = False


@dataclass
class MathLine:
    """A line drawn as part of math (fraction bar, sqrt)."""
    x: float
    y: float
    width: float
    thickness: float


@dataclass
class MathLayout:
    """Complete layout of a math expression."""
    boxes: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    width: float = 0.0
    height: float = 0.0
    depth: float = 0.0


class MathLayoutEngine:
    """Lay out math AST nodes into positioned boxes."""

    def __init__(self, base_size: float = 10.5, char_width: float = 0.55):
        self.base_size = base_size
        self.char_width = char_width

    def layout(self, node: MathNode, size: float | None = None) -> MathLayout:
        size = size or self.base_size
        return self._layout_node(node, 0.0, 0.0, size)

    def _layout_node(self, node: MathNode, x: float, y: float,
                     size: float) -> MathLayout:
        if isinstance(node, TextNode):
            return self._layout_text(node, x, y, size)
        elif isinstance(node, SymbolNode):
            return self._layout_symbol(node, x, y, size)
        elif isinstance(node, GroupNode):
            return self._layout_group(node, x, y, size)
        elif isinstance(node, SuperscriptNode):
            return self._layout_superscript(node, x, y, size)
        elif isinstance(node, SubscriptNode):
            return self._layout_subscript(node, x, y, size)
        elif isinstance(node, SuperSubNode):
            return self._layout_supersub(node, x, y, size)
        elif isinstance(node, FractionNode):
            return self._layout_fraction(node, x, y, size)
        elif isinstance(node, SqrtNode):
            return self._layout_sqrt(node, x, y, size)
        elif isinstance(node, SpaceNode):
            w = node.width_em * size
            return MathLayout(width=w, height=size, depth=0)
        elif isinstance(node, AccentNode):
            return self._layout_accent(node, x, y, size)
        elif isinstance(node, DelimiterNode):
            return self._layout_delimiter(node, x, y, size)
        return MathLayout()

    def _char_w(self, size: float) -> float:
        return size * self.char_width

    def _layout_text(self, node: TextNode, x: float, y: float,
                     size: float) -> MathLayout:
        w = len(node.text) * self._char_w(size)
        box = MathBox(text=node.text, x=x, y=y, size=size,
                      italic=node.italic, symbol=False)
        return MathLayout(boxes=[box], width=w, height=size, depth=0)

    def _layout_symbol(self, node: SymbolNode, x: float, y: float,
                       size: float) -> MathLayout:
        w = self._char_w(size)
        box = MathBox(text=node.display, x=x, y=y, size=size,
                      italic=False, symbol=True)
        return MathLayout(boxes=[box], width=w, height=size, depth=0)

    def _layout_group(self, node: GroupNode, x: float, y: float,
                      size: float) -> MathLayout:
        layout = MathLayout(height=size, depth=0)
        cursor = x
        for child in node.children:
            child_layout = self._layout_node(child, cursor, y, size)
            layout.boxes.extend(child_layout.boxes)
            layout.lines.extend(child_layout.lines)
            cursor += child_layout.width
            layout.height = max(layout.height, child_layout.height)
            layout.depth = max(layout.depth, child_layout.depth)
        layout.width = cursor - x
        return layout

    def _layout_superscript(self, node: SuperscriptNode, x: float,
                            y: float, size: float) -> MathLayout:
        base = self._layout_node(node.base, x, y, size)
        sup_size = size * 0.7
        sup_y = y + size * 0.45
        sup = self._layout_node(node.exponent, x + base.width, sup_y, sup_size)

        layout = MathLayout()
        layout.boxes = base.boxes + sup.boxes
        layout.lines = base.lines + sup.lines
        layout.width = base.width + sup.width
        layout.height = max(base.height, sup_y + sup.height - y)
        layout.depth = base.depth
        return layout

    def _layout_subscript(self, node: SubscriptNode, x: float,
                          y: float, size: float) -> MathLayout:
        base = self._layout_node(node.base, x, y, size)
        sub_size = size * 0.7
        sub_y = y - size * 0.25
        sub = self._layout_node(node.subscript, x + base.width, sub_y, sub_size)

        layout = MathLayout()
        layout.boxes = base.boxes + sub.boxes
        layout.lines = base.lines + sub.lines
        layout.width = base.width + sub.width
        layout.height = base.height
        layout.depth = max(base.depth, -(sub_y - y) + sub_size * 0.3)
        return layout

    def _layout_supersub(self, node: SuperSubNode, x: float,
                         y: float, size: float) -> MathLayout:
        base = self._layout_node(node.base, x, y, size)
        script_size = size * 0.7
        sup_y = y + size * 0.45
        sub_y = y - size * 0.25
        sup = self._layout_node(node.superscript, x + base.width, sup_y, script_size)
        sub = self._layout_node(node.subscript, x + base.width, sub_y, script_size)
        script_w = max(sup.width, sub.width)

        layout = MathLayout()
        layout.boxes = base.boxes + sup.boxes + sub.boxes
        layout.lines = base.lines + sup.lines + sub.lines
        layout.width = base.width + script_w
        layout.height = max(base.height, sup_y + sup.height - y)
        layout.depth = max(base.depth, -(sub_y - y) + script_size * 0.3)
        return layout

    def _layout_fraction(self, node: FractionNode, x: float,
                         y: float, size: float) -> MathLayout:
        frac_size = size * 0.85
        num = self._layout_node(node.numerator, 0, 0, frac_size)
        den = self._layout_node(node.denominator, 0, 0, frac_size)

        total_w = max(num.width, den.width) + size * 0.3
        bar_y = y + size * 0.25
        bar_thickness = size * 0.04

        num_x = x + (total_w - num.width) / 2
        num_y = bar_y + size * 0.15
        den_x = x + (total_w - den.width) / 2
        den_y = bar_y - frac_size - size * 0.1

        num_shifted = self._layout_node(node.numerator, num_x, num_y, frac_size)
        den_shifted = self._layout_node(node.denominator, den_x, den_y, frac_size)

        layout = MathLayout()
        layout.boxes = num_shifted.boxes + den_shifted.boxes
        layout.lines = num_shifted.lines + den_shifted.lines
        layout.lines.append(MathLine(
            x=x, y=bar_y, width=total_w, thickness=bar_thickness
        ))
        layout.width = total_w
        layout.height = (num_y + frac_size) - y
        layout.depth = y - den_y + frac_size * 0.3
        return layout

    def _layout_sqrt(self, node: SqrtNode, x: float, y: float,
                     size: float) -> MathLayout:
        inner = self._layout_node(node.radicand, 0, 0, size)
        hook_w = size * 0.5
        pad = size * 0.15

        inner_shifted = self._layout_node(
            node.radicand, x + hook_w, y, size
        )

        layout = MathLayout()
        layout.boxes = inner_shifted.boxes
        layout.lines = inner_shifted.lines

        bar_y = y + inner.height + pad * 0.5
        layout.lines.append(MathLine(
            x=x + hook_w - 1, y=bar_y,
            width=inner.width + 2,
            thickness=size * 0.04,
        ))

        # Radical sign from Symbol font
        radical = MathBox(text="√", x=x, y=y - size * 0.1,
                          size=size * 1.1, italic=False, symbol=True)
        layout.boxes.append(radical)

        layout.width = hook_w + inner.width
        layout.height = inner.height + pad
        layout.depth = inner.depth
        return layout

    def _layout_accent(self, node: AccentNode, x: float, y: float,
                       size: float) -> MathLayout:
        base = self._layout_node(node.base, x, y, size)
        accent_map = {
            "hat": ("^", False),
            "bar": ("¯", False),
            "dot": (".", False),
            "vec": ("→", True),
            "tilde": ("~", False),
        }
        accent_text, is_symbol = accent_map.get(node.accent_type, ("^", False))
        accent_y = y + base.height + size * 0.05
        accent_x = x + (base.width - self._char_w(size * 0.8)) / 2

        layout = MathLayout()
        layout.boxes = base.boxes + [
            MathBox(text=accent_text, x=accent_x, y=accent_y,
                    size=size * 0.7, italic=False, symbol=is_symbol)
        ]
        layout.lines = base.lines
        layout.width = base.width
        layout.height = base.height + size * 0.3
        layout.depth = base.depth
        return layout

    def _layout_delimiter(self, node: DelimiterNode, x: float,
                          y: float, size: float) -> MathLayout:
        inner = self._layout_node(node.content, 0, 0, size)
        delim_w = self._char_w(size)
        delim_size = max(size, inner.height + inner.depth) * 1.1

        left_box = MathBox(text=node.left, x=x, y=y, size=delim_size,
                           italic=False)
        right_box = MathBox(text=node.right,
                            x=x + delim_w + inner.width,
                            y=y, size=delim_size, italic=False)

        inner_shifted = self._layout_node(
            node.content, x + delim_w, y, size
        )

        layout = MathLayout()
        layout.boxes = [left_box] + inner_shifted.boxes + [right_box]
        layout.lines = inner_shifted.lines
        layout.width = delim_w * 2 + inner.width
        layout.height = max(inner.height, delim_size)
        layout.depth = max(inner.depth, delim_size * 0.2)
        return layout


@dataclass
class MathExpression:
    """A mathematical expression to render in a document."""
    source: str
    display: bool = False
    style: object | None = None

    @property
    def structure_tag(self) -> str:
        return "Formula"


def render_math(stream, math_expr: MathExpression, x: float, y: float,
                font_key: str, size: float, color: str = "000000",
                italic_key: str | None = None,
                symbol_key: str | None = None) -> float:
    """Render a math expression into a content stream.

    Returns the total width of the rendered expression.
    """
    node = parse_math(math_expr.source)
    engine = MathLayoutEngine(base_size=size)
    layout = engine.layout(node)

    for box in layout.boxes:
        if box.symbol and symbol_key:
            encoded = _symbol_encode(box.text)
            stream.raw(b"BT")
            stream.set_fill(color)
            stream.raw(f"/{symbol_key} ".encode("ascii")
                       + stream._num(box.size) + b" Tf")
            stream.raw(b" ".join([
                stream._num(x + box.x),
                stream._num(y + box.y), b"Td"
            ]))
            stream.raw(encoded + b" Tj")
            stream.raw(b"ET")
        else:
            key = italic_key if (italic_key and box.italic) else font_key
            stream.text_line(
                box.text, key, box.size,
                x + box.x, y + box.y, color,
            )

    for line in layout.lines:
        stream.line(
            x + line.x, y + line.y,
            x + line.x + line.width, y + line.y,
            color=color, width=line.thickness,
        )

    return layout.width
