#!/usr/bin/env python3
"""Reverse-analyze KCB option 50%+ opportunity days against ETF 1m patterns.

This is a diagnostic script, not a trading-rule backtest.
It starts from the already-built daily option return distribution and asks:

- Was the best 50%+ option opportunity plausibly identifiable from ETF action
  in the opening window?
- If not, was it identifiable from afternoon ETF acceleration?
- Or was it likely deep-OTM / low-price jump noise?

Outputs:
  research/kcb_50pct_opportunity_pattern_days.csv
  research/kcb_50pct_opportunity_pattern_summary.csv
  research/kcb_50pct_opportunity_pattern_report.md
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backtest_v10_opening_range_b as opening  # noqa: E402


RESEARCH = ROOT / "research"
DATA = ROOT / "data"
OPTION_DIST = RESEARCH / "kcb_option_daily_return_distribution.csv"
OPTION_DAILY = DATA / "kcb_option_daily.csv"
ETF_1M_ROOT = opening.ETF_1M_ROOT
OPTION_FULL_ROOT = DATA / "科创板 1 分钟数据（全）" / "华夏上证科创板50ETF"
INTRADAY_CACHE = DATA / "intraday_cache"

OUT_DAYS = RESEARCH / "kcb_50pct_opportunity_pattern_days.csv"
OUT_SUMMARY = RESEARCH / "kcb_50pct_opportunity_pattern_summary.csv"
OUT_REPORT = RESEARCH / "kcb_50pct_opportunity_pattern_report.md"


def classify_direction(option_type: Any) -> str:
    text = str(option_type).strip().lower()
    if text.startswith("c"):
        return "call"
    if text.startswith("p"):
        return "put"
    return "unknown"


def first_close_at_or_before(df: pd.DataFrame, hhmm: str) -> float | None:
    rows = df[df["time"] <= hhmm]
    if rows.empty:
        return None
    return float(rows.iloc[-1]["close"])


def load_option_1m(trade_date: str, option_code: int | str) -> pd.DataFrame:
    code = str(int(float(option_code))).zfill(8)
    cache = INTRADAY_CACHE / f"{trade_date}_{code}_1m.csv"
    if cache.exists():
        raw = pd.read_csv(cache)
    else:
        ym = trade_date[:7]
        member = f"SSE.{code}.csv"
        zip_path = OPTION_FULL_ROOT / f"{ym}.zip"
        folder_path = OPTION_FULL_ROOT / ym / member
        if zip_path.exists():
            with zipfile.ZipFile(zip_path) as zf:
                if member not in zf.namelist():
                    return pd.DataFrame()
                with zf.open(member) as fh:
                    raw = pd.read_csv(fh)
        elif folder_path.exists():
            raw = pd.read_csv(folder_path)
        else:
            return pd.DataFrame()
    raw = raw.rename(
        columns={
            "时间": "datetime",
            "开盘价": "open",
            "最高价": "high",
            "最低价": "low",
            "收盘价": "close",
            "成交量": "volume",
        }
    )
    raw["datetime"] = pd.to_datetime(raw["datetime"], errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    out = raw.dropna(subset=["datetime", "close"]).copy()
    out = out[out["datetime"].dt.strftime("%Y-%m-%d") == trade_date]
    out["time"] = out["datetime"].dt.strftime("%H:%M")
    return out.sort_values("datetime")


def option_timing_metrics(trade_date: str, option_code: int | str, open_price: float) -> dict[str, Any]:
    out = {
        "option_high_time": "",
        "option_gain_by_0935": pd.NA,
        "option_gain_by_0945": pd.NA,
        "option_gain_by_1000": pd.NA,
        "option_max_gain_before_0935_share": pd.NA,
        "option_max_gain_before_0945_share": pd.NA,
        "option_max_gain_before_1000_share": pd.NA,
    }
    bars = load_option_1m(trade_date, option_code)
    if bars.empty or not open_price or open_price <= 0:
        return out
    high_idx = bars["high"].idxmax()
    max_gain = float(bars.loc[high_idx, "high"] / open_price - 1.0)
    out["option_high_time"] = str(bars.loc[high_idx, "datetime"])
    for hhmm in ["09:35", "09:45", "10:00"]:
        window = bars[bars["time"] <= hhmm]
        if window.empty:
            continue
        gain = float(window["high"].max() / open_price - 1.0)
        out[f"option_gain_by_{hhmm.replace(':', '')}"] = gain
        out[f"option_max_gain_before_{hhmm.replace(':', '')}_share"] = (
            gain / max_gain if max_gain > 0 else pd.NA
        )
    return out


def etf_pattern_metrics(etf1: pd.DataFrame, direction: str) -> dict[str, Any]:
    result = {
        "etf_missing": etf1.empty,
        "early_identifiable": False,
        "afternoon_identifiable": False,
        "early_reason": "",
        "afternoon_reason": "",
        "etf_open": pd.NA,
        "etf_close_1000": pd.NA,
        "early_call_high_gain": pd.NA,
        "early_put_low_gain": pd.NA,
        "afternoon_call_high_gain": pd.NA,
        "afternoon_put_low_gain": pd.NA,
        "best_afternoon_15m_move": pd.NA,
        "best_afternoon_15m_vol_ratio": pd.NA,
    }
    if etf1.empty or direction not in ["call", "put"]:
        return result
    etf1 = etf1.copy().sort_values("datetime")
    day_open = float(etf1.iloc[0]["open"])
    result["etf_open"] = day_open
    result["etf_close_1000"] = first_close_at_or_before(etf1, "10:00")

    early = etf1[etf1["time"] <= "10:00"]
    if not early.empty and day_open > 0:
        call_high_gain = float(early["high"].max() / day_open - 1.0)
        put_low_gain = float(day_open / early["low"].min() - 1.0)
        close_1000 = float(early.iloc[-1]["close"])
        result["early_call_high_gain"] = call_high_gain
        result["early_put_low_gain"] = put_low_gain
        if direction == "call" and call_high_gain >= 0.006 and close_1000 / day_open - 1.0 >= 0.002:
            result["early_identifiable"] = True
            result["early_reason"] = "call_opening_directional_move"
        if direction == "put" and put_low_gain >= 0.006 and close_1000 / day_open - 1.0 <= -0.002:
            result["early_identifiable"] = True
            result["early_reason"] = "put_opening_directional_move"

    lunch_rows = etf1[etf1["time"] <= "11:30"]
    afternoon = etf1[etf1["time"] >= "13:00"]
    lunch_close = float(lunch_rows.iloc[-1]["close"]) if not lunch_rows.empty else day_open
    if not afternoon.empty and lunch_close > 0:
        aft_call = float(afternoon["high"].max() / lunch_close - 1.0)
        aft_put = float(lunch_close / afternoon["low"].min() - 1.0)
        result["afternoon_call_high_gain"] = aft_call
        result["afternoon_put_low_gain"] = aft_put

        bars15 = etf1.set_index("datetime").resample("15min", label="right", closed="right").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna(subset=["open", "close"])
        bars15["time"] = bars15.index.strftime("%H:%M")
        bars15 = bars15[(bars15["time"] >= "09:45") & (bars15["time"] <= "14:45")].copy()
        bars15["dir_move"] = bars15["close"] / bars15["open"] - 1.0
        if direction == "put":
            bars15["dir_move"] = bars15["open"] / bars15["close"] - 1.0
        bars15["vol_base"] = bars15["volume"].rolling(5, min_periods=3).mean().shift(1)
        bars15["vol_ratio"] = bars15["volume"] / bars15["vol_base"]
        aft15 = bars15[bars15["time"] >= "13:15"]
        if not aft15.empty:
            best = aft15.sort_values("dir_move", ascending=False).iloc[0]
            result["best_afternoon_15m_move"] = float(best["dir_move"])
            result["best_afternoon_15m_vol_ratio"] = float(best["vol_ratio"]) if pd.notna(best["vol_ratio"]) else pd.NA
        if direction == "call" and (aft_call >= 0.008 or ((aft15["dir_move"] >= 0.006) & (aft15["vol_ratio"] >= 1.8)).any()):
            result["afternoon_identifiable"] = True
            result["afternoon_reason"] = "call_afternoon_acceleration"
        if direction == "put" and (aft_put >= 0.008 or ((aft15["dir_move"] >= 0.006) & (aft15["vol_ratio"] >= 1.8)).any()):
            result["afternoon_identifiable"] = True
            result["afternoon_reason"] = "put_afternoon_acceleration"
    return result


def main() -> None:
    dist = pd.read_csv(OPTION_DIST)
    dist["trade_date"] = pd.to_datetime(dist["trade_date"]).dt.strftime("%Y-%m-%d")
    dist["option_code"] = dist["option_code"].astype(str).str.replace(r"\.0$", "", regex=True)
    for col in ["open", "high", "volume", "max_intraday_gain"]:
        dist[col] = pd.to_numeric(dist[col], errors="coerce")
    opp = dist[(dist["open"] >= 0.005) & (dist["volume"] >= 1000) & (dist["max_intraday_gain"] >= 0.50)].copy()

    daily = pd.read_csv(OPTION_DAILY, dtype={"option_code": str, "underlying_code": str})
    daily["trade_date"] = pd.to_datetime(daily["trade_date"]).dt.strftime("%Y-%m-%d")
    keep_cols = [
        "trade_date",
        "option_code",
        "contract_id",
        "contract_symbol",
        "option_type",
        "strike",
        "delta",
        "implied_volatility",
        "option_volume",
        "etf_return",
    ]
    daily = daily[[c for c in keep_cols if c in daily.columns]].copy()
    opp = opp.merge(daily, on=["trade_date", "option_code"], how="left", suffixes=("", "_daily"))

    best = opp.sort_values(["trade_date", "max_intraday_gain"], ascending=[True, False]).groupby("trade_date").head(1)
    rows: list[dict[str, Any]] = []
    for item in best.to_dict("records"):
        trade_date = item["trade_date"]
        direction = classify_direction(item.get("option_type"))
        etf1 = opening.load_etf_1m(ETF_1M_ROOT, trade_date, "588000")
        pattern = etf_pattern_metrics(etf1, direction)
        abs_delta = abs(float(item["delta"])) if pd.notna(item.get("delta")) else pd.NA
        low_price_noise = float(item["open"]) < 0.010
        deep_delta_noise = pd.notna(abs_delta) and abs_delta < 0.15
        likely_noise = bool(low_price_noise or deep_delta_noise)

        if likely_noise:
            bucket = "deep_otm_or_jump_noise"
        elif pattern["early_identifiable"]:
            bucket = "early_identifiable"
        elif pattern["afternoon_identifiable"]:
            bucket = "afternoon_identifiable"
        else:
            bucket = "not_identifiable_by_etf_heuristic"

        timing = option_timing_metrics(trade_date, item["option_code"], float(item["open"]))
        rows.append(
            {
                **item,
                "direction": direction,
                "abs_delta": abs_delta,
                "likely_noise": likely_noise,
                "noise_low_open_price": low_price_noise,
                "noise_deep_delta": deep_delta_noise,
                "classification": bucket,
                **pattern,
                **timing,
            }
        )

    out = pd.DataFrame(rows).sort_values("trade_date")
    out.to_csv(OUT_DAYS, index=False)

    summary_rows: list[dict[str, Any]] = []
    total = len(out)
    for key, group in out.groupby("classification", dropna=False):
        summary_rows.append(
            {
                "classification": key,
                "days": len(group),
                "share": len(group) / total if total else 0,
                "median_best_gain": group["max_intraday_gain"].median(),
                "max_best_gain": group["max_intraday_gain"].max(),
            }
        )
    for key, group in out.groupby("direction", dropna=False):
        summary_rows.append(
            {
                "classification": f"direction_{key}",
                "days": len(group),
                "share": len(group) / total if total else 0,
                "median_best_gain": group["max_intraday_gain"].median(),
                "max_best_gain": group["max_intraday_gain"].max(),
            }
        )
    timing_cols = [
        ("option_max_gain_before_0935_share", "best_option_gain_share_by_0935_ge_50pct"),
        ("option_max_gain_before_0945_share", "best_option_gain_share_by_0945_ge_50pct"),
        ("option_max_gain_before_1000_share", "best_option_gain_share_by_1000_ge_50pct"),
    ]
    for col, name in timing_cols:
        clean = pd.to_numeric(out[col], errors="coerce")
        summary_rows.append(
            {
                "classification": name,
                "days": int((clean >= 0.50).sum()),
                "share": float((clean >= 0.50).mean()),
                "median_best_gain": float(clean.median()),
                "max_best_gain": float(clean.max()),
            }
        )
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(OUT_SUMMARY, index=False)

    counts = out["classification"].value_counts().to_dict()
    direction_counts = out["direction"].value_counts().to_dict()
    lines = [
        "# 科创板期权 50%+ 机会日 ETF 反推诊断",
        "",
        f"- 机会定义：期权开盘价 >= 0.005、当日成交量 >= 1000、日内最高涨幅 >= 50%。",
        f"- 机会日数量：{total} 天。",
        f"- 数据区间：{out['trade_date'].min()} 到 {out['trade_date'].max()}。",
        f"- 方向分布：{direction_counts}。",
        "",
        "## 分类结果",
        "",
    ]
    for key in [
        "early_identifiable",
        "afternoon_identifiable",
        "not_identifiable_by_etf_heuristic",
        "deep_otm_or_jump_noise",
    ]:
        days = counts.get(key, 0)
        lines.append(f"- {key}: {days} 天，占 {days / total:.1%}。")
    lines.extend(
        [
            "",
            "## 期权涨幅发生速度",
            "",
        ]
    )
    for col, label in [
        ("option_max_gain_before_0935_share", "09:35 前已走出全天最大涨幅 50% 以上"),
        ("option_max_gain_before_0945_share", "09:45 前已走出全天最大涨幅 50% 以上"),
        ("option_max_gain_before_1000_share", "10:00 前已走出全天最大涨幅 50% 以上"),
    ]:
        clean = pd.to_numeric(out[col], errors="coerce")
        lines.append(f"- {label}: {int((clean >= 0.50).sum())} 天，占 {(clean >= 0.50).mean():.1%}；中位完成度 {clean.median():.1%}。")
    lines.extend(
        [
            "",
            "## 启发式说明",
            "",
            "- early_identifiable：ETF 在 10:00 前已出现与机会方向一致的 >=0.6% 日内方向运动，且 10:00 收盘仍有方向确认。",
            "- afternoon_identifiable：未早盘识别，但午后从午盘基准出现 >=0.8% 方向运动，或 15 分钟方向K线 >=0.6% 且量能 >=1.8 倍。",
            "- deep_otm_or_jump_noise：当天最佳机会合约开盘价 <0.01，或有 delta 且 |delta|<0.15，优先判为疑似深虚/跳价噪音。",
            "- not_identifiable_by_etf_heuristic：不满足上述 ETF 识别和噪音规则；不是说一定不能交易，只是 ETF 形态不够直接。",
            "",
            f"明细：`{OUT_DAYS}`",
            f"汇总：`{OUT_SUMMARY}`",
        ]
    )
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_DAYS}")
    print(f"Wrote {OUT_SUMMARY}")
    print(f"Wrote {OUT_REPORT}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
