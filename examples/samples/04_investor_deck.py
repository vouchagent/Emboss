"""Executive presentation deck: themes, stats, chart, code, fit-to-slide."""

from emboss import Chart
from emboss.slides import SlideDeck

deck = SlideDeck("Series C Update", presenter="Founder & CEO", date="Q3 2026", theme="boardroom")

deck.title_slide(subtitle="Growth, efficiency, and the next 18 months")
deck.section_divider("Where We Are")

deck.stat_slide(
    "Key Metrics",
    [
        ("ARR", "$18.6M", "+64%"),
        ("Net Revenue Retention", "132%", "+6pp"),
        ("Gross Margin", "78%", "+2pp"),
        ("Months of Runway", "27", "+5"),
    ],
)

deck.chart_slide(
    "Revenue Growth",
    Chart(
        chart_type="line",
        labels=["Q4 '25", "Q1 '26", "Q2 '26", "Q3 '26"],
        values=[10.4, 13.1, 15.8, 18.6],
        y_title="ARR ($M)",
    ),
    takeaway="Four consecutive quarters of accelerating growth.",
)

deck.section_divider("How We Got Here")

deck.bullet_slide(
    "What Changed",
    [
        "Shipped usage-based pricing in February, expanding average contract value 40%.",
        "Opened the EU region, now 22% of new bookings.",
        "Cut infra cost per customer by half via the platform rewrite.",
    ],
    takeaway="Efficiency gains funded the EU expansion without new capital.",
)

deck.code_slide(
    "The Rewrite in One Function",
    "def route_workload(job: Job) -> Region:\n"
    "    if job.residency_required:\n"
    "        return job.customer.home_region\n"
    "    return least_loaded_region(job.class_)",
    language="python",
)

deck.quote_slide(
    "This is the fastest quarter-over-quarter improvement we have seen from any portfolio company this year.",
    attribution="Lead Investor, Board Observer",
)

deck.closing_slide("Thank you", contact="ceo@example.com")

deck.save("examples/output/04_investor_deck.pdf")
print("wrote 04_investor_deck.pdf")
