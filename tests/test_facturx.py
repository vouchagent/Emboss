"""Tests for Factur-X / ZUGFeRD EN 16931 e-invoicing."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from decimal import Decimal

import pytest

from emboss import (
    Document,
    FacturXMeta,
    Invoice,
    InvoiceLine,
    Party,
    build_cii_xml,
    facturx_attachment,
)
from emboss.pdfa import build_xmp_metadata, pdfa_part_for

_RSM = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
_RAM = (
    "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
)
_NS = {"rsm": _RSM, "ram": _RAM}


def _sample_invoice() -> Invoice:
    """A two-line EN 16931 invoice with reconciled totals."""
    seller = Party(
        name="Muster GmbH",
        country_code="DE",
        vat_id="DE123456789",
        postcode="10115",
        city="Berlin",
        street="Hauptstrasse 1",
    )
    buyer = Party(
        name="Kunde AG",
        country_code="FR",
        vat_id="FR00123456789",
        postcode="75001",
        city="Paris",
        street="Rue de Rivoli 2",
    )
    lines = [
        InvoiceLine(
            name="Widget",
            quantity=Decimal("2"),
            unit_price=Decimal("100.00"),
            net_amount=Decimal("200.00"),
            tax_rate_percent=Decimal("19"),
        ),
        InvoiceLine(
            name="Gadget",
            quantity=Decimal("1"),
            unit_price=Decimal("50.00"),
            net_amount=Decimal("50.00"),
            tax_rate_percent=Decimal("19"),
        ),
    ]
    return Invoice(
        invoice_number="INV-2024-001",
        issue_date="20240115",
        currency="EUR",
        seller=seller,
        buyer=buyer,
        lines=lines,
    )


def test_totals_compute_correctly() -> None:
    inv = _sample_invoice()
    assert inv.line_total_amount() == Decimal("250.00")
    assert inv.tax_basis_total() == Decimal("250.00")
    assert inv.tax_total_amount() == Decimal("47.50")
    assert inv.grand_total_amount() == Decimal("297.50")
    assert inv.due_payable_amount() == Decimal("297.50")


def test_build_cii_xml_well_formed_and_complete() -> None:
    xml = build_cii_xml(_sample_invoice(), profile="EN 16931")
    root = ET.fromstring(xml)
    assert root.tag == f"{{{_RSM}}}CrossIndustryInvoice"

    guideline = root.find(
        "rsm:ExchangedDocumentContext/"
        "ram:GuidelineSpecifiedDocumentContextParameter/ram:ID",
        _NS,
    )
    assert guideline is not None
    assert guideline.text == "urn:cen.eu:en16931:2017"

    number = root.find("rsm:ExchangedDocument/ram:ID", _NS)
    assert number is not None and number.text == "INV-2024-001"

    date = root.find(
        "rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString",
        {**_NS, "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"},
    )
    assert date is not None and date.attrib["format"] == "102"
    assert date.text == "20240115"

    lines = root.findall(
        "rsm:SupplyChainTradeTransaction/ram:IncludedSupplyChainTradeLineItem",
        _NS,
    )
    assert len(lines) == 2

    vats = root.findall(".//ram:SpecifiedTaxRegistration/ram:ID", _NS)
    vat_values = {v.text for v in vats}
    assert "DE123456789" in vat_values
    assert "FR00123456789" in vat_values

    grand = root.find(
        "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement/"
        "ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:GrandTotalAmount",
        _NS,
    )
    assert grand is not None and grand.text == "297.50"

    tax_total = root.find(
        "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement/"
        "ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:TaxTotalAmount",
        _NS,
    )
    assert tax_total is not None
    assert tax_total.attrib["currencyID"] == "EUR"
    assert tax_total.text == "47.50"


def test_basic_profile_urn() -> None:
    xml = build_cii_xml(_sample_invoice(), profile="BASIC")
    root = ET.fromstring(xml)
    guideline = root.find(
        "rsm:ExchangedDocumentContext/"
        "ram:GuidelineSpecifiedDocumentContextParameter/ram:ID",
        _NS,
    )
    assert guideline is not None
    assert "basic" in guideline.text


def test_unknown_profile_raises() -> None:
    with pytest.raises(ValueError, match="unknown Factur-X profile"):
        build_cii_xml(_sample_invoice(), profile="NONEXISTENT")


def test_inconsistent_line_net_raises() -> None:
    inv = _sample_invoice()
    inv.lines[0] = InvoiceLine(
        name="Widget",
        quantity=Decimal("2"),
        unit_price=Decimal("100.00"),
        net_amount=Decimal("199.00"),  # should be 200.00
        tax_rate_percent=Decimal("19"),
    )
    with pytest.raises(ValueError, match="does not equal"):
        inv.validate()
    with pytest.raises(ValueError):
        build_cii_xml(inv)


def test_consistent_invoice_does_not_raise() -> None:
    _sample_invoice().validate()


def test_bad_issue_date_raises() -> None:
    inv = _sample_invoice()
    inv.issue_date = "2024-01-15"
    with pytest.raises(ValueError, match="YYYYMMDD"):
        inv.validate()


def test_multi_rate_tax_breakdown() -> None:
    inv = Invoice(
        invoice_number="INV-2",
        issue_date="20240201",
        currency="EUR",
        seller=Party(name="S", country_code="DE", vat_id="DE1"),
        buyer=Party(name="B", country_code="DE"),
        lines=[
            InvoiceLine(
                name="A",
                quantity=Decimal("1"),
                unit_price=Decimal("100.00"),
                net_amount=Decimal("100.00"),
                tax_rate_percent=Decimal("19"),
            ),
            InvoiceLine(
                name="B",
                quantity=Decimal("1"),
                unit_price=Decimal("100.00"),
                net_amount=Decimal("100.00"),
                tax_rate_percent=Decimal("7"),
            ),
        ],
    )
    breakdown = inv.tax_breakdown()
    assert len(breakdown) == 2
    assert inv.tax_total_amount() == Decimal("26.00")
    assert inv.grand_total_amount() == Decimal("226.00")
    root = ET.fromstring(build_cii_xml(inv))
    taxes = root.findall(
        "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement/"
        "ram:ApplicableTradeTax",
        _NS,
    )
    assert len(taxes) == 2


def test_facturx_attachment_metadata() -> None:
    att = facturx_attachment(_sample_invoice())
    assert att.name == "factur-x.xml"
    assert att.mime == "text/xml"
    assert att.relationship == "Alternative"
    assert att.description == "Factur-X invoice"
    assert b"CrossIndustryInvoice" in att.data


def test_xmp_facturx_namespace_and_schema() -> None:
    meta = FacturXMeta(conformance_level="EN 16931")
    xmp = build_xmp_metadata(
        title="Invoice",
        author="Muster GmbH",
        subject="Invoice",
        keywords="",
        creator="Emboss",
        producer="Emboss",
        language="en-US",
        pdfa=True,
        tagged=True,
        part=3,
        facturx=meta,
    ).decode("utf-8")
    assert "urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#" in xmp
    assert "<fx:DocumentFileName>factur-x.xml</fx:DocumentFileName>" in xmp
    assert "<fx:ConformanceLevel>EN 16931</fx:ConformanceLevel>" in xmp
    assert "Factur-X PDFA Extension Schema" in xmp
    # The XMP body (between the xpacket markers) must be well-formed XML.
    start = xmp.index("<x:xmpmeta")
    end = xmp.index("</x:xmpmeta>") + len("</x:xmpmeta>")
    ET.fromstring(xmp[start:end])


def test_xmp_without_facturx_unchanged() -> None:
    xmp = build_xmp_metadata(
        title="Doc",
        author="A",
        subject="S",
        keywords="",
        creator="Emboss",
        producer="Emboss",
        language="en-US",
    ).decode("utf-8")
    assert "factur-x" not in xmp
    assert "fx:DocumentType" not in xmp


def test_pdfa_part_is_three_with_attachments() -> None:
    assert pdfa_part_for(True) == 3


def _make_document() -> Document:
    doc = Document(title="Invoice INV-2024-001", author="Muster GmbH")
    doc.heading("Invoice INV-2024-001", level=1)
    doc.paragraph("Total due: EUR 297.50")
    doc.attach_facturx(_sample_invoice(), profile="EN 16931")
    return doc


def test_attach_facturx_sets_pdfa_and_meta() -> None:
    doc = _make_document()
    assert doc.pdfa is True
    assert doc._facturx_meta is not None
    assert doc._facturx_meta.conformance_level == "EN 16931"
    assert len(doc._extra_attachments) == 1


def test_attach_facturx_validates_eagerly() -> None:
    inv = _sample_invoice()
    inv.lines[0] = InvoiceLine(
        name="Widget",
        quantity=Decimal("2"),
        unit_price=Decimal("100.00"),
        net_amount=Decimal("199.00"),
        tax_rate_percent=Decimal("19"),
    )
    with pytest.raises(ValueError):
        Document(title="X").attach_facturx(inv)


def test_render_is_deterministic() -> None:
    a = _make_document().render()
    b = _make_document().render()
    assert a == b


def test_rendered_pdf_declares_facturx_xmp() -> None:
    data = _make_document().render()
    assert b"urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#" in data
    assert b"EN 16931" in data
    assert b"factur-x.xml" in data
    assert b"pdfaid:part>3" in data


def test_rendered_pdf_has_facturx_attachment() -> None:
    pikepdf = pytest.importorskip("pikepdf")
    data = _make_document().render()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        af = pdf.Root.AF
        specs = list(af)
        names = {str(spec.F) for spec in specs}
        assert "factur-x.xml" in names
        target = next(spec for spec in specs if str(spec.F) == "factur-x.xml")
        assert str(target.AFRelationship) == "/Alternative"
        stream = target.EF.F
        xml_bytes = stream.read_bytes()
        assert b"CrossIndustryInvoice" in xml_bytes
        assert b"INV-2024-001" in xml_bytes


@pytest.mark.skipif(
    not (shutil.which("verapdf") or os.environ.get("VERAPDF_PATH")),
    reason="veraPDF not available",
)
def test_verapdf_pdfa3b_conformant() -> None:
    binary = os.environ.get("VERAPDF_PATH") or shutil.which("verapdf")
    data = _make_document().render()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
        handle.write(data)
        path = handle.name
    try:
        result = subprocess.run(
            [binary, "-f", "3b", path],
            capture_output=True,
            text=True,
            check=False,
        )
        assert 'isCompliant="true"' in result.stdout or result.returncode == 0
    finally:
        os.unlink(path)
