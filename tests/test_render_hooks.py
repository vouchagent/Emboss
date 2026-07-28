"""Tests for render-side hooks: blockquote, strikethrough, tasks, lists, XMP."""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pikepdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document  # noqa: E402
from emboss.spec import BlockQuote, Paragraph, TextRun  # noqa: E402


def _content(pdf_bytes: bytes, page: int = 0) -> bytes:
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        return bytes(pdf.pages[page].Contents.read_bytes())


_TD_RE = re.compile(rb"([\d.-]+) ([\d.-]+) Td")
_STRING_RE = re.compile(rb"\(((?:\\.|[^\\()])*)\)")


def _text_ops(content: bytes) -> list:
    """Extract (x, y, joined strings) per BT..ET block in stream order."""
    ops = []
    for block in re.findall(rb"BT(.*?)ET", content, re.DOTALL):
        td = _TD_RE.search(block)
        strings = _STRING_RE.findall(block)
        if td and strings:
            ops.append((float(td.group(1)), float(td.group(2)), b"".join(strings)))
    return ops


class TestBlockQuoteRendering:
    def test_accent_bar_italic_and_attribution(self):
        doc = Document(
            title="Q",
            content=[BlockQuote(content="Wise words endure.", attribution="A. Author")],
        )
        pdf = doc.render()
        content = _content(pdf)

        bars = re.findall(rb"[\d.-]+ [\d.-]+ 2 [\d.-]+ re\nf", content)
        assert len(bars) == 1
        assert b"Helvetica-Oblique" in pdf
        assert b"/BlockQuote <</MCID" in content
        assert b"/BlockQuote" in pdf

        ops = _text_ops(content)
        body = [op for op in ops if b"Wise" in op[2]]
        attribution = [op for op in ops if b"Author" in op[2]]
        assert body and attribution
        assert attribution[0][0] > body[0][0]

    def test_markdown_quote_end_to_end(self):
        doc = Document.from_markdown("> quoted wisdom\n\nAfter.", title="Quote")
        assert any(isinstance(e, BlockQuote) for e in doc.content)
        content = _content(doc.render())
        assert b"/BlockQuote <</MCID" in content
        assert any(b"quoted" in op[2] for op in _text_ops(content))


class TestStrikethrough:
    def test_line_inside_mcid_at_expected_y(self):
        doc = Document(
            title="Strike",
            content=[
                Paragraph(
                    [
                        TextRun("keep "),
                        TextRun("gone", strikethrough=True),
                        TextRun(" end"),
                    ]
                )
            ],
        )
        content = _content(doc.render())
        start = content.index(b"/P <</MCID")
        end = content.index(b"EMC", start)
        region = content[start:end]
        assert b"/Artifact" not in region

        size = float(re.search(rb"/F\d+ ([\d.]+) Tf", region).group(1))
        baseline = float(_TD_RE.search(region).group(2))
        stroke = re.search(rb"([\d.-]+) ([\d.-]+) m\n([\d.-]+) ([\d.-]+) l\nS", region)
        assert stroke is not None
        y = float(stroke.group(2))
        assert abs(y - (baseline + 0.28 * size)) < 0.05
        assert float(stroke.group(4)) == y

        thickness = float(re.search(rb"([\d.]+) w\n", region).group(1))
        assert abs(thickness - max(0.06 * size, 0.4)) < 0.01


class TestTaskListCheckboxes:
    def test_square_tick_and_stripped_text(self):
        doc = Document.from_markdown("- [ ] todo\n- [x] done", title="Tasks")
        content = _content(doc.render())

        squares = re.findall(rb"[\d.-]+ [\d.-]+ 7 7 re\nS", content)
        assert len(squares) == 2
        ticks = re.findall(
            rb"[\d.-]+ [\d.-]+ m\n[\d.-]+ [\d.-]+ l\n[\d.-]+ [\d.-]+ l\nS", content
        )
        assert len(ticks) == 1

        strings = _STRING_RE.findall(content)
        joined = b" ".join(strings)
        assert b"todo" in joined and b"done" in joined
        assert not any(b"[" in s or b"]" in s for s in strings)

    def test_checkbox_geometry_deterministic(self):
        md = "- [x] done"
        first = _content(Document.from_markdown(md, title="T").render())
        second = _content(Document.from_markdown(md, title="T").render())
        assert first == second


class TestNestedListOffsets:
    def test_nested_labels_step_14pt(self):
        doc = Document.from_markdown("- top\n  - mid\n    - deep", title="Nest")
        content = _content(doc.render())
        ops = _text_ops(content)
        x_by_text = {op[2]: op[0] for op in ops}
        x_top = x_by_text[b"\\225"]  # bullet at depth 0
        x_mid = x_by_text[b"-"]  # depth 1
        x_deep = x_by_text[b"\\267"]  # depth 2
        assert abs((x_mid - x_top) - 14.0) < 0.01
        assert abs((x_deep - x_mid) - 14.0) < 0.01


class TestXmpMetadata:
    def test_tagged_non_pdfa_has_pdfua_xmp(self):
        doc = Document(title="Tagged", content=[Paragraph("hello")])
        assert doc.tagged and not doc.pdfa
        pdf = doc.render()
        assert b"/Metadata" in pdf
        assert b"<pdfuaid:part>1</pdfuaid:part>" in pdf
        assert b"pdfaid" not in pdf

    def test_pdfa_doc_has_both_identifiers(self):
        doc = Document(title="Archive", pdfa=True, content=[Paragraph("hello")])
        pdf = doc.render()
        assert b"<pdfaid:part>2</pdfaid:part>" in pdf
        assert b"<pdfaid:conformance>B</pdfaid:conformance>" in pdf
        assert b"<pdfuaid:part>1</pdfuaid:part>" in pdf


class TestDeterminism:
    def test_double_render_identical(self):
        md = (
            "> A quote worth repeating\n\n"
            "- [x] done\n- [ ] todo\n\n"
            "- top\n  - mid\n    - deep\n\n"
            "Text with ~~struck words~~ inside.\n"
        )
        first = Document.from_markdown(md, title="Det").render()
        second = Document.from_markdown(md, title="Det").render()
        assert first == second
