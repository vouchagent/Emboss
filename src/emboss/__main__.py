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
    try:
        from .adapters.pydantic_schema import DocumentSpec
    except ImportError:
        print(
            "error: pydantic is required for JSON-to-PDF conversion.\n"
            "  pip install emboss[llm]",
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
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON: {exc}", file=sys.stderr)
        return 1

    try:
        spec = DocumentSpec.model_validate(data)
    except Exception as exc:
        print(f"error: invalid document spec:\n  {exc}", file=sys.stderr)
        return 1

    try:
        doc = spec.to_document()
        pdf_bytes = doc.render()
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
            "  pip install emboss[llm]",
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
    return 0 if report.ok else 1


def _export(args: argparse.Namespace) -> int:
    try:
        from .adapters.pydantic_schema import DocumentSpec
    except ImportError:
        print(
            "error: pydantic is required.\n  pip install emboss[llm]",
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
            "error: pydantic is required.\n  pip install emboss[llm]",
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

    print(
        f"valid: {spec.title!r}, "
        f"{len(spec.content)} blocks, "
        f"style={spec.style}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="emboss",
        description="Emboss — constraint-driven PDF generation for LLM pipelines",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"%(prog)s {_get_version()}",
    )
    sub = parser.add_subparsers(dest="command")

    render_p = sub.add_parser(
        "render",
        help="Render a JSON document spec to PDF",
        description="Convert a JSON document specification to a professionally typeset PDF.",
    )
    render_p.add_argument("input", help="JSON spec file path, or '-' for stdin")
    render_p.add_argument("-o", "--output", default="output.pdf", help="Output PDF path (default: output.pdf)")
    render_p.add_argument("-q", "--quiet", action="store_true", help="Suppress status output")

    schema_p = sub.add_parser(
        "schema",
        help="Export the JSON Schema for LLM prompt engineering",
        description="Generate the JSON Schema that LLMs use to produce valid document specs.",
    )
    schema_p.add_argument("-o", "--output", default=None, help="Write to file instead of stdout")
    schema_p.add_argument("-q", "--quiet", action="store_true")

    verify_p = sub.add_parser(
        "verify",
        help="Verify an existing PDF's structural integrity",
    )
    verify_p.add_argument("input", help="PDF file path")

    export_p = sub.add_parser(
        "export",
        help="Export a JSON spec to HTML, Markdown, or Office-ready JSON",
        description="Convert a document spec to alternative formats for preview, editing, or PPTX/DOCX conversion.",
    )
    export_p.add_argument("input", help="JSON spec file path, or '-' for stdin")
    export_p.add_argument(
        "-f", "--format",
        choices=["html", "markdown", "office-json"],
        default="html",
        help="Output format (default: html)",
    )
    export_p.add_argument("-o", "--output", default=None, help="Write to file instead of stdout")
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

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    handlers = {
        "render": _render,
        "schema": _schema,
        "verify": _verify,
        "export": _export,
        "analyze": _analyze,
        "validate": _validate,
    }
    return handlers[args.command](args)


def _get_version() -> str:
    try:
        from . import __version__

        return __version__
    except Exception:
        return "0.1.0"


if __name__ == "__main__":
    sys.exit(main())
