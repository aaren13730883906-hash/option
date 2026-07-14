#!/usr/bin/env python3
"""Build CYB ETF opening-signal dates from local ETF bars.

This is the first step of the v1.2 CYB data-rebuild flow.  It does not need
option data.  It scans 159915 ETF 1m archives with the same opening-range
logic used by the backtest and writes the dates/directions that need SZSE
option risk indicators.
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-07-01")
    parser.add_argument("--end", default="2026-06-30")
    parser.add_argument("--underlying", default="159915")
    parser.add_argument("--etf-daily-csv", type=Path, default=DATA / "etf_daily_159915.csv")
    parser.add_argument("--etf-1m-root", type=Path, default=opening.ETF_1M_ROOT)
    parser.add_argument("--range-threshold", type=float, default=0.0025)
    parser.add_argument("--breakout-vol-mult", type=float, default=1.25)
    parser.add_argument("--breakout-volmax-mult", type=float, default=0.80)
    parser.add_argument(
        "--output",
        type=Path,
        default=RESEARCH / "cyb_opening_signal_dates_202407_202606.csv",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=RESEARCH / "cyb_opening_signal_dates_202407_202606_summary.csv",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    RESEARCH.mkdir(parents=True, exist_ok=True)
    daily_direction = bt.load_daily_direction(args.underlying, args.etf_daily_csv)
    daily_direction = daily_direction[
        (daily_direction["trade_date"] >= args.start)
        & (daily_direction["trade_date"] <= args.end)
    ].copy()
    signal_args = argparse.Namespace(
        range_threshold=args.range_threshold,
        breakout_vol_mult=args.breakout_vol_mult,
        breakout_volmax_mult=args.breakout_volmax_mult,
    )

    rows: list[dict[str, Any]] = []
    stats = {
        "underlying": args.underlying,
        "start": args.start,
        "end": args.end,
        "daily_direction_dates": int(len(daily_direction)),
        "missing_etf_1m": 0,
        "direction_none": 0,
        "no_opening_signal": 0,
        "signals": 0,
    }
    for row in daily_direction.itertuples(index=False):
        trade_date = str(row.trade_date)
        direction = str(row.daily_direction)
        if direction not in {"call", "put"}:
            stats["direction_none"] += 1
            continue
        etf1 = opening.load_etf_1m(args.etf_1m_root, trade_date, args.underlying)
        if etf1.empty:
            stats["missing_etf_1m"] += 1
            continue
        signal = opening.find_opening_breakout(etf1, direction, signal_args)
        if signal is None:
            stats["no_opening_signal"] += 1
            continue
        stats["signals"] += 1
        rows.append(
            {
                "trade_date": trade_date,
                "underlying_code": args.underlying,
                "direction": direction,
                "entry_time": signal["entry_time"],
                "breakout_time": signal["breakout_time"],
                "opening_high": signal["opening_high"],
                "opening_low": signal["opening_low"],
                "opening_amp": signal["opening_amp"],
                "breakout_vol_ratio": signal["breakout_vol_ratio"],
                "daily_ref_volume_ratio20": getattr(row, "daily_ref_volume_ratio20", math.nan),
                "daily_ref_ma_cluster": getattr(row, "daily_ref_ma_cluster", math.nan),
            }
        )

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("trade_date")
    out.to_csv(args.output, index=False)
    pd.DataFrame([stats]).to_csv(args.summary, index=False)
    print(pd.DataFrame([stats]).to_string(index=False))
    print({"output": str(args.output), "rows": int(len(out))})


if __name__ == "__main__":
    main()
