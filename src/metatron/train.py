"""CLI: python -m metatron.train --config config.yaml [--input file.csv] [--run-id ID]

Exit code 0 = trained, 2 = stopped by the data-contract gate, 1 = failed.
"""

from __future__ import annotations

import argparse
import json
import sys

from metatron.config import load_config
from metatron.flows.training_flow import run_training


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the METATRON TrainingFlow")
    ap.add_argument("--config", default=None)
    ap.add_argument("--input", default=None, help="CSV/Excel of sellers (default: data.raw_path)")
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()
    cfg = load_config(args.config)
    state = run_training(cfg.path(args.input or cfg.data.raw_path), cfg, args.run_id)
    print(json.dumps(state.model_dump(), ensure_ascii=False, indent=2))
    return {"trained": 0, "stopped": 2}.get(state.status, 1)


if __name__ == "__main__":
    sys.exit(main())
