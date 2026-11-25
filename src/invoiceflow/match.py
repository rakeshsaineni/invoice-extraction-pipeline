"""3-way match: invoice vs purchase order vs goods receipt, plus duplicate detection."""

from __future__ import annotations

from dataclasses import dataclass, field

from .extract import ExtractedInvoice

PRICE_TOLERANCE = 0.02  # 2% over PO price is accepted (common AP policy)


@dataclass
class MatchResult:
    decision: str  # "auto_approve" | "needs_review"
    reasons: list[str] = field(default_factory=list)


def three_way_match(inv: ExtractedInvoice, purchase_orders: dict, seen: set[tuple[str, str]],
                    extraction_issues: list[str]) -> MatchResult:
    reasons = [f"extraction: {i}" for i in extraction_issues]
    key = (inv.supplier_id or "", inv.invoice_number or "")
    if all(key) and key in seen:
        reasons.append("duplicate: this supplier already submitted this invoice number")
    po = purchase_orders.get(inv.po_number or "")
    if po is None:
        reasons.append(f"unknown purchase order {inv.po_number}")
    else:
        if po["supplier_id"] != inv.supplier_id:
            reasons.append("supplier on invoice does not match the purchase order")
        for ln in inv.lines:
            pl = po["lines"].get(ln.sku)
            if pl is None:
                reasons.append(f"{ln.sku} is not on the purchase order")
                continue
            if ln.unit_price > pl["unit_price"] * (1 + PRICE_TOLERANCE):
                reasons.append(f"{ln.sku}: billed {ln.unit_price:.2f}, PO price {pl['unit_price']:.2f}")
            if ln.qty > pl["received"]:
                reasons.append(f"{ln.sku}: billed {ln.qty} units, received {pl['received']}")
    return MatchResult("needs_review" if reasons else "auto_approve", reasons)
