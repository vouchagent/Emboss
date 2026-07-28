# Emboss — Feature Set (final)

One engine, two profiles: `Document(profile="transactional" | "technical")`.
Profile A = high-volume, agent-authored, customer-facing. Profile B = authored, reviewed, internal.
Diagram and signing dependencies ship as extras. Layer 0 must be complete before anything above it ships.

---

## Layer 0 — Core

| Feature | Serves | Enterprise value |
|---|---|---|
| No-overflow layout guarantee | Both | Unattended generation; removes per-document layout QA |
| Deterministic byte-identical output | Both | Git-native docs, hash attestation, meaningful diffs |
| PDF/UA tagging by default | Both | Clears the accessibility procurement gate; kills remediation spend |
| `emboss verify` → veraPDF conformance report | Both | Audit-ready compliance evidence shipped with the document |
| Stable node IDs on every block | Both | Prerequisite for diffing, editing and review |
| **Layout map** (node ID → page → bounding boxes) | Both | Prerequisite for annotation round-trip; only a spec-owning engine can emit it |
| Document diff → redlined PDF | Both | Review workflow for reports, contracts, design revisions |
| Cross-references and auto numbering | Both | Long-document credibility |
| Tabular figures + numeric formatting | Both | The fastest visual tell of professional typesetting |
| Landscape / mixed page geometry | Both | Wide tables and architecture diagrams |
| Provenance block + XMP metadata | Both | Separates a verified document from a plausible one |
| TOC, appendices, index, glossary | Both | Long-form navigability |

---

## Layer 1 — Presentation

| Feature | Serves | Enterprise value |
|---|---|---|
| BrandKit as a versioned object | Both | Brand defined once, propagates on next build |
| Cover page + document control block | Both | Turns an export into a document |
| Chart hardening (no truncation, direct labels, zero baseline, pattern fills) | Both | Removes chart fiddling and the dashboard-screenshot habit |
| **Derived alt text** — computed from the data, no model | Both | Beats any LLM description, which is guessing at a chart it cannot see |
| **Long description via element-level `/AF`** | Both | Screen-reader user gets the actual numbers, not a paragraph approximating them |
| **Fact-verified captions** | Both | Model phrases only computed facts; numbers not in the fact set are rejected |
| Headline / subtitle / source line convention | Both | States the finding, not just the data — the biggest perceived-quality gap |
| Refuse charts the data can't support | Both | Three points is not a trend; a non-summing series is not a pie |
| Source lines under tables and figures | Both | Audit culture; provenance visible on the page |

---

## Layer 2 — Container features

Exploits PDF capabilities page-painting engines cannot use, because they don't know which marks were a table.

| Feature | Serves | Enterprise value |
|---|---|---|
| Embed spec + layout map inside the PDF (PDF/A-3) | Both | Document is self-describing and re-editable; no source file to lose |
| **Element-level associated files (`/AF`)** — see 2.1 | Both | Any element carries its own reference data: verification, accessibility, reuse |
| Spec recovery from the tag tree (`Document.from_pdf`) | Both | Round-trip still works if the attachment was stripped |
| Node-scoped patching | Both | LLM edits one section, not the document |
| `emboss strip` for external distribution | Both | Removes embedded spec, provenance and internal identifiers |
| Redaction by construction + redaction log | A | Content never enters the stream — the only honest redaction claim available |
| Reproducibility manifest + `emboss reproduce` | Both | Re-renders and proves byte equality against the original |
| Signed spec + lineage pointer to predecessor | Both | Verifiable chain: this PDF came from that approved source |
| Reflowable alternative attachment (`/AF` = `Alternative`) | Both | Accessibility beyond tagging; mobile and screen-reader friendly twin |
| Certified permissions (DocMDP) | A | Annotate but do not alter, enforceable |
| Encrypted payload attachment | A | Distribute the report widely, gate the underlying data |

### 2.1 Associated files — one mechanism, any reference data

`/AF` attaches to the document, a page, an annotation, **or an individual structure element**, with a declared `AFRelationship`. Because Emboss owns the semantic tree, it can attach to the right element — a page-painting engine cannot, because it doesn't know which marks were a chart.

| Attached to | Content | `AFRelationship` | Serves |
|---|---|---|---|
| Chart figure | Source CSV / series JSON | `Data` | Long description for screen readers; reader verification; re-analysis |
| Table | Source CSV | `Data` | Verification; extraction without parsing |
| Document | `emboss-spec.json` | `Source` | Round-trip editing, lossless downstream consumption |
| Document | `emboss-layout.json` | `Supplement` | Annotation resolution |
| Document | Reflowable Markdown / HTML twin | `Alternative` | Accessibility beyond tagging; mobile reading |
| Document | Chunk manifest | `Supplement` | Retrieval-ready, semantically bounded chunks |
| Requirement | Test or verification evidence | `Supplement` | Traceability in controlled documents |
| Invoice | CII XML (EN 16931) | `Data` | Factur-X / ZUGFeRD compliance |
| Bibliography | BibTeX / CSL JSON | `Supplement` | Citation reuse downstream |
| Any element | Encrypted blob | `EncryptedPayload` | Ship the document widely, gate the data |

**Rules**

- Alt text stays short and factual; **never** use `/Alt` to carry a data table — that's what the attachment is for.
- Every attachment is an exfiltration path. `emboss strip` must remove all of them; default embedding on for Profile B, off for Profile A.
- Attachments may be stripped by mail gateways or lost on re-save. The tag tree is always the fallback; anything attached must be regenerable from it, degraded but functional.

---

## Layer 3 — Review and revision

The two features that close the loop. Both depend on the layout map and stable node IDs.

| Feature | Serves | Enterprise value |
|---|---|---|
| Annotation extraction and resolution | Both | Reviewer markup in Acrobat becomes structured feedback against the spec |
| Multi-reviewer merge | Both | One comment list from several returned PDFs |
| Proposed patches per comment | Both | LLM applies feedback per node; redline proves what changed |
| Comment response and resolution state | Both | Closes the loop back to the reviewer |
| Incremental amendment (append-only revisions) | Both | Audit trail lives inside the document |
| Revision history and coverage check | Both | Detects appended content no signature covers |
| Static HTML review report | Both | Non-technical owners can triage without a server or a CLI |

### 3.1 Annotation round-trip

**Why it's defensible:** every other PDF has no structure to resolve a comment against. Emboss knows which glyphs belong to which node, so a highlight becomes a node reference and a character range — not a guess.

**Reviewers use Acrobat, Preview or Chrome. No new tool for legal or finance.**

```bash
emboss render spec.json -o v1.pdf              # embeds spec + layout map
# reviewers mark up v1.pdf in whatever they already use

emboss review v1-legal.pdf v1-finance.pdf -o comments.json
emboss review v1-legal.pdf --html review.html  # triage view, no server

emboss apply comments.json --spec spec.json --propose
emboss render spec.json -o v2.pdf
emboss diff v1.pdf v2.pdf -o redline.pdf
emboss respond v2.pdf --from comments.json     # marks annotations resolved
```

Extracted comment shape:

```json
{
  "id": "c-07",
  "type": "strikeout",
  "author": "R. Patel",
  "page": 4,
  "node_id": "sec-risk.p3",
  "node_path": "Document > Section[Risk] > Paragraph[3]",
  "anchor_text": "exposure exceeds $4.2M",
  "char_range": [120, 143],
  "comment": "Overstates it — use the netted figure",
  "resolution": "exact",
  "status": "open"
}
```

`char_range` is the load-bearing field: it lets a model edit the phrase objected to, not "somewhere in this paragraph".

**Resolution states — required field, never silent:**

| State | Meaning | Behaviour |
|---|---|---|
| `exact` | Resolved to one node and character range | Patchable |
| `node` | Resolved to a node, no character range | Patchable, whole-node |
| `spanning` | Crosses two or more nodes | Report both IDs; never split silently |
| `unanchored` | No content beneath the annotation | Surface with page and rect; never drop |

**Rules**

- `--propose` is the default. Never auto-apply reviewer comments — that ships a document nobody approved.
- Prefer `/StructParent` over geometry when the annotating tool supplied it.
- Report the unresolved count loudly. A silently mis-resolved comment is worse than an unresolved one.
- Build the unresolved path before the happy path.

**Known fragility:** flattened annotations (Preview's flattened export) are unrecoverable; the layout map must survive; geometric resolution varies by viewer. Test across Acrobat, Preview and Chrome before claiming support.

### 3.2 Incremental updates

**The distinction that keeps the API coherent — do not blur it:**

| Operation | Use for | Result |
|---|---|---|
| `emboss render` | Content changed | **New file**, linked to predecessor by lineage hash |
| `emboss amend` | Attestation added | **Same file**, one appended revision, prior bytes untouched |

Content edits go through the spec. Signatures, approvals, annotations, resolution states and added attachments append.

```bash
emboss render contract.spec.json -o contract.pdf

emboss amend contract.pdf --sign --cert legal.pem   --reason "Approved: Legal"
emboss amend contract.pdf --sign --cert finance.pem --reason "Approved: Finance"

emboss history contract.pdf
emboss verify contract.pdf --revisions
```

```
Rev 1  2026-07-20  base            spec 4a91c3…  matches embedded spec ✓
Rev 2  2026-07-22  signature       R. Patel (Legal)      covers rev 1 ✓
Rev 3  2026-07-24  signature       M. Osei (Finance)     covers rev 1–2 ✓
Rev 4  2026-07-25  annotations     3 comments, unsigned   ⚠ not covered by any signature
```

That last line is the feature — detecting appended content no signature covers is the check auditors actually want, and it falls out of the structure for free.

**Implementation constraints**

| Constraint | Requirement |
|---|---|
| Original bytes | Never rewrite. Continue object numbering from previous max; chain trailer via `/Prev` |
| DocMDP | If rev 1 certifies with restrictive permissions, some amendments are illegal — check and fail loudly |
| Linearization | Amended files are no longer linearized. Re-linearize on fresh render or document the loss |
| PDF/A and PDF/UA | Re-validate after every amend |
| Encryption | Must match the base revision |

**Restate the determinism claim once this ships:**

> Revision N is byte-identical to what it was when created. Amendments append; they never rewrite. The rendered document is reproducible from its embedded spec at any revision.

More defensible than a blanket claim, and stronger — it survives signing, which the current phrasing does not.

---

## Layer 4 — Profile A (transactional)

| Feature | Serves | Enterprise value |
|---|---|---|
| MCP server | A | Makes the deliverable agent-callable — this is distribution |
| LLM spec parsing with per-block recovery | A | One bad block doesn't kill a batch job |
| **Factur-X / ZUGFeRD e-invoicing** | A | PDF/A-3 + EN 16931 XML; France's B2B mandate starts Sept 2026 |
| KPI stat tiles with deltas | A | Executive-grade first page |
| PDF/A-2b archival | A | Records retention, filing ingest |
| Content arithmetic validation | A | Refuses to render an internally inconsistent financial table |
| Bates, line numbering, watermark | A | Legal discovery and e-filing |
| WTPDF 1.0 Reuse conformance | A | Your PDFs re-extract cleanly into your own RAG pipeline |

---

## Layer 5 — Profile B (technical)

| Feature | Serves | Enterprise value |
|---|---|---|
| Mermaid / PlantUML / Graphviz → native vector | B | Without it you cannot render an architecture doc at all |
| CLI: Markdown directory → one PDF | B | B teams add a build step; they don't call an API |
| **EmbossMD** — Markdown + closed component set | B | Human- and LLM-friendly authoring; likely more robust than JSON |
| `.mdx` importer (subset, with dropped-content report) | B | Reaches the Docusaurus/Mintlify corpus without a Node dependency |
| Sphinx / MkDocs builder plugin | B | Inherits an audience; PDF with no TeX Live in CI |
| Revision history + approval block + controlled-doc header | B | The line between a nice PDF and a controlled document |
| Requirement IDs + auto traceability matrix | B | What regulated hardware and med-device teams pay for |
| Include-from-source for code samples | B | Documented examples can't drift from the code |
| Syntax-highlighted code blocks | B | Table stakes |

### EmbossMD rules

Closed component set mapping one-to-one onto EmbossSpec elements. No JavaScript evaluation.

```markdown
---
title: Payments Architecture
profile: technical
brandkit: acme@2
---

<Callout variant="warning">Retries are not idempotent below v4.</Callout>

<Requirement id="REQ-042" verify="test_retry_idempotent">
The gateway MUST deduplicate on idempotency key.
</Requirement>

<Diagram lang="mermaid">
sequenceDiagram
  Client->>Gateway: POST /charge
</Diagram>

See @REQ-042 and Table 3.
```

- Unknown component → error listing valid components
- `import`, `export`, `{expression}` → error stating this is not MDX
- Name it EmbossMD, never "MDX support" — MDX compiles to JavaScript and full fidelity needs a JS runtime, which would destroy the pure-Python, in-process guarantee

---

## Cut

| Drop | Reason |
|---|---|
| `slides.py` | Decks want editable PPTX; typography advantage is void at 30 words a slide |
| MathML / PDF/UA-2 math | LaTeX shipped it in TeX Live 2025 with Overleaf support |
| Academic journal templates | Conferences mandate LaTeX `.cls` files |
| DOCX round-trip | Unbounded scope, no differentiation |
| MyST | Deferred |
| Hosted web review UI | Inverts the "documents never leave the VPC" differentiator |

---

## Sequencing

| Release | Contents |
|---|---|
| 0.2 | Layer 0 complete, including layout map; veraPDF gate in CI; version aligned with README |
| 0.3 | Layer 1; MCP server; diagram-as-code; CLI; EmbossMD |
| 0.4 | Layer 2 container features; Layer 3 annotation round-trip + incremental updates |
| 0.5 | Factur-X; controlled-doc + traceability; remaining Profile A and B items |

**Gate:** nothing above Layer 0 ships until the four core claims — no overflow, determinism, PDF/UA, PDF/A — pass in CI.

**Dependency note:** Layer 3 is blocked on the layout map and stable node IDs. Ship those in 0.2 even though nothing consumes them yet, or Layer 3 slips a full release.
