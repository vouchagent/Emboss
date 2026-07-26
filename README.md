# PrecisionPDF

Constraint-driven PDF generation for Python. You describe a document; the
engine handles typography, layout, and the PDF/UA structure tree.

```python
from precisionpdf import Document

doc = Document(title="Q3 Report", style="finance")
doc.heading("Revenue Analysis", level=1)
doc.paragraph("Revenue increased 12% year over year.")
doc.table(headers=["Region", "Q3"], rows=[["North America", "$2.4M"]])
doc.save("report.pdf")
```

No coordinates. No manual page-break handling. No separate accessibility
pass.

## Status

**Phase 1, alpha.** The core engine works end to end and is tested, but
several things in the roadmap are not built yet. Read
[Known limitations](#known-limitations) before adopting.

## Why this exists

Existing Python PDF libraries are page-description tools: you place ink at
coordinates, and the resulting file has no idea that a given string was a
heading. Accessibility tags, if available at all, are painted on afterwards
and tend to disagree with the visible page.

PrecisionPDF inverts that. The semantic document is the source of truth,
and both the visual output and the structure tree are derived from it. They
cannot drift apart, because they come from the same description.

## What it guarantees

**Deterministic output.** The same document produces byte-identical PDFs
across runs and machines. No timestamps, no random identifiers; the file
`/ID` is derived from content. This is what makes output hash-verifiable
for filings and diffable in CI.

```python
assert doc.render() == doc.render()   # always true
```

**Structural correctness.** Cross-reference offsets are recorded as bytes
are written, so the xref table cannot disagree with the file. A verifier
parses the output and checks it:

```python
from precisionpdf.pdf.verify import verify_pdf
print(verify_pdf(doc.render()))
```

**Content never overflows.** Everything is measured before anything is
placed, so text running off the page is not a failure mode.

**Tagged by default.** Headings become `/H1`–`/H6`, paragraphs `/P`, tables
`/Table` with `/TH` cells carrying `/Scope`. Running heads, page numbers,
Bates stamps, and watermarks are marked `/Artifact` so assistive technology
skips them.

## Typography

**Knuth-Plass line breaking.** Optimises the paragraph as a whole rather
than filling each line greedily, which produces noticeably more even
spacing in justified text:

```
greedy   widths: [216, 172, 168, 162, 176]   variance 367
optimal  widths: [216, 224, 202, 198]        variance 110
```

**Knuth-Liang hyphenation**, with a no-break list so legal and financial
abbreviations (`Inc.`, `LLC`, `EBITDA`, `plaintiff`) are never split.

**Real font metrics.** Glyph advances and kerning come from the font, and
text is emitted with the `TJ` operator so kerning is actually applied.

**Design presets.** Five stylesheets (`legal`, `finance`, `academic`,
`corporate`, `minimal`) encode type scale, leading, and table rules, so
output looks authored without choosing a single measurement yourself.

## Layout

Widow and orphan control, keep-with-next for headings, keep-together for
atomic blocks, and multi-page tables that repeat their header row. Column
widths are solved from actual content metrics, with decimal alignment for
numeric columns so `$1,234,567.89` and `$12.34` line up.

## Domain features

Bates numbering, continuous line numbering for court pleadings, and
watermarks — as first-class configuration rather than manual drawing:

```python
from precisionpdf import Document, LegalFeatures, PageSpec

doc = Document(
    title="Memorandum",
    style="legal",
    page=PageSpec.letter(margin_left=108),
    legal=LegalFeatures(
        watermark="CONFIDENTIAL",
        line_numbering=True,
        bates_prefix="ACME-",
    ),
)
```

## Validation

Problems are caught against the specification before rendering starts.
Repairable issues are fixed on a copy; genuine errors are reported.

```python
from precisionpdf.constraints import ConstraintValidator

result = ConstraintValidator().validate(doc)
for issue in result.issues:
    print(issue)   # fixed/mathematical: column widths rescaled ...
```

## Installation

```bash
pip install precision-pdf
```

Requires Python 3.10+ and `fonttools`. `pikepdf` is optional and used only
by the test suite.

## Known limitations

Being explicit, because these matter for adoption decisions:

- **Not yet validated against veraPDF.** The structure tree is built to
  spec and verified structurally, but PDF/UA conformance is not yet
  gated in CI. Do not rely on it for compliance until it is.
- **No OpenType shaping.** Ligatures and GPOS kerning are not applied;
  only the legacy `kern` table is read. Complex scripts (Arabic,
  Devanagari) and CJK line-breaking rules are unsupported.
- **WinAnsi encoding only.** Codepoints outside it will not render
  correctly.
- **No images or charts** (roadmap Phase 5).
- **No PDF/A archival output** (roadmap Phase 4).
- **Performance is untuned.** Layout is pure Python; large documents will
  be slower than a compiled engine.

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | Core engine, typography, layout, tagging | done |
| 2 | veraPDF gating, OpenType shaping, Unicode | next |
| 3 | Images, charts, TOC, multi-column | planned |
| 4 | PDF/A, redaction, signatures | planned |

The next milestone is deliberately not a feature: it is getting veraPDF
validation green in CI, because the compliance claim is the reason to
choose this library over an established one.

## Development

```bash
pip install -e ".[dev]"
pytest
python examples/financial_report.py
```

## License

Apache-2.0.
