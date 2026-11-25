"""Wires extraction, matching and storage onto the event bus.

Every handler is idempotent (keyed by the document hash), so redelivered events and
re-uploaded files never double-process an invoice."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .extract import ExtractedInvoice, extract
from .match import three_way_match
from .store import InvoiceStore


class BlobStore:
    """Local folder standing in for Azure Blob Storage (same put/get-by-name contract)."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def put(self, name: str, data: bytes) -> str:
        (self.root / name).write_bytes(data)
        return name

    def get(self, name: str) -> bytes:
        return (self.root / name).read_bytes()


class Pipeline:
    def __init__(self, broker, store: InvoiceStore, blobs: BlobStore, purchase_orders: dict):
        self.broker, self.store, self.blobs, self.pos = broker, store, blobs, purchase_orders
        broker.subscribe("invoice.received", self.on_received)
        broker.subscribe("invoice.extracted", self.on_extracted)

    def submit(self, filename: str, data: bytes) -> str:
        inv_id = hashlib.sha256(data).hexdigest()
        existing = self.store.get(inv_id)
        if existing and existing["status"] != "received":
            return inv_id  # same bytes uploaded again: nothing to do
        blob = self.blobs.put(f"{inv_id}.pdf", data)
        self.store.upsert(inv_id, filename=filename, status="received")
        self.broker.publish("invoice.received", {"id": inv_id, "blob": blob})
        return inv_id

    def on_received(self, event: dict) -> None:
        row = self.store.get(event["id"])
        if row and row["status"] not in ("received",):
            return  # redelivery
        try:
            ex = extract(self.blobs.get(event["blob"]))
        except Exception as e:  # a poison document must not stop the consumer: park it for a person
            self.store.upsert(event["id"], status="needs_review",
                              match={"decision": "needs_review", "reasons": [f"extraction failed: {type(e).__name__}"]})
            return
        self.store.upsert(event["id"], status="extracted", extraction=ex.model_dump(mode="json"),
                          supplier_id=ex.invoice.supplier_id, invoice_number=ex.invoice.invoice_number)
        self.broker.publish("invoice.extracted", {"id": event["id"]})

    def on_extracted(self, event: dict) -> None:
        row = self.store.get(event["id"])
        if not row or row["status"] != "extracted":
            return
        ex = row["extraction"]
        inv = ExtractedInvoice(**ex["invoice"])
        result = three_way_match(inv, self.pos, self.store.seen_keys(exclude_id=event["id"]), ex["issues"])
        status = "auto_approved" if result.decision == "auto_approve" else "needs_review"
        self.store.upsert(event["id"], status=status, match={"decision": result.decision, "reasons": result.reasons})
        self.broker.publish("invoice.matched", {"id": event["id"], "status": status})
