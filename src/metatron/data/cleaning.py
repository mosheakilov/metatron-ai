"""Deterministic cleaning steps. The Data Cleaner agent calls these as tools; it never edits data itself."""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

CITY_ALIASES = {
    'ת"א': "תל אביב", "תל-אביב": "תל אביב", "תל אביב יפו": "תל אביב",
    'ר"ג': "רמת גן", "רמת-גן": "רמת גן",
    "גבעתים": "גבעתיים",
    "בת-ים": "בת ים",
    'ראשל"צ': "ראשון לציון", "ראשון": "ראשון לציון",
    'פ"ת': "פתח תקווה", "פתח תקוה": "פתח תקווה",
    "הרצליא": "הרצליה",
}
NUMERIC = ["rooms", "area_sqm", "floor", "asking_price", "days_on_market", "price_drops",
           "n_photos", "description_len", "previously_listed", "agreed_to_meeting"]
INT_COLS = ["area_sqm", "floor", "asking_price", "days_on_market", "price_drops", "n_photos",
            "description_len", "previously_listed", "agreed_to_meeting"]
MEDIAN_IMPUTE = ["n_photos", "floor", "description_len"]
REQUIRED = ["seller_id", "city", "rooms", "area_sqm", "asking_price", "source"]
OUTLIER_FACTOR = 4.0  # price per sqm more than 4x the city median => suspected typo


def to_number(value: Any) -> float:
    """'₪1,850,000' -> 1850000.0 ; '85 מ"ר' -> 85.0 ; None -> nan"""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    if isinstance(value, int | float | np.number):
        return float(value)
    digits = re.sub(r"[^\d.]", "", str(value))
    return float(digits) if digits else np.nan


def normalize_city(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    v = value.strip()
    return CITY_ALIASES.get(v, v)


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Return (clean frame, cleaning log). Each step records how many rows it touched."""
    log: dict[str, Any] = {"rows_in": int(len(df)), "steps": []}

    def step(name: str, **counts: Any) -> None:
        log["steps"].append({"step": name, **{k: int(v) for k, v in counts.items()}})

    df = df.copy()
    before = len(df)
    df = df.drop_duplicates()
    exact = before - len(df)
    before = len(df)
    df = df.drop_duplicates(subset="seller_id", keep="first")
    step("remove_duplicates", exact=exact, same_seller_id=before - len(df))

    text_numbers = 0
    for col in NUMERIC:
        if col in df:
            is_text = df[col].map(
                lambda v: isinstance(v, str) and not re.fullmatch(r"-?\d+(\.\d+)?", v.strip()))
            text_numbers += int(is_text.sum())
            df[col] = df[col].map(to_number)
    step("parse_numbers", text_values_converted=text_numbers)

    raw_city = df["city"].copy()
    df["city"] = df["city"].map(normalize_city)
    step("normalize_city", values_changed=(raw_city != df["city"]).sum())

    city_median = (df["asking_price"] / df["area_sqm"]).groupby(df["city"]).transform("median")
    ppsqm = df["asking_price"] / df["area_sqm"]
    typo = ppsqm > OUTLIER_FACTOR * city_median
    df.loc[typo, "asking_price"] = df.loc[typo, "asking_price"] / 10
    still = (df["asking_price"] / df["area_sqm"]) > OUTLIER_FACTOR * city_median
    df = df[~still]
    step("fix_price_outliers", divided_by_10=typo.sum(), dropped=still.sum())

    missing_required = df[REQUIRED].isna().any(axis=1)
    df = df[~missing_required]
    step("drop_missing_required", dropped=missing_required.sum())

    imputed = {}
    for col in MEDIAN_IMPUTE:
        if col not in df:
            continue
        n_missing = int(df[col].isna().sum())
        df[col] = df[col].fillna(df[col].median())
        imputed[col] = n_missing
    step("impute_median", **imputed)

    for col in [c for c in INT_COLS if c in df]:
        df[col] = df[col].round().astype(np.int64)
    df["rooms"] = df["rooms"].astype(float)
    df = df.sort_values("seller_id").reset_index(drop=True)
    log["rows_out"] = int(len(df))
    return df, log
