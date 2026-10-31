"""Metrics: ROC-AUC, PR-AUC, Precision@top-fraction, Brier, cross-validation and calibration."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_score


def precision_at(y_true: np.ndarray, scores: np.ndarray, fraction: float) -> float:
    """Of the top `fraction` sellers by score, how many agreed to a meeting."""
    k = max(1, int(round(len(scores) * fraction)))
    top = np.argsort(-scores, kind="stable")[:k]
    return float(np.asarray(y_true)[top].mean())


def calibration(y_true: np.ndarray, scores: np.ndarray, bins: int = 10) -> list[dict]:
    df = pd.DataFrame({"y": np.asarray(y_true), "p": scores})
    df["bin"] = pd.qcut(df["p"], bins, duplicates="drop")
    g = df.groupby("bin", observed=True).agg(predicted=("p", "mean"), actual=("y", "mean"),
                                              n=("y", "size"))
    return [{"predicted": round(float(r.predicted), 4), "actual": round(float(r.actual), 4),
             "n": int(r.n)} for r in g.itertuples()]


def evaluate(pipe, X_tr, y_tr, X_te, y_te, top_fraction: float, cv_folds: int,
             seed: int) -> dict:
    scores = pipe.predict_proba(X_te)[:, 1]
    cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=seed)
    cv_auc = cross_val_score(clone(pipe), X_tr, y_tr, cv=cv, scoring="roc_auc")
    base_rate = float(np.mean(y_te))
    p_at = precision_at(y_te, scores, top_fraction)
    return {
        "roc_auc": round(float(roc_auc_score(y_te, scores)), 4),
        "pr_auc": round(float(average_precision_score(y_te, scores)), 4),
        f"precision_at_{int(top_fraction * 100)}": round(p_at, 4),
        "lift_at_top": round(p_at / base_rate, 2) if base_rate else None,
        "brier": round(float(brier_score_loss(y_te, scores)), 4),
        "cv_roc_auc_mean": round(float(cv_auc.mean()), 4),
        "cv_roc_auc_std": round(float(cv_auc.std()), 4),
        "base_rate": round(base_rate, 4),
        "n_test": int(len(y_te)),
        "calibration": calibration(y_te, scores),
    }


def select_best(metrics: dict[str, dict], by: str) -> str:
    return max(metrics, key=lambda v: (metrics[v][by], -int(v.lstrip("v"))))
