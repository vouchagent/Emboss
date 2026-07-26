"""Test suite for Emboss.

The tests that matter most for this library are the guarantee tests:
determinism, xref correctness, structure-tree integrity, and text
extraction round-trips. Those are the claims the library makes, so they
are gated rather than spot-checked.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import (  # noqa: E402
    Document, Heading, LegalFeatures, PageSpec, Paragraph, Style, Table,
    TableCell, TextRun, ValidationError,
)
from emboss.constraints import ConstraintValidator  # noqa: E402
from emboss.pdf.objects import PdfName, PdfString, fmt_number  # noqa: E402
from emboss.pdf.verify import verify_pdf  # noqa: E402
from emboss.typography.font_metrics import FontMetrics, FontRegistry  # noqa: E402
from emboss.typography.hyphenation import Hyphenator  # noqa: E402
from emboss.typography.line_breaking import (  # noqa: E402
    Box, Glue, LineBreaker, Penalty, build_items,
)


def _page_content(document: Document, page: int = 0) -> bytes:
    """Return one page's decompressed content stream.

    Content streams are Flate-compressed, so searching the raw file bytes
    for operators gives false negatives.
    """
    import io

    import pikepdf

    with pikepdf.open(io.BytesIO(document.render())) as pdf:
        return bytes(pdf.pages[page].Contents.read_bytes())


def simple_document(**kw) -> Document:
    doc = Document(title="Test Document", **kw)
    doc.heading("Section One", level=1)
    doc.paragraph("The quick brown fox jumps over the lazy dog. " * 6)
    return doc


# --------------------------------------------------------------------------
# Determinism -- the core guarantee
# --------------------------------------------------------------------------

class TestDeterminism:
    def test_identical_input_yields_identical_bytes(self):
        first = simple_document().render()
        second = simple_document().render()
        assert first == second

    def test_no_timestamp_in_output(self):
        data = simple_document().render()
        assert b"/CreationDate" not in data
        assert b"/ModDate" not in data

    def test_document_id_is_content_derived(self):
        """Same content -> same /ID; different content -> different /ID."""
        one = simple_document().render()
        two = simple_document().render()
        assert _extract_id(one) == _extract_id(two)

        other = simple_document()
        other.paragraph("An additional paragraph changes the content.")
        assert _extract_id(other.render()) != _extract_id(one)

    def test_complex_document_is_deterministic(self):
        def build():
            doc = Document(title="Complex", style="legal",
                           legal=LegalFeatures(watermark="DRAFT",
                                               bates_prefix="X-"))
            doc.heading("Heading", level=1)
            doc.paragraph("Body text that is long enough to wrap. " * 10)
            doc.table(headers=["A", "B"],
                      rows=[[f"r{i}", f"v{i}"] for i in range(30)])
            doc.bullets(["one", "two", "three"])
            return doc.render()

        assert build() == build()


def _extract_id(data: bytes) -> bytes:
    match = re.search(rb"/ID\s*\[\s*<([0-9A-Fa-f]+)>", data)
    assert match, "no /ID found in trailer"
    return match.group(1)


# --------------------------------------------------------------------------
# PDF structural integrity
# --------------------------------------------------------------------------

class TestPdfStructure:
    def test_output_is_structurally_valid(self):
        report = verify_pdf(simple_document().render())
        assert report.ok, report.problems

    def test_xref_offsets_point_at_their_objects(self):
        """The xref table must agree with the actual byte layout."""
        data = simple_document().render()
        report = verify_pdf(data)
        assert not [p for p in report.problems if "xref" in p]

    def test_header_and_trailer(self):
        data = simple_document().render()
        assert data.startswith(b"%PDF-1.7")
        assert data.rstrip().endswith(b"%%EOF")

    def test_opens_in_third_party_parser(self):
        pikepdf = pytest.importorskip("pikepdf")
        import io

        data = simple_document().render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            assert len(pdf.pages) >= 1

    def test_page_count_matches_declaration(self):
        doc = Document(title="Long")
        for _ in range(40):
            doc.paragraph("Filler paragraph text that occupies vertical space. " * 4)
        result = doc.render()
        report = verify_pdf(result)
        assert report.page_count > 1
        assert report.ok


# --------------------------------------------------------------------------
# Accessibility / tagging
# --------------------------------------------------------------------------

class TestAccessibility:
    def test_structure_tree_is_present(self):
        data = simple_document().render()
        assert b"/StructTreeRoot" in data
        assert b"/MarkInfo" in data
        assert b"/ParentTree" in data

    def test_language_and_title_are_set(self):
        data = simple_document().render()
        assert b"/Lang" in data
        assert b"/DisplayDocTitle" in data

    def test_headings_produce_heading_tags(self):
        doc = Document(title="T")
        doc.heading("Level One", level=1)
        doc.heading("Level Two", level=2)
        doc.paragraph("Body")
        data = doc.render()
        assert b"/H1" in data
        assert b"/H2" in data
        assert b"/P" in data

    def test_table_header_cells_declare_scope(self):
        doc = Document(title="T")
        doc.table(headers=["Col A", "Col B"], rows=[["1", "2"]])
        data = doc.render()
        assert b"/TH" in data
        assert b"/Scope" in data
        assert b"/Column" in data

    def test_decorative_content_is_artifacted(self):
        """Headers, footers and page numbers must not be read as content."""
        content = _page_content(
            Document(title="T", footer_text="Footer", page_numbers=True)
            .paragraph("Body")
        )
        assert b"/Artifact" in content

    def test_missing_title_is_rejected_when_tagged(self):
        doc = Document(title="", tagged=True)
        doc.paragraph("Body")
        with pytest.raises(ValidationError, match="title"):
            doc.render()

    def test_untagged_document_needs_no_title(self):
        doc = Document(title="", tagged=False)
        doc.paragraph("Body")
        assert doc.render().startswith(b"%PDF")


# --------------------------------------------------------------------------
# Text extraction round-trip
# --------------------------------------------------------------------------

class TestTextExtraction:
    def test_text_survives_round_trip(self):
        pytest.importorskip("pikepdf")
        import shutil
        import subprocess
        import tempfile

        if not shutil.which("pdftotext"):
            pytest.skip("pdftotext not available")

        marker = "Distinctive phrase for extraction testing"
        doc = Document(title="Extraction")
        doc.paragraph(marker)
        with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
            handle.write(doc.render())
            handle.flush()
            output = subprocess.run(
                ["pdftotext", handle.name, "-"],
                capture_output=True, text=True, check=True,
            ).stdout
        assert "Distinctive phrase" in output


# --------------------------------------------------------------------------
# Typography
# --------------------------------------------------------------------------

class TestFontMetrics:
    def test_base14_widths_are_known_values(self):
        metrics = FontMetrics.base14("Helvetica")
        # 'A' is 667/1000 em in Helvetica.
        assert metrics.width_of(ord("A")) == pytest.approx(667.0)
        assert metrics.text_width("A", 12.0) == pytest.approx(8.004, abs=1e-3)

    def test_text_width_scales_with_size(self):
        metrics = FontMetrics.base14("Helvetica")
        at_ten = metrics.text_width("Hello", 10.0)
        at_twenty = metrics.text_width("Hello", 20.0)
        assert at_twenty == pytest.approx(at_ten * 2)

    def test_courier_is_monospaced(self):
        metrics = FontMetrics.base14("Courier")
        assert metrics.text_width("iii", 10.0) == pytest.approx(
            metrics.text_width("WWW", 10.0)
        )

    def test_registry_resolves_styles(self):
        registry = FontRegistry()
        assert registry.resolve("Helvetica", bold=True).name == "Helvetica-Bold"
        assert registry.resolve("Times", italic=True).name == "Times-Italic"

    def test_unknown_family_falls_back(self):
        registry = FontRegistry()
        assert registry.resolve("NoSuchFont").name == "Helvetica"

    def test_line_height_uses_real_metrics(self):
        metrics = FontMetrics.base14("Helvetica")
        # (718 + 207) / 1000 * 10 * 1.2
        assert metrics.line_height(10.0, 1.2) == pytest.approx(11.1, abs=0.01)


class TestHyphenation:
    def test_finds_break_points(self):
        hyphenator = Hyphenator()
        points = hyphenator.break_points("hyphenation")
        assert points, "expected at least one break point"
        assert all(0 < p < len("hyphenation") for p in points)

    def test_respects_minimum_prefix_and_suffix(self):
        hyphenator = Hyphenator(min_prefix=3, min_suffix=4)
        for word in ["indemnification", "representation", "consideration"]:
            for point in hyphenator.break_points(word):
                assert point >= 3
                assert len(word) - point >= 4

    def test_short_words_are_never_broken(self):
        hyphenator = Hyphenator()
        for word in ["the", "and", "cat", "four"]:
            assert hyphenator.break_points(word) == []

    def test_legal_abbreviations_are_protected(self):
        hyphenator = Hyphenator()
        for term in ["plaintiff", "defendant", "appellant"]:
            assert hyphenator.break_points(term) == []

    def test_exceptions_override_patterns(self):
        hyphenator = Hyphenator()
        hyphenator.add_exception("example", ["ex", "am", "ple"])
        assert hyphenator.break_points("example") == [2, 4]

    def test_results_are_cached_consistently(self):
        hyphenator = Hyphenator()
        first = hyphenator.break_points("information")
        second = hyphenator.break_points("information")
        assert first == second


class TestLineBreaking:
    @staticmethod
    def _items(text: str, width: float = 10.0) -> list:
        items = []
        for index, word in enumerate(text.split()):
            if index:
                items.append(Glue(width=4.0, stretch=2.0, shrink=1.0))
            items.append(Box(width=len(word) * width, text=word))
        items.append(Glue(width=0.0, stretch=10_000.0))
        items.append(Penalty(penalty=-10_000.0))
        return items

    def test_no_line_exceeds_the_target_width(self):
        breaker = LineBreaker()
        text = "the quick brown fox jumps over the lazy dog again and again"
        lines = breaker.break_paragraph(self._items(text), 200.0)
        assert lines
        for line in lines[:-1]:
            assert line.width <= 200.0 * 1.02

    def test_all_content_is_preserved(self):
        breaker = LineBreaker()
        text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        lines = breaker.break_paragraph(self._items(text), 150.0)
        produced = " ".join(line.text for line in lines).split()
        assert produced == text.split()

    def test_optimal_beats_greedy_on_evenness(self):
        """Knuth-Plass should produce more consistent line fill than greedy."""
        breaker = LineBreaker()
        text = ("typography is the art and technique of arranging type to "
                "make written language legible readable and appealing when "
                "displayed the arrangement involves selecting typefaces")
        items = self._items(text, width=6.0)
        optimal = breaker.break_paragraph(items, 220.0)
        greedy = breaker._greedy(items, lambda _n: 220.0)

        def variance(lines):
            widths = [l.width for l in lines[:-1]]
            if len(widths) < 2:
                return 0.0
            mean = sum(widths) / len(widths)
            return sum((w - mean) ** 2 for w in widths) / len(widths)

        assert variance(optimal) <= variance(greedy) * 1.05

    def test_empty_input_returns_no_lines(self):
        assert LineBreaker().break_paragraph([], 100.0) == []

    def test_narrow_column_still_produces_output(self):
        """A pathological width must degrade, not fail."""
        breaker = LineBreaker()
        lines = breaker.break_paragraph(self._items("extraordinarily long"), 20.0)
        assert lines


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------

class TestLayout:
    def test_content_never_overflows_the_page(self):
        doc = Document(title="Overflow")
        for index in range(30):
            doc.paragraph(f"Paragraph {index}. " + "Body text. " * 20)
        data = doc.render()
        assert verify_pdf(data).page_count > 1

    def test_page_break_forces_new_page(self):
        doc = Document(title="Breaks")
        doc.paragraph("First page")
        doc.page_break()
        doc.paragraph("Second page")
        assert verify_pdf(doc.render()).page_count == 2

    def test_long_table_splits_and_repeats_header(self):
        doc = Document(title="Table")
        doc.table(headers=["Index", "Value"],
                  rows=[[str(i), f"value {i}"] for i in range(90)])
        data = doc.render()
        report = verify_pdf(data)
        assert report.page_count > 1
        assert report.ok
        # The header row should appear once per page it spans.
        assert data.count(b"/THead") >= report.page_count - 1

    def test_table_columns_fit_content_width(self):
        from emboss.layout.engine import LayoutEngine
        from emboss.styles import resolve_preset

        engine = LayoutEngine(FontRegistry(), resolve_preset("finance"))
        table = Table(headers=["Short", "A much longer header cell"],
                      rows=[["x", "y"]])
        measured = engine.measure(table, 468.0)
        assert sum(measured.table.column_widths) == pytest.approx(468.0, abs=1.0)

    def test_explicit_column_widths_are_honoured(self):
        from emboss.layout.engine import LayoutEngine
        from emboss.styles import resolve_preset

        engine = LayoutEngine(FontRegistry(), resolve_preset("finance"))
        table = Table(headers=["A", "B"], rows=[["1", "2"]],
                      column_widths=[1.0, 3.0])
        measured = engine.measure(table, 400.0)
        widths = measured.table.column_widths
        assert widths[1] == pytest.approx(widths[0] * 3, rel=0.01)

    def test_heading_stays_with_following_paragraph(self):
        """A heading must not be stranded alone at the foot of a page.

        Asserted against the paginated layout rather than the content
        stream: text is emitted as kerned TJ arrays, so a phrase is not
        contiguous in the page bytes.
        """
        from emboss.layout.engine import LayoutEngine
        from emboss.typography.hyphenation import Hyphenator

        marker = "This paragraph must share a page with its heading."

        # Sweep filler lengths so the heading lands at a page boundary
        # regardless of exact metric rounding.
        boundary_seen = False
        for filler in range(18, 30):
            doc = Document(title="Keep")
            for _ in range(filler):
                doc.paragraph("Filler text pushing the heading downward. " * 3)
            doc.heading("Stranded Heading", level=2)
            doc.paragraph(marker)

            engine = LayoutEngine(
                FontRegistry(), doc.stylesheet, hyphenator=Hyphenator()
            )
            measured = [
                engine.measure(el, doc.page.content_width)
                for el in doc.content
            ]
            pages = engine.paginate(measured, doc.page)
            if len(pages) < 2:
                continue
            boundary_seen = True

            heading_page = paragraph_page = None
            for index, page in enumerate(pages):
                for placed in page.blocks:
                    element = placed.block.element
                    if isinstance(element, Heading):
                        heading_page = index
                    elif (isinstance(element, Paragraph)
                          and element.plain_text.startswith("This paragraph")):
                        paragraph_page = index

            assert heading_page is not None
            assert paragraph_page is not None
            assert heading_page == paragraph_page, (
                f"with {filler} filler blocks the heading landed on page "
                f"{heading_page} but its paragraph on page {paragraph_page}"
            )

        assert boundary_seen, "no configuration produced a page boundary"


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

class TestValidation:
    def test_empty_document_is_rejected(self):
        with pytest.raises(ValidationError, match="no content"):
            Document(title="Empty").render()

    def test_impossible_margins_are_rejected(self):
        doc = Document(title="Margins",
                       page=PageSpec(width=200, height=200,
                                     margin_left=95, margin_right=95))
        doc.paragraph("Body")
        with pytest.raises(ValidationError, match="usable width"):
            doc.render()

    def test_oversized_font_is_clamped(self):
        doc = Document(title="Clamp")
        doc.paragraph("Body", style=Style(font_size=500.0))
        result = ConstraintValidator().validate(doc)
        assert any("clamped" in issue.message for issue in result.fixes)
        assert result.ok

    def test_overwide_columns_are_rescaled(self):
        doc = Document(title="Rescale")
        doc.table(headers=["A", "B"], rows=[["1", "2"]],
                  column_widths=[900.0, 900.0])
        result = ConstraintValidator().validate(doc)
        assert any("rescaled" in issue.message for issue in result.fixes)
        assert sum(result.document.content[0].column_widths) <= (
            doc.page.content_width * 1.01
        )

    def test_skipped_heading_level_warns(self):
        doc = Document(title="Skip")
        doc.heading("One", level=1)
        doc.heading("Three", level=3)
        result = ConstraintValidator().validate(doc)
        assert any("jumps" in issue.message for issue in result.warnings)

    def test_strict_mode_promotes_warnings(self):
        doc = Document(title="Strict")
        doc.heading("One", level=1)
        doc.heading("Three", level=3)
        result = ConstraintValidator(strict=True).validate(doc)
        assert not result.ok

    def test_validation_does_not_mutate_the_input(self):
        doc = Document(title="Immutable")
        doc.table(headers=["A"], rows=[["1"]], column_widths=[5000.0])
        ConstraintValidator().validate(doc)
        assert doc.content[0].column_widths == [5000.0]

    def test_table_row_length_mismatch_warns(self):
        doc = Document(title="Ragged")
        doc.table(headers=["A", "B", "C"], rows=[["1", "2"]])
        result = ConstraintValidator().validate(doc)
        assert any("cells" in issue.message for issue in result.warnings)


# --------------------------------------------------------------------------
# Object serialization
# --------------------------------------------------------------------------

class TestSerialization:
    def test_number_formatting_is_stable(self):
        assert fmt_number(1.0) == b"1"
        assert fmt_number(1.5) == b"1.5"
        assert fmt_number(0.0) == b"0"
        assert fmt_number(-0.0) == b"0"
        assert fmt_number(1.23456789) == b"1.2346"

    def test_non_finite_numbers_are_rejected(self):
        with pytest.raises(ValueError):
            fmt_number(float("inf"))
        with pytest.raises(ValueError):
            fmt_number(float("nan"))

    def test_names_escape_special_characters(self):
        assert PdfName("Simple").serialize() == b"/Simple"
        assert b"#20" in PdfName("With Space").serialize()

    def test_strings_escape_delimiters(self):
        assert PdfString("a(b)c").serialize() == b"(a\\(b\\)c)"

    def test_unicode_strings_use_utf16(self):
        result = PdfString("caf\u00e9").serialize()
        assert result.startswith(b"<FEFF")


# --------------------------------------------------------------------------
# Domain features
# --------------------------------------------------------------------------

class TestLegalFeatures:
    def test_bates_numbers_increment_per_page(self):
        pytest.importorskip("pikepdf")
        import io

        import pikepdf

        doc = Document(title="Bates",
                       legal=LegalFeatures(bates_prefix="ACME-", bates_start=1))
        for _ in range(25):
            doc.paragraph("Filler content for pagination. " * 8)

        with pikepdf.open(io.BytesIO(doc.render())) as pdf:
            assert len(pdf.pages) >= 2
            first = pdf.pages[0].Contents.read_bytes()
            second = pdf.pages[1].Contents.read_bytes()
        assert b"ACME-000001" in first
        assert b"ACME-000002" in second

    def test_watermark_is_an_artifact(self):
        doc = Document(title="Watermark",
                       legal=LegalFeatures(watermark="CONFIDENTIAL"))
        doc.paragraph("Body")
        content = _page_content(doc)
        assert b"CONFIDENTIAL" in content
        assert b"/Watermark" in content
        assert b"/ExtGState" in doc.render()

    def test_line_numbering_renders(self):
        doc = Document(title="Pleading", style="legal",
                       page=PageSpec.letter(margin_left=108),
                       legal=LegalFeatures(line_numbering=True))
        doc.paragraph("Body text for a pleading. " * 10)
        assert b"/LineNumber" in _page_content(doc)


class TestStyles:
    def test_all_presets_render(self):
        from emboss.styles import PRESETS

        for name in PRESETS:
            doc = Document(title=f"Preset {name}", style=name)
            doc.heading("Heading", level=1)
            doc.paragraph("Body text. " * 20)
            doc.table(headers=["A", "B"], rows=[["1", "2"]])
            assert verify_pdf(doc.render()).ok

    def test_style_cascade_prefers_child_values(self):
        parent = Style(font_size=12.0, color="000000")
        child = Style(font_size=14.0)
        merged = child.inherit_from(parent)
        assert merged.font_size == 14.0
        assert merged.color == "000000"

    def test_unknown_preset_raises(self):
        with pytest.raises(KeyError, match="unknown style preset"):
            Document(title="X", style="nonexistent").stylesheet

    def test_inline_run_overrides_apply(self):
        doc = Document(title="Runs")
        doc.paragraph([
            TextRun("normal "),
            TextRun("bold", bold=True),
            TextRun(" and "),
            TextRun("colored", color="cc0000"),
        ])
        data = doc.render()
        assert verify_pdf(data).ok


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
