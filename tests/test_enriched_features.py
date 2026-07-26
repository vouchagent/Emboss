"""Tests for enriched features: footnotes, callouts, colors, cross-refs, ligatures."""

import pytest

from precisionpdf import (
    Document, Footnote, Callout, ColorTheme, CrossReferenceIndex,
    resolve_color, PALETTES,
)
from precisionpdf.colors import _SEMANTIC
from precisionpdf.crossref import RefEntry
from precisionpdf.typography.ligatures import apply_ligatures, LIGATURE_MAP


# ===========================================================================
# COLOR THEME TESTS
# ===========================================================================

class TestColors:
    def test_hex_passthrough(self):
        assert resolve_color("2563eb") == "2563eb"
        assert resolve_color("FF0000") == "ff0000"

    def test_named_shade(self):
        assert resolve_color("blue-600") == "2563eb"
        assert resolve_color("red-500") == "ef4444"
        assert resolve_color("green-700") == "15803d"

    def test_semantic_names(self):
        assert resolve_color("primary") == "2563eb"
        assert resolve_color("danger") == "dc2626"
        assert resolve_color("success") == "16a34a"

    def test_unknown_color_raises(self):
        with pytest.raises(ValueError, match="unknown color"):
            resolve_color("rainbow-42")

    def test_all_palettes_complete(self):
        for name, palette in PALETTES.items():
            assert "500" in palette, f"{name} missing shade 500"
            assert "100" in palette, f"{name} missing shade 100"
            assert "900" in palette, f"{name} missing shade 900"

    def test_color_theme(self):
        theme = ColorTheme(brand="blue-600", highlight="amber-500")
        assert theme.resolve("brand") == "2563eb"
        assert theme.resolve("highlight") == "f59e0b"
        assert theme.resolve("red-500") == "ef4444"

    def test_color_theme_hex_input(self):
        theme = ColorTheme(custom="abcdef")
        assert theme.resolve("custom") == "abcdef"

    def test_palette_coverage(self):
        expected_colors = {"slate", "gray", "red", "orange", "amber",
                           "green", "blue", "indigo", "purple", "pink", "teal"}
        assert expected_colors <= set(PALETTES.keys())


# ===========================================================================
# FOOTNOTE TESTS
# ===========================================================================

class TestFootnotes:
    def test_footnote_creation(self):
        fn = Footnote(content="See appendix A.", marker="1")
        assert fn.marker == "1"
        assert fn.structure_tag == "Note"
        assert len(fn.runs) == 1

    def test_footnote_default_marker(self):
        fn = Footnote(content="Default marker")
        assert fn.marker is None

    def test_footnote_in_document(self):
        doc = Document(title="Footnote Test")
        doc.paragraph("Main text with a footnote reference.")
        doc.footnote("Source: Annual Report 2024", marker="1")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf
        assert b"/Note" in pdf

    def test_multiple_footnotes(self):
        doc = Document(title="Multi Footnotes")
        doc.paragraph("First reference.")
        doc.footnote("First source.", marker="1")
        doc.paragraph("Second reference.")
        doc.footnote("Second source.", marker="2")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_footnote_via_convenience(self):
        doc = Document(title="Convenience")
        doc.footnote("This is a footnote.", marker="*")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf


# ===========================================================================
# CALLOUT TESTS
# ===========================================================================

class TestCallouts:
    def test_callout_creation(self):
        c = Callout(content="Important note.", variant="info")
        assert c.variant == "info"
        assert c.background == "eff6ff"
        assert c.border_color == "3b82f6"
        assert c.icon == "i"
        assert c.structure_tag == "Div"

    def test_callout_variants(self):
        for variant in ("info", "warning", "success", "danger", "note"):
            c = Callout(content="Test", variant=variant)
            assert c.background is not None
            assert c.border_color is not None

    def test_callout_in_document(self):
        doc = Document(title="Callout Test")
        doc.callout("This is important.", variant="warning", title="Warning")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_callout_all_variants_render(self):
        for variant in ("info", "warning", "success", "danger", "note"):
            doc = Document(title=f"Callout {variant}")
            doc.callout(f"This is a {variant} callout.", variant=variant)
            pdf = doc.render()
            assert b"%PDF-1.7" in pdf

    def test_callout_with_title(self):
        doc = Document(title="Titled Callout")
        doc.callout("Check this out.", variant="info", title="Note")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_callout_custom_colors(self):
        c = Callout(
            content="Custom", variant="note",
            background="e0f2fe", border_color="0284c7",
        )
        assert c.background == "e0f2fe"
        assert c.border_color == "0284c7"


# ===========================================================================
# CROSS-REFERENCE TESTS
# ===========================================================================

class TestCrossReferences:
    def test_basic_cross_ref(self):
        doc = Document(title="CrossRef")
        doc.heading("Introduction", level=1, anchor="sec:intro")
        doc.table(["A"], [["1"]], caption="Data summary")
        doc.heading("Methods", level=1, anchor="sec:methods")

        idx = CrossReferenceIndex(doc)
        assert idx.label("sec:intro") == "Section 1"
        assert idx.label("sec:methods") == "Section 2"

    def test_figure_numbering(self, tmp_path):
        import struct, zlib, binascii

        def make_png():
            buf = bytearray(b"\x89PNG\r\n\x1a\n")
            ihdr = struct.pack(">IIBB", 4, 4, 8, 2) + b"\x00\x00\x00"
            buf += struct.pack(">I", len(ihdr))
            buf += b"IHDR" + ihdr
            crc = binascii.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF
            buf += struct.pack(">I", crc)
            raw = b""
            for _ in range(4):
                raw += b"\x00" + b"\xff\x00\x00" * 4
            compressed = zlib.compress(bytes(raw), 6)
            buf += struct.pack(">I", len(compressed))
            buf += b"IDAT" + compressed
            crc = binascii.crc32(b"IDAT" + compressed) & 0xFFFFFFFF
            buf += struct.pack(">I", crc)
            buf += struct.pack(">I", 0) + b"IEND"
            crc = binascii.crc32(b"IEND") & 0xFFFFFFFF
            buf += struct.pack(">I", crc)
            return bytes(buf)

        png_path = tmp_path / "fig.png"
        png_path.write_bytes(make_png())

        doc = Document(title="Figures")
        doc.image(str(png_path), caption="Revenue chart", alt_text="chart")
        doc.image(str(png_path), caption="Cost breakdown", alt_text="costs")

        idx = CrossReferenceIndex(doc)
        assert idx.label("fig:1") == "Figure 1"
        assert idx.label("fig:2") == "Figure 2"

    def test_table_numbering(self):
        doc = Document(title="Tables")
        doc.table(["X"], [["1"]], caption="First table")
        doc.table(["Y"], [["2"]], caption="Second table")

        idx = CrossReferenceIndex(doc)
        assert idx.label("tbl:1") == "Table 1"
        assert idx.label("tbl:2") == "Table 2"

    def test_unknown_ref(self):
        doc = Document(title="Empty")
        doc.paragraph("No refs.")
        idx = CrossReferenceIndex(doc)
        assert idx.label("unknown") == "[unknown?]"
        assert idx.number("unknown") is None

    def test_resolve_text(self):
        doc = Document(title="Resolve")
        doc.heading("Intro", level=1, anchor="sec:intro")
        doc.table(["A"], [["1"]], caption="Data")

        idx = CrossReferenceIndex(doc)
        text = idx.resolve_text("See @sec:intro and @tbl:1 for details.")
        assert "Section 1" in text
        assert "Table 1" in text

    def test_entry_lists(self):
        doc = Document(title="Lists")
        doc.heading("A", level=1, anchor="a")
        doc.table(["X"], [["1"]], caption="T1")
        doc.heading("B", level=1, anchor="b")

        idx = CrossReferenceIndex(doc)
        assert len(idx.sections()) == 2
        assert len(idx.tables()) == 1
        assert len(idx.all_entries()) == 3


# ===========================================================================
# LIGATURE TESTS
# ===========================================================================

class TestLigatures:
    def test_fi_ligature(self):
        result = apply_ligatures("find")
        assert "fi" not in result or result != "find"
        assert LIGATURE_MAP["fi"] in result

    def test_fl_ligature(self):
        result = apply_ligatures("flow")
        assert LIGATURE_MAP["fl"] in result

    def test_ffi_ligature(self):
        result = apply_ligatures("office")
        assert LIGATURE_MAP["ffi"] in result

    def test_no_change_without_ligatures(self):
        assert apply_ligatures("hello") == "hello"

    def test_multiple_ligatures(self):
        result = apply_ligatures("find the file")
        assert result.count(LIGATURE_MAP["fi"]) == 2
        assert LIGATURE_MAP["fl"] not in result

    def test_font_support_filter(self):
        result = apply_ligatures("find", font_supports=lambda c: False)
        assert result == "find"

    def test_ligature_map_complete(self):
        assert "fi" in LIGATURE_MAP
        assert "fl" in LIGATURE_MAP
        assert "ffi" in LIGATURE_MAP
        assert "ffl" in LIGATURE_MAP


# ===========================================================================
# PYDANTIC ADAPTER TESTS
# ===========================================================================

class TestPydanticEnrichedTypes:
    def test_footnote_spec(self):
        from precisionpdf.adapters.pydantic_schema import DocumentSpec
        data = {
            "title": "FN Test",
            "content": [
                {"type": "paragraph", "text": "Main text."},
                {"type": "footnote", "text": "Source info.", "marker": "1"},
            ],
        }
        spec = DocumentSpec.model_validate(data)
        doc = spec.to_document()
        assert isinstance(doc.content[1], Footnote)

    def test_callout_spec(self):
        from precisionpdf.adapters.pydantic_schema import DocumentSpec
        data = {
            "title": "Callout Test",
            "content": [
                {
                    "type": "callout",
                    "text": "Important!",
                    "variant": "warning",
                    "title": "Heads up",
                },
            ],
        }
        spec = DocumentSpec.model_validate(data)
        doc = spec.to_document()
        assert isinstance(doc.content[0], Callout)
        assert doc.content[0].variant == "warning"


# ===========================================================================
# EXPORT ADAPTER TESTS
# ===========================================================================

class TestExportAdaptersEnriched:
    def test_html_footnote(self):
        from precisionpdf.adapters.html_export import to_html
        doc = Document(title="HTML FN")
        doc.footnote("Source data.", marker="1")
        html = to_html(doc)
        assert "footnote" in html
        assert "Source data" in html

    def test_html_callout(self):
        from precisionpdf.adapters.html_export import to_html
        doc = Document(title="HTML Callout")
        doc.callout("Be careful!", variant="danger", title="Danger")
        html = to_html(doc)
        assert "callout-danger" in html
        assert "Danger" in html

    def test_markdown_footnote(self):
        from precisionpdf.adapters.markdown_export import to_markdown
        doc = Document(title="MD FN")
        doc.footnote("Ref 1.", marker="1")
        md = to_markdown(doc)
        assert "[^1]:" in md

    def test_markdown_callout(self):
        from precisionpdf.adapters.markdown_export import to_markdown
        doc = Document(title="MD Callout")
        doc.callout("Note this.", variant="info", title="Info")
        md = to_markdown(doc)
        assert "> " in md
        assert "Info" in md

    def test_office_footnote(self):
        from precisionpdf.adapters.docx_export import to_office_dict
        doc = Document(title="Office FN")
        doc.footnote("Source.", marker="*")
        data = to_office_dict(doc)
        assert data["content"][0]["type"] == "footnote"

    def test_office_callout(self):
        from precisionpdf.adapters.docx_export import to_office_dict
        doc = Document(title="Office Callout")
        doc.callout("Note.", variant="success")
        data = to_office_dict(doc)
        assert data["content"][0]["type"] == "callout"


# ===========================================================================
# INTEGRATION: FULL DOCUMENT WITH ENRICHED FEATURES
# ===========================================================================

class TestEnrichedIntegration:
    def test_rich_document(self):
        doc = Document(title="Enriched Document", style="corporate")
        doc.heading("Executive Summary", level=1)
        doc.paragraph("This report covers Q3 performance.")
        doc.callout(
            "Revenue exceeded projections by 15%.",
            variant="success",
            title="Highlight",
        )
        doc.paragraph("Detailed analysis follows.")
        doc.footnote("Based on preliminary data.", marker="1")
        doc.callout(
            "Tax implications are still being reviewed.",
            variant="warning",
        )
        doc.heading("Methodology", level=2)
        doc.paragraph("Standard valuation methods were applied.")
        doc.footnote("See methodology appendix.", marker="2")

        pdf = doc.render()
        assert b"%PDF-1.7" in pdf
        assert b"/Note" in pdf

    def test_deterministic_with_new_features(self):
        def make():
            doc = Document(title="Determinism")
            doc.callout("Info here.", variant="info")
            doc.footnote("Source.", marker="1")
            return doc.render()

        assert make() == make()
