"""Compliance tests: PDF/UA XMP id, ICC profile structure, CMYK appearances."""

from emboss.pdf.streams import ContentStream
from emboss.pdfa import (
    _build_minimal_cmyk_icc,
    _build_minimal_srgb_icc,
    build_xmp_metadata,
)
from emboss.redaction import RedactionMark, apply_redactions
from emboss.signing import SignatureField, build_signature_appearance
from emboss.spec import Document


def _xmp(**overrides) -> str:
    kwargs = dict(
        title="Test",
        author="Author",
        subject="Subject",
        keywords="key1, key2",
        creator="Emboss",
        producer="Emboss",
        language="en-US",
    )
    kwargs.update(overrides)
    return build_xmp_metadata(**kwargs).decode("utf-8")


def _parse_icc(profile: bytes) -> tuple[int, dict[bytes, tuple[int, int]]]:
    size = int.from_bytes(profile[0:4], "big")
    tag_count = int.from_bytes(profile[128:132], "big")
    tags = {}
    for i in range(tag_count):
        entry = 132 + i * 12
        sig = profile[entry : entry + 4]
        offset = int.from_bytes(profile[entry + 4 : entry + 8], "big")
        length = int.from_bytes(profile[entry + 8 : entry + 12], "big")
        tags[sig] = (offset, length)
    return size, tags


class TestXmpIdentifiers:
    def test_pdfa_packet_has_both_identifiers(self):
        text = _xmp()
        assert "<pdfaid:part>2</pdfaid:part>" in text
        assert "<pdfaid:conformance>B</pdfaid:conformance>" in text
        assert "<pdfuaid:part>1</pdfuaid:part>" in text
        assert 'xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/"' in text
        assert 'xmlns:pdfuaid="http://www.aiim.org/pdfua/ns/id/"' in text

    def test_non_pdfa_packet_keeps_pdfua_only(self):
        text = _xmp(pdfa=False)
        assert "pdfaid" not in text
        assert "<pdfuaid:part>1</pdfuaid:part>" in text

    def test_untagged_packet_omits_pdfua(self):
        text = _xmp(tagged=False)
        assert "pdfuaid" not in text
        assert "<pdfaid:part>2</pdfaid:part>" in text

    def test_tagged_pdfa_document_declares_pdfua(self):
        doc = Document(title="Compliance", pdfa=True)
        doc.paragraph("Tagged PDF/A body text.")
        pdf = doc.render()
        assert b"<pdfaid:part>2</pdfaid:part>" in pdf
        assert b"<pdfaid:conformance>B</pdfaid:conformance>" in pdf
        assert b"<pdfuaid:part>1</pdfuaid:part>" in pdf

    def test_xmp_deterministic(self):
        assert _xmp() == _xmp()


class TestSrgbIccProfile:
    def test_header_structure(self):
        profile = _build_minimal_srgb_icc()
        size, _ = _parse_icc(profile)
        assert size == len(profile)
        assert profile[36:40] == b"acsp"
        assert profile[12:16] == b"mntr"
        assert profile[16:20] == b"RGB "
        assert profile[20:24] == b"XYZ "
        assert profile[100:128] == b"\x00" * 28  # reserved header bytes

    def test_required_tags_present_and_in_bounds(self):
        profile = _build_minimal_srgb_icc()
        size, tags = _parse_icc(profile)
        required = [b"desc", b"wtpt", b"cprt", b"rXYZ", b"gXYZ", b"bXYZ"]
        required += [b"rTRC", b"gTRC", b"bTRC"]
        for sig in required:
            assert sig in tags, f"missing tag {sig!r}"
            offset, length = tags[sig]
            assert offset + length <= size

    def test_trc_uses_v2_curv_type(self):
        profile = _build_minimal_srgb_icc()
        _, tags = _parse_icc(profile)
        offset, _ = tags[b"rTRC"]
        assert profile[offset : offset + 4] == b"curv"
        assert b"para" not in profile

    def test_deterministic(self):
        assert _build_minimal_srgb_icc() == _build_minimal_srgb_icc()


class TestCmykIccProfile:
    def test_header_structure(self):
        profile = _build_minimal_cmyk_icc()
        size, _ = _parse_icc(profile)
        assert size == len(profile)
        assert profile[36:40] == b"acsp"
        assert profile[12:16] == b"prtr"
        assert profile[16:20] == b"CMYK"
        assert profile[20:24] == b"XYZ "
        assert profile[100:128] == b"\x00" * 28

    def test_required_tags_present_and_in_bounds(self):
        profile = _build_minimal_cmyk_icc()
        size, tags = _parse_icc(profile)
        required = [b"desc", b"wtpt", b"cprt", b"gamt"]
        required += [b"A2B0", b"A2B1", b"A2B2", b"B2A0", b"B2A1", b"B2A2"]
        for sig in required:
            assert sig in tags, f"missing tag {sig!r}"
            offset, length = tags[sig]
            assert offset + length <= size

    def test_intent_luts_share_data(self):
        profile = _build_minimal_cmyk_icc()
        _, tags = _parse_icc(profile)
        assert tags[b"A2B0"] == tags[b"A2B1"] == tags[b"A2B2"]
        assert tags[b"B2A0"] == tags[b"B2A1"] == tags[b"B2A2"]
        offset, _ = tags[b"A2B0"]
        assert profile[offset : offset + 4] == b"mft1"

    def test_deterministic(self):
        assert _build_minimal_cmyk_icc() == _build_minimal_cmyk_icc()


class TestRedactionColorMode:
    def _marks(self):
        return [
            RedactionMark(
                page_index=0,
                x=72,
                y=700,
                width=120,
                height=16,
                replacement_text="[REDACTED]",
            )
        ]

    def test_cmyk_mode_emits_k_not_rg(self):
        stream = ContentStream()
        apply_redactions(stream, self._marks(), 0, "F1", 10, color_mode="cmyk")
        output = stream.to_bytes()
        assert b" k" in output
        assert b" rg" not in output
        assert stream.color_mode == "rgb"  # caller's stream mode restored

    def test_cmyk_stream_mode_inferred(self):
        stream = ContentStream(color_mode="cmyk")
        apply_redactions(stream, self._marks(), 0, "F1", 10)
        output = stream.to_bytes()
        assert b" k" in output
        assert b" rg" not in output

    def test_default_rgb_unchanged(self):
        stream = ContentStream()
        apply_redactions(stream, self._marks(), 0, "F1", 10)
        output = stream.to_bytes()
        assert b" rg" in output
        assert b" k" not in output


class TestSignatureColorMode:
    def _sig(self):
        return SignatureField(
            page_index=0,
            x=100,
            y=100,
            signer_name="Test Signer",
            reason="Testing",
            location="Remote",
        )

    def test_cmyk_mode_emits_k_not_rg(self):
        stream = ContentStream()
        build_signature_appearance(stream, self._sig(), "F1", 10, color_mode="cmyk")
        output = stream.to_bytes()
        assert b" k" in output
        assert b" K" in output  # border stroke
        assert b" rg" not in output
        assert b" RG" not in output
        assert stream.color_mode == "rgb"

    def test_cmyk_stream_mode_inferred(self):
        stream = ContentStream(color_mode="cmyk")
        build_signature_appearance(stream, self._sig(), "F1", 10)
        output = stream.to_bytes()
        assert b" k" in output
        assert b" rg" not in output

    def test_default_rgb_unchanged(self):
        stream = ContentStream()
        build_signature_appearance(stream, self._sig(), "F1", 10)
        output = stream.to_bytes()
        assert b"0.4 0.4 0.4 rg" in output
        assert b" k" not in output
