"""Executive overview of Emboss, generated from LLM output and rendered by Emboss.

This is the core product loop end to end. The EmbossSpec in
`exec_overview.json` was drafted by Claude Sonnet 5, constrained to a
sheet of facts verified against this codebase, then reviewed claim by
claim for accuracy (one imprecise statement was corrected) before being
committed. Rendering it here is deterministic and needs no API key, so
the document reproduces byte-for-byte.

Every claim about Emboss in the output is verifiable against the source
and its test suite. The comparison speaks only about the general
category of PDF tooling, never a specific product.
"""

from pathlib import Path

from emboss import Document

spec = (Path(__file__).parent / "exec_overview.json").read_text()
doc = Document.from_json(spec, style="brief", title="Emboss for Enterprise")

doc.save("examples/output/08_emboss_overview.pdf")
print("wrote 08_emboss_overview.pdf")
