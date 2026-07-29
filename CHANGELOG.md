# Changelog

All notable changes to this project are documented here. This project
follows [Semantic Versioning](https://semver.org/).

## [0.4.0] - 2026-07-29

### Added
- Review round-trip, the review loop for LLM-generated content. A reviewer
  marks up a rendered PDF in Acrobat, Preview, or Chrome, and each
  annotation resolves back to the exact node and character range it covers:
  - Text-position index (`textmap.py`): the renderer records every text
    fragment's node id, character offsets, and box. `Document.text_index()`
    resolves any page rectangle to a node and character range;
    `render(embed_spec=True)` embeds `emboss-textmap.json`.
  - `annotations.extract_comments()` reads reviewer markup via pikepdf and
    resolves each to a `Comment` with node id, `char_range`, `anchor_text`,
    `node_path`, and a required resolution state (`exact` | `node` |
    `spanning` | `unanchored`). `merge_comments()` unions several reviewers;
    `unresolved_count()` is surfaced loudly.
  - `review.propose_patches` / `apply_replacements` / `redline`: comments are
    never auto-applied; an `exact` edit splices only the objected-to phrase.
  - `review_html.review_html()`: a self-contained static triage report.
  - CLI: `emboss review` and `emboss apply`; `emboss render --embed-spec`.
- Incremental amendment (`amend.py`): append-only revisions for signatures
  and approvals that never rewrite prior bytes. `amend_sign` /
  `prepare_signature` / `amend_pdf`, `revision_history`, and
  `coverage_report` / `format_history` detect content appended after a
  signature that no signature covers. DocMDP is enforced; encrypted bases are
  rejected. CLI: `emboss amend`, `emboss history`, `emboss verify
  --revisions`.

### Fixed
- Explicit block ids were dropped on the spec-JSON round-trip (`from_json`
  and `emboss render`), so patch-by-id and annotation resolution could not
  find a node. Ids now survive both the pydantic and manual parse paths.

## [0.3.0] - 2026-07-28

### Added
- Specialized diagram types, each described as a plain node/edge list,
  laid out automatically, rendered as native vector graphics with
  deterministic `/Alt` text, and exposed in the fluent API, JSON spec,
  Pydantic schema, and LLM spec prompt:
  - `Document.architecture_diagram` -- cloud and deployment topologies
    with twelve built-in service glyphs (`compute`, `database`,
    `storage`, `queue`, `gateway`, `cache`, `cdn`, `function`,
    `loadbalancer`, `user`, `external`, `generic`) and nesting groups
    that draw zones such as a VPC wrapping public and private subnets.
    Relabels cleanly to AWS, Azure, or GCP.
  - `Document.sequence_diagram` -- participant lifelines with `sync`,
    `async`, and `return` message styles, activation bars, and
    self-loops.
  - `Document.er_diagram` -- entities with typed `PK`/`FK` attributes and
    labeled relationships carrying `from_card`/`to_card` cardinality.

### Changed
- Code-block backgrounds now fit the width of the code instead of always
  spanning the full page, so short snippets no longer leave a large empty
  area; wide or wrapped code still fills out to the margin.
- Architecture zone titles render on a solid chip above the edges, so a
  zone title never collides with an edge label crossing its boundary.

### Fixed
- `\|` in math now sets as a double norm bar (a single bar read as the
  letter `l`), and `\mid` sets as the conditioning bar; both resolve to
  glyphs the embedded font carries, so neither falls back to a missing
  glyph box.

## [0.2.0] - 2026-07-28

### Added
- Front-matter block elements for cover pages and long-form apparatus:
  `CoverPage`, `Abstract`, `Authors`/`Author`, `PullQuote`, `StatTiles`/
  `Stat`, `TableOfContents` (plus `ListOfFigures`/`ListOfTables`
  variants), `Appendix` (lettered, with its own `A.1`-style heading
  numbering), `Index` (alphabetized, resolved from `TextRun.index_terms`
  marks), and `Glossary`/`GlossaryEntry` (alphabetized, with each term's
  first body occurrence auto-linked to its entry). All are part of the
  EmbossSpec JSON vocabulary (`cover_page`, `abstract`, `authors`,
  `pull_quote`, `stat_tiles`, `toc`, `appendix`, `index`, `glossary`),
  not just the Python API; `blockquote` is likewise a real JSON block
  type, not Python-only as previously documented.
- `SlideDeck` (`emboss.slides`): a full presentation-deck builder with
  nine designed slide layouts (title, section divider, content,
  bullets, stats, chart, quote, code, closing), four WCAG-contrast-
  checked color themes (`boardroom`, `horizon`, `carbon`, `meadow`),
  two-column content slides, and fit-to-slide validation that scales
  type down in steps rather than letting a slide overflow.
- Diagram element (`emboss.diagrams`): node/edge graphs with automatic
  layered-DAG layout (longest-path layering, barycenter crossing
  reduction, cycle handling via back-edge reversal), five node shapes,
  solid/dashed edges, deterministic auto-generated alt text, and a
  fenced ` ```diagram ` Markdown syntax. Exposed as `doc.diagram(...)`
  and the `diagram` JSON block type.
- MathML input: `parse_math`/`MathBlock` auto-detect presentation
  MathML and route it through the new `emboss.mathml` parser into the
  same AST the LaTeX parser produces, so layout and rendering are
  shared. Supports `mi`/`mn`/`mo`, `mrow`, `mfrac`, `msqrt`/`mroot`,
  `msup`/`msub`/`msubsup`, `munder`/`mover`/`munderover`, `mtable`,
  `mfenced`, `mtext`, `mspace`, `mstyle`, and `semantics`.
- Real math alphabets: `\mathbb`, `\mathcal`/`\mathscr`, and `\mathfrak`
  render actual double-struck, script, and fraktur glyphs from the
  bundled Emboss Math font (a modified STIX Two Math subset), not a
  substitution approximation.
- Expanded SVG subset (`emboss.svg`): full path data (`M/L/H/V/C/S/Q/T/A/Z`,
  including elliptical arcs converted to cubic Beziers), transform
  stacks (`translate`/`scale`/`rotate`/`skewX`/`skewY`/`matrix`) composed
  through nested groups, `linearGradient`/`radialGradient` (with `href`
  stop inheritance) plus `gradient_shading` for true PDF type 2/3
  `/Shading` dictionaries, `clipPath` compiled to a real PDF clip, real
  `ExtGState` opacity, and `<text>`/`<use>`/`<defs>`.
- BrandKit (`emboss.brandkit`): an immutable, versioned brand object
  (palette, fonts, logo) applied on top of any style preset via
  `Document(brand=...)`; brand text colors are auto-darkened to meet
  4.5:1 contrast, and `derived_palette`/`series_palette` generate a
  deterministic N-color chart palette from the brand's primary and
  accent colors.
- Self-describing PDFs: `Document.render(embed_spec=True)` embeds the
  document's own EmbossSpec JSON, a node id -> layout map, and a
  reflowable Markdown twin as real `/AF` file attachments (ISO 32000-2,
  `emboss.pdf.attachments`); `Document.from_pdf()` recovers an
  equivalent document from the attachment, or degrades to walking the
  PDF/UA structure tree (recovering headings, paragraphs, tables, lists,
  block quotes, footnotes, and code blocks in order with their original
  node ids) when attachments are absent or `strict=True` is not set.
- Stable node ids (`emboss.nodeid`): every top-level block gets a
  deterministic content-derived id (or keeps an explicit one), and
  `Document.layout_map()` resolves every id to its page and bounding
  box across however many placements it was split into.
- `emboss strip` / `strip_pdf`: removes `/AF` attachments, provenance
  XMP/Info metadata (`Producer`, `Creator`, document history), and
  structure-tree node ids from an already-rendered PDF, keeping Title,
  Author, and date fields.
- Real veraPDF conformance checking (`emboss.pdf.verify.verify_conformance`,
  `emboss verify --conformance {ua1,2b,3b}`): shells out to the actual
  veraPDF CLI and parses its JSON report into a structured
  `ConformanceReport`. The CI `conformance` job installs the real
  veraPDF binary and runs this suite against it on every push and pull
  request, not a simulated check.
- PDF/A-3b support alongside PDF/A-2b (`emboss.pdfa.pdfa_part_for`):
  `render(embed_spec=True)` automatically upgrades a `pdfa=True`
  document to PDF/A-3 (which permits arbitrary embedded files) since
  PDF/A-2 forbids them.
- Document diff and redline (`emboss.diff`): `diff_documents()` matches
  blocks between two documents by stable node id and classifies each as
  added, removed, or changed (with a word-level diff on text-bearing
  blocks); `render_redline()` renders the new document with deletions
  struck through, insertions underlined, a measured change-bar on added
  blocks, and a prepended summary page. `emboss diff old.pdf new.pdf`
  from the command line.
- `PageSpec.a5()` and `PageSpec.compact()` (A5, tight margins, tuned for
  phone/tablet reading); `page_styles` + `PageBreak.page_style` let a
  document switch page geometry (e.g. to landscape for one wide table
  or diagram) and switch back.
- `emboss.typography.numbers.format_number`: deterministic, locale-
  independent display formatting (plain, thousands-grouped, currency,
  percent) for values headed into text runs or table cells.
- Reproducibility manifest (`emboss.manifest`): `Document.render(manifest=True)`
  attaches a deterministic `emboss-manifest.json` (spec sha256, Emboss
  version, embedded font sha256s, non-default render options);
  `reproduce()` (and `emboss reproduce report.pdf`) recovers a document
  from a PDF, re-renders it, and structurally compares the two.
- Construction-time redaction (`emboss.redaction.RedactionRule`,
  `redact_document`, `Document.redact(rules)`): matches whole content
  blocks by node id, regex/predicate over plain text, or element type,
  and removes or replaces them before layout or rendering, so redacted
  text never reaches a content stream. `mode="placeholder"` covers
  same-shaped filler with an opaque box; `mode="remove"` drops the
  block. The prior `RedactionMark`/`apply_redactions` post-render
  masking is kept for callers without a `Document`.
- DocMDP certification signatures (`emboss.signing`):
  `build_docmdp_reference`, `build_certifying_signature`,
  `build_perms_dict`, and `sign_pdf(..., certify=True,
  docmdp_permission=...)` produce an ISO 32000-1 12.8.2.3 certification
  signature declaring what changes are permitted after signing.
- Encrypted attachments: `Document.attach_encrypted(name, data,
  password)` queues an AES-256-GCM-encrypted `/AF` attachment
  (`relationship="EncryptedPayload"`); `encrypt_attachment`/
  `decrypt_attachment` (`emboss.redaction`) implement the cipher.
- `Document.patch(node_id, **changes)`: returns a new Document with the
  one block carrying `node_id` replaced, for editing a single block
  without regenerating the whole spec.
- Chart fact verification (`emboss.chart_facts`): `compute_facts`
  derives a deterministic fact set (min/max/first/last/mean, totals,
  direction, shares) from chart data; `verify_caption` flags caption
  numbers unsupported by those facts; `fact_sentence` generates a
  one-line finding phrased only from computed facts. `Chart.verify_facts`
  opts a chart's `headline` into this verification, falling back to the
  generated sentence when the authored headline can't be supported.
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
- Markdown blockquotes render as the native `BlockQuote` element (accent
  bar, optional attribution) by default rather than an indented italic
  paragraph.
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
