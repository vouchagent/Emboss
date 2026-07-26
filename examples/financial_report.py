"""A quarterly financial report: charts of numbers, tables, running heads."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document, PageSpec, Style, TableCell, TextRun


def build() -> Document:
    doc = Document(
        title="Q3 2026 Financial Report",
        author="Finance Team",
        subject="Quarterly results and regional performance",
        style="finance",
        page=PageSpec.letter(),
        header_text="Acme Corporation \u2014 Confidential",
        footer_text="Prepared by the Office of the CFO",
    )

    doc.heading("Executive Summary", level=1)
    doc.paragraph(
        "Revenue for the third quarter reached $4.53 million, an increase of "
        "11.8% over the prior quarter and 24.1% year over year. Growth was "
        "concentrated in the enterprise segment, where annual contract value "
        "expanded materially following the platform release in July."
    )
    doc.paragraph(
        "Operating margin improved to 18.2% from 15.6%, reflecting both "
        "operating leverage and a one-time reduction in cloud infrastructure "
        "costs following the migration completed in August."
    )

    doc.heading("Regional Performance", level=2)
    doc.paragraph(
        "All regions grew sequentially. Asia Pacific posted the strongest "
        "percentage growth from a smaller base."
    )
    doc.table(
        headers=[
            TableCell("Region"),
            TableCell("Q3 2026", align="decimal"),
            TableCell("Q2 2026", align="decimal"),
            TableCell("Change", align="right"),
        ],
        rows=[
            ["North America", "$2,431,000.00", "$2,180,500.00", "+11.5%"],
            ["Europe", "$1,204,300.50", "$1,150,000.00", "+4.7%"],
            ["Asia Pacific", "$892,150.25", "$740,900.00", "+20.4%"],
            [TableCell("Total", bold=True),
             TableCell("$4,527,450.75", bold=True, align="decimal"),
             TableCell("$4,071,400.00", bold=True, align="decimal"),
             TableCell("+11.2%", bold=True, align="right")],
        ],
        stripe=True,
        caption="Table 1: Revenue by region",
    )

    doc.heading("Risk Factors", level=2)
    doc.bullets([
        "Regulatory approval timelines in the European Union remain uncertain",
        "Integration complexity following the Q2 acquisition",
        "Currency exposure in emerging markets, partially hedged",
        [TextRun("Concentration risk: "),
         TextRun("the top three customers represent 31% of revenue",
                 italic=True)],
    ])

    doc.heading("Outlook", level=2)
    doc.paragraph(
        "Management reiterates full-year guidance of $18.5 to $19.2 million "
        "in revenue, with operating margin expected to remain above 17%.",
        style=Style(indent_first=18.0),
    )
    return doc


if __name__ == "__main__":
    document = build()
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "financial_report.pdf")
    document.save(output)
    print(f"wrote {output}")
