"""Build one PDF from a directory of Markdown files.

A documentation team adds a build step rather than calling an API: point this
at a folder of Markdown, and it concatenates the files, in order, into a single
tagged PDF. File order is alphabetical by default (so numeric prefixes like
``01-intro.md`` work), or an explicit order can be supplied.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["build_from_directory", "ordered_markdown_files"]


def ordered_markdown_files(directory, order=None) -> list:
    """Return the Markdown files to include, in render order.

    ``order`` is an optional list of file names (relative to *directory*);
    without it, files are taken in sorted order. A ``.order`` file in the
    directory, one file name per line (blank lines and ``#`` comments
    ignored), is honored when ``order`` is not given.
    """
    base = Path(directory)
    if not base.is_dir():
        raise ValueError(f"not a directory: {directory}")

    if order is None:
        order_file = base / ".order"
        if order_file.is_file():
            order = [
                line.strip()
                for line in order_file.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]

    if order:
        files = [base / name for name in order]
        missing = [str(p) for p in files if not p.is_file()]
        if missing:
            raise ValueError(f"ordered file(s) not found: {', '.join(missing)}")
        return files

    return sorted(p for p in base.glob("*.md") if p.is_file())


def build_from_directory(
    directory,
    *,
    title=None,
    style=None,
    toc=True,
    page_break_between=True,
    order=None,
):
    """Concatenate a directory of Markdown files into one Document.

    Document-level metadata (title, style) comes from the first file's front
    matter unless overridden. Each file's content is appended in order, with a
    page break between files by default.
    """
    from .markdown import parse_front_matter, parse_markdown
    from .spec import Document

    files = ordered_markdown_files(directory, order)
    if not files:
        raise ValueError(f"no Markdown files found in {directory}")

    first = parse_front_matter(files[0].read_text(encoding="utf-8"))
    meta = first.fields
    doc_title = title or meta.get("title") or Path(directory).name
    doc_style = style or meta.get("style", "corporate")

    doc = Document(title=doc_title, style=doc_style, toc=toc)
    for index, path in enumerate(files):
        matter = parse_front_matter(path.read_text(encoding="utf-8"))
        # Resolve file= includes relative to each Markdown file's own folder.
        elements = parse_markdown(matter.body, base_dir=path.parent)
        if index > 0 and page_break_between:
            doc.page_break()
        for element in elements:
            doc.add(element)
    return doc
