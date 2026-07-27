"""End-to-end tests for CMYK color mode across the full render pipeline.

Renders complete documents in cmyk mode, decompresses every content
stream, and asserts that only CMYK (k/K) color operators are emitted —
and that rgb mode stays pure RGB (rg/RG). Also covers cmyk() string
colors, spot color Separation resources, the CMYK PDF/A output intent,
and byte-for-byte determinism in both modes.
"""

from __future__ import annotations

import re
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document  # noqa: E402
from emboss.colors import CmykColor, SpotColor, resolve_color  # noqa: E402
from emboss.charts import ChartData, ChartSpec, render_chart  # noqa: E402
from emboss.pdf.streams import ContentStream  # noqa: E402
from emboss.spec import HeaderFooter, LegalFeatures, TextRun  # noqa: E402

_SVG = (
    '<svg width="120" height="80" viewBox="0 0 120 80">'
    '<rect x="4" y="4" width="40" height="30" fill="#3b82f6" stroke="#1d4ed8"/>'
    '<circle cx="80" cy="30" r="20" fill="#ef4444" stroke="black"/>'
    '<ellipse cx="30" cy="60" rx="16" ry="9" fill="#22c55e"/>'
    '<line x1="0" y1="78" x2="120" y2="78" stroke="#44403c"/>'
    '<path d="M60 50 L70 70 L50 70 Z" fill="#f59e0b" stroke="#78350f"/>'
    '<polygon points="100,50 115,70 90,70" fill="#8b5cf6"/>'
    "</svg>"
)


def _full_document(color_mode: str) -> Document:
    """Build a document exercising every color-emitting draw path."""
    doc = Document(
        title="Print Production Test",
        author="Emboss",
        color_mode=color_mode,
        header=HeaderFooter(left="Report", right="{page} / {pages}"),
        footer=HeaderFooter(center="Confidential", separator_line=True),
        legal=LegalFeatures(watermark="DRAFT"),
    )
    doc.heading("Quarterly Results", level=2)
    doc.paragraph("Body text with a colored run: ")
    doc.paragraph(TextRun("emphasized figures", color="dc2626"))
    doc.table(
        ["Region", "Revenue"],
        [["North", "120"], ["South", "80"], ["East", "95"]],
        stripe=True,
    )
    doc.callout("Margins improved year over year.", variant="info")
    doc.code_block("total = sum(values)\nprint(total)", language="python")
    doc.chart("bar", ["Q1", "Q2", "Q3"], [10.0, 20.0, 15.0], title="Revenue")
    doc.chart("line", ["Jan", "Feb", "Mar"], [3.0, 7.0, 5.0])
    doc.chart("pie", ["A", "B"], [60.0, 40.0])
    doc.rule()
    doc.svg(_SVG)
    return doc


def _content_ops(pdf: bytes) -> bytes:
    """Extract and concatenate all decompressed page content streams."""
    parts = []
    for match in re.finditer(rb"stream\r?\n(.*?)\nendstream", pdf, re.S):
        data = match.group(1)
        try:
            data = zlib.decompress(data)
        except zlib.error:
            pass
        if b"BT" in data and b"ET" in data:
            parts.append(data)
    assert parts, "no content streams found in PDF"
    return b"\n".join(parts)


def _operator_soup(pdf: bytes) -> bytes:
    """Content stream operators with string literals stripped out."""
    ops = _content_ops(pdf)
    ops = re.sub(rb"\((?:\\.|[^\\()])*\)", b"", ops)
    return re.sub(rb"<[0-9A-Fa-f]*>", b"", ops)


def _count(soup: bytes, op: bytes) -> int:
    return len(re.findall(rb"(?:^|[\s])" + op + rb"(?=[\s]|$)", soup))


# ---------------------------------------------------------------------------
# Full-document color mode sweeps
# ---------------------------------------------------------------------------


class TestCmykDocument:
    def test_cmyk_mode_emits_only_cmyk_operators(self):
        pdf = _full_document("cmyk").render()
        soup = _operator_soup(pdf)
        assert _count(soup, b"k") > 0
        assert _count(soup, b"K") > 0
        assert _count(soup, b"rg") == 0
        assert _count(soup, b"RG") == 0

    def test_rgb_mode_emits_only_rgb_operators(self):
        pdf = _full_document("rgb").render()
        soup = _operator_soup(pdf)
        assert _count(soup, b"rg") > 0
        assert _count(soup, b"RG") > 0
        assert _count(soup, b"k") == 0
        assert _count(soup, b"K") == 0

    def test_determinism_both_modes(self):
        for mode in ("rgb", "cmyk"):
            first = _full_document(mode).render()
            second = _full_document(mode).render()
            assert first == second, f"non-deterministic output in {mode} mode"

    def test_modes_differ(self):
        assert _full_document("rgb").render() != _full_document("cmyk").render()


# ---------------------------------------------------------------------------
# cmyk() string colors
# ---------------------------------------------------------------------------


class TestCmykStringColors:
    def test_resolve_color_cmyk_string(self):
        color = resolve_color("cmyk(0,100,100,0)")
        assert isinstance(color, CmykColor)
        assert color.components == (0.0, 1.0, 1.0, 0.0)

    def test_resolve_color_cmyk_fractions(self):
        color = resolve_color("cmyk(0.2,0.4,0.6,0.8)")
        assert isinstance(color, CmykColor)
        assert color.c == 0.2

    def test_resolve_color_hex_still_works(self):
        assert resolve_color("2563eb") == "2563eb"
        assert resolve_color("blue-600") == "2563eb"
        assert resolve_color("primary") == "2563eb"

    def test_cmyk_string_emits_exact_components(self):
        doc = Document(title="Exact", color_mode="cmyk")
        doc.paragraph(TextRun("pure magenta+yellow", color="cmyk(0,100,100,0)"))
        soup = _operator_soup(doc.render())
        assert re.search(rb"(?:^|[\s])0 1 1 0 k(?=[\s]|$)", soup)

    def test_cmyk_string_converts_in_rgb_mode(self):
        doc = Document(title="Converted", color_mode="rgb")
        doc.paragraph(TextRun("red via cmyk", color="cmyk(0,100,100,0)"))
        soup = _operator_soup(doc.render())
        assert re.search(rb"(?:^|[\s])1 0 0 rg(?=[\s]|$)", soup)
        assert _count(soup, b"k") == 0

    def test_cmyk_object_accepted_by_funnel(self):
        stream = ContentStream(color_mode="cmyk")
        stream.set_fill(CmykColor(0.1, 0.2, 0.3, 0.4))
        assert b"0.1 0.2 0.3 0.4 k" in stream.to_bytes()

    def test_cmyk_object_converts_in_rgb_funnel(self):
        stream = ContentStream()
        stream.set_fill(CmykColor(0.0, 1.0, 1.0, 0.0))
        assert b"1 0 0 rg" in stream.to_bytes()


# ---------------------------------------------------------------------------
# Spot colors
# ---------------------------------------------------------------------------


class TestSpotColors:
    def test_resolve_color_spot_string(self):
        color = resolve_color("spot(PANTONE 485 C,0,100,95,0)")
        assert isinstance(color, SpotColor)
        assert color.name == "PANTONE 485 C"
        assert color.m == 1.0
        assert color.y == 0.95

    def test_spot_document_resources_and_operators(self):
        doc = Document(title="Spot", color_mode="cmyk")
        doc.paragraph(TextRun("brand red", color="spot(PANTONE 485 C,0,100,95,0)"))
        pdf = doc.render()
        assert b"/Separation" in pdf
        assert b"/ColorSpace" in pdf
        assert b"/CSPANTONE485C" in pdf
        assert b"/DeviceCMYK" in pdf
        soup = _operator_soup(pdf)
        assert re.search(rb"/CSPANTONE485C cs", soup)
        assert _count(soup, b"scn") > 0
        assert _count(soup, b"rg") == 0

    def test_spot_object_via_funnel_records_usage(self):
        stream = ContentStream(color_mode="cmyk")
        stream.set_fill(SpotColor("My Spot!", 0.5, 0.5, 0.0, 0.0))
        stream.set_stroke(SpotColor("My Spot!", 0.5, 0.5, 0.0, 0.0))
        output = stream.to_bytes()
        assert b"/CSMySpot cs" in output
        assert b"/CSMySpot CS" in output
        assert b"scn" in output and b"SCN" in output
        assert list(stream.used_spots) == ["My Spot!"]

    def test_spot_document_is_deterministic(self):
        def build() -> bytes:
            doc = Document(title="Spot", color_mode="cmyk")
            doc.paragraph(TextRun("a", color="spot(Gold,10,20,80,5)"))
            doc.paragraph(TextRun("b", color="spot(Navy,100,80,0,40)"))
            return doc.render()

        assert build() == build()


# ---------------------------------------------------------------------------
# Charts route through the color funnel
# ---------------------------------------------------------------------------


class TestChartColorMode:
    def _render(self, mode: str) -> bytes:
        stream = ContentStream(color_mode=mode)
        data = ChartData(labels=["A", "B"], values=[1.0, 2.0], title="T")
        for kind in ("bar", "line", "pie"):
            spec = ChartSpec(chart_type=kind, data=data)
            render_chart(stream, spec, 50.0, 700.0, "F1", 9.0)
        return stream.to_bytes()

    def test_chart_cmyk(self):
        ops = self._render("cmyk")
        soup = re.sub(rb"\((?:\\.|[^\\()])*\)", b"", ops)
        assert _count(soup, b"k") > 0
        assert _count(soup, b"K") > 0
        assert _count(soup, b"rg") == 0
        assert _count(soup, b"RG") == 0

    def test_chart_rgb(self):
        ops = self._render("rgb")
        soup = re.sub(rb"\((?:\\.|[^\\()])*\)", b"", ops)
        assert _count(soup, b"rg") > 0
        assert _count(soup, b"k") == 0


# ---------------------------------------------------------------------------
# PDF/A output intent
# ---------------------------------------------------------------------------


class TestPdfaOutputIntent:
    def test_cmyk_output_intent_n4(self):
        doc = Document(title="Print Archive", color_mode="cmyk", pdfa=True)
        doc.paragraph("archived print document")
        pdf = doc.render()
        assert b"/OutputIntents" in pdf
        assert b"/N 4" in pdf
        assert b"CGATS TR 001" in pdf

    def test_rgb_output_intent_n3(self):
        doc = Document(title="Screen Archive", color_mode="rgb", pdfa=True)
        doc.paragraph("archived screen document")
        pdf = doc.render()
        assert b"/N 3" in pdf
        assert b"sRGB IEC61966-2.1" in pdf
        assert b"/N 4" not in pdf

    def test_pdfa_cmyk_deterministic(self):
        def build() -> bytes:
            doc = Document(title="PA", color_mode="cmyk", pdfa=True)
            doc.paragraph("x")
            return doc.render()

        assert build() == build()
