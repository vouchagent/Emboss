"""Tests for chart/table headline+source_line, full ChartData wiring, chart
fact verification, and element-level /AF data attachments (Layer-1 remainder).
"""

from __future__ import annotations

import io

import pytest

from emboss import Chart, Document, Series, Table
from emboss.chart_facts import resolve_headline


def _page_content(document: Document, page: int = 0) -> bytes:
    pikepdf = pytest.importorskip("pikepdf")
    with pikepdf.open(io.BytesIO(document.render())) as pdf:
        return bytes(pdf.pages[page].Contents.read_bytes())


def _font_basefonts(document: Document, page: int = 0) -> dict:
    pikepdf = pytest.importorskip("pikepdf")
    with pikepdf.open(io.BytesIO(document.render())) as pdf:
        fonts = pdf.pages[page].Resources.Font
        return {str(key): str(fonts[key].BaseFont) for key in fonts.keys()}


def _bold_font_keys(document: Document, page: int = 0) -> set:
    return {k for k, name in _font_basefonts(document, page).items() if "Bold" in name}


class TestChartHeadlineSourceLine:
    def _doc(self, **kw) -> Document:
        doc = Document(title="T")
        doc.add(Chart(chart_type="bar", labels=["Q1", "Q2"], values=[10.0, 20.0], **kw))
        return doc

    def test_headline_bold_above_and_source_line_gray_below(self):
        doc = self._doc(
            headline="Revenue Growth", subtitle="FY2026", source_line="Source: Internal"
        )
        content = _page_content(doc)
        assert b"(Revenue Growth)" in content
        assert b"(FY2026)" in content
        assert b"(Source: Internal)" in content

        bold_keys = _bold_font_keys(doc)
        assert bold_keys
        bold_key = next(iter(bold_keys)).lstrip("/")
        text = content.decode("latin1")
        head_tf = text[: text.find("(Revenue Growth)")].rsplit("Tf", 1)[0].split()[-2]
        assert head_tf.lstrip("/") == bold_key

    def test_source_line_uses_small_gray_size(self):
        doc = self._doc(source_line="Source: X")
        text = _page_content(doc).decode("latin1")
        idx = text.find("(Source: X)")
        window = text[max(0, idx - 120) : idx]
        assert "7.5 Tf" in window
        assert " rg" in window
        # small gray, not the body ink color
        assert "0.102 0.102 0.102 rg" not in window

    def test_no_headline_or_source_line_by_default(self):
        doc = self._doc()
        content = _page_content(doc)
        assert b"Tj" in content  # chart still draws category labels etc.

    def test_subtitle_without_headline_still_renders(self):
        doc = self._doc(subtitle="Just a subtitle")
        content = _page_content(doc)
        assert b"(Just a subtitle)" in content


class TestTableHeadlineSourceLine:
    def _doc(self, **kw) -> Document:
        doc = Document(title="T")
        doc.add(Table(headers=["A", "B"], rows=[["1", "2"]], **kw))
        return doc

    def test_headline_bold_above_and_source_line_gray_below(self):
        doc = self._doc(
            headline="Table Headline",
            subtitle="Table Subtitle",
            source_line="Source: Y",
        )
        content = _page_content(doc)
        assert b"(Table Headline)" in content
        assert b"(Table Subtitle)" in content
        assert b"(Source: Y)" in content

        bold_keys = _bold_font_keys(doc)
        assert bold_keys
        bold_key = next(iter(bold_keys)).lstrip("/")
        text = content.decode("latin1")
        head_tf = text[: text.find("(Table Headline)")].rsplit("Tf", 1)[0].split()[-2]
        assert head_tf.lstrip("/") == bold_key

    def test_coexists_with_existing_caption(self):
        doc = self._doc(
            caption="A caption",
            headline="Head",
            source_line="Src",
        )
        content = _page_content(doc)
        assert b"(Head)" in content
        assert b"(Src)" in content
        assert b"A caption" in content

    def test_headline_only_on_first_page_of_split_table(self):
        doc = Document(title="T")
        rows = [[str(i), f"value {i}"] for i in range(80)]
        doc.add(
            Table(
                headers=["ID", "Value"],
                rows=rows,
                headline="Big Table",
                source_line="Tail Source",
            )
        )
        pikepdf = pytest.importorskip("pikepdf")
        with pikepdf.open(io.BytesIO(doc.render())) as pdf:
            assert len(pdf.pages) > 1
            headline_pages = sum(
                1 for page in pdf.pages if b"(Big Table)" in page.Contents.read_bytes()
            )
            source_pages = sum(
                1
                for page in pdf.pages
                if b"(Tail Source)" in page.Contents.read_bytes()
            )
        assert headline_pages == 1
        assert source_pages == 1

    def test_no_new_fields_renders_unaffected(self):
        plain = Document(title="T")
        plain.add(Table(headers=["A"], rows=[["1"]]))
        content = _page_content(plain)
        assert b"Headline" not in content
        assert b"Source" not in content


class TestChartDataFullWiring:
    def test_series_x_title_y_title_legend_patterns_end_to_end(self):
        doc = Document(title="T")
        doc.add(
            Chart(
                chart_type="line",
                labels=["Q1", "Q2"],
                series=[Series("North", [1.0, 2.0]), Series("South", [2.0, 3.0])],
                x_title="Quarter",
                y_title="Units",
                patterns=True,
            )
        )
        content = _page_content(doc)
        assert b"(North)" in content  # legend label
        assert b"(South)" in content
        assert b"(Quarter)" in content
        assert b"(Units)" in content
        # legend swatches: exactly one filled rect per named series
        assert content.count(b" re") >= 2

    def test_patterns_produce_clipped_pattern_strokes(self):
        doc = Document(title="T")
        doc.add(
            Chart(
                chart_type="bar",
                labels=["a", "b", "c", "d"],
                values=[10.0] * 4,
                patterns=True,
                legend=False,
            )
        )
        content = _page_content(doc)
        clips = [line for line in content.split(b"\n") if line.endswith(b"re W n")]
        assert len(clips) == 4

    def test_patterns_absent_by_default(self):
        doc = Document(title="T")
        doc.add(Chart(chart_type="bar", labels=["a", "b"], values=[1.0, 2.0]))
        content = _page_content(doc)
        assert b"re W n" not in content

    def test_legend_false_suppresses_swatches_for_named_series(self):
        doc = Document(title="T")
        doc.add(
            Chart(
                chart_type="line",
                labels=["a", "b"],
                series=[Series("A", [1.0, 2.0]), Series("B", [2.0, 1.0])],
                legend=False,
            )
        )
        content = _page_content(doc)
        assert b"(A)" not in content
        assert b"(B)" not in content


class TestPydanticPatterns:
    def test_chart_spec_patterns_parses_and_renders(self):
        pytest.importorskip("pydantic")
        from emboss.adapters.pydantic_schema import ChartSpec

        spec = ChartSpec(
            type="chart",
            chart_type="bar",
            labels=["a", "b"],
            values=[1.0, 2.0],
            patterns=True,
        )
        element = spec.to_element()
        assert element.patterns is True

        doc = Document(title="T")
        doc.add(element)
        content = _page_content(doc)
        clips = [line for line in content.split(b"\n") if line.endswith(b"re W n")]
        assert len(clips) == 2

    def test_chart_spec_headline_fields_wire_through(self):
        pytest.importorskip("pydantic")
        from emboss.adapters.pydantic_schema import ChartSpec

        spec = ChartSpec(
            type="chart",
            chart_type="bar",
            labels=["a"],
            values=[1.0],
            headline="H",
            subtitle="S",
            source_line="Src",
            verify_facts=True,
            attach_data=True,
        )
        element = spec.to_element()
        assert element.headline == "H"
        assert element.subtitle == "S"
        assert element.source_line == "Src"
        assert element.verify_facts is True
        assert element.attach_data is True

    def test_table_spec_new_fields_wire_through(self):
        pytest.importorskip("pydantic")
        from emboss.adapters.pydantic_schema import TableSpec

        spec = TableSpec(
            type="table",
            headers=["A"],
            rows=[["1"]],
            headline="H",
            subtitle="S",
            source_line="Src",
            attach_data=True,
        )
        element = spec.to_element()
        assert element.headline == "H"
        assert element.subtitle == "S"
        assert element.source_line == "Src"
        assert element.attach_data is True


class TestVerifyFacts:
    def test_fabricated_number_falls_back_to_fact_sentence(self):
        chart = Chart(
            chart_type="bar",
            labels=["Q1", "Q2"],
            values=[10.0, 20.0],
            headline="Revenue grew an incredible 900%",
            verify_facts=True,
        )
        resolved = resolve_headline(chart)
        assert resolved != chart.headline
        assert "900%" not in resolved

    def test_valid_caption_is_kept(self):
        chart = Chart(
            chart_type="bar",
            labels=["Q1", "Q2"],
            values=[10.0, 20.0],
            headline="Q2 leads at 20",
            verify_facts=True,
        )
        assert resolve_headline(chart) == "Q2 leads at 20"

    def test_verify_facts_off_leaves_headline_untouched_even_if_wrong(self):
        chart = Chart(
            chart_type="bar",
            labels=["Q1", "Q2"],
            values=[10.0, 20.0],
            headline="Revenue grew an incredible 900%",
        )
        assert resolve_headline(chart) == "Revenue grew an incredible 900%"

    def test_missing_headline_with_verify_facts_autogenerates(self):
        chart = Chart(
            chart_type="bar",
            labels=["Q1", "Q2"],
            values=[10.0, 20.0],
            verify_facts=True,
        )
        resolved = resolve_headline(chart)
        assert resolved
        assert "leads at" in resolved

    def test_fallback_renders_in_document(self):
        doc = Document(title="T")
        doc.add(
            Chart(
                chart_type="bar",
                labels=["Q1", "Q2"],
                values=[10.0, 20.0],
                headline="Grew an incredible 900%",
                verify_facts=True,
            )
        )
        content = _page_content(doc)
        assert b"900%" not in content
        assert b"leads at" in content


class TestAttachData:
    def test_chart_attach_data_true_produces_af_with_correct_csv(self):
        pikepdf = pytest.importorskip("pikepdf")
        doc = Document(title="T")
        doc.add(
            Chart(
                chart_type="bar",
                labels=["Q1", "Q2"],
                values=[10.0, 20.0],
                attach_data=True,
            )
        )
        with pikepdf.open(io.BytesIO(doc.render())) as pdf:
            names = list(pdf.attachments.keys())
            assert names == ["chart-1-data.csv"]
            spec = pdf.attachments["chart-1-data.csv"]
            attached = spec.get_file()
            assert attached.mime_type == "text/csv"
            assert attached.read_bytes() == b"category,value\nQ1,10.0\nQ2,20.0\n"
            assert spec.obj.AFRelationship == pikepdf.Name("/Data")
            assert len(pdf.Root.AF) == 1

    def test_chart_attach_data_with_series(self):
        pikepdf = pytest.importorskip("pikepdf")
        doc = Document(title="T")
        doc.add(
            Chart(
                chart_type="line",
                labels=["Q1", "Q2"],
                series=[Series("North", [1.0, 2.0]), Series("South", [2.0, 3.0])],
                attach_data=True,
            )
        )
        with pikepdf.open(io.BytesIO(doc.render())) as pdf:
            spec = pdf.attachments["chart-1-data.csv"]
            csv_bytes = spec.get_file().read_bytes()
            assert csv_bytes == (b"category,North,South\nQ1,1.0,2.0\nQ2,2.0,3.0\n")

    def test_table_attach_data_true_produces_af_with_correct_csv(self):
        pikepdf = pytest.importorskip("pikepdf")
        doc = Document(title="T")
        doc.add(
            Table(
                headers=["Region", "Revenue"],
                rows=[["North", "100"], ["South", "200"]],
                attach_data=True,
            )
        )
        with pikepdf.open(io.BytesIO(doc.render())) as pdf:
            names = list(pdf.attachments.keys())
            assert names == ["table-1-data.csv"]
            spec = pdf.attachments["table-1-data.csv"]
            attached = spec.get_file()
            assert attached.mime_type == "text/csv"
            assert attached.read_bytes() == (b"Region,Revenue\nNorth,100\nSouth,200\n")
            assert len(pdf.Root.AF) == 1

    def test_attach_data_false_by_default_produces_no_attachment(self):
        pikepdf = pytest.importorskip("pikepdf")
        doc = Document(title="T")
        doc.add(Chart(chart_type="bar", labels=["Q1"], values=[1.0]))
        doc.add(Table(headers=["A"], rows=[["1"]]))
        with pikepdf.open(io.BytesIO(doc.render())) as pdf:
            assert list(pdf.attachments.keys()) == []
            assert "/AF" not in pdf.Root

    def test_document_pdfa_opts_in_without_explicit_flag(self):
        pikepdf = pytest.importorskip("pikepdf")
        doc = Document(
            title="T",
            author="A",
            subject="S",
            keywords="",
            pdfa=True,
        )
        doc.add(Chart(chart_type="bar", labels=["Q1"], values=[1.0]))
        with pikepdf.open(io.BytesIO(doc.render())) as pdf:
            assert list(pdf.attachments.keys()) == ["chart-1-data.csv"]

    def test_both_chart_and_table_attachments_coexist(self):
        pikepdf = pytest.importorskip("pikepdf")
        doc = Document(title="T")
        doc.add(Chart(chart_type="bar", labels=["Q1"], values=[1.0], attach_data=True))
        doc.add(Table(headers=["A"], rows=[["1"]], attach_data=True))
        with pikepdf.open(io.BytesIO(doc.render())) as pdf:
            assert sorted(pdf.attachments.keys()) == [
                "chart-1-data.csv",
                "table-1-data.csv",
            ]
            assert len(pdf.Root.AF) == 2


class TestDeterminism:
    def _build(self) -> bytes:
        doc = Document(title="T")
        doc.add(
            Chart(
                chart_type="bar",
                labels=["Q1", "Q2"],
                values=[10.0, 20.0],
                headline="Revenue Growth",
                subtitle="FY2026",
                source_line="Source: Internal",
                patterns=True,
                attach_data=True,
                verify_facts=True,
            )
        )
        doc.add(
            Table(
                headers=["A", "B"],
                rows=[["1", "2"]],
                headline="Table Headline",
                subtitle="Table Subtitle",
                source_line="Source: X",
                attach_data=True,
            )
        )
        return doc.render()

    def test_double_render_identical_bytes(self):
        assert self._build() == self._build()


class TestRegression:
    def test_chart_without_new_fields_still_renders(self):
        doc = Document(title="T")
        doc.add(Chart(chart_type="bar", labels=["Q1", "Q2"], values=[10.0, 20.0]))
        pdf = doc.render()
        assert pdf.startswith(b"%PDF")

    def test_table_without_new_fields_still_renders(self):
        doc = Document(title="T")
        doc.add(Table(headers=["A"], rows=[["1"]]))
        pdf = doc.render()
        assert pdf.startswith(b"%PDF")

    def test_multiseries_chart_regression_unaffected(self):
        doc = Document(title="T")
        doc.add(
            Chart(
                chart_type="scatter",
                labels=["Q1", "Q2"],
                series=[
                    Series("North", [100.0, 150.0]),
                    Series("South", [90.0, 120.0]),
                ],
                x_title="Quarter",
                y_title="Units",
            )
        )
        pdf = doc.render()
        assert pdf.startswith(b"%PDF")
