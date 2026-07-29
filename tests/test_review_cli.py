"""End-to-end tests for the `emboss review` and `emboss apply` CLI commands."""

import io
import json

import pytest

from emboss import Document
from emboss.__main__ import main
from emboss.recovery import document_to_spec_dict, spec_dict_to_json

pikepdf = pytest.importorskip("pikepdf")


def _scenario(tmp_path):
    doc = Document(title="Report")
    doc.paragraph("The exposure exceeds four million dollars this quarter.", id="p1")
    (tmp_path / "spec.json").write_bytes(spec_dict_to_json(document_to_spec_dict(doc)))

    pdf = doc.render(embed_spec=True)
    idx = doc.text_index()
    spans = [s for s in idx._index["p1"] if s["text"] in ("four", "million")]
    x0 = min(s["x0"] for s in spans)
    x1 = max(s["x1"] for s in spans)
    y0 = min(s["y0"] for s in spans)
    y1 = max(s["y1"] for s in spans)
    with pikepdf.open(io.BytesIO(pdf)) as p:
        quad = [x0, y1, x1, y1, x0, y0, x1, y0]
        annot = pikepdf.Dictionary(
            Type=pikepdf.Name.Annot,
            Subtype=pikepdf.Name.StrikeOut,
            Rect=[x0, y0, x1, y1],
            QuadPoints=quad,
            T="Legal",
            Contents="use the netted figure",
        )
        p.pages[0].Annots = pikepdf.Array([p.make_indirect(annot)])
        out = io.BytesIO()
        p.save(out)
        (tmp_path / "marked.pdf").write_bytes(out.getvalue())
    return tmp_path


def test_review_writes_comments_and_html(tmp_path):
    _scenario(tmp_path)
    rc = main(
        [
            "review",
            str(tmp_path / "marked.pdf"),
            "-o",
            str(tmp_path / "comments.json"),
            "--html",
            str(tmp_path / "review.html"),
            "-q",
        ]
    )
    assert rc == 0
    comments = json.loads((tmp_path / "comments.json").read_text())
    assert comments[0]["node_id"] == "p1"
    assert comments[0]["anchor_text"] == "four million"
    assert (tmp_path / "review.html").read_text().startswith("<!doctype html>")


def test_review_exit_code_flags_unresolved(tmp_path):
    _scenario(tmp_path)
    # Add a stray, unanchored annotation to force a non-zero exit.
    with pikepdf.open(tmp_path / "marked.pdf") as p:
        annot = pikepdf.Dictionary(
            Type=pikepdf.Name.Annot,
            Subtype=pikepdf.Name.Highlight,
            Rect=[430, 60, 520, 80],
            QuadPoints=[430, 80, 520, 80, 430, 60, 520, 60],
            T="R",
            Contents="stray",
        )
        existing = list(p.pages[0].Annots)
        existing.append(p.make_indirect(annot))
        p.pages[0].Annots = pikepdf.Array(existing)
        p.save(tmp_path / "marked2.pdf")
    rc = main(["review", str(tmp_path / "marked2.pdf"), "-q"])
    assert rc == 2  # unresolved comments present


def test_apply_propose_then_edit(tmp_path):
    _scenario(tmp_path)
    main(
        [
            "review",
            str(tmp_path / "marked.pdf"),
            "-o",
            str(tmp_path / "comments.json"),
            "-q",
        ]
    )
    # Propose only: no output written.
    rc = main(
        [
            "apply",
            str(tmp_path / "comments.json"),
            "--spec",
            str(tmp_path / "spec.json"),
            "-q",
        ]
    )
    assert rc == 0

    # Apply a concrete edit.
    (tmp_path / "edits.json").write_text(json.dumps({"c-01": "2.8 million"}))
    rc = main(
        [
            "apply",
            str(tmp_path / "comments.json"),
            "--spec",
            str(tmp_path / "spec.json"),
            "--edits",
            str(tmp_path / "edits.json"),
            "-o",
            str(tmp_path / "out.pdf"),
            "--redline",
            str(tmp_path / "rl.pdf"),
            "-q",
        ]
    )
    assert rc == 0
    patched = Document.from_pdf(tmp_path / "out.pdf")
    assert any(
        getattr(b, "content", "")
        == "The exposure exceeds 2.8 million dollars this quarter."
        for b in patched.content
    )
    assert (tmp_path / "rl.pdf").read_bytes().startswith(b"%PDF")
