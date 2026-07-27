"""Tests for the bundled full en-US hyphenation pattern set."""

import gzip
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from emboss.typography import hyphenation  # noqa: E402
from emboss.typography.hyphenation import Hyphenator  # noqa: E402

CUSTOM_TEX = """\
% custom fixture patterns
\\patterns{ % comment after brace
ab1c
% full comment line
x1y2z
}
\\hyphenation{
wid-get
gadget
}
"""


class TestFullPatternResults:
    def test_hyphenation_word(self):
        assert Hyphenator().break_points("hyphenation") == [2, 6]

    def test_associate_uses_exception(self):
        assert Hyphenator().break_points("associate") == [2, 4]

    def test_computer(self):
        # righthyphenmin=3 forbids put-er, matching TeX's com-puter.
        assert Hyphenator().break_points("computer") == [3]

    def test_algorithm(self):
        assert Hyphenator().break_points("algorithm") == [2, 4]

    def test_syllables_join_back_to_word(self):
        for word in ["hyphenation", "associate", "algorithm", "typography"]:
            assert "".join(Hyphenator().syllables(word)) == word

    def test_min_prefix_and_suffix_respected(self):
        hyphenator = Hyphenator()
        for word in ["hyphenation", "algorithm", "determination"]:
            for point in hyphenator.break_points(word):
                assert point >= hyphenator.min_prefix
                assert len(word) - point >= hyphenator.min_suffix


class TestBundledLoading:
    def test_bundled_file_loads_full_set(self):
        assert len(Hyphenator()._patterns) > 4000

    def test_data_file_exists_in_package(self):
        path = Path(hyphenation.__file__).parent / "patterns" / "en_us.txt.gz"
        assert path.is_file()
        text = gzip.decompress(path.read_bytes()).decode("utf-8")
        assert "\\patterns{" in text
        assert "\\hyphenation{" in text
        assert "copyright" in text.lower()

    def test_non_english_language_uses_fallback(self):
        hyphenator = Hyphenator(language="xx-XX")
        assert len(hyphenator._patterns) < 4000

    def test_fallback_when_data_file_missing(self, monkeypatch):
        def missing(language):
            raise FileNotFoundError(language)

        monkeypatch.setattr(hyphenation, "_read_bundled", missing)
        monkeypatch.setattr(hyphenation, "_BUNDLED_TABLES", {})
        hyphenator = Hyphenator()
        assert 0 < len(hyphenator._patterns) < 4000
        assert hyphenator.break_points("hyphenation"), "fallback still works"


class TestFromPatternFile:
    def _check(self, hyphenator):
        assert hyphenator._patterns["abc"] == (0, 0, 1, 0)
        assert hyphenator._patterns["xyz"] == (0, 1, 2, 0)
        assert hyphenator._exceptions["widget"] == ["wid", "get"]
        assert hyphenator._exceptions["gadget"] == ["gadget"]
        assert "comment" not in hyphenator._patterns
        assert "fixture" not in hyphenator._patterns

    def test_tex_file(self, tmp_path):
        path = tmp_path / "custom.tex"
        path.write_text(CUSTOM_TEX, encoding="utf-8")
        self._check(Hyphenator.from_pattern_file(path, language="xx"))

    def test_txt_file_bare_patterns(self, tmp_path):
        path = tmp_path / "custom.txt"
        path.write_text("ab1c\nx1y2z\n", encoding="utf-8")
        hyphenator = Hyphenator.from_pattern_file(path, language="xx")
        assert hyphenator._patterns["abc"] == (0, 0, 1, 0)
        assert hyphenator._patterns["xyz"] == (0, 1, 2, 0)

    def test_gz_file(self, tmp_path):
        path = tmp_path / "custom.txt.gz"
        path.write_bytes(gzip.compress(CUSTOM_TEX.encode("utf-8")))
        self._check(Hyphenator.from_pattern_file(path, language="xx"))

    def test_load_alias(self, tmp_path):
        path = tmp_path / "custom.tex"
        path.write_text(CUSTOM_TEX, encoding="utf-8")
        self._check(Hyphenator.load(path, language="xx"))


class TestBundledExceptions:
    def test_exception_block_is_honored(self):
        hyphenator = Hyphenator()
        assert hyphenator.break_points("table") == [2]  # ta-ble
        assert hyphenator.break_points("project") == []
        assert hyphenator.break_points("present") == []

    def test_user_exception_overrides_bundled(self):
        hyphenator = Hyphenator()
        hyphenator.add_exception("associate", ["asso", "ciate"])
        assert hyphenator.break_points("associate") == [4]


class TestDeterminism:
    def test_same_word_twice_same_result(self):
        hyphenator = Hyphenator()
        for word in ["hyphenation", "associate", "algorithm", "computer"]:
            assert hyphenator.break_points(word) == hyphenator.break_points(word)

    def test_fresh_instances_agree(self):
        first = Hyphenator().break_points("determination")
        second = Hyphenator().break_points("determination")
        assert first == second == [2, 5, 7, 9]
