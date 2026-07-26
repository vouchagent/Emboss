# Changelog

All notable changes to this project are documented here. This project
follows [Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

Phase 1: core engine.

### Added
- Semantic document model (`Document`, `Heading`, `Paragraph`, `Table`,
  `BulletList`, `TextRun`) with a cascading style system and five
  professionally tuned presets.
- Font metrics engine with base-14 metrics built in and TrueType/OpenType
  loading, subsetting, and `/ToUnicode` generation via fontTools.
- Knuth-Plass optimal line breaking with fitness classes, active-node
  pruning, and a greedy fallback.
- Knuth-Liang hyphenation with a no-break list for legal and financial
  abbreviations.
- Constraint-based pagination: widow and orphan control, keep-with-next,
  keep-together, and table splitting with header repetition.
- Table column solver using real font metrics, with decimal alignment for
  numeric columns.
- PDF/UA structure tree with ParentTree, role map, and header cell scope.
  Decorative content is marked as `/Artifact`.
- Byte-exact assembler with content-derived `/ID`; output is
  reproducible across runs and machines.
- Constraint validator with auto-fix and error categories.
- Legal features: Bates numbering, continuous line numbering, watermarks.
- Structural verifier (`precisionpdf.pdf.verify`).

### Known limitations
- No image or chart support yet (Phase 5).
- No PDF/A archival output yet (Phase 4).
- OpenType shaping is not implemented: ligatures and GPOS kerning are not
  applied. Only the legacy `kern` table is read. Complex scripts (Arabic,
  Devanagari) and CJK line breaking are unsupported.
- Text encoding is limited to WinAnsi; codepoints outside it are not
  rendered correctly.
- Output has not yet been validated against veraPDF.
