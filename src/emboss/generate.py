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
from typing import Literal

__all__ = ["spec_prompt", "generate", "parse_spec_json"]


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
  "title": "Document Title (required)",
  "author": "Author Name",
  "style": "{style}",
  "content": [
    // Array of block elements (see types below)
  ]
}}
```

## Available Styles
- "legal" — serif, justified, generous leading (contracts, briefs)
- "finance" — sans-serif, tight, tabular (reports, filings)
- "academic" — serif body, sans headings, justified (papers, theses)
- "corporate" — sans-serif, readable, roomy (memos, policies)
- "minimal" — compact, minimal ornament (data exports)

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
For inline formatting:
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
For numeric columns, use "align": "decimal" on cells to align decimal points.

### Bullet List
```json
{{"type": "bullet_list", "items": ["First item", "Second item"]}}
```
Nested: `"items": ["Top", ["Nested A", "Nested B"]]`

### Numbered List
```json
{{"type": "numbered_list", "items": ["Step one", "Step two"], "start": 1}}
```

### Code Block
```json
{{"type": "code_block", "code": "def hello():\\n    print('hi')", "language": "python", "line_numbers": true}}
```
Languages: python, javascript, typescript, sql, json, html, css, rust, go, java, c, text.

### Math Block
```json
{{"type": "math_block", "source": "E = mc^2"}}
```
LaTeX syntax: superscripts (^), subscripts (_), \\frac, \\sqrt, \\sum, \\int, Greek letters.

### Image
```json
{{"type": "image", "source": "path/to/image.png", "width": 400, "caption": "Figure caption"}}
```

### Callout / Admonition
```json
{{"type": "callout", "content": "Important information here.", "variant": "note", "title": "Note"}}
```
Variants: note, tip, warning, caution, important.

### Horizontal Rule
```json
{{"type": "horizontal_rule"}}
```

### Page Break
```json
{{"type": "page_break"}}
```

### Chart
```json
{{"type": "chart", "chart_type": "bar", "labels": ["Q1", "Q2"], "values": [100, 150], "caption": "Revenue"}}
```
Types: bar, line, pie, scatter.

## Rules
1. Always output valid JSON — no comments, no trailing commas.
2. The "type" field is required on every content block.
3. Use professional, precise language appropriate for the document style.
4. Structure content with clear headings and logical flow.
5. Use tables for comparative or tabular data.
6. Use code blocks with the correct language tag for any code.
7. Use math blocks for equations and formulas.
{feature_hints}
Output ONLY the JSON object, no surrounding text or markdown fences."""


def parse_spec_json(json_str: str, **overrides) -> "Document":
    """Parse an EmbossSpec JSON string into a Document.

    Handles common LLM output quirks: markdown fences around JSON,
    trailing commas, and missing required fields.

    Args:
        json_str: JSON string (optionally wrapped in ```json ... ```)
        **overrides: Document-level overrides (style, page, legal, etc.)
    """
    from .spec import Document

    text = json_str.strip()
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    import re
    text = re.sub(r",\s*([}\]])", r"\1", text)

    data = json.loads(text)

    for key, value in overrides.items():
        data[key] = value

    try:
        from .adapters.pydantic_schema import DocumentSpec
        spec = DocumentSpec.model_validate(data)
        return spec.to_document()
    except ImportError:
        return _manual_parse(data)


def _manual_parse(data: dict) -> "Document":
    """Fallback parser when pydantic is not installed."""
    from .spec import (
        BulletList, Callout, Chart, CodeBlock, Document, Heading,
        HorizontalRule, Image, MathBlock, NumberedList, PageBreak,
        Paragraph, Table, TextRun,
    )

    doc = Document(
        title=data.get("title", "Untitled"),
        author=data.get("author", ""),
        subject=data.get("subject", ""),
        keywords=data.get("keywords", ""),
        style=data.get("style", "corporate"),
    )

    type_map = {
        "heading": lambda b: Heading(text=b.get("text", ""), level=b.get("level", 1)),
        "paragraph": lambda b: _parse_paragraph(b),
        "bullet_list": lambda b: BulletList(items=b.get("items", [])),
        "numbered_list": lambda b: NumberedList(items=b.get("items", []), start=b.get("start", 1)),
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
        "math_block": lambda b: MathBlock(source=b.get("source", "")),
        "image": lambda b: Image(
            source=b.get("source", ""),
            width=b.get("width"),
            caption=b.get("caption"),
        ),
        "chart": lambda b: Chart(
            chart_type=b.get("chart_type", "bar"),
            labels=b.get("labels", []),
            values=b.get("values", []),
            caption=b.get("caption"),
        ),
        "callout": lambda b: Callout(
            content=b.get("content", ""),
            variant=b.get("variant", "note"),
            title=b.get("title"),
        ),
        "horizontal_rule": lambda b: HorizontalRule(),
        "page_break": lambda b: PageBreak(),
    }

    for block in data.get("content", []):
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
            runs.append(TextRun(
                text=r.get("text", ""),
                bold=r.get("bold", False),
                italic=r.get("italic", False),
                color=r.get("color"),
                font_family=r.get("font_family"),
            ))
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
        raise ValueError(f"Unknown provider: {provider!r}. Use 'anthropic' or 'openai'.")

    doc = parse_spec_json(json_str, style=style, **doc_overrides)
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
            "anthropic package is required for generate().\n"
            "  pip install anthropic"
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
