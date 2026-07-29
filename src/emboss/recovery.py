"""Spec embedding and recovery: Document <-> JSON, and PDF -> Document.

Three concerns live here, all serving the same goal — a rendered PDF that
carries enough of its own provenance to be reconstructed later:

  document_to_spec_dict / document_from_spec_dict
      A canonical, JSON-serializable view of a Document's content tree,
      round-trippable through ``generate.parse_spec_dict`` (the same
      EmbossSpec vocabulary the pydantic adapter and prompt teach).

  recover_from_attachment
      Reads the ``emboss-spec.json`` /AF attachment a document embedded
      with ``render(embed_spec=True)`` and rebuilds an equivalent Document.

  recover_from_structure_tree
      A degraded fallback used when no attachment is present: walks the
      PDF/UA structure tree and pulls text out of the content streams by
      marked-content id, so headings, paragraphs, tables, and lists come
      back as real elements, in order, with their stable ids, even though
      styling and exact spec fields are lost.

  strip_pdf
      Removes embedded files, provenance-revealing XMP/Info fields, and
      internal structure-tree node ids from already-rendered PDF bytes.
"""

from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path
from typing import Any, Callable

from .bibliography import BibliographyBlock, Citation
from .spec import (
    Abstract,
    Appendix,
    Authors,
    BlockQuote,
    BulletList,
    Callout,
    Chart,
    CodeBlock,
    CoverPage,
    Document,
    DocumentControl,
    Footnote,
    Glossary,
    Heading,
    HorizontalRule,
    Image,
    Index,
    MathBlock,
    NumberedList,
    PageBreak,
    PageSpec,
    Paragraph,
    PullQuote,
    StatTiles,
    SvgBlock,
    Table,
    TableCell,
    TableOfContents,
    TextRun,
)

__all__ = [
    "document_to_spec_dict",
    "document_from_spec_dict",
    "spec_dict_to_json",
    "recover_from_attachment",
    "recover_from_structure_tree",
    "strip_pdf",
]


# -- Document -> spec dict -----------------------------------------------


def _page_spec_dict(page: PageSpec) -> dict:
    return {
        "width": page.width,
        "height": page.height,
        "margin_top": page.margin_top,
        "margin_right": page.margin_right,
        "margin_bottom": page.margin_bottom,
        "margin_left": page.margin_left,
        "columns": page.columns,
        "column_gap": page.column_gap,
        "mirror_margins": page.mirror_margins,
        "landscape": page.landscape,
    }


def _header_footer_dict(hf) -> dict | None:
    if hf is None:
        return None
    return {
        "left": hf.left,
        "center": hf.center,
        "right": hf.right,
        "font_size": hf.font_size,
        "font_family": hf.font_family,
        "color": hf.color,
        "separator_line": hf.separator_line,
        "first_page": hf.first_page,
        "first_page_override": _header_footer_dict(hf.first_page_override),
    }


def _legal_dict(legal) -> dict | None:
    if legal is None:
        return None
    return {
        "watermark": legal.watermark,
        "watermark_opacity": legal.watermark_opacity,
        "line_numbering": legal.line_numbering,
        "bates_prefix": legal.bates_prefix,
        "bates_start": legal.bates_start,
        "bates_digits": legal.bates_digits,
        "bates_position": legal.bates_position,
    }


def _run_dict(run: TextRun) -> dict:
    block: dict = {"text": run.text}
    if run.bold:
        block["bold"] = True
    if run.italic:
        block["italic"] = True
    if run.font_size is not None:
        block["font_size"] = run.font_size
    if run.font_family is not None:
        block["font_family"] = run.font_family
    if run.color is not None:
        block["color"] = run.color
    if run.link is not None:
        block["link"] = run.link
    if run.index_terms:
        block["index_terms"] = list(run.index_terms)
    return block


def _runs_plain_text(runs) -> str:
    return "".join(run.text for run in runs)


def _runs_are_plain(runs) -> bool:
    return all(
        not run.bold
        and not run.italic
        and run.font_size is None
        and run.font_family is None
        and run.color is None
        and run.link is None
        and not run.index_terms
        for run in runs
    )


def _text_or_runs(runs) -> dict:
    if _runs_are_plain(runs):
        return {"text": _runs_plain_text(runs)}
    return {"runs": [_run_dict(run) for run in runs]}


def _list_item_texts(lst) -> list:
    """Flatten a (possibly nested) bullet/numbered list into item strings."""
    texts: list = []
    for runs, sub in lst.flat_items:
        if runs is not None:
            texts.append(_runs_plain_text(runs))
        else:
            texts.extend(_list_item_texts(sub))
    return texts


def _table_cell_value(cell: TableCell):
    text = cell.plain_text
    extra: dict = {}
    if cell.align:
        extra["align"] = cell.align
    if cell.bold:
        extra["bold"] = True
    if cell.background:
        extra["background"] = cell.background
    if not extra:
        return text
    extra["value"] = text
    return extra


def _citation_dict(citation: Citation) -> dict:
    block: dict = {"key": citation.key}
    if citation.authors:
        block["authors"] = list(citation.authors)
    if citation.title:
        block["title"] = citation.title
    if citation.year not in ("", None):
        block["year"] = citation.year
    if citation.journal:
        block["journal"] = citation.journal
    if citation.volume:
        block["volume"] = citation.volume
    if citation.pages:
        block["pages"] = citation.pages
    if citation.publisher:
        block["publisher"] = citation.publisher
    if citation.doi:
        block["doi"] = citation.doi
    if citation.url:
        block["url"] = citation.url
    if citation.entry_type != "article":
        block["entry_type"] = citation.entry_type
    return block


def _heading_block(el: Heading) -> dict:
    block = {"type": "heading", "text": el.text, "level": el.level}
    if el.numbering:
        block["numbering"] = el.numbering
    return block


def _paragraph_block(el: Paragraph) -> dict:
    block: dict = {"type": "paragraph"}
    block.update(_text_or_runs(el.runs))
    return block


def _bullets_block(el: BulletList) -> dict:
    block: dict = {"type": "bullets", "items": _list_item_texts(el)}
    if el.bullet != "•":
        block["bullet"] = el.bullet
    return block


def _numbered_block(el: NumberedList) -> dict:
    block: dict = {"type": "numbered", "items": _list_item_texts(el)}
    if el.start != 1:
        block["start"] = el.start
    return block


def _table_block(el: Table) -> dict:
    # Colspan is not yet part of the canonical vocabulary (table colspan is
    # in-flight elsewhere); a spanned cell round-trips as a plain cell.
    block: dict = {
        "type": "table",
        "headers": [_table_cell_value(c) for c in el.header_cells],
        "rows": [[_table_cell_value(c) for c in row] for row in el.body_rows],
    }
    if el.column_widths:
        block["column_widths"] = list(el.column_widths)
    if el.caption:
        block["caption"] = el.caption
    if el.stripe:
        block["stripe"] = True
    if not el.repeat_header:
        block["repeat_header"] = False
    if el.headline:
        block["headline"] = el.headline
    if el.subtitle:
        block["subtitle"] = el.subtitle
    if el.source_line:
        block["source_line"] = el.source_line
    if el.attach_data:
        block["attach_data"] = True
    if el.verify_totals:
        block["verify_totals"] = True
    return block


def _blockquote_block(el: BlockQuote) -> dict:
    block = {"type": "blockquote", "text": _runs_plain_text(el.runs)}
    if el.attribution:
        block["attribution"] = el.attribution
    return block


def _image_block(el: Image) -> dict:
    block: dict = {"type": "image"}
    if isinstance(el.source, str):
        block["source"] = el.source
    else:
        # ImageSpec.source is a path string; raw bytes have no canonical
        # slot, so they travel as an extra base64 field for callers that
        # want them (parse_spec_dict ignores unknown keys).
        block["source"] = ""
        block["source_b64"] = base64.b64encode(el.source).decode("ascii")
    if el.alt_text:
        block["alt_text"] = el.alt_text
    if el.width is not None:
        block["width"] = el.width
    if el.height is not None:
        block["height"] = el.height
    if el.caption:
        block["caption"] = el.caption
    if el.align != "center":
        block["align"] = el.align
    return block


def _chart_block(el: Chart) -> dict:
    block: dict = {
        "type": "chart",
        "chart_type": el.chart_type,
        "labels": list(el.labels),
    }
    if el.series:
        block["series"] = [
            {"label": s.label, "values": list(s.values)} for s in el.series
        ]
    else:
        block["values"] = list(el.values)
    if el.colors:
        block["colors"] = list(el.colors)
    if el.title:
        block["title"] = el.title
    if el.x_title:
        block["x_title"] = el.x_title
    if el.y_title:
        block["y_title"] = el.y_title
    if not el.legend:
        block["legend"] = False
    if el.width != 400.0:
        block["width"] = el.width
    if el.height != 250.0:
        block["height"] = el.height
    if el.patterns:
        block["patterns"] = True
    if el.headline:
        block["headline"] = el.headline
    if el.subtitle:
        block["subtitle"] = el.subtitle
    if el.source_line:
        block["source_line"] = el.source_line
    if el.verify_facts:
        block["verify_facts"] = True
    if el.attach_data:
        block["attach_data"] = True
    return block


def _footnote_block(el: Footnote) -> dict:
    block = {"type": "footnote", "text": _runs_plain_text(el.runs)}
    if el.marker:
        block["marker"] = el.marker
    return block


def _callout_block(el: Callout) -> dict:
    block = {
        "type": "callout",
        "text": _runs_plain_text(el.runs),
        "variant": el.variant,
    }
    if el.title:
        block["title"] = el.title
    return block


def _code_block(el: CodeBlock) -> dict:
    block: dict = {"type": "code_block", "code": el.code}
    if el.language != "text":
        block["language"] = el.language
    if not el.line_numbers:
        block["line_numbers"] = False
    if el.theme != "dark_modern":
        block["theme"] = el.theme
    if el.start_line != 1:
        block["start_line"] = el.start_line
    if el.highlight_lines:
        block["highlight_lines"] = list(el.highlight_lines)
    if el.caption:
        block["caption"] = el.caption
    return block


def _math_block(el: MathBlock) -> dict:
    block: dict = {"type": "math", "source": el.source}
    if not el.display:
        block["display"] = False
    if el.caption:
        block["caption"] = el.caption
    if el.label:
        block["label"] = el.label
    if el.number:
        block["number"] = True
    if el.tag:
        block["tag"] = el.tag
    return block


def _svg_block(el: SvgBlock) -> dict:
    block: dict = {"type": "svg"}
    if isinstance(el.source, str):
        block["source"] = el.source
    else:
        block["source"] = ""
        block["source_b64"] = base64.b64encode(el.source).decode("ascii")
    if el.width is not None:
        block["width"] = el.width
    if el.height is not None:
        block["height"] = el.height
    if el.caption:
        block["caption"] = el.caption
    if el.label:
        block["label"] = el.label
    if el.alt_text:
        block["alt_text"] = el.alt_text
    if el.align != "center":
        block["align"] = el.align
    return block


def _bibliography_block(el: BibliographyBlock) -> dict:
    block: dict = {
        "type": "bibliography",
        "citations": [_citation_dict(c) for c in el.citations],
    }
    if el.bib_style != "ieee":
        block["bib_style"] = el.bib_style
    if el.title != "References":
        block["title"] = el.title
    if el.heading_level != 2:
        block["heading_level"] = el.heading_level
    return block


def _cover_page_block(el: CoverPage) -> dict:
    block: dict = {"type": "cover_page", "title": el.title}
    if el.subtitle:
        block["subtitle"] = el.subtitle
    if el.authors:
        block["authors"] = [str(a) for a in el.authors]
    if el.date:
        block["date"] = el.date
    if el.kicker:
        block["kicker"] = el.kicker
    return block


def _abstract_block(el: Abstract) -> dict:
    block: dict = {"type": "abstract", "text": el.text}
    if el.keywords:
        block["keywords"] = list(el.keywords)
    return block


def _authors_block(el: Authors) -> dict:
    return {
        "type": "authors",
        "authors": [
            {"name": a.name, "affiliation": a.affiliation, "email": a.email}
            for a in el.author_list
        ],
    }


def _pull_quote_block(el: PullQuote) -> dict:
    block: dict = {"type": "pull_quote", "text": el.text}
    if el.attribution:
        block["attribution"] = el.attribution
    return block


def _stat_tiles_block(el: StatTiles) -> dict:
    stats = []
    for stat in el.stat_list:
        entry = {"label": stat.label, "value": stat.value}
        if stat.delta:
            entry["delta"] = stat.delta
        stats.append(entry)
    return {"type": "stat_tiles", "stats": stats}


def _toc_block(el: TableOfContents) -> dict:
    block: dict = {"type": "toc"}
    if el.title != "Contents":
        block["title"] = el.title
    if el.depth != 3:
        block["depth"] = el.depth
    if el.source != "headings":
        block["source"] = el.source
    return block


def _page_break_block(el: PageBreak) -> dict:
    block: dict = {"type": "page_break"}
    if el.page_style:
        block["page_style"] = el.page_style
    return block


def _rule_block(el: HorizontalRule) -> dict:
    block: dict = {"type": "rule"}
    if el.thickness != 0.5:
        block["thickness"] = el.thickness
    if el.color != "cccccc":
        block["color"] = el.color
    return block


def _appendix_block(el: Appendix) -> dict:
    content = []
    for child in el.content:
        block = _element_to_block(child)
        if block is not None:
            content.append(block)
    return {"type": "appendix", "title": el.title, "content": content}


def _index_block(el: Index) -> dict:
    block: dict = {"type": "index"}
    if el.title != "Index":
        block["title"] = el.title
    return block


def _glossary_block(el: Glossary) -> dict:
    block: dict = {
        "type": "glossary",
        "entries": [
            {"term": e.term, "definition": e.definition} for e in el.entry_list
        ],
    }
    if el.title != "Glossary":
        block["title"] = el.title
    return block


def _document_control_block(el: DocumentControl) -> dict:
    block: dict = {"type": "document_control"}
    for key in (
        "doc_id",
        "title",
        "version",
        "status",
        "effective_date",
        "classification",
        "owner",
    ):
        value = getattr(el, key)
        if value is not None:
            block[key] = value
    if el.approvals:
        block["approvals"] = [
            {
                "name": a.name,
                "role": a.role,
                "date": a.date,
                "statement": a.statement,
            }
            for a in el.approval_list
        ]
    if el.revisions:
        block["revisions"] = [
            {
                "version": r.version,
                "date": r.date,
                "author": r.author,
                "summary": r.summary,
            }
            for r in el.revision_list
        ]
    return block


_BLOCK_SERIALIZERS: dict[type, Callable[[Any], dict]] = {
    Heading: _heading_block,
    Paragraph: _paragraph_block,
    BulletList: _bullets_block,
    NumberedList: _numbered_block,
    Table: _table_block,
    BlockQuote: _blockquote_block,
    Image: _image_block,
    Chart: _chart_block,
    Footnote: _footnote_block,
    Callout: _callout_block,
    CodeBlock: _code_block,
    MathBlock: _math_block,
    BibliographyBlock: _bibliography_block,
    SvgBlock: _svg_block,
    CoverPage: _cover_page_block,
    Abstract: _abstract_block,
    Authors: _authors_block,
    PullQuote: _pull_quote_block,
    StatTiles: _stat_tiles_block,
    TableOfContents: _toc_block,
    PageBreak: _page_break_block,
    HorizontalRule: _rule_block,
    Appendix: _appendix_block,
    Index: _index_block,
    Glossary: _glossary_block,
    DocumentControl: _document_control_block,
}


def _element_to_block(element) -> dict | None:
    serializer = _BLOCK_SERIALIZERS.get(type(element))
    if serializer is None:
        return None
    block = serializer(element)
    node_id = getattr(element, "id", None)
    if node_id:
        block["id"] = node_id
    return block


def document_to_spec_dict(document: Document) -> dict:
    """Serialize a Document's content tree to a canonical EmbossSpec dict.

    The result uses the same type-tag vocabulary as
    ``adapters.pydantic_schema.ContentBlock`` and ``generate._manual_parse``,
    so it round-trips through ``generate.parse_spec_dict`` back into an
    equivalent Document. Branding (``Document.brand``) is deliberately not
    serialized: it is applied programmatically by the integrator, not part
    of the authored content. Key order is insertion order here; callers
    that need a deterministic byte encoding should serialize with
    ``spec_dict_to_json`` (``sort_keys=True``).
    """
    spec: dict[str, Any] = {
        "title": document.title,
        "author": document.author,
        "subject": document.subject,
        "keywords": document.keywords,
        "language": document.language,
        "style": document.style if isinstance(document.style, str) else "corporate",
        "page": _page_spec_dict(document.page),
    }
    if document.page_styles:
        spec["page_styles"] = {
            name: _page_spec_dict(page) for name, page in document.page_styles.items()
        }
    if document.header_text:
        spec["header_text"] = document.header_text
    if document.footer_text:
        spec["footer_text"] = document.footer_text
    if document.header is not None:
        spec["header"] = _header_footer_dict(document.header)
    if document.footer is not None:
        spec["footer"] = _header_footer_dict(document.footer)
    spec["page_numbers"] = document.page_numbers
    spec["page_number_format"] = document.page_number_format
    if document.front_matter_pages:
        spec["front_matter_pages"] = document.front_matter_pages
    spec["tagged"] = document.tagged
    spec["toc"] = document.toc
    if document.legal is not None:
        spec["legal"] = _legal_dict(document.legal)

    content = []
    for element in document.content:
        block = _element_to_block(element)
        if block is not None:
            content.append(block)
    spec["content"] = content
    return spec


def spec_dict_to_json(spec: dict) -> bytes:
    """Encode a spec dict as deterministic, sorted-key UTF-8 JSON bytes."""
    return json.dumps(spec, ensure_ascii=True, sort_keys=True, indent=2).encode("utf-8")


def _restore_ids(document: Document, content_ids: list) -> None:
    for element, node_id in zip(document.content, content_ids):
        if node_id and hasattr(element, "id"):
            element.id = node_id


def document_from_spec_dict(spec: dict) -> Document:
    """Reconstruct a Document from a ``document_to_spec_dict`` payload.

    Uses ``generate.parse_spec_dict`` (pydantic when available, otherwise
    the manual fallback parser), then restores each block's stable node id
    from the payload since neither parse path threads ``id`` through.
    """
    import copy

    from .generate import parse_spec_dict

    data = copy.deepcopy(spec)
    original_title = data.get("title", "") or ""
    if not original_title.strip():
        data["title"] = "Untitled"
    content_ids = [
        block.get("id") if isinstance(block, dict) else None
        for block in data.get("content", [])
    ]
    document = parse_spec_dict(data)
    document.title = original_title
    _restore_ids(document, content_ids)
    return document


# -- attachment-based recovery --------------------------------------------


def _read_pdf_bytes(source) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()
    raise TypeError(f"expected bytes, str, or Path, got {type(source).__name__}")


def recover_from_attachment(source: bytes | str | Path) -> Document | None:
    """Rebuild a Document from an embedded ``emboss-spec.json``, or None.

    Returns None (rather than raising) when pikepdf is unavailable or the
    attachment is absent, so callers can fall back to structure-tree
    recovery.
    """
    try:
        import pikepdf
    except ImportError:
        return None

    data = _read_pdf_bytes(source)
    with pikepdf.open(io.BytesIO(data)) as pdf:
        try:
            filespec = pdf.attachments["emboss-spec.json"]
        except KeyError:
            return None
        raw = filespec.get_file().read_bytes()

    spec = json.loads(raw.decode("utf-8"))
    return document_from_spec_dict(spec)


# -- structure-tree degraded recovery -------------------------------------


class _TagNode:
    """One node of the walked structure tree: a tag, id, mcids, and kids."""

    __slots__ = ("tag", "node_id", "alt_text", "page_index", "mcids", "children")

    def __init__(self, tag: str, node_id, alt_text, page_index, mcids, children):
        self.tag = tag
        self.node_id = node_id
        self.alt_text = alt_text
        self.page_index = page_index
        self.mcids = mcids
        self.children = children


def _strip_id_suffix(node_id: str) -> str:
    """Strip the ``~N`` disambiguation suffix a split block's /ID carries."""
    return node_id.split("~", 1)[0]


def _iter_struct_children(k):
    """Yield the dict-like (StructElem/OBJR/MCR) entries of a /K value."""
    import pikepdf

    if k is None:
        return
    items = list(k) if isinstance(k, pikepdf.Array) else [k]
    for item in items:
        if hasattr(item, "keys"):
            yield item


def _walk_struct_elem(obj, page_index_by_objgen: dict) -> _TagNode:
    tag = str(obj.get("/S", "")).lstrip("/")
    node_id = None
    if "/ID" in obj:
        node_id = _strip_id_suffix(str(obj["/ID"]))
    alt_text = str(obj["/Alt"]) if "/Alt" in obj else None
    page_index = None
    if "/Pg" in obj:
        page_index = page_index_by_objgen.get(obj["/Pg"].objgen)

    mcids: list = []
    children: list = []
    for item in _raw_k_items(obj.get("/K")):
        if hasattr(item, "keys"):
            item_type = str(item.get("/Type", ""))
            if item_type == "/OBJR":
                continue
            if item_type == "/MCR":
                mcid_val = item.get("/MCID")
                if mcid_val is not None:
                    mcids.append(int(mcid_val))
                continue
            children.append(_walk_struct_elem(item, page_index_by_objgen))
        else:
            try:
                mcids.append(int(item))
            except (TypeError, ValueError):
                pass
    return _TagNode(tag, node_id, alt_text, page_index, mcids, children)


def _raw_k_items(k) -> list:
    import pikepdf

    if k is None:
        return []
    if isinstance(k, pikepdf.Array):
        return list(k)
    return [k]


_TO_UNICODE_BFCHAR_RE = re.compile(rb"beginbfchar(.*?)endbfchar", re.DOTALL)
_TO_UNICODE_BFRANGE_RE = re.compile(rb"beginbfrange(.*?)endbfrange", re.DOTALL)
_BFCHAR_ENTRY_RE = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
_BFRANGE_ENTRY_RE = re.compile(
    rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>"
)

#: WinAnsiEncoding codepoints 0x80-0x9F that diverge from Latin-1 (mirrors
#: streams._UNICODE_TO_WINANSI, inverted, for decoding base-14 text back).
_WINANSI_HIGH_TO_UNICODE = {
    0x80: 0x20AC,
    0x82: 0x201A,
    0x83: 0x0192,
    0x84: 0x201E,
    0x85: 0x2026,
    0x86: 0x2020,
    0x87: 0x2021,
    0x88: 0x02C6,
    0x89: 0x2030,
    0x8A: 0x0160,
    0x8B: 0x2039,
    0x8C: 0x0152,
    0x8E: 0x017D,
    0x91: 0x2018,
    0x92: 0x2019,
    0x93: 0x201C,
    0x94: 0x201D,
    0x95: 0x2022,
    0x96: 0x2013,
    0x97: 0x2014,
    0x98: 0x02DC,
    0x99: 0x2122,
    0x9A: 0x0161,
    0x9B: 0x203A,
    0x9C: 0x0153,
    0x9E: 0x017E,
    0x9F: 0x0178,
}


def _hex_to_unicode(hex_str: bytes) -> str:
    raw = bytes.fromhex(hex_str.decode("ascii"))
    return raw.decode("utf-16-be", errors="replace")


def _parse_to_unicode_cmap(data: bytes) -> dict:
    """Parse a /ToUnicode CMap stream into a {code: unicode text} map."""
    mapping: dict = {}
    for block in _TO_UNICODE_BFCHAR_RE.findall(data):
        for src, dst in _BFCHAR_ENTRY_RE.findall(block):
            mapping[int(src, 16)] = _hex_to_unicode(dst)
    for block in _TO_UNICODE_BFRANGE_RE.findall(data):
        for lo, hi, dst in _BFRANGE_ENTRY_RE.findall(block):
            lo_i, hi_i = int(lo, 16), int(hi, 16)
            if len(dst) == 4:
                base = int(dst, 16)
                for code in range(lo_i, hi_i + 1):
                    mapping[code] = chr(base + (code - lo_i))
    return mapping


def _cid_decoder(table: dict) -> Callable[[bytes], str]:
    def decode(raw: bytes) -> str:
        chars = []
        for i in range(0, len(raw) - 1, 2):
            code = (raw[i] << 8) | raw[i + 1]
            text = table.get(code)
            if text:
                chars.append(text)
        return "".join(chars)

    return decode


def _winansi_decoder(raw: bytes) -> str:
    chars = []
    for byte in raw:
        if 0x20 <= byte <= 0x7E:
            chars.append(chr(byte))
        elif byte in _WINANSI_HIGH_TO_UNICODE:
            chars.append(chr(_WINANSI_HIGH_TO_UNICODE[byte]))
        elif 0xA0 <= byte <= 0xFF:
            chars.append(chr(byte))
        elif byte in (0x09, 0x0A, 0x0D):
            chars.append(chr(byte))
    return "".join(chars)


def _font_decoders(page) -> dict:
    """Map each page font resource key to a bytes-decoding function."""
    decoders: dict = {}
    resources = page.get("/Resources")
    if resources is None or "/Font" not in resources:
        return decoders
    font_dict = resources["/Font"]
    for key in font_dict.keys():
        font = font_dict[key]
        subtype = str(font.get("/Subtype", ""))
        clean_key = str(key).lstrip("/")
        if subtype == "/Type0":
            to_unicode = font.get("/ToUnicode")
            table = (
                _parse_to_unicode_cmap(bytes(to_unicode.read_bytes()))
                if to_unicode
                else {}
            )
            decoders[clean_key] = _cid_decoder(table)
        else:
            decoders[clean_key] = _winansi_decoder
    return decoders


def _unescape_pdf_string(raw: bytes) -> bytes:
    """Decode a PDF literal ``(...)`` or hex ``<...>`` string to raw bytes."""
    if raw.startswith(b"<"):
        hex_digits = re.sub(rb"\s+", b"", raw[1:-1])
        if len(hex_digits) % 2:
            hex_digits += b"0"
        return bytes.fromhex(hex_digits.decode("ascii")) if hex_digits else b""

    body = raw[1:-1]
    out = bytearray()
    i = 0
    escape_map = {
        0x6E: 0x0A,  # \n
        0x72: 0x0D,  # \r
        0x74: 0x09,  # \t
        0x62: 0x08,  # \b
        0x66: 0x0C,  # \f
        0x28: 0x28,  # \(
        0x29: 0x29,  # \)
        0x5C: 0x5C,  # \\
    }
    while i < len(body):
        c = body[i]
        if c == 0x5C and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in escape_map:
                out.append(escape_map[nxt])
                i += 2
            elif 0x30 <= nxt <= 0x37:
                j = i + 1
                digits = bytearray()
                while j < len(body) and len(digits) < 3 and 0x30 <= body[j] <= 0x37:
                    digits.append(body[j])
                    j += 1
                out.append(int(bytes(digits), 8) & 0xFF)
                i = j
            elif nxt in (0x0A, 0x0D):
                i += 2
                if nxt == 0x0D and i < len(body) and body[i] == 0x0A:
                    i += 1
            else:
                out.append(nxt)
                i += 2
        else:
            out.append(c)
            i += 1
    return bytes(out)


_CONTENT_TOKEN_RE = re.compile(
    rb"(?P<bdc>/(?P<bdctag>[A-Za-z0-9]+)\s*<<(?P<bdcbody>.*?)>>\s*BDC)"
    rb"|(?P<emc>\bEMC\b)"
    rb"|(?P<tf>/(?P<font>[A-Za-z0-9_.+-]+)\s+[\d.+-]+\s+Tf)"
    rb"|(?P<tj>(?P<tjstr>\((?:[^()\\]|\\.)*\)|<[0-9A-Fa-f\s]*>)\s*Tj)"
    rb"|(?P<tjarr>\[(?P<arrbody>[^\[\]]*)\]\s*TJ)",
    re.DOTALL,
)
_MCID_IN_BODY_RE = re.compile(rb"/MCID\s+(\d+)")
_STRING_IN_ARRAY_RE = re.compile(rb"\((?:[^()\\]|\\.)*\)|<[0-9A-Fa-f\s]*>")


def _extract_text_by_mcid(content: bytes, fonts: dict) -> dict:
    """Scan one page's content stream, returning {mcid: visible text}."""
    stack: list = []
    current_font = None
    parts: dict = {}

    def current_mcid():
        for mcid in reversed(stack):
            if mcid is not None:
                return mcid
        return None

    def append(raw_strings: list) -> None:
        mcid = current_mcid()
        if mcid is None or current_font not in fonts:
            return
        decode = fonts[current_font]
        text = "".join(decode(_unescape_pdf_string(s)) for s in raw_strings)
        if text:
            parts.setdefault(mcid, []).append(text)

    for match in _CONTENT_TOKEN_RE.finditer(content):
        if match.group("bdc"):
            body = match.group("bdcbody")
            mcid_match = _MCID_IN_BODY_RE.search(body)
            stack.append(int(mcid_match.group(1)) if mcid_match else None)
        elif match.group("emc"):
            if stack:
                stack.pop()
        elif match.group("tf"):
            current_font = match.group("font").decode("ascii")
        elif match.group("tj"):
            append([match.group("tjstr")])
        elif match.group("tjarr") is not None:
            append(_STRING_IN_ARRAY_RE.findall(match.group("arrbody")))

    # Each writer text_line() call draws one word (or one run) at its own
    # explicit position rather than relying on a space glyph between
    # Tj/TJ operators, so separate operators within one mcid need a space
    # rejoined between them; a single operator's own segments (kerned TJ
    # splits mid-word) were already concatenated with no gap in `append`.
    return {mcid: " ".join(chunks) for mcid, chunks in parts.items()}


def _page_text_map(page) -> dict:
    contents = page.get("/Contents")
    if contents is None:
        return {}
    content = bytes(contents.read_bytes())
    fonts = _font_decoders(page)
    return _extract_text_by_mcid(content, fonts)


def _aggregate_text(node: _TagNode, text_getter) -> str:
    parts = []
    if node.mcids and node.page_index is not None:
        page_map = text_getter(node.page_index)
        for mcid in node.mcids:
            text = page_map.get(mcid)
            if text:
                parts.append(text)
    for child in node.children:
        if child.tag == "Lbl":
            continue
        sub = _aggregate_text(child, text_getter)
        if sub:
            parts.append(sub)
    return " ".join(parts).strip()


_NUMBERED_LABEL_RE = re.compile(r"[0-9]+\.|[a-zA-Z]+\.")


def _list_from_node(node: _TagNode, text_getter) -> BulletList | NumberedList:
    items: list = []
    labels: list = []
    for li in node.children:
        if li.tag != "LI":
            continue
        label_text = ""
        body_text = ""
        for sub in li.children:
            if sub.tag == "Lbl":
                label_text = _aggregate_text(sub, text_getter)
            elif sub.tag == "LBody":
                body_text = _aggregate_text(sub, text_getter)
        labels.append(label_text)
        items.append(body_text)

    is_numbered = bool(labels) and all(
        not label or _NUMBERED_LABEL_RE.fullmatch(label.strip()) for label in labels
    )
    if is_numbered:
        start = 1
        if labels and labels[0]:
            digits = re.match(r"(\d+)\.", labels[0].strip())
            if digits:
                start = int(digits.group(1))
        return NumberedList(items=items, start=start)
    return BulletList(items=items)


def _table_from_node(node: _TagNode, text_getter) -> Table:
    headers: list = []
    rows: list = []
    caption = None
    for child in node.children:
        if child.tag == "THead":
            for row in child.children:
                if row.tag == "TR":
                    headers = [
                        _aggregate_text(cell, text_getter)
                        for cell in row.children
                        if cell.tag == "TH"
                    ]
        elif child.tag == "TBody":
            for row in child.children:
                if row.tag == "TR":
                    rows.append(
                        [
                            _aggregate_text(cell, text_getter)
                            for cell in row.children
                            if cell.tag == "TD"
                        ]
                    )
        elif child.tag == "Caption" and caption is None:
            text = _aggregate_text(child, text_getter)
            if text:
                caption = text
    return Table(headers=headers, rows=rows, caption=caption)


def _figure_from_node(node: _TagNode, text_getter) -> Image:
    caption = None
    for child in node.children:
        if child.tag == "Caption":
            text = _aggregate_text(child, text_getter)
            if text:
                caption = text
                break
    # The image bytes themselves are never recoverable from a tag tree;
    # only the accessible text (alt text, caption) survives.
    return Image(source="", alt_text=node.alt_text or "", caption=caption)


_HEADING_TAG_RE = re.compile(r"^H([1-6])$")


def _node_to_element(node: _TagNode, text_getter):
    tag = node.tag
    heading_match = _HEADING_TAG_RE.match(tag)
    if heading_match:
        text = _aggregate_text(node, text_getter)
        return Heading(text=text, level=int(heading_match.group(1))) if text else None
    if tag == "P":
        text = _aggregate_text(node, text_getter)
        return Paragraph(content=text) if text else None
    if tag == "BlockQuote":
        text = _aggregate_text(node, text_getter)
        return BlockQuote(content=text) if text else None
    if tag == "Note":
        text = _aggregate_text(node, text_getter)
        return Footnote(content=text) if text else None
    if tag == "Code":
        text = _aggregate_text(node, text_getter)
        return CodeBlock(code=text) if text else None
    if tag == "L":
        lst = _list_from_node(node, text_getter)
        return lst if lst.items else None
    if tag == "Table":
        return _table_from_node(node, text_getter)
    if tag == "Figure":
        return _figure_from_node(node, text_getter)
    if tag == "Div":
        text = _aggregate_text(node, text_getter)
        return Paragraph(content=text) if text else None
    return None


def _flatten_sections(nodes: list) -> list:
    """Inline ``Sect`` (Appendix) wrapper children as top-level blocks.

    Appendix content nests under a /Sect element; the title/heading and
    body it wraps still recover fine as individual blocks once elevated
    to document order, they just lose the appendix grouping itself.
    """
    flat: list = []
    for node in nodes:
        if node.tag == "Sect":
            flat.extend(_flatten_sections(node.children))
        else:
            flat.append(node)
    return flat


def _pdf_title(pdf) -> str:
    info = pdf.docinfo
    if "/Title" in info:
        return str(info["/Title"])
    return ""


def recover_from_structure_tree(source: bytes | str | Path) -> Document:
    """Rebuild a degraded-but-valid Document from the PDF/UA structure tree.

    Used when no ``emboss-spec.json`` attachment is present. Headings,
    paragraphs, tables, lists, block quotes, footnotes, and code blocks
    come back with correct text and document order (and, where the
    original had one, the same node id with any ``~N`` split-continuation
    suffix stripped); everything else — styling, images, charts, math,
    front-matter elements — degrades to plain text or is dropped.
    """
    try:
        import pikepdf
    except ImportError as exc:
        raise ImportError(
            "pikepdf is required for structure-tree recovery.\n"
            "  pip install emboss-pdf[verify]"
        ) from exc

    data = _read_pdf_bytes(source)
    with pikepdf.open(io.BytesIO(data)) as pdf:
        if "/StructTreeRoot" not in pdf.Root:
            raise ValueError(
                "PDF has no /StructTreeRoot; cannot recover a Document from it"
            )
        struct_root = pdf.Root.StructTreeRoot
        pages = list(pdf.pages)
        page_index_by_objgen = {page.objgen: i for i, page in enumerate(pages)}

        top_nodes = [
            _walk_struct_elem(item, page_index_by_objgen)
            for item in _iter_struct_children(struct_root.get("/K"))
        ]
        blocks: list = []
        for node in top_nodes:
            if node.tag == "Document":
                blocks.extend(node.children)
            else:
                blocks.append(node)
        blocks = _flatten_sections(blocks)

        cache: dict = {}

        def text_getter(page_index: int) -> dict:
            if page_index not in cache:
                cache[page_index] = _page_text_map(pages[page_index])
            return cache[page_index]

        content = []
        node_ids: list = []
        for node in blocks:
            element = _node_to_element(node, text_getter)
            if element is None:
                continue
            content.append(element)
            node_ids.append(node.node_id)

        title = _pdf_title(pdf)

    document = Document(title=title, content=content)
    _restore_ids(document, node_ids)
    return document


# -- strip: remove attachments, provenance, and node ids ------------------


def _strip_attachments(pdf) -> None:
    root = pdf.Root
    if "/Names" in root and "/EmbeddedFiles" in root["/Names"]:
        del root["/Names"]["/EmbeddedFiles"]
        if len(list(root["/Names"].keys())) == 0:
            del root["/Names"]
    if "/AF" in root:
        del root["/AF"]
    for page in pdf.pages:
        if "/AF" in page:
            del page["/AF"]
    if "/StructTreeRoot" in root:
        _strip_af_recursive(root.StructTreeRoot)


def _strip_af_recursive(node) -> None:
    if "/AF" in node:
        del node["/AF"]
    for child in _iter_struct_children(node.get("/K")):
        _strip_af_recursive(child)


def _strip_provenance(pdf) -> None:
    info = pdf.docinfo
    for key in ("/Producer", "/Creator"):
        if key in info:
            del info[key]

    if "/Metadata" not in pdf.Root:
        return
    with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
        for key in (
            "xmp:CreatorTool",
            "pdf:Producer",
            "xmpMM:DocumentID",
            "xmpMM:InstanceID",
            "xmpMM:History",
        ):
            if key in meta:
                del meta[key]


def _strip_struct_ids(pdf) -> None:
    if "/StructTreeRoot" not in pdf.Root:
        return
    struct_root = pdf.Root.StructTreeRoot
    if "/IDTree" in struct_root:
        del struct_root["/IDTree"]
    _strip_ids_recursive(struct_root)


def _strip_ids_recursive(node) -> None:
    if "/ID" in node:
        del node["/ID"]
    for child in _iter_struct_children(node.get("/K")):
        _strip_ids_recursive(child)


def strip_pdf(source: bytes | str | Path) -> bytes:
    """Remove embedded files, provenance metadata, and node ids via pikepdf.

    Operates on already-rendered PDF bytes (load, mutate, save) rather than
    re-rendering, so it works on any Emboss-produced PDF. Keeps Title,
    Author, and date fields; drops CreatorTool/Producer and the /IDTree and
    per-element /ID structure-tree attributes. Output is deterministic.
    """
    try:
        import pikepdf
    except ImportError as exc:
        raise ImportError(
            "pikepdf is required for `emboss strip`.\n  pip install emboss-pdf[verify]"
        ) from exc

    data = _read_pdf_bytes(source)
    with pikepdf.open(io.BytesIO(data)) as pdf:
        _strip_attachments(pdf)
        _strip_provenance(pdf)
        _strip_struct_ids(pdf)
        out = io.BytesIO()
        pdf.save(out, deterministic_id=True)
        return out.getvalue()
