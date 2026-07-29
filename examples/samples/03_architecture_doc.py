"""Technical architecture doc: diagram element, code blocks, wide table on landscape."""

from emboss import Document, PageSpec

doc = Document(
    title="Payments Service — Architecture Overview",
    author="Platform Engineering",
    style="corporate",
    page_styles={"wide": PageSpec.a4(landscape=True)},
)

doc.heading("System Overview", level=1)
doc.paragraph(
    "The payments service decouples authorization from settlement via an "
    "event-sourced ledger. Requests are validated, queued, and settled "
    "asynchronously with idempotency guarantees at each hop."
)

doc.heading("Request Flow", level=1)
doc.diagram(
    nodes=[
        {"id": "gw", "label": "API Gateway", "shape": "rounded"},
        {"id": "auth", "label": "Auth Service", "shape": "box"},
        {"id": "risk", "label": "Risk Check", "shape": "decision"},
        {"id": "ledger", "label": "Ledger DB", "shape": "store"},
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
    caption="Figure 1: Authorization and settlement request path.",
)

doc.heading("Idempotency Key Derivation", level=1)
doc.code_block(
    "def idempotency_key(request: PaymentRequest) -> str:\n"
    "    payload = f\"{request.merchant_id}:{request.amount}:{request.nonce}\"\n"
    "    return hashlib.sha256(payload.encode()).hexdigest()[:32]",
    language="python",
    line_numbers=True,
)

doc.page_break(page_style="wide")
doc.heading("Component Latency Budget", level=1)
doc.table(
    headers=["Component", "p50 (ms)", "p99 (ms)", "Timeout (ms)", "Owner", "On-call rotation", "Runbook"],
    rows=[
        ["API Gateway", "4", "22", "200", "Platform", "platform-oncall", "runbooks/gateway"],
        ["Auth Service", "8", "45", "300", "Identity", "identity-oncall", "runbooks/auth"],
        ["Risk Check", "12", "80", "500", "Risk", "risk-oncall", "runbooks/risk"],
        ["Ledger DB", "3", "18", "150", "Data", "data-oncall", "runbooks/ledger"],
        ["Settlement Queue", "2", "9", "100", "Platform", "platform-oncall", "runbooks/queue"],
    ],
    headline="Every hop budgets under 500ms at p99",
    source_line="Source: latency dashboards, 30-day trailing window",
)

doc.save("examples/samples/03_architecture_doc.pdf")
print("wrote 03_architecture_doc.pdf")
