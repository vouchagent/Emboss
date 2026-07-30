"""Tests for building tables and charts directly from CSV/DataFrame data."""

import io

import pytest

from emboss import Document
from emboss.constraints import ValidationError

pd = pytest.importorskip("pandas", reason="pandas is an optional dependency")


CSV_TEXT = (
    "Region,Q1,Q2\n"
    'North America,"$12,430.00","$14,200.50"\n'
    'EMEA,"8,910.25",9500\n'
    'APAC,"5,204.75",6000\n'
)

TOTALS_CSV = "Segment,Bookings,Costs\nPlatform,12400,7100\nServices,6800,4200\nTotal,19200,11300\n"

BAD_TOTALS_CSV = "Segment,Bookings\nPlatform,12400\nServices,6800\nTotal,99999\n"


class TestTableFromCsv:
    def test_from_path(self, tmp_path):
        path = tmp_path / "bookings.csv"
        path.write_text(CSV_TEXT, encoding="utf-8")
        doc = Document(title="D").table_from_csv(path)
        table = doc.content[0]
        assert [c.plain_text for c in table.header_cells] == ["Region", "Q1", "Q2"]
        assert doc.render().startswith(b"%PDF")

    def test_from_csv_text(self):
        doc = Document(title="D").table_from_csv(CSV_TEXT)
        table = doc.content[0]
        assert table.body_rows[0][0].plain_text == "North America"

    def test_from_file_object(self, tmp_path):
        path = tmp_path / "bookings.csv"
        path.write_text(CSV_TEXT, encoding="utf-8")
        with open(path, newline="", encoding="utf-8") as fh:
            doc = Document(title="D").table_from_csv(fh)
        assert doc.render().startswith(b"%PDF")

    def test_from_stringio(self):
        doc = Document(title="D").table_from_csv(io.StringIO(CSV_TEXT))
        assert doc.render().startswith(b"%PDF")

    def test_no_header_synthesizes_columns(self):
        doc = Document(title="D").table_from_csv(CSV_TEXT, has_header=False)
        table = doc.content[0]
        assert [c.plain_text for c in table.header_cells] == [
            "Column 1",
            "Column 2",
            "Column 3",
        ]
        assert table.body_rows[0][0].plain_text == "Region"

    def test_composes_with_verify_totals_consistent(self):
        doc = Document(title="D").table_from_csv(TOTALS_CSV, verify_totals=True)
        assert doc.render().startswith(b"%PDF")

    def test_composes_with_verify_totals_inconsistent_refused(self):
        doc = Document(title="D").table_from_csv(BAD_TOTALS_CSV, verify_totals=True)
        with pytest.raises(ValidationError, match="sum"):
            doc.render()

    def test_composes_with_attach_data(self):
        pikepdf = pytest.importorskip("pikepdf")
        doc = Document(title="D").table_from_csv(CSV_TEXT, attach_data=True)
        pdf = doc.render(embed_spec=True)
        with pikepdf.open(io.BytesIO(pdf)) as p:
            assert "table-1-data.csv" in p.attachments

    def test_kwargs_pass_through_caption(self):
        doc = Document(title="D").table_from_csv(CSV_TEXT, caption="Bookings")
        assert doc.content[0].caption == "Bookings"

    def test_from_dataframe(self):
        df = pd.DataFrame({"Region": ["NA", "EMEA"], "Q1": [100, 200]})
        doc = Document(title="D").table_from_csv(df)
        table = doc.content[0]
        assert [c.plain_text for c in table.header_cells] == ["Region", "Q1"]
        assert table.body_rows[0][0].plain_text == "NA"

    def test_empty_csv_raises(self):
        with pytest.raises(ValueError, match="no rows"):
            Document(title="D").table_from_csv("")


class TestChartFromCsv:
    def test_multi_series(self):
        doc = Document(title="D").chart_from_csv(CSV_TEXT, chart_type="bar")
        chart = doc.content[0]
        assert chart.labels == ["North America", "EMEA", "APAC"]
        assert {s.label for s in chart.series} == {"Q1", "Q2"}
        assert chart.series[0].values == pytest.approx([12430.0, 8910.25, 5204.75])
        assert doc.render().startswith(b"%PDF")

    def test_single_series_uses_plain_values(self):
        text = "Region,Bookings\nNA,100\nEMEA,200\n"
        doc = Document(title="D").chart_from_csv(text)
        chart = doc.content[0]
        assert not chart.series
        assert chart.values == pytest.approx([100.0, 200.0])

    def test_explicit_value_columns_by_name(self):
        doc = Document(title="D").chart_from_csv(CSV_TEXT, value_columns=["Q2"])
        chart = doc.content[0]
        assert not chart.series
        assert chart.values == pytest.approx([14200.5, 9500.0, 6000.0])

    def test_explicit_category_column_by_name(self):
        doc = Document(title="D").chart_from_csv(CSV_TEXT, category_column="Region")
        assert doc.content[0].labels == ["North America", "EMEA", "APAC"]

    def test_composes_with_attach_data(self):
        pikepdf = pytest.importorskip("pikepdf")
        doc = Document(title="D").chart_from_csv(CSV_TEXT, attach_data=True)
        pdf = doc.render(embed_spec=True)
        with pikepdf.open(io.BytesIO(pdf)) as p:
            assert "chart-1-data.csv" in p.attachments

    def test_no_numeric_columns_raises(self):
        text = "A,B\nfoo,bar\nbaz,qux\n"
        with pytest.raises(ValueError, match="numeric"):
            Document(title="D").chart_from_csv(text)

    def test_from_dataframe(self):
        df = pd.DataFrame({"Region": ["NA", "EMEA"], "Bookings": [100, 200]})
        doc = Document(title="D").chart_from_csv(df)
        assert doc.content[0].labels == ["NA", "EMEA"]
        assert doc.render().startswith(b"%PDF")


class TestDeterminism:
    def test_table_from_csv_deterministic(self):
        doc = Document(title="D").table_from_csv(CSV_TEXT)
        assert doc.render() == doc.render()

    def test_chart_from_csv_deterministic(self):
        doc = Document(title="D").chart_from_csv(CSV_TEXT)
        assert doc.render() == doc.render()
