"""Tests for the Content Intelligence Engine."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss.intelligence import (
    ContentAnalyzer,
    DocumentTypeDetector,
    SmartTypography,
    TableIntelligence,
)


class TestSmartTypography:
    def setup_method(self):
        self.typo = SmartTypography()

    def test_smart_double_quotes(self):
        result = self.typo.transform('He said "hello" to her.')
        assert "“" in result  # "
        assert "”" in result  # "

    def test_smart_single_quotes(self):
        result = self.typo.transform("It's a 'test' of quotes.")
        assert "’" in result  # apostrophe / closing single quote

    def test_em_dash(self):
        result = self.typo.transform("word---another word")
        assert "—" in result  # —

    def test_en_dash(self):
        result = self.typo.transform("word--another")
        assert "–" in result  # –

    def test_number_range_en_dash(self):
        result = self.typo.transform("pages 10-20")
        assert "10–20" in result

    def test_ellipsis(self):
        result = self.typo.transform("wait for it...")
        assert "…" in result  # …

    def test_fractions(self):
        result = self.typo.transform("about 1/2 of 3/4")
        assert "½" in result  # ½
        assert "¾" in result  # ¾

    def test_non_breaking_space_before_units(self):
        result = self.typo.transform("The file is 500 MB in size.")
        assert "500 MB" in result

    def test_preserves_normal_text(self):
        text = "Simple text with no special characters."
        result = self.typo.transform(text)
        assert result == text


class TestTableIntelligence:
    def setup_method(self):
        self.intel = TableIntelligence()

    def test_detects_currency_column(self):
        analysis = self.intel.analyze(
            headers=["Item", "Amount"],
            rows=[
                ["Widget A", "$1,234.56"],
                ["Widget B", "$987.65"],
                ["Widget C", "$2,345.00"],
            ],
        )
        assert analysis.columns[1].content_type == "currency"
        assert analysis.columns[1].recommended_align == "decimal"
        assert analysis.columns[1].is_numeric

    def test_detects_percentage_column(self):
        analysis = self.intel.analyze(
            headers=["Item", "Growth"],
            rows=[
                ["A", "+12.5%"],
                ["B", "-3.2%"],
                ["C", "+8.0%"],
            ],
        )
        assert analysis.columns[1].content_type == "percentage"
        assert analysis.columns[1].recommended_align == "right"

    def test_detects_text_column(self):
        analysis = self.intel.analyze(
            headers=["Name", "City"],
            rows=[
                ["Alice", "New York"],
                ["Bob", "London"],
            ],
        )
        assert analysis.columns[0].content_type == "text"
        assert analysis.columns[0].recommended_align == "left"

    def test_detects_summary_row(self):
        analysis = self.intel.analyze(
            headers=["Item", "Amount"],
            rows=[
                ["Widget A", "$100"],
                ["Widget B", "$200"],
                ["Total", "$300"],
            ],
        )
        assert analysis.summary_rows == [2]
        assert analysis.has_total_row

    def test_detects_subtotal_row(self):
        analysis = self.intel.analyze(
            headers=["Item", "Amount"],
            rows=[
                ["Widget A", "$100"],
                ["Subtotal", "$100"],
                ["Widget B", "$200"],
                ["Grand Total", "$300"],
            ],
        )
        assert 1 in analysis.summary_rows
        assert 3 in analysis.summary_rows

    def test_recommends_stripe_for_large_tables(self):
        rows = [[f"Item {i}", f"${i * 100}"] for i in range(10)]
        analysis = self.intel.analyze(
            headers=["Item", "Amount"],
            rows=rows,
        )
        assert analysis.recommended_stripe

    def test_no_stripe_for_small_tables(self):
        analysis = self.intel.analyze(
            headers=["A", "B"],
            rows=[["1", "2"], ["3", "4"]],
        )
        assert not analysis.recommended_stripe


class TestDocumentTypeDetector:
    def setup_method(self):
        self.detector = DocumentTypeDetector()

    def test_detects_legal_document(self):
        profile = self.detector.detect(
            title="Non-Disclosure Agreement",
            headings=["Recitals", "Confidential Information", "Term and Termination"],
            paragraphs=[
                "WHEREAS Party A desires to disclose confidential information.",
                "The parties hereby agree pursuant to the following terms.",
                "Notwithstanding any provision herein, the liability shall be limited.",
            ],
            table_count=0,
        )
        assert profile.detected_type == "legal"
        assert profile.recommended_style == "legal"
        assert profile.confidence > 0.2

    def test_detects_financial_document(self):
        profile = self.detector.detect(
            title="Q3 2026 Financial Report",
            headings=["Executive Summary", "Revenue Analysis", "Forecast"],
            paragraphs=[
                "Revenue for Q3 reached $4.53 million with operating margin at 18.2%.",
                "EBITDA improved by 12% as cash flow from operations strengthened.",
                "Management reiterates full-year guidance with dividend expectations.",
            ],
            table_count=3,
        )
        assert profile.detected_type == "financial"
        assert profile.recommended_style == "finance"

    def test_detects_academic_document(self):
        profile = self.detector.detect(
            title="Effects of Temperature on Enzyme Activity",
            headings=["Abstract", "Methodology", "Results", "References"],
            paragraphs=[
                "This study presents empirical findings from a longitudinal analysis.",
                "The hypothesis was tested using quantitative regression analysis.",
                "Statistical significance was confirmed with p-value < 0.05.",
            ],
            table_count=1,
        )
        assert profile.detected_type == "academic"
        assert profile.recommended_style == "academic"

    def test_detects_technical_document(self):
        profile = self.detector.detect(
            title="API Migration Guide v2.0",
            headings=["Architecture Overview", "Deployment", "Configuration"],
            paragraphs=[
                "The new API endpoint supports authentication via OAuth2.",
                "Deploy the container using Kubernetes with the updated schema.",
                "Configure the CI/CD pipeline for automated monitoring.",
            ],
            table_count=0,
        )
        assert profile.detected_type == "technical"
        assert profile.recommended_style == "corporate"

    def test_returns_general_for_ambiguous(self):
        profile = self.detector.detect(
            title="My Document",
            headings=["Section 1"],
            paragraphs=["This is a paragraph about general topics."],
            table_count=0,
        )
        assert profile.detected_type == "general"
        assert profile.recommended_style == "corporate"


class TestContentAnalyzer:
    def setup_method(self):
        self.analyzer = ContentAnalyzer()

    def test_full_analysis(self):
        spec = {
            "title": "Revenue Report",
            "content": [
                {"type": "heading", "text": "Summary", "level": 1},
                {"type": "paragraph", "text": "Revenue reached $4.5M in Q3."},
                {
                    "type": "table",
                    "headers": ["Region", "Revenue", "Change"],
                    "rows": [
                        ["North America", "$2,431,000", "+11.5%"],
                        ["Europe", "$1,204,300", "+4.7%"],
                        ["Total", "$3,635,300", "+8.9%"],
                    ],
                },
            ],
        }
        analysis = self.analyzer.analyze_spec(spec)
        assert analysis.document_profile is not None
        assert len(analysis.table_analyses) == 1
        assert analysis.table_analyses[0].summary_rows == [2]

    def test_enhance_applies_smart_typography(self):
        spec = {
            "title": "Test",
            "content": [
                {"type": "paragraph", "text": 'He said "hello" and left...'},
            ],
        }
        enhanced = self.analyzer.enhance_spec(spec)
        text = enhanced["content"][0]["text"]
        assert "“" in text  # smart quote
        assert "…" in text  # ellipsis

    def test_enhance_bolds_summary_rows(self):
        spec = {
            "title": "Test",
            "content": [
                {
                    "type": "table",
                    "headers": ["Item", "Amount"],
                    "rows": [
                        ["Widget", "$100"],
                        ["Total", "$100"],
                    ],
                }
            ],
        }
        enhanced = self.analyzer.enhance_spec(spec)
        total_row = enhanced["content"][0]["rows"][1]
        for cell in total_row:
            if isinstance(cell, dict):
                assert cell.get("bold") is True

    def test_enhance_auto_detects_style(self):
        spec = {
            "title": "Non-Disclosure Agreement",
            "content": [
                {"type": "heading", "text": "Recitals", "level": 1},
                {
                    "type": "paragraph",
                    "text": "WHEREAS the parties herein agree pursuant to this covenant.",
                },
            ],
        }
        enhanced = self.analyzer.enhance_spec(spec)
        assert enhanced.get("style") == "legal"

    def test_enhance_respects_explicit_style(self):
        spec = {
            "title": "Non-Disclosure Agreement",
            "style": "corporate",
            "content": [
                {"type": "heading", "text": "Recitals", "level": 1},
                {"type": "paragraph", "text": "WHEREAS the parties agree."},
            ],
        }
        enhanced = self.analyzer.enhance_spec(spec)
        assert enhanced["style"] == "corporate"

    def test_from_smart_integration(self):
        from emboss.adapters.pydantic_schema import DocumentSpec

        spec = DocumentSpec.from_smart(
            {
                "title": "Report",
                "content": [
                    {"type": "heading", "text": "Summary", "level": 1},
                    {"type": "paragraph", "text": 'Revenue grew "significantly"...'},
                ],
            }
        )
        assert spec.title == "Report"
        pdf = spec.render()
        from emboss.pdf.verify import verify_pdf

        assert verify_pdf(pdf).ok


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
