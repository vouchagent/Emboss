"""The core product loop: raw LLM Markdown output -> structured PDF.

No JSON spec, no manual layout -- this is what an LLM naturally writes.
"""

from emboss import Document

llm_output = """\
---
title: Incident Postmortem — Checkout Latency Spike
author: SRE Team
style: corporate
toc: true
---

# Incident Postmortem: Checkout Latency Spike

## Summary

On September 14, checkout p99 latency rose from **180ms to 4.2s** for
23 minutes, affecting an estimated 6% of checkout attempts. Root cause
was a connection pool exhaustion in the inventory service triggered by
a deploy that removed a timeout.

## Timeline

- **14:02** — Deploy of inventory-service v2.44.0 completes
- **14:09** — Checkout p99 latency alert fires
- **14:14** — On-call engages, identifies connection pool saturation
- **14:22** — Rollback to v2.43.2 initiated
- **14:25** — Latency returns to baseline

## Impact

| Metric | Before | During incident | After |
|---|---|---|---|
| Checkout p99 | 180ms | 4,200ms | 175ms |
| Error rate | 0.02% | 1.8% | 0.02% |
| Affected orders | — | ~340 | — |

> [!WARNING]
> The removed timeout also affects the recommendations service, which
> shares the same client library. A follow-up audit is required.

## Contributing Factors

1. A refactor removed an explicit `connect_timeout` on the shared HTTP client
2. Load testing did not cover the connection-pool-exhaustion scenario
3. The alert threshold was tuned for a slower failure mode and fired late

## Action Items

- [x] Roll back inventory-service to v2.43.2
- [ ] Restore explicit timeouts in the shared client library
- [ ] Add a connection-pool-exhaustion scenario to the load test suite
- [ ] Lower the checkout p99 alert threshold from 1s to 400ms

## Code Reference

```python
# The missing timeout, restored in the follow-up PR
client = HttpClient(
    connect_timeout=2.0,
    read_timeout=5.0,
    pool_maxsize=50,
)
```

Full context available in the linked runbook.[^1]

[^1]: See `runbooks/inventory-service-timeouts.md` for the shared client
    library's timeout configuration guide.
"""

doc = Document.from_markdown(llm_output)
doc.save("examples/output/07_llm_markdown_input.pdf")
print("wrote 07_llm_markdown_input.pdf")
