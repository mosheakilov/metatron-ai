"""Deterministic EDA: statistics and charts the EDA Analyst agent interprets."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

NUMERIC = ["rooms", "area_sqm", "floor", "asking_price", "days_on_market", "price_drops",
           "n_photos", "description_len", "previously_listed"]


def _rate_by(df: pd.DataFrame, col: str, target: str) -> dict:
    g = df.groupby(col)[target].agg(["mean", "count"]).round(4)
    return {str(k): {"rate": float(r["mean"]), "n": int(r["count"])} for k, r in g.iterrows()}


def run_eda(df: pd.DataFrame, target: str, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    ppsqm = df["asking_price"] / df["area_sqm"]
    ask_ratio = ppsqm / ppsqm.groupby(df["city"]).transform("median")

    summary = {
        "rows": int(len(df)),
        "target_rate": round(float(df[target].mean()), 4),
        "describe": df[NUMERIC].describe().round(2).to_dict(),
        "corr_with_target": df[NUMERIC + [target]].corr()[target].drop(target)
                              .round(3).sort_values(ascending=False).to_dict(),
        "rate_by_city": _rate_by(df, "city", target),
        "rate_by_source": _rate_by(df, "source", target),
        "rate_by_price_drops": _rate_by(df, "price_drops", target),
        "rate_by_ask_ratio_bin": _rate_by(
            df.assign(b=pd.cut(ask_ratio, [0, .95, 1.0, 1.05, 1.1, 1.2, np.inf]).astype(str)),
            "b", target),
        "charts": [],
    }

    def save(fig, name: str) -> None:
        fig.tight_layout()
        fig.savefig(out_dir / name, dpi=110)
        plt.close(fig)
        summary["charts"].append(name)

    fig, ax = plt.subplots(figsize=(6, 3.5))
    for v, label in [(0, "declined"), (1, "agreed")]:
        ax.hist(df.loc[df[target] == v, "days_on_market"], bins=40, alpha=.6, label=label)
    ax.set(title="Days on market by outcome", xlabel="days", ylabel="sellers")
    ax.legend()
    save(fig, "days_on_market.png")

    fig, ax = plt.subplots(figsize=(6, 3.5))
    r = df.groupby("price_drops")[target].mean()
    ax.bar(r.index.astype(str), r.values, color="#1f4e8c")
    ax.set(title="Meeting rate by number of price drops", xlabel="price drops", ylabel="rate")
    save(fig, "rate_by_price_drops.png")

    fig, ax = plt.subplots(figsize=(6, 3.5))
    bins = pd.qcut(ask_ratio, 10, duplicates="drop")
    r = df.groupby(bins, observed=True)[target].mean()
    ax.plot([i.mid for i in r.index], r.values, marker="o", color="#c8a24a")
    ax.set(title="Meeting rate vs. asking price / city median", xlabel="ratio", ylabel="rate")
    save(fig, "rate_by_ask_ratio.png")

    fig, ax = plt.subplots(figsize=(6, 3.5))
    r = df.groupby("source")[target].mean().sort_values()
    ax.barh(r.index, r.values, color="#2e8b6e")
    ax.set(title="Meeting rate by listing source", xlabel="rate")
    save(fig, "rate_by_source.png")
    return summary
