"""Model Context Protocol server exposing Emboss to an AI assistant.

Configure this server into an MCP client (Claude Desktop, for one) and an
assistant can generate PDFs, and -- the point -- answer questions about them
with certainty. An Emboss PDF made with ``embed_spec=True`` carries its own
EmbossSpec JSON, a per-character text-position index, and any data attached to
its tables and charts. The query tools read that embedded structure, so an
answer about the document comes from the structured source, not from guessing
at rendered pixels.

Run it over stdio:

    python -m emboss.mcp_server        # or the `emboss-mcp` console script

Requires the optional MCP SDK: ``pip install emboss-pdf[mcp]``.
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

__all__ = ["build_server", "main", "dispatch"]

_SERVER_NAME = "emboss"


# -- tool implementations (pure, testable, no MCP types) ---------------------


def _read_pdf(path: str) -> bytes:
    return Path(path).read_bytes()


def _attachments(pdf_bytes: bytes) -> dict:
    """Map every embedded file name to its bytes, via pikepdf."""
    import pikepdf

    out: dict = {}
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        for name in pdf.attachments:
            out[name] = pdf.attachments[name].get_file().read_bytes()
    return out


def tool_render_document(
    spec: dict, output_path: str, embed_spec: bool = True, pdfa: bool = False
) -> dict:
    """Render an EmbossSpec JSON document to a PDF file."""
    from .generate import parse_spec_dict

    doc = parse_spec_dict(spec)
    if pdfa:
        doc.pdfa = True
    pdf = doc.render(embed_spec=embed_spec)
    Path(output_path).write_bytes(pdf)
    return {
        "output_path": output_path,
        "bytes": len(pdf),
        "self_describing": embed_spec,
        "note": (
            "embed_spec=True embedded the spec, layout map, and text map, so "
            "this PDF can be queried and reviewed later"
            if embed_spec
            else "rendered without embedded structure; pass embed_spec to query it later"
        ),
    }


def tool_render_markdown(
    markdown: str, output_path: str, embed_spec: bool = True
) -> dict:
    """Render a Markdown document (with optional YAML front matter) to a PDF."""
    from .spec import Document

    doc = Document.from_markdown(markdown)
    pdf = doc.render(embed_spec=embed_spec)
    Path(output_path).write_bytes(pdf)
    return {
        "output_path": output_path,
        "bytes": len(pdf),
        "self_describing": embed_spec,
    }


def tool_get_document_spec(pdf_path: str) -> dict:
    """Return the exact EmbossSpec JSON embedded in a PDF (the structured source)."""
    files = _attachments(_read_pdf(pdf_path))
    raw = files.get("emboss-spec.json")
    if raw is None:
        return {
            "found": False,
            "reason": "no emboss-spec.json; render with embed_spec=True to embed it",
        }
    return {"found": True, "spec": json.loads(raw.decode("utf-8"))}


def tool_get_document_text(pdf_path: str) -> dict:
    """Return the exact text of each node, from the embedded text-position index."""
    from .textmap import TextIndex

    index = TextIndex.from_pdf(_read_pdf(pdf_path))
    if index is None:
        return {
            "found": False,
            "reason": "no emboss-textmap.json; render with embed_spec=True",
        }
    return {
        "found": True,
        "nodes": {nid: index.node_text(nid) for nid in index.node_ids()},
    }


def tool_list_embedded_data(pdf_path: str) -> dict:
    """List the files embedded in a PDF: spec, maps, and any table/chart CSVs."""
    files = _attachments(_read_pdf(pdf_path))
    return {
        "attachments": [
            {"name": name, "bytes": len(data)} for name, data in sorted(files.items())
        ]
    }


def tool_extract_embedded_data(pdf_path: str, name: str) -> dict:
    """Extract one embedded file (e.g. a table's source CSV) as text."""
    files = _attachments(_read_pdf(pdf_path))
    data = files.get(name)
    if data is None:
        return {"found": False, "available": sorted(files), "reason": f"no {name!r}"}
    try:
        text = data.decode("utf-8")
        return {"found": True, "name": name, "text": text}
    except UnicodeDecodeError:
        return {
            "found": True,
            "name": name,
            "base64": base64.b64encode(data).decode("ascii"),
        }


def tool_extract_review_comments(pdf_path: str) -> dict:
    """Extract reviewer annotations, each resolved to a node and character range."""
    from .annotations import extract_comments, unresolved_count

    comments = extract_comments(_read_pdf(pdf_path))
    return {
        "count": len(comments),
        "unresolved": unresolved_count(comments),
        "comments": [c.to_dict() for c in comments],
    }


def tool_revision_history(pdf_path: str) -> dict:
    """Return the incremental-revision history and signature coverage."""
    from .amend import coverage_report, format_history

    data = _read_pdf(pdf_path)
    report = coverage_report(data)
    return {
        "table": format_history(data),
        "revisions": [
            {
                "index": r.index,
                "kind": r.kind,
                "signer": r.signer,
                "covered": r.covered,
            }
            for r in report.revisions
        ],
        "uncovered_after_signature": [
            i for i in report.uncovered if i not in report.signatures
        ],
    }


def tool_verify_document(pdf_path: str) -> dict:
    """Report a PDF's structural integrity and whether it is accessibility-tagged."""
    from .pdf.verify import verify_pdf

    report = verify_pdf(_read_pdf(pdf_path))
    return {
        "ok": report.ok,
        "pages": report.page_count,
        "tagged": report.has_struct_tree,
        "problems": list(report.problems),
    }


def tool_get_spec_schema() -> dict:
    """Return the EmbossSpec JSON Schema, so a spec can be authored correctly."""
    from .adapters.pydantic_schema import generate_json_schema

    return {"schema": json.loads(generate_json_schema(indent=0))}


#: name -> (handler, description, input JSON schema)
_TOOLS: dict = {
    "render_document": (
        tool_render_document,
        "Render an EmbossSpec JSON document to a PDF. Pass embed_spec=true "
        "(default) to make the PDF self-describing and queryable later.",
        {
            "type": "object",
            "properties": {
                "spec": {"type": "object", "description": "EmbossSpec JSON document"},
                "output_path": {"type": "string"},
                "embed_spec": {"type": "boolean", "default": True},
                "pdfa": {"type": "boolean", "default": False},
            },
            "required": ["spec", "output_path"],
        },
    ),
    "render_markdown": (
        tool_render_markdown,
        "Render a Markdown document (optional YAML front matter) to a PDF.",
        {
            "type": "object",
            "properties": {
                "markdown": {"type": "string"},
                "output_path": {"type": "string"},
                "embed_spec": {"type": "boolean", "default": True},
            },
            "required": ["markdown", "output_path"],
        },
    ),
    "get_document_spec": (
        tool_get_document_spec,
        "Return the exact EmbossSpec JSON embedded in a PDF. Answers about the "
        "document's structure come from this, so they are exact, not inferred.",
        {
            "type": "object",
            "properties": {"pdf_path": {"type": "string"}},
            "required": ["pdf_path"],
        },
    ),
    "get_document_text": (
        tool_get_document_text,
        "Return each node's exact text from the embedded text-position index.",
        {
            "type": "object",
            "properties": {"pdf_path": {"type": "string"}},
            "required": ["pdf_path"],
        },
    ),
    "list_embedded_data": (
        tool_list_embedded_data,
        "List files embedded in a PDF: the spec, layout/text maps, and any CSV "
        "data attached to its tables and charts.",
        {
            "type": "object",
            "properties": {"pdf_path": {"type": "string"}},
            "required": ["pdf_path"],
        },
    ),
    "extract_embedded_data": (
        tool_extract_embedded_data,
        "Extract one embedded file, such as a table's source CSV, as text.",
        {
            "type": "object",
            "properties": {
                "pdf_path": {"type": "string"},
                "name": {"type": "string", "description": "e.g. table-1-data.csv"},
            },
            "required": ["pdf_path", "name"],
        },
    ),
    "extract_review_comments": (
        tool_extract_review_comments,
        "Extract reviewer annotations, each resolved to a node id and character "
        "range with a resolution state (exact/node/spanning/unanchored).",
        {
            "type": "object",
            "properties": {"pdf_path": {"type": "string"}},
            "required": ["pdf_path"],
        },
    ),
    "revision_history": (
        tool_revision_history,
        "Show a PDF's incremental-revision history and flag content appended "
        "after a signature that no signature covers.",
        {
            "type": "object",
            "properties": {"pdf_path": {"type": "string"}},
            "required": ["pdf_path"],
        },
    ),
    "verify_document": (
        tool_verify_document,
        "Report a PDF's structural integrity, page count, and tagging.",
        {
            "type": "object",
            "properties": {"pdf_path": {"type": "string"}},
            "required": ["pdf_path"],
        },
    ),
    "get_spec_schema": (
        tool_get_spec_schema,
        "Return the EmbossSpec JSON Schema for authoring a document spec.",
        {"type": "object", "properties": {}},
    ),
}


def dispatch(name: str, arguments: dict) -> dict:
    """Run a tool by name against its arguments; returns a JSON-ready dict."""
    entry = _TOOLS.get(name)
    if entry is None:
        raise ValueError(f"unknown tool: {name!r}")
    handler = entry[0]
    try:
        return handler(**(arguments or {}))
    except Exception as exc:  # surface a clean error to the assistant
        return {"error": f"{type(exc).__name__}: {exc}"}


# -- MCP wiring --------------------------------------------------------------


def build_server():
    """Build the FastMCP server with every Emboss tool registered.

    Uses the MCP Python SDK's high-level ``FastMCP`` API. Each tool's input
    schema is inferred from its handler's type hints; the tested ``dispatch``
    handlers above are the implementation.
    """
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(_SERVER_NAME)
    for name, (handler, desc, _schema) in _TOOLS.items():
        server.add_tool(handler, name=name, description=desc)
    return server


def main() -> None:
    """Console-script entry point: serve over stdio."""
    build_server().run()


if __name__ == "__main__":
    main()
