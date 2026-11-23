#!/usr/bin/env python3
"""Sensitivity test for MA20-deviation filters on KCB 09:45 Put reversal add-on."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from backtest_kcb_put_flow_0945 import read_option_1m
from backtest_kcb_put_reversal_0945 import calc_capital


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = ROOT / "research"
DAILY_CSV = ROOT / "data" / "etf_daily_588000_588080.csv"
BASE_TRADES_CSV = RESEARCH_DIR / "full_confirm_tp2_3p0_trades.csv"
ADDON_TRADES_CSV = RESEARCH_DIR / (
    "put_reversal_0945_conservative20_cap5"
    "_etfup0.005_delta0.45_0.6_pos0.2_normal_rankvolume15"
    "_minp0.03_minv1000_slip0.0003_capshare0.05_trades.csv"
)


def load_daily_ma20() -> pd.DataFrame:
    daily = pd.read_csv(DAILY_CSV)
    daily = daily[daily["underlying_code"].astype(str).eq("588000")].copy()
    daily["trade_date"] = pd.to_datetime(daily["trade_date"])
    daily = daily.sort_values("trade_date")
    daily["prev_ma20"] = daily["etf_close"].rolling(20).mean().shift(1)
    daily["prev_close"] = daily["etf_close"].shift(1)
    return daily[["trade_date", "prev_ma20", "prev_close"]]


def enrich_trend(addon: pd.DataFrame) -> pd.DataFrame:
    daily = load_daily_ma20()
    out = addon.copy()
    out["trade_date_dt"] = pd.to_datetime(out["trade_date"])
    out = out.merge(daily, left_on="trade_date_dt", right_on="trade_date", how="left", suffixes=("", "_daily"))
    out["etf_0945_close"] = out["entry_price"] * 0.0 + pd.to_numeric(out["etf_intraday_return"], errors="coerce")
    # kcb_option_flow_15m_events already stores the actual ETF 09:45 close in
    # etf15_close. The generated trade rows did not keep it, so join it back.
    events = pd.read_csv(RESEARCH_DIR / "kcb_option_flow_15m_events.csv")
    events = events[
        (events["time"] == "09:45")
        & (events["option_type"] == "put")
    ][["trade_date", "option_code", "etf15_close"]].copy()
    events["trade_date"] = events["trade_date"].astype(str)
    events["option_code"] = events["option_code"].astype(int)
    out["trade_date_key"] = out["trade_date"].astype(str)
    out["option_code"] = out["option_code"].astype(int)
    out = out.merge(
        events,
        left_on=["trade_date_key", "option_code"],
        right_on=["trade_date", "option_code"],
        how="left",
        suffixes=("", "_event"),
    )
    out["ma20_deviation_0945"] = out["etf15_close"] / out["prev_ma20"] - 1.0
    out["trend_bucket"] = "normal"
    out.loc[out["ma20_deviation_0945"] >= 0.03, "trend_bucket"] = "warm"
    out.loc[out["ma20_deviation_0945"] >= 0.07, "trend_bucket"] = "hot"
    # restore canonical trade_date column after merges
    out["trade_date"] = out["trade_date_key"]
    return out.drop(columns=[c for c in ["trade_date_dt", "trade_date_daily", "trade_date_event", "trade_date_key"] if c in out])


def apply_quick_tp(row: pd.Series, quick_tp: float | None) -> pd.Series:
    if quick_tp is None:
        return row
    entry = float(row["entry_price"])
    target = entry * (1.0 + quick_tp)
    bars = read_option_1m(row["option_code"], str(row["trade_date"]))
    bars = bars[
        (bars["datetime"] >= pd.Timestamp(row["entry_time"]))
        & (bars["datetime"] <= pd.Timestamp(row["exit_time"]))
    ].copy()
    hit = bars[bars["high"] >= target]
    if hit.empty:
        return row
    first = hit.iloc[0]
    row = row.copy()
    row["exit_time"] = first["datetime"]
    row["exit_price_1"] = target
    row["exit_price_2"] = target
    row["return"] = quick_tp
    row["exit_reason"] = "warm_quick_tp_{:.0f}".format(quick_tp * 100)
    row["exit_legs"] = "1.0@{:.6f}".format(target)
    row["tp1_time"] = first["datetime"]
    return row


def build_scenario_addon(
    addon_base: pd.DataFrame,
    mode: str,
    hot_threshold: float | None = None,
    warm_low: float = 0.03,
    warm_position: float = 0.10,
    quick_tp: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    addon = addon_base.copy()
    addon["trend_action"] = "normal"
    addon["trend_skip"] = False
    addon["trend_original_position_pct"] = addon["position_pct"]

    if mode == "hard_ban":
        assert hot_threshold is not None
        addon.loc[addon["ma20_deviation_0945"] >= hot_threshold, "trend_skip"] = True
        addon.loc[addon["trend_skip"], "trend_action"] = f"ban_ge_{hot_threshold:g}"
    elif mode == "three_tier":
        assert hot_threshold is not None
        warm = (addon["ma20_deviation_0945"] >= warm_low) & (addon["ma20_deviation_0945"] < hot_threshold)
        hot = addon["ma20_deviation_0945"] >= hot_threshold
        addon.loc[warm, "position_pct"] = warm_position
        addon.loc[warm, "trend_action"] = f"warm_pos_{warm_position:g}"
        addon.loc[hot, "trend_skip"] = True
        addon.loc[hot, "trend_action"] = f"ban_ge_{hot_threshold:g}"
        if quick_tp is not None:
            adjusted = []
            for _, row in addon.iterrows():
                if row["trend_action"].startswith("warm_pos") and not bool(row["trend_skip"]):
                    adjusted.append(apply_quick_tp(row, quick_tp))
                else:
                    adjusted.append(row)
            addon = pd.DataFrame(adjusted)
    elif mode == "baseline":
        pass
    else:
        raise ValueError(mode)

    filtered = addon[addon["trend_skip"]].copy()
    active = addon[~addon["trend_skip"]].copy()
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
        "total_return": summary["total_return"],
        "trades": summary["trades"],
        "win_rate": summary["win_rate"],
        "max_drawdown": summary["max_drawdown"],
        "addon_active_before_capacity": len(addon),
        "addon_trend_filtered": len(filtered),
        "addon_capacity_skipped": int(addon_cap["skipped"].fillna(False).sum()) if not addon_cap.empty else 0,
        "addon_executed": int((~addon_cap["skipped"].fillna(False)).sum()) if not addon_cap.empty else 0,
        "addon_net_pnl": float(addon_cap["net_pnl"].sum()) if not addon_cap.empty else 0.0,
        "addon_top5_profit_share": top5_profit_share(capital),
        "addon_max_volume_share": float(addon_cap.loc[~addon_cap["skipped"].fillna(False), "volume_share"].max()) if not addon_cap.empty else 0.0,
    }
    return row, capital


def main() -> None:
    base = pd.read_csv(BASE_TRADES_CSV, parse_dates=["entry_time", "exit_time"])
    addon_all = pd.read_csv(ADDON_TRADES_CSV, parse_dates=["entry_time", "exit_time"])
    addon_all = enrich_trend(addon_all)

    base_dates = set(base["trade_date"].astype(str))
    addon_candidates = addon_all[~addon_all["trade_date"].astype(str).isin(base_dates)].copy()

    rows: list[dict[str, Any]] = []
    filtered_rows: list[pd.DataFrame] = []

    scenarios: list[tuple[str, str, float | None, float, float, float | None]] = [
        ("baseline_no_trend_filter", "baseline", None, 0.03, 0.20, None),
    ]
    for threshold in [0.05, 0.06, 0.07, 0.08]:
        scenarios.append((f"hard_ban_ma20dev_ge_{threshold:g}", "hard_ban", threshold, 0.03, 0.20, None))
    for threshold in [0.05, 0.06, 0.07, 0.08]:
        scenarios.append((f"tier_warm3_hot{threshold:g}_pos10_original_exit", "three_tier", threshold, 0.03, 0.10, None))
        scenarios.append((f"tier_warm3_hot{threshold:g}_pos10_quicktp10", "three_tier", threshold, 0.03, 0.10, 0.10))
        scenarios.append((f"tier_warm3_hot{threshold:g}_pos10_quicktp12", "three_tier", threshold, 0.03, 0.10, 0.12))

    for name, mode, hot, warm_low, warm_pos, quick_tp in scenarios:
        addon, filtered = build_scenario_addon(
            addon_candidates,
            mode=mode,
            hot_threshold=hot,
            warm_low=warm_low,
            warm_position=warm_pos,
            quick_tp=quick_tp,
        )
        row, capital = run_scenario(name, base, addon, filtered)
        rows.append(row)
        if not filtered.empty:
            detail = filtered.copy()
            detail["scenario"] = name
            filtered_rows.append(detail)
        capital.to_csv(RESEARCH_DIR / f"put_reversal_trend_filter_{name}_capital.csv", index=False)

    summary = pd.DataFrame(rows).sort_values(["max_drawdown", "total_return"], ascending=[True, False])
    summary.to_csv(RESEARCH_DIR / "put_reversal_trend_filter_summary.csv", index=False)
    if filtered_rows:
        filtered_detail = pd.concat(filtered_rows, ignore_index=True, sort=False)
        filtered_detail[
            [
                "scenario",
                "trade_date",
                "contract_symbol",
                "entry_price",
                "return",
                "exit_reason",
                "ma20_deviation_0945",
                "etf15_close",
                "prev_ma20",
                "etf_intraday_return",
                "day_max_gain_from_open",
                "future_gain_eod",
                "volume15",
                "delta",
                "implied_volatility",
            ]
        ].to_csv(RESEARCH_DIR / "put_reversal_trend_filter_filtered_trades.csv", index=False)

    print(summary.to_string(index=False))
    print("summary", RESEARCH_DIR / "put_reversal_trend_filter_summary.csv")
    print("filtered", RESEARCH_DIR / "put_reversal_trend_filter_filtered_trades.csv")


if __name__ == "__main__":
    main()
