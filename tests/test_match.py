from invoiceflow.extract import ExtractedInvoice, LineItem
from invoiceflow.match import three_way_match

PO = {"PO-1": {"supplier_id": "SUP-1", "lines": {"A": {"qty": 10, "unit_price": 10.0, "received": 8}}}}


def inv(**kw):
    base = dict(invoice_number="INV-1", supplier_id="SUP-1", po_number="PO-1",
                lines=[LineItem(sku="A", description="x", qty=8, unit_price=10.0, amount=80.0)])
    return ExtractedInvoice(**{**base, **kw})


def test_clean_invoice_is_auto_approved():
    assert three_way_match(inv(), PO, set(), []).decision == "auto_approve"


def test_price_tolerance_and_quantity_received():
    within = [LineItem(sku="A", description="x", qty=8, unit_price=10.19, amount=81.52)]
    assert three_way_match(inv(lines=within), PO, set(), []).decision == "auto_approve"  # +1.9%
    over = [LineItem(sku="A", description="x", qty=8, unit_price=10.5, amount=84.0)]
    assert "PO price" in three_way_match(inv(lines=over), PO, set(), []).reasons[0]
    billed_more = [LineItem(sku="A", description="x", qty=10, unit_price=10.0, amount=100.0)]
    assert "received 8" in three_way_match(inv(lines=billed_more), PO, set(), []).reasons[0]


def test_unknown_po_supplier_mismatch_duplicate_and_extraction_issues():
    assert "unknown purchase order" in three_way_match(inv(po_number="PO-9"), PO, set(), []).reasons[0]
    assert "does not match" in three_way_match(inv(supplier_id="SUP-2"), PO, set(), []).reasons[0]
    assert "duplicate" in three_way_match(inv(), PO, {("SUP-1", "INV-1")}, []).reasons[0]
    assert three_way_match(inv(), PO, set(), ["no line items found"]).decision == "needs_review"
