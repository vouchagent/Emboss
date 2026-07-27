"""Tests for Markdown-to-EmbossSpec conversion and LLM integration."""

from emboss import Document, parse_markdown, spec_prompt, parse_spec_json
from emboss.spec import (
    Heading,
    Paragraph,
    BulletList,
    NumberedList,
    Table,
    CodeBlock,
    MathBlock,
    Image,
    HorizontalRule,
    PageBreak,
    Callout,
)


class TestMarkdownHeadings:
    def test_h1(self):
        result = parse_markdown("# Hello World")
        assert len(result) == 1
        assert isinstance(result[0], Heading)
        assert result[0].text == "Hello World"
        assert result[0].level == 1

    def test_h2_through_h6(self):
        md = "## H2\n### H3\n#### H4\n##### H5\n###### H6"
        result = parse_markdown(md)
        assert len(result) == 5
        for i, level in enumerate([2, 3, 4, 5, 6]):
            assert result[i].level == level

    def test_heading_with_trailing_hashes(self):
        result = parse_markdown("## Title ##")
        assert result[0].text == "Title"


class TestMarkdownParagraphs:
    def test_plain_paragraph(self):
        result = parse_markdown("Hello world.")
        assert len(result) == 1
        assert isinstance(result[0], Paragraph)

    def test_multiline_paragraph(self):
        result = parse_markdown("Line one\nline two")
        assert len(result) == 1
        assert isinstance(result[0], Paragraph)

    def test_paragraphs_separated_by_blank(self):
        result = parse_markdown("First para.\n\nSecond para.")
        assert len(result) == 2

    def test_bold_inline(self):
        result = parse_markdown("This is **bold** text.")
        assert isinstance(result[0], Paragraph)

    def test_italic_inline(self):
        result = parse_markdown("This is *italic* text.")
        assert isinstance(result[0], Paragraph)


class TestMarkdownLists:
    def test_bullet_list(self):
        md = "- Item one\n- Item two\n- Item three"
        result = parse_markdown(md)
        assert len(result) == 1
        assert isinstance(result[0], BulletList)
        assert len(result[0].items) == 3

    def test_numbered_list(self):
        md = "1. First\n2. Second\n3. Third"
        result = parse_markdown(md)
        assert len(result) == 1
        assert isinstance(result[0], NumberedList)
        assert len(result[0].items) == 3

    def test_bullet_with_asterisk(self):
        md = "* Item A\n* Item B"
        result = parse_markdown(md)
        assert isinstance(result[0], BulletList)

    def test_bullet_with_plus(self):
        md = "+ Item A\n+ Item B"
        result = parse_markdown(md)
        assert isinstance(result[0], BulletList)


class TestMarkdownTables:
    def test_simple_table(self):
        md = "| Name | Value |\n|---|---|\n| Alpha | 100 |\n| Beta | 200 |"
        result = parse_markdown(md)
        assert len(result) == 1
        assert isinstance(result[0], Table)
        assert len(result[0].rows) == 2

    def test_table_alignment(self):
        md = "| Left | Center | Right |\n|:---|:---:|---:|\n| a | b | c |"
        result = parse_markdown(md)
        table = result[0]
        assert isinstance(table, Table)


class TestMarkdownCodeBlocks:
    def test_fenced_code(self):
        md = "```python\ndef hello():\n    print('hi')\n```"
        result = parse_markdown(md)
        assert len(result) == 1
        assert isinstance(result[0], CodeBlock)
        assert result[0].language == "python"
        assert "def hello" in result[0].code

    def test_code_no_language(self):
        md = "```\nsome code\n```"
        result = parse_markdown(md)
        assert result[0].language == "text"


class TestMarkdownMath:
    def test_math_block(self):
        md = "$$\nE = mc^2\n$$"
        result = parse_markdown(md)
        assert len(result) == 1
        assert isinstance(result[0], MathBlock)
        assert result[0].source == "E = mc^2"

    def test_inline_math_standalone(self):
        md = "$E = mc^2$"
        result = parse_markdown(md)
        assert isinstance(result[0], MathBlock)


class TestMarkdownMisc:
    def test_horizontal_rule(self):
        result = parse_markdown("---")
        assert isinstance(result[0], HorizontalRule)

    def test_hr_with_asterisks(self):
        result = parse_markdown("***")
        assert isinstance(result[0], HorizontalRule)

    def test_image(self):
        result = parse_markdown("![Alt text](image.png)")
        assert isinstance(result[0], Image)
        assert result[0].source == "image.png"

    def test_page_break(self):
        result = parse_markdown("\\newpage")
        assert isinstance(result[0], PageBreak)

    def test_callout(self):
        md = "> [!NOTE]\n> This is important."
        result = parse_markdown(md)
        assert isinstance(result[0], Callout)
        assert result[0].variant == "note"


class TestMarkdownComplex:
    def test_full_document(self):
        md = """# Quarterly Report

Revenue grew 12% year over year.

## Financial Summary

| Metric | Value |
|---|---|
| Revenue | $24.1M |
| EBITDA | $8.2M |

### Key Highlights

- North America: +15%
- EMEA: +8%
- APAC: +11%

```python
def calculate_growth(current, previous):
    return (current - previous) / previous * 100
```

$$
\\Delta = \\frac{R_{current} - R_{previous}}{R_{previous}} \\times 100
$$
"""
        result = parse_markdown(md)
        types = [type(e).__name__ for e in result]
        assert "Heading" in types
        assert "Paragraph" in types
        assert "Table" in types
        assert "BulletList" in types
        assert "CodeBlock" in types
        assert "MathBlock" in types


class TestDocumentFromMarkdown:
    def test_basic(self):
        doc = Document.from_markdown("# Test\n\nHello world.")
        assert doc.title == "Test"
        assert len(doc.content) == 2

    def test_with_style(self):
        doc = Document.from_markdown("# Report\n\nContent.", style="finance")
        assert doc.stylesheet.name == "finance"

    def test_renders_to_pdf(self):
        doc = Document.from_markdown("# Test\n\nA paragraph of text.")
        pdf = doc.render()
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 500

    def test_with_overrides(self):
        doc = Document.from_markdown(
            "# Report\n\nContent.",
            style="legal",
            author="Test Author",
        )
        assert doc.author == "Test Author"

    def test_title_from_first_heading(self):
        doc = Document.from_markdown("# My Title\n\nBody text.")
        assert doc.title == "My Title"

    def test_explicit_title_overrides(self):
        doc = Document.from_markdown("# Heading\n\nBody.", title="Custom Title")
        assert doc.title == "Custom Title"


class TestSpecPrompt:
    def test_returns_string(self):
        prompt = spec_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 500

    def test_contains_format_description(self):
        prompt = spec_prompt()
        assert "EmbossSpec" in prompt
        assert "heading" in prompt
        assert "paragraph" in prompt
        assert "table" in prompt

    def test_style_included(self):
        prompt = spec_prompt(style="legal")
        assert '"legal"' in prompt

    def test_features_hint(self):
        prompt = spec_prompt(features=["tables", "math"])
        assert "tables" in prompt
        assert "math" in prompt


class TestParseSpecJson:
    def test_basic_json(self):
        json_str = '{"title": "Test", "content": [{"type": "heading", "text": "Hello", "level": 1}]}'
        doc = parse_spec_json(json_str)
        assert doc.title == "Test"
        assert len(doc.content) >= 1

    def test_json_with_fences(self):
        json_str = '```json\n{"title": "Test", "content": [{"type": "paragraph", "text": "Hi"}]}\n```'
        doc = parse_spec_json(json_str)
        assert doc.title == "Test"

    def test_json_with_trailing_comma(self):
        json_str = (
            '{"title": "Test", "content": [{"type": "paragraph", "text": "Hi",}],}'
        )
        doc = parse_spec_json(json_str)
        assert doc.title == "Test"

    def test_style_override(self):
        json_str = '{"title": "Test", "style": "corporate", "content": [{"type": "paragraph", "text": "Hi"}]}'
        doc = parse_spec_json(json_str, style="finance")
        assert doc.stylesheet.name == "finance"

    def test_renders_to_pdf(self):
        json_str = '{"title": "Test", "content": [{"type": "heading", "text": "Hello", "level": 1}, {"type": "paragraph", "text": "World"}]}'
        doc = parse_spec_json(json_str)
        pdf = doc.render()
        assert pdf[:5] == b"%PDF-"


class TestDocumentFromJson:
    def test_basic(self):
        json_str = (
            '{"title": "Test", "content": [{"type": "paragraph", "text": "Hello"}]}'
        )
        doc = Document.from_json(json_str)
        assert doc.title == "Test"

    def test_renders(self):
        json_str = '{"title": "Report", "style": "finance", "content": [{"type": "heading", "text": "Summary", "level": 1}]}'
        doc = Document.from_json(json_str)
        pdf = doc.render()
        assert pdf[:5] == b"%PDF-"
