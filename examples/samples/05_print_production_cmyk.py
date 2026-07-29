"""Print-production output: CMYK color mode, spot color, PDF/A archival."""

from emboss import Document

doc = Document(
    title="Annual Report — Cover Signature",
    author="Design & Print Operations",
    style="journal",
    color_mode="cmyk",
    pdfa=True,
)

doc.heading("2026 Annual Report", level=1)
doc.paragraph(
    "This signature is rendered in CMYK for offset print separation and "
    "wrapped in a PDF/A-2b archival container. Every color below resolves "
    "to true CMYK components rather than an RGB approximation."
)

doc.callout(
    "Corporate blue reproduces as cmyk(0.85, 0.55, 0.0, 0.10) on our "
    "approved press profile, not a device-RGB conversion.",
    variant="note",
    title="Color accuracy",
)

doc.table(
    headers=["Element", "Color specification", "Usage"],
    rows=[
        ["Headline rule", "cmyk(0.85,0.55,0,0.10)", "Section dividers"],
        ["Accent tint", "spot(PANTONE 485 C,0,0.91,0.88,0)", "Callout borders"],
        ["Body text", "cmyk(0,0,0,0.85)", "Rich black avoided for small type"],
    ],
    headline="Approved press palette for the 2026 signature",
    source_line="Source: brand guidelines v4.2, approved 2026-06-01",
)

doc.chart(
    chart_type="bar",
    labels=["Print", "Digital", "Direct Mail"],
    values=[42.0, 38.0, 20.0],
    y_title="Budget allocation (%)",
    patterns=True,
    headline="Channel mix stays print-forward for the annual signature",
    source_line="Source: 2026 marketing operating plan",
)

doc.save("examples/samples/05_print_production_cmyk.pdf")
print("wrote 05_print_production_cmyk.pdf")
