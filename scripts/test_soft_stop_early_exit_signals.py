#!/usr/bin/env python3
"""Test early-exit signals for trades that otherwise hit -18% soft stops."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from backtest_kcb_put_flow_0945 import read_option_1m
from backtest_kcb_put_reversal_0945 import calc_capital
from backtest_v02_recent_intraday import DEFAULT_SQLITE, load_etf_15m


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = ROOT / "research"
BASELINE_TRADES = RESEARCH_DIR / (
    "put_reversal_0945_conservative20_cap5"
    "_etfup0.005_delta0.45_0.6_pos0.2_normal_rankvolume15"
    "_minp0.03_minv1000_slip0.0003_capshare0.05_combined_trades.csv"
)


def parse_exit_legs_return(row: pd.Series, new_time: pd.Timestamp, new_price: float) -> pd.Series:
    out = row.copy()
    entry = float(row["entry_price"])
    out["exit_time"] = new_time
    out["exit_price_1"] = new_price
    out["exit_price_2"] = new_price
    out["return"] = new_price / entry - 1.0
    out["exit_legs"] = f"1.0@{new_price:.6f}"
    out["early_exit_modified"] = True
    return out


def option_path(row: pd.Series) -> pd.DataFrame:
    code = int(row["option_code"])
    trade_date = str(row["trade_date"])
    entry_time = pd.Timestamp(row["entry_time"])
    end_time = pd.Timestamp(row["exit_time"])
    bars = read_option_1m(code, trade_date)
    return bars[(bars["datetime"] > entry_time) & (bars["datetime"] <= end_time)].copy()


def timed_exit(row: pd.Series, check_time: str, ret_lte: float) -> pd.Series:
    path = option_path(row)
    if path.empty:
        return row
    ts = pd.Timestamp(f"{row['trade_date']} {check_time}:00")
    if pd.Timestamp(row["exit_time"]) <= ts:
        return row
    x = path[path["datetime"] <= ts].tail(1)
    if x.empty:
        return row
    price = float(x.iloc[0]["close"])
    if price / float(row["entry_price"]) - 1.0 <= ret_lte:
        out = parse_exit_legs_return(row, pd.Timestamp(x.iloc[0]["datetime"]), price)
        out["exit_reason"] = f"early_timed_{check_time}_lte_{ret_lte:.0%}"
        return out
    return row


def first_threshold_exit(row: pd.Series, ret_lte: float, not_before: str | None = None) -> pd.Series:
    path = option_path(row)
    if path.empty:
        return row
    if not_before is not None:
        path = path[path["datetime"] >= pd.Timestamp(f"{row['trade_date']} {not_before}:00")]
    entry = float(row["entry_price"])
    hit = path[path["close"] <= entry * (1.0 + ret_lte)].head(1)
    if hit.empty:
        return row
    out = parse_exit_legs_return(row, pd.Timestamp(hit.iloc[0]["datetime"]), float(hit.iloc[0]["close"]))
    out["exit_reason"] = f"early_first_close_lte_{ret_lte:.0%}"
    return out


def ema_weak_exit(row: pd.Series, ret_lte: float, consecutive: int = 3) -> pd.Series:
    path = option_path(row)
    if path.empty:
        return row
    entry = float(row["entry_price"])
    path = path.assign(below_ema=path["close"] < path["ema5"], ret=path["close"] / entry - 1.0)
    vals = path.reset_index(drop=True)
    for i in range(consecutive - 1, len(vals)):
        if bool(vals.loc[i - consecutive + 1 : i, "below_ema"].all()) and float(vals.loc[i, "ret"]) <= ret_lte:
            out = parse_exit_legs_return(row, pd.Timestamp(vals.loc[i, "datetime"]), float(vals.loc[i, "close"]))
            out["exit_reason"] = f"early_{consecutive}belowema_lte_{ret_lte:.0%}"
            return out
    return row


def no_followthrough_exit(row: pd.Series, check_time: str, max_high_lt: float, close_lte: float) -> pd.Series:
    path = option_path(row)
    if path.empty:
        return row
    ts = pd.Timestamp(f"{row['trade_date']} {check_time}:00")
    if pd.Timestamp(row["exit_time"]) <= ts:
        return row
    x = path[path["datetime"] <= ts].copy()
    if x.empty:
        return row
    entry = float(row["entry_price"])
    max_high = float(x["high"].max() / entry - 1.0)
    close_ret = float(x.iloc[-1]["close"] / entry - 1.0)
    if max_high < max_high_lt and close_ret <= close_lte:
        out = parse_exit_legs_return(row, pd.Timestamp(x.iloc[-1]["datetime"]), float(x.iloc[-1]["close"]))
        out["exit_reason"] = f"early_no_follow_{check_time}_hi{max_high_lt:.0%}_cl{close_lte:.0%}"
        return out
    return row


def etf_adverse_exit(row: pd.Series, etf15: pd.DataFrame, check_time: str, etf_up_gte: float, opt_ret_lte: float) -> pd.Series:
    if str(row["direction"]) != "put":
        return row
    path = option_path(row)
    if path.empty:
        return row
    ts = pd.Timestamp(f"{row['trade_date']} {check_time}:00")
    if pd.Timestamp(row["exit_time"]) <= ts:
        return row
    x = path[path["datetime"] <= ts].tail(1)
    if x.empty:
        return row
    entry = float(row["entry_price"])
    opt_ret = float(x.iloc[0]["close"] / entry - 1.0)
    if opt_ret > opt_ret_lte:
        return row
    day = etf15[etf15["trade_date"].astype(str).eq(str(row["trade_date"]))]
    entry_etf = day[day["datetime"] <= pd.Timestamp(row["entry_time"])].tail(1)
    check_etf = day[day["datetime"] <= ts].tail(1)
    if entry_etf.empty or check_etf.empty:
        return row
    etf_ret = float(check_etf.iloc[0]["close"] / entry_etf.iloc[0]["close"] - 1.0)
    if etf_ret >= etf_up_gte:
        out = parse_exit_legs_return(row, pd.Timestamp(x.iloc[0]["datetime"]), float(x.iloc[0]["close"]))
        out["exit_reason"] = f"early_etf_up_{check_time}_{etf_up_gte:.1%}_optlte{opt_ret_lte:.0%}"
        return out
    return row


def apply_scenario(trades: pd.DataFrame, etf15: pd.DataFrame, scenario: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for _, row in trades.iterrows():
        if not str(row.get("direction", "")).lower().startswith("put"):
            rows.append(row)
            continue
        kind = scenario["kind"]
        if kind == "timed":
            rows.append(timed_exit(row, scenario["time"], scenario["ret_lte"]))
        elif kind == "threshold":
            rows.append(first_threshold_exit(row, scenario["ret_lte"], scenario.get("not_before")))
        elif kind == "ema":
            rows.append(ema_weak_exit(row, scenario["ret_lte"], scenario.get("consecutive", 3)))
        elif kind == "nofollow":
            rows.append(no_followthrough_exit(row, scenario["time"], scenario["max_high_lt"], scenario["close_lte"]))
        elif kind == "etf":
            rows.append(etf_adverse_exit(row, etf15, scenario["time"], scenario["etf_up_gte"], scenario["opt_ret_lte"]))
        else:
            rows.append(row)
    return pd.DataFrame(rows)


def run(name: str, trades: pd.DataFrame, etf15: pd.DataFrame, scenario: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame]:
    mod = apply_scenario(trades, etf15, scenario)
    capital, summary = calc_capital(mod, slippage_tick=0.0003, max_volume_share=0.05)
    active = capital[~capital["skipped"].fillna(False)].copy()
    row = {
        "scenario": name,
        "final_capital": summary["final_capital"],
        "total_return_pct": summary["total_return"] * 100.0,
        "trades": summary["trades"],
        "win_rate_pct": summary["win_rate"] * 100.0,
        "max_drawdown_pct": summary["max_drawdown"] * 100.0,
        "soft_stop_count": int((active["exit_reason"] == "soft_stop").sum()),
        "early_exit_count": int(active["exit_reason"].astype(str).str.startswith("early_").sum()),
        "early_exit_net_pnl": float(active.loc[active["exit_reason"].astype(str).str.startswith("early_"), "net_pnl"].sum()),
    }
    return row, capital


def main() -> None:
    trades = pd.read_csv(BASELINE_TRADES, parse_dates=["entry_time", "exit_time"])
    trades["early_exit_modified"] = False
    etf15 = load_etf_15m(DEFAULT_SQLITE, ["588000"], str(trades["trade_date"].min()), str(trades["trade_date"].max()))
    scenarios: list[tuple[str, dict[str, Any]]] = [
        ("baseline", {"kind": "none"}),
        ("first_close_lte_neg5", {"kind": "threshold", "ret_lte": -0.05}),
        ("first_close_lte_neg8", {"kind": "threshold", "ret_lte": -0.08}),
        ("first_close_lte_neg10", {"kind": "threshold", "ret_lte": -0.10}),
        ("timed_1000_lte_neg5", {"kind": "timed", "time": "10:00", "ret_lte": -0.05}),
        ("timed_1015_lte_neg5", {"kind": "timed", "time": "10:15", "ret_lte": -0.05}),
        ("timed_1015_lte_neg8", {"kind": "timed", "time": "10:15", "ret_lte": -0.08}),
        ("timed_1030_lte_neg8", {"kind": "timed", "time": "10:30", "ret_lte": -0.08}),
        ("ema3_lte_neg5", {"kind": "ema", "ret_lte": -0.05, "consecutive": 3}),
        ("ema3_lte_neg8", {"kind": "ema", "ret_lte": -0.08, "consecutive": 3}),
        ("nofollow_1015_hi_lt5_cl_lte0", {"kind": "nofollow", "time": "10:15", "max_high_lt": 0.05, "close_lte": 0.0}),
        ("nofollow_1030_hi_lt5_cl_lte_neg3", {"kind": "nofollow", "time": "10:30", "max_high_lt": 0.05, "close_lte": -0.03}),
        ("etf_1000_up05_opt_lte0", {"kind": "etf", "time": "10:00", "etf_up_gte": 0.005, "opt_ret_lte": 0.0}),
        ("etf_1015_up05_opt_lte0", {"kind": "etf", "time": "10:15", "etf_up_gte": 0.005, "opt_ret_lte": 0.0}),
        ("etf_1015_up03_opt_lte_neg3", {"kind": "etf", "time": "10:15", "etf_up_gte": 0.003, "opt_ret_lte": -0.03}),
    ]
    rows = []
    for name, scenario in scenarios:
        if scenario["kind"] == "none":
            capital, summary = calc_capital(trades, slippage_tick=0.0003, max_volume_share=0.05)
            active = capital[~capital["skipped"].fillna(False)].copy()
            row = {
                "scenario": name,
                "final_capital": summary["final_capital"],
                "total_return_pct": summary["total_return"] * 100.0,
                "trades": summary["trades"],
                "win_rate_pct": summary["win_rate"] * 100.0,
                "max_drawdown_pct": summary["max_drawdown"] * 100.0,
                "soft_stop_count": int((active["exit_reason"] == "soft_stop").sum()),
                "early_exit_count": 0,
                "early_exit_net_pnl": 0.0,
            }
        else:
            row, capital = run(name, trades, etf15, scenario)
        rows.append(row)
        capital.to_csv(RESEARCH_DIR / f"soft_stop_early_exit_{name}_capital.csv", index=False)
    summary = pd.DataFrame(rows).sort_values("total_return_pct", ascending=False)
    summary.to_csv(RESEARCH_DIR / "soft_stop_early_exit_summary.csv", index=False)
    print(summary.to_string(index=False))
    print("summary", RESEARCH_DIR / "soft_stop_early_exit_summary.csv")


if __name__ == "__main__":
    main()
