"""Tests for synthetic small-caps rendering: sizes, ActualText, width parity."""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document  # noqa: E402
from emboss.spec import Paragraph, TextRun  # noqa: E402
from emboss.typography.font_metrics import (  # noqa: E402
    FontMetrics,
    SMALL_CAPS_RATIO,
    small_caps_segments,
)

pikepdf = pytest.importorskip("pikepdf")

_LITERAL = re.compile(rb"\(((?:[^()\\]|\\.)*)\)")
_ACTUAL = re.compile(rb"/ActualText <([0-9A-Fa-f]+)>")


def _page_stream(data: bytes) -> bytes:
    with pikepdf.open(io.BytesIO(data)) as pdf:
        return bytes(pdf.pages[0].Contents.read_bytes())


def _tf_sizes(stream: bytes) -> list:
    return [float(x) for x in re.findall(rb"/F\d+ ([\d.]+) Tf", stream)]


def _text(stream: bytes) -> bytes:
    return b"".join(m.group(1) for m in _LITERAL.finditer(stream))


def test_small_caps_segments_uppercase_and_size():
    segs = small_caps_segments("Hi!", 10.0)
    # 'H' at full size, 'i' -> 'I' at reduced size, '!' at full size.
    assert segs[0] == ("H", 10.0)
    assert segs[1] == ("I", 10.0 * SMALL_CAPS_RATIO)
    assert segs[2] == ("!", 10.0)


def test_two_tf_sizes_emitted():
    doc = Document(title="SC", style="corporate")
    doc.add(Paragraph([TextRun("Hello World", small_caps=True)]))
    stream = _page_stream(doc.render())
    sizes = set(_tf_sizes(stream))
    base = 10.5
    assert base in sizes
    assert round(base * SMALL_CAPS_RATIO, 3) in {round(s, 3) for s in sizes}


def test_rendered_glyphs_are_uppercased():
    doc = Document(title="SC", style="corporate")
    doc.add(Paragraph([TextRun("hello", small_caps=True)]))
    text = _text(_page_stream(doc.render())).replace(b" ", b"")
    assert b"HELLO" in text
    assert b"hello" not in text


def test_actual_text_preserves_casing():
    doc = Document(title="SC", style="corporate")
    doc.add(Paragraph([TextRun("Hello", small_caps=True)]))
    stream = _page_stream(doc.render())
    recovered = ""
    for hexblob in _ACTUAL.findall(stream):
        # Strip the leading FEFF BOM and decode UTF-16BE.
        decoded = bytes.fromhex(hexblob.decode()).decode("utf-16-be")
        recovered += decoded
    assert "ello" in recovered  # original lowercase survived for extraction


def test_measure_render_width_parity():
    metrics = FontMetrics.base14("Helvetica")
    text, size = "Hello World", 12.0
    rendered = sum(
        metrics.text_width(seg_text, seg_size, kerning=False)
        for seg_text, seg_size in small_caps_segments(text, size)
    )
    measured = metrics.small_caps_width(text, size)
    assert rendered == pytest.approx(measured, abs=1e-9)


def test_small_caps_determinism():
    doc = Document(title="SC", style="corporate")
    doc.add(Paragraph([TextRun("Small Caps Heading", small_caps=True)]))
    assert doc.render() == doc.render()


def test_plain_run_unaffected():
    doc = Document(title="Plain", style="corporate")
    doc.add(Paragraph([TextRun("no small caps here")]))
    stream = _page_stream(doc.render())
    assert b"ActualText" not in stream
    # The synthetic small-caps size (0.8x body) is never emitted.
    assert round(10.5 * SMALL_CAPS_RATIO, 3) not in {
        round(s, 3) for s in _tf_sizes(stream)
    }
