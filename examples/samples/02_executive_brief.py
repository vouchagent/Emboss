"""Executive brief: cover page, stat tiles, pull quote, hardened charts."""

from emboss import Document, Series

doc = Document(title="Q3 2026 Board Update", author="Finance Team", style="brief")

doc.cover(
    title="Q3 2026 Board Update",
    subtitle="Growth, margin expansion, and the path to profitability",
    authors=["Finance & Strategy"],
    date="October 2026",
    kicker="CONFIDENTIAL — BOARD OF DIRECTORS",
)

doc.heading("Highlights", level=1)
doc.stat_tiles([
    {"label": "Revenue", "value": "$24.1M", "delta": "+12%"},
    {"label": "Gross Margin", "value": "61.4%", "delta": "+3.1pp"},
    {"label": "Net Retention", "value": "128%", "delta": "+4pp"},
    {"label": "Burn Multiple", "value": "0.7x", "delta": "-0.2x"},
])

doc.pull_quote(
    "We crossed the profitability inflection point two quarters ahead of plan.",
    attribution="CFO, Board Letter",
)

doc.heading("Revenue by Segment", level=1)
doc.chart(
    chart_type="bar",
    labels=["Enterprise", "Mid-Market", "SMB", "Self-Serve"],
    values=[],
    series=[
        Series(label="Q2 2026", values=[8.2, 5.1, 3.4, 2.9]),
        Series(label="Q3 2026", values=[9.9, 5.8, 3.6, 3.1]),
    ],
    y_title="Revenue ($M)",
    legend=True,
    headline="Enterprise led growth, up 21% quarter over quarter",
    source_line="Source: internal billing system, as of Sep 30 2026",
)

doc.callout(
    "Enterprise ACV grew 21% QoQ, driven by the July platform release and "
    "two multi-year renewals in EMEA.",
    variant="note",
    title="Why it matters",
)

doc.heading("Outlook", level=1)
doc.bullets([
    "Reiterating full-year guidance of $98-102M revenue.",
    "Targeting adjusted EBITDA breakeven in Q1 2027.",
    "Headcount growth capped at 8% through year-end.",
])

doc.save("examples/samples/02_executive_brief.pdf")
print("wrote 02_executive_brief.pdf")
