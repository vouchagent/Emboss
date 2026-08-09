"""Tests for the HTML/CSS -> EmbossSpec import adapter.

Covers the supported tag/CSS subset: block and inline tag mapping, the
cascade (tag/class/id specificity, descendant combinators, inline-style
override), CSS custom properties (var()), unit conversion, flex-row ->
Columns compilation, and the documented error cases (remote images).
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import (  # noqa: E402
    BulletList,
    Columns,
    HorizontalRule,
    Image,
    NumberedList,
    Table,
)
from emboss.spec import BlockQuote  # noqa: E402
from emboss.adapters.html_import import import_html  # noqa: E402
from emboss.pdf.verify import verify_pdf  # noqa: E402

# A 1x1 transparent PNG, for data: URI image tests.
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42Y"
    "AAAAASUVORK5CYII="
)


class TestBasicTags:
    def test_headings_and_paragraph(self):
        doc = import_html("<h1>Title</h1><h2>Sub</h2><p>Body text.</p>")
        assert [type(b).__name__ for b in doc.content] == ["Heading", "Heading", "Paragraph"]
        assert doc.content[0].text == "Title"
        assert doc.content[0].level == 1
        assert doc.content[1].level == 2
        assert doc.content[2].plain_text == "Body text."

    def test_empty_paragraph_is_dropped(self):
        doc = import_html("<p>Real</p><p>   </p><p></p>")
        assert len(doc.content) == 1

    def test_bullet_and_numbered_lists(self):
        doc = import_html("<ul><li>a</li><li>b</li></ul><ol><li>x</li><li>y</li></ol>")
        bl, nl = doc.content
        assert isinstance(bl, BulletList)
        assert isinstance(nl, NumberedList)
        assert [r[0].text for r in bl.item_runs] == ["a", "b"]
        assert [r[0].text for r in nl.item_runs] == ["x", "y"]

    def test_nested_list(self):
        doc = import_html(
            "<ul><li>Parent<ul><li>Child one</li><li>Child two</li></ul></li></ul>"
        )
        top = doc.content[0]
        _runs, nested = top.flat_items[-1]
        assert nested is not None
        assert [r[0].text for r in nested.item_runs] == ["Child one", "Child two"]

    def test_hr_and_blockquote(self):
        doc = import_html("<hr><blockquote>Quoted text.</blockquote>")
        assert isinstance(doc.content[0], HorizontalRule)
        assert isinstance(doc.content[1], BlockQuote)
        assert doc.content[1].plain_text == "Quoted text."

    def test_table_with_thead_tbody(self):
        doc = import_html(
            "<table><thead><tr><th>A</th><th>B</th></tr></thead>"
            "<tbody><tr><td>1</td><td>2</td></tr><tr><td>3</td><td>4</td></tr></tbody></table>"
        )
        table = doc.content[0]
        assert isinstance(table, Table)
        assert [c.plain_text for c in table.header_cells] == ["A", "B"]
        assert [[c.plain_text for c in row] for row in table.body_rows] == [
            ["1", "2"],
            ["3", "4"],
        ]

    def test_table_bare_tr_with_th_becomes_header(self):
        doc = import_html("<table><tr><th>A</th></tr><tr><td>1</td></tr></table>")
        table = doc.content[0]
        assert [c.plain_text for c in table.header_cells] == ["A"]
        assert [[c.plain_text for c in row] for row in table.body_rows] == [["1"]]

    def test_table_colspan(self):
        doc = import_html("<table><tr><td colspan='2'>Wide</td></tr></table>")
        table = doc.content[0]
        assert table.body_rows[0][0].colspan == 2

    def test_data_uri_image(self):
        doc = import_html(f'<img src="data:image/png;base64,{_TINY_PNG_B64}" alt="dot">')
        img = doc.content[0]
        assert isinstance(img, Image)
        assert isinstance(img.source, bytes)
        assert img.source == base64.b64decode(_TINY_PNG_B64)
        assert img.alt_text == "dot"

    def test_image_width_height_attrs_convert_px_to_pt(self):
        doc = import_html(
            f'<img src="data:image/png;base64,{_TINY_PNG_B64}" width="100" height="50">'
        )
        img = doc.content[0]
        assert img.width == pytest.approx(75.0)
        assert img.height == pytest.approx(37.5)

    def test_remote_image_raises(self):
        with pytest.raises(ValueError, match="does not fetch remote"):
            import_html('<img src="https://example.com/logo.png">')

    def test_local_path_image_passes_through(self):
        doc = import_html('<img src="assets/logo.png">')
        assert doc.content[0].source == "assets/logo.png"


class TestInlineFormatting:
    def test_bold_italic_code_link(self):
        doc = import_html(
            '<p><b>bold</b> <i>italic</i> <code>code</code> '
            '<a href="https://x.test">link</a></p>'
        )
        runs = doc.content[0].runs
        by_text = {r.text.strip(): r for r in runs if r.text.strip()}
        assert by_text["bold"].bold is True
        assert by_text["italic"].italic is True
        assert by_text["code"].font_family == "Courier"
        assert by_text["link"].link == "https://x.test"

    def test_strong_em_synonyms(self):
        doc = import_html("<p><strong>s</strong><em>e</em></p>")
        runs = [r for r in doc.content[0].runs if r.text]
        assert runs[0].bold is True
        assert runs[1].italic is True

    def test_underline_and_strikethrough(self):
        doc = import_html("<p><u>under</u><s>strike</s></p>")
        runs = [r for r in doc.content[0].runs if r.text]
        assert runs[0].underline is True
        assert runs[1].strikethrough is True

    def test_br_splits_into_separate_paragraphs(self):
        doc = import_html("<p>Line one<br>Line two</p>")
        assert len(doc.content) == 2
        assert doc.content[0].plain_text == "Line one"
        assert doc.content[1].plain_text == "Line two"

    def test_br_nested_inside_inline_element_still_splits(self):
        doc = import_html("<p><span>one<br>two</span></p>")
        assert len(doc.content) == 2
        assert doc.content[0].plain_text == "one"
        assert doc.content[1].plain_text == "two"

    def test_br_inside_table_cell_does_not_crash(self):
        # Table cells have no concept of a hard line break; `<br>` is
        # dropped there rather than corrupting the cell content.
        doc = import_html("<table><tr><td>a<br>b</td></tr></table>")
        assert doc.content[0].body_rows[0][0].plain_text == "ab"

    def test_br_inside_list_item_does_not_crash(self):
        doc = import_html("<ul><li>x<br>y</li></ul>")
        texts = "".join(r.text for r in doc.content[0].item_runs[0])
        assert texts == "xy"

    def test_br_only_blockquote_is_not_empty_block(self):
        doc = import_html("<blockquote>only<br></blockquote>")
        assert len(doc.content) == 1
        assert doc.content[0].plain_text == "only"

    def test_span_inherits_css_color(self):
        html = '<style>.hot { color: #ff0000; }</style><p><span class="hot">warm</span></p>'
        doc = import_html(html)
        run = next(r for r in doc.content[0].runs if r.text == "warm")
        assert run.color == "ff0000"


class TestCssCascade:
    def test_tag_selector(self):
        doc = import_html("<style>p { color: #123456; }</style><p>Text</p>")
        assert doc.content[0].style.color == "123456"

    def test_class_beats_tag(self):
        html = (
            "<style>p { color: #111111; } .special { color: #222222; }</style>"
            '<p class="special">Text</p>'
        )
        doc = import_html(html)
        assert doc.content[0].style.color == "222222"

    def test_id_beats_class(self):
        html = (
            "<style>.special { color: #222222; } #unique { color: #333333; }</style>"
            '<p id="unique" class="special">Text</p>'
        )
        doc = import_html(html)
        assert doc.content[0].style.color == "333333"

    def test_inline_style_beats_everything(self):
        html = (
            "<style>#unique { color: #333333; }</style>"
            '<p id="unique" style="color:#444444">Text</p>'
        )
        doc = import_html(html)
        assert doc.content[0].style.color == "444444"

    def test_descendant_combinator(self):
        html = (
            "<style>div.card p { color: #555555; }</style>"
            '<div class="card"><p>Inside</p></div><p>Outside</p>'
        )
        doc = import_html(html)
        inside, outside = doc.content
        assert inside.style.color == "555555"
        assert outside.style is None

    def test_comma_separated_selectors(self):
        html = "<style>h1, h2 { color: #666666; }</style><h1>A</h1><h2>B</h2>"
        doc = import_html(html)
        assert doc.content[0].style.color == "666666"
        assert doc.content[1].style.color == "666666"

    def test_later_rule_wins_at_equal_specificity(self):
        html = "<style>p { color: #111111; } p { color: #999999; }</style><p>Text</p>"
        doc = import_html(html)
        assert doc.content[0].style.color == "999999"


class TestCssCustomProperties:
    def test_var_resolves_from_root(self):
        html = (
            "<style>:root { --brand: #1a73e8; } h1 { color: var(--brand); }</style>"
            "<h1>Title</h1>"
        )
        doc = import_html(html)
        assert doc.content[0].style.color == "1a73e8"

    def test_var_fallback_used_when_undefined(self):
        html = "<style>h1 { color: var(--missing, #abcdef); }</style><h1>Title</h1>"
        doc = import_html(html)
        assert doc.content[0].style.color == "abcdef"

    def test_var_inherits_down_the_tree(self):
        html = (
            "<style>:root { --brand: #0000aa; } "
            "p { color: var(--brand); }</style>"
            '<div><div><p>Nested</p></div></div>'
        )
        doc = import_html(html)
        assert doc.content[0].style.color == "0000aa"

    def test_local_override_of_custom_property(self):
        html = (
            "<style>:root { --c: #111111; } .scope { --c: #eeeeee; } "
            "p { color: var(--c); }</style>"
            '<div class="scope"><p>Text</p></div>'
        )
        doc = import_html(html)
        assert doc.content[0].style.color == "eeeeee"


class TestUnits:
    def test_px_to_pt(self):
        doc = import_html("<p style='margin-top:16px'>x</p>")
        assert doc.content[0].style.space_before == pytest.approx(12.0)

    def test_pt_passthrough(self):
        doc = import_html("<p style='margin-top:10pt'>x</p>")
        assert doc.content[0].style.space_before == pytest.approx(10.0)

    def test_em_relative_to_parent_size(self):
        doc = import_html(
            "<style>p { font-size: 20pt; margin-top: 1em; }</style><p>x</p>"
        )
        assert doc.content[0].style.space_before == pytest.approx(20.0)

    def test_margin_shorthand_four_values(self):
        doc = import_html("<p style='margin:1pt 2pt 3pt 4pt'>x</p>")
        style = doc.content[0].style
        assert style.space_before == pytest.approx(1.0)
        assert style.indent_right == pytest.approx(2.0)
        assert style.space_after == pytest.approx(3.0)
        assert style.indent_left == pytest.approx(4.0)


class TestFlexColumns:
    def test_flex_row_becomes_columns(self):
        html = (
            '<div style="display:flex"><div><p>Left</p></div>'
            "<div><p>Right</p></div></div>"
        )
        doc = import_html(html)
        assert isinstance(doc.content[0], Columns)
        assert len(doc.content[0].columns) == 2

    def test_flex_weights_become_widths(self):
        html = (
            '<div style="display:flex">'
            '<div style="flex:2"><p>Left</p></div>'
            '<div style="flex:1"><p>Right</p></div></div>'
        )
        doc = import_html(html)
        cols = doc.content[0]
        assert cols.widths == [2.0, 1.0]

    def test_flex_gap_converts_units(self):
        html = '<div style="display:flex;gap:20px"><div><p>A</p></div><div><p>B</p></div></div>'
        doc = import_html(html)
        assert doc.content[0].gap == pytest.approx(15.0)

    def test_non_flex_div_is_transparent_wrapper(self):
        doc = import_html("<div><p>A</p><div><p>B</p></div></div>")
        assert [type(b).__name__ for b in doc.content] == ["Paragraph", "Paragraph"]

    def test_single_child_flex_row_stays_transparent(self):
        doc = import_html('<div style="display:flex"><div><p>Only</p></div></div>')
        assert [type(b).__name__ for b in doc.content] == ["Paragraph"]


class TestStructureAndRobustness:
    def test_fragment_without_html_body_wrapper(self):
        doc = import_html("<h1>Title</h1><p>Body</p>")
        assert len(doc.content) == 2

    def test_unknown_tag_recurses_into_children(self):
        doc = import_html("<custom-widget><p>Inside custom tag</p></custom-widget>")
        assert len(doc.content) == 1
        assert doc.content[0].plain_text == "Inside custom tag"

    def test_title_and_lang_extracted(self):
        doc = import_html(
            '<html lang="fr"><head><title>Mon Titre</title></head>'
            "<body><p>x</p></body></html>"
        )
        assert doc.title == "Mon Titre"
        assert doc.language == "fr"

    def test_script_and_style_content_not_rendered_as_text(self):
        doc = import_html(
            "<style>p{color:#000000}</style><script>alert(1)</script><p>Real text</p>"
        )
        assert len(doc.content) == 1
        assert doc.content[0].plain_text == "Real text"

    def test_bad_data_uri_encoding_raises(self):
        with pytest.raises(ValueError, match="unsupported data URI"):
            import_html('<img src="data:image/png,not-base64">')


class TestFullDocumentRoundTrip:
    def test_realistic_report_renders_to_valid_pdf(self):
        html = """
        <html lang="en">
        <head>
          <title>Quarterly Report</title>
          <style>
            :root { --brand: #1a73e8; }
            h1 { color: var(--brand); text-align: center; }
            .row { display: flex; gap: 16px; }
          </style>
        </head>
        <body>
          <h1>Quarterly Report</h1>
          <p>Revenue increased <strong>12%</strong> year over year.<br>Costs held flat.</p>
          <div class="row">
            <div>
              <h2>Highlights</h2>
              <ul><li>Revenue up 12%</li><li>New markets</li></ul>
            </div>
            <div>
              <h2>Risks</h2>
              <p>Supply chain remains <code>fragile</code>.</p>
            </div>
          </div>
          <table>
            <thead><tr><th>Region</th><th>Q3</th></tr></thead>
            <tbody><tr><td>North</td><td>$2.4M</td></tr></tbody>
          </table>
          <hr>
          <p>Prepared by <a href="mailto:cfo@example.com">the CFO</a>.</p>
        </body>
        </html>
        """
        doc = import_html(html)
        data = doc.render()
        report = verify_pdf(data)
        assert report.ok, report.problems
        assert b"/StructTreeRoot" in data
        assert b"/H1" in data
        assert b"/Table" in data

    def test_import_output_is_deterministic(self):
        html = "<h1>T</h1><p>Body</p>"
        assert import_html(html).render() == import_html(html).render()
