import json

import pytest

from invoiceflow.synth import generate


@pytest.fixture(scope="session")
def dataset(tmp_path_factory):
    root = tmp_path_factory.mktemp("ap")
    generate(root, n=40, seed=3, scanned_share=0.1)
    gt = [json.loads(line) for line in (root / "ground_truth.jsonl").read_text().splitlines() if line.strip()]
    pos = json.loads((root / "purchase_orders.json").read_text())
    return root, gt, pos
