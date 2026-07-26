"""Emboss - constraint-driven PDF generation.

Describe a document; the engine handles layout, typography, and the
PDF/UA structure tree. Output is deterministic: identical input always
produces identical bytes.

    from emboss import Document

    doc = Document(title="Quarterly Report", style="finance")
    doc.heading("Revenue Analysis", level=1)
    doc.paragraph("Revenue increased 12% year over year.")
    doc.table(headers=["Region", "Q3"], rows=[["North", "$2.4M"]])
    doc.save("report.pdf")
"""

from .constraints import (
    ConstraintValidator, Issue, ValidationError, ValidationResult,
)
from .spec import (
    BibliographyBlock, BulletList, Callout, Chart, Citation, CodeBlock,
    Document, Footnote, HeaderFooter, Heading, HorizontalRule, Image,
    LegalFeatures, MathBlock, NumberedList, PageBreak, PageSpec, Paragraph,
    SvgBlock, Table, TableCell, TextRun,
)
from .bibliography import format_citation, format_bibliography
from .code_highlight import tokenize, colorize, THEMES as CODE_THEMES, LANGUAGES
from .math_render import parse_math, MathExpression, render_math
from .colors import ColorTheme, resolve_color, PALETTES
from .crossref import CrossReferenceIndex
from .svg import SvgImage, parse_svg, render_svg
from .numbering import NumberingContext
from .styles import PRESETS, Style, StyleSheet, resolve_preset
from .typography.font_metrics import FontMetrics, FontRegistry
from .typography.hyphenation import Hyphenator
from .typography.line_breaking import LineBreaker
from .intelligence import (
    ContentAnalyzer, QualityScorer, SmartTypography, TableIntelligence,
    DocumentTypeDetector,
)
from .slides import slide_document, SlideConfig, SLIDE_16_9, SLIDE_4_3
from .templates import (
    memo, report, letter, invoice, academic_paper, legal_brief,
    slide_deck, data_sheet,
)
from .writer import RenderResult, render_document

__version__ = "0.1.0"

__all__ = [
    "Document", "PageSpec", "Heading", "Paragraph", "BulletList",
    "NumberedList", "Table", "TableCell", "TextRun", "Image", "Chart",
    "Footnote", "Callout", "CodeBlock", "MathBlock", "BibliographyBlock",
    "Citation", "SvgBlock", "PageBreak", "HorizontalRule", "LegalFeatures",
    "HeaderFooter", "SvgImage", "parse_svg", "render_svg", "NumberingContext",
    "format_citation", "format_bibliography",
    "tokenize", "colorize", "CODE_THEMES", "LANGUAGES",
    "parse_math", "MathExpression", "render_math",
    "ColorTheme", "resolve_color", "PALETTES", "CrossReferenceIndex",
    "Style", "StyleSheet", "PRESETS", "resolve_preset",
    "FontRegistry", "FontMetrics", "Hyphenator", "LineBreaker",
    "ConstraintValidator", "ValidationResult", "ValidationError", "Issue",
    "slide_document", "SlideConfig", "SLIDE_16_9", "SLIDE_4_3",
    "memo", "report", "letter", "invoice", "academic_paper",
    "legal_brief", "slide_deck", "data_sheet",
    "render_document", "RenderResult",
    "ContentAnalyzer", "QualityScorer", "SmartTypography",
    "TableIntelligence", "DocumentTypeDetector",
    "__version__",
]
