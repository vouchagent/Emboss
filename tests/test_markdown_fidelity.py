"""Tests for Markdown inline/block fidelity (plan items 2.1 and 2.2)."""

from emboss import Document, parse_markdown
from emboss.layout.engine import LayoutEngine, MeasuredBlock
from emboss.markdown import BLOCKQUOTE_NATIVE, _parse_inline
from emboss.spec import (
    BlockQuote,
    BulletList,
    Footnote,
    Heading,
    HorizontalRule,
    NumberedList,
    Paragraph,
    Table,
    TextRun,
)
from emboss.styles import resolve_preset
from emboss.typography.font_metrics import FontRegistry


def _engine() -> LayoutEngine:
    return LayoutEngine(FontRegistry(), resolve_preset("corporate"))


class TestBackslashEscapes:
    def test_escaped_asterisks_stay_literal(self):
        runs = _parse_inline(r"\*not bold\*")
        assert len(runs) == 1
        assert runs[0].text == "*not bold*"
        assert not runs[0].bold and not runs[0].italic

    def test_escaped_specials(self):
        runs = _parse_inline(r"\_a\_ \`b\` \$c\$ \[d\] \~e\~")
        assert len(runs) == 1
        assert runs[0].text == "_a_ `b` $c$ [d] ~e~"

    def test_unescaped_backslash_kept(self):
        runs = _parse_inline(r"C:\path\to")
        assert runs[0].text == r"C:\path\to"


class TestLinks:
    def test_inline_link(self):
        runs = _parse_inline("see [Emboss](https://emboss.dev) now")
        linked = [r for r in runs if r.link]
        assert len(linked) == 1
        assert linked[0].text == "Emboss"
        assert linked[0].link == "https://emboss.dev"

    def test_bold_inside_link_text(self):
        runs = _parse_inline("[plain **bold**](https://x.com)")
        assert [(r.text, r.bold, r.link) for r in runs] == [
            ("plain ", False, "https://x.com"),
            ("bold", True, "https://x.com"),
        ]

    def test_reference_link(self):
        md = "See [the docs][ref].\n\n[ref]: https://docs.example"
        elements = parse_markdown(md)
        assert len(elements) == 1
        para = elements[0]
        linked = [r for r in para.runs if r.link]
        assert linked[0].text == "the docs"
        assert linked[0].link == "https://docs.example"

    def test_collapsed_reference_link(self):
        md = "See [docs][].\n\n[docs]: https://docs.example"
        para = parse_markdown(md)[0]
        linked = [r for r in para.runs if r.link]
        assert linked[0].text == "docs"
        assert linked[0].link == "https://docs.example"

    def test_definition_removed_from_flow(self):
        md = "A [x][r].\n\n[r]: https://y.z"
        elements = parse_markdown(md)
        assert len(elements) == 1
        assert "https://y.z" not in elements[0].plain_text

    def test_bare_autolink(self):
        runs = _parse_inline("go to <https://auto.example/p> now")
        linked = [r for r in runs if r.link]
        assert linked[0].text == "https://auto.example/p"
        assert linked[0].link == "https://auto.example/p"

    def test_unresolved_reference_stays_literal(self):
        runs = _parse_inline("just [text][nope] here")
        assert "".join(r.text for r in runs) == "just [text][nope] here"


class TestStrikethrough:
    def test_field_defaults_off(self):
        assert TextRun("x").strikethrough is False

    def test_parse_strikethrough(self):
        runs = _parse_inline("keep ~~drop this~~ end")
        struck = [r for r in runs if r.strikethrough]
        assert len(struck) == 1
        assert struck[0].text == "drop this"

    def test_bold_inside_strikethrough(self):
        runs = _parse_inline("~~a **b**~~")
        assert all(r.strikethrough for r in runs)
        assert runs[1].bold


class TestInlineMath:
    def test_mid_sentence_math_is_italic_without_dollars(self):
        runs = _parse_inline("the value $x^2$ grows")
        math = [r for r in runs if r.italic]
        assert math[0].text == "x^2"
        assert "$" not in "".join(r.text for r in runs)

    def test_currency_not_treated_as_math(self):
        runs = _parse_inline("costs $5 and $6 total")
        assert "".join(r.text for r in runs) == "costs $5 and $6 total"
        assert not any(r.italic for r in runs)


class TestInlineImages:
    def test_inline_image_becomes_alt_text(self):
        runs = _parse_inline("before ![the alt](pic.png) after")
        assert "".join(r.text for r in runs) == "before the alt after"


class TestTableCellInline:
    def test_bold_in_cell_produces_runs(self):
        md = "| H |\n|---|\n| **bold** cell |"
        table = parse_markdown(md)[0]
        assert isinstance(table, Table)
        cell = table.rows[0][0]
        assert isinstance(cell.content, list)
        assert [(r.text, r.bold) for r in cell.runs] == [
            ("bold", True),
            (" cell", False),
        ]

    def test_plain_cell_stays_string(self):
        md = "| H |\n|---|\n| plain |"
        table = parse_markdown(md)[0]
        assert table.rows[0][0].content == "plain"

    def test_run_list_cell_measures(self):
        md = "| H |\n|---|\n| **bold** cell with ~~strike~~ |"
        table = parse_markdown(md)[0]
        block = _engine().measure(table, 400.0)
        assert block.height > 0
        assert block.table is not None


class TestNestedLists:
    def test_three_level_bullets_each_own_item(self):
        md = "- top\n  - mid\n    - deep\n- second"
        result = parse_markdown(md)
        assert len(result) == 1
        outer = result[0]
        assert isinstance(outer, BulletList)
        assert outer.items[0] == "top"
        level2 = outer.items[1]
        assert isinstance(level2, BulletList)
        assert level2.items[0] == "mid"
        level3 = level2.items[1]
        assert isinstance(level3, BulletList)
        assert level3.items == ["deep"]
        assert outer.items[2] == "second"

    def test_depth_markers_differ(self):
        md = "- top\n  - mid\n    - deep"
        outer = parse_markdown(md)[0]
        level2 = outer.items[1]
        level3 = level2.items[1]
        assert outer.bullet == "•"
        assert level2.bullet == "-"
        assert level3.bullet == "·"

    def test_engine_measures_nested_as_own_blocks(self):
        md = "- top\n  - mid\n    - deep"
        outer = parse_markdown(md)[0]
        block = _engine().measure(outer, 400.0)
        nested = [e for e in block.list_items if isinstance(e, MeasuredBlock)]
        assert len(nested) == 1
        inner = nested[0]
        assert isinstance(inner.element, BulletList)
        assert inner.lines == []  # its text lives in its own list_items
        assert any(isinstance(e, MeasuredBlock) for e in inner.list_items)
        assert block.height > inner.height > 0

    def test_engine_nested_indent_constant(self):
        assert LayoutEngine.NESTED_LIST_INDENT == 14.0

    def test_nested_ordered_uses_alpha_markers(self):
        md = "1. one\n   1. sub one\n   2. sub two\n2. two"
        outer = parse_markdown(md)[0]
        assert isinstance(outer, NumberedList)
        assert outer.marker(0) == "1."
        sub = outer.items[1]
        assert isinstance(sub, NumberedList)
        assert sub.marker_style == "alpha"
        assert sub.marker(0) == "a."
        assert sub.marker(1) == "b."

    def test_mixed_kind_nesting(self):
        md = "- top\n  1. step\n- next"
        outer = parse_markdown(md)[0]
        assert isinstance(outer, BulletList)
        assert isinstance(outer.items[1], NumberedList)

    def test_plain_python_nested_list_items(self):
        bl = BulletList(items=["a", ["a1", "a2"], "b"])
        flat = bl.flat_items
        assert flat[0][0] is not None
        assert isinstance(flat[1][1], BulletList)
        assert flat[1][1].items == ["a1", "a2"]
        block = _engine().measure(bl, 400.0)
        assert any(isinstance(e, MeasuredBlock) for e in block.list_items)

    def test_plain_nested_list_in_numbered(self):
        nl = NumberedList(items=["a", ["a1"]])
        sub = nl.flat_items[1][1]
        assert isinstance(sub, NumberedList)
        assert sub.marker(0) == "a."


class TestTaskLists:
    def test_task_prefix_and_metadata(self):
        md = "- [ ] todo\n- [x] done\n- plain"
        result = parse_markdown(md)[0]
        assert isinstance(result, BulletList)
        assert result.items[0] == "[ ] todo"
        assert result.items[1] == "[x] done"
        assert result.items[2] == "plain"
        assert result.checked == [False, True, None]

    def test_non_task_list_has_no_metadata(self):
        result = parse_markdown("- a\n- b")[0]
        assert result.checked is None


class TestBlockquotes:
    def test_flag_defaults_off(self):
        assert BLOCKQUOTE_NATIVE is False

    def test_plain_blockquote_maps_to_indented_italic_paragraph(self):
        result = parse_markdown("> quoted wisdom")
        assert len(result) == 1
        para = result[0]
        assert isinstance(para, Paragraph)
        assert all(r.italic for r in para.runs)
        assert para.style is not None
        assert para.style.indent_left > 0

    def test_multiline_and_lazy_continuation(self):
        md = "> line one\n> line two\nlazy three"
        para = parse_markdown(md)[0]
        assert isinstance(para, Paragraph)
        assert para.plain_text == "line one line two lazy three"

    def test_blockquote_renders_today(self):
        md = "> quoted wisdom\n\nAfter."
        pdf = Document.from_markdown(md, title="Quote").render()
        assert pdf[:5] == b"%PDF-"

    def test_native_blockquote_measurement(self):
        quote = BlockQuote(content="Wise words repeated. " * 8)
        block = _engine().measure(quote, 300.0)
        assert block.height > 0
        assert len(block.lines) > 1
        assert block.style.require("italic") is True

    def test_blockquote_attribution_measurement(self):
        quote = BlockQuote(content="Short quote.", attribution="A. Author")
        plain = BlockQuote(content="Short quote.")
        engine = _engine()
        assert engine.measure(quote, 300.0).height > engine.measure(plain, 300.0).height


class TestSetextHeadings:
    def test_setext_h1(self):
        result = parse_markdown("The Title\n===")
        assert isinstance(result[0], Heading)
        assert result[0].level == 1
        assert result[0].text == "The Title"

    def test_setext_h2(self):
        result = parse_markdown("Sub Title\n---")
        assert isinstance(result[0], Heading)
        assert result[0].level == 2

    def test_standalone_dashes_still_hr(self):
        result = parse_markdown("A paragraph.\n\n---\n\nAnother.")
        types = [type(e).__name__ for e in result]
        assert types == ["Paragraph", "HorizontalRule", "Paragraph"]

    def test_dashes_directly_after_paragraph_are_setext(self):
        result = parse_markdown("A title line\n---\n\nBody.")
        assert isinstance(result[0], Heading)
        assert result[0].level == 2
        assert not any(isinstance(e, HorizontalRule) for e in result)


class TestFootnotes:
    def test_footnote_collected_and_marker_replaced(self):
        md = "A claim[^1] here.\n\n[^1]: The supporting note."
        result = parse_markdown(md)
        assert len(result) == 2
        para, note = result
        assert isinstance(para, Paragraph)
        assert para.plain_text == "A claim[1] here."
        assert isinstance(note, Footnote)
        assert note.marker == "1"
        assert "The supporting note." in "".join(r.text for r in note.runs)

    def test_definition_removed_from_flow(self):
        md = "Ref[^a].\n\n[^a]: Note text."
        result = parse_markdown(md)
        paragraphs = [e for e in result if isinstance(e, Paragraph)]
        assert len(paragraphs) == 1

    def test_footnote_emitted_once(self):
        md = "One[^1] and again[^1].\n\n[^1]: Only once."
        result = parse_markdown(md)
        notes = [e for e in result if isinstance(e, Footnote)]
        assert len(notes) == 1

    def test_footnote_renders(self):
        md = "A claim[^1] here.\n\n[^1]: The note."
        pdf = Document.from_markdown(md, title="Notes").render()
        assert pdf[:5] == b"%PDF-"


class TestEndToEnd:
    def test_full_fidelity_document_renders(self):
        md = """Big Title
===

Section
---

Text with **bold**, a [link](https://emboss.dev), ~~old~~, math $x^2$,
escaped \\*stars\\*, ref [docs][d], and <https://auto.example>.

- top level
  - nested level
    - deep level
- [ ] open task
- [x] done task

1. first
   1. sub first
   2. sub second
2. second

> A quoted passage that
continues lazily.

| Metric | Value |
|---|---|
| **Revenue** | $24.1M |

A footnote claim[^1].

---

[^1]: The footnote body.
[d]: https://docs.example
"""
        doc = Document.from_markdown(md)
        pdf = doc.render()
        assert pdf[:5] == b"%PDF-"
        types = [type(e).__name__ for e in doc.content]
        assert types.count("Heading") == 2
        assert "Footnote" in types
        assert "Table" in types
        assert "HorizontalRule" in types

    def test_double_parse_deterministic(self):
        md = "- a\n  - b\n\n> q\n\nT\n==="
        first = parse_markdown(md)
        second = parse_markdown(md)
        assert [repr(e) for e in first] == [repr(e) for e in second]
