"""Tests for the code block syntax highlighting feature."""

from emboss import Document, CodeBlock
from emboss.code_highlight import (
    Token,
    tokenize,
    colorize,
    THEMES,
    THEME_BACKGROUNDS,
    LANGUAGES,
)


# ===========================================================================
# TOKENIZER
# ===========================================================================


class TestTokenizer:
    def test_plain_text(self):
        tokens = tokenize("hello world", "text")
        assert len(tokens) == 1
        assert tokens[0].text == "hello world"
        assert tokens[0].type == "plain"

    def test_python_keywords(self):
        tokens = tokenize("def foo():\n    pass", "python")
        types = {t.text: t.type for t in tokens if t.text.strip()}
        assert types["def"] == "keyword"
        assert types["pass"] == "keyword"
        assert types["foo"] == "function"

    def test_python_string(self):
        tokens = tokenize('"hello"', "python")
        string_tokens = [t for t in tokens if t.type == "string"]
        assert len(string_tokens) == 1
        assert string_tokens[0].text == '"hello"'

    def test_python_comment(self):
        tokens = tokenize("x = 1  # comment", "python")
        comments = [t for t in tokens if t.type == "comment"]
        assert len(comments) == 1
        assert "comment" in comments[0].text

    def test_python_number(self):
        tokens = tokenize("x = 42", "python")
        numbers = [t for t in tokens if t.type == "number"]
        assert len(numbers) == 1
        assert numbers[0].text == "42"

    def test_python_types(self):
        tokens = tokenize("x: int = 0", "python")
        types = {t.text: t.type for t in tokens if t.text.strip()}
        assert types["int"] == "type"

    def test_javascript_keywords(self):
        tokens = tokenize("const x = true;", "javascript")
        types = {t.text: t.type for t in tokens if t.text.strip()}
        assert types["const"] == "keyword"
        assert types["true"] == "keyword"

    def test_javascript_alias(self):
        tokens_js = tokenize("const x = 1;", "js")
        tokens_full = tokenize("const x = 1;", "javascript")
        assert [t.type for t in tokens_js] == [t.type for t in tokens_full]

    def test_typescript(self):
        tokens = tokenize("interface Foo { bar: string; }", "typescript")
        types = {t.text: t.type for t in tokens if t.text.strip()}
        assert types["interface"] == "keyword"

    def test_rust_keywords(self):
        tokens = tokenize("fn main() { let x = 42; }", "rust")
        types = {t.text: t.type for t in tokens if t.text.strip()}
        assert types["fn"] == "keyword"
        assert types["let"] == "keyword"
        assert types["main"] == "function"

    def test_go_keywords(self):
        tokens = tokenize("func main() { var x int }", "go")
        types = {t.text: t.type for t in tokens if t.text.strip()}
        assert types["func"] == "keyword"
        assert types["var"] == "keyword"
        assert types["int"] == "type"

    def test_sql_keywords(self):
        tokens = tokenize("SELECT * FROM users WHERE id = 1", "sql")
        types = {t.text: t.type for t in tokens if t.text.strip()}
        assert types["SELECT"] == "keyword"
        assert types["FROM"] == "keyword"
        assert types["WHERE"] == "keyword"

    def test_html_tags(self):
        tokens = tokenize('<div class="x">', "html")
        keywords = [t for t in tokens if t.type == "keyword"]
        assert any("<div" in t.text for t in keywords)

    def test_css_selectors(self):
        tokens = tokenize(".btn { color: red; }", "css")
        types = [t for t in tokens if t.type == "type"]
        assert any(".btn" in t.text for t in types)

    def test_json_structure(self):
        tokens = tokenize('{"key": "value", "num": 42}', "json")
        strings = [t for t in tokens if t.type == "string"]
        numbers = [t for t in tokens if t.type == "number"]
        assert len(strings) >= 1
        assert len(numbers) == 1

    def test_yaml_keys(self):
        tokens = tokenize("name: John\nage: 30", "yaml")
        keywords = [t for t in tokens if t.type == "keyword"]
        assert any("name" in t.text for t in keywords)

    def test_shell_keywords(self):
        tokens = tokenize("if [ -f file ]; then echo ok; fi", "shell")
        types = {t.text: t.type for t in tokens if t.text.strip()}
        assert types["if"] == "keyword"
        assert types["then"] == "keyword"
        assert types["fi"] == "keyword"

    def test_bash_alias(self):
        tokens = tokenize("export PATH=/usr/bin", "bash")
        types = {t.text: t.type for t in tokens if t.text.strip()}
        assert types["export"] == "keyword"

    def test_empty_code(self):
        tokens = tokenize("", "python")
        assert tokens == []

    def test_unknown_language_plain(self):
        tokens = tokenize("hello", "unknown_lang")
        assert all(
            t.type
            in (
                "plain",
                "keyword",
                "string",
                "comment",
                "number",
                "function",
                "type",
                "operator",
                "punctuation",
            )
            for t in tokens
        )

    def test_preserves_whitespace(self):
        tokens = tokenize("  x = 1", "python")
        text = "".join(t.text for t in tokens)
        assert text == "  x = 1"

    def test_multiline_code(self):
        code = "def foo():\n    return 42"
        tokens = tokenize(code, "python")
        text = "".join(t.text for t in tokens)
        assert text == code

    def test_hex_number(self):
        tokens = tokenize("0xFF", "python")
        numbers = [t for t in tokens if t.type == "number"]
        assert len(numbers) == 1

    def test_float_number(self):
        tokens = tokenize("3.14", "python")
        numbers = [t for t in tokens if t.type == "number"]
        assert len(numbers) == 1
        assert numbers[0].text == "3.14"


# ===========================================================================
# COLORIZER
# ===========================================================================


class TestColorizer:
    def test_dark_modern_theme(self):
        tokens = [
            Token("def", "keyword"),
            Token(" ", "plain"),
            Token("foo", "function"),
        ]
        colored = colorize(tokens, "dark_modern")
        assert len(colored) == 3
        assert colored[0] == ("def", "569cd6")
        assert colored[2] == ("foo", "dcdcaa")

    def test_light_clean_theme(self):
        tokens = [Token("if", "keyword")]
        colored = colorize(tokens, "light_clean")
        assert colored[0] == ("if", "0000ff")

    def test_night_owl_theme(self):
        tokens = [Token("42", "number")]
        colored = colorize(tokens, "night_owl")
        assert colored[0] == ("42", "f78c6c")

    def test_unknown_theme_defaults(self):
        tokens = [Token("x", "plain")]
        colored = colorize(tokens, "nonexistent_theme")
        assert colored[0][1] == "d4d4d4"

    def test_all_themes_have_all_types(self):
        token_types = [
            "keyword",
            "string",
            "comment",
            "number",
            "operator",
            "function",
            "type",
            "punctuation",
            "plain",
        ]
        for theme_name, theme_colors in THEMES.items():
            for tt in token_types:
                assert tt in theme_colors, f"{theme_name} missing {tt}"

    def test_theme_backgrounds_exist(self):
        for theme_name in THEMES:
            assert theme_name in THEME_BACKGROUNDS


# ===========================================================================
# LANGUAGES LIST
# ===========================================================================


class TestLanguages:
    def test_supported_languages(self):
        expected = {
            "python",
            "javascript",
            "typescript",
            "rust",
            "go",
            "html",
            "css",
            "sql",
            "json",
            "yaml",
            "shell",
            "bash",
        }
        assert expected.issubset(set(LANGUAGES))

    def test_no_short_aliases_in_list(self):
        assert "js" not in LANGUAGES
        assert "ts" not in LANGUAGES
        assert "py" not in LANGUAGES
        assert "sh" not in LANGUAGES


# ===========================================================================
# CODE BLOCK DATACLASS
# ===========================================================================


class TestCodeBlockSpec:
    def test_defaults(self):
        cb = CodeBlock(code="print('hi')")
        assert cb.language == "text"
        assert cb.line_numbers is True
        assert cb.theme == "dark_modern"
        assert cb.start_line == 1
        assert cb.highlight_lines == []
        assert cb.caption is None
        assert cb.style is None

    def test_structure_tag(self):
        cb = CodeBlock(code="x = 1")
        assert cb.structure_tag == "Code"

    def test_custom_values(self):
        cb = CodeBlock(
            code="fn main() {}",
            language="rust",
            line_numbers=False,
            theme="night_owl",
            start_line=10,
            highlight_lines=[11, 12],
            caption="Rust example",
        )
        assert cb.language == "rust"
        assert cb.line_numbers is False
        assert cb.start_line == 10
        assert cb.highlight_lines == [11, 12]


# ===========================================================================
# DOCUMENT INTEGRATION
# ===========================================================================


class TestDocumentIntegration:
    def test_convenience_method(self):
        doc = Document(title="Test")
        doc.code_block("x = 1", language="python")
        assert len(doc.content) == 1
        assert isinstance(doc.content[0], CodeBlock)
        assert doc.content[0].language == "python"

    def test_add_directly(self):
        doc = Document(title="Test")
        cb = CodeBlock(code="let x = 1;", language="javascript")
        doc.add(cb)
        assert len(doc.content) == 1

    def test_chaining(self):
        doc = Document(title="Test")
        result = doc.code_block("x = 1")
        assert result is doc

    def test_render_produces_pdf(self):
        doc = Document(title="Code Test")
        doc.paragraph("Before code:")
        doc.code_block("def hello():\n    print('world')", language="python")
        doc.paragraph("After code.")
        pdf = doc.render()
        assert pdf[:5] == b"%PDF-"
        assert b"%%EOF" in pdf

    def test_render_with_line_numbers(self):
        doc = Document(title="Line Numbers")
        doc.code_block(
            "line 1\nline 2\nline 3",
            language="text",
            line_numbers=True,
            start_line=10,
        )
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_render_without_line_numbers(self):
        doc = Document(title="No Line Numbers")
        doc.code_block("x = 1", language="python", line_numbers=False)
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_render_with_highlight_lines(self):
        doc = Document(title="Highlights")
        doc.code_block(
            "a = 1\nb = 2\nc = 3",
            language="python",
            highlight_lines=[2],
        )
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_render_with_caption(self):
        doc = Document(title="Caption Code")
        doc.code_block("SELECT * FROM users;", language="sql", caption="Query example")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_render_all_themes(self):
        for theme in THEMES:
            doc = Document(title=f"Theme {theme}")
            doc.code_block("x = 1", language="python", theme=theme)
            pdf = doc.render()
            assert b"%PDF-" in pdf, f"Failed for theme {theme}"

    def test_render_multiple_languages(self):
        doc = Document(title="Multi Language")
        doc.code_block("def foo(): pass", language="python")
        doc.code_block("const x = 1;", language="javascript")
        doc.code_block("fn main() {}", language="rust")
        doc.code_block('{"key": "val"}', language="json")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_structure_tag_in_pdf(self):
        doc = Document(title="Tagged Code", tagged=True)
        doc.code_block("x = 1", language="python")
        pdf = doc.render()
        assert b"/Code" in pdf

    def test_deterministic_output(self):
        def make():
            doc = Document(title="Deterministic")
            doc.code_block("print('hello')", language="python")
            return doc.render()

        assert make() == make()


# ===========================================================================
# ADAPTER TESTS
# ===========================================================================


class TestMarkdownExport:
    def test_code_block_export(self):
        from emboss.adapters.markdown_export import to_markdown

        doc = Document(title="MD Test")
        doc.code_block("x = 1", language="python")
        md = to_markdown(doc)
        assert "```python" in md
        assert "x = 1" in md
        assert "```" in md

    def test_plain_text_no_lang(self):
        from emboss.adapters.markdown_export import to_markdown

        doc = Document(title="MD Plain")
        doc.code_block("hello", language="text")
        md = to_markdown(doc)
        assert "```\n" in md

    def test_caption_in_markdown(self):
        from emboss.adapters.markdown_export import to_markdown

        doc = Document(title="MD Caption")
        doc.code_block("x = 1", language="python", caption="Example")
        md = to_markdown(doc)
        assert "*Example*" in md


class TestHTMLExport:
    def test_code_block_export(self):
        from emboss.adapters.html_export import to_html

        doc = Document(title="HTML Test")
        doc.code_block("def foo(): pass", language="python")
        html = to_html(doc)
        assert "<pre" in html
        assert "<code" in html
        assert "language-python" in html

    def test_colored_spans(self):
        from emboss.adapters.html_export import to_html

        doc = Document(title="HTML Colors")
        doc.code_block("def foo(): pass", language="python")
        html = to_html(doc)
        assert '<span style="color:#' in html

    def test_caption_in_html(self):
        from emboss.adapters.html_export import to_html

        doc = Document(title="HTML Caption")
        doc.code_block("x = 1", caption="Example code")
        html = to_html(doc)
        assert "Example code" in html


class TestDocxExport:
    def test_code_block_export(self):
        from emboss.adapters.docx_export import to_office_dict

        doc = Document(title="DOCX Test")
        doc.code_block("x = 1", language="python", caption="Example")
        data = to_office_dict(doc)
        blocks = data["content"]
        assert len(blocks) == 1
        assert blocks[0]["type"] == "code_block"
        assert blocks[0]["code"] == "x = 1"
        assert blocks[0]["language"] == "python"
        assert blocks[0]["caption"] == "Example"


class TestPydanticSchema:
    def test_code_block_spec(self):
        from emboss.adapters.pydantic_schema import CodeBlockSpec

        spec = CodeBlockSpec(code="x = 1", language="python")
        element = spec.to_element()
        assert isinstance(element, CodeBlock)
        assert element.code == "x = 1"
        assert element.language == "python"

    def test_code_block_in_document_spec(self):
        from emboss.adapters.pydantic_schema import DocumentSpec

        data = {
            "title": "Test",
            "content": [
                {
                    "type": "code_block",
                    "code": "print('hi')",
                    "language": "python",
                }
            ],
        }
        spec = DocumentSpec.model_validate(data)
        doc = spec.to_document()
        assert len(doc.content) == 1
        assert isinstance(doc.content[0], CodeBlock)

    def test_code_block_full_options(self):
        from emboss.adapters.pydantic_schema import CodeBlockSpec

        spec = CodeBlockSpec(
            code="fn main() {}",
            language="rust",
            line_numbers=False,
            theme="night_owl",
            start_line=5,
            highlight_lines=[6, 7],
            caption="Rust code",
        )
        element = spec.to_element()
        assert element.line_numbers is False
        assert element.theme == "night_owl"
        assert element.start_line == 5
        assert element.highlight_lines == [6, 7]
        assert element.caption == "Rust code"


# ===========================================================================
# VALIDATION
# ===========================================================================


class TestConstraintValidation:
    def test_code_block_passes_validation(self):
        from emboss.constraints import ConstraintValidator

        doc = Document(title="Validation Test")
        doc.code_block("x = 1", language="python")
        validator = ConstraintValidator()
        result = validator.validate(doc)
        assert result.ok, f"Validation failed: {result.errors}"

    def test_code_block_not_rejected_as_unknown(self):
        from emboss.constraints import ConstraintValidator

        doc = Document(title="Known Type")
        doc.code_block("x = 1")
        validator = ConstraintValidator()
        result = validator.validate(doc)
        unknown_errors = [
            i for i in result.errors if "unsupported element type" in i.message
        ]
        assert len(unknown_errors) == 0
