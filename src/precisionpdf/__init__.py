"""PrecisionPDF - constraint-driven PDF generation.

Describe a document; the engine handles layout, typography, and the
PDF/UA structure tree. Output is deterministic: identical input always
produces identical bytes.

    from precisionpdf import Document

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
    Document, Footnote, Heading, HorizontalRule, Image, LegalFeatures,
    MathBlock, PageBreak, PageSpec, Paragraph, Table, TableCell, TextRun,
)
from .bibliography import format_citation, format_bibliography
from .code_highlight import tokenize, colorize, THEMES as CODE_THEMES, LANGUAGES
from .math_render import parse_math, MathExpression, render_math
from .colors import ColorTheme, resolve_color, PALETTES
from .crossref import CrossReferenceIndex
from .styles import PRESETS, Style, StyleSheet, resolve_preset
from .typography.font_metrics import FontMetrics, FontRegistry
from .typography.hyphenation import Hyphenator
from .typography.line_breaking import LineBreaker
from .intelligence import (
    ContentAnalyzer, QualityScorer, SmartTypography, TableIntelligence,
    DocumentTypeDetector,
)
from .slides import slide_document, SlideConfig, SLIDE_16_9, SLIDE_4_3
from .writer import RenderResult, render_document

__version__ = "0.1.0"

__all__ = [
    "Document", "PageSpec", "Heading", "Paragraph", "BulletList", "Table",
    "TableCell", "TextRun", "Image", "Chart", "Footnote", "Callout",
    "CodeBlock", "MathBlock", "BibliographyBlock", "Citation",
    "PageBreak", "HorizontalRule", "LegalFeatures",
    "format_citation", "format_bibliography",
    "tokenize", "colorize", "CODE_THEMES", "LANGUAGES",
    "parse_math", "MathExpression", "render_math",
    "ColorTheme", "resolve_color", "PALETTES", "CrossReferenceIndex",
    "Style", "StyleSheet", "PRESETS", "resolve_preset",
    "FontRegistry", "FontMetrics", "Hyphenator", "LineBreaker",
    "ConstraintValidator", "ValidationResult", "ValidationError", "Issue",
    "slide_document", "SlideConfig", "SLIDE_16_9", "SLIDE_4_3",
    "render_document", "RenderResult",
    "ContentAnalyzer", "QualityScorer", "SmartTypography",
    "TableIntelligence", "DocumentTypeDetector",
    "__version__",
]
