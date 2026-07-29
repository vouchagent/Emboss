"""Regression tests for rendering polish fixes.

Covers three defects found while building the capabilities showcase:
a caption that already carries a label was double-prefixed, display
equations centered on a hardcoded width instead of the page, and long
stat-tile values were broken mid-word instead of shrinking to fit.
"""

import re
import zlib

from emboss import Document


def _content_streams(pdf: bytes) -> list:
    out = []
    for raw in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.DOTALL):
        try:
            out.append(zlib.decompress(raw).decode("latin1"))
        except Exception:
            continue
    return out


def _text_positions(data: str) -> list:
    xs, cur = [], None
    for tok in re.finditer(r"([-\d.]+)\s+([-\d.]+)\s+Td|\((.*?)\)\s*Tj", data):
        if tok.group(1):
            cur = float(tok.group(1))
        elif tok.group(3) is not None and cur is not None:
            xs.append((cur, tok.group(3)))
    return xs


class TestCaptionLabelGuard:
    def test_caption_with_existing_label_not_doubled(self):
        doc = Document(title="Cap")
        doc.table(
            headers=["A", "B"],
            rows=[["1", "2"]],
            caption="Table 1: already labeled by the author",
        )
        text = "".join(_content_streams(doc.render()))
        assert "Table 1: already labeled" in text.replace(" ", " ")
        assert "Table 1: Table 1:" not in text

    def test_caption_without_label_is_auto_numbered(self):
        doc = Document(title="Cap")
        doc.table(headers=["A"], rows=[["1"]], caption="Plain caption text")
        joined = " ".join(
            t for s in _content_streams(doc.render()) for _, t in _text_positions(s)
        )
        assert "Table" in joined  # the auto number prefix was added


class TestMathCentering:
    def test_display_equation_centers_on_page(self):
        doc = Document(title="Eq")
        doc.math(r"E = mc^2", display=True)
        for data in _content_streams(doc.render()):
            glyphs = [
                x for x, t in _text_positions(data) if t in ("E", "m", "c", "2", "=")
            ]
            if len(glyphs) >= 3:
                span_center = (min(glyphs) + max(glyphs)) / 2
                # Letter page content center is 306; allow a small tolerance.
                assert abs(span_center - 306.0) < 25.0
                return
        raise AssertionError("equation glyphs not found")


class TestCodeBackgroundFit:
    def _rect_widths(self, pdf: bytes) -> list:
        import io

        import pytest

        pikepdf = pytest.importorskip("pikepdf")
        widths = []
        with pikepdf.open(io.BytesIO(pdf)) as doc:
            for page in doc.pages:
                data = pikepdf.parse_content_stream(page)
                for operands, op in data:
                    if str(op) == "re":
                        widths.append(round(float(operands[2]), 1))
        return widths

    def test_narrow_code_background_hugs_content(self):
        doc = Document(title="Code")
        doc.code_block("x = 1", language="python")
        widths = self._rect_widths(doc.render())
        # The dark code background must not span the full ~468pt page width
        # for a five-character line; it hugs the code plus padding.
        assert widths and max(widths) < 200.0

    def test_wide_code_background_spans_page(self):
        doc = Document(title="Code")
        doc.code_block(
            "result = compute(alpha, beta, gamma, delta, epsilon, zeta, eta)",
            language="python",
        )
        widths = self._rect_widths(doc.render())
        # A near-full-width line fills the box out toward the page width.
        assert widths and max(widths) > 300.0

    def test_code_background_deterministic(self):
        doc = Document(title="Code")
        doc.code_block("def f():\n    return 1", language="python")
        assert doc.render() == doc.render()


class TestStatTileFit:
    def test_long_value_is_not_broken_midword(self):
        doc = Document(title="Stat")
        doc.stat_tiles(
            [
                {"label": "Layout", "value": "Automatic"},
                {"label": "Input", "value": "Deterministic"},
                {"label": "Output", "value": "Accessible"},
                {"label": "Made", "value": "Reproducible"},
            ]
        )
        # Each value must render as a single show-text token. A mid-word
        # split would emit the word as two separate tokens, so checking
        # for the whole token (not a reconstruction) detects the break.
        tokens = [
            t
            for s in _content_streams(doc.render())
            for t in re.findall(r"\((.*?)\)\s*Tj", s)
        ]
        for word in ("Automatic", "Deterministic", "Accessible", "Reproducible"):
            assert word in tokens, f"{word} was broken mid-word"

    def test_short_values_still_render(self):
        doc = Document(title="Stat")
        doc.stat_tiles([{"label": "Revenue", "value": "$24.1M", "delta": "+12%"}])
        assert doc.render().startswith(b"%PDF")

    def test_stat_tiles_deterministic(self):
        doc = Document(title="Stat")
        doc.stat_tiles([{"label": "Long Label Here", "value": "Reproducible"}])
        assert doc.render() == doc.render()
