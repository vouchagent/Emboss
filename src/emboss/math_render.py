"""Mathematical notation rendering for PDF content streams.

Renders a LaTeX-like subset of math notation directly to PDF operators.
No external dependencies. Greek letters and math symbols use the PDF
Symbol font; regular text uses Times (italic for variables, roman for
digits, operators and function names), with widths measured from the
real base-14 AFM tables and inter-atom spacing following the TeX
spacing classes (thin/medium/thick).

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
  - Environments: \\begin{pmatrix|bmatrix|vmatrix|Bmatrix|matrix}
    with & column separators and \\\\ row breaks; \\begin{cases};
    \\begin{aligned}/align/align*/split; \\begin{gathered}/gather/gather*
  - Display-mode limits: \\sum_{i=1}^{n} places limits above/below
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .typography.font_metrics import FontMetrics

__all__ = [
    "MathExpression",
    "parse_math",
    "render_math",
    "GREEK_LETTERS",
    "MATH_SYMBOLS",
    "MathLayoutEngine",
    "MathLayout",
    "MathBox",
    "MathLine",
    "MatrixNode",
    "AlignedNode",
]

GREEK_LETTERS: dict[str, str] = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "zeta": "ζ",
    "eta": "η",
    "theta": "θ",
    "iota": "ι",
    "kappa": "κ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "tau": "τ",
    "upsilon": "υ",
    "phi": "φ",
    "chi": "χ",
    "psi": "ψ",
    "omega": "ω",
    "Alpha": "Α",
    "Beta": "Β",
    "Gamma": "Γ",
    "Delta": "Δ",
    "Epsilon": "Ε",
    "Zeta": "Ζ",
    "Eta": "Η",
    "Theta": "Θ",
    "Iota": "Ι",
    "Kappa": "Κ",
    "Lambda": "Λ",
    "Mu": "Μ",
    "Nu": "Ν",
    "Xi": "Ξ",
    "Pi": "Π",
    "Rho": "Ρ",
    "Sigma": "Σ",
    "Tau": "Τ",
    "Upsilon": "Υ",
    "Phi": "Φ",
    "Chi": "Χ",
    "Psi": "Ψ",
    "Omega": "Ω",
}

MATH_SYMBOLS: dict[str, str] = {
    "sum": "∑",
    "prod": "∏",
    "int": "∫",
    "partial": "∂",
    "nabla": "∇",
    "infty": "∞",
    "pm": "±",
    "mp": "∓",
    "times": "×",
    "div": "÷",
    "cdot": "·",
    "bullet": "•",
    "leq": "≤",
    "geq": "≥",
    "neq": "≠",
    "approx": "≈",
    "equiv": "≡",
    "sim": "∼",
    "propto": "∝",
    "to": "→",
    "leftarrow": "←",
    "rightarrow": "→",
    "Leftarrow": "⇐",
    "Rightarrow": "⇒",
    "leftrightarrow": "↔",
    "Leftrightarrow": "⇔",
    "uparrow": "↑",
    "downarrow": "↓",
    "in": "∈",
    "notin": "∉",
    "ni": "∋",
    "subset": "⊂",
    "supset": "⊃",
    "subseteq": "⊆",
    "supseteq": "⊇",
    "cup": "∪",
    "cap": "∩",
    "emptyset": "∅",
    "forall": "∀",
    "exists": "∃",
    "neg": "¬",
    "wedge": "∧",
    "vee": "∨",
    "ldots": "…",
    "cdots": "⋯",
    "vdots": "⋮",
    "prime": "′",
    "circ": "∘",
    "star": "⋆",
    "dagger": "†",
    "ddagger": "‡",
    "ell": "ℓ",
    "hbar": "ℏ",
    "Re": "ℜ",
    "Im": "ℑ",
    "aleph": "ℵ",
}

# Unicode codepoint -> Symbol font byte value
_UNICODE_TO_SYMBOL: dict[int, int] = {
    # Lowercase Greek
    0x03B1: 0x61,
    0x03B2: 0x62,
    0x03B3: 0x67,
    0x03B4: 0x64,
    0x03B5: 0x65,
    0x03B6: 0x7A,
    0x03B7: 0x68,
    0x03B8: 0x71,
    0x03B9: 0x69,
    0x03BA: 0x6B,
    0x03BB: 0x6C,
    0x03BC: 0x6D,
    0x03BD: 0x6E,
    0x03BE: 0x78,
    0x03C0: 0x70,
    0x03C1: 0x72,
    0x03C3: 0x73,
    0x03C4: 0x74,
    0x03C5: 0x75,
    0x03C6: 0x66,
    0x03C7: 0x63,
    0x03C8: 0x79,
    0x03C9: 0x77,
    # Uppercase Greek
    0x0391: 0x41,
    0x0392: 0x42,
    0x0393: 0x47,
    0x0394: 0x44,
    0x0395: 0x45,
    0x0396: 0x5A,
    0x0397: 0x48,
    0x0398: 0x51,
    0x0399: 0x49,
    0x039A: 0x4B,
    0x039B: 0x4C,
    0x039C: 0x4D,
    0x039D: 0x4E,
    0x039E: 0x58,
    0x03A0: 0x50,
    0x03A1: 0x52,
    0x03A3: 0x53,
    0x03A4: 0x54,
    0x03A5: 0x55,
    0x03A6: 0x46,
    0x03A7: 0x43,
    0x03A8: 0x59,
    0x03A9: 0x57,
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
    bold: bool = False


@dataclass
class SymbolNode(MathNode):
    symbol: str
    display: str


@dataclass
class SuperscriptNode(MathNode):
    base: MathNode
    exponent: MathNode
    limits: bool = False


@dataclass
class SubscriptNode(MathNode):
    base: MathNode
    subscript: MathNode
    limits: bool = False


@dataclass
class SuperSubNode(MathNode):
    base: MathNode
    superscript: MathNode
    subscript: MathNode
    limits: bool = False


@dataclass
class FractionNode(MathNode):
    numerator: MathNode
    denominator: MathNode


@dataclass
class SqrtNode(MathNode):
    radicand: MathNode
    index: MathNode | None = None


@dataclass
class GroupNode(MathNode):
    children: list = field(default_factory=list)


@dataclass
class SpaceNode(MathNode):
    width_em: float
    soft: bool = False


@dataclass
class AccentNode(MathNode):
    base: MathNode
    accent_type: str


@dataclass
class DelimiterNode(MathNode):
    left: str
    right: str
    content: MathNode


@dataclass
class MatrixNode(MathNode):
    rows: list = field(default_factory=list)
    left_delim: str = ""
    right_delim: str = ""
    col_align: str = "c"


@dataclass
class AlignedNode(MathNode):
    rows: list = field(default_factory=list)
    col_align: str = "rl"


# environment name -> (left delimiter, right delimiter)
_MATRIX_ENVS: dict[str, tuple[str, str]] = {
    "matrix": ("", ""),
    "pmatrix": ("(", ")"),
    "bmatrix": ("[", "]"),
    "vmatrix": ("|", "|"),
    "Bmatrix": ("{", "}"),
}
_ALIGNED_ENVS = frozenset({"aligned", "align", "align*", "split"})
_GATHERED_ENVS = frozenset({"gathered", "gather", "gather*"})


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

    def _parse_sequence(self, stop_at: str = "", env_mode: bool = False) -> list:
        nodes = []
        while self.pos < len(self.source):
            ch = self.source[self.pos]
            if ch in stop_at:
                break
            if env_mode and ch == "\\":
                if self.source.startswith("\\\\", self.pos) or self.source.startswith(
                    "\\end", self.pos
                ):
                    break
            if ch == "{":
                self.pos += 1
                inner = self._parse_sequence(stop_at="}")
                if self.pos < len(self.source) and self.source[self.pos] == "}":
                    self.pos += 1
                node = GroupNode(children=inner) if len(inner) != 1 else inner[0]
                nodes.append(node)
            elif ch == "^":
                self.pos += 1
                base = nodes.pop() if nodes else TextNode("")
                base = self._split_last_char(nodes, base)
                exp = self._parse_atom()
                if self.pos < len(self.source) and self.source[self.pos] == "_":
                    self.pos += 1
                    sub = self._parse_atom()
                    nodes.append(
                        SuperSubNode(base=base, superscript=exp, subscript=sub)
                    )
                else:
                    nodes.append(SuperscriptNode(base=base, exponent=exp))
            elif ch == "_":
                self.pos += 1
                base = nodes.pop() if nodes else TextNode("")
                base = self._split_last_char(nodes, base)
                sub = self._parse_atom()
                if self.pos < len(self.source) and self.source[self.pos] == "^":
                    self.pos += 1
                    exp = self._parse_atom()
                    nodes.append(
                        SuperSubNode(base=base, superscript=exp, subscript=sub)
                    )
                else:
                    nodes.append(SubscriptNode(base=base, subscript=sub))
            elif ch == "\\":
                nodes.append(self._parse_command())
            elif ch.isspace():
                self.pos += 1
                nodes.append(SpaceNode(width_em=0.15, soft=True))
            elif ch == "&":
                # Stray column separator outside an environment.
                self.pos += 1
                nodes.append(TextNode("&", italic=False))
            else:
                start = self.pos
                while (
                    self.pos < len(self.source)
                    and self.source[self.pos] not in stop_at
                    and self.source[self.pos] not in "{^_\\&"
                    and not self.source[self.pos].isspace()
                ):
                    self.pos += 1
                nodes.append(TextNode(self.source[start : self.pos]))
        return nodes

    @staticmethod
    def _split_last_char(nodes: list, base: MathNode) -> MathNode:
        """Split a multi-char TextNode so only the last char is the base.

        Only splits italic (math-variable) text like "mc" into "m" + "c".
        Non-italic text from \\text{} is a word and should not be split.
        """
        if isinstance(base, TextNode) and len(base.text) > 1 and base.italic:
            nodes.append(TextNode(base.text[:-1], italic=base.italic))
            return TextNode(base.text[-1], italic=base.italic)
        return base

    def _parse_atom(self) -> MathNode:
        if self.pos >= len(self.source):
            return TextNode("")
        ch = self.source[self.pos]
        if ch == "{":
            self.pos += 1
            inner = self._parse_sequence(stop_at="}")
            if self.pos < len(self.source) and self.source[self.pos] == "}":
                self.pos += 1
            return GroupNode(children=inner) if len(inner) != 1 else inner[0]
        elif ch == "\\":
            return self._parse_command()
        else:
            self.pos += 1
            return TextNode(ch)

    @staticmethod
    def _flatten_to_text(node: MathNode) -> str:
        """Reconstruct plain text from a parsed node tree."""
        if isinstance(node, TextNode):
            return node.text
        if isinstance(node, SpaceNode):
            return " "
        if isinstance(node, SymbolNode):
            return node.display
        if isinstance(node, GroupNode):
            return "".join(MathParser._flatten_to_text(c) for c in node.children)
        return ""

    def _read_brace_name(self) -> str:
        """Read a {name} group, returning the bare name."""
        if self.pos >= len(self.source) or self.source[self.pos] != "{":
            return ""
        self.pos += 1
        start = self.pos
        while self.pos < len(self.source) and self.source[self.pos] != "}":
            self.pos += 1
        name = self.source[start : self.pos]
        if self.pos < len(self.source):
            self.pos += 1
        return name

    @staticmethod
    def _as_cell(nodes: list) -> MathNode:
        """Wrap a parsed cell sequence into a single node."""
        if len(nodes) == 1:
            return nodes[0]
        return GroupNode(children=nodes)

    @staticmethod
    def _is_empty_cell(node: MathNode) -> bool:
        """True when a cell contains no visible content."""
        if isinstance(node, TextNode):
            return not node.text
        if isinstance(node, GroupNode):
            return all(
                MathParser._is_empty_cell(c) or isinstance(c, SpaceNode)
                for c in node.children
            )
        return False

    def _parse_environment(self) -> MathNode:
        """Parse \\begin{env}...\\end{env} into a matrix-like node."""
        env = self._read_brace_name()
        rows: list = []
        cells: list = []
        while True:
            nodes = self._parse_sequence(stop_at="&", env_mode=True)
            cells.append(self._as_cell(nodes))
            if self.pos < len(self.source) and self.source[self.pos] == "&":
                self.pos += 1
                continue
            if self.source.startswith("\\\\", self.pos):
                self.pos += 2
                rows.append(cells)
                cells = []
                continue
            if self.source.startswith("\\end", self.pos):
                self.pos += 4
                self._read_brace_name()
                rows.append(cells)
                break
            rows.append(cells)
            break
        if rows and all(self._is_empty_cell(c) for c in rows[-1]):
            rows.pop()
        if not rows:
            rows = [[GroupNode()]]
        if env in _MATRIX_ENVS:
            left, right = _MATRIX_ENVS[env]
            return MatrixNode(rows=rows, left_delim=left, right_delim=right)
        if env == "cases":
            return MatrixNode(rows=rows, left_delim="{", right_delim="", col_align="l")
        if env in _ALIGNED_ENVS:
            return AlignedNode(rows=rows, col_align="rl")
        if env in _GATHERED_ENVS:
            return AlignedNode(rows=rows, col_align="c")
        return MatrixNode(rows=rows)

    def _parse_command(self) -> MathNode:
        self.pos += 1  # skip backslash
        if self.pos >= len(self.source):
            return TextNode("\\")

        start = self.pos
        while self.pos < len(self.source) and self.source[self.pos].isalpha():
            self.pos += 1
        name = self.source[start : self.pos]

        if not name:
            ch = self.source[self.pos] if self.pos < len(self.source) else ""
            self.pos += 1
            if ch == ",":
                return SpaceNode(width_em=0.17)
            elif ch == ";":
                return SpaceNode(width_em=0.28)
            elif ch == "!":
                return SpaceNode(width_em=-0.17)
            elif ch == " ":
                return SpaceNode(width_em=0.25)
            return TextNode(ch)

        if name == "frac":
            num = self._parse_atom()
            den = self._parse_atom()
            return FractionNode(numerator=num, denominator=den)
        elif name == "sqrt":
            index: MathNode | None = None
            if self.pos < len(self.source) and self.source[self.pos] == "[":
                self.pos += 1
                inner = self._parse_sequence(stop_at="]")
                if self.pos < len(self.source) and self.source[self.pos] == "]":
                    self.pos += 1
                index = GroupNode(children=inner) if len(inner) != 1 else inner[0]
            radicand = self._parse_atom()
            return SqrtNode(radicand=radicand, index=index)
        elif name == "begin":
            return self._parse_environment()
        elif name in ("hat", "bar", "dot", "vec", "tilde"):
            base = self._parse_atom()
            return AccentNode(base=base, accent_type=name)
        elif name == "text":
            content = self._parse_atom()
            text = self._flatten_to_text(content)
            return TextNode(text, italic=False)
        elif name == "operatorname":
            content = self._parse_atom()
            text = self._flatten_to_text(content)
            return TextNode(text, italic=False)
        elif name in ("mathcal", "mathscr"):
            content = self._parse_atom()
            text = self._flatten_to_text(content)
            return TextNode(text, italic=True)
        elif name == "mathrm":
            content = self._parse_atom()
            text = self._flatten_to_text(content)
            return TextNode(text, italic=False)
        elif name == "mathbf":
            content = self._parse_atom()
            text = self._flatten_to_text(content)
            return TextNode(text, italic=False, bold=True)
        elif name == "mathbb":
            content = self._parse_atom()
            text = self._flatten_to_text(content)
            return TextNode(text, italic=False, bold=True)
        elif name == "mathit":
            content = self._parse_atom()
            text = self._flatten_to_text(content)
            return TextNode(text, italic=True)
        elif name == "left":
            delim = self.source[self.pos] if self.pos < len(self.source) else "("
            self.pos += 1
            inner = self._parse_sequence(stop_at="\\")
            right_delim = ")"
            if self.pos < len(self.source) and self.source[self.pos] == "\\":
                self.pos += 1
                rstart = self.pos
                while self.pos < len(self.source) and self.source[self.pos].isalpha():
                    self.pos += 1
                rname = self.source[rstart : self.pos]
                if rname == "right" and self.pos < len(self.source):
                    right_delim = self.source[self.pos]
                    self.pos += 1
            content = GroupNode(children=inner) if len(inner) != 1 else inner[0]
            return DelimiterNode(left=delim, right=right_delim, content=content)
        elif name == "quad":
            return SpaceNode(width_em=1.0)
        elif name == "qquad":
            return SpaceNode(width_em=2.0)
        elif name in (
            "lim",
            "sin",
            "cos",
            "tan",
            "log",
            "ln",
            "exp",
            "det",
            "max",
            "min",
        ):
            return TextNode(name, italic=False)
        elif name in GREEK_LETTERS:
            return SymbolNode(symbol=name, display=GREEK_LETTERS[name])
        elif name in MATH_SYMBOLS:
            return SymbolNode(symbol=name, display=MATH_SYMBOLS[name])
        else:
            return TextNode(name, italic=False)


def parse_math(source: str) -> MathNode:
    """Parse a LaTeX math string (or presentation MathML) into an AST."""
    if source.lstrip().startswith("<math"):
        from .mathml import parse_mathml

        return parse_mathml(source)
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


# -- TeX spacing classes --

_ORD, _OP, _BIN, _REL, _OPEN, _CLOSE, _PUNCT = range(7)

_THIN = 3.0 / 18.0
_MED = 4.0 / 18.0
_THICK = 5.0 / 18.0

# Inter-atom space in ems, indexed [left_class][right_class] (TeXbook ch. 18).
_SPACING = (
    (0.0, _THIN, _MED, _THICK, 0.0, 0.0, 0.0),  # ORD
    (_THIN, _THIN, _MED, _THICK, 0.0, 0.0, 0.0),  # OP
    (_MED, _MED, _MED, _MED, _MED, _MED, _MED),  # BIN
    (_THICK, _THICK, _MED, 0.0, _THICK, 0.0, 0.0),  # REL
    (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),  # OPEN
    (0.0, _THIN, _MED, _THICK, 0.0, 0.0, 0.0),  # CLOSE
    (_THIN, _THIN, _MED, _THIN, _THIN, _THIN, _THIN),  # PUNCT
)

_BIN_SYMBOLS = frozenset(
    {
        "pm",
        "mp",
        "times",
        "div",
        "cdot",
        "bullet",
        "wedge",
        "vee",
        "cup",
        "cap",
        "circ",
        "star",
        "dagger",
        "ddagger",
    }
)
_REL_SYMBOLS = frozenset(
    {
        "leq",
        "geq",
        "neq",
        "approx",
        "equiv",
        "sim",
        "propto",
        "in",
        "notin",
        "ni",
        "subset",
        "supset",
        "subseteq",
        "supseteq",
        "to",
        "leftarrow",
        "rightarrow",
        "Leftarrow",
        "Rightarrow",
        "leftrightarrow",
        "Leftrightarrow",
        "uparrow",
        "downarrow",
    }
)
_OP_SYMBOLS = frozenset({"sum", "prod", "int"})
_FUNC_NAMES = frozenset(
    {
        "lim",
        "sin",
        "cos",
        "tan",
        "log",
        "ln",
        "exp",
        "det",
        "max",
        "min",
    }
)


def _char_class(ch: str) -> int:
    """TeX spacing class of a single ASCII math character."""
    if ch in "+-*":
        return _BIN
    if ch in "=<>":
        return _REL
    if ch in "([":
        return _OPEN
    if ch in ")]":
        return _CLOSE
    if ch in ",;":
        return _PUNCT
    return _ORD


def _split_text(node: TextNode) -> list:
    """Split an italic text run into per-class atoms (digits go upright)."""
    if not node.text or not node.italic:
        return [node]
    runs: list = []
    for ch in node.text:
        cls = _char_class(ch)
        italic = cls == _ORD and ch.isalpha()
        if runs and cls == _ORD and runs[-1][1] == _ORD and runs[-1][2] == italic:
            runs[-1][0] += ch
        else:
            runs.append([ch, cls, italic])
    if len(runs) == 1 and runs[0][2] == node.italic:
        return [node]
    return [
        TextNode(text, italic=italic, bold=node.bold) for text, _cls, italic in runs
    ]


def _classify(node: MathNode) -> int:
    """TeX spacing class of a laid-out atom."""
    if isinstance(node, TextNode):
        if not node.text:
            return _ORD
        if not node.italic and node.text in _FUNC_NAMES:
            return _OP
        return _char_class(node.text[0])
    if isinstance(node, SymbolNode):
        if node.symbol in _OP_SYMBOLS:
            return _OP
        if node.symbol in _BIN_SYMBOLS:
            return _BIN
        if node.symbol in _REL_SYMBOLS:
            return _REL
        return _ORD
    if isinstance(node, (SuperscriptNode, SuperSubNode)):
        return _classify(node.base)
    if isinstance(node, SubscriptNode):
        return _classify(node.base)
    return _ORD


def _demote_bins(classes: list) -> list:
    """Demote binary operators to ordinary per the TeX context rules."""
    out = list(classes)
    n = len(out)
    for i in range(n):
        if out[i] != _BIN:
            continue
        prev = out[i - 1] if i > 0 else None
        nxt = out[i + 1] if i + 1 < n else None
        if prev is None or prev in (_BIN, _OP, _REL, _OPEN, _PUNCT):
            out[i] = _ORD
        elif nxt is None or nxt in (_REL, _CLOSE, _PUNCT):
            out[i] = _ORD
    return out


_METRICS_CACHE: dict[str, FontMetrics] = {}


def _base14(name: str) -> FontMetrics:
    """Shared, cached base-14 metrics instance."""
    metrics = _METRICS_CACHE.get(name)
    if metrics is None:
        metrics = FontMetrics.base14(name)
        _METRICS_CACHE[name] = metrics
    return metrics


class MathLayoutEngine:
    """Lay out math AST nodes into positioned boxes."""

    def __init__(
        self, base_size: float = 10.5, char_width: float = 0.55, display: bool = False
    ):
        self.base_size = base_size
        self.char_width = char_width  # retained for API compatibility
        self.display = display
        self._roman = _base14("Times-Roman")
        self._italic = _base14("Times-Italic")
        self._symbol = _base14("Symbol")

    def layout(self, node: MathNode, size: float | None = None) -> MathLayout:
        size = size or self.base_size
        return self._layout_node(node, 0.0, 0.0, size)

    def _layout_node(
        self, node: MathNode, x: float, y: float, size: float
    ) -> MathLayout:
        if isinstance(node, TextNode):
            runs = _split_text(node)
            if len(runs) > 1:
                return self._layout_group(GroupNode(children=runs), x, y, size)
            return self._layout_text(runs[0], x, y, size)
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
        elif isinstance(node, MatrixNode):
            return self._layout_grid(
                node.rows,
                node.left_delim,
                node.right_delim,
                node.col_align,
                0.6,
                x,
                y,
                size,
            )
        elif isinstance(node, AlignedNode):
            return self._layout_grid(
                node.rows,
                "",
                "",
                node.col_align,
                0.28,
                x,
                y,
                size,
            )
        return MathLayout()

    # -- font selection --

    def _text_metrics(self, italic: bool) -> FontMetrics:
        return self._italic if italic else self._roman

    def _layout_text(
        self, node: TextNode, x: float, y: float, size: float
    ) -> MathLayout:
        metrics = self._text_metrics(node.italic)
        w = metrics.text_width(node.text, size)
        box = MathBox(
            text=node.text,
            x=x,
            y=y,
            size=size,
            italic=node.italic,
            bold=node.bold,
            symbol=False,
        )
        return MathLayout(boxes=[box], width=w, height=size, depth=0)

    def _layout_symbol(
        self, node: SymbolNode, x: float, y: float, size: float
    ) -> MathLayout:
        w = self._symbol.text_width(node.display, size)
        box = MathBox(text=node.display, x=x, y=y, size=size, italic=False, symbol=True)
        return MathLayout(boxes=[box], width=w, height=size, depth=0)

    def _layout_group(
        self, node: GroupNode, x: float, y: float, size: float
    ) -> MathLayout:
        atoms: list = []
        for child in node.children:
            if isinstance(child, TextNode):
                atoms.extend(_split_text(child))
            else:
                atoms.append(child)
        atoms = [a for a in atoms if not (isinstance(a, SpaceNode) and a.soft)]
        classes = [None if isinstance(a, SpaceNode) else _classify(a) for a in atoms]
        classes = _demote_bins(classes)

        layout = MathLayout(height=size, depth=0)
        cursor = x
        prev_class = None
        for atom, cls in zip(atoms, classes):
            if prev_class is not None and cls is not None:
                cursor += _SPACING[prev_class][cls] * size
            child_layout = self._layout_node(atom, cursor, y, size)
            layout.boxes.extend(child_layout.boxes)
            layout.lines.extend(child_layout.lines)
            cursor += child_layout.width
            layout.height = max(layout.height, child_layout.height)
            layout.depth = max(layout.depth, child_layout.depth)
            prev_class = cls
        layout.width = cursor - x
        return layout

    # -- scripts --

    @staticmethod
    def _movable_limits(base: MathNode) -> bool:
        """True for operators whose limits attach only in display mode."""
        if isinstance(base, SymbolNode) and base.symbol in _OP_SYMBOLS:
            return True
        if isinstance(base, TextNode) and not base.italic:
            return base.text == "lim"
        return False

    def _limits_base(self, base: MathNode) -> bool:
        """True when scripts should render as display-style limits."""
        return self.display and self._movable_limits(base)

    def _script_as_limits(self, node) -> bool:
        """True when a script node places its scripts above/below the base."""
        if self._movable_limits(node.base):
            return self.display
        return node.limits

    def _layout_limits(
        self,
        base_node: MathNode,
        sup_node: MathNode | None,
        sub_node: MathNode | None,
        x: float,
        y: float,
        size: float,
    ) -> MathLayout:
        base = self._layout_node(base_node, 0.0, 0.0, size)
        script_size = size * 0.7
        sup = (
            self._layout_node(sup_node, 0.0, 0.0, script_size)
            if sup_node is not None
            else None
        )
        sub = (
            self._layout_node(sub_node, 0.0, 0.0, script_size)
            if sub_node is not None
            else None
        )
        total_w = max(
            base.width,
            sup.width if sup else 0.0,
            sub.width if sub else 0.0,
        )
        gap = size * 0.15

        layout = MathLayout()
        base_p = self._layout_node(base_node, x + (total_w - base.width) / 2, y, size)
        layout.boxes.extend(base_p.boxes)
        layout.lines.extend(base_p.lines)
        layout.height = base.height
        layout.depth = base.depth
        if sup_node is not None and sup is not None:
            sup_y = y + base.height + gap + sup.depth
            sup_p = self._layout_node(
                sup_node, x + (total_w - sup.width) / 2, sup_y, script_size
            )
            layout.boxes.extend(sup_p.boxes)
            layout.lines.extend(sup_p.lines)
            layout.height = base.height + gap + sup.depth + sup.height
        if sub_node is not None and sub is not None:
            sub_y = y - base.depth - gap - sub.height
            sub_p = self._layout_node(
                sub_node, x + (total_w - sub.width) / 2, sub_y, script_size
            )
            layout.boxes.extend(sub_p.boxes)
            layout.lines.extend(sub_p.lines)
            layout.depth = base.depth + gap + sub.height + sub.depth
        layout.width = total_w
        return layout

    def _layout_superscript(
        self, node: SuperscriptNode, x: float, y: float, size: float
    ) -> MathLayout:
        if self._script_as_limits(node):
            return self._layout_limits(node.base, node.exponent, None, x, y, size)
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

    def _layout_subscript(
        self, node: SubscriptNode, x: float, y: float, size: float
    ) -> MathLayout:
        if self._script_as_limits(node):
            return self._layout_limits(node.base, None, node.subscript, x, y, size)
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

    def _layout_supersub(
        self, node: SuperSubNode, x: float, y: float, size: float
    ) -> MathLayout:
        if self._script_as_limits(node):
            return self._layout_limits(
                node.base, node.superscript, node.subscript, x, y, size
            )
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

    def _layout_fraction(
        self, node: FractionNode, x: float, y: float, size: float
    ) -> MathLayout:
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
        layout.lines.append(
            MathLine(x=x, y=bar_y, width=total_w, thickness=bar_thickness)
        )
        layout.width = total_w
        layout.height = (num_y + frac_size) - y
        layout.depth = y - den_y + frac_size * 0.3
        return layout

    def _layout_sqrt(
        self, node: SqrtNode, x: float, y: float, size: float
    ) -> MathLayout:
        inner = self._layout_node(node.radicand, 0, 0, size)
        hook_w = self._symbol.text_width("√", size * 1.1)
        pad = size * 0.15

        index_w = 0.0
        index_boxes: list = []
        index_lines: list = []
        index_top = 0.0
        if node.index is not None:
            index_size = size * 0.6
            index_y = y + size * 0.45
            measured = self._layout_node(node.index, 0.0, 0.0, index_size)
            placed = self._layout_node(node.index, x, index_y, index_size)
            # The index tucks into the radical's rising diagonal.
            index_w = max(0.0, measured.width - hook_w * 0.35)
            index_boxes = placed.boxes
            index_lines = placed.lines
            index_top = (index_y - y) + measured.height

        rad_x = x + index_w
        inner_shifted = self._layout_node(node.radicand, rad_x + hook_w, y, size)

        layout = MathLayout()
        layout.boxes = index_boxes + inner_shifted.boxes
        layout.lines = index_lines + inner_shifted.lines

        bar_y = y + inner.height + pad * 0.5
        layout.lines.append(
            MathLine(
                x=rad_x + hook_w - 1,
                y=bar_y,
                width=inner.width + 2,
                thickness=size * 0.04,
            )
        )

        # Radical sign from Symbol font
        radical = MathBox(
            text="√",
            x=rad_x,
            y=y - size * 0.1,
            size=size * 1.1,
            italic=False,
            symbol=True,
        )
        layout.boxes.append(radical)

        layout.width = index_w + hook_w + inner.width
        layout.height = max(inner.height + pad, index_top)
        layout.depth = inner.depth
        return layout

    def _layout_accent(
        self, node: AccentNode, x: float, y: float, size: float
    ) -> MathLayout:
        base = self._layout_node(node.base, x, y, size)
        accent_map = {
            "hat": ("^", False),
            "bar": ("¯", False),
            "dot": (".", False),
            "vec": ("→", True),
            "tilde": ("~", False),
        }
        accent_text, is_symbol = accent_map.get(node.accent_type, ("^", False))
        accent_size = size * 0.7
        accent_metrics = self._symbol if is_symbol else self._roman
        accent_w = accent_metrics.text_width(accent_text, accent_size)
        accent_y = y + base.height + size * 0.05
        accent_x = x + (base.width - accent_w) / 2

        layout = MathLayout()
        layout.boxes = base.boxes + [
            MathBox(
                text=accent_text,
                x=accent_x,
                y=accent_y,
                size=accent_size,
                italic=False,
                symbol=is_symbol,
            )
        ]
        layout.lines = base.lines
        layout.width = base.width
        layout.height = base.height + size * 0.3
        layout.depth = base.depth
        return layout

    def _layout_delimiter(
        self, node: DelimiterNode, x: float, y: float, size: float
    ) -> MathLayout:
        inner = self._layout_node(node.content, 0, 0, size)
        delim_size = max(size, inner.height + inner.depth) * 1.1
        left_w = (
            self._roman.text_width(node.left, delim_size)
            if node.left and node.left != "."
            else 0.0
        )
        right_w = (
            self._roman.text_width(node.right, delim_size)
            if node.right and node.right != "."
            else 0.0
        )
        delim_y = y - (delim_size - size) * 0.35

        layout = MathLayout()
        if left_w:
            layout.boxes.append(
                MathBox(text=node.left, x=x, y=delim_y, size=delim_size, italic=False)
            )
        inner_shifted = self._layout_node(node.content, x + left_w, y, size)
        layout.boxes.extend(inner_shifted.boxes)
        layout.lines.extend(inner_shifted.lines)
        if right_w:
            layout.boxes.append(
                MathBox(
                    text=node.right,
                    x=x + left_w + inner.width,
                    y=delim_y,
                    size=delim_size,
                    italic=False,
                )
            )
        layout.width = left_w + inner.width + right_w
        layout.height = max(inner.height, delim_size)
        layout.depth = max(inner.depth, delim_size * 0.2)
        return layout

    # -- environments --

    def _layout_grid(
        self,
        rows: list,
        left: str,
        right: str,
        col_align: str,
        col_gap_em: float,
        x: float,
        y: float,
        size: float,
    ) -> MathLayout:
        measured = [
            [self._layout_node(cell, 0.0, 0.0, size) for cell in row] for row in rows
        ]
        ncols = max(len(row) for row in measured)
        col_widths = [0.0] * ncols
        for row in measured:
            for j, cell in enumerate(row):
                col_widths[j] = max(col_widths[j], cell.width)
        row_ascents = [
            max((cell.height for cell in row), default=size) for row in measured
        ]
        row_descents = [
            max((cell.depth for cell in row), default=0.0) for row in measured
        ]
        row_heights = [asc + desc for asc, desc in zip(row_ascents, row_descents)]
        # Row leading is 1.25x the row height: gap of 0.25x below each row.
        total_h = sum(row_heights) + sum(0.25 * h for h in row_heights[:-1])
        col_gap = col_gap_em * size
        grid_w = sum(col_widths) + col_gap * (ncols - 1)

        axis = size * 0.25
        top = y + axis + total_h / 2
        delim_size = max(size, total_h * 1.05)
        delim_y = y + axis - delim_size * 0.30
        left_w = self._roman.text_width(left, delim_size) if left else 0.0
        right_w = self._roman.text_width(right, delim_size) if right else 0.0

        layout = MathLayout()
        if left:
            layout.boxes.append(
                MathBox(text=left, x=x, y=delim_y, size=delim_size, italic=False)
            )
        content_x = x + left_w
        cursor_top = top
        for i, row in enumerate(rows):
            baseline = cursor_top - row_ascents[i]
            cell_x = content_x
            for j, cell in enumerate(row):
                cell_w = measured[i][j].width
                if col_align == "l":
                    cx = cell_x
                elif col_align == "rl":
                    if j % 2 == 0:
                        cx = cell_x + col_widths[j] - cell_w
                    else:
                        cx = cell_x
                else:
                    cx = cell_x + (col_widths[j] - cell_w) / 2
                placed = self._layout_node(cell, cx, baseline, size)
                layout.boxes.extend(placed.boxes)
                layout.lines.extend(placed.lines)
                cell_x += col_widths[j] + col_gap
            cursor_top = baseline - row_descents[i] - 0.25 * row_heights[i]
        if right:
            layout.boxes.append(
                MathBox(
                    text=right,
                    x=content_x + grid_w,
                    y=delim_y,
                    size=delim_size,
                    italic=False,
                )
            )
        layout.width = left_w + grid_w + right_w
        layout.height = axis + total_h / 2
        layout.depth = max(0.0, total_h / 2 - axis)
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


def render_math(
    stream,
    math_expr: MathExpression,
    x: float,
    y: float,
    font_key: str,
    size: float,
    color: str = "000000",
    italic_key: str | None = None,
    symbol_key: str | None = None,
) -> float:
    """Render a math expression into a content stream.

    Returns the total width of the rendered expression.
    """
    node = parse_math(math_expr.source)
    engine = MathLayoutEngine(base_size=size, display=math_expr.display)
    layout = engine.layout(node)

    for box in layout.boxes:
        if box.symbol and symbol_key:
            encoded = _symbol_encode(box.text)
            stream.raw(b"BT")
            stream.set_fill(color)
            stream.raw(
                f"/{symbol_key} ".encode("ascii") + stream._num(box.size) + b" Tf"
            )
            stream.raw(
                b" ".join([stream._num(x + box.x), stream._num(y + box.y), b"Td"])
            )
            stream.raw(encoded + b" Tj")
            stream.raw(b"ET")
        else:
            key = italic_key if (italic_key and box.italic) else font_key
            stream.text_line(
                box.text,
                key,
                box.size,
                x + box.x,
                y + box.y,
                color,
            )

    for line in layout.lines:
        stream.line(
            x + line.x,
            y + line.y,
            x + line.x + line.width,
            y + line.y,
            color=color,
            width=line.thickness,
        )

    return layout.width
