"""Tests for paged-media features: mirroring, first-page variants, numbering."""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss.spec import Document, HeaderFooter, PageSpec  # noqa: E402
from emboss.writer import roman  # noqa: E402

HEADER_Y = 730.0
FOOTER_Y = 60.0

_TEXT_OP = re.compile(rb"([0-9.+-]+) ([0-9.+-]+) Td\n(.*?)\nET", re.DOTALL)


def _page_contents(data: bytes) -> list:
    pikepdf = pytest.importorskip("pikepdf")
    with pikepdf.open(io.BytesIO(data)) as pdf:
        return [bytes(page.Contents.read_bytes()) for page in pdf.pages]


def _text_ops(content: bytes) -> list:
    ops = []
    for match in _TEXT_OP.finditer(content):
        text = b"".join(re.findall(rb"\((.*?)\)", match.group(3)))
        ops.append(
            (
                float(match.group(1)),
                float(match.group(2)),
                text.decode("latin-1"),
            )
        )
    return ops


def _ops_with(ops: list, needle: str) -> list:
    return [op for op in ops if needle in op[2]]


def _page_texts(content: bytes) -> str:
    return " ".join(op[2] for op in _text_ops(content))


class TestRomanHelper:
    def test_lowercase_values(self):
        assert roman(1) == "i"
        assert roman(4) == "iv"
        assert roman(9) == "ix"
        assert roman(14) == "xiv"
        assert roman(1994) == "mcmxciv"

    def test_uppercase_variant(self):
        assert roman(3, upper=True) == "III"
        assert roman(40, upper=True) == "XL"

    def test_non_positive_falls_back_to_decimal(self):
        assert roman(0) == "0"
        assert roman(-2) == "-2"


class TestMirroredMargins:
    def _doc(self) -> Document:
        page = PageSpec(margin_left=54.0, margin_right=90.0, mirror_margins=True)
        doc = Document(
            title="Mirror Test",
            page=page,
            header=HeaderFooter(left="LEFTTEXT", right="RIGHTTEXT"),
        )
        doc.paragraph("Verse one of the mirrored body content.")
        doc.page_break()
        doc.paragraph("Verse two of the mirrored body content.")
        return doc

    def test_even_page_content_shifted_by_margin_delta(self):
        pages = _page_contents(self._doc().render())
        recto = _ops_with(_text_ops(pages[0]), "Verse")[0]
        verso = _ops_with(_text_ops(pages[1]), "Verse")[0]
        assert verso[0] - recto[0] == pytest.approx(36.0, abs=0.01)

    def test_header_slots_swapped_on_verso(self):
        pages = _page_contents(self._doc().render())
        ops1, ops2 = _text_ops(pages[0]), _text_ops(pages[1])
        left1 = _ops_with(ops1, "LEFTTEXT")[0]
        right1 = _ops_with(ops1, "RIGHTTEXT")[0]
        left2 = _ops_with(ops2, "LEFTTEXT")[0]
        right2 = _ops_with(ops2, "RIGHTTEXT")[0]
        assert left1[0] < right1[0]
        assert right2[0] < left2[0]
        assert left1[0] == pytest.approx(54.0)
        assert right2[0] == pytest.approx(90.0)


class TestFirstPageVariants:
    def _two_pages(self, header: HeaderFooter) -> list:
        doc = Document(title="Cover Test", header=header)
        doc.paragraph("Cover page body.")
        doc.page_break()
        doc.paragraph("Second page body.")
        return _page_contents(doc.render())

    def test_first_page_false_suppresses_page_one_header(self):
        pages = self._two_pages(HeaderFooter(center="RUNNINGHEAD", first_page=False))
        assert "RUNNINGHEAD" not in _page_texts(pages[0])
        assert "RUNNINGHEAD" in _page_texts(pages[1])

    def test_first_page_override_wins_over_suppression(self):
        pages = self._two_pages(
            HeaderFooter(
                center="RUNNINGHEAD",
                first_page=False,
                first_page_override=HeaderFooter(center="COVERHEAD"),
            )
        )
        assert "COVERHEAD" in _page_texts(pages[0])
        assert "RUNNINGHEAD" not in _page_texts(pages[0])
        assert "RUNNINGHEAD" in _page_texts(pages[1])
        assert "COVERHEAD" not in _page_texts(pages[1])

    def test_first_page_default_keeps_header_everywhere(self):
        pages = self._two_pages(HeaderFooter(center="RUNNINGHEAD"))
        assert "RUNNINGHEAD" in _page_texts(pages[0])
        assert "RUNNINGHEAD" in _page_texts(pages[1])


class TestSectionToken:
    def _doc(self) -> Document:
        doc = Document(
            title="Field Guide",
            header=HeaderFooter(center="{section}"),
        )
        doc.paragraph("Intro before any section heading.")
        doc.page_break()
        doc.heading("Alpha", level=1)
        doc.paragraph("Alpha body.")
        doc.page_break()
        doc.heading("Beta", level=2)
        doc.paragraph("Beta body.")
        return doc

    def _header_texts(self, pages: list) -> list:
        texts = []
        for content in pages:
            headers = [op[2] for op in _text_ops(content) if op[1] > HEADER_Y]
            texts.append(" ".join(headers))
        return texts

    def test_section_tracks_latest_heading_per_page(self):
        headers = self._header_texts(_page_contents(self._doc().render()))
        assert headers[0] == "Field Guide"
        assert headers[1] == "Alpha"
        assert headers[2] == "Beta"

    def test_section_falls_back_to_title_before_any_heading(self):
        doc = Document(
            title="",
            tagged=False,
            header=HeaderFooter(center="pre-{section}-post"),
        )
        doc.paragraph("No headings anywhere.")
        pages = _page_contents(doc.render())
        assert "pre--post" in _page_texts(pages[0])


class TestPageNumberFormats:
    def _footer_texts(self, doc: Document) -> list:
        texts = []
        for content in _page_contents(doc.render()):
            footers = [op[2] for op in _text_ops(content) if op[1] < FOOTER_Y]
            texts.append(" ".join(footers))
        return texts

    def _four_page_doc(self, **kw) -> Document:
        doc = Document(
            title="Front Matter",
            footer=HeaderFooter(center="{page} of {pages}"),
            **kw,
        )
        for index in range(4):
            if index:
                doc.page_break()
            doc.paragraph(f"Body {index + 1}.")
        return doc

    def test_roman_front_matter_then_arabic_restart(self):
        doc = self._four_page_doc(front_matter_pages=2)
        assert self._footer_texts(doc) == [
            "i of ii",
            "ii of ii",
            "1 of 2",
            "2 of 2",
        ]

    def test_uppercase_roman_document(self):
        doc = self._four_page_doc(page_number_format="ROMAN")
        assert self._footer_texts(doc) == [
            "I of IV",
            "II of IV",
            "III of IV",
            "IV of IV",
        ]

    def test_front_matter_clamped_to_page_count(self):
        doc = Document(title="Clamp", footer=HeaderFooter(center="{page}/{pages}"))
        doc.front_matter_pages = 9
        doc.paragraph("Only page.")
        assert self._footer_texts(doc) == ["i/i"]

    def test_default_page_number_footer_uses_sequence(self):
        doc = Document(title="Plain", front_matter_pages=1)
        doc.paragraph("First.")
        doc.page_break()
        doc.paragraph("Second.")
        texts = self._footer_texts(doc)
        assert "i of i" in texts[0]
        assert "1 of 1" in texts[1]


class TestPageLabelsTree:
    def test_front_matter_emits_roman_and_decimal_ranges(self):
        doc = Document(title="Labels", front_matter_pages=2)
        for index in range(3):
            if index:
                doc.page_break()
            doc.paragraph(f"Page {index + 1}.")
        data = doc.render()
        assert b"/PageLabels" in data
        assert b"/Nums [0 <</S /r" in data
        assert b"2 <</S /D" in data

    def test_roman_format_without_front_matter(self):
        doc = Document(title="Roman Labels", page_number_format="ROMAN")
        doc.paragraph("Body.")
        data = doc.render()
        assert b"/PageLabels" in data
        assert b"/Nums [0 <</S /R" in data

    def test_default_document_has_no_page_labels(self):
        doc = Document(title="Default")
        doc.paragraph("Body.")
        assert b"/PageLabels" not in doc.render()


class TestPydanticRoundTrip:
    def _spec_dict(self) -> dict:
        return {
            "title": "Round Trip",
            "content": [{"type": "paragraph", "text": "Body."}],
            "page": {
                "preset": "letter",
                "margin_left": 50,
                "margin_right": 80,
                "mirror_margins": True,
            },
            "header": {
                "center": "{section}",
                "first_page": False,
                "first_page_override": {"center": "Cover"},
            },
            "footer": {"right": "{page} of {pages}"},
            "page_number_format": "roman",
            "front_matter_pages": 1,
        }

    def test_new_fields_map_to_document(self):
        pytest.importorskip("pydantic")
        from emboss.adapters.pydantic_schema import DocumentSpec

        doc = DocumentSpec.model_validate(self._spec_dict()).to_document()
        assert doc.page.mirror_margins is True
        assert doc.header.first_page is False
        assert doc.header.first_page_override.center == "Cover"
        assert doc.footer.first_page is True
        assert doc.page_number_format == "roman"
        assert doc.front_matter_pages == 1

    def test_model_dump_round_trip_preserves_fields(self):
        pytest.importorskip("pydantic")
        from emboss.adapters.pydantic_schema import DocumentSpec

        spec = DocumentSpec.model_validate(self._spec_dict())
        again = DocumentSpec.model_validate(spec.model_dump())
        assert again.page.mirror_margins is True
        assert again.header.first_page is False
        assert again.header.first_page_override.center == "Cover"
        assert again.page_number_format == "roman"
        assert again.front_matter_pages == 1

    def test_spec_renders(self):
        pytest.importorskip("pydantic")
        from emboss.adapters.pydantic_schema import DocumentSpec

        data = DocumentSpec.model_validate(self._spec_dict()).render()
        assert data.startswith(b"%PDF")


class TestDeterminismAndRegression:
    def _featured_doc(self) -> Document:
        page = PageSpec(margin_left=50.0, margin_right=80.0, mirror_margins=True)
        doc = Document(
            title="Deterministic",
            page=page,
            header=HeaderFooter(
                left="{section}",
                right="{page} of {pages}",
                first_page=False,
                first_page_override=HeaderFooter(center="Cover"),
            ),
            front_matter_pages=1,
        )
        doc.paragraph("Front matter.")
        doc.page_break()
        doc.heading("Body Section", level=1)
        doc.paragraph("Body text.")
        return doc

    def test_double_render_is_byte_identical(self):
        assert self._featured_doc().render() == self._featured_doc().render()

    def _default_doc(self, **kw) -> Document:
        doc = Document(
            title="Baseline",
            header=HeaderFooter(center="Running Head", **kw),
        )
        doc.paragraph("Page one body.")
        doc.page_break()
        doc.heading("Later Section", level=1)
        doc.paragraph("Page two body.")
        return doc

    def test_defaults_match_explicitly_defaulted_features(self):
        plain = self._default_doc()
        explicit = self._default_doc(first_page=True, first_page_override=None)
        explicit.page.mirror_margins = False
        explicit.page_number_format = "arabic"
        explicit.front_matter_pages = 0
        assert plain.render() == explicit.render()
