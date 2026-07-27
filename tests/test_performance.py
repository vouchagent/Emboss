"""Performance tests for Emboss.

Ensures that rendering large documents completes within a reasonable
time budget, and that key optimizations (caching, slots) are in effect.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document, TextRun  # noqa: E402
from emboss.typography.font_metrics import FontMetrics  # noqa: E402
from emboss.typography.line_breaking import Box, Glue, Line, Penalty, _Node  # noqa: E402
from emboss.layout.engine import LaidOutLine, PlacedBlock  # noqa: E402


class TestTextWidthCache:
    """FontMetrics.text_width() should cache repeated calls."""

    def test_cache_returns_same_result(self):
        metrics = FontMetrics.base14("Helvetica")
        first = metrics.text_width("Hello, world!", 12.0)
        second = metrics.text_width("Hello, world!", 12.0)
        assert first == second

    def test_cache_hit_is_faster(self):
        metrics = FontMetrics.base14("Helvetica")
        text = "The quick brown fox jumps over the lazy dog." * 10

        # Prime the cache
        metrics.text_width(text, 12.0)

        # Time many cached calls
        start = time.perf_counter()
        for _ in range(10_000):
            metrics.text_width(text, 12.0)
        cached_time = time.perf_counter() - start

        # Time many uncached calls (different sizes each time)
        metrics2 = FontMetrics.base14("Helvetica")
        start = time.perf_counter()
        for i in range(10_000):
            metrics2.text_width(text, 12.0 + i * 0.001)
        uncached_time = time.perf_counter() - start

        # Cached should be noticeably faster
        assert cached_time < uncached_time

    def test_cache_size_limit(self):
        metrics = FontMetrics.base14("Helvetica")
        # Generate more than 4096 unique cache entries
        for i in range(5000):
            metrics.text_width(f"text_{i}", 12.0)
        # Should not crash and cache should not grow unbounded
        assert len(metrics._text_width_cache) <= 4096

    def test_different_inputs_different_results(self):
        metrics = FontMetrics.base14("Helvetica")
        w1 = metrics.text_width("Hello", 12.0)
        metrics.text_width("World", 12.0)
        # Different strings have different widths (unless coincidence)
        # but different sizes definitely differ
        w3 = metrics.text_width("Hello", 24.0)
        assert w3 == pytest.approx(w1 * 2.0)

    def test_empty_text_returns_zero(self):
        metrics = FontMetrics.base14("Helvetica")
        assert metrics.text_width("", 12.0) == 0.0


class TestSlotsOptimization:
    """Hot-path dataclasses should use __slots__ for memory efficiency."""

    def test_box_has_slots(self):
        assert hasattr(Box, "__slots__")
        b = Box(width=10.0, text="x")
        # frozen + slots raises TypeError or AttributeError depending on version
        with pytest.raises((AttributeError, TypeError)):
            b.arbitrary = True  # type: ignore

    def test_glue_has_slots(self):
        assert hasattr(Glue, "__slots__")
        g = Glue(width=5.0)
        with pytest.raises((AttributeError, TypeError)):
            g.arbitrary = True  # type: ignore

    def test_penalty_has_slots(self):
        assert hasattr(Penalty, "__slots__")
        p = Penalty(penalty=50.0)
        with pytest.raises((AttributeError, TypeError)):
            p.arbitrary = True  # type: ignore

    def test_line_has_slots(self):
        assert hasattr(Line, "__slots__")

    def test_node_has_slots(self):
        assert hasattr(_Node, "__slots__")

    def test_laid_out_line_has_slots(self):
        assert hasattr(LaidOutLine, "__slots__")

    def test_placed_block_has_slots(self):
        assert hasattr(PlacedBlock, "__slots__")


class TestLargeDocumentPerformance:
    """Rendering a substantial document should complete quickly."""

    def test_large_document_performance(self):
        """Generate a 50-page document and verify it renders within budget."""
        doc = Document(title="Performance Test", style="corporate")

        # Build varied content: 200 paragraphs with headings and tables
        for i in range(200):
            if i % 20 == 0:
                doc.heading(f"Chapter {i // 20 + 1}", level=1)
            elif i % 10 == 0:
                doc.heading(f"Section {i // 10}", level=2)

            if i % 15 == 0:
                doc.table(
                    headers=["Name", "Value", "Status"],
                    rows=[[f"Item {j}", f"${j * 100:,}", "Active"] for j in range(5)],
                )
            else:
                # Varied paragraph lengths
                sentence = "The quick brown fox jumps over the lazy dog. "
                repeat = (i % 5) + 2
                doc.paragraph(sentence * repeat)

        start = time.perf_counter()
        pdf_bytes = doc.render()
        elapsed = time.perf_counter() - start

        assert len(pdf_bytes) > 0
        assert elapsed < 10.0, (
            f"Large document render took {elapsed:.2f}s, expected < 10s"
        )

    def test_text_heavy_document(self):
        """A document with many text runs should benefit from caching."""
        doc = Document(title="Text Heavy", style="corporate")

        # Use the same text run repeatedly to exercise the cache
        repeated_text = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
        for i in range(100):
            doc.paragraph(
                [
                    TextRun(repeated_text, bold=(i % 3 == 0)),
                    TextRun(repeated_text, italic=(i % 2 == 0)),
                ]
            )

        start = time.perf_counter()
        pdf_bytes = doc.render()
        elapsed = time.perf_counter() - start

        assert len(pdf_bytes) > 0
        assert elapsed < 5.0, (
            f"Text-heavy document render took {elapsed:.2f}s, expected < 5s"
        )


class TestFontMetricsHashable:
    """FontMetrics must be hashable for use in sets/dicts."""

    def test_hashable(self):
        m = FontMetrics.base14("Helvetica")
        h = hash(m)
        assert isinstance(h, int)

    def test_identity_equality(self):
        m1 = FontMetrics.base14("Helvetica")
        m2 = FontMetrics.base14("Helvetica")
        # Different instances are not equal
        assert m1 != m2
        # Same instance is equal to itself
        assert m1 == m1

    def test_usable_in_dict(self):
        m = FontMetrics.base14("Helvetica")
        d = {m: "helvetica"}
        assert d[m] == "helvetica"
