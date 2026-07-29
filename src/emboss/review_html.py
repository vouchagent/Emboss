"""A self-contained static HTML triage view of extracted review comments.

No server, no CLI: a non-technical owner opens one file and sees every
comment, who made it, what it resolved to, and -- loudly, at the top -- how
many did not resolve to a single node.
"""

from __future__ import annotations

import html

from .annotations import unresolved_count

__all__ = ["review_html"]

_STATE_LABEL = {
    "exact": "exact",
    "node": "whole node",
    "spanning": "spans nodes",
    "unanchored": "unanchored",
}

_STYLE = """
body{font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;color:#1c1917;
background:#fafaf9}
header{padding:24px 32px;border-bottom:1px solid #e7e5e4;background:#fff}
h1{margin:0 0 4px;font-size:20px}
.count{display:inline-block;margin-top:8px;padding:4px 12px;border-radius:999px;
font-weight:600}
.count.clear{background:#dcfce7;color:#166534}
.count.warn{background:#fef3c7;color:#92400e}
table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:10px 14px;border-bottom:1px solid #ececeb;
vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:#78716c;
background:#f5f5f4;position:sticky;top:0}
td.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px}
.badge{display:inline-block;padding:2px 8px;border-radius:6px;font-size:12px;
font-weight:600}
.badge.exact{background:#dcfce7;color:#166534}
.badge.node{background:#e0e7ff;color:#3730a3}
.badge.spanning{background:#fef3c7;color:#92400e}
.badge.unanchored{background:#fee2e2;color:#991b1b}
.anchor{color:#57534e}
main{padding:0 32px 40px}
"""


def _badge(resolution: str) -> str:
    label = _STATE_LABEL.get(resolution, resolution)
    return f'<span class="badge {resolution}">{html.escape(label)}</span>'


def _row(comment) -> str:
    node = comment.node_id or ", ".join(comment.node_ids) or "-"
    anchor = comment.anchor_text or ""
    where = anchor if anchor else "(no text beneath)"
    return (
        "<tr>"
        f"<td class='mono'>{html.escape(comment.id)}</td>"
        f"<td>{html.escape(comment.author or 'unknown')}</td>"
        f"<td>{comment.page + 1}</td>"
        f"<td>{html.escape(comment.type)}</td>"
        f"<td>{_badge(comment.resolution)}</td>"
        f"<td class='mono'>{html.escape(node)}</td>"
        f"<td class='anchor'>{html.escape(where)}</td>"
        f"<td>{html.escape(comment.comment)}</td>"
        "</tr>"
    )


def review_html(comments: list, *, title: str = "Review comments") -> str:
    """Render extracted comments as a single self-contained HTML page."""
    unresolved = unresolved_count(comments)
    total = len(comments)
    if unresolved:
        count_html = (
            f'<span class="count warn">{unresolved} of {total} unresolved '
            "(need attention)</span>"
        )
    else:
        count_html = f'<span class="count clear">all {total} comments resolved</span>'

    rows = "\n".join(_row(c) for c in comments)
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head>"
        "<body><header>"
        f"<h1>{html.escape(title)}</h1>{count_html}</header><main>"
        "<table><thead><tr>"
        "<th>ID</th><th>Reviewer</th><th>Page</th><th>Type</th>"
        "<th>Resolution</th><th>Node</th><th>Anchored text</th><th>Comment</th>"
        "</tr></thead><tbody>"
        f"{rows}"
        "</tbody></table></main></body></html>"
    )
