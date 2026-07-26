"""A tagged document, plus the determinism and structure guarantees."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document
from emboss.pdf.verify import verify_pdf
from emboss.writer import render_document


def build() -> Document:
    doc = Document(
        title="Accessible Document Example",
        author="Emboss",
        language="en-US",
        style="corporate",
        tagged=True,
    )
    doc.heading("Introduction", level=1)
    doc.paragraph(
        "Every element in this document carries a structure tag. Headings "
        "become /H1 through /H6, paragraphs become /P, and table header "
        "cells declare their scope so a screen reader can announce the "
        "correct column when the reader moves between data cells."
    )
    doc.heading("How Tagging Works", level=2)
    doc.paragraph(
        "Structure is derived from the document model rather than inferred "
        "from font sizes after the fact, so the visible page and the "
        "structure tree cannot disagree."
    )
    doc.table(
        headers=["Element", "Structure Tag"],
        rows=[
            ["Heading(level=1)", "/H1"],
            ["Paragraph", "/P"],
            ["Table header cell", "/TH with /Scope"],
            ["Page number", "/Artifact"],
        ],
    )
    return doc


if __name__ == "__main__":
    document = build()
    result = render_document(document, return_result=True)

    print(f"pages: {result.page_count}")
    print(f"bytes: {len(result.data)}")
    for issue in result.issues:
        print(f"  {issue}")

    print()
    print(verify_pdf(result.data))

    again = document.render()
    print(f"\ndeterministic: {again == result.data}")

    output = Path(sys.argv[1] if len(sys.argv) > 1 else "accessible_report.pdf")
    output.write_bytes(result.data)
    print(f"wrote {output}")
