#!/usr/bin/env python3
"""Build broad option 1m cache requirements from local daily candidate tables.

This deliberately over-selects a little: for every trade date and both option
directions, keep the top daily-volume candidates that satisfy the strategy's
DTE, Delta and IV gates.  The resulting list is used to extract only relevant
1m files from the full local option-minute archives.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backtest_v02_recent_intraday as bt  # noqa: E402


DATA = ROOT / "data"
RESEARCH = ROOT / "research"

DEFAULT_DAILY = {
    "588000": DATA / "kcb_option_daily.csv",
    "159915": DATA / "cyb_option_signal_daily.csv",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2023-06-06")
    parser.add_argument("--end", default="2026-06-30")
    parser.add_argument("--underlyings", default="588000,159915")
    parser.add_argument(
        "--daily-csv-588000",
        type=Path,
        default=DEFAULT_DAILY["588000"],
    )
    parser.add_argument(
        "--daily-csv-159915",
        type=Path,
        default=DEFAULT_DAILY["159915"],
    )
    parser.add_argument("--candidate-pool", type=int, default=8)
    parser.add_argument("--candidate-head", type=int, default=3)
    parser.add_argument("--edge-dte-fallback", action="store_true")
    parser.add_argument("--high-iv-crash-put", action="store_true")
    parser.add_argument("--high-iv-put-min", type=float, default=0.70)
    parser.add_argument("--high-iv-put-max", type=float, default=0.90)
    parser.add_argument(
        "--output",
        type=Path,
        default=RESEARCH / "full_option_cache_requirements_202306_202606.csv",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=RESEARCH / "full_option_cache_requirements_202306_202606_summary.csv",
    )
    return parser.parse_args()


def load_daily(path: Path, underlying: str, start: str, end: str) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(
        path,
        dtype={
            "option_code": str,
            "contract_id": str,
            "underlying_code": str,
        },
    )
    if df.empty:
        return df
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    df["underlying_code"] = df["underlying_code"].astype(str).str.split(".").str[0]
    df["option_code"] = df["option_code"].astype(str).str.split(".").str[0].str.zfill(8)
    return df[
        (df["underlying_code"] == underlying)
        & (df["trade_date"] >= start)
        & (df["trade_date"] <= end)
    ].copy()


def candidate_rows(
    daily: pd.DataFrame,
    trade_date: str,
    underlying: str,
    direction: str,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    candidates = bt.option_candidates(
        daily,
        trade_date,
        underlying,
        direction,
        args.candidate_pool,
        allow_edge_dte=args.edge_dte_fallback,
        high_iv_crash_put=args.high_iv_crash_put,
        high_iv_put_min=args.high_iv_put_min,
        high_iv_put_max=args.high_iv_put_max,
    )
    rows: list[dict[str, Any]] = []
    for rank, row in enumerate(candidates.head(args.candidate_head).itertuples(index=False), 1):
        item = row._asdict()
        rows.append(
            {
                "trade_date": trade_date,
                "underlying_code": underlying,
                "direction": direction,
                "candidate_rank": rank,
                "option_code": str(item.get("option_code", "")).split(".")[0].zfill(8),
                "contract_id": item.get("contract_id", ""),
                "contract_symbol": item.get("contract_symbol", ""),
                "option_type": item.get("option_type", ""),
                "expiry_ym": item.get("expiry_ym", ""),
                "strike": item.get("strike", pd.NA),
                "dte": item.get("dte", pd.NA),
                "delta": item.get("delta", pd.NA),
                "implied_volatility": item.get("implied_volatility", pd.NA),
                "option_volume": item.get("option_volume", pd.NA),
                "edge_dte_candidate": item.get("edge_dte_candidate", False),
                "high_iv_crash_put_candidate": item.get("high_iv_crash_put_candidate", False),
            }
        )
    return rows


def main() -> None:
    args = parse_args()
    output_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    underlyings = [item.strip() for item in args.underlyings.split(",") if item.strip()]
    daily_paths = {
        "588000": args.daily_csv_588000,
        "159915": args.daily_csv_159915,
    }
    for underlying in underlyings:
        daily = load_daily(daily_paths[underlying], underlying, args.start, args.end)
        dates = sorted(daily["trade_date"].unique()) if not daily.empty else []
        before = len(output_rows)
        for trade_date in dates:
            for direction in ["call", "put"]:
                output_rows.extend(candidate_rows(daily, trade_date, underlying, direction, args))
        summary_rows.append(
            {
                "underlying_code": underlying,
                "daily_csv": str(daily_paths[underlying]),
                "daily_rows": int(len(daily)),
                "dates": int(len(dates)),
                "requirement_rows": int(len(output_rows) - before),
                "unique_contract_dates": int(
                    len(
                        {
                            (row["trade_date"], row["option_code"])
                            for row in output_rows[before:]
                        }
                    )
                ),
            }
        )

    out = pd.DataFrame(output_rows)
    if not out.empty:
        out = out.drop_duplicates(
            ["trade_date", "underlying_code", "direction", "candidate_rank", "option_code"]
        )
        out = out.sort_values(["trade_date", "underlying_code", "direction", "candidate_rank"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    pd.DataFrame(summary_rows).to_csv(args.summary, index=False)
    print(pd.DataFrame(summary_rows).to_string(index=False))
    print({"output": str(args.output), "rows": int(len(out))})


if __name__ == "__main__":
    main()
