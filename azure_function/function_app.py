"""Azure Functions (Python v2 model): a blob upload to `invoices/` triggers extraction and
matching, and the result is written to Cosmos DB through an output binding.

Purchase orders come from the ERP export in blob storage (`reference/purchase_orders.json`).
Duplicate detection against earlier invoices runs in the API service, which can query Cosmos.
"""

import json

import azure.functions as func

from invoiceflow.extract import extract
from invoiceflow.match import three_way_match

app = func.FunctionApp()


def handle_blob(name: str, data: bytes, purchase_orders: dict) -> dict:
    ex = extract(data)
    result = three_way_match(ex.invoice, purchase_orders, set(), ex.issues)
    return {"id": ex.document_sha256, "blob": name, "supplier_id": ex.invoice.supplier_id or "unknown",
            "status": "auto_approved" if result.decision == "auto_approve" else "needs_review",
            "extraction": ex.model_dump(mode="json"), "match": {"decision": result.decision, "reasons": result.reasons}}


@app.blob_trigger(arg_name="blob", path="invoices/{name}", connection="AzureWebJobsStorage")
@app.blob_input(arg_name="pos", path="reference/purchase_orders.json", connection="AzureWebJobsStorage")
@app.cosmos_db_output(arg_name="doc", database_name="invoiceflow", container_name="invoices",
                      connection="COSMOS_CONNECTION")
def process_invoice(blob: func.InputStream, pos: str, doc: func.Out[func.Document]) -> None:
    doc.set(func.Document.from_dict(handle_blob(blob.name, blob.read(), json.loads(pos))))
