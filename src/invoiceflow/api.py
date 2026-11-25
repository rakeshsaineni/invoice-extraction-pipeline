"""REST API: upload invoices, check status, and work the human review queue."""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from .broker import InMemoryBroker
from .pipeline import BlobStore, Pipeline
from .store import InvoiceStore


class Review(BaseModel):
    reviewer: str
    approve: bool
    corrections: dict = {}
    note: str | None = None


def create_app(pipeline: Pipeline | None = None) -> FastAPI:
    if pipeline is None:
        data = Path(os.environ.get("INVOICEFLOW_DATA", "data"))
        po_file = data / "purchase_orders.json"
        pos = json.loads(po_file.read_text()) if po_file.exists() else {}
        pipeline = Pipeline(InMemoryBroker(), InvoiceStore(), BlobStore(data / "blobs"), pos)
    app = FastAPI(title="invoice-extraction-pipeline", version="0.1.0")

    @app.post("/invoices", status_code=202)
    async def upload(request: Request, filename: str = "upload.pdf") -> dict:
        body = await request.body()
        if not body.startswith(b"%PDF"):
            raise HTTPException(415, "expected a PDF body (Content-Type: application/pdf)")
        if len(body) > 10 * 1024 * 1024:
            raise HTTPException(413, "PDF larger than 10 MB")
        inv_id = pipeline.submit(filename, body)
        if isinstance(pipeline.broker, InMemoryBroker):
            pipeline.broker.drain()  # local mode: process synchronously
        return {"id": inv_id, "status": pipeline.store.get(inv_id)["status"]}

    @app.get("/invoices/{inv_id}")
    def get(inv_id: str) -> dict:
        row = pipeline.store.get(inv_id)
        if not row:
            raise HTTPException(404, "not found")
        return row

    @app.get("/review-queue")
    def queue() -> list[dict]:
        return [{"id": r["id"], "filename": r["filename"], "reasons": (r["match"] or {}).get("reasons", [])}
                for r in pipeline.store.by_status("needs_review")]

    @app.post("/invoices/{inv_id}/review")
    def review(inv_id: str, body: Review) -> dict:
        row = pipeline.store.get(inv_id)
        if not row or row["status"] != "needs_review":
            raise HTTPException(409, "invoice is not waiting for review")
        status = "approved" if body.approve else "rejected"
        pipeline.store.upsert(inv_id, status=status, review=body.model_dump())
        return {"id": inv_id, "status": status}

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app
