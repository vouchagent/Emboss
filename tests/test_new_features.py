"""Tests for all new features: numbered lists, nested lists, cross-references,
figure/table numbering, custom headers/footers, SVG embedding, multi-column,
and templates.
"""

from emboss import (
    Document,
    NumberedList,
    BulletList,
    HeaderFooter,
    CrossReferenceIndex,
    NumberingContext,
    PageSpec,
)


class TestNumberedList:
    def test_basic_numbered_list(self):
        doc = Document(title="Test")
        doc.numbered(["First", "Second", "Third"])
        pdf = doc.render()
        assert len(pdf) > 0

    def test_numbered_list_start(self):
        nl = NumberedList(items=["A", "B"], start=5)
        assert nl.marker(0) == "5."
        assert nl.marker(1) == "6."

    def test_numbered_list_structure_tag(self):
        nl = NumberedList(items=["A"])
        assert nl.structure_tag == "L"

    def test_numbered_list_item_runs(self):
        nl = NumberedList(items=["Hello", "World"])
        runs = nl.item_runs
        assert len(runs) == 2
        assert runs[0][0].text == "Hello"

    def test_numbered_list_flat_items(self):
        nl = NumberedList(
            items=[
                "Text item",
                BulletList(items=["Sub-a"]),
            ]
        )
        flat = nl.flat_items
        assert len(flat) == 2
        assert flat[0][0] is not None  # text item
        assert flat[1][1] is not None  # sub-list


class TestNestedLists:
    def test_bullet_with_bullet_sub(self):
        doc = Document(title="Test")
        doc.bullets(
            [
                "Parent 1",
                BulletList(items=["Child A", "Child B"], bullet="-"),
                "Parent 2",
            ]
        )
        pdf = doc.render()
        assert len(pdf) > 0

    def test_bullet_with_numbered_sub(self):
        doc = Document(title="Test")
        doc.bullets(
            [
                "Item one",
                NumberedList(items=["Step 1", "Step 2"]),
                "Item two",
            ]
        )
        pdf = doc.render()
        assert len(pdf) > 0

    def test_numbered_with_bullet_sub(self):
        doc = Document(title="Test")
        doc.numbered(
            [
                "First",
                BulletList(items=["Sub-a", "Sub-b"]),
                "Second",
            ]
        )
        pdf = doc.render()
        assert len(pdf) > 0

    def test_numbered_with_numbered_sub(self):
        doc = Document(title="Test")
        doc.numbered(
            [
                "Outer 1",
                NumberedList(items=["Inner 1", "Inner 2"], start=1),
                "Outer 2",
            ]
        )
        pdf = doc.render()
        assert len(pdf) > 0


class TestCrossReferences:
    def test_heading_anchor(self):
        doc = Document(title="Test")
        doc.heading("Intro", level=1, anchor="sec:intro")
        idx = CrossReferenceIndex(doc)
        assert idx.label("sec:intro") == "Section 1"
        assert idx.number("sec:intro") == 1

    def test_table_label(self):
        doc = Document(title="Test")
        doc.table(
            headers=["A"],
            rows=[["1"]],
            caption="My Table",
            label="tbl:data",
        )
        idx = CrossReferenceIndex(doc)
        assert idx.label("tbl:data") == "Table 1"

    def test_math_label(self):
        doc = Document(title="Test")
        doc.math(r"x^2", caption="Equation", label="eq:x2")
        idx = CrossReferenceIndex(doc)
        assert idx.label("eq:x2") == "Equation 1"

    def test_code_label(self):
        doc = Document(title="Test")
        doc.code_block("x = 1", language="python", caption="Code", label="lst:x")
        idx = CrossReferenceIndex(doc)
        assert idx.label("lst:x") == "Listing 1"

    def test_missing_label(self):
        doc = Document(title="Test")
        idx = CrossReferenceIndex(doc)
        assert idx.label("missing") == "[missing?]"
        assert idx.number("missing") is None

    def test_resolve_text(self):
        doc = Document(title="Test")
        doc.heading("Intro", level=1, anchor="sec:intro")
        doc.math(r"y", caption="Formula", label="eq:y")
        idx = CrossReferenceIndex(doc)
        result = idx.resolve_text("See @sec:intro and @eq:y")
        assert result == "See Section 1 and Equation 1"

    def test_all_entries(self):
        doc = Document(title="Test")
        doc.heading("H1", level=1, anchor="s1")
        doc.heading("H2", level=2, anchor="s2")
        idx = CrossReferenceIndex(doc)
        entries = idx.all_entries()
        assert len(entries) == 2

    def test_sections_filter(self):
        doc = Document(title="Test")
        doc.heading("H1", level=1, anchor="s1")
        doc.table(headers=["A"], rows=[["1"]], caption="T", label="t1")
        idx = CrossReferenceIndex(doc)
        assert len(idx.sections()) == 1
        assert len(idx.tables()) == 1


class TestNumbering:
    def test_counter_increment(self):
        ctx = NumberingContext()
        assert ctx.next("figure") == 1
        assert ctx.next("figure") == 2
        assert ctx.next("table") == 1

    def test_register_and_resolve(self):
        ctx = NumberingContext()
        n = ctx.next("figure")
        ctx.register("fig1", "figure", n)
        assert ctx.resolve("fig1") == "Figure 1"
        assert ctx.resolve("unknown") is None

    def test_heading_numbering(self):
        ctx = NumberingContext()
        assert ctx.next_heading(1) == "1"
        assert ctx.next_heading(1) == "2"
        assert ctx.next_heading(2) == "2.1"
        assert ctx.next_heading(2) == "2.2"
        assert ctx.next_heading(1) == "3"
        assert ctx.next_heading(2) == "3.1"


class TestCustomHeadersFooters:
    def test_structured_header(self):
        doc = Document(
            title="Test",
            header=HeaderFooter(left="Left", center="Center", right="Right"),
        )
        doc.paragraph("Content.")
        pdf = doc.render()
        assert len(pdf) > 0

    def test_structured_footer_with_page_numbers(self):
        doc = Document(
            title="Test",
            footer=HeaderFooter(right="Page {page} of {pages}"),
            page_numbers=False,
        )
        doc.paragraph("Content.")
        pdf = doc.render()
        assert len(pdf) > 0

    def test_separator_lines(self):
        doc = Document(
            title="Test",
            header=HeaderFooter(center="Header", separator_line=True),
            footer=HeaderFooter(center="Footer", separator_line=True),
        )
        doc.paragraph("Content.")
        pdf = doc.render()
        assert len(pdf) > 0

    def test_custom_font(self):
        doc = Document(
            title="Test",
            header=HeaderFooter(
                left="Custom",
                font_size=10.0,
                font_family="Courier",
                color="ff0000",
            ),
        )
        doc.paragraph("Content.")
        pdf = doc.render()
        assert len(pdf) > 0


class TestSvgEmbedding:
    SIMPLE_SVG = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
        '<rect x="10" y="10" width="80" height="80" fill="#3b82f6"/>'
        "</svg>"
    )

    def test_basic_svg(self):
        doc = Document(title="Test")
        doc.svg(self.SIMPLE_SVG)
        pdf = doc.render()
        assert len(pdf) > 0

    def test_svg_with_caption(self):
        doc = Document(title="Test")
        doc.svg(self.SIMPLE_SVG, caption="Blue square")
        pdf = doc.render()
        assert len(pdf) > 0

    def test_svg_shapes(self):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"'
            ' viewBox="0 0 200 100">'
            '<circle cx="50" cy="50" r="30" fill="red"/>'
            '<ellipse cx="120" cy="50" rx="40" ry="20" fill="green"/>'
            '<line x1="10" y1="90" x2="190" y2="90" stroke="black" stroke-width="2"/>'
            '<polygon points="170,20 190,80 150,80" fill="blue"/>'
            "</svg>"
        )
        doc = Document(title="Test")
        doc.svg(svg)
        pdf = doc.render()
        assert len(pdf) > 0

    def test_svg_path(self):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
            '<path d="M 10 10 L 90 10 L 50 90 Z" fill="orange"/>'
            "</svg>"
        )
        doc = Document(title="Test")
        doc.svg(svg)
        pdf = doc.render()
        assert len(pdf) > 0

    def test_svg_bytes(self):
        doc = Document(title="Test")
        doc.svg(self.SIMPLE_SVG.encode("utf-8"))
        pdf = doc.render()
        assert len(pdf) > 0

    def test_svg_crossref(self):
        doc = Document(title="Test")
        doc.svg(self.SIMPLE_SVG, caption="Figure", label="fig:svg1")
        idx = CrossReferenceIndex(doc)
        assert idx.label("fig:svg1") == "Figure 1"


class TestMultiColumn:
    def test_two_columns(self):
        doc = Document(title="Test", page=PageSpec(columns=2))
        for i in range(4):
            doc.paragraph(f"Block {i + 1}")
        pdf = doc.render()
        assert len(pdf) > 0

    def test_three_columns(self):
        doc = Document(title="Test", page=PageSpec(columns=3, column_gap=12.0))
        for i in range(6):
            doc.paragraph(f"Block {i + 1}")
        pdf = doc.render()
        assert len(pdf) > 0


class TestTemplates:
    def test_memo(self):
        from emboss.templates import memo

        doc = memo(title="Weekly Update", author="Eng")
        doc.paragraph("All clear.")
        pdf = doc.render()
        assert len(pdf) > 0

    def test_report(self):
        from emboss.templates import report

        doc = report(title="Q3 Report", author="Finance", toc=True)
        doc.heading("Summary", level=1)
        doc.paragraph("Revenue grew.")
        pdf = doc.render()
        assert len(pdf) > 0

    def test_academic_paper(self):
        from emboss.templates import academic_paper

        doc = academic_paper(title="On Testing", author="Dr. X")
        doc.heading("Abstract", level=1)
        doc.paragraph("Results presented.")
        pdf = doc.render()
        assert len(pdf) > 0

    def test_invoice(self):
        from emboss.templates import invoice

        doc = invoice(title="INV-001", author="Sales")
        doc.table(headers=["Item", "Price"], rows=[["Widget", "$10"]])
        pdf = doc.render()
        assert len(pdf) > 0

    def test_legal_brief(self):
        from emboss.templates import legal_brief

        doc = legal_brief(title="Motion", author="Counsel")
        doc.paragraph("Comes now the defendant.")
        pdf = doc.render()
        assert len(pdf) > 0

    def test_data_sheet(self):
        from emboss.templates import data_sheet

        doc = data_sheet(title="Metrics", author="Ops")
        doc.paragraph("Data here.")
        pdf = doc.render()
        assert len(pdf) > 0

    def test_letter(self):
        from emboss.templates import letter

        doc = letter(title="Notice", author="HR")
        doc.paragraph("Dear team.")
        pdf = doc.render()
        assert len(pdf) > 0


class TestPydanticNewTypes:
    def test_numbered_list_spec(self):
        from emboss.adapters.pydantic_schema import DocumentSpec

        spec = DocumentSpec.model_validate(
            {
                "title": "Test",
                "content": [
                    {"type": "numbered", "items": ["A", "B", "C"]},
                ],
            }
        )
        pdf = spec.render()
        assert len(pdf) > 0

    def test_svg_spec(self):
        from emboss.adapters.pydantic_schema import DocumentSpec

        spec = DocumentSpec.model_validate(
            {
                "title": "Test",
                "content": [
                    {
                        "type": "svg",
                        "source": '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"><rect width="50" height="50" fill="blue"/></svg>',
                    },
                ],
            }
        )
        pdf = spec.render()
        assert len(pdf) > 0

    def test_header_footer_spec(self):
        from emboss.adapters.pydantic_schema import DocumentSpec

        spec = DocumentSpec.model_validate(
            {
                "title": "Test",
                "content": [{"type": "paragraph", "text": "Hello"}],
                "header": {"left": "Title", "right": "{page}"},
                "footer": {"center": "Page {page} of {pages}", "separator_line": True},
            }
        )
        pdf = spec.render()
        assert len(pdf) > 0
