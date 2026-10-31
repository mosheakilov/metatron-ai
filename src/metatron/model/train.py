"""Fixed training code. The Model Trainer agent runs it as a tool; the LLM never writes training code."""

from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from metatron.model.features import AskRatio, column_transformer

KINDS = {
    "logistic_regression": (LogisticRegression, True),
    "gradient_boosting": (GradientBoostingClassifier, False),
}


def build_pipeline(kind: str, params: dict, seed: int) -> Pipeline:
    cls, scale = KINDS[kind]
    return Pipeline([
        ("ask_ratio", AskRatio()),
        ("columns", column_transformer(scale=scale)),
        ("model", cls(**params, random_state=seed)),
    ])


def train_version(kind: str, params: dict, seed: int, X: pd.DataFrame, y: pd.Series,
                  out_dir: Path) -> Pipeline:
    pipe = build_pipeline(kind, params, seed).fit(X, y)
    out_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, out_dir / "model.joblib")
    return pipe


def load_model(path: Path) -> Pipeline:
    return joblib.load(path)
