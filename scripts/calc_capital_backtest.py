#!/usr/bin/env python3
"""Calculate capital curve for option intraday backtest trades."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = ROOT / "research"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trades", type=Path, default=RESEARCH_DIR / "backtest_v05_588000_recent1m_trades.csv")
    parser.add_argument("--output", type=Path, default=RESEARCH_DIR / "backtest_v05_588000_capital_100k.csv")
    parser.add_argument("--summary", type=Path, default=RESEARCH_DIR / "backtest_v05_588000_capital_100k_summary.csv")
    parser.add_argument("--initial-capital", type=float, default=100000.0)
    parser.add_argument("--contract-multiplier", type=float, default=10000.0)
    parser.add_argument("--fee-per-contract-side", type=float, default=2.0)
    parser.add_argument("--slippage-tick", type=float, default=0.0001)
    parser.add_argument("--daily-loss-limit-pct", type=float, default=0.05)
    parser.add_argument("--strategy-version", default="v1.0B")
    return parser.parse_args()


def parse_exit_legs(value: object) -> list[tuple[float, float]]:
    if isinstance(value, str) and value.strip():
        legs: list[tuple[float, float]] = []
        for part in value.split(";"):
            weight, price = part.split("@", 1)
            legs.append((float(weight), float(price)))
        total = sum(weight for weight, _ in legs)
        if total > 0:
            return [(weight / total, price) for weight, price in legs]
    return []


def main() -> None:
    args = parse_args()
    trades = pd.read_csv(args.trades, parse_dates=["entry_time", "exit_time"])
    capital = args.initial_capital
    rows: list[dict[str, object]] = []
    daily_pnl: dict[str, float] = {}

    for _, trade in trades.sort_values("entry_time").iterrows():
        trade_date = str(trade["trade_date"])
        day_loss_limit = -args.initial_capital * args.daily_loss_limit_pct
        if daily_pnl.get(trade_date, 0.0) <= day_loss_limit:
            rows.append(
                {
                    "trade_date": trade_date,
                    "entry_time": trade["entry_time"],
                    "contract_id": trade["contract_id"],
                    "skipped": True,
                    "skip_reason": "daily_loss_limit",
                    "capital_before": capital,
                    "capital_after": capital,
                    "net_pnl": 0.0,
                }
            )
            continue

        entry_mid = float(trade["entry_price"])
        entry_fill = entry_mid + args.slippage_tick
        position_pct = float(trade.get("position_pct", 0.10))
        contracts = int((capital * position_pct) // (entry_fill * args.contract_multiplier))
        premium = contracts * entry_fill * args.contract_multiplier

        legs = parse_exit_legs(trade.get("exit_legs"))
        if not legs:
            exit1_mid = float(trade["exit_price_1"])
            exit2_mid = float(trade["exit_price_2"])
            if abs(exit1_mid - exit2_mid) > 1e-12:
                legs = [(0.5, exit1_mid), (0.5, exit2_mid)]
            else:
                legs = [(1.0, exit2_mid)]
        remaining = contracts
        gross_sell = 0.0
        exit_leg_text: list[str] = []
        for idx, (weight, mid_price) in enumerate(legs):
            if idx == len(legs) - 1:
                leg_contracts = remaining
            else:
                leg_contracts = int(round(contracts * weight))
                leg_contracts = min(leg_contracts, remaining)
            remaining -= leg_contracts
            fill_price = max(mid_price - args.slippage_tick, 0.0)
            gross_sell += leg_contracts * fill_price * args.contract_multiplier
            exit_leg_text.append(f"{leg_contracts}@{fill_price:.6f}")
        fee = contracts * args.fee_per_contract_side + contracts * args.fee_per_contract_side
        net_pnl = gross_sell - premium - fee
        capital_before = capital
        capital += net_pnl
        daily_pnl[trade_date] = daily_pnl.get(trade_date, 0.0) + net_pnl

        rows.append(
            {
                "trade_date": trade_date,
                "underlying_code": trade["underlying_code"],
                "direction": trade["direction"],
                "entry_time": trade["entry_time"],
                "contract_id": trade["contract_id"],
                "dte": trade["dte"],
                "delta": trade["delta"],
                "iv_rank_252": trade["iv_rank_252"],
                "implied_volatility": trade["implied_volatility"],
                "signal_strength": trade.get("signal_strength", ""),
                "position_pct": position_pct,
                "entry_mid": entry_mid,
                "entry_fill": entry_fill,
                "exit_reason": trade["exit_reason"],
                "exit_legs": trade.get("exit_legs", ""),
                "exit_fills": ";".join(exit_leg_text),
                "contracts": contracts,
                "premium": premium,
                "fee": fee,
                "gross_pnl": gross_sell - premium,
                "net_pnl": net_pnl,
                "return_on_premium": net_pnl / premium if premium else 0.0,
                "daily_pnl_after": daily_pnl[trade_date],
                "capital_before": capital_before,
                "capital_after": capital,
                "skipped": False,
                "skip_reason": "",
            }
        )

    out = pd.DataFrame(rows)
    out.to_csv(args.output, index=False)
    active = out[~out["skipped"].fillna(False)].copy() if not out.empty else out
    underlying = (
        ",".join(sorted(active["underlying_code"].dropna().astype(str).unique()))
        if not active.empty and "underlying_code" in active
        else ""
    )
    if not active.empty:
        curve = pd.concat([pd.Series([args.initial_capital]), active["capital_after"]], ignore_index=True)
        drawdown = (curve.cummax() - curve) / curve.cummax()
        summary = {
            "strategy_version": args.strategy_version,
            "underlying": underlying,
            "initial_capital": args.initial_capital,
            "final_capital": capital,
            "net_pnl": capital - args.initial_capital,
            "total_return": capital / args.initial_capital - 1,
            "trades": int(len(active)),
            "skipped_trades": int(out["skipped"].fillna(False).sum()),
            "win_rate_net": float((active["net_pnl"] > 0).mean()),
            "avg_net_pnl": float(active["net_pnl"].mean()),
            "median_net_pnl": float(active["net_pnl"].median()),
            "best_net_pnl": float(active["net_pnl"].max()),
            "worst_net_pnl": float(active["net_pnl"].min()),
            "total_fees": float(active["fee"].sum()),
            "max_drawdown": float(drawdown.max()),
        }
    else:
        summary = {
            "strategy_version": args.strategy_version,
            "underlying": underlying,
            "initial_capital": args.initial_capital,
            "final_capital": capital,
            "net_pnl": 0.0,
            "total_return": 0.0,
            "trades": 0,
            "skipped_trades": 0,
        }
    pd.DataFrame([summary]).to_csv(args.summary, index=False)
    print(pd.DataFrame([summary]).to_string(index=False))


if __name__ == "__main__":
    main()
