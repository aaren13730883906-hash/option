#!/usr/bin/env python3
"""Pressure-test absolute premium caps for the 1759.55% KCB strategy.

This recalculates the capital curve from the existing trade audit file using
different absolute premium caps.  It keeps the signal sequence fixed and tests
whether each trade can be sized under:

- position percentage,
- optional absolute premium cap,
- optional 09:45 15-minute volume share cap for Put-reversal rows.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRADES = ROOT / "research" / "putrev_selection_capacity_aware_momentum_to_20260723_trades.csv"
DEFAULT_OUT = ROOT / "research" / "premium_cap_pressure_summary.csv"


def parse_legs(value: object) -> list[tuple[float, float]]:
    if not isinstance(value, str) or not value.strip():
        return []
    legs: list[tuple[float, float]] = []
    for part in value.split(";"):
        if "@" not in part:
            continue
        weight, price = part.split("@", 1)
        try:
            legs.append((float(weight), float(price)))
        except Exception:
            continue
    total = sum(weight for weight, _ in legs)
    if total <= 0:
        return []
    return [(weight / total, price) for weight, price in legs]


def max_drawdown(values: list[float]) -> float:
    peak = values[0]
    worst = 0.0
    for value in values:
        if value > peak:
            peak = value
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst


def recalc(
    trades: pd.DataFrame,
    premium_cap: float | None,
    volume_share_cap: float,
    scope: str,
    initial: float,
    slippage_tick: float,
) -> dict[str, float | int | str]:
    capital = initial
    curve = [initial]
    active_pnls: list[float] = []
    skipped_capacity = 0
    skipped_small = 0
    premium_used: list[float] = []
    contracts_used: list[int] = []
    putrev_trades = 0
    main_trades = 0

    for _, trade in trades.sort_values(["entry_time", "contract_id"]).iterrows():
        entry_mid = float(trade["entry_price"])
        entry_fill = entry_mid + slippage_tick
        position_pct = float(trade.get("position_pct", 0.0) or 0.0)
        leg = str(trade.get("strategy_leg", ""))
        is_putrev = leg == "put_reversal_0945"
        applies = scope == "all" or (scope == "put_reversal" and is_putrev)
        budget = capital * position_pct
        if applies and premium_cap is not None:
            budget = min(budget, premium_cap)
        planned = int(budget // (entry_fill * 10000.0)) if entry_fill > 0 else 0
        if planned <= 0:
            skipped_small += 1
            curve.append(capital)
            continue

        if is_putrev:
            volume15 = float(trade.get("volume15", 0.0) or 0.0)
            if volume15 <= 0 or planned > volume15 * volume_share_cap:
                skipped_capacity += 1
                curve.append(capital)
                continue

        premium = planned * entry_fill * 10000.0
        gross_sell = 0.0
        remaining = planned
        legs = parse_legs(trade.get("exit_legs"))
        if not legs:
            try:
                legs = [(1.0, float(trade["exit_price_2"]))]
            except Exception:
                legs = []
        for idx, (weight, mid) in enumerate(legs):
            qty = remaining if idx == len(legs) - 1 else min(remaining, int(round(planned * weight)))
            remaining -= qty
            fill = max(float(mid) - slippage_tick, 0.0)
            gross_sell += qty * fill * 10000.0
        fee = planned * 2.0 * 2.0
        net = gross_sell - premium - fee
        capital += net
        curve.append(capital)
        active_pnls.append(net)
        premium_used.append(premium)
        contracts_used.append(planned)
        if is_putrev:
            putrev_trades += 1
        else:
            main_trades += 1

    wins = sum(1 for pnl in active_pnls if pnl > 0)
    return {
        "scope": scope,
        "premium_cap": "none" if premium_cap is None else int(premium_cap),
        "volume_share_cap_pct": volume_share_cap * 100.0,
        "final_capital": capital,
        "total_return_pct": (capital / initial - 1.0) * 100.0,
        "trades": len(active_pnls),
        "main_or_fallback_trades": main_trades,
        "put_reversal_trades": putrev_trades,
        "skipped_capacity": skipped_capacity,
        "skipped_small_budget": skipped_small,
        "win_rate_pct": wins / len(active_pnls) * 100.0 if active_pnls else 0.0,
        "max_dd_pct": max_drawdown(curve) * 100.0,
        "max_premium_used": max(premium_used) if premium_used else 0.0,
        "avg_premium_used": sum(premium_used) / len(premium_used) if premium_used else 0.0,
        "max_contracts": max(contracts_used) if contracts_used else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trades", default=str(DEFAULT_TRADES))
    parser.add_argument("--output", default=str(DEFAULT_OUT))
    parser.add_argument("--initial", type=float, default=100000.0)
    parser.add_argument("--slippage-tick", type=float, default=0.0003)
    parser.add_argument("--caps", default="none,50000,100000,150000,200000,300000")
    parser.add_argument("--volume-share-caps", default="0.03,0.05")
    args = parser.parse_args()

    trades = pd.read_csv(args.trades, parse_dates=["entry_time", "exit_time"])
    caps: list[float | None] = []
    for item in args.caps.split(","):
        item = item.strip().lower()
        if item in ["", "none", "null"]:
            caps.append(None)
        else:
            caps.append(float(item))
    share_caps = [float(item) for item in args.volume_share_caps.split(",") if item.strip()]

    rows = []
    for scope in ["put_reversal", "all"]:
        for share in share_caps:
            for cap in caps:
                rows.append(
                    recalc(
                        trades,
                        premium_cap=cap,
                        volume_share_cap=share,
                        scope=scope,
                        initial=args.initial,
                        slippage_tick=args.slippage_tick,
                    )
                )
    out = pd.DataFrame(rows)
    out.to_csv(args.output, index=False)
    print(out.to_string(index=False))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
