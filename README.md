# Emboss

[![CI](https://github.com/GGChamp85/Emboss/actions/workflows/ci.yml/badge.svg)](https://github.com/GGChamp85/Emboss/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://pypi.org/project/emboss-pdf/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)

Turn structured or LLM-generated content into accessible, print-ready PDFs. Describe a document once, as a declarative spec or as Markdown, and Emboss handles typesetting, PDF/UA tagging, and the full PDF structure. Output is deterministic and byte-identical across runs, so every PDF is hash-verifiable and diffable in CI.

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

- [Built for Enterprise](#built-for-enterprise)
- [How Emboss Compares](#how-emboss-compares)
- [Why Emboss](#why-emboss)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [EmbossSpec Format](#embossspec-format)
- [Document Elements](#document-elements)
- [Style Presets](#style-presets)
- [BrandKit](#brandkit)
- [Typography Engine](#typography-engine)
- [Layout System](#layout-system)
- [Accessibility and Conformance (PDF/UA)](#accessibility-and-conformance-pdfua)
- [Self-Describing PDFs](#self-describing-pdfs)
- [Document Diff and Redline](#document-diff-and-redline)
- [Review Round-Trip](#review-round-trip)
- [Templates](#templates)
- [Executive Decks](#executive-decks)
- [Domain Features](#domain-features)
- [Cross-References and Numbering](#cross-references-and-numbering)
- [SVG Embedding](#svg-embedding)
- [Diagrams](#diagrams)
- [Multi-Column Layout](#multi-column-layout)
- [Math Notation](#math-notation)
- [Code Blocks](#code-blocks)
- [Charts](#charts)
- [PDF/A Archival Output](#pdfa-archival-output)
- [CMYK and Print Production](#cmyk-and-print-production)
- [Digital Signatures](#digital-signatures)
- [Incremental Amendment](#incremental-amendment)
- [Redaction](#redaction)
- [Validation](#validation)
- [Adapters](#adapters)
- [API Reference](#api-reference)
- [Performance](#performance)
- [Development](#development)
- [Architecture](#architecture)
- [Roadmap](#roadmap)
- [License](#license)

---

## Built for Enterprise

Emboss is built around guarantees that matter once a PDF leaves a notebook and enters a filing, an audit trail, or a distribution pipeline -- not marketing claims, but specific, checkable code paths.

- **Deterministic, hash-verifiable output.** The same `Document` always renders to the same bytes: no timestamps, no random identifiers, the file `/ID` derived from content. Two runs, two machines, one hash -- renders are byte-diffable in CI.
- **PDF/UA tagged by default, with real conformance evidence.** Every document ships a complete structure tree, and `emboss verify out.pdf --conformance 2b` (also `ua1`, `3b`) shells out to the actual veraPDF CLI and reports its verdict. This is not a simulated check: the CI conformance job installs the real veraPDF binary and runs the test suite against it on every push (`.github/workflows/ci.yml`).
- **Self-describing PDFs.** `doc.render(embed_spec=True)` embeds the document's own EmbossSpec JSON, its node-keyed layout map, and a reflowable Markdown twin as real `/AF` file attachments. `Document.from_pdf()` reconstructs an equivalent document from those attachments, and falls back to walking the PDF/UA structure tree -- recovering headings, paragraphs, tables, and lists in order -- if the attachments were stripped.
- **Stable node ids and a queryable layout map.** Every block gets a deterministic id and a page/bounding-box entry in `doc.layout_map()`: the foundation for auditing, redlining, and programmatic review of what landed where on the page.
- **Document diff and redline.** `diff_documents()` matches blocks between two documents by node id and classifies each as added, removed, or changed, with a word-level diff on text-bearing blocks; `render_redline()` turns that into a real PDF with struck-through deletions, underlined insertions, margin change-bars on added content, and a summary page. Also available as `emboss diff old.pdf new.pdf -o redline.pdf` from the command line.
- **A reproducibility manifest.** `doc.render(manifest=True)` attaches a deterministic `emboss-manifest.json`: the spec's sha256, the Emboss version, every embedded font's sha256, and any non-default render options. `emboss.reproduce()` (and `emboss reproduce report.pdf`) closes the loop: recover the document, re-render it, and structurally verify the two PDFs agree.
- **Redaction by construction.** `Document.redact(rules)` matches whole blocks by node id, regex, predicate, or type and removes or replaces them *before* layout, so redacted text never reaches a content stream -- not a black box painted over extractable text.
- **DocMDP certification signatures.** `sign_pdf(..., certify=True, docmdp_permission=...)` produces an ISO 32000-1 certification signature declaring what changes (if any) are permitted after signing.
- **BrandKit.** A single versioned brand object (palette, fonts, logo) applies across every document built from it, so a rebrand touches one object instead of every document.
- **CMYK and PDF/A archival output** for print production and long-term retention pipelines.
- **Long-form apparatus**: numbered appendices, an alphabetized back-of-book index with resolved page numbers, a glossary with auto-linked first occurrences, and a visible table of contents with real page numbers and dot leaders.
- **`emboss strip`** removes embedded files, provenance-revealing metadata, and internal structure-tree node ids from a rendered PDF before it goes to an external party.

---

## How Emboss Compares

Emboss is not a general-purpose drawing library or an HTML-to-PDF converter. It is built for the pipeline where structured or model-generated content becomes a trustworthy document, and the comparison is most honest at the level of tool categories rather than head-to-head with a specific product.

Every claim in the Emboss column below is verifiable against this repository and its test suite. The right column describes what general-purpose PDF tooling (imperative drawing libraries and HTML/CSS engines) *typically* does; it is a category statement, not a claim about any one product, and specifics for a given tool should be verified against that tool.

**Where Emboss is differentiated**

| Dimension | Emboss | Typical general-purpose PDF tools |
|---|---|---|
| Input a model can be constrained to | JSON schema, provider-native structured outputs, Markdown | Imperative code or HTML/CSS; no schema contract |
| Validation and repair of imperfect input | Built in (truncation repair, per-block recovery) | Not provided |
| Deterministic byte-identical output | Yes, test-verified | Generally not guaranteed |
| PDF/UA accessibility tagging | On by default | Opt-in or unavailable |
| Conformance evidence | Real veraPDF check in CI and `emboss verify` | Varies; rarely built in |
| Self-describing, recoverable document | `embed_spec` + `from_pdf` | No |
| Stable node ids and layout map | Yes | No |
| Document diff to a redlined PDF | Yes | No |
| Redaction that never enters the content stream | Yes | Typically overlay-based |

**Where established tools are ahead**

This side matters just as much. Stated plainly:

| Dimension | Emboss | Typical general-purpose PDF tools |
|---|---|---|
| Complex-script shaping (Arabic, Indic) | Not supported | Several engines support it |
| Arbitrary HTML and CSS input | Not supported | HTML/CSS engines accept it |
| Image formats | PNG and JPEG | Often broader |
| Production maturity | New, released 2026 | Many have 10 to 20 years in production |

For turning structured or LLM-generated content into accessible, verifiable, auditable PDFs, Emboss covers ground the general category does not. For arbitrary HTML rendering, complex-script typesetting, or a long track record in production, an established tool is the safer choice.

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

### Bundled Fonts

An OFL-licensed font set ships with the package (Source Serif 4, Source Sans 3, Source Code Pro; ~2.7MB, Latin, Greek, and Cyrillic coverage), plus Emboss Math, a modified subset of STIX Two Math carrying the mathematical alphanumeric glyphs used by `\mathbb`/`\mathcal`/`\mathfrak`. Registering the set gives embedded fonts with full kerning and ligatures, no system font files required:

```python
from emboss import Document
from emboss.bundled_fonts import register_bundled_fonts

doc = Document(title="Report")
register_bundled_fonts(doc.fonts)
```

The three text families are also available under the aliases `"emboss serif"`, `"emboss sans"`, and `"emboss mono"`. Two lower-level helpers, `bundled_font_path(family, bold=, italic=)` and `BUNDLED_FAMILIES`, are available for callers that want the file paths directly.

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

**Robust parsing.** LLM output is messy; the parser is built for it:

```python
doc = Document.from_json(
    text,
    strict=False,      # default: repair instead of raising
    smart=True,        # content intelligence: typography, tables, auto-style
    on_warning=print,  # one message per repair performed
)
```

- `spec_prompt()` teaches the exact vocabulary the validator accepts, so valid output is the common case
- Synonym type tags and field spellings are normalized to the canonical vocabulary on both parse paths
- Truncated JSON (cut off mid-generation) is repaired before parsing
- When validation fails, recovery is per block: invalid blocks are coerced to paragraphs or dropped, the rest of the document renders
- `strict=True` raises on any malformed input instead of repairing

Specs can also request layout features directly: `"toc": true` inserts an auto-generated table of contents, and `"page": {"columns": 2, "column_gap": 18}` sets multi-column geometry.

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
| `PageBreak` | Force a page break (optionally to a named `page_styles` geometry) | `page_style` |
| `BlockQuote` | Quoted passage set off with an accent bar | `content`, `attribution` |
| `CoverPage` | Full-page title composition, forces a page break | `title`, `subtitle`, `authors`, `date`, `kicker` |
| `Abstract` | Indented abstract block with a keywords line | `text`, `keywords` |
| `Authors` | Centered grid of author entries | `authors` (name, affiliation, email) |
| `PullQuote` | Large-type offset quotation | `text`, `attribution` |
| `StatTiles` | Row of bordered statistic tiles, colored deltas | `stats` (label, value, delta) |
| `TableOfContents` | Visible listing with dot leaders and page numbers | `title`, `depth`, `source` (headings/figures/tables) |
| `Appendix` | Lettered section (Appendix A, B, ...) with its own `A.1` numbering | `title`, `content` |
| `Index` | Back-of-book index resolved from `index_terms` marks | `title` |
| `Glossary` | Alphabetized term/definition list with auto-linked first occurrences | `entries`, `title` |
| Diagram | Node/edge graph with automatic layout, via `doc.diagram(...)` | `nodes`, `edges`, `direction`, `caption` |

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

Seven professionally designed stylesheets are built in. Each encodes type scale, leading, table rules, and spacing so output looks authored without choosing a single measurement.

| Preset | Body Font | Heading Font | Body Size | Alignment | Use Case |
|--------|-----------|-------------|-----------|-----------|----------|
| `legal` | Times | Times | 11.5pt | Justified | Contracts, briefs, pleadings |
| `finance` | Helvetica | Helvetica | 10pt | Left | Reports, filings, data sheets |
| `academic` | Times | Helvetica | 11.5pt | Justified | Papers, dissertations, theses |
| `corporate` | Helvetica | Helvetica | 10.5pt | Left | Memos, policies, manuals |
| `minimal` | Helvetica | Helvetica | 9.5pt | Left | Data exports, compact reports |
| `journal` | Times | Times | 10.5pt | Justified | Journals, periodicals |
| `brief` | Helvetica | Helvetica | 10.5pt | Left | Executive briefs, one-pagers |

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

## BrandKit

A `BrandKit` is an immutable, versioned brand object layered on top of any style preset at render time. Set it once on the document and colors, fonts, and footer text propagate everywhere, so a rebrand is a single-object change rather than a find-and-replace across every document.

```python
from emboss import Document, BrandKit

brand = BrandKit(
    name="Acme",
    version="2.1",
    primary="1f4e79",
    accent="1f8a70",
    ink="1a1a1a",
    muted="6b7280",
    heading_font="Emboss Serif",
    body_font="Emboss Sans",
    footer_text="Acme Corp -- Confidential",
)

doc = Document(title="Board Deck", style="corporate", brand=brand)
```

- Heading and table-header colors take the brand `primary`; body and secondary text take `ink`/`muted`. Any brand color that fails 4.5:1 contrast against white is automatically darkened for text use, while the raw brand color is kept for fills and rules.
- `brand.series_palette(n)` returns a deterministic N-color chart palette derived from `primary` and `accent` (or the explicit `palette` tuple, padded with derived colors if it runs short) -- charts under a brand stay on-brand without hand-picked colors.
- `brand.to_dict()` / `BrandKit.from_dict()` round-trip a brand kit through JSON (logo bytes travel as base64), for storing a brand centrally and loading it per render.

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
- Penalizes abrupt spacing changes and tight/loose lines
- Flags hyphen breaks and caps hyphen ladders: a large demerit stops runs of more than 3 consecutive hyphenated lines
- Splits any word wider than the measure into character-level pieces (long URLs, identifiers), so lines never overflow even in narrow columns
- Falls back to greedy breaking only for pathological input

### Knuth-Liang Hyphenation

The full Knuth-Liang en-US pattern set is bundled, plus a no-break list for domain terms (`Inc.`, `LLC`, `EBITDA`, `plaintiff`) that should never be split.

### Real Font Metrics

Glyph advances and kerning come from the font file (via fonttools). Text is emitted with the PDF `TJ` operator so kerning pairs are actually applied between glyphs. Kerning reads GPOS pair positioning in full: class-based (Format 2) pairs resolved lazily and memoized, Extension (LookupType 9) wrappers unwrapped, and Value2 adjustments summed.

Base-14 font metrics are built in, so valid PDFs are produced with no font files present. The built-in AFM widths cover more than ASCII: en/em dashes, curly quotes, and accented Latin letters resolve to correct advances (accents via NFD decomposition to the base letter). For embedded fonts out of the box, see [Bundled Fonts](#bundled-fonts).

### Smart Typography

Automatic curly quotes, em/en dashes, fractions, ellipses, and non-breaking spaces before units. Applied during text processing, not as a post-process.

### Ligature Support

Automatic fi, fl, ff, ffi, and ffl ligature substitution on embedded fonts, gated per glyph on the font's cmap. Base-14 fonts carry no ligature glyphs and are left untouched.

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

# A4 landscape, tuned for wide tables and diagrams
page = PageSpec.a4(landscape=True)
```

Also built in: `PageSpec.a5()` and the tight-margin `PageSpec.compact()` (A5, tuned for phone and tablet PDF readers).

### Per-Section Page Geometry

A document can switch page geometry mid-flow for one wide table or diagram, then switch back, via `page_styles` and `PageBreak.page_style`:

```python
doc = Document(
    title="Annual Report",
    page_styles={"wide": PageSpec.a4(landscape=True)},
)
doc.paragraph("Portrait content here.")
doc.page_break(page_style="wide")   # subsequent pages use the wide geometry
doc.table(headers=[...], rows=[...])
doc.page_break()                    # no page_style: reverts to the document default
```

### Pagination Features

- **Widow and orphan control**: prevents single lines stranded at page tops/bottoms
- **Keep-with-next**: headings stay with their following paragraph
- **Keep-together**: atomic blocks (callouts, small tables) never split across pages
- **Table splitting**: large tables break across pages with header row repetition
- **Column balancing**: multi-column layouts balance content across columns

---

## Accessibility and Conformance (PDF/UA)

Every document is tagged with a complete PDF/UA structure tree:

- Headings become `/H1` through `/H6`
- Paragraphs become `/P`
- Tables become `/Table` with `/TH` and `/TD` cells; header cells carry `/Scope`
- Lists become `/L` with `/LI`, `/Lbl`, and `/LBody`
- Images, SVG blocks, and charts get `/Figure` with the alt text emitted as `/Alt` (a description is auto-derived when none is given)
- Hyperlinks are written as `/Link` annotations and tagged as `/Link` structure elements with `OBJR` references, as PDF/UA requires
- Running heads, page numbers, Bates stamps, and watermarks are marked `/Artifact`
- Tagged documents declare the PDF/UA-1 identifier in their XMP metadata

```python
from emboss.pdf.verify import verify_pdf

result = verify_pdf(doc.render())
print(result)  # VerificationReport(ok=True, has_struct_tree=True, ...)
```

`verify_pdf` is a structural check on the bytes Emboss just wrote (well-formed xref, matching object offsets, a present structure tree). It is not a conformance check by itself.

### Real veraPDF Conformance

For actual ISO conformance, `emboss.pdf.verify.verify_conformance` (and the `emboss verify --conformance` CLI flag) invoke the real veraPDF CLI as a subprocess and parse its JSON report -- this is not a simulation, and it is not optional in CI: the `conformance` job in `.github/workflows/ci.yml` installs the official veraPDF binary and runs the test suite against it on every push and pull request.

```bash
emboss verify report.pdf --conformance 2b     # PDF/A-2b
emboss verify report.pdf --conformance ua1    # PDF/UA-1
emboss verify report.pdf --conformance 3b     # PDF/A-3b (with attachments)
```

```python
from emboss.pdf.verify import verify_conformance

report = verify_conformance(doc.render(), flavour="ua1")
print(report.compliant)    # bool
print(report.violations)   # list[RuleViolation]: clause, description, count
```

Requires the `verapdf` executable on `PATH`, or `VERAPDF_PATH` pointing at it; otherwise `verify_conformance` raises with an install hint rather than silently skipping the check.

---

## Self-Describing PDFs

A rendered PDF can carry enough of its own provenance to be reconstructed later, without a side channel or a database lookup.

```python
doc = Document(title="Q3 Report", style="finance")
doc.heading("Revenue", level=1)
doc.paragraph("Revenue increased 12% year over year.")

pdf_bytes = doc.render(embed_spec=True)
```

`embed_spec=True` attaches three real `/AF` (associated file) attachments to the PDF:

| Attachment | Contents | `/AFRelationship` |
|------------|----------|--------------------|
| `emboss-spec.json` | The canonical EmbossSpec JSON for exact reconstruction | `Source` |
| `emboss-layout.json` | The node id -> page/bounding-box layout map | `Supplement` |
| `emboss-textmap.json` | The node id -> per-character text-position index | `Supplement` |
| `emboss-doc.md` | A reflowable Markdown twin of the document | `Alternative` |

```python
from emboss import Document

recovered = Document.from_pdf("report.pdf")
```

`Document.from_pdf` tries the embedded `emboss-spec.json` first, an exact reconstruction. If it is missing (or `strict=True` is not set and no attachment was ever embedded), it falls back to a degraded reconstruction by walking the PDF/UA structure tree and pulling text out of the content streams by marked-content id: headings, paragraphs, tables, lists, block quotes, footnotes, and code blocks come back with correct text and order (and their original stable node ids), even when styling and exact spec fields are lost. Pass `strict=True` to require the exact path and raise instead.

```python
layout = doc.layout_map()
# {"n1a2b3c4": [{"page": 0, "x0": 72.0, "y0": 690.2, "x1": 540.0, "y1": 706.4}], ...}
```

Every top-level block gets a stable id -- an explicit one if you set it, otherwise a deterministic token derived from the element's type, position, and content, so the same document assigns the same ids on any machine and across runs. `doc.layout_map()` resolves every id to where it actually landed on the page, in PDF coordinates. Node ids and the layout map are the mechanism behind `from_pdf` recovery, the diff/redline tooling below, and any downstream annotation or programmatic-review workflow that needs to key off "this specific block, wherever it ends up."

Before a PDF leaves the building, `emboss strip` removes all of this:

```bash
emboss strip report.pdf -o external.pdf
```

```python
from emboss import strip_pdf

clean_bytes = strip_pdf(pdf_bytes)
```

`strip_pdf` operates on already-rendered bytes: it drops the `/AF` attachments and the `/Names /EmbeddedFiles` tree, clears `/Producer` and `/Creator` plus the XMP `CreatorTool`/document-history fields, and removes the structure tree's `/IDTree` and per-element `/ID` node ids -- while keeping Title, Author, and date fields. Output stays deterministic.

### Data-Carrying Tables and Charts

A single table or chart can carry its own source data inside the PDF, so the numbers a reader sees are one double-click away from the spreadsheet behind them. Set `attach_data=True`:

```python
doc.table(
    headers=["Quarter", "Bookings"],
    rows=[["Q1", "1,240"], ["Q2", "1,510"], ["Q3", "1,880"]],
    caption="Bookings by quarter",
    attach_data=True,   # embeds the table as an /AF CSV attachment
)
```

Emboss writes the table (or the chart's series) out as a CSV and embeds it as a real `/AF` associated-file attachment on that element -- not a separate side file. The visible page is unchanged; the data rides along inside the same PDF.

**How a reader opens the attachment.** Attachment support is a PDF-reader feature, not something the document controls, so the steps differ by reader:

| Reader | How to open the embedded data |
|--------|-------------------------------|
| Adobe Acrobat / Reader | **View -> Show/Hide -> Side panels -> Attachments**, then double-click the CSV |
| Firefox (built-in viewer) | Click the **paperclip** icon in the left toolbar, then the file |
| Preview (macOS), Chrome | No attachment UI -- these readers do not surface `/AF` files; use Acrobat or Firefox, or extract programmatically (below) |

Any embedded file can also be pulled out without a viewer, straight from the bytes:

```python
import io, pikepdf

with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
    csv = pdf.attachments["table-1-data.csv"].get_file().read_bytes()
```

### Reproducibility Manifest

Beyond recovering a document's content, `manifest=True` records what it takes to reproduce its exact rendered bytes:

```python
pdf_bytes = doc.render(manifest=True)   # attaches emboss-manifest.json
```

The manifest is a deterministic JSON summary: the spec's sha256, the running Emboss version, every embedded font's sha256, and any render options that differ from their defaults (`pdfa`, `color_mode`, `tagged`, `toc`, `page_number_format`, `page_numbers`, `front_matter_pages`). `doc.reproducibility_manifest(...)` builds the same dict without rendering.

```bash
emboss reproduce report.pdf
```

```python
from emboss import reproduce

report = reproduce("report.pdf")   # recover -> re-render -> structurally compare
print(report.ok)                   # bool
```

`reproduce()` recovers the document from the PDF (via the embedded spec, or the degraded structure-tree path), re-renders it, and reports whether the two PDFs agree structurally -- same page count and same visible text per page, not a byte-for-byte match (attaching a manifest to the reproduction would itself shift bytes across the attachment boundary). A way to catch drift between what a PDF claims to be and what actually generated it.

### Node-Scoped Patching

`doc.patch(node_id, **changes)` returns a new `Document` with the one block carrying `node_id` replaced (`dataclasses.replace(block, **changes)` under the hood) -- everything else, and the original document, untouched. Useful when a caller (an LLM given one block's id and a small diff, or an editing UI) only needs to change a single block without regenerating the whole spec.

---

## Document Diff and Redline

`diff_documents` matches blocks between two documents by their stable node id (assigning ids first if either side lacks them), and classifies each as added, removed, changed, or unchanged. A matched pair counts as "changed" only when both sides already carry the same id for that block -- typically because the id was assigned once (an explicit `id=`, a prior render) and the block was edited in place rather than replaced.

```python
from emboss import diff_documents, render_redline

result = diff_documents(old_doc, new_doc)
print(len(result.added), len(result.removed), len(result.changed))

redline_bytes = render_redline(old_doc, new_doc, result)
```

`render_redline` renders the new document through the normal measure/paginate/render pipeline with revision marks baked in, not overlaid: deleted words struck through in crimson, inserted words underlined in forest green, added blocks marked with a real measured change-bar in the left margin, and a prepended summary page listing what was removed. Changed headings and pull quotes keep their new text with a redlined note paragraph underneath, since they carry no per-run styling to inline a word diff into.

```bash
emboss diff old.pdf new.pdf -o redline.pdf
```

---

## Review Round-Trip

A reviewer highlights, strikes out, or comments on a rendered PDF in whatever they already use -- Acrobat, Preview, Chrome. Because an Emboss PDF carries a text-position index, each annotation resolves back to the exact node and character range it covers, not a guess at a rectangle. This is the piece other PDFs cannot do: they have no structure to resolve a comment against.

Render with `embed_spec=True` so the text map (`emboss-textmap.json`) is present, then read the markup back:

```python
from emboss.annotations import extract_comments, merge_comments

doc.save("v1.pdf", embed_spec=True)   # reviewers mark this up in their reader

comments = extract_comments("v1-legal.pdf")
comments = merge_comments(
    extract_comments("v1-legal.pdf"), extract_comments("v1-finance.pdf")
)
```

Each comment carries the reviewer, page, type, their text, and a resolution keyed to a stable node id and character range:

```python
{"id": "c-07", "type": "strikeout", "author": "R. Patel", "page": 4,
 "node_id": "sec-risk.p3", "anchor_text": "exposure exceeds $4.2M",
 "char_range": [120, 143], "comment": "Overstates it, use the netted figure",
 "resolution": "exact", "status": "open"}
```

The `resolution` is never omitted, so a mis-resolved comment cannot pass silently:

| State | Meaning | Behaviour |
|-------|---------|-----------|
| `exact` | One node and a character range | Patchable, phrase-level |
| `node` | One node, no character range | Patchable, whole-node |
| `spanning` | Crosses two or more nodes | Reports every node id; never split silently |
| `unanchored` | No content beneath the annotation | Surfaced with page and rect; never dropped |

Comments are never auto-applied -- that would ship a document nobody approved. Turning a free-text comment into a concrete replacement is a separate step (often a model); Emboss applies it deterministically and proves the change:

```python
from emboss.review import propose_patches, apply_replacements, redline

propose_patches(doc, comments, replacements={})          # what would change
new_doc = apply_replacements(doc, comments, {"c-07": "the netted $2.8M"})
redline_pdf = redline(doc, new_doc)                       # proves the change
```

For an `exact` resolution over plain text, only the objected-to phrase is spliced; everything else stays byte-identical. `review_html(comments)` renders a self-contained triage report with the unresolved count loud at the top.

```bash
emboss render spec.json -o v1.pdf --embed-spec       # embeds spec, layout, text map
emboss review v1-legal.pdf v1-finance.pdf -o comments.json
emboss review v1-legal.pdf --html review.html        # triage view, no server
emboss apply comments.json --spec spec.json                       # propose only
emboss apply comments.json --spec spec.json --edits edits.json \
    -o v2.pdf --redline redline.pdf                               # apply and prove
```

`emboss review` exits non-zero when any comment is unresolved, so a pipeline can gate on it. Flattened annotations (Preview's flattened export) are burned into the page and cannot be recovered by anything; a stripped PDF (no text map) resolves at page-and-rect granularity only, never a wrong guess.

---

## MCP Server

Make Emboss documents callable from an AI assistant that speaks the [Model Context Protocol](https://modelcontextprotocol.io), such as Claude Desktop. Configure it once, and the assistant can generate PDFs and answer questions about them **from their embedded structure, not from guessing at rendered pixels** -- because an Emboss PDF made with `embed_spec=True` carries its own EmbossSpec JSON, a per-character text index, and any CSV data attached to its tables.

```bash
pip install "emboss-pdf[mcp]"
```

```json
{
  "mcpServers": {
    "emboss": { "command": "emboss-mcp" }
  }
}
```

The server (built on the standard FastMCP API, served over stdio) exposes tools for the novel capabilities: `render_document`, `get_document_spec` and `get_document_text` (exact answers from the embedded JSON), `list_embedded_data` / `extract_embedded_data` (pull a table's source CSV back out), `extract_review_comments` (annotations resolved to nodes), `revision_history` (traceability), plus `verify_document` and `get_spec_schema`. Every query tool takes a file path, so one server answers questions about every PDF you generate. See the [MCP Server guide](https://ggchamp85.github.io/Emboss/mcp) for the step-by-step Claude Desktop setup.

The tools are plain, tested functions (`emboss.mcp_server.dispatch`), callable from your own code without an MCP client.

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

## Executive Decks

`SlideDeck` builds a presentation deck from designed slide layouts, complete color themes, and a fit-to-slide guarantee: no slide ever spills onto a continuation page.

```python
from emboss.slides import SlideDeck

deck = SlideDeck("Q3 Board Review", presenter="Ana Ruiz", date="Oct 2026", theme="boardroom")
deck.title_slide(subtitle="Board update")
deck.section_divider("Results")
deck.stat_slide("Key metrics", [("ARR", "$12.4M", "+18%"), ("Churn", "2.1%", "-0.3%")])
deck.bullet_slide("Highlights", ["Enterprise ARR up 22%", "Net retention at 118%"])
deck.chart_slide("Growth", chart_element)
deck.quote_slide("The window for category leadership is now.", attribution="CEO")
deck.closing_slide("Thank you", contact="ana@acme.com")
deck.save("board_deck.pdf")
```

- **Layouts**: `title_slide`, `section_divider`, `content_slide` (single or `layout="two-column"`), `bullet_slide`, `stat_slide`, `chart_slide`, `quote_slide`, `code_slide`, `closing_slide`.
- **Four built-in themes**, each a complete, WCAG-contrast-checked color system: `boardroom` (navy and gold), `horizon` (dusk blue and coral), `carbon` (near-black and electric blue), `meadow` (forest and spring green). Aliases `default`, `dark`, `light`, `minimal` resolve to one of the four.
- **Fit-to-slide**: every slide is measured after composition; if it would overflow, type and spacing scale down in steps (to a floor of 0.8x) until it fits one slide, or a clear error names which slide and by how much it overflowed rather than silently clipping content.
- Charts dropped into a themed deck automatically pick up the theme's chart palette unless colors are set explicitly.
- `deck.build()` returns the underlying `Document` for further customization before `.render()`/`.save()`.

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

### Factur-X / ZUGFeRD e-invoicing

A visual invoice PDF can carry a machine-readable EN 16931 Cross Industry Invoice XML inside it, for the France B2B mandate (September 2026) and EU electronic invoicing. `Document.attach_facturx` embeds the XML as a `factur-x.xml` `/AF` attachment, forces PDF/A-3, and writes the ZUGFeRD/Factur-X XMP metadata.

```python
from emboss import Document, Invoice, Party, InvoiceLine

invoice = Invoice(
    invoice_number="INV-2026-001",
    issue_date="20260115",
    currency="EUR",
    seller=Party(name="Acme GmbH", country_code="DE", vat_id="DE123456789"),
    buyer=Party(name="Beispiel SA", country_code="FR"),
    lines=[
        InvoiceLine(name="Consulting", quantity="10", unit_price="150.00",
                    net_amount="1500.00", tax_rate_percent="19"),
    ],
)

doc = Document(title="Invoice INV-2026-001", style="finance")
# ... render the human-readable invoice with tables/stat tiles ...
doc.attach_facturx(invoice)          # embeds factur-x.xml, forces PDF/A-3
doc.save("invoice.pdf")
```

`Invoice.validate()` (called before any XML is produced) reconciles the line net amounts, the per-rate tax, and the grand total, so an invoice whose numbers do not add up raises rather than emitting a non-conformant document. The default profile is EN 16931 (COMFORT); MINIMUM, BASIC, and EXTENDED select the guideline URN. `build_cii_xml(invoice)` returns the XML directly if you want to inspect or transmit it on its own.

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

The `@label` syntax resolves to "Table 1", "Figure 2", etc., with automatic counter tracking via `NumberingContext`. Captions are numbered automatically ("Figure 1: ...", "Table 1: ..."), and each `@label` reference becomes a clickable in-document link (a GoTo action targeting the labeled element's page).

Section numbering is available by setting `number_sections = True` on the document; headings are numbered hierarchically and `@label` references to sections resolve to the section number.

---

## SVG Embedding

Embed SVG vector graphics as native PDF paths, no rasterization:

```python
doc.svg("""
<svg width="200" height="100">
  <rect x="10" y="10" width="80" height="80" fill="#2563eb"/>
  <circle cx="150" cy="50" r="40" fill="#dc2626"/>
</svg>
""", width=200, height=100)
```

A substantial subset of static SVG is supported, using only the standard library:

- **Shapes**: `rect`, `circle`, `ellipse`, `line`, `polygon`, `polyline`.
- **Full path data**: `path` supports `M/L/H/V/C/S/Q/T/A/Z`, including relative lowercase forms and implicit command repetition -- elliptical arcs (`A`) are converted to cubic Bezier segments.
- **Transforms**: `translate`, `scale`, `rotate` (with an optional pivot), `skewX`, `skewY`, and `matrix`, composed correctly through nested `<g>` groups.
- **Gradients**: `linearGradient` and `radialGradient`, including `href` stop inheritance, rendered as banded fills; `gradient_shading` builds the equivalent true PDF type 2/3 `/Shading` dictionary for callers wiring page resources directly.
- **Clipping**: `clipPath` compiles to a real PDF clip (`W n`).
- **Opacity**: element and group `opacity`/`fill-opacity`/`stroke-opacity` emit real `ExtGState` (`gs`) operators, not simulated transparency.
- **Text**: `<text>` with `text-anchor`, using base-14 metrics mapped from the requested `font-family`.
- **`<use>`/`<defs>`**: reference-based reuse with a bounded reference depth to guard against cycles.
- Excluded by design: filters, animation, masks, patterns, and CSS beyond the `style` attribute.

---

## Diagrams

Node/edge graphs (architecture diagrams, flowcharts, state machines) with automatic layout: no coordinates to compute by hand.

```python
doc.diagram(
    nodes=[
        {"id": "api", "label": "API Gateway"},
        {"id": "auth", "label": "Auth Service"},
        {"id": "db", "label": "User Store", "shape": "store"},
        {"id": "ok", "label": "Response", "shape": "rounded"},
    ],
    edges=[
        {"src": "api", "dst": "auth", "label": "verify"},
        {"src": "auth", "dst": "db"},
        {"src": "db", "dst": "auth", "style": "dashed"},
        {"src": "auth", "dst": "ok"},
    ],
    caption="Login flow",
)
```

- **Layout is automatic**: a longest-path layering assigns nodes to layers, barycenter sweeps order nodes within each layer to reduce edge crossings, and cycles are handled by reversing back edges for layout purposes while rendering them along their true direction.
- **Node shapes**: `box`, `rounded`, `decision` (diamond), `store` (database cylinder), `start_end` (pill).
- **Edges**: solid or `style="dashed"`, with optional labels; self-loops render as a small loop back into the node.
- Renders as native vector graphics (an `SvgBlock` under the hood), with a deterministic, auto-generated `/Alt` description summarizing the node and edge count -- no diagram ships without accessible alt text.
- Also available as a fenced Markdown block: a ` ```diagram ` fence with `id: Label [shape]` node lines, `a -> b: label` (or `-->` for dashed) edge lines, and an optional `direction: right` line.
- Lower-level API: `emboss.diagrams.layout_diagram`, `render_diagram_svg`, `diagram_alt_text`, and the `DiagramNode`/`DiagramEdge` dataclasses.

### Specialized diagram types

Beyond the general flowchart, three purpose-built diagram types cover most technical-documentation needs. Each is described as a plain node/edge list, laid out automatically, and rendered as native vector graphics with auto-generated `/Alt` text.

**Cloud / deployment architecture** -- `doc.architecture_diagram(nodes, edges, groups=...)`. Nodes carry a `service` glyph (`compute`, `database`, `storage`, `queue`, `gateway`, `cache`, `cdn`, `function`, `loadbalancer`, `user`, `external`, `generic`) and an optional `group`; groups nest to draw zones such as a VPC wrapping public and private subnets. Edges are solid or `dashed` with labels. Relabel the nodes and the same layout describes an AWS, Azure, or GCP topology.

```python
doc.architecture_diagram(
    nodes=[
        {"id": "alb", "label": "ALB", "service": "loadbalancer", "group": "public"},
        {"id": "ec2", "label": "EC2 - App", "service": "compute", "group": "private"},
        {"id": "rds", "label": "RDS", "service": "database", "group": "private"},
    ],
    edges=[("alb", "ec2"), ("ec2", "rds", "SQL")],
    groups=[
        {"id": "public", "label": "Public Subnet", "node_ids": ["alb"]},
        {"id": "private", "label": "Private Subnet", "node_ids": ["ec2", "rds"]},
        {"id": "vpc", "label": "VPC", "node_ids": ["public", "private"]},
    ],
    caption="AWS three-tier architecture",
)
```

**Sequence** -- `doc.sequence_diagram(participants, messages)`. Draws one lifeline per participant; messages carry a `style` of `sync` (solid, filled arrowhead), `async` (open arrowhead), or `return` (dashed), and `activate=True` opens an activation bar on the receiver. Self-messages render as a loop.

```python
doc.sequence_diagram(
    participants=[{"id": "u", "label": "Client"}, {"id": "api", "label": "API"}],
    messages=[
        {"from": "u", "to": "api", "label": "POST /settle", "style": "sync",
         "activate": True},
        {"from": "api", "to": "u", "label": "202 Accepted", "style": "return"},
    ],
)
```

**Entity-relationship** -- `doc.er_diagram(entities, relationships)`. Each entity lists typed attributes with a `key` of `PK`/`FK`; each relationship carries a label and `from_card`/`to_card` cardinality (`1`, `N`, ...).

```python
doc.er_diagram(
    entities=[
        {"id": "account", "name": "Account", "attributes": [
            {"name": "id", "key": "PK", "type": "uuid"},
        ]},
        {"id": "payment", "name": "Payment", "attributes": [
            {"name": "account_id", "key": "FK", "type": "uuid"},
        ]},
    ],
    relationships=[
        {"from": "account", "to": "payment", "label": "makes",
         "from_card": "1", "to_card": "N"},
    ],
)
```

All three are exposed in the Pydantic schema and the LLM spec prompt, so a model can emit them directly as `architecture_diagram` / `sequence_diagram` / `er_diagram` spec blocks.

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
doc.math(r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}")
doc.math(r"f(x) = \begin{cases} x^2 & x \ge 0 \\ -x & x < 0 \end{cases}")
```

Supported: superscripts, subscripts, fractions (`\frac`), square roots (`\sqrt`), integrals, summations, Greek letters, `\text{}`, `\mathcal`, `\mathbb`, `\mathbf`, `\mathrm`, `\operatorname`, and more.

### Environments

`\begin{...}` with `&` column separators and `\\` row breaks:

- Matrices: `matrix`, `pmatrix`, `bmatrix`, `vmatrix`, `Bmatrix`
- Piecewise: `cases`
- Aligned equations: `aligned`, `align`, `align*`, `split`
- Gathered equations: `gathered`, `gather`, `gather*`

### Real Math Alphabets

`\mathbb`, `\mathcal`/`\mathscr`, and `\mathfrak` render actual double-struck, script, and fraktur glyphs (Unicode Mathematical Alphanumeric Symbols, with the letterlike-symbol exceptions like `\mathbb{R}` and `\mathcal{H}` mapped to their reserved codepoints) from the bundled Emboss Math font, not a font-substitution approximation:

```python
doc.math(r"\mathbb{R}^n \to \mathcal{H}")
```

### MathML Input

Presentation MathML is accepted alongside LaTeX. `parse_math` (and `MathBlock`/`doc.math`) auto-detects a source starting with `<math` and routes it through `emboss.mathml.parse_mathml` into the same AST the LaTeX parser produces, so layout and rendering are shared:

```python
doc.math('<math><mfrac><mi>a</mi><mi>b</mi></mfrac></math>')
```

Supported elements: `mi`/`mn`/`mo` tokens, `mrow`, `mfrac`, `msqrt`/`mroot`, `msup`/`msub`/`msubsup`, `munder`/`mover`/`munderover` (mapped onto the display-limit machinery), `mtable`/`mtr`/`mtd`, `mfenced`, `mtext`, `mspace`, `mstyle`, and `semantics` (annotations ignored). HTML5/MathML named entities are expanded and namespaces stripped, using only the standard library; malformed input raises `ValueError` rather than rendering garbage.

### Layout Quality

Layout comes from real metrics, not approximations: glyph dimensions use the base-14 AFM tables (Times italic for variables, Times roman for text, Symbol for operators), inter-atom spacing follows the TeX spacing classes (thin, medium, thick), and in display mode `\sum`, `\prod`, `\int`, and `\lim` place their limits above and below the operator.

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

## CMYK and Print Production

Set `color_mode="cmyk"` and every draw path (text, rules, tables, charts, shapes) emits CMYK operators (`k`/`K`) instead of RGB:

```python
from emboss import Document, Paragraph, TextRun

doc = Document(
    title="Print Run",
    color_mode="cmyk",
    pdfa=True,   # output intent switches to a CMYK profile (N=4)
)
doc.paragraph([TextRun(text="Brand red", color="cmyk(0,100,95,0)")])
doc.paragraph([TextRun(text="Spot ink", color="spot(PANTONE 485 C,0,100,95,0)")])
doc.save("print_run.pdf")
```

- `cmyk(c,m,y,k)` color strings work anywhere a color is accepted; RGB colors are converted when the document is in CMYK mode
- `spot(name,c,m,y,k)` defines a named spot color, emitted as a PDF Separation color space with a CMYK fallback
- PDF/A output in CMYK mode uses a CMYK OutputIntent instead of sRGB
- Redaction and signature appearances follow the document's color mode

---

## Digital Signatures

Sign PDFs with X.509 certificates. A visual signature field is placed at render time; the PKCS#7 signature is injected afterward:

```python
from emboss import Document, SignatureField
from emboss.signing import sign_pdf

doc = Document(
    title="Approval",
    signatures=[
        SignatureField(
            page_index=0, x=360, y=60, signer_name="Jane Doe",
            reason="Approved", location="San Francisco",
        )
    ],
)
pdf_bytes = doc.render()

signed_bytes = sign_pdf(pdf_bytes, "signer-key.pem", "signer.pem")
```

Requires `pip install emboss-pdf[signing]`.

### DocMDP Certification Signatures

`sign_pdf(..., certify=True, docmdp_permission=2)` produces an ISO 32000-1 12.8.2.3 certification signature: the /DocMDP entry it asserts states what changes (if any) are permitted after signing (`1` forbids any further changes, `2` -- the default -- permits form fill-in and further signing, `3` additionally permits annotations). A certifying signature must be the document's first signature field; `build_docmdp_reference`, `build_certifying_signature`, and `build_perms_dict` (in `emboss.signing`) build the underlying /Reference, signature field, and catalog /Perms entries for callers assembling the PDF at a lower level than `Document.render`.

---

## Incremental Amendment

Keep the distinction sharp: **content edits go through the spec (`render`, a new file); attestations append.** Signatures, approvals, and annotations are added by appending an incremental revision that never rewrites the bytes already in the file. The original bytes stay a byte-exact prefix of the result, which is exactly what lets a signature's `/ByteRange` attest to everything written before it.

```python
from emboss import amend_sign, revision_history, format_history

signed = amend_sign(pdf_bytes, cert="legal.pem", key="legal.key",
                    reason="Approved: Legal", name="R. Patel")
signed = amend_sign(signed, cert="finance.pem", key="finance.key",
                    reason="Approved: Finance", name="M. Osei")

print(format_history(signed))
```

```
Rev  Kind        Bytes             Signer        Coverage
--------------------------------------------------------------
  0  base        0-6582                          covers by rev 1,2
  1  signature   6582-24003        R. Patel      signed
  2  signature   24003-41560       M. Osei       signed
```

The headline check is coverage: a revision appended *after* a signature that no signature's `/ByteRange` covers is detected and reported. That is the audit question -- what was added that nobody signed -- and it falls out of the `/Prev` chain for free.

```bash
emboss amend contract.pdf --sign --cert legal.pem --key legal.key --reason "Approved: Legal"
emboss history contract.pdf
emboss verify contract.pdf --revisions      # exits non-zero on uncovered appended content
```

`amend_pdf` handles non-signature attestations (a placed annotation, an added attachment) the same append-only way. DocMDP is enforced: if the base certifies with `/P=1` (no changes) or `/P=2` (signatures only), an amendment that exceeds the permitted scope raises rather than producing an illegal file. Amended files are valid but no longer linearized, since the appended revision sits after the original `%%EOF` -- inherent to incremental updates, and the price of never rewriting prior bytes.

> **Determinism, restated for signing.** Each revision is byte-identical to what it was when created. Amendments append; they never rewrite. The document remains reproducible from its embedded spec at any revision. This is stronger than a blanket "byte-identical output" claim, because it survives signing.

---

## Redaction

Two redaction models are available, and they are not equally honest. **Construction-time redaction** (`Document.redact`) is the one to use for anything that actually matters: it matches whole content blocks -- by stable node id, a regex or predicate over the block's plain text, or element type -- and removes or replaces them *before* layout or rendering, so the real text never reaches a content stream.

```python
from emboss import Callout, RedactionRule

rules = [
    RedactionRule(name="ssn", pattern=r"\d{3}-\d{2}-\d{4}"),
    RedactionRule(name="internal-notes", element_type=Callout, mode="remove"),
]
redacted_doc = doc.redact(rules)
pdf_bytes = redacted_doc.render()

redacted_doc.redaction_log   # what was removed, by which rule, before removal -- an audit trail, never auto-attached to output
```

`mode="placeholder"` (the default) replaces a matched block with same-length filler text so the layout doesn't visibly reflow, then covers the filler's own rendered footprint with an opaque box -- the box conceals filler, never the original content. `mode="remove"` drops the block outright. Placeholder mode covers the common text-bearing block types (`Heading`, `Paragraph`, `BlockQuote`, `Callout`, `Footnote`, `PullQuote`, `BulletList`, `NumberedList`, `Table`, `CodeBlock`); match other element types with `mode="remove"`.

The older `RedactionMark`/`Document.redactions` mechanism draws opaque rectangles directly onto an already-rendered page and is kept for callers masking content that never went through a `Document` at all (it is also what the [diff/redline](#document-diff-and-redline) change-bars use) -- the underlying text is still in the content stream underneath the box, so it is not a substitute for construction-time redaction of real secret text.

For payloads that need to travel with the PDF but stay opaque to anyone without a password, `Document.attach_encrypted(name, data, password)` queues an AES-256-GCM-encrypted `/AF` attachment (`relationship="EncryptedPayload"`), decrypted later with `emboss.decrypt_attachment`.

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
from emboss.adapters.docx_export import to_office_dict

html_str = to_html(doc)
md_str = to_markdown(doc)
office_data = to_office_dict(doc)
```

### Pydantic Schema (LLM Integration)

```python
from emboss.adapters.pydantic_schema import DocumentSpec, generate_json_schema

# Get the JSON Schema for LLM structured output
schema = generate_json_schema()

# Parse an LLM-generated JSON document
doc = DocumentSpec.model_validate_json(json_string).to_document()
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
    brand=None,            # BrandKit layered on top of `style`
    page=PageSpec(),       # Page dimensions and margins
    page_styles={},        # Name -> PageSpec, switched via PageBreak.page_style
    content=[],            # List of block elements
    header=None,           # HeaderFooter for page headers
    footer=None,           # HeaderFooter for page footers
    page_numbers=True,     # Show page numbers
    tagged=True,           # Generate PDF/UA structure tree
    legal=None,            # LegalFeatures (Bates, line numbers, watermark)
    pdfa=False,            # Generate PDF/A-2b (or -3b with embed_spec) output
    toc=False,             # Generate table of contents
    color_mode="rgb",      # "rgb" or "cmyk" (print production)
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
doc.diagram(nodes, edges=(), direction="down", caption=None)
doc.code_block(code, language="text")
doc.math(source)
doc.footnote(content)
doc.callout(content, variant="note")
doc.svg(source)
doc.rule()
doc.page_break(page_style=None)
doc.cover(title); doc.abstract(text); doc.authors(authors); doc.pull_quote(text)
doc.stat_tiles(stats); doc.table_of_contents(); doc.appendix(title, *blocks)
doc.index(); doc.glossary(entries)
doc.render(linearize=False, embed_spec=False) -> bytes
doc.save(path, linearize=False, embed_spec=False)
doc.layout_map() -> dict

Document.from_pdf(source, strict=False)   # recover a Document from a rendered PDF
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
    numbers.py          # Deterministic display number formatting
  pdf/
    assembler.py        # Low-level PDF object writer
    fonts.py            # Font resource building + subsetting
    objects.py          # PDF object types (Dict, Array, Stream)
    streams.py          # Content stream operators (text, shapes)
    tags.py             # PDF/UA structure tree builder
    verify.py           # Structural verification + real veraPDF conformance
    attachments.py      # /AF embedded-file attachments (PDF/A-3)
  adapters/
    html_export.py      # HTML export
    markdown_export.py  # Markdown export
    docx_export.py      # DOCX export
    pydantic_schema.py  # JSON Schema / Pydantic models for LLM
  math_render.py        # LaTeX math parser + renderer, math alphabets
  mathml.py             # Presentation MathML parser
  code_highlight.py     # Syntax highlighting
  charts.py             # Chart rendering
  chart_facts.py        # Chart fact extraction + caption verification
  images.py             # Image handling
  svg.py                # SVG parser + renderer (paths, gradients, clipping)
  diagrams.py           # Node/edge diagram layout + SVG rendering
  crossref.py           # Cross-reference resolution
  numbering.py          # Figure/table auto-numbering
  templates.py          # Document templates
  bibliography.py       # Citation formatting
  colors.py             # Color palettes + theming
  brandkit.py           # Versioned brand object
  bundled_fonts.py      # Bundled OFL font set + registration
  intelligence.py       # Content analysis + smart typography
  toc.py                # Table of contents generation
  pdfa.py               # PDF/A-2b/A-3b conformance
  signing.py            # Digital signatures
  redaction.py          # Content redaction
  slides.py             # SlideDeck + slide/presentation layout
  nodeid.py             # Stable node ids + layout map
  recovery.py           # Spec embedding, from_pdf recovery, strip_pdf
  manifest.py           # Reproducibility manifest + reproduce()
  diff.py               # Node-keyed document diff + redline rendering
  generate.py           # LLM prompt, structured generation, spec parsing
  markdown.py           # Markdown -> EmbossSpec parser
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
| 6 | Micro-typography, GPOS kerning, performance, CMYK | Done |
| 7 | BrandKit, SlideDeck, diagrams, MathML, real veraPDF conformance, self-describing PDFs (`embed_spec`/`from_pdf`/`strip`), document diff and redline, reproducibility manifest, construction-time redaction, DocMDP certification signatures, encrypted attachments, node-scoped patching | Done |

---

## License

Apache-2.0. See [LICENSE](LICENSE) for the full text.
