#!/usr/bin/env python3
"""Research 09:50-10:00 opening-down late-continuation Put entries.

This script is research-only. It does not touch QMT or send orders.

Candidate idea:
- 09:45 is weak but not weak enough for the existing pullback-fail channel;
- by 09:50-10:00 the ETF continues lower and confirms the downtrend;
- buy a near-ATM put with the same 25% P0+P1 fast exit profile.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import math

import pandas as pd

from backtest_kcb_put_reversal_0945 import calc_capital
from compare_opening_down_put_entry_modes import fmt_legs
from test_opening_put_pullback_fail import (
    DEFAULT_SQLITE,
    EVENTS_CSV,
    UNDERLYING,
    build_early_etf_stats,
    cached_option_1m,
    load_etf_5m,
    select_put_contract,
)


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = ROOT / "research"
SUMMARY_CSV = RESEARCH_DIR / "opening_put_late_continue_summary.csv"
TRADES_CSV = RESEARCH_DIR / "opening_put_late_continue_trades.csv"
BEST_TRADES_CSV = RESEARCH_DIR / "opening_put_late_continue_best_trades.csv"
CURRENT_1606_BASE = RESEARCH_DIR / "full_with_putrev_hold_and_opening_p0p1_pos25_tp25_45_trades.csv"

POSITION_PCT = 0.25
CLOSE_POS_MAX = 0.35


def simulate_p0p1_exit(
    bars: pd.DataFrame,
    entry_time: pd.Timestamp,
    entry_price: float,
    *,
    stop_factor: float = 0.88,
    tp1_factor: float = 1.25,
    tp2_factor: float = 1.45,
    trail: float = 0.12,
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
    tp2 = entry_price * tp2_factor
    high_water = entry_price
    partial_done = False
    hold_mode = False
    exit1_price = math.nan
    tp1_time = pd.NaT

    for row in path.itertuples(index=False):
        high_water = max(high_water, float(row.high))

        if float(row.low) <= stop:
            if not partial_done and not hold_mode:
                return {
                    "exit_time": row.datetime,
                    "exit_price_1": stop,
                    "exit_price_2": stop,
                    "return": stop / entry_price - 1.0,
                    "exit_reason": "fast_stop_12",
                    "exit_legs": f"1.0@{stop:.6f}",
                    "tp1_time": tp1_time,
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

        if hold_mode:
            trail_stop = max(stop, high_water * (1.0 - trail))
            if float(row.low) <= trail_stop:
                return {
                    "exit_time": row.datetime,
                    "exit_price_1": trail_stop,
                    "exit_price_2": trail_stop,
                    "return": trail_stop / entry_price - 1.0,
                    "exit_reason": "strong_trail_12",
                    "exit_legs": f"1.0@{trail_stop:.6f}",
                    "tp1_time": tp1_time,
                    "high_water": high_water,
                }
            continue

        if not partial_done and float(row.high) >= tp1:
            if float(row.high) >= tp2:
                hold_mode = True
                tp1_time = row.datetime
                continue
            partial_done = True
            exit1_price = tp1
            tp1_time = row.datetime

        if partial_done and float(row.high) >= tp2:
            ret = 0.5 * (exit1_price / entry_price - 1.0) + 0.5 * (tp2 / entry_price - 1.0)
            return {
                "exit_time": row.datetime,
                "exit_price_1": exit1_price,
                "exit_price_2": tp2,
                "return": ret,
                "exit_reason": "tp45",
                "exit_legs": fmt_legs([(0.5, exit1_price), (0.5, tp2)]),
                "tp1_time": tp1_time,
            }

    last = path.iloc[-1]
    last_price = float(last["close"])
    if partial_done:
        ret = 0.5 * (exit1_price / entry_price - 1.0) + 0.5 * (last_price / entry_price - 1.0)
        return {
            "exit_time": last["datetime"],
            "exit_price_1": exit1_price,
            "exit_price_2": last_price,
            "return": ret,
            "exit_reason": "tp25_eod_1445",
            "exit_legs": fmt_legs([(0.5, exit1_price), (0.5, last_price)]),
            "tp1_time": tp1_time,
            "high_water": high_water,
        }
    return {
        "exit_time": last["datetime"],
        "exit_price_1": last_price,
        "exit_price_2": last_price,
        "return": last_price / entry_price - 1.0,
        "exit_reason": "eod_1445",
        "exit_legs": f"1.0@{last_price:.6f}",
        "tp1_time": tp1_time,
        "high_water": high_water,
    }


def detect_late_continue(
    info: dict[str, Any],
    *,
    scan_start: str,
    scan_end: str,
    min_945_down: float,
    min_current_down: float,
    break_from_945: float,
    rebound_max: float,
) -> pd.Timestamp | None:
    if info["open_ret_945"] > -min_945_down:
        return None
    if info["close_pos_945"] > CLOSE_POS_MAX:
        return None

    day = info["day"].sort_values("datetime")
    path = day[(day["time"] > "09:45") & (day["time"] >= scan_start) & (day["time"] <= scan_end)]
    if path.empty:
        return None

    close945 = float(info["close945"])
    open0 = float(info["open0"])
    trigger_level = close945 * (1.0 - break_from_945)
    early_path = day[(day["time"] > "09:45") & (day["time"] <= scan_end)]
    max_rebound = float(early_path["high"].max()) / close945 - 1.0 if close945 > 0 and not early_path.empty else 999.0
    if max_rebound > rebound_max:
        return None

    for row in path.itertuples(index=False):
        current_return = float(row.close) / open0 - 1.0
        if current_return <= -min_current_down and float(row.close) <= trigger_level:
            return pd.Timestamp(row.datetime)
    return None


def build_trades(
    events945: pd.DataFrame,
    etf_stats: dict[str, dict[str, Any]],
    params: dict[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for trade_date, info in etf_stats.items():
        entry_time = detect_late_continue(info, **params)
        if entry_time is None:
            continue
        selected = select_put_contract(events945, trade_date, entry_time)
        if selected is None:
            continue
        bars = cached_option_1m(selected["option_code"], trade_date)
        if bars.empty:
            continue
        exit_info = simulate_p0p1_exit(bars, entry_time, float(selected["entry_price"]))
        rows.append(
            {
                "trade_date": trade_date,
                "underlying_code": UNDERLYING,
                "direction": "put",
                "entry_time": entry_time,
                "option_code": selected["option_code"],
                "contract_id": selected["contract_id"],
                "contract_symbol": selected["contract_symbol"],
                "entry_price": selected["entry_price"],
                "position_pct": POSITION_PCT,
                "signal_strength": "opening_put_late_continue",
                # Reuse this leg name so calc_capital applies the 5% volume capacity cap.
                "strategy_leg": "put_reversal_0945",
                "trigger_leg": "opening_put_late_continue",
                "delta": selected["delta"],
                "implied_volatility": selected["iv"],
                "volume15": selected["volume15"],
                "option_momentum_to_entry": selected["momentum_to_entry"],
                "etf_open_ret_945": info["open_ret_945"],
                "etf_close_pos_945": info["close_pos_945"],
                **params,
                **exit_info,
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("entry_time")


def summarize(trades: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    _, summary = calc_capital(trades, slippage_tick=0.0003, max_volume_share=0.05)
    out = dict(summary)
    out.update(params)
    out["selected_trades"] = int(len(trades))
    if CURRENT_1606_BASE.exists() and not trades.empty:
        base = pd.read_csv(CURRENT_1606_BASE, parse_dates=["entry_time", "exit_time"])
        base_dates = set(base["trade_date"].astype(str))
        add_on = trades[~trades["trade_date"].astype(str).isin(base_dates)].copy()
        combined = pd.concat([base, add_on], ignore_index=True, sort=False).sort_values("entry_time")
        _, combined_summary = calc_capital(combined, slippage_tick=0.0003, max_volume_share=0.05)
        out["addon_after_1606_same_day_skip"] = int(len(add_on))
        out["addon_same_day_skipped"] = int(len(trades) - len(add_on))
        out["combined_1606_final"] = combined_summary["final_capital"]
        out["combined_1606_net_pnl"] = combined_summary["net_pnl"]
        out["combined_1606_max_drawdown"] = combined_summary["max_drawdown"]
    return out


def main() -> None:
    events = pd.read_csv(EVENTS_CSV, parse_dates=["datetime"])
    events945 = events[(events["time"] == "09:45") & (events["option_type"] == "put")].copy()
    etf_5m = load_etf_5m(DEFAULT_SQLITE, [UNDERLYING], str(events945["trade_date"].min()), str(events945["trade_date"].max()))
    etf_stats = build_early_etf_stats(etf_5m)

    all_trades: list[pd.DataFrame] = []
    summaries: list[dict[str, Any]] = []
    for scan_start in ["09:50", "09:55"]:
        for min_945_down in [0.0035, 0.0040, 0.0045]:
            for min_current_down in [0.0080, 0.0090, 0.0100]:
                for break_from_945 in [0.0020, 0.0030]:
                    for rebound_max in [0.0080]:
                        params = {
                            "scan_start": scan_start,
                            "scan_end": "10:00",
                            "min_945_down": min_945_down,
                            "min_current_down": min_current_down,
                            "break_from_945": break_from_945,
                            "rebound_max": rebound_max,
                        }
                        trades = build_trades(events945, etf_stats, params)
                        if trades.empty:
                            continue
                        scenario = (
                            f"late_{scan_start}_d945{min_945_down:.4f}"
                            f"_dcur{min_current_down:.4f}_br{break_from_945:.4f}_reb{rebound_max:.4f}"
                        )
                        trades = trades.copy()
                        trades["scenario"] = scenario
                        all_trades.append(trades)
                        row = summarize(trades, params)
                        row["scenario"] = scenario
                        summaries.append(row)

    summary_df = pd.DataFrame(summaries).sort_values(
        ["combined_1606_final", "final_capital", "trades"],
        ascending=[False, False, False],
    )
    trades_df = pd.concat(all_trades, ignore_index=True, sort=False)
    summary_df.to_csv(SUMMARY_CSV, index=False)
    trades_df.to_csv(TRADES_CSV, index=False)

    best_scenario = str(summary_df.iloc[0]["scenario"])
    best_trades = trades_df[trades_df["scenario"] == best_scenario].copy()
    best_trades.to_csv(BEST_TRADES_CSV, index=False)

    print("summary", SUMMARY_CSV)
    print("trades", TRADES_CSV)
    print("best_trades", BEST_TRADES_CSV)
    cols = [
        "scenario",
        "trades",
        "skipped_trades",
        "selected_trades",
        "addon_after_1606_same_day_skip",
        "addon_same_day_skipped",
        "final_capital",
        "net_pnl",
        "win_rate",
        "max_drawdown",
        "max_volume_share",
        "combined_1606_final",
        "combined_1606_net_pnl",
        "combined_1606_max_drawdown",
    ]
    print(summary_df[cols].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
