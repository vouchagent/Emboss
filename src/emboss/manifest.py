"""Reproducibility manifest, and structural verification of a re-render.

Two concerns live here:

  build_manifest / manifest_json
      A deterministic, JSON-serializable summary of what it takes to
      reproduce a document's rendered bytes: the sha256 of its canonical
      spec, the Emboss version, every embedded font's sha256, any
      non-default render options, and an optional signed-lineage pointer
      to the document this one was derived from. ``Document.render(
      manifest=True)`` attaches this as an ``emboss-manifest.json`` /AF
      file (see ``spec.Document.reproducibility_manifest``).

  reproduce
      The other half of the loop: recover a Document from a PDF's
      embedded spec (or degrade to the structure tree), re-render it,
      and check the two PDFs agree structurally. Backs the ``emboss
      reproduce`` CLI subcommand.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "MANIFEST_FILENAME",
    "GeneratorInfo",
    "build_manifest",
    "manifest_json",
    "read_generator_info",
    "ReproductionReport",
    "reproduce",
]

MANIFEST_FILENAME = "emboss-manifest.json"

#: Document flags whose non-default value affects the rendered bytes
#: enough to matter for reproduction; each maps to its default value.
_RENDER_OPTION_DEFAULTS: dict[str, Any] = {
    "pdfa": False,
    "color_mode": "rgb",
    "tagged": True,
    "toc": False,
    "page_number_format": "arabic",
    "page_numbers": True,
    "front_matter_pages": 0,
}


@dataclass
class GeneratorInfo:
    """A verifiable record of what generated a document.

    ``prompt_sha256`` is a hash, never the raw prompt: the manifest records
    that a specific, reproducible input produced this output without
    disclosing potentially sensitive prompt content. Pass a raw prompt
    through ``hashlib.sha256(prompt.encode()).hexdigest()`` yourself (or use
    ``GeneratorInfo.from_prompt``) if you want it recorded; the manifest
    never stores prompt text itself. ``reviewed_by``/``reviewed_at`` are
    plain caller-supplied strings -- never populated from the wall clock --
    so recording a review is a deliberate, deterministic act, not automatic.
    """

    model: str | None = None
    provider: str | None = None
    prompt_sha256: str | None = None
    params: dict = field(default_factory=dict)
    reviewed_by: str | None = None
    reviewed_at: str | None = None

    @classmethod
    def from_prompt(
        cls,
        prompt: str,
        *,
        model: str | None = None,
        provider: str | None = None,
        params: dict | None = None,
        reviewed_by: str | None = None,
        reviewed_at: str | None = None,
    ) -> "GeneratorInfo":
        """Build a GeneratorInfo, hashing *prompt* rather than storing it."""
        return cls(
            model=model,
            provider=provider,
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            params=dict(params or {}),
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
        )

    def to_dict(self) -> dict[str, Any]:
        """A dict with only the fields actually set, for a compact manifest."""
        out: dict[str, Any] = {}
        if self.model:
            out["model"] = self.model
        if self.provider:
            out["provider"] = self.provider
        if self.prompt_sha256:
            out["prompt_sha256"] = self.prompt_sha256
        if self.params:
            out["params"] = dict(self.params)
        if self.reviewed_by:
            out["reviewed_by"] = self.reviewed_by
        if self.reviewed_at:
            out["reviewed_at"] = self.reviewed_at
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "GeneratorInfo":
        return cls(
            model=data.get("model"),
            provider=data.get("provider"),
            prompt_sha256=data.get("prompt_sha256"),
            params=dict(data.get("params") or {}),
            reviewed_by=data.get("reviewed_by"),
            reviewed_at=data.get("reviewed_at"),
        )


def _package_version() -> str:
    """Return the running Emboss version (see ``emboss.__version__``)."""
    from . import __version__

    return __version__


def _render_options(document, *, embed_spec: bool) -> dict[str, Any]:
    """Non-default Document render flags, plus ``embed_spec`` if set."""
    options: dict[str, Any] = {}
    for name, default in _RENDER_OPTION_DEFAULTS.items():
        value = getattr(document, name, default)
        if value != default:
            options[name] = value
    if embed_spec:
        options["embed_spec"] = True
    return options


def _font_entries(document) -> list[dict[str, str]]:
    """List every embedded/bundled font this document's fonts resolved.

    Reads ``document.fonts``' resolution cache, so it only reflects
    fonts actually used if a layout pass has already run (``render``,
    ``save``, ``layout_map``, or ``reproducibility_manifest`` all do
    this before building the manifest).
    """
    registry = getattr(document, "fonts", None)
    if registry is None:
        return []
    seen: dict[str, str] = {}
    for metrics in getattr(registry, "_cache", {}).values():
        if not metrics.is_embedded or metrics.font_path is None:
            continue
        seen.setdefault(str(metrics.font_path), metrics.name)
    return [
        {
            "family": seen[path],
            "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        }
        for path in sorted(seen)
    ]


def build_manifest(
    document,
    *,
    embed_spec: bool = False,
    predecessor_sha256: str | None = None,
    predecessor_manifest_sha256: str | None = None,
    generator: "GeneratorInfo | None" = None,
) -> dict[str, Any]:
    """Build *document*'s reproducibility manifest as a plain dict.

    ``{"spec_sha256": ..., "emboss_version": ..., "fonts": [...],
    "render_options": {...}}``, plus a ``"lineage"`` key when a
    predecessor is known (``predecessor_sha256`` falls back to
    ``document.predecessor`` when not given explicitly), and a
    ``"generator"`` key when ``generator`` is given (falls back to
    ``document.generator`` when not given explicitly) -- a verifiable
    record of what generated the document: model, provider, a hash of
    the prompt, and an optional reviewer. Deterministic: given the same
    document and arguments, always produces the same dict.
    """
    from .recovery import document_to_spec_dict, spec_dict_to_json

    spec_bytes = spec_dict_to_json(document_to_spec_dict(document))
    manifest: dict[str, Any] = {
        "spec_sha256": hashlib.sha256(spec_bytes).hexdigest(),
        "emboss_version": _package_version(),
        "fonts": _font_entries(document),
        "render_options": _render_options(document, embed_spec=embed_spec),
    }

    predecessor = predecessor_sha256
    if predecessor is None:
        predecessor = getattr(document, "predecessor", None)
    lineage: dict[str, str] = {}
    if predecessor:
        lineage["predecessor_sha256"] = predecessor
    if predecessor_manifest_sha256:
        lineage["predecessor_manifest_sha256"] = predecessor_manifest_sha256
    if lineage:
        manifest["lineage"] = lineage

    generator_info = generator
    if generator_info is None:
        generator_info = getattr(document, "generator", None)
    if generator_info is not None:
        generator_dict = generator_info.to_dict()
        if generator_dict:
            manifest["generator"] = generator_dict
    return manifest


def manifest_json(manifest: dict) -> bytes:
    """Encode a manifest as deterministic, sorted-key UTF-8 JSON bytes."""
    return json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2).encode(
        "utf-8"
    )


# -- reproduce -------------------------------------------------------------


@dataclass
class ReproductionReport:
    """Result of comparing a re-render against the PDF it was recovered from.

    Byte-for-byte equality isn't the bar: re-attaching a manifest/spec to
    the reproduction would itself change its bytes relative to the
    original across the attachment boundary. Instead this checks
    structural equivalence -- same page count, same visible text per
    page (extracted from the content streams by MCID, same method for
    both PDFs).
    """

    ok: bool
    original_pages: int
    reproduced_pages: int
    page_mismatches: list = field(default_factory=list)
    diffs: list = field(default_factory=list)

    def __str__(self) -> str:
        if self.ok:
            return (
                f"PASS: {self.original_pages} page"
                f"{'s' if self.original_pages != 1 else ''}, "
                "text matches page-for-page (structural comparison; "
                "manifest/spec attachment boundary excluded)"
            )
        lines = ["FAIL: reproduction diverges from the original"]
        if self.original_pages != self.reproduced_pages:
            lines.append(
                f"  page count: original={self.original_pages} "
                f"reproduced={self.reproduced_pages}"
            )
        lines.extend(f"  {diff}" for diff in self.diffs)
        return "\n".join(lines)


def _read_bytes(source) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    return Path(source).read_bytes()


def _read_manifest_attachment(pdf_bytes: bytes) -> dict | None:
    """Read the ``emboss-manifest.json`` /AF attachment, or None if absent."""
    try:
        import pikepdf
    except ImportError:
        return None
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        try:
            filespec = pdf.attachments[MANIFEST_FILENAME]
        except KeyError:
            return None
        raw = filespec.get_file().read_bytes()
    return json.loads(raw.decode("utf-8"))


def read_generator_info(source: bytes | str | Path) -> "GeneratorInfo | None":
    """Read the generator info from a PDF's embedded manifest, or None.

    Returns None (rather than raising) when pikepdf is unavailable, no
    manifest attachment is present, or the manifest carries no generator
    record -- so a caller can always ask "who generated this?" and get an
    honest absence rather than an exception.
    """
    pdf_bytes = _read_bytes(source)
    manifest = _read_manifest_attachment(pdf_bytes)
    if manifest is None:
        return None
    generator_dict = manifest.get("generator")
    if not generator_dict:
        return None
    return GeneratorInfo.from_dict(generator_dict)


def _apply_render_options(document, options: dict[str, Any]) -> None:
    """Set any render flags a manifest's ``render_options`` recorded."""
    for name in _RENDER_OPTION_DEFAULTS:
        if name in options:
            setattr(document, name, options[name])


def _extract_page_texts(pdf_bytes: bytes) -> list[str]:
    """Return each page's visible text, extracted from content streams by MCID."""
    import pikepdf

    from .recovery import _extract_text_by_mcid, _font_decoders

    texts: list[str] = []
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            contents = page.get("/Contents")
            if contents is None:
                texts.append("")
                continue
            content = bytes(contents.read_bytes())
            fonts = _font_decoders(page)
            mcid_text = _extract_text_by_mcid(content, fonts)
            texts.append(" ".join(mcid_text[mcid] for mcid in sorted(mcid_text)))
    return texts


def _diff_summary(page_index: int, original: str | None, reproduced: str | None) -> str:
    if original is None:
        return f"page {page_index}: present only in the reproduction"
    if reproduced is None:
        return f"page {page_index}: present only in the original"
    limit = min(len(original), len(reproduced))
    offset = next((i for i in range(limit) if original[i] != reproduced[i]), limit)
    start = max(0, offset - 20)
    return (
        f"page {page_index}: text differs at offset {offset}: "
        f"original={original[start : offset + 20]!r} "
        f"reproduced={reproduced[start : offset + 20]!r}"
    )


def _compare_structurally(original: bytes, reproduced: bytes) -> ReproductionReport:
    original_pages = _extract_page_texts(original)
    reproduced_pages = _extract_page_texts(reproduced)

    mismatches: list = []
    diffs: list = []
    for i in range(max(len(original_pages), len(reproduced_pages))):
        orig = original_pages[i] if i < len(original_pages) else None
        repro = reproduced_pages[i] if i < len(reproduced_pages) else None
        if orig != repro:
            mismatches.append(i)
            diffs.append(_diff_summary(i, orig, repro))

    ok = not mismatches and len(original_pages) == len(reproduced_pages)
    return ReproductionReport(
        ok=ok,
        original_pages=len(original_pages),
        reproduced_pages=len(reproduced_pages),
        page_mismatches=mismatches,
        diffs=diffs,
    )


def reproduce(source: bytes | str | Path) -> ReproductionReport:
    """Recover a Document from *source*, re-render it, and compare structurally.

    Recovers the embedded EmbossSpec (or degrades to the PDF/UA structure
    tree) via ``Document.from_pdf``, applies the reproducibility
    manifest's ``render_options`` when a manifest attachment is present,
    then re-renders the recovered Document plainly -- without
    ``embed_spec`` or ``manifest`` of its own, since attaching either
    would change the reproduction's bytes relative to the original in a
    way that has nothing to do with whether the *content* reproduced
    correctly. The comparison is therefore structural rather than
    byte-exact: page count, and per-page visible text extracted from the
    content streams by MCID identically for both PDFs. Requires
    ``pip install emboss-pdf[verify]`` (pikepdf).
    """
    from .spec import Document

    original_bytes = _read_bytes(source)
    document = Document.from_pdf(original_bytes)

    manifest = _read_manifest_attachment(original_bytes)
    if manifest is not None:
        _apply_render_options(document, manifest.get("render_options", {}))

    reproduced_bytes = document.render()
    return _compare_structurally(original_bytes, reproduced_bytes)
