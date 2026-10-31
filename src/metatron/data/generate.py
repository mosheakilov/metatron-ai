"""Synthetic seller dataset for the lead-scoring model.

There are no real outreach outcomes yet, so the label comes from a documented probability
function plus noise. Data-quality problems are injected on purpose so the Data Crew has real work.

    python -m metatron.data.generate --config config.yaml

Ground truth (logit of P(agreed_to_meeting)):
    -2.6
    + 0.018 * min(days_on_market, 120)         # stale listings => more open to a broker
    + 0.45  * price_drops
    + 2.2   * (ask_ratio - 1)                  # overpriced vs. area median => harder to sell alone
    + 0.6   * previously_listed
    - 0.025 * n_photos                         # well-marketed sellers need us less
    - 0.002 * description_len / 10
    + source effect (facebook +0.35, komo +0.1, madlan 0, yad2 -0.1)
    + 0.9 if days_on_market > 60 and price_drops >= 2   # interaction (non-linear)
    + N(0, 0.5) noise
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from metatron.config import load_config

# City -> (median price per sqm in ILS, alternative spellings used for injected dirt)
CITIES: dict[str, tuple[int, list[str]]] = {
    "תל אביב": (62000, ['ת"א', "תל-אביב", "תל אביב יפו"]),
    "רמת גן": (41000, ['ר"ג', "רמת-גן"]),
    "גבעתיים": (44000, ["גבעתים"]),
    "חולון": (31000, ["חולון "]),
    "בת ים": (30000, ["בת-ים"]),
    "ראשון לציון": (30000, ['ראשל"צ', "ראשון"]),
    "פתח תקווה": (29000, ['פ"ת', "פתח תקוה"]),
    "הרצליה": (45000, ["הרצליא"]),
}
CITY_WEIGHTS = [0.24, 0.16, 0.08, 0.11, 0.08, 0.13, 0.12, 0.08]
SOURCES = ["yad2", "madlan", "facebook", "komo"]
SOURCE_WEIGHTS = [0.5, 0.2, 0.2, 0.1]
SOURCE_EFFECT = {"yad2": -0.1, "madlan": 0.0, "facebook": 0.35, "komo": 0.1}
STREETS = ["הרצל", "ביאליק", "ז'בוטינסקי", "סוקולוב", "ויצמן", "רוטשילד", "אחד העם", "הנביאים",
           "בן גוריון", "קק\"ל", "הגפן", "הזית", "ארלוזורוב", "שינקין", "דיזנגוף"]
FIRST = ["אבי", "דנה", "יוסי", "מירב", "רונית", "אלון", "שירה", "משה", "נועה", "עומר", "תמר",
         "איתי", "ליאת", "גיל", "רחל", "דוד", "מאיה", "יעל", "אורי", "חן"]
LAST = ["כהן", "לוי", "מזרחי", "פרץ", "ביטון", "אברהם", "פרידמן", "אזולאי", "שפירא", "גולן"]


def _clean_frame(n: int, rng: np.random.Generator) -> pd.DataFrame:
    city = rng.choice(list(CITIES), size=n, p=CITY_WEIGHTS)
    rooms = rng.choice([2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6],
                       size=n, p=[.07, .05, .18, .12, .22, .1, .14, .06, .06])
    area = np.clip(np.round(rooms * 24 + rng.normal(8, 10, n)), 35, 260)
    floor = np.clip(rng.poisson(3.2, n), 0, 30)
    ppsqm = np.array([CITIES[c][0] for c in city])
    fair = ppsqm * area * rng.lognormal(0, 0.08, n)
    ask_ratio = rng.lognormal(0.04, 0.09, n)
    asking_price = np.round(fair * ask_ratio / 1000) * 1000
    days = np.clip(rng.gamma(2.0, 24, n), 1, 400).round().astype(int)
    drops = np.minimum(rng.poisson(days / 55), 6)
    photos = np.clip(rng.poisson(9, n), 0, 30)
    desc_len = np.clip(rng.normal(320, 140, n), 0, 1500).round().astype(int)
    source = rng.choice(SOURCES, size=n, p=SOURCE_WEIGHTS)
    prev = (rng.random(n) < 0.22).astype(int)

    # True ask ratio vs. the area median (what the model must recover from price/area/city)
    true_ratio = asking_price / (ppsqm * area)
    logit = (
        -2.6
        + 0.018 * np.minimum(days, 120)
        + 0.45 * drops
        + 2.2 * (true_ratio - 1)
        + 0.6 * prev
        - 0.025 * photos
        - 0.002 * desc_len / 10
        + np.array([SOURCE_EFFECT[s] for s in source])
        + 0.9 * ((days > 60) & (drops >= 2))
        + rng.normal(0, 0.5, n)
    )
    target = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)

    names = [f"{rng.choice(FIRST)} {rng.choice(LAST)}" for _ in range(n)]
    addresses = [f"{rng.choice(STREETS)} {rng.integers(1, 120)}" for _ in range(n)]
    return pd.DataFrame({
        "seller_id": [f"S{i:05d}" for i in range(1, n + 1)],
        "seller_name": names,
        # Deliberately invalid prefix (000): synthetic sellers can never receive a real message.
        "phone": [f"+972-000-{i:06d}" for i in range(1, n + 1)],
        "city": city,
        "address": addresses,
        "rooms": rooms,
        "area_sqm": area.astype(int),
        "floor": floor,
        "asking_price": asking_price.astype(int),
        "days_on_market": days,
        "price_drops": drops,
        "n_photos": photos,
        "description_len": desc_len,
        "source": source,
        "previously_listed": prev,
        "agreed_to_meeting": target,
    })


def _inject_dirt(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    df = df.astype(object).copy()
    n = len(df)

    def pick(frac: float) -> np.ndarray:
        return rng.choice(n, size=int(n * frac), replace=False)

    for col, frac in [("n_photos", .05), ("floor", .04), ("description_len", .02),
                      ("area_sqm", .015), ("source", .01)]:
        df.loc[pick(frac), col] = None
    for i in pick(.12):  # inconsistent city spellings
        df.at[i, "city"] = rng.choice(CITIES[df.at[i, "city"]][1])
    for i in pick(.10):  # numbers stored as text
        df.at[i, "asking_price"] = f"₪{int(df.at[i, 'asking_price']):,}"
    for i in pick(.05):
        if df.at[i, "area_sqm"] is not None:
            df.at[i, "area_sqm"] = f'{df.at[i, "area_sqm"]} מ"ר'
    for i in pick(.005):  # outliers: extra zero typed into the price
        p = df.at[i, "asking_price"]
        if isinstance(p, int):
            df.at[i, "asking_price"] = p * 10
    dups = df.iloc[pick(.03)]  # ~3% duplicate rows (same seller exported twice)
    df = pd.concat([df, dups], ignore_index=True)
    return df.sample(frac=1, random_state=int(rng.integers(1 << 31))).reset_index(drop=True)


def generate(n_rows: int, seed: int, dirty: bool = True) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = _clean_frame(n_rows, rng)
    return _inject_dirt(df, rng) if dirty else df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--clean", action="store_true", help="skip injected data-quality problems")
    ap.add_argument("--n-rows", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--no-label", action="store_true",
                    help="drop the target: new sellers to score, not to train on")
    args = ap.parse_args()
    cfg = load_config(args.config)
    out = cfg.path(args.out or cfg.data.raw_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    seed = cfg.seed if args.seed is None else args.seed
    df = generate(args.n_rows or cfg.data.n_rows, seed, dirty=not args.clean)
    if args.no_label:
        df = df.drop(columns=[cfg.data.target])
    df.to_csv(out, index=False, encoding="utf-8-sig")
    rate = f"  (target rate {df[cfg.data.target].mean():.3f})" if cfg.data.target in df else ""
    print(f"wrote {len(df)} rows -> {out}{rate}")


if __name__ == "__main__":
    main()
