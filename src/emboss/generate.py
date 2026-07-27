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

__all__ = ["spec_prompt", "generate", "parse_spec_json"]

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


def spec_prompt(
    style: str = "corporate",
    features: list[str] | None = None,
) -> str:
    """Return a system prompt that teaches an LLM the EmbossSpec format.

    The prompt is compact (~2K tokens) and describes every block type with
    examples. Pass it as the system prompt and the LLM will output valid
    EmbossSpec JSON.

    Args:
        style: default style preset to suggest (legal/finance/academic/corporate/minimal)
        features: optional list of features to emphasize (e.g. ["tables", "math", "code"])
    """
    feature_hints = ""
    if features:
        feature_hints = f"\nFocus on these elements: {', '.join(features)}.\n"

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

## Available Styles
- "legal" — serif, justified, generous leading (contracts, briefs)
- "finance" — sans-serif, tight, tabular (reports, filings)
- "academic" — serif body, sans headings, justified (papers, theses)
- "corporate" — sans-serif, readable, roomy (memos, policies)
- "minimal" — compact, minimal ornament (data exports)

## Page Options
```json
{{"page": {{"preset": "a4", "columns": 2, "column_gap": 24}}, "toc": true}}
```
Presets: letter, a4, legal. Use "columns": 2 for two-column layouts (newsletters, academic papers); "column_gap" is in points.

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
{{"type": "math", "source": "E = mc^2"}}
```
LaTeX syntax: superscripts (^), subscripts (_), \\frac, \\sqrt, \\sum, \\int, Greek letters.

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
Types: bar, line, pie.

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
Output ONLY the JSON object, no surrounding text or markdown fences."""


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
        return _recover_document(data, on_warning)
    return spec.to_document()


def _manual_parse(data: dict) -> "Document":
    """Fallback parser when pydantic is not installed."""
    from .spec import (
        BulletList,
        Callout,
        Chart,
        CodeBlock,
        Document,
        Heading,
        HorizontalRule,
        Image,
        MathBlock,
        NumberedList,
        PageBreak,
        Table,
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
        "math": lambda b: MathBlock(source=b.get("source", "")),
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
        "rule": lambda b: HorizontalRule(),
        "page_break": lambda b: PageBreak(),
    }

    for block in data.get("content", []):
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "")
        builder = type_map.get(block_type)
        if builder:
            doc.add(builder(block))

    return doc


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


def generate(
    prompt: str,
    *,
    style: str = "corporate",
    output: str | None = None,
    provider: Literal["anthropic", "openai"] = "anthropic",
    model: str | None = None,
    api_key: str | None = None,
    smart: bool = False,
    **doc_overrides,
) -> bytes:
    """Generate a PDF from a natural language prompt via LLM.

    This is the full pipeline: builds a system prompt with the EmbossSpec
    format, calls the LLM, parses the JSON response, and renders to PDF.

    Args:
        prompt: What document to create (e.g. "Write a quarterly financial report")
        style: Style preset (legal/finance/academic/corporate/minimal)
        output: Optional file path to save the PDF
        provider: LLM provider ("anthropic" or "openai")
        model: Model name (defaults to claude-sonnet-5 or gpt-4o)
        api_key: API key (or set ANTHROPIC_API_KEY / OPENAI_API_KEY env var)
        smart: Apply content intelligence to the parsed spec
        **doc_overrides: Additional Document-level settings (legal, header, footer, etc.)

    Returns:
        PDF bytes
    """
    system = spec_prompt(style=style)

    if provider == "anthropic":
        json_str = _call_anthropic(prompt, system, model or "claude-sonnet-5", api_key)
    elif provider == "openai":
        json_str = _call_openai(prompt, system, model or "gpt-4o", api_key)
    else:
        raise ValueError(
            f"Unknown provider: {provider!r}. Use 'anthropic' or 'openai'."
        )

    doc = parse_spec_json(json_str, smart=smart, style=style, **doc_overrides)
    pdf_bytes = doc.render()

    if output:
        from pathlib import Path

        Path(output).write_bytes(pdf_bytes)

    return pdf_bytes


def _call_anthropic(prompt: str, system: str, model: str, api_key: str | None) -> str:
    """Call the Anthropic Messages API."""
    import os

    try:
        from anthropic import Anthropic
    except ImportError:
        raise ImportError(
            "anthropic package is required for generate().\n  pip install anthropic"
        ) from None

    client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return text


def _call_openai(prompt: str, system: str, model: str, api_key: str | None) -> str:
    """Call the OpenAI Chat Completions API."""
    import os

    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError(
            "openai package is required for generate() with provider='openai'.\n"
            "  pip install openai"
        ) from None

    client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        max_tokens=8192,
        temperature=0.3,
    )
    return response.choices[0].message.content
