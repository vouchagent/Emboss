"""Tests for table total validation and number parsing."""

import pytest

from emboss import Document
from emboss.arithmetic import check_table_totals, parse_number
from emboss.constraints import ValidationError


class TestParseNumber:
    def test_currency_and_thousands(self):
        assert parse_number("$1,234.50") == 1234.5

    def test_accounting_negative(self):
        assert parse_number("(123)") == -123.0

    def test_european_decimal(self):
        assert parse_number("1.234,50") == 1234.5

    def test_percent(self):
        assert parse_number("45%") == 45.0

    def test_non_numeric_is_none(self):
        assert parse_number("n/a") is None
        assert parse_number("") is None
        assert parse_number("-") is None


class TestCheckTotals:
    def test_consistent_total_row_passes(self):
        msgs = check_table_totals(
            ["Region", "Q1", "Q2"],
            [["NA", "100", "200"], ["EMEA", "50", "80"], ["Total", "150", "280"]],
        )
        assert msgs == []

    def test_inconsistent_total_row_flagged(self):
        msgs = check_table_totals(
            ["Region", "Q1", "Q2"],
            [["NA", "100", "200"], ["EMEA", "50", "80"], ["Total", "150", "999"]],
        )
        assert len(msgs) == 1
        assert "999" in msgs[0] and "280" in msgs[0]

    def test_total_column_checked(self):
        msgs = check_table_totals(
            ["Item", "Jan", "Feb", "Total"],
            [["A", "10", "20", "30"], ["B", "5", "5", "99"]],
        )
        assert len(msgs) == 1
        assert "'B'" in msgs[0]

    def test_non_total_table_ignored(self):
        # No total row/column, so nothing to check.
        assert check_table_totals(["A", "B"], [["1", "2"], ["3", "4"]]) == []

    def test_cent_rounding_within_tolerance(self):
        msgs = check_table_totals(
            ["X", "V"], [["a", "0.005"], ["b", "0.005"], ["Total", "0.01"]]
        )
        assert msgs == []


class TestRenderIntegration:
    def test_consistent_table_renders_with_verify(self):
        doc = Document(title="Fin")
        doc.table(
            headers=["Region", "Q1", "Q2"],
            rows=[["NA", "100", "200"], ["Total", "100", "200"]],
            verify_totals=True,
        )
        assert doc.render().startswith(b"%PDF")

    def test_inconsistent_table_is_refused(self):
        doc = Document(title="Bad")
        doc.table(
            headers=["Region", "Q1"],
            rows=[["NA", "100"], ["EMEA", "50"], ["Total", "999"]],
            verify_totals=True,
        )
        with pytest.raises(ValidationError, match="sum"):
            doc.render()

    def test_without_verify_flag_inconsistent_still_renders(self):
        doc = Document(title="Loose")
        doc.table(
            headers=["Region", "Q1"],
            rows=[["NA", "100"], ["Total", "999"]],
        )
        assert doc.render().startswith(b"%PDF")

    def test_verify_totals_survives_spec_roundtrip(self):
        from emboss.recovery import document_to_spec_dict, spec_dict_to_json

        doc = Document(title="R")
        doc.table(headers=["A", "B"], rows=[["x", "1"]], verify_totals=True, id="t1")
        spec = spec_dict_to_json(document_to_spec_dict(doc)).decode()
        loaded = Document.from_json(spec)
        assert loaded.content[0].verify_totals is True
