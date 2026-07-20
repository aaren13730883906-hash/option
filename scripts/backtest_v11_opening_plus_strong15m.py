#!/usr/bin/env python3
"""Backtest v1.1: v1.0B opening primary plus strong 15m fallback.

The fallback is eligible only on dates with no executed opening trade. All
component backtests use local caches; this wrapper never calls iFinD.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = ROOT / "research"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=510)
    parser.add_argument("--initial-capital", type=float, default=100000.0)
    parser.add_argument("--underlying", choices=["588000", "159915"], default="588000")
    parser.add_argument(
        "--daily-csv",
        type=Path,
        default=ROOT / "data" / "kcb_option_daily.csv",
    )
    parser.add_argument(
        "--market-iv-csv",
        type=Path,
        default=ROOT / "data" / "kcb_market_iv_daily.csv",
    )
    parser.add_argument(
        "--etf-daily-csv",
        type=Path,
        default=ROOT / "data" / "etf_daily_588000_588080.csv",
    )
    parser.add_argument("--range-threshold", type=float, default=0.0030)
    parser.add_argument("--put-range-threshold", type=float, default=None)
    parser.add_argument("--breakout-vol-mult", type=float, default=1.30)
    parser.add_argument("--normal-tp2-factor", type=float, default=1.80)
    parser.add_argument("--disable-fallback", action="store_true")
    parser.add_argument("--fallback-position-multiplier", type=float, default=2.5)
    parser.add_argument("--fallback-position-cap", type=float, default=0.50)
    parser.add_argument("--fallback-progress-min", type=float, default=1.15)
    parser.add_argument("--warmup-trading-days", type=int, default=20)
    parser.add_argument("--late-trend-acceleration", action="store_true")
    parser.add_argument("--late-strong-volume-mult", type=float, default=1.8)
    parser.add_argument("--high-iv-crash-put", action="store_true")
    parser.add_argument("--high-iv-put-min", type=float, default=0.70)
    parser.add_argument("--high-iv-put-max", type=float, default=0.90)
    parser.add_argument("--high-iv-put-position-cap", type=float, default=0.25)
    parser.add_argument("--cluster-acceleration-exemption", action="store_true")
    parser.add_argument("--cluster-exemption-volume-mult", type=float, default=3.0)
    parser.add_argument("--cluster-exemption-position-cap", type=float, default=0.25)
    parser.add_argument(
        "--cluster-exemption-direction",
        choices=["both", "call", "put"],
        default="put",
    )
    parser.add_argument("--fallback-option-momentum-confirm", action="store_true")
    parser.add_argument(
        "--fallback-option-momentum-direction",
        choices=["both", "call", "put"],
        default="both",
    )
    parser.add_argument("--fallback-option-lookback-minutes", type=int, default=8)
    parser.add_argument("--fallback-option-recent-minutes", type=int, default=3)
    parser.add_argument("--fallback-option-pullback-max", type=float, default=0.08)
    parser.add_argument("--fallback-option-volume-fade-ratio", type=float, default=0.70)
    parser.add_argument("--edge-dte-fallback", action="store_true")
    parser.add_argument(
        "--disable-long-exhaustion-filter",
        action="store_true",
        help="Disable the default 588000 opening-Call long-exhaustion filter.",
    )
    parser.add_argument("--long-exhaustion-price-threshold", type=float, default=0.05)
    parser.add_argument(
        "--output",
        type=Path,
        default=RESEARCH_DIR / "backtest_v11_opening_plus_strong15m_trades.csv",
    )
    parser.add_argument(
        "--capital-output",
        type=Path,
        default=RESEARCH_DIR / "backtest_v11_opening_plus_strong15m_capital.csv",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=RESEARCH_DIR / "backtest_v11_opening_plus_strong15m_summary.csv",
    )
    return parser.parse_args()


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def read_trades(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def main() -> None:
    args = parse_args()
    for path in [args.output, args.capital_output, args.summary]:
        path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="option-v11-") as temp_dir:
        temp = Path(temp_dir)
        opening_path = temp / "opening.csv"
        opening_summary = temp / "opening_summary.csv"
        fallback_pool_path = temp / "fallback_pool.csv"
        fallback_pool_summary = temp / "fallback_pool_summary.csv"
        capital_summary = temp / "capital_summary.csv"

        opening_command = [
                sys.executable,
                "scripts/backtest_v10_opening_range_b.py",
                "--days",
                str(args.days),
                "--underlying",
                args.underlying,
                "--daily-csv",
                str(args.daily_csv),
                "--market-iv-csv",
                str(args.market_iv_csv),
                "--etf-daily-csv",
                str(args.etf_daily_csv),
                "--range-threshold",
                str(args.range_threshold),
                "--warmup-trading-days",
                str(args.warmup_trading_days),
                "--breakout-vol-mult",
                str(args.breakout_vol_mult),
                "--normal-tp2-factor",
                str(args.normal_tp2_factor),
                "--daily-volume-tiered",
                "--output",
                str(opening_path),
                "--summary",
                str(opening_summary),
            ]
        if args.put_range_threshold is not None:
            opening_command.extend(["--put-range-threshold", str(args.put_range_threshold)])
        if args.edge_dte_fallback:
            opening_command.append("--edge-dte-fallback")
        if args.disable_long_exhaustion_filter:
            opening_command.append("--disable-long-exhaustion-filter")
        if args.long_exhaustion_price_threshold != 0.05:
            opening_command.extend(
                [
                    "--long-exhaustion-price-threshold",
                    str(args.long_exhaustion_price_threshold),
                ]
            )
        run(opening_command)
        if not args.disable_fallback:
            fallback_command = [
                sys.executable,
                "scripts/backtest_v02_recent_intraday.py",
                "--days",
                str(args.days),
                "--underlying",
                args.underlying,
                "--daily-csv",
                str(args.daily_csv),
                "--market-iv-csv",
                str(args.market_iv_csv),
                "--etf-daily-csv",
                str(args.etf_daily_csv),
                "--candidate-pool",
                "3",
                "--daily-volume-tiered",
                "--strong-signals-only",
                "--entry-start-time",
                "09:45",
                "--execute-0945-at-0946",
                "--position-multiplier",
                str(args.fallback_position_multiplier),
                "--position-cap",
                str(args.fallback_position_cap),
                "--fallback-progress-min",
                str(args.fallback_progress_min),
                "--normal-tp2-factor",
                str(args.normal_tp2_factor),
                "--warmup-trading-days",
                str(args.warmup_trading_days),
                "--no-fetch",
                "--output",
                str(fallback_pool_path),
                "--summary",
                str(fallback_pool_summary),
            ]
            if args.late_trend_acceleration:
                fallback_command.extend(
                    ["--late-trend-acceleration", "--late-strong-volume-mult", str(args.late_strong_volume_mult)]
                )
            if args.high_iv_crash_put:
                fallback_command.extend(
                    [
                        "--high-iv-crash-put",
                        "--high-iv-put-min",
                        str(args.high_iv_put_min),
                        "--high-iv-put-max",
                        str(args.high_iv_put_max),
                        "--high-iv-put-position-cap",
                        str(args.high_iv_put_position_cap),
                    ]
                )
            if args.cluster_acceleration_exemption:
                fallback_command.extend(
                    [
                        "--cluster-acceleration-exemption",
                        "--cluster-exemption-volume-mult",
                        str(args.cluster_exemption_volume_mult),
                        "--cluster-exemption-position-cap",
                        str(args.cluster_exemption_position_cap),
                        "--cluster-exemption-direction",
                        args.cluster_exemption_direction,
                    ]
                )
            if args.fallback_option_momentum_confirm:
                fallback_command.extend(
                    [
                        "--fallback-option-momentum-confirm",
                        "--fallback-option-momentum-direction",
                        args.fallback_option_momentum_direction,
                        "--fallback-option-lookback-minutes",
                        str(args.fallback_option_lookback_minutes),
                        "--fallback-option-recent-minutes",
                        str(args.fallback_option_recent_minutes),
                        "--fallback-option-pullback-max",
                        str(args.fallback_option_pullback_max),
                        "--fallback-option-volume-fade-ratio",
                        str(args.fallback_option_volume_fade_ratio),
                    ]
                )
            run(fallback_command)

        opening = read_trades(opening_path)
        fallback_pool = pd.DataFrame() if args.disable_fallback else read_trades(fallback_pool_path)
        opening_dates = set(opening.get("trade_date", pd.Series(dtype=str)).astype(str))
        if fallback_pool.empty:
            fallback = fallback_pool.copy()
        else:
            strong = fallback_pool["signal_strength"].astype(str).str.startswith("strong")
            no_opening_trade = ~fallback_pool["trade_date"].astype(str).isin(opening_dates)
            fallback = fallback_pool[strong & no_opening_trade].copy()

        if not opening.empty:
            opening["strategy_leg"] = "opening_primary"
        if not fallback.empty:
            fallback["strategy_leg"] = "strong_15m_fallback"
        combined = pd.concat([opening, fallback], ignore_index=True, sort=False)
        if not combined.empty:
            combined["entry_time"] = pd.to_datetime(combined["entry_time"])
            combined = combined.sort_values("entry_time")
        combined.to_csv(args.output, index=False)

        run(
            [
                sys.executable,
                "scripts/calc_capital_backtest.py",
                "--trades",
                str(args.output),
                "--output",
                str(args.capital_output),
                "--summary",
                str(capital_summary),
                "--initial-capital",
                str(args.initial_capital),
                "--strategy-version",
                "v1.1",
            ]
        )

        summary = pd.read_csv(capital_summary)
        summary["opening_trades"] = len(opening)
        summary["strong_15m_pool_trades"] = int(
            fallback_pool.get("signal_strength", pd.Series(dtype=str)).astype(str).str.startswith("strong").sum()
        )
        summary["blocked_by_opening_trade"] = int(
            (
                fallback_pool.get("signal_strength", pd.Series(dtype=str)).astype(str).str.startswith("strong")
                & fallback_pool.get("trade_date", pd.Series(dtype=str)).astype(str).isin(opening_dates)
            ).sum()
        )
        summary["fallback_trades"] = len(fallback)
        summary["fallback_progress_min"] = args.fallback_progress_min
        summary["normal_tp2_factor"] = args.normal_tp2_factor
        summary["warmup_trading_days"] = args.warmup_trading_days
        summary["put_range_threshold"] = (
            args.put_range_threshold if args.put_range_threshold is not None else args.range_threshold
        )
        summary["late_trend_acceleration"] = args.late_trend_acceleration
        summary["late_strong_volume_mult"] = args.late_strong_volume_mult
        summary["high_iv_crash_put"] = args.high_iv_crash_put
        summary["high_iv_put_range"] = "{}-{}".format(args.high_iv_put_min, args.high_iv_put_max)
        summary["high_iv_put_position_cap"] = args.high_iv_put_position_cap
        summary["cluster_acceleration_exemption"] = args.cluster_acceleration_exemption
        summary["cluster_exemption_direction"] = args.cluster_exemption_direction
        summary["cluster_exemption_volume_mult"] = args.cluster_exemption_volume_mult
        summary["cluster_exemption_position_cap"] = args.cluster_exemption_position_cap
        summary["data_mode"] = "local_cache_only"
        summary.to_csv(args.summary, index=False)
        print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
