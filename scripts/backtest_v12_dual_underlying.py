#!/usr/bin/env python3
"""Combine 588000 v1.1 and 159915 v1.1 trades into the dual-ETF strategy.

If both underlyings trade on the same date, retain only the ETF with the higher
normalized opening-strength score. Position exits remain independent.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from calc_capital_backtest import parse_exit_legs


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--kcb-trades",
        type=Path,
        default=RESEARCH / "backtest_v11_opening_plus_strong15m_trades.csv",
    )
    parser.add_argument(
        "--cyb-trades",
        type=Path,
        default=RESEARCH / "backtest_v12_159915_opening_trades.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=RESEARCH / "backtest_v12_dual_underlying_trades.csv",
    )
    parser.add_argument(
        "--capital-output",
        type=Path,
        default=RESEARCH / "backtest_v12_dual_underlying_capital.csv",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=RESEARCH / "backtest_v12_dual_underlying_summary.csv",
    )
    parser.add_argument("--initial-capital", type=float, default=100000.0)
    parser.add_argument("--start-date", default="2025-07-04")
    parser.add_argument("--end-date", default="2026-05-25")
    parser.add_argument("--contract-multiplier", type=float, default=10000.0)
    parser.add_argument("--fee-per-contract-side", type=float, default=2.0)
    parser.add_argument("--slippage-tick", type=float, default=0.0001)
    return parser.parse_args()


def trade_pnl(
    trade: pd.Series,
    capital: float,
    multiplier: float,
    fee_per_side: float,
    slippage_tick: float,
) -> dict[str, object]:
    entry_mid = float(trade["entry_price"])
    entry_fill = entry_mid + slippage_tick
    position_pct = float(trade["position_pct"])
    contracts = int((capital * position_pct) // (entry_fill * multiplier))
    premium = contracts * entry_fill * multiplier
    legs = parse_exit_legs(trade.get("exit_legs"))
    if not legs:
        exit1 = float(trade["exit_price_1"])
        exit2 = float(trade["exit_price_2"])
        legs = [(0.5, exit1), (0.5, exit2)] if abs(exit1 - exit2) > 1e-12 else [(1.0, exit2)]

    remaining = contracts
    gross_sell = 0.0
    fills: list[str] = []
    for idx, (weight, mid_price) in enumerate(legs):
        if idx == len(legs) - 1:
            count = remaining
        else:
            count = min(int(round(contracts * weight)), remaining)
        remaining -= count
        fill = max(float(mid_price) - slippage_tick, 0.0)
        gross_sell += count * fill * multiplier
        fills.append(f"{count}@{fill:.6f}")
    fee = contracts * fee_per_side * 2
    net_pnl = gross_sell - premium - fee
    return {
        "contracts": contracts,
        "entry_fill": entry_fill,
        "premium": premium,
        "fee": fee,
        "gross_pnl": gross_sell - premium,
        "net_pnl": net_pnl,
        "return_on_premium": net_pnl / premium if premium else 0.0,
        "exit_fills": ";".join(fills),
    }


def main() -> None:
    args = parse_args()
    kcb = pd.read_csv(args.kcb_trades)
    cyb = pd.read_csv(args.cyb_trades)
    kcb = kcb[kcb["trade_date"].astype(str).between(args.start_date, args.end_date)].copy()
    cyb = cyb[cyb["trade_date"].astype(str).between(args.start_date, args.end_date)].copy()
    kcb["strategy_source"] = "588000_v1.1"
    cyb["strategy_source"] = "159915_v1.1"
    trades = pd.concat([kcb, cyb], ignore_index=True, sort=False)
    trades["trade_date"] = trades["trade_date"].astype(str)
    trades["entry_time"] = pd.to_datetime(trades["entry_time"])
    trades["position_pct_standalone"] = pd.to_numeric(trades["position_pct"])

    thresholds = {
        "588000": {"range": 0.0030, "volume": 1.30},
        "159915": {"range": 0.0025, "volume": 1.25},
    }
    trades["opening_strength_score"] = pd.NA
    for idx, trade in trades.iterrows():
        underlying = str(trade["underlying_code"])
        params = thresholds[underlying]
        amp = pd.to_numeric(trade.get("opening_amp"), errors="coerce")
        volume = pd.to_numeric(trade.get("breakout_vol_ratio"), errors="coerce")
        if pd.notna(amp) and pd.notna(volume):
            trades.loc[idx, "opening_strength_score"] = (
                float(amp) / params["range"]
            ) * (float(volume) / params["volume"])

    overlapping_dates = set(
        trades.groupby("trade_date")["underlying_code"].nunique().loc[lambda s: s > 1].index
    )
    trades["dual_signal_date"] = trades["trade_date"].isin(overlapping_dates)
    selected_rows: list[pd.DataFrame] = []
    for trade_date, day in trades.groupby("trade_date", sort=True):
        if len(day["underlying_code"].unique()) == 1:
            selected_rows.append(day)
            continue
        ranked = day.sort_values(
            ["opening_strength_score", "underlying_code"],
            ascending=[False, True],
            na_position="last",
        )
        selected_rows.append(ranked.head(1))
    trades = pd.concat(selected_rows, ignore_index=True)
    trades["selection_rule"] = "single_signal"
    trades.loc[trades["dual_signal_date"], "selection_rule"] = "stronger_opening_only"
    trades = trades.sort_values(["trade_date", "entry_time", "underlying_code"]).reset_index(drop=True)
    trades.to_csv(args.output, index=False)

    capital = args.initial_capital
    capital_rows: list[dict[str, object]] = []
    daily_curve = [capital]
    for trade_date, day in trades.groupby("trade_date", sort=True):
        day_start = capital
        day_pnl = 0.0
        calculated: list[tuple[pd.Series, dict[str, object]]] = []
        for _, trade in day.iterrows():
            pnl = trade_pnl(
                trade,
                day_start,
                args.contract_multiplier,
                args.fee_per_contract_side,
                args.slippage_tick,
            )
            day_pnl += float(pnl["net_pnl"])
            calculated.append((trade, pnl))
        capital += day_pnl
        daily_curve.append(capital)
        for trade, pnl in calculated:
            capital_rows.append(
                {
                    "trade_date": trade_date,
                    "underlying_code": trade["underlying_code"],
                    "direction": trade["direction"],
                    "entry_time": trade["entry_time"],
                    "contract_id": trade["contract_id"],
                    "strategy_source": trade["strategy_source"],
                    "dual_signal_date": trade["dual_signal_date"],
                    "position_pct_standalone": trade["position_pct_standalone"],
                    "position_pct": trade["position_pct"],
                    "exit_reason": trade["exit_reason"],
                    **pnl,
                    "capital_before_day": day_start,
                    "day_net_pnl": day_pnl,
                    "capital_after_day": capital,
                }
            )

    capital_df = pd.DataFrame(capital_rows)
    capital_df.to_csv(args.capital_output, index=False)
    curve = pd.Series(daily_curve)
    drawdown = (curve.cummax() - curve) / curve.cummax()
    summary = {
        "strategy_version": "v1.2_dual_underlying",
        "underlying": "588000+159915",
        "start": args.start_date,
        "end": args.end_date,
        "initial_capital": args.initial_capital,
        "final_capital": capital,
        "net_pnl": capital - args.initial_capital,
        "total_return": capital / args.initial_capital - 1,
        "trades": len(capital_df),
        "kcb_trades": int((capital_df["underlying_code"].astype(str) == "588000").sum()),
        "cyb_trades": int((capital_df["underlying_code"].astype(str) == "159915").sum()),
        "resolved_overlap_dates": len(overlapping_dates),
        "win_rate_net": float((capital_df["net_pnl"] > 0).mean()),
        "total_fees": float(capital_df["fee"].sum()),
        "max_drawdown": float(drawdown.max()),
        "overlap_policy": "higher normalized opening strength only",
    }
    pd.DataFrame([summary]).to_csv(args.summary, index=False)
    print(pd.DataFrame([summary]).to_string(index=False))


if __name__ == "__main__":
    main()
