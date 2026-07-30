"""The render pipeline.

    Document -> validate -> measure -> paginate -> render -> tag -> bytes

Every stage after validation is deterministic: no timestamps, no random
identifiers, no iteration over unordered collections. The same document
renders to the same bytes on any machine, which is what makes output
hash-verifiable for filings and diffable in CI.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field, replace

from .constraints import ConstraintValidator
from .crossref import CrossReferenceIndex
from .numbering import AppendixNumberingContext, NumberingContext
from .layout.engine import LayoutEngine, PlacedBlock, annotation_sizes
from .nodeid import assign_node_ids, round_bbox
from .pdf.assembler import PDFAssembler
from .pdf.attachments import (
    FileAttachment,
    af_array,
    build_embedded_file,
    build_names_tree,
)
from .pdf.fonts import build_font_resource
from .pdf.objects import PdfArray, PdfDict, PdfName, PdfRef, PdfStream
from .pdf.streams import ContentStream
from .pdf.tags import StructureElement, StructureTreeBuilder
from .spec import (
    Abstract,
    Appendix,
    Authors,
    BibliographyBlock,
    BlockQuote,
    BulletList,
    Callout,
    Chart,
    CheckboxField,
    CodeBlock,
    CoverPage,
    Document,
    DocumentControl,
    DropdownField,
    Footnote,
    Glossary,
    Heading,
    HorizontalRule,
    Image,
    Index,
    MathBlock,
    NumberedList,
    PageBreak,
    Paragraph,
    PullQuote,
    StatTiles,
    SvgBlock,
    Table,
    TableOfContents,
    TextField,
)
from .styles import Style
from .typography.hyphenation import Hyphenator

__all__ = ["render_document", "RenderResult", "Renderer", "roman"]

_ROMAN_NUMERALS = (
    (1000, "m"),
    (900, "cm"),
    (500, "d"),
    (400, "cd"),
    (100, "c"),
    (90, "xc"),
    (50, "l"),
    (40, "xl"),
    (10, "x"),
    (9, "ix"),
    (5, "v"),
    (4, "iv"),
    (1, "i"),
)


_CAPTION_LABEL_RE = re.compile(
    r"^\s*(figure|table|equation|listing|chart|diagram|exhibit|fig)\b\s*[\dA-Za-z.]*\s*[:.\-–—]",
    re.IGNORECASE,
)


def roman(value: int, upper: bool = False) -> str:
    """Format a positive integer as a roman numeral, lowercase by default."""
    if value <= 0:
        return str(value)
    parts = []
    for magnitude, glyph in _ROMAN_NUMERALS:
        while value >= magnitude:
            parts.append(glyph)
            value -= magnitude
    text = "".join(parts)
    return text.upper() if upper else text


@dataclass
class RenderResult:
    """Rendered bytes plus what happened along the way."""

    data: bytes
    page_count: int
    issues: list = field(default_factory=list)
    layout_map: dict = field(default_factory=dict)
    text_index: dict = field(default_factory=dict)

    def __bytes__(self) -> bytes:
        return self.data


# Chart/table annotation colors: headline uses the body text color at bold
# weight; subtitle and source_line step down in emphasis and size.
_SUBTITLE_COLOR = "44403c"
_SOURCE_LINE_COLOR = "78716c"


def _csv_bytes(rows: list) -> bytes:
    """Encode rows of strings as UTF-8 CSV with deterministic line endings."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def render_document(
    document: Document,
    *,
    strict: bool = False,
    return_result: bool = False,
    embed_files: list | None = None,
):
    """Render a document to PDF bytes.

    ``embed_files`` are ``FileAttachment``s embedded at the document level
    (not tied to a specific structure element) — used by
    ``Document.render(embed_spec=True)`` to attach the EmbossSpec JSON,
    layout map, and Markdown twin.
    """
    renderer = Renderer(document, strict=strict, embed_files=embed_files)
    result = renderer.run()
    return result if return_result else result.data


class Renderer:
    """Owns one render pass over one document."""

    def __init__(
        self,
        document: Document,
        strict: bool = False,
        embed_files: list | None = None,
    ) -> None:
        self.fonts = document.fonts
        if document.pdfa or document.pdfx:
            self.fonts.enable_pdfa_embedding()
        self.validator = ConstraintValidator(fonts=self.fonts, strict=strict)
        self.source = document
        self.strict = strict
        # (page_index, [x0, y0, x1, y1], url, parent_element) in render order
        self._link_records: list = []
        # anchor name -> (page_ref, y); populated by cross-referencing later
        self._anchor_map: dict = {}
        # id(element) -> anchor key, filled by the resolve pass
        self._element_keys: dict = {}
        # spot color name -> SpotColor, in first-use order across pages
        self._used_spots: dict = {}
        # page index -> running section title for the {section} token
        self._section_titles: list = []
        # page index -> {gstate name -> {ca, CA}} recorded by SVG rendering
        self._svg_gstates_by_page: dict = {}
        # SVG text resource key -> base-14 family name
        self._svg_fonts: dict = {}
        # node id -> list of {page, x0, y0, x1, y1} placements
        self._layout_map: dict = {}
        # node id -> list of {page, char_start, char_end, x0,y0,x1,y1} text
        # spans, in render order; the basis for resolving a highlight rect to
        # a character range within a node (the text-position index).
        self._text_index: dict = {}
        # (FileAttachment, StructureElement | None) pairs awaiting embedding;
        # a None target is a document-level attachment (e.g. embed_spec=True).
        self._pending_attachments: list = [(fa, None) for fa in (embed_files or [])]
        # id(element) of chart/table elements already fully drawn once,
        # so a split table's headline/attachment fire only on its first page
        self._chart_table_seen: set = set()
        self._chart_attach_count = 0
        self._table_attach_count = 0
        # (page_index, [x0, y0, x1, y1], element, StructureElement) per
        # placed text/checkbox/dropdown field, in render order; consumed by
        # `_build_form_field_widgets` once page refs exist.
        self._formfield_records: list = []
        # AcroForm field/widget refs built from `_formfield_records`.
        self._form_field_refs: list = []
        # next unused /StructParents key for annotations (links, then
        # fields), continued across both so no page/annotation key collides.
        self._struct_parent_next = 0

    def run(self) -> RenderResult:
        validation = self.validator.validate(self.source).raise_if_failed()
        document = validation.document
        sheet = document.stylesheet

        hyphenator = Hyphenator(language=document.language)
        engine = LayoutEngine(self.fonts, sheet, hyphenator=hyphenator)

        content = list(document.content)
        content = self._expand_appendices(content)
        content = self._expand_document_control(content)
        content = self._resolve_references(document, content)
        content = self._link_glossary_terms(content)
        content = self._prepend_title_block(document, sheet, content)
        self._prepare_footnotes(sheet, content)
        # Stable ids are assigned on the validator's deep copy, before
        # measurement, so the tag tree and layout map can key off them.
        assign_node_ids(content)

        width = document.page.content_width
        toc_indices = [
            i for i, el in enumerate(content) if isinstance(el, TableOfContents)
        ]
        index_indices = [i for i, el in enumerate(content) if isinstance(el, Index)]
        if toc_indices or index_indices:
            pages = self._paginate_with_toc(
                engine, document, content, width, toc_indices, index_indices
            )
        else:
            pages = self._paginate_sections(engine, document, content)
        self._section_titles = self._collect_section_titles(document, pages)

        assembler = PDFAssembler()
        data = self._assemble(assembler, document, sheet, pages)

        issues = list(validation.issues)
        issues.extend(engine.warnings)
        return RenderResult(
            data=data,
            page_count=len(pages),
            issues=issues,
            layout_map=self._layout_map,
            text_index=self._text_index,
        )

    # -- appendices --

    @staticmethod
    def _expand_appendices(content: list) -> list:
        """Flatten `Appendix` blocks into a lettered heading plus content.

        Headings inside get flat `A.1`, `A.2` prefixes baked into their
        text (matching how `number_sections` bakes numeric prefixes), so
        both the visible TOC and PDF bookmarks pick them up unchanged.
        Expanded headings are marked so a later `number_sections` pass
        does not also number them.
        """
        if not any(isinstance(el, Appendix) for el in content):
            return content
        out: list = []
        numbering = AppendixNumberingContext()
        for element in content:
            if not isinstance(element, Appendix):
                out.append(element)
                continue
            letter = numbering.next_appendix()
            title_text = (
                f"Appendix {letter}: {element.title}"
                if element.title
                else (f"Appendix {letter}")
            )
            title_heading = Heading(
                text=title_text, level=1, style=element.style, id=element.id
            )
            title_heading._is_appendix = True
            out.append(title_heading)
            for child in element.content:
                if isinstance(child, Heading):
                    prefix = numbering.next_heading(child.level)
                    child = replace(child, text=f"{prefix} {child.text}")
                child._is_appendix = True
                out.append(child)
        return out

    # -- controlled documents --

    @staticmethod
    def _expand_document_control(content: list) -> list:
        """Flatten `DocumentControl` blocks into label paragraphs and tables.

        The metadata grid and the approvals/revision tables become real
        `Table` blocks, so pagination, /Table and /TH tagging, and styling
        come from the existing table machinery unchanged.
        """
        if not any(isinstance(el, DocumentControl) for el in content):
            return content
        out: list = []
        for element in content:
            if isinstance(element, DocumentControl):
                out.extend(element.to_blocks())
            else:
                out.append(element)
        return out

    # -- glossary auto-linking --

    def _link_glossary_terms(self, content: list) -> list:
        """Register a glossary anchor and link each term's first occurrence.

        Body paragraphs are scanned in document order for exact,
        word-bounded, case-sensitive matches of each glossary term; only
        the first document-wide occurrence of a term is linked, via the
        same `#anchor` internal-link mechanism `@key` cross-references use.
        """
        glossaries = [el for el in content if isinstance(el, Glossary)]
        for gi, glossary in enumerate(glossaries):
            anchor = f"glossary-{gi}"
            self._element_keys[id(glossary)] = anchor
            terms = sorted(
                {e.term for e in glossary.entry_list if e.term},
                key=len,
                reverse=True,
            )
            if not terms:
                continue
            pattern = re.compile("|".join(rf"\b{re.escape(t)}\b" for t in terms))
            linked: set = set()
            for element in content:
                if element is glossary or not isinstance(element, Paragraph):
                    continue
                resolved = self._link_terms_in_runs(
                    element.runs, pattern, linked, anchor
                )
                if resolved is not None:
                    element.runs = resolved
        return content

    @staticmethod
    def _link_terms_in_runs(
        runs: list, pattern, linked: set, anchor: str
    ) -> list | None:
        """Split runs so each unlinked term's first match becomes a link."""
        changed = False
        out: list = []
        for run in runs:
            if run.link or not run.text:
                out.append(run)
                continue
            pieces: list = []
            cursor = 0
            any_new = False
            for match in pattern.finditer(run.text):
                term = match.group(0)
                if match.start() > cursor:
                    pieces.append((run.text[cursor : match.start()], None))
                if term not in linked:
                    linked.add(term)
                    pieces.append((term, f"#{anchor}"))
                    any_new = True
                else:
                    pieces.append((term, None))
                cursor = match.end()
            if not any_new:
                out.append(run)
                continue
            changed = True
            if cursor < len(run.text):
                pieces.append((run.text[cursor:], None))
            for text, link in pieces:
                out.append(
                    replace(run, text=text, link=link)
                    if link
                    else replace(run, text=text)
                )
        return out if changed else None

    @staticmethod
    def _prepend_title_block(document, sheet, content: list) -> list:
        """Insert a title heading and author line before the first content."""
        if not document.title:
            return content
        if content and isinstance(content[0], CoverPage):
            return content
        first_is_heading = content and isinstance(content[0], Heading)
        if first_is_heading and content[0].text == document.title:
            return content
        title_style = Style(
            font_family=sheet.h1.font_family or "Helvetica",
            font_size=(sheet.h1.font_size or 16.0) * 1.35,
            bold=True,
            align="center",
            color=sheet.h1.color or "111111",
            space_before=24.0,
            space_after=8.0,
        )
        prefix = [Heading(document.title, level=1, style=title_style)]
        if document.author:
            author_style = Style(
                align="center",
                space_after=20.0,
            )
            prefix.append(Paragraph(document.author, style=author_style))
        return prefix + content

    # -- footnotes --

    FOOTNOTE_REF_SIZE = 0.65
    FOOTNOTE_REF_RISE = 0.33

    def _prepare_footnotes(self, sheet, content: list) -> None:
        """Assign sequential markers and superscript in-text reference marks."""
        notes = [el for el in content if isinstance(el, Footnote)]
        if not notes:
            return
        counter = 0
        for note in notes:
            if not note.marker:
                counter += 1
                note.marker = str(counter)
        tokens = sorted(
            {f"[{note.marker}]" for note in notes}, key=lambda t: (-len(t), t)
        )
        pattern = re.compile("|".join(re.escape(token) for token in tokens))
        for element in content:
            if not isinstance(element, Paragraph):
                continue
            style = sheet.resolved(sheet.body, element.style)
            base_size = style.require("font_size")
            resolved = self._superscript_marks(element.runs, pattern, base_size)
            if resolved is not None:
                element.runs = resolved

    def _superscript_marks(self, runs: list, pattern, base_size: float) -> list | None:
        """Split runs so [marker] tokens become raised small runs, or None."""
        changed = False
        out: list = []
        for run in runs:
            if run.link or "[" not in run.text:
                out.append(run)
                continue
            pieces: list = []
            cursor = 0
            for match in pattern.finditer(run.text):
                if match.start() > cursor:
                    pieces.append((run.text[cursor : match.start()], False))
                pieces.append((match.group(0), True))
                cursor = match.end()
            if cursor == 0:
                out.append(run)
                continue
            changed = True
            if cursor < len(run.text):
                pieces.append((run.text[cursor:], False))
            size = run.font_size or base_size
            for text, is_mark in pieces:
                if is_mark:
                    mark = replace(
                        run, text=text, font_size=size * self.FOOTNOTE_REF_SIZE
                    )
                    mark.baseline_rise = size * self.FOOTNOTE_REF_RISE
                    out.append(mark)
                else:
                    out.append(replace(run, text=text))
        return out if changed else None

    # -- paged-media helpers --

    @staticmethod
    def _collect_section_titles(document, pages) -> list:
        """Map each page to its running section title for the {section} token."""
        current = document.title or ""
        titles = []
        for page in pages:
            for placed in page.blocks:
                element = placed.block.element
                if isinstance(element, Heading) and element.level <= 2:
                    prefix = f"{element.numbering} " if element.numbering else ""
                    current = prefix + element.text
            titles.append(current)
        return titles

    @staticmethod
    def _is_mirrored(document, page_index: int) -> bool:
        """True on verso pages (PDF page 2, 4, ...) of a mirrored document."""
        mirror = bool(getattr(document.page, "mirror_margins", False))
        return mirror and page_index % 2 == 1

    @staticmethod
    def _front_matter_count(document, total: int) -> int:
        """Clamp front_matter_pages to the actual page count."""
        front = int(getattr(document, "front_matter_pages", 0) or 0)
        return min(max(front, 0), total)

    def _page_number_labels(self, document, page_index: int, total: int) -> tuple:
        """Return ({page}, {pages}) labels for this page's numbering sequence."""
        fmt = getattr(document, "page_number_format", "arabic")
        front = self._front_matter_count(document, total)
        upper = fmt == "ROMAN"
        if page_index < front:
            return roman(page_index + 1, upper=upper), roman(front, upper=upper)

        def _fmt(n: int) -> str:
            return roman(n, upper=upper) if fmt in ("roman", "ROMAN") else str(n)

        return _fmt(page_index - front + 1), _fmt(total - front)

    def _page_labels_dict(self, document, total: int):
        """Build a /PageLabels tree matching the visible numbering, or None."""
        fmt = getattr(document, "page_number_format", "arabic")
        front = self._front_matter_count(document, total)
        if fmt == "arabic" and front == 0:
            return None
        body_style = {"arabic": "D", "roman": "r", "ROMAN": "R"}[fmt]

        def _range(style: str) -> PdfDict:
            entry = PdfDict()
            entry["S"] = PdfName(style)
            return entry

        nums: list = []
        if front:
            nums.extend([0, _range("R" if fmt == "ROMAN" else "r")])
            if front < total:
                nums.extend([front, _range(body_style)])
        else:
            nums.extend([0, _range(body_style)])
        labels = PdfDict()
        labels["Nums"] = PdfArray(nums)
        return labels

    @staticmethod
    def _effective_hf(hf, page_index: int, mirrored: bool):
        """Resolve first-page override/suppression and mirror slot swapping."""
        if hf is None:
            return None
        if page_index == 0:
            override = getattr(hf, "first_page_override", None)
            if override is not None:
                hf = override
            elif not getattr(hf, "first_page", True):
                return None
        if mirrored and (hf.left or hf.right):
            hf = replace(hf, left=hf.right, right=hf.left)
        return hf

    # -- cross-reference resolution --

    _REF_PATTERN = re.compile(r"@([\w](?:[\w:.-]*[\w])?)|\\(?:eq)?ref\{([^}]+)\}")

    def _resolve_references(self, document, content: list) -> list:
        """Number captions, resolve @key tokens, and collect anchor keys."""
        auto_number = bool(getattr(document, "auto_number", True))
        number_sections = bool(getattr(document, "number_sections", False))

        section_numbers: dict = {}
        if number_sections:
            context = NumberingContext()
            for idx, element in enumerate(content):
                if isinstance(element, Heading) and not getattr(
                    element, "_is_appendix", False
                ):
                    section_numbers[idx] = context.next_heading(element.level)

        index = CrossReferenceIndex(document, section_numbers=section_numbers or None)
        entries = {entry.element_index: entry for entry in index.all_entries()}
        if not entries and not section_numbers:
            return content

        # `content` elements belong to the validator's deep copy, so
        # rewriting them in place never mutates caller-owned objects.
        for idx, element in enumerate(content):
            entry = entries.get(idx)
            if isinstance(element, Heading):
                number = section_numbers.get(idx)
                if number:
                    element.text = f"{number} {element.text}"
                if entry is not None:
                    self._element_keys[id(element)] = entry.anchor
            elif entry is not None:
                if isinstance(element, Chart):
                    if auto_number and element.title:
                        if element.alt_text is None:
                            element.alt_text = (
                                f"{element.chart_type} chart: {element.title}"
                            )
                        if not _CAPTION_LABEL_RE.match(element.title):
                            element.title = f"{entry.label}: {element.title}"
                elif auto_number and getattr(element, "caption", None):
                    if not _CAPTION_LABEL_RE.match(element.caption):
                        element.caption = f"{entry.label}: {element.caption}"
                if isinstance(element, MathBlock):
                    element._assigned_number = entry.number
                self._element_keys[id(element)] = entry.anchor
            elif isinstance(element, Paragraph):
                resolved = self._resolve_runs(element.runs, index)
                if resolved is not None:
                    element.runs = resolved
        return content

    def _resolve_runs(self, runs: list, index) -> list | None:
        """Rewrite @key tokens into linked label runs, or None if unchanged."""
        changed = False
        out: list = []
        for run in runs:
            text = run.text
            if run.link or (
                "@" not in text and "\\ref" not in text and "\\eqref" not in text
            ):
                out.append(run)
                continue
            pieces: list = []
            cursor = 0
            for match in self._REF_PATTERN.finditer(run.text):
                key = match.group(1) or match.group(2)
                entry = index.get(key) or index.get(f"eq:{key}")
                if entry is None:
                    continue
                if match.start() > cursor:
                    pieces.append((run.text[cursor : match.start()], None))
                pieces.append((entry.ref_label, entry.anchor))
                cursor = match.end()
            if not pieces:
                out.append(run)
                continue
            changed = True
            if cursor < len(run.text):
                pieces.append((run.text[cursor:], None))
            for text, anchor in pieces:
                link = f"#{anchor}" if anchor else None
                out.append(replace(run, text=text, link=link))
        return out if changed else None

    def _record_anchors(self, page, page_ref) -> None:
        """Map registered element keys to this page for GoTo destinations."""
        for placed in page.blocks:
            key = self._element_keys.get(id(placed.block.element))
            if key is not None and key not in self._anchor_map:
                self._anchor_map[key] = (page_ref, round(placed.y, 2))

    # -- visible table of contents --

    TOC_MAX_PASSES = 3

    def _toc_entries(self, content: list, toc_element) -> list:
        """Collect (target, text, level, link_key) rows for one TOC block."""
        entries: list = []
        counter = 0
        for element in content:
            if toc_element.source == "headings":
                if not isinstance(element, Heading):
                    continue
                if element.level > toc_element.depth:
                    continue
                text, level = element.text, element.level
            elif toc_element.source == "figures":
                if isinstance(element, Chart):
                    text = element.title
                elif isinstance(element, (Image, SvgBlock)):
                    text = element.caption
                else:
                    continue
                if not text:
                    continue
                level = 1
            elif toc_element.source == "tables":
                if not isinstance(element, Table) or not element.caption:
                    continue
                text, level = element.caption, 1
            else:
                continue
            key = self._element_keys.get(id(element))
            if key is None:
                key = f"__toc{counter}"
                counter += 1
                self._element_keys[id(element)] = key
            entries.append((element, text, level, key))
        return entries

    def _paginate_sections(self, engine, document, content: list) -> list:
        """Measure and paginate content, switching page geometry at styled
        `PageBreak` markers so a document can mix page sizes mid-flow."""
        sections = self._split_page_sections(document, content)
        pages: list = []
        for spec, chunk in sections:
            measured = [engine.measure(el, spec.content_width) for el in chunk]
            pages.extend(engine.paginate(measured, spec))
        for index, page in enumerate(pages, start=1):
            page.number = index
        return pages

    @staticmethod
    def _split_page_sections(document, content: list) -> list:
        """Split content into runs that each share one page geometry.

        A `PageBreak.page_style` names an entry in `document.page_styles`;
        everything after it uses that geometry until another `PageBreak`
        switches again, or reverts to the document's default page when a
        `PageBreak` carries no `page_style`.
        """
        default_spec = document.page
        styles = getattr(document, "page_styles", None) or {}
        sections: list = []
        current_spec = default_spec
        chunk: list = []
        for element in content:
            if isinstance(element, PageBreak):
                name = element.page_style
                if name is None:
                    next_spec = default_spec
                elif name in styles:
                    next_spec = styles[name]
                else:
                    available = ", ".join(sorted(styles)) or "(none registered)"
                    raise ValueError(
                        f"unknown page_style {name!r}; registered: {available}"
                    )
                if next_spec is not current_spec:
                    sections.append((current_spec, chunk))
                    chunk = []
                    current_spec = next_spec
                    continue
            chunk.append(element)
        sections.append((current_spec, chunk))
        return sections

    @staticmethod
    def _collect_index_targets(content: list, index_indices: list) -> dict:
        """Map id(element) -> set of index terms carried by its runs."""
        if not index_indices:
            return {}
        targets: dict = {}
        for element in content:
            runs = getattr(element, "runs", None)
            if not runs:
                continue
            terms = {
                term for run in runs for term in getattr(run, "index_terms", ()) or ()
            }
            if terms:
                targets[id(element)] = terms
        return targets

    def _paginate_with_toc(
        self,
        engine,
        document,
        content,
        width: float,
        toc_indices: list,
        index_indices: list | None = None,
    ) -> list:
        """Two-pass layout: fill real page numbers into TOC and Index blocks."""
        index_indices = index_indices or []
        toc_index_set = set(toc_indices)
        index_index_set = set(index_indices)
        entries_by_toc = {
            i: self._toc_entries(content, content[i]) for i in toc_indices
        }
        target_ids = {
            id(target)
            for entries in entries_by_toc.values()
            for target, _t, _l, _k in entries
        }

        index_targets = self._collect_index_targets(content, index_indices)
        all_terms = sorted({term for terms in index_targets.values() for term in terms})

        page_map: dict = {}
        term_pages: dict = {}
        pages: list = []
        for _ in range(self.TOC_MAX_PASSES):
            measured = []
            for i, element in enumerate(content):
                if i in toc_index_set:
                    rows = [
                        (text, level, page_map.get(id(target), ""), key)
                        for target, text, level, key in entries_by_toc[i]
                    ]
                    measured.append(engine.measure_toc(element, width, rows))
                elif i in index_index_set:
                    rows = [
                        (term, ", ".join(term_pages.get(term, [])))
                        for term in all_terms
                    ]
                    measured.append(engine.measure_index(element, width, rows))
                else:
                    measured.append(engine.measure(element, width))
            pages = engine.paginate(measured, document.page)

            new_map = {}
            new_term_pages: dict = {}
            for pidx, page in enumerate(pages):
                for placed in page.blocks:
                    eid = id(placed.block.element)
                    if eid in target_ids and eid not in new_map:
                        new_map[eid] = self._page_number_labels(
                            document, pidx, len(pages)
                        )[0]
                    terms = index_targets.get(eid)
                    if terms:
                        label = self._page_number_labels(document, pidx, len(pages))[0]
                        for term in terms:
                            lst = new_term_pages.setdefault(term, [])
                            if label not in lst:
                                lst.append(label)
            if new_map == page_map and new_term_pages == term_pages:
                break
            page_map = new_map
            term_pages = new_term_pages
        return pages

    # -- assembly --

    def _assemble(self, assembler, document, sheet, pages) -> bytes:
        catalog_id = assembler.allocate()
        pages_id = assembler.allocate()

        page_ids = [assembler.allocate() for _ in pages]
        page_refs = [PdfRef(pid) for pid in page_ids]

        root = StructureElement(tag="Document")
        font_resources: dict = {}
        content_refs = []

        for index, page in enumerate(pages):
            if self._element_keys:
                self._record_anchors(page, page_refs[index])
            stream, page_root = self._render_page(
                document, sheet, page, index, len(pages), font_resources
            )
            for child in page_root.children:
                root.children.append(child)
            content_refs.append(assembler.add(PdfStream(data=stream)))

        annots_by_page = self._build_link_annots(assembler, document, len(pages))
        if self._formfield_records:
            self._build_form_field_widgets(
                assembler, document, page_refs, annots_by_page
            )

        # Register fonts after rendering so usage is known for subsetting.
        if self._svg_fonts:
            from .typography.font_metrics import FontMetrics

            for key in sorted(self._svg_fonts):
                font_resources.setdefault(key, FontMetrics.base14(self._svg_fonts[key]))
        font_dict = PdfDict()
        for key, metrics in sorted(font_resources.items()):
            resource = build_font_resource(assembler, key, metrics)
            font_dict[key] = resource.ref

        xobject_dict = PdfDict()
        if hasattr(self, "_image_refs"):
            from .images import load_image, image_xobject

            for name, element in self._image_refs.values():
                img_data = load_image(element.source)
                ref = image_xobject(assembler, img_data)
                xobject_dict[name] = ref
        if getattr(self, "_watermark_image_ref", None) is not None:
            from .images import load_image, image_xobject

            name, source = self._watermark_image_ref
            img_data = load_image(source)
            xobject_dict[name] = image_xobject(assembler, img_data)

        resources = PdfDict()
        resources["Font"] = font_dict
        proc_set = [PdfName("PDF"), PdfName("Text")]
        if xobject_dict.entries:
            resources["XObject"] = xobject_dict
            proc_set.append(PdfName("ImageC"))
        resources["ProcSet"] = PdfArray(proc_set)
        if self._used_spots:
            from .colors import build_spot_color_resource

            cs_dict = PdfDict()
            for spot_name in sorted(self._used_spots):
                spot = self._used_spots[spot_name]
                res_name, cs_ref = build_spot_color_resource(
                    assembler, spot.name, spot.c, spot.m, spot.y, spot.k
                )
                cs_dict[res_name] = cs_ref
            resources["ColorSpace"] = cs_dict
        ext_states = None
        if document.legal and (
            document.legal.watermark or document.legal.watermark_image
        ):
            ext_states = self._watermark_gstate(assembler, document.legal)
            resources["ExtGState"] = ext_states
        resources_ref = assembler.add(resources)
        page_resource_refs = self._build_svg_page_resources(
            assembler, resources, ext_states
        )

        attachment_entries: list = []
        for file_attachment, target_el in self._pending_attachments:
            filespec_ref, _ef_ref = build_embedded_file(
                assembler,
                name=file_attachment.name,
                data=file_attachment.data,
                mime=file_attachment.mime,
                description=file_attachment.description,
                relationship=file_attachment.relationship,
            )
            attachment_entries.append((file_attachment.name, filespec_ref))
            if target_el is not None:
                target_el.af_refs = [filespec_ref]

        struct_ref = None
        if document.tagged:
            builder = StructureTreeBuilder(assembler, page_refs)
            struct_ref = builder.build(root)

        for index, (page, page_id) in enumerate(zip(pages, page_ids)):
            page_dict = PdfDict()
            page_dict["Type"] = PdfName("Page")
            page_dict["Parent"] = PdfRef(pages_id)
            page_spec = getattr(page, "spec", None) or document.page
            page_dict["MediaBox"] = PdfArray([0, 0, page_spec.width, page_spec.height])
            page_dict["Resources"] = page_resource_refs.get(index, resources_ref)
            page_dict["Contents"] = content_refs[index]
            if document.tagged:
                page_dict["StructParents"] = index
            page_annots = annots_by_page.get(index)
            if page_annots:
                page_dict["Annots"] = PdfArray(page_annots)
            page_dict["Tabs"] = PdfName("S")
            assembler.add(page_dict, obj_id=page_id)

        pages_dict = PdfDict()
        pages_dict["Type"] = PdfName("Pages")
        pages_dict["Kids"] = PdfArray(page_refs)
        pages_dict["Count"] = len(pages)
        assembler.add(pages_dict, obj_id=pages_id)

        catalog = PdfDict()
        catalog["Type"] = PdfName("Catalog")
        catalog["Pages"] = PdfRef(pages_id)
        catalog["Lang"] = document.language
        if attachment_entries:
            tree_ref = assembler.add(build_names_tree(attachment_entries))
            names = catalog.get("Names")
            if names is None:
                names = PdfDict()
                catalog["Names"] = names
            names["EmbeddedFiles"] = tree_ref
            catalog["AF"] = af_array([ref for _name, ref in attachment_entries])
        if document.tagged:
            catalog["StructTreeRoot"] = struct_ref
            mark_info = PdfDict()
            mark_info["Marked"] = True
            catalog["MarkInfo"] = mark_info
            view_prefs = PdfDict()
            view_prefs["DisplayDocTitle"] = True
            catalog["ViewerPreferences"] = view_prefs

        page_labels = self._page_labels_dict(document, len(pages))
        if page_labels is not None:
            catalog["PageLabels"] = page_labels

        if document.toc:
            from .toc import build_toc_entries, build_outline_dict

            entries = build_toc_entries(pages)
            outline_ref = build_outline_dict(assembler, entries, page_refs)
            if outline_ref:
                catalog["Outlines"] = outline_ref

        if document.pdfa:
            from .pdfa import pdfa_catalog_entries, pdfa_part_for

            part = pdfa_part_for(bool(attachment_entries))
            pdfa_entries = pdfa_catalog_entries(assembler, document, part=part)
            for key, value in pdfa_entries.items():
                catalog[key] = value
        elif document.tagged or document.pdfx or document.wtpdf:
            from .pdfa import build_xmp_stream

            catalog["Metadata"] = build_xmp_stream(assembler, document, pdfa=False)

        if document.pdfx:
            from .pdfx import build_pdfx_output_intent

            intent_ref = build_pdfx_output_intent(assembler, document)
            existing = catalog.get("OutputIntents")
            if isinstance(existing, PdfArray):
                existing.append(intent_ref)
            else:
                catalog["OutputIntents"] = PdfArray([intent_ref])

        sig_field_refs: list = []
        if document.signatures:
            from .signing import SignatureField, build_sig_field_dict

            for sig in document.signatures:
                if isinstance(sig, dict):
                    sig = SignatureField(**sig)
                pidx = min(sig.page_index, len(page_refs) - 1)
                ref = build_sig_field_dict(assembler, sig, page_refs[pidx])
                sig_field_refs.append(ref)

        if sig_field_refs or self._form_field_refs:
            from .formfields import build_form_acroform

            sig_acroform = None
            if sig_field_refs:
                from .signing import build_acroform

                sig_acroform = build_acroform(sig_field_refs)
            catalog["AcroForm"] = build_form_acroform(
                assembler, self._form_field_refs, sig_acroform=sig_acroform
            )

        assembler.add(catalog, obj_id=catalog_id)

        info = PdfDict()
        if document.title:
            info["Title"] = document.title
        if document.author:
            info["Author"] = document.author
        if document.subject:
            info["Subject"] = document.subject
        if document.keywords:
            info["Keywords"] = document.keywords
        info["Creator"] = document.creator
        info["Producer"] = document.producer
        if document.pdfx:
            from .pdfx import PDFX_VERSION

            info["GTS_PDFXVersion"] = PDFX_VERSION

        return assembler.build(PdfRef(catalog_id), info=info)

    def _build_link_annots(self, assembler, document, page_count: int) -> dict:
        """Emit /Link annotations for recorded link rects, page by page."""
        annots_by_page: dict = {}
        next_key = page_count
        for page_index, rect, url, parent_el in self._link_records:
            action = None
            dest = None
            if url.startswith("#"):
                anchor = self._anchor_map.get(url[1:])
                if anchor is None:
                    continue
                page_ref, dest_y = anchor
                dest = PdfArray([page_ref, PdfName("XYZ"), None, dest_y, None])
            elif url.startswith(("http://", "https://", "mailto:")):
                action = PdfDict()
                action["S"] = PdfName("URI")
                action["URI"] = url
            else:
                continue

            annot_id = assembler.allocate()
            annot_ref = PdfRef(annot_id)
            annot = PdfDict()
            annot["Type"] = PdfName("Annot")
            annot["Subtype"] = PdfName("Link")
            annot["Rect"] = PdfArray(list(rect))
            annot["Border"] = PdfArray([0, 0, 0])
            if action is not None:
                annot["A"] = action
            else:
                annot["Dest"] = dest
            if document.tagged:
                annot["StructParent"] = next_key
                link_el = StructureElement(tag="Link", page_index=page_index)
                link_el.annot_ref = annot_ref
                link_el.struct_parent = next_key
                parent_el.children.append(link_el)
                next_key += 1
            assembler.add(annot, obj_id=annot_id)
            annots_by_page.setdefault(page_index, []).append(annot_ref)
        self._struct_parent_next = next_key
        return annots_by_page

    def _build_form_field_widgets(
        self, assembler, document, page_refs: list, annots_by_page: dict
    ) -> None:
        """Build widget annotations for placed text/checkbox/dropdown fields.

        Consumes `self._formfield_records` (populated while drawing pages),
        building each field's AcroForm dict + widget annotation, adding it
        to the page's /Annots, and -- when the document is tagged -- wiring
        its /Form structure element to the widget via the same annot_ref/
        struct_parent OBJR mechanism link annotations use, continuing the
        shared /StructParents key sequence `_build_link_annots` started.
        """
        from .formfields import (
            build_checkbox_field_dict,
            build_dropdown_field_dict,
            build_text_field_dict,
        )

        next_key = self._struct_parent_next
        refs: list = []
        for page_index, rect, element, field_el in self._formfield_records:
            page_ref = page_refs[page_index]
            tooltip = element.label or element.name
            if isinstance(element, TextField):
                ref = build_text_field_dict(
                    assembler,
                    name=element.name,
                    rect=rect,
                    page_ref=page_ref,
                    default=element.default,
                    multiline=element.multiline,
                    required=element.required,
                    tooltip=tooltip,
                )
            elif isinstance(element, CheckboxField):
                ref = build_checkbox_field_dict(
                    assembler,
                    name=element.name,
                    rect=rect,
                    page_ref=page_ref,
                    checked=element.checked,
                    tooltip=tooltip,
                )
            elif isinstance(element, DropdownField):
                ref = build_dropdown_field_dict(
                    assembler,
                    name=element.name,
                    rect=rect,
                    page_ref=page_ref,
                    options=element.option_list,
                    default=element.default,
                    tooltip=tooltip,
                )
            else:  # pragma: no cover - defensive, unreachable via public API
                continue

            if document.tagged:
                field_el.page_index = page_index
                field_el.annot_ref = ref
                field_el.struct_parent = next_key
                next_key += 1
            annots_by_page.setdefault(page_index, []).append(ref)
            refs.append(ref)

        self._struct_parent_next = next_key
        self._form_field_refs = refs

    def _build_svg_page_resources(self, assembler, resources, ext_states) -> dict:
        """Per-page Resources overriding ExtGState for pages with SVG opacity."""
        page_resource_refs: dict = {}
        if not self._svg_gstates_by_page:
            return page_resource_refs
        gstate_cache: dict = {}
        for page_index in sorted(self._svg_gstates_by_page):
            page_res = PdfDict()
            for key, value in resources.entries.items():
                if key != "ExtGState":
                    page_res[key] = value
            states = PdfDict()
            if ext_states is not None:
                for name, ref in ext_states.entries.items():
                    states[name] = ref
            page_states = self._svg_gstates_by_page[page_index]
            for name in sorted(page_states):
                params = page_states[name]
                cache_key = (params["ca"], params["CA"])
                ref = gstate_cache.get(cache_key)
                if ref is None:
                    gstate = PdfDict()
                    gstate["Type"] = PdfName("ExtGState")
                    gstate["ca"] = params["ca"]
                    gstate["CA"] = params["CA"]
                    ref = assembler.add(gstate)
                    gstate_cache[cache_key] = ref
                states[name] = ref
            page_res["ExtGState"] = states
            page_resource_refs[page_index] = assembler.add(page_res)
        return page_resource_refs

    def _watermark_gstate(self, assembler, legal) -> PdfDict:
        gstate = PdfDict()
        gstate["Type"] = PdfName("ExtGState")
        gstate["ca"] = legal.watermark_opacity
        gstate["CA"] = legal.watermark_opacity
        states = PdfDict()
        states["GSwm"] = assembler.add(gstate)
        return states

    # -- page rendering --

    def _font_key(self, metrics, registry: dict) -> str:
        for key, existing in registry.items():
            if existing is metrics:
                return key
        key = f"F{len(registry) + 1}"
        registry[key] = metrics
        return key

    def _render_page(
        self, document, sheet, page, page_index, total, font_registry
    ) -> tuple:
        stream = ContentStream(color_mode=document.color_mode)
        root = StructureElement(tag="Document")
        legal = document.legal

        page_spec = getattr(page, "spec", None) or document.page

        if legal and legal.watermark_image:
            self._draw_image_watermark(stream, page_spec, legal)
        if legal and legal.watermark:
            self._draw_watermark(stream, page_spec, sheet, legal, font_registry)

        page_blocks = page.blocks
        page_footnotes = list(getattr(page, "footnotes", []) or [])
        if self._is_mirrored(document, page_index):
            shift = page_spec.margin_right - page_spec.margin_left
            if shift:
                page_blocks = [
                    replace(placed, x=placed.x + shift) for placed in page.blocks
                ]
                page_footnotes = [
                    replace(note, x=note.x + shift) for note in page_footnotes
                ]

        for placed in page_blocks:
            element = placed.block.element
            struct_before = len(root.children)
            self._record_layout(page_spec, placed, page_index)
            if isinstance(element, Heading):
                self._draw_text_block(
                    stream,
                    placed,
                    page_index,
                    root,
                    font_registry,
                    tag=element.structure_tag,
                )
            elif isinstance(element, Paragraph):
                self._draw_text_block(
                    stream, placed, page_index, root, font_registry, tag="P"
                )
            elif isinstance(element, BlockQuote):
                self._draw_blockquote(stream, placed, page_index, root, font_registry)
            elif isinstance(element, BulletList):
                self._draw_list(stream, placed, page_index, root, font_registry)
            elif isinstance(element, NumberedList):
                self._draw_numbered_list(
                    stream, placed, page_index, root, font_registry
                )
            elif isinstance(element, Table):
                self._draw_table(stream, placed, page_index, root, font_registry, sheet)
            elif isinstance(element, Footnote):
                self._draw_footnote(stream, placed, page_index, root, font_registry)
            elif isinstance(element, Callout):
                self._draw_callout(
                    stream,
                    placed,
                    page_index,
                    root,
                    font_registry,
                    page_spec.content_width,
                )
            elif isinstance(element, Image):
                self._draw_image(stream, placed, page_index, root, font_registry)
            elif isinstance(element, Chart):
                self._draw_chart(stream, placed, page_index, root, font_registry)
            elif isinstance(element, CodeBlock):
                self._draw_code_block(
                    stream,
                    placed,
                    page_index,
                    root,
                    font_registry,
                    page_spec.content_width,
                )
            elif isinstance(element, MathBlock):
                self._draw_math(
                    stream,
                    placed,
                    page_index,
                    root,
                    font_registry,
                    page_spec.content_width,
                )
            elif isinstance(element, BibliographyBlock):
                self._draw_bibliography(stream, placed, page_index, root, font_registry)
            elif isinstance(element, SvgBlock):
                self._draw_svg(
                    stream,
                    placed,
                    page_index,
                    root,
                    font_registry,
                    page_spec.content_width,
                )
            elif isinstance(element, CoverPage):
                self._draw_cover(
                    stream, placed, page_index, root, font_registry, page_spec
                )
            elif isinstance(element, Abstract):
                self._draw_abstract(stream, placed, page_index, root, font_registry)
            elif isinstance(element, Authors):
                self._draw_authors(stream, placed, page_index, root, font_registry)
            elif isinstance(element, PullQuote):
                self._draw_pullquote(stream, placed, page_index, root, font_registry)
            elif isinstance(element, StatTiles):
                self._draw_stat_tiles(stream, placed, page_index, root, font_registry)
            elif isinstance(element, TableOfContents):
                self._draw_toc(stream, placed, page_index, root, font_registry)
            elif isinstance(element, Glossary):
                self._draw_glossary(stream, placed, page_index, root, font_registry)
            elif isinstance(element, Index):
                self._draw_index(stream, placed, page_index, root, font_registry)
            elif isinstance(element, HorizontalRule):
                self._draw_rule(stream, placed, page_spec.content_width)
            elif isinstance(element, TextField):
                self._draw_text_field(stream, placed, page_index, root, font_registry)
            elif isinstance(element, CheckboxField):
                self._draw_checkbox_field(
                    stream, placed, page_index, root, font_registry
                )
            elif isinstance(element, DropdownField):
                self._draw_dropdown_field(
                    stream, placed, page_index, root, font_registry
                )

            node_id = getattr(element, "id", None)
            if node_id:
                for child in root.children[struct_before:]:
                    if child.node_id is None:
                        child.node_id = node_id

        for placed_note in page_footnotes:
            self._draw_footnote_area(
                stream, placed_note, page_index, root, font_registry
            )

        if document.redactions:
            from .redaction import apply_redactions, RedactionMark

            marks = []
            for r in document.redactions:
                if isinstance(r, RedactionMark):
                    marks.append(r)
                elif isinstance(r, dict):
                    marks.append(RedactionMark(**r))
            if marks:
                style = sheet.resolved(sheet.body)
                _, size, key = self._resolve_font(style, None, font_registry)
                apply_redactions(stream, marks, page_index, key, size * 0.8)

        if document.signatures:
            from .signing import SignatureField, build_signature_appearance

            for sig in document.signatures:
                if isinstance(sig, dict):
                    sig = SignatureField(**sig)
                if sig.page_index == page_index:
                    style = sheet.resolved(sheet.body)
                    _, size, key = self._resolve_font(style, None, font_registry)
                    build_signature_appearance(stream, sig, key, size)

        self._draw_running_content(
            stream, document, sheet, page, page_index, total, font_registry
        )
        for spot_name, spot in stream.used_spots.items():
            self._used_spots.setdefault(spot_name, spot)
        svg_gstates = getattr(stream, "used_svg_gstates", None)
        if svg_gstates:
            self._svg_gstates_by_page[page_index] = dict(svg_gstates)
        svg_fonts = getattr(stream, "used_svg_fonts", None)
        if svg_fonts:
            for key in sorted(svg_fonts):
                self._svg_fonts.setdefault(key, svg_fonts[key])
        return stream.to_bytes(), root

    def _block_width(self, placed, page_spec) -> float:
        """Horizontal extent of a placed block for its layout-map bbox."""
        if getattr(placed.block, "full_page", False):
            return page_spec.content_width
        cols = getattr(page_spec, "columns", 1)
        if cols > 1:
            gap = page_spec.column_gap
            col_w = (page_spec.content_width - gap * (cols - 1)) / cols
            near_left = abs(placed.x - page_spec.margin_left) < 0.5
            if near_left and placed.height and page_spec.content_width - col_w > 0.5:
                # Column-spanning blocks are placed at the left margin.
                span = getattr(placed.block.element, "style", None)
                if span is not None and getattr(span, "column_span", None):
                    return page_spec.content_width
            return col_w
        return page_spec.content_width

    def _record_layout(self, page_spec, placed, page_index) -> None:
        """Add one node-id -> page/bbox entry from a placed block's geometry."""
        node_id = getattr(placed.block.element, "id", None)
        if not node_id:
            return
        width = self._block_width(placed, page_spec)
        box = round_bbox(
            placed.x,
            placed.y - placed.height,
            placed.x + width,
            placed.y,
        )
        entry = {"page": page_index}
        entry.update(box)
        self._layout_map.setdefault(node_id, []).append(entry)

    def _record_text_span(
        self, node_id, page_index, char_start, text, x, baseline, metrics, size
    ) -> int:
        """Record a rendered fragment's char range and rect; return its length.

        The character offsets count the visible rendered text of the node in
        render order, so a highlight rect over these glyphs maps back to a
        char range within the node.
        """
        length = len(text)
        if not node_id or not text:
            return length
        width = metrics.text_width(text, size)
        box = round_bbox(
            x,
            baseline + metrics.descent(size),
            x + width,
            baseline + metrics.ascent(size),
        )
        entry = {
            "page": page_index,
            "char_start": char_start,
            "char_end": char_start + length,
            "text": text,
        }
        entry.update(box)
        self._text_index.setdefault(node_id, []).append(entry)
        return length

    def _resolve_font(self, style, run, registry) -> tuple:
        family = (
            run.font_family if run and run.font_family else style.require("font_family")
        )
        bold = run.bold if run and run.bold else style.require("bold")
        italic = run.italic if run and run.italic else style.require("italic")
        metrics = self.fonts.resolve(family, bold=bold, italic=italic)
        size = run.font_size if run and run.font_size else style.require("font_size")
        key = self._font_key(metrics, registry)
        return metrics, size, key

    @staticmethod
    def _actual_text_bdc(text: str) -> bytes:
        """Marked-content opener carrying ActualText (UTF-16BE) for extraction."""
        hexed = text.encode("utf-16-be").hex().upper()
        return b"/Span <</ActualText <FEFF" + hexed.encode("ascii") + b">>> BDC"

    def _draw_strikethrough(
        self, stream, metrics, size: float, x: float, baseline: float, text, color
    ) -> None:
        """Strike a fragment with a rule above the baseline, in text color."""
        width = metrics.text_width(text, size)
        if width <= 0:
            return
        y = baseline + size * 0.28
        stream.line(x, y, x + width, y, color=color, width=max(size * 0.06, 0.4))

    def _draw_underline(
        self, stream, metrics, size: float, x: float, baseline: float, text, color
    ) -> None:
        """Underline a fragment with a rule below the baseline, in text color."""
        width = metrics.text_width(text, size)
        if width <= 0:
            return
        y = baseline - size * 0.12
        stream.line(x, y, x + width, y, color=color, width=max(size * 0.06, 0.4))

    def _draw_text_block(
        self, stream, placed, page_index, root, registry, tag: str
    ) -> None:
        from .typography.protrusion import left_protrusion

        style = placed.block.style
        element = StructureElement(tag=tag)
        root.children.append(element)

        mcid = stream.next_mcid()
        element.add_mcid(page_index, mcid)
        stream.begin_marked(tag, mcid)

        y = placed.y
        indent = style.require("indent_left")

        align = style.require("align")
        apply_protrusion = align in ("justify", "left")

        node_id = getattr(placed.block.element, "id", None)
        char_cursor = 0
        previous_line_space_break = True

        for line in placed.lines:
            baseline = y - line.ascent
            first_fragment_of_line = True

            protrusion_shift = 0.0
            if apply_protrusion and line.fragments:
                first_text = line.fragments[0][0]
                if first_text:
                    first_run = line.fragments[0][1]
                    first_metrics, first_size, _ = self._resolve_font(
                        style, first_run, registry
                    )
                    char = first_text[0]
                    factor = left_protrusion(char)
                    if factor > 0:
                        char_width = first_metrics.text_width(char, first_size)
                        protrusion_shift = -(char_width * factor)

            previous_link = None
            for text, run, offset in line.fragments:
                metrics, size, key = self._resolve_font(style, run, registry)
                color = run.color or style.require("color")
                x = placed.x + indent + offset + protrusion_shift
                rise = getattr(run, "baseline_rise", 0.0)
                sc_actual = getattr(run, "_sc_actual", None)
                if sc_actual is not None:
                    stream.raw(self._actual_text_bdc(sc_actual))
                stream.text_line(
                    text,
                    key,
                    size,
                    x,
                    baseline + rise if rise else baseline,
                    color,
                    kern_pairs=metrics.kern_pairs(text),
                    gid_map=metrics.gid_map,
                )
                if sc_actual is not None:
                    stream.raw(b"EMC")
                # A line break only stands for a space when the line ended
                # on a real inter-word Glue; a hyphenation or CJK soft break
                # continues the same word/character run with no space.
                if char_cursor > 0 and text:
                    if not first_fragment_of_line or previous_line_space_break:
                        char_cursor += 1  # word separator between fragments
                first_fragment_of_line = False
                char_cursor += self._record_text_span(
                    node_id, page_index, char_cursor, text, x, baseline, metrics, size
                )
                if run.strikethrough:
                    self._draw_strikethrough(
                        stream, metrics, size, x, baseline, text, color
                    )
                if run.underline:
                    self._draw_underline(
                        stream, metrics, size, x, baseline, text, color
                    )
                if run.link:
                    rect = [
                        x,
                        baseline + metrics.descent(size),
                        x + metrics.text_width(text, size),
                        baseline + metrics.ascent(size),
                    ]
                    if previous_link == run.link and self._link_records:
                        merged = self._link_records[-1][1]
                        merged[1] = min(merged[1], rect[1])
                        merged[2] = max(merged[2], rect[2])
                        merged[3] = max(merged[3], rect[3])
                    else:
                        self._link_records.append((page_index, rect, run.link, element))
                previous_link = run.link
            previous_line_space_break = line.space_break
            y -= line.height

        stream.end_marked()

    @staticmethod
    def _draw_checkbox(
        stream, x: float, baseline: float, color, checked, size: float = 7.0
    ) -> None:
        """Draw a `size`pt checkbox outline plus a two-segment tick when checked."""
        stream.rect(
            x, baseline, size, size, stroke=color, line_width=max(0.7, size * 0.1)
        )
        if checked:
            scale = size / 7.0
            stream.set_stroke(color)
            stream.set_line_width(max(0.9, 0.9 * scale))
            stream.raw(
                b" ".join(
                    [
                        stream._num(x + 1.4 * scale),
                        stream._num(baseline + 3.5 * scale),
                        b"m",
                    ]
                )
            )
            stream.raw(
                b" ".join(
                    [
                        stream._num(x + 2.9 * scale),
                        stream._num(baseline + 1.7 * scale),
                        b"l",
                    ]
                )
            )
            stream.raw(
                b" ".join(
                    [
                        stream._num(x + 5.6 * scale),
                        stream._num(baseline + 5.3 * scale),
                        b"l",
                    ]
                )
            )
            stream.raw(b"S")

    @staticmethod
    def _strip_task_prefix(lines: list, checked) -> list:
        """Drop the literal checkbox prefix from a task item's first line."""
        if not lines:
            return lines
        pending = "[x]" if checked else "[]"
        fragments: list = []
        shift = None
        for text, run, offset in lines[0].fragments:
            if pending:
                if pending.startswith(text):
                    pending = pending[len(text) :]
                    continue
                if text.startswith(pending):
                    text = text[len(pending) :]
                pending = ""
            if shift is None:
                shift = offset
            if text:
                fragments.append((text, run, offset - shift))
        return [replace(lines[0], fragments=fragments)] + list(lines[1:])

    def _draw_list(self, stream, placed, page_index, root, registry) -> None:
        from .layout.engine import MeasuredBlock

        block = placed.block
        style = block.style
        element = block.element

        list_el = StructureElement(tag="L")
        root.children.append(list_el)

        metrics, size, key = self._resolve_font(style, None, registry)
        checked = list(getattr(element, "checked", None) or [])
        if checked:
            bullet_width = LayoutEngine.CHECKBOX_SIZE + LayoutEngine.CHECKBOX_GAP
        else:
            bullet_width = metrics.text_width(element.bullet + " ", size)
        indent = style.require("indent_left")
        color = style.require("color")

        y = placed.y
        for item_index, entry in enumerate(block.list_items):
            if isinstance(entry, MeasuredBlock):
                nested_placed = PlacedBlock(
                    block=entry,
                    x=placed.x + LayoutEngine.NESTED_LIST_INDENT,
                    y=y,
                    height=entry.height,
                    lines=entry.lines,
                )
                self._draw_nested_list(
                    stream,
                    nested_placed,
                    page_index,
                    root,
                    registry,
                )
                y -= entry.height + entry.space_after
                continue

            item_checked = checked[item_index] if item_index < len(checked) else None
            lines = entry
            if item_checked is not None:
                lines = self._strip_task_prefix(lines, item_checked)
            item = StructureElement(tag="LI")
            list_el.children.append(item)

            label = StructureElement(tag="Lbl")
            item.children.append(label)
            label_mcid = stream.next_mcid()
            label.add_mcid(page_index, label_mcid)
            stream.begin_marked("Lbl", label_mcid)
            if lines and item_checked is not None:
                self._draw_checkbox(
                    stream,
                    placed.x + indent,
                    y - lines[0].ascent,
                    color,
                    item_checked,
                )
            elif lines:
                stream.text_line(
                    element.bullet,
                    key,
                    size,
                    placed.x + indent,
                    y - lines[0].ascent,
                    color,
                    gid_map=metrics.gid_map,
                )
            stream.end_marked()

            body = StructureElement(tag="LBody")
            item.children.append(body)
            body_mcid = stream.next_mcid()
            body.add_mcid(page_index, body_mcid)
            stream.begin_marked("LBody", body_mcid)

            for line in lines:
                baseline = y - line.ascent
                for text, run, offset in line.fragments:
                    run_metrics, run_size, run_key = self._resolve_font(
                        style, run, registry
                    )
                    x = placed.x + indent + bullet_width + offset
                    stream.text_line(
                        text,
                        run_key,
                        run_size,
                        x,
                        baseline,
                        run.color or color,
                        kern_pairs=run_metrics.kern_pairs(text),
                        gid_map=run_metrics.gid_map,
                    )
                    if run.strikethrough:
                        self._draw_strikethrough(
                            stream,
                            run_metrics,
                            run_size,
                            x,
                            baseline,
                            text,
                            run.color or color,
                        )
                    if run.underline:
                        self._draw_underline(
                            stream,
                            run_metrics,
                            run_size,
                            x,
                            baseline,
                            text,
                            run.color or color,
                        )
                y -= line.height
            stream.end_marked()
            y -= style.require("space_after")

    def _draw_numbered_list(self, stream, placed, page_index, root, registry) -> None:
        from .layout.engine import MeasuredBlock

        block = placed.block
        style = block.style
        element = block.element

        list_el = StructureElement(tag="L")
        root.children.append(list_el)

        metrics, size, key = self._resolve_font(style, None, registry)
        text_count = sum(
            1 for e in block.list_items if not isinstance(e, MeasuredBlock)
        )
        last_marker = element.marker(text_count - 1) if text_count else "1."
        marker_width = metrics.text_width(last_marker + " ", size)
        indent = style.require("indent_left")
        color = style.require("color")

        y = placed.y
        text_idx = 0
        for entry in block.list_items:
            if isinstance(entry, MeasuredBlock):
                nested_placed = PlacedBlock(
                    block=entry,
                    x=placed.x + LayoutEngine.NESTED_LIST_INDENT,
                    y=y,
                    height=entry.height,
                    lines=entry.lines,
                )
                self._draw_nested_list(
                    stream,
                    nested_placed,
                    page_index,
                    root,
                    registry,
                )
                y -= entry.height + entry.space_after
                continue

            lines = entry
            item = StructureElement(tag="LI")
            list_el.children.append(item)

            label = StructureElement(tag="Lbl")
            item.children.append(label)
            label_mcid = stream.next_mcid()
            label.add_mcid(page_index, label_mcid)
            stream.begin_marked("Lbl", label_mcid)
            marker = element.marker(text_idx)
            if lines:
                stream.text_line(
                    marker,
                    key,
                    size,
                    placed.x + indent,
                    y - lines[0].ascent,
                    color,
                    gid_map=metrics.gid_map,
                )
            stream.end_marked()

            body = StructureElement(tag="LBody")
            item.children.append(body)
            body_mcid = stream.next_mcid()
            body.add_mcid(page_index, body_mcid)
            stream.begin_marked("LBody", body_mcid)

            for line in lines:
                baseline = y - line.ascent
                for text, run, offset in line.fragments:
                    run_metrics, run_size, run_key = self._resolve_font(
                        style, run, registry
                    )
                    x = placed.x + indent + marker_width + offset
                    stream.text_line(
                        text,
                        run_key,
                        run_size,
                        x,
                        baseline,
                        run.color or color,
                        kern_pairs=run_metrics.kern_pairs(text),
                        gid_map=run_metrics.gid_map,
                    )
                    if run.strikethrough:
                        self._draw_strikethrough(
                            stream,
                            run_metrics,
                            run_size,
                            x,
                            baseline,
                            text,
                            run.color or color,
                        )
                    if run.underline:
                        self._draw_underline(
                            stream,
                            run_metrics,
                            run_size,
                            x,
                            baseline,
                            text,
                            run.color or color,
                        )
                y -= line.height
            stream.end_marked()
            y -= style.require("space_after")
            text_idx += 1

    def _draw_nested_list(self, stream, placed, page_index, root, registry) -> None:
        from .spec import BulletList, NumberedList

        element = placed.block.element
        if isinstance(element, NumberedList):
            self._draw_numbered_list(stream, placed, page_index, root, registry)
        elif isinstance(element, BulletList):
            self._draw_list(stream, placed, page_index, root, registry)

    def _draw_blockquote(self, stream, placed, page_index, root, registry) -> None:
        element = placed.block.element
        style = placed.block.style
        inset = LayoutEngine.BLOCKQUOTE_INDENT
        color = style.require("color")

        stream.begin_artifact()
        stream.rect(placed.x, placed.y - placed.height, 2.0, placed.height, fill=color)
        stream.end_marked()

        quote_el = StructureElement(tag="BlockQuote")
        root.children.append(quote_el)
        mcid = stream.next_mcid()
        quote_el.add_mcid(page_index, mcid)
        stream.begin_marked("BlockQuote", mcid)

        body_ids = {id(run) for run in element.runs}
        y = placed.y
        for line in placed.lines:
            baseline = y - line.ascent
            for text, run, offset in line.fragments:
                metrics, size, key = self._resolve_font(style, run, registry)
                if id(run) not in body_ids:
                    size *= 0.85
                x = placed.x + inset + offset
                stream.text_line(
                    text,
                    key,
                    size,
                    x,
                    baseline,
                    run.color or color,
                    kern_pairs=metrics.kern_pairs(text),
                    gid_map=metrics.gid_map,
                )
                if run.strikethrough:
                    self._draw_strikethrough(
                        stream, metrics, size, x, baseline, text, run.color or color
                    )
                if run.underline:
                    self._draw_underline(
                        stream, metrics, size, x, baseline, text, run.color or color
                    )
            y -= line.height

        stream.end_marked()

    def _draw_headline_block(
        self, stream, x, y, width, headline, subtitle, style, registry
    ) -> float:
        """Draw a bold headline then a lighter subtitle above content.

        Returns the new top y where the content body should start.
        """
        headline_size, subtitle_size, _source_size = annotation_sizes(style)
        if headline:
            metrics, _, key = self._resolve_font(style.with_(bold=True), None, registry)
            tx = x + max(0.0, (width - metrics.text_width(headline, headline_size)) / 2)
            stream.text_line(
                headline,
                key,
                headline_size,
                tx,
                y - headline_size,
                style.require("color"),
                gid_map=metrics.gid_map,
            )
            y -= headline_size + 4.0
        if subtitle:
            metrics, _, key = self._resolve_font(style, None, registry)
            tx = x + max(0.0, (width - metrics.text_width(subtitle, subtitle_size)) / 2)
            stream.text_line(
                subtitle,
                key,
                subtitle_size,
                tx,
                y - subtitle_size,
                _SUBTITLE_COLOR,
                gid_map=metrics.gid_map,
            )
            y -= subtitle_size + 3.0
        return y

    def _draw_source_line(
        self, stream, x, y, width, source_line, style, registry
    ) -> None:
        """Draw a small gray source line below content, centered on width."""
        if not source_line:
            return
        _headline_size, _subtitle_size, source_size = annotation_sizes(style)
        metrics, _, key = self._resolve_font(style, None, registry)
        tx = x + max(0.0, (width - metrics.text_width(source_line, source_size)) / 2)
        stream.text_line(
            source_line,
            key,
            source_size,
            tx,
            y - source_size - 2.0,
            _SOURCE_LINE_COLOR,
            gid_map=metrics.gid_map,
        )

    def _queue_attachment(
        self, name: str, data: bytes, description: str, target_el
    ) -> None:
        """Record a CSV attachment for a structure element, embedded once assembled."""
        self._pending_attachments.append(
            (
                FileAttachment(
                    name=name,
                    data=data,
                    mime="text/csv",
                    description=description,
                    relationship="Data",
                ),
                target_el,
            )
        )

    def _table_csv_bytes(self, element) -> bytes:
        """Encode a table's headers and rows as CSV, cell text only."""
        headers = [cell.plain_text for cell in element.header_cells]
        rows = [[cell.plain_text for cell in row] for row in element.body_rows]
        return _csv_bytes(([headers] if headers else []) + rows)

    def _chart_csv_bytes(self, element) -> bytes:
        """Encode a chart's categories and series values as CSV."""
        labels = [str(v) for v in element.labels]
        if element.series:
            header = ["category"] + [
                (s.label or f"series {i + 1}") for i, s in enumerate(element.series)
            ]
            count = max([len(labels)] + [len(s.values) for s in element.series])
            rows = []
            for i in range(count):
                cat = labels[i] if i < len(labels) else str(i + 1)
                row = [cat] + [
                    str(s.values[i]) if i < len(s.values) else ""
                    for s in element.series
                ]
                rows.append(row)
        else:
            header = ["category", "value"]
            rows = [
                [labels[i] if i < len(labels) else str(i + 1), str(v)]
                for i, v in enumerate(element.values)
            ]
        return _csv_bytes([header] + rows)

    def _draw_table(self, stream, placed, page_index, root, registry, sheet) -> None:
        block = placed.block
        layout = block.table
        if layout is None:
            return

        element = block.element
        table_el = StructureElement(tag="Table")
        root.children.append(table_el)

        pad_x = sheet.table_cell_padding_x
        pad_y = sheet.table_cell_padding_y
        widths = layout.column_widths
        x_positions, cursor = [], placed.x
        for width in widths:
            x_positions.append(cursor)
            cursor += width
        table_width = sum(widths)

        first_segment = id(element) not in self._chart_table_seen
        if first_segment:
            self._chart_table_seen.add(id(element))
            if element.attach_data or self.source.pdfa:
                self._table_attach_count += 1
                name = f"table-{self._table_attach_count}-data.csv"
                self._queue_attachment(
                    name, self._table_csv_bytes(element), "Table source data", table_el
                )

        y = placed.y
        if first_segment and (element.headline or element.subtitle):
            head_el = StructureElement(tag="Caption")
            table_el.children.append(head_el)
            head_mcid = stream.next_mcid()
            head_el.add_mcid(page_index, head_mcid)
            stream.begin_marked("Caption", head_mcid)
            y = self._draw_headline_block(
                stream,
                placed.x,
                y,
                table_width,
                element.headline,
                element.subtitle,
                block.style,
                registry,
            )
            stream.end_marked()

        if layout.header_lines and placed.include_table_header:
            head = StructureElement(tag="THead")
            table_el.children.append(head)
            row_el = StructureElement(tag="TR")
            head.children.append(row_el)

            header_style = sheet.resolved(sheet.table_header)
            header_spans = layout.header_spans
            for column, lines in enumerate(layout.header_lines):
                span = header_spans[column] if header_spans else 1
                if span == 0:
                    continue
                cell_el = StructureElement(tag="TH", scope="Column")
                if span > 1:
                    cell_el.colspan = span
                row_el.children.append(cell_el)
                mcid = stream.next_mcid()
                cell_el.add_mcid(page_index, mcid)
                stream.begin_marked("TH", mcid)
                self._draw_cell_lines(
                    stream,
                    lines,
                    x_positions[column] + pad_x,
                    y - pad_y,
                    header_style,
                    registry,
                    sum(widths[column : column + span]) - 2 * pad_x,
                )
                stream.end_marked()

            y -= layout.header_height
            stream.begin_artifact()
            stream.line(
                placed.x,
                y,
                placed.x + table_width,
                y,
                color=sheet.table_header_rule_color,
                width=sheet.table_header_rule_width,
            )
            stream.end_marked()

        body = StructureElement(tag="TBody")
        table_el.children.append(body)

        row_indices = placed.table_rows or list(range(len(layout.row_heights)))
        for position, row_index in enumerate(row_indices):
            height = layout.row_heights[row_index]
            cells = layout.row_lines[row_index]

            if block.element.stripe and position % 2 == 1:
                stream.begin_artifact("Background")
                stream.rect(
                    placed.x,
                    y - height,
                    table_width,
                    height,
                    fill=sheet.table_stripe_color,
                )
                stream.end_marked()

            row_el = StructureElement(tag="TR")
            body.children.append(row_el)

            spans = layout.row_spans[row_index] if layout.row_spans else None
            for column, lines in enumerate(cells):
                span = spans[column] if spans else 1
                if span == 0:
                    continue
                cell_el = StructureElement(tag="TD")
                if span > 1:
                    cell_el.colspan = span
                row_el.children.append(cell_el)
                mcid = stream.next_mcid()
                cell_el.add_mcid(page_index, mcid)
                stream.begin_marked("TD", mcid)
                self._draw_cell_lines(
                    stream,
                    lines,
                    x_positions[column] + pad_x,
                    y - pad_y,
                    block.style,
                    registry,
                    sum(widths[column : column + span]) - 2 * pad_x,
                )
                stream.end_marked()

            y -= height
            if position < len(row_indices) - 1:
                stream.begin_artifact()
                stream.line(
                    placed.x,
                    y,
                    placed.x + table_width,
                    y,
                    color=sheet.table_rule_color,
                    width=sheet.table_rule_width,
                )
                stream.end_marked()

        stream.begin_artifact()
        stream.line(
            placed.x,
            y,
            placed.x + table_width,
            y,
            color=sheet.table_header_rule_color,
            width=sheet.table_rule_width,
        )
        stream.end_marked()

        caption = element.caption
        is_last_segment = bool(
            row_indices and row_indices[-1] == len(layout.row_heights) - 1
        )
        content_bottom = y
        if caption and is_last_segment:
            metrics, size, key = self._resolve_font(block.style, None, registry)
            cap_size = size * 0.85
            cap_width = metrics.text_width(caption, cap_size)
            cap_x = placed.x + (table_width - cap_width) / 2
            cap_el = StructureElement(tag="Caption")
            table_el.children.append(cap_el)
            cap_mcid = stream.next_mcid()
            cap_el.add_mcid(page_index, cap_mcid)
            stream.begin_marked("Caption", cap_mcid)
            stream.text_line(
                caption,
                key,
                cap_size,
                cap_x,
                y - cap_size - 4.0,
                block.style.require("color"),
                gid_map=metrics.gid_map,
            )
            stream.end_marked()
            content_bottom -= cap_size + 8.0

        if element.source_line and is_last_segment:
            src_el = StructureElement(tag="Caption")
            table_el.children.append(src_el)
            src_mcid = stream.next_mcid()
            src_el.add_mcid(page_index, src_mcid)
            stream.begin_marked("Caption", src_mcid)
            self._draw_source_line(
                stream,
                placed.x,
                content_bottom,
                table_width,
                element.source_line,
                block.style,
                registry,
            )
            stream.end_marked()

    def _draw_cell_lines(self, stream, lines, x, y, style, registry, available) -> None:
        cursor = y
        for line in lines:
            baseline = cursor - line.ascent
            for text, run, offset in line.fragments:
                metrics, size, key = self._resolve_font(style, run, registry)
                stream.text_line(
                    text,
                    key,
                    size,
                    x + offset,
                    baseline,
                    run.color or style.require("color"),
                    kern_pairs=metrics.kern_pairs(text),
                    gid_map=metrics.gid_map,
                )
            cursor -= line.height

    def _draw_rule(self, stream, placed, content_width: float) -> None:
        element = placed.block.element
        stream.begin_artifact()
        stream.line(
            placed.x,
            placed.y,
            placed.x + content_width,
            placed.y,
            color=element.color,
            width=element.thickness,
        )
        stream.end_marked()

    def _draw_image(self, stream, placed, page_index, root, registry) -> None:
        element = placed.block.element
        style = placed.block.style

        fig_el = StructureElement(tag="Figure")
        if element.alt_text:
            fig_el.alt_text = element.alt_text
        root.children.append(fig_el)

        mcid = stream.next_mcid()
        fig_el.add_mcid(page_index, mcid)
        stream.begin_marked("Figure", mcid)

        img_name = self._get_image_ref(element)
        from .images import load_image

        img = load_image(element.source)

        content_width = placed.block.style.require("font_size") * 30
        display_w = element.width or min(float(img.width), content_width)
        scale = display_w / img.width
        display_h = element.height or img.height * scale

        x = placed.x
        if element.align == "center":
            x = placed.x + (content_width - display_w) / 2
        elif element.align == "right":
            x = placed.x + content_width - display_w

        y = placed.y - display_h

        stream.save()
        stream.raw(
            b" ".join(
                [
                    stream._num(display_w),
                    b"0 0",
                    stream._num(display_h),
                    stream._num(x),
                    stream._num(y),
                    b"cm",
                ]
            )
        )
        stream.raw(f"/{img_name} Do".encode("ascii"))
        stream.restore()

        if element.caption:
            metrics, size, key = self._resolve_font(style, None, registry)
            cap_size = size * 0.85
            cap_y = y - cap_size - 2.0
            color = style.require("color")
            cap_x = x + (display_w - metrics.text_width(element.caption, cap_size)) / 2
            stream.text_line(
                element.caption,
                key,
                cap_size,
                cap_x,
                cap_y,
                color,
                gid_map=metrics.gid_map,
            )

        stream.end_marked()

    def _get_image_ref(self, element) -> str:
        if not hasattr(self, "_image_refs"):
            self._image_refs = {}
        source_key = id(element)
        if source_key not in self._image_refs:
            name = f"Im{len(self._image_refs) + 1}"
            self._image_refs[source_key] = (name, element)
        return self._image_refs[source_key][0]

    def _draw_chart(self, stream, placed, page_index, root, registry) -> None:
        from .chart_facts import resolve_headline
        from .charts import ChartData, ChartSpec, render_chart, series_summary

        element = placed.block.element
        style = placed.block.style

        fig_el = StructureElement(tag="Figure")
        fig_el.alt_text = element.alt_text or series_summary(element)
        root.children.append(fig_el)

        if element.attach_data or self.source.pdfa:
            self._chart_attach_count += 1
            name = f"chart-{self._chart_attach_count}-data.csv"
            self._queue_attachment(
                name, self._chart_csv_bytes(element), "Chart source data", fig_el
            )

        mcid = stream.next_mcid()
        fig_el.add_mcid(page_index, mcid)
        stream.begin_marked("Figure", mcid)

        _, size, key = self._resolve_font(style, None, registry)

        headline = resolve_headline(element)
        y = self._draw_headline_block(
            stream,
            placed.x,
            placed.y,
            element.width,
            headline,
            element.subtitle,
            style,
            registry,
        )

        data = ChartData(
            labels=list(element.labels),
            values=list(element.values),
            colors=list(element.colors) if element.colors else None,
            title=element.title,
            series=list(element.series) if element.series else None,
            x_title=element.x_title,
            y_title=element.y_title,
            legend=element.legend,
            patterns=element.patterns,
        )
        spec = ChartSpec(
            chart_type=element.chart_type,
            data=data,
            width=element.width,
            height=element.height,
        )
        render_chart(stream, spec, placed.x, y, key, size * 0.8)

        self._draw_source_line(
            stream,
            placed.x,
            y - element.height,
            element.width,
            element.source_line,
            style,
            registry,
        )

        stream.end_marked()

    def _draw_footnote(self, stream, placed, page_index, root, registry) -> None:
        element = placed.block.element
        style = placed.block.style

        note_el = StructureElement(tag="Note")
        root.children.append(note_el)

        mcid = stream.next_mcid()
        note_el.add_mcid(page_index, mcid)
        stream.begin_marked("Note", mcid)

        metrics, size, key = self._resolve_font(style, None, registry)
        color = style.require("color")
        marker = element.marker or "*"
        marker_width = metrics.text_width(marker + " ", size)

        stream.begin_artifact()
        stream.line(
            placed.x,
            placed.y + 2.0,
            placed.x + 100.0,
            placed.y + 2.0,
            color="d6d3d1",
            width=0.5,
        )
        stream.end_marked()

        y = placed.y
        baseline = y - placed.lines[0].ascent if placed.lines else y
        stream.text_line(
            marker,
            key,
            size,
            placed.x,
            baseline,
            color,
            gid_map=metrics.gid_map,
        )

        for line in placed.lines:
            baseline = y - line.ascent
            for text, run, offset in line.fragments:
                run_metrics, run_size, run_key = self._resolve_font(
                    style, run, registry
                )
                stream.text_line(
                    text,
                    run_key,
                    run_size,
                    placed.x + marker_width + offset,
                    baseline,
                    run.color or color,
                    gid_map=run_metrics.gid_map,
                )
            y -= line.height

        stream.end_marked()

    def _draw_footnote_area(self, stream, placed, page_index, root, registry) -> None:
        """Render one bottom-anchored footnote, with a separator when first."""
        block = placed.block
        element = block.element
        style = block.style

        if placed.separator:
            rule_y = placed.y + 3.0
            stream.begin_artifact()
            stream.line(
                placed.x,
                rule_y,
                placed.x + placed.width * 0.3,
                rule_y,
                color="d6d3d1",
                width=0.5,
            )
            stream.end_marked()

        note_el = StructureElement(tag="Note")
        root.children.append(note_el)
        mcid = stream.next_mcid()
        note_el.add_mcid(page_index, mcid)
        stream.begin_marked("Note", mcid)

        metrics, size, key = self._resolve_font(style, None, registry)
        color = style.require("color")
        marker = element.marker or "*"
        marker_width = metrics.text_width(marker + " ", size)

        y = placed.y
        first_ascent = block.lines[0].ascent if block.lines else metrics.ascent(size)
        stream.text_line(
            marker,
            key,
            size,
            placed.x,
            y - first_ascent,
            color,
            gid_map=metrics.gid_map,
        )

        for line in block.lines:
            baseline = y - line.ascent
            for text, run, offset in line.fragments:
                run_metrics, run_size, run_key = self._resolve_font(
                    style, run, registry
                )
                stream.text_line(
                    text,
                    run_key,
                    run_size,
                    placed.x + marker_width + offset,
                    baseline,
                    run.color or color,
                    kern_pairs=run_metrics.kern_pairs(text),
                    gid_map=run_metrics.gid_map,
                )
            y -= line.height
        stream.end_marked()

    def _draw_callout(
        self,
        stream,
        placed,
        page_index,
        root,
        registry,
        page_content_width: float = 468.0,
    ) -> None:
        element = placed.block.element
        style = placed.block.style

        div_el = StructureElement(tag="Div")
        root.children.append(div_el)

        mcid = stream.next_mcid()
        div_el.add_mcid(page_index, mcid)

        padding = 10.0
        border_width = 3.0

        stream.begin_artifact("Background")
        stream.rect(
            placed.x,
            placed.y - placed.height,
            page_content_width,
            placed.height,
            fill=element.background,
        )
        stream.rect(
            placed.x,
            placed.y - placed.height,
            border_width,
            placed.height,
            fill=element.border_color,
        )
        stream.end_marked()

        stream.begin_marked("Div", mcid)

        metrics, size, key = self._resolve_font(style, None, registry)
        color = style.require("color")
        content_x = placed.x + padding + border_width

        y = placed.y - padding

        if element.icon:
            icon_size = size * 1.2
            stream.text_line(
                element.icon,
                key,
                icon_size,
                content_x,
                y - metrics.ascent(icon_size),
                element.border_color,
                gid_map=metrics.gid_map,
            )
            content_x += icon_size + 4.0

        for line in placed.lines:
            baseline = y - line.ascent
            for text, run, offset in line.fragments:
                run_metrics, run_size, run_key = self._resolve_font(
                    style, run, registry
                )
                stream.text_line(
                    text,
                    run_key,
                    run_size,
                    content_x + offset,
                    baseline,
                    run.color or color,
                    gid_map=run_metrics.gid_map,
                )
            y -= line.height

        stream.end_marked()

    def _draw_code_block(
        self,
        stream,
        placed,
        page_index,
        root,
        registry,
        page_content_width: float = 468.0,
    ) -> None:
        from .code_highlight import (
            THEME_BACKGROUNDS,
            colorize,
            tokenize,
            wrap_colored,
        )

        element = placed.block.element
        style = placed.block.style
        code_size = style.require("font_size") * 0.85

        metrics = self.fonts.resolve("Courier", bold=False, italic=False)
        key = self._font_key(metrics, registry)
        line_height = metrics.line_height(code_size, 1.4)
        padding = 10.0

        bg_color = THEME_BACKGROUNDS.get(element.theme, "1e1e1e")
        content_width = page_content_width

        lines = element.code.split("\n")
        gutter_width = 0.0
        if element.line_numbers:
            max_num = str(element.start_line + len(lines) - 1)
            gutter_width = metrics.text_width(max_num + "  ", code_size)

        max_text_width = content_width - 2 * padding - gutter_width

        def _mw(text: str) -> float:
            return metrics.text_width(text, code_size)

        line_rows = []
        max_row_width = 0.0
        for line_text in lines:
            colored = colorize(tokenize(line_text, element.language), element.theme)
            rows = wrap_colored(colored, _mw, max_text_width) or [[]]
            line_rows.append(rows)
            for segments in rows:
                row_width = sum(_mw(text) for text, _ in segments)
                if row_width > max_row_width:
                    max_row_width = row_width

        box_width = min(content_width, gutter_width + max_row_width + 2 * padding)

        stream.begin_artifact("Background")
        stream.rect(
            placed.x,
            placed.y - placed.height,
            box_width,
            placed.height,
            fill=bg_color,
        )
        stream.end_marked()

        code_el = StructureElement(tag="Code")
        root.children.append(code_el)
        mcid = stream.next_mcid()
        code_el.add_mcid(page_index, mcid)
        stream.begin_marked("Code", mcid)

        y = placed.y - padding
        for i, rows in enumerate(line_rows):
            line_num = element.start_line + i

            for r, segments in enumerate(rows):
                baseline = y - metrics.ascent(code_size)

                if element.highlight_lines and line_num in element.highlight_lines:
                    stream.save()
                    stream.rect(
                        placed.x,
                        y - line_height,
                        box_width,
                        line_height,
                        fill="ffffff",
                    )
                    stream.restore()

                if element.line_numbers and r == 0:
                    num_str = str(line_num)
                    num_width = metrics.text_width(num_str, code_size)
                    num_x = (
                        placed.x
                        + padding
                        + gutter_width
                        - num_width
                        - metrics.text_width("  ", code_size)
                    )
                    stream.text_line(
                        num_str,
                        key,
                        code_size,
                        num_x,
                        baseline,
                        "6a737d",
                        gid_map=metrics.gid_map,
                    )

                x = placed.x + padding + gutter_width
                for text, color in segments:
                    if not text:
                        continue
                    stream.text_line(
                        text,
                        key,
                        code_size,
                        x,
                        baseline,
                        color,
                        gid_map=metrics.gid_map,
                    )
                    x += metrics.text_width(text, code_size)

                y -= line_height

        stream.end_marked()

        if element.caption:
            body_metrics, body_size, body_key = self._resolve_font(
                style, None, registry
            )
            cap_size = body_size * 0.85
            cap_y = placed.y - placed.height + cap_size + 2.0
            cap_color = style.require("color")
            stream.text_line(
                element.caption,
                body_key,
                cap_size,
                placed.x,
                cap_y - cap_size,
                cap_color,
                gid_map=body_metrics.gid_map,
            )

    def _draw_math(
        self,
        stream,
        placed,
        page_index,
        root,
        registry,
        page_content_width: float = 468.0,
    ) -> None:
        from .math_render import (
            MathExpression,
            render_math,
            parse_math,
            MathLayoutEngine,
        )

        element = placed.block.element
        style = placed.block.style

        formula_el = StructureElement(tag="Formula")
        root.children.append(formula_el)

        mcid = stream.next_mcid()
        formula_el.add_mcid(page_index, mcid)
        stream.begin_marked("Formula", mcid)

        metrics, size, key = self._resolve_font(style, None, registry)
        color = style.require("color")

        if element.display:
            size *= 1.2

        italic_metrics = self.fonts.resolve(
            style.require("font_family"), bold=False, italic=True
        )
        italic_key = self._font_key(italic_metrics, registry)

        symbol_metrics = self.fonts.resolve("Symbol")
        symbol_key = self._font_key(symbol_metrics, registry)

        expr = MathExpression(source=element.source, display=element.display)
        baseline_y = placed.y - size
        content_width = page_content_width

        node = parse_math(element.source)
        engine = MathLayoutEngine(base_size=size)
        layout = engine.layout(node)

        mathalpha_key = None
        mathalpha_metrics = None
        if any(box.alpha for box in layout.boxes):
            from .bundled_fonts import bundled_font_path

            if not self.fonts.is_available("Emboss Math"):
                self.fonts.register("Emboss Math", bundled_font_path("Emboss Math"))
            mathalpha_metrics = self.fonts.resolve("Emboss Math")
            mathalpha_key = self._font_key(mathalpha_metrics, registry)

        x = placed.x
        if element.display:
            x = placed.x + (content_width - layout.width) / 2

        render_math(
            stream,
            expr,
            x,
            baseline_y,
            key,
            size,
            color,
            italic_key=italic_key,
            symbol_key=symbol_key,
            mathalpha_key=mathalpha_key,
            mathalpha_metrics=mathalpha_metrics,
        )

        if getattr(element, "number", False):
            num_text = element.tag or f"({getattr(element, '_assigned_number', 1)})"
            num_width = metrics.text_width(num_text, size)
            num_x = placed.x + content_width - num_width
            center = baseline_y + (layout.height - layout.depth) / 2
            num_y = center - metrics.ascent(size) / 2
            metrics.note_usage(num_text)
            stream.text_line(
                num_text,
                key,
                size,
                num_x,
                num_y,
                color,
                gid_map=metrics.gid_map,
            )

        if element.caption:
            cap_size = size * 0.7
            cap_y = baseline_y - layout.depth - cap_size - 4.0
            cap_width = metrics.text_width(element.caption, cap_size)
            cap_x = placed.x + (content_width - cap_width) / 2
            stream.text_line(
                element.caption,
                key,
                cap_size,
                cap_x,
                cap_y,
                color,
                gid_map=metrics.gid_map,
            )

        stream.end_marked()

    def _draw_bibliography(self, stream, placed, page_index, root, registry) -> None:
        block = placed.block
        element = block.element
        style = block.style
        indent = style.require("indent_left")

        bib_el = StructureElement(tag="Div")
        root.children.append(bib_el)

        heading_style = self.source.stylesheet.resolved(
            self.source.stylesheet.for_heading(element.heading_level),
            element.style,
        )

        lines = list(placed.lines)
        groups = block.line_groups or [("entry", len(lines))]

        y = placed.y
        position = 0
        for kind, count in groups:
            if position >= len(lines):
                break
            group_lines = lines[position : position + count]
            position += count

            if kind == "title":
                group_style = heading_style
                tag = f"H{element.heading_level}"
                x_base = placed.x
            else:
                group_style = style
                tag = "P"
                x_base = placed.x + indent
            group_color = group_style.require("color")

            group_el = StructureElement(tag=tag)
            bib_el.children.append(group_el)
            mcid = stream.next_mcid()
            group_el.add_mcid(page_index, mcid)
            stream.begin_marked(tag, mcid)

            for line in group_lines:
                baseline = y - line.ascent
                for text, run, offset in line.fragments:
                    run_metrics, run_size, run_key = self._resolve_font(
                        group_style, run, registry
                    )
                    stream.text_line(
                        text,
                        run_key,
                        run_size,
                        x_base + offset,
                        baseline,
                        run.color or group_color,
                        kern_pairs=run_metrics.kern_pairs(text),
                        gid_map=run_metrics.gid_map,
                    )
                y -= line.height
            stream.end_marked()

    def _draw_glossary(self, stream, placed, page_index, root, registry) -> None:
        """Draw a glossary's title and term/definition entries as paragraphs.

        Runs already carry their own weight, size, and color (baked in at
        measurement), so this loop resolves fonts per-fragment exactly like
        a plain paragraph, grouped one structure element per entry.
        """
        block = placed.block
        style = block.style

        div_el = StructureElement(tag="Div")
        root.children.append(div_el)

        lines = list(placed.lines)
        groups = block.line_groups or [("entry", len(lines))]

        y = placed.y
        position = 0
        for _kind, count in groups:
            if position >= len(lines):
                break
            group_lines = lines[position : position + count]
            position += count

            group_el = StructureElement(tag="P")
            div_el.children.append(group_el)
            mcid = stream.next_mcid()
            group_el.add_mcid(page_index, mcid)
            stream.begin_marked("P", mcid)

            for line in group_lines:
                baseline = y - line.ascent
                for text, run, offset in line.fragments:
                    run_metrics, run_size, run_key = self._resolve_font(
                        style, run, registry
                    )
                    stream.text_line(
                        text,
                        run_key,
                        run_size,
                        placed.x + offset,
                        baseline,
                        run.color or style.require("color"),
                        kern_pairs=run_metrics.kern_pairs(text),
                        gid_map=run_metrics.gid_map,
                    )
                y -= line.height
            stream.end_marked()

    def _draw_index(self, stream, placed, page_index, root, registry) -> None:
        """Draw an index's title, then its two columns of term/page entries."""
        data = placed.block.extras["index"]
        style = placed.block.style
        color = style.require("color")

        div = StructureElement(tag="Div")
        root.children.append(div)

        title_para = StructureElement(tag="P")
        div.children.append(title_para)
        mcid = stream.next_mcid()
        title_para.add_mcid(page_index, mcid)
        stream.begin_marked("P", mcid)
        y = self._emit_lines(
            stream, data["title_lines"], placed.x, placed.y, registry, style, color
        )
        stream.end_marked()

        col_w = data["col_w"]
        gap = data["gap"]
        for col_index, col_lines in enumerate((data["left"], data["right"])):
            if not col_lines:
                continue
            x = placed.x + col_index * (col_w + gap)
            para = StructureElement(tag="P")
            div.children.append(para)
            mcid = stream.next_mcid()
            para.add_mcid(page_index, mcid)
            stream.begin_marked("P", mcid)
            self._emit_lines(stream, col_lines, x, y, registry, style, color)
            stream.end_marked()

    # -- front matter --

    def _emit_lines(
        self, stream, lines, x_base, y, registry, style, default_color
    ) -> float:
        """Draw laid-out lines from top `y`; returns the y after the block."""
        for line in lines:
            baseline = y - line.ascent
            for text, run, offset in line.fragments:
                metrics, size, key = self._resolve_font(style, run, registry)
                sc = getattr(run, "_sc_actual", None)
                if sc is not None:
                    stream.raw(self._actual_text_bdc(sc))
                stream.text_line(
                    text,
                    key,
                    size,
                    x_base + offset,
                    baseline,
                    run.color or default_color,
                    kern_pairs=metrics.kern_pairs(text),
                    gid_map=metrics.gid_map,
                )
                if sc is not None:
                    stream.raw(b"EMC")
            y -= line.height
        return y

    def _draw_cover(
        self, stream, placed, page_index, root, registry, page_spec
    ) -> None:
        parts = placed.block.extras.get("cover", [])
        style = placed.block.style
        page = page_spec
        left = page.margin_left
        width = placed.block.extras.get("width", page.content_width)
        color = style.require("color")

        total = 0.0
        for part in parts:
            if "lines" in part:
                total += sum(line.height for line in part["lines"])
            elif "rule" in part:
                total += 2.0
            total += part.get("gap", 0.0)

        div = StructureElement(tag="Div")
        root.children.append(div)

        y = (page.height + total) / 2.0
        for part in parts:
            if "rule" in part:
                rule_w = LayoutEngine.COVER_RULE_WIDTH
                rx = left + (width - rule_w) / 2.0
                stream.begin_artifact()
                stream.line(
                    rx, y - 1.0, rx + rule_w, y - 1.0, color=part["rule"], width=1.5
                )
                stream.end_marked()
                y -= 2.0
            else:
                para = StructureElement(tag="P")
                div.children.append(para)
                mcid = stream.next_mcid()
                para.add_mcid(page_index, mcid)
                stream.begin_marked("P", mcid)
                y = self._emit_lines(
                    stream, part["lines"], left, y, registry, style, color
                )
                stream.end_marked()
            y -= part.get("gap", 0.0)

    def _draw_abstract(self, stream, placed, page_index, root, registry) -> None:
        data = placed.block.extras["abstract"]
        style = placed.block.style
        color = style.require("color")
        x = placed.x + data["indent"]
        y = placed.y

        div = StructureElement(tag="Div")
        root.children.append(div)
        for key in ("label", "body", "keywords"):
            lines = data[key]
            if not lines:
                continue
            para = StructureElement(tag="P")
            div.children.append(para)
            mcid = stream.next_mcid()
            para.add_mcid(page_index, mcid)
            stream.begin_marked("P", mcid)
            y = self._emit_lines(stream, lines, x, y, registry, style, color)
            stream.end_marked()
            if key == "label":
                y -= 2.0
            elif key == "body" and data["keywords"]:
                y -= 6.0

    def _draw_authors(self, stream, placed, page_index, root, registry) -> None:
        data = placed.block.extras["authors"]
        style = placed.block.style
        color = style.require("color")
        col_w = data["col_w"]

        div = StructureElement(tag="Div")
        root.children.append(div)
        y = placed.y
        for row in data["rows"]:
            row_h = max(sum(line.height for line in cell) for cell in row)
            for ci, cell in enumerate(row):
                cell_x = placed.x + ci * col_w + 6.0
                para = StructureElement(tag="P")
                div.children.append(para)
                mcid = stream.next_mcid()
                para.add_mcid(page_index, mcid)
                stream.begin_marked("P", mcid)
                self._emit_lines(stream, cell, cell_x, y, registry, style, color)
                stream.end_marked()
            y -= row_h + 10.0

    def _draw_pullquote(self, stream, placed, page_index, root, registry) -> None:
        data = placed.block.extras["pullquote"]
        style = placed.block.style
        color = style.require("color")
        x = placed.x + data["indent"]
        usable = data["usable"]

        quote_el = StructureElement(tag="BlockQuote")
        root.children.append(quote_el)

        rule_w = min(48.0, usable * 0.25)
        rule_x = x + (usable - rule_w) / 2.0
        stream.begin_artifact()
        stream.line(
            rule_x,
            placed.y - 4.0,
            rule_x + rule_w,
            placed.y - 4.0,
            color=data["accent"],
            width=2.0,
        )
        stream.end_marked()

        mcid = stream.next_mcid()
        quote_el.add_mcid(page_index, mcid)
        stream.begin_marked("BlockQuote", mcid)
        y = placed.y - 12.0
        y = self._emit_lines(stream, data["lines"], x, y, registry, style, color)
        if data["attr"]:
            y -= 6.0
            self._emit_lines(stream, data["attr"], x, y, registry, style, color)
        stream.end_marked()

    def _draw_stat_tiles(self, stream, placed, page_index, root, registry) -> None:
        data = placed.block.extras["stattiles"]
        style = placed.block.style
        color = style.require("color")
        tile_w = data["tile_w"]
        gap = data["gap"]
        pad = data["pad"]
        tile_h = data["tile_h"]

        div = StructureElement(tag="Div")
        root.children.append(div)
        top = placed.y
        for i, tile in enumerate(data["tiles"]):
            tx = placed.x + i * (tile_w + gap)
            stream.begin_artifact()
            stream.rect(
                tx,
                top - tile_h,
                tile_w,
                tile_h,
                stroke=data["accent"],
                line_width=0.8,
            )
            stream.end_marked()

            tile_div = StructureElement(tag="Div")
            div.children.append(tile_div)
            mcid = stream.next_mcid()
            tile_div.add_mcid(page_index, mcid)
            stream.begin_marked("Div", mcid)
            inner_x = tx + pad
            y = top - pad
            y = self._emit_lines(
                stream, tile["value"], inner_x, y, registry, style, data["accent"]
            )
            y = self._emit_lines(
                stream, tile["label"], inner_x, y, registry, style, color
            )
            if tile["delta"]:
                self._emit_lines(
                    stream,
                    tile["delta"],
                    inner_x,
                    y,
                    registry,
                    style,
                    tile["delta_color"],
                )
            stream.end_marked()

    def _draw_toc(self, stream, placed, page_index, root, registry) -> None:
        style = placed.block.style
        color = style.require("color")

        toc_el = StructureElement(tag="Div")
        root.children.append(toc_el)

        y = placed.y
        for line in placed.lines:
            baseline = y - line.ascent
            para = StructureElement(tag="P")
            toc_el.children.append(para)
            mcid = stream.next_mcid()
            para.add_mcid(page_index, mcid)
            stream.begin_marked("P", mcid)
            for text, run, offset in line.fragments:
                metrics, size, key = self._resolve_font(style, run, registry)
                x = placed.x + offset
                stream.text_line(
                    text,
                    key,
                    size,
                    x,
                    baseline,
                    run.color or color,
                    kern_pairs=metrics.kern_pairs(text),
                    gid_map=metrics.gid_map,
                )
                if run.link:
                    rect = [
                        x,
                        baseline + metrics.descent(size),
                        x + metrics.text_width(text, size),
                        baseline + metrics.ascent(size),
                    ]
                    self._link_records.append((page_index, rect, run.link, para))
            stream.end_marked()
            y -= line.height

    def _draw_field_label(self, stream, lines, x, y, page_index, root, registry, style):
        """Draw wrapped label lines tagged /Lbl; returns y after the label."""
        if not lines:
            return y
        color = style.require("color")
        label_el = StructureElement(tag="Lbl")
        root.children.append(label_el)
        mcid = stream.next_mcid()
        label_el.add_mcid(page_index, mcid)
        stream.begin_marked("Lbl", mcid)
        y = self._emit_lines(stream, lines, x, y, registry, style, color)
        stream.end_marked()
        return y

    def _draw_text_field(self, stream, placed, page_index, root, registry) -> None:
        """Draw a text field's label, input box, and default-value preview.

        The visible box/preview is an Artifact: the real, interactive
        content is the AcroForm widget built later in `_build_form_field_
        widgets`, which reuses this call's recorded rect and the /Form
        structure element appended here.
        """
        element = placed.block.element
        style = placed.block.style
        data = placed.block.extras["formfield"]
        color = style.require("color")

        y = self._draw_field_label(
            stream,
            data["label_lines"],
            placed.x,
            placed.y,
            page_index,
            root,
            registry,
            style,
        )
        if data["label_lines"]:
            y -= LayoutEngine.FORM_FIELD_LABEL_GAP

        box_h = data["box_height"]
        box_w = data["box_width"]
        box_y = y - box_h

        stream.begin_artifact("Background")
        stream.rect(placed.x, box_y, box_w, box_h, stroke="a8a29e", line_width=0.75)
        if element.default:
            metrics, size, key = self._resolve_font(style, None, registry)
            preview_size = size * 0.95
            line_h = metrics.line_height(preview_size, 1.3)
            if element.multiline:
                text_y = box_y + box_h - preview_size * 1.05
                avail_lines = max(1, int(box_h // line_h))
                for line_text in element.default.split("\n")[:avail_lines]:
                    stream.text_line(
                        line_text,
                        key,
                        preview_size,
                        placed.x + 6.0,
                        text_y,
                        color,
                        gid_map=metrics.gid_map,
                    )
                    text_y -= line_h
            else:
                baseline = box_y + (box_h - preview_size) / 2.0 + preview_size * 0.18
                stream.text_line(
                    element.default,
                    key,
                    preview_size,
                    placed.x + 6.0,
                    baseline,
                    color,
                    gid_map=metrics.gid_map,
                )
        stream.end_marked()

        field_el = StructureElement(tag="Form")
        field_el.alt_text = element.label or element.name
        root.children.append(field_el)
        rect = [placed.x, box_y, placed.x + box_w, box_y + box_h]
        self._formfield_records.append((page_index, rect, element, field_el))

    def _draw_dropdown_field(self, stream, placed, page_index, root, registry) -> None:
        """Draw a dropdown field's label, input box, default preview, and arrow."""
        element = placed.block.element
        style = placed.block.style
        data = placed.block.extras["formfield"]
        color = style.require("color")

        y = self._draw_field_label(
            stream,
            data["label_lines"],
            placed.x,
            placed.y,
            page_index,
            root,
            registry,
            style,
        )
        if data["label_lines"]:
            y -= LayoutEngine.FORM_FIELD_LABEL_GAP

        box_h = data["box_height"]
        box_w = data["box_width"]
        box_y = y - box_h

        stream.begin_artifact("Background")
        stream.rect(placed.x, box_y, box_w, box_h, stroke="a8a29e", line_width=0.75)
        if element.default:
            metrics, size, key = self._resolve_font(style, None, registry)
            preview_size = size * 0.95
            baseline = box_y + (box_h - preview_size) / 2.0 + preview_size * 0.18
            stream.text_line(
                element.default,
                key,
                preview_size,
                placed.x + 6.0,
                baseline,
                color,
                gid_map=metrics.gid_map,
            )
        self._draw_dropdown_arrow(
            stream, placed.x + box_w - 14.0, box_y + box_h / 2.0, color
        )
        stream.end_marked()

        field_el = StructureElement(tag="Form")
        field_el.alt_text = element.label or element.name
        root.children.append(field_el)
        rect = [placed.x, box_y, placed.x + box_w, box_y + box_h]
        self._formfield_records.append((page_index, rect, element, field_el))

    @staticmethod
    def _draw_dropdown_arrow(stream, cx: float, cy: float, color) -> None:
        """Draw a small downward-pointing triangle marking a choice affordance."""
        stream.set_fill(color)
        half = 3.0
        stream.raw(
            b" ".join([stream._num(cx - half), stream._num(cy + half * 0.6), b"m"])
        )
        stream.raw(
            b" ".join([stream._num(cx + half), stream._num(cy + half * 0.6), b"l"])
        )
        stream.raw(b" ".join([stream._num(cx), stream._num(cy - half * 0.6), b"l"]))
        stream.raw(b"h f")

    def _draw_checkbox_field(self, stream, placed, page_index, root, registry) -> None:
        """Draw a checkbox field's square and label.

        The visible tick is an Artifact matching the AcroForm widget's own
        /AP appearance built in `_build_form_field_widgets`; the widget
        itself is the real, interactive control.
        """
        element = placed.block.element
        style = placed.block.style
        data = placed.block.extras["formfield"]
        color = style.require("color")
        box = data["box"]

        top = placed.y
        box_y = top - box
        stream.begin_artifact("Background")
        self._draw_checkbox(stream, placed.x, box_y, color, element.checked, size=box)
        stream.end_marked()

        label_lines = data["label_lines"]
        if label_lines:
            label_x = placed.x + box + LayoutEngine.FORM_CHECKBOX_GAP
            self._draw_field_label(
                stream, label_lines, label_x, top, page_index, root, registry, style
            )

        field_el = StructureElement(tag="Form")
        field_el.alt_text = element.label or element.name
        root.children.append(field_el)
        rect = [placed.x, box_y, placed.x + box, box_y + box]
        self._formfield_records.append((page_index, rect, element, field_el))

    def _draw_svg(
        self,
        stream,
        placed,
        page_index,
        root,
        registry,
        page_content_width: float = 468.0,
    ) -> None:
        from .svg import parse_svg, render_svg

        element = placed.block.element
        style = placed.block.style

        fig_el = StructureElement(tag="Figure")
        if element.alt_text:
            fig_el.alt_text = element.alt_text
        root.children.append(fig_el)

        mcid = stream.next_mcid()
        fig_el.add_mcid(page_index, mcid)
        stream.begin_marked("Figure", mcid)

        svg = parse_svg(element.source)
        display_w = element.width or min(svg.width, page_content_width)
        if display_w > page_content_width:
            display_w = page_content_width
        scale = display_w / svg.aspect_width if svg.aspect_width else 1.0
        display_h = element.height or svg.aspect_height * scale

        x = placed.x
        if element.align == "center":
            x = placed.x + (page_content_width - display_w) / 2
        elif element.align == "right":
            x = placed.x + page_content_width - display_w

        render_svg(stream, svg, x, placed.y, display_w, display_h)

        if element.caption:
            metrics, size, key = self._resolve_font(style, None, registry)
            cap_size = size * 0.85
            cap_y = placed.y - display_h - cap_size - 2.0
            color = style.require("color")
            cap_width = metrics.text_width(element.caption, cap_size)
            cap_x = x + (display_w - cap_width) / 2
            stream.text_line(
                element.caption,
                key,
                cap_size,
                cap_x,
                cap_y,
                color,
                gid_map=metrics.gid_map,
            )

        stream.end_marked()

    def _get_watermark_image_ref(self, legal) -> str:
        if getattr(self, "_watermark_image_ref", None) is None:
            self._watermark_image_ref = ("ImWatermark", legal.watermark_image)
        return self._watermark_image_ref[0]

    def _draw_image_watermark(self, stream, page_spec, legal) -> None:
        from .images import load_image

        img = load_image(legal.watermark_image)
        name = self._get_watermark_image_ref(legal)

        import math

        display_w = img.width * legal.watermark_image_scale
        display_h = img.height * legal.watermark_image_scale
        angle = 52.0
        radians = math.radians(angle)
        cos, sin = math.cos(radians), math.sin(radians)
        cx = page_spec.width / 2.0
        cy = page_spec.height / 2.0

        stream.save()
        stream.begin_artifact("Watermark")
        stream.set_ext_gstate("GSwm")
        stream.raw(b" ".join([b"1 0 0 1", stream._num(cx), stream._num(cy), b"cm"]))
        stream.raw(
            b" ".join(
                [
                    stream._num(cos),
                    stream._num(sin),
                    stream._num(-sin),
                    stream._num(cos),
                    b"0 0 cm",
                ]
            )
        )
        stream.raw(
            b" ".join(
                [
                    b"1 0 0 1",
                    stream._num(-display_w / 2.0),
                    stream._num(-display_h / 2.0),
                    b"cm",
                ]
            )
        )
        stream.raw(
            b" ".join(
                [stream._num(display_w), b"0 0", stream._num(display_h), b"0 0 cm"]
            )
        )
        stream.raw(f"/{name} Do".encode("ascii"))
        stream.end_marked()
        stream.restore()

    def _draw_watermark(self, stream, page_spec, sheet, legal, registry) -> None:
        metrics = self.fonts.resolve("Helvetica", bold=True)
        key = self._font_key(metrics, registry)
        size = 64.0
        width = metrics.text_width(legal.watermark, size)

        page = page_spec
        import math

        angle = 52.0
        radians = math.radians(angle)
        x = (page.width - width * math.cos(radians)) / 2.0
        y = (page.height - width * math.sin(radians)) / 2.0

        stream.save()
        stream.begin_artifact("Watermark")
        stream.set_ext_gstate("GSwm")
        stream.rotated_text(legal.watermark, key, size, x, y, "9a3412", angle)
        stream.end_marked()
        stream.restore()

    @staticmethod
    def _draw_hf_slots(
        stream,
        hf,
        font_key,
        size,
        color,
        metrics,
        gmap,
        left,
        right,
        y,
        expand,
        artifact_type,
    ):
        """Draw left / center / right slots for a HeaderFooter."""
        content_width = right - left
        for slot_text, align in [
            (hf.left, "left"),
            (hf.center, "center"),
            (hf.right, "right"),
        ]:
            if not slot_text:
                continue
            rendered = expand(slot_text)
            tw = metrics.text_width(rendered, size)
            if align == "left":
                x = left
            elif align == "center":
                x = left + (content_width - tw) / 2.0
            else:
                x = right - tw
            stream.begin_artifact(artifact_type)
            stream.text_line(rendered, font_key, size, x, y, color, gid_map=gmap)
            stream.end_marked()

    def _draw_running_content(
        self, stream, document, sheet, page, page_index, total, registry
    ) -> None:
        if getattr(page, "suppress_chrome", False):
            return
        style = sheet.resolved(sheet.header_footer)
        metrics, size, key = self._resolve_font(style, None, registry)
        color = style.require("color")
        spec = getattr(page, "spec", None) or document.page
        legal = document.legal

        gmap = metrics.gid_map
        mirrored = self._is_mirrored(document, page_index)
        if mirrored:
            content_left = spec.margin_right
            content_right = spec.width - spec.margin_left
        else:
            content_left = spec.margin_left
            content_right = spec.width - spec.margin_right

        header_y = spec.height - spec.margin_top + 22.0
        footer_y = spec.margin_bottom - 26.0

        page_label, pages_label = self._page_number_labels(document, page_index, total)
        titles = self._section_titles
        section = (
            titles[page_index] if page_index < len(titles) else document.title or ""
        )

        def expand(text: str) -> str:
            return (
                text.replace("{page}", page_label)
                .replace("{pages}", pages_label)
                .replace("{section}", section)
            )

        base_header = document.header if hasattr(document, "header") else None
        base_footer = document.footer if hasattr(document, "footer") else None
        hf_header = self._effective_hf(base_header, page_index, mirrored)
        hf_footer = self._effective_hf(base_footer, page_index, mirrored)

        if hf_header:
            h_size = hf_header.font_size or size
            h_color = hf_header.color or color
            if hf_header.font_family:
                h_metrics = self.fonts.resolve(hf_header.font_family)
                h_key = self._font_key(h_metrics, registry)
                h_gmap = h_metrics.gid_map
            else:
                h_metrics, h_key, h_gmap = metrics, key, gmap
            self._draw_hf_slots(
                stream,
                hf_header,
                h_key,
                h_size,
                h_color,
                h_metrics,
                h_gmap,
                content_left,
                content_right,
                header_y,
                expand,
                "Header",
            )
            if hf_header.separator_line:
                line_y = header_y - h_size * 0.5
                stream.begin_artifact()
                stream.line(
                    content_left,
                    line_y,
                    content_right,
                    line_y,
                    color=h_color,
                    width=0.5,
                )
                stream.end_marked()
        elif document.header_text and base_header is None:
            stream.begin_artifact("Header")
            stream.text_line(
                document.header_text,
                key,
                size,
                content_left,
                header_y,
                color,
                gid_map=gmap,
            )
            stream.end_marked()

        if hf_footer:
            f_size = hf_footer.font_size or size
            f_color = hf_footer.color or color
            if hf_footer.font_family:
                f_metrics = self.fonts.resolve(hf_footer.font_family)
                f_key = self._font_key(f_metrics, registry)
                f_gmap = f_metrics.gid_map
            else:
                f_metrics, f_key, f_gmap = metrics, key, gmap
            if hf_footer.separator_line:
                line_y = footer_y + f_size * 1.2
                stream.begin_artifact()
                stream.line(
                    content_left,
                    line_y,
                    content_right,
                    line_y,
                    color=f_color,
                    width=0.5,
                )
                stream.end_marked()
            self._draw_hf_slots(
                stream,
                hf_footer,
                f_key,
                f_size,
                f_color,
                f_metrics,
                f_gmap,
                content_left,
                content_right,
                footer_y,
                expand,
                "Footer",
            )
        elif document.footer_text and base_footer is None:
            stream.begin_artifact("Footer")
            stream.text_line(
                document.footer_text,
                key,
                size,
                content_left,
                footer_y,
                color,
                gid_map=gmap,
            )
            stream.end_marked()

        if document.page_numbers and base_footer is None:
            label = f"{page_label} of {pages_label}"
            width = metrics.text_width(label, size)
            stream.begin_artifact("Footer")
            stream.text_line(
                label,
                key,
                size,
                content_right - width,
                footer_y,
                color,
                gid_map=gmap,
            )
            stream.end_marked()

        if legal and legal.bates_prefix:
            number = legal.bates_start + page_index
            label = f"{legal.bates_prefix}{number:0{legal.bates_digits}d}"
            bates_size = legal.bates_font_size
            width = metrics.text_width(label, bates_size)
            if legal.bates_position == "bottom-left":
                x = spec.margin_left
                y = footer_y - 11.0
            elif legal.bates_position == "top-right":
                x = spec.width - spec.margin_right - width
                y = spec.height - spec.margin_top + 34.0
            else:
                x = spec.width - spec.margin_right - width
                y = footer_y - 11.0
            stream.begin_artifact("Footer")
            stream.text_line(
                label,
                key,
                bates_size,
                x,
                y,
                "44403c",
                gid_map=gmap,
            )
            stream.end_marked()

        if legal and legal.line_numbering:
            self._draw_line_numbers(
                stream, document, page, page_index, key, metrics, legal
            )

    def _draw_line_numbers(
        self, stream, document, page, page_index, key, metrics, legal
    ) -> None:
        """Number lines down the left margin, as court rules require.

        Numbering is positional: every line slot on the page is counted at
        a fixed pitch, so numbers stay aligned with the ruled margin and
        restart at the top of each page. That is what pleading paper does,
        rather than counting only lines that happen to carry text.
        """
        spec = getattr(page, "spec", None) or document.page
        size = legal.line_number_font_size
        color = "78716c"

        # Derive the pitch from body leading so numbers track the text.
        sheet = document.stylesheet
        body = sheet.resolved(sheet.body)
        body_metrics = self.fonts.resolve(
            body.require("font_family"),
            bold=body.require("bold"),
            italic=body.require("italic"),
        )
        pitch = body_metrics.line_height(
            body.require("font_size"), body.require("line_height")
        )
        if pitch <= 0:
            return

        slots = int(spec.content_height // pitch)
        x = spec.margin_left - 14.0

        gmap = metrics.gid_map
        stream.begin_artifact("LineNumber")
        for slot in range(slots):
            number = legal.line_number_start + slot
            label = str(number)
            width = metrics.text_width(label, size)
            y = spec.content_top - (slot + 1) * pitch + pitch * 0.25
            stream.text_line(
                label,
                key,
                size,
                x - width,
                y,
                color,
                gid_map=gmap,
            )
        stream.end_marked()
