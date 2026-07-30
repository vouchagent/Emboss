"""Tests for the LLM-to-EmbossSpec pipeline: schema, repair, routing, front matter."""

import json
import re
import sys
import types
from types import SimpleNamespace

import pytest

from emboss import (
    Document,
    generate,
    parse_front_matter,
    parse_spec_json,
    spec_prompt,
    spec_schema,
)
from emboss.generate import (
    _DOC_TYPE_EXEMPLARS,
    _call_anthropic,
    _call_openai,
    _extract_json_candidate,
    _strict_schema,
)
from emboss.markdown import parse_markdown
from emboss.spec import Heading, HorizontalRule, MathBlock, Paragraph

VALID_SPEC = {
    "title": "Mock Doc",
    "content": [{"type": "paragraph", "text": "Hello from the mock."}],
}
INVALID_JSON = '{"title": "Bad"}'


def _tool_response(payload):
    return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=payload)])


def _text_response(text):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def _install_anthropic(monkeypatch, responses):
    calls = []

    def _create(**kwargs):
        calls.append(kwargs)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    class FakeAnthropic:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.messages = SimpleNamespace(create=_create)

    module = types.ModuleType("anthropic")
    module.Anthropic = FakeAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", module)
    return calls


def _install_openai(monkeypatch, contents):
    calls = []

    def _create(**kwargs):
        calls.append(kwargs)
        content = contents[min(len(calls) - 1, len(contents) - 1)]
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeOpenAI:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=_create))

    module = types.ModuleType("openai")
    module.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", module)
    return calls


class TestSpecSchema:
    def test_returns_dict_with_content_array(self):
        pytest.importorskip("pydantic")
        schema = spec_schema()
        assert isinstance(schema, dict)
        content = schema["properties"]["content"]
        assert content["type"] == "array"
        assert "items" in content
        assert "title" in schema["properties"]

    def test_raises_clear_import_error_without_pydantic(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "emboss.adapters.pydantic_schema", None)
        with pytest.raises(ImportError, match="pydantic"):
            spec_schema()


SAMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "count": {"type": "integer", "default": 1},
        "mode": {"type": "string", "enum": ["a", "b"], "default": "a"},
        "tag": {"type": "string", "const": "block", "default": "block"},
        "child": {
            "type": "object",
            "properties": {"deep": {"type": "string", "default": ""}},
        },
        "maybe": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
        "linked": {"$ref": "#/$defs/Thing"},
    },
    "required": ["name"],
    "$defs": {
        "Thing": {"type": "object", "properties": {"x": {"type": "number"}}},
    },
}


def _assert_strict(node):
    if isinstance(node, dict):
        if isinstance(node.get("properties"), dict):
            assert node.get("additionalProperties") is False
            assert set(node.get("required", [])) == set(node["properties"])
        for value in node.values():
            _assert_strict(value)
    elif isinstance(node, list):
        for value in node:
            _assert_strict(value)


class TestStrictSchemaTransform:
    def test_all_objects_closed_and_fully_required(self):
        strict = _strict_schema(SAMPLE_SCHEMA)
        _assert_strict(strict)

    def test_optional_scalars_become_null_unions(self):
        strict = _strict_schema(SAMPLE_SCHEMA)
        props = strict["properties"]
        assert props["count"]["type"] == ["integer", "null"]
        assert props["mode"]["type"] == ["string", "null"]
        assert None in props["mode"]["enum"]
        assert props["child"]["type"] == ["object", "null"]

    def test_required_and_const_fields_untouched(self):
        strict = _strict_schema(SAMPLE_SCHEMA)
        assert strict["properties"]["name"]["type"] == "string"
        assert strict["properties"]["tag"]["type"] == "string"
        assert strict["properties"]["tag"]["const"] == "block"

    def test_existing_null_union_not_duplicated(self):
        strict = _strict_schema(SAMPLE_SCHEMA)
        options = strict["properties"]["maybe"]["anyOf"]
        assert sum(1 for o in options if o.get("type") == "null") == 1

    def test_optional_ref_wrapped_in_any_of(self):
        strict = _strict_schema(SAMPLE_SCHEMA)
        options = strict["properties"]["linked"]["anyOf"]
        assert {"$ref": "#/$defs/Thing"} in options
        assert {"type": "null"} in options

    def test_defs_processed(self):
        strict = _strict_schema(SAMPLE_SCHEMA)
        thing = strict["$defs"]["Thing"]
        assert thing["additionalProperties"] is False
        assert thing["required"] == ["x"]

    def test_input_schema_not_mutated(self):
        _strict_schema(SAMPLE_SCHEMA)
        assert SAMPLE_SCHEMA["properties"]["count"]["type"] == "integer"
        assert "additionalProperties" not in SAMPLE_SCHEMA

    def test_full_spec_schema_transform(self):
        pytest.importorskip("pydantic")
        _assert_strict(_strict_schema(spec_schema()))


class TestStructuredProviders:
    def test_anthropic_forced_tool_use_shape(self, monkeypatch):
        pytest.importorskip("pydantic")
        calls = _install_anthropic(monkeypatch, [_tool_response(VALID_SPEC)])
        result = _call_anthropic(
            "Make a report", "sys prompt", "claude-sonnet-5", "k", structured=True
        )
        assert result == VALID_SPEC
        assert isinstance(result, dict)
        (call,) = calls
        assert call["tool_choice"] == {"type": "tool", "name": "emit_document"}
        assert call["tools"][0]["name"] == "emit_document"
        assert call["tools"][0]["input_schema"] == spec_schema()
        assert call["system"] == "sys prompt"
        assert call["messages"] == [{"role": "user", "content": "Make a report"}]

    def test_anthropic_unstructured_returns_text(self, monkeypatch):
        calls = _install_anthropic(monkeypatch, [_text_response("plain output")])
        result = _call_anthropic("p", "s", "m", "k", structured=False)
        assert result == "plain output"
        assert "tools" not in calls[0]

    def test_openai_response_format_shape(self, monkeypatch):
        pytest.importorskip("pydantic")
        calls = _install_openai(monkeypatch, [json.dumps(VALID_SPEC)])
        result = _call_openai("p", "s", "gpt-4o", "k", structured=True)
        assert result == json.dumps(VALID_SPEC)
        response_format = calls[0]["response_format"]
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["name"] == "emboss_spec"
        assert response_format["json_schema"]["strict"] is True
        _assert_strict(response_format["json_schema"]["schema"])

    def test_openai_unstructured_omits_response_format(self, monkeypatch):
        calls = _install_openai(monkeypatch, ["{}"])
        _call_openai("p", "s", "gpt-4o", "k", structured=False)
        assert "response_format" not in calls[0]

    def test_generate_structured_dict_passthrough(self, monkeypatch):
        pytest.importorskip("pydantic")
        calls = _install_anthropic(monkeypatch, [_tool_response(VALID_SPEC)])
        pdf = generate("Write it", api_key="k")
        assert pdf.startswith(b"%PDF")
        assert len(calls) == 1
        assert calls[0]["tool_choice"]["name"] == "emit_document"

    def test_generate_unstructured_keeps_prompt_path(self, monkeypatch):
        calls = _install_anthropic(
            monkeypatch, [_text_response(json.dumps(VALID_SPEC))]
        )
        pdf = generate("Write it", api_key="k", structured=False)
        assert pdf.startswith(b"%PDF")
        assert "tools" not in calls[0]
        assert "tool_choice" not in calls[0]

    def test_generate_structured_openai(self, monkeypatch):
        pytest.importorskip("pydantic")
        calls = _install_openai(monkeypatch, [json.dumps(VALID_SPEC)])
        pdf = generate("Write it", provider="openai", api_key="k")
        assert pdf.startswith(b"%PDF")
        assert calls[0]["response_format"]["type"] == "json_schema"


class TestRepairLoop:
    def test_correction_round_recovers(self, monkeypatch):
        pytest.importorskip("pydantic")
        calls = _install_anthropic(
            monkeypatch,
            [_text_response(INVALID_JSON), _text_response(json.dumps(VALID_SPEC))],
        )
        pdf = generate(
            "Write it",
            api_key="k",
            structured=False,
            max_repair_rounds=1,
        )
        assert pdf.startswith(b"%PDF")
        assert len(calls) == 2
        messages = calls[1]["messages"]
        assert messages[0] == {"role": "user", "content": "Write it"}
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == INVALID_JSON
        correction = messages[2]["content"]
        assert messages[2]["role"] == "user"
        assert "Your previous output failed validation:" in correction
        assert "content" in correction
        assert "Return the corrected complete JSON." in correction

    def test_exhausted_rounds_raise_last_error(self, monkeypatch):
        pytest.importorskip("pydantic")
        calls = _install_anthropic(
            monkeypatch,
            [_text_response(INVALID_JSON), _text_response(INVALID_JSON)],
        )
        with pytest.raises(ValueError):
            generate("Write it", api_key="k", structured=False, max_repair_rounds=1)
        assert len(calls) == 2

    def test_structured_semantic_failure_repaired(self, monkeypatch):
        pytest.importorskip("pydantic")
        bad_chart = {
            "title": "T",
            "content": [{"type": "chart", "chart_type": "bar", "labels": ["a"]}],
        }
        calls = _install_anthropic(
            monkeypatch,
            [_tool_response(bad_chart), _tool_response(VALID_SPEC)],
        )
        pdf = generate("Write it", api_key="k", max_repair_rounds=1)
        assert pdf.startswith(b"%PDF")
        assert len(calls) == 2
        assert calls[1]["tool_choice"]["name"] == "emit_document"
        correction = calls[1]["messages"][-1]["content"]
        assert "Your previous output failed validation:" in correction

    def test_zero_rounds_stays_lenient(self, monkeypatch):
        calls = _install_anthropic(monkeypatch, [_text_response(INVALID_JSON)])
        pdf = generate("Write it", api_key="k", structured=False)
        assert pdf.startswith(b"%PDF")
        assert len(calls) == 1


class TestGenreExemplars:
    @pytest.mark.parametrize("doc_type", sorted(_DOC_TYPE_EXEMPLARS))
    def test_exemplar_parses_strict(self, doc_type):
        pytest.importorskip("pydantic")
        prompt = spec_prompt(doc_type=doc_type)
        assert f"## Worked Example: {doc_type}" in prompt
        blocks = re.findall(r"```json\n(.*?)```", prompt, re.DOTALL)
        exemplar = blocks[-1].strip()
        assert len(exemplar.split("\n")) <= 45
        payload = json.loads(exemplar)
        assert payload == _DOC_TYPE_EXEMPLARS[doc_type]
        doc = parse_spec_json(exemplar, strict=True)
        assert doc.title
        assert doc.content

    def test_unknown_doc_type_raises(self):
        with pytest.raises(ValueError, match="doc_type"):
            spec_prompt(doc_type="novel")

    def test_default_prompt_has_no_exemplar(self):
        assert "Worked Example" not in spec_prompt()


FENCED = (
    "Sure! Here is the document you asked for:\n\n"
    "```json\n"
    '{"title": "Fenced", "content": [{"type": "paragraph", "text": "Hi"}]}\n'
    "```\n\nLet me know if you need edits."
)
BARE = (
    "Here you go: "
    '{"title": "Bare", "content": [{"type": "paragraph", "text": "Hi"}]}'
    " Hope that helps!"
)
MATHML = (
    '<math xmlns="http://www.w3.org/1998/Math/MathML">'
    "<mi>x</mi><mo>=</mo><mn>2</mn></math>"
)


class TestFromLlmRouting:
    def test_fenced_json_with_chat_wrapper(self):
        doc = Document.from_llm(FENCED)
        assert doc.title == "Fenced"
        assert isinstance(doc.content[0], Paragraph)

    def test_bare_json_with_preamble(self):
        doc = Document.from_llm(BARE)
        assert doc.title == "Bare"

    def test_markdown_route(self):
        doc = Document.from_llm("# My Doc\n\nSome body text.")
        assert doc.title == "My Doc"
        assert isinstance(doc.content[0], Heading)

    def test_mathml_route(self):
        doc = Document.from_llm(MATHML)
        assert isinstance(doc.content[0], MathBlock)
        assert doc.content[0].source.startswith("<math")

    def test_mathml_embedded_in_prose(self):
        doc = Document.from_llm(f"The identity is {MATHML} as shown above.")
        assert isinstance(doc.content[0], MathBlock)
        assert doc.content[0].source.endswith("</math>")

    def test_ambiguous_text_falls_back_to_markdown(self):
        doc = Document.from_llm("Just a plain sentence with no markup.")
        assert isinstance(doc.content[0], Paragraph)

    def test_unparseable_fenced_json_falls_back_to_markdown(self):
        text = "```json\nthis is not json at all {{{\n```\n\n# Fallback\n\nBody."
        doc = Document.from_llm(text)
        assert doc.title == "Fallback"

    def test_json_without_content_key_is_markdown(self):
        text = 'Config: {"debug": true} explains the *setting*.'
        assert _extract_json_candidate(text) is None
        doc = Document.from_llm(text)
        assert isinstance(doc.content[0], Paragraph)

    def test_kwargs_forwarded(self):
        assert Document.from_llm("# T\n\nx.", style="finance").style == "finance"
        assert Document.from_llm(FENCED, style="legal").style == "legal"

    def test_first_bare_candidate_wins(self):
        text = (
            '{"note": 1} then '
            '{"title": "First", "content": [{"type": "paragraph", "text": "a"}]}'
            ' and {"title": "Second", "content": []}'
        )
        candidate = _extract_json_candidate(text)
        assert json.loads(candidate)["title"] == "First"


ALL_KEYS_MD = """---
title: Annual Plan
author: J. Doe
subject: Planning
keywords: plan, annual
style: finance
toc: true
number_sections: true
language: de-DE
page_numbers: false
color_mode: cmyk
---
# Ignored Title

Body text.
"""


class TestFrontMatter:
    def test_all_recognized_keys_applied(self):
        doc = Document.from_markdown(ALL_KEYS_MD)
        assert doc.title == "Annual Plan"
        assert doc.author == "J. Doe"
        assert doc.subject == "Planning"
        assert doc.keywords == "plan, annual"
        assert doc.style == "finance"
        assert doc.toc is True
        assert doc.number_sections is True
        assert doc.language == "de-DE"
        assert doc.page_numbers is False
        assert doc.color_mode == "cmyk"
        assert isinstance(doc.content[0], Heading)
        assert doc.content[0].text == "Ignored Title"

    def test_explicit_kwargs_win(self):
        doc = Document.from_markdown(ALL_KEYS_MD, title="Explicit", style="legal")
        assert doc.title == "Explicit"
        assert doc.style == "legal"
        assert doc.author == "J. Doe"

    def test_quoted_and_unquoted_scalars(self):
        matter = parse_front_matter(
            '---\ntitle: "Colon: Subtitle"\n'
            "author: 'Single Quoted'\n"
            "keywords: 2024\n"
            "toc: yes\n"
            "page_numbers: 0\n---\nbody"
        )
        assert matter.fields["title"] == "Colon: Subtitle"
        assert matter.fields["author"] == "Single Quoted"
        assert matter.fields["keywords"] == "2024"
        assert matter.fields["toc"] is True
        assert matter.fields["page_numbers"] is False
        assert matter.body == "body"

    def test_unknown_keys_collected_as_warnings(self):
        matter = parse_front_matter("---\ntitle: T\ncustom_field: 5\n---\nbody")
        assert matter.fields == {"title": "T"}
        assert any("custom_field" in w for w in matter.warnings)

    def test_bad_bool_and_color_mode_warn(self):
        matter = parse_front_matter("---\ntoc: maybe\ncolor_mode: pantone\n---\nbody")
        assert "toc" not in matter.fields
        assert "color_mode" not in matter.fields
        assert len(matter.warnings) == 2

    def test_malformed_front_matter_is_regular_markdown(self):
        text = "---\nthis line has no colon\n---\n# Doc\n\nBody."
        matter = parse_front_matter(text)
        assert matter.fields == {}
        assert matter.body == text
        doc = Document.from_markdown(text)
        assert doc.title == "Doc"
        assert any(isinstance(el, HorizontalRule) for el in doc.content)

    def test_unterminated_block_is_regular_markdown(self):
        text = "---\ntitle: X\n# Doc"
        matter = parse_front_matter(text)
        assert matter.fields == {}
        assert matter.body == text

    def test_parse_markdown_strips_front_matter(self):
        elements = parse_markdown("---\ntitle: X\n---\n# H\n\nBody.")
        assert isinstance(elements[0], Heading)
        assert elements[0].text == "H"

    def test_blank_lines_and_comments_allowed(self):
        matter = parse_front_matter("---\n\n# a comment\ntitle: T\n---\nbody")
        assert matter.fields == {"title": "T"}

    def test_from_llm_markdown_route_applies_front_matter(self):
        doc = Document.from_llm("---\ntitle: FM Doc\nstyle: legal\n---\n\nBody.")
        assert doc.title == "FM Doc"
        assert doc.style == "legal"


class TestDeterminism:
    def test_spec_prompt_deterministic(self):
        assert spec_prompt(doc_type="report") == spec_prompt(doc_type="report")
        assert spec_prompt(style="finance") == spec_prompt(style="finance")

    def test_spec_prompt_watermark_guardrail(self):
        prompt = spec_prompt(style="legal")
        assert "watermark" in prompt.lower()
        assert "unless the user explicitly asked" in prompt

    def test_from_llm_render_deterministic(self):
        text = "# Det\n\nThe same text renders to the same bytes."
        assert Document.from_llm(text).render() == Document.from_llm(text).render()

    def test_front_matter_render_deterministic(self):
        first = Document.from_markdown(ALL_KEYS_MD)
        second = Document.from_markdown(ALL_KEYS_MD)
        assert first.render() == second.render()
