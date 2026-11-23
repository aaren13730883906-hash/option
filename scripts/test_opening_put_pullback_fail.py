#!/usr/bin/env python3
"""Research opening-down put entry: first drop, weak rebound, fail again.

This is a research-only script. It does not touch QMT or send orders.

The new candidate path keeps position size fixed at 20%, same as the existing
09:45 put-reversal path. Other parameters are scanned:

- how much the ETF must be down by 09:45;
- how close 09:45 is to the first-15m low;
- how late we are still willing to enter;
- how weak the rebound must be;
- how much confirmation is required before buying put.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import math

import pandas as pd

from backtest_kcb_put_flow_0945 import read_option_1m
from backtest_kcb_put_reversal_0945 import calc_capital
from backtest_v02_recent_intraday import DEFAULT_SQLITE, load_etf_5m
from test_put_reversal_hold_winners import simulate_putrev_baseline_1445


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = ROOT / "research"
EVENTS_CSV = RESEARCH_DIR / "kcb_option_flow_15m_events.csv"
BASE_TRADES_CSV = RESEARCH_DIR / "full_confirm_tp2_3p0_trades.csv"

POSITION_PCT = 0.20
UNDERLYING = "588000"


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return default
        return number
    except Exception:
        return default


@lru_cache(maxsize=4096)
def cached_option_1m(option_code: str, trade_date: str) -> pd.DataFrame:
    try:
        return read_option_1m(option_code, trade_date)
    except Exception:
        return pd.DataFrame()


def last_option_bar_at_or_before(option_code: str, trade_date: str, entry_time: pd.Timestamp) -> pd.Series | None:
    bars = cached_option_1m(option_code, trade_date)
    if bars.empty:
        return None
    rows = bars[bars["datetime"] <= entry_time].tail(1)
    if rows.empty:
        return None
    return rows.iloc[0]


def option_momentum_to_entry(option_code: str, trade_date: str, entry_time: pd.Timestamp, entry_price: float) -> float:
    bars = cached_option_1m(option_code, trade_date)
    if bars.empty:
        return 0.0
    first = bars.head(1)
    if first.empty or float(first.iloc[0]["open"]) <= 0:
        return 0.0
    return entry_price / float(first.iloc[0]["open"]) - 1.0


def build_early_etf_stats(etf_5m: pd.DataFrame) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for trade_date, day in etf_5m.groupby("trade_date"):
        day = day.sort_values("datetime")
        early = day[(day["time"] >= "09:35") & (day["time"] <= "09:45")]
        row945 = day[day["time"] == "09:45"]
        if early.empty or row945.empty:
            continue
        open0 = safe_float(early.iloc[0]["open"])
        close945 = safe_float(row945.iloc[-1]["close"])
        if open0 is None or close945 is None or open0 <= 0:
            continue
        high15 = float(early["high"].max())
        low15 = float(early["low"].min())
        width = high15 - low15
        close_pos = (close945 - low15) / width if width > 0 else 0.5
        stats[str(trade_date)] = {
            "open0": open0,
            "close945": close945,
            "high15": high15,
            "low15": low15,
            "open_ret_945": close945 / open0 - 1.0,
            "close_pos_945": close_pos,
            "day": day,
        }
    return stats


def detect_trigger(
    day: pd.DataFrame,
    close945: float,
    scan_end: str,
    rebound_max: float,
    break_confirm: float,
) -> pd.Timestamp | None:
    path = day[(day["time"] > "09:45") & (day["time"] <= scan_end)].sort_values("datetime")
    if path.empty:
        return None
    max_rebound = float(path["high"].max()) / close945 - 1.0
    if max_rebound > rebound_max:
        return None
    trigger_level = close945 * (1.0 - break_confirm)
    hit = path[path["close"] <= trigger_level].head(1)
    if hit.empty:
        return None
    return pd.Timestamp(hit.iloc[0]["datetime"])


def select_put_contract(events945: pd.DataFrame, trade_date: str, entry_time: pd.Timestamp) -> dict[str, Any] | None:
    candidates = events945[
        (events945["trade_date"].astype(str) == trade_date)
        & (events945["option_type"] == "put")
        & (events945["time"] == "09:45")
        & (events945["close"] >= 0.03)
        & (events945["volume15"] >= 1000)
        & (events945["abs_delta"] >= 0.45)
        & (events945["abs_delta"] <= 0.60)
    ].copy()
    if candidates.empty:
        return None

    rows: list[dict[str, Any]] = []
    for row in candidates.itertuples(index=False):
        code = str(getattr(row, "option_code"))
        entry_bar = last_option_bar_at_or_before(code, trade_date, entry_time)
        if entry_bar is None:
            continue
        entry_price = safe_float(entry_bar["close"])
        if entry_price is None or entry_price < 0.03:
            continue
        momentum = option_momentum_to_entry(code, trade_date, entry_time, entry_price)
        score = (
            -abs(float(getattr(row, "abs_delta")) - 0.50) * 10.0
            + math.log(max(float(getattr(row, "volume15")), 1.0)) * 0.05
            + momentum
        )
        rows.append(
            {
                "option_code": code,
                "contract_id": getattr(row, "contract_id"),
                "contract_symbol": getattr(row, "contract_symbol"),
                "entry_price": entry_price,
                "delta": float(getattr(row, "delta")),
                "iv": float(getattr(row, "iv")),
                "volume15": float(getattr(row, "volume15")),
                "momentum_to_entry": momentum,
                "score": score,
            }
        )
    if not rows:
        return None
    rows.sort(key=lambda item: item["score"], reverse=True)
    return rows[0]


def build_trades_for_scenario(
    *,
    events945: pd.DataFrame,
    etf_stats: dict[str, dict[str, Any]],
    drop_min: float,
    close_pos_max: float,
    scan_end: str,
    rebound_max: float,
    break_confirm: float,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for trade_date, info in etf_stats.items():
        if info["open_ret_945"] > -abs(drop_min):
            continue
        if info["close_pos_945"] > close_pos_max:
            continue
        entry_time = detect_trigger(
            info["day"],
            float(info["close945"]),
            scan_end,
            rebound_max,
            break_confirm,
        )
        if entry_time is None:
            continue
        selected = select_put_contract(events945, trade_date, entry_time)
        if selected is None:
            continue
        bars = cached_option_1m(selected["option_code"], trade_date)
        if bars.empty:
            continue
        exit_info = simulate_putrev_baseline_1445(bars, entry_time, float(selected["entry_price"]))
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
                "signal_strength": "opening_put_pullback_fail",
                "strategy_leg": "opening_put_pullback_fail",
                "delta": selected["delta"],
                "implied_volatility": selected["iv"],
                "volume15": selected["volume15"],
                "option_momentum_to_entry": selected["momentum_to_entry"],
                "etf_open_ret_945": info["open_ret_945"],
                "etf_close_pos_945": info["close_pos_945"],
                "param_drop_min": drop_min,
                "param_close_pos_max": close_pos_max,
                "param_scan_end": scan_end,
                "param_rebound_max": rebound_max,
                "param_break_confirm": break_confirm,
                **exit_info,
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("entry_time")


def evaluate_with_base(trades: pd.DataFrame) -> dict[str, Any]:
    # The shared capital helper applies the 5% volume-cap rule only to the
    # existing put_reversal_0945 add-on. For this research path, evaluate with
    # the same conservative capacity rule while keeping the output label clean.
    cap_trades = trades.copy()
    cap_trades["strategy_leg"] = "put_reversal_0945"
    capital, summary = calc_capital(cap_trades, slippage_tick=0.0003, max_volume_share=0.05)
    summary = dict(summary)
    summary["addon_selected"] = int(len(trades))
    summary["addon_after_same_day_skip"] = int(len(trades))
    summary["addon_same_day_skipped"] = 0

    if BASE_TRADES_CSV.exists() and not trades.empty:
        base = pd.read_csv(BASE_TRADES_CSV, parse_dates=["entry_time", "exit_time"])
        base_dates = set(base["trade_date"].astype(str))
        add_on = trades[~trades["trade_date"].astype(str).isin(base_dates)].copy()
        cap_add_on = add_on.copy()
        cap_add_on["strategy_leg"] = "put_reversal_0945"
        combined = pd.concat([base, cap_add_on], ignore_index=True, sort=False).sort_values("entry_time")
        combined_capital, combined_summary = calc_capital(combined, slippage_tick=0.0003, max_volume_share=0.05)
        summary["standalone_final_capital"] = summary["final_capital"]
        summary["standalone_net_pnl"] = summary["net_pnl"]
        summary["combined_final_capital"] = combined_summary["final_capital"]
        summary["combined_net_pnl"] = combined_summary["net_pnl"]
        summary["combined_max_drawdown"] = combined_summary["max_drawdown"]
        summary["addon_after_same_day_skip"] = int(len(add_on))
        summary["addon_same_day_skipped"] = int(len(trades) - len(add_on))
    else:
        summary["standalone_final_capital"] = summary["final_capital"]
        summary["standalone_net_pnl"] = summary["net_pnl"]
        summary["combined_final_capital"] = summary["final_capital"]
        summary["combined_net_pnl"] = summary["net_pnl"]
        summary["combined_max_drawdown"] = summary["max_drawdown"]

    return summary


def main() -> None:
    events = pd.read_csv(EVENTS_CSV, parse_dates=["datetime"])
    events945 = events[(events["time"] == "09:45") & (events["option_type"] == "put")].copy()
    start = str(events945["trade_date"].min())
    end = str(events945["trade_date"].max())
    etf_5m = load_etf_5m(DEFAULT_SQLITE, [UNDERLYING], start, end)
    etf_stats = build_early_etf_stats(etf_5m)

    summary_rows: list[dict[str, Any]] = []
    trade_sets: dict[str, pd.DataFrame] = {}
    for drop_min in [0.005, 0.006, 0.008, 0.010, 0.012]:
        for close_pos_max in [0.25, 0.35, 0.45]:
            for scan_end in ["09:50", "09:55", "10:00"]:
                for rebound_max in [0.002, 0.0035, 0.005]:
                    for break_confirm in [0.0, 0.001, 0.002]:
                        trades = build_trades_for_scenario(
                            events945=events945,
                            etf_stats=etf_stats,
                            drop_min=drop_min,
                            close_pos_max=close_pos_max,
                            scan_end=scan_end,
                            rebound_max=rebound_max,
                            break_confirm=break_confirm,
                        )
                        scenario = (
                            f"drop{drop_min:.3f}_pos{close_pos_max:.2f}"
                            f"_end{scan_end.replace(':','')}_reb{rebound_max:.4f}_brk{break_confirm:.3f}"
                        )
                        if trades.empty:
                            summary_rows.append(
                                {
                                    "scenario": scenario,
                                    "drop_min": drop_min,
                                    "close_pos_max": close_pos_max,
                                    "scan_end": scan_end,
                                    "rebound_max": rebound_max,
                                    "break_confirm": break_confirm,
                                    "trades": 0,
                                    "final_capital": 100000.0,
                                    "net_pnl": 0.0,
                                    "total_return": 0.0,
                                    "max_drawdown": 0.0,
                                    "win_rate": 0.0,
                                    "combined_final_capital": None,
                                    "combined_net_pnl": None,
                                    "combined_max_drawdown": None,
                                }
                            )
                            continue
                        summary = evaluate_with_base(trades)
                        summary.update(
                            {
                                "scenario": scenario,
                                "drop_min": drop_min,
                                "close_pos_max": close_pos_max,
                                "scan_end": scan_end,
                                "rebound_max": rebound_max,
                                "break_confirm": break_confirm,
                            }
                        )
                        summary_rows.append(summary)
                        trade_sets[scenario] = trades

    summary_df = pd.DataFrame(summary_rows)
    summary_df = summary_df.sort_values(
        ["combined_final_capital", "final_capital", "trades"],
        ascending=[False, False, False],
        na_position="last",
    )
    summary_path = RESEARCH_DIR / "opening_put_pullback_fail_summary.csv"
    summary_df.to_csv(summary_path, index=False)

    best_scenario = str(summary_df.iloc[0]["scenario"])
    best_trades = trade_sets.get(best_scenario, pd.DataFrame())
    best_path = RESEARCH_DIR / "opening_put_pullback_fail_best_trades.csv"
    best_trades.to_csv(best_path, index=False)

    print("summary", summary_path)
    print("best_trades", best_path)
    display_cols = [
        "scenario",
        "trades",
        "addon_after_same_day_skip",
        "addon_same_day_skipped",
        "final_capital",
        "net_pnl",
        "win_rate",
        "max_drawdown",
        "combined_final_capital",
        "combined_net_pnl",
        "combined_max_drawdown",
    ]
    existing = [col for col in display_cols if col in summary_df.columns]
    print(summary_df[existing].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
