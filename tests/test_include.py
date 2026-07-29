"""Tests for include-from-source and its Markdown code-fence integration."""

import pytest

from emboss.include import IncludeError, include_source
from emboss.markdown import parse_markdown
from emboss.spec import CodeBlock

_SAMPLE = """import os


def greet(name):
    # region body
    message = f"hello {name}"
    print(message)
    # endregion body


# BEGIN calc
total = 1 + 2
# END calc
"""


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / "example.py"
    path.write_text(_SAMPLE, encoding="utf-8")
    return path


class TestIncludeSource:
    def test_whole_file(self, sample):
        content = include_source(sample)
        assert content.startswith("import os")
        assert "total = 1 + 2" in content

    def test_line_range(self, sample):
        # Lines 4-5 are the def and the region marker (1-based inclusive).
        content = include_source(sample, lines="4-5")
        assert content == "def greet(name):\n    # region body"

    def test_single_line(self, sample):
        assert include_source(sample, lines="1") == "import os"

    def test_marker_region(self, sample):
        content = include_source(sample, marker="body")
        assert content == 'message = f"hello {name}"\nprint(message)'

    def test_begin_end_marker(self, sample):
        assert include_source(sample, marker="calc") == "total = 1 + 2"

    def test_dedent_default(self, sample):
        content = include_source(sample, marker="body")
        assert not content.startswith(" ")

    def test_dedent_disabled(self, sample):
        content = include_source(sample, marker="body", dedent=False)
        assert content.startswith("    ")

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(IncludeError):
            include_source(tmp_path / "nope.py")

    def test_missing_range_raises(self, sample):
        with pytest.raises(IncludeError):
            include_source(sample, lines="500-600")

    def test_bad_range_raises(self, sample):
        with pytest.raises(IncludeError):
            include_source(sample, lines="10-2")

    def test_missing_marker_raises(self, sample):
        with pytest.raises(IncludeError):
            include_source(sample, marker="ghost")

    def test_unclosed_marker_raises(self, tmp_path):
        path = tmp_path / "open.py"
        path.write_text("# region x\ncode here\n", encoding="utf-8")
        with pytest.raises(IncludeError):
            include_source(path, marker="x")

    def test_lines_and_marker_conflict(self, sample):
        with pytest.raises(IncludeError):
            include_source(sample, lines="1-2", marker="body")


class TestMarkdownIntegration:
    def test_file_fence_loads_content(self, tmp_path):
        (tmp_path / "foo.py").write_text(_SAMPLE, encoding="utf-8")
        md = "```python file=foo.py marker=calc\n```"
        elements = parse_markdown(md, base_dir=tmp_path)
        assert isinstance(elements[0], CodeBlock)
        assert elements[0].language == "python"
        assert elements[0].code == "total = 1 + 2"

    def test_file_fence_with_line_range(self, tmp_path):
        (tmp_path / "foo.py").write_text(_SAMPLE, encoding="utf-8")
        md = "```python file=foo.py lines=1-1\n```"
        elements = parse_markdown(md, base_dir=tmp_path)
        assert elements[0].code == "import os"

    def test_base_dir_resolution(self, tmp_path):
        sub = tmp_path / "src"
        sub.mkdir()
        (sub / "code.py").write_text(_SAMPLE, encoding="utf-8")
        md = "```python file=src/code.py lines=1-1\n```"
        elements = parse_markdown(md, base_dir=tmp_path)
        assert elements[0].code == "import os"

    def test_absolute_path(self, tmp_path):
        path = tmp_path / "abs.py"
        path.write_text(_SAMPLE, encoding="utf-8")
        md = f"```python file={path} lines=1-1\n```"
        elements = parse_markdown(md)
        assert elements[0].code == "import os"

    def test_missing_include_degrades_with_warning(self, tmp_path):
        warnings = []
        md = "```python file=missing.py\n```"
        elements = parse_markdown(md, base_dir=tmp_path, on_warning=warnings.append)
        assert isinstance(elements[0], CodeBlock)
        assert len(warnings) == 1
        assert warnings[0].kind == "include"

    def test_missing_include_strict_raises(self, tmp_path):
        md = "```python file=missing.py\n```"
        with pytest.raises(IncludeError):
            parse_markdown(md, base_dir=tmp_path, strict=True)

    def test_plain_fence_unaffected(self):
        md = "```python\nprint('hi')\n```"
        elements = parse_markdown(md)
        assert elements[0].code == "print('hi')"
        assert elements[0].language == "python"
