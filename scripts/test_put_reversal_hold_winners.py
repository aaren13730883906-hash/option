#!/usr/bin/env python3
"""Test delayed profit-taking for KCB 09:45 Put reversal trades.

This research script keeps the existing 1032 entry set and capital sizing, but
recomputes only the put_reversal_0945 exits:

- baseline_1445: +35% sell half, 3x exit, 14:45 EOD.
- hold winner variants: when +35% is reached and the move still looks strong,
  do not sell half immediately; use a trailing stop and optional +80% scale-out.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import math

import pandas as pd

from backtest_kcb_put_flow_0945 import read_option_1m
from backtest_kcb_put_reversal_0945 import calc_capital
from backtest_v02_recent_intraday import DEFAULT_SQLITE, load_etf_15m


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = ROOT / "research"
BASE_TRADES_CSV = RESEARCH_DIR / "full_confirm_tp2_3p0_trades.csv"
ADDON_TRADES_CSV = RESEARCH_DIR / (
    "put_reversal_0945_conservative20_cap5"
    "_etfup0.005_delta0.45_0.6_pos0.2_normal_rankvolume15"
    "_minp0.03_minv1000_slip0.0003_capshare0.05_trades.csv"
)
EVENTS_CSV = RESEARCH_DIR / "kcb_option_flow_15m_events.csv"


def fmt_legs(legs: list[tuple[float, float]]) -> str:
    return ";".join(f"{weight:.6f}@{price:.6f}" for weight, price in legs)


def latest_etf_close(etf_day: pd.DataFrame, when: pd.Timestamp) -> float | None:
    if etf_day.empty:
        return None
    rows = etf_day[etf_day["datetime"] <= when].tail(1)
    if rows.empty:
        return None
    return float(rows.iloc[0]["close"])


def etf_entry_close(etf_day: pd.DataFrame, entry_time: pd.Timestamp, fallback: float | None) -> float | None:
    close = latest_etf_close(etf_day, entry_time)
    if close is not None:
        return close
    return fallback


def strong_tp1_context(
    *,
    row: Any,
    entry_price: float,
    high_water: float,
    entry_etf: float | None,
    etf_day: pd.DataFrame,
    etf_follow_min: float | None,
    close_near_high_min: float,
    latest_time: str,
) -> bool:
    if pd.Timestamp(row.datetime).time() >= pd.Timestamp(latest_time).time():
        return False
    if high_water <= 0:
        return False
    if float(row.close) < high_water * close_near_high_min:
        return False
    if float(row.close) < entry_price * 1.35:
        return False
    if etf_follow_min is not None and entry_etf is not None and entry_etf > 0:
        etf_now = latest_etf_close(etf_day, pd.Timestamp(row.datetime))
        if etf_now is None:
            return False
        # For a long put, the ETF should have stopped following the early rally
        # and should be at least mildly below the 09:45 ETF close.
        if etf_now > entry_etf * (1.0 - etf_follow_min):
            return False
    return True


def simulate_putrev_baseline_1445(
    bars: pd.DataFrame,
    entry_time: pd.Timestamp,
    entry_price: float,
) -> dict[str, Any]:
    stop = entry_price * 0.70
    soft_stop = entry_price * 0.82
    tp1 = entry_price * 1.35
    tp2 = entry_price * 3.0
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
    half_done = False
    exit1_price = math.nan
    exit1_time = pd.NaT
    for row in path.itertuples(index=False):
        if not half_done and row.low <= soft_stop:
            return {
                "exit_time": row.datetime,
                "exit_price_1": soft_stop,
                "exit_price_2": soft_stop,
                "return": soft_stop / entry_price - 1.0,
                "exit_reason": "soft_stop",
                "exit_legs": f"1.0@{soft_stop:.6f}",
            }
        if row.low <= stop:
            if not half_done:
                return {
                    "exit_time": row.datetime,
                    "exit_price_1": stop,
                    "exit_price_2": stop,
                    "return": -0.30,
                    "exit_reason": "stop",
                    "exit_legs": f"1.0@{stop:.6f}",
                }
            ret = 0.5 * (exit1_price / entry_price - 1.0) + 0.5 * (stop / entry_price - 1.0)
            return {
                "exit_time": row.datetime,
                "exit_price_1": exit1_price,
                "exit_price_2": stop,
                "return": ret,
                "exit_reason": "stop_after_tp1",
                "exit_legs": fmt_legs([(0.5, exit1_price), (0.5, stop)]),
                "tp1_time": exit1_time,
            }
        if not half_done and row.high >= tp1:
            half_done = True
            exit1_price = tp1
            exit1_time = row.datetime
        if half_done and row.high >= tp2:
            ret = 0.5 * (exit1_price / entry_price - 1.0) + 0.5 * (tp2 / entry_price - 1.0)
            return {
                "exit_time": row.datetime,
                "exit_price_1": exit1_price,
                "exit_price_2": tp2,
                "return": ret,
                "exit_reason": "tp2",
                "exit_legs": fmt_legs([(0.5, exit1_price), (0.5, tp2)]),
                "tp1_time": exit1_time,
            }
    last = path.iloc[-1]
    if not half_done:
        ret = float(last["close"]) / entry_price - 1.0
        return {
            "exit_time": last["datetime"],
            "exit_price_1": float(last["close"]),
            "exit_price_2": float(last["close"]),
            "return": ret,
            "exit_reason": "eod_1445",
            "exit_legs": f"1.0@{float(last['close']):.6f}",
        }
    ret = 0.5 * (exit1_price / entry_price - 1.0) + 0.5 * (float(last["close"]) / entry_price - 1.0)
    return {
        "exit_time": last["datetime"],
        "exit_price_1": exit1_price,
        "exit_price_2": float(last["close"]),
        "return": ret,
        "exit_reason": "tp1_eod_1445",
        "exit_legs": fmt_legs([(0.5, exit1_price), (0.5, float(last["close"]))]),
        "tp1_time": exit1_time,
    }


def simulate_putrev_hold_winner(
    bars: pd.DataFrame,
    etf_day: pd.DataFrame,
    entry_time: pd.Timestamp,
    entry_price: float,
    entry_etf_close_value: float | None,
    *,
    trail_pct: float,
    scaleout_factor: float | None,
    scaleout_weight: float,
    etf_follow_min: float | None,
    close_near_high_min: float,
    latest_tp1_hold_time: str = "14:30",
) -> dict[str, Any]:
    stop = entry_price * 0.70
    soft_stop = entry_price * 0.82
    tp1 = entry_price * 1.35
    tp2 = entry_price * 3.0
    scaleout = entry_price * scaleout_factor if scaleout_factor else None
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

    entry_etf = etf_entry_close(etf_day, entry_time, entry_etf_close_value)
    normal_half_done = False
    hold_mode = False
    scale_done = False
    exit_legs: list[tuple[float, float]] = []
    remaining_weight = 1.0
    high_water = entry_price
    trailing_stop = stop
    tp1_time = pd.NaT

    for row in path.itertuples(index=False):
        high_water = max(high_water, float(row.high))

        if not normal_half_done and not hold_mode and row.low <= soft_stop:
            return {
                "exit_time": row.datetime,
                "exit_price_1": soft_stop,
                "exit_price_2": soft_stop,
                "return": soft_stop / entry_price - 1.0,
                "exit_reason": "soft_stop",
                "exit_legs": f"1.0@{soft_stop:.6f}",
            }

        if row.low <= stop:
            if remaining_weight >= 0.999:
                return {
                    "exit_time": row.datetime,
                    "exit_price_1": stop,
                    "exit_price_2": stop,
                    "return": -0.30,
                    "exit_reason": "stop",
                    "exit_legs": f"1.0@{stop:.6f}",
                }
            exit_legs.append((remaining_weight, stop))
            ret = sum(w * (p / entry_price - 1.0) for w, p in exit_legs)
            return {
                "exit_time": row.datetime,
                "exit_price_1": exit_legs[0][1],
                "exit_price_2": stop,
                "return": ret,
                "exit_reason": "stop_after_partial",
                "exit_legs": fmt_legs(exit_legs),
                "tp1_time": tp1_time,
                "high_water": high_water,
                "trailing_stop": trailing_stop,
            }

        if not normal_half_done and not hold_mode and row.high >= tp1:
            tp1_time = row.datetime
            if strong_tp1_context(
                row=row,
                entry_price=entry_price,
                high_water=high_water,
                entry_etf=entry_etf,
                etf_day=etf_day,
                etf_follow_min=etf_follow_min,
                close_near_high_min=close_near_high_min,
                latest_time=latest_tp1_hold_time,
            ):
                hold_mode = True
                trailing_stop = max(stop, high_water * (1.0 - trail_pct))
            else:
                normal_half_done = True
                exit_legs.append((0.5, tp1))
                remaining_weight = 0.5

        if hold_mode:
            trailing_stop = max(trailing_stop, high_water * (1.0 - trail_pct))
            if scaleout is not None and not scale_done and row.high >= scaleout:
                weight = min(scaleout_weight, remaining_weight)
                exit_legs.append((weight, scaleout))
                remaining_weight -= weight
                scale_done = True
            if row.low <= trailing_stop:
                exit_legs.append((remaining_weight, trailing_stop))
                ret = sum(w * (p / entry_price - 1.0) for w, p in exit_legs)
                return {
                    "exit_time": row.datetime,
                    "exit_price_1": exit_legs[0][1],
                    "exit_price_2": trailing_stop,
                    "return": ret,
                    "exit_reason": "hold_trailing_{:.0f}%".format(trail_pct * 100),
                    "exit_legs": fmt_legs(exit_legs),
                    "tp1_time": tp1_time,
                    "high_water": high_water,
                    "trailing_stop": trailing_stop,
                }

        if normal_half_done and row.high >= tp2:
            exit_legs.append((remaining_weight, tp2))
            ret = sum(w * (p / entry_price - 1.0) for w, p in exit_legs)
            return {
                "exit_time": row.datetime,
                "exit_price_1": exit_legs[0][1],
                "exit_price_2": tp2,
                "return": ret,
                "exit_reason": "tp2",
                "exit_legs": fmt_legs(exit_legs),
                "tp1_time": tp1_time,
                "high_water": high_water,
                "trailing_stop": trailing_stop,
            }

    last = path.iloc[-1]
    exit_legs.append((remaining_weight, float(last["close"])))
    ret = sum(w * (p / entry_price - 1.0) for w, p in exit_legs)
    reason = "hold_eod_1445" if hold_mode else ("tp1_eod_1445" if normal_half_done else "eod_1445")
    return {
        "exit_time": last["datetime"],
        "exit_price_1": exit_legs[0][1],
        "exit_price_2": float(last["close"]),
        "return": ret,
        "exit_reason": reason,
        "exit_legs": fmt_legs(exit_legs),
        "tp1_time": tp1_time,
        "high_water": high_water,
        "trailing_stop": trailing_stop,
    }


def event_entry_etf_map() -> dict[tuple[str, int], float]:
    events = pd.read_csv(EVENTS_CSV)
    events = events[(events["time"] == "09:45") & (events["option_type"] == "put")].copy()
    out: dict[tuple[str, int], float] = {}
    for _, row in events.iterrows():
        try:
            out[(str(row["trade_date"]), int(row["option_code"]))] = float(row["etf15_close"])
        except Exception:
            pass
    return out


def recompute_addon_exits(
    addon: pd.DataFrame,
    *,
    scenario: str,
    trail_pct: float = 0.15,
    scaleout_factor: float | None = 1.80,
    scaleout_weight: float = 1.0 / 3.0,
    etf_follow_min: float | None = 0.0,
    close_near_high_min: float = 0.92,
) -> pd.DataFrame:
    out_rows: list[pd.Series] = []
    entry_etf = event_entry_etf_map()
    start = str(addon["trade_date"].min())
    end = str(addon["trade_date"].max())
    etf_15m = load_etf_15m(DEFAULT_SQLITE, ["588000"], start, end)
    for _, row in addon.iterrows():
        trade_date = str(row["trade_date"])
        entry_time = pd.Timestamp(row["entry_time"])
        bars = read_option_1m(int(row["option_code"]), trade_date)
        if bars.empty:
            continue
        etf_day = etf_15m[etf_15m["datetime"].dt.date == pd.Timestamp(trade_date).date()].copy()
        entry_price = float(row["entry_price"])
        if scenario == "baseline_1445":
            exit_info = simulate_putrev_baseline_1445(bars, entry_time, entry_price)
        else:
            exit_info = simulate_putrev_hold_winner(
                bars,
                etf_day,
                entry_time,
                entry_price,
                entry_etf.get((trade_date, int(row["option_code"]))),
                trail_pct=trail_pct,
                scaleout_factor=scaleout_factor,
                scaleout_weight=scaleout_weight,
                etf_follow_min=etf_follow_min,
                close_near_high_min=close_near_high_min,
            )
        new_row = row.copy()
        for key, value in exit_info.items():
            new_row[key] = value
        new_row["exit_variant"] = scenario
        out_rows.append(new_row)
    return pd.DataFrame(out_rows)


def run_scenario(name: str, base: pd.DataFrame, addon_all: pd.DataFrame, **kwargs: Any) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    adjusted = recompute_addon_exits(addon_all, scenario=name, **kwargs)
    base_dates = set(base["trade_date"].astype(str))
    addon = adjusted[~adjusted["trade_date"].astype(str).isin(base_dates)].copy()
    combined = pd.concat([base, addon], ignore_index=True, sort=False).sort_values("entry_time")
    capital, summary = calc_capital(combined, slippage_tick=0.0003, max_volume_share=0.05)
    addon_cap = capital[capital["contract_id"].astype(str).str.contains("P_REV", na=False)].copy()
    executed = addon_cap[~addon_cap["skipped"].fillna(False)].copy()
    hold_count = int(adjusted["exit_reason"].astype(str).str.startswith("hold_").sum())
    changed = adjusted.merge(
        recompute_addon_exits(addon_all, scenario="baseline_1445")[
            ["trade_date", "option_code", "exit_reason", "exit_legs", "return"]
        ],
        on=["trade_date", "option_code"],
        how="left",
        suffixes=("", "_baseline"),
    )
    changed = changed[
        (changed["exit_reason"].astype(str) != changed["exit_reason_baseline"].astype(str))
        | ((pd.to_numeric(changed["return"], errors="coerce") - pd.to_numeric(changed["return_baseline"], errors="coerce")).abs() > 1e-9)
    ].copy()
    row = {
        "scenario": name,
        "final_capital": summary["final_capital"],
        "total_return": summary["total_return"],
        "net_pnl": summary["net_pnl"],
        "trades": summary["trades"],
        "win_rate": summary["win_rate"],
        "max_drawdown": summary["max_drawdown"],
        "addon_selected": int(len(adjusted)),
        "addon_after_same_day_skip": int(len(addon)),
        "addon_executed": int(len(executed)),
        "addon_net_pnl": float(addon_cap["net_pnl"].sum()) if not addon_cap.empty else 0.0,
        "hold_mode_trades": hold_count,
        "changed_exit_trades": int(len(changed)),
        "avg_addon_pnl": float(executed["net_pnl"].mean()) if not executed.empty else 0.0,
        "median_addon_pnl": float(executed["net_pnl"].median()) if not executed.empty else 0.0,
    }
    return row, capital, changed


def main() -> None:
    base = pd.read_csv(BASE_TRADES_CSV, parse_dates=["entry_time", "exit_time"])
    addon_all = pd.read_csv(ADDON_TRADES_CSV, parse_dates=["entry_time", "exit_time"])

    scenarios: list[tuple[str, dict[str, Any]]] = [
        ("baseline_1445", {}),
        ("hold_trail12_scale80_etf_flat", {"trail_pct": 0.12, "scaleout_factor": 1.80, "etf_follow_min": 0.0}),
        ("hold_trail15_scale80_etf_flat", {"trail_pct": 0.15, "scaleout_factor": 1.80, "etf_follow_min": 0.0}),
        ("hold_trail18_scale80_etf_flat", {"trail_pct": 0.18, "scaleout_factor": 1.80, "etf_follow_min": 0.0}),
        ("hold_trail15_no_scale_etf_flat", {"trail_pct": 0.15, "scaleout_factor": None, "etf_follow_min": 0.0}),
        ("hold_trail15_scale80_etf_down02", {"trail_pct": 0.15, "scaleout_factor": 1.80, "etf_follow_min": 0.002}),
        ("hold_trail15_scale80_option_only", {"trail_pct": 0.15, "scaleout_factor": 1.80, "etf_follow_min": None}),
    ]

    rows: list[dict[str, Any]] = []
    changed_tables: list[pd.DataFrame] = []
    for name, kwargs in scenarios:
        row, capital, changed = run_scenario(name, base, addon_all, **kwargs)
        rows.append(row)
        capital.to_csv(RESEARCH_DIR / f"put_reversal_hold_winners_{name}_capital.csv", index=False)
        if not changed.empty:
            changed["scenario"] = name
            changed_tables.append(changed)

    summary = pd.DataFrame(rows)
    summary.to_csv(RESEARCH_DIR / "put_reversal_hold_winners_summary.csv", index=False)
    if changed_tables:
        changed_all = pd.concat(changed_tables, ignore_index=True, sort=False)
        keep_cols = [
            "scenario",
            "trade_date",
            "option_code",
            "contract_symbol",
            "entry_price",
            "exit_reason_baseline",
            "return_baseline",
            "exit_legs_baseline",
            "exit_reason",
            "return",
            "exit_legs",
            "tp1_time",
            "high_water",
            "trailing_stop",
            "volume15",
            "etf_intraday_return",
            "future_gain_eod",
        ]
        changed_all[[c for c in keep_cols if c in changed_all.columns]].to_csv(
            RESEARCH_DIR / "put_reversal_hold_winners_changed_trades.csv",
            index=False,
        )

    print(summary.sort_values("final_capital", ascending=False).to_string(index=False))
    print("summary", RESEARCH_DIR / "put_reversal_hold_winners_summary.csv")
    print("changed", RESEARCH_DIR / "put_reversal_hold_winners_changed_trades.csv")


if __name__ == "__main__":
    main()
