#!/usr/bin/env python3
"""Extend v1.2 ETF and option inputs through a requested end date.

The extension uses iFinD for ETF/option quotations and exchange risk
indicators for historical option codes and Greeks. Existing rows and raw
caches are preserved; only later dates are appended.
"""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import pandas as pd
import requests

import backtest_v02_recent_intraday as bt
import build_cyb_option_signal_data as cyb
import build_kcb_option_daily as kcb


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ETF_CACHE = DATA / "etf_intraday_ifind"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2026-05-26")
    parser.add_argument("--end", default="2026-06-30")
    parser.add_argument("--sleep", type=float, default=0.12)
    return parser.parse_args()


def fetch_etf_1m(
    code: str,
    trade_date: str,
    headers: dict[str, str],
    sleep: float,
) -> pd.DataFrame:
    ETF_CACHE.mkdir(parents=True, exist_ok=True)
    cache = ETF_CACHE / f"{trade_date}_{code}_1m.csv"
    if cache.exists():
        return pd.read_csv(cache, parse_dates=["datetime"])
    body = {
        "codes": bt.market_symbol(code),
        "indicators": bt.INDICATORS,
        "starttime": f"{trade_date} 09:30:00",
        "endtime": f"{trade_date} 15:00:00",
        "functionpara": {"Fill": "Blank"},
    }
    response = requests.post(
        bt.HIGH_FREQUENCY_URL,
        json=body,
        headers=headers,
        timeout=90,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errorcode") == -4211:
        return pd.DataFrame()
    raw = bt.normalize_tables(payload)
    if raw.empty:
        return pd.DataFrame()
    raw["datetime"] = pd.to_datetime(raw["time"], errors="coerce")
    keep = ["datetime", "open", "high", "low", "close", "volume", "amount"]
    out = raw[keep].copy()
    for column in keep[1:]:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.dropna(subset=["datetime", "close"])
    out = out.drop_duplicates("datetime").sort_values("datetime")
    out.to_csv(cache, index=False)
    time.sleep(sleep)
    return out


def aggregate_daily(frames: list[pd.DataFrame], code: str) -> pd.DataFrame:
    rows = []
    for bars in frames:
        if bars.empty:
            continue
        rows.append(
            {
                "underlying_code": code,
                "underlying_name": "科创50ETF" if code == "588000" else "易方达创业板ETF",
                "etf_open": bars.iloc[0]["open"],
                "etf_high": bars["high"].max(),
                "etf_low": bars["low"].min(),
                "etf_close": bars.iloc[-1]["close"],
                "etf_volume": bars["volume"].sum(),
                "etf_amount": bars["amount"].sum(),
                "etf_bar_count": int(bars["close"].notna().sum()),
                "trade_date": bars.iloc[0]["datetime"].strftime("%Y-%m-%d"),
            }
        )
    return pd.DataFrame(rows)


def append_etf_daily(path: Path, extension: pd.DataFrame) -> pd.DataFrame:
    old = pd.read_csv(path, dtype={"underlying_code": str})
    combined = pd.concat([old, extension], ignore_index=True, sort=False)
    combined = combined.drop_duplicates(
        ["underlying_code", "trade_date"],
        keep="last",
    ).sort_values(["underlying_code", "trade_date"])
    combined["etf_return"] = combined.groupby("underlying_code")["etf_close"].pct_change()
    for window in [20, 30, 60, 120]:
        combined[f"hv_{window}d"] = (
            combined.groupby("underlying_code")["etf_return"]
            .rolling(window)
            .std()
            .reset_index(level=0, drop=True)
            * math.sqrt(252)
        )
    combined.to_csv(path, index=False)
    return combined


def expiry_date(expiry_ym: object) -> pd.Timestamp:
    value = int(expiry_ym)
    return cyb.fourth_wednesday(value // 100, value % 100)


def eligible_rows(rows: pd.DataFrame) -> pd.DataFrame:
    out = rows.copy()
    out["expiry_date"] = out["expiry_ym"].map(expiry_date)
    out["dte"] = (
        out["expiry_date"] - pd.to_datetime(out["trade_date"])
    ).dt.days
    return out[
        out["dte"].between(10, 35)
        & out["delta"].abs().between(0.35, 0.65)
    ].copy()


def quote_rows(rows: pd.DataFrame, headers: dict[str, str]) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame()
    return cyb.fetch_daily_quotes(rows, headers)


def extend_kcb(
    dates: list[str],
    etf_daily: pd.DataFrame,
    headers: dict[str, str],
    sleep: float,
) -> None:
    raw = kcb.fetch_risk_indicators(
        [date.replace("-", "") for date in dates],
        retries=3,
        sleep=sleep,
        refresh=False,
    )
    risk = kcb.normalize_risk(raw)
    risk = risk[risk["underlying_code"] == "588000"].copy()
    old_risk = pd.read_csv(
        DATA / "kcb_option_risk_indicators.csv",
        dtype={"option_code": str, "underlying_code": str},
    )
    all_risk = pd.concat([old_risk, risk], ignore_index=True, sort=False)
    all_risk = all_risk.drop_duplicates(
        ["trade_date", "option_code"],
        keep="last",
    )
    all_risk.to_csv(DATA / "kcb_option_risk_indicators.csv", index=False)

    candidates = eligible_rows(risk)
    quotes = quote_rows(candidates, headers)
    merged = candidates.merge(
        quotes,
        on=["trade_date", "option_code"],
        how="left",
    )
    merged = merged.rename(
        columns={
            "open": "option_open",
            "high": "option_high",
            "low": "option_low",
            "close": "option_close",
            "volume": "option_volume",
        }
    )
    merged["option_return"] = pd.to_numeric(
        merged.get("changeRatio"),
        errors="coerce",
    ) / 100
    merged = merged.merge(
        etf_daily,
        on=["trade_date", "underlying_code"],
        how="left",
    )
    old = pd.read_csv(
        DATA / "kcb_option_daily.csv",
        dtype={"option_code": str, "contract_id": str, "underlying_code": str},
    )
    for column in old.columns:
        if column not in merged:
            merged[column] = pd.NA
    combined = pd.concat(
        [old, merged[old.columns]],
        ignore_index=True,
    ).drop_duplicates(["trade_date", "option_code"], keep="last")
    combined = combined.sort_values(
        ["trade_date", "underlying_code", "contract_id"]
    )
    combined.to_csv(DATA / "kcb_option_daily.csv", index=False)
    combined.to_csv(DATA / "kcb_option_daily_with_etf.csv", index=False)
    print(
        "[extend] KCB",
        "risk_rows=",
        len(risk),
        "candidate_rows=",
        len(candidates),
        "quoted_rows=",
        int(merged["option_close"].notna().sum()),
    )


def extend_cyb(
    dates: list[str],
    etf_daily: pd.DataFrame,
    headers: dict[str, str],
) -> None:
    frames = []
    for trade_date in dates:
        raw = cyb.fetch_risk_date(trade_date)
        raw["trade_date"] = trade_date
        parsed = pd.DataFrame(
            [cyb.parse_contract(row) for _, row in raw.iterrows()]
        )
        frames.append(parsed)
    risk = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    candidates = eligible_rows(risk)
    quotes = quote_rows(candidates, headers)
    merged = candidates.merge(
        quotes,
        on=["trade_date", "option_code"],
        how="left",
    )
    merged = merged.rename(
        columns={
            "open": "option_open",
            "high": "option_high",
            "low": "option_low",
            "close": "option_close",
            "volume": "option_volume",
            "amount": "option_amount",
            "changeRatio": "option_return_pct",
        }
    )
    merged = merged.merge(
        etf_daily[["trade_date", "etf_close"]],
        on="trade_date",
        how="left",
    )
    merged["implied_volatility"] = merged.apply(
        lambda row: cyb.implied_volatility_from_greeks(
            delta=float(row["delta"]),
            gamma=float(row["gamma"]),
            spot=float(row["etf_close"]),
            dte=int(row["dte"]),
            option_type=str(row["option_type"]),
        ),
        axis=1,
    )
    merged["iv_source"] = "szse_delta_gamma_derived"
    merged["option_return"] = pd.to_numeric(
        merged["option_return_pct"],
        errors="coerce",
    ) / 100
    old = pd.read_csv(
        DATA / "cyb_option_signal_daily.csv",
        dtype={"option_code": str, "contract_id": str, "underlying_code": str},
    )
    for column in old.columns:
        if column not in merged:
            merged[column] = pd.NA
    combined = pd.concat(
        [old, merged[old.columns]],
        ignore_index=True,
    ).drop_duplicates(["trade_date", "option_code"], keep="last")
    combined = combined.sort_values(["trade_date", "contract_id"])
    combined.to_csv(DATA / "cyb_option_signal_daily.csv", index=False)
    risk_out = candidates.drop(columns=["expiry_date"], errors="ignore")
    old_risk = pd.read_csv(
        DATA / "cyb_option_risk_signal_dates.csv",
        dtype={"option_code": str, "contract_id": str},
    )
    risk_combined = pd.concat([old_risk, risk_out], ignore_index=True, sort=False)
    risk_combined = risk_combined.drop_duplicates(
        ["trade_date", "option_code"],
        keep="last",
    )
    risk_combined.to_csv(DATA / "cyb_option_risk_signal_dates.csv", index=False)
    print(
        "[extend] CYB",
        "risk_rows=",
        len(risk),
        "candidate_rows=",
        len(candidates),
        "quoted_rows=",
        int(merged["option_close"].notna().sum()),
    )


def main() -> None:
    args = parse_args()
    token = bt.get_access_token()
    headers = {"Content-Type": "application/json", "access_token": token}
    weekdays = pd.date_range(args.start, args.end, freq="B")
    by_code: dict[str, list[pd.DataFrame]] = {"588000": [], "159915": []}
    trading_dates: list[str] = []
    for day in weekdays:
        trade_date = day.strftime("%Y-%m-%d")
        kcb_bars = fetch_etf_1m("588000", trade_date, headers, args.sleep)
        if kcb_bars.empty:
            continue
        cyb_bars = fetch_etf_1m("159915", trade_date, headers, args.sleep)
        if cyb_bars.empty:
            raise RuntimeError(f"159915 missing on {trade_date}")
        by_code["588000"].append(kcb_bars)
        by_code["159915"].append(cyb_bars)
        trading_dates.append(trade_date)
        print("[extend] ETF", trade_date, len(kcb_bars), len(cyb_bars))

    kcb_extension = aggregate_daily(by_code["588000"], "588000")
    cyb_extension = aggregate_daily(by_code["159915"], "159915")
    kcb_daily = append_etf_daily(
        DATA / "etf_daily_588000_588080.csv",
        kcb_extension,
    )
    cyb_daily = append_etf_daily(
        DATA / "etf_daily_159915.csv",
        cyb_extension,
    )
    extend_kcb(trading_dates, kcb_daily, headers, args.sleep)
    extend_cyb(trading_dates, cyb_daily, headers)
    print(
        "[extend] COMPLETE",
        "start=",
        trading_dates[0],
        "end=",
        trading_dates[-1],
        "days=",
        len(trading_dates),
    )


if __name__ == "__main__":
    main()
