from fastapi.testclient import TestClient

from invoiceflow.api import create_app
from invoiceflow.broker import InMemoryBroker
from invoiceflow.pipeline import BlobStore, Pipeline
from invoiceflow.store import InvoiceStore


def test_upload_review_flow(dataset, tmp_path):
    root, gt, pos = dataset
    c = TestClient(create_app(Pipeline(InMemoryBroker(), InvoiceStore(), BlobStore(tmp_path), pos)))
    bad = next(g for g in gt if g["problem"] in ("price_over_po", "qty_over_received", "unknown_po"))
    r = c.post("/invoices", params={"filename": "x.pdf"}, content=(root / bad["file"]).read_bytes(),
               headers={"content-type": "application/pdf"}).json()
    assert r["status"] == "needs_review"
    assert c.get("/review-queue").json()[0]["reasons"]
    assert c.post(f"/invoices/{r['id']}/review", json={"reviewer": "ap-clerk", "approve": False}).json()["status"] == \
        "rejected"
    assert c.post(f"/invoices/{r['id']}/review", json={"reviewer": "ap-clerk", "approve": True}).status_code == 409
    assert c.post("/invoices", content=b"hello", headers={"content-type": "text/plain"}).status_code == 415
