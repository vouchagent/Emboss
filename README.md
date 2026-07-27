# Emboss

[![CI](https://github.com/GGChamp85/Emboss/actions/workflows/ci.yml/badge.svg)](https://github.com/GGChamp85/Emboss/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://pypi.org/project/emboss-pdf/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)

Precision PDF generation for Python. Describe a document with a declarative spec; the engine handles typography, layout, accessibility tagging, and the complete PDF structure. Output is deterministic and byte-identical across runs.

```python
from emboss import Document

doc = Document(title="Q3 Report", style="finance")
doc.heading("Revenue Analysis", level=1)
doc.paragraph("Revenue increased 12% year over year.")
doc.table(headers=["Region", "Q3"], rows=[["North America", "$2.4M"]])
doc.save("report.pdf")
```

No coordinates. No manual page-break handling. No separate accessibility pass.

---

## Table of Contents

- [Why Emboss](#why-emboss)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [EmbossSpec Format](#embossspec-format)
- [Document Elements](#document-elements)
- [Style Presets](#style-presets)
- [Typography Engine](#typography-engine)
- [Layout System](#layout-system)
- [Accessibility (PDF/UA)](#accessibility-pdfua)
- [Templates](#templates)
- [Domain Features](#domain-features)
- [Cross-References and Numbering](#cross-references-and-numbering)
- [SVG Embedding](#svg-embedding)
- [Multi-Column Layout](#multi-column-layout)
- [Math Notation](#math-notation)
- [Code Blocks](#code-blocks)
- [Charts](#charts)
- [PDF/A Archival Output](#pdfa-archival-output)
- [Digital Signatures](#digital-signatures)
- [Validation](#validation)
- [Adapters](#adapters)
- [API Reference](#api-reference)
- [Performance](#performance)
- [Development](#development)
- [Architecture](#architecture)
- [Roadmap](#roadmap)
- [License](#license)

---

## Why Emboss

Existing Python PDF libraries are page-description tools: you place ink at coordinates, and the resulting file has no idea that a given string was a heading. Accessibility tags, if available at all, are painted on after the fact and tend to disagree with the visible page.

Emboss inverts that. The semantic document is the source of truth, and both the visual output and the structure tree are derived from it. They cannot drift apart, because they come from the same description.

### What it guarantees

**Deterministic output.** The same document produces byte-identical PDFs across runs and machines. No timestamps, no random identifiers; the file `/ID` is derived from content. This makes output hash-verifiable for filings and diffable in CI.

```python
assert doc.render() == doc.render()   # always true
```

**Structural correctness.** Cross-reference offsets are recorded as bytes are written, so the xref table cannot disagree with the file.

**Content never overflows.** Everything is measured before anything is placed, so text running off the page is not a failure mode.

**Tagged by default.** Every document ships with a complete PDF/UA structure tree.

---

## Installation

```bash
pip install emboss-pdf
```

Requires Python 3.10+ and `fonttools`. Optional extras:

```bash
pip install emboss-pdf[all]       # pydantic + pikepdf + cryptography
pip install emboss-pdf[llm]       # pydantic schemas for LLM structured output
pip install emboss-pdf[verify]    # pikepdf for PDF structural verification
pip install emboss-pdf[signing]   # cryptography for digital signatures
pip install emboss-pdf[dev]       # full dev environment (pytest, mypy, ruff)
```

---

## Quick Start

### Fluent API

```python
from emboss import Document

doc = Document(title="Quarterly Report", author="Finance Team", style="finance")
doc.heading("Executive Summary", level=1)
doc.paragraph("Revenue grew 12% year over year, driven by enterprise expansion.")
doc.table(
    headers=["Metric", "Q3 2025", "Q3 2024", "Change"],
    rows=[
        ["Revenue", "$24.1M", "$21.5M", "+12%"],
        ["EBITDA",  "$8.2M",  "$6.9M",  "+19%"],
    ],
)
doc.bullets(["North America: +15%", "EMEA: +8%", "APAC: +11%"])
doc.save("quarterly_report.pdf")
```

### Declarative Spec

```python
from emboss.spec import Document, Heading, Paragraph, Table

doc = Document(
    title="Quarterly Report",
    style="finance",
    content=[
        Heading(text="Executive Summary", level=1),
        Paragraph(content="Revenue grew 12% year over year."),
        Table(
            headers=["Metric", "Value"],
            rows=[["Revenue", "$24.1M"], ["EBITDA", "$8.2M"]],
        ),
    ],
)
pdf_bytes = doc.render()
```

### LLM Integration (3 tiers)

**Tier 1: Spec prompt** (full quality, recommended) -- pass the EmbossSpec format with your prompt:

```python
from emboss import spec_prompt, Document

system = spec_prompt(style="finance")  # compact EmbossSpec description for LLMs
response = client.messages.create(
    model="claude-sonnet-5",
    system=system,
    messages=[{"role": "user", "content": "Create a Q3 financial report"}],
)
doc = Document.from_json(response.text)
doc.save("report.pdf")
```

**Tier 2: One-liner** (zero friction):

```python
from emboss import generate

generate("Create a quarterly financial report",
         style="finance", output="report.pdf",
         provider="anthropic")  # or "openai"
```

**Tier 3: Markdown** (works with any LLM output):

```python
from emboss import Document

md = llm.generate("Write a quarterly report...")  # any LLM, any provider
doc = Document.from_markdown(md, style="finance")
doc.save("report.pdf")
```

All three tiers produce identical PDF quality -- the typography engine (Knuth-Plass, optical margins, kerning) runs the same regardless of input format.

---

## EmbossSpec Format

Documents are defined using **EmbossSpec**, a declarative JSON-serializable specification. Every document element is a typed Python dataclass that can be constructed programmatically, deserialized from JSON, or generated by an LLM via structured output.

The spec is the single source of truth. From it, Emboss derives:
- The visual PDF (typography, layout, pagination)
- The accessibility structure tree (PDF/UA tags)
- HTML, Markdown, and DOCX exports (via adapters)

```json
{
  "title": "Annual Report",
  "style": "corporate",
  "content": [
    {"type": "heading", "text": "Overview", "level": 1},
    {"type": "paragraph", "content": "Company performance exceeded targets."},
    {"type": "table", "headers": ["Q1", "Q2"], "rows": [["$1M", "$1.2M"]]}
  ]
}
```

---

## Document Elements

| Element | Description | Key Parameters |
|---------|-------------|----------------|
| `Heading` | Section heading (H1-H6) | `text`, `level` (1-6) |
| `Paragraph` | Body text with inline formatting | `content` (str, TextRun, or list) |
| `BulletList` | Unordered list with nesting | `items` (strings or sublists) |
| `NumberedList` | Ordered list with nesting | `items`, `start` |
| `Table` | Data table with header row | `headers`, `rows`, `caption` |
| `Image` | Embedded image | `source` (path or bytes), `width`, `caption` |
| `CodeBlock` | Syntax-highlighted code | `code`, `language`, `line_numbers` |
| `MathBlock` | LaTeX-style math notation | `source`, `display` |
| `Chart` | Data visualization | `chart_type`, `labels`, `values` |
| `Callout` | Admonition box (note/warning/tip) | `content`, `variant`, `title` |
| `Footnote` | Numbered footnote | `content` |
| `SvgBlock` | Inline SVG vector graphic | `source`, `width`, `height` |
| `BibliographyBlock` | Formatted citation list | `citations` |
| `HorizontalRule` | Visual separator | `thickness`, `color` |
| `PageBreak` | Force a page break | -- |

### Inline Formatting

```python
from emboss import Paragraph, TextRun

Paragraph(content=[
    TextRun(text="Regular text, "),
    TextRun(text="bold text", bold=True),
    TextRun(text=", "),
    TextRun(text="italic text", italic=True),
    TextRun(text=", and "),
    TextRun(text="colored text", color="2563eb"),
])
```

---

## Style Presets

Five professionally designed stylesheets are built in. Each encodes type scale, leading, table rules, and spacing so output looks authored without choosing a single measurement.

| Preset | Body Font | Heading Font | Body Size | Alignment | Use Case |
|--------|-----------|-------------|-----------|-----------|----------|
| `legal` | Times | Times | 11.5pt | Justified | Contracts, briefs, pleadings |
| `finance` | Helvetica | Helvetica | 10pt | Left | Reports, filings, data sheets |
| `academic` | Times | Helvetica | 11.5pt | Justified | Papers, dissertations, theses |
| `corporate` | Helvetica | Helvetica | 10.5pt | Left | Memos, policies, manuals |
| `minimal` | Helvetica | Helvetica | 9.5pt | Left | Data exports, compact reports |

```python
# Use a preset by name
doc = Document(style="finance")

# Or create a custom stylesheet
from emboss import Style, StyleSheet
custom = StyleSheet(
    name="custom",
    body=Style(font_family="Helvetica", font_size=11.0, align="justify"),
    h1=Style(font_size=18.0, bold=True),
    # ... other elements
)
doc = Document(style=custom)
```

---

## Typography Engine

### Knuth-Plass Line Breaking

Emboss uses the Knuth-Plass algorithm from Knuth and Plass (1981) for optimal paragraph line breaking. Unlike greedy algorithms that fill each line independently, Knuth-Plass treats the paragraph as a shortest-path problem and minimizes total demerits across all lines:

```
greedy   widths: [216, 172, 168, 162, 176]   variance 367
optimal  widths: [216, 224, 202, 198]        variance 110
```

The algorithm:
- Models text as Box (word), Glue (elastic space), and Penalty (breakpoint) items
- Considers all legal breakpoints simultaneously
- Penalizes consecutive hyphenation, abrupt spacing changes, and tight/loose lines
- Falls back to greedy breaking only for pathological input (long URLs, extreme narrow columns)

### Knuth-Liang Hyphenation

Pattern-based hyphenation with a no-break list for domain terms (`Inc.`, `LLC`, `EBITDA`, `plaintiff`) that should never be split.

### Real Font Metrics

Glyph advances and kerning come from the font file (via fonttools). Text is emitted with the PDF `TJ` operator so kerning pairs are actually applied between glyphs. Base-14 font metrics are built in, so valid PDFs are produced with no font files present.

### Smart Typography

Automatic curly quotes, em/en dashes, fractions, ellipses, and non-breaking spaces before units. Applied during text processing, not as a post-process.

### Ligature Support

Automatic fi, fl, ffi, and ffl ligature substitution for fonts that support them.

---

## Layout System

### Page Setup

```python
from emboss import PageSpec

# Standard sizes
page = PageSpec.letter()                        # 8.5 x 11 in
page = PageSpec.a4()                            # 210 x 297 mm
page = PageSpec.legal()                         # 8.5 x 14 in

# Custom dimensions and margins (in points, 72pt = 1 inch)
page = PageSpec(
    width=612, height=792,
    margin_top=72, margin_bottom=72,
    margin_left=90, margin_right=72,
)

# Multi-column layout
page = PageSpec.a4(columns=2, column_gap=18)
```

### Pagination Features

- **Widow and orphan control**: prevents single lines stranded at page tops/bottoms
- **Keep-with-next**: headings stay with their following paragraph
- **Keep-together**: atomic blocks (callouts, small tables) never split across pages
- **Table splitting**: large tables break across pages with header row repetition
- **Column balancing**: multi-column layouts balance content across columns

---

## Accessibility (PDF/UA)

Every document is tagged with a complete PDF/UA structure tree:

- Headings become `/H1` through `/H6`
- Paragraphs become `/P`
- Tables become `/Table` with `/TH` and `/TD` cells; header cells carry `/Scope`
- Lists become `/L` with `/LI`, `/Lbl`, and `/LBody`
- Images get `/Figure` with alt text
- Running heads, page numbers, Bates stamps, and watermarks are marked `/Artifact`

```python
from emboss.pdf.verify import verify_pdf

result = verify_pdf(doc.render())
print(result)  # VerifyResult(valid=True, structure_tree=True, ...)
```

---

## Templates

Pre-configured document factories for common formats:

```python
from emboss.templates import memo, report, letter, invoice

# Create a memo with pre-set styling
doc = memo(title="Project Update", author="Engineering Team")
doc.heading("Status", level=2)
doc.paragraph("All milestones are on track.")
doc.save("memo.pdf")

# Create an invoice
doc = invoice(title="Invoice #2024-0147", author="Acme Corp")
doc.table(
    headers=["Item", "Qty", "Price"],
    rows=[["Widget", "100", "$5.00"], ["Gadget", "50", "$12.00"]],
)
doc.save("invoice.pdf")
```

Available templates: `memo`, `report`, `letter`, `invoice`, `academic_paper`, `legal_brief`, `slide_deck`, `data_sheet`.

---

## Domain Features

### Legal and Financial Documents

```python
from emboss import Document, LegalFeatures, PageSpec

doc = Document(
    title="Memorandum of Understanding",
    style="legal",
    page=PageSpec.letter(margin_left=108),
    legal=LegalFeatures(
        watermark="CONFIDENTIAL",
        watermark_opacity=0.12,
        line_numbering=True,
        bates_prefix="ACME-",
        bates_start=1,
        bates_digits=6,
        bates_position="bottom-right",
    ),
)
```

- **Bates numbering**: sequential identifiers for legal discovery
- **Line numbering**: continuous line numbers in the left margin (court filings)
- **Watermarks**: diagonal text overlay with configurable opacity

### Custom Headers and Footers

```python
from emboss import HeaderFooter

doc = Document(
    header=HeaderFooter(
        left="Acme Corp",
        center="Confidential",
        right="{page} of {pages}",
        separator=True,
    ),
    footer=HeaderFooter(
        center="Generated by Emboss",
    ),
)
```

Placeholders `{page}` and `{pages}` are resolved at render time.

---

## Cross-References and Numbering

Automatic figure, table, and equation numbering with label-based cross-references:

```python
from emboss import Document, Table, Image
from emboss.crossref import CrossReferenceIndex

doc = Document(title="Research Paper", style="academic")
doc.table(
    headers=["Variable", "Value"],
    rows=[["x", "42"]],
    caption="Experimental results",
    label="results-table",
)
doc.paragraph("As shown in @results-table, the value of x is 42.")
```

The `@label` syntax resolves to "Table 1", "Figure 2", etc., with automatic counter tracking via `NumberingContext`.

---

## SVG Embedding

Embed SVG vector graphics as native PDF paths (no rasterization):

```python
doc.svg("""
<svg width="200" height="100">
  <rect x="10" y="10" width="80" height="80" fill="#2563eb"/>
  <circle cx="150" cy="50" r="40" fill="#dc2626"/>
</svg>
""", width=200, height=100)
```

Supported elements: `rect`, `circle`, `ellipse`, `line`, `polygon`, `polyline`, `path` (M/L/H/V/C/Z commands).

---

## Multi-Column Layout

```python
from emboss import Document, PageSpec

doc = Document(
    title="Newsletter",
    page=PageSpec.a4(columns=2, column_gap=18),
)
doc.heading("Top Stories", level=1)
doc.paragraph("Content flows automatically across columns...")
```

Content flows between columns automatically. Column-spanning elements (headings, wide tables) are supported via the `column_span` style property.

---

## Math Notation

LaTeX-style math rendering with support for common commands:

```python
doc.math(r"E = mc^2")
doc.math(r"\int_{0}^{\infty} e^{-x^2} dx = \frac{\sqrt{\pi}}{2}")
doc.math(r"\sum_{i=1}^{n} x_i = \frac{n(n+1)}{2}")
```

Supported: superscripts, subscripts, fractions (`\frac`), square roots (`\sqrt`), integrals, summations, Greek letters, `\text{}`, `\mathcal`, `\mathbb`, `\mathbf`, `\mathrm`, `\operatorname`, and more.

---

## Code Blocks

Syntax-highlighted code with optional line numbers:

```python
doc.code_block(
    code='def hello():\n    print("Hello, world!")',
    language="python",
    line_numbers=True,
)
```

Built-in highlighters for Python, JavaScript, TypeScript, SQL, JSON, HTML, CSS, Rust, Go, Java, C, and more.

---

## Charts

Data visualization rendered as native PDF vector graphics:

```python
doc.chart(
    chart_type="bar",
    labels=["Q1", "Q2", "Q3", "Q4"],
    values=[120, 150, 180, 210],
    caption="Quarterly Revenue ($M)",
)
```

Chart types: `bar`, `line`, `pie`, `scatter`.

---

## PDF/A Archival Output

Generate PDF/A-2b compliant output for long-term archival:

```python
doc = Document(
    title="Annual Filing",
    pdfa=True,       # enables PDF/A-2b conformance
    tagged=True,     # required for PDF/A
)
```

Includes XMP metadata, sRGB ICC output intent, and all required PDF/A catalog entries.

---

## Digital Signatures

Sign PDFs with X.509 certificates:

```python
from emboss.signing import sign_pdf

signed_bytes = sign_pdf(
    pdf_bytes,
    cert_path="signer.pem",
    key_path="signer-key.pem",
    reason="Approved",
    location="San Francisco",
)
```

Requires `pip install emboss-pdf[signing]`.

---

## Validation

Constraints are checked before rendering. Repairable issues are fixed automatically; genuine errors are reported:

```python
from emboss import ConstraintValidator

result = ConstraintValidator().validate(doc)
for issue in result.issues:
    print(issue)
# fixed/mathematical: column widths rescaled to fit page
# fixed/structural: orphan heading moved to next page
```

---

## Adapters

Export to multiple formats from a single document spec:

```python
from emboss.adapters.html_export import to_html
from emboss.adapters.markdown_export import to_markdown
from emboss.adapters.docx_export import to_docx

html_str = to_html(doc)
md_str = to_markdown(doc)
docx_bytes = to_docx(doc)
```

### Pydantic Schema (LLM Integration)

```python
from emboss.adapters.pydantic_schema import build_json_schema, parse_document

# Get the JSON Schema for LLM structured output
schema = build_json_schema()

# Parse an LLM-generated JSON document
doc = parse_document(json_string)
pdf_bytes = doc.render()
```

---

## API Reference

### Document

```python
Document(
    title="",              # Document title (appears in PDF metadata and title block)
    author="",             # Author name
    subject="",            # Subject line
    keywords="",           # Comma-separated keywords
    language="en-US",      # BCP 47 language tag
    style="corporate",     # Preset name or StyleSheet instance
    page=PageSpec(),       # Page dimensions and margins
    content=[],            # List of block elements
    header=None,           # HeaderFooter for page headers
    footer=None,           # HeaderFooter for page footers
    page_numbers=True,     # Show page numbers
    tagged=True,           # Generate PDF/UA structure tree
    legal=None,            # LegalFeatures (Bates, line numbers, watermark)
    pdfa=False,            # Generate PDF/A-2b compliant output
    toc=False,             # Generate table of contents
    signatures=None,       # Digital signature fields
)
```

### Convenience Methods

```python
doc.heading(text, level=1)
doc.paragraph(content)
doc.bullets(items)
doc.numbered(items)
doc.table(headers, rows)
doc.image(source, width=None, caption=None)
doc.chart(chart_type, labels, values)
doc.code_block(code, language="text")
doc.math(source)
doc.footnote(content)
doc.callout(content, variant="note")
doc.svg(source)
doc.rule()
doc.page_break()
doc.render() -> bytes
doc.save(path)
```

---

## Performance

- Layout is pure Python with Knuth-Plass optimal line breaking
- Font metrics are cached with LRU caching
- A typical 10-page document renders in ~50-100ms
- 200-page documents are supported with ~20-50MB peak memory
- O(n) linear scaling with document size

---

## Development

### Setup

```bash
git clone https://github.com/GGChamp85/Emboss.git
cd Emboss
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Running Tests

```bash
pytest                          # run all tests
pytest tests/test_emboss.py     # run core tests
pytest -q                       # quiet mode
```

### Code Quality

```bash
ruff check src/ tests/          # linting
mypy src/emboss/                # type checking
```

### Generating Example PDFs

```bash
python examples/financial_report.py
python examples/legal_pleading.py
python examples/showcase.py
```

---

## Architecture

```
Document (EmbossSpec)
    |
    v
ConstraintValidator --> validate + auto-fix
    |
    v
LayoutEngine --> measure (font metrics) --> paginate (Knuth-Plass)
    |
    v
Renderer --> ContentStream (PDF operators) + StructureTree (PDF/UA tags)
    |
    v
PDFAssembler --> byte-exact PDF with content-derived /ID
```

### Package Structure

```
src/emboss/
  spec.py               # Document data model (EmbossSpec)
  writer.py             # Render pipeline: measure -> paginate -> render
  styles.py             # Cascading style system + presets
  constraints.py        # Validation + auto-fix
  layout/
    engine.py           # Layout engine: measurement + pagination
  typography/
    font_metrics.py     # Glyph metrics, kerning, subsetting
    line_breaking.py    # Knuth-Plass line breaker
    hyphenation.py      # Knuth-Liang hyphenation
    ligatures.py        # fi/fl/ffi/ffl substitution
  pdf/
    assembler.py        # Low-level PDF object writer
    fonts.py            # Font resource building + subsetting
    objects.py          # PDF object types (Dict, Array, Stream)
    streams.py          # Content stream operators (text, shapes)
    tags.py             # PDF/UA structure tree builder
    verify.py           # Structural verification
  adapters/
    html_export.py      # HTML export
    markdown_export.py  # Markdown export
    docx_export.py      # DOCX export
    pydantic_schema.py  # JSON Schema / Pydantic models for LLM
  math_render.py        # LaTeX math parser + renderer
  code_highlight.py     # Syntax highlighting
  charts.py             # Chart rendering
  images.py             # Image handling
  svg.py                # SVG parser + renderer
  crossref.py           # Cross-reference resolution
  numbering.py          # Figure/table auto-numbering
  templates.py          # Document templates
  bibliography.py       # Citation formatting
  colors.py             # Color palettes + theming
  intelligence.py       # Content analysis + smart typography
  toc.py                # Table of contents generation
  pdfa.py               # PDF/A-2b conformance
  signing.py            # Digital signatures
  redaction.py          # Content redaction
  slides.py             # Slide/presentation layout
```

---

## Roadmap

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Core engine, typography, layout, tagging | Done |
| 2 | Unicode CIDFont, code highlighting, math, bibliography, charts | Done |
| 3 | Images, SVG, TOC, multi-column, templates | Done |
| 4 | PDF/A, redaction, digital signatures | Done |
| 5 | Cross-references, custom headers/footers, numbered lists | Done |
| 6 | Micro-typography, GPOS kerning, performance, CMYK | In progress |

---

## License

Apache-2.0. See [LICENSE](LICENSE) for the full text.
