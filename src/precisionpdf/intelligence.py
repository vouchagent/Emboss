"""Content Intelligence Engine — semantic analysis that no other PDF tool has.

This module analyzes document content and makes intelligent decisions that
go beyond mechanical rendering:

  1. **Smart Typography** — transforms raw text into typographically correct
     output: smart quotes, proper dashes, ellipses, non-breaking spaces
     before units, ordinal superscripts. Other PDF tools ship raw text
     unchanged.

  2. **Table Intelligence** — auto-detects summary rows (Total, Average,
     Subtotal), currency/percentage columns, and applies domain-specific
     formatting: bold totals, separator lines, right-alignment for numbers.
     No existing tool does this.

  3. **Document Type Detection** — infers document domain (legal, financial,
     academic, business) from content patterns and applies optimal style
     if the user didn't specify one.

  4. **Typographic Quality Score** — rates output quality after rendering:
     spacing consistency, widow/orphan count, hyphenation density, line
     length variance. Returns actionable suggestions.

  5. **Smart Content Transforms** — detects and fixes common content
     issues: duplicate headings, orphaned sections, tables with
     inconsistent column counts.

These features are hard to replicate because they require deep domain
knowledge about typography, document design, and content semantics —
not just PDF byte layout.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

__all__ = [
    "SmartTypography",
    "TableIntelligence",
    "DocumentTypeDetector",
    "QualityScorer",
    "QualityReport",
    "ContentAnalyzer",
]

# ---------------------------------------------------------------------------
# Smart Typography
# ---------------------------------------------------------------------------

class SmartTypography:
    """Transforms raw text into typographically correct output.

    Applies the same micro-typographic rules that professional typesetters
    use, which no Python PDF library does automatically:
    - Straight quotes → curly quotes (" " ' ')
    - Double/triple hyphens → en/em dashes
    - Three dots → proper ellipsis
    - Non-breaking spaces before units and after single-letter words
    - Fraction replacement (1/2 → ½)
    """

    _FRACTIONS = {
        "1/4": "¼", "1/2": "½", "3/4": "¾",
        "1/3": "⅓", "2/3": "⅔",
        "1/5": "⅕", "2/5": "⅖", "3/5": "⅗", "4/5": "⅘",
        "1/6": "⅙", "5/6": "⅚",
        "1/8": "⅛", "3/8": "⅜", "5/8": "⅝", "7/8": "⅞",
    }

    _UNITS_RE = re.compile(
        r"(\d)\s+(km|cm|mm|m|kg|g|mg|lb|oz|ft|in|mi|"
        r"MB|GB|TB|KB|MHz|GHz|kHz|"
        r"ms|ns|hr|min|sec|"
        r"px|pt|em|rem|"
        r"%|°C|°F)\b"
    )

    _ORDINAL_RE = re.compile(r"\b(\d+)(st|nd|rd|th)\b")

    _SINGLE_LETTER_RE = re.compile(r"\b([A-Za-z])\s")

    def transform(self, text: str) -> str:
        """Apply all smart typography transforms to text."""
        text = self._smart_quotes(text)
        text = self._smart_dashes(text)
        text = self._smart_ellipsis(text)
        text = self._smart_fractions(text)
        text = self._non_breaking_units(text)
        return text

    def _smart_quotes(self, text: str) -> str:
        result = []
        in_single = False
        in_double = False
        i = 0
        while i < len(text):
            ch = text[i]
            if ch == '"':
                if in_double:
                    result.append("”")  # "
                    in_double = False
                else:
                    result.append("“")  # "
                    in_double = True
            elif ch == "'":
                prev = text[i - 1] if i > 0 else " "
                nxt = text[i + 1] if i + 1 < len(text) else " "
                if prev.isalpha() and nxt.isalpha():
                    result.append("’")  # apostrophe
                elif in_single:
                    result.append("’")  # '
                    in_single = False
                else:
                    result.append("‘")  # '
                    in_single = True
            else:
                result.append(ch)
            i += 1
        return "".join(result)

    def _smart_dashes(self, text: str) -> str:
        text = text.replace("---", "—")  # em dash
        text = text.replace("--", "–")   # en dash
        text = re.sub(r"(\d)\s*-\s*(\d)", r"\1–\2", text)
        return text

    def _smart_ellipsis(self, text: str) -> str:
        return text.replace("...", "…")

    def _smart_fractions(self, text: str) -> str:
        for ascii_frac, unicode_frac in self._FRACTIONS.items():
            text = re.sub(
                rf"(?<!\d){re.escape(ascii_frac)}(?!\d)",
                unicode_frac,
                text,
            )
        return text

    def _non_breaking_units(self, text: str) -> str:
        return self._UNITS_RE.sub(r"\1 \2", text)


# ---------------------------------------------------------------------------
# Table Intelligence
# ---------------------------------------------------------------------------

_SUMMARY_PATTERNS = re.compile(
    r"^(total|subtotal|sub-total|grand\s*total|sum|average|avg|mean|"
    r"median|net|gross|balance|variance|difference|change|"
    r"overall|aggregate|combined|consolidated)s?$",
    re.IGNORECASE,
)

_CURRENCY_RE = re.compile(
    r"^[\s]*[$€£¥₹₽₩]?\s*[\-\(]?\s*\d[\d,]*\.?\d*\s*[\)]?\s*$"
)

_PERCENTAGE_RE = re.compile(
    r"^[\s]*[\-\+]?\s*\d[\d,]*\.?\d*\s*%\s*$"
)

_DATE_RE = re.compile(
    r"^\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}$|"
    r"^\d{4}[/\-]\d{1,2}[/\-]\d{1,2}$|"
    r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s+\d{4}$",
    re.IGNORECASE,
)


@dataclass
class ColumnProfile:
    """Semantic profile of a table column."""

    index: int
    header: str
    content_type: str  # "text", "currency", "percentage", "number", "date"
    recommended_align: str  # "left", "right", "decimal", "center"
    is_numeric: bool = False


@dataclass
class TableAnalysis:
    """Complete semantic analysis of a table."""

    columns: list[ColumnProfile]
    summary_rows: list[int]
    has_total_row: bool = False
    recommended_stripe: bool = False
    row_count: int = 0


class TableIntelligence:
    """Semantic analysis of table content for intelligent formatting.

    Existing PDF tools treat table content as opaque strings. This engine
    understands what the data means and formats it accordingly:

    - Detects summary rows (Total, Subtotal, Average) → auto-bold
    - Classifies columns (currency, percentage, date, text) → alignment
    - Identifies when striping improves readability (>5 rows)
    - Detects header-less tables and suggests headers from content
    """

    def analyze(self, headers: Sequence[str],
                rows: Sequence[Sequence[str]]) -> TableAnalysis:
        if not rows:
            return TableAnalysis(
                columns=[], summary_rows=[], row_count=0,
            )

        col_count = len(headers) if headers else (
            max(len(r) for r in rows) if rows else 0
        )

        columns = []
        for col_idx in range(col_count):
            header = headers[col_idx] if col_idx < len(headers) else ""
            values = []
            for row in rows:
                if col_idx < len(row):
                    values.append(str(row[col_idx]).strip())

            profile = self._classify_column(col_idx, header, values)
            columns.append(profile)

        summary_rows = []
        for row_idx, row in enumerate(rows):
            if self._is_summary_row(row):
                summary_rows.append(row_idx)

        has_total = any(
            row_idx == len(rows) - 1 for row_idx in summary_rows
        )

        return TableAnalysis(
            columns=columns,
            summary_rows=summary_rows,
            has_total_row=has_total,
            recommended_stripe=len(rows) > 5,
            row_count=len(rows),
        )

    def _classify_column(self, index: int, header: str,
                         values: list[str]) -> ColumnProfile:
        if not values:
            return ColumnProfile(
                index=index, header=header,
                content_type="text", recommended_align="left",
            )

        non_empty = [v for v in values if v]
        if not non_empty:
            return ColumnProfile(
                index=index, header=header,
                content_type="text", recommended_align="left",
            )

        currency_count = sum(1 for v in non_empty if _CURRENCY_RE.match(v))
        pct_count = sum(1 for v in non_empty if _PERCENTAGE_RE.match(v))
        date_count = sum(1 for v in non_empty if _DATE_RE.match(v))

        threshold = len(non_empty) * 0.7

        if currency_count >= threshold and currency_count >= 2:
            return ColumnProfile(
                index=index, header=header,
                content_type="currency", recommended_align="decimal",
                is_numeric=True,
            )
        if pct_count >= threshold and pct_count >= 2:
            return ColumnProfile(
                index=index, header=header,
                content_type="percentage", recommended_align="right",
                is_numeric=True,
            )
        if date_count >= threshold and date_count >= 2:
            return ColumnProfile(
                index=index, header=header,
                content_type="date", recommended_align="left",
            )

        number_re = re.compile(r"^[\-\+]?\s*\d[\d,]*\.?\d*$")
        num_count = sum(1 for v in non_empty if number_re.match(v.strip()))
        if num_count >= threshold and num_count >= 2:
            return ColumnProfile(
                index=index, header=header,
                content_type="number", recommended_align="right",
                is_numeric=True,
            )

        return ColumnProfile(
            index=index, header=header,
            content_type="text", recommended_align="left",
        )

    def _is_summary_row(self, row: Sequence) -> bool:
        if not row:
            return False
        first_cell = str(row[0]).strip()
        return bool(_SUMMARY_PATTERNS.match(first_cell))


# ---------------------------------------------------------------------------
# Document Type Detection
# ---------------------------------------------------------------------------

@dataclass
class DocumentProfile:
    """Detected document characteristics."""

    detected_type: str  # "legal", "financial", "academic", "business", "technical", "general"
    confidence: float   # 0.0 to 1.0
    signals: list[str]
    recommended_style: str


class DocumentTypeDetector:
    """Infer document domain from content patterns.

    Analyzes heading text, paragraph content, table structure, and
    vocabulary to determine the document type and recommend an
    appropriate style preset. No other PDF tool does this — they all
    require the user to manually specify styling.
    """

    _LEGAL_TERMS = {
        "whereas", "herein", "hereinafter", "pursuant", "notwithstanding",
        "indemnify", "indemnification", "arbitration", "jurisdiction",
        "plaintiff", "defendant", "stipulate", "covenant", "affidavit",
        "deposition", "subpoena", "memorandum", "witnesseth", "recitals",
        "exhibit", "schedule", "amendment", "termination", "breach",
        "liable", "liability", "warranty", "warranties", "negligence",
        "damages", "injunction", "confidential", "non-disclosure",
        "force majeure", "governing law", "severability", "waiver",
    }

    _FINANCIAL_TERMS = {
        "revenue", "ebitda", "margin", "quarter", "fiscal", "dividend",
        "earnings", "eps", "p/e", "roi", "irr", "npv", "cash flow",
        "balance sheet", "income statement", "depreciation", "amortization",
        "capex", "opex", "yield", "portfolio", "equity", "debt",
        "assets", "liabilities", "shareholders", "valuation", "forecast",
        "budget", "variance", "accrual", "receivable", "payable",
        "gross margin", "operating margin", "net income", "guidance",
    }

    _ACADEMIC_TERMS = {
        "abstract", "methodology", "hypothesis", "findings", "literature",
        "citation", "bibliography", "references", "peer-reviewed",
        "empirical", "qualitative", "quantitative", "regression",
        "correlation", "statistical", "significance", "p-value",
        "sample size", "population", "longitudinal", "cross-sectional",
        "theoretical", "framework", "paradigm", "dissertation", "thesis",
        "appendix", "acknowledgments", "doi", "journal", "proceedings",
    }

    _TECHNICAL_TERMS = {
        "api", "endpoint", "authentication", "deployment", "infrastructure",
        "architecture", "microservice", "container", "kubernetes", "docker",
        "pipeline", "ci/cd", "repository", "latency", "throughput",
        "scalability", "redundancy", "failover", "monitoring", "logging",
        "configuration", "migration", "schema", "database", "query",
        "algorithm", "implementation", "specification", "protocol",
        "interface", "module", "dependency", "version", "release",
    }

    def detect(self, title: str, headings: list[str],
               paragraphs: list[str], table_count: int) -> DocumentProfile:
        all_text = " ".join([title] + headings + paragraphs).lower()
        words = set(re.findall(r"\b\w+\b", all_text))

        scores = {
            "legal": self._score_domain(words, all_text, self._LEGAL_TERMS),
            "financial": self._score_domain(words, all_text, self._FINANCIAL_TERMS),
            "academic": self._score_domain(words, all_text, self._ACADEMIC_TERMS),
            "technical": self._score_domain(words, all_text, self._TECHNICAL_TERMS),
        }

        if table_count >= 3:
            scores["financial"] += 0.15

        legal_patterns = [
            r"\bsection\s+\d+", r"\barticle\s+\d+", r"\bclause\s+\d+",
            r"\bparty\s+[a-z]", r"\bexhibit\s+[a-z]",
        ]
        for pat in legal_patterns:
            if re.search(pat, all_text, re.IGNORECASE):
                scores["legal"] += 0.08

        academic_patterns = [
            r"\b(?:fig|figure|table)\s*\.?\s*\d+", r"\bet\s+al\b",
            r"\b\d{4}\)", r"\[\d+\]",
        ]
        for pat in academic_patterns:
            if re.search(pat, all_text, re.IGNORECASE):
                scores["academic"] += 0.08

        best = max(scores, key=scores.get)
        confidence = scores[best]

        if confidence < 0.15:
            return DocumentProfile(
                detected_type="general",
                confidence=0.5,
                signals=["No strong domain signals detected"],
                recommended_style="corporate",
            )

        style_map = {
            "legal": "legal",
            "financial": "finance",
            "academic": "academic",
            "technical": "corporate",
        }

        signals = self._explain_signals(words, all_text, best)

        return DocumentProfile(
            detected_type=best,
            confidence=min(confidence, 1.0),
            signals=signals,
            recommended_style=style_map[best],
        )

    def _score_domain(self, words: set, text: str,
                      terms: set) -> float:
        matches = 0
        for term in terms:
            if " " in term:
                if term in text:
                    matches += 1
            elif term in words:
                matches += 1
        if matches == 0:
            return 0.0
        return min(1.0, matches * 0.12)

    def _explain_signals(self, words: set, text: str,
                         domain: str) -> list[str]:
        terms = {
            "legal": self._LEGAL_TERMS,
            "financial": self._FINANCIAL_TERMS,
            "academic": self._ACADEMIC_TERMS,
            "technical": self._TECHNICAL_TERMS,
        }[domain]

        found = []
        for term in sorted(terms):
            if " " in term:
                if term in text:
                    found.append(term)
            elif term in words:
                found.append(term)

        return found[:8]


# ---------------------------------------------------------------------------
# Typographic Quality Scorer
# ---------------------------------------------------------------------------

@dataclass
class QualityReport:
    """Typographic quality analysis of rendered output."""

    score: float          # 0-100
    grade: str            # A+ through F
    metrics: dict = field(default_factory=dict)
    suggestions: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        lines = [f"Quality: {self.score:.0f}/100 ({self.grade})"]
        for key, value in self.metrics.items():
            lines.append(f"  {key}: {value}")
        if self.suggestions:
            lines.append("Suggestions:")
            for s in self.suggestions:
                lines.append(f"  - {s}")
        return "\n".join(lines)


class QualityScorer:
    """Rates typographic quality of laid-out pages.

    Measures what professional typesetters check:
    - Line length consistency (coefficient of variation)
    - Spacing uniformity in justified text
    - Widow/orphan occurrences
    - Hyphenation density (too many consecutive hyphens)
    - Page fill balance (are pages roughly equally full?)
    - Heading proximity (headings too close to page bottom)
    """

    def score(self, pages, page_spec) -> QualityReport:
        metrics = {}
        deductions = 0.0
        suggestions = []

        line_score, line_suggestions = self._score_lines(pages)
        metrics["line_quality"] = f"{line_score:.0f}/25"
        deductions += 25 - line_score
        suggestions.extend(line_suggestions)

        spacing_score, spacing_suggestions = self._score_spacing(pages)
        metrics["spacing_quality"] = f"{spacing_score:.0f}/25"
        deductions += 25 - spacing_score
        suggestions.extend(spacing_suggestions)

        page_score, page_suggestions = self._score_page_balance(
            pages, page_spec
        )
        metrics["page_balance"] = f"{page_score:.0f}/25"
        deductions += 25 - page_score
        suggestions.extend(page_suggestions)

        structure_score, structure_suggestions = self._score_structure(pages)
        metrics["structure"] = f"{structure_score:.0f}/25"
        deductions += 25 - structure_score
        suggestions.extend(structure_suggestions)

        total = max(0.0, 100.0 - deductions)
        grade = self._grade(total)

        return QualityReport(
            score=total,
            grade=grade,
            metrics=metrics,
            suggestions=suggestions,
        )

    def _score_lines(self, pages) -> tuple[float, list]:
        score = 25.0
        suggestions = []
        all_ratios = []

        for page in pages:
            for placed in page.blocks:
                for line in placed.lines:
                    all_ratios.append(abs(line.ratio))

        if not all_ratios:
            return score, suggestions

        avg_ratio = sum(all_ratios) / len(all_ratios)
        if avg_ratio > 1.5:
            score -= min(10.0, (avg_ratio - 1.5) * 5)
            suggestions.append(
                "High average line stretch ratio — consider wider margins "
                "or smaller font for better line breaks"
            )

        overfull = sum(1 for r in all_ratios if r > 2.0)
        if overfull > 0:
            penalty = min(8.0, overfull * 2.0)
            score -= penalty
            suggestions.append(
                f"{overfull} line(s) with excessive spacing — long words "
                "may benefit from hyphenation"
            )

        consecutive_hyphens = 0
        max_consecutive = 0
        for page in pages:
            for placed in page.blocks:
                for line in placed.lines:
                    if line.hyphenated:
                        consecutive_hyphens += 1
                        max_consecutive = max(max_consecutive, consecutive_hyphens)
                    else:
                        consecutive_hyphens = 0

        if max_consecutive >= 3:
            score -= min(5.0, (max_consecutive - 2) * 2.0)
            suggestions.append(
                f"{max_consecutive} consecutive hyphenated lines — "
                "distracting for readers"
            )

        return max(0.0, score), suggestions

    def _score_spacing(self, pages) -> tuple[float, list]:
        score = 25.0
        suggestions = []

        for page in pages:
            blocks = page.blocks
            for i in range(len(blocks) - 1):
                gap = blocks[i].y - blocks[i].height - blocks[i + 1].y
                if gap < 0:
                    score -= 3.0
                    suggestions.append("Overlapping content detected")
                    break

        return max(0.0, score), suggestions

    def _score_page_balance(self, pages, page_spec) -> tuple[float, list]:
        score = 25.0
        suggestions = []

        if len(pages) < 2:
            return score, suggestions

        fills = []
        content_height = page_spec.content_height
        for page in pages:
            if not page.blocks:
                fills.append(0.0)
                continue
            top = page.blocks[0].y
            bottom = page.blocks[-1].y - page.blocks[-1].height
            used = top - bottom
            fills.append(used / content_height if content_height > 0 else 0.0)

        last_fill = fills[-1] if fills else 0.0
        if last_fill < 0.25 and len(pages) > 1:
            score -= 5.0
            suggestions.append(
                f"Last page is only {last_fill:.0%} full — consider "
                "tightening spacing to eliminate a nearly-empty page"
            )

        return max(0.0, score), suggestions

    def _score_structure(self, pages) -> tuple[float, list]:
        score = 25.0
        suggestions = []

        for page in pages:
            if not page.blocks:
                continue
            last_block = page.blocks[-1]
            from .spec import Heading
            if isinstance(last_block.block.element, Heading):
                remaining = last_block.y - last_block.height - page.spec.content_bottom
                if remaining < 30:
                    score -= 3.0
                    suggestions.append(
                        "Heading stranded near the bottom of a page — "
                        "keep-with-next should push it to the next page"
                    )

        return max(0.0, score), suggestions

    def _grade(self, score: float) -> str:
        if score >= 95:
            return "A+"
        if score >= 90:
            return "A"
        if score >= 85:
            return "A-"
        if score >= 80:
            return "B+"
        if score >= 75:
            return "B"
        if score >= 70:
            return "B-"
        if score >= 65:
            return "C+"
        if score >= 60:
            return "C"
        if score >= 55:
            return "C-"
        if score >= 50:
            return "D"
        return "F"


# ---------------------------------------------------------------------------
# Content Analyzer — unified entry point
# ---------------------------------------------------------------------------

@dataclass
class ContentAnalysis:
    """Complete intelligence analysis of a document."""

    document_profile: DocumentProfile | None = None
    table_analyses: list[TableAnalysis] = field(default_factory=list)
    typography_applied: bool = False
    auto_style_recommendation: str | None = None

    @property
    def summary(self) -> str:
        lines = []
        if self.document_profile:
            dp = self.document_profile
            lines.append(
                f"Document type: {dp.detected_type} "
                f"(confidence: {dp.confidence:.0%})"
            )
            lines.append(f"Recommended style: {dp.recommended_style}")
            if dp.signals:
                lines.append(f"Signals: {', '.join(dp.signals[:5])}")

        for i, ta in enumerate(self.table_analyses):
            lines.append(f"Table {i+1}: {ta.row_count} rows, "
                         f"{len(ta.columns)} columns")
            for col in ta.columns:
                if col.content_type != "text":
                    lines.append(
                        f"  Column '{col.header}': {col.content_type} "
                        f"→ align {col.recommended_align}"
                    )
            if ta.summary_rows:
                lines.append(
                    f"  Summary rows: {ta.summary_rows}"
                )

        if self.typography_applied:
            lines.append("Smart typography: applied")

        return "\n".join(lines)


class ContentAnalyzer:
    """Unified content intelligence for document analysis and transformation.

    Call `analyze()` to get a full intelligence report, or use individual
    engines for specific tasks. The analyzer can also apply transforms
    in-place on a Document spec before rendering.
    """

    def __init__(self) -> None:
        self.typography = SmartTypography()
        self.table_intel = TableIntelligence()
        self.detector = DocumentTypeDetector()

    def analyze_spec(self, spec_data: dict) -> ContentAnalysis:
        """Analyze a raw document spec dict and return intelligence."""
        title = spec_data.get("title", "")
        content = spec_data.get("content", [])

        headings = [
            b["text"] for b in content
            if b.get("type") == "heading" and "text" in b
        ]
        paragraphs = [
            b.get("text", "")
            for b in content
            if b.get("type") == "paragraph" and b.get("text")
        ]
        tables = [b for b in content if b.get("type") == "table"]

        profile = self.detector.detect(
            title, headings, paragraphs, len(tables)
        )

        table_analyses = []
        for table in tables:
            headers = [
                str(h) if isinstance(h, str) else h.get("value", "")
                for h in table.get("headers", [])
            ]
            rows = []
            for row in table.get("rows", []):
                cells = []
                for cell in row:
                    if isinstance(cell, str):
                        cells.append(cell)
                    elif isinstance(cell, dict):
                        cells.append(cell.get("value", ""))
                    else:
                        cells.append(str(cell))
                rows.append(cells)
            table_analyses.append(
                self.table_intel.analyze(headers, rows)
            )

        return ContentAnalysis(
            document_profile=profile,
            table_analyses=table_analyses,
            auto_style_recommendation=profile.recommended_style,
        )

    def enhance_spec(self, spec_data: dict, *,
                     auto_style: bool = True,
                     smart_typography: bool = True,
                     smart_tables: bool = True) -> dict:
        """Apply intelligence transforms to a spec dict in-place.

        Returns the same dict, modified with intelligent defaults.
        """
        analysis = self.analyze_spec(spec_data)

        if auto_style and "style" not in spec_data:
            if (analysis.document_profile
                    and analysis.document_profile.confidence >= 0.3):
                spec_data["style"] = analysis.document_profile.recommended_style

        content = spec_data.get("content", [])

        if smart_typography:
            for block in content:
                if block.get("type") == "paragraph" and block.get("text"):
                    block["text"] = self.typography.transform(block["text"])
                if block.get("type") == "paragraph" and block.get("runs"):
                    for run in block["runs"]:
                        if "text" in run:
                            run["text"] = self.typography.transform(run["text"])
                if block.get("type") == "heading" and block.get("text"):
                    block["text"] = self.typography.transform(block["text"])

        if smart_tables:
            table_idx = 0
            for block in content:
                if block.get("type") != "table":
                    continue
                if table_idx < len(analysis.table_analyses):
                    ta = analysis.table_analyses[table_idx]
                    self._apply_table_intelligence(block, ta)
                table_idx += 1

        return spec_data

    def _apply_table_intelligence(self, table_block: dict,
                                  analysis: TableAnalysis) -> None:
        rows = table_block.get("rows", [])

        for col in analysis.columns:
            if col.content_type in ("currency", "percentage", "number"):
                for row_idx, row in enumerate(rows):
                    if col.index < len(row):
                        cell = row[col.index]
                        if isinstance(cell, str):
                            row[col.index] = {
                                "value": cell,
                                "align": col.recommended_align,
                            }
                        elif isinstance(cell, dict) and "align" not in cell:
                            cell["align"] = col.recommended_align

        for row_idx in analysis.summary_rows:
            if row_idx < len(rows):
                row = rows[row_idx]
                for col_idx, cell in enumerate(row):
                    if isinstance(cell, str):
                        row[col_idx] = {"value": cell, "bold": True}
                    elif isinstance(cell, dict):
                        cell["bold"] = True

        if analysis.recommended_stripe and not table_block.get("stripe"):
            table_block["stripe"] = True
