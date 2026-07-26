# Changelog

All notable changes to this project are documented here. This project
follows [Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

Initial release of Emboss (formerly PrecisionPDF).

### Core Engine
- Semantic document model (`Document`, `Heading`, `Paragraph`, `Table`,
  `BulletList`, `NumberedList`, `TextRun`) with a cascading style system
  and five professionally tuned presets (legal, finance, academic,
  corporate, minimal).
- Byte-exact PDF assembler with content-derived `/ID`; output is
  reproducible across runs and machines.
- Constraint validator with auto-fix and error categories.

### Typography
- Knuth-Plass optimal line breaking with fitness classes, active-node
  pruning, and a greedy fallback.
- Knuth-Liang hyphenation with a no-break list for legal and financial
  terms.
- Font metrics engine with base-14 metrics built in and TrueType/OpenType
  loading, subsetting, and `/ToUnicode` generation via fonttools.
- Smart typography: curly quotes, em/en dashes, fractions, ellipses,
  non-breaking spaces before units.
- Ligature substitution (fi, fl, ffi, ffl).

### Layout
- Constraint-based pagination: widow and orphan control, keep-with-next,
  keep-together, and table splitting with header repetition.
- Table column solver using real font metrics, with decimal alignment for
  numeric columns.
- Multi-column layout with column balancing and column-spanning elements.

### Accessibility
- PDF/UA structure tree with ParentTree, role map, and header cell scope.
  Decorative content is marked as `/Artifact`.
- Structural verifier (`emboss.pdf.verify`).

### Content Elements
- Unicode/CIDFont support for full Unicode coverage.
- Syntax-highlighted code blocks with line numbers.
- LaTeX-style math notation with superscripts, subscripts, fractions,
  roots, integrals, summations, Greek letters, and font commands.
- Charts (bar, line, pie, scatter) rendered as native PDF vectors.
- SVG embedding with support for paths, shapes, and basic styling.
- Footnotes with automatic numbering.
- Callout/admonition boxes (note, warning, tip, caution, important).
- Bibliography formatting with multiple citation styles.
- Table of contents with page numbers.
- Cross-references with `@label` syntax and auto-numbering for
  figures, tables, equations, and sections.

### Document Features
- Custom headers and footers with left/center/right slots and
  `{page}`/`{pages}` placeholders.
- Legal features: Bates numbering, continuous line numbering, watermarks.
- PDF/A-2b archival output with XMP metadata and sRGB ICC profile.
- Digital signature support via PKCS#7/CMS.
- Content redaction.
- Slide/presentation layout (16:9 and 4:3).
- Eight document templates: memo, report, letter, invoice, academic paper,
  legal brief, slide deck, data sheet.

### Adapters
- HTML export.
- Markdown export.
- DOCX export.
- Pydantic/JSON Schema for LLM structured output integration.

### Intelligence
- Content analysis and document type detection.
- Typographic quality scoring.
- Table intelligence (alignment inference, numeric detection).
