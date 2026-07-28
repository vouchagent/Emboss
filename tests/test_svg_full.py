"""Tests for the full static SVG subset: paths, transforms, gradients, text."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from emboss import Document  # noqa: E402
from emboss.pdf.streams import ContentStream  # noqa: E402
from emboss.svg import gradient_shading, parse_svg, render_svg  # noqa: E402
from emboss.typography.font_metrics import FontMetrics  # noqa: E402


def _render(source: str, mode: str = "rgb") -> ContentStream:
    svg = parse_svg(source)
    stream = ContentStream(color_mode=mode)
    render_svg(stream, svg, 0.0, svg.height, svg.width, svg.height)
    return stream


def _ops(stream: ContentStream) -> str:
    return stream.to_bytes().decode("latin-1")


def _lines(stream: ContentStream) -> list:
    return _ops(stream).strip("\n").split("\n")


def _floats(line: str) -> list:
    return [float(tok) for tok in line.split()[:-1]]


def _svg(body: str, w: int = 100, h: int = 100) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">{body}</svg>'
    )


class TestPathCommands:
    def test_arc_quarter_circle_endpoint_math(self):
        stream = _render(
            _svg(
                '<path d="M 10 0 A 10 10 0 0 1 0 10" fill="none" stroke="black"/>',
                w=20,
                h=20,
            )
        )
        curves = [ln for ln in _lines(stream) if ln.endswith(" c")]
        assert len(curves) == 1
        vals = _floats(curves[0])
        k = 5.5228475
        assert vals == pytest.approx([10.0, 20 - k, k, 10.0, 0.0, 10.0], abs=2e-3)

    def test_arc_half_circle_splits_at_90_degrees(self):
        stream = _render(
            _svg(
                '<path d="M 10 10 A 5 5 0 0 1 0 10" fill="none" stroke="black"/>',
                w=20,
                h=20,
            )
        )
        curves = [ln for ln in _lines(stream) if ln.endswith(" c")]
        assert len(curves) == 2
        assert _floats(curves[1])[-2:] == pytest.approx([0.0, 10.0], abs=2e-3)

    def test_quadratic_converts_to_cubic(self):
        stream = _render(
            _svg('<path d="M 0 0 Q 10 0 10 10" fill="none" stroke="black"/>', 20, 20)
        )
        curves = [ln for ln in _lines(stream) if ln.endswith(" c")]
        assert len(curves) == 1
        expected = [20.0 / 3.0, 20.0, 10.0, 20.0 - 10.0 / 3.0, 10.0, 10.0]
        assert _floats(curves[0]) == pytest.approx(expected, abs=2e-3)

    def test_smooth_quadratic_reflects_control(self):
        stream = _render(
            _svg(
                '<path d="M 0 0 Q 10 0 10 10 T 20 20" fill="none" stroke="black"/>',
                20,
                20,
            )
        )
        curves = [ln for ln in _lines(stream) if ln.endswith(" c")]
        assert len(curves) == 2
        expected = [10.0, 20.0 - 50.0 / 3.0, 40.0 / 3.0, 0.0, 20.0, 0.0]
        assert _floats(curves[1]) == pytest.approx(expected, abs=2e-3)

    def test_smooth_cubic_reflects_control(self):
        stream = _render(
            _svg(
                '<path d="M 0 0 C 0 10 10 10 10 0 S 20 -10 20 0"'
                ' fill="none" stroke="black"/>',
                20,
                20,
            )
        )
        curves = [ln for ln in _lines(stream) if ln.endswith(" c")]
        assert len(curves) == 2
        assert _floats(curves[1])[:2] == pytest.approx([10.0, 30.0], abs=2e-3)

    def test_implicit_repeat_and_number_forms(self):
        stream = _render(
            _svg('<path d="M0,0 10,20 3e1,10" fill="none" stroke="black"/>', 40, 40)
        )
        lines = _lines(stream)
        assert "10.0000 20.0000 l" in lines
        assert "30.0000 30.0000 l" in lines


class TestTransforms:
    def test_nested_group_transform_cm(self):
        stream = _render(
            _svg(
                '<g transform="translate(10,20)"><g transform="rotate(90)">'
                '<rect x="0" y="0" width="5" height="5" fill="red"/></g></g>'
            )
        )
        lines = _lines(stream)
        assert lines[0] == "q" and lines[-1] == "Q"
        cm = [ln for ln in lines if ln.endswith(" cm")]
        assert len(cm) == 1
        assert _floats(cm[0]) == pytest.approx([0, -1, -1, 0, 10, 80], abs=1e-6)
        assert lines.count("q") == lines.count("Q")

    def test_rotate_about_center(self):
        stream = _render(
            _svg(
                '<rect x="10" y="10" width="4" height="4" fill="red"'
                ' transform="rotate(90 10 10)"/>'
            )
        )
        cm = [ln for ln in _lines(stream) if ln.endswith(" cm")]
        assert _floats(cm[0]) == pytest.approx([0, -1, -1, 0, 20, 100], abs=1e-6)

    def test_untransformed_rect_has_no_cm(self):
        stream = _render(_svg('<rect x="0" y="0" width="5" height="5" fill="red"/>'))
        assert not any(ln.endswith(" cm") for ln in _lines(stream))


class TestUseDefs:
    def test_use_resolves_with_xy_translate(self):
        stream = _render(
            _svg(
                '<defs><rect id="box" width="10" height="10" fill="blue"/></defs>'
                '<use href="#box" x="5" y="7"/>'
            )
        )
        cm = [ln for ln in _lines(stream) if ln.endswith(" cm")]
        assert len(cm) == 1
        assert _floats(cm[0]) == pytest.approx([1, 0, 0, -1, 5, 93], abs=1e-6)

    def test_use_xlink_href(self):
        source = (
            '<svg xmlns="http://www.w3.org/2000/svg"'
            ' xmlns:xlink="http://www.w3.org/1999/xlink"'
            ' width="50" height="50">'
            '<defs><rect id="r" width="10" height="10" fill="red"/></defs>'
            '<use xlink:href="#r"/></svg>'
        )
        stream = _render(source)
        assert "re" in _ops(stream)

    def test_reference_cycle_terminates(self):
        stream = _render(
            _svg(
                '<g id="a"><rect width="2" height="2" fill="red"/>'
                '<use href="#b"/></g>'
                '<g id="b"><use href="#a"/></g>',
                10,
                10,
            )
        )
        data = stream.to_bytes()
        assert len(data) > 0
        assert data.decode("latin-1").count("re") <= 40


class TestGradients:
    LINEAR = _svg(
        '<defs><linearGradient id="lg">'
        '<stop offset="0" stop-color="#ff0000"/>'
        '<stop offset="50%" stop-color="#00ff00"/>'
        '<stop offset="1" stop-color="#0000ff"/>'
        "</linearGradient></defs>"
        '<rect x="0" y="0" width="100" height="50" fill="url(#lg)"/>',
        100,
        50,
    )
    RADIAL = _svg(
        '<defs><radialGradient id="rg">'
        '<stop offset="0" stop-color="white"/>'
        '<stop offset="1" stop-color="black"/>'
        "</radialGradient></defs>"
        '<circle cx="50" cy="25" r="20" fill="url(#rg)"/>',
        100,
        50,
    )

    def test_linear_shading_dict(self):
        svg = parse_svg(self.LINEAR)
        sh = gradient_shading(svg, "lg", (0.0, 0.0, 100.0, 50.0))
        assert sh["ShadingType"] == 2
        assert sh["ColorSpace"] == "DeviceRGB"
        assert sh["Coords"] == pytest.approx([0.0, 0.0, 100.0, 0.0])
        assert sh["Extend"] == [True, True]
        fn = sh["Function"]
        assert fn["FunctionType"] == 3
        assert fn["Bounds"] == pytest.approx([0.5])
        assert fn["Encode"] == [0.0, 1.0, 0.0, 1.0]
        first, second = fn["Functions"]
        assert first["FunctionType"] == 2 and first["N"] == 1.0
        assert first["C0"] == pytest.approx([1.0, 0.0, 0.0])
        assert first["C1"] == pytest.approx([0.0, 1.0, 0.0])
        assert second["C1"] == pytest.approx([0.0, 0.0, 1.0])

    def test_radial_shading_dict(self):
        svg = parse_svg(self.RADIAL)
        sh = gradient_shading(svg, "rg", (0.0, 0.0, 100.0, 50.0))
        assert sh["ShadingType"] == 3
        radius = 0.5 * math.hypot(100.0, 50.0) / math.sqrt(2.0)
        assert sh["Coords"] == pytest.approx([50.0, 25.0, 0.0, 50.0, 25.0, radius])
        fn = sh["Function"]
        assert fn["FunctionType"] == 2
        assert fn["C0"] == pytest.approx([1.0, 1.0, 1.0])
        assert fn["C1"] == pytest.approx([0.0, 0.0, 0.0])

    def test_linear_gradient_renders_clipped_bands(self):
        stream = _render(self.LINEAR)
        lines = _lines(stream)
        assert "W n" in lines
        assert lines.count("f") >= 20
        rg = [ln for ln in lines if ln.endswith(" rg")]
        assert len(rg) >= 24
        assert rg[0] == "0.9569 0.0431 0.0000 rg"
        assert rg[-1] == "0.0000 0.0431 0.9569 rg"

    def test_radial_gradient_renders_bands(self):
        stream = _render(self.RADIAL)
        lines = _lines(stream)
        assert "W n" in lines
        assert lines.count("f") >= 24

    def test_user_space_units(self):
        svg = parse_svg(
            _svg(
                '<defs><linearGradient id="u" gradientUnits="userSpaceOnUse"'
                ' x1="10" y1="0" x2="90" y2="0">'
                '<stop offset="0" stop-color="black"/>'
                '<stop offset="1" stop-color="white"/>'
                "</linearGradient></defs>"
                '<rect width="100" height="20" fill="url(#u)"/>'
            )
        )
        sh = gradient_shading(svg, "u", (0.0, 0.0, 100.0, 20.0))
        assert sh["Coords"] == pytest.approx([10.0, 0.0, 90.0, 0.0])


class TestClipPath:
    def test_clip_emits_w_n(self):
        stream = _render(
            _svg(
                '<defs><clipPath id="cp"><rect width="50" height="50"/></clipPath>'
                "</defs>"
                '<circle cx="50" cy="50" r="40" fill="red" clip-path="url(#cp)"/>'
            )
        )
        lines = _lines(stream)
        assert "W n" in lines
        assert lines.count("q") == lines.count("Q")
        assert any(ln.endswith(" c") for ln in lines)

    def test_group_clip_wraps_children(self):
        stream = _render(
            _svg(
                '<defs><clipPath id="cp"><path d="M0 0 H50 V50 H0 Z"/></clipPath>'
                "</defs>"
                '<g clip-path="url(#cp)"><rect width="80" height="80" fill="red"/>'
                "</g>"
            )
        )
        lines = _lines(stream)
        assert "W n" in lines
        assert lines.count("q") == lines.count("Q")


class TestText:
    def test_text_anchor_middle_offsets_half_width(self):
        stream = _render(
            _svg(
                '<text x="100" y="25" font-size="12" text-anchor="middle"'
                ' font-family="Helvetica">Hello</text>',
                200,
                50,
            )
        )
        width = FontMetrics.base14("Helvetica").text_width("Hello", 12.0)
        td = [ln for ln in _lines(stream) if ln.endswith(" Td")]
        assert len(td) == 1
        assert _floats(td[0]) == pytest.approx([100.0 - width / 2.0, 25.0], abs=1e-3)
        assert "(Hello) Tj" in _ops(stream)
        assert stream.used_svg_fonts == {"FsvgH": "Helvetica"}

    def test_text_anchor_end(self):
        stream = _render(
            _svg('<text x="90" y="10" font-size="10" text-anchor="end">Hi</text>')
        )
        width = FontMetrics.base14("Helvetica").text_width("Hi", 10.0)
        td = [ln for ln in _lines(stream) if ln.endswith(" Td")]
        assert _floats(td[0])[0] == pytest.approx(90.0 - width, abs=1e-3)

    def test_font_family_mapping(self):
        mono = _render(
            _svg('<text x="0" y="10" font-family="Courier New, monospace">m</text>')
        )
        serif = _render(_svg('<text x="0" y="10" font-family="serif">s</text>'))
        assert mono.used_svg_fonts == {"FsvgC": "Courier"}
        assert serif.used_svg_fonts == {"FsvgT": "Times-Roman"}
        assert "/FsvgC" in _ops(mono)

    def test_tspan_flattening(self):
        stream = _render(_svg('<text x="0" y="10">A<tspan>B</tspan>C</text>'))
        assert "(ABC) Tj" in _ops(stream)


class TestOpacity:
    def test_fill_opacity_uses_extgstate(self):
        stream = _render(
            _svg('<rect width="10" height="10" fill="red" fill-opacity="0.5"/>', 10, 10)
        )
        lines = _lines(stream)
        assert "/GSsvg1 gs" in lines
        assert stream.used_svg_gstates == {"GSsvg1": {"ca": 0.5, "CA": 1.0}}
        assert "1.0000 0.0000 0.0000 rg" in lines

    def test_group_opacity_multiplies(self):
        stream = _render(
            _svg(
                '<g opacity="0.5"><rect width="10" height="10" fill="red"'
                ' fill-opacity="0.5"/></g>',
                10,
                10,
            )
        )
        assert stream.used_svg_gstates == {"GSsvg1": {"ca": 0.25, "CA": 0.5}}

    def test_gstates_deduplicate(self):
        stream = _render(
            _svg(
                '<rect width="4" height="4" fill="red" opacity="0.5"/>'
                '<rect x="5" width="4" height="4" fill="blue" opacity="0.5"/>',
                10,
                10,
            )
        )
        assert list(stream.used_svg_gstates) == ["GSsvg1"]


class TestCmykMode:
    def test_transformed_fill_uses_k(self):
        stream = _render(
            _svg(
                '<rect width="10" height="10" fill="red" transform="translate(1,1)"/>',
                20,
                20,
            ),
            mode="cmyk",
        )
        assert "0.0000 1.0000 1.0000 0.0000 k" in _lines(stream)

    def test_gradient_bands_use_k(self):
        stream = _render(TestGradients.LINEAR, mode="cmyk")
        k_lines = [ln for ln in _lines(stream) if ln.endswith(" k")]
        assert len(k_lines) >= 20

    def test_shading_dict_cmyk_stops(self):
        svg = parse_svg(TestGradients.LINEAR)
        sh = gradient_shading(svg, "lg", (0.0, 0.0, 100.0, 50.0), color_mode="cmyk")
        assert sh["ColorSpace"] == "DeviceCMYK"
        first = sh["Function"]["Functions"][0]
        assert first["C0"] == pytest.approx([0.0, 1.0, 1.0, 0.0])
        assert first["C1"] == pytest.approx([1.0, 0.0, 1.0, 0.0])


COMPLEX_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80">'
    '<defs><linearGradient id="lg"><stop offset="0" stop-color="red"/>'
    '<stop offset="1" stop-color="blue"/></linearGradient>'
    '<clipPath id="cp"><rect width="60" height="60"/></clipPath>'
    '<circle id="dot" r="4" fill="teal"/></defs>'
    '<rect width="50" height="30" fill="url(#lg)"/>'
    '<path d="M 60 10 A 10 10 0 0 1 80 10 Q 85 20 80 30 T 60 30 Z"'
    ' fill="orange" stroke="black"/>'
    '<g transform="translate(10,40) scale(1.5)" clip-path="url(#cp)">'
    '<rect width="20" height="20" fill="green" opacity="0.5"/></g>'
    '<use href="#dot" x="100" y="60"/>'
    '<text x="60" y="70" font-size="10" text-anchor="middle">Label</text>'
    "</svg>"
)


class TestDeterminism:
    def test_double_render_is_byte_identical(self):
        first = _render(COMPLEX_SVG)
        second = _render(COMPLEX_SVG)
        assert first.to_bytes() == second.to_bytes()

    def test_document_integration(self):
        doc = Document(title="SVG test")
        doc.svg(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50">'
            '<defs><linearGradient id="g"><stop offset="0" stop-color="red"/>'
            '<stop offset="1" stop-color="blue"/></linearGradient></defs>'
            '<rect width="100" height="20" fill="url(#g)"/>'
            '<path d="M 10 30 A 10 10 0 0 1 30 30 Z" fill="navy"/></svg>'
        )
        pdf = doc.render()
        assert len(pdf) > 0


REGRESSION_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" '
    'viewBox="0 0 200 100">'
    '<rect x="5" y="5" width="40" height="20" fill="#336699" stroke="black"/>'
    '<rect x="50" y="5" width="40" height="20" stroke="red"/>'
    '<circle cx="120" cy="20" r="15" fill="orange" stroke="#222222" stroke-width="2"/>'
    '<ellipse cx="160" cy="20" rx="20" ry="10" fill="none" stroke="navy"/>'
    '<line x1="0" y1="50" x2="200" y2="50" stroke="#00ff00" stroke-width="1.5"/>'
    '<g><polygon points="10,60 30,60 20,90" fill="purple"/></g>'
    '<polyline points="40,60 60,90 80,60" stroke="teal"/>'
    '<path d="M 100 60 L 120 60 H 140 V 80 C 140 90 120 95 110 90 l -5 -5 '
    'c -2 -2 -3 -4 -3 -6 Z" fill="#dddddd" stroke="black" stroke-width="0.8"/>'
    "</svg>"
)

REGRESSION_RGB = (
    "\n".join(
        [
            "q",
            "0.2 0.4 0.6 rg",
            "77 675 40 20 re",
            "f",
            "77 675 40 20 re",
            "S",
            "122 675 40 20 re",
            "S",
            "1.0000 0.6471 0.0000 rg",
            "0.1333 0.1333 0.1333 RG",
            "2.0000 w",
            "207.0000 680.0000 m",
            "207.0000 688.2843 200.2843 695.0000 192.0000 695.0000 c",
            "183.7157 695.0000 177.0000 688.2843 177.0000 680.0000 c",
            "177.0000 671.7157 183.7157 665.0000 192.0000 665.0000 c",
            "200.2843 665.0000 207.0000 671.7157 207.0000 680.0000 c",
            "B",
            "0.0000 0.0000 0.5020 RG",
            "1.0000 w",
            "252.0000 680.0000 m",
            "252.0000 685.5228 243.0457 690.0000 232.0000 690.0000 c",
            "220.9543 690.0000 212.0000 685.5228 212.0000 680.0000 c",
            "212.0000 674.4772 220.9543 670.0000 232.0000 670.0000 c",
            "243.0457 670.0000 252.0000 674.4772 252.0000 680.0000 c",
            "S",
            "0 1 0 RG",
            "1.5 w",
            "72 650 m",
            "272 650 l",
            "S",
            "0.5020 0.0000 0.5020 rg",
            "82.0000 640.0000 m",
            "102.0000 640.0000 l",
            "92.0000 610.0000 l",
            "h",
            "f",
            "0.0000 0.5020 0.5020 RG",
            "1.0000 w",
            "112.0000 640.0000 m",
            "132.0000 610.0000 l",
            "152.0000 640.0000 l",
            "S",
            "0.8667 0.8667 0.8667 rg",
            "0.0000 0.0000 0.0000 RG",
            "0.8000 w",
            "172.0000 640.0000 m",
            "192.0000 640.0000 l",
            "212.0000 640.0000 l",
            "212.0000 620.0000 l",
            "212.0000 610.0000 192.0000 605.0000 182.0000 610.0000 c",
            "177.0000 615.0000 l",
            "175.0000 617.0000 174.0000 619.0000 174.0000 621.0000 c",
            "h",
            "B",
            "Q",
        ]
    )
    + "\n"
).encode("ascii")

REGRESSION_CMYK = (
    "\n".join(
        [
            "q",
            "0.6667 0.3333 0 0.4 k",
            "77 675 40 20 re",
            "f",
            "77 675 40 20 re",
            "S",
            "122 675 40 20 re",
            "S",
            "0.0000 0.3529 1.0000 0.0000 k",
            "0.0000 0.0000 0.0000 0.8667 K",
            "2.0000 w",
            "207.0000 680.0000 m",
            "207.0000 688.2843 200.2843 695.0000 192.0000 695.0000 c",
            "183.7157 695.0000 177.0000 688.2843 177.0000 680.0000 c",
            "177.0000 671.7157 183.7157 665.0000 192.0000 665.0000 c",
            "200.2843 665.0000 207.0000 671.7157 207.0000 680.0000 c",
            "B",
            "1.0000 1.0000 0.0000 0.4980 K",
            "1.0000 w",
            "252.0000 680.0000 m",
            "252.0000 685.5228 243.0457 690.0000 232.0000 690.0000 c",
            "220.9543 690.0000 212.0000 685.5228 212.0000 680.0000 c",
            "212.0000 674.4772 220.9543 670.0000 232.0000 670.0000 c",
            "243.0457 670.0000 252.0000 674.4772 252.0000 680.0000 c",
            "S",
            "1 0 1 0 K",
            "1.5 w",
            "72 650 m",
            "272 650 l",
            "S",
            "0.0000 1.0000 0.0000 0.4980 k",
            "82.0000 640.0000 m",
            "102.0000 640.0000 l",
            "92.0000 610.0000 l",
            "h",
            "f",
            "1.0000 0.0000 0.0000 0.4980 K",
            "1.0000 w",
            "112.0000 640.0000 m",
            "132.0000 610.0000 l",
            "152.0000 640.0000 l",
            "S",
            "0.0000 0.0000 0.0000 0.1333 k",
            "0.0000 0.0000 0.0000 1.0000 K",
            "0.8000 w",
            "172.0000 640.0000 m",
            "192.0000 640.0000 l",
            "212.0000 640.0000 l",
            "212.0000 620.0000 l",
            "212.0000 610.0000 192.0000 605.0000 182.0000 610.0000 c",
            "177.0000 615.0000 l",
            "175.0000 617.0000 174.0000 619.0000 174.0000 621.0000 c",
            "h",
            "B",
            "Q",
        ]
    )
    + "\n"
).encode("ascii")


class TestOldSubsetRegression:
    def _capture(self, mode: str) -> bytes:
        svg = parse_svg(REGRESSION_SVG)
        stream = ContentStream(color_mode=mode)
        render_svg(stream, svg, 72.0, 700.0, 200.0, 100.0)
        return stream.to_bytes()

    def test_rgb_byte_identity(self):
        assert self._capture("rgb") == REGRESSION_RGB

    def test_cmyk_byte_identity(self):
        assert self._capture("cmyk") == REGRESSION_CMYK
