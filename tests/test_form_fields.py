"""Tests for fillable AcroForm fields: text, checkbox, and dropdown."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import (  # noqa: E402
    CheckboxField,
    Document,
    DropdownField,
    TextField,
    ValidationError,
)
from emboss.generate import _manual_parse  # noqa: E402
from emboss.pdf.verify import verify_pdf  # noqa: E402
from emboss.recovery import document_to_spec_dict, spec_dict_to_json  # noqa: E402

pikepdf = pytest.importorskip("pikepdf")


def _sample_document(**kw) -> Document:
    doc = Document(title="Client Intake", **kw)
    doc.heading("Client Intake Form", level=1)
    doc.paragraph("Please complete the fields below.")
    doc.text_field("full_name", label="Full Name", required=True)
    doc.checkbox_field("agree_terms", label="I agree to the terms", checked=True)
    doc.dropdown_field(
        "country",
        ["United States", "Canada", "Mexico"],
        label="Country",
        default="Canada",
    )
    return doc


def _acroform_fields(data: bytes):
    """Open *data* and return (pdf, acroform, fields); keep `pdf` alive.

    pikepdf.Object handles are only valid while their owning Pdf is
    alive, so callers must hold onto the returned `pdf` for as long as
    they read from `acroform`/`fields`.
    """
    pdf = pikepdf.open(io.BytesIO(data))
    acroform = pdf.Root.get("/AcroForm")
    assert acroform is not None, "no /AcroForm in catalog"
    return pdf, acroform, list(acroform.Fields)


def _field_by_name(fields, name: str):
    for f in fields:
        if str(f.get("/T", "")) == name:
            return f
    raise AssertionError(
        f"no field named {name!r} in {[str(f.get('/T')) for f in fields]}"
    )


# ---------------------------------------------------------------------------
# Construction: fluent + dict/spec input
# ---------------------------------------------------------------------------


def test_fluent_api_builds_all_three_types():
    doc = Document(title="Form")
    doc.text_field("name", label="Name")
    doc.checkbox_field("agree", label="Agree")
    doc.dropdown_field("choice", ["a", "b"], label="Choice")
    assert isinstance(doc.content[0], TextField)
    assert isinstance(doc.content[1], CheckboxField)
    assert isinstance(doc.content[2], DropdownField)
    assert doc.content[0].name == "name"
    assert doc.content[1].name == "agree"
    assert doc.content[2].name == "choice"


def test_dict_and_dataclass_input_both_render():
    doc = Document(title="Form")
    doc.add(TextField(name="a", label="A"))
    doc.add(CheckboxField(name="b", label="B", checked=True))
    doc.add(DropdownField(name="c", options=["x", "y"], label="C"))
    assert doc.render().startswith(b"%PDF-")


def test_each_field_type_renders_to_pdf_alone():
    for element in (
        TextField(name="t1", label="T"),
        CheckboxField(name="c1", label="C"),
        DropdownField(name="d1", options=["1", "2"], label="D"),
    ):
        doc = Document(title="Solo")
        doc.add(element)
        data = doc.render()
        assert data.startswith(b"%PDF-")


# ---------------------------------------------------------------------------
# pikepdf extraction: /AcroForm/Fields structure
# ---------------------------------------------------------------------------


def test_text_field_extracted_with_correct_ft_t_v():
    doc = _sample_document()
    doc.text_field("bio", label="Short Bio", default="Hello there", multiline=True)
    data = doc.render()
    _pdf, _acroform, fields = _acroform_fields(data)

    field = _field_by_name(fields, "full_name")
    assert str(field["/FT"]) == "/Tx"
    assert str(field["/T"]) == "full_name"

    bio = _field_by_name(fields, "bio")
    assert str(bio["/FT"]) == "/Tx"
    assert str(bio["/V"]) == "Hello there"
    assert int(bio["/Ff"]) & 0x1000  # multiline bit


def test_checkbox_field_extracted_with_correct_ft_and_as():
    doc = _sample_document()
    data = doc.render()
    _pdf, _acroform, fields = _acroform_fields(data)

    field = _field_by_name(fields, "agree_terms")
    assert str(field["/FT"]) == "/Btn"
    assert str(field["/AS"]) == "/Yes"
    assert str(field["/V"]) == "/Yes"
    assert "/AP" in field
    assert "/Yes" in field["/AP"]["/N"]
    assert "/Off" in field["/AP"]["/N"]


def test_unchecked_checkbox_reads_off():
    doc = Document(title="Form")
    doc.checkbox_field("opt_in", label="Opt in", checked=False)
    data = doc.render()
    _pdf, _acroform, fields = _acroform_fields(data)
    field = _field_by_name(fields, "opt_in")
    assert str(field["/AS"]) == "/Off"
    assert str(field["/V"]) == "/Off"


def test_dropdown_field_extracted_with_correct_ft_and_opt():
    doc = _sample_document()
    data = doc.render()
    _pdf, _acroform, fields = _acroform_fields(data)

    field = _field_by_name(fields, "country")
    assert str(field["/FT"]) == "/Ch"
    assert int(field["/Ff"]) & 0x20000  # combo bit
    options = [str(o) for o in field["/Opt"]]
    assert options == ["United States", "Canada", "Mexico"]
    assert str(field["/V"]) == "Canada"


def test_all_three_fields_present_in_one_acroform():
    doc = _sample_document()
    data = doc.render()
    _pdf, _acroform, fields = _acroform_fields(data)
    names = {str(f.get("/T", "")) for f in fields}
    assert {"full_name", "agree_terms", "country"} <= names


def test_widgets_appear_on_page_annots():
    doc = _sample_document()
    data = doc.render()
    pdf = pikepdf.open(io.BytesIO(data))
    annots = list(pdf.pages[0].get("/Annots", []))
    widget_names = {
        str(a.get("/T", "")) for a in annots if str(a.get("/Subtype", "")) == "/Widget"
    }
    assert {"full_name", "agree_terms", "country"} <= widget_names


def test_signature_and_form_fields_share_one_acroform():
    from emboss.signing import SignatureField

    doc = _sample_document()
    doc.signatures = [SignatureField(page_index=0, x=72, y=72, field_name="Signature1")]
    data = doc.render()
    _pdf, _acroform, fields = _acroform_fields(data)
    names = {str(f.get("/T", "")) for f in fields}
    assert "Signature1" in names
    assert "full_name" in names


# ---------------------------------------------------------------------------
# Validation failure paths
# ---------------------------------------------------------------------------


def test_duplicate_field_names_raise_value_error():
    doc = Document(title="Form")
    doc.text_field("email", label="Email")
    doc.checkbox_field("email", label="Duplicate name checkbox")
    with pytest.raises(ValueError, match="duplicate form field name"):
        doc.render()


def test_duplicate_names_across_all_three_types_raise():
    doc = Document(title="Form")
    doc.text_field("x", label="Text")
    doc.dropdown_field("x", ["a", "b"], label="Dropdown")
    with pytest.raises(ValidationError):
        doc.render()


def test_empty_dropdown_options_raise_value_error():
    doc = Document(title="Form")
    doc.dropdown_field("choice", [], label="Choice")
    with pytest.raises(ValueError, match="no options"):
        doc.render()


# ---------------------------------------------------------------------------
# PDF/UA structure tagging
# ---------------------------------------------------------------------------


def test_document_with_form_fields_stays_pdf_ua_valid():
    doc = _sample_document()
    data = doc.render()
    report = verify_pdf(data)
    assert report.ok, report.problems
    assert report.has_struct_tree
    assert report.has_lang


def test_form_fields_do_not_regress_baseline_tagging():
    baseline = Document(title="Baseline")
    baseline.heading("Section", level=1)
    baseline.paragraph("Body text.")
    baseline_report = verify_pdf(baseline.render())

    forms = _sample_document()
    forms_report = verify_pdf(forms.render())

    assert baseline_report.ok
    assert forms_report.ok
    assert forms_report.has_struct_tree == baseline_report.has_struct_tree
    assert forms_report.has_lang == baseline_report.has_lang


def test_form_struct_elements_carry_objr_and_role_map():
    doc = _sample_document()
    data = doc.render()
    assert b"/S /Form" in data
    assert b"/OBJR" in data
    # RoleMap maps the custom "Form" tag onto itself (a standard structure type).
    assert b"/Form /Form" in data or b"/Form/Form" in data


# ---------------------------------------------------------------------------
# JSON spec round-trip
# ---------------------------------------------------------------------------


def test_json_round_trip_preserves_all_fields_and_explicit_id():
    doc = Document(title="Form")
    doc.add(
        TextField(
            name="email",
            label="Email Address",
            default="you@example.com",
            multiline=False,
            required=True,
            id="field-email",
        )
    )
    doc.add(
        CheckboxField(
            name="newsletter",
            label="Subscribe to newsletter",
            checked=True,
            id="field-newsletter",
        )
    )
    doc.add(
        DropdownField(
            name="plan",
            options=["Basic", "Pro", "Enterprise"],
            label="Plan",
            default="Pro",
            id="field-plan",
        )
    )

    spec = document_to_spec_dict(doc)
    restored = Document.from_json(spec_dict_to_json(spec).decode("utf-8"))

    text_el, checkbox_el, dropdown_el = restored.content[:3]

    assert isinstance(text_el, TextField)
    assert text_el.name == "email"
    assert text_el.label == "Email Address"
    assert text_el.default == "you@example.com"
    assert text_el.required is True
    assert text_el.multiline is False
    assert text_el.id == "field-email"

    assert isinstance(checkbox_el, CheckboxField)
    assert checkbox_el.name == "newsletter"
    assert checkbox_el.label == "Subscribe to newsletter"
    assert checkbox_el.checked is True
    assert checkbox_el.id == "field-newsletter"

    assert isinstance(dropdown_el, DropdownField)
    assert dropdown_el.name == "plan"
    assert dropdown_el.options == ["Basic", "Pro", "Enterprise"]
    assert dropdown_el.label == "Plan"
    assert dropdown_el.default == "Pro"
    assert dropdown_el.id == "field-plan"


def test_manual_parse_fallback_builds_all_three_types():
    data = {
        "title": "Form",
        "content": [
            {"type": "text_field", "name": "n1", "label": "Name", "required": True},
            {"type": "checkbox_field", "name": "c1", "label": "Check", "checked": True},
            {
                "type": "dropdown_field",
                "name": "d1",
                "label": "Choose",
                "options": ["a", "b"],
                "default": "b",
            },
        ],
    }
    doc = _manual_parse(dict(data))
    text_el, checkbox_el, dropdown_el = doc.content
    assert isinstance(text_el, TextField) and text_el.required is True
    assert isinstance(checkbox_el, CheckboxField) and checkbox_el.checked is True
    assert isinstance(dropdown_el, DropdownField) and dropdown_el.default == "b"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_many_fields_force_a_page_break():
    doc = Document(title="Long Form")
    doc.heading("Application", level=1)
    for i in range(30):
        doc.text_field(f"field_{i}", label=f"Question {i}")
    data = doc.render()
    assert data.startswith(b"%PDF-")
    pdf = pikepdf.open(io.BytesIO(data))
    assert len(pdf.pages) > 1

    _pdf, _acroform, fields = _acroform_fields(data)
    names = {str(f.get("/T", "")) for f in fields}
    assert names == {f"field_{i}" for i in range(30)}


def test_field_near_page_boundary_places_intact_not_split():
    doc = Document(title="Boundary Form")
    doc.heading("Application", level=1)
    for i in range(30):
        doc.text_field(f"field_{i}", label=f"Question number {i} goes here")
    data = doc.render()
    pdf = pikepdf.open(io.BytesIO(data))

    _pdf, _acroform, fields = _acroform_fields(data)
    # Every field's widget /Rect must be a well-formed 4-number box (never
    # a degenerate/zero-height rect from a corrupted split placement).
    for field in fields:
        rect = [float(v) for v in field["/Rect"]]
        assert len(rect) == 4
        x0, y0, x1, y1 = rect
        assert x1 > x0
        assert y1 > y0

    # Each widget's /P points at one of the document's actual page objects.
    page_objgens = {p.objgen for p in pdf.pages}
    for field in fields:
        assert field["/P"].objgen in page_objgens


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_double_render_is_byte_identical():
    def make() -> bytes:
        return _sample_document().render()

    assert make() == make()


def test_double_render_with_all_field_kinds_is_byte_identical():
    def make() -> bytes:
        doc = Document(title="Determinism")
        doc.text_field("a", label="A", default="hello", multiline=True)
        doc.checkbox_field("b", label="B", checked=True)
        doc.dropdown_field("c", ["1", "2", "3"], label="C", default="2")
        return doc.render()

    assert make() == make()
