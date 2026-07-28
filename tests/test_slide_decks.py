"""Tests for the SlideDeck builder, themes, and fit-to-slide."""

import re
import zlib

import pytest

from emboss.slides import (
    DECK_16_9,
    SLIDE_16_9,
    SLIDE_4_3,
    SlideDeck,
    THEMES,
    contrast_ratio,
    relative_luminance,
    resolve_theme,
    slide_document,
)
from emboss.spec import BulletList, Chart, Document, Paragraph, Table

THEME_NAMES = ("boardroom", "horizon", "carbon", "meadow")


def _page_streams(pdf: bytes) -> list:
    """Decompressed content stream per page, in page-tree order."""
    objs = dict(re.findall(rb"(\d+) 0 obj(.*?)endobj", pdf, re.S))
    kids = re.search(rb"/Kids \[(.*?)\]", pdf, re.S).group(1)
    streams = []
    for num in re.findall(rb"(\d+) 0 R", kids):
        contents = re.search(rb"/Contents (\d+) 0 R", objs[num])
        raw = re.search(
            rb"stream\r?\n(.*?)endstream", objs[contents.group(1)], re.S
        ).group(1)
        try:
            raw = zlib.decompressobj().decompress(raw)
        except zlib.error:
            pass
        streams.append(raw)
    return streams


def _td_positions(stream: bytes) -> list:
    return [
        (float(x), float(y)) for x, y in re.findall(rb"([\d.-]+) ([\d.-]+) Td", stream)
    ]


def _font_sizes(stream: bytes) -> set:
    return {float(m) for m in re.findall(rb"/\w+ ([\d.]+) Tf", stream)}


def _fill_colors(stream: bytes) -> set:
    return {
        tuple(round(float(c), 3) for c in triple)
        for triple in re.findall(rb"([\d.]+) ([\d.]+) ([\d.]+) rg", stream)
    }


def _hex_triple(color: str) -> tuple:
    return tuple(round(int(color[i : i + 2], 16) / 255.0, 3) for i in (0, 2, 4))


def _color_close(a: tuple, b: tuple, tol: float = 0.005) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def full_deck(theme: str = "boardroom") -> SlideDeck:
    deck = SlideDeck(
        "FY26 Strategy", presenter="Ana Ruiz", date="July 2026", theme=theme
    )
    deck.title_slide(subtitle="Board update")
    deck.section_divider("Where we are")
    deck.content_slide(
        "Context",
        Paragraph("Demand recovered across all regions."),
        BulletList(items=["EMEA +12%", "APAC +9%"]),
    )
    deck.bullet_slide(
        "Priorities",
        ["Ship platform v2", "Enter two new markets", "Hold burn flat"],
        takeaway="Focus stays on efficient growth.",
    )
    deck.stat_slide(
        "Key numbers",
        [
            ("ARR", "$12.4M", "+18%"),
            ("NRR", "118%", "+6pts"),
            ("Churn", "2.1%", "-0.4pts"),
        ],
    )
    deck.chart_slide(
        "Revenue by quarter",
        Chart(
            chart_type="bar",
            labels=["Q1", "Q2", "Q3", "Q4"],
            values=[3.1, 3.4, 3.9, 4.2],
        ),
        takeaway="Sequential growth every quarter.",
    )
    deck.quote_slide("The best way to predict the future is to invent it.", "Alan Kay")
    deck.code_slide(
        "Rollout gate",
        "def ready(service):\n    return service.slo() > 0.999",
        language="python",
    )
    deck.closing_slide("Thank you", contact="ana@example.com")
    return deck


class TestDeckLayouts:
    def test_every_layout_renders_one_page_per_slide(self):
        deck = full_deck()
        pdf = deck.render()
        assert pdf.startswith(b"%PDF-1.7")
        assert b"%%EOF" in pdf
        assert deck.slide_count == 9
        assert len(_page_streams(pdf)) == 9
        count = re.search(rb"/Count (\d+)", pdf)
        assert int(count.group(1)) == 9

    def test_build_returns_document(self):
        doc = full_deck().build()
        assert isinstance(doc, Document)
        assert doc.title == "FY26 Strategy"
        assert doc.page is DECK_16_9

    def test_render_and_save_conveniences(self, tmp_path):
        deck = full_deck()
        path = tmp_path / "deck.pdf"
        deck.save(path)
        assert path.read_bytes() == deck.render()

    def test_4_3_aspect_ratio(self):
        deck = SlideDeck("Squarer", aspect_ratio="4:3")
        deck.title_slide()
        pdf = deck.render()
        assert b"/MediaBox [0 0 720 540]" in pdf

    def test_deck_verifies(self):
        from emboss.pdf.verify import verify_pdf

        report = verify_pdf(full_deck().render())
        assert report.ok, f"verification failed: {report.problems}"

    def test_layout_methods_chain(self):
        deck = SlideDeck("Chain")
        result = deck.title_slide().bullet_slide("A", ["b"]).closing_slide("Bye")
        assert result is deck
        assert deck.slide_count == 3

    def test_unknown_layout_rejected(self):
        deck = SlideDeck("Bad")
        with pytest.raises(ValueError, match="two-column"):
            deck.content_slide("T", Paragraph("x"), layout="three-column")


class TestFooter:
    def test_title_slide_suppresses_footer_later_slides_show_it(self):
        pages = _page_streams(full_deck().render())
        # The footer strip sits below the 36pt bottom margin (y ~= 10).
        first_footer = [t for t in _td_positions(pages[0]) if t[1] < 30]
        assert first_footer == []
        for stream in pages[1:]:
            footer_ops = [t for t in _td_positions(stream) if t[1] < 30]
            assert footer_ops, "expected footer text ops on non-title slides"

    def test_footer_has_left_title_and_right_slide_number(self):
        pages = _page_streams(full_deck().render())
        xs = sorted(x for x, y in _td_positions(pages[1]) if y < 30)
        assert xs[0] == pytest.approx(36.0)  # deck title at left margin
        assert xs[-1] > 600.0  # slide number at the right edge


class TestStatSlide:
    def test_large_accent_values_at_2_2x_scale(self):
        pages = _page_streams(full_deck().render())
        stat_stream = pages[4]
        assert b"39.6 Tf" in stat_stream  # 18pt body * 2.2
        assert 39.6 in _font_sizes(stat_stream)

    def test_stat_values_use_accent_ink(self):
        theme = THEMES["boardroom"]
        pages = _page_streams(full_deck().render())
        assert any(
            _color_close(fill, _hex_triple(theme.accent_ink))
            for fill in _fill_colors(pages[4])
        )

    def test_delta_colors_split_by_sign(self):
        theme = THEMES["boardroom"]
        fills = _fill_colors(_page_streams(full_deck().render())[4])
        assert any(_color_close(f, _hex_triple(theme.delta_up)) for f in fills)
        assert any(_color_close(f, _hex_triple(theme.delta_down)) for f in fills)


class TestDividerSlide:
    @pytest.mark.parametrize("theme_name", THEME_NAMES)
    def test_full_width_background_rect_in_theme_panel_color(self, theme_name):
        theme = THEMES[theme_name]
        pages = _page_streams(full_deck(theme_name).render())
        divider = pages[1]
        assert any(
            _color_close(fill, _hex_triple(theme.panel))
            for fill in _fill_colors(divider)
        )
        rects = [
            tuple(float(v) for v in r)
            for r in re.findall(rb"([\d.-]+) ([\d.-]+) ([\d.-]+) ([\d.-]+) re", divider)
        ]
        full_width = [r for r in rects if r[2] == pytest.approx(648.0)]
        assert full_width, "expected a rect spanning the full content width"

    def test_divider_title_text_on_panel(self):
        theme = THEMES["carbon"]
        divider = _page_streams(full_deck("carbon").render())[1]
        assert any(
            _color_close(fill, _hex_triple(theme.on_panel))
            for fill in _fill_colors(divider)
        )


class TestThemes:
    def test_four_designed_themes_exist(self):
        assert set(THEME_NAMES) <= set(THEMES)

    @pytest.mark.parametrize("theme_name", THEME_NAMES)
    def test_theme_renders_full_deck(self, theme_name):
        pdf = full_deck(theme_name).render()
        assert pdf.startswith(b"%PDF-1.7")
        assert len(_page_streams(pdf)) == 9

    @pytest.mark.parametrize("theme_name", THEME_NAMES)
    def test_deterministic_double_render(self, theme_name):
        assert full_deck(theme_name).render() == full_deck(theme_name).render()

    @pytest.mark.parametrize("theme_name", THEME_NAMES)
    def test_body_text_contrast_on_page(self, theme_name):
        theme = THEMES[theme_name]
        assert contrast_ratio(theme.ink, "ffffff") >= 4.5
        assert contrast_ratio(theme.title, "ffffff") >= 4.5
        assert contrast_ratio(theme.accent_ink, "ffffff") >= 4.5

    @pytest.mark.parametrize("theme_name", THEME_NAMES)
    def test_panel_text_contrast(self, theme_name):
        theme = THEMES[theme_name]
        assert contrast_ratio(theme.on_panel, theme.panel) >= 4.5

    def test_luminance_helper_bounds(self):
        assert relative_luminance("000000") == pytest.approx(0.0)
        assert relative_luminance("ffffff") == pytest.approx(1.0)
        assert contrast_ratio("000000", "ffffff") == pytest.approx(21.0)

    def test_theme_aliases_and_errors(self):
        assert resolve_theme("default").name == "boardroom"
        assert resolve_theme("dark").name == "carbon"
        with pytest.raises(KeyError, match="unknown slide theme"):
            resolve_theme("neon")

    def test_chart_inherits_theme_palette(self):
        deck = SlideDeck("Charts", theme="meadow")
        deck.chart_slide("Growth", Chart(chart_type="bar", labels=["a"], values=[1.0]))
        doc = deck.build()
        chart = next(el for el in doc.content if isinstance(el, Chart))
        assert tuple(chart.colors) == THEMES["meadow"].chart_palette

    def test_explicit_chart_colors_kept(self):
        deck = SlideDeck("Charts")
        deck.chart_slide(
            "Growth",
            Chart(chart_type="bar", labels=["a"], values=[1.0], colors=["112233"]),
        )
        doc = deck.build()
        chart = next(el for el in doc.content if isinstance(el, Chart))
        assert list(chart.colors) == ["112233"]


class TestFitToSlide:
    def test_overlong_bullet_slide_shrinks_to_fit(self):
        deck = SlideDeck("Fit test")
        deck.bullet_slide(
            "Many bullets",
            [f"Bullet point number {i} in the list" for i in range(9)],
        )
        pages = _page_streams(deck.render())
        assert len(pages) == 1  # no silent continuation page
        sizes = _font_sizes(pages[0])
        assert 18.0 not in sizes  # default body size was scaled down
        assert any(12.0 < size < 18.0 for size in sizes)

    def test_short_slide_keeps_default_sizes(self):
        deck = SlideDeck("No fit needed")
        deck.bullet_slide("Few", ["One", "Two"])
        sizes = _font_sizes(_page_streams(deck.render())[0])
        assert 18.0 in sizes

    def test_pathological_slide_raises_naming_the_slide(self):
        deck = SlideDeck("Overflow test")
        deck.title_slide()
        deck.bullet_slide("Way too many", [f"Bullet {i}" for i in range(40)])
        with pytest.raises(ValueError) as excinfo:
            deck.build()
        message = str(excinfo.value)
        assert "slide 2" in message
        assert "Way too many" in message
        assert "0.8" in message

    def test_page_break_inside_slide_rejected(self):
        from emboss.spec import PageBreak

        deck = SlideDeck("No breaks")
        with pytest.raises(ValueError, match="PageBreak"):
            deck.content_slide("T", PageBreak())


class TestTwoColumn:
    def test_blocks_placed_side_by_side(self):
        deck = SlideDeck("Cols")
        deck.content_slide(
            "Compare",
            Paragraph("The left column carries the current-state text."),
            BulletList(items=["Left bullet one", "Left bullet two"]),
            Paragraph("The right column carries the future-state text."),
            BulletList(items=["Right bullet one"]),
            layout="two-column",
        )
        stream = _page_streams(deck.render())[0]
        body_xs = {x for x, y in _td_positions(stream) if 30 < y < 280}
        left = [x for x in body_xs if x < 120]
        right = [x for x in body_xs if x > 300]
        assert left and right, f"expected two x clusters, got {sorted(body_xs)}"

    def test_two_column_rejects_non_text_blocks(self):
        deck = SlideDeck("Cols")
        chart = Chart(chart_type="bar", labels=["a"], values=[1.0])
        with pytest.raises(TypeError, match="chart_slide"):
            deck.content_slide("T", chart, Paragraph("x"), layout="two-column")

    def test_single_layout_accepts_tables_and_charts(self):
        deck = SlideDeck("Rich")
        deck.content_slide(
            "Data",
            Table(headers=["K", "V"], rows=[["Revenue", "$12M"]]),
            Chart(chart_type="pie", labels=["a", "b"], values=[1.0, 2.0]),
        )
        assert deck.render().startswith(b"%PDF-1.7")


class TestBackwardCompatibility:
    def test_slide_page_specs_unchanged(self):
        assert SLIDE_16_9.width == 720.0 and SLIDE_16_9.height == 405.0
        assert SLIDE_16_9.margin_left == 48.0
        assert SLIDE_4_3.width == 720.0 and SLIDE_4_3.height == 540.0

    def test_slide_document_still_works(self):
        doc = slide_document("Legacy Deck", subtitle="Sub", author="Me")
        doc.heading("Slide 2", level=2)
        doc.paragraph("Content.")
        pdf = doc.render()
        assert pdf.startswith(b"%PDF-1.7")
        assert doc.page is SLIDE_16_9

    def test_templates_slide_deck_renders(self):
        from emboss.templates import slide_deck

        doc = slide_deck(title="Quarterly", author="Ana", subtitle="Update")
        pdf = doc.render()
        assert pdf.startswith(b"%PDF-1.7")
        assert len(_page_streams(pdf)) == 1

    def test_templates_slide_deck_deterministic(self):
        from emboss.templates import slide_deck

        make = lambda: slide_deck(title="Same", author="A").render()  # noqa: E731
        assert make() == make()


class TestDeckWithoutTitleSlide:
    def test_first_slide_gets_deck_masthead(self):
        deck = SlideDeck("Masthead Deck")
        deck.bullet_slide("Agenda", ["One", "Two"])
        pdf = deck.render()
        pages = _page_streams(pdf)
        assert len(pages) == 1
        # The footer is not suppressed when there is no title slide.
        assert [t for t in _td_positions(pages[0]) if t[1] < 30]
