# Changelog

All notable changes to this project are documented here. This project
follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Two new style presets: `journal` (serif, justified, for periodicals)
  and `brief` (sans, executive briefs), bringing the total to seven.
- Bundled OFL font set (Source Serif 4, Source Sans 3, Source Code Pro;
  ~2.7MB, Latin/Greek/Cyrillic) registered via
  `emboss.bundled_fonts.register_bundled_fonts`, with "emboss serif",
  "emboss sans", and "emboss mono" aliases.
- Robust LLM spec parsing: truncated-JSON repair, synonym normalization
  on both parse paths, and per-block recovery on validation errors
  (invalid blocks coerced to paragraphs or dropped). `strict=True`
  raises instead of repairing; `on_warning` receives one message per
  repair; `smart=True` applies content intelligence to the parsed spec.
- `spec_prompt()` teaches the exact vocabulary the validator accepts;
  specs can request `toc` and page `columns`/`column_gap` directly.
- Emergency character-level line breaking for words and URLs wider than
  the measure, so lines never overflow.
- Hyphen-ladder control: hyphen breaks are flagged and ladders are
  capped at 3 consecutive hyphenated lines via a large demerit.
- Full Knuth-Liang en-US hyphenation pattern set bundled.
- Math environments: `matrix`/`pmatrix`/`bmatrix`/`vmatrix`/`Bmatrix`,
  `cases`, `aligned`/`align`/`align*`/`split`, and
  `gathered`/`gather`/`gather*`.
- Display-mode limits: `\sum`, `\prod`, `\int`, and `\lim` place limits
  above and below the operator.
- End-to-end CMYK output: `color_mode="cmyk"` switches every draw path
  to `k`/`K` operators, with `cmyk()` and `spot()` color strings, spot
  colors as Separation color spaces, a CMYK PDF/A OutputIntent (N=4),
  and redaction/signature appearances that honor the mode.
- Markdown parsing: escapes, inline and reference links, autolinks,
  strikethrough, inline math, formatted table cells, true nested lists
  with per-depth markers, task lists, setext headings, footnote
  definitions, and blockquotes (rendered as indented italic).
- Hyperlink `/Link` annotations with PDF/UA Link structure elements and
  `OBJR` references.
- Alt text emitted as `/Alt` for images, SVG blocks, and charts, with an
  auto-derived description when none is given.
- Cross-references wired end to end: automatic "Figure N:"/"Table N:"
  captions, `@key` resolution to clickable GoTo links, and section
  numbering via `number_sections`.
- Table captions render.
- PDF/UA-1 identifier declared in XMP metadata for tagged output.

### Changed
- Base-14 AFM widths extended beyond ASCII: dashes, curly quotes, and
  accented Latin (resolved via NFD decomposition to the base letter).
- GPOS kerning now unwraps Extension (LookupType 9) lookups, sums
  Value2 advances, and resolves class-pair (Format 2) kerning lazily
  with per-pair memoization.
- Ligature substitution (fi, fl, ff, ffi, ffl) runs on embedded fonts
  with per-glyph cmap detection; base-14 fonts are left untouched.
- Math rendering uses real base-14 AFM metrics (Times italic/roman,
  Symbol) and TeX spacing classes (thin/medium/thick) between atoms.
- Bibliography entries wrap with a hanging indent.
- ICC profiles hardened and fully deterministic.
- Embedded-font subsetting is deterministic (no timestamps).

### Fixed
- Mixed-size inline runs raise the line height to the tallest run.
- Removed synthetic font expansion via the `Tz` horizontal-scaling
  operator; glyphs render at their natural widths.

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
