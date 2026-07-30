"""Tests for AI provenance / content credentials in the reproducibility manifest."""

import io

import pytest

from emboss import Document
from emboss.manifest import GeneratorInfo, build_manifest, read_generator_info

pikepdf = pytest.importorskip("pikepdf")


class TestGeneratorInfo:
    def test_from_prompt_hashes_not_stores(self):
        info = GeneratorInfo.from_prompt("a secret prompt", model="m", provider="p")
        assert info.prompt_sha256
        assert "secret" not in info.prompt_sha256

    def test_from_prompt_is_deterministic(self):
        a = GeneratorInfo.from_prompt("same text")
        b = GeneratorInfo.from_prompt("same text")
        assert a.prompt_sha256 == b.prompt_sha256

    def test_different_prompts_hash_differently(self):
        a = GeneratorInfo.from_prompt("prompt one")
        b = GeneratorInfo.from_prompt("prompt two")
        assert a.prompt_sha256 != b.prompt_sha256

    def test_to_dict_omits_unset_fields(self):
        info = GeneratorInfo(model="m")
        d = info.to_dict()
        assert d == {"model": "m"}

    def test_to_dict_from_dict_round_trip(self):
        info = GeneratorInfo(
            model="claude-sonnet-5",
            provider="anthropic",
            prompt_sha256="abc123",
            params={"temperature": 0.7},
            reviewed_by="R. Patel",
            reviewed_at="2026-07-29",
        )
        restored = GeneratorInfo.from_dict(info.to_dict())
        assert restored == info


class TestManifestIntegration:
    def test_generator_recorded_in_manifest_dict(self):
        doc = Document(title="D")
        doc.paragraph("Hello.")
        gen = GeneratorInfo(model="m", provider="p")
        manifest = build_manifest(doc, generator=gen)
        assert manifest["generator"] == {"model": "m", "provider": "p"}

    def test_no_generator_omits_key(self):
        doc = Document(title="D")
        doc.paragraph("Hello.")
        manifest = build_manifest(doc)
        assert "generator" not in manifest

    def test_document_generator_field_is_fallback(self):
        doc = Document(title="D")
        doc.paragraph("Hello.")
        doc.generator = GeneratorInfo(model="fallback-model")
        manifest = build_manifest(doc)
        assert manifest["generator"]["model"] == "fallback-model"

    def test_explicit_generator_overrides_document_field(self):
        doc = Document(title="D")
        doc.paragraph("Hello.")
        doc.generator = GeneratorInfo(model="doc-level")
        manifest = build_manifest(doc, generator=GeneratorInfo(model="explicit"))
        assert manifest["generator"]["model"] == "explicit"

    def test_backward_compat_manifest_without_generator_key_still_valid(self):
        doc = Document(title="D")
        doc.paragraph("Hello.")
        manifest = build_manifest(doc)
        assert set(manifest.keys()) == {
            "spec_sha256",
            "emboss_version",
            "fonts",
            "render_options",
        }


class TestRenderAndRead:
    def test_render_with_generator_embeds_it(self):
        doc = Document(title="D")
        doc.paragraph("Hello.")
        gen = GeneratorInfo.from_prompt(
            "write a report",
            model="claude-sonnet-5",
            provider="anthropic",
            reviewed_by="R. Patel",
            reviewed_at="2026-07-29",
        )
        pdf = doc.render(manifest=True, generator=gen)
        info = read_generator_info(pdf)
        assert info.model == "claude-sonnet-5"
        assert info.provider == "anthropic"
        assert info.reviewed_by == "R. Patel"
        assert info.reviewed_at == "2026-07-29"
        assert info.prompt_sha256 == gen.prompt_sha256

    def test_read_generator_info_none_without_manifest(self):
        doc = Document(title="D")
        doc.paragraph("Hello.")
        pdf = doc.render()
        assert read_generator_info(pdf) is None

    def test_read_generator_info_none_with_manifest_but_no_generator(self):
        doc = Document(title="D")
        doc.paragraph("Hello.")
        pdf = doc.render(manifest=True)
        assert read_generator_info(pdf) is None

    def test_document_generator_field_used_by_render(self):
        doc = Document(title="D")
        doc.paragraph("Hello.")
        doc.generator = GeneratorInfo(model="via-field")
        pdf = doc.render(manifest=True)
        info = read_generator_info(pdf)
        assert info.model == "via-field"

    def test_manifest_still_attaches_as_af_file(self):
        doc = Document(title="D")
        doc.paragraph("Hello.")
        gen = GeneratorInfo(model="m")
        pdf = doc.render(manifest=True, generator=gen)
        with pikepdf.open(io.BytesIO(pdf)) as p:
            assert "emboss-manifest.json" in p.attachments

    def test_determinism(self):
        doc = Document(title="D")
        doc.paragraph("Hello.")
        gen = GeneratorInfo.from_prompt("p", model="m", provider="q")
        assert doc.render(manifest=True, generator=gen) == doc.render(
            manifest=True, generator=gen
        )


class TestGenerateFunction:
    """generate() (the one-liner LLM tier) auto-populates GeneratorInfo."""

    def _stub(self, monkeypatch, result):
        import importlib

        # emboss/__init__.py does `from .generate import generate`, which
        # rebinds the `emboss.generate` attribute to the function; import
        # the submodule directly from sys.modules to reach _call_anthropic.
        generate_module = importlib.import_module("emboss.generate")

        def fake_call(prompt, system, model, api_key, structured=True, history=None):
            return result

        monkeypatch.setattr(generate_module, "_call_anthropic", fake_call)
        return generate_module

    def test_manifest_true_auto_populates_generator(self, monkeypatch):
        generate_module = self._stub(
            monkeypatch,
            {"title": "T", "content": [{"type": "paragraph", "text": "Hi."}]},
        )
        pdf = generate_module.generate("write something", manifest=True)
        info = read_generator_info(pdf)
        assert info.model == "claude-sonnet-5"
        assert info.provider == "anthropic"
        assert info.prompt_sha256

    def test_default_call_unchanged_no_manifest(self, monkeypatch):
        generate_module = self._stub(
            monkeypatch,
            {"title": "T", "content": [{"type": "paragraph", "text": "Hi."}]},
        )
        pdf = generate_module.generate("write something")
        assert read_generator_info(pdf) is None

    def test_explicit_generator_overrides_auto(self, monkeypatch):
        generate_module = self._stub(
            monkeypatch,
            {"title": "T", "content": [{"type": "paragraph", "text": "Hi."}]},
        )
        pdf = generate_module.generate(
            "write something",
            manifest=True,
            generator=GeneratorInfo(model="custom"),
        )
        info = read_generator_info(pdf)
        assert info.model == "custom"


class TestMcpTool:
    def test_get_provenance_found(self, tmp_path):
        from emboss.mcp_server import dispatch

        doc = Document(title="D")
        doc.paragraph("Hello.")
        gen = GeneratorInfo(model="m", provider="p", reviewed_by="R")
        path = tmp_path / "doc.pdf"
        path.write_bytes(doc.render(manifest=True, generator=gen))
        result = dispatch("get_provenance", {"pdf_path": str(path)})
        assert result["found"]
        assert result["model"] == "m"
        assert result["reviewed_by"] == "R"

    def test_get_provenance_not_found(self, tmp_path):
        from emboss.mcp_server import dispatch

        doc = Document(title="D")
        doc.paragraph("Hello.")
        path = tmp_path / "doc.pdf"
        path.write_bytes(doc.render())
        result = dispatch("get_provenance", {"pdf_path": str(path)})
        assert not result["found"]
