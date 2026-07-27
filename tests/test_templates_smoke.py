"""Smoke tests for every public template factory."""

import pytest

from emboss import templates
from emboss.spec import Document
from emboss.templates import slide_deck


def test_slide_deck_renders_valid_pdf():
    """slide_deck must build a Document whose render() yields a PDF."""
    doc = slide_deck(title="X")
    assert isinstance(doc, Document)
    output = doc.render()
    assert output.startswith(b"%PDF")


def test_slide_deck_passes_metadata_and_options():
    """slide_deck forwards title, author, and slide options."""
    doc = slide_deck(title="Quarterly", author="Ana", aspect_ratio="4:3")
    assert doc.title == "Quarterly"
    assert doc.author == "Ana"
    assert doc.page.width == 720.0
    assert doc.page.height == 540.0
    assert doc.render().startswith(b"%PDF")


@pytest.mark.parametrize("name", sorted(templates.__all__))
def test_every_template_renders_valid_pdf(name):
    """Each public template factory builds and renders without raising."""
    factory = getattr(templates, name)
    doc = factory(title="Smoke Test", author="Tester")
    assert isinstance(doc, Document)
    if not doc.content:
        doc.paragraph("Smoke test paragraph.")
    output = doc.render()
    assert output.startswith(b"%PDF")
