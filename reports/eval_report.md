# Evaluation report

300 synthetic invoices through the full pipeline.

## Extraction accuracy

| Field | Digital PDFs (text layer) | Scanned PDFs (OCR) |
|---|---|---|
| invoice_number | 100.0% | 100.0% |
| supplier_id | 100.0% | 100.0% |
| po_number | 100.0% | 100.0% |
| invoice_date | 100.0% | 100.0% |
| due_date | 100.0% | 100.0% |
| total | 100.0% | 100.0% |
| All line items (SKU, qty, price) | 100.0% | 49.4% |
| **Whole invoice exactly right** | 100.0% | 49.4% |
| Documents | 219 | 81 |

## Decisions

| Metric | Value |
|---|---|
| Straight-through (auto-approved, no human touch) | 71.3% |
| **Bad invoices auto-approved (escapes)** | **0** |
| Planted problems held (sent to review, or identical re-upload absorbed) | 55 of 55 |
| OCR misreads sent to review instead of approved | 30 |
| Clean, correctly read invoices sent to review | 1 of 215 |
| Median latency per invoice | text layer 11.5 ms, OCR 1534.4 ms |

| Planted problem | Caught |
|---|---|
| duplicate | 12/12 |
| price_over_po | 8/8 |
| qty_over_received | 16/16 |
| total_mismatch | 7/7 |
| unknown_po | 12/12 |
