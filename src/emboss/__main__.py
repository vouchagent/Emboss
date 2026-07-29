"""CLI entry point: emboss render spec.json -o output.pdf

Supports JSON input from files or stdin, so an LLM can pipe its output
directly into PDF generation:

    llm "Generate a financial report" --json | emboss render - -o report.pdf
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _render(args: argparse.Namespace) -> int:
    if args.input == "-":
        raw = sys.stdin.read()
    else:
        path = Path(args.input)
        if not path.exists():
            print(f"error: file not found: {path}", file=sys.stderr)
            return 1
        raw = path.read_text(encoding="utf-8")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON: {exc}", file=sys.stderr)
        return 1

    try:
        from .generate import parse_spec_dict

        doc = parse_spec_dict(data)
    except Exception as exc:
        print(f"error: invalid document spec:\n  {exc}", file=sys.stderr)
        return 1

    try:
        pdf_bytes = doc.render(embed_spec=args.embed_spec)
    except Exception as exc:
        print(f"error: rendering failed: {exc}", file=sys.stderr)
        return 1

    output = Path(args.output)
    output.write_bytes(pdf_bytes)

    if not args.quiet:
        from .pdf.verify import verify_pdf

        report = verify_pdf(pdf_bytes)
        print(
            f"{output} — {len(pdf_bytes):,} bytes, "
            f"{report.page_count} page{'s' if report.page_count != 1 else ''}, "
            f"tagged={report.has_struct_tree}",
        )
        if not report.ok:
            for problem in report.problems:
                print(f"  warning: {problem}", file=sys.stderr)
    return 0


def _schema(args: argparse.Namespace) -> int:
    try:
        from .adapters.pydantic_schema import generate_json_schema
    except ImportError:
        print(
            "error: pydantic is required for schema generation.\n"
            "  pip install emboss-pdf[llm]",
            file=sys.stderr,
        )
        return 1

    output = generate_json_schema(indent=2)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        if not args.quiet:
            print(f"Schema written to {args.output}")
    else:
        print(output)
    return 0


def _verify(args: argparse.Namespace) -> int:
    from .pdf.verify import verify_pdf

    path = Path(args.input)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 1

    data = path.read_bytes()
    report = verify_pdf(data)
    print(report)
    exit_code = 0 if report.ok else 1

    if args.conformance:
        from .pdf.verify import verify_conformance

        try:
            conformance = verify_conformance(data, flavour=args.conformance)
        except RuntimeError as exc:
            print(f"conformance check unavailable: {exc}", file=sys.stderr)
            return 1
        print(conformance)
        if not conformance.compliant:
            exit_code = 1

    if getattr(args, "revisions", False):
        from .amend import coverage_report, format_history

        print(format_history(data))
        report = coverage_report(data)
        # Alarm only on content appended after a signature that no signature
        # covers, not on an unsigned base (which is simply not yet signed).
        appended_uncovered = [i for i in report.uncovered if i not in report.signatures]
        if report.signatures and appended_uncovered:
            exit_code = 1
    return exit_code


def _strip(args: argparse.Namespace) -> int:
    from .recovery import strip_pdf

    path = Path(args.input)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 1

    try:
        stripped = strip_pdf(path.read_bytes())
    except ImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output = Path(args.output)
    output.write_bytes(stripped)
    if not args.quiet:
        print(f"{output} — {len(stripped):,} bytes, attachments and provenance removed")
    return 0


def _diff(args: argparse.Namespace) -> int:
    from .diff import diff_documents, render_redline
    from .spec import Document

    old_path = Path(args.old)
    new_path = Path(args.new)
    if not old_path.exists():
        print(f"error: file not found: {old_path}", file=sys.stderr)
        return 1
    if not new_path.exists():
        print(f"error: file not found: {new_path}", file=sys.stderr)
        return 1

    try:
        old_doc = Document.from_pdf(old_path)
        new_doc = Document.from_pdf(new_path)
    except Exception as exc:
        print(f"error: could not read PDF(s): {exc}", file=sys.stderr)
        return 1

    result = diff_documents(old_doc, new_doc)
    redline_bytes = render_redline(old_doc, new_doc, result)

    output = Path(args.output)
    output.write_bytes(redline_bytes)

    if not args.quiet:
        print(
            f"{output} — {len(result.added)} added, {len(result.removed)} removed, "
            f"{len(result.changed)} changed, {len(result.unchanged)} unchanged"
        )
    return 0


def _reproduce(args: argparse.Namespace) -> int:
    from .manifest import reproduce

    path = Path(args.input)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 1

    try:
        report = reproduce(path.read_bytes())
    except ImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: reproduction failed: {exc}", file=sys.stderr)
        return 1

    print(report)
    return 0 if report.ok else 1


def _export(args: argparse.Namespace) -> int:
    try:
        from .adapters.pydantic_schema import DocumentSpec
    except ImportError:
        print(
            "error: pydantic is required.\n  pip install emboss-pdf[llm]",
            file=sys.stderr,
        )
        return 1

    if args.input == "-":
        raw = sys.stdin.read()
    else:
        path = Path(args.input)
        if not path.exists():
            print(f"error: file not found: {path}", file=sys.stderr)
            return 1
        raw = path.read_text(encoding="utf-8")

    try:
        spec = DocumentSpec.model_validate_json(raw)
    except Exception as exc:
        print(f"error: invalid document spec:\n  {exc}", file=sys.stderr)
        return 1

    doc = spec.to_document()
    fmt = args.format

    if fmt == "html":
        from .adapters.html_export import to_html

        output = to_html(doc, standalone=True)
    elif fmt == "markdown":
        from .adapters.markdown_export import to_markdown

        output = to_markdown(doc)
    elif fmt == "office-json":
        from .adapters.docx_export import to_office_dict

        output = json.dumps(to_office_dict(doc), indent=2, ensure_ascii=False)
    else:
        print(f"error: unknown format: {fmt}", file=sys.stderr)
        return 1

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        if not args.quiet:
            print(f"Exported {fmt} to {args.output}")
    else:
        print(output)
    return 0


def _analyze(args: argparse.Namespace) -> int:
    from .intelligence import ContentAnalyzer

    if args.input == "-":
        raw = sys.stdin.read()
    else:
        path = Path(args.input)
        if not path.exists():
            print(f"error: file not found: {path}", file=sys.stderr)
            return 1
        raw = path.read_text(encoding="utf-8")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON: {exc}", file=sys.stderr)
        return 1

    analyzer = ContentAnalyzer()
    analysis = analyzer.analyze_spec(data)
    print(analysis.summary)
    return 0


def _validate(args: argparse.Namespace) -> int:
    try:
        from .adapters.pydantic_schema import DocumentSpec
    except ImportError:
        print(
            "error: pydantic is required.\n  pip install emboss-pdf[llm]",
            file=sys.stderr,
        )
        return 1

    if args.input == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.input).read_text(encoding="utf-8")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON: {exc}", file=sys.stderr)
        return 1

    try:
        spec = DocumentSpec.model_validate(data)
    except Exception as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1

    print(f"valid: {spec.title!r}, {len(spec.content)} blocks, style={spec.style}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="emboss",
        description="Emboss — constraint-driven PDF generation for LLM pipelines",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
    )
    sub = parser.add_subparsers(dest="command")

    render_p = sub.add_parser(
        "render",
        help="Render a JSON document spec to PDF",
        description="Convert a JSON document specification to a professionally typeset PDF.",
    )
    render_p.add_argument("input", help="JSON spec file path, or '-' for stdin")
    render_p.add_argument(
        "-o",
        "--output",
        default="output.pdf",
        help="Output PDF path (default: output.pdf)",
    )
    render_p.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress status output"
    )
    render_p.add_argument(
        "--embed-spec",
        action="store_true",
        help="Embed the spec, layout map, and text map (needed for review)",
    )

    build_p = sub.add_parser(
        "build",
        help="Build one PDF from a directory of Markdown files",
        description=(
            "Concatenate a folder of Markdown files, in order, into a single "
            "tagged PDF. Order is alphabetical by default (numeric prefixes "
            "like 01-intro.md work) or from a .order file in the directory. "
            "The first file's front matter supplies the title and style."
        ),
    )
    build_p.add_argument("directory", help="Directory of .md files")
    build_p.add_argument(
        "-o", "--output", default="book.pdf", help="Output PDF path (default: book.pdf)"
    )
    build_p.add_argument("--title", default=None, help="Override the document title")
    build_p.add_argument("--style", default=None, help="Style preset override")
    build_p.add_argument(
        "--no-toc", action="store_true", help="Do not add a table of contents"
    )
    build_p.add_argument(
        "--no-page-breaks",
        action="store_true",
        help="Do not insert a page break between files",
    )
    build_p.add_argument("-q", "--quiet", action="store_true")

    schema_p = sub.add_parser(
        "schema",
        help="Export the JSON Schema for LLM prompt engineering",
        description="Generate the JSON Schema that LLMs use to produce valid document specs.",
    )
    schema_p.add_argument(
        "-o", "--output", default=None, help="Write to file instead of stdout"
    )
    schema_p.add_argument("-q", "--quiet", action="store_true")

    verify_p = sub.add_parser(
        "verify",
        help="Verify an existing PDF's structural integrity",
    )
    verify_p.add_argument("input", help="PDF file path")
    verify_p.add_argument(
        "--conformance",
        choices=["ua1", "2b", "3b"],
        default=None,
        help=(
            "Also validate ISO conformance with veraPDF "
            "(requires verapdf on PATH or VERAPDF_PATH set)"
        ),
    )
    verify_p.add_argument(
        "--revisions",
        action="store_true",
        help="Show the incremental-revision history and signature coverage",
    )

    strip_p = sub.add_parser(
        "strip",
        help="Remove embedded files, provenance metadata, and node ids from a PDF",
        description=(
            "Strip an Emboss-produced PDF of /AF attachments, provenance "
            "XMP/Info fields, and structure-tree node ids, in place."
        ),
    )
    strip_p.add_argument("input", help="PDF file path")
    strip_p.add_argument(
        "-o",
        "--output",
        default="stripped.pdf",
        help="Output PDF path (default: stripped.pdf)",
    )
    strip_p.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress status output"
    )

    amend_p = sub.add_parser(
        "amend",
        help="Append a signature to a PDF without rewriting prior bytes",
        description=(
            "Amend a PDF by appending an incremental revision: the original "
            "bytes are never rewritten, so a signature's ByteRange attests to "
            "everything before it. Content edits go through 'render'; only "
            "attestations append here."
        ),
    )
    amend_p.add_argument("input", help="PDF file path")
    amend_p.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output path (default: overwrite the input in place)",
    )
    amend_p.add_argument(
        "--sign", action="store_true", help="Append a PKCS#7 signature revision"
    )
    amend_p.add_argument("--cert", default=None, help="Signer certificate (PEM) path")
    amend_p.add_argument("--key", default=None, help="Signer private key (PEM) path")
    amend_p.add_argument(
        "--reason", default="", help="Reason recorded in the signature"
    )
    amend_p.add_argument("--name", default="", help="Signer name recorded in the field")
    amend_p.add_argument("-q", "--quiet", action="store_true")

    history_p = sub.add_parser(
        "history",
        help="Show a PDF's incremental-revision history and signature coverage",
        description=(
            "List each incremental revision (base, signature, annotations, "
            "attachment) with its byte range, and flag any revision that no "
            "signature's ByteRange covers -- appended content nobody signed."
        ),
    )
    history_p.add_argument("input", help="PDF file path")

    diff_p = sub.add_parser(
        "diff",
        help="Diff two PDFs and render a redlined comparison",
        description=(
            "Compare two Emboss-produced PDFs by node id (recovering an "
            "embedded spec if present, else the degraded structure-tree "
            "path) and render a redlined PDF: additions, deletions, and "
            "word-level text changes, with a summary page."
        ),
    )
    diff_p.add_argument("old", help="Original PDF file path")
    diff_p.add_argument("new", help="Revised PDF file path")
    diff_p.add_argument(
        "-o",
        "--output",
        default="redline.pdf",
        help="Output redlined PDF path (default: redline.pdf)",
    )
    diff_p.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress status output"
    )

    reproduce_p = sub.add_parser(
        "reproduce",
        help="Re-render a PDF from its embedded spec and verify structural equivalence",
        description=(
            "Recover the EmbossSpec (and reproducibility manifest, if "
            "present) embedded in a PDF, re-render it, and compare the "
            "result against the original. Byte-for-byte equality is not "
            "the bar: re-attaching a manifest/spec to the reproduction "
            "would itself change its bytes across the attachment "
            "boundary, so this instead verifies structural equivalence "
            "-- same page count, and the same visible text per page via "
            "pikepdf/MCID extraction -- and prints PASS or FAIL with a "
            "diff summary."
        ),
    )
    reproduce_p.add_argument("input", help="PDF file path")

    export_p = sub.add_parser(
        "export",
        help="Export a JSON spec to HTML, Markdown, or Office-ready JSON",
        description="Convert a document spec to alternative formats for preview, editing, or PPTX/DOCX conversion.",
    )
    export_p.add_argument("input", help="JSON spec file path, or '-' for stdin")
    export_p.add_argument(
        "-f",
        "--format",
        choices=["html", "markdown", "office-json"],
        default="html",
        help="Output format (default: html)",
    )
    export_p.add_argument(
        "-o", "--output", default=None, help="Write to file instead of stdout"
    )
    export_p.add_argument("-q", "--quiet", action="store_true")

    analyze_p = sub.add_parser(
        "analyze",
        help="Run content intelligence analysis on a document spec",
        description="Detect document type, classify table columns, and report content intelligence.",
    )
    analyze_p.add_argument("input", help="JSON spec file, or '-' for stdin")

    validate_p = sub.add_parser(
        "validate",
        help="Validate a JSON document spec without rendering",
    )
    validate_p.add_argument("input", help="JSON spec file, or '-' for stdin")

    review_p = sub.add_parser(
        "review",
        help="Extract reviewer annotations from marked-up PDFs to comments",
        description=(
            "Read the highlights, strike-outs, and notes reviewers added to "
            "one or more Emboss-produced PDFs (rendered with embed_spec=True) "
            "and resolve each against the embedded text map to a node id and "
            "character range. Several returned PDFs merge into one comment "
            "list. The unresolved count is reported loudly."
        ),
    )
    review_p.add_argument("inputs", nargs="+", help="Marked-up PDF file paths")
    review_p.add_argument(
        "-o", "--output", default=None, help="Write comments JSON to this path"
    )
    review_p.add_argument(
        "--html", default=None, help="Write a static HTML triage report to this path"
    )
    review_p.add_argument("-q", "--quiet", action="store_true")

    apply_p = sub.add_parser(
        "apply",
        help="Apply resolved comments to a spec (proposes by default)",
        description=(
            "Turn extracted comments into targeted node edits. Without an "
            "--edits map this only proposes the patches and writes nothing, "
            "since reviewer comments are never auto-applied. With --edits "
            "(comment id to replacement text) it patches each node, renders "
            "the result, and can write a redline proving the change."
        ),
    )
    apply_p.add_argument("comments", help="comments JSON from 'emboss review'")
    apply_p.add_argument(
        "--spec", required=True, help="JSON spec of the document to patch"
    )
    apply_p.add_argument(
        "--edits",
        default=None,
        help="JSON map of comment id to replacement text (omit to propose only)",
    )
    apply_p.add_argument(
        "-o", "--output", default=None, help="Write the patched, re-rendered PDF here"
    )
    apply_p.add_argument(
        "--redline", default=None, help="Write a redlined PDF of the change here"
    )
    apply_p.add_argument("-q", "--quiet", action="store_true")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    handlers = {
        "render": _render,
        "build": _build,
        "schema": _schema,
        "verify": _verify,
        "strip": _strip,
        "diff": _diff,
        "reproduce": _reproduce,
        "export": _export,
        "analyze": _analyze,
        "validate": _validate,
        "review": _review,
        "apply": _apply,
        "amend": _amend,
        "history": _history,
    }
    return handlers[args.command](args)


def _review(args: argparse.Namespace) -> int:
    from .annotations import (
        comments_to_json,
        extract_comments,
        merge_comments,
        unresolved_count,
    )

    lists = []
    for name in args.inputs:
        path = Path(name)
        if not path.exists():
            print(f"error: file not found: {path}", file=sys.stderr)
            return 1
        try:
            lists.append(extract_comments(path.read_bytes()))
        except Exception as exc:
            print(f"error: could not read {path}: {exc}", file=sys.stderr)
            return 1

    comments = merge_comments(*lists) if len(lists) > 1 else lists[0]

    if args.output:
        Path(args.output).write_text(comments_to_json(comments), encoding="utf-8")
    if args.html:
        from .review_html import review_html

        Path(args.html).write_text(review_html(comments), encoding="utf-8")
    if not args.output and not args.html:
        print(comments_to_json(comments))

    unresolved = unresolved_count(comments)
    if not args.quiet:
        note = f"{len(comments)} comments"
        if unresolved:
            note += f" -- WARNING: {unresolved} unresolved (spanning/unanchored)"
        print(note, file=sys.stderr)
    # Non-zero exit signals unresolved comments to a calling script.
    return 2 if unresolved else 0


def _apply(args: argparse.Namespace) -> int:
    import json

    from .annotations import Comment
    from .review import apply_replacements, propose_patches, redline
    from .spec import Document

    comments_path = Path(args.comments)
    spec_path = Path(args.spec)
    for path in (comments_path, spec_path):
        if not path.exists():
            print(f"error: file not found: {path}", file=sys.stderr)
            return 1

    raw = json.loads(comments_path.read_text(encoding="utf-8"))
    comments = [Comment(**c) for c in raw]
    doc = Document.from_json(spec_path.read_text(encoding="utf-8"))
    doc.layout_map()  # assign node ids so patches resolve

    if not args.edits:
        patches = propose_patches(doc, comments, {})
        for p in patches:
            state = "patchable" if p.patchable else f"SKIP ({p.note})"
            print(f"{p.comment_id} [{p.resolution}] {p.node_id}: {state}")
            if p.before:
                print(f"    before: {p.before}")
        if not args.quiet:
            print(
                f"{len(patches)} comments proposed; supply --edits to apply",
                file=sys.stderr,
            )
        return 0

    edits = json.loads(Path(args.edits).read_text(encoding="utf-8"))
    patched = apply_replacements(doc, comments, edits)

    if args.output:
        Path(args.output).write_bytes(patched.render(embed_spec=True))
    if args.redline:
        Path(args.redline).write_bytes(redline(doc, patched))
    if not args.quiet:
        print(f"applied {len(edits)} edits", file=sys.stderr)
    return 0


def _amend(args: argparse.Namespace) -> int:
    from .amend import amend_sign

    path = Path(args.input)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 1
    if not args.sign:
        print(
            "error: nothing to amend; pass --sign with --cert and --key",
            file=sys.stderr,
        )
        return 1
    if not args.cert or not args.key:
        print("error: --sign requires --cert and --key", file=sys.stderr)
        return 1

    try:
        amended = amend_sign(
            path.read_bytes(),
            cert=args.cert,
            key=args.key,
            reason=args.reason,
            name=args.name,
        )
    except Exception as exc:
        print(f"error: amend failed: {exc}", file=sys.stderr)
        return 1

    output = Path(args.output) if args.output else path
    output.write_bytes(amended)
    if not args.quiet:
        print(f"{output} -- appended signature revision, prior bytes untouched")
    return 0


def _history(args: argparse.Namespace) -> int:
    from .amend import format_history

    path = Path(args.input)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 1
    print(format_history(path.read_bytes()))
    return 0


def _build(args: argparse.Namespace) -> int:
    from .builder import build_from_directory

    directory = Path(args.directory)
    if not directory.is_dir():
        print(f"error: not a directory: {directory}", file=sys.stderr)
        return 1

    try:
        doc = build_from_directory(
            directory,
            title=args.title,
            style=args.style,
            toc=not args.no_toc,
            page_break_between=not args.no_page_breaks,
        )
        pdf_bytes = doc.render()
    except Exception as exc:
        print(f"error: build failed: {exc}", file=sys.stderr)
        return 1

    output = Path(args.output)
    output.write_bytes(pdf_bytes)
    if not args.quiet:
        print(f"{output} -- {len(pdf_bytes):,} bytes from {directory}")
    return 0


def _get_version() -> str:
    try:
        from . import __version__

        return __version__
    except Exception:
        return "0.2.0"


if __name__ == "__main__":
    sys.exit(main())
