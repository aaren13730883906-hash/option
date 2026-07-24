#!/usr/bin/env python3
"""Backtest KCB 09:45 Put option-flow add-on candidates.

This is a research-only add-on test.  It does not change the main strategy.
It reuses the existing exit model from backtest_v02_recent_intraday.py so the
experiment isolates the new entry signal.
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

from backtest_v02_recent_intraday import DEFAULT_SQLITE, load_etf_15m, simulate_exit


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = ROOT / "research"
FULL_KCB_1M_DIR = ROOT / "data" / "科创板 1 分钟数据（全）" / "华夏上证科创板50ETF"
EVENTS_CSV = RESEARCH_DIR / "kcb_early_daily_volume_flow_events.csv"
BASE_TRADES_CSV = RESEARCH_DIR / "full_confirm_tp2_3p0_trades.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, default=EVENTS_CSV)
    parser.add_argument("--base-trades", type=Path, default=BASE_TRADES_CSV)
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    parser.add_argument("--threshold", type=float, default=0.10)
    parser.add_argument("--position-pct", type=float, default=0.25)
    parser.add_argument("--etf-up-min", type=float, default=None)
    parser.add_argument("--delta-min", type=float, default=None)
    parser.add_argument("--delta-max", type=float, default=None)
    parser.add_argument("--normal-tp2-factor", type=float, default=3.0)
    parser.add_argument("--strong-trailing-pct", type=float, default=0.20)
    parser.add_argument("--output-prefix", default="put_flow_0945")
    return parser.parse_args()


def month_key(trade_date: str) -> str:
    return str(trade_date)[:7]


def read_option_1m(option_code: int | str, trade_date: str) -> pd.DataFrame:
    code = str(int(option_code))
    month = month_key(trade_date)
    csv_path = FULL_KCB_1M_DIR / month / f"SSE.{code}.csv"
    zip_path = FULL_KCB_1M_DIR / f"{month}.zip"

    if csv_path.exists():
        df = pd.read_csv(csv_path)
    elif zip_path.exists():
        member = f"SSE.{code}.csv"
        with zipfile.ZipFile(zip_path) as zf:
            candidates = [name for name in zf.namelist() if name.endswith(member)]
            if not candidates:
                raise FileNotFoundError(f"{member} not found in {zip_path}")
            with zf.open(candidates[0]) as handle:
                df = pd.read_csv(handle)
    else:
        raise FileNotFoundError(f"No 1m file for {code} in {month}")

    df["datetime"] = pd.to_datetime(df["datetime"])
    day = pd.Timestamp(trade_date).date()
    df = df[df["datetime"].dt.date == day].copy()
    df["ema5"] = df["close"].ewm(span=5, adjust=False).mean()
    return df


def choose_events(events: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    df = events.copy()
    df = df[
        (df["threshold"].round(6) == round(args.threshold, 6))
        & (df["option_type"] == "put")
        & (df["time"] == "09:45")
    ].copy()
    if args.etf_up_min is not None:
        df = df[df["etf_intraday_return"] >= args.etf_up_min].copy()
    if args.delta_min is not None:
        df = df[df["delta"].abs() >= args.delta_min].copy()
    if args.delta_max is not None:
        df = df[df["delta"].abs() <= args.delta_max].copy()

    # One signal per day: use the strongest daily-volume share.
    df = df.sort_values(["trade_date", "volume15_to_prior5_daily"], ascending=[True, False])
    return df.groupby("trade_date", as_index=False).first()


def build_trade_rows(events: pd.DataFrame, etf_15m: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, event in events.iterrows():
        trade_date = str(event["trade_date"])
        entry_time = pd.Timestamp(f"{trade_date} 09:45:00")
        bars = read_option_1m(event["option_code"], trade_date)
        if bars.empty:
            continue
        entry_rows = bars[bars["datetime"] == entry_time]
        if entry_rows.empty:
            entry_rows = bars[bars["datetime"] <= entry_time].tail(1)
        if entry_rows.empty:
            continue
        entry_price = float(entry_rows.iloc[-1]["close"])
        day_etf = etf_15m[etf_15m["datetime"].dt.date == pd.Timestamp(trade_date).date()].copy()
        exit_info = simulate_exit(
            bars,
            day_etf,
            entry_time,
            entry_price,
            direction="put",
            signal_strength="strong_put_flow_0945",
            strong_trailing_pct=args.strong_trailing_pct,
            normal_tp2_factor=args.normal_tp2_factor,
            soft_stop_pct=0.82,
            soft_stop_delay_minutes=0,
        )
        rows.append(
            {
                "trade_date": trade_date,
                "underlying_code": "588000",
                "direction": "put",
                "entry_time": entry_time,
                "option_code": int(event["option_code"]),
                "contract_id": f"588000P_FLOW_{int(event['option_code'])}",
                "contract_symbol": event.get("contract_symbol", ""),
                "entry_price": entry_price,
                "position_pct": args.position_pct,
                "signal_strength": "strong_put_flow_0945",
                "strategy_leg": "put_flow_0945",
                "dte": event.get("dte", 0),
                "delta": event.get("delta", 0),
                "implied_volatility": event.get("iv", 0),
                "iv_rank_252": 0,
                "volume15_to_prior5_daily": event.get("volume15_to_prior5_daily", 0),
                "etf_intraday_return": event.get("etf_intraday_return", 0),
                "exit_time": exit_info.get("exit_time"),
                "exit_price_1": exit_info.get("exit_price_1"),
                "exit_price_2": exit_info.get("exit_price_2"),
                "return": exit_info.get("return"),
                "exit_reason": exit_info.get("exit_reason"),
                "exit_legs": exit_info.get("exit_legs"),
                "tp1_time": exit_info.get("tp1_time", pd.NaT),
                "high_water": exit_info.get("high_water", pd.NA),
                "trailing_stop": exit_info.get("trailing_stop", pd.NA),
            }
        )
    return pd.DataFrame(rows)


def calc_capital(trades: pd.DataFrame, initial: float = 100000.0) -> tuple[pd.DataFrame, dict[str, Any]]:
    capital = initial
    rows: list[dict[str, Any]] = []
    for _, trade in trades.sort_values("entry_time").iterrows():
        entry = float(trade["entry_price"]) + 0.0001
        position_pct = float(trade["position_pct"])
        contracts = int((capital * position_pct) // (entry * 10000.0))
        if contracts <= 0:
            net_pnl = 0.0
            after = capital
        else:
            legs = []
            for part in str(trade["exit_legs"]).split(";"):
                if "@" in part:
                    weight, price = part.split("@", 1)
                    legs.append((float(weight), float(price)))
            if not legs:
                legs = [(1.0, float(trade["exit_price_2"]))]
            remaining = contracts
            gross_sell = 0.0
            for idx, (weight, price) in enumerate(legs):
                qty = remaining if idx == len(legs) - 1 else min(remaining, int(round(contracts * weight)))
                remaining -= qty
                gross_sell += qty * max(price - 0.0001, 0.0) * 10000.0
            premium = contracts * entry * 10000.0
            fee = contracts * 2.0 * 2.0
            net_pnl = gross_sell - premium - fee
            after = capital + net_pnl
        rows.append(
            {
                "trade_date": trade["trade_date"],
                "entry_time": trade["entry_time"],
                "direction": trade["direction"],
                "contract_id": trade["contract_id"],
                "position_pct": position_pct,
                "contracts": contracts,
                "net_pnl": net_pnl,
                "capital_before": capital,
                "capital_after": after,
                "exit_reason": trade["exit_reason"],
            }
        )
        capital = after
    curve = pd.concat([pd.Series([initial]), pd.Series([r["capital_after"] for r in rows])], ignore_index=True)
    drawdown = (curve.cummax() - curve) / curve.cummax() if len(curve) else pd.Series([0])
    active = pd.DataFrame(rows)
    summary = {
        "initial_capital": initial,
        "final_capital": capital,
        "total_return": capital / initial - 1,
        "trades": int(len(active)),
        "win_rate": float((active["net_pnl"] > 0).mean()) if not active.empty else 0.0,
        "max_drawdown": float(drawdown.max()),
        "net_pnl": capital - initial,
    }
    return active, summary


def main() -> None:
    args = parse_args()
    events = pd.read_csv(args.events)
    chosen = choose_events(events, args)
    if chosen.empty:
        raise SystemExit("No events selected")

    start = str(chosen["trade_date"].min())
    end = str(chosen["trade_date"].max())
    etf_15m = load_etf_15m(args.sqlite, ["588000"], start, end)

    trades = build_trade_rows(chosen, etf_15m, args)
    prefix = RESEARCH_DIR / args.output_prefix
    suffix = f"_th{args.threshold:g}_pos{args.position_pct:g}"
    if args.etf_up_min is not None:
        suffix += f"_etfup{args.etf_up_min:g}"
    if args.delta_min is not None or args.delta_max is not None:
        suffix += f"_delta{args.delta_min:g}_{args.delta_max:g}"

    trades_path = Path(f"{prefix}{suffix}_trades.csv")
    capital_path = Path(f"{prefix}{suffix}_capital.csv")
    summary_path = Path(f"{prefix}{suffix}_summary.csv")
    combined_trades_path = Path(f"{prefix}{suffix}_combined_trades.csv")
    combined_capital_path = Path(f"{prefix}{suffix}_combined_capital.csv")
    combined_summary_path = Path(f"{prefix}{suffix}_combined_summary.csv")

    trades.to_csv(trades_path, index=False)
    cap, summary = calc_capital(trades)
    cap.to_csv(capital_path, index=False)
    pd.DataFrame([summary]).to_csv(summary_path, index=False)

    if args.base_trades.exists():
        base = pd.read_csv(args.base_trades, parse_dates=["entry_time", "exit_time"])
        combined = pd.concat([base, trades], ignore_index=True, sort=False).sort_values("entry_time")
        combined.to_csv(combined_trades_path, index=False)
        ccap, csummary = calc_capital(combined)
        ccap.to_csv(combined_capital_path, index=False)
        pd.DataFrame([csummary]).to_csv(combined_summary_path, index=False)
    else:
        csummary = {}

    print("trades", trades_path)
    print(pd.DataFrame([summary]).to_string(index=False))
    if csummary:
        print("combined", combined_summary_path)
        print(pd.DataFrame([csummary]).to_string(index=False))


if __name__ == "__main__":
    main()
