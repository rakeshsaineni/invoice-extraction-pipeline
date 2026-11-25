"""Synthetic accounts-payable data: suppliers, purchase orders, goods receipts and
invoice PDFs in three layouts, some of them "scanned" (image-only, rotated, noisy).

About 20% of invoices carry a planted problem (price above the PO, more units billed
than received, unknown PO, duplicate submission, totals that don't add up), so the
3-way match can be scored. All companies and part numbers are fictional.
"""

from __future__ import annotations

import io
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pypdfium2 as pdfium
from fpdf import FPDF
from PIL import Image, ImageFilter

SUPPLIERS = [("SUP-101", "Lakeside Fasteners Inc."), ("SUP-102", "Northbend Plastics LLC"),
             ("SUP-103", "Riverton Castings Co."), ("SUP-104", "Midstate Wiring Systems"),
             ("SUP-105", "Copperline Electronics"), ("SUP-106", "Granite Seals & Gaskets")]
PARTS = [("BRK-2207", "Brake caliper bracket"), ("FST-0410", "M8 flange bolt (box of 100)"),
         ("HSG-1180", "Sensor housing, PA66"), ("WHR-3302", "Door wiring harness"),
         ("GSK-0915", "Coolant pump gasket"), ("PCB-7720", "Body control module PCB"),
         ("CLP-0058", "Hose clamp 32mm"), ("BRG-6203", "Ball bearing 6203-2RS")]
PROBLEMS = ["price_over_po", "qty_over_received", "unknown_po", "duplicate", "total_mismatch"]


@dataclass
class Line:
    sku: str
    description: str
    qty: int
    unit_price: float

    @property
    def amount(self) -> float:
        return round(self.qty * self.unit_price, 2)


@dataclass
class Invoice:
    invoice_number: str
    supplier_id: str
    supplier_name: str
    po_number: str
    invoice_date: str
    due_date: str
    currency: str
    lines: list[Line]
    tax_rate: float
    subtotal: float = 0.0
    tax: float = 0.0
    total: float = 0.0
    layout: int = 0
    scanned: bool = False
    problem: str | None = None
    file: str = ""


@dataclass
class PurchaseOrder:
    po_number: str
    supplier_id: str
    lines: dict[str, dict] = field(default_factory=dict)  # sku -> {qty, unit_price, received}


def _fmt_date(d: date, layout: int) -> str:
    return [d.strftime("%m/%d/%Y"), d.strftime("%d %b %Y"), d.isoformat()][layout]


def _money(x: float) -> str:
    return f"{x:,.2f}"


def render_pdf(inv: Invoice) -> bytes:
    pdf = FPDF(format="Letter")
    pdf.add_page()
    pdf.set_auto_page_break(False)
    L = inv.layout
    title = ["INVOICE", "Tax Invoice", "Commercial Invoice"][L]
    labels = [("Invoice #", "PO Number", "Invoice Date", "Due Date"),
              ("Invoice No.", "Purchase Order", "Date", "Payment Due"),
              ("Inv Number", "Customer PO", "Issued", "Due By")][L]
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, title, new_x="LMARGIN", new_y="NEXT", align="R" if L == 1 else "L")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, inv.supplier_name, new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, f"Supplier ID: {inv.supplier_id}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.cell(0, 7, "Bill to: Demo Motors Assembly, 100 Plant Rd, Detroit, MI", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    for label, value in zip(labels, (inv.invoice_number, inv.po_number, inv.invoice_date, inv.due_date)):
        pdf.cell(0, 7, f"{label}: {value}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 10)
    heads = [["Item", "Description", "Qty", "Unit Price", "Amount"],
             ["SKU", "Description", "Quantity", "Price", "Line Total"],
             ["Part No", "Description", "Qty", "Rate", "Total"]][L]
    widths = [28, 82, 18, 30, 32]
    for h, w in zip(heads, widths):
        pdf.cell(w, 8, h, border=1)
    pdf.ln()
    pdf.set_font("Helvetica", "", 10)
    for ln in inv.lines:
        for v, w in zip((ln.sku, ln.description, str(ln.qty), _money(ln.unit_price), _money(ln.amount)), widths):
            pdf.cell(w, 8, v, border=1)
        pdf.ln()
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 11)
    for label, value in (("Subtotal", inv.subtotal), (f"Tax ({inv.tax_rate:.0%})", inv.tax),
                         (f"Total Due ({inv.currency})", inv.total)):
        pdf.cell(0, 7, f"{label}: {_money(value)}", new_x="LMARGIN", new_y="NEXT", align="R")
    return bytes(pdf.output())


def scan(pdf_bytes: bytes, rng: random.Random) -> bytes:
    """Make an image-only PDF that looks like a slightly crooked, noisy office scan."""
    page = pdfium.PdfDocument(pdf_bytes)[0]
    img = page.render(scale=150 / 72).to_pil().convert("L")
    img = img.rotate(rng.uniform(-1.2, 1.2), expand=False, fillcolor=255, resample=Image.BICUBIC)
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    noise = Image.effect_noise(img.size, 18).convert("L")
    img = Image.blend(img, noise, 0.08)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=55)
    out = io.BytesIO()
    Image.open(buf).save(out, format="PDF", resolution=150)
    return out.getvalue()


def generate(root: Path, n: int = 300, seed: int = 7, scanned_share: float = 0.25) -> dict:
    rng = random.Random(seed)
    pdf_dir = root / "invoices"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pos: dict[str, PurchaseOrder] = {}
    invoices: list[Invoice] = []
    for i in range(n):
        sid, sname = rng.choice(SUPPLIERS)
        po_no = f"PO-{450000 + i}"
        po = PurchaseOrder(po_no, sid)
        lines = []
        for sku, desc in rng.sample(PARTS, rng.randint(1, 4)):
            qty, price = rng.choice([10, 25, 50, 100, 200, 500]), round(rng.uniform(0.8, 140), 2)
            po.lines[sku] = {"qty": qty, "unit_price": price, "received": qty}
            lines.append(Line(sku, desc, qty, price))
        pos[po_no] = po
        d = date(2026, 1, 5) + timedelta(days=rng.randint(0, 300))
        layout = rng.randint(0, 2)
        inv = Invoice(f"INV-{rng.randint(10000, 99999)}", sid, sname, po_no, _fmt_date(d, layout),
                      _fmt_date(d + timedelta(days=rng.choice([30, 45, 60])), layout), "USD", lines,
                      rng.choice([0.0, 0.06]), layout=layout, scanned=rng.random() < scanned_share)
        problem = rng.choice(PROBLEMS) if rng.random() < 0.2 else None
        if problem == "price_over_po":
            ln = rng.choice(inv.lines)
            ln.unit_price = round(ln.unit_price * rng.uniform(1.08, 1.3), 2)
        elif problem == "qty_over_received":
            ln = rng.choice(inv.lines)
            po.lines[ln.sku]["received"] = max(1, ln.qty - rng.choice([5, 10, 20]))
        elif problem == "unknown_po":
            inv.po_number = f"PO-{990000 + i}"
        elif problem == "duplicate" and invoices:
            prev = rng.choice([x for x in invoices if not x.problem] or invoices)
            inv = Invoice(**{**asdict(prev), "lines": [Line(**ln) for ln in asdict(prev)["lines"]],
                             "problem": "duplicate", "scanned": rng.random() < scanned_share, "file": ""})
        elif problem == "duplicate":
            problem = None
        inv.problem = problem
        inv.subtotal = round(sum(ln.amount for ln in inv.lines), 2)
        inv.tax = round(inv.subtotal * inv.tax_rate, 2)
        inv.total = round(inv.subtotal + inv.tax, 2)
        if problem == "total_mismatch":
            inv.total = round(inv.total + rng.choice([10, 25.5, 100]), 2)
        pdf_bytes = render_pdf(inv)
        if inv.scanned:
            pdf_bytes = scan(pdf_bytes, rng)
        inv.file = f"invoices/{i:04d}_{inv.invoice_number}.pdf"
        (root / inv.file).write_bytes(pdf_bytes)
        invoices.append(inv)
    (root / "purchase_orders.json").write_text(json.dumps({k: asdict(v) for k, v in pos.items()}, indent=1))
    (root / "ground_truth.jsonl").write_text("\n".join(json.dumps(asdict(x)) for x in invoices) + "\n")
    return {"invoices": n, "scanned": sum(x.scanned for x in invoices),
            "with_problems": sum(bool(x.problem) for x in invoices)}


if __name__ == "__main__":
    print(generate(Path("data")))
