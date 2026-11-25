import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "azure_function"))


def test_blob_handler_produces_a_cosmos_document(dataset):
    from function_app import handle_blob

    root, gt, pos = dataset
    g = next(g for g in gt if not g["scanned"] and not g["problem"])
    doc = handle_blob(f"invoices/{g['file']}", (root / g["file"]).read_bytes(), pos)
    assert doc["status"] == "auto_approved" and doc["supplier_id"] == g["supplier_id"] and len(doc["id"]) == 64
