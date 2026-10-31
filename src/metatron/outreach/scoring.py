"""Score a file of new sellers with the selected model of the latest trained run."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from metatron.config import Config
from metatron.data.cleaning import clean
from metatron.model.features import INPUT_COLUMNS
from metatron.model.train import load_model
from metatron.outreach.store import Store
from metatron.pipeline import read_table


def latest_run(cfg: Config) -> Path:
    runs = cfg.path(cfg["runs_dir"])
    marker = runs / "LATEST"
    if not marker.exists():
        raise FileNotFoundError("no trained run yet: run `python -m metatron.train` first")
    return runs / marker.read_text(encoding="utf-8").strip()


def score_frame(df: pd.DataFrame, run_dir: Path) -> tuple[pd.DataFrame, str]:
    import json

    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    version = metrics["selected"]
    model = load_model(run_dir / "models" / version / "model.joblib")
    out = df.copy()
    out["score"] = model.predict_proba(out[INPUT_COLUMNS])[:, 1].round(4)
    out = out.sort_values("score", ascending=False, kind="stable").reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)
    return out, version


def score_file(path: Path, cfg: Config, store: Store, run_dir: Path | None = None) -> dict:
    run_dir = run_dir or latest_run(cfg)
    df, log = clean(read_table(path).drop(columns=[cfg["data"]["target"]], errors="ignore"))
    scored, version = score_frame(df, run_dir)
    rows = [{"seller_id": r.seller_id, "name": r.seller_name, "phone": r.phone, "city": r.city,
             "address": r.address, "rooms": float(r.rooms), "area_sqm": int(r.area_sqm),
             "asking_price": int(r.asking_price), "days_on_market": int(r.days_on_market),
             "price_drops": int(r.price_drops), "score": float(r.score), "rank": int(r.rank),
             "model_version": version, "run_id": run_dir.name}
            for r in scored.itertuples()]
    store.upsert_sellers(rows)
    store.log(None, "scored_file", f"{path.name}: {len(rows)} sellers, model {version}")
    return {"n": len(rows), "model_version": version, "run_id": run_dir.name,
            "cleaning": log}
