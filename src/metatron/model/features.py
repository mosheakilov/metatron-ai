"""Feature engineering. Fitted inside the sklearn pipeline, so city medians come from train only."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder, StandardScaler

NUMERIC_FEATURES = ["days_on_market", "price_drops", "ask_ratio", "log_price", "rooms",
                    "area_sqm", "floor", "n_photos", "description_len", "previously_listed"]
CATEGORICAL_FEATURES = ["city", "source"]
INPUT_COLUMNS = ["city", "rooms", "area_sqm", "floor", "asking_price", "days_on_market",
                 "price_drops", "n_photos", "description_len", "source", "previously_listed"]


class AskRatio(BaseEstimator, TransformerMixin):
    """Adds ask_ratio = price per sqm / city median price per sqm (learned on fit) and log_price."""

    def fit(self, X: pd.DataFrame, y=None):
        ppsqm = X["asking_price"] / X["area_sqm"]
        self.city_median_ = ppsqm.groupby(X["city"]).median().to_dict()
        self.global_median_ = float(ppsqm.median())
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        X = X.copy()
        med = X["city"].map(self.city_median_).fillna(self.global_median_)
        X["ask_ratio"] = (X["asking_price"] / X["area_sqm"]) / med
        X["log_price"] = np.log(X["asking_price"])
        return X

    def set_output(self, *, transform=None):
        return self


def column_transformer(scale: bool) -> ColumnTransformer:
    num = StandardScaler() if scale else "passthrough"
    return ColumnTransformer([
        ("num", num, NUMERIC_FEATURES),
        ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
    ])


def split(df: pd.DataFrame, target: str, test_size: float, seed: int):
    X, y = df[INPUT_COLUMNS], df[target]
    return train_test_split(X, y, test_size=test_size, stratify=y, random_state=seed)


def feature_frame(df: pd.DataFrame, target: str, test_size: float, seed: int) -> pd.DataFrame:
    """Engineered features + split column, saved as features.parquet for inspection."""
    X_tr, X_te, y_tr, y_te = split(df, target, test_size, seed)
    ar = AskRatio().fit(X_tr)
    parts = []
    for name, X, y in [("train", X_tr, y_tr), ("test", X_te, y_te)]:
        f = ar.transform(X)[NUMERIC_FEATURES + CATEGORICAL_FEATURES]
        parts.append(f.assign(**{target: y.values, "split": name},
                              seller_id=df.loc[X.index, "seller_id"].values))
    return pd.concat(parts).reset_index(drop=True)
