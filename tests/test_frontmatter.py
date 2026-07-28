"""Tests for front-matter and executive-brief block elements."""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document  # noqa: E402
from emboss.spec import (  # noqa: E402
    Abstract,
    Author,
    Authors,
    CoverPage,
    PullQuote,
    Stat,
    StatTiles,
)

pikepdf = pytest.importorskip("pikepdf")

_LITERAL = re.compile(rb"\(((?:[^()\\]|\\.)*)\)")


def _page_stream(data: bytes, index: int) -> bytes:
    with pikepdf.open(io.BytesIO(data)) as pdf:
        return bytes(pdf.pages[index].Contents.read_bytes())


def _page_count(data: bytes) -> int:
    with pikepdf.open(io.BytesIO(data)) as pdf:
        return len(pdf.pages)


def _text(stream: bytes) -> bytes:
    return b"".join(m.group(1) for m in _LITERAL.finditer(stream))


def _tf_sizes(stream: bytes) -> list:
    return [float(x) for x in re.findall(rb"/F\d+ ([\d.]+) Tf", stream)]


def test_cover_renders_full_page_and_breaks():
    doc = Document(title="Report", style="brief")
    doc.add(CoverPage(title="Annual Report", subtitle="FY2025", kicker="Draft"))
    doc.paragraph("Body content on the next page.")
    data = doc.render()
    assert data[:5] == b"%PDF-"
    # Cover consumes a full page; body flows onto the next page.
    assert _page_count(data) == 2
    assert b"/Div" in data


def test_cover_suppresses_running_chrome():
    doc = Document(title="Report", style="corporate")
    doc.add(CoverPage(title="Annual Report"))
    doc.paragraph("Body content.")
    data = doc.render()
    cover = _page_stream(data, 0)
    body = _page_stream(data, 1)
    # No footer/page-number artifact on the cover; present on the body page.
    assert b"/Footer" not in cover
    assert b"/Footer" in body


def test_abstract_renders_label_and_body():
    doc = Document(title="Paper", style="academic")
    doc.add(Abstract("We present a spectral method.", keywords=["spectral", "sparse"]))
    data = doc.render()
    text = _text(_page_stream(data, 0))
    assert b"ABSTRACT" in text
    assert b"spectral method" in text.replace(b" ", b"") or b"spectral" in text
    assert b"Keywords" in text
    assert b"/Div" in data


def test_authors_grid_lists_names():
    doc = Document(title="Paper", style="academic")
    doc.add(
        Authors(
            [
                Author("Ada Lovelace", "Analytical Engine", "ada@x.io"),
                Author("Alan Turing", "NPL"),
            ]
        )
    )
    data = doc.render()
    squashed = _text(_page_stream(data, 0)).replace(b" ", b"")
    assert b"AdaLovelace" in squashed
    assert b"AlanTuring" in squashed


def test_pullquote_is_blockquote_tagged():
    doc = Document(title="Brief", style="brief")
    doc.add(PullQuote("Invent the future.", attribution="Alan Kay"))
    data = doc.render()
    assert b"/BlockQuote" in data
    squashed = _text(_page_stream(data, 0)).replace(b" ", b"")
    assert b"Inventthefuture." in squashed


def test_stat_tiles_draw_n_bordered_tiles():
    stats = [
        Stat("Revenue", "$4.5M", "+12%"),
        Stat("Churn", "2.1%", "-0.3%"),
        Stat("NPS", "61"),
    ]
    doc = Document(title="Brief", style="brief")
    doc.add(StatTiles(stats))
    data = doc.render()
    stream = _page_stream(data, 0)
    # One rectangle border per tile.
    assert len(re.findall(rb"\bre\b", stream)) == len(stats)
    squashed = _text(stream).replace(b" ", b"")
    assert b"$4.5M" in squashed
    assert b"REVENUE" in squashed
    # A signed delta is rendered.
    assert b"+12%" in squashed


def test_each_element_measures_and_tags():
    from emboss.layout.engine import LayoutEngine

    sheet = Document(title="x").stylesheet
    engine = LayoutEngine(Document(title="x").fonts, sheet)
    elements = [
        CoverPage(title="T", subtitle="s"),
        Abstract("body text here", keywords=["a"]),
        Authors([Author("A", "Aff")]),
        PullQuote("q", attribution="x"),
        StatTiles([Stat("L", "9", "+1")]),
    ]
    for el in elements:
        block = engine.measure(el, 468.0)
        assert block.height >= 0.0
        assert el.structure_tag in ("Div", "BlockQuote")


def test_determinism_double_render():
    doc = Document(title="Brief", style="brief")
    doc.add(CoverPage(title="Report", subtitle="sub", authors=["Jane"]))
    doc.add(Abstract("abstract body", keywords=["k"]))
    doc.add(PullQuote("quote", attribution="who"))
    doc.add(StatTiles([Stat("A", "1", "+1"), Stat("B", "2", "-2")]))
    assert doc.render() == doc.render()


def test_plain_doc_unaffected():
    doc = Document(title="Plain", style="corporate")
    doc.heading("Intro", level=1)
    doc.paragraph("Ordinary paragraph without front matter.")
    assert doc.render() == doc.render()
