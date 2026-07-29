"""A court pleading: line numbering, Bates stamps, watermark, justified serif."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document, LegalFeatures, PageSpec


def build() -> Document:
    doc = Document(
        title="Memorandum in Support of Motion",
        author="Counsel for Plaintiff",
        style="legal",
        # Wide left margin leaves room for line numbers.
        page=PageSpec.letter(margin_left=108.0, margin_right=72.0),
        legal=LegalFeatures(
            watermark="CONFIDENTIAL",
            line_numbering=True,
            bates_prefix="ACME-",
            bates_start=1,
        ),
        footer_text="Case No. 26-CV-04821",
    )

    doc.heading("Preliminary Statement", level=1)
    doc.paragraph(
        "The parties hereby agree that the Indemnifying Party shall defend, "
        "indemnify and hold harmless the Indemnified Party from and against "
        "all Claims arising out of or resulting from the performance of this "
        "Agreement, including without limitation any indemnification "
        "obligations set forth in Section 9.2 hereof."
    )
    doc.paragraph(
        "Notwithstanding the foregoing, no such indemnification obligation "
        "shall extend to Claims arising from the gross negligence or willful "
        "misconduct of the Indemnified Party, as determined by a court of "
        "competent jurisdiction in a final and non-appealable judgment."
    )

    doc.heading("Statement of Facts", level=1)
    for index in range(1, 5):
        doc.paragraph(
            f"{index}. On or about the dates set forth in the accompanying "
            "declaration, Defendant undertook a series of representations "
            "concerning the financial condition of the acquired entity, upon "
            "which Plaintiff reasonably relied in executing the Agreement."
        )

    doc.heading("Argument", level=1)
    doc.heading("The Agreement Is Enforceable", level=2)
    doc.paragraph(
        "Under settled principles of contract interpretation, an agreement "
        "supported by consideration and entered into by parties with capacity "
        "is enforceable according to its terms. Plaintiff respectfully submits "
        "that each element is satisfied here."
    )
    return doc


if __name__ == "__main__":
    document = build()
    output = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else Path(__file__).resolve().parent / "output" / "legal_pleading.pdf"
    )
    document.save(output)
    print(f"wrote {output}")
