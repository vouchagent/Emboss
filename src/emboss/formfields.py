"""Interactive AcroForm field construction: text, checkbox, and dropdown.

Extends the ``/AcroForm`` machinery ``signing.py`` already builds for
signature fields: each function here builds one ``/Widget`` annotation
(plus its ``/FT`` field dictionary) and returns a reference the caller
adds to a page's ``/Annots`` array and to the document's ``/AcroForm/
Fields``. ``build_form_acroform`` merges those refs into the same
``/AcroForm`` dict a document's signature fields already populate.
"""

from __future__ import annotations

from .pdf.objects import PdfArray, PdfDict, PdfName, PdfRef, PdfStream

__all__ = [
    "build_text_field_dict",
    "build_checkbox_field_dict",
    "build_dropdown_field_dict",
    "build_form_acroform",
]

#: /Ff flag bits (ISO 32000-1 Table 221/226/228).
_FF_REQUIRED = 1 << 1  # bit 2: field must have a value at submission time
_FF_MULTILINE = 1 << 12  # bit 13 (0x1000): text field allows line breaks
_FF_COMBO = 1 << 17  # bit 18 (0x20000): choice field is a combo box

_DEFAULT_FONT_KEY = "Helv"
_DEFAULT_FONT_SIZE = 10.0


def _base_widget(name: str, rect, page_ref: PdfRef, tooltip: str | None) -> PdfDict:
    """Build the /Widget annotation fields shared by every field type."""
    widget = PdfDict()
    widget["Type"] = PdfName("Annot")
    widget["Subtype"] = PdfName("Widget")
    widget["Rect"] = PdfArray([rect[0], rect[1], rect[2], rect[3]])
    widget["F"] = 4  # Print flag: the widget appears when the page is printed.
    widget["P"] = page_ref
    widget["T"] = name
    if tooltip:
        widget["TU"] = tooltip
    return widget


def build_text_field_dict(
    assembler,
    *,
    name: str,
    rect,
    page_ref: PdfRef,
    default: str = "",
    multiline: bool = False,
    required: bool = False,
    tooltip: str | None = None,
    font_key: str = _DEFAULT_FONT_KEY,
    font_size: float = _DEFAULT_FONT_SIZE,
) -> PdfRef:
    """Build a /Tx (text) AcroForm field and its widget annotation.

    Returns a reference to the field/widget object. The caller must add
    it to the page's /Annots array and to the document's /AcroForm/Fields.
    """
    field = _base_widget(name, rect, page_ref, tooltip)
    field["FT"] = PdfName("Tx")
    field["V"] = default
    field["DA"] = f"/{font_key} {font_size:g} Tf 0 g"
    flags = 0
    if multiline:
        flags |= _FF_MULTILINE
    if required:
        flags |= _FF_REQUIRED
    if flags:
        field["Ff"] = flags
    return assembler.add(field)


def build_dropdown_field_dict(
    assembler,
    *,
    name: str,
    rect,
    page_ref: PdfRef,
    options,
    default: str | None = None,
    tooltip: str | None = None,
    font_key: str = _DEFAULT_FONT_KEY,
    font_size: float = _DEFAULT_FONT_SIZE,
) -> PdfRef:
    """Build a /Ch (choice) combo-box AcroForm field and its widget.

    ``options`` populates /Opt in the given order; ``default``, when
    given, seeds /V with that option's text.
    """
    field = _base_widget(name, rect, page_ref, tooltip)
    field["FT"] = PdfName("Ch")
    field["Ff"] = _FF_COMBO
    field["Opt"] = PdfArray(list(options))
    if default is not None:
        field["V"] = default
    field["DA"] = f"/{font_key} {font_size:g} Tf 0 g"
    return assembler.add(field)


def build_checkbox_field_dict(
    assembler,
    *,
    name: str,
    rect,
    page_ref: PdfRef,
    checked: bool = False,
    tooltip: str | None = None,
) -> PdfRef:
    """Build a /Btn (checkbox) AcroForm field and its widget annotation.

    Builds minimal /AP/N appearance streams for the /Yes and /Off states
    (an empty stream for /Off, a stroked checkmark for /Yes) so the
    widget renders correctly in any PDF reader without regenerating
    appearances, and sets /AS and /V to match ``checked``.
    """
    field = _base_widget(name, rect, page_ref, tooltip)
    field["FT"] = PdfName("Btn")
    state = "Yes" if checked else "Off"
    size = rect[2] - rect[0]
    on_ref = _build_checkbox_appearance(assembler, size, checked=True)
    off_ref = _build_checkbox_appearance(assembler, size, checked=False)
    normal = PdfDict()
    normal["Yes"] = on_ref
    normal["Off"] = off_ref
    appearance = PdfDict()
    appearance["N"] = normal
    field["AP"] = appearance
    field["AS"] = PdfName(state)
    field["V"] = PdfName(state)
    return assembler.add(field)


def _build_checkbox_appearance(assembler, size: float, *, checked: bool) -> PdfRef:
    """Build a Form XObject appearance stream for one checkbox /AP state."""
    ops: list[bytes] = []
    if checked:
        scale = size / 7.0
        stroke_width = max(0.9, 0.9 * scale)
        ops.append(f"{stroke_width:.3f} w".encode("ascii"))
        ops.append(b"0 G")
        x0, y0 = 1.4 * scale, 3.5 * scale
        x1, y1 = 2.9 * scale, 1.7 * scale
        x2, y2 = 5.6 * scale, 5.3 * scale
        ops.append(f"{x0:.3f} {y0:.3f} m".encode("ascii"))
        ops.append(f"{x1:.3f} {y1:.3f} l".encode("ascii"))
        ops.append(f"{x2:.3f} {y2:.3f} l".encode("ascii"))
        ops.append(b"S")
    data = b"\n".join(ops)
    stream = PdfStream(data=data)
    stream.dictionary["Type"] = PdfName("XObject")
    stream.dictionary["Subtype"] = PdfName("Form")
    stream.dictionary["BBox"] = PdfArray([0, 0, size, size])
    return assembler.add(stream)


def build_form_acroform(
    assembler, field_refs: list, *, sig_acroform: PdfDict | None = None
) -> PdfDict:
    """Build or extend the document's /AcroForm dict with form-field refs.

    When ``sig_acroform`` is given (the dict ``signing.build_acroform``
    already built for the document's signature fields), *field_refs* is
    appended to its existing /Fields and its /SigFlags is preserved, so
    signature fields and text/checkbox/dropdown fields end up in one
    /AcroForm. Otherwise a fresh dict is built with no /SigFlags, since
    that flag only applies when a signature field is present. Either way
    the result gets /DR (a Helvetica font resource) and /DA so readers
    have a default appearance font, and /NeedAppearances so text and
    dropdown fields (which carry no per-widget /AP) render their /V.
    """
    acroform = sig_acroform if sig_acroform is not None else PdfDict()
    existing = list(acroform["Fields"].items) if "Fields" in acroform else []
    acroform["Fields"] = PdfArray(existing + list(field_refs))

    helv = PdfDict()
    helv["Type"] = PdfName("Font")
    helv["Subtype"] = PdfName("Type1")
    helv["BaseFont"] = PdfName("Helvetica")
    helv["Encoding"] = PdfName("WinAnsiEncoding")
    helv_ref = assembler.add(helv)
    font_dict = PdfDict()
    font_dict[_DEFAULT_FONT_KEY] = helv_ref
    dr = PdfDict()
    dr["Font"] = font_dict
    acroform["DR"] = dr
    acroform["DA"] = f"/{_DEFAULT_FONT_KEY} {_DEFAULT_FONT_SIZE:g} Tf 0 g"
    acroform["NeedAppearances"] = True
    return acroform
