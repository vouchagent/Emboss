"""Generate comprehensive content via Claude Sonnet 5, render with Emboss,
and produce an HTML equivalent for side-by-side comparison.

Run:
    python examples/llm_comparison.py

Output:
    examples/output/llm_generated.pdf   - Emboss render
    examples/output/llm_generated.html  - HTML equivalent (open in browser, print to PDF)
"""

import json
import os
import sys
from pathlib import Path

# Load API key from .env
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from anthropic import Anthropic

from emboss import (
    Document, TextRun, Citation, LegalFeatures,
)

OUTPUT = Path(__file__).parent / "output"
OUTPUT.mkdir(exist_ok=True)

CONTENT_PROMPT = """\
You are generating structured content for a comprehensive technical document.
Return ONLY valid JSON matching the schema below. No markdown, no explanation.

The document topic: "Distributed Systems: Consensus Algorithms and Fault Tolerance"

This should be a real, factual technical reference covering:
1. Introduction to distributed consensus
2. The CAP theorem with a data table
3. Paxos algorithm with pseudocode
4. Raft algorithm with pseudocode
5. Byzantine fault tolerance
6. Performance benchmarks (table with numbers)
7. Mathematical foundations (formal proofs, probability)
8. Implementation considerations (code example)
9. Bibliography with real references

IMPORTANT STYLE RULES:
- Write in clear, direct technical prose
- Use hyphens (-) not em-dashes
- Use straight quotes, not curly quotes
- No filler phrases like "In today's world" or "It is worth noting"
- Every sentence should carry specific technical information
- Tables must have real numeric data
- Code must be syntactically correct
- Math must be valid LaTeX-subset notation
- Bibliography entries must reference real published works

JSON Schema:
{
  "title": "string",
  "author": "string",
  "sections": [
    {
      "heading": "string",
      "level": 1,
      "elements": [
        {"type": "paragraph", "text": "string"},
        {"type": "paragraph_rich", "runs": [{"text": "string", "bold": false, "italic": false, "color": null}]},
        {"type": "bullets", "items": ["string"]},
        {"type": "table", "headers": ["string"], "rows": [["string"]], "caption": "string", "stripe": true},
        {"type": "code", "code": "string", "language": "string", "caption": "string"},
        {"type": "math", "source": "string", "caption": "string"},
        {"type": "callout", "text": "string", "variant": "info|warning|success|danger"},
        {"type": "chart", "chart_type": "bar|line|pie", "labels": ["string"], "values": [0], "title": "string"},
        {"type": "footnote", "text": "string", "marker": "string"},
        {"type": "bibliography", "citations": [{"key": "string", "authors": ["string"], "title": "string", "year": "string", "publisher": "string", "journal": "string", "volume": "string", "pages": "string", "entry_type": "article|book|inproceedings"}]}
      ]
    }
  ]
}

Generate at least 8 sections with diverse element types. Include at least:
- 3 tables with numeric data
- 3 code blocks (different languages)
- 5 math formulas
- 2 charts
- 4 callouts
- 2 rich text paragraphs with bold/italic
- 1 bibliography with at least 5 real references
Aim for roughly 2500 words of content total.
"""


def call_claude(api_key: str) -> dict:
    """Call Claude Sonnet 5 and parse the JSON response."""
    client = Anthropic(api_key=api_key)

    print("Calling Claude Sonnet 5 for content generation...")
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=8192,
        messages=[{"role": "user", "content": CONTENT_PROMPT}],
    )

    text = next(b.text for b in response.content if b.type == "text").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]

    data = json.loads(text)
    print(f"  Received {len(data.get('sections', []))} sections")
    return data


def build_pdf(data: dict) -> bytes:
    """Convert structured content to Emboss."""
    doc = Document(
        title=data.get("title", "Generated Document"),
        author=data.get("author", ""),
        language="en-US",
        style="academic",
        header_text=data.get("title", ""),
        page_numbers=True,
        tagged=True,
        toc=True,
    )

    for si, section in enumerate(data.get("sections", [])):
        if si > 0:
            doc.page_break()

        doc.heading(section["heading"], level=section.get("level", 1))

        for elem in section.get("elements", []):
            etype = elem.get("type", "")

            if etype == "paragraph":
                doc.paragraph(elem["text"])

            elif etype == "paragraph_rich":
                runs = []
                for r in elem.get("runs", []):
                    runs.append(TextRun(
                        text=r["text"],
                        bold=r.get("bold", False),
                        italic=r.get("italic", False),
                        color=r.get("color"),
                    ))
                doc.paragraph(runs)

            elif etype == "bullets":
                doc.bullets(elem["items"])

            elif etype == "table":
                doc.table(
                    headers=elem["headers"],
                    rows=elem["rows"],
                    caption=elem.get("caption"),
                    stripe=elem.get("stripe", False),
                )

            elif etype == "code":
                doc.code_block(
                    code=elem["code"],
                    language=elem.get("language", "text"),
                    line_numbers=True,
                    theme="dark_modern",
                    caption=elem.get("caption"),
                )

            elif etype == "math":
                doc.math(
                    elem["source"],
                    caption=elem.get("caption"),
                )

            elif etype == "callout":
                doc.callout(
                    elem["text"],
                    variant=elem.get("variant", "info"),
                )

            elif etype == "chart":
                doc.chart(
                    chart_type=elem.get("chart_type", "bar"),
                    labels=elem["labels"],
                    values=[float(v) for v in elem["values"]],
                    title=elem.get("title"),
                )

            elif etype == "footnote":
                doc.footnote(
                    elem["text"],
                    marker=elem.get("marker"),
                )

            elif etype == "bibliography":
                citations = []
                for c in elem.get("citations", []):
                    citations.append(Citation(
                        key=c["key"],
                        authors=c.get("authors", []),
                        title=c.get("title", ""),
                        year=c.get("year", ""),
                        publisher=c.get("publisher"),
                        journal=c.get("journal"),
                        volume=c.get("volume"),
                        pages=c.get("pages"),
                        entry_type=c.get("entry_type", "article"),
                    ))
                doc.bibliography(citations=citations)

    return doc.render()


def build_html(data: dict) -> str:
    """Convert the same structured content to standalone HTML for comparison."""
    parts = []
    parts.append("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
@page {{ size: letter; margin: 1in; }}
body {{
    font-family: 'Times New Roman', 'Georgia', serif;
    font-size: 11pt;
    line-height: 1.5;
    max-width: 7.5in;
    margin: 0 auto;
    padding: 1in;
    color: #1a1a1a;
}}
h1 {{ font-size: 20pt; margin-top: 24pt; margin-bottom: 12pt; color: #111; }}
h2 {{ font-size: 16pt; margin-top: 20pt; margin-bottom: 10pt; color: #222; }}
h3 {{ font-size: 13pt; margin-top: 16pt; margin-bottom: 8pt; color: #333; }}
table {{
    border-collapse: collapse;
    width: 100%;
    margin: 12pt 0;
    font-size: 10pt;
}}
th, td {{
    border: 1px solid #ccc;
    padding: 6pt 10pt;
    text-align: left;
}}
th {{ background: #f0f0f0; font-weight: bold; }}
tr:nth-child(even) {{ background: #fafafa; }}
caption {{ font-style: italic; margin-bottom: 6pt; font-size: 10pt; color: #666; }}
pre {{
    background: #1e1e2e;
    color: #cdd6f4;
    padding: 12pt;
    border-radius: 4pt;
    overflow-x: auto;
    font-size: 9pt;
    line-height: 1.4;
    font-family: 'Courier New', monospace;
}}
.caption {{ font-style: italic; font-size: 10pt; color: #666; margin-top: 4pt; }}
.math {{
    display: block;
    text-align: center;
    font-family: 'Times New Roman', serif;
    font-size: 12pt;
    margin: 12pt 0;
    font-style: italic;
}}
.callout {{
    padding: 10pt 14pt;
    border-left: 3pt solid;
    margin: 12pt 0;
    border-radius: 0 4pt 4pt 0;
    font-size: 10pt;
}}
.callout-info {{ background: #eff6ff; border-color: #3b82f6; }}
.callout-warning {{ background: #fffbeb; border-color: #f59e0b; }}
.callout-success {{ background: #f0fdf4; border-color: #22c55e; }}
.callout-danger {{ background: #fef2f2; border-color: #ef4444; }}
ul {{ margin: 8pt 0; padding-left: 24pt; }}
li {{ margin-bottom: 4pt; }}
.bib {{ font-size: 10pt; margin-left: 24pt; text-indent: -24pt; margin-bottom: 6pt; }}
.footnote {{ font-size: 9pt; color: #666; border-top: 1px solid #ccc; padding-top: 6pt; margin-top: 24pt; }}
.page-break {{ page-break-after: always; }}
</style>
</head>
<body>
""".format(title=_html_escape(data.get("title", "Document"))))

    parts.append(f"<h1>{_html_escape(data.get('title', ''))}</h1>\n")
    if data.get("author"):
        parts.append(f"<p><em>{_html_escape(data['author'])}</em></p>\n")

    for si, section in enumerate(data.get("sections", [])):
        if si > 0:
            parts.append('<div class="page-break"></div>\n')

        level = section.get("level", 1)
        tag = f"h{min(level, 6)}"
        parts.append(f"<{tag}>{_html_escape(section['heading'])}</{tag}>\n")

        for elem in section.get("elements", []):
            etype = elem.get("type", "")

            if etype == "paragraph":
                parts.append(f"<p>{_html_escape(elem['text'])}</p>\n")

            elif etype == "paragraph_rich":
                parts.append("<p>")
                for r in elem.get("runs", []):
                    text = _html_escape(r["text"])
                    if r.get("bold"):
                        text = f"<strong>{text}</strong>"
                    if r.get("italic"):
                        text = f"<em>{text}</em>"
                    if r.get("color"):
                        text = f'<span style="color:#{r["color"]}">{text}</span>'
                    parts.append(text)
                parts.append("</p>\n")

            elif etype == "bullets":
                parts.append("<ul>\n")
                for item in elem["items"]:
                    parts.append(f"  <li>{_html_escape(item)}</li>\n")
                parts.append("</ul>\n")

            elif etype == "table":
                parts.append("<table>\n")
                if elem.get("caption"):
                    parts.append(f"  <caption>{_html_escape(elem['caption'])}</caption>\n")
                parts.append("  <thead><tr>")
                for h in elem["headers"]:
                    parts.append(f"<th>{_html_escape(h)}</th>")
                parts.append("</tr></thead>\n  <tbody>\n")
                for row in elem["rows"]:
                    parts.append("    <tr>")
                    for cell in row:
                        parts.append(f"<td>{_html_escape(str(cell))}</td>")
                    parts.append("</tr>\n")
                parts.append("  </tbody>\n</table>\n")

            elif etype == "code":
                lang = elem.get("language", "text")
                parts.append(f"<pre><code>")
                parts.append(_html_escape(elem["code"]))
                parts.append("</code></pre>\n")
                if elem.get("caption"):
                    parts.append(f'<p class="caption">{_html_escape(elem["caption"])}</p>\n')

            elif etype == "math":
                parts.append(f'<div class="math">{_html_escape(elem["source"])}</div>\n')
                if elem.get("caption"):
                    parts.append(f'<p class="caption">{_html_escape(elem["caption"])}</p>\n')

            elif etype == "callout":
                variant = elem.get("variant", "info")
                parts.append(f'<div class="callout callout-{variant}">')
                parts.append(_html_escape(elem["text"]))
                parts.append("</div>\n")

            elif etype == "chart":
                parts.append(f'<div style="margin:12pt 0;padding:10pt;background:#f8f9fa;border:1px solid #ddd;border-radius:4pt;">')
                if elem.get("title"):
                    parts.append(f'<strong>{_html_escape(elem["title"])}</strong><br>')
                parts.append(f'<em>[{elem.get("chart_type","bar")} chart]</em><br>')
                labels = elem.get("labels", [])
                values = elem.get("values", [])
                for l, v in zip(labels, values):
                    parts.append(f'{_html_escape(str(l))}: {v}<br>')
                parts.append("</div>\n")

            elif etype == "footnote":
                marker = elem.get("marker", "*")
                parts.append(f'<div class="footnote"><sup>{_html_escape(marker)}</sup> {_html_escape(elem["text"])}</div>\n')

            elif etype == "bibliography":
                parts.append("<h3>References</h3>\n")
                for i, c in enumerate(elem.get("citations", []), 1):
                    authors = ", ".join(c.get("authors", []))
                    title = c.get("title", "")
                    year = c.get("year", "")
                    journal = c.get("journal", "")
                    publisher = c.get("publisher", "")
                    venue = journal or publisher
                    parts.append(f'<p class="bib">[{i}] {_html_escape(authors)}, ')
                    parts.append(f'"{_html_escape(title)}," ')
                    if venue:
                        parts.append(f'<em>{_html_escape(venue)}</em>, ')
                    parts.append(f'{_html_escape(year)}.</p>\n')

    parts.append("</body>\n</html>")
    return "".join(parts)


def _html_escape(text: str) -> str:
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def verify(pdf_bytes: bytes, label: str) -> None:
    """Quick structural verification."""
    checks = {
        "valid_header": pdf_bytes[:5] == b"%PDF-",
        "has_eof": pdf_bytes.rstrip().endswith(b"%%EOF"),
        "has_xref": b"xref" in pdf_bytes or b"XRef" in pdf_bytes,
        "is_tagged": b"/StructTreeRoot" in pdf_bytes,
        "has_fonts": b"/Font" in pdf_bytes,
        "size_kb": round(len(pdf_bytes) / 1024, 1),
    }
    print(f"\n  {label}")
    print(f"  {'=' * 50}")
    for k, v in checks.items():
        if isinstance(v, bool):
            print(f"  [{'PASS' if v else 'FAIL'}] {k}")
        else:
            print(f"  [INFO] {k}: {v}")


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("Error: Set ANTHROPIC_API_KEY in .env")
        sys.exit(1)

    # Step 1: Generate content via Claude
    data = call_claude(api_key)

    # Save raw JSON for inspection
    json_path = OUTPUT / "llm_content.json"
    json_path.write_text(json.dumps(data, indent=2))
    print(f"  Raw content saved: {json_path}")

    # Step 2: Render with Emboss
    print("\nRendering with Emboss...")
    pdf_bytes = build_pdf(data)
    pdf_path = OUTPUT / "llm_generated.pdf"
    pdf_path.write_bytes(pdf_bytes)
    verify(pdf_bytes, "Emboss Output")
    print(f"  Saved: {pdf_path}")

    # Step 3: Generate HTML equivalent
    print("\nGenerating HTML equivalent...")
    html = build_html(data)
    html_path = OUTPUT / "llm_generated.html"
    html_path.write_text(html)
    print(f"  Saved: {html_path}")
    print(f"  (Open in browser and print to PDF for comparison)")

    # Step 4: Determinism check
    print("\nDeterminism check...")
    pdf2 = build_pdf(data)
    if pdf_bytes == pdf2:
        print("  [PASS] Identical bytes on second render")
    else:
        print("  [FAIL] Output differs between renders")

    print(f"\nDone. Compare:")
    print(f"  PDF: {pdf_path}")
    print(f"  HTML: {html_path}")


if __name__ == "__main__":
    main()
