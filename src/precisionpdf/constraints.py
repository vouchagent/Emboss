"""Deterministic validation of a document specification before rendering.

Problems are caught against the specification rather than discovered
halfway through writing bytes. Some are repairable (a table whose columns
sum to more than the page width can be rescaled); others are genuine
authoring errors and are reported.

Validation never mutates the caller's document. Auto-fixes are applied to
a copy, so the same input always validates the same way.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Literal

from .spec import (
    BulletList, Callout, Chart, Document, Footnote, Heading, HorizontalRule,
    Image, PageBreak, Paragraph, Table,
)

__all__ = ["Issue", "ValidationResult", "ConstraintValidator", "ValidationError"]

Severity = Literal["error", "warning", "fixed"]
Category = Literal["structural", "mathematical", "semantic", "accessibility"]

MIN_FONT_SIZE = 4.0
MAX_FONT_SIZE = 96.0


class ValidationError(ValueError):
    """Raised when a document cannot be rendered as specified."""

    def __init__(self, issues) -> None:
        self.issues = list(issues)
        detail = "\n".join(f"  - {issue}" for issue in self.issues)
        super().__init__(
            f"document failed validation with {len(self.issues)} error(s):\n"
            f"{detail}"
        )


@dataclass(frozen=True)
class Issue:
    """One validation finding."""

    severity: Severity
    category: Category
    message: str
    location: str = ""

    def __str__(self) -> str:
        where = f" [{self.location}]" if self.location else ""
        return f"{self.severity}/{self.category}{where}: {self.message}"


@dataclass
class ValidationResult:
    document: Document
    issues: list = field(default_factory=list)

    @property
    def errors(self) -> list:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def fixes(self) -> list:
        return [i for i in self.issues if i.severity == "fixed"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_if_failed(self) -> "ValidationResult":
        if self.errors:
            raise ValidationError(self.errors)
        return self


class ConstraintValidator:
    """Checks and repairs a document specification."""

    def __init__(self, fonts=None, strict: bool = False) -> None:
        self.fonts = fonts
        self.strict = strict

    def validate(self, document: Document) -> ValidationResult:
        working = copy.deepcopy(document)
        issues: list = []

        self._check_page(working, issues)
        self._check_metadata(working, issues)
        self._check_content(working, issues)
        self._check_headings(working, issues)
        self._check_tables(working, issues)

        if self.strict:
            issues = [
                Issue("error", i.category, i.message, i.location)
                if i.severity == "warning" else i
                for i in issues
            ]
        return ValidationResult(document=working, issues=issues)

    # -- individual checks --

    def _check_page(self, document: Document, issues: list) -> None:
        page = document.page
        if page.width <= 0 or page.height <= 0:
            issues.append(Issue(
                "error", "structural",
                f"page dimensions must be positive, got "
                f"{page.width}x{page.height}",
                "page",
            ))
            return

        if page.content_width <= 36:
            issues.append(Issue(
                "error", "structural",
                f"margins leave only {page.content_width:.1f}pt of usable "
                "width; reduce margin_left/margin_right",
                "page",
            ))
        if page.content_height <= 36:
            issues.append(Issue(
                "error", "structural",
                f"margins leave only {page.content_height:.1f}pt of usable "
                "height; reduce margin_top/margin_bottom",
                "page",
            ))

    def _check_metadata(self, document: Document, issues: list) -> None:
        if document.tagged and not document.title.strip():
            issues.append(Issue(
                "error", "accessibility",
                "PDF/UA requires a document title; set Document(title=...) "
                "or disable tagging with tagged=False",
                "metadata",
            ))
        if document.tagged and not document.language.strip():
            issues.append(Issue(
                "error", "accessibility",
                "PDF/UA requires a language; set Document(language='en-US')",
                "metadata",
            ))

    def _check_content(self, document: Document, issues: list) -> None:
        if not document.content:
            issues.append(Issue(
                "error", "structural",
                "document has no content", "content",
            ))
            return

        known = (Heading, Paragraph, BulletList, Table, Image, Chart,
                 Footnote, Callout, PageBreak, HorizontalRule)
        for index, element in enumerate(document.content):
            if not isinstance(element, known):
                issues.append(Issue(
                    "error", "structural",
                    f"unsupported element type {type(element).__name__}",
                    f"content[{index}]",
                ))
                continue

            style = getattr(element, "style", None)
            if style is not None and style.font_size is not None:
                size = style.font_size
                if not MIN_FONT_SIZE <= size <= MAX_FONT_SIZE:
                    clamped = min(max(size, MIN_FONT_SIZE), MAX_FONT_SIZE)
                    element.style = style.with_(font_size=clamped)
                    issues.append(Issue(
                        "fixed", "mathematical",
                        f"font size {size}pt out of range; clamped to "
                        f"{clamped}pt",
                        f"content[{index}]",
                    ))

            if (self.fonts is not None and style is not None
                    and style.font_family
                    and not self.fonts.is_available(style.font_family)):
                issues.append(Issue(
                    "fixed", "structural",
                    f"font {style.font_family!r} is not registered; "
                    "falling back to Helvetica",
                    f"content[{index}]",
                ))
                element.style = style.with_(font_family="Helvetica")

    def _check_headings(self, document: Document, issues: list) -> None:
        """Heading levels must not skip: H1 then H3 breaks navigation."""
        previous = 0
        for index, element in enumerate(document.content):
            if not isinstance(element, Heading):
                continue
            if previous and element.level > previous + 1:
                issues.append(Issue(
                    "warning", "semantic",
                    f"heading level jumps from H{previous} to "
                    f"H{element.level}; screen reader navigation expects "
                    "no gaps",
                    f"content[{index}]",
                ))
            if not element.text.strip():
                issues.append(Issue(
                    "error", "accessibility",
                    "heading has no text", f"content[{index}]",
                ))
            previous = element.level

    def _check_tables(self, document: Document, issues: list) -> None:
        usable = document.page.content_width

        for index, element in enumerate(document.content):
            if not isinstance(element, Table):
                continue

            if not element.headers:
                issues.append(Issue(
                    "warning", "accessibility",
                    "table has no header row; assistive technology cannot "
                    "announce column context",
                    f"content[{index}]",
                ))

            if not element.rows:
                issues.append(Issue(
                    "warning", "structural",
                    "table has no data rows", f"content[{index}]",
                ))
                continue

            columns = element.column_count
            for row_index, row in enumerate(element.rows):
                if len(row) != columns:
                    issues.append(Issue(
                        "warning", "structural",
                        f"row {row_index} has {len(row)} cells but the table "
                        f"has {columns} columns; missing cells render empty",
                        f"content[{index}]",
                    ))

            if element.column_widths:
                if len(element.column_widths) != columns:
                    issues.append(Issue(
                        "error", "mathematical",
                        f"column_widths has {len(element.column_widths)} "
                        f"entries but the table has {columns} columns",
                        f"content[{index}]",
                    ))
                    continue
                total = sum(element.column_widths)
                if total > usable * 1.001:
                    scale = usable / total
                    element.column_widths = [
                        w * scale for w in element.column_widths
                    ]
                    issues.append(Issue(
                        "fixed", "mathematical",
                        f"column widths summed to {total:.1f}pt, exceeding "
                        f"the {usable:.1f}pt content width; rescaled "
                        "proportionally",
                        f"content[{index}]",
                    ))
