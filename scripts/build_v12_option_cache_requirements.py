#!/usr/bin/env python3
"""Build the option 1m cache requirements for the v1.2 dual-ETF backtest.

The script intentionally does not fetch or convert minute bars.  It only
answers: on which dates does the ETF signal require option minute data, and
which daily candidate contracts should be cached before running the backtest?
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backtest_v02_recent_intraday as bt  # noqa: E402
import backtest_v10_opening_range_b as opening  # noqa: E402


DATA = ROOT / "data"
RESEARCH = ROOT / "research"

DEFAULT_DAILY = {
    "588000": DATA / "kcb_option_daily.csv",
    "159915": DATA / "cyb_option_signal_daily.csv",
}
DEFAULT_ETF_DAILY = {
    "588000": DATA / "etf_daily_588000_588080.csv",
    "159915": DATA / "etf_daily_159915.csv",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-07-01")
    parser.add_argument("--end", default="2026-06-30")
    parser.add_argument("--underlyings", default="588000,159915")
    parser.add_argument("--sqlite", type=Path, default=bt.DEFAULT_SQLITE)
    parser.add_argument("--etf-1m-root", type=Path, default=opening.ETF_1M_ROOT)
    parser.add_argument("--candidate-pool", type=int, default=8)
    parser.add_argument("--candidate-head", type=int, default=3)
    parser.add_argument("--range-threshold-588000", type=float, default=0.0030)
    parser.add_argument("--range-threshold-159915", type=float, default=0.0025)
    parser.add_argument("--breakout-vol-mult-588000", type=float, default=1.30)
    parser.add_argument("--breakout-vol-mult-159915", type=float, default=1.25)
    parser.add_argument("--breakout-volmax-mult", type=float, default=0.80)
    parser.add_argument("--daily-volume-tiered", action="store_true")
    parser.add_argument("--edge-dte-fallback", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=RESEARCH / "v12_option_cache_requirements.csv",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=RESEARCH / "v12_option_cache_requirements_summary.csv",
    )
    return parser.parse_args()


def signal_args(args: argparse.Namespace, underlying: str) -> argparse.Namespace:
    return argparse.Namespace(
        range_threshold=(
            args.range_threshold_159915
            if underlying == "159915"
            else args.range_threshold_588000
        ),
        breakout_vol_mult=(
            args.breakout_vol_mult_159915
            if underlying == "159915"
            else args.breakout_vol_mult_588000
        ),
        breakout_volmax_mult=args.breakout_volmax_mult,
    )


def load_daily_candidates(path: Path, start: str, end: str, underlying: str) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    daily = pd.read_csv(
        path,
        dtype={
            "option_code": str,
            "contract_id": str,
            "underlying_code": str,
        },
    )
    if "trade_date" not in daily or "underlying_code" not in daily:
        return pd.DataFrame()
    daily["trade_date"] = pd.to_datetime(daily["trade_date"]).dt.strftime("%Y-%m-%d")
    daily["option_code"] = daily["option_code"].astype(str).str.split(".").str[0].str.zfill(8)
    daily["underlying_code"] = daily["underlying_code"].astype(str).str.split(".").str[0]
    return daily[
        (daily["trade_date"] >= start)
        & (daily["trade_date"] <= end)
        & (daily["underlying_code"] == underlying)
    ].copy()


def build_for_underlying(args: argparse.Namespace, underlying: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    daily = load_daily_candidates(DEFAULT_DAILY[underlying], args.start, args.end, underlying)
    stats: dict[str, Any] = {
        "underlying": underlying,
        "daily_csv": str(DEFAULT_DAILY[underlying]),
        "daily_rows": int(len(daily)),
        "dates": 0,
        "missing_etf_1m": 0,
        "missing_daily_direction": 0,
        "daily_volume_blocked": 0,
        "no_opening_signal": 0,
        "no_daily_candidates": 0,
        "requirement_rows": 0,
        "signal_dates": 0,
    }
    if daily.empty:
        return pd.DataFrame(), stats

    daily_direction = bt.load_daily_direction(underlying, DEFAULT_ETF_DAILY[underlying])
    daily_direction = daily_direction[
        (daily_direction["trade_date"] >= args.start)
        & (daily_direction["trade_date"] <= args.end)
    ].copy()

    rows: list[dict[str, Any]] = []
    for trade_date in sorted(daily["trade_date"].unique()):
        stats["dates"] += 1
        etf1 = opening.load_etf_1m(args.etf_1m_root, trade_date, underlying)
        if etf1.empty:
            stats["missing_etf_1m"] += 1
            continue

        direction_rows = daily_direction[daily_direction["trade_date"] == trade_date]
        if direction_rows.empty:
            stats["missing_daily_direction"] += 1
            continue
        daily_row = direction_rows.iloc[0]
        daily_volume_ratio20 = daily_row.get("daily_ref_volume_ratio20", math.nan)
        if (
            args.daily_volume_tiered
            and (pd.isna(daily_volume_ratio20) or float(daily_volume_ratio20) < 0.65)
        ):
            stats["daily_volume_blocked"] += 1
            continue

        direction = str(daily_row["daily_direction"])
        signal = opening.find_opening_breakout(etf1, direction, signal_args(args, underlying))
        if signal is None:
            stats["no_opening_signal"] += 1
            continue

        candidates = bt.option_candidates(
            daily,
            trade_date,
            underlying,
            signal["direction"],
            args.candidate_pool,
            allow_edge_dte=args.edge_dte_fallback,
        )
        if candidates.empty:
            stats["no_daily_candidates"] += 1
            continue
        stats["signal_dates"] += 1
        for rank, row in enumerate(candidates.head(args.candidate_head).itertuples(index=False), 1):
            item = row._asdict()
            rows.append(
                {
                    "trade_date": trade_date,
                    "underlying_code": underlying,
                    "direction": signal["direction"],
                    "breakout_time": signal["breakout_time"],
                    "entry_time": signal["entry_time"],
                    "candidate_rank": rank,
                    "option_code": str(item["option_code"]).split(".")[0].zfill(8),
                    "contract_id": item.get("contract_id", ""),
                    "contract_symbol": item.get("contract_symbol", ""),
                    "option_type": item.get("option_type", ""),
                    "expiry_ym": item.get("expiry_ym", ""),
                    "strike": item.get("strike", math.nan),
                    "dte": item.get("dte", math.nan),
                    "delta": item.get("delta", math.nan),
                    "implied_volatility": item.get("implied_volatility", math.nan),
                    "option_volume": item.get("option_volume", math.nan),
                    "edge_dte_candidate": item.get("edge_dte_candidate", False),
                    "source_daily_csv": str(DEFAULT_DAILY[underlying]),
                }
            )
    out = pd.DataFrame(rows)
    stats["requirement_rows"] = int(len(out))
    return out, stats


def main() -> None:
    args = parse_args()
    RESEARCH.mkdir(parents=True, exist_ok=True)
    underlyings = [item.strip() for item in args.underlyings.split(",") if item.strip()]
    frames: list[pd.DataFrame] = []
    summaries: list[dict[str, Any]] = []
    for underlying in underlyings:
        frame, stats = build_for_underlying(args, underlying)
        frames.append(frame)
        summaries.append(stats)

    output = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not output.empty:
        output = output.drop_duplicates(["trade_date", "underlying_code", "option_code", "candidate_rank"])
        output = output.sort_values(["trade_date", "underlying_code", "candidate_rank"])
    output.to_csv(args.output, index=False)
    pd.DataFrame(summaries).to_csv(args.summary, index=False)
    print(pd.DataFrame(summaries).to_string(index=False))
    print({"output": str(args.output), "rows": int(len(output))})


if __name__ == "__main__":
    main()
