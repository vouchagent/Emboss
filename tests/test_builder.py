"""Tests for building one PDF from a directory of Markdown files."""

import pytest

from emboss import build_from_directory, ordered_markdown_files
from emboss.__main__ import main


def _write(dir_path, name, text):
    (dir_path / name).write_text(text, encoding="utf-8")


class TestOrdering:
    def test_alphabetical_by_default(self, tmp_path):
        _write(tmp_path, "02-b.md", "# B\n")
        _write(tmp_path, "01-a.md", "# A\n")
        files = ordered_markdown_files(tmp_path)
        assert [f.name for f in files] == ["01-a.md", "02-b.md"]

    def test_explicit_order(self, tmp_path):
        _write(tmp_path, "a.md", "# A\n")
        _write(tmp_path, "b.md", "# B\n")
        files = ordered_markdown_files(tmp_path, order=["b.md", "a.md"])
        assert [f.name for f in files] == ["b.md", "a.md"]

    def test_order_file(self, tmp_path):
        _write(tmp_path, "a.md", "# A\n")
        _write(tmp_path, "b.md", "# B\n")
        _write(tmp_path, ".order", "# comment\nb.md\na.md\n")
        files = ordered_markdown_files(tmp_path)
        assert [f.name for f in files] == ["b.md", "a.md"]

    def test_missing_ordered_file_raises(self, tmp_path):
        _write(tmp_path, "a.md", "# A\n")
        with pytest.raises(ValueError, match="not found"):
            ordered_markdown_files(tmp_path, order=["a.md", "gone.md"])


class TestBuild:
    def test_title_from_first_front_matter(self, tmp_path):
        _write(tmp_path, "01.md", "---\ntitle: Handbook\n---\n\n# Intro\n\nHi.\n")
        _write(tmp_path, "02.md", "# More\n\nText.\n")
        doc = build_from_directory(tmp_path)
        assert doc.title == "Handbook"

    def test_title_override(self, tmp_path):
        _write(tmp_path, "01.md", "---\ntitle: A\n---\n\n# X\n")
        doc = build_from_directory(tmp_path, title="Override")
        assert doc.title == "Override"

    def test_concatenates_all_files_with_page_breaks(self, tmp_path):
        _write(tmp_path, "01.md", "# One\n\nAlpha.\n")
        _write(tmp_path, "02.md", "# Two\n\nBeta.\n")
        doc = build_from_directory(tmp_path)
        types = [type(b).__name__ for b in doc.content]
        assert "PageBreak" in types  # a break between the two files
        assert doc.render().startswith(b"%PDF")

    def test_no_page_breaks(self, tmp_path):
        _write(tmp_path, "01.md", "# One\n\nAlpha.\n")
        _write(tmp_path, "02.md", "# Two\n\nBeta.\n")
        doc = build_from_directory(tmp_path, page_break_between=False)
        assert "PageBreak" not in [type(b).__name__ for b in doc.content]

    def test_empty_directory_raises(self, tmp_path):
        with pytest.raises(ValueError, match="no Markdown"):
            build_from_directory(tmp_path)


class TestCli:
    def test_build_command(self, tmp_path):
        _write(tmp_path, "01.md", "---\ntitle: Book\n---\n\n# Intro\n\nHi.\n")
        _write(tmp_path, "02.md", "# Next\n\nMore.\n")
        out = tmp_path / "book.pdf"
        rc = main(["build", str(tmp_path), "-o", str(out), "-q"])
        assert rc == 0
        assert out.read_bytes().startswith(b"%PDF")

    def test_build_missing_directory(self, tmp_path):
        rc = main(["build", str(tmp_path / "nope"), "-q"])
        assert rc == 1
