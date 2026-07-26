"""Tests for bibliography and citation system."""

import pytest

from emboss import Document
from emboss.bibliography import (
    BibliographyBlock,
    Citation,
    format_bibliography,
    format_citation,
)


def _sample_article():
    return Citation(
        key="einstein1905",
        authors=["Albert Einstein"],
        title="On the Electrodynamics of Moving Bodies",
        year=1905,
        journal="Annalen der Physik",
        volume="17",
        pages="891-921",
    )


def _sample_book():
    return Citation(
        key="knuth1997",
        authors=["Donald E. Knuth"],
        title="The Art of Computer Programming",
        year=1997,
        publisher="Addison-Wesley",
        edition="3rd",
        entry_type="book",
    )


def _sample_inproceedings():
    return Citation(
        key="turing1950",
        authors=["Alan M. Turing"],
        title="Computing Machinery and Intelligence",
        year=1950,
        book_title="Proc. Mind",
        pages="433-460",
        entry_type="inproceedings",
    )


class TestCitation:
    def test_default_entry_type(self):
        c = Citation(key="test")
        assert c.entry_type == "article"

    def test_article_fields(self):
        c = _sample_article()
        assert c.key == "einstein1905"
        assert c.authors == ["Albert Einstein"]
        assert c.year == 1905

    def test_book_fields(self):
        c = _sample_book()
        assert c.entry_type == "book"
        assert c.publisher == "Addison-Wesley"

    def test_optional_fields_none(self):
        c = Citation(key="minimal", title="Test")
        assert c.journal is None
        assert c.doi is None
        assert c.url is None


class TestIEEEFormat:
    def test_article(self):
        text = format_citation(_sample_article(), "ieee", number=1)
        assert text.startswith("[1]")
        assert "A. Einstein" in text
        assert '"On the Electrodynamics of Moving Bodies,"' in text
        assert "Annalen der Physik" in text
        assert "1905" in text

    def test_book(self):
        text = format_citation(_sample_book(), "ieee", number=2)
        assert text.startswith("[2]")
        assert "D. E. Knuth" in text
        assert "The Art of Computer Programming" in text
        assert "Addison-Wesley" in text

    def test_inproceedings(self):
        text = format_citation(_sample_inproceedings(), "ieee", number=3)
        assert text.startswith("[3]")
        assert "A. M. Turing" in text
        assert "in Proc. Mind" in text

    def test_with_doi(self):
        c = _sample_article()
        c.doi = "10.1002/andp.19053221004"
        text = format_citation(c, "ieee", number=1)
        assert "doi: 10.1002/andp.19053221004" in text

    def test_multiple_authors(self):
        c = Citation(
            key="multi",
            authors=["Alice Smith", "Bob Jones", "Carol White"],
            title="Joint Work",
            year=2024,
        )
        text = format_citation(c, "ieee")
        assert "A. Smith" in text
        assert "B. Jones" in text
        assert "and C. White" in text

    def test_two_authors(self):
        c = Citation(
            key="two",
            authors=["Alice Smith", "Bob Jones"],
            title="Pair Work",
            year=2024,
        )
        text = format_citation(c, "ieee")
        assert "A. Smith and B. Jones" in text


class TestAPAFormat:
    def test_article(self):
        text = format_citation(_sample_article(), "apa")
        assert "Einstein, A." in text
        assert "(1905)" in text
        assert "On the Electrodynamics of Moving Bodies" in text

    def test_book(self):
        text = format_citation(_sample_book(), "apa")
        assert "Knuth, D. E." in text
        assert "(1997)" in text
        assert "Addison-Wesley" in text

    def test_no_year(self):
        c = Citation(key="noyear", authors=["Test Author"], title="No Year")
        text = format_citation(c, "apa")
        assert "(n.d.)" in text

    def test_with_doi(self):
        c = _sample_article()
        c.doi = "10.1002/andp.19053221004"
        text = format_citation(c, "apa")
        assert "https://doi.org/10.1002/andp.19053221004" in text


class TestFormatBibliography:
    def test_multiple_entries(self):
        citations = [_sample_article(), _sample_book()]
        entries = format_bibliography(citations, "ieee")
        assert len(entries) == 2
        assert entries[0].startswith("[1]")
        assert entries[1].startswith("[2]")

    def test_dict_input(self):
        entries = format_bibliography([
            {"key": "test", "authors": ["Jane Doe"], "title": "A Study", "year": 2024}
        ])
        assert len(entries) == 1
        assert "J. Doe" in entries[0]

    def test_empty_list(self):
        entries = format_bibliography([])
        assert entries == []

    def test_numbered_style(self):
        entries = format_bibliography([_sample_article()], "numbered")
        assert entries[0].startswith("[1]")


class TestBibliographyBlock:
    def test_structure_tag(self):
        block = BibliographyBlock(citations=[_sample_article()])
        assert block.structure_tag == "Div"

    def test_default_title(self):
        block = BibliographyBlock(citations=[])
        assert block.title == "References"

    def test_custom_style(self):
        block = BibliographyBlock(citations=[], bib_style="apa")
        assert block.bib_style == "apa"


class TestBibliographyRendering:
    def test_renders_valid_pdf(self):
        doc = Document(title="Bibliography Test")
        doc.heading("Introduction", level=1)
        doc.paragraph("Some content with references.")
        doc.bibliography([
            _sample_article(),
            _sample_book(),
        ])
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf
        assert b"%%EOF" in pdf

    def test_renders_with_apa_style(self):
        doc = Document(title="APA Test")
        doc.bibliography(
            [_sample_article()],
            bib_style="apa",
            title="Works Cited",
        )
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_empty_bibliography(self):
        doc = Document(title="Empty Bib")
        doc.bibliography([])
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_no_title_bibliography(self):
        doc = Document(title="No Title Bib")
        doc.bibliography([_sample_article()], title=None)
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_deterministic_output(self):
        def make():
            doc = Document(title="Deterministic Bib")
            doc.bibliography([_sample_article(), _sample_book()])
            return doc.render()
        assert make() == make()

    def test_verification_passes(self):
        from emboss.pdf.verify import verify_pdf

        doc = Document(title="Verified Bib")
        doc.paragraph("Reference content.")
        doc.bibliography([_sample_article()])
        pdf = doc.render()

        report = verify_pdf(pdf)
        assert report.ok, f"Verification failed: {report.problems}"

    def test_document_convenience_method(self):
        doc = Document(title="Convenience")
        doc.bibliography([_sample_article()])
        assert len(doc.content) == 1
        assert isinstance(doc.content[0], BibliographyBlock)


class TestBibliographyHTML:
    def test_html_export(self):
        from emboss.adapters.html_export import to_html

        doc = Document(title="HTML Bib")
        doc.bibliography([_sample_article()], title="References")
        html = to_html(doc)
        assert "<h2>" in html
        assert "References" in html
        assert "bibliography" in html
        assert "Einstein" in html


class TestBibliographyMarkdown:
    def test_markdown_export(self):
        from emboss.adapters.markdown_export import to_markdown

        doc = Document(title="MD Bib")
        doc.bibliography([_sample_article()], title="References")
        md = to_markdown(doc)
        assert "## References" in md
        assert "Einstein" in md
