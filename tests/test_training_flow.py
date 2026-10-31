import json

import pandas as pd
import pytest

from metatron.config import load_config
from metatron.data.generate import generate
from metatron.flows.training_flow import run_training
from metatron.model.evaluate import precision_at, select_best


@pytest.fixture()
def cfg(tmp_path):
    c = load_config()
    c["runs_dir"] = str(tmp_path / "runs")
    c["model"]["cv_folds"] = 3
    c["model"]["versions"]["v2"]["params"]["n_estimators"] = 60
    return c


def _csv(tmp_path, df, name="sellers.csv"):
    p = tmp_path / name
    df.to_csv(p, index=False, encoding="utf-8-sig")
    return p


def test_flow_trains_and_is_reproducible(cfg, tmp_path):
    path = _csv(tmp_path, generate(1500, seed=11))
    s1 = run_training(path, cfg, run_id="a")
    run_training(path, cfg, run_id="b")
    assert s1.status == "trained" and s1.mode == "offline"
    run = tmp_path / "runs" / "a"
    for f in ["clean.parquet", "cleaning_log.json", "eda/summary.json", "insights.md",
              "data_contract.json", "validation_report.json", "features.parquet",
              "models/v1/model.joblib", "models/v2/model.joblib", "metrics.json",
              "MODEL_CARD.md", "run.json"]:
        assert (run / f).exists(), f
    m1 = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
    m2 = json.loads((tmp_path / "runs" / "b" / "metrics.json").read_text(encoding="utf-8"))
    assert m1 == m2  # same config + same data => same metrics
    assert m1["versions"]["v1"]["roc_auc"] > 0.65
    info = json.loads((run / "run.json").read_text(encoding="utf-8"))
    assert len(info["input_sha256"]) == 64 and info["status"] == "trained"
    assert "SYNTHETIC" in (run / "MODEL_CARD.md").read_text(encoding="utf-8").upper()


def test_flow_stops_on_broken_file(cfg, tmp_path):
    df = generate(1500, seed=11)
    df["agreed_to_meeting"] = 0           # broken labels: target balance out of range
    state = run_training(_csv(tmp_path, df), cfg, run_id="broken")
    run = tmp_path / "runs" / "broken"
    assert state.status == "stopped"
    assert any(e["check"] == "target_balance" for e in state.errors)
    assert (run / "validation_report.json").exists()
    assert not (run / "models").exists()   # nothing was trained
    assert not (tmp_path / "runs" / "LATEST").exists()


def test_flow_stops_on_missing_column(cfg, tmp_path):
    df = generate(1500, seed=11).drop(columns=["days_on_market"])
    state = run_training(_csv(tmp_path, df), cfg, run_id="nocol")
    assert state.status == "stopped"
    assert state.errors[0]["check"] == "data_crew"
    assert "days_on_market" in state.errors[0]["detail"]


def test_precision_at_and_selection():
    y = pd.Series([1, 0, 1, 0, 0, 0, 0, 0, 0, 1]).values
    s = pd.Series([.9, .8, .7, .1, .2, .3, .1, .1, .1, .05]).values
    assert precision_at(y, s, 0.2) == 0.5
    assert select_best({"v1": {"pr_auc": .5}, "v2": {"pr_auc": .5}}, "pr_auc") == "v1"
    assert select_best({"v1": {"pr_auc": .5}, "v2": {"pr_auc": .6}}, "pr_auc") == "v2"
