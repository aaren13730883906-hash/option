#!/usr/bin/env python3
"""Analyze KCB option IV regime and simple long-option forward returns."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "kcb_option_daily.csv"
OUT_DIR = ROOT / "research"


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["expiry_dt"] = pd.to_datetime(df["expiry_ym"].astype(str) + "01", format="%Y%m%d") + pd.offsets.MonthEnd(0)
    df["dte_approx"] = (df["expiry_dt"] - df["trade_date"]).dt.days
    df["moneyness"] = df["etf_close"] / df["strike"]
    df["abs_moneyness"] = (df["moneyness"] - 1).abs()
    return df


def build_market_iv(df: pd.DataFrame) -> pd.DataFrame:
    tradable = df[df["option_close"].notna()].copy()
    selected = tradable[
        tradable["dte_approx"].between(10, 45)
        & (tradable["abs_moneyness"] <= 0.08)
        & (tradable["option_volume"] > 0)
        & (tradable["implied_volatility"] > 0)
    ].copy()
    market = (
        selected.groupby(["underlying_code", "trade_date"])
        .agg(
            market_iv=("implied_volatility", "median"),
            atm_iv_mean=("implied_volatility", "mean"),
            sample_contracts=("option_code", "nunique"),
            avg_abs_moneyness=("abs_moneyness", "mean"),
        )
        .reset_index()
        .sort_values(["underlying_code", "trade_date"])
    )
    frames = []
    for _, group in market.groupby("underlying_code"):
        group = group.sort_values("trade_date").copy()
        roll_min = group["market_iv"].rolling(252, min_periods=60).min()
        roll_max = group["market_iv"].rolling(252, min_periods=60).max()
        group["iv_rank_252"] = ((group["market_iv"] - roll_min) / (roll_max - roll_min)).clip(0, 1)
        group["iv_percentile_252"] = group["market_iv"].rolling(252, min_periods=60).apply(
            lambda values: (values <= values[-1]).mean(),
            raw=True,
        )
        frames.append(group)
    return pd.concat(frames, ignore_index=True)


def forward_return_summary(df: pd.DataFrame, market_iv: pd.DataFrame) -> pd.DataFrame:
    tradable = df[df["option_close"].notna()].sort_values(["option_code", "trade_date"]).copy()
    for horizon in [1, 3, 5]:
        tradable[f"fwd_ret_{horizon}d"] = (
            tradable.groupby("option_code")["option_close"].shift(-horizon) / tradable["option_close"] - 1
        )
    tradable = tradable.merge(
        market_iv[["underlying_code", "trade_date", "market_iv", "iv_rank_252", "iv_percentile_252"]],
        on=["underlying_code", "trade_date"],
        how="left",
    )
    candidates = tradable[
        tradable["dte_approx"].between(10, 20)
        & (tradable["abs_moneyness"] <= 0.12)
        & (tradable["option_volume"] > 0)
        & tradable["iv_rank_252"].notna()
        & tradable["delta"].abs().between(0.3, 0.7)
    ].copy()
    labels = ["0-20%", "20-35%", "35-50%", "50-65%", "65-80%", "80-100%"]
    candidates["iv_rank_bucket"] = pd.cut(
        candidates["iv_rank_252"],
        bins=[0, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0],
        labels=labels,
        include_lowest=True,
    )
    rows = []
    for horizon in [1, 3, 5]:
        col = f"fwd_ret_{horizon}d"
        tmp = candidates[candidates[col].notna()]
        for (underlying, bucket), group in tmp.groupby(["underlying_code", "iv_rank_bucket"], observed=True):
            rows.append(
                {
                    "underlying_code": underlying,
                    "iv_rank_bucket": str(bucket),
                    "horizon": f"{horizon}d",
                    "n": len(group),
                    "win_rate": (group[col] > 0).mean(),
                    "median_ret": group[col].median(),
                    "mean_ret": group[col].mean(),
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    df = add_time_features(pd.read_csv(DATA, dtype={"option_code": str, "contract_id": str}))
    market_iv = build_market_iv(df)
    summary = forward_return_summary(df, market_iv)
    market_iv.to_csv(ROOT / "data" / "kcb_market_iv_daily.csv", index=False)
    summary.to_csv(OUT_DIR / "iv_rank_forward_return_summary.csv", index=False)
    print(market_iv.groupby("underlying_code")["market_iv"].describe().to_string())
    print()
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
