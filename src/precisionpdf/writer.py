"""The render pipeline.

    Document -> validate -> measure -> paginate -> render -> tag -> bytes

Every stage after validation is deterministic: no timestamps, no random
identifiers, no iteration over unordered collections. The same document
renders to the same bytes on any machine, which is what makes output
hash-verifiable for filings and diffable in CI.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .constraints import ConstraintValidator
from .layout.engine import LayoutEngine
from .pdf.assembler import PDFAssembler
from .pdf.fonts import build_font_resource
from .pdf.objects import PdfArray, PdfDict, PdfName, PdfRef, PdfStream
from .pdf.streams import ContentStream
from .pdf.tags import StructureElement, StructureTreeBuilder
from .spec import (
    BibliographyBlock, BulletList, Callout, Chart, CodeBlock, Document,
    Footnote, Heading, HorizontalRule, Image, MathBlock, PageBreak,
    Paragraph, Table,
)
from .styles import Style
from .typography.font_metrics import FontRegistry
from .typography.hyphenation import Hyphenator

__all__ = ["render_document", "RenderResult", "Renderer"]


@dataclass
class RenderResult:
    """Rendered bytes plus what happened along the way."""

    data: bytes
    page_count: int
    issues: list = field(default_factory=list)

    def __bytes__(self) -> bytes:
        return self.data


def render_document(document: Document, *, strict: bool = False,
                    return_result: bool = False):
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

    def run(self) -> RenderResult:
        validation = self.validator.validate(self.source).raise_if_failed()
        document = validation.document
        sheet = document.stylesheet

        hyphenator = Hyphenator(language=document.language)
        engine = LayoutEngine(self.fonts, sheet, hyphenator=hyphenator)

        content = list(document.content)
        content = self._prepend_title_block(document, sheet, content)

        width = document.page.content_width
        measured = [engine.measure(el, width) for el in content]
        pages = engine.paginate(measured, document.page)

        assembler = PDFAssembler()
        data = self._assemble(assembler, document, sheet, pages)

        return RenderResult(
            data=data, page_count=len(pages), issues=validation.issues
        )

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
            stream, page_root = self._render_page(
                document, sheet, page, index, len(pages), font_resources
            )
            for child in page_root.children:
                root.children.append(child)
            content_refs.append(assembler.add(PdfStream(data=stream)))

        # Register fonts after rendering so usage is known for subsetting.
        font_dict = PdfDict()
        for key, metrics in sorted(font_resources.items()):
            resource = build_font_resource(assembler, key, metrics)
            font_dict[key] = resource.ref

        xobject_dict = PdfDict()
        if hasattr(self, '_image_refs'):
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
        if document.legal and document.legal.watermark:
            resources["ExtGState"] = self._watermark_gstate(
                assembler, document.legal
            )
        resources_ref = assembler.add(resources)

        struct_ref = None
        if document.tagged:
            builder = StructureTreeBuilder(assembler, page_refs)
            struct_ref = builder.build(root)

        for index, (page, page_id) in enumerate(zip(pages, page_ids)):
            page_dict = PdfDict()
            page_dict["Type"] = PdfName("Page")
            page_dict["Parent"] = PdfRef(pages_id)
            page_dict["MediaBox"] = PdfArray([
                0, 0, document.page.width, document.page.height
            ])
            page_dict["Resources"] = resources_ref
            page_dict["Contents"] = content_refs[index]
            if document.tagged:
                page_dict["StructParents"] = index
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

        if document.signatures:
            from .signing import (
                SignatureField, build_sig_field_dict, build_acroform,
            )
            sig_field_refs = []
            for sig in document.signatures:
                if isinstance(sig, dict):
                    sig = SignatureField(**sig)
                pidx = min(sig.page_index, len(page_refs) - 1)
                ref = build_sig_field_dict(
                    assembler, sig, page_refs[pidx]
                )
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

    def _render_page(self, document, sheet, page, page_index, total,
                     font_registry) -> tuple:
        stream = ContentStream()
        root = StructureElement(tag="Document")
        legal = document.legal

        if legal and legal.watermark:
            self._draw_watermark(stream, document, sheet, legal, font_registry)

        for placed in page.blocks:
            element = placed.block.element
            if isinstance(element, Heading):
                self._draw_text_block(
                    stream, placed, page_index, root, font_registry,
                    tag=element.structure_tag,
                )
            elif isinstance(element, Paragraph):
                self._draw_text_block(
                    stream, placed, page_index, root, font_registry, tag="P"
                )
            elif isinstance(element, BulletList):
                self._draw_list(
                    stream, placed, page_index, root, font_registry
                )
            elif isinstance(element, Table):
                self._draw_table(
                    stream, placed, page_index, root, font_registry, sheet
                )
            elif isinstance(element, Footnote):
                self._draw_footnote(
                    stream, placed, page_index, root, font_registry
                )
            elif isinstance(element, Callout):
                self._draw_callout(
                    stream, placed, page_index, root, font_registry,
                    document.page.content_width,
                )
            elif isinstance(element, Image):
                self._draw_image(
                    stream, placed, page_index, root, font_registry
                )
            elif isinstance(element, Chart):
                self._draw_chart(
                    stream, placed, page_index, root, font_registry
                )
            elif isinstance(element, CodeBlock):
                self._draw_code_block(
                    stream, placed, page_index, root, font_registry,
                    document.page.content_width,
                )
            elif isinstance(element, MathBlock):
                self._draw_math(
                    stream, placed, page_index, root, font_registry
                )
            elif isinstance(element, BibliographyBlock):
                self._draw_bibliography(
                    stream, placed, page_index, root, font_registry
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
                    _, size, key = self._resolve_font(
                        style, None, font_registry
                    )
                    build_signature_appearance(stream, sig, key, size)

        self._draw_running_content(
            stream, document, sheet, page, page_index, total, font_registry
        )
        return stream.to_bytes(), root

    def _resolve_font(self, style, run, registry) -> tuple:
        family = (run.font_family if run and run.font_family
                  else style.require("font_family"))
        bold = run.bold if run and run.bold else style.require("bold")
        italic = run.italic if run and run.italic else style.require("italic")
        metrics = self.fonts.resolve(family, bold=bold, italic=italic)
        size = (run.font_size if run and run.font_size
                else style.require("font_size"))
        key = self._font_key(metrics, registry)
        return metrics, size, key

    def _draw_text_block(self, stream, placed, page_index, root, registry,
                         tag: str) -> None:
        style = placed.block.style
        element = StructureElement(tag=tag)
        root.children.append(element)

        mcid = stream.next_mcid()
        element.add_mcid(page_index, mcid)
        stream.begin_marked(tag, mcid)

        y = placed.y
        indent = style.require("indent_left")
        for line in placed.lines:
            baseline = y - line.ascent
            for text, run, offset in line.fragments:
                metrics, size, key = self._resolve_font(style, run, registry)
                color = run.color or style.require("color")
                stream.text_line(
                    text, key, size,
                    placed.x + indent + offset, baseline, color,
                    kern_pairs=metrics.kern_pairs(text),
                    gid_map=metrics.gid_map,
                )
            y -= line.height

        stream.end_marked()

    def _draw_list(self, stream, placed, page_index, root, registry) -> None:
        block = placed.block
        style = block.style
        element = block.element

        list_el = StructureElement(tag="L")
        root.children.append(list_el)

        metrics, size, key = self._resolve_font(style, None, registry)
        bullet_width = metrics.text_width(element.bullet + " ", size)
        indent = style.require("indent_left")
        color = style.require("color")

        y = placed.y
        for lines in block.list_items:
            item = StructureElement(tag="LI")
            list_el.children.append(item)

            label = StructureElement(tag="Lbl")
            item.children.append(label)
            label_mcid = stream.next_mcid()
            label.add_mcid(page_index, label_mcid)
            stream.begin_marked("Lbl", label_mcid)
            if lines:
                stream.text_line(
                    element.bullet, key, size,
                    placed.x + indent, y - lines[0].ascent, color,
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
                    stream.text_line(
                        text, run_key, run_size,
                        placed.x + indent + bullet_width + offset,
                        baseline, run.color or color,
                        kern_pairs=run_metrics.kern_pairs(text),
                        gid_map=run_metrics.gid_map,
                    )
                y -= line.height
            stream.end_marked()
            y -= style.require("space_after")

    def _draw_table(self, stream, placed, page_index, root, registry,
                    sheet) -> None:
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
                    stream, lines, x_positions[column] + pad_x,
                    y - pad_y, header_style, registry,
                    widths[column] - 2 * pad_x,
                )
                stream.end_marked()

            y -= layout.header_height
            stream.begin_artifact()
            stream.line(
                placed.x, y, placed.x + table_width, y,
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
                    placed.x, y - height, table_width, height,
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
                    stream, lines, x_positions[column] + pad_x,
                    y - pad_y, block.style, registry,
                    widths[column] - 2 * pad_x,
                )
                stream.end_marked()

            y -= height
            if position < len(row_indices) - 1:
                stream.begin_artifact()
                stream.line(
                    placed.x, y, placed.x + table_width, y,
                    color=sheet.table_rule_color,
                    width=sheet.table_rule_width,
                )
                stream.end_marked()

        stream.begin_artifact()
        stream.line(
            placed.x, y, placed.x + table_width, y,
            color=sheet.table_header_rule_color,
            width=sheet.table_rule_width,
        )
        stream.end_marked()

    def _draw_cell_lines(self, stream, lines, x, y, style, registry,
                         available) -> None:
        cursor = y
        for line in lines:
            baseline = cursor - line.ascent
            for text, run, offset in line.fragments:
                metrics, size, key = self._resolve_font(style, run, registry)
                stream.text_line(
                    text, key, size, x + offset, baseline,
                    run.color or style.require("color"),
                    kern_pairs=metrics.kern_pairs(text),
                    gid_map=metrics.gid_map,
                )
            cursor -= line.height

    def _draw_rule(self, stream, placed, document, sheet) -> None:
        element = placed.block.element
        stream.begin_artifact()
        stream.line(
            placed.x, placed.y,
            placed.x + document.page.content_width, placed.y,
            color=element.color, width=element.thickness,
        )
        stream.end_marked()

    def _draw_image(self, stream, placed, page_index, root, registry) -> None:
        element = placed.block.element
        style = placed.block.style

        fig_el = StructureElement(tag="Figure")
        if element.alt_text:
            fig_el.alt = element.alt_text
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
        stream.raw(b" ".join([
            stream._num(display_w), b"0 0",
            stream._num(display_h),
            stream._num(x), stream._num(y), b"cm",
        ]))
        stream.raw(f"/{img_name} Do".encode("ascii"))
        stream.restore()

        if element.caption:
            metrics, size, key = self._resolve_font(style, None, registry)
            cap_size = size * 0.85
            cap_y = y - cap_size - 2.0
            color = style.require("color")
            cap_x = x + (display_w - metrics.text_width(element.caption, cap_size)) / 2
            stream.text_line(
                element.caption, key, cap_size, cap_x, cap_y, color,
                gid_map=metrics.gid_map,
            )

        stream.end_marked()

    def _get_image_ref(self, element) -> str:
        if not hasattr(self, '_image_refs'):
            self._image_refs = {}
        source_key = id(element)
        if source_key not in self._image_refs:
            name = f"Im{len(self._image_refs) + 1}"
            self._image_refs[source_key] = (name, element)
        return self._image_refs[source_key][0]

    def _draw_chart(self, stream, placed, page_index, root, registry) -> None:
        from .charts import ChartData, ChartSpec, render_chart

        element = placed.block.element
        style = placed.block.style

        fig_el = StructureElement(tag="Figure")
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
            placed.x, placed.y + 2.0,
            placed.x + 100.0, placed.y + 2.0,
            color="d6d3d1", width=0.5,
        )
        stream.end_marked()

        y = placed.y
        baseline = y - placed.lines[0].ascent if placed.lines else y
        stream.text_line(
            marker, key, size, placed.x, baseline, color,
            gid_map=metrics.gid_map,
        )

        for line in placed.lines:
            baseline = y - line.ascent
            for text, run, offset in line.fragments:
                run_metrics, run_size, run_key = self._resolve_font(
                    style, run, registry
                )
                stream.text_line(
                    text, run_key, run_size,
                    placed.x + marker_width + offset,
                    baseline, run.color or color,
                    gid_map=run_metrics.gid_map,
                )
            y -= line.height

        stream.end_marked()

    def _draw_callout(self, stream, placed, page_index, root, registry,
                      page_content_width: float = 468.0) -> None:
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
            placed.x, placed.y - placed.height,
            page_content_width,
            placed.height,
            fill=element.background,
        )
        stream.rect(
            placed.x, placed.y - placed.height,
            border_width, placed.height,
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
                element.icon, key, icon_size,
                content_x, y - metrics.ascent(icon_size),
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
                    text, run_key, run_size,
                    content_x + offset, baseline,
                    run.color or color,
                    gid_map=run_metrics.gid_map,
                )
            y -= line.height

        stream.end_marked()

    def _draw_code_block(self, stream, placed, page_index, root,
                         registry, page_content_width: float = 468.0) -> None:
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
            placed.x, placed.y - placed.height,
            content_width, placed.height,
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
                    placed.x, y - line_height,
                    content_width, line_height,
                    fill="ffffff",
                )
                stream.restore()

            if element.line_numbers:
                num_str = str(line_num)
                num_width = metrics.text_width(num_str, code_size)
                num_x = placed.x + padding + gutter_width - num_width - metrics.text_width("  ", code_size)
                stream.text_line(
                    num_str, key, code_size,
                    num_x, baseline, "6a737d",
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
                            clipped, key, code_size,
                            x, baseline, color,
                            gid_map=metrics.gid_map,
                        )
                        x += metrics.text_width(clipped, code_size)
                    stream.text_line(
                        "...", key, code_size,
                        x, baseline, "6a737d",
                        gid_map=metrics.gid_map,
                    )
                    truncated = True
                    continue
                stream.text_line(
                    text, key, code_size,
                    x, baseline, color,
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
                element.caption, body_key, cap_size,
                placed.x, cap_y - cap_size, cap_color,
                gid_map=body_metrics.gid_map,
            )

    def _draw_math(self, stream, placed, page_index, root, registry) -> None:
        from .math_render import MathExpression, render_math, parse_math, MathLayoutEngine

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

        render_math(stream, expr, x, baseline_y, key, size, color,
                    italic_key=italic_key, symbol_key=symbol_key)

        if element.caption:
            cap_size = size * 0.7
            cap_y = baseline_y - layout.depth - cap_size - 4.0
            cap_width = metrics.text_width(element.caption, cap_size)
            cap_x = placed.x + (content_width - cap_width) / 2
            stream.text_line(
                element.caption, key, cap_size, cap_x, cap_y, color,
                gid_map=metrics.gid_map,
            )

        stream.end_marked()

    def _draw_bibliography(self, stream, placed, page_index, root,
                           registry) -> None:
        from .bibliography import format_bibliography

        element = placed.block.element
        style = placed.block.style
        metrics, size, key = self._resolve_font(style, None, registry)
        color = style.require("color")

        bib_el = StructureElement(tag="Div")
        root.children.append(bib_el)

        y = placed.y

        if element.title:
            heading_style = self.source.stylesheet.resolved(
                self.source.stylesheet.for_heading(element.heading_level),
                element.style,
            )
            h_metrics, h_size, h_key = self._resolve_font(
                heading_style, None, registry
            )
            h_color = heading_style.require("color")
            h_tag = f"H{element.heading_level}"

            h_el = StructureElement(tag=h_tag)
            bib_el.children.append(h_el)
            mcid = stream.next_mcid()
            h_el.add_mcid(page_index, mcid)
            stream.begin_marked(h_tag, mcid)

            baseline = y - h_metrics.ascent(h_size)
            stream.text_line(
                element.title, h_key, h_size,
                placed.x, baseline, h_color,
                gid_map=h_metrics.gid_map,
            )
            y -= h_metrics.line_height(
                h_size, heading_style.require("line_height")
            )
            y -= heading_style.require("space_after")
            stream.end_marked()

        entries = format_bibliography(element.citations, element.bib_style)
        line_h = metrics.line_height(size, style.require("line_height"))
        indent = style.require("indent_left")

        for entry_text in entries:
            p_el = StructureElement(tag="P")
            bib_el.children.append(p_el)
            mcid = stream.next_mcid()
            p_el.add_mcid(page_index, mcid)
            stream.begin_marked("P", mcid)

            baseline = y - metrics.ascent(size)
            stream.text_line(
                entry_text, key, size,
                placed.x + indent, baseline, color,
                kern_pairs=metrics.kern_pairs(entry_text),
                gid_map=metrics.gid_map,
            )
            y -= line_h
            y -= style.require("space_after") * 0.5
            stream.end_marked()

    def _draw_watermark(self, stream, document, sheet, legal,
                        registry) -> None:
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
        stream.rotated_text(
            legal.watermark, key, size, x, y, "9a3412", angle
        )
        stream.end_marked()
        stream.restore()

    def _draw_running_content(self, stream, document, sheet, page,
                              page_index, total, registry) -> None:
        style = sheet.resolved(sheet.header_footer)
        metrics, size, key = self._resolve_font(style, None, registry)
        color = style.require("color")
        spec = document.page
        legal = document.legal

        gmap = metrics.gid_map

        if document.header_text:
            stream.begin_artifact("Header")
            stream.text_line(
                document.header_text, key, size,
                spec.margin_left, spec.height - spec.margin_top + 22.0,
                color, gid_map=gmap,
            )
            stream.end_marked()

        footer_y = spec.margin_bottom - 26.0
        if document.footer_text:
            stream.begin_artifact("Footer")
            stream.text_line(
                document.footer_text, key, size,
                spec.margin_left, footer_y, color, gid_map=gmap,
            )
            stream.end_marked()

        if document.page_numbers:
            label = f"{page_index + 1} of {total}"
            width = metrics.text_width(label, size)
            stream.begin_artifact("Footer")
            stream.text_line(
                label, key, size,
                spec.width - spec.margin_right - width, footer_y, color,
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
                label, key, bates_size, x, y, "44403c", gid_map=gmap,
            )
            stream.end_marked()

        if legal and legal.line_numbering:
            self._draw_line_numbers(
                stream, document, page, page_index, key, metrics, legal
            )

    def _draw_line_numbers(self, stream, document, page, page_index, key,
                           metrics, legal) -> None:
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
                label, key, size, x - width, y, color, gid_map=gmap,
            )
        stream.end_marked()
