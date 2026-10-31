"""Deterministic pipeline steps over one run directory: runs/<run_id>/.

Both the CrewAI tools and the offline mode call these functions, so a run produces the same
artifacts and metrics whether or not an LLM is involved. Only the prose (insights, model card)
differs.
"""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import sklearn

from metatron.config import Config
from metatron.data import cleaning, contract, eda
from metatron.model import evaluate, features, train


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path, encoding="utf-8-sig")


def _dump(obj: Any, path: Path) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class Run:
    cfg: Config
    dir: Path

    @classmethod
    def create(cls, cfg: Config, input_path: Path, run_id: str | None = None) -> Run:
        run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
        d = cfg.path(cfg.runs_dir) / run_id
        d.mkdir(parents=True, exist_ok=True)
        run = cls(cfg, d)
        dest = d / f"input{input_path.suffix.lower()}"
        shutil.copyfile(input_path, dest)
        _dump({
            "run_id": run_id,
            "input_file": str(input_path),
            "input_sha256": file_sha256(input_path),
            "seed": cfg.seed,
            "config": dict(cfg),
            "python": platform.python_version(),
            "sklearn": sklearn.__version__,
            "pandas": pd.__version__,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }, d / "run.json")
        return run

    def p(self, name: str) -> Path:
        return self.dir / name

    def read_json(self, name: str) -> Any:
        return _load(self.p(name))

    def write_json(self, name: str, obj: Any) -> None:
        _dump(obj, self.p(name))

    @property
    def target(self) -> str:
        return self.cfg["data"]["target"]

    # ---- Data Crew steps -------------------------------------------------------------
    def clean(self) -> dict:
        raw = read_table(next(self.dir.glob("input.*")))
        missing = [c for c in contract.DOMAIN if c not in raw.columns]
        if missing:
            raise ValueError(f"input file is missing required columns: {missing}")
        df, log = cleaning.clean(raw)
        df.to_parquet(self.p("clean.parquet"), index=False)
        self.write_json("cleaning_log.json", log)
        return log

    def clean_df(self) -> pd.DataFrame:
        return pd.read_parquet(self.p("clean.parquet"))

    def eda(self) -> dict:
        summary = eda.run_eda(self.clean_df(), self.target, self.p("eda"))
        self.write_json("eda/summary.json", summary)
        return summary

    def build_contract(self) -> dict:
        d = self.cfg["data"]
        c = contract.build_contract(self.clean_df(), self.target, d["min_rows"],
                                    d["target_rate_range"])
        self.write_json("data_contract.json", c)
        return c

    # ---- Gate --------------------------------------------------------------------------
    def validate(self, data_error: str | None = None) -> dict:
        if data_error:
            report = contract._report([{"check": "data_crew", "ok": False, "detail": data_error,
                                        "fix": "check that the file has all required columns"}])
        elif not self.p("clean.parquet").exists() or not self.p("data_contract.json").exists():
            report = contract._report([{"check": "artifacts_present", "ok": False,
                                        "detail": "clean.parquet or data_contract.json missing",
                                        "fix": "re-run the Data Crew"}])
        else:
            report = contract.validate(self.clean_df(), self.read_json("data_contract.json"))
        self.write_json("validation_report.json", report)
        return report

    # ---- Model Crew steps --------------------------------------------------------------
    def _split(self):
        m = self.cfg["model"]
        return features.split(self.clean_df(), self.target, m["test_size"], self.cfg.seed)

    def build_features(self) -> dict:
        m = self.cfg["model"]
        f = features.feature_frame(self.clean_df(), self.target, m["test_size"], self.cfg.seed)
        f.to_parquet(self.p("features.parquet"), index=False)
        return {"rows": len(f), "train": int((f.split == "train").sum()),
                "test": int((f.split == "test").sum()),
                "features": features.NUMERIC_FEATURES + features.CATEGORICAL_FEATURES}

    def train(self) -> dict:
        X_tr, _, y_tr, _ = self._split()
        out = {}
        for version, spec in self.cfg["model"]["versions"].items():
            train.train_version(spec["kind"], spec["params"], self.cfg.seed, X_tr, y_tr,
                                self.p(f"models/{version}"))
            out[version] = spec["kind"]
        return out

    def evaluate(self) -> dict:
        m = self.cfg["model"]
        X_tr, X_te, y_tr, y_te = self._split()
        metrics = {}
        for version in m["versions"]:
            pipe = train.load_model(self.p(f"models/{version}/model.joblib"))
            metrics[version] = evaluate.evaluate(pipe, X_tr, y_tr, X_te, y_te,
                                                 m["top_fraction"], m["cv_folds"], self.cfg.seed)
        best = evaluate.select_best(metrics, m["select_by"])
        result = {"versions": {v: {"kind": m["versions"][v]["kind"], **metrics[v]}
                               for v in metrics},
                  "selected": best, "selected_by": m["select_by"]}
        self.write_json("metrics.json", result)
        return result

    def finish(self, status: str, **extra: Any) -> None:
        info = self.read_json("run.json")
        info.update(status=status, finished_at=datetime.now().isoformat(timespec="seconds"),
                    **extra)
        self.write_json("run.json", info)
