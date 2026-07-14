#!/usr/bin/env python3
"""Rebuild CYB option candidate daily data from generated signal dates.

This is the second step of the v1.2 CYB data-rebuild flow.  Unlike
``build_cyb_option_signal_data.py``, it reads signal dates from a CSV instead
of using a hard-coded SIGNALS dictionary.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backtest_v02_recent_intraday as bt  # noqa: E402
import build_cyb_option_signal_data as cyb  # noqa: E402


DATA = ROOT / "data"
RESEARCH = ROOT / "research"
SIGNALS_CSV = RESEARCH / "cyb_opening_signal_dates_202407_202606.csv"
OUTPUT = DATA / "cyb_option_signal_daily.csv"
RISK_OUTPUT = DATA / "cyb_option_risk_signal_dates.csv"


def main() -> None:
    if not SIGNALS_CSV.exists():
        raise FileNotFoundError(SIGNALS_CSV)
    signals = pd.read_csv(SIGNALS_CSV)
    signals["trade_date"] = pd.to_datetime(signals["trade_date"]).dt.strftime("%Y-%m-%d")
    signal_map = dict(zip(signals["trade_date"], signals["direction"]))

    etf_daily = pd.read_csv(DATA / "etf_daily_159915.csv")
    etf_daily["trade_date"] = pd.to_datetime(etf_daily["trade_date"]).dt.strftime("%Y-%m-%d")
    market_iv = pd.read_csv(DATA / "cyb_market_iv_daily.csv")
    market_iv["trade_date"] = pd.to_datetime(market_iv["trade_date"]).dt.strftime("%Y-%m-%d")

    risk_frames: list[pd.DataFrame] = []
    for trade_date in sorted(signal_map):
        raw = cyb.fetch_risk_date(trade_date)
        raw["trade_date"] = trade_date
        parsed = pd.DataFrame([cyb.parse_contract(row) for _, row in raw.iterrows()])
        parsed["dte"] = (parsed["expiry_date"] - pd.Timestamp(trade_date)).dt.days
        common = parsed[
            (parsed["option_type"] == signal_map[trade_date])
            & parsed["delta"].abs().between(0.35, 0.65)
        ].copy()
        normal = common[common["dte"].between(10, 35)].copy()
        if not normal.empty:
            normal["edge_dte_candidate"] = False
            normal["dte_position_factor"] = 1.0
            risk_frames.append(normal)
            continue
        edge = common[
            common["dte"].between(7, 9) | common["dte"].between(36, 40)
        ].copy()
        edge["edge_dte_candidate"] = True
        edge["dte_position_factor"] = 0.60
        risk_frames.append(edge)

    risk = pd.concat(risk_frames, ignore_index=True) if risk_frames else pd.DataFrame()
    RISK_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    risk.to_csv(RISK_OUTPUT, index=False)

    headers = {
        "Content-Type": "application/json",
        "access_token": bt.get_access_token(),
    }
    quotes = cyb.fetch_daily_quotes(risk, headers)
    daily = risk.merge(quotes, on=["trade_date", "option_code"], how="left")
    daily = daily.merge(
        market_iv[["trade_date", "market_iv", "iv_rank_252"]],
        on="trade_date",
        how="left",
    )
    daily = daily.merge(
        etf_daily[["trade_date", "etf_close"]],
        on="trade_date",
        how="left",
    )
    daily["implied_volatility"] = daily.apply(
        lambda row: cyb.implied_volatility_from_greeks(
            delta=float(row["delta"]),
            gamma=float(row["gamma"]),
            spot=float(row["etf_close"]),
            dte=int(row["dte"]),
            option_type=str(row["option_type"]),
        ),
        axis=1,
    )
    daily["iv_source"] = "szse_delta_gamma_derived"
    daily["iv_gap_vs_market"] = daily["implied_volatility"] - daily["market_iv"]
    daily = daily.rename(
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
    for col in ["option_open", "option_high", "option_low", "option_close", "option_volume"]:
        if col not in daily:
            daily[col] = pd.NA
        daily[col] = pd.to_numeric(daily[col], errors="coerce")
    daily["option_return"] = pd.to_numeric(daily.get("option_return_pct"), errors="coerce") / 100
    daily = daily.drop(columns=["expiry_date", "thscode"], errors="ignore")
    daily.to_csv(OUTPUT, index=False)
    print(
        {
            "signal_dates": len(signal_map),
            "risk_rows": int(len(risk)),
            "output_rows": int(len(daily)),
            "quoted_rows": int(daily["option_volume"].notna().sum()),
            "derived_iv_rows": int(daily["implied_volatility"].notna().sum()),
            "output": str(OUTPUT),
        },
        flush=True,
    )


if __name__ == "__main__":
    main()
