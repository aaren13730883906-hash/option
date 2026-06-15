#!/usr/bin/env python3
"""Fill missing option OHLCV rows with iFinD QuantAPI.

Token handling:
  - Prefer IFIND_ACCESS_TOKEN
  - Else use IFIND_REFRESH_TOKEN
  - Else read data/ifind_refresh_token.txt

Output:
  - data/ifind_option_ohlc_cache.csv
  - data/kcb_option_daily_ifind_filled.csv
  - data/ifind_fill_report.csv
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
INPUT_CSV = DATA_DIR / "kcb_option_daily.csv"
CACHE_CSV = DATA_DIR / "ifind_option_ohlc_cache.csv"
OUTPUT_CSV = DATA_DIR / "kcb_option_daily_ifind_filled.csv"
REPORT_CSV = DATA_DIR / "ifind_fill_report.csv"
REFRESH_TOKEN_FILE = DATA_DIR / "ifind_refresh_token.txt"

GET_ACCESS_TOKEN_URL = "https://quantapi.51ifind.com/api/v1/get_access_token"
HISTORY_URL = "https://quantapi.51ifind.com/api/v1/cmd_history_quotation"
INDICATORS = "open,high,low,close,volume,amount,changeRatio"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=INPUT_CSV)
    parser.add_argument("--output", type=Path, default=OUTPUT_CSV)
    parser.add_argument("--cache", type=Path, default=CACHE_CSV)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--limit-contracts", type=int, default=None)
    parser.add_argument("--code-format", choices=["auto", "option", "contract"], default="auto")
    parser.add_argument("--refresh-cache", action="store_true")
    return parser.parse_args()


def load_secret(name: str, fallback_file: Path | None = None) -> str | None:
    value = os.environ.get(name)
    if value:
        return value.strip()
    if fallback_file and fallback_file.exists():
        return fallback_file.read_text(encoding="utf-8").strip()
    return None


def get_access_token() -> str:
    access_token = load_secret("IFIND_ACCESS_TOKEN")
    if access_token:
        return access_token

    refresh_token = load_secret("IFIND_REFRESH_TOKEN", REFRESH_TOKEN_FILE)
    if not refresh_token:
        raise RuntimeError(
            "No iFinD token found. Set IFIND_ACCESS_TOKEN, IFIND_REFRESH_TOKEN, "
            "or write the refresh token to data/ifind_refresh_token.txt."
        )

    headers = {"Content-Type": "application/json", "refresh_token": refresh_token}
    response = requests.post(GET_ACCESS_TOKEN_URL, headers=headers, timeout=30)
    response.raise_for_status()
    payload = response.json()
    try:
        return payload["data"]["access_token"]
    except KeyError as exc:
        raise RuntimeError(f"Failed to get access_token: {payload}") from exc


def normalize_tables(payload: dict[str, Any]) -> pd.DataFrame:
    if payload.get("errorcode") not in (0, None):
        raise RuntimeError(f"iFinD error {payload.get('errorcode')}: {payload.get('errmsg')}")

    tables = payload.get("tables") or payload.get("data", {}).get("tables") or []
    frames: list[pd.DataFrame] = []
    for table in tables:
        code = table.get("thscode") or table.get("code") or table.get("time")
        data = table.get("table") or table.get("data") or {}
        if isinstance(data, list):
            df = pd.DataFrame(data)
        elif isinstance(data, dict):
            df = pd.DataFrame(data)
        else:
            continue
        if df.empty:
            continue
        if "thscode" not in df.columns and code:
            df["thscode"] = code
        frames.append(df)

    if frames:
        return pd.concat(frames, ignore_index=True)

    # Some API responses can be directly tabular under data/tables after json_normalize.
    if "tables" in payload:
        flat = pd.json_normalize(payload["tables"])
        return flat
    return pd.DataFrame()


def date_col(df: pd.DataFrame) -> str | None:
    for col in ["time", "date", "tradeDate", "trade_date"]:
        if col in df.columns:
            return col
    return None


def request_history(headers: dict[str, str], code: str, start: str, end: str) -> pd.DataFrame:
    body = {
        "codes": code,
        "indicators": INDICATORS,
        "startdate": start,
        "enddate": end,
        "functionpara": {"Fill": "Blank"},
    }
    response = requests.post(HISTORY_URL, json=body, headers=headers, timeout=60)
    response.raise_for_status()
    payload = response.json()
    df = normalize_tables(payload)
    if df.empty:
        return df
    df["ifind_code"] = code
    return df


def candidate_codes(option_code: str, contract_id: str, mode: str) -> list[str]:
    option_code = str(option_code).zfill(8)
    contract_id = str(contract_id)
    if mode == "option":
        return [f"{option_code}.SH", option_code]
    if mode == "contract":
        return [f"{contract_id}.SH", contract_id]
    return [f"{option_code}.SH", f"{contract_id}.SH", option_code, contract_id]


def standardize_history(df: pd.DataFrame, option_code: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    aliases = {
        "open": "option_open_ifind",
        "high": "option_high_ifind",
        "low": "option_low_ifind",
        "close": "option_close_ifind",
        "volume": "option_volume_ifind",
        "amount": "option_amount_ifind",
        "changeRatio": "option_return_pct_ifind",
    }
    out = df.rename(columns={k: v for k, v in aliases.items() if k in df.columns}).copy()
    dc = date_col(out)
    if dc is None:
        return pd.DataFrame()
    out["trade_date"] = pd.to_datetime(out[dc], errors="coerce").dt.strftime("%Y-%m-%d")
    out["option_code"] = str(option_code).zfill(8)
    keep = ["trade_date", "option_code", "ifind_code"] + [v for v in aliases.values() if v in out.columns]
    out = out[keep].dropna(subset=["trade_date"]).drop_duplicates(["trade_date", "option_code"], keep="last")
    for col in keep:
        if col not in ["trade_date", "option_code", "ifind_code"]:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "option_return_pct_ifind" in out.columns:
        out["option_return_ifind"] = out["option_return_pct_ifind"] / 100
    return out


def main() -> None:
    args = parse_args()
    df = pd.read_csv(args.input, dtype={"option_code": str, "contract_id": str})
    missing = df[df["option_close"].isna()].copy()
    if missing.empty:
        print("No missing option OHLC rows.")
        df.to_csv(args.output, index=False)
        return

    cache = pd.DataFrame()
    if args.cache.exists() and not args.refresh_cache:
        cache = pd.read_csv(args.cache, dtype={"option_code": str})

    cached_codes = set(cache["option_code"].astype(str)) if not cache.empty else set()
    groups = missing.groupby(["option_code", "contract_id"], sort=True)["trade_date"].agg(["min", "max"]).reset_index()
    groups = groups[~groups["option_code"].astype(str).isin(cached_codes)]
    if args.limit_contracts:
        groups = groups.head(args.limit_contracts)

    token = get_access_token()
    headers = {"Content-Type": "application/json", "access_token": token}
    fetched: list[pd.DataFrame] = []
    report: list[dict[str, Any]] = []

    for idx, row in groups.reset_index(drop=True).iterrows():
        option_code = str(row["option_code"]).zfill(8)
        contract_id = str(row["contract_id"])
        start = str(row["min"])
        end = str(row["max"])
        print(f"[ifind] {idx + 1}/{len(groups)} {option_code} {contract_id} {start} {end}", flush=True)
        hit = pd.DataFrame()
        errors: list[str] = []
        for code in candidate_codes(option_code, contract_id, args.code_format):
            try:
                raw = request_history(headers, code, start, end)
                std = standardize_history(raw, option_code)
                if not std.empty:
                    hit = std
                    break
            except Exception as exc:  # noqa: BLE001 - try next code format.
                errors.append(f"{code}: {exc}")
        if not hit.empty:
            fetched.append(hit)
            report.append({"option_code": option_code, "contract_id": contract_id, "rows": len(hit), "status": "ok"})
        else:
            report.append(
                {
                    "option_code": option_code,
                    "contract_id": contract_id,
                    "rows": 0,
                    "status": "empty",
                    "error": " | ".join(errors),
                }
            )
        time.sleep(args.sleep)

    if fetched:
        new_cache = pd.concat([cache, *fetched], ignore_index=True) if not cache.empty else pd.concat(fetched, ignore_index=True)
    else:
        new_cache = cache
    if not new_cache.empty:
        new_cache = new_cache.drop_duplicates(["trade_date", "option_code"], keep="last")
        new_cache.to_csv(args.cache, index=False)

    if report:
        report_df = pd.DataFrame(report)
        if REPORT_CSV.exists() and not args.refresh_cache:
            old_report = pd.read_csv(REPORT_CSV, dtype={"option_code": str})
            report_df = pd.concat([old_report, report_df], ignore_index=True)
            report_df = report_df.drop_duplicates(["option_code", "contract_id"], keep="last")
        report_df.to_csv(REPORT_CSV, index=False)

    if new_cache.empty:
        print("No iFinD rows fetched.")
        df.to_csv(args.output, index=False)
        return

    fill = new_cache
    merged = df.merge(fill, on=["trade_date", "option_code"], how="left")
    field_pairs = [
        ("option_open", "option_open_ifind"),
        ("option_high", "option_high_ifind"),
        ("option_low", "option_low_ifind"),
        ("option_close", "option_close_ifind"),
        ("option_volume", "option_volume_ifind"),
        ("option_return", "option_return_ifind"),
    ]
    for base, fill_col in field_pairs:
        if fill_col in merged.columns:
            merged[base] = merged[base].combine_first(merged[fill_col])

    merged["ohlc_source"] = "akshare"
    has_ifind = merged["option_close_ifind"].notna() if "option_close_ifind" in merged.columns else False
    merged.loc[has_ifind, "ohlc_source"] = "ifind"
    helper_cols = [c for c in merged.columns if c.endswith("_ifind") or c == "ifind_code"]
    merged.drop(columns=helper_cols, inplace=True, errors="ignore")
    merged.to_csv(args.output, index=False)
    print(
        {
            "input_missing_option_close": int(df["option_close"].isna().sum()),
            "output_missing_option_close": int(merged["option_close"].isna().sum()),
            "filled_rows": int(df["option_close"].isna().sum() - merged["option_close"].isna().sum()),
            "output": str(args.output),
        },
        flush=True,
    )


if __name__ == "__main__":
    main()
