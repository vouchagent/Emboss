"""Factur-X / ZUGFeRD e-invoicing: EN 16931 CII XML embedded on PDF/A-3.

Builds a UN/CEFACT Cross Industry Invoice (CII) XML for the ZUGFeRD
EN 16931 (COMFORT) profile and packages it as the standardized
``factur-x.xml`` associated file. ``Document.attach_facturx`` wires the
attachment, the PDF/A part 3 declaration, and the ``fx`` XMP extension
schema so the visual PDF and its machine-readable twin describe the same
invoice. Amounts are formatted with fixed decimals and no wall-clock or
random values enter the pipeline, so output stays deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .pdf.attachments import FileAttachment

__all__ = [
    "Party",
    "InvoiceLine",
    "Invoice",
    "FacturXMeta",
    "build_cii_xml",
    "facturx_attachment",
    "PROFILE_URNS",
]

Money = Decimal | int | str

_TWO = Decimal("0.01")
_QTY = Decimal("0.0001")

#: ZUGFeRD/Factur-X profile name to guideline specification URN.
PROFILE_URNS: dict[str, str] = {
    "MINIMUM": "urn:factur-x.eu:1p0:minimum",
    "BASIC WL": "urn:factur-x.eu:1p0:basicwl",
    "BASIC": "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic",
    "EN 16931": "urn:cen.eu:en16931:2017",
    "COMFORT": "urn:cen.eu:en16931:2017",
    "EXTENDED": ("urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended"),
}

_RSM = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
_RAM = (
    "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
)
_QDT = "urn:un:unece:uncefact:data:standard:QualifiedDataType:100"
_UDT = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"


def _dec(value: Money) -> Decimal:
    """Coerce a money-like value to Decimal without float rounding error."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _amt(value: Money) -> str:
    """Format an amount with exactly two decimal places."""
    return str(_dec(value).quantize(_TWO, rounding=ROUND_HALF_UP))


def _qty(value: Money) -> str:
    """Format a quantity with four decimal places."""
    return str(_dec(value).quantize(_QTY, rounding=ROUND_HALF_UP))


def _pct(value: Money) -> str:
    """Format a tax percentage with two decimal places."""
    return str(_dec(value).quantize(_TWO, rounding=ROUND_HALF_UP))


def _esc(text: str) -> str:
    """Escape XML special characters in element text."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _profile_urn(profile: str) -> str:
    """Return the guideline URN for a profile name or raise on unknown."""
    urn = PROFILE_URNS.get(profile.upper())
    if urn is None:
        allowed = ", ".join(sorted(PROFILE_URNS))
        raise ValueError(
            f"unknown Factur-X profile {profile!r}; must be one of: {allowed}"
        )
    return urn


@dataclass(frozen=True)
class Party:
    """A trade party (seller or buyer) with address and VAT registration."""

    name: str
    country_code: str
    vat_id: str | None = None
    postcode: str | None = None
    city: str | None = None
    street: str | None = None


@dataclass(frozen=True)
class InvoiceLine:
    """One invoice line: product, billed quantity, price, net, and VAT rate."""

    name: str
    quantity: Money
    unit_price: Money
    net_amount: Money
    tax_rate_percent: Money
    unit_code: str = "C62"
    category_code: str = "S"

    def expected_net(self) -> Decimal:
        """Return quantity times unit price, quantized to two decimals."""
        product = _dec(self.quantity) * _dec(self.unit_price)
        return product.quantize(_TWO, rounding=ROUND_HALF_UP)

    def net(self) -> Decimal:
        """Return the asserted line net amount, quantized to two decimals."""
        return _dec(self.net_amount).quantize(_TWO, rounding=ROUND_HALF_UP)


@dataclass
class Invoice:
    """An EN 16931 invoice: header, parties, and lines with reconciled totals."""

    invoice_number: str
    issue_date: str
    currency: str
    seller: Party
    buyer: Party
    lines: list[InvoiceLine] = field(default_factory=list)
    type_code: str = "380"

    def validate(self) -> None:
        """Raise ValueError if header fields or line/total arithmetic disagree."""
        if not self.invoice_number:
            raise ValueError("invoice_number must be non-empty")
        if not (len(self.issue_date) == 8 and self.issue_date.isdigit()):
            raise ValueError(
                f"issue_date must be YYYYMMDD digits, got {self.issue_date!r}"
            )
        if not self.currency:
            raise ValueError("currency must be non-empty")
        if not self.lines:
            raise ValueError("invoice must have at least one line")

        for index, line in enumerate(self.lines, start=1):
            expected = line.expected_net()
            if line.net() != expected:
                raise ValueError(
                    f"line {index} ({line.name!r}) net {line.net()} does not equal "
                    f"quantity * unit_price = {expected}"
                )

        line_total = self.line_total_amount()
        tax_basis = self.tax_basis_total()
        if line_total != tax_basis:
            raise ValueError(
                f"line total {line_total} does not equal tax basis {tax_basis}"
            )

        tax_total = Decimal("0.00")
        for _category, _rate, basis, calculated in self.tax_breakdown():
            expected_tax = (basis * _rate / Decimal("100")).quantize(
                _TWO, rounding=ROUND_HALF_UP
            )
            if calculated != expected_tax:
                raise ValueError(
                    f"tax for basis {basis} at {_rate}% is {calculated}, "
                    f"expected {expected_tax}"
                )
            tax_total += calculated

        grand_total = self.grand_total_amount()
        if grand_total != (tax_basis + tax_total).quantize(_TWO):
            raise ValueError(
                f"grand total {grand_total} does not equal basis {tax_basis} "
                f"plus tax {tax_total}"
            )

    def line_total_amount(self) -> Decimal:
        """Sum of all line net amounts."""
        total = sum((line.net() for line in self.lines), Decimal("0"))
        return total.quantize(_TWO, rounding=ROUND_HALF_UP)

    def tax_basis_total(self) -> Decimal:
        """Taxable basis total; equals the line total for this profile."""
        return self.line_total_amount()

    def tax_breakdown(self) -> list[tuple[str, Decimal, Decimal, Decimal]]:
        """Return (category, rate, basis, calculated) groups, sorted for order."""
        groups: dict[tuple[str, Decimal], Decimal] = {}
        for line in self.lines:
            key = (line.category_code, _dec(line.tax_rate_percent))
            groups[key] = groups.get(key, Decimal("0")) + line.net()
        breakdown = []
        for (category, rate), basis in sorted(
            groups.items(), key=lambda item: (item[0][0], item[0][1])
        ):
            basis_q = basis.quantize(_TWO, rounding=ROUND_HALF_UP)
            calculated = (basis_q * rate / Decimal("100")).quantize(
                _TWO, rounding=ROUND_HALF_UP
            )
            breakdown.append((category, rate, basis_q, calculated))
        return breakdown

    def tax_total_amount(self) -> Decimal:
        """Sum of the calculated tax across all rate groups."""
        total = sum(
            (calculated for _c, _r, _b, calculated in self.tax_breakdown()),
            Decimal("0"),
        )
        return total.quantize(_TWO, rounding=ROUND_HALF_UP)

    def grand_total_amount(self) -> Decimal:
        """Tax basis total plus tax total."""
        return (self.tax_basis_total() + self.tax_total_amount()).quantize(
            _TWO, rounding=ROUND_HALF_UP
        )

    def due_payable_amount(self) -> Decimal:
        """Amount due for payment; equals the grand total for this profile."""
        return self.grand_total_amount()


def _party_xml(tag: str, party: Party) -> str:
    """Render a SellerTradeParty or BuyerTradeParty element."""
    address_parts = ["      <ram:PostalTradeAddress>"]
    if party.postcode:
        address_parts.append(
            f"        <ram:PostcodeCode>{_esc(party.postcode)}</ram:PostcodeCode>"
        )
    if party.street:
        address_parts.append(f"        <ram:LineOne>{_esc(party.street)}</ram:LineOne>")
    if party.city:
        address_parts.append(f"        <ram:CityName>{_esc(party.city)}</ram:CityName>")
    address_parts.append(
        f"        <ram:CountryID>{_esc(party.country_code)}</ram:CountryID>"
    )
    address_parts.append("      </ram:PostalTradeAddress>")
    address = "\n".join(address_parts)

    registration = ""
    if party.vat_id:
        registration = (
            "\n      <ram:SpecifiedTaxRegistration>\n"
            f'        <ram:ID schemeID="VA">{_esc(party.vat_id)}</ram:ID>\n'
            "      </ram:SpecifiedTaxRegistration>"
        )

    return (
        f"    <ram:{tag}>\n"
        f"      <ram:Name>{_esc(party.name)}</ram:Name>\n"
        f"{address}"
        f"{registration}\n"
        f"    </ram:{tag}>"
    )


def _line_xml(index: int, line: InvoiceLine) -> str:
    """Render one IncludedSupplyChainTradeLineItem (COMFORT detail)."""
    return (
        "    <ram:IncludedSupplyChainTradeLineItem>\n"
        "      <ram:AssociatedDocumentLineDocument>\n"
        f"        <ram:LineID>{index}</ram:LineID>\n"
        "      </ram:AssociatedDocumentLineDocument>\n"
        "      <ram:SpecifiedTradeProduct>\n"
        f"        <ram:Name>{_esc(line.name)}</ram:Name>\n"
        "      </ram:SpecifiedTradeProduct>\n"
        "      <ram:SpecifiedLineTradeAgreement>\n"
        "        <ram:NetPriceProductTradePrice>\n"
        f"          <ram:ChargeAmount>{_amt(line.unit_price)}</ram:ChargeAmount>\n"
        "        </ram:NetPriceProductTradePrice>\n"
        "      </ram:SpecifiedLineTradeAgreement>\n"
        "      <ram:SpecifiedLineTradeDelivery>\n"
        f'        <ram:BilledQuantity unitCode="{_esc(line.unit_code)}">'
        f"{_qty(line.quantity)}</ram:BilledQuantity>\n"
        "      </ram:SpecifiedLineTradeDelivery>\n"
        "      <ram:SpecifiedLineTradeSettlement>\n"
        "        <ram:ApplicableTradeTax>\n"
        "          <ram:TypeCode>VAT</ram:TypeCode>\n"
        f"          <ram:CategoryCode>{_esc(line.category_code)}</ram:CategoryCode>\n"
        "          <ram:RateApplicablePercent>"
        f"{_pct(line.tax_rate_percent)}</ram:RateApplicablePercent>\n"
        "        </ram:ApplicableTradeTax>\n"
        "        <ram:SpecifiedTradeSettlementLineMonetarySummation>\n"
        f"          <ram:LineTotalAmount>{_amt(line.net())}</ram:LineTotalAmount>\n"
        "        </ram:SpecifiedTradeSettlementLineMonetarySummation>\n"
        "      </ram:SpecifiedLineTradeSettlement>\n"
        "    </ram:IncludedSupplyChainTradeLineItem>"
    )


def _trade_tax_xml(category: str, rate: Decimal, basis: Decimal, calc: Decimal) -> str:
    """Render one header ApplicableTradeTax group."""
    return (
        "      <ram:ApplicableTradeTax>\n"
        f"        <ram:CalculatedAmount>{_amt(calc)}</ram:CalculatedAmount>\n"
        "        <ram:TypeCode>VAT</ram:TypeCode>\n"
        f"        <ram:BasisAmount>{_amt(basis)}</ram:BasisAmount>\n"
        f"        <ram:CategoryCode>{_esc(category)}</ram:CategoryCode>\n"
        f"        <ram:RateApplicablePercent>{_pct(rate)}</ram:RateApplicablePercent>\n"
        "      </ram:ApplicableTradeTax>"
    )


def build_cii_xml(invoice: Invoice, profile: str = "EN 16931") -> str:
    """Build the UN/CEFACT CII XML for *invoice* under the named profile."""
    invoice.validate()
    urn = _profile_urn(profile)
    currency = invoice.currency

    lines_xml = "\n".join(
        _line_xml(index, line) for index, line in enumerate(invoice.lines, start=1)
    )
    seller_xml = _party_xml("SellerTradeParty", invoice.seller)
    buyer_xml = _party_xml("BuyerTradeParty", invoice.buyer)
    taxes_xml = "\n".join(
        _trade_tax_xml(category, rate, basis, calc)
        for category, rate, basis, calc in invoice.tax_breakdown()
    )

    line_total = _amt(invoice.line_total_amount())
    tax_basis = _amt(invoice.tax_basis_total())
    tax_total = _amt(invoice.tax_total_amount())
    grand_total = _amt(invoice.grand_total_amount())
    due = _amt(invoice.due_payable_amount())

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<rsm:CrossIndustryInvoice xmlns:rsm="{_RSM}" xmlns:ram="{_RAM}"'
        f' xmlns:qdt="{_QDT}" xmlns:udt="{_UDT}">\n'
        "  <rsm:ExchangedDocumentContext>\n"
        "    <ram:GuidelineSpecifiedDocumentContextParameter>\n"
        f"      <ram:ID>{_esc(urn)}</ram:ID>\n"
        "    </ram:GuidelineSpecifiedDocumentContextParameter>\n"
        "  </rsm:ExchangedDocumentContext>\n"
        "  <rsm:ExchangedDocument>\n"
        f"    <ram:ID>{_esc(invoice.invoice_number)}</ram:ID>\n"
        f"    <ram:TypeCode>{_esc(invoice.type_code)}</ram:TypeCode>\n"
        "    <ram:IssueDateTime>\n"
        f'      <udt:DateTimeString format="102">{_esc(invoice.issue_date)}'
        "</udt:DateTimeString>\n"
        "    </ram:IssueDateTime>\n"
        "  </rsm:ExchangedDocument>\n"
        "  <rsm:SupplyChainTradeTransaction>\n"
        f"{lines_xml}\n"
        "    <ram:ApplicableHeaderTradeAgreement>\n"
        f"{seller_xml}\n"
        f"{buyer_xml}\n"
        "    </ram:ApplicableHeaderTradeAgreement>\n"
        "    <ram:ApplicableHeaderTradeDelivery/>\n"
        "    <ram:ApplicableHeaderTradeSettlement>\n"
        f"      <ram:InvoiceCurrencyCode>{_esc(currency)}</ram:InvoiceCurrencyCode>\n"
        f"{taxes_xml}\n"
        "      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>\n"
        f"        <ram:LineTotalAmount>{line_total}</ram:LineTotalAmount>\n"
        f"        <ram:TaxBasisTotalAmount>{tax_basis}</ram:TaxBasisTotalAmount>\n"
        f'        <ram:TaxTotalAmount currencyID="{_esc(currency)}">{tax_total}'
        "</ram:TaxTotalAmount>\n"
        f"        <ram:GrandTotalAmount>{grand_total}</ram:GrandTotalAmount>\n"
        f"        <ram:DuePayableAmount>{due}</ram:DuePayableAmount>\n"
        "      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>\n"
        "    </ram:ApplicableHeaderTradeSettlement>\n"
        "  </rsm:SupplyChainTradeTransaction>\n"
        "</rsm:CrossIndustryInvoice>\n"
    )


@dataclass(frozen=True)
class FacturXMeta:
    """XMP fx-namespace values describing the embedded Factur-X invoice."""

    document_type: str = "INVOICE"
    filename: str = "factur-x.xml"
    version: str = "1.0"
    conformance_level: str = "EN 16931"


def facturx_attachment(invoice: Invoice, profile: str = "EN 16931") -> FileAttachment:
    """Build the ``factur-x.xml`` /AF attachment for *invoice*."""
    xml = build_cii_xml(invoice, profile=profile)
    return FileAttachment(
        name="factur-x.xml",
        data=xml.encode("utf-8"),
        mime="text/xml",
        description="Factur-X invoice",
        relationship="Alternative",
    )
