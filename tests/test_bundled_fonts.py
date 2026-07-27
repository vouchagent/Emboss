"""Tests for the bundled OFL serif/sans/mono font set."""

from pathlib import Path

import pytest

from emboss import Document
from emboss.bundled_fonts import (
    BUNDLED_FAMILIES,
    FAMILY_ALIASES,
    bundled_font_path,
    register_bundled_fonts,
)
from emboss.styles import Style
from emboss.typography.font_metrics import FontRegistry

FONT_DIR = Path(__file__).resolve().parents[1] / "src" / "emboss" / "fonts"

ALL_FILES = sorted(
    {name for styles in BUNDLED_FAMILIES.values() for name in styles.values()}
)


class TestBundledFiles:
    def test_all_declared_files_exist(self):
        for filename in ALL_FILES:
            assert (FONT_DIR / filename).is_file(), filename

    @pytest.mark.parametrize("filename", ALL_FILES)
    def test_file_parses_with_fonttools(self, filename):
        from fontTools.ttLib import TTFont

        font = TTFont(str(FONT_DIR / filename), lazy=True)
        try:
            cmap = font.getBestCmap()
            assert ord("A") in cmap
            assert ord("é") in cmap  # e-acute
            assert ord("—") in cmap  # em dash
            assert ord("Ж") in cmap  # Cyrillic Zhe
            assert ord("Ω") in cmap  # Greek Omega
        finally:
            font.close()

    def test_total_bundle_under_budget(self):
        total = sum((FONT_DIR / name).stat().st_size for name in ALL_FILES)
        assert total < 3.5 * 1024 * 1024

    def test_license_files_present(self):
        licenses = list(FONT_DIR.glob("LICENSE-*.txt"))
        assert len(licenses) >= 3
        for path in licenses:
            text = path.read_text(encoding="utf-8")
            assert "SIL OPEN FONT LICENSE" in text.upper()


class TestBundledFontPath:
    def test_regular_paths_exist(self):
        for family in BUNDLED_FAMILIES:
            assert bundled_font_path(family).is_file()

    def test_bold_italic_variants(self):
        path = bundled_font_path("Source Serif 4", bold=True, italic=True)
        assert path.name == "SourceSerif4-BoldIt.ttf"

    def test_alias_resolves(self):
        assert bundled_font_path("Emboss Serif") == bundled_font_path("Source Serif 4")
        assert bundled_font_path("emboss mono", bold=True).name == (
            "SourceCodePro-Bold.ttf"
        )

    def test_mono_italic_falls_back_to_upright(self):
        path = bundled_font_path("Source Code Pro", italic=True)
        assert path.name == "SourceCodePro-Regular.ttf"

    def test_unknown_family_raises(self):
        with pytest.raises(KeyError):
            bundled_font_path("Comic Serif Neue")


class TestRegistration:
    def test_returns_new_registry_when_none(self):
        registry = register_bundled_fonts()
        assert isinstance(registry, FontRegistry)
        for family in BUNDLED_FAMILIES:
            assert registry.is_available(family)
        for alias in FAMILY_ALIASES:
            assert registry.is_available(alias)

    def test_resolves_embedded_metrics(self):
        registry = register_bundled_fonts()
        metrics = registry.resolve("Source Serif 4")
        assert metrics.is_embedded
        assert metrics.name == "SourceSerif4-Regular"
        bold = registry.resolve("Source Sans 3", bold=True)
        assert bold.name == "SourceSans3-Bold"

    def test_alias_resolves_same_file(self):
        registry = register_bundled_fonts()
        alias = registry.resolve("Emboss Mono")
        canonical = registry.resolve("Source Code Pro")
        assert alias.font_path == canonical.font_path

    def test_idempotent(self):
        registry = register_bundled_fonts()
        register_bundled_fonts(registry)
        metrics = registry.resolve("Source Serif 4")
        assert metrics.is_embedded

    def test_registers_into_document_registry(self):
        doc = Document(title="Bundled")
        result = register_bundled_fonts(doc.fonts)
        assert result is doc.fonts
        assert doc.fonts.is_available("Source Sans 3")


class TestRenderWithBundledFont:
    def _render(self, family):
        doc = Document(title="Bundled Font Render")
        register_bundled_fonts(doc.fonts)
        doc.paragraph(
            "Precision — café, “quotes”, Ж, Ω.",
            style=Style(font_family=family),
        )
        return doc.render()

    def test_embedded_font_markers(self):
        pdf = self._render("Source Serif 4")
        assert b"/Subtype /Type0" in pdf
        assert b"/Subtype /CIDFontType2" in pdf
        assert b"/FontFile2" in pdf

    def test_alias_family_renders_embedded(self):
        pdf = self._render("Emboss Sans")
        assert b"/FontFile2" in pdf

    def test_deterministic_double_render(self):
        assert self._render("Source Serif 4") == self._render("Source Serif 4")
