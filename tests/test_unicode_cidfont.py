"""Tests for Unicode CIDFont/Type0 font embedding.

Verifies that embedded fonts use the Type0/CIDFontType2 architecture
with Identity-H encoding and 2-byte glyph IDs, supporting the full
Unicode range. Also tests the hex encoding path in content streams.
"""

import pytest

from precisionpdf import Document
from precisionpdf.styles import Style
from precisionpdf.pdf.streams import _escape_text, _cid_encode_text, _encode_text
from precisionpdf.typography.font_metrics import FontMetrics


def _make_test_font(path, glyph_chars=None):
    """Build a minimal valid TrueType font for testing."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    if glyph_chars is None:
        glyph_chars = {32: "space", 65: "A", 66: "B", 67: "C"}

    glyph_names = [".notdef"] + list(glyph_chars.values())
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(glyph_names)
    fb.setupCharacterMap(glyph_chars)

    glyphs = {}
    metrics = {}

    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((500, 0))
    pen.lineTo((500, 700))
    pen.lineTo((0, 700))
    pen.closePath()
    glyphs[".notdef"] = pen.glyph()
    metrics[".notdef"] = (500, 0)

    for cp, name in glyph_chars.items():
        pen = TTGlyphPen(None)
        if name == "space":
            pen.moveTo((0, 0))
            pen.endPath()
            glyphs[name] = pen.glyph()
            metrics[name] = (250, 0)
        else:
            w = 500 + (cp % 200)
            pen.moveTo((0, 0))
            pen.lineTo((w, 0))
            pen.lineTo((w, 700))
            pen.lineTo((0, 700))
            pen.closePath()
            glyphs[name] = pen.glyph()
            metrics[name] = (w, 0)

    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "TestFont", "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, sCapHeight=700)
    fb.setupPost()
    fb.font.save(str(path))
    return path


# ===========================================================================
# STREAM ENCODING
# ===========================================================================

class TestCIDEncoding:
    def test_escape_text_ascii(self):
        result = _escape_text("Hello")
        assert result == b"(Hello)"

    def test_escape_text_parens(self):
        result = _escape_text("a(b)")
        assert result == b"(a\\(b\\))"

    def test_escape_text_backslash(self):
        result = _escape_text("a\\b")
        assert result == b"(a\\\\b)"

    def test_cid_encode_basic(self):
        gid_map = {72: 10, 105: 20}
        result = _cid_encode_text("Hi", gid_map)
        assert result == b"<000A0014>"

    def test_cid_encode_missing_glyph(self):
        gid_map = {72: 10}
        result = _cid_encode_text("Hi", gid_map)
        assert result == b"<000A0000>"

    def test_cid_encode_empty(self):
        result = _cid_encode_text("", {})
        assert result == b"<>"

    def test_encode_text_selects_mode(self):
        result_literal = _encode_text("AB", None)
        assert result_literal.startswith(b"(")

        gid_map = {65: 1, 66: 2}
        result_cid = _encode_text("AB", gid_map)
        assert result_cid.startswith(b"<")
        assert result_cid == b"<00010002>"

    def test_cid_encode_large_gids(self):
        gid_map = {65: 0xFFFF}
        result = _cid_encode_text("A", gid_map)
        assert result == b"<FFFF>"

    def test_cid_encode_unicode_codepoints(self):
        gid_map = {0x4E16: 500, 0x754C: 501}
        result = _cid_encode_text("世界", gid_map)
        assert result == b"<01F401F5>"


# ===========================================================================
# FONT METRICS GID MAP
# ===========================================================================

class TestFontMetricsGIDMap:
    def test_base14_no_gid_map(self):
        metrics = FontMetrics.base14("Helvetica")
        assert metrics.gid_map is None

    def test_base14_not_embedded(self):
        metrics = FontMetrics.base14("Times-Roman")
        assert not metrics.is_embedded
        assert metrics.gid_map is None

    @pytest.fixture
    def ttf_path(self, tmp_path):
        try:
            from fontTools.fontBuilder import FontBuilder
        except ImportError:
            pytest.skip("fontTools required for embedded font tests")
        return _make_test_font(tmp_path / "test_font.ttf")

    def test_embedded_font_has_gid_map(self, ttf_path):
        metrics = FontMetrics.from_file(ttf_path)
        assert metrics.is_embedded
        assert metrics.gid_map is not None
        assert 65 in metrics.gid_map
        assert 66 in metrics.gid_map
        assert 67 in metrics.gid_map

    def test_gid_map_values_are_ints(self, ttf_path):
        metrics = FontMetrics.from_file(ttf_path)
        for cp, gid in metrics.gid_map.items():
            assert isinstance(cp, int)
            assert isinstance(gid, int)
            assert gid >= 0


# ===========================================================================
# FONT BUILDING
# ===========================================================================

class TestCIDFontBuilding:
    @pytest.fixture
    def ttf_path(self, tmp_path):
        try:
            from fontTools.fontBuilder import FontBuilder
        except ImportError:
            pytest.skip("fontTools required")
        return _make_test_font(tmp_path / "cidtest.ttf")

    def test_embedded_produces_type0(self, ttf_path):
        doc = Document(title="CID Font Test")
        doc.fonts.register("TestFont", str(ttf_path))
        doc.paragraph("AB", style=Style(font_family="TestFont"))
        pdf = doc.render()

        assert b"/Type /Font" in pdf
        assert b"/Subtype /Type0" in pdf
        assert b"/Encoding /Identity-H" in pdf
        assert b"/Subtype /CIDFontType2" in pdf
        assert b"/CIDToGIDMap /Identity" in pdf

    def test_tounicode_cmap_2byte(self, ttf_path):
        import re, zlib
        doc = Document(title="ToUnicode Test")
        doc.fonts.register("TestFont", str(ttf_path))
        doc.paragraph("AB", style=Style(font_family="TestFont"))
        pdf = doc.render()

        assert b"/ToUnicode" in pdf
        # Extract and decompress streams
        decompressed = b""
        for m in re.finditer(rb"stream\n(.*?)\nendstream", pdf, re.DOTALL):
            raw = m.group(1)
            try:
                decompressed += zlib.decompress(raw)
            except Exception:
                decompressed += raw

        assert b"<0000> <FFFF>" in decompressed
        assert b"beginbfchar" in decompressed

    def test_content_stream_uses_hex(self, ttf_path):
        doc = Document(title="Hex Stream Test")
        doc.fonts.register("TestFont", str(ttf_path))
        doc.paragraph("A", style=Style(font_family="TestFont"))
        pdf = doc.render()

        assert b"/Identity-H" in pdf

    def test_base14_still_uses_winansi(self):
        doc = Document(title="Base14 Test")
        doc.paragraph("Hello World")
        pdf = doc.render()

        assert b"/Subtype /Type1" in pdf
        assert b"/Encoding /WinAnsiEncoding" in pdf
        assert b"/Type0" not in pdf

    def test_deterministic_with_embedded_font(self, ttf_path):
        def make():
            doc = Document(title="Deterministic CID")
            doc.fonts.register("TestFont", str(ttf_path))
            doc.paragraph("AB", style=Style(font_family="TestFont"))
            return doc.render()

        assert make() == make()

    def test_mixed_base14_and_embedded(self, ttf_path):
        doc = Document(title="Mixed Fonts")
        doc.fonts.register("TestFont", str(ttf_path))
        doc.paragraph("Hello World")
        doc.paragraph("AB", style=Style(font_family="TestFont"))
        pdf = doc.render()

        assert b"/Subtype /Type1" in pdf
        assert b"/Subtype /Type0" in pdf


# ===========================================================================
# SUBSET RETENTION
# ===========================================================================

class TestSubsetRetainGIDs:
    @pytest.fixture
    def ttf_path(self, tmp_path):
        try:
            from fontTools.fontBuilder import FontBuilder
        except ImportError:
            pytest.skip("fontTools required")
        chars = {32: "space"}
        for i in range(65, 91):
            chars[i] = f"uni{i:04X}"
        return _make_test_font(tmp_path / "alpha.ttf", chars)

    def test_subset_preserves_gids(self, ttf_path):
        from precisionpdf.pdf.fonts import _subset_font

        metrics = FontMetrics.from_file(ttf_path)
        original_gids = dict(metrics.gid_map)

        metrics.note_usage("ABC")
        data, codepoints = _subset_font(metrics)

        from fontTools.ttLib import TTFont
        from io import BytesIO
        subset = TTFont(BytesIO(data))
        subset_cmap = subset.getBestCmap()

        for cp in [65, 66, 67]:
            assert cp in subset_cmap
            subset_gid = subset.getGlyphID(subset_cmap[cp])
            assert subset_gid == original_gids[cp]

        subset.close()


# ===========================================================================
# END-TO-END RENDERING
# ===========================================================================

class TestUnicodeEndToEnd:
    @pytest.fixture
    def ttf_path(self, tmp_path):
        try:
            from fontTools.fontBuilder import FontBuilder
        except ImportError:
            pytest.skip("fontTools required")
        chars = {32: "space"}
        for i in range(65, 91):
            chars[i] = f"uni{i:04X}"
        return _make_test_font(tmp_path / "unicode.ttf", chars)

    def test_full_render_with_embedded_font(self, ttf_path):
        doc = Document(title="Full Unicode Doc")
        doc.fonts.register("Unicode", str(ttf_path))
        doc.heading("TEST HEADING", level=1,
                     style=Style(font_family="Unicode"))
        doc.paragraph("ABC DEF GHI",
                       style=Style(font_family="Unicode"))
        doc.paragraph("JKL MNO PQR",
                       style=Style(font_family="Unicode"))

        pdf = doc.render()
        assert b"%PDF-1.7" in pdf
        assert b"/Subtype /Type0" in pdf
        assert b"/Identity-H" in pdf
        assert b"%%EOF" in pdf

    def test_embedded_font_with_table(self, ttf_path):
        doc = Document(title="Table with CIDFont")
        doc.fonts.register("Unicode", str(ttf_path))
        doc.table(
            ["COL A", "COL B"],
            [["ABC", "DEF"], ["GHI", "JKL"]],
            style=Style(font_family="Unicode"),
        )
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf
        assert b"/Subtype /Type0" in pdf

    def test_embedded_font_with_bullet_list(self, ttf_path):
        doc = Document(title="List with CIDFont")
        doc.fonts.register("Unicode", str(ttf_path))
        doc.bullet_list(
            ["ABC DEF", "GHI JKL"],
            style=Style(font_family="Unicode"),
        )
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_verification_passes(self, ttf_path):
        from precisionpdf.pdf.verify import verify_pdf

        doc = Document(title="Verified CID")
        doc.fonts.register("Unicode", str(ttf_path))
        doc.paragraph("ABC DEF", style=Style(font_family="Unicode"))
        pdf = doc.render()

        report = verify_pdf(pdf)
        assert report.ok, f"Verification failed: {report.problems}"

    def test_structure_tree_with_embedded(self, ttf_path):
        doc = Document(title="Tagged CID", tagged=True)
        doc.fonts.register("Unicode", str(ttf_path))
        doc.heading("TITLE", level=1, style=Style(font_family="Unicode"))
        doc.paragraph("CONTENT", style=Style(font_family="Unicode"))
        pdf = doc.render()

        assert b"/StructTreeRoot" in pdf
        assert b"/ParentTree" in pdf
