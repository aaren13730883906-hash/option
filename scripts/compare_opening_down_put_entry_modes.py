#!/usr/bin/env python3
"""Compare opening-down put entry modes.

Modes:
- direct_0945: buy put at 09:45 after the opening-down condition.
- direct_0950: buy put at 09:50 after the same condition.
- direct_1000: buy put at 10:00 after the same condition.
- pullback_fail: wait until a weak rebound / sideways pause fails.

All modes keep position_pct fixed at 20%.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import math

import pandas as pd

from backtest_kcb_put_reversal_0945 import calc_capital
from test_opening_put_pullback_fail import (
    BASE_TRADES_CSV,
    DEFAULT_SQLITE,
    EVENTS_CSV,
    POSITION_PCT,
    UNDERLYING,
    build_early_etf_stats,
    cached_option_1m,
    detect_trigger,
    load_etf_5m,
    select_put_contract,
)
from test_put_reversal_hold_winners import simulate_putrev_baseline_1445


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = ROOT / "research"
SUMMARY_CSV = RESEARCH_DIR / "opening_down_put_entry_modes_summary.csv"
TRADES_CSV = RESEARCH_DIR / "opening_down_put_entry_modes_trades.csv"


DROP_MIN = 0.006
CLOSE_POS_MAX = 0.35
REBOUND_MAX = 0.005
BREAK_CONFIRM = 0.001
PULLBACK_SCAN_END = "10:00"


def fmt_legs(legs: list[tuple[float, float]]) -> str:
    return ";".join(f"{weight:.6f}@{price:.6f}" for weight, price in legs)


def simulate_fast_opening_put_exit(
    bars: pd.DataFrame,
    entry_time: pd.Timestamp,
    entry_price: float,
    *,
    stop_factor: float = 0.88,
    tp1_factor: float = 1.20,
    strong_factor: float = 1.35,
    strong_trail: float = 0.12,
) -> dict[str, Any]:
    eod = pd.Timestamp(f"{entry_time:%Y-%m-%d} 14:45:00")
    path = bars[(bars["datetime"] > entry_time) & (bars["datetime"] <= eod)].copy()
    if path.empty:
        return {
            "exit_time": entry_time,
            "exit_price_1": entry_price,
            "exit_price_2": entry_price,
            "return": 0.0,
            "exit_reason": "no_path",
            "exit_legs": f"1.0@{entry_price:.6f}",
        }
    stop = entry_price * stop_factor
    tp1 = entry_price * tp1_factor
    strong_tp = entry_price * strong_factor
    half_done = False
    hold_strong = False
    exit1_price = math.nan
    tp1_time = pd.NaT
    high_water = entry_price
    for row in path.itertuples(index=False):
        high_water = max(high_water, float(row.high))
        if float(row.low) <= stop:
            if not half_done:
                return {
                    "exit_time": row.datetime,
                    "exit_price_1": stop,
                    "exit_price_2": stop,
                    "return": stop / entry_price - 1.0,
                    "exit_reason": "fast_stop_88",
                    "exit_legs": f"1.0@{stop:.6f}",
                }
            ret = 0.5 * (exit1_price / entry_price - 1.0) + 0.5 * (stop / entry_price - 1.0)
            return {
                "exit_time": row.datetime,
                "exit_price_1": exit1_price,
                "exit_price_2": stop,
                "return": ret,
                "exit_reason": "fast_stop_after_tp1",
                "exit_legs": fmt_legs([(0.5, exit1_price), (0.5, stop)]),
                "tp1_time": tp1_time,
            }
        if not half_done and float(row.high) >= tp1:
            if float(row.high) >= strong_tp:
                hold_strong = True
                half_done = True
                exit1_price = entry_price
                tp1_time = row.datetime
            else:
                half_done = True
                exit1_price = tp1
                tp1_time = row.datetime
        if hold_strong:
            trail_stop = max(stop, high_water * (1.0 - strong_trail))
            if float(row.low) <= trail_stop:
                return {
                    "exit_time": row.datetime,
                    "exit_price_1": trail_stop,
                    "exit_price_2": trail_stop,
                    "return": trail_stop / entry_price - 1.0,
                    "exit_reason": "strong_trail_12",
                    "exit_legs": f"1.0@{trail_stop:.6f}",
                    "tp1_time": tp1_time,
                }
        elif half_done and float(row.high) >= strong_tp:
            ret = 0.5 * (exit1_price / entry_price - 1.0) + 0.5 * (strong_tp / entry_price - 1.0)
            return {
                "exit_time": row.datetime,
                "exit_price_1": exit1_price,
                "exit_price_2": strong_tp,
                "return": ret,
                "exit_reason": "fast_tp2_35",
                "exit_legs": fmt_legs([(0.5, exit1_price), (0.5, strong_tp)]),
                "tp1_time": tp1_time,
            }
    last = path.iloc[-1]
    last_price = float(last["close"])
    if half_done and not hold_strong:
        ret = 0.5 * (exit1_price / entry_price - 1.0) + 0.5 * (last_price / entry_price - 1.0)
        return {
            "exit_time": last["datetime"],
            "exit_price_1": exit1_price,
            "exit_price_2": last_price,
            "return": ret,
            "exit_reason": "fast_tp1_eod_1445",
            "exit_legs": fmt_legs([(0.5, exit1_price), (0.5, last_price)]),
            "tp1_time": tp1_time,
        }
    return {
        "exit_time": last["datetime"],
        "exit_price_1": last_price,
        "exit_price_2": last_price,
        "return": last_price / entry_price - 1.0,
        "exit_reason": "eod_1445",
        "exit_legs": f"1.0@{last_price:.6f}",
    }


def fixed_time_entry(day: pd.DataFrame, trade_date: str, time_text: str) -> pd.Timestamp | None:
    rows = day[day["time"] == time_text]
    if rows.empty:
        return None
    return pd.Timestamp(rows.iloc[-1]["datetime"])


def mode_entry_time(mode: str, info: dict[str, Any], trade_date: str) -> pd.Timestamp | None:
    if mode == "direct_0945":
        return fixed_time_entry(info["day"], trade_date, "09:45")
    if mode == "direct_0950":
        return fixed_time_entry(info["day"], trade_date, "09:50")
    if mode == "direct_1000":
        return fixed_time_entry(info["day"], trade_date, "10:00")
    if mode == "pullback_fail":
        return detect_trigger(
            info["day"],
            float(info["close945"]),
            PULLBACK_SCAN_END,
            REBOUND_MAX,
            BREAK_CONFIRM,
        )
    raise ValueError(mode)


def build_mode_trades(events945: pd.DataFrame, etf_stats: dict[str, dict[str, Any]], mode: str, exit_model: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for trade_date, info in etf_stats.items():
        if info["open_ret_945"] > -DROP_MIN:
            continue
        if info["close_pos_945"] > CLOSE_POS_MAX:
            continue
        entry_time = mode_entry_time(mode, info, trade_date)
        if entry_time is None:
            continue
        selected = select_put_contract(events945, trade_date, entry_time)
        if selected is None:
            continue
        bars = cached_option_1m(selected["option_code"], trade_date)
        if bars.empty:
            continue
        if exit_model == "baseline":
            exit_info = simulate_putrev_baseline_1445(bars, entry_time, float(selected["entry_price"]))
        elif exit_model == "fast":
            exit_info = simulate_fast_opening_put_exit(bars, entry_time, float(selected["entry_price"]))
        else:
            raise ValueError(exit_model)
        rows.append(
            {
                "mode": mode,
                "exit_model": exit_model,
                "trade_date": trade_date,
                "underlying_code": UNDERLYING,
                "direction": "put",
                "entry_time": entry_time,
                "option_code": selected["option_code"],
                "contract_id": selected["contract_id"],
                "contract_symbol": selected["contract_symbol"],
                "entry_price": selected["entry_price"],
                "position_pct": POSITION_PCT,
                "signal_strength": mode,
                "strategy_leg": "put_reversal_0945",
                "delta": selected["delta"],
                "implied_volatility": selected["iv"],
                "volume15": selected["volume15"],
                "option_momentum_to_entry": selected["momentum_to_entry"],
                "etf_open_ret_945": info["open_ret_945"],
                "etf_close_pos_945": info["close_pos_945"],
                **exit_info,
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("entry_time")


def summarize(trades: pd.DataFrame, mode: str, exit_model: str) -> dict[str, Any]:
    capital, summary = calc_capital(trades, slippage_tick=0.0003, max_volume_share=0.05)
    out = dict(summary)
    out["mode"] = mode
    out["exit_model"] = exit_model
    out["selected_trades"] = int(len(trades))
    if BASE_TRADES_CSV.exists() and not trades.empty:
        base = pd.read_csv(BASE_TRADES_CSV, parse_dates=["entry_time", "exit_time"])
        base_dates = set(base["trade_date"].astype(str))
        add_on = trades[~trades["trade_date"].astype(str).isin(base_dates)].copy()
        combined = pd.concat([base, add_on], ignore_index=True, sort=False).sort_values("entry_time")
        combined_capital, combined_summary = calc_capital(combined, slippage_tick=0.0003, max_volume_share=0.05)
        out["addon_after_same_day_skip"] = int(len(add_on))
        out["addon_same_day_skipped"] = int(len(trades) - len(add_on))
        out["combined_final_capital"] = combined_summary["final_capital"]
        out["combined_net_pnl"] = combined_summary["net_pnl"]
        out["combined_max_drawdown"] = combined_summary["max_drawdown"]
    return out


def main() -> None:
    events = pd.read_csv(EVENTS_CSV, parse_dates=["datetime"])
    events945 = events[(events["time"] == "09:45") & (events["option_type"] == "put")].copy()
    etf_5m = load_etf_5m(DEFAULT_SQLITE, [UNDERLYING], str(events945["trade_date"].min()), str(events945["trade_date"].max()))
    etf_stats = build_early_etf_stats(etf_5m)
    all_trades: list[pd.DataFrame] = []
    summaries: list[dict[str, Any]] = []
    for mode in ["direct_0945", "direct_0950", "direct_1000", "pullback_fail"]:
        for exit_model in ["baseline", "fast"]:
            trades = build_mode_trades(events945, etf_stats, mode, exit_model)
            all_trades.append(trades)
            summaries.append(summarize(trades, mode, exit_model))
    summary_df = pd.DataFrame(summaries).sort_values(
        ["combined_final_capital", "final_capital"],
        ascending=[False, False],
    )
    trades_df = pd.concat(all_trades, ignore_index=True, sort=False)
    summary_df.to_csv(SUMMARY_CSV, index=False)
    trades_df.to_csv(TRADES_CSV, index=False)
    print("summary", SUMMARY_CSV)
    print("trades", TRADES_CSV)
    cols = [
        "mode",
        "exit_model",
        "selected_trades",
        "addon_after_same_day_skip",
        "final_capital",
        "net_pnl",
        "win_rate",
        "max_drawdown",
        "combined_final_capital",
        "combined_net_pnl",
        "combined_max_drawdown",
    ]
    print(summary_df[cols].to_string(index=False))


if __name__ == "__main__":
    main()
