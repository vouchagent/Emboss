"""Deterministic chart fact extraction, caption verification, and findings.

``compute_facts`` derives a fact set (min/max/first/last/mean, totals,
direction, shares) from chart data; ``verify_caption`` flags caption
numbers that no fact supports within a 1% relative tolerance; and
``fact_sentence`` emits a one-line finding built only from computed
facts, so generated captions are verifiable rather than hallucinated.
"""

from __future__ import annotations

import re

from .charts import direction_of, format_value

__all__ = ["compute_facts", "fact_sentence", "verify_caption"]

_EXEMPT_MAX = 12
_SUFFIX_SCALE = {"K": 1_000.0, "k": 1_000.0, "M": 1_000_000.0, "m": 1_000_000.0}

_NUMBER_RE = re.compile(
    r"(?P<sign>[-+])?\$?(?P<int>\d{1,3}(?:,\d{3})+|\d+)"
    r"(?P<frac>\.\d+)?(?:\s?(?P<suffix>[KkMm%])(?![A-Za-z]))?"
)


def _series_of(data) -> list[tuple[str, list[float]]]:
    """Normalize chart data to (name, values) pairs with stable names."""
    series = getattr(data, "series", None)
    if series:
        out = []
        for i, s in enumerate(series):
            name = getattr(s, "label", "") or f"series {i + 1}"
            out.append((name, [float(v) for v in getattr(s, "values", [])]))
        return out
    values = [float(v) for v in (getattr(data, "values", None) or [])]
    return [("series 1", values)] if values else []


def compute_facts(chart) -> dict:
    """Compute a deterministic fact set dict for a chart or its data."""
    data = getattr(chart, "data", chart)
    kind = getattr(chart, "chart_type", None) or getattr(data, "chart_type", "bar")
    labels = [str(label) for label in (getattr(data, "labels", None) or [])]
    series = _series_of(data)

    def cat(i: int) -> str:
        return labels[i] if i < len(labels) else str(i + 1)

    facts: dict = {
        "chart_type": kind,
        "series_count": len(series),
        "category_count": len(labels),
        "categories": labels,
        "series": {},
    }

    grand_total = 0.0
    for name, values in series:
        if not values:
            continue
        key = name
        if key in facts["series"]:
            key = f"{name} ({len(facts['series']) + 1})"
        first, last = values[0], values[-1]
        entry: dict = {
            "values": [round(v, 4) for v in values],
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "first": round(first, 4),
            "last": round(last, 4),
            "mean": round(sum(values) / len(values), 4),
            "total": round(sum(values), 4),
            "min_category": cat(values.index(min(values))),
            "max_category": cat(values.index(max(values))),
            "direction": direction_of(first, last),
        }
        if first != 0:
            entry["pct_change"] = round((last - first) / abs(first) * 100.0, 4)
        facts["series"][key] = entry
        grand_total += sum(values)
    facts["total"] = round(grand_total, 4)
    if facts["series"]:
        first_key = next(iter(facts["series"]))
        facts["direction"] = facts["series"][first_key]["direction"]

    count = max([len(values) for _name, values in series] + [len(labels)], default=0)
    totals = [
        sum(values[i] for _name, values in series if i < len(values))
        for i in range(count)
    ]
    if totals and any(values for _name, values in series):
        hi = totals.index(max(totals))
        lo = totals.index(min(totals))
        facts["largest_category"] = cat(hi)
        facts["smallest_category"] = cat(lo)
        facts["largest_category_total"] = round(totals[hi], 4)
        facts["smallest_category_total"] = round(totals[lo], 4)

    if kind == "pie" and series and series[0][1]:
        values = series[0][1]
        total = sum(abs(v) for v in values)
        if total:
            facts["shares"] = {
                cat(i): round(abs(v) / total * 100.0, 4) for i, v in enumerate(values)
            }
    return facts


def _numeric_facts(node) -> list[float]:
    """Flatten every numeric fact (and magnitudes of negatives) to a list."""
    out: list[float] = []
    if isinstance(node, bool):
        return out
    if isinstance(node, (int, float)):
        out.append(float(node))
        if node < 0:
            out.append(abs(float(node)))
        return out
    if isinstance(node, dict):
        for value in node.values():
            out.extend(_numeric_facts(value))
    elif isinstance(node, (list, tuple)):
        for value in node:
            out.extend(_numeric_facts(value))
    return out


def verify_caption(caption: str, facts: dict) -> list[str]:
    """Return violations for caption numbers unsupported by the fact set."""
    numbers = _numeric_facts(facts)
    violations: list[str] = []
    for match in _NUMBER_RE.finditer(caption):
        raw = match.group(0).strip()
        sign, int_part, frac, suffix = match.groups()
        value = float(int_part.replace(",", "") + (frac or ""))
        if sign == "-":
            value = -value
        plain_int = frac is None and suffix is None
        if plain_int and abs(value) <= _EXEMPT_MAX:
            continue
        scale = _SUFFIX_SCALE.get(suffix or "", 1.0)
        value *= scale
        decimals = len(frac) - 1 if frac else 0
        quantum = 0.5 * scale * 10.0 ** (-decimals)
        supported = any(
            abs(value - fact) <= max(0.01 * max(abs(value), abs(fact)), quantum, 1e-9)
            for fact in numbers
        )
        if not supported:
            violations.append(
                f"caption number {raw!r} (= {value:g}) is not supported by "
                "the chart data (no computed fact within 1%)"
            )
    return violations


def fact_sentence(chart) -> str:
    """Return a one-line finding phrased only from computed chart facts."""
    facts = compute_facts(chart)
    if not facts["series"]:
        return ""
    kind = facts["chart_type"]
    data = getattr(chart, "data", chart)
    title = getattr(data, "title", None) or getattr(chart, "title", None)
    categories = facts["categories"]

    if kind == "pie" and "shares" in facts:
        top = facts["largest_category"]
        share = facts["shares"].get(top, 0.0)
        return (
            f"{top} is the largest share at {share:.1f}% of the total "
            f"across {facts['category_count']} categories."
        )

    if kind == "bar":
        return (
            f"{facts['largest_category']} leads at "
            f"{format_value(facts['largest_category_total'])}, while "
            f"{facts['smallest_category']} trails at "
            f"{format_value(facts['smallest_category_total'])}."
        )

    first_key = next(iter(facts["series"]))
    s = facts["series"][first_key]
    name = (title or "The series") if first_key == "series 1" else first_key
    span = len(s["values"])
    first_cat = categories[0] if categories else "1"
    last_cat = categories[span - 1] if span - 1 < len(categories) else str(span)
    if s["direction"] == "flat":
        return (
            f"{name} held flat near {format_value(s['mean'])} "
            f"from {first_cat} to {last_cat}."
        )
    verb = "rose" if s["direction"] == "rising" else "fell"
    peak = f", peaking at {format_value(s['max'])} in {s['max_category']}"
    if "pct_change" in s:
        return (
            f"{name} {verb} {abs(s['pct_change']):.1f}% "
            f"from {first_cat} to {last_cat}{peak}."
        )
    return (
        f"{name} {verb} from {format_value(s['first'])} "
        f"to {format_value(s['last'])}{peak}."
    )
