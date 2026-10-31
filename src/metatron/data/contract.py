"""JSON data contract: built from clean data, validated before training.

The contract itself is checked against CONTRACT_SCHEMA (jsonschema), then every rule in it is
checked against the data. Any failure => the TrainingFlow stops and writes validation_report.json.
"""

from __future__ import annotations

from typing import Any

import jsonschema
import pandas as pd

CONTRACT_SCHEMA = {
    "type": "object",
    "required": ["version", "target", "primary_key", "min_rows", "target_rate_range", "columns"],
    "properties": {
        "version": {"type": "string"},
        "target": {"type": "string"},
        "primary_key": {"type": "string"},
        "min_rows": {"type": "integer", "minimum": 1},
        "target_rate_range": {"type": "array", "items": {"type": "number"},
                              "minItems": 2, "maxItems": 2},
        "columns": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["dtype", "nullable"],
                "properties": {
                    "dtype": {"enum": ["int", "float", "string"]},
                    "nullable": {"type": "boolean"},
                    "min": {"type": "number"},
                    "max": {"type": "number"},
                    "allowed": {"type": "array"},
                    "description": {"type": "string"},
                },
            },
        },
    },
}

# Domain rules (not learned from the data: a contract that only mirrors the data proves nothing).
DOMAIN = {
    "seller_id":         {"dtype": "string", "nullable": False, "description": "unique seller key"},
    "seller_name":       {"dtype": "string", "nullable": False},
    "phone":             {"dtype": "string", "nullable": False},
    "city":              {"dtype": "string", "nullable": False},
    "address":           {"dtype": "string", "nullable": False},
    "rooms":             {"dtype": "float", "nullable": False, "min": 1, "max": 12},
    "area_sqm":          {"dtype": "int", "nullable": False, "min": 20, "max": 600},
    "floor":             {"dtype": "int", "nullable": False, "min": 0, "max": 60},
    "asking_price":      {"dtype": "int", "nullable": False, "min": 300_000, "max": 40_000_000},
    "days_on_market":    {"dtype": "int", "nullable": False, "min": 0, "max": 1000},
    "price_drops":       {"dtype": "int", "nullable": False, "min": 0, "max": 20},
    "n_photos":          {"dtype": "int", "nullable": False, "min": 0, "max": 100},
    "description_len":   {"dtype": "int", "nullable": False, "min": 0, "max": 5000},
    "source":            {"dtype": "string", "nullable": False,
                          "allowed": ["yad2", "madlan", "facebook", "komo"]},
    "previously_listed": {"dtype": "int", "nullable": False, "allowed": [0, 1]},
    "agreed_to_meeting": {"dtype": "int", "nullable": False, "allowed": [0, 1],
                          "description": "target: agreed to a recruitment meeting within 14 days"},
}


def build_contract(df: pd.DataFrame, target: str, min_rows: int,
                   target_rate_range: list[float]) -> dict:
    """Domain rules + the city vocabulary observed after cleaning."""
    columns = {k: dict(v) for k, v in DOMAIN.items()}
    columns["city"]["allowed"] = sorted(df["city"].dropna().unique().tolist())
    return {
        "version": "1.0",
        "target": target,
        "primary_key": "seller_id",
        "min_rows": int(min_rows),
        "target_rate_range": [float(x) for x in target_rate_range],
        "columns": columns,
    }


def _dtype_ok(s: pd.Series, dtype: str) -> bool:
    if dtype == "int":
        return pd.api.types.is_integer_dtype(s)
    if dtype == "float":
        return pd.api.types.is_numeric_dtype(s)
    return s.dropna().map(lambda v: isinstance(v, str)).all()


def validate(df: pd.DataFrame, contract: dict) -> dict:
    """Return a report: {"valid": bool, "checks": [...], "errors": [...]}."""
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str = "", fix: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail, "fix": fix})

    try:
        jsonschema.validate(contract, CONTRACT_SCHEMA)
        check("contract_schema", True)
    except jsonschema.ValidationError as e:
        check("contract_schema", False, e.message, "fix data_contract.json")
        return _report(checks)

    cols = contract["columns"]
    missing = [c for c in cols if c not in df.columns]
    check("columns_present", not missing, f"missing: {missing}" if missing else "",
          "add the missing columns to the input file")
    extra = [c for c in df.columns if c not in cols]
    check("no_unexpected_columns", not extra, f"unexpected: {extra}" if extra else "",
          "remove the columns or add them to the contract")

    for name, rule in cols.items():
        if name not in df.columns:
            continue
        s = df[name]
        if not rule["nullable"]:
            n = int(s.isna().sum())
            check(f"{name}.not_null", n == 0, f"{n} nulls" if n else "",
                  "impute or drop rows in the cleaning step")
        ok = _dtype_ok(s, rule["dtype"])
        check(f"{name}.dtype", ok, "" if ok else f"expected {rule['dtype']}, got {s.dtype}",
              "convert the column type in the cleaning step")
        if not ok:
            continue
        if "min" in rule:
            n = int((s < rule["min"]).sum())
            check(f"{name}.min", n == 0, f"{n} values < {rule['min']}" if n else "",
                  "fix or drop out-of-range rows")
        if "max" in rule:
            n = int((s > rule["max"]).sum())
            check(f"{name}.max", n == 0, f"{n} values > {rule['max']}" if n else "",
                  "fix or drop out-of-range rows")
        if "allowed" in rule:
            bad = sorted(set(s.dropna().unique()) - set(rule["allowed"]), key=str)
            check(f"{name}.allowed", not bad, f"not allowed: {bad[:10]}" if bad else "",
                  "normalize values or extend the contract vocabulary")

    pk = contract["primary_key"]
    if pk in df.columns:
        dups = int(df[pk].duplicated().sum())
        check("primary_key_unique", dups == 0, f"{dups} duplicate {pk}" if dups else "",
              "remove duplicates in the cleaning step")
    check("min_rows", len(df) >= contract["min_rows"],
          f"{len(df)} rows < {contract['min_rows']}" if len(df) < contract["min_rows"] else "",
          "load a bigger file")
    t = contract["target"]
    if t in df.columns and pd.api.types.is_numeric_dtype(df[t]):
        rate = float(df[t].mean())
        lo, hi = contract["target_rate_range"]
        check("target_balance", lo <= rate <= hi,
              f"target rate {rate:.3f} outside [{lo}, {hi}]" if not lo <= rate <= hi else "",
              "check the labels: the outcome column looks wrong")
    return _report(checks)


def _report(checks: list[dict]) -> dict:
    errors = [c for c in checks if not c["ok"]]
    return {"valid": not errors, "n_checks": len(checks), "n_failed": len(errors),
            "errors": errors, "checks": checks}
