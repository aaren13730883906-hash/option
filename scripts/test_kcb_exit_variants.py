#!/usr/bin/env python3
"""Fast exit-rule sensitivity test for fixed KCB option entries.

This script intentionally keeps the entry list fixed and only recalculates
option exits from cached 1m bars.  It is for diagnosing take-profit rules.
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
from analyze_kcb_50pct_opportunity_patterns import load_option_1m  # noqa: E402


RESEARCH = ROOT / "research"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trades", type=Path, default=RESEARCH / "sens_fallback_call_momentum_p08_r3_v70_trades.csv")
    parser.add_argument("--output-prefix", default="exit_variant_kcb_base621")
    parser.add_argument("--initial-capital", type=float, default=100000.0)
    parser.add_argument("--contract-multiplier", type=float, default=10000.0)
    parser.add_argument("--fee-per-contract-side", type=float, default=2.0)
    parser.add_argument("--slippage-tick", type=float, default=0.0001)
    return parser.parse_args()


def is_strong(value: object) -> bool:
    return str(value).startswith("strong")


def etf_reversal_at(etf15: pd.DataFrame, when: pd.Timestamp, direction: str) -> bool:
    row = etf15[etf15["datetime"] <= when].tail(1)
    if row.empty:
        return False
    e = row.iloc[0]
    if direction == "call":
        return (
            pd.notna(e.get("ema20"))
            and pd.notna(e.get("ema20_slope"))
            and e["close"] < e["ema20"]
            and e["ema20_slope"] < 0
        )
    return (
        pd.notna(e.get("ema20"))
        and pd.notna(e.get("ema20_slope"))
        and e["close"] > e["ema20"]
        and e["ema20_slope"] > 0
    )


def exit_to_dict(
    exit_time: pd.Timestamp,
    exit_price_1: float,
    exit_price_2: float,
    ret: float,
    reason: str,
    legs: str,
    tp1_time: Any = pd.NaT,
    high_water: float | None = None,
    trailing_stop: float | None = None,
) -> dict[str, Any]:
    out = {
        "exit_time": exit_time,
        "exit_price_1": exit_price_1,
        "exit_price_2": exit_price_2,
        "return": ret,
        "exit_reason": reason,
        "exit_legs": legs,
        "tp1_time": tp1_time,
    }
    if high_water is not None:
        out["high_water"] = high_water
    if trailing_stop is not None:
        out["trailing_stop"] = trailing_stop
    return out


def simulate_exit_variant(
    bars_1m: pd.DataFrame,
    etf15: pd.DataFrame,
    trade: pd.Series,
    variant: dict[str, Any],
) -> dict[str, Any]:
    entry_time = pd.Timestamp(trade["entry_time"])
    entry_price = float(trade["entry_price"])
    direction = str(trade["direction"])
    strong = is_strong(trade.get("signal_strength", ""))
    stop = entry_price * 0.70
    default_soft = 0.75 if str(trade.get("strategy_leg")) == "opening_primary" else 0.82
    default_delay = 5 if str(trade.get("strategy_leg")) == "opening_primary" else 0
    soft_stop = entry_price * float(variant.get("soft_stop_pct", default_soft))
    soft_stop_ts = entry_time + pd.Timedelta(minutes=int(variant.get("soft_delay", default_delay)))
    eod = pd.Timestamp(f"{entry_time:%Y-%m-%d} 14:55:00")

    bars = bars_1m.copy()
    if "ema5" not in bars.columns:
        bars["ema5"] = bars["close"].ewm(span=5, adjust=False).mean()
    path = bars[(bars["datetime"] > entry_time) & (bars["datetime"] <= eod)].copy()
    if path.empty:
        return exit_to_dict(entry_time, entry_price, entry_price, 0.0, "no_path", f"1.0@{entry_price:.6f}")

    normal_runner = bool(variant.get("normal_runner", False)) and not strong
    normal_runner_only_opening = bool(variant.get("normal_runner_only_opening", False))
    if normal_runner and normal_runner_only_opening and str(trade.get("strategy_leg")) != "opening_primary":
        normal_runner = False

    if not strong and not normal_runner:
        tp1 = entry_price * 1.35
        tp2 = entry_price * float(variant.get("normal_tp2", 1.80))
        half_done = False
        exit1_price = math.nan
        exit1_time = pd.NaT
        for row in path.itertuples(index=False):
            opt_weak = pd.notna(row.ema5) and row.close < row.ema5
            reversal = etf_reversal_at(etf15, row.datetime, direction)
            if row.datetime >= soft_stop_ts and not half_done and row.low <= soft_stop and (opt_weak or reversal):
                return exit_to_dict(row.datetime, soft_stop, soft_stop, soft_stop / entry_price - 1, "soft_stop", f"1.0@{soft_stop:.6f}")
            if row.low <= stop:
                if not half_done:
                    return exit_to_dict(row.datetime, stop, stop, -0.30, "stop", f"1.0@{stop:.6f}")
                ret = 0.5 * (exit1_price / entry_price - 1) + 0.5 * (stop / entry_price - 1)
                return exit_to_dict(row.datetime, exit1_price, stop, ret, "stop_after_tp1", f"0.5@{exit1_price:.6f};0.5@{stop:.6f}", exit1_time)
            if not half_done and row.high >= tp1:
                half_done = True
                exit1_price = tp1
                exit1_time = row.datetime
            if half_done and row.high >= tp2:
                ret = 0.5 * (exit1_price / entry_price - 1) + 0.5 * (tp2 / entry_price - 1)
                return exit_to_dict(row.datetime, exit1_price, tp2, ret, "tp2", f"0.5@{exit1_price:.6f};0.5@{tp2:.6f}", exit1_time)
        last = path.iloc[-1]
        if not half_done:
            return exit_to_dict(last["datetime"], last["close"], last["close"], last["close"] / entry_price - 1, "eod", f"1.0@{last['close']:.6f}")
        ret = 0.5 * (exit1_price / entry_price - 1) + 0.5 * (last["close"] / entry_price - 1)
        return exit_to_dict(last["datetime"], exit1_price, last["close"], ret, "tp1_eod", f"0.5@{exit1_price:.6f};0.5@{last['close']:.6f}", exit1_time)

    if normal_runner:
        tp1 = entry_price * float(variant.get("normal_runner_tp1", 1.35))
        first_weight = float(variant.get("normal_runner_first_weight", 0.50))
        runner_weight = 1.0 - first_weight
        first_done = False
        exit1_price = math.nan
        exit1_time = pd.NaT
        high_water = entry_price
        trailing_stop = stop
        trail_before = float(variant.get("normal_runner_trail_before_1030", 0.35))
        trail_after = float(variant.get("normal_runner_trail_after_1030", 0.25))
        for row in path.itertuples(index=False):
            high_water = max(high_water, float(row.high))
            opt_weak = pd.notna(row.ema5) and row.close < row.ema5
            reversal = etf_reversal_at(etf15, row.datetime, direction)
            if row.datetime >= soft_stop_ts and not first_done and row.low <= soft_stop and (opt_weak or reversal):
                return exit_to_dict(row.datetime, soft_stop, soft_stop, soft_stop / entry_price - 1, "soft_stop", f"1.0@{soft_stop:.6f}", high_water=high_water)
            if row.low <= stop:
                if not first_done:
                    return exit_to_dict(row.datetime, stop, stop, -0.30, "stop", f"1.0@{stop:.6f}", high_water=high_water)
                ret = first_weight * (exit1_price / entry_price - 1) + runner_weight * (stop / entry_price - 1)
                return exit_to_dict(row.datetime, exit1_price, stop, ret, "runner_stop_after_tp1", f"{first_weight:.6f}@{exit1_price:.6f};{runner_weight:.6f}@{stop:.6f}", exit1_time, high_water)
            if not first_done and row.high >= tp1:
                first_done = True
                exit1_price = tp1
                exit1_time = row.datetime
                high_water = max(high_water, tp1)
            if first_done:
                trail_pct = trail_before if pd.Timestamp(row.datetime).time() < pd.Timestamp("10:30").time() else trail_after
                trailing_stop = max(trailing_stop, high_water * (1.0 - trail_pct))
                if row.low <= trailing_stop:
                    ret = first_weight * (exit1_price / entry_price - 1) + runner_weight * (trailing_stop / entry_price - 1)
                    return exit_to_dict(row.datetime, exit1_price, trailing_stop, ret, f"normal_runner_trail_{trail_pct:.0%}", f"{first_weight:.6f}@{exit1_price:.6f};{runner_weight:.6f}@{trailing_stop:.6f}", exit1_time, high_water, trailing_stop)
        last = path.iloc[-1]
        if not first_done:
            return exit_to_dict(last["datetime"], last["close"], last["close"], last["close"] / entry_price - 1, "eod", f"1.0@{last['close']:.6f}", high_water=high_water)
        ret = first_weight * (exit1_price / entry_price - 1) + runner_weight * (last["close"] / entry_price - 1)
        return exit_to_dict(last["datetime"], exit1_price, last["close"], ret, "normal_runner_eod", f"{first_weight:.6f}@{exit1_price:.6f};{runner_weight:.6f}@{last['close']:.6f}", exit1_time, high_water, trailing_stop)

    # Strong path.
    tp1 = entry_price * 1.50
    first_done = False
    exit1_price = math.nan
    exit1_time = pd.NaT
    high_water = entry_price
    trailing_stop = stop
    trail_before = float(variant.get("strong_trail_before_1030", 0.35))
    trail_after = float(variant.get("strong_trail_after_1030", 0.20))
    crash_put_delay = str(variant.get("high_iv_put_no_trail_before", ""))
    for row in path.itertuples(index=False):
        high_water = max(high_water, float(row.high))
        opt_weak = pd.notna(row.ema5) and row.close < row.ema5
        reversal = etf_reversal_at(etf15, row.datetime, direction)
        if row.datetime >= soft_stop_ts and not first_done and row.low <= soft_stop and (opt_weak or reversal):
            return exit_to_dict(row.datetime, soft_stop, soft_stop, soft_stop / entry_price - 1, "soft_stop", f"1.0@{soft_stop:.6f}", high_water=high_water)
        if row.low <= stop:
            if not first_done:
                return exit_to_dict(row.datetime, stop, stop, -0.30, "stop", f"1.0@{stop:.6f}", high_water=high_water)
            ret = (1 / 3) * (exit1_price / entry_price - 1) + (2 / 3) * (stop / entry_price - 1)
            return exit_to_dict(row.datetime, exit1_price, stop, ret, "stop_after_tp1", f"0.333333@{exit1_price:.6f};0.666667@{stop:.6f}", exit1_time, high_water)
        if not first_done and row.high >= tp1:
            first_done = True
            exit1_price = tp1
            exit1_time = row.datetime
            high_water = max(high_water, tp1)
        if first_done:
            high_iv_value = str(trade.get("high_iv_crash_put", False)).strip().lower()
            is_high_iv_crash_put = direction == "put" and high_iv_value in ["true", "1", "yes"]
            if is_high_iv_crash_put and crash_put_delay and pd.Timestamp(row.datetime).strftime("%H:%M") < crash_put_delay:
                continue
            trail_pct = trail_before if pd.Timestamp(row.datetime).time() < pd.Timestamp("10:30").time() else trail_after
            trailing_stop = max(trailing_stop, high_water * (1.0 - trail_pct))
            if row.low <= trailing_stop:
                ret = (1 / 3) * (exit1_price / entry_price - 1) + (2 / 3) * (trailing_stop / entry_price - 1)
                return exit_to_dict(row.datetime, exit1_price, trailing_stop, ret, f"trail_{trail_pct:.0%}", f"0.333333@{exit1_price:.6f};0.666667@{trailing_stop:.6f}", exit1_time, high_water, trailing_stop)
    last = path.iloc[-1]
    if not first_done:
        return exit_to_dict(last["datetime"], last["close"], last["close"], last["close"] / entry_price - 1, "eod", f"1.0@{last['close']:.6f}", high_water=high_water)
    ret = (1 / 3) * (exit1_price / entry_price - 1) + (2 / 3) * (last["close"] / entry_price - 1)
    return exit_to_dict(last["datetime"], exit1_price, last["close"], ret, "tp1_eod", f"0.333333@{exit1_price:.6f};0.666667@{last['close']:.6f}", exit1_time, high_water, trailing_stop)


def calculate_capital(trades: pd.DataFrame, args: argparse.Namespace) -> dict[str, Any]:
    capital = args.initial_capital
    daily_pnl: dict[str, float] = {}
    curve = [capital]
    rows = []
    for _, trade in trades.sort_values("entry_time").iterrows():
        trade_date = str(trade["trade_date"])
        if daily_pnl.get(trade_date, 0.0) <= -args.initial_capital * 0.05:
            rows.append({"skipped": True, "capital_before": capital, "capital_after": capital, "net_pnl": 0.0})
            continue
        entry_mid = float(trade["entry_price"])
        entry_fill = entry_mid + args.slippage_tick
        position_pct = float(trade.get("position_pct", 0.10))
        contracts = int((capital * position_pct) // (entry_fill * args.contract_multiplier))
        premium = contracts * entry_fill * args.contract_multiplier
        gross_sell = 0.0
        legs = bt.parse_exit_legs(trade.get("exit_legs")) if hasattr(bt, "parse_exit_legs") else []
        if not legs:
            legs = []
            for part in str(trade["exit_legs"]).split(";"):
                if "@" in part:
                    weight, price = part.split("@", 1)
                    legs.append((float(weight), float(price)))
        total = sum(w for w, _ in legs) or 1.0
        legs = [(w / total, p) for w, p in legs]
        remaining = contracts
        for idx, (weight, mid_price) in enumerate(legs):
            if idx == len(legs) - 1:
                leg_contracts = remaining
            else:
                leg_contracts = min(int(round(contracts * weight)), remaining)
            remaining -= leg_contracts
            gross_sell += leg_contracts * max(mid_price - args.slippage_tick, 0.0) * args.contract_multiplier
        fee = contracts * args.fee_per_contract_side * 2
        net_pnl = gross_sell - premium - fee
        before = capital
        capital += net_pnl
        daily_pnl[trade_date] = daily_pnl.get(trade_date, 0.0) + net_pnl
        curve.append(capital)
        rows.append(
            {
                "skipped": False,
                "capital_before": before,
                "capital_after": capital,
                "net_pnl": net_pnl,
                "contracts": contracts,
            }
        )
    curve_s = pd.Series(curve)
    dd = (curve_s.cummax() - curve_s) / curve_s.cummax()
    active = pd.DataFrame(rows)
    active = active[~active["skipped"].fillna(False)] if not active.empty else active
    return {
        "final_capital": capital,
        "total_return": capital / args.initial_capital - 1.0,
        "trades": int(len(active)),
        "win_rate": float((active["net_pnl"] > 0).mean()) if not active.empty else 0.0,
        "max_drawdown": float(dd.max()),
        "best_net_pnl": float(active["net_pnl"].max()) if not active.empty else 0.0,
        "worst_net_pnl": float(active["net_pnl"].min()) if not active.empty else 0.0,
    }


def variant_grid() -> list[dict[str, Any]]:
    variants = [{"name": "base_fixed_normal_strong_trail20"}]
    for trail in [0.20, 0.25, 0.30, 0.35, 0.40]:
        variants.append(
            {
                "name": f"opening_normal_runner_trail{int(trail*100)}",
                "normal_runner": True,
                "normal_runner_only_opening": True,
                "normal_runner_trail_after_1030": trail,
            }
        )
    for weight in [0.33, 0.50, 0.65]:
        variants.append(
            {
                "name": f"opening_normal_runner_w{int(weight*100)}_trail30",
                "normal_runner": True,
                "normal_runner_only_opening": True,
                "normal_runner_first_weight": weight,
                "normal_runner_trail_after_1030": 0.30,
            }
        )
    for tp2 in [2.0, 2.2, 2.5, 3.0]:
        variants.append({"name": f"normal_fixed_tp2_{tp2:.1f}", "normal_tp2": tp2})
    for trail in [0.25, 0.30, 0.35, 0.40, 0.45]:
        variants.append({"name": f"strong_trail_after_{int(trail*100)}", "strong_trail_after_1030": trail})
    for delay in ["10:00", "10:05", "10:15", "10:30"]:
        variants.append({"name": f"highiv_put_no_trail_before_{delay.replace(':','')}", "high_iv_put_no_trail_before": delay})
    for trail in [0.25, 0.30, 0.35]:
        variants.append(
            {
                "name": f"runner_trail{int(trail*100)}_put_delay1005",
                "normal_runner": True,
                "normal_runner_only_opening": True,
                "normal_runner_trail_after_1030": trail,
                "high_iv_put_no_trail_before": "10:05",
            }
        )
    return variants


def main() -> None:
    args = parse_args()
    trades = pd.read_csv(args.trades, parse_dates=["entry_time", "exit_time"])
    start = pd.to_datetime(trades["trade_date"]).min().strftime("%Y-%m-%d")
    end = pd.to_datetime(trades["trade_date"]).max().strftime("%Y-%m-%d")
    etf15_all = bt.load_etf_15m(bt.DEFAULT_SQLITE, ["588000"], start, end)
    etf15_all = etf15_all[etf15_all["underlying_code"].astype(str) == "588000"].copy()

    option_cache: dict[tuple[str, str], pd.DataFrame] = {}
    summary_rows = []
    detail_outputs = {}
    for variant in variant_grid():
        recalced = []
        for _, trade in trades.iterrows():
            trade_date = str(trade["trade_date"])
            option_code = str(int(float(trade["option_code"]))).zfill(8)
            key = (trade_date, option_code)
            if key not in option_cache:
                option_cache[key] = load_option_1m(trade_date, option_code)
            bars = option_cache[key]
            etf15 = etf15_all[etf15_all["trade_date"] == trade_date]
            exit_info = simulate_exit_variant(bars, etf15, trade, variant)
            row = trade.to_dict()
            row.update(exit_info)
            recalced.append(row)
        out = pd.DataFrame(recalced)
        cap = calculate_capital(out, args)
        summary_rows.append({"variant": variant["name"], **cap})
        detail_outputs[variant["name"]] = out

    summary = pd.DataFrame(summary_rows).sort_values(["total_return", "max_drawdown"], ascending=[False, True])
    summary_path = RESEARCH / f"{args.output_prefix}_summary.csv"
    summary.to_csv(summary_path, index=False)
    for save_name in ["base_fixed_normal_strong_trail20", "opening_normal_runner_trail35", "opening_normal_runner_trail40", str(summary.iloc[0]["variant"])]:
        detail_outputs[save_name].to_csv(RESEARCH / f"{args.output_prefix}_{save_name}_trades.csv", index=False)
    best_name = str(summary.iloc[0]["variant"])
    best_path = RESEARCH / f"{args.output_prefix}_{best_name}_trades.csv"
    print(summary.head(20).to_string(index=False))
    print(f"Wrote {summary_path}")
    print(f"Wrote {best_path}")


if __name__ == "__main__":
    main()
