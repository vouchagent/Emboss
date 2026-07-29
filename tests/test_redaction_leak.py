"""A redacted value must not survive in any embedded artifact.

Construction-time redaction removes a block before the spec, text index,
layout map, Markdown twin, or manifest are built, so a redacted value must be
absent not only from the content stream but from every /AF attachment too.
These tests lock that in against future regressions (e.g. if embed_spec ever
started from the pre-redaction document).
"""

import io
import re
import zlib

import pytest

from emboss import Document
from emboss.redaction import RedactionRule

pikepdf = pytest.importorskip("pikepdf")

SECRET = b"EXPOSURE-4200000-SECRET"


def _all_embedded_and_stream_bytes(pdf: bytes) -> bytes:
    """Every byte a reader could recover: raw, decompressed streams, and /AF."""
    out = pdf
    for raw in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.DOTALL):
        try:
            out += zlib.decompress(raw)
        except Exception:
            pass
    with pikepdf.open(io.BytesIO(pdf)) as doc:
        for name in doc.attachments:
            out += doc.attachments[name].get_file().read_bytes()
    return out


def _doc_with_secret():
    doc = Document(title="Report")
    doc.paragraph("Public introduction.", id="p0")
    doc.paragraph(f"The secret exposure is {SECRET.decode()} dollars.", id="p1")
    doc.table(
        headers=["Item", "Value"],
        rows=[["Confidential", SECRET.decode()]],
        attach_data=True,
        id="t1",
    )
    return doc


class TestRemoveMode:
    def test_removed_block_absent_from_all_artifacts(self):
        red = _doc_with_secret().redact(
            [
                RedactionRule(name="p", node_id="p1", mode="remove"),
                RedactionRule(name="t", node_id="t1", mode="remove"),
            ]
        )
        pdf = red.render(embed_spec=True)
        assert SECRET not in _all_embedded_and_stream_bytes(pdf)

    def test_removed_with_manifest(self):
        red = _doc_with_secret().redact(
            [
                RedactionRule(name="p", node_id="p1", mode="remove"),
                RedactionRule(name="t", node_id="t1", mode="remove"),
            ]
        )
        pdf = red.render(embed_spec=True, manifest=True)
        assert SECRET not in _all_embedded_and_stream_bytes(pdf)

    def test_pattern_rule_removes_the_whole_block(self):
        red = _doc_with_secret().redact(
            [
                RedactionRule(name="pat", pattern=SECRET.decode(), mode="remove"),
            ]
        )
        pdf = red.render(embed_spec=True)
        assert SECRET not in _all_embedded_and_stream_bytes(pdf)


class TestPlaceholderMode:
    def test_placeholder_original_absent_from_all_artifacts(self):
        red = _doc_with_secret().redact(
            [
                RedactionRule(name="p", node_id="p1", mode="placeholder"),
                RedactionRule(name="t", node_id="t1", mode="placeholder"),
            ]
        )
        pdf = red.render(embed_spec=True)
        assert SECRET not in _all_embedded_and_stream_bytes(pdf)


class TestLogNotEmbedded:
    def test_redaction_log_is_not_attached(self):
        red = _doc_with_secret().redact(
            [
                RedactionRule(name="p", node_id="p1", mode="remove"),
                RedactionRule(name="t", node_id="t1", mode="remove"),
            ]
        )
        # The audit log exists on the returned document...
        assert red.redaction_log
        # ...but it is never written into the output's attachments.
        pdf = red.render(embed_spec=True)
        with pikepdf.open(io.BytesIO(pdf)) as doc:
            for name in doc.attachments:
                blob = doc.attachments[name].get_file().read_bytes()
                assert SECRET not in blob


class TestBlockGranularity:
    def test_unredacted_table_csv_still_carries_its_data(self):
        # Redaction is block-level: a value in a table you do NOT redact stays
        # in that table's embedded CSV. To remove it, redact the table too.
        doc = Document(title="R")
        doc.paragraph("Public.", id="p0")
        doc.paragraph(f"Secret {SECRET.decode()}.", id="p1")
        doc.table(
            headers=["Item", "Value"],
            rows=[["Confidential", SECRET.decode()]],
            attach_data=True,
            id="t1",
        )
        # Redact only the paragraph; the table remains.
        red = doc.redact([RedactionRule(name="p", node_id="p1", mode="remove")])
        pdf = red.render(embed_spec=True)
        # The kept table's own CSV still contains the value (expected).
        assert SECRET in _all_embedded_and_stream_bytes(pdf)

        # Redacting the table too removes it everywhere.
        red2 = doc.redact(
            [
                RedactionRule(name="p", node_id="p1", mode="remove"),
                RedactionRule(name="t", node_id="t1", mode="remove"),
            ]
        )
        assert SECRET not in _all_embedded_and_stream_bytes(
            red2.render(embed_spec=True)
        )
