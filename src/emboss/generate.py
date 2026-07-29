"""LLM integration for Emboss.

Tier 1: spec_prompt() returns a system prompt that teaches an LLM the
        EmbossSpec format. The LLM outputs JSON, you parse and render.

Tier 2: generate() handles the full pipeline: prompt -> LLM call ->
        parse -> render -> save.

Tier 3: Document.from_markdown() converts any Markdown (natural LLM
        output) to a high-quality PDF. See markdown.py.

    # Tier 1: bring your own LLM client
    from emboss import spec_prompt, Document
    system = spec_prompt(style="finance")
    # ... call your LLM with system prompt ...
    doc = Document.from_json(llm_response)
    doc.save("output.pdf")

    # Tier 2: one-liner
    from emboss import generate
    generate("Write a quarterly report", style="finance", output="report.pdf")
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Callable, Literal

if TYPE_CHECKING:
    from .spec import Document

__all__ = [
    "spec_prompt",
    "generate",
    "parse_spec_json",
    "parse_spec_dict",
    "spec_schema",
]

SPEC_SYNONYMS = {
    "bullet_list": "bullets",
    "numbered_list": "numbered",
    "math_block": "math",
    "horizontal_rule": "rule",
}

CALLOUT_VARIANT_SYNONYMS = {
    "tip": "info",
    "caution": "warning",
    "important": "note",
}


def _normalize_spec(data: dict) -> dict:
    """Map legacy type tags and field spellings onto the canonical vocabulary."""
    content = data.get("content")
    if not isinstance(content, list):
        return data
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype in SPEC_SYNONYMS:
            btype = SPEC_SYNONYMS[btype]
            block["type"] = btype
        if btype == "callout":
            variant = block.get("variant")
            if variant in CALLOUT_VARIANT_SYNONYMS:
                block["variant"] = CALLOUT_VARIANT_SYNONYMS[variant]
            if "text" not in block and isinstance(block.get("content"), str):
                block["text"] = block.pop("content")
        if btype == "chart" and "title" not in block and "caption" in block:
            block["title"] = block.pop("caption")
    return data


def spec_schema() -> dict:
    """Return the JSON Schema dict for the EmbossSpec document format."""
    try:
        from .adapters.pydantic_schema import DocumentSpec
    except ImportError:
        raise ImportError(
            "Structured outputs require pydantic to build the EmbossSpec "
            "JSON Schema.\n  pip install pydantic"
        ) from None
    return DocumentSpec.model_json_schema()


def _add_null_union(prop: dict) -> None:
    """Make a property schema accept null, per OpenAI's optional-field pattern."""
    options = prop.get("anyOf")
    if isinstance(options, list):
        if not any(o.get("type") == "null" for o in options if isinstance(o, dict)):
            options.append({"type": "null"})
        return
    if "$ref" in prop:
        prop["anyOf"] = [{"$ref": prop.pop("$ref")}, {"type": "null"}]
        return
    type_tag = prop.get("type")
    if isinstance(type_tag, str):
        prop["type"] = [type_tag, "null"]
    elif isinstance(type_tag, list) and "null" not in type_tag:
        type_tag.append("null")
    enum = prop.get("enum")
    if isinstance(enum, list) and None not in enum:
        enum.append(None)


def _make_strict(node) -> None:
    """Recursively enforce OpenAI strict-mode rules on a schema node."""
    if isinstance(node, dict):
        if isinstance(node.get("properties"), dict):
            node["additionalProperties"] = False
            optional = set(node["properties"]) - set(node.get("required", []))
            node["required"] = list(node["properties"])
            for name, prop in node["properties"].items():
                if name in optional and isinstance(prop, dict) and "const" not in prop:
                    _add_null_union(prop)
        elif node.get("type") == "object":
            node.setdefault("additionalProperties", False)
        for value in node.values():
            _make_strict(value)
    elif isinstance(node, list):
        for value in node:
            _make_strict(value)


def _strict_schema(schema: dict) -> dict:
    """Return a deep copy of `schema` compatible with OpenAI strict mode."""
    import copy

    schema = copy.deepcopy(schema)
    _make_strict(schema)
    return schema


_DOC_TYPE_EXEMPLARS: dict[str, dict] = {
    "report": {
        "title": "Q3 Operations Report",
        "style": "finance",
        "toc": True,
        "content": [
            {"type": "heading", "text": "Executive Summary", "level": 1},
            {"type": "paragraph", "text": "Output rose 8% quarter over quarter."},
            {"type": "heading", "text": "Regional Performance", "level": 2},
            {
                "type": "table",
                "headers": ["Region", "Revenue", "Change"],
                "rows": [["North", "$2.4M", "+11.5%"], ["South", "$1.8M", "+3.2%"]],
                "stripe": True,
            },
            {"type": "heading", "text": "Trend", "level": 2},
            {
                "type": "chart",
                "chart_type": "bar",
                "labels": ["Q1", "Q2", "Q3"],
                "values": [100, 120, 130],
                "title": "Quarterly Output",
            },
        ],
    },
    "paper": {
        "title": "Spectral Methods for Sparse Systems",
        "style": "academic",
        "page": {"preset": "a4", "columns": 2},
        "content": [
            {
                "type": "paragraph",
                "text": "Abstract. We present a spectral method for sparse systems.",
                "style": {"italic": True},
            },
            {"type": "heading", "text": "Introduction", "level": 1, "numbering": "1"},
            {"type": "paragraph", "text": "Sparse systems arise across analysis."},
            {"type": "heading", "text": "Method", "level": 1, "numbering": "2"},
            {"type": "math", "source": "\\sum_{i=1}^{n} \\lambda_i x_i = b"},
            {"type": "heading", "text": "References", "level": 1},
            {"type": "paragraph", "text": "[1] A. Author, Iterative Methods, 2024."},
        ],
    },
    "brief": {
        "title": "Market Entry Brief",
        "style": "brief",
        "content": [
            {"type": "heading", "text": "Market Entry: Northern Europe", "level": 1},
            {
                "type": "table",
                "headers": ["Metric", "Value"],
                "rows": [["TAM", "$1.2B"], ["CAGR", "9.4%"]],
            },
            {
                "type": "callout",
                "text": "Regulatory approval expected in Q2.",
                "variant": "info",
                "title": "Timing",
            },
            {
                "type": "blockquote",
                "text": "The window for category leadership is now.",
                "attribution": "CEO",
            },
            {
                "type": "callout",
                "text": "Currency exposure remains unhedged.",
                "variant": "warning",
            },
        ],
    },
    "deck": {
        "title": "Product Launch Deck",
        "style": "corporate",
        "content": [
            {"type": "heading", "text": "Launch Plan", "level": 1},
            {"type": "paragraph", "text": "A three-phase rollout in two markets."},
            {"type": "page_break"},
            {"type": "heading", "text": "Phase One", "level": 1},
            {
                "type": "bullets",
                "items": ["Private beta", "Feedback loop", "Pricing test"],
            },
            {"type": "page_break"},
            {"type": "heading", "text": "Metrics", "level": 1},
            {
                "type": "chart",
                "chart_type": "line",
                "labels": ["W1", "W2", "W3"],
                "values": [120, 340, 610],
                "title": "Signups",
            },
        ],
    },
    "architecture": {
        "title": "Ingest Service Architecture",
        "style": "corporate",
        "content": [
            {"type": "heading", "text": "Overview", "level": 1},
            {"type": "paragraph", "text": "Events flow from gateway to processor."},
            {
                "type": "svg",
                "source": (
                    '<svg xmlns="http://www.w3.org/2000/svg" width="200" '
                    'height="60"><rect x="5" y="15" width="80" height="30" '
                    'fill="none" stroke="black"/><rect x="115" y="15" '
                    'width="80" height="30" fill="none" stroke="black"/>'
                    '<line x1="85" y1="30" x2="115" y2="30" stroke="black"/>'
                    "</svg>"
                ),
                "caption": "Gateway to processor",
                "alt_text": "Two boxes joined by a line",
            },
            {"type": "heading", "text": "Endpoints", "level": 2},
            {
                "type": "table",
                "headers": ["Route", "Method"],
                "rows": [["/ingest", "POST"], ["/health", "GET"]],
            },
            {
                "type": "code_block",
                "code": "def handle(event):\n    return enqueue(event)",
                "language": "python",
            },
            {
                "type": "callout",
                "text": "The queue is the only stateful component.",
                "variant": "note",
            },
        ],
    },
}


def _format_exemplar(doc: dict) -> str:
    """Format an exemplar dict as compact JSON with one content block per line."""
    lines = ["{"]
    items = list(doc.items())
    for index, (key, value) in enumerate(items):
        comma = "," if index < len(items) - 1 else ""
        if key == "content":
            lines.append('  "content": [')
            for j, block in enumerate(value):
                block_comma = "," if j < len(value) - 1 else ""
                encoded = json.dumps(block, separators=(", ", ": "))
                lines.append(f"    {encoded}{block_comma}")
            lines.append(f"  ]{comma}")
        else:
            encoded = json.dumps(value, separators=(", ", ": "))
            lines.append(f"  {json.dumps(key)}: {encoded}{comma}")
    lines.append("}")
    return "\n".join(lines)


def spec_prompt(
    style: str = "corporate",
    features: list[str] | None = None,
    doc_type: str | None = None,
) -> str:
    """Return a system prompt that teaches an LLM the EmbossSpec format.

    The prompt is compact (~2K tokens) and describes every block type with
    examples. Pass it as the system prompt and the LLM will output valid
    EmbossSpec JSON.

    Args:
        style: default style preset to suggest (legal/finance/academic/corporate/minimal/journal/brief)
        features: optional list of features to emphasize (e.g. ["tables", "math", "code"])
        doc_type: optional genre (report/paper/brief/deck/architecture) whose
            worked example is appended to the prompt
    """
    if doc_type is not None and doc_type not in _DOC_TYPE_EXEMPLARS:
        available = ", ".join(sorted(_DOC_TYPE_EXEMPLARS))
        raise ValueError(f"Unknown doc_type {doc_type!r}. Available: {available}")

    feature_hints = ""
    if features:
        feature_hints = f"\nFocus on these elements: {', '.join(features)}.\n"

    exemplar_section = ""
    if doc_type is not None:
        exemplar = _format_exemplar(_DOC_TYPE_EXEMPLARS[doc_type])
        exemplar_section = (
            f"\n\n## Worked Example: {doc_type}\n"
            "Follow this genre skeleton; replace the material with content "
            f"for the user's request.\n```json\n{exemplar}\n```"
        )

    return f"""You are a document generation assistant. Output a JSON object following the EmbossSpec format below. The JSON will be rendered into a professional PDF with optimal typography, accessibility tags, and deterministic output.

## EmbossSpec JSON Format

```json
{{
  "title": "Document Title",
  "author": "Author Name",
  "style": "{style}",
  "content": [
    {{"type": "heading", "text": "Overview", "level": 1}},
    {{"type": "paragraph", "text": "Body text."}}
  ]
}}
```

"title" and "content" are required. Optional document fields: "author", "subject", "keywords", "toc" (true inserts an auto-generated table of contents), and "page" for geometry.

Do not emit brand colors, fonts, or a logo: visual branding is applied programmatically by the integrator via a BrandKit, not by you.

## Available Styles
- "legal" — serif, justified, generous leading (contracts, briefs)
- "finance" — sans-serif, tight, tabular (reports, filings)
- "academic" — serif body, sans headings, justified (papers, theses)
- "corporate" — sans-serif, readable, roomy (memos, policies)
- "minimal" — compact, minimal ornament (data exports)
- "journal" — serif, justified, muted forest accent (long-form reports, journals)
- "brief" — sans-serif, bold accents, stat-friendly (executive briefs)

## Page Options
```json
{{"page": {{"preset": "a4", "columns": 2, "column_gap": 24}}, "toc": true}}
```
Presets: letter, a4, a5, legal, compact. Use "columns": 2 for two-column layouts (newsletters, academic papers); "column_gap" is in points.
The "compact" preset (A5 with tight margins) suits phone and tablet reading.
Set "landscape": true on "page" (or any entry in "page_styles") for a wide page. "page_styles" is a name -> page-geometry map; a {{"type": "page_break", "page_style": "wide"}} block switches to that geometry until a page break with no "page_style" reverts to the document default — use this for a wide table or diagram inside an otherwise portrait document.

## Headers, Footers & Page Numbers
```json
{{"header": {{"left": "{{section}}", "right": "{{page}} of {{pages}}"}}, "page_number_format": "arabic", "front_matter_pages": 0}}
```
"header"/"footer" slots (left/center/right) accept {{page}}, {{pages}}, and {{section}} (current heading) tokens; "first_page": false suppresses page 1. "page_number_format" is "arabic", "roman", or "ROMAN"; "front_matter_pages": N numbers the first N pages i, ii, ... and restarts the body at 1.

## Block Element Types

### Heading
```json
{{"type": "heading", "text": "Section Title", "level": 1}}
```
Levels 1-6. Level 1 is the largest.

### Paragraph
```json
{{"type": "paragraph", "text": "Plain text paragraph."}}
```
For inline formatting use "runs" (fields: text, bold, italic, color as 6-digit hex without '#', link):
```json
{{"type": "paragraph", "runs": [
  {{"text": "Normal "}},
  {{"text": "bold", "bold": true}},
  {{"text": " and "}},
  {{"text": "italic", "italic": true}}
]}}
```

### Table
```json
{{"type": "table", "headers": ["Col A", "Col B"], "rows": [["val1", "val2"]], "caption": "Optional caption", "stripe": true}}
```
Cells are strings, or objects for formatting: {{"value": "$1,234.56", "align": "decimal"}} aligns numbers on the decimal point.

### Bullet List
```json
{{"type": "bullets", "items": ["First item", "Second item"]}}
```
"items" is a flat list of strings.

### Numbered List
```json
{{"type": "numbered", "items": ["Step one", "Step two"], "start": 1}}
```

### Code Block
```json
{{"type": "code_block", "code": "def hello():\\n    print('hi')", "language": "python", "line_numbers": true}}
```
Languages: python, javascript, typescript, sql, json, html, css, rust, go, java, c, text.

### Math Block
```json
{{"type": "math", "source": "E = mc^2", "number": true, "label": "eq:energy"}}
```
LaTeX syntax: superscripts (^), subscripts (_), \\frac, \\sqrt, \\sum, \\int, Greek letters. Set "number": true to right-flush an auto-assigned equation number; give a "label" so text can reference it with @eq:energy or \\eqref{{energy}} (resolves to "(3)" with a link). "tag" overrides the number text.

### Image
```json
{{"type": "image", "source": "path/to/image.png", "width": 400, "caption": "Figure caption", "alt_text": "Description for accessibility"}}
```

### Callout / Admonition
```json
{{"type": "callout", "text": "Important information here.", "variant": "note", "title": "Note"}}
```
Variants: info, warning, success, danger, note.

### Horizontal Rule
```json
{{"type": "rule"}}
```

### Page Break
```json
{{"type": "page_break"}}
```

### Chart
```json
{{"type": "chart", "chart_type": "bar", "labels": ["Q1", "Q2"], "values": [100, 150], "title": "Revenue"}}
```
Multi-series (grouped bars, multi-line, or scatter) with axis titles and legend:
```json
{{"type": "chart", "chart_type": "scatter", "labels": ["Q1", "Q2"], "series": [{{"label": "North", "values": [100, 150]}}, {{"label": "South", "values": [90, 120]}}], "x_title": "Quarter", "y_title": "Units"}}
```
Types: bar, line, pie, scatter. Pie uses the first series only.

### Diagram
Architecture and workflow graphs as node/edge lists; layout, arrow routing, and alt text are automatic (cycles are fine):
```json
{{"type": "diagram", "direction": "down", "nodes": [{{"id": "api", "label": "API Gateway"}}, {{"id": "auth", "label": "Auth Service"}}, {{"id": "db", "label": "User Store", "shape": "store"}}, {{"id": "ok", "label": "Response", "shape": "rounded"}}], "edges": [{{"src": "api", "dst": "auth", "label": "verify"}}, {{"src": "auth", "dst": "db"}}, {{"src": "db", "dst": "auth", "style": "dashed"}}, {{"src": "auth", "dst": "ok"}}], "caption": "Login flow"}}
```
Node shapes: box, rounded, decision (diamond), store (database), start_end. Edge "style": "dashed" marks optional/async paths; "direction" is "down" or "right".

### Architecture Diagram
System/cloud topology with built-in service glyphs and nested boundary zones (VPC / subnet / account). Nodes carry a "service" glyph; "groups" enclose member node/group ids:
```json
{{"type": "architecture_diagram", "direction": "down", "nodes": [{{"id": "u", "label": "User", "service": "user"}}, {{"id": "cdn", "label": "CDN", "service": "cdn"}}, {{"id": "api", "label": "API", "service": "compute", "group": "vpc"}}, {{"id": "db", "label": "Postgres", "service": "database", "group": "vpc"}}, {{"id": "q", "label": "Jobs", "service": "queue", "group": "vpc"}}], "groups": [{{"id": "vpc", "label": "VPC", "node_ids": ["api", "db", "q"]}}], "edges": [{{"src": "u", "dst": "cdn"}}, {{"src": "u", "dst": "api", "label": "https"}}, {{"src": "api", "dst": "db", "label": "sql"}}, {{"src": "api", "dst": "q", "style": "dashed"}}], "caption": "Request path"}}
```
Services: compute, database, storage, queue, gateway, cache, cdn, function, loadbalancer, user, external, generic. Groups may nest by listing another group id in "node_ids".

### Sequence Diagram
Participant lifelines with time-ordered messages (top to bottom). Message "style": "sync" (filled arrow), "async" (open arrow), "return" (dashed); "activate": true draws an activation bar:
```json
{{"type": "sequence_diagram", "participants": [{{"id": "u", "label": "User"}}, {{"id": "api", "label": "API"}}, {{"id": "db", "label": "Database"}}], "messages": [{{"src": "u", "dst": "api", "label": "POST /login", "style": "sync", "activate": true}}, {{"src": "api", "dst": "db", "label": "SELECT user", "style": "async"}}, {{"src": "db", "dst": "api", "label": "row", "style": "return"}}, {{"src": "api", "dst": "u", "label": "token", "style": "return"}}], "caption": "Login sequence"}}
```
A message with equal "src" and "dst" renders as a self-loop.

### Entity-Relationship Diagram
Entity tables with attributes and cardinality-labeled relationships. Mark keys with "key": "PK" or "FK":
```json
{{"type": "er_diagram", "entities": [{{"id": "user", "name": "User", "attributes": [{{"name": "id", "key": "PK", "type": "int"}}, {{"name": "email", "type": "text"}}]}}, {{"id": "order", "name": "Order", "attributes": [{{"name": "id", "key": "PK", "type": "int"}}, {{"name": "user_id", "key": "FK", "type": "int"}}]}}], "relationships": [{{"src": "user", "dst": "order", "label": "places", "src_card": "1", "dst_card": "N"}}]}}
```
Cardinality is any short label ("1", "N", "0..1", "1..N").

### Front Matter & Executive Elements
"cover_page" fills a page (no header/footer) and forces a page break:
```json
{{"type": "cover_page", "title": "Annual Report", "subtitle": "FY2025", "authors": ["Jane Doe"], "date": "July 2026", "kicker": "Confidential"}}
```
```json
{{"type": "abstract", "text": "We present a layout engine.", "keywords": ["layout", "typography"]}}
```
```json
{{"type": "authors", "authors": [{{"name": "Ada Lovelace", "affiliation": "Analytical Engine", "email": "ada@x.io"}}]}}
```
```json
{{"type": "pull_quote", "text": "Simplicity is the ultimate sophistication.", "attribution": "da Vinci"}}
```
"stat_tiles" draws a row of bordered tiles; deltas are colored by sign:
```json
{{"type": "stat_tiles", "stats": [{{"label": "Revenue", "value": "$4.5M", "delta": "+12%"}}, {{"label": "Churn", "value": "2.1%", "delta": "-0.3%"}}]}}
```

### Table of Contents / Figures / Tables
```json
{{"type": "toc", "title": "Contents", "depth": 3, "source": "headings"}}
```
Renders a visible listing with dot leaders, real page numbers, and clickable links. "source" is "headings", "figures", or "tables".

### Appendix, Index, Glossary
```json
{{"type": "appendix", "title": "Survey Instrument", "content": [{{"type": "paragraph", "text": "..."}}]}}
```
Wraps nested blocks in a lettered section ("Appendix A", "Appendix B", ...) with its own headings numbered "A.1", "A.2".
```json
{{"type": "index", "title": "Index"}}
```
Renders a two-column back-of-book index. Mark index terms on a paragraph's "runs" with `"index_terms": ["term"]` (no visible effect); include at most one "index" block, near the end.
```json
{{"type": "glossary", "entries": [{{"term": "Latency", "definition": "Time to first byte."}}]}}
```
Alphabetized bold-term/definition list; each term's first body occurrence is auto-linked to its entry.

## Rules
1. Always output valid JSON — no comments, no trailing commas.
2. The "type" field is required on every content block.
3. Use professional, precise language appropriate for the document style.
4. Structure content with clear headings and logical flow.
5. Use tables for comparative or tabular data.
6. Use code blocks with the correct language tag for any code.
7. Use math blocks for equations and formulas.
8. Set "toc": true for long documents with many sections.
{feature_hints}
Output ONLY the JSON object, no surrounding text or markdown fences.{exemplar_section}"""


def _strip_fences(text: str) -> str:
    """Remove a surrounding markdown code fence if present."""
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return text


def _repair_truncation(text: str) -> str:
    """Deterministically close an unterminated string and balance brackets."""
    stack: list[str] = []
    in_string = False
    escape = False
    prev_sig = ""
    string_ctx = ""
    for ch in text:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
                prev_sig = '"'
        else:
            if ch == '"':
                in_string = True
                string_ctx = prev_sig
            elif ch in "{[":
                stack.append(ch)
                prev_sig = ch
            elif ch in "}]":
                if stack:
                    stack.pop()
                prev_sig = ch
            elif not ch.isspace():
                prev_sig = ch

    if in_string:
        if escape:
            text = text[:-1]
        text += '"'
        if stack and stack[-1] == "{" and string_ctx in ("{", ","):
            text += ": null"
    else:
        text = text.rstrip()
        if text.endswith(","):
            text = text[:-1]
        elif text.endswith(":"):
            text += " null"

    for opener in reversed(stack):
        text += "}" if opener == "{" else "]"
    return text


def _warn(on_warning: Callable[[str], None] | None, message: str) -> None:
    """Send a recovery message to the warning callback, if any."""
    if on_warning is not None:
        on_warning(message)


def _coerce_block(block) -> dict | None:
    """Turn an invalid content block into a paragraph, or None if empty."""
    if isinstance(block, str):
        return {"type": "paragraph", "text": block} if block.strip() else None
    if not isinstance(block, dict):
        return None
    for key in ("text", "content", "code", "source"):
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            return {"type": "paragraph", "text": value}
    return None


def _recover_document(
    data: dict, on_warning: Callable[[str], None] | None
) -> "Document":
    """Rebuild a Document by validating each content block independently."""
    from pydantic import TypeAdapter, ValidationError

    from .adapters.pydantic_schema import ContentBlock, DocumentSpec

    adapter = TypeAdapter(ContentBlock)
    blocks = []
    for i, block in enumerate(data.get("content") or []):
        try:
            adapter.validate_python(block)
        except ValidationError:
            coerced = _coerce_block(block)
            if coerced is None:
                _warn(on_warning, f"content[{i}] invalid; dropped")
                continue
            _warn(on_warning, f"content[{i}] invalid; coerced to paragraph")
            block = coerced
        blocks.append(block)

    healed = {k: v for k, v in data.items() if k != "content"}
    healed["content"] = blocks or [{"type": "paragraph", "text": " "}]
    if not healed.get("title"):
        healed["title"] = "Untitled"

    try:
        return DocumentSpec.model_validate(healed).to_document()
    except ValidationError:
        _warn(on_warning, "document-level validation failed; manual parse")
        return _manual_parse(healed)


def parse_spec_json(
    json_str: str,
    *,
    strict: bool = False,
    smart: bool = False,
    on_warning: Callable[[str], None] | None = None,
    **overrides,
) -> "Document":
    """Parse an EmbossSpec JSON string into a Document.

    Handles common LLM output quirks: markdown fences around JSON,
    trailing commas, truncated output, and invalid content blocks.

    Args:
        json_str: JSON string (optionally wrapped in ```json ... ```)
        strict: raise instead of repairing malformed input
        smart: apply content intelligence (typography, tables, auto-style)
        on_warning: callback receiving a message per repair performed
        **overrides: Document-level overrides (style, page, legal, etc.)
    """
    text = _strip_fences(json_str)
    text = re.sub(r",\s*([}\]])", r"\1", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        if strict:
            raise
        data = json.loads(_repair_truncation(text))
        _warn(on_warning, "repaired truncated JSON")

    return _parse_spec_data(
        data, strict=strict, smart=smart, on_warning=on_warning, **overrides
    )


def parse_spec_dict(
    data: dict,
    *,
    strict: bool = False,
    smart: bool = False,
    on_warning: Callable[[str], None] | None = None,
    **overrides,
) -> "Document":
    """Parse an EmbossSpec dict (e.g. forced tool-use input) into a Document."""
    import copy

    return _parse_spec_data(
        copy.deepcopy(data),
        strict=strict,
        smart=smart,
        on_warning=on_warning,
        **overrides,
    )


def _parse_spec_data(
    data: dict,
    *,
    strict: bool = False,
    smart: bool = False,
    on_warning: Callable[[str], None] | None = None,
    **overrides,
) -> "Document":
    """Validate a decoded EmbossSpec dict through the normalize/repair pipeline."""
    for key, value in overrides.items():
        data[key] = value

    _normalize_spec(data)

    try:
        from .adapters.pydantic_schema import DocumentSpec
    except ImportError:
        return _manual_parse(data)

    from pydantic import ValidationError

    try:
        if smart:
            spec = DocumentSpec.from_smart(data)
        else:
            spec = DocumentSpec.model_validate(data)
    except ValidationError as exc:
        if strict:
            raise
        _warn(on_warning, f"validation failed with {exc.error_count()} error(s)")
        doc = _recover_document(data, on_warning)
        _assign_explicit_ids(doc, data)
        return doc
    doc = spec.to_document()
    _assign_explicit_ids(doc, data)
    return doc


def _assign_explicit_ids(doc, data: dict) -> None:
    """Carry explicit block ids from the spec dict onto the parsed elements.

    The pydantic content specs do not model the ``id`` field, so an explicit
    id set in the spec (used for node-scoped patching and annotation
    round-tripping) is reapplied here by position. If the block count diverged
    through normalization or repair, ids are left unassigned rather than
    mapped to the wrong element.
    """
    blocks = [b for b in data.get("content", []) if isinstance(b, dict)]
    if len(blocks) != len(doc.content):
        return
    for block, element in zip(blocks, doc.content):
        node_id = block.get("id")
        if node_id and hasattr(element, "id"):
            element.id = node_id


def _manual_parse(data: dict) -> "Document":
    """Fallback parser when pydantic is not installed."""
    from .spec import (
        Abstract,
        Appendix,
        Author,
        Authors,
        BlockQuote,
        BulletList,
        Callout,
        Chart,
        CodeBlock,
        CoverPage,
        Document,
        Glossary,
        GlossaryEntry,
        Heading,
        HorizontalRule,
        Image,
        Index,
        MathBlock,
        NumberedList,
        PageBreak,
        PullQuote,
        Stat,
        StatTiles,
        Table,
        TableOfContents,
    )

    _normalize_spec(data)

    doc = Document(
        title=data.get("title", "Untitled"),
        author=data.get("author", ""),
        subject=data.get("subject", ""),
        keywords=data.get("keywords", ""),
        style=data.get("style", "corporate"),
        toc=bool(data.get("toc", False)),
    )

    type_map = {
        "heading": lambda b: Heading(text=b.get("text", ""), level=b.get("level", 1)),
        "paragraph": lambda b: _parse_paragraph(b),
        "bullets": lambda b: BulletList(items=b.get("items", [])),
        "numbered": lambda b: NumberedList(
            items=b.get("items", []), start=b.get("start", 1)
        ),
        "table": lambda b: Table(
            headers=b.get("headers", []),
            rows=b.get("rows", []),
            caption=b.get("caption"),
            stripe=b.get("stripe", False),
        ),
        "code_block": lambda b: CodeBlock(
            code=b.get("code", ""),
            language=b.get("language", "text"),
            line_numbers=b.get("line_numbers", False),
        ),
        "math": lambda b: MathBlock(
            source=b.get("source", ""),
            display=b.get("display", True),
            caption=b.get("caption"),
            label=b.get("label"),
            number=b.get("number", False),
            tag=b.get("tag"),
        ),
        "cover_page": lambda b: CoverPage(
            title=b.get("title", ""),
            subtitle=b.get("subtitle", ""),
            authors=tuple(b.get("authors", ())),
            date=b.get("date", ""),
            kicker=b.get("kicker", ""),
        ),
        "abstract": lambda b: Abstract(
            text=b.get("text", ""), keywords=tuple(b.get("keywords", ()))
        ),
        "authors": lambda b: Authors(
            authors=[
                Author(**a) if isinstance(a, dict) else Author(name=str(a))
                for a in b.get("authors", [])
            ]
        ),
        "pull_quote": lambda b: PullQuote(
            text=b.get("text", ""), attribution=b.get("attribution", "")
        ),
        "stat_tiles": lambda b: StatTiles(
            stats=[
                Stat(**s) if isinstance(s, dict) else Stat(label="", value=str(s))
                for s in b.get("stats", [])
            ]
        ),
        "toc": lambda b: TableOfContents(
            title=b.get("title", "Contents"),
            depth=b.get("depth", 3),
            source=b.get("source", "headings"),
        ),
        "image": lambda b: Image(
            source=b.get("source", ""),
            alt_text=b.get("alt_text", ""),
            width=b.get("width"),
            caption=b.get("caption"),
        ),
        "chart": lambda b: Chart(
            chart_type=b.get("chart_type", "bar"),
            labels=b.get("labels", []),
            values=b.get("values", []),
            title=b.get("title"),
        ),
        "callout": lambda b: Callout(
            content=b.get("text", ""),
            variant=b.get("variant", "note"),
            title=b.get("title"),
        ),
        "blockquote": lambda b: BlockQuote(
            content=b.get("text", ""),
            attribution=b.get("attribution"),
        ),
        "rule": lambda b: HorizontalRule(),
        "page_break": lambda b: PageBreak(page_style=b.get("page_style")),
        "diagram": lambda b: _parse_diagram(b),
        "architecture_diagram": lambda b: _parse_architecture(b),
        "sequence_diagram": lambda b: _parse_sequence(b),
        "er_diagram": lambda b: _parse_er(b),
    }
    type_map["index"] = lambda b: Index(title=b.get("title", "Index"))
    type_map["glossary"] = lambda b: Glossary(
        title=b.get("title", "Glossary"),
        entries=[
            GlossaryEntry(term=e.get("term", ""), definition=e.get("definition", ""))
            for e in b.get("entries", [])
            if isinstance(e, dict)
        ],
    )
    type_map["appendix"] = lambda b: Appendix(
        title=b.get("title", ""),
        content=[
            type_map[child["type"]](child)
            for child in b.get("content", [])
            if isinstance(child, dict) and child.get("type") in type_map
        ],
    )

    for block in data.get("content", []):
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "")
        builder = type_map.get(block_type)
        if builder:
            element = builder(block)
            node_id = block.get("id")
            if node_id and hasattr(element, "id"):
                element.id = node_id
            doc.add(element)

    return doc


def _parse_diagram(block: dict):
    """Parse a diagram block in the no-pydantic fallback path."""
    from .diagrams import diagram_svg_block

    return diagram_svg_block(
        block.get("nodes", []),
        block.get("edges", []),
        direction=block.get("direction", "down"),
        caption=block.get("caption"),
    )


def _parse_architecture(block: dict):
    """Parse an architecture_diagram block in the no-pydantic fallback path."""
    from .diagrams import architecture_svg_block

    return architecture_svg_block(
        block.get("nodes", []),
        block.get("edges", []),
        groups=block.get("groups"),
        direction=block.get("direction", "down"),
        caption=block.get("caption"),
    )


def _parse_sequence(block: dict):
    """Parse a sequence_diagram block in the no-pydantic fallback path."""
    from .diagrams import sequence_svg_block

    return sequence_svg_block(
        block.get("participants", []),
        block.get("messages", []),
        caption=block.get("caption"),
    )


def _parse_er(block: dict):
    """Parse an er_diagram block in the no-pydantic fallback path."""
    from .diagrams import er_svg_block

    return er_svg_block(
        block.get("entities", []),
        block.get("relationships", []),
        caption=block.get("caption"),
    )


def _parse_paragraph(block: dict):
    """Parse a paragraph block, handling both plain text and runs."""
    from .spec import Paragraph, TextRun

    if "runs" in block:
        runs = []
        for r in block["runs"]:
            runs.append(
                TextRun(
                    text=r.get("text", ""),
                    bold=r.get("bold", False),
                    italic=r.get("italic", False),
                    color=r.get("color"),
                    font_family=r.get("font_family"),
                )
            )
        return Paragraph(content=runs)
    return Paragraph(content=block.get("text", ""))


_FENCED_JSON_RE = re.compile(r"```json\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def _balanced_object_end(text: str, start: int) -> int:
    """Return the index of the } closing the { at `start`, or -1."""
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _extract_json_candidate(text: str) -> str | None:
    """Find EmbossSpec JSON inside chat output: fenced block, then bare object."""
    fenced = _FENCED_JSON_RE.search(text)
    if fenced:
        return fenced.group(1).strip()
    start = text.find("{")
    while start != -1:
        end = _balanced_object_end(text, start)
        if end != -1 and '"content"' in text[start : end + 1]:
            return text[start : end + 1]
        start = text.find("{", start + 1)
    return None


def _extract_mathml(text: str) -> str:
    """Return the <math>...</math> fragment embedded in `text`."""
    start = text.find("<math")
    if start == -1:
        return text.strip()
    end = text.find("</math>", start)
    if end == -1:
        return text[start:].strip()
    return text[start : end + len("</math>")].strip()


def document_from_llm_text(text: str, **kw) -> "Document":
    """Route raw LLM output to JSON, MathML, or Markdown Document parsing."""
    from .spec import Document, MathBlock

    candidate = _extract_json_candidate(text)
    if candidate is not None:
        try:
            return parse_spec_json(candidate, **kw)
        except (ValueError, TypeError, KeyError):
            pass
    stripped = text.strip()
    if stripped.startswith("<math") or "<math xmlns" in stripped:
        title = kw.pop("title", "") or "Equation"
        return Document(
            title=title, content=[MathBlock(source=_extract_mathml(stripped))], **kw
        )
    return Document.from_markdown(text, **kw)


def generate(
    prompt: str,
    *,
    style: str = "corporate",
    output: str | None = None,
    provider: Literal["anthropic", "openai"] = "anthropic",
    model: str | None = None,
    api_key: str | None = None,
    smart: bool = False,
    structured: bool = True,
    max_repair_rounds: int = 0,
    **doc_overrides,
) -> bytes:
    """Generate a PDF from a natural language prompt via LLM.

    This is the full pipeline: builds a system prompt with the EmbossSpec
    format, calls the LLM, parses the JSON response, and renders to PDF.

    Args:
        prompt: What document to create (e.g. "Write a quarterly financial report")
        style: Style preset (legal/finance/academic/corporate/minimal/journal/brief)
        output: Optional file path to save the PDF
        provider: LLM provider ("anthropic" or "openai")
        model: Model name (defaults to claude-sonnet-5 or gpt-4o)
        api_key: API key (or set ANTHROPIC_API_KEY / OPENAI_API_KEY env var)
        smart: Apply content intelligence to the parsed spec
        structured: Use constrained decoding (forced tool-use / JSON schema mode)
        max_repair_rounds: LLM correction rounds when validation fails
        **doc_overrides: Additional Document-level settings (legal, header, footer, etc.)

    Returns:
        PDF bytes
    """
    system = spec_prompt(style=style)

    if provider == "anthropic":
        call, model = _call_anthropic, model or "claude-sonnet-5"
    elif provider == "openai":
        call, model = _call_openai, model or "gpt-4o"
    else:
        raise ValueError(
            f"Unknown provider: {provider!r}. Use 'anthropic' or 'openai'."
        )

    strict = max_repair_rounds > 0
    raw = call(prompt, system, model, api_key, structured=structured)
    doc = None
    for round_index in range(max_repair_rounds + 1):
        try:
            doc = _parse_llm_result(
                raw, strict=strict, smart=smart, style=style, **doc_overrides
            )
            break
        except ValueError as exc:
            if round_index == max_repair_rounds:
                raise
            previous = raw if isinstance(raw, str) else json.dumps(raw)
            correction = (
                f"Your previous output failed validation: {exc}. "
                "Return the corrected complete JSON."
            )
            history = [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": previous},
            ]
            raw = call(
                correction,
                system,
                model,
                api_key,
                structured=structured,
                history=history,
            )

    pdf_bytes = doc.render()

    if output:
        from pathlib import Path

        Path(output).write_bytes(pdf_bytes)

    return pdf_bytes


def _parse_llm_result(
    raw: str | dict, *, strict: bool, smart: bool, **overrides
) -> "Document":
    """Parse a provider result: dicts skip string parsing entirely."""
    if isinstance(raw, dict):
        return parse_spec_dict(raw, strict=strict, smart=smart, **overrides)
    return parse_spec_json(raw, strict=strict, smart=smart, **overrides)


def _call_anthropic(
    prompt: str,
    system: str,
    model: str,
    api_key: str | None,
    *,
    structured: bool = False,
    history: list[dict] | None = None,
) -> str | dict:
    """Call the Anthropic Messages API, forcing tool-use when structured."""
    import os

    try:
        from anthropic import Anthropic
    except ImportError:
        raise ImportError(
            "anthropic package is required for generate().\n  pip install anthropic"
        ) from None

    client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    messages = [*(history or []), {"role": "user", "content": prompt}]
    if structured:
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            system=system,
            messages=messages,
            tools=[
                {
                    "name": "emit_document",
                    "description": "Emit the complete EmbossSpec document.",
                    "input_schema": spec_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": "emit_document"},
        )
        return next(b.input for b in response.content if b.type == "tool_use")
    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=system,
        messages=messages,
    )
    return next(b.text for b in response.content if b.type == "text")


def _call_openai(
    prompt: str,
    system: str,
    model: str,
    api_key: str | None,
    *,
    structured: bool = False,
    history: list[dict] | None = None,
) -> str:
    """Call the OpenAI Chat Completions API, in strict JSON-schema mode when structured."""
    import os

    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError(
            "openai package is required for generate() with provider='openai'.\n"
            "  pip install openai"
        ) from None

    client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
    messages = [
        {"role": "system", "content": system},
        *(history or []),
        {"role": "user", "content": prompt},
    ]
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": 8192,
        "temperature": 0.3,
    }
    if structured:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "emboss_spec",
                "schema": _strict_schema(spec_schema()),
                "strict": True,
            },
        }
    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content
