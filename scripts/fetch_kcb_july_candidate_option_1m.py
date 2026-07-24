#!/usr/bin/env python3
"""Fetch KCB July 2026 candidate option 1m bars into data/intraday_cache.

This is intentionally narrow: it fetches only KCB option rows that pass the
strategy's broad daily candidate gates, instead of downloading every listed
contract. It reuses the existing iFinD token/cache helpers.
"""

from __future__ import annotations

import argparse
import calendar
from pathlib import Path

import pandas as pd

import backtest_v02_recent_intraday as bt


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2026-07-01")
    parser.add_argument("--end", default="2026-07-23")
    parser.add_argument("--daily-csv", type=Path, default=DATA / "kcb_option_daily.csv")
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args()


def fourth_wednesday(year: int, month: int) -> pd.Timestamp:
    days = [
        day
        for day in range(1, calendar.monthrange(year, month)[1] + 1)
        if calendar.weekday(year, month, day) == calendar.WEDNESDAY
    ]
    return pd.Timestamp(year=year, month=month, day=days[3])


def expiry_from_ym(expiry_ym: object) -> pd.Timestamp:
    value = int(expiry_ym)
    return fourth_wednesday(value // 100, value % 100)


def main() -> None:
    args = parse_args()
    daily = pd.read_csv(args.daily_csv, dtype={"option_code": str, "underlying_code": str})
    daily["trade_date"] = pd.to_datetime(daily["trade_date"])
    daily["expiry_date"] = daily["expiry_ym"].map(expiry_from_ym)
    daily["dte_calc"] = (daily["expiry_date"] - daily["trade_date"]).dt.days
    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    candidates = daily[
        (daily["underlying_code"] == "588000")
        & daily["trade_date"].between(start, end)
        & pd.to_numeric(daily["dte_calc"], errors="coerce").between(10, 35)
        & pd.to_numeric(daily["delta"], errors="coerce").abs().between(0.35, 0.65)
    ].copy()
    candidates = candidates.drop_duplicates(["trade_date", "option_code"])
    candidates = candidates.sort_values(["trade_date", "option_type", "option_code"])
    print("[fetch_1m] candidates=", len(candidates), "dates=", candidates["trade_date"].nunique())
    if candidates.empty:
        return

    token = bt.get_access_token()
    headers = {"Content-Type": "application/json", "access_token": token}
    fetched = 0
    cached = 0
    missing = 0
    for idx, row in candidates.reset_index(drop=True).iterrows():
        trade_date = row["trade_date"].strftime("%Y-%m-%d")
        option_code = str(row["option_code"]).zfill(8)
        cache_path = bt.INTRADAY_CACHE / f"{trade_date}_{option_code}_1m.csv"
        if cache_path.exists() and not args.refresh:
            cached += 1
            continue
        bars = bt.fetch_option_1m(
            option_code,
            trade_date,
            headers=headers,
            sleep=args.sleep,
            retries=args.retries,
            refresh=args.refresh,
            no_fetch=False,
        )
        if bars.empty:
            missing += 1
        else:
            fetched += 1
        print(
            "[fetch_1m]",
            f"{idx + 1}/{len(candidates)}",
            trade_date,
            option_code,
            "rows=",
            len(bars),
            flush=True,
        )
    print("[fetch_1m] COMPLETE fetched=", fetched, "cached=", cached, "missing=", missing)


if __name__ == "__main__":
    main()
