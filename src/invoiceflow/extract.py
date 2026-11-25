"""PDF -> validated invoice JSON.

1. Use the text layer when there is one (digital PDFs).
2. Otherwise OCR: render at 300 DPI, deskew, erase table borders, run Tesseract with two
   page-segmentation modes, and keep the reading whose line items add up to the subtotal.
3. Parse fields with layout-tolerant patterns (or an LLM, see `llm_extract`).
4. Validate with Pydantic and reconcile the arithmetic. Anything that doesn't reconcile
   goes to a human; nothing is silently "fixed".
"""

from __future__ import annotations

import hashlib
import io
import re
from datetime import date, datetime

import numpy as np
import pdfplumber
from PIL import Image
from pydantic import BaseModel, Field, ValidationError, field_validator

MONEY = r"(\d{1,3}(?:,\d{3})*\.\d{2})"


class LineItem(BaseModel):
    sku: str
    description: str
    qty: int = Field(gt=0)
    unit_price: float = Field(ge=0)
    amount: float = Field(ge=0)


class ExtractedInvoice(BaseModel):
    invoice_number: str | None = None
    supplier_id: str | None = None
    po_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str | None = None
    lines: list[LineItem] = []
    subtotal: float | None = None
    tax_rate: float | None = None
    tax: float | None = None
    total: float | None = None
    unreadable_lines: int = 0

    @field_validator("invoice_date", "due_date", mode="before")
    @classmethod
    def parse_date(cls, v):
        if v is None or isinstance(v, date):
            return v
        for fmt in ("%m/%d/%Y", "%d %b %Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(v.strip(), fmt).date()
            except ValueError:
                continue
        return None


class Extraction(BaseModel):
    document_sha256: str
    method: str  # "text-layer" | "ocr"
    invoice: ExtractedInvoice
    issues: list[str]
    confidence: float


def _num(s: str | None) -> float | None:
    return float(s.replace(",", "")) if s else None


DATE = r"([0-9]{1,4}[/\-][0-9]{1,2}[/\-][0-9]{2,4}|\d{1,2} [A-Z][a-z]{2} \d{4})"
LABELS = {
    "invoice_number": r"(?:Invoice\s*(?:#|No\.?|Number)|Inv\s*Number)\s*[:#]?\s*([A-Z]{2,4}-\d{4,6})",
    "po_number": r"(?:PO\s*Number|Purchase\s*Order|Customer\s*PO)\s*[:#]?\s*(PO-\d{6})",
    "supplier_id": r"Supplier\s*ID\s*[:#]?\s*(SUP-\d{3})",
    "invoice_date": r"(?:Invoice\s*Date|^Date|Issued)\s*:\s*" + DATE,
    "due_date": r"(?:Due\s*Date|Payment\s*Due|Due\s*By)\s*:\s*" + DATE,
}
LINE_RE = re.compile(r"^\W*([A-Z]{3}-\d{4})\W+(.+?)\W+(\d{1,4})\W+" + MONEY + r"\W+" + MONEY + r"\W*$")


def parse(text: str) -> ExtractedInvoice:
    out: dict = {}
    for field, pat in LABELS.items():
        m = re.search(pat, text, re.I | re.M)
        out[field] = m.group(1) if m else None
    lines, unreadable = [], 0
    for raw in text.splitlines():
        m = LINE_RE.match(raw.strip())
        if m:
            try:
                lines.append(LineItem(sku=m.group(1), description=m.group(2).strip(" |"), qty=int(m.group(3)),
                                      unit_price=_num(m.group(4)), amount=_num(m.group(5))))
            except ValidationError:  # e.g. OCR read a quantity as 0: flag it, don't guess
                unreadable += 1
    out["lines"], out["unreadable_lines"] = lines, unreadable
    m = re.search(r"Subtotal\W+" + MONEY, text)
    out["subtotal"] = _num(m.group(1)) if m else None
    m = re.search(r"Tax\s*\((\d+)%\)\W+" + MONEY, text)
    out["tax_rate"], out["tax"] = (int(m.group(1)) / 100, _num(m.group(2))) if m else (None, None)
    m = re.search(r"Total\s*Due\s*\((\w{3})\)\W+" + MONEY, text)
    out["currency"], out["total"] = (m.group(1), _num(m.group(2))) if m else (None, None)
    return ExtractedInvoice(**out)


def reconcile(inv: ExtractedInvoice) -> list[str]:
    issues = [f"missing {f}" for f in ("invoice_number", "supplier_id", "po_number", "invoice_date", "total")
              if getattr(inv, f) in (None, "")]
    if not inv.lines:
        issues.append("no line items found")
    if inv.unreadable_lines:
        issues.append(f"{inv.unreadable_lines} line item(s) could not be read")
    for ln in inv.lines:
        if abs(ln.qty * ln.unit_price - ln.amount) > 0.011:
            issues.append(f"line {ln.sku}: qty x price != amount")
    if inv.lines and inv.subtotal is not None and abs(sum(ln.amount for ln in inv.lines) - inv.subtotal) > 0.011:
        issues.append("line items do not add up to the subtotal")
    if None not in (inv.subtotal, inv.tax, inv.total) and abs(inv.subtotal + inv.tax - inv.total) > 0.011:
        issues.append("subtotal + tax != total")
    if inv.invoice_date and inv.due_date and inv.due_date < inv.invoice_date:
        issues.append("due date is before the invoice date")
    return issues


# ---------------------------------------------------------------- OCR helpers

def deskew(img: Image.Image, max_deg: float = 2.0, step: float = 0.2) -> Image.Image:
    """Pick the rotation that makes text rows sharpest (max variance of the row profile)."""
    small = img.convert("L").resize((img.width // 4, img.height // 4))
    best, best_score = 0.0, -1.0
    for deg in np.arange(-max_deg, max_deg + 1e-9, step):
        a = np.asarray(small.rotate(deg, fillcolor=255)) < 128
        score = float(np.var(a.sum(axis=1)))
        if score > best_score:
            best, best_score = float(deg), score
    return img.rotate(best, fillcolor=255, resample=Image.BICUBIC) if abs(best) > 1e-6 else img


def remove_rules(img: Image.Image, min_len: int = 60) -> Image.Image:
    """Erase long horizontal and vertical dark runs (table borders) so OCR sees plain rows."""
    a = np.array(img.convert("L"))
    dark = a < 140
    for axis, need in ((1, min_len * 3), (0, min_len)):
        d, o = (dark, a) if axis == 1 else (dark.T, a.T)
        for i in np.flatnonzero(d.any(axis=1)):
            edges = np.flatnonzero(np.diff(np.concatenate(([0], d[i].astype(np.int8), [0]))))
            for s, e in zip(edges[::2], edges[1::2]):
                if e - s >= need:
                    o[i, s:e] = 255
    return Image.fromarray(a)


def ocr(img: Image.Image) -> str:
    import pytesseract

    clean = remove_rules(deskew(img))
    best_text, best_issues = "", None
    for psm in (4, 6):
        text = pytesseract.image_to_string(clean, config=f"--psm {psm}")
        issues = reconcile(parse(text))
        if best_issues is None or len(issues) < len(best_issues):
            best_text, best_issues = text, issues
        if not issues:
            break
    return best_text


def read_text(pdf_bytes: bytes) -> tuple[str, str]:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[0]
        text = page.extract_text() or ""
        if len(text.strip()) > 50:
            return text, "text-layer"
        return ocr(page.to_image(resolution=300).original), "ocr"


def extract(pdf_bytes: bytes) -> Extraction:
    text, method = read_text(pdf_bytes)
    inv = parse(text)
    issues = reconcile(inv)
    confidence = max(0.0, 1.0 - 0.25 * len(issues)) * (1.0 if method == "text-layer" else 0.9)
    return Extraction(document_sha256=hashlib.sha256(pdf_bytes).hexdigest(), method=method, invoice=inv,
                      issues=issues, confidence=round(confidence, 2))


LLM_PROMPT = ("Extract the invoice into JSON matching the schema. Copy values exactly as printed; use null for "
              "anything not present. Do not compute or correct totals.")


def llm_extract(text: str, llm) -> ExtractedInvoice:
    """For layouts the patterns don't know: the same schema, filled by an LLM (structured output).
    The result goes through the same `reconcile` checks, so a model can't invent a balanced invoice
    without the arithmetic being checked."""
    return ExtractedInvoice(**llm.complete_json(LLM_PROMPT, text, ExtractedInvoice.model_json_schema()))
