"""Runs in CI against a PostgreSQL service container (DATABASE_URL); skipped elsewhere."""

import os

import pytest

from invoiceflow.store import InvoiceStore

pytestmark = pytest.mark.postgres
URL = os.environ.get("DATABASE_URL", "")


@pytest.mark.skipif(not URL.startswith("postgresql"), reason="DATABASE_URL is not PostgreSQL")
def test_jsonb_roundtrip_and_status_queries():
    s = InvoiceStore(URL)
    s.upsert("pg-1", filename="a.pdf", status="needs_review", supplier_id="SUP-1", invoice_number="INV-1",
             match={"decision": "needs_review", "reasons": ["unknown purchase order PO-9"]})
    row = s.get("pg-1")
    assert row["match"]["reasons"] == ["unknown purchase order PO-9"]
    assert any(r["id"] == "pg-1" for r in s.by_status("needs_review"))
    assert ("SUP-1", "INV-1") in s.seen_keys()
