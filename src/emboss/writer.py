"""The render pipeline.

    Document -> validate -> measure -> paginate -> render -> tag -> bytes

Every stage after validation is deterministic: no timestamps, no random
identifiers, no iteration over unordered collections. The same document
renders to the same bytes on any machine, which is what makes output
hash-verifiable for filings and diffable in CI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from .constraints import ConstraintValidator
from .crossref import CrossReferenceIndex
from .numbering import NumberingContext
from .layout.engine import LayoutEngine, PlacedBlock
from .pdf.assembler import PDFAssembler
from .pdf.fonts import build_font_resource
from .pdf.objects import PdfArray, PdfDict, PdfName, PdfRef, PdfStream
from .pdf.streams import ContentStream
from .pdf.tags import StructureElement, StructureTreeBuilder
from .spec import (
    BibliographyBlock,
    BlockQuote,
    BulletList,
    Callout,
    Chart,
    CodeBlock,
    Document,
    Footnote,
    Heading,
    HorizontalRule,
    Image,
    MathBlock,
    NumberedList,
    Paragraph,
    SvgBlock,
    Table,
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

    def __bytes__(self) -> bytes:
        return self.data


def render_document(
    document: Document, *, strict: bool = False, return_result: bool = False
):
    """Render a document to PDF bytes."""
    renderer = Renderer(document, strict=strict)
    result = renderer.run()
    return result if return_result else result.data


class Renderer:
    """Owns one render pass over one document."""

    def __init__(self, document: Document, strict: bool = False) -> None:
        self.fonts = document.fonts
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

    def run(self) -> RenderResult:
        validation = self.validator.validate(self.source).raise_if_failed()
        document = validation.document
        sheet = document.stylesheet

        hyphenator = Hyphenator(language=document.language)
        engine = LayoutEngine(self.fonts, sheet, hyphenator=hyphenator)

        content = list(document.content)
        content = self._resolve_references(document, content)
        content = self._prepend_title_block(document, sheet, content)

        width = document.page.content_width
        measured = [engine.measure(el, width) for el in content]
        pages = engine.paginate(measured, document.page)
        self._section_titles = self._collect_section_titles(document, pages)

        assembler = PDFAssembler()
        data = self._assemble(assembler, document, sheet, pages)

        return RenderResult(data=data, page_count=len(pages), issues=validation.issues)

    @staticmethod
    def _prepend_title_block(document, sheet, content: list) -> list:
        """Insert a title heading and author line before the first content."""
        if not document.title:
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

    _REF_PATTERN = re.compile(r"@([\w](?:[\w:.-]*[\w])?)")

    def _resolve_references(self, document, content: list) -> list:
        """Number captions, resolve @key tokens, and collect anchor keys."""
        auto_number = bool(getattr(document, "auto_number", True))
        number_sections = bool(getattr(document, "number_sections", False))

        section_numbers: dict = {}
        if number_sections:
            context = NumberingContext()
            for idx, element in enumerate(content):
                if isinstance(element, Heading):
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
                        element.title = f"{entry.label}: {element.title}"
                elif auto_number and getattr(element, "caption", None):
                    element.caption = f"{entry.label}: {element.caption}"
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
            if run.link or "@" not in run.text:
                out.append(run)
                continue
            pieces: list = []
            cursor = 0
            for match in self._REF_PATTERN.finditer(run.text):
                entry = index.get(match.group(1))
                if entry is None:
                    continue
                if match.start() > cursor:
                    pieces.append((run.text[cursor : match.start()], None))
                pieces.append((entry.label, entry.anchor))
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

        # Register fonts after rendering so usage is known for subsetting.
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
        if document.legal and document.legal.watermark:
            resources["ExtGState"] = self._watermark_gstate(assembler, document.legal)
        resources_ref = assembler.add(resources)

        struct_ref = None
        if document.tagged:
            builder = StructureTreeBuilder(assembler, page_refs)
            struct_ref = builder.build(root)

        for index, (page, page_id) in enumerate(zip(pages, page_ids)):
            page_dict = PdfDict()
            page_dict["Type"] = PdfName("Page")
            page_dict["Parent"] = PdfRef(pages_id)
            page_dict["MediaBox"] = PdfArray(
                [0, 0, document.page.width, document.page.height]
            )
            page_dict["Resources"] = resources_ref
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
            from .pdfa import pdfa_catalog_entries

            pdfa_entries = pdfa_catalog_entries(assembler, document)
            for key, value in pdfa_entries.items():
                catalog[key] = value
        elif document.tagged:
            from .pdfa import build_xmp_stream

            catalog["Metadata"] = build_xmp_stream(assembler, document, pdfa=False)

        if document.signatures:
            from .signing import (
                SignatureField,
                build_sig_field_dict,
                build_acroform,
            )

            sig_field_refs = []
            for sig in document.signatures:
                if isinstance(sig, dict):
                    sig = SignatureField(**sig)
                pidx = min(sig.page_index, len(page_refs) - 1)
                ref = build_sig_field_dict(assembler, sig, page_refs[pidx])
                sig_field_refs.append(ref)
            if sig_field_refs:
                catalog["AcroForm"] = build_acroform(sig_field_refs)

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
        return annots_by_page

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

        if legal and legal.watermark:
            self._draw_watermark(stream, document, sheet, legal, font_registry)

        page_blocks = page.blocks
        if self._is_mirrored(document, page_index):
            shift = document.page.margin_right - document.page.margin_left
            if shift:
                page_blocks = [
                    replace(placed, x=placed.x + shift) for placed in page.blocks
                ]

        for placed in page_blocks:
            element = placed.block.element
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
                    document.page.content_width,
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
                    document.page.content_width,
                )
            elif isinstance(element, MathBlock):
                self._draw_math(stream, placed, page_index, root, font_registry)
            elif isinstance(element, BibliographyBlock):
                self._draw_bibliography(stream, placed, page_index, root, font_registry)
            elif isinstance(element, SvgBlock):
                self._draw_svg(
                    stream,
                    placed,
                    page_index,
                    root,
                    font_registry,
                    document.page.content_width,
                )
            elif isinstance(element, HorizontalRule):
                self._draw_rule(stream, placed, document, sheet)

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
        return stream.to_bytes(), root

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

    def _draw_strikethrough(
        self, stream, metrics, size: float, x: float, baseline: float, text, color
    ) -> None:
        """Strike a fragment with a rule above the baseline, in text color."""
        width = metrics.text_width(text, size)
        if width <= 0:
            return
        y = baseline + size * 0.28
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

        for line in placed.lines:
            baseline = y - line.ascent

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
                stream.text_line(
                    text,
                    key,
                    size,
                    x,
                    baseline,
                    color,
                    kern_pairs=metrics.kern_pairs(text),
                    gid_map=metrics.gid_map,
                )
                if run.strikethrough:
                    self._draw_strikethrough(
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
            y -= line.height

        stream.end_marked()

    @staticmethod
    def _draw_checkbox(stream, x: float, baseline: float, color, checked) -> None:
        """Draw a 7pt checkbox outline plus a two-segment tick when checked."""
        stream.rect(x, baseline, 7.0, 7.0, stroke=color, line_width=0.7)
        if checked:
            stream.set_stroke(color)
            stream.set_line_width(0.9)
            stream.raw(
                b" ".join([stream._num(x + 1.4), stream._num(baseline + 3.5), b"m"])
            )
            stream.raw(
                b" ".join([stream._num(x + 2.9), stream._num(baseline + 1.7), b"l"])
            )
            stream.raw(
                b" ".join([stream._num(x + 5.6), stream._num(baseline + 5.3), b"l"])
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
        bullet_width = metrics.text_width(element.bullet + " ", size)
        indent = style.require("indent_left")
        color = style.require("color")
        checked = list(getattr(element, "checked", None) or [])

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
            y -= line.height

        stream.end_marked()

    def _draw_table(self, stream, placed, page_index, root, registry, sheet) -> None:
        block = placed.block
        layout = block.table
        if layout is None:
            return

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

        y = placed.y

        if layout.header_lines and placed.include_table_header:
            head = StructureElement(tag="THead")
            table_el.children.append(head)
            row_el = StructureElement(tag="TR")
            head.children.append(row_el)

            header_style = sheet.resolved(sheet.table_header)
            for column, lines in enumerate(layout.header_lines):
                cell_el = StructureElement(tag="TH", scope="Column")
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
                    widths[column] - 2 * pad_x,
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

            for column, lines in enumerate(cells):
                cell_el = StructureElement(tag="TD")
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
                    widths[column] - 2 * pad_x,
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

        caption = block.element.caption
        is_last_segment = bool(
            row_indices and row_indices[-1] == len(layout.row_heights) - 1
        )
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

    def _draw_rule(self, stream, placed, document, sheet) -> None:
        element = placed.block.element
        stream.begin_artifact()
        stream.line(
            placed.x,
            placed.y,
            placed.x + document.page.content_width,
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
        from .charts import ChartData, ChartSpec, render_chart, series_summary

        element = placed.block.element
        style = placed.block.style

        fig_el = StructureElement(tag="Figure")
        fig_el.alt_text = element.alt_text or series_summary(element)
        root.children.append(fig_el)

        mcid = stream.next_mcid()
        fig_el.add_mcid(page_index, mcid)
        stream.begin_marked("Figure", mcid)

        _, size, key = self._resolve_font(style, None, registry)

        data = ChartData(
            labels=list(element.labels),
            values=list(element.values),
            colors=list(element.colors) if element.colors else None,
            title=element.title,
        )
        spec = ChartSpec(
            chart_type=element.chart_type,
            data=data,
            width=element.width,
            height=element.height,
        )
        render_chart(stream, spec, placed.x, placed.y, key, size * 0.8)

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
        from .code_highlight import tokenize, colorize, THEME_BACKGROUNDS

        element = placed.block.element
        style = placed.block.style
        code_size = style.require("font_size") * 0.85

        metrics = self.fonts.resolve("Courier", bold=False, italic=False)
        key = self._font_key(metrics, registry)
        line_height = metrics.line_height(code_size, 1.4)
        padding = 10.0

        bg_color = THEME_BACKGROUNDS.get(element.theme, "1e1e1e")
        content_width = page_content_width
        stream.begin_artifact("Background")
        stream.rect(
            placed.x,
            placed.y - placed.height,
            content_width,
            placed.height,
            fill=bg_color,
        )
        stream.end_marked()

        code_el = StructureElement(tag="Code")
        root.children.append(code_el)
        mcid = stream.next_mcid()
        code_el.add_mcid(page_index, mcid)
        stream.begin_marked("Code", mcid)

        lines = element.code.split("\n")
        gutter_width = 0.0
        if element.line_numbers:
            max_num = str(element.start_line + len(lines) - 1)
            gutter_width = metrics.text_width(max_num + "  ", code_size)

        max_text_width = content_width - 2 * padding - gutter_width
        ellipsis_w = metrics.text_width("...", code_size)

        y = placed.y - padding
        for i, line_text in enumerate(lines):
            line_num = element.start_line + i
            baseline = y - metrics.ascent(code_size)

            if element.highlight_lines and line_num in element.highlight_lines:
                stream.save()
                stream.rect(
                    placed.x,
                    y - line_height,
                    content_width,
                    line_height,
                    fill="ffffff",
                )
                stream.restore()

            if element.line_numbers:
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

            tokens = tokenize(line_text, element.language)
            colored = colorize(tokens, element.theme)

            x = placed.x + padding + gutter_width
            x_start = x
            truncated = False
            for text, color in colored:
                if not text or truncated:
                    continue
                token_w = metrics.text_width(text, code_size)
                if (x - x_start) + token_w > max_text_width - ellipsis_w:
                    avail = max_text_width - ellipsis_w - (x - x_start)
                    clipped = ""
                    for ch in text:
                        ch_w = metrics.text_width(ch, code_size)
                        if avail < ch_w:
                            break
                        clipped += ch
                        avail -= ch_w
                    if clipped:
                        stream.text_line(
                            clipped,
                            key,
                            code_size,
                            x,
                            baseline,
                            color,
                            gid_map=metrics.gid_map,
                        )
                        x += metrics.text_width(clipped, code_size)
                    stream.text_line(
                        "...",
                        key,
                        code_size,
                        x,
                        baseline,
                        "6a737d",
                        gid_map=metrics.gid_map,
                    )
                    truncated = True
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
                x += token_w

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

    def _draw_math(self, stream, placed, page_index, root, registry) -> None:
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
        content_width = style.require("font_size") * 30

        node = parse_math(element.source)
        engine = MathLayoutEngine(base_size=size)
        layout = engine.layout(node)

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

    def _draw_watermark(self, stream, document, sheet, legal, registry) -> None:
        metrics = self.fonts.resolve("Helvetica", bold=True)
        key = self._font_key(metrics, registry)
        size = 64.0
        width = metrics.text_width(legal.watermark, size)

        page = document.page
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
        style = sheet.resolved(sheet.header_footer)
        metrics, size, key = self._resolve_font(style, None, registry)
        color = style.require("color")
        spec = document.page
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
        spec = document.page
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
