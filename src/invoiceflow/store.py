"""Persistence with SQLAlchemy Core: SQLite locally, PostgreSQL (JSONB) in production.
The same code runs on both; CI runs the integration tests against a real Postgres."""

from __future__ import annotations

import json
import os
import time

from sqlalchemy import JSON, Column, Float, MetaData, String, Table, create_engine, insert, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.pool import StaticPool

meta = MetaData()
JsonType = JSON().with_variant(JSONB(), "postgresql")

invoices = Table(
    "invoices", meta,
    Column("id", String(64), primary_key=True),          # sha256 of the document: natural idempotency key
    Column("filename", String(255)),
    # received | extracted | auto_approved | needs_review | approved | rejected
    Column("status", String(32), index=True),
    Column("supplier_id", String(32), index=True),
    Column("invoice_number", String(64)),
    Column("extraction", JsonType),
    Column("match", JsonType),
    Column("review", JsonType),
    Column("updated", Float),
)


class InvoiceStore:
    def __init__(self, url: str | None = None):
        url = url or os.environ.get("DATABASE_URL", "sqlite:///:memory:")
        if url.startswith("sqlite") and ":memory:" in url:  # one shared in-memory DB across threads
            self.engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
        else:
            self.engine = create_engine(url, pool_pre_ping=True)
        meta.create_all(self.engine)

    def upsert(self, inv_id: str, **values) -> bool:
        """Insert or update. Returns False if the document was already fully processed (idempotent replay)."""
        values = {k: (json.loads(json.dumps(v, default=str)) if isinstance(v, (dict, list)) else v)
                  for k, v in values.items()}
        with self.engine.begin() as cx:
            row = cx.execute(select(invoices.c.status).where(invoices.c.id == inv_id)).first()
            if row is None:
                cx.execute(insert(invoices).values(id=inv_id, updated=time.time(), **values))
                return True
            cx.execute(update(invoices).where(invoices.c.id == inv_id).values(updated=time.time(), **values))
            return True

    def get(self, inv_id: str) -> dict | None:
        with self.engine.connect() as cx:
            row = cx.execute(select(invoices).where(invoices.c.id == inv_id)).mappings().first()
            return dict(row) if row else None

    def by_status(self, status: str) -> list[dict]:
        with self.engine.connect() as cx:
            return [dict(r) for r in cx.execute(select(invoices).where(invoices.c.status == status)).mappings()]

    def seen_keys(self, exclude_id: str | None = None) -> set[tuple[str, str]]:
        with self.engine.connect() as cx:
            rows = cx.execute(select(invoices.c.id, invoices.c.supplier_id, invoices.c.invoice_number)
                              .where(invoices.c.status.in_(["auto_approved", "needs_review", "approved"])))
            return {(r.supplier_id, r.invoice_number) for r in rows if r.id != exclude_id and r.invoice_number}
