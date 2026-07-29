"""A capabilities showcase framed around what users and enterprises need.

The reason to reach for Emboss is simple: you have content, increasingly
written by a language model, and you need a nice-looking, well-structured
PDF without hand-placing text or fighting pagination. This document is
that output. Every element on the page is rendered live by the engine,
organized by the work people actually do, and it highlights the
capabilities that general-purpose PDF tools do not have because they do
not know which marks were a heading, a table, or a chart.
"""

from emboss import Document, Series

doc = Document(title="Emboss — Capabilities Showcase", author="Emboss", style="corporate")

doc.cover(
    title="Emboss",
    subtitle="Nice-looking, well-structured PDFs from your content",
    date="2026",
    kicker="CAPABILITIES SHOWCASE",
)

doc.table_of_contents()

# --------------------------------------------------------------------------
doc.heading("Why teams use Emboss", level=1)
doc.paragraph(
    "You have content to turn into a document. Increasingly it is written "
    "by a language model, which produces good words but not a designed, "
    "paginated, accessible PDF. The last mile, making it look "
    "professional and hold together across pages, is where most tools "
    "leave you placing text by hand or fighting a layout engine."
)
doc.paragraph(
    "Emboss removes that last mile. You describe the document once, as "
    "structured content or as Markdown, and the engine sets the "
    "typography, builds the structure, and produces a finished PDF. This "
    "page and everything after it were produced that way."
)
doc.stat_tiles([
    {"label": "Input", "value": "Spec, Markdown, LLM"},
    {"label": "Layout", "value": "Automatic"},
    {"label": "Look", "value": "Designed by default"},
    {"label": "Made by", "value": "Emboss itself"},
])

doc.callout(
    "The pitch is not a feature list. It is that a non-designer, or a "
    "language model, can hand Emboss content and get back a document that "
    "looks like a designer made it, every time, identically.",
    variant="note",
    title="The one-line reason",
)

# --------------------------------------------------------------------------
doc.heading("It looks designed, by default", level=1)
doc.paragraph(
    "Good-looking output is not an afterthought here; it is the point. "
    "Paragraphs are set with optimal line breaking, real kerning, and "
    "hyphenation, so text reads like a typeset book rather than a screen "
    "dump. Seven presets cover common document classes, a bundled "
    "professional font set ships with the package, and a single BrandKit "
    "object can carry an organization's palette, fonts, and logo across "
    "every document it produces."
)
doc.bullets([
    "Seven presets: legal, finance, academic, corporate, minimal, journal, brief.",
    "Bundled fonts: a serif, a sans, a monospace, and a math family, so output looks designed with no font setup.",
    "BrandKit applies one brand definition everywhere, with text colors auto-adjusted to stay readable.",
])

# --------------------------------------------------------------------------
doc.heading("The novel part: data that travels with the document", level=1)
doc.paragraph(
    "Because Emboss knows which marks on the page are a table and which "
    "are a chart, it can attach that element's own source data to that "
    "element, inside the PDF. A page-painting tool cannot do this: it "
    "sees ink, not a table. The table below carries its own CSV as a file "
    "attachment. A reader can open it from the PDF and get the exact "
    "numbers, no re-keying, no separate spreadsheet to track down."
)
doc.table(
    headers=["Region", "Bookings", "Growth"],
    rows=[
        ["North America", "12,430.00", "+14%"],
        ["EMEA", "8,910.50", "+21%"],
        ["APAC", "5,204.75", "+9%"],
    ],
    attach_data=True,
    headline="Bookings by region, with the source CSV attached",
    caption="The numbers behind this table are embedded in the file.",
)
doc.paragraph(
    "To view it in Acrobat: View then Show/Hide then Side panels then "
    "Attachments (or click the paperclip icon), then open table-1-data.csv."
)
doc.callout(
    "For an enterprise this closes a real gap. The figure an executive "
    "sees and the data an analyst needs to verify or reuse are the same "
    "artifact, so numbers cannot drift between the report and the "
    "spreadsheet behind it. Charts can carry their series data the same "
    "way.",
    variant="success",
    title="Why this matters to an organization",
)

# --------------------------------------------------------------------------
doc.heading("Change one section, not the whole document", level=1)
doc.paragraph(
    "Because the document is structured content with a stable identifier "
    "on every block, a single section can be replaced on its own. A "
    "person revising a report, or a language model editing it, updates "
    "just the block that changed and re-renders, rather than regenerating "
    "the whole document."
)
doc.bullets([
    "A model emits only the changed section, not the entire document, so "
    "token usage and cost scale with the edit rather than the page count.",
    "Everything else stays byte-identical, so a version diff shows exactly "
    "the intended change and nothing else.",
    "A specific paragraph, table, or figure can be located and updated by "
    "its id, which makes automated and reviewed edits precise.",
])
doc.callout(
    "For iterative, model-driven document workflows this is the "
    "difference between paying to regenerate a fifty-page report on every "
    "small change and paying only for the paragraph that moved.",
    variant="note",
    title="A direct cost saving for LLM workflows",
)

# --------------------------------------------------------------------------
doc.heading("Software and architecture documentation", level=1)
doc.paragraph(
    "Describe a system, do not draw it. Emboss renders syntax-highlighted "
    "code and lays out node-and-edge diagrams automatically, so a design "
    "doc stays in sync with its own description."
)
doc.code_block(
    "async def settle(payment: Payment) -> Receipt:\n"
    "    async with ledger.transaction() as tx:\n"
    "        if not risk.approve(payment):\n"
    "            raise Declined(payment.id)\n"
    "        entry = await tx.debit(payment.account, payment.amount)\n"
    "        return Receipt(entry_id=entry.id, status=\"settled\")",
    language="python",
    line_numbers=True,
)
doc.diagram(
    nodes=[
        {"id": "gw", "label": "API Gateway", "shape": "rounded"},
        {"id": "auth", "label": "Auth", "shape": "box"},
        {"id": "risk", "label": "Risk Check", "shape": "decision"},
        {"id": "ledger", "label": "Ledger", "shape": "store"},
        {"id": "queue", "label": "Settlement Queue", "shape": "box"},
        {"id": "bank", "label": "Bank Rail", "shape": "start_end"},
    ],
    edges=[
        {"src": "gw", "dst": "auth", "label": "validate"},
        {"src": "auth", "dst": "risk"},
        {"src": "risk", "dst": "ledger", "label": "approved"},
        {"src": "risk", "dst": "gw", "label": "declined", "style": "dashed"},
        {"src": "ledger", "dst": "queue"},
        {"src": "queue", "dst": "bank", "label": "T+1"},
    ],
    caption="A workflow described as nodes and edges, laid out automatically.",
)

# --------------------------------------------------------------------------
doc.heading("Research and technical writing", level=1)
doc.paragraph(
    "Mathematics is set from LaTeX or MathML, numbered, and referenceable "
    "from the prose. Blackboard and script letters are real glyphs, not "
    "substitutes."
)
doc.math(
    r"\|\hat{x} - x\|_2 \leq C_1 \frac{\|x - x_k\|_1}{\sqrt{k}} + C_2 \epsilon",
    display=True, number=True, tag="recovery",
)
doc.paragraph("The bound in @eq:recovery holds for any matrix satisfying the condition below.")
doc.math(
    r"A = \begin{pmatrix} 2 & 1 \\ -3 & -1 \end{pmatrix}, \quad "
    r"f(x) = \begin{cases} x^2 & x \geq 0 \\ -x^2 & x < 0 \end{cases}, \quad "
    r"x \in \mathbb{R}",
    display=True,
)

# --------------------------------------------------------------------------
doc.heading("Executive and board briefs", level=1)
doc.paragraph(
    "A brief states the finding, not just the data. Stat tiles, a "
    "headlined chart, and a pull quote carry the message at a glance, and "
    "charts are drawn as vector output that stays crisp in print."
)
doc.stat_tiles([
    {"label": "Revenue", "value": "$24.1M", "delta": "+12%"},
    {"label": "Gross Margin", "value": "61.4%", "delta": "+3.1pp"},
    {"label": "Net Retention", "value": "128%", "delta": "+4pp"},
    {"label": "Runway", "value": "27 mo", "delta": "+5"},
])
doc.chart(
    chart_type="bar",
    labels=["Enterprise", "Mid-Market", "SMB", "Self-Serve"],
    values=[],
    series=[
        Series(label="Q2", values=[8.2, 5.1, 3.4, 2.9]),
        Series(label="Q3", values=[9.9, 5.8, 3.6, 3.1]),
    ],
    y_title="Revenue ($M)",
    legend=True,
    headline="Enterprise led growth, up 21% quarter over quarter",
    source_line="Source: internal billing, as of Sep 30",
)
doc.pull_quote(
    "We crossed the profitability inflection point two quarters ahead of plan.",
    attribution="CFO, Board Letter",
)

# --------------------------------------------------------------------------
doc.heading("Financial and data reports", level=1)
doc.paragraph(
    "Numbers line up on the decimal point and charts keep an honest "
    "baseline. Long reports gain a visible table of contents, lettered "
    "appendices, an index, a glossary, and can mix portrait and landscape "
    "pages for wide tables. Output can be CMYK for print and PDF/A for "
    "archives."
)
doc.table(
    headers=["Metric", "Q3 2026", "Q3 2025", "Change"],
    rows=[
        ["Revenue", "24,113.50", "21,494.20", "+12.2%"],
        ["EBITDA", "8,204.10", "6,912.75", "+18.7%"],
        ["Free cash flow", "3,190.00", "1,240.40", "+157%"],
    ],
    headline="Quarterly results, figures in thousands",
    source_line="Source: audited management accounts",
)

# --------------------------------------------------------------------------
doc.heading("What it saves", level=1)
doc.paragraph(
    "Capabilities matter because of what they cost or save. The table "
    "below reads the features as an operator would."
)
doc.table(
    headers=["What it costs today", "With Emboss"],
    rows=[
        ["A designer or manual formatting for every document", "Designed output automatically, from content"],
        ["Regenerating a whole document to change one line", "Patch one section; pay for the edit, not the page count"],
        ["Re-keying numbers from a report into a spreadsheet", "The source data is attached to its own table"],
        ["Per-seat or per-server license fees", "Open source under Apache-2.0; pip install"],
        ["Manual accessibility remediation before release", "Tagged and conformance-checked by default"],
        ["Re-reviewing output that changed unexpectedly", "Deterministic; only the intended change appears"],
    ],
    headline="Cost and utility at a glance",
)

# --------------------------------------------------------------------------
doc.heading("How Emboss compares", level=1)
doc.paragraph(
    "Emboss is built for turning structured or model-generated content "
    "into a trustworthy, good-looking document. The comparison is at the "
    "level of tool categories. Every Emboss claim is verifiable against "
    "the codebase; the right column describes what general-purpose PDF "
    "tooling typically provides, not any specific product."
)
doc.table(
    headers=["Dimension", "Emboss", "Typical general-purpose PDF tools"],
    rows=[
        ["Designed output with no manual layout", "Yes, from content", "Author places or styles content"],
        ["Input a model can be constrained to", "JSON schema, structured outputs, Markdown", "Imperative code or HTML/CSS"],
        ["Source data attached to its own table or chart", "Yes", "No; the tool does not know it is a table"],
        ["Self-describing, recoverable document", "Yes", "No"],
        ["Document diff to a redlined PDF", "Yes", "No"],
        ["Deterministic byte-identical output", "Yes", "Generally not guaranteed"],
        ["Accessibility tagging", "On by default", "Opt-in or unavailable"],
    ],
    headline="Where Emboss is differentiated",
    source_line="Right column describes the general category, not a specific product",
)
doc.table(
    headers=["Dimension", "Emboss", "Typical general-purpose PDF tools"],
    rows=[
        ["Complex-script shaping (Arabic, Indic)", "Not supported", "Several engines support it"],
        ["Arbitrary HTML and CSS input", "Not supported", "HTML/CSS engines accept it"],
        ["Image formats", "PNG and JPEG", "Often broader"],
        ["Production maturity", "New, released 2026", "Many have 10 to 20 years in production"],
    ],
    headline="Where established tools are ahead",
    source_line="Stated plainly so the picture is complete",
)

# --------------------------------------------------------------------------
doc.heading("Trust, briefly", level=1)
doc.paragraph(
    "One section, because it should be assumed rather than sold. Every "
    "document is accessibility-tagged by default and renders to the same "
    "bytes on every run. It can carry its own source so it can be "
    "reconstructed later, and it supports a redlined diff between "
    "versions for review. Conformance to PDF/UA-1 and PDF/A is checked "
    "against the real veraPDF validator in continuous integration. The "
    "project is open source under Apache-2.0 with more than 1,700 "
    "automated tests."
)

doc.save("examples/output/09_capabilities_showcase.pdf")
print("wrote 09_capabilities_showcase.pdf")
