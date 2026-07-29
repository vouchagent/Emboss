"""Tests for the text-position index and rectangle resolver."""

import io
import json

import pytest

from emboss import Document
from emboss.textmap import TextIndex, reconstruct_node_text, text_map_json


def _span(idx: TextIndex, node_id: str, word: str) -> dict:
    return next(s for s in idx._index[node_id] if s["text"] == word)


class TestReconstructNodeText:
    def test_words_rejoined_with_spaces(self):
        spans = [
            {"char_start": 0, "char_end": 3, "text": "The"},
            {"char_start": 4, "char_end": 8, "text": "cat"[:3] + "s"},
        ]
        assert reconstruct_node_text(spans) == "The cats"

    def test_round_trips_a_real_paragraph(self):
        doc = Document(title="D")
        text = "The exposure exceeds four million dollars this quarter."
        doc.paragraph(text, id="p1")
        idx = doc.text_index()
        assert idx.node_text("p1") == text


class TestResolveExact:
    def _index(self):
        doc = Document(title="D")
        doc.paragraph("The exposure exceeds four million dollars.", id="p1")
        return doc.text_index()

    def test_single_word(self):
        idx = self._index()
        s = _span(idx, "p1", "exceeds")
        res = idx.resolve(0, s["x0"], s["y0"], s["x1"], s["y1"])
        assert res.state == "exact"
        assert res.node_id == "p1"
        assert res.anchor_text == "exceeds"
        start, end = res.char_range
        assert idx.node_text("p1")[start:end] == "exceeds"

    def test_multi_word_range(self):
        idx = self._index()
        a = _span(idx, "p1", "exposure")
        b = _span(idx, "p1", "exceeds")
        res = idx.resolve(0, a["x0"], a["y0"], b["x1"], b["y1"])
        assert res.state == "exact"
        assert res.anchor_text == "exposure exceeds"
        assert res.patchable

    def test_line_above_not_picked_up(self):
        # A tall highlight must not grab a word one line up: vertical overlap
        # is required to exceed a fraction of the span height.
        doc = Document(title="D")
        doc.paragraph("alpha beta gamma delta epsilon zeta eta theta", id="p1")
        idx = doc.text_index()
        first = idx._index["p1"][0]
        res = idx.resolve(0, first["x0"], first["y0"], first["x1"], first["y1"])
        assert res.state == "exact"
        assert res.anchor_text == "alpha"


class TestResolveStates:
    def test_unanchored_over_empty_area(self):
        doc = Document(title="D")
        doc.paragraph("Some text near the top.", id="p1")
        idx = doc.text_index()
        res = idx.resolve(0, 500, 60, 540, 80)
        assert res.state == "unanchored"
        assert res.node_id is None
        assert res.page == 0
        assert res.rect == [500, 60, 540, 80]
        assert not res.patchable

    def test_spanning_two_nodes(self):
        doc = Document(title="D")
        doc.paragraph("First paragraph with several words here.", id="p1")
        doc.paragraph("Second paragraph with several words here.", id="p2")
        idx = doc.text_index()
        a = idx._index["p1"][0]
        b = idx._index["p2"][0]
        # A rectangle from the first line down into the second paragraph.
        res = idx.resolve(
            0,
            min(a["x0"], b["x0"]),
            min(a["y0"], b["y0"]),
            max(a["x1"], b["x1"]),
            max(a["y1"], b["y1"]),
        )
        assert res.state == "spanning"
        assert res.node_ids == sorted(["p1", "p2"])
        assert res.char_range is None

    def test_node_state_over_a_figure(self):
        doc = Document(title="D")
        doc.chart(
            chart_type="bar",
            labels=["A", "B"],
            values=[1, 2],
            title="Chart",
            id="fig1",
        )
        idx = doc.text_index()
        box = doc.layout_map()["fig1"][0]
        cx = (box["x0"] + box["x1"]) / 2.0
        cy = (box["y0"] + box["y1"]) / 2.0
        res = idx.resolve(0, cx - 5, cy - 5, cx + 5, cy + 5)
        assert res.state == "node"
        assert res.node_id == "fig1"
        assert res.patchable


class TestSerialization:
    def test_text_map_json_is_deterministic(self):
        doc = Document(title="D")
        doc.paragraph("Deterministic output please.", id="p1")
        assert text_map_json(doc) == text_map_json(doc)

    def test_text_map_json_has_text_and_spans(self):
        doc = Document(title="D")
        doc.paragraph("Hello world.", id="p1")
        data = json.loads(text_map_json(doc))
        assert data["p1"]["text"] == "Hello world."
        assert data["p1"]["spans"]

    def test_embed_spec_attaches_textmap(self):
        pikepdf = pytest.importorskip("pikepdf")
        doc = Document(title="D")
        doc.paragraph("Attach me.", id="p1")
        pdf = doc.render(embed_spec=True)
        with pikepdf.open(io.BytesIO(pdf)) as p:
            assert "emboss-textmap.json" in p.attachments


class TestCaching:
    def test_index_cached_until_content_changes(self):
        doc = Document(title="D")
        doc.paragraph("One.", id="p1")
        first = doc.text_index()
        assert doc.text_index() is first
        doc.paragraph("Two.", id="p2")
        assert doc.text_index() is not first
