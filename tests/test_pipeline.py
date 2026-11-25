from invoiceflow.broker import InMemoryBroker
from invoiceflow.evaluate import run
from invoiceflow.pipeline import BlobStore, Pipeline
from invoiceflow.store import InvoiceStore


def make(tmp_path, pos):
    return Pipeline(InMemoryBroker(), InvoiceStore(), BlobStore(tmp_path / "blobs"), pos)


def test_end_to_end_no_bad_invoice_is_auto_approved(dataset, tmp_path):
    root, gt, _ = dataset
    result, fails = run(root, tmp_path / "reports")
    assert not fails, fails
    assert result["planted_caught"] == result["planted_problems"] > 0


def test_resubmitting_the_same_file_is_idempotent(dataset, tmp_path):
    root, gt, pos = dataset
    p = make(tmp_path, pos)
    data = (root / gt[0]["file"]).read_bytes()
    a = p.submit("a.pdf", data)
    p.broker.drain()
    b = p.submit("copy-of-a.pdf", data)
    p.broker.drain()
    assert a == b and len(p.broker.published) == 3  # received, extracted, matched: once


def test_redelivered_event_is_ignored(dataset, tmp_path):
    root, gt, pos = dataset
    p = make(tmp_path, pos)
    inv_id = p.submit("a.pdf", (root / gt[0]["file"]).read_bytes())
    p.broker.drain()
    before = p.store.get(inv_id)["status"]
    p.on_received({"id": inv_id, "blob": f"{inv_id}.pdf"})  # Kafka at-least-once redelivery
    p.on_extracted({"id": inv_id})
    assert p.store.get(inv_id)["status"] == before


def test_poison_document_is_parked_not_fatal(tmp_path):
    p = make(tmp_path, {})
    inv_id = p.submit("broken.pdf", b"%PDF-1.4 this is not really a pdf")
    p.broker.drain()
    row = p.store.get(inv_id)
    assert row["status"] == "needs_review" and "extraction failed" in row["match"]["reasons"][0]
