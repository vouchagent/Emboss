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
    "The file is table-1-data.csv, embedded in this PDF. Acrobat lists it "
    "under View, Show/Hide, Side panels, Attachments; Firefox shows it "
    "under the paperclip icon."
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
    "Every block carries a stable id, so one block can be replaced on its "
    "own. Recover the document from its own PDF, patch the block by id, and "
    "re-render. A paragraph's text or a chart's type and colors change "
    "without touching anything else on the page."
)
doc.code_block(
    "from emboss import Document\n"
    "\n"
    "# 1. Recover the document from its own PDF (embed_spec put it there).\n"
    'doc = Document.from_pdf("report.pdf")\n'
    "\n"
    "# 2. Patch one paragraph by its id -- nothing else moves.\n"
    'doc = doc.patch("exec-summary",\n'
    '                content="Revised Q3 outlook: bookings up 18%.")\n'
    "\n"
    "# 3. Re-type and re-color one chart the same way, by its id.\n"
    'doc = doc.patch("rev-chart",\n'
    '                chart_type="line", colors=["1f8a70", "b7452c"])\n'
    "\n"
    "# 4. Re-render. Only the two edited blocks differ.\n"
    'doc.render(embed_spec=True)',
    language="python",
)
doc.callout(
    "A model is handed one block's id and a one-line diff, not the whole "
    "document. Editing a paragraph in a fifty-page report costs a "
    "paragraph's worth of tokens, not the report's, and every other block "
    "stays byte-identical, so a version diff shows exactly the change and "
    "nothing else.",
    variant="note",
    title="A direct cost saving for LLM workflows",
)

# --------------------------------------------------------------------------
doc.heading("Review that resolves to the exact words", level=1)
doc.paragraph(
    "A reviewer marks up the PDF in whatever they already use, Acrobat, "
    "Preview, or Chrome. Because the document carries a text-position index, "
    "each highlight or strike-out resolves back to the exact node and "
    "character range it covers, not a guess at a region. Other PDFs have no "
    "structure to resolve a comment against."
)
doc.code_block(
    "from emboss.annotations import extract_comments, merge_comments\n"
    "\n"
    "# reviewers mark up v1.pdf in their own reader, then:\n"
    "comments = merge_comments(\n"
    '    extract_comments("v1-legal.pdf"),\n'
    '    extract_comments("v1-finance.pdf"),\n'
    ")",
    language="python",
)
doc.paragraph(
    "A resolved comment names the block and the phrase, not just the page:"
)
doc.code_block(
    '{"id": "c-07", "author": "R. Patel", "type": "strikeout",\n'
    ' "node_id": "sec-risk.p3", "char_range": [120, 143],\n'
    ' "anchor_text": "exposure exceeds $4.2M",\n'
    ' "comment": "Overstates it, use the netted figure",\n'
    ' "resolution": "exact", "status": "open"}',
    language="json",
)
doc.callout(
    "The resolution state is never omitted: exact (one node and a character "
    "range), node (one node), spanning (two or more, reported not split), or "
    "unanchored (no text beneath, surfaced not dropped). A silently "
    "mis-resolved comment is worse than an unresolved one. A model then edits "
    "only the phrase objected to, and a redline proves the change.",
    variant="success",
    title="Reviewer markup becomes structured, node-keyed feedback",
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
doc.paragraph(
    "Beyond the general flowchart, Emboss draws the specialized diagram "
    "types a design document actually needs: cloud architecture, sequence, "
    "and entity-relationship, each from a plain description. The "
    "architecture below is a standard AWS three-tier web stack; the same "
    "service glyphs and nested zones describe an Azure or GCP topology just "
    "by relabeling the nodes."
)
doc.architecture_diagram(
    nodes=[
        {"id": "users", "label": "Users", "service": "user"},
        {"id": "cf", "label": "CloudFront", "service": "cdn"},
        {"id": "s3", "label": "S3 - Assets", "service": "storage"},
        {"id": "alb", "label": "ALB", "service": "loadbalancer", "group": "public"},
        {"id": "ec2", "label": "EC2 - App", "service": "compute", "group": "private"},
        {"id": "lam", "label": "Lambda", "service": "function", "group": "private"},
        {"id": "rds", "label": "RDS - Postgres", "service": "database",
         "group": "private"},
        {"id": "redis", "label": "ElastiCache", "service": "cache",
         "group": "private"},
        {"id": "sqs", "label": "SQS", "service": "queue", "group": "private"},
    ],
    edges=[
        ("users", "cf", "https"),
        ("cf", "s3", "static", "dashed"),
        ("cf", "alb", "dynamic"),
        ("alb", "ec2"),
        ("ec2", "rds", "SQL"),
        ("ec2", "redis", "cache"),
        ("ec2", "sqs", "enqueue", "dashed"),
        ("sqs", "lam", "trigger"),
    ],
    groups=[
        {"id": "public", "label": "Public Subnet", "node_ids": ["alb"]},
        {"id": "private", "label": "Private Subnet",
         "node_ids": ["ec2", "lam", "rds", "redis", "sqs"]},
        {"id": "vpc", "label": "VPC - 10.0.0.0/16",
         "node_ids": ["public", "private"]},
    ],
    caption="AWS three-tier architecture: service glyphs in nested VPC subnets.",
)
doc.sequence_diagram(
    participants=[
        {"id": "u", "label": "Client"},
        {"id": "api", "label": "Payments API"},
        {"id": "ledger", "label": "Ledger"},
    ],
    messages=[
        {"from": "u", "to": "api", "label": "POST /settle", "style": "sync",
         "activate": True},
        {"from": "api", "to": "ledger", "label": "debit", "style": "async"},
        {"from": "ledger", "to": "api", "label": "entry id", "style": "return"},
        {"from": "api", "to": "u", "label": "202 Accepted", "style": "return"},
    ],
    caption="Sequence diagram: lifelines, an activation bar, and typed messages.",
)
doc.er_diagram(
    entities=[
        {"id": "account", "name": "Account", "attributes": [
            {"name": "id", "key": "PK", "type": "uuid"},
            {"name": "balance", "type": "money"},
        ]},
        {"id": "payment", "name": "Payment", "attributes": [
            {"name": "id", "key": "PK", "type": "uuid"},
            {"name": "account_id", "key": "FK", "type": "uuid"},
            {"name": "amount", "type": "money"},
        ]},
    ],
    relationships=[
        {"from": "account", "to": "payment", "label": "makes",
         "from_card": "1", "to_card": "N"},
    ],
    caption="Entity-relationship diagram: keys, types, and cardinality.",
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
    display=True, number=True, label="eq:recovery",
)
doc.paragraph("The bound in @eq:recovery holds for any matrix satisfying the condition below.")
doc.paragraph(
    "Everyday statistics set just as cleanly. The Gaussian density in "
    "@eq:gauss, the model behind most confidence intervals, carries a "
    "fraction, a radical, an exponent, and Greek symbols in one expression."
)
doc.math(
    r"f(x \mid \mu, \sigma^2) = \frac{1}{\sigma\sqrt{2\pi}}\, "
    r"e^{-\frac{(x - \mu)^2}{2\sigma^2}}",
    display=True, number=True, label="eq:gauss",
)
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
doc.heading("Sign without rewriting, and prove what nobody signed", level=1)
doc.paragraph(
    "Content edits produce a new file; approvals append. A signature is added "
    "as an incremental revision that never rewrites the bytes already in the "
    "file, so each signature attests to everything before it. The revision "
    "history makes the audit question answerable: what was added that nobody "
    "signed?"
)
doc.table(
    headers=["Rev", "Kind", "Signer", "Coverage"],
    rows=[
        ["0", "base", "", "covered by rev 1, 2"],
        ["1", "signature", "R. Patel (Legal)", "signed"],
        ["2", "signature", "M. Osei (Finance)", "signed"],
        ["3", "annotations", "", "not covered by any signature"],
    ],
    caption="An incremental-revision history with a signature-coverage check.",
)
doc.callout(
    "That last row is the feature: content appended after a signature that no "
    "signature covers is detected and reported. It falls out of the revision "
    "chain for free, and it is the check auditors actually want.",
    variant="note",
    title="Append-only revisions with signature coverage",
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
    "project is open source under Apache-2.0 with more than 1,800 "
    "automated tests."
)

doc.save("examples/output/09_capabilities_showcase.pdf")
print("wrote 09_capabilities_showcase.pdf")
