"""Contract tests: spec_prompt() examples and parse_spec_json robustness."""

import inspect
import json
import re
import sys

import pytest

from emboss import generate, parse_spec_json, spec_prompt
from emboss.spec import (
    BulletList,
    Callout,
    Heading,
    HorizontalRule,
    MathBlock,
    NumberedList,
    Paragraph,
)


def _json_blocks(prompt: str) -> list[str]:
    return re.findall(r"```json\n(.*?)```", prompt, re.DOTALL)


def _wrap(payload) -> dict:
    if isinstance(payload, dict) and "content" in payload:
        return payload
    if isinstance(payload, dict) and "type" in payload:
        return {"title": "Contract", "content": [payload]}
    doc = {"title": "Contract", "content": [{"type": "paragraph", "text": "x"}]}
    if isinstance(payload, dict):
        doc.update(payload)
    return doc


SYNONYM_DOC = {
    "title": "Synonyms",
    "content": [
        {"type": "bullet_list", "items": ["a", "b"]},
        {"type": "numbered_list", "items": ["x"], "start": 3},
        {"type": "math_block", "source": "E = mc^2"},
        {"type": "horizontal_rule"},
        {"type": "callout", "text": "t1", "variant": "tip"},
        {"type": "callout", "text": "t2", "variant": "caution"},
        {"type": "callout", "text": "t3", "variant": "important"},
    ],
}


def _assert_synonyms_resolved(doc) -> None:
    els = doc.content
    assert isinstance(els[0], BulletList)
    assert isinstance(els[1], NumberedList)
    assert els[1].start == 3
    assert isinstance(els[2], MathBlock)
    assert els[2].source == "E = mc^2"
    assert isinstance(els[3], HorizontalRule)
    assert all(isinstance(c, Callout) for c in els[4:7])
    assert [c.variant for c in els[4:7]] == ["info", "warning", "note"]


class TestPromptContract:
    def test_prompt_has_examples(self):
        assert len(_json_blocks(spec_prompt())) >= 12

    def test_every_example_is_valid_json(self):
        for block in _json_blocks(spec_prompt()):
            json.loads(block)

    def test_every_example_parses_strict(self):
        pytest.importorskip("pydantic")
        for block in _json_blocks(spec_prompt()):
            payload = json.loads(block)
            doc = parse_spec_json(json.dumps(_wrap(payload)), strict=True)
            assert doc.content

    def test_no_legacy_tags_in_prompt(self):
        prompt = spec_prompt()
        for legacy in (
            "bullet_list",
            "numbered_list",
            "math_block",
            "horizontal_rule",
            "scatter",
        ):
            assert legacy not in prompt

    def test_canonical_vocabulary_taught(self):
        prompt = spec_prompt()
        for canonical in ('"bullets"', '"numbered"', '"math"', '"rule"'):
            assert canonical in prompt
        assert "columns" in prompt
        assert "toc" in prompt


class TestRobustParsing:
    def test_truncated_mid_string_recovers(self):
        text = '{"title": "T", "content": [{"type": "paragraph", "text": "Hello wor'
        doc = parse_spec_json(text)
        assert doc.title == "T"
        assert len(doc.content) == 1

    def test_truncated_mid_key_recovers(self):
        text = '{"title": "T", "content": [{"type": "paragraph", "te'
        doc = parse_spec_json(text)
        assert doc.title == "T"

    def test_truncated_after_comma_recovers(self):
        text = '{"title": "T", "content": [{"type": "paragraph", "text": "Hi"},'
        doc = parse_spec_json(text)
        assert doc.title == "T"
        assert len(doc.content) == 1

    def test_fenced_json(self):
        text = (
            '```json\n{"title": "T", "content": '
            '[{"type": "paragraph", "text": "Hi"}]}\n```'
        )
        doc = parse_spec_json(text)
        assert doc.title == "T"

    def test_invalid_block_among_valid_keeps_valid(self):
        pytest.importorskip("pydantic")
        data = {
            "title": "T",
            "content": [
                {"type": "heading", "text": "Good", "level": 1},
                {"type": "heading"},
                {"type": "table", "text": "Meant to be a table"},
                {"type": "paragraph", "text": "Also good"},
            ],
        }
        warnings: list[str] = []
        doc = parse_spec_json(json.dumps(data), on_warning=warnings.append)
        assert doc.title == "T"
        assert [type(e) for e in doc.content] == [Heading, Paragraph, Paragraph]
        assert doc.content[0].text == "Good"
        assert doc.content[1].content == "Meant to be a table"
        assert warnings

    def test_strict_raises_on_truncated_json(self):
        with pytest.raises(json.JSONDecodeError):
            parse_spec_json('{"title": "T", "content": [', strict=True)

    def test_strict_raises_on_invalid_block(self):
        pydantic = pytest.importorskip("pydantic")
        data = {"title": "T", "content": [{"type": "heading"}]}
        with pytest.raises(pydantic.ValidationError):
            parse_spec_json(json.dumps(data), strict=True)

    def test_warning_callback_on_truncation(self):
        warnings: list[str] = []
        parse_spec_json(
            '{"title": "T", "content": [{"type": "paragraph", "text": "Hi',
            on_warning=warnings.append,
        )
        assert warnings


class TestSynonymVocabulary:
    def test_pydantic_path(self):
        pytest.importorskip("pydantic")
        doc = parse_spec_json(json.dumps(SYNONYM_DOC), strict=True)
        _assert_synonyms_resolved(doc)

    def test_manual_path(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "emboss.adapters.pydantic_schema", None)
        doc = parse_spec_json(json.dumps(SYNONYM_DOC))
        _assert_synonyms_resolved(doc)

    def test_canonical_tags_on_manual_path(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "emboss.adapters.pydantic_schema", None)
        data = {
            "title": "T",
            "content": [
                {"type": "bullets", "items": ["a"]},
                {"type": "math", "source": "x^2"},
                {"type": "rule"},
            ],
        }
        doc = parse_spec_json(json.dumps(data))
        assert isinstance(doc.content[0], BulletList)
        assert isinstance(doc.content[1], MathBlock)
        assert isinstance(doc.content[2], HorizontalRule)

    def test_callout_content_field_synonym(self):
        pytest.importorskip("pydantic")
        data = {
            "title": "T",
            "content": [{"type": "callout", "content": "Body", "variant": "info"}],
        }
        doc = parse_spec_json(json.dumps(data), strict=True)
        assert isinstance(doc.content[0], Callout)
        assert doc.content[0].content == "Body"


class TestPageConfigAndToc:
    def test_columns_and_toc_map_through(self):
        pytest.importorskip("pydantic")
        data = {
            "title": "T",
            "toc": True,
            "page": {"preset": "letter", "columns": 2, "column_gap": 24},
            "content": [{"type": "paragraph", "text": "Hi"}],
        }
        doc = parse_spec_json(json.dumps(data), strict=True)
        assert doc.toc is True
        assert doc.page.columns == 2
        assert doc.page.column_gap == 24

    def test_column_gap_defaults(self):
        pytest.importorskip("pydantic")
        data = {
            "title": "T",
            "page": {"columns": 2},
            "content": [{"type": "paragraph", "text": "Hi"}],
        }
        doc = parse_spec_json(json.dumps(data), strict=True)
        assert doc.page.columns == 2
        assert doc.page.column_gap == 18.0
        assert doc.toc is False


class TestSmart:
    SMART_DOC = {
        "title": "Report",
        "content": [
            {"type": "heading", "text": 'The "Big" Picture -- 2024', "level": 1},
            {"type": "paragraph", "text": 'She said "hello"... it was 1/2 done.'},
        ],
    }

    def test_smart_typography_applied(self):
        pytest.importorskip("pydantic")
        doc = parse_spec_json(json.dumps(self.SMART_DOC), smart=True)
        text = doc.content[1].content
        assert "“" in text
        assert "…" in text

    def test_smart_off_leaves_text_unchanged(self):
        doc = parse_spec_json(json.dumps(self.SMART_DOC))
        assert doc.content[1].content == 'She said "hello"... it was 1/2 done.'

    def test_smart_runs_deterministically(self):
        pytest.importorskip("pydantic")
        payload = json.dumps(self.SMART_DOC)
        first = parse_spec_json(payload, smart=True).render()
        second = parse_spec_json(payload, smart=True).render()
        assert first == second

    def test_generate_accepts_smart(self):
        assert "smart" in inspect.signature(generate).parameters
