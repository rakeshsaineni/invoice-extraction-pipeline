"""invoiceflow generate | extract FILE | eval | serve"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="invoiceflow")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("-n", type=int, default=300)
    x = sub.add_parser("extract")
    x.add_argument("pdf")
    e = sub.add_parser("eval")
    e.add_argument("-n", type=int, default=None)
    e.add_argument("--out", default="reports")
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8000)
    a = ap.parse_args(argv)
    data = Path("data")
    if a.cmd == "generate":
        from .synth import generate

        print(generate(data, n=a.n))
    elif a.cmd == "extract":
        from .extract import extract

        print(json.dumps(extract(Path(a.pdf).read_bytes()).model_dump(mode="json"), indent=2))
    elif a.cmd == "eval":
        from .evaluate import run

        _, fails = run(data, Path(a.out), a.n)
        print(Path(a.out, "eval_report.md").read_text())
        if fails:
            print("EVAL GATE FAILED: " + "; ".join(fails), file=sys.stderr)
            return 1
    elif a.cmd == "serve":
        import uvicorn

        uvicorn.run("invoiceflow.api:create_app", factory=True, host="0.0.0.0", port=a.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
