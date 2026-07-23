#!/usr/bin/env python3
"""Sensitivity tests for 09:45 Put reversal exit and ETF-wick filters.

This is a research-only script.  It does not change the formal strategy.
It starts from the already-generated conservative 09:45 Put reversal trades
and changes only two things:

1. Early profit taking when ETF is above the previous daily MA20.
2. Entry confirmation using the 09:45 ETF 15m upper/lower shadow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from backtest_kcb_put_flow_0945 import read_option_1m
from backtest_kcb_put_reversal_0945 import calc_capital
from backtest_v02_recent_intraday import DEFAULT_SQLITE, load_etf_15m


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = ROOT / "research"
DAILY_CSV = ROOT / "data" / "etf_daily_588000_588080.csv"
BASE_TRADES_CSV = RESEARCH_DIR / "full_confirm_tp2_3p0_trades.csv"
ADDON_TRADES_CSV = RESEARCH_DIR / (
    "put_reversal_0945_conservative20_cap5"
    "_etfup0.005_delta0.45_0.6_pos0.2_normal_rankvolume15"
    "_minp0.03_minv1000_slip0.0003_capshare0.05_trades.csv"
)
EVENTS_CSV = RESEARCH_DIR / "kcb_option_flow_15m_events.csv"


def load_daily_ma20() -> pd.DataFrame:
    daily = pd.read_csv(DAILY_CSV)
    daily = daily[daily["underlying_code"].astype(str).eq("588000")].copy()
    daily["trade_date"] = pd.to_datetime(daily["trade_date"])
    daily = daily.sort_values("trade_date")
    daily["prev_ma20"] = daily["etf_close"].rolling(20).mean().shift(1)
    return daily[["trade_date", "prev_ma20"]]


def enrich_addon(addon: pd.DataFrame) -> pd.DataFrame:
    out = addon.copy()
    out["trade_date_key"] = out["trade_date"].astype(str)
    out["option_code"] = out["option_code"].astype(int)

    daily = load_daily_ma20()
    out["trade_date_dt"] = pd.to_datetime(out["trade_date_key"])
    out = out.merge(
        daily,
        left_on="trade_date_dt",
        right_on="trade_date",
        how="left",
        suffixes=("", "_daily"),
    )

    events = pd.read_csv(EVENTS_CSV)
    events = events[
        (events["time"] == "09:45")
        & (events["option_type"] == "put")
    ][
        [
            "trade_date",
            "option_code",
            "etf15_close",
            "etf_intraday_return",
            "etf15_volume",
        ]
    ].copy()
    events["trade_date_key"] = events["trade_date"].astype(str)
    events["option_code"] = events["option_code"].astype(int)
    events = events.drop(columns=["trade_date"])

    out = out.merge(
        events,
        on=["trade_date_key", "option_code"],
        how="left",
        suffixes=("", "_event"),
    )

    start = str(pd.to_datetime(out["trade_date_key"]).min().date())
    end = str(pd.to_datetime(out["trade_date_key"]).max().date())
    candles = load_etf_15m(DEFAULT_SQLITE, ["588000"], start, end)
    candles = candles[
        (candles["underlying_code"].astype(str) == "588000")
        & (candles["time"] == "09:45")
    ][["trade_date", "open", "high", "low", "close"]].copy()
    candles = candles.rename(
        columns={
            "trade_date": "trade_date_key",
            "open": "etf15_open_real",
            "high": "etf15_high_real",
            "low": "etf15_low_real",
            "close": "etf15_close_real",
        }
    )
    candles["trade_date_key"] = candles["trade_date_key"].astype(str)
    out = out.merge(candles, on="trade_date_key", how="left")

    out["etf15_open_real"] = pd.to_numeric(out["etf15_open_real"], errors="coerce")
    out["etf15_high_real"] = pd.to_numeric(out["etf15_high_real"], errors="coerce")
    out["etf15_low_real"] = pd.to_numeric(out["etf15_low_real"], errors="coerce")
    out["etf15_close_real"] = pd.to_numeric(out["etf15_close_real"], errors="coerce")
    out["etf15_close"] = pd.to_numeric(out["etf15_close"], errors="coerce").fillna(out["etf15_close_real"])
    out["ma20_deviation_0945"] = out["etf15_close"] / out["prev_ma20"] - 1.0
    out["above_prev_ma20"] = out["etf15_close"] > out["prev_ma20"]
    out["above_prev_ma20_3pct"] = out["etf15_close"] >= out["prev_ma20"] * 1.03
    out["upper_shadow"] = (out["etf15_high_real"] - out["etf15_close_real"]).clip(lower=0)
    out["lower_shadow"] = (out["etf15_open_real"] - out["etf15_low_real"]).clip(lower=0)
    out["wick_ratio"] = out["upper_shadow"] / out["lower_shadow"].replace(0, pd.NA)
    out["close_pullback_from_high"] = out["etf15_high_real"] / out["etf15_close_real"] - 1.0
    out["trade_date"] = out["trade_date_key"]
    drop_cols = [
        "trade_date_dt",
        "trade_date_daily",
        "trade_date_key",
    ]
    return out.drop(columns=[c for c in drop_cols if c in out.columns])


def first_option_price_at_or_before(
    option_code: int,
    trade_date: str,
    end_time: pd.Timestamp,
    start_time: pd.Timestamp,
) -> tuple[pd.Timestamp, float] | None:
    bars = read_option_1m(option_code, trade_date)
    window = bars[(bars["datetime"] > start_time) & (bars["datetime"] <= end_time)].copy()
    if window.empty:
        return None
    row = window.iloc[-1]
    return pd.Timestamp(row["datetime"]), float(row["close"])


def apply_early_tp(
    row: pd.Series,
    *,
    trend_col: str,
    quick_tp: float | None,
    force_1300: bool,
) -> pd.Series:
    if not bool(row.get(trend_col, False)):
        return row
    entry = float(row["entry_price"])
    entry_time = pd.Timestamp(row["entry_time"])
    exit_time = pd.Timestamp(row["exit_time"])
    trade_date = str(row["trade_date"])
    bars = read_option_1m(row["option_code"], trade_date)
    path = bars[(bars["datetime"] > entry_time) & (bars["datetime"] <= exit_time)].copy()
    if path.empty:
        return row

    if quick_tp is not None:
        target = entry * (1.0 + quick_tp)
        hit = path[path["high"] >= target]
        if not hit.empty:
            first = hit.iloc[0]
            out = row.copy()
            out["exit_time"] = pd.Timestamp(first["datetime"])
            out["exit_price_1"] = target
            out["exit_price_2"] = target
            out["return"] = quick_tp
            out["exit_reason"] = f"trend_quick_tp_{quick_tp:.0%}"
            out["exit_legs"] = f"1.0@{target:.6f}"
            out["tp1_time"] = pd.Timestamp(first["datetime"])
            out["exit_modified"] = True
            return out

    if force_1300 and exit_time > pd.Timestamp(f"{trade_date} 13:00:00"):
        forced = first_option_price_at_or_before(
            int(row["option_code"]),
            trade_date,
            pd.Timestamp(f"{trade_date} 13:00:00"),
            entry_time,
        )
        if forced is not None:
            forced_time, forced_price = forced
            out = row.copy()
            out["exit_time"] = forced_time
            out["exit_price_1"] = forced_price
            out["exit_price_2"] = forced_price
            out["return"] = forced_price / entry - 1.0
            out["exit_reason"] = "trend_force_1300"
            out["exit_legs"] = f"1.0@{forced_price:.6f}"
            out["exit_modified"] = True
            return out

    return row


def build_addon(
    addon: pd.DataFrame,
    *,
    wick_ratio_min: float | None = None,
    pullback_min: float | None = None,
    quick_tp: float | None = None,
    trend_col: str = "above_prev_ma20",
    force_1300: bool = False,
    wick_only_when_trend: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = addon.copy()
    df["filter_reason"] = ""
    df["exit_modified"] = False

    keep = pd.Series(True, index=df.index)
    if wick_ratio_min is not None:
        wick_ok = df["wick_ratio"].fillna(-1) >= wick_ratio_min
        if wick_only_when_trend:
            wick_ok = (~df[trend_col].fillna(False)) | wick_ok
        keep &= wick_ok
        df.loc[~wick_ok, "filter_reason"] += f"wick_lt_{wick_ratio_min:g};"
    if pullback_min is not None:
        pullback_ok = df["close_pullback_from_high"].fillna(-1) >= pullback_min
        if wick_only_when_trend:
            pullback_ok = (~df[trend_col].fillna(False)) | pullback_ok
        keep &= pullback_ok
        df.loc[~pullback_ok, "filter_reason"] += f"pullback_lt_{pullback_min:g};"

    filtered = df[~keep].copy()
    active = df[keep].copy()

    if quick_tp is not None or force_1300:
        rows = []
        for _, row in active.iterrows():
            rows.append(
                apply_early_tp(
                    row,
                    trend_col=trend_col,
                    quick_tp=quick_tp,
                    force_1300=force_1300,
                )
            )
        active = pd.DataFrame(rows)

    return active, filtered


def top5_profit_share(capital: pd.DataFrame) -> float:
    active = capital[~capital["skipped"].fillna(False)].copy()
    addon = active[active["contract_id"].astype(str).str.contains("P_REV", na=False)].copy()
    total = float(addon["net_pnl"].sum())
    if total == 0:
        return 0.0
    return float(addon["net_pnl"].sort_values(ascending=False).head(5).sum() / total)


def run_scenario(name: str, base: pd.DataFrame, addon: pd.DataFrame, filtered: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    combined = pd.concat([base, addon], ignore_index=True, sort=False).sort_values("entry_time")
    capital, summary = calc_capital(
        combined,
        slippage_tick=0.0003,
        max_volume_share=0.05,
    )
    addon_cap = capital[capital["contract_id"].astype(str).str.contains("P_REV", na=False)].copy()
    row = {
        "scenario": name,
        "final_capital": summary["final_capital"],
        "total_return_pct": summary["total_return"] * 100.0,
        "trades": summary["trades"],
        "win_rate_pct": summary["win_rate"] * 100.0,
        "max_drawdown_pct": summary["max_drawdown"] * 100.0,
        "addon_active_before_capacity": len(addon),
        "addon_filtered": len(filtered),
        "addon_capacity_skipped": int(addon_cap["skipped"].fillna(False).sum()) if not addon_cap.empty else 0,
        "addon_executed": int((~addon_cap["skipped"].fillna(False)).sum()) if not addon_cap.empty else 0,
        "addon_exit_modified": int(addon.get("exit_modified", pd.Series(False, index=addon.index)).fillna(False).sum()) if not addon.empty else 0,
        "addon_net_pnl": float(addon_cap["net_pnl"].sum()) if not addon_cap.empty else 0.0,
        "addon_top5_profit_share": top5_profit_share(capital),
        "addon_max_volume_share_pct": (
            float(addon_cap.loc[~addon_cap["skipped"].fillna(False), "volume_share"].max()) * 100.0
            if not addon_cap.empty
            else 0.0
        ),
    }
    return row, capital


def main() -> None:
    base = pd.read_csv(BASE_TRADES_CSV, parse_dates=["entry_time", "exit_time"])
    addon_all = pd.read_csv(ADDON_TRADES_CSV, parse_dates=["entry_time", "exit_time"])
    addon_all = enrich_addon(addon_all)

    base_dates = set(base["trade_date"].astype(str))
    addon_candidates = addon_all[~addon_all["trade_date"].astype(str).isin(base_dates)].copy()

    scenarios: list[dict[str, Any]] = [
        {"name": "baseline"},
        {"name": "trend_ma20_tp8", "quick_tp": 0.08},
        {"name": "trend_ma20_tp10", "quick_tp": 0.10},
        {"name": "trend_ma20_tp12", "quick_tp": 0.12},
        {"name": "trend_ma20_tp10_force1300", "quick_tp": 0.10, "force_1300": True},
        {"name": "trend_ma20_tp12_force1300", "quick_tp": 0.12, "force_1300": True},
        {"name": "trend_ma20dev3_tp10", "quick_tp": 0.10, "trend_col": "above_prev_ma20_3pct"},
        {"name": "trend_ma20dev3_tp12", "quick_tp": 0.12, "trend_col": "above_prev_ma20_3pct"},
        {"name": "wick_ratio_ge_1p0", "wick_ratio_min": 1.0},
        {"name": "wick_ratio_ge_1p2", "wick_ratio_min": 1.2},
        {"name": "wick_ratio_ge_1p5", "wick_ratio_min": 1.5},
        {"name": "wick_ratio_ge_1p0_pullback15bp", "wick_ratio_min": 1.0, "pullback_min": 0.0015},
        {"name": "wick_ratio_ge_1p2_pullback15bp", "wick_ratio_min": 1.2, "pullback_min": 0.0015},
        {"name": "combo_wick1p0_trend_tp10", "wick_ratio_min": 1.0, "quick_tp": 0.10, "wick_only_when_trend": True},
        {"name": "combo_wick1p2_trend_tp10", "wick_ratio_min": 1.2, "quick_tp": 0.10, "wick_only_when_trend": True},
        {"name": "combo_wick1p0_trend_tp12", "wick_ratio_min": 1.0, "quick_tp": 0.12, "wick_only_when_trend": True},
        {"name": "combo_wick1p2_trend_tp12", "wick_ratio_min": 1.2, "quick_tp": 0.12, "wick_only_when_trend": True},
        {"name": "combo_wick1p0_trend_tp10_force1300", "wick_ratio_min": 1.0, "quick_tp": 0.10, "force_1300": True, "wick_only_when_trend": True},
    ]

    rows: list[dict[str, Any]] = []
    filtered_rows: list[pd.DataFrame] = []
    modified_rows: list[pd.DataFrame] = []
    for scenario in scenarios:
        name = scenario.pop("name")
        active, filtered = build_addon(addon_candidates, **scenario)
        row, capital = run_scenario(name, base, active, filtered)
        rows.append(row)
        capital.to_csv(RESEARCH_DIR / f"put_reversal_exit_wick_{name}_capital.csv", index=False)
        if not filtered.empty:
            tmp = filtered.copy()
            tmp["scenario"] = name
            filtered_rows.append(tmp)
        if "exit_modified" in active.columns and active["exit_modified"].fillna(False).any():
            tmp = active[active["exit_modified"].fillna(False)].copy()
            tmp["scenario"] = name
            modified_rows.append(tmp)

    summary = pd.DataFrame(rows).sort_values("total_return_pct", ascending=False)
    summary.to_csv(RESEARCH_DIR / "put_reversal_exit_wick_summary.csv", index=False)

    columns = [
        "scenario",
        "trade_date",
        "contract_symbol",
        "entry_price",
        "exit_time",
        "return",
        "exit_reason",
        "ma20_deviation_0945",
        "wick_ratio",
        "upper_shadow",
        "lower_shadow",
        "close_pullback_from_high",
        "etf_intraday_return",
        "volume15",
        "delta",
        "implied_volatility",
    ]
    if filtered_rows:
        pd.concat(filtered_rows, ignore_index=True, sort=False)[
            [c for c in columns + ["filter_reason"] if c in pd.concat(filtered_rows, ignore_index=True, sort=False).columns]
        ].to_csv(RESEARCH_DIR / "put_reversal_exit_wick_filtered_trades.csv", index=False)
    if modified_rows:
        pd.concat(modified_rows, ignore_index=True, sort=False)[
            [c for c in columns if c in pd.concat(modified_rows, ignore_index=True, sort=False).columns]
        ].to_csv(RESEARCH_DIR / "put_reversal_exit_wick_modified_exits.csv", index=False)

    print(summary.to_string(index=False))
    print("summary", RESEARCH_DIR / "put_reversal_exit_wick_summary.csv")
    print("filtered", RESEARCH_DIR / "put_reversal_exit_wick_filtered_trades.csv")
    print("modified", RESEARCH_DIR / "put_reversal_exit_wick_modified_exits.csv")


if __name__ == "__main__":
    main()
