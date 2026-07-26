"""Export a DocumentSpec to semantic HTML.

The HTML output preserves the document's semantic structure (headings,
paragraphs, tables with proper thead/tbody, lists) and applies styles
as inline CSS derived from the same style presets that drive the PDF.

This serves two purposes:
  1. Preview: render the document in a browser before committing to PDF.
  2. Interchange: the HTML can be opened in Google Docs, Word, or
     converted to PPTX/DOCX by downstream tools that understand
     semantic HTML better than raw PDF.
"""

from __future__ import annotations

import html as html_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..spec import Document

__all__ = ["to_html"]


def _esc(text: str) -> str:
    return html_module.escape(text)


def _hex_to_css(color: str) -> str:
    return f"#{color}"


def to_html(document: "Document", *, standalone: bool = True) -> str:
    """Convert a Document to semantic HTML.

    When standalone=True, wraps in a complete <!DOCTYPE html> page.
    When standalone=False, returns just the <article> content.
    """
    from ..spec import (
        BibliographyBlock,
        BulletList,
        Callout,
        Chart,
        CodeBlock,
        Footnote,
        Heading,
        HorizontalRule,
        Image,
        MathBlock,
        PageBreak,
        Paragraph,
        Table,
    )

    sheet = document.stylesheet

    parts: list[str] = []
    parts.append('<article class="precisionpdf-document">')

    for element in document.content:
        if isinstance(element, Heading):
            tag = f"h{element.level}"
            style_str = _heading_style(sheet, element.level)
            numbering = f'<span class="numbering">{_esc(element.numbering)} </span>' if element.numbering else ""
            parts.append(f"<{tag}{style_str}>{numbering}{_esc(element.text)}</{tag}>")

        elif isinstance(element, Paragraph):
            runs_html = _render_runs(element.runs)
            body_style = sheet.resolved(sheet.body, element.style)
            style_str = _body_style(body_style)
            parts.append(f"<p{style_str}>{runs_html}</p>")

        elif isinstance(element, BulletList):
            parts.append("<ul>")
            for item_runs in element.item_runs:
                runs_html = _render_runs(item_runs)
                parts.append(f"  <li>{runs_html}</li>")
            parts.append("</ul>")

        elif isinstance(element, Table):
            parts.append(_render_table(element, sheet))

        elif isinstance(element, HorizontalRule):
            parts.append(
                f'<hr style="border:none;border-top:{element.thickness}pt solid #{element.color};'
                f'margin:{element.space_before}pt 0 {element.space_after}pt 0">'
            )

        elif isinstance(element, Image):
            src = _esc(element.source) if isinstance(element.source, str) else ""
            alt = _esc(element.alt_text)
            style_parts = [f"text-align:{element.align}"]
            img_style = "max-width:100%"
            if element.width:
                img_style += f";width:{element.width}pt"
            if element.height:
                img_style += f";height:{element.height}pt"
            parts.append(f'<figure style="{";".join(style_parts)}">')
            parts.append(f'  <img src="{src}" alt="{alt}" style="{img_style}">')
            if element.caption:
                parts.append(f"  <figcaption>{_esc(element.caption)}</figcaption>")
            parts.append("</figure>")

        elif isinstance(element, Chart):
            parts.append(f'<div class="chart" data-type="{element.chart_type}">')
            if element.title:
                parts.append(f"  <p><strong>{_esc(element.title)}</strong></p>")
            parts.append("  <table>")
            parts.append("    <tr>")
            for label in element.labels:
                parts.append(f"      <th>{_esc(str(label))}</th>")
            parts.append("    </tr><tr>")
            for value in element.values:
                parts.append(f"      <td>{_esc(str(value))}</td>")
            parts.append("    </tr>")
            parts.append("  </table>")
            parts.append("</div>")

        elif isinstance(element, Footnote):
            marker = _esc(element.marker or "*")
            runs_html = _render_runs(element.runs)
            parts.append(f'<aside class="footnote"><sup>{marker}</sup> {runs_html}</aside>')

        elif isinstance(element, Callout):
            bg = element.background or "f5f5f4"
            border = element.border_color or "a8a29e"
            runs_html = _render_runs(element.runs)
            title_html = f"<strong>{_esc(element.title)}</strong><br>" if element.title else ""
            icon_html = f'<span class="callout-icon">{_esc(element.icon)}</span> ' if element.icon else ""
            parts.append(
                f'<div class="callout callout-{element.variant}" '
                f'style="background:#{bg};border-left:3px solid #{border};'
                f'padding:10px;border-radius:{element.border_radius}pt;margin:8pt 0">'
                f'{icon_html}{title_html}{runs_html}</div>'
            )

        elif isinstance(element, CodeBlock):
            from ..code_highlight import tokenize, colorize, THEME_BACKGROUNDS
            bg = THEME_BACKGROUNDS.get(element.theme, "1e1e1e")
            lang_attr = f' class="language-{_esc(element.language)}"' if element.language != "text" else ""
            parts.append(f'<pre style="background:#{bg};padding:10px;border-radius:4px;overflow-x:auto;margin:8pt 0"><code{lang_attr}>')
            tokens = tokenize(element.code, element.language)
            colored = colorize(tokens, element.theme)
            for text, color in colored:
                parts.append(f'<span style="color:#{color}">{_esc(text)}</span>')
            parts.append("</code></pre>")
            if element.caption:
                parts.append(f"<p><em>{_esc(element.caption)}</em></p>")

        elif isinstance(element, MathBlock):
            display = "display:block;text-align:center;margin:1em 0" if element.display else "display:inline"
            parts.append(f'<div class="math" style="{display}">')
            parts.append(f"  <code>{_esc(element.source)}</code>")
            parts.append("</div>")
            if element.caption:
                parts.append(f'<p style="text-align:center"><em>{_esc(element.caption)}</em></p>')

        elif isinstance(element, BibliographyBlock):
            from ..bibliography import format_bibliography
            if element.title:
                tag = f"h{element.heading_level}"
                parts.append(f"<{tag}>{_esc(element.title)}</{tag}>")
            entries = format_bibliography(element.citations, element.bib_style)
            parts.append('<ol class="bibliography" style="padding-left:0;list-style:none">')
            for entry in entries:
                parts.append(f"  <li>{_esc(entry)}</li>")
            parts.append("</ol>")

        elif isinstance(element, PageBreak):
            parts.append('<div style="page-break-before:always"></div>')

    parts.append("</article>")
    content = "\n".join(parts)

    if not standalone:
        return content

    base = sheet.resolved(sheet.body)
    font = base.require("font_family")
    size = base.require("font_size")
    color = base.require("color")
    line_h = base.require("line_height")

    return f"""<!DOCTYPE html>
<html lang="{_esc(document.language)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(document.title)}</title>
<style>
body {{
  font-family: {_css_font(font)};
  font-size: {size}pt;
  color: #{color};
  line-height: {line_h};
  max-width: 800px;
  margin: 2em auto;
  padding: 0 1em;
}}
table {{
  border-collapse: collapse;
  width: 100%;
  margin: 1em 0;
}}
th, td {{
  padding: {sheet.table_cell_padding_y}pt {sheet.table_cell_padding_x}pt;
  text-align: left;
  border-bottom: {sheet.table_rule_width}pt solid #{sheet.table_rule_color};
}}
th {{
  font-weight: bold;
  border-bottom: {sheet.table_header_rule_width}pt solid #{sheet.table_header_rule_color};
}}
ul {{ padding-left: 1.5em; }}
li {{ margin-bottom: 0.3em; }}
.stripe-row {{ background: #{sheet.table_stripe_color}; }}
@media print {{
  body {{ max-width: none; margin: 0; padding: 0; }}
  h1, h2, h3, h4, h5, h6 {{ page-break-after: avoid; }}
  table {{ page-break-inside: auto; }}
  tr {{ page-break-inside: avoid; }}
}}
</style>
</head>
<body>
{content}
</body>
</html>"""


def _css_font(family: str) -> str:
    mapping = {
        "Helvetica": "Helvetica, Arial, sans-serif",
        "Times": "'Times New Roman', Times, serif",
        "Courier": "'Courier New', Courier, monospace",
    }
    return mapping.get(family, f"'{family}', sans-serif")


def _heading_style(sheet, level: int) -> str:
    style = sheet.resolved(sheet.for_heading(level))
    parts = []
    parts.append(f"font-size:{style.require('font_size')}pt")
    parts.append(f"color:#{style.require('color')}")
    parts.append(f"line-height:{style.require('line_height')}")
    parts.append(f"margin:{style.require('space_before')}pt 0 {style.require('space_after')}pt 0")
    return f' style="{";".join(parts)}"'


def _body_style(style) -> str:
    parts = []
    align = style.require("align")
    if align != "left":
        parts.append(f"text-align:{align}")
    indent = style.indent_first
    if indent:
        parts.append(f"text-indent:{indent}pt")
    if not parts:
        return ""
    return f' style="{";".join(parts)}"'


def _render_runs(runs: list) -> str:
    parts = []
    for run in runs:
        text = _esc(run.text)
        styles = []
        if run.bold:
            text = f"<strong>{text}</strong>"
        if run.italic:
            text = f"<em>{text}</em>"
        if run.color:
            styles.append(f"color:#{run.color}")
        if run.font_size:
            styles.append(f"font-size:{run.font_size}pt")
        if run.link:
            text = f'<a href="{_esc(run.link)}">{text}</a>'
        if styles:
            text = f'<span style="{";".join(styles)}">{text}</span>'
        parts.append(text)
    return "".join(parts)


def _render_table(table, sheet) -> str:
    parts = ["<table>"]

    if table.caption:
        parts.append(f"  <caption>{_esc(table.caption)}</caption>")

    if table.headers:
        parts.append("  <thead><tr>")
        for cell in table.header_cells:
            align = f' style="text-align:{cell.align}"' if cell.align != "left" else ""
            parts.append(f"    <th{align}>{_esc(cell.plain_text)}</th>")
        parts.append("  </tr></thead>")

    parts.append("  <tbody>")
    for row_idx, row in enumerate(table.body_rows):
        cls = ' class="stripe-row"' if table.stripe and row_idx % 2 == 1 else ""
        parts.append(f"  <tr{cls}>")
        for cell in row:
            style_parts = []
            if cell.align and cell.align not in ("left",):
                css_align = "right" if cell.align == "decimal" else cell.align
                style_parts.append(f"text-align:{css_align}")
            if cell.background:
                style_parts.append(f"background:#{cell.background}")
            style = f' style="{";".join(style_parts)}"' if style_parts else ""
            tag = "td"
            weight = " font-weight:bold;" if cell.bold else ""
            if weight:
                if style:
                    style = style[:-1] + f";{weight.strip()}" + '"'
                else:
                    style = f' style="{weight.strip()}"'
            parts.append(f"    <{tag}{style}>{_esc(cell.plain_text)}</{tag}>")
        parts.append("  </tr>")
    parts.append("  </tbody>")
    parts.append("</table>")
    return "\n".join(parts)
