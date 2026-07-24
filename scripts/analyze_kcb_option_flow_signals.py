#!/usr/bin/env python3
"""Analyze KCB option flow signals from local 1m option archives.

The goal is diagnostic, not a portfolio backtest:

- Build 15m signal events for KCB ETF options near ATM (ATM +/- N strikes).
- Use only data available at each 15m timestamp.
- Measure future option upside from the signal timestamp to end of day.
- Summarize whether volume/OI/price-breakout flow signals have edge.

Outputs:
  research/kcb_option_flow_15m_events.csv
  research/kcb_option_flow_signal_summary.csv
  research/kcb_option_flow_signal_report.md
"""

from __future__ import annotations

import argparse
import math
import sys
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backtest_v10_opening_range_b as opening  # noqa: E402


DATA = ROOT / "data"
RESEARCH = ROOT / "research"
OPTION_DAILY = DATA / "kcb_option_daily.csv"
OPTION_FULL_ROOT = DATA / "科创板 1 分钟数据（全）" / "华夏上证科创板50ETF"
INTRADAY_CACHE = DATA / "intraday_cache"
ETF_1M_ROOT = opening.ETF_1M_ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2023-06-06")
    parser.add_argument("--end", default="2026-06-30")
    parser.add_argument("--atm-rank", type=int, default=2, help="Use ATM +/- N strikes per option side.")
    parser.add_argument("--min-close", type=float, default=0.005)
    parser.add_argument("--min-bar-volume", type=float, default=100)
    parser.add_argument("--output-events", type=Path, default=RESEARCH / "kcb_option_flow_15m_events.csv")
    parser.add_argument("--output-summary", type=Path, default=RESEARCH / "kcb_option_flow_signal_summary.csv")
    parser.add_argument("--output-report", type=Path, default=RESEARCH / "kcb_option_flow_signal_report.md")
    return parser.parse_args()


def option_code_text(value: Any) -> str:
    try:
        return str(int(float(value))).zfill(8)
    except Exception:
        return str(value).strip().zfill(8)


def load_option_1m(trade_date: str, option_code: str) -> pd.DataFrame:
    code = option_code_text(option_code)
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
            "开仓持仓": "open_oi",
            "收盘持仓": "close_oi",
        }
    )
    raw["datetime"] = pd.to_datetime(raw["datetime"], errors="coerce")
    for col in ["open", "high", "low", "close", "volume", "open_oi", "close_oi"]:
        if col in raw.columns:
            raw[col] = pd.to_numeric(raw[col], errors="coerce")
        else:
            raw[col] = math.nan
    out = raw.dropna(subset=["datetime", "close"]).copy()
    out = out[out["datetime"].dt.strftime("%Y-%m-%d") == trade_date]
    out["time"] = out["datetime"].dt.strftime("%H:%M")
    return out.sort_values("datetime")


def build_daily_candidates(args: argparse.Namespace) -> pd.DataFrame:
    daily = pd.read_csv(OPTION_DAILY, dtype={"option_code": str, "underlying_code": str})
    daily["trade_date"] = pd.to_datetime(daily["trade_date"], errors="coerce")
    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    daily = daily[(daily["trade_date"] >= start) & (daily["trade_date"] <= end)].copy()
    daily = daily[daily["underlying_code"].astype(str) == "588000"].copy()
    for col in ["strike", "etf_open", "option_open", "option_volume", "delta", "implied_volatility"]:
        daily[col] = pd.to_numeric(daily[col], errors="coerce")
    daily["option_code"] = daily["option_code"].map(option_code_text)
    daily["option_type"] = daily["option_type"].astype(str).str.lower()
    daily["abs_moneyness_dist"] = (daily["strike"] - daily["etf_open"]).abs()
    daily = daily.dropna(subset=["trade_date", "strike", "etf_open", "option_open"])

    parts: list[pd.DataFrame] = []
    for (_, side), group in daily.groupby(["trade_date", "option_type"]):
        group = group.sort_values(["abs_moneyness_dist", "strike"]).copy()
        group["atm_rank"] = range(len(group))
        parts.append(group[group["atm_rank"] <= args.atm_rank].copy())
    candidates = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    candidates["trade_date"] = candidates["trade_date"].dt.strftime("%Y-%m-%d")

    daily_all = daily.copy()
    daily_all["trade_date_text"] = daily_all["trade_date"].dt.strftime("%Y-%m-%d")
    daily_all = daily_all.sort_values(["option_code", "trade_date"])
    daily_all["prior5_daily_volume"] = (
        daily_all.groupby("option_code")["option_volume"]
        .transform(lambda s: s.shift(1).rolling(5, min_periods=2).mean())
    )
    daily_all["prior_iv"] = daily_all.groupby("option_code")["implied_volatility"].shift(1)
    candidates = candidates.merge(
        daily_all[["trade_date_text", "option_code", "prior5_daily_volume", "prior_iv"]],
        left_on=["trade_date", "option_code"],
        right_on=["trade_date_text", "option_code"],
        how="left",
    )
    candidates = candidates.drop(columns=["trade_date_text"], errors="ignore")
    return candidates


def future_gain_after(bars: pd.DataFrame, when: pd.Timestamp, price: float, minutes: int | None = None) -> float:
    path = bars[bars["datetime"] > when]
    if minutes is not None:
        path = path[path["datetime"] <= when + pd.Timedelta(minutes=minutes)]
    if path.empty or price <= 0:
        return math.nan
    return float(path["high"].max() / price - 1.0)


def build_contract_events(row: pd.Series) -> pd.DataFrame:
    trade_date = str(row["trade_date"])
    code = option_code_text(row["option_code"])
    bars = load_option_1m(trade_date, code)
    if bars.empty:
        return pd.DataFrame()

    bars = bars.copy()
    bars["ema5_1m"] = bars["close"].ewm(span=5, adjust=False).mean()
    bars["ema20_1m"] = bars["close"].ewm(span=20, adjust=False).mean()
    bars["bar15_time"] = bars["datetime"].dt.floor("15min") + pd.Timedelta(minutes=15)
    grouped = bars.groupby("bar15_time").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume15=("volume", "sum"),
        open_oi=("open_oi", "first"),
        close_oi=("close_oi", "last"),
        ema5_1m=("ema5_1m", "last"),
        ema20_1m=("ema20_1m", "last"),
    ).dropna(subset=["close"]).reset_index()
    grouped = grouped.rename(columns={"bar15_time": "datetime"})
    grouped = grouped[(grouped["datetime"].dt.strftime("%H:%M") >= "09:45") & (grouped["datetime"].dt.strftime("%H:%M") <= "14:45")].copy()
    if grouped.empty:
        return pd.DataFrame()
    first_open_oi = grouped["open_oi"].dropna().iloc[0] if grouped["open_oi"].notna().any() else math.nan
    grouped["time"] = grouped["datetime"].dt.strftime("%H:%M")
    grouped["trade_date"] = trade_date
    grouped["option_code"] = code
    grouped["contract_id"] = row.get("contract_id", "")
    grouped["contract_symbol"] = row.get("contract_symbol", "")
    grouped["option_type"] = row.get("option_type", "")
    grouped["strike"] = row.get("strike", math.nan)
    grouped["atm_rank"] = row.get("atm_rank", math.nan)
    grouped["delta"] = row.get("delta", math.nan)
    grouped["abs_delta"] = abs(float(row.get("delta"))) if pd.notna(row.get("delta")) else math.nan
    grouped["iv"] = row.get("implied_volatility", math.nan)
    grouped["prior_iv"] = row.get("prior_iv", math.nan)
    grouped["iv_change_vs_prior"] = grouped["iv"] - grouped["prior_iv"]
    grouped["prior5_daily_volume"] = row.get("prior5_daily_volume", math.nan)
    grouped["volume15_to_prior5_daily"] = grouped["volume15"] / grouped["prior5_daily_volume"]
    grouped["volume15_prev5bar_avg"] = grouped["volume15"].shift(1).rolling(5, min_periods=2).mean()
    grouped["volume15_ratio_prev5bar"] = grouped["volume15"] / grouped["volume15_prev5bar_avg"]
    grouped["oi_change_intraday"] = grouped["close_oi"] / first_open_oi - 1.0 if first_open_oi and first_open_oi > 0 else math.nan
    grouped["oi_change_bar"] = grouped["close_oi"] / grouped["open_oi"] - 1.0
    grouped["price_breakout"] = (
        (grouped["close"] > grouped["ema5_1m"])
        & (grouped["ema5_1m"] > grouped["ema20_1m"])
        & (grouped["volume15_ratio_prev5bar"] >= 1.5)
    )
    grouped["future_gain_30m"] = [future_gain_after(bars, ts, price, 30) for ts, price in zip(grouped["datetime"], grouped["close"])]
    grouped["future_gain_60m"] = [future_gain_after(bars, ts, price, 60) for ts, price in zip(grouped["datetime"], grouped["close"])]
    grouped["future_gain_eod"] = [future_gain_after(bars, ts, price, None) for ts, price in zip(grouped["datetime"], grouped["close"])]
    grouped["day_max_gain_from_open"] = float(bars["high"].max() / bars.iloc[0]["open"] - 1.0) if bars.iloc[0]["open"] > 0 else math.nan
    grouped["day_high_time"] = str(bars.loc[bars["high"].idxmax(), "datetime"]) if not bars.empty else ""
    return grouped


def add_pcr(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events
    pcr = events.groupby(["trade_date", "datetime", "option_type"]).agg(
        side_volume15=("volume15", "sum"),
        side_close_oi=("close_oi", "sum"),
    ).reset_index()
    wide_v = pcr.pivot_table(index=["trade_date", "datetime"], columns="option_type", values="side_volume15", aggfunc="sum")
    wide_oi = pcr.pivot_table(index=["trade_date", "datetime"], columns="option_type", values="side_close_oi", aggfunc="sum")
    wide = pd.DataFrame(index=wide_v.index)
    wide["atm_volume_pcr"] = wide_v.get("put", math.nan) / wide_v.get("call", math.nan)
    wide["atm_oi_pcr"] = wide_oi.get("put", math.nan) / wide_oi.get("call", math.nan)
    wide = wide.reset_index()
    out = events.merge(wide, on=["trade_date", "datetime"], how="left")
    # Rolling percentile by event time across prior days. Shifted to avoid future leakage.
    for col in ["atm_volume_pcr", "atm_oi_pcr"]:
        pct_col = f"{col}_pct252"
        out[pct_col] = math.nan
        for time_text, idx in out.groupby("time").groups.items():
            s = out.loc[idx, ["trade_date", col]].drop_duplicates("trade_date").sort_values("trade_date")
            vals = []
            hist: list[float] = []
            for value in s[col]:
                clean = [x for x in hist[-252:] if pd.notna(x) and math.isfinite(float(x))]
                if clean and pd.notna(value) and math.isfinite(float(value)):
                    vals.append(sum(x <= float(value) for x in clean) / len(clean))
                else:
                    vals.append(math.nan)
                hist.append(float(value) if pd.notna(value) else math.nan)
            mapping = dict(zip(s["trade_date"], vals))
            out.loc[idx, pct_col] = out.loc[idx, "trade_date"].map(mapping)
    return out


def add_etf_confirmation(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events
    frames: list[pd.DataFrame] = []
    for trade_date in sorted(events["trade_date"].dropna().unique()):
        etf1 = opening.load_etf_1m(ETF_1M_ROOT, str(trade_date), "588000")
        if etf1.empty:
            continue
        bars15 = etf1.set_index("datetime").resample("15min", label="right", closed="right").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna(subset=["close"]).reset_index()
        bars15 = bars15[(bars15["datetime"].dt.strftime("%H:%M") >= "09:45") & (bars15["datetime"].dt.strftime("%H:%M") <= "14:45")].copy()
        bars15["trade_date"] = str(trade_date)
        bars15["etf_ema20_15m"] = bars15["close"].ewm(span=20, adjust=False).mean()
        bars15["etf_ema20_slope"] = bars15["etf_ema20_15m"].diff()
        bars15["etf_intraday_return"] = bars15["close"] / float(etf1.iloc[0]["open"]) - 1.0
        frames.append(
            bars15[
                [
                    "trade_date",
                    "datetime",
                    "close",
                    "volume",
                    "etf_ema20_15m",
                    "etf_ema20_slope",
                    "etf_intraday_return",
                ]
            ].rename(columns={"close": "etf15_close", "volume": "etf15_volume"})
        )
    if not frames:
        events["etf_confirm"] = False
        return events
    etf = pd.concat(frames, ignore_index=True)
    out = events.merge(etf, on=["trade_date", "datetime"], how="left")
    out["etf_confirm"] = (
        (
            (out["option_type"] == "call")
            & (out["etf15_close"] > out["etf_ema20_15m"])
            & (out["etf_ema20_slope"] > 0)
        )
        | (
            (out["option_type"] == "put")
            & (out["etf15_close"] < out["etf_ema20_15m"])
            & (out["etf_ema20_slope"] < 0)
        )
    )
    out["time_bucket"] = "midday"
    out.loc[out["time"] <= "10:00", "time_bucket"] = "opening"
    out.loc[out["time"] >= "13:15", "time_bucket"] = "afternoon"
    return out


def first_events_for_signal(events: pd.DataFrame, mask: pd.Series, signal_name: str) -> pd.DataFrame:
    selected = events[mask].copy()
    if selected.empty:
        return selected
    selected["signal"] = signal_name
    return selected.sort_values("datetime").groupby(["trade_date", "option_code"]).head(1)


def summarize_signal(events: pd.DataFrame, signal_name: str) -> dict[str, Any]:
    out = {
        "signal": signal_name,
        "events": len(events),
        "days": events["trade_date"].nunique() if not events.empty else 0,
        "hit_30m_30pct": math.nan,
        "hit_60m_30pct": math.nan,
        "hit_eod_30pct": math.nan,
        "hit_eod_50pct": math.nan,
        "median_future_gain_eod": math.nan,
        "mean_future_gain_eod": math.nan,
        "median_close": math.nan,
        "opening_share": math.nan,
        "afternoon_share": math.nan,
    }
    if events.empty:
        return out
    out["hit_30m_30pct"] = float((events["future_gain_30m"] >= 0.30).mean())
    out["hit_60m_30pct"] = float((events["future_gain_60m"] >= 0.30).mean())
    out["hit_eod_30pct"] = float((events["future_gain_eod"] >= 0.30).mean())
    out["hit_eod_50pct"] = float((events["future_gain_eod"] >= 0.50).mean())
    out["median_future_gain_eod"] = float(events["future_gain_eod"].median())
    out["mean_future_gain_eod"] = float(events["future_gain_eod"].mean())
    out["median_close"] = float(events["close"].median())
    out["opening_share"] = float((events["time_bucket"] == "opening").mean()) if "time_bucket" in events else math.nan
    out["afternoon_share"] = float((events["time_bucket"] == "afternoon").mean()) if "time_bucket" in events else math.nan
    return out


def main() -> None:
    args = parse_args()
    args.output_events.parent.mkdir(parents=True, exist_ok=True)
    candidates = build_daily_candidates(args)
    frames: list[pd.DataFrame] = []
    total = len(candidates)
    for i, row in enumerate(candidates.itertuples(index=False), start=1):
        if i % 1000 == 0:
            print(f"processed {i}/{total}")
        frames.append(build_contract_events(pd.Series(row._asdict())))
    events = pd.concat([f for f in frames if not f.empty], ignore_index=True) if frames else pd.DataFrame()
    events = add_pcr(events)
    events = add_etf_confirmation(events)
    liquid = events[(events["close"] >= args.min_close) & (events["volume15"] >= args.min_bar_volume)].copy()

    signal_sets: list[pd.DataFrame] = []
    baseline = liquid.sort_values("datetime").groupby(["trade_date", "option_code"]).head(1).copy()
    baseline["signal"] = "baseline_first_liquid_15m"
    signal_sets.append(baseline)
    signal_sets.append(
        first_events_for_signal(
            liquid,
            liquid["volume15_ratio_prev5bar"] >= 3.0,
            "volume_spike_prev5bar_3x",
        )
    )
    signal_sets.append(
        first_events_for_signal(
            liquid,
            (liquid["volume15_ratio_prev5bar"] >= 2.0) & (liquid["volume15_ratio_prev5bar"] < 3.0),
            "volume_spike_prev5bar_2to3x",
        )
    )
    signal_sets.append(
        first_events_for_signal(
            liquid,
            liquid["volume15_to_prior5_daily"] >= 0.10,
            "volume15_to_prior5daily_10pct",
        )
    )
    signal_sets.append(
        first_events_for_signal(
            liquid,
            liquid["volume15_to_prior5_daily"] >= 0.20,
            "volume15_to_prior5daily_20pct",
        )
    )
    signal_sets.append(
        first_events_for_signal(
            liquid,
            liquid["oi_change_intraday"] >= 0.15,
            "oi_intraday_growth_15pct",
        )
    )
    signal_sets.append(
        first_events_for_signal(
            liquid,
            liquid["price_breakout"],
            "price_breakout_volume_confirm",
        )
    )
    signal_sets.append(
        first_events_for_signal(
            liquid,
            (liquid["price_breakout"]) & (liquid["volume15_ratio_prev5bar"] >= 3.0),
            "price_breakout_and_volume3x",
        )
    )
    signal_sets.append(
        first_events_for_signal(
            liquid,
            (liquid["price_breakout"]) & (liquid["etf_confirm"]),
            "price_breakout_etf_confirm",
        )
    )
    signal_sets.append(
        first_events_for_signal(
            liquid,
            (liquid["price_breakout"])
            & (liquid["volume15_ratio_prev5bar"] >= 2.0)
            & (liquid["etf_confirm"])
            & (liquid["abs_delta"].between(0.25, 0.75)),
            "flow_combo_price_vol_etf_delta",
        )
    )
    signal_sets.append(
        first_events_for_signal(
            liquid,
            (liquid["volume15_to_prior5_daily"] >= 0.10)
            & (liquid["etf_confirm"])
            & (liquid["abs_delta"].between(0.25, 0.75)),
            "flow_combo_dailyvol_etf_delta",
        )
    )
    signal_sets.append(
        first_events_for_signal(
            liquid,
            (liquid["atm_oi_pcr_pct252"] >= 0.80) & (liquid["option_type"] == "call"),
            "atm_oi_pcr_high_call",
        )
    )
    signal_sets.append(
        first_events_for_signal(
            liquid,
            (liquid["atm_oi_pcr_pct252"] <= 0.20) & (liquid["option_type"] == "put"),
            "atm_oi_pcr_low_put",
        )
    )

    signal_events = pd.concat([s for s in signal_sets if not s.empty], ignore_index=True) if signal_sets else pd.DataFrame()
    summary = pd.DataFrame([summarize_signal(group, signal) for signal, group in signal_events.groupby("signal")])
    summary = summary.sort_values(["hit_eod_50pct", "median_future_gain_eod", "events"], ascending=[False, False, False])
    events.to_csv(args.output_events, index=False)
    summary.to_csv(args.output_summary, index=False)

    lines = [
        "# 科创期权资金流信号诊断（15分钟，平值±2档）",
        "",
        f"- 数据区间：{args.start} 到 {args.end}",
        f"- 候选池：每日 Call/Put 各平值±{args.atm_rank} 档",
        f"- 事件过滤：当前价格 >= {args.min_close}，15分钟成交量 >= {args.min_bar_volume}",
        f"- 全部 15m 候选事件：{len(events):,}",
        f"- 流动性过滤后事件：{len(liquid):,}",
        "",
        "## 信号命中率",
        "",
        "| 信号 | 事件数 | 天数 | EOD 后续涨幅>=50% | EOD 后续涨幅>=30% | 60m >=30% | 中位后续涨幅 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary.to_dict("records"):
        lines.append(
            "| {signal} | {events} | {days} | {hit50:.1%} | {hit30:.1%} | {hit6030:.1%} | {median:.1%} |".format(
                signal=row["signal"],
                events=int(row["events"]),
                days=int(row["days"]),
                hit50=row["hit_eod_50pct"] if pd.notna(row["hit_eod_50pct"]) else 0,
                hit30=row["hit_eod_30pct"] if pd.notna(row["hit_eod_30pct"]) else 0,
                hit6030=row["hit_60m_30pct"] if pd.notna(row["hit_60m_30pct"]) else 0,
                median=row["median_future_gain_eod"] if pd.notna(row["median_future_gain_eod"]) else 0,
            )
        )
    lines.extend(
        [
            "",
            "## 解释口径",
            "",
            "- `baseline_first_liquid_15m`：每张候选合约当天第一根满足流动性的15分钟事件，用作基准。",
            "- `volume_spike_prev5bar_3x`：当前15分钟成交量 >= 当天此前最多5根15分钟均量的3倍。",
            "- `oi_intraday_growth_15pct`：当前持仓量相对当天首个候选15分钟持仓增加 >=15%。",
            "- `price_breakout_volume_confirm`：期权价格 `close > EMA5 > EMA20` 且15分钟成交量 >= 前5根15分钟均量1.5倍。",
            "- PCR 为平值±2档候选池内的 Put/Call 15分钟成交量或持仓量比，并使用相同分钟槽的历史分位，避免未来函数。",
            "",
            "## 初步使用建议",
            "",
            "- 先看 `price_breakout_volume_confirm` 和 `price_breakout_and_volume3x`，它们最接近可执行入场信号。",
            "- 单纯 OI 增仓需要谨慎，必须结合价格和方向，否则可能包含卖方开仓/对冲噪音。",
            "- 如果资金流信号相对 baseline 有明显提升，再进入完整收益回测；否则不应急着替换 ETF 驱动策略。",
            "",
            f"明细：`{args.output_events}`",
            f"汇总：`{args.output_summary}`",
        ]
    )
    args.output_report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary.to_string(index=False))
    print(f"Wrote {args.output_events}")
    print(f"Wrote {args.output_summary}")
    print(f"Wrote {args.output_report}")


if __name__ == "__main__":
    main()
