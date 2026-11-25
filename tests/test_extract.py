from invoiceflow.evaluate import FIELDS, _field_ok
from invoiceflow.extract import ExtractedInvoice, LineItem, extract, parse, reconcile


def test_digital_pdfs_extract_exactly_in_all_layouts(dataset):
    root, gt, _ = dataset
    digital = [g for g in gt if not g["scanned"]]
    assert {g["layout"] for g in digital} == {0, 1, 2}
    for g in digital:
        ex = extract((root / g["file"]).read_bytes())
        assert ex.method == "text-layer"
        assert all(_field_ok(f, ex.invoice.model_dump(mode="json"), g) for f in FIELDS), g["file"]


def test_scanned_pdf_goes_through_ocr(dataset):
    root, gt, _ = dataset
    g = next(g for g in gt if g["scanned"])
    ex = extract((root / g["file"]).read_bytes())
    assert ex.method == "ocr"
    assert ex.invoice.invoice_number == g["invoice_number"] and ex.invoice.po_number == g["po_number"]


def test_parser_tolerates_ocr_noise():
    text = """Inv Number: INV-12345
Customer PO: PO-450001
Supplier ID: SUP-101
Issued: 2026-03-02
CLP-0058 | Hose clamp 32mm | 200 | '132.72 | (26,544.00 |
GSK-0915 Coolant pump gasket 0 82.31 16,462.00
Subtotal: 26,544.00
Tax (0%): 0.00
Total Due (USD): 26,544.00"""
    inv = parse(text)
    assert inv.invoice_number == "INV-12345" and inv.lines[0].amount == 26544.0
    assert inv.unreadable_lines == 1  # quantity 0 is impossible: flagged, not guessed
    assert "1 line item(s) could not be read" in reconcile(inv)


def test_reconcile_catches_arithmetic_problems():
    inv = ExtractedInvoice(invoice_number="INV-1", supplier_id="SUP-1", po_number="PO-1", invoice_date="2026-01-02",
                           total=130.0, subtotal=100.0, tax=6.0,
                           lines=[LineItem(sku="A", description="x", qty=2, unit_price=50, amount=100)])
    assert reconcile(inv) == ["subtotal + tax != total"]
