"""Tests for slide/presentation layout support."""

import pytest

from precisionpdf import Document
from precisionpdf.slides import (
    SLIDE_16_9, SLIDE_4_3, SlideConfig, slide_document, _build_slide_sheet,
)
from precisionpdf.styles import Style


class TestSlideConfig:
    def test_default_aspect_ratio(self):
        config = SlideConfig()
        assert config.aspect_ratio == "16:9"
        assert config.page_spec is SLIDE_16_9

    def test_4_3_aspect_ratio(self):
        config = SlideConfig(aspect_ratio="4:3")
        assert config.page_spec is SLIDE_4_3

    def test_slide_numbers_default(self):
        config = SlideConfig()
        assert config.slide_numbers is True


class TestPageSpecs:
    def test_16_9_landscape(self):
        assert SLIDE_16_9.width > SLIDE_16_9.height
        assert SLIDE_16_9.width == 720.0
        assert SLIDE_16_9.height == 405.0

    def test_4_3_landscape(self):
        assert SLIDE_4_3.width > SLIDE_4_3.height
        assert SLIDE_4_3.width == 720.0
        assert SLIDE_4_3.height == 540.0

    def test_content_area_16_9(self):
        assert SLIDE_16_9.content_width == 720.0 - 48.0 - 48.0
        assert SLIDE_16_9.content_height == 405.0 - 36.0 - 36.0

    def test_content_area_4_3(self):
        assert SLIDE_4_3.content_width == 720.0 - 48.0 - 48.0
        assert SLIDE_4_3.content_height == 540.0 - 40.0 - 40.0


class TestSlideDocument:
    def test_basic_creation(self):
        doc = slide_document("My Presentation")
        assert doc.title == "My Presentation"
        assert doc.page is SLIDE_16_9
        assert doc.page_numbers is True
        assert len(doc.content) >= 2  # heading + page_break

    def test_with_subtitle(self):
        doc = slide_document("Title", subtitle="A Subtitle")
        assert len(doc.content) >= 3

    def test_with_author(self):
        doc = slide_document("Title", author="Jane Doe")
        assert doc.author == "Jane Doe"
        assert len(doc.content) >= 3

    def test_full_title_slide(self):
        doc = slide_document("Title", subtitle="Sub", author="Author")
        assert len(doc.content) >= 4

    def test_4_3_aspect(self):
        doc = slide_document("Title", aspect_ratio="4:3")
        assert doc.page is SLIDE_4_3

    def test_no_slide_numbers(self):
        doc = slide_document("Title", slide_numbers=False)
        assert doc.page_numbers is False


class TestSlideThemes:
    def test_default_theme(self):
        sheet = _build_slide_sheet("default")
        assert sheet.name == "slide-default"
        assert sheet.body.font_size == 18.0

    def test_dark_theme(self):
        sheet = _build_slide_sheet("dark")
        assert sheet.name == "slide-dark"
        assert sheet.body.color == "e2e8f0"

    def test_minimal_theme(self):
        sheet = _build_slide_sheet("minimal")
        assert sheet.name == "slide-minimal"

    def test_unknown_theme_falls_back(self):
        sheet = _build_slide_sheet("nonexistent")
        assert sheet.body.font_size == 18.0

    def test_slide_fonts_larger_than_document(self):
        sheet = _build_slide_sheet("default")
        assert sheet.body.font_size > 14.0
        resolved_h1 = sheet.h1
        assert resolved_h1.font_size > 30.0

    def test_h1_centered(self):
        sheet = _build_slide_sheet("default")
        assert sheet.h1.align == "center"

    def test_h2_left_aligned(self):
        sheet = _build_slide_sheet("default")
        assert sheet.h2.align == "left"


class TestSlideRendering:
    def test_renders_valid_pdf(self):
        doc = slide_document("Test Presentation")
        doc.heading("Slide 2", level=2)
        doc.paragraph("Content on slide 2.")
        pdf = doc.render()

        assert b"%PDF-1.7" in pdf
        assert b"%%EOF" in pdf

    def test_renders_with_bullet_list(self):
        doc = slide_document("Bullets Test")
        doc.heading("Key Points", level=2)
        doc.bullets(["Point one", "Point two", "Point three"])
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_renders_with_table(self):
        doc = slide_document("Table Test")
        doc.heading("Data", level=2)
        doc.table(
            ["Metric", "Value"],
            [["Revenue", "$12.4M"], ["Growth", "18%"]],
        )
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_multi_slide_document(self):
        doc = slide_document("Multi Slide")
        for i in range(2, 6):
            doc.heading(f"Slide {i}", level=2)
            doc.paragraph(f"Content for slide {i}.")
            if i < 5:
                doc.page_break()
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf
        # Should have title slide + 4 content slides = 5 pages
        count_match = __import__("re").search(rb"/Count (\d+)", pdf)
        assert count_match
        assert int(count_match.group(1)) == 5

    def test_dark_theme_renders(self):
        doc = slide_document("Dark Theme", theme="dark")
        doc.heading("Dark Slide", level=2)
        doc.paragraph("Dark themed content.")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_minimal_theme_renders(self):
        doc = slide_document("Minimal", theme="minimal")
        doc.heading("Clean", level=2)
        doc.paragraph("Minimal styled slide.")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_slide_with_callout(self):
        doc = slide_document("Callout Slide")
        doc.heading("Important", level=2)
        doc.callout("This is a key takeaway.", variant="success")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_verification_passes(self):
        from precisionpdf.pdf.verify import verify_pdf

        doc = slide_document("Verified Slides")
        doc.heading("Slide 2", level=2)
        doc.paragraph("Content.")
        pdf = doc.render()

        report = verify_pdf(pdf)
        assert report.ok, f"Verification failed: {report.problems}"

    def test_deterministic_output(self):
        def make():
            doc = slide_document("Deterministic", subtitle="Sub")
            doc.heading("Content", level=2)
            doc.paragraph("Same every time.")
            return doc.render()

        assert make() == make()

    def test_landscape_media_box(self):
        doc = slide_document("Landscape Check")
        doc.heading("Slide 2", level=2)
        doc.paragraph("Checking media box.")
        pdf = doc.render()

        # MediaBox should be [0 0 720 405]
        assert b"/MediaBox [0 0 720 405]" in pdf
