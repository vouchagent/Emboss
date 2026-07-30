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


def tool_search_document(pdf_path: str, query: str) -> dict:
    """Find the nodes whose text contains a query, for grounded answers.

    Returns the matching nodes and their exact text. An empty ``matches`` is a
    definite "this document does not contain that", so an assistant can say so
    instead of guessing. Requires an embedded text map (embed_spec=True).
    """
    from .textmap import TextIndex

    index = TextIndex.from_pdf(_read_pdf(pdf_path))
    if index is None:
        return {
            "found": False,
            "reason": "no emboss-textmap.json; render with embed_spec=True",
        }
    needle = (query or "").lower().strip()
    matches = []
    if needle:
        for node_id in index.node_ids():
            text = index.node_text(node_id)
            if needle in text.lower():
                matches.append({"node_id": node_id, "text": text})
    if matches:
        message = (
            f"Found {len(matches)} passage(s) in this document matching "
            f"{query!r}. Answer only from the matched text below."
        )
    else:
        message = (
            f"This document contains no text matching {query!r}. The "
            "information is not present in the document (it may be worded "
            "differently, or simply not covered). Do not answer from outside "
            "the document; tell the user it is not in this document, and "
            "optionally offer what the document does cover via get_document_text."
        )
    return {
        "query": query,
        "match_count": len(matches),
        "matches": matches,
        "message": message,
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
        return {
            "found": False,
            "available": sorted(files),
            "message": f"No embedded file named {name!r} in this PDF. The files "
            "it does carry are listed in 'available'.",
        }
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


def tool_get_provenance(pdf_path: str) -> dict:
    """Return a document's AI provenance: model, provider, and reviewer.

    Reads the generator record from the PDF's embedded reproducibility
    manifest, so the answer to "which model produced this, and was it
    reviewed?" comes from a verifiable field inside the document, not a
    guess.
    """
    from .manifest import read_generator_info

    info = read_generator_info(_read_pdf(pdf_path))
    if info is None:
        return {
            "found": False,
            "reason": "no generator record; render with manifest=True and a "
            "generator to record one",
        }
    return {
        "found": True,
        "model": info.model,
        "provider": info.provider,
        "prompt_sha256": info.prompt_sha256,
        "params": info.params,
        "reviewed_by": info.reviewed_by,
        "reviewed_at": info.reviewed_at,
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


def tool_edit_document_text(
    pdf_path: str, node_id: str, new_text: str, output_path: str
) -> dict:
    """Edit one block's text by node id and re-render, keeping everything else.

    Works because a self-describing Emboss PDF carries its own spec: the
    document is recovered, the one block is patched, and the result is
    re-rendered. Only that block changes; the rest stays byte-identical.
    """
    from .review import _find, _text_field
    from .spec import Document

    doc = Document.from_pdf(pdf_path)
    doc.layout_map()  # assign node ids so the patch resolves
    element = _find(doc, node_id)
    field = _text_field(element)
    if field is None:
        return {
            "error": f"node {node_id} is a {type(element).__name__} with no "
            "editable text field; use patch_node for other fields"
        }
    edited = doc.patch(node_id, **{field: new_text})
    Path(output_path).write_bytes(edited.render(embed_spec=True))
    return {"output_path": output_path, "node_id": node_id, "edited_field": field}


def tool_patch_node(
    pdf_path: str, node_id: str, changes: dict, output_path: str
) -> dict:
    """Patch any fields of one block by node id and re-render (advanced).

    ``changes`` maps element fields to new values, e.g. {"chart_type": "line"}
    for a chart or {"content": "..."} for a paragraph. Everything else stays.
    """
    from .spec import Document

    doc = Document.from_pdf(pdf_path)
    doc.layout_map()
    edited = doc.patch(node_id, **changes)
    Path(output_path).write_bytes(edited.render(embed_spec=True))
    return {"output_path": output_path, "node_id": node_id, "changed": sorted(changes)}


def _embedded_spec(pdf_path: str) -> dict | None:
    files = _attachments(_read_pdf(pdf_path))
    raw = files.get("emboss-spec.json")
    return json.loads(raw.decode("utf-8")) if raw else None


def tool_insert_block(
    pdf_path: str, block: dict, output_path: str, after_node_id: str | None = None
) -> dict:
    """Add a new block to a document and re-render, keeping the rest intact.

    Adds a section (or any block) to the document's own spec, then re-renders.
    Because the spec is declarative, Emboss re-validates, re-paginates, and
    re-tags the whole document, so the structure and accessibility stay
    correct by construction; every unchanged block keeps its stable id.
    ``after_node_id`` places the block after that node, or at the end if None.
    """
    from .generate import parse_spec_dict

    spec = _embedded_spec(pdf_path)
    if spec is None:
        return {"error": "no embedded spec; render with embed_spec=True first"}
    content = spec.setdefault("content", [])
    if after_node_id is None:
        content.append(block)
        position = len(content) - 1
    else:
        idx = next(
            (
                i
                for i, b in enumerate(content)
                if isinstance(b, dict) and b.get("id") == after_node_id
            ),
            None,
        )
        if idx is None:
            return {"error": f"no block with id {after_node_id!r}"}
        content.insert(idx + 1, block)
        position = idx + 1
    doc = parse_spec_dict(spec)
    Path(output_path).write_bytes(doc.render(embed_spec=True))
    return {
        "output_path": output_path,
        "inserted": block.get("type", "block"),
        "position": position,
        "total_blocks": len(content),
    }


def tool_remove_node(pdf_path: str, node_id: str, output_path: str) -> dict:
    """Remove one block by node id and re-render, keeping the rest intact."""
    from .generate import parse_spec_dict

    spec = _embedded_spec(pdf_path)
    if spec is None:
        return {"error": "no embedded spec; render with embed_spec=True first"}
    content = spec.get("content", [])
    kept = [b for b in content if not (isinstance(b, dict) and b.get("id") == node_id)]
    if len(kept) == len(content):
        return {"error": f"no block with id {node_id!r}"}
    spec["content"] = kept
    doc = parse_spec_dict(spec)
    Path(output_path).write_bytes(doc.render(embed_spec=True))
    return {"output_path": output_path, "removed": node_id, "total_blocks": len(kept)}


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
    "search_document": (
        tool_search_document,
        "Find the nodes whose text contains a query. An empty result means the "
        "document does not contain it, so answer from matches only and say "
        "'not in this document' when there are none, rather than guessing.",
        {
            "type": "object",
            "properties": {
                "pdf_path": {"type": "string"},
                "query": {"type": "string"},
            },
            "required": ["pdf_path", "query"],
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
    "get_provenance": (
        tool_get_provenance,
        "Return a document's AI provenance: which model generated it, from "
        "what prompt (hashed, not the raw text), and who reviewed it, read "
        "from the embedded manifest.",
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
    "edit_document_text": (
        tool_edit_document_text,
        "Edit one block's text by node id and re-render. Recovers the document "
        "from its embedded spec, patches just that block, and keeps the rest "
        "byte-identical. Find the node id with get_document_spec first.",
        {
            "type": "object",
            "properties": {
                "pdf_path": {"type": "string"},
                "node_id": {"type": "string"},
                "new_text": {"type": "string"},
                "output_path": {"type": "string"},
            },
            "required": ["pdf_path", "node_id", "new_text", "output_path"],
        },
    ),
    "patch_node": (
        tool_patch_node,
        "Patch any fields of one block by node id and re-render (advanced): "
        "e.g. a chart's type/colors or a paragraph's content. Everything else "
        "stays unchanged.",
        {
            "type": "object",
            "properties": {
                "pdf_path": {"type": "string"},
                "node_id": {"type": "string"},
                "changes": {"type": "object"},
                "output_path": {"type": "string"},
            },
            "required": ["pdf_path", "node_id", "changes", "output_path"],
        },
    ),
    "insert_block": (
        tool_insert_block,
        "Add a new block (section, paragraph, table, chart, ...) to a document "
        "and re-render. The whole document is re-validated, re-paginated, and "
        "re-tagged, so structure and accessibility stay correct; unchanged "
        "blocks keep their ids. Use get_spec_schema for the block shape.",
        {
            "type": "object",
            "properties": {
                "pdf_path": {"type": "string"},
                "block": {"type": "object", "description": "One EmbossSpec block"},
                "after_node_id": {
                    "type": "string",
                    "description": "Insert after this node (end of document if omitted)",
                },
                "output_path": {"type": "string"},
            },
            "required": ["pdf_path", "block", "output_path"],
        },
    ),
    "remove_node": (
        tool_remove_node,
        "Remove one block by node id and re-render; everything else is kept.",
        {
            "type": "object",
            "properties": {
                "pdf_path": {"type": "string"},
                "node_id": {"type": "string"},
                "output_path": {"type": "string"},
            },
            "required": ["pdf_path", "node_id", "output_path"],
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
