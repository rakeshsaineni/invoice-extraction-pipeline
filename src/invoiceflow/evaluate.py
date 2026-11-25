"""End-to-end benchmark: every synthetic invoice goes through the real pipeline (bus, extractor,
3-way match, store) and is scored against ground truth."""

from __future__ import annotations

import json
import statistics
import time
from datetime import date, datetime
from pathlib import Path

from .broker import InMemoryBroker
from .pipeline import BlobStore, Pipeline
from .store import InvoiceStore

FIELDS = ["invoice_number", "supplier_id", "po_number", "invoice_date", "due_date", "total", "lines"]


def _iso(s: str) -> str:
    for fmt in ("%m/%d/%Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return s


def _field_ok(field: str, got: dict, gt: dict) -> bool:
    if field == "lines":
        return [(x["sku"], x["qty"], round(x["unit_price"], 2)) for x in got["lines"]] == [
            (x["sku"], x["qty"], round(x["unit_price"], 2)) for x in gt["lines"]]
    if field in ("invoice_date", "due_date"):
        return got[field] == _iso(gt[field])
    if field == "total":
        return got["total"] is not None and abs(got["total"] - gt["total"]) < 0.005
    return got[field] == gt[field]


def run(data: Path, out: Path, n: int | None = None) -> tuple[dict, list[str]]:
    gt = [json.loads(line) for line in (data / "ground_truth.jsonl").read_text().splitlines() if line.strip()][:n]
    pos = json.loads((data / "purchase_orders.json").read_text())
    pipe = Pipeline(InMemoryBroker(), InvoiceStore("sqlite:///:memory:"), BlobStore(out / "_blobs"), pos)
    per_method: dict[str, dict] = {}
    rows, lat, seen_ids = [], {"text-layer": [], "ocr": []}, set()
    for g in gt:  # submission order matters: duplicates are only detectable after the original
        t0 = time.perf_counter()
        inv_id = pipe.submit(g["file"], (data / g["file"]).read_bytes())
        pipe.broker.drain()
        ms = (time.perf_counter() - t0) * 1000
        row = dict(pipe.store.get(inv_id))
        if inv_id in seen_ids:  # byte-identical resubmission: absorbed by the idempotency key, never re-paid
            row["status"], row["match"] = "deduplicated", {"reasons": ["identical file already received"]}
        seen_ids.add(inv_id)
        ex = row["extraction"]
        method = ex["method"]
        lat[method].append(ms)
        oks = {f: _field_ok(f, ex["invoice"], g) for f in FIELDS}
        m = per_method.setdefault(method, {"docs": 0, "exact": 0, **{f: 0 for f in FIELDS}})
        m["docs"] += 1
        m["exact"] += all(oks.values())
        for f, ok in oks.items():
            m[f] += ok
        rows.append({"file": g["file"], "problem": g["problem"], "method": method, "extracted_ok": all(oks.values()),
                     "status": row["status"], "reasons": (row["match"] or {}).get("reasons", [])})
    for f in (out / "_blobs").glob("*"):
        f.unlink()
    (out / "_blobs").rmdir()

    held = ("needs_review", "deduplicated")
    auto = [r for r in rows if r["status"] == "auto_approved"]
    bad = [r for r in rows if r["problem"] or not r["extracted_ok"]]
    clean = [r for r in rows if not r["problem"] and r["extracted_ok"]]
    planted = [r for r in rows if r["problem"]]
    result = {
        "invoices": len(rows), "by_method": per_method,
        "straight_through_rate": len(auto) / len(rows),
        "escapes": [r for r in auto if r["problem"] or not r["extracted_ok"]],
        "planted_problems": len(planted),
        "planted_caught": sum(r["status"] in held for r in planted),
        "deduplicated_on_upload": sum(r["status"] == "deduplicated" for r in rows),
        "caught_by_type": {p: f"{sum(r['status'] in held for r in planted if r['problem'] == p)}/"
                              f"{sum(r['problem'] == p for r in planted)}"
                           for p in sorted({r["problem"] for r in planted})},
        "clean_sent_to_review": sum(r["status"] == "needs_review" for r in clean), "clean": len(clean),
        "bad": len(bad), "ocr_misreads_sent_to_review": sum(r["status"] == "needs_review" for r in bad
                                                             if not r["problem"]),
        "latency_ms_median": {k: round(statistics.median(v), 1) for k, v in lat.items() if v},
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "eval.json").write_text(json.dumps({**result, "generated": date.today().isoformat()}, indent=1))
    (out / "eval_report.md").write_text(to_markdown(result))
    fails = []
    if result["escapes"]:
        fails.append(f"{len(result['escapes'])} bad invoice(s) were auto-approved")
    tl = per_method.get("text-layer")
    if tl and tl["exact"] < tl["docs"]:
        fails.append("digital PDFs are no longer extracted exactly")
    return result, fails


def to_markdown(r: dict) -> str:
    L = ["# Evaluation report", "", f"{r['invoices']} synthetic invoices through the full pipeline.", "",
         "## Extraction accuracy", "", "| Field | Digital PDFs (text layer) | Scanned PDFs (OCR) |", "|---|---|---|"]
    tl, oc = r["by_method"].get("text-layer", {}), r["by_method"].get("ocr", {})

    def pct(m, f):
        return f"{m[f] / m['docs']:.1%}" if m else "-"
    for f in FIELDS + ["exact"]:
        name = {"exact": "**Whole invoice exactly right**", "lines": "All line items (SKU, qty, price)"}.get(f, f)
        L.append(f"| {name} | {pct(tl, f)} | {pct(oc, f)} |")
    L += [f"| Documents | {tl.get('docs', 0)} | {oc.get('docs', 0)} |", "",
          "## Decisions", "", "| Metric | Value |", "|---|---|",
          f"| Straight-through (auto-approved, no human touch) | {r['straight_through_rate']:.1%} |",
          f"| **Bad invoices auto-approved (escapes)** | **{len(r['escapes'])}** |",
          f"| Planted problems held (sent to review, or identical re-upload absorbed) | {r['planted_caught']} of "
          f"{r['planted_problems']} |",
          f"| OCR misreads sent to review instead of approved | {r['ocr_misreads_sent_to_review']} |",
          f"| Clean, correctly read invoices sent to review | {r['clean_sent_to_review']} of {r['clean']} |",
          f"| Median latency per invoice | text layer {r['latency_ms_median'].get('text-layer', '-')} ms, "
          f"OCR {r['latency_ms_median'].get('ocr', '-')} ms |", "",
          "| Planted problem | Caught |", "|---|---|"]
    L += [f"| {p} | {v} |" for p, v in r["caught_by_type"].items()]
    return "\n".join(L) + "\n"
