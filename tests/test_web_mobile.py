"""Tests for Fast Web View (linearized) output and the compact page preset."""

import io
import sys

import pytest

from emboss import Document, PageSpec

pikepdf = pytest.importorskip("pikepdf")

MARKER = "LINEARIZEMARKER77"


def _document(**kw) -> Document:
    doc = Document(title="Web Mobile Test", **kw)
    doc.heading("Section One", level=1)
    doc.paragraph(f"{MARKER} the quick brown fox jumps over the lazy dog. " * 4)
    return doc


def _page_content(data: bytes, page: int = 0) -> bytes:
    with pikepdf.open(io.BytesIO(data)) as pdf:
        return bytes(pdf.pages[page].Contents.read_bytes())


class TestLinearize:
    def test_output_is_pdf_and_linearized(self):
        data = _document().render(linearize=True)
        assert data.startswith(b"%PDF")
        with pikepdf.open(io.BytesIO(data)) as pdf:
            assert pdf.is_linearized

    def test_default_output_is_not_linearized(self):
        data = _document().render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            assert not pdf.is_linearized

    def test_content_intact_after_linearization(self):
        data = _document().render(linearize=True)
        assert MARKER.encode() in _page_content(data)

    def test_linearized_output_is_deterministic(self):
        first = _document().render(linearize=True)
        second = _document().render(linearize=True)
        assert first == second

    def test_default_render_unchanged_by_new_parameter(self):
        from emboss.writer import render_document

        doc = _document()
        assert doc.render() == render_document(doc)
        assert doc.render(linearize=False) == render_document(doc)

    def test_save_linearized(self, tmp_path):
        target = tmp_path / "linear.pdf"
        _document().save(target, linearize=True)
        with pikepdf.open(target) as pdf:
            assert pdf.is_linearized

    def test_save_default_not_linearized(self, tmp_path):
        target = tmp_path / "plain.pdf"
        _document().save(target)
        assert target.read_bytes() == _document().render()

    def test_missing_pikepdf_raises_clear_error(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "pikepdf", None)
        with pytest.raises(ImportError, match=r"pikepdf is required"):
            _document().render(linearize=True)


class TestCompactPage:
    def test_a5_dimensions(self):
        page = PageSpec.a5()
        assert page.width == pytest.approx(419.53, abs=0.01)
        assert page.height == pytest.approx(595.28, abs=0.01)

    def test_compact_dimensions_and_margins(self):
        page = PageSpec.compact()
        assert page.width == pytest.approx(419.53, abs=0.01)
        assert page.height == pytest.approx(595.28, abs=0.01)
        assert page.margin_top == 40.0
        assert page.margin_right == 40.0
        assert page.margin_bottom == 40.0
        assert page.margin_left == 40.0
        assert page.columns == 1

    def test_compact_margin_override(self):
        page = PageSpec.compact(margin_left=54.0)
        assert page.margin_left == 54.0
        assert page.margin_top == 40.0

    def test_compact_renders_multi_page_text(self):
        doc = _document(page=PageSpec.compact())
        for i in range(12):
            doc.paragraph(f"Paragraph {i}: filler prose for pagination. " * 12)
        data = doc.render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            assert len(pdf.pages) >= 2
            box = [float(v) for v in pdf.pages[0].MediaBox]
            assert box[2] == pytest.approx(419.53, abs=0.01)
            assert box[3] == pytest.approx(595.28, abs=0.01)

    def test_compact_reachable_via_pydantic(self):
        pytest.importorskip("pydantic")
        from emboss.adapters.pydantic_schema import DocumentSpec

        spec = DocumentSpec.model_validate(
            {
                "title": "Mobile",
                "page": {"preset": "compact"},
                "content": [{"type": "paragraph", "text": "Hello mobile reader."}],
            }
        )
        page = spec.page.to_page_spec()
        assert page.width == pytest.approx(419.53, abs=0.01)
        assert page.margin_left == 40.0
        assert spec.to_document().render().startswith(b"%PDF")

    def test_a5_reachable_via_pydantic(self):
        pytest.importorskip("pydantic")
        from emboss.adapters.pydantic_schema import PageConfig

        page = PageConfig(preset="a5").to_page_spec()
        assert page.width == pytest.approx(419.53, abs=0.01)
        assert page.margin_left == 72.0

    def test_spec_prompt_mentions_compact(self):
        from emboss import spec_prompt

        prompt = spec_prompt()
        assert "compact" in prompt
        assert "a5" in prompt
