import pandas as pd

from metatron.data.cleaning import clean, normalize_city, to_number
from metatron.data.contract import build_contract, validate
from metatron.data.generate import generate


def test_generator_is_reproducible():
    a = generate(300, seed=1)
    b = generate(300, seed=1)
    pd.testing.assert_frame_equal(a, b)


def test_generator_injects_dirt():
    df = generate(2000, seed=3)
    assert df["seller_id"].duplicated().any()
    assert df["n_photos"].isna().any()
    assert df["asking_price"].map(lambda v: isinstance(v, str)).any()
    assert df["city"].isin(['ת"א', "תל-אביב"]).any()


def test_parsers():
    assert to_number("₪1,850,000") == 1850000
    assert to_number('85 מ"ר') == 85
    assert normalize_city('ת"א') == "תל אביב"
    assert normalize_city("חולון ") == "חולון"


def test_clean_output_satisfies_contract():
    raw = generate(1500, seed=5)
    df, log = clean(raw)
    assert log["rows_out"] < log["rows_in"]
    assert not df["seller_id"].duplicated().any()
    contract = build_contract(df, "agreed_to_meeting", 500, [0.05, 0.6])
    report = validate(df, contract)
    assert report["valid"], report["errors"]


def test_contract_catches_broken_data():
    df, _ = clean(generate(1500, seed=5))
    contract = build_contract(df, "agreed_to_meeting", 500, [0.05, 0.6])
    broken = df.copy()
    broken.loc[0, "rooms"] = 40
    broken.loc[1, "source"] = "telegram"
    broken = pd.concat([broken, broken.iloc[[2]]])
    report = validate(broken, contract)
    failed = {e["check"] for e in report["errors"]}
    assert not report["valid"]
    assert {"rooms.max", "source.allowed", "primary_key_unique"} <= failed
    assert all(e["fix"] for e in report["errors"])


def test_contract_catches_missing_column_and_small_file():
    df, _ = clean(generate(1500, seed=5))
    contract = build_contract(df, "agreed_to_meeting", 500, [0.05, 0.6])
    report = validate(df.drop(columns=["floor"]).head(100), contract)
    failed = {e["check"] for e in report["errors"]}
    assert {"columns_present", "min_rows"} <= failed
