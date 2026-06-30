#!/usr/bin/env python3
"""Backtest the v0.9 588000 ETF option intraday framework on recent data.

This is a first-pass research backtest:
  - ETF trend signal comes from local 5m ETF data resampled to 15m.
  - Option universe comes from daily option IV/Greeks.
  - Option execution/confirmation uses iFinD 1m bars, cached under data/intraday_cache.
"""

from __future__ import annotations

import argparse
import calendar
import json
import math
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RESEARCH_DIR = ROOT / "research"
INTRADAY_CACHE = DATA_DIR / "intraday_cache"
DAILY_CSV = DATA_DIR / "kcb_option_daily.csv"
MARKET_IV_CSV = DATA_DIR / "kcb_market_iv_daily.csv"
ETF_DAILY_CSV = DATA_DIR / "etf_daily_588000_588080.csv"
TOKEN_RTF = ROOT / "data:ifind_refresh_token" / "refresh- token.rtf"
DEFAULT_SQLITE = Path("/Users/aaren/策略/china-etf-strategy/cache/etf_5m_2020_202605.sqlite")

GET_ACCESS_TOKEN_URL = "https://quantapi.51ifind.com/api/v1/get_access_token"
HIGH_FREQUENCY_URL = "https://quantapi.51ifind.com/api/v1/high_frequency"
INDICATORS = "open,high,low,close,volume,amount,changeRatio"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=31)
    parser.add_argument("--underlying", choices=["588000", "159915"], default="588000")
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    parser.add_argument("--daily-csv", type=Path, default=DAILY_CSV)
    parser.add_argument("--market-iv-csv", type=Path, default=MARKET_IV_CSV)
    parser.add_argument("--etf-daily-csv", type=Path, default=ETF_DAILY_CSV)
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--candidate-pool", type=int, default=8, help="Daily-volume shortlist before iFinD fetch.")
    parser.add_argument("--strong-trailing-pct", type=float, default=0.20)
    parser.add_argument("--entry-start-time", default="09:35")
    parser.add_argument("--force-entry-time", default=None)
    parser.add_argument(
        "--execute-0945-at-0946",
        action="store_true",
        help="Confirm the 09:45 15m signal at its close and fill at the 09:46 option-bar open.",
    )
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--no-fetch", action="store_true", help="Only use existing intraday cache.")
    parser.add_argument(
        "--daily-volume-tiered",
        action="store_true",
        help="Keep signals at 0.65-0.80 prior-day volume ratio and multiply position by 0.70.",
    )
    parser.add_argument(
        "--strong-signals-only",
        action="store_true",
        help="Reject non-strong ETF bars before contract selection and trade-state updates.",
    )
    parser.add_argument("--output", type=Path, default=RESEARCH_DIR / "backtest_v05_588000_recent1m_trades.csv")
    parser.add_argument("--summary", type=Path, default=RESEARCH_DIR / "backtest_v05_588000_recent1m_summary.csv")
    return parser.parse_args()


def position_pct_for_signal(iv_rank: float, etf_volume_ratio: float) -> tuple[float, str]:
    """Return premium allocation and signal label for v0.9 sizing."""
    strong = etf_volume_ratio >= 2.0
    if iv_rank >= 0.35:
        return (0.15, "strong_reduced") if strong else (0.10, "reduced")
    return (0.20, "strong") if strong else (0.20, "normal")


def reduce_position(position_pct: float, signal_strength: str, reason: str) -> tuple[float, str]:
    if position_pct >= 0.15:
        return 0.10, f"{signal_strength}_{reason}"
    if position_pct >= 0.10:
        return 0.07, f"{signal_strength}_{reason}"
    return position_pct, signal_strength


def market_symbol(underlying: str) -> str:
    """Return the exchange-qualified ETF symbol used by local archives."""
    suffix = "SZ" if str(underlying).startswith(("15", "16")) else "SH"
    return f"{underlying}.{suffix}"


def option_thscode(option_code: str) -> str:
    """Return the iFinD code for an SSE/SZSE ETF option numeric code."""
    code = str(option_code).zfill(8)
    suffix = "SZ" if code.startswith("9") else "SH"
    return f"{code}.{suffix}"


def load_daily_direction(underlying: str, etf_daily_csv: Path = ETF_DAILY_CSV) -> pd.DataFrame:
    """Use the previous completed daily bar to decide the tradable direction."""
    df = pd.read_csv(etf_daily_csv, dtype={"underlying_code": str})
    df = df[df["underlying_code"] == underlying].copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values("trade_date")
    for window in [5, 10, 20]:
        df[f"ma{window}"] = df["etf_close"].rolling(window).mean()
        df[f"ma{window}_slope"] = df[f"ma{window}"].diff()
    df["ma_cluster"] = (df[["ma5", "ma10", "ma20"]].max(axis=1) - df[["ma5", "ma10", "ma20"]].min(axis=1)) / df["etf_close"]
    day_range = (df["etf_high"] - df["etf_low"]).replace(0, pd.NA)
    df["upper_shadow_ratio"] = (df["etf_high"] - df[["etf_open", "etf_close"]].max(axis=1)) / day_range
    df["lower_shadow_ratio"] = (df[["etf_open", "etf_close"]].min(axis=1) - df["etf_low"]) / day_range
    df["volume_ratio20"] = df["etf_volume"] / df["etf_volume"].rolling(20).mean()
    prev_cols = [
        "trade_date",
        "etf_close",
        "ma5",
        "ma10",
        "ma20",
        "ma5_slope",
        "ma10_slope",
        "ma20_slope",
        "ma_cluster",
        "upper_shadow_ratio",
        "lower_shadow_ratio",
        "volume_ratio20",
    ]
    prev = df[prev_cols].shift(1)
    out = df[["trade_date"]].copy()
    out["trade_date"] = out["trade_date"].dt.strftime("%Y-%m-%d")
    out["daily_ref_date"] = prev["trade_date"].dt.strftime("%Y-%m-%d")
    out["daily_ref_close"] = prev["etf_close"]
    out["daily_ref_ma5"] = prev["ma5"]
    out["daily_ref_ma10"] = prev["ma10"]
    out["daily_ref_ma20"] = prev["ma20"]
    out["daily_ref_ma5_slope"] = prev["ma5_slope"]
    out["daily_ref_ma10_slope"] = prev["ma10_slope"]
    out["daily_ref_ma20_slope"] = prev["ma20_slope"]
    out["daily_ref_ma_cluster"] = prev["ma_cluster"]
    out["daily_ref_upper_shadow_ratio"] = prev["upper_shadow_ratio"]
    out["daily_ref_lower_shadow_ratio"] = prev["lower_shadow_ratio"]
    out["daily_ref_volume_ratio20"] = prev["volume_ratio20"]
    out["daily_direction"] = "none"
    bullish = (
        out["daily_ref_close"].gt(out["daily_ref_ma5"])
        & out["daily_ref_ma5"].gt(out["daily_ref_ma10"])
        & out["daily_ref_ma10"].gt(out["daily_ref_ma20"])
        & out["daily_ref_ma5_slope"].gt(0)
        & out["daily_ref_ma20_slope"].ge(0)
    )
    bearish = (
        out["daily_ref_close"].lt(out["daily_ref_ma5"])
        & out["daily_ref_ma5"].lt(out["daily_ref_ma10"])
        & out["daily_ref_ma10"].lt(out["daily_ref_ma20"])
        & out["daily_ref_ma5_slope"].lt(0)
        & out["daily_ref_ma20_slope"].le(0)
    )
    out.loc[bullish, "daily_direction"] = "call"
    out.loc[bearish, "daily_direction"] = "put"
    return out


def daily_breakout_direction(daily_row: pd.Series, etf_close: float) -> str:
    """Allow fresh daily breakouts before the moving averages fully stack."""
    values = [
        daily_row["daily_ref_ma5"],
        daily_row["daily_ref_ma10"],
        daily_row["daily_ref_ma20"],
        daily_row["daily_ref_ma5_slope"],
        daily_row["daily_ref_ma20_slope"],
    ]
    if any(pd.isna(value) for value in values):
        return "none"
    above_all = (
        etf_close > daily_row["daily_ref_ma5"]
        and etf_close > daily_row["daily_ref_ma10"]
        and etf_close > daily_row["daily_ref_ma20"]
    )
    below_all = (
        etf_close < daily_row["daily_ref_ma5"]
        and etf_close < daily_row["daily_ref_ma10"]
        and etf_close < daily_row["daily_ref_ma20"]
    )
    if above_all and daily_row["daily_ref_ma5_slope"] > 0 and daily_row["daily_ref_ma20_slope"] >= 0:
        return "call"
    if below_all and daily_row["daily_ref_ma5_slope"] < 0 and daily_row["daily_ref_ma20_slope"] <= 0:
        return "put"
    return "none"


def ensure_dirs() -> None:
    INTRADAY_CACHE.mkdir(parents=True, exist_ok=True)
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)


def fourth_wednesday(year: int, month: int) -> pd.Timestamp:
    days = [
        day
        for day in range(1, calendar.monthrange(year, month)[1] + 1)
        if calendar.weekday(year, month, day) == calendar.WEDNESDAY
    ]
    return pd.Timestamp(year=year, month=month, day=days[3])


def expiry_date(expiry_ym: object) -> pd.Timestamp:
    value = str(int(expiry_ym))
    return fourth_wednesday(int(value[:4]), int(value[4:6]))


def next_month_ym(ts: pd.Timestamp) -> int:
    month = ts.month + 1
    year = ts.year
    if month == 13:
        month = 1
        year += 1
    return year * 100 + month


def parse_rtf_secret(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(errors="ignore")
    tokens = re.findall(r"[A-Za-z0-9_.=-]{50,}", text)
    return max(tokens, key=len) if tokens else None


def get_access_token() -> str:
    access_token = os.environ.get("IFIND_ACCESS_TOKEN")
    if access_token:
        return access_token.strip()

    refresh_token = os.environ.get("IFIND_REFRESH_TOKEN") or parse_rtf_secret(TOKEN_RTF)
    if not refresh_token:
        raise RuntimeError("No iFinD token found in env or data:ifind_refresh_token/refresh- token.rtf")

    response = requests.post(
        GET_ACCESS_TOKEN_URL,
        headers={"Content-Type": "application/json", "refresh_token": refresh_token.strip()},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    try:
        return payload["data"]["access_token"]
    except KeyError as exc:
        raise RuntimeError(f"Failed to obtain iFinD access token: {payload}") from exc


def normalize_tables(payload: dict[str, Any]) -> pd.DataFrame:
    if payload.get("errorcode") not in (0, None):
        raise RuntimeError(f"iFinD error {payload.get('errorcode')}: {payload.get('errmsg')}")
    tables = payload.get("tables") or payload.get("data", {}).get("tables") or []
    frames: list[pd.DataFrame] = []
    for table in tables:
        code = table.get("thscode") or table.get("code")
        data = table.get("table") or table.get("data") or {}
        df = pd.DataFrame(data)
        if "time" not in df.columns and "time" in table:
            df["time"] = table["time"]
        if not df.empty:
            df["thscode"] = code
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def standardize_hf(df: pd.DataFrame, option_code: str) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.rename(columns={"changeRatio": "change_ratio"}).copy()
    time_col = next((c for c in ["time", "datetime", "date"] if c in out.columns), None)
    if time_col is None:
        return pd.DataFrame()
    out["datetime"] = pd.to_datetime(out[time_col], errors="coerce")
    out["option_code"] = str(option_code).zfill(8)
    keep = ["datetime", "option_code", "open", "high", "low", "close", "volume", "amount", "change_ratio"]
    for col in keep:
        if col not in out.columns:
            out[col] = pd.NA
    out = out[keep].dropna(subset=["datetime"]).drop_duplicates(["datetime", "option_code"], keep="last")
    for col in ["open", "high", "low", "close", "volume", "amount", "change_ratio"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.sort_values("datetime")


def fetch_option_1m(
    option_code: str,
    trade_date: str,
    headers: dict[str, str],
    sleep: float,
    retries: int,
    refresh: bool,
    no_fetch: bool,
) -> pd.DataFrame:
    option_code = str(option_code).zfill(8)
    cache_path = INTRADAY_CACHE / f"{trade_date}_{option_code}_1m.csv"
    if cache_path.exists() and not refresh:
        return pd.read_csv(cache_path, parse_dates=["datetime"], dtype={"option_code": str})
    if no_fetch:
        return pd.DataFrame()

    body = {
        "codes": option_thscode(option_code),
        "indicators": INDICATORS,
        "starttime": f"{trade_date} 09:30:00",
        "endtime": f"{trade_date} 15:00:00",
        "functionpara": {"Fill": "Blank"},
    }
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.post(HIGH_FREQUENCY_URL, json=body, headers=headers, timeout=90)
            response.raise_for_status()
            df = standardize_hf(normalize_tables(response.json()), option_code)
            if not df.empty:
                df.to_csv(cache_path, index=False)
            time.sleep(sleep)
            return df
        except Exception as exc:  # noqa: BLE001 - data vendor boundary.
            last_error = exc
            if attempt < retries:
                time.sleep(sleep * attempt * 5)
    print(f"[warn] skip {trade_date} {option_code}: {last_error}", flush=True)
    return pd.DataFrame()


def load_etf_15m(sqlite_path: Path, underlyings: list[str], start: str, end: str) -> pd.DataFrame:
    symbols = [market_symbol(code) for code in underlyings]
    params: list[object] = symbols + [start.replace("-", ""), end.replace("-", "")]
    sql = f"""
        select symbol, dt, date, open, high, low, close, volume, amount
        from bars_5m
        where symbol in ({",".join("?" for _ in symbols)})
          and date between ? and ?
        order by symbol, dt
    """
    with sqlite3.connect(sqlite_path) as conn:
        bars = pd.read_sql_query(sql, conn, params=params)
    if bars.empty:
        raise RuntimeError(f"No ETF bars found in {sqlite_path}")
    bars["datetime"] = pd.to_datetime(bars["dt"])
    bars["underlying_code"] = bars["symbol"].str.slice(0, 6)
    frames: list[pd.DataFrame] = []
    for code, group in bars.groupby("underlying_code"):
        g = group.set_index("datetime").sort_index()
        agg = g.resample("15min", label="right", closed="right").agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            amount=("amount", "sum"),
        )
        agg = agg.dropna(subset=["close"]).reset_index()
        agg["underlying_code"] = code
        frames.append(agg)
    out = pd.concat(frames, ignore_index=True).sort_values(["underlying_code", "datetime"])
    out["trade_date"] = out["datetime"].dt.strftime("%Y-%m-%d")
    out["time"] = out["datetime"].dt.strftime("%H:%M")
    out["day_cum_volume"] = out.groupby(["underlying_code", "trade_date"])["volume"].cumsum()
    out["progress_volume_mean20"] = out.groupby(["underlying_code", "time"])["day_cum_volume"].transform(
        lambda s: s.shift(1).rolling(20).mean()
    )
    out["intraday_volume_progress_ratio"] = out["day_cum_volume"] / out["progress_volume_mean20"]
    out["ema5"] = out.groupby("underlying_code")["close"].transform(lambda s: s.ewm(span=5, adjust=False).mean())
    out["ema20"] = out.groupby("underlying_code")["close"].transform(lambda s: s.ewm(span=20, adjust=False).mean())
    out["ema20_slope"] = out.groupby("underlying_code")["ema20"].diff()
    out["prev5_vol_mean"] = out.groupby("underlying_code")["volume"].transform(lambda s: s.shift(1).rolling(5).mean())
    out["prev3_high"] = out.groupby("underlying_code")["high"].transform(lambda s: s.shift(1).rolling(3).max())
    out["prev3_low"] = out.groupby("underlying_code")["low"].transform(lambda s: s.shift(1).rolling(3).min())
    return out


def load_etf_5m(sqlite_path: Path, underlyings: list[str], start: str, end: str) -> pd.DataFrame:
    symbols = [market_symbol(code) for code in underlyings]
    params: list[object] = symbols + [start.replace("-", ""), end.replace("-", "")]
    sql = f"""
        select symbol, dt, date, open, high, low, close, volume, amount
        from bars_5m
        where symbol in ({",".join("?" for _ in symbols)})
          and date between ? and ?
        order by symbol, dt
    """
    with sqlite3.connect(sqlite_path) as conn:
        out = pd.read_sql_query(sql, conn, params=params)
    if out.empty:
        raise RuntimeError(f"No ETF 5m bars found in {sqlite_path}")
    out["datetime"] = pd.to_datetime(out["dt"])
    out["underlying_code"] = out["symbol"].str.slice(0, 6)
    out["trade_date"] = out["datetime"].dt.strftime("%Y-%m-%d")
    out["time"] = out["datetime"].dt.strftime("%H:%M")
    out = out.sort_values(["underlying_code", "datetime"])
    out["day_cum_volume"] = out.groupby(["underlying_code", "trade_date"])["volume"].cumsum()
    out["progress_volume_mean20"] = out.groupby(["underlying_code", "time"])["day_cum_volume"].transform(
        lambda s: s.shift(1).rolling(20).mean()
    )
    out["intraday_volume_progress_ratio"] = out["day_cum_volume"] / out["progress_volume_mean20"]
    out["ema5"] = out.groupby("underlying_code")["close"].transform(lambda s: s.ewm(span=5, adjust=False).mean())
    out["ema20"] = out.groupby("underlying_code")["close"].transform(lambda s: s.ewm(span=20, adjust=False).mean())
    out["ema20_slope"] = out.groupby("underlying_code")["ema20"].diff()
    out["prev_high"] = out.groupby("underlying_code")["high"].shift(1)
    out["prev_low"] = out.groupby("underlying_code")["low"].shift(1)
    return out


def resample_option_15m(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    g = df.set_index("datetime").sort_index()
    out = g.resample("15min", label="right", closed="right").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        amount=("amount", "sum"),
    )
    out = out.dropna(subset=["close"]).reset_index()
    out["ema5"] = out["close"].ewm(span=5, adjust=False).mean()
    out["ema20"] = out["close"].ewm(span=20, adjust=False).mean()
    return out


def option_candidates(
    daily: pd.DataFrame,
    trade_date: str,
    underlying: str,
    direction: str,
    pool: int,
    allow_edge_dte: bool = False,
) -> pd.DataFrame:
    td = pd.Timestamp(trade_date)
    cur_ym = td.year * 100 + td.month
    nxt_ym = next_month_ym(td)
    opt_type = "call" if direction == "call" else "put"
    d = daily[
        (daily["trade_date"] == trade_date)
        & (daily["underlying_code"] == underlying)
        & (daily["option_type"] == opt_type)
    ].copy()
    if d.empty:
        return d
    d["expiry_date"] = d["expiry_ym"].map(expiry_date)
    d["dte"] = (d["expiry_date"] - td).dt.days
    d["abs_delta"] = d["delta"].abs()
    common = (
        d["expiry_ym"].isin([cur_ym, nxt_ym])
        & d["abs_delta"].between(0.35, 0.65)
        & d["implied_volatility"].between(0.20, 0.70)
        & (d["option_volume"] > 0)
    )
    normal = d[common & d["dte"].between(10, 35)].copy()
    if not normal.empty:
        normal["edge_dte_candidate"] = False
        normal["dte_position_factor"] = 1.0
        return normal.sort_values("option_volume", ascending=False).head(pool)
    if not allow_edge_dte:
        return normal
    edge_band = d["dte"].between(7, 9) | d["dte"].between(36, 40)
    edge = d[common & edge_band].copy()
    edge["edge_dte_candidate"] = True
    edge["dte_position_factor"] = 0.60
    return edge.sort_values("option_volume", ascending=False).head(pool)


def bounded(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def score_option_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not candidates:
        return candidates
    max_cum_volume = max(item["cum_volume"] for item in candidates) or 1.0
    max_trend_strength = max(item["option_trend_strength"] for item in candidates) or 1.0
    for item in candidates:
        liquidity_score = item["cum_volume"] / max_cum_volume
        delta_score = bounded(1 - abs(abs(item["delta"]) - 0.50) / 0.15)
        trend_score = item["option_trend_strength"] / max_trend_strength
        dte_score = 1.0 if 10 <= item["dte"] <= 25 else 0.65
        iv_score = bounded(1 - max(item["implied_volatility"] - 0.40, 0) / 0.30)
        item["selection_score"] = (
            0.40 * liquidity_score
            + 0.25 * delta_score
            + 0.20 * trend_score
            + 0.10 * dte_score
            + 0.05 * iv_score
        )
        item["selection_liquidity_score"] = liquidity_score
        item["selection_delta_score"] = delta_score
        item["selection_trend_score"] = trend_score
        item["selection_dte_score"] = dte_score
        item["selection_iv_score"] = iv_score
    return sorted(candidates, key=lambda x: x["selection_score"], reverse=True)


def simulate_exit(
    bars_1m: pd.DataFrame,
    etf_15m: pd.DataFrame,
    entry_time: pd.Timestamp,
    entry_price: float,
    direction: str,
    signal_strength: str,
    strong_trailing_pct: float,
    soft_stop_pct: float = 0.82,
    soft_stop_delay_minutes: int = 0,
) -> dict[str, Any]:
    stop = entry_price * 0.70
    soft_stop = entry_price * soft_stop_pct
    soft_stop_ts = entry_time + pd.Timedelta(minutes=soft_stop_delay_minutes)
    eod = pd.Timestamp(f"{entry_time:%Y-%m-%d} 14:55:00")
    bars_1m = bars_1m.copy()
    if "ema5" not in bars_1m.columns:
        bars_1m["ema5"] = bars_1m["close"].ewm(span=5, adjust=False).mean()
    path = bars_1m[(bars_1m["datetime"] > entry_time) & (bars_1m["datetime"] <= eod)].copy()
    if path.empty:
        return {
            "exit_time": entry_time,
            "exit_price_1": entry_price,
            "exit_price_2": entry_price,
            "return": 0.0,
            "exit_reason": "no_path",
            "exit_legs": "1.0@{:.6f}".format(entry_price),
        }

    is_strong = str(signal_strength).startswith("strong")
    if not is_strong:
        tp1 = entry_price * 1.35
        tp2 = entry_price * 1.80
        half1_done = False
        exit1_price = math.nan
        exit1_time = pd.NaT
        for row in path.itertuples(index=False):
            opt_weak = pd.notna(row.ema5) and row.close < row.ema5
            etf_row = etf_15m[etf_15m["datetime"] <= row.datetime].tail(1)
            etf_reversal = False
            if not etf_row.empty:
                e = etf_row.iloc[0]
                etf_reversal = (
                    direction == "call"
                    and pd.notna(e["ema20"])
                    and pd.notna(e["ema20_slope"])
                    and e["close"] < e["ema20"]
                    and e["ema20_slope"] < 0
                ) or (
                    direction == "put"
                    and pd.notna(e["ema20"])
                    and pd.notna(e["ema20_slope"])
                    and e["close"] > e["ema20"]
                    and e["ema20_slope"] > 0
                )
            if row.datetime >= soft_stop_ts and not half1_done and row.low <= soft_stop and (opt_weak or etf_reversal):
                return {
                    "exit_time": row.datetime,
                    "exit_price_1": soft_stop,
                    "exit_price_2": soft_stop,
                    "return": soft_stop / entry_price - 1,
                    "exit_reason": "soft_stop",
                    "exit_legs": "1.0@{:.6f}".format(soft_stop),
                }
            if row.low <= stop:
                if not half1_done:
                    return {
                        "exit_time": row.datetime,
                        "exit_price_1": stop,
                        "exit_price_2": stop,
                        "return": -0.30,
                        "exit_reason": "stop",
                        "exit_legs": "1.0@{:.6f}".format(stop),
                    }
                ret = 0.5 * (exit1_price / entry_price - 1) + 0.5 * (stop / entry_price - 1)
                return {
                    "exit_time": row.datetime,
                    "exit_price_1": exit1_price,
                    "exit_price_2": stop,
                    "return": ret,
                    "exit_reason": "stop_after_tp1",
                    "exit_legs": "0.5@{:.6f};0.5@{:.6f}".format(exit1_price, stop),
                }
            if not half1_done and row.high >= tp1:
                half1_done = True
                exit1_price = tp1
                exit1_time = row.datetime
            if half1_done and row.high >= tp2:
                ret = 0.5 * (exit1_price / entry_price - 1) + 0.5 * (tp2 / entry_price - 1)
                return {
                    "exit_time": row.datetime,
                    "exit_price_1": exit1_price,
                    "exit_price_2": tp2,
                    "return": ret,
                    "exit_reason": "tp2",
                    "exit_legs": "0.5@{:.6f};0.5@{:.6f}".format(exit1_price, tp2),
                    "tp1_time": exit1_time,
                }

        last = path.iloc[-1]
        if not half1_done:
            ret = last["close"] / entry_price - 1
            return {
                "exit_time": last["datetime"],
                "exit_price_1": last["close"],
                "exit_price_2": last["close"],
                "return": ret,
                "exit_reason": "eod",
                "exit_legs": "1.0@{:.6f}".format(last["close"]),
            }
        ret = 0.5 * (exit1_price / entry_price - 1) + 0.5 * (last["close"] / entry_price - 1)
        return {
            "exit_time": last["datetime"],
            "exit_price_1": exit1_price,
            "exit_price_2": last["close"],
            "return": ret,
            "exit_reason": "tp1_eod",
            "exit_legs": "0.5@{:.6f};0.5@{:.6f}".format(exit1_price, last["close"]),
            "tp1_time": exit1_time,
        }

    tp1 = entry_price * 1.50
    first_leg_done = False
    exit1_price = math.nan
    exit1_time = pd.NaT
    high_water = entry_price
    trailing_stop = stop
    for row in path.itertuples(index=False):
        high_water = max(high_water, float(row.high))
        opt_weak = pd.notna(row.ema5) and row.close < row.ema5
        etf_row = etf_15m[etf_15m["datetime"] <= row.datetime].tail(1)
        etf_reversal = False
        if not etf_row.empty:
            e = etf_row.iloc[0]
            etf_reversal = (
                direction == "call"
                and pd.notna(e["ema20"])
                and pd.notna(e["ema20_slope"])
                and e["close"] < e["ema20"]
                and e["ema20_slope"] < 0
            ) or (
                direction == "put"
                and pd.notna(e["ema20"])
                and pd.notna(e["ema20_slope"])
                and e["close"] > e["ema20"]
                and e["ema20_slope"] > 0
            )
        if row.datetime >= soft_stop_ts and not first_leg_done and row.low <= soft_stop and (opt_weak or etf_reversal):
            return {
                "exit_time": row.datetime,
                "exit_price_1": soft_stop,
                "exit_price_2": soft_stop,
                "return": soft_stop / entry_price - 1,
                "exit_reason": "soft_stop",
                "exit_legs": "1.0@{:.6f}".format(soft_stop),
                "high_water": high_water,
            }
        if row.low <= stop:
            if not first_leg_done:
                return {
                    "exit_time": row.datetime,
                    "exit_price_1": stop,
                    "exit_price_2": stop,
                    "return": -0.30,
                    "exit_reason": "stop",
                    "exit_legs": "1.0@{:.6f}".format(stop),
                    "high_water": high_water,
                }
            ret = (1 / 3) * (exit1_price / entry_price - 1) + (2 / 3) * (stop / entry_price - 1)
            return {
                "exit_time": row.datetime,
                "exit_price_1": exit1_price,
                "exit_price_2": stop,
                "return": ret,
                "exit_reason": "stop_after_tp1",
                "exit_legs": "0.333333@{:.6f};0.666667@{:.6f}".format(exit1_price, stop),
                "tp1_time": exit1_time,
                "high_water": high_water,
            }
        if not first_leg_done and row.high >= tp1:
            first_leg_done = True
            exit1_price = tp1
            exit1_time = row.datetime
            high_water = max(high_water, tp1)
            trail_pct = 0.35 if pd.Timestamp(row.datetime).time() < pd.Timestamp("10:30").time() else strong_trailing_pct
            trailing_stop = high_water * (1 - trail_pct)
        if first_leg_done:
            trail_pct = 0.35 if pd.Timestamp(row.datetime).time() < pd.Timestamp("10:30").time() else strong_trailing_pct
            trailing_stop = max(trailing_stop, high_water * (1 - trail_pct))
            if row.low <= trailing_stop:
                ret = (1 / 3) * (exit1_price / entry_price - 1) + (2 / 3) * (trailing_stop / entry_price - 1)
                return {
                    "exit_time": row.datetime,
                    "exit_price_1": exit1_price,
                    "exit_price_2": trailing_stop,
                    "return": ret,
                    "exit_reason": f"trail_{trail_pct:.0%}",
                    "exit_legs": "0.333333@{:.6f};0.666667@{:.6f}".format(exit1_price, trailing_stop),
                    "tp1_time": exit1_time,
                    "high_water": high_water,
                    "trailing_stop": trailing_stop,
                }

    last = path.iloc[-1]
    if not first_leg_done:
        ret = last["close"] / entry_price - 1
        return {
            "exit_time": last["datetime"],
            "exit_price_1": last["close"],
            "exit_price_2": last["close"],
            "return": ret,
            "exit_reason": "eod",
            "exit_legs": "1.0@{:.6f}".format(last["close"]),
            "high_water": high_water,
        }
    ret = (1 / 3) * (exit1_price / entry_price - 1) + (2 / 3) * (last["close"] / entry_price - 1)
    return {
        "exit_time": last["datetime"],
        "exit_price_1": exit1_price,
        "exit_price_2": last["close"],
        "return": ret,
        "exit_reason": "tp1_eod",
        "exit_legs": "0.333333@{:.6f};0.666667@{:.6f}".format(exit1_price, last["close"]),
        "tp1_time": exit1_time,
        "high_water": high_water,
        "trailing_stop": trailing_stop,
    }


def main() -> None:
    args = parse_args()
    ensure_dirs()
    daily = pd.read_csv(args.daily_csv, dtype={"option_code": str, "contract_id": str, "underlying_code": str})
    market_iv = pd.read_csv(args.market_iv_csv, dtype={"underlying_code": str})
    end = pd.to_datetime(daily["trade_date"].max())
    start = end - pd.Timedelta(days=args.days)
    underlyings = [args.underlying]
    daily = daily[(daily["trade_date"] >= start.strftime("%Y-%m-%d")) & (daily["trade_date"] <= end.strftime("%Y-%m-%d"))]
    daily = daily[daily["underlying_code"].isin(underlyings)].copy()
    market_iv = market_iv[(market_iv["trade_date"] >= start.strftime("%Y-%m-%d")) & (market_iv["trade_date"] <= end.strftime("%Y-%m-%d"))]
    daily_direction = load_daily_direction(args.underlying, args.etf_daily_csv)
    etf15 = load_etf_15m(args.sqlite, underlyings, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    etf5 = load_etf_5m(args.sqlite, underlyings, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    early5 = etf5[etf5["time"].isin(["09:35", "09:40"])].copy()
    early5["bar_interval"] = "5m"
    early5["prev3_high"] = early5["prev_high"]
    early5["prev3_low"] = early5["prev_low"]
    early5["prev5_vol_mean"] = pd.NA
    etf15 = etf15.copy()
    etf15["bar_interval"] = "15m"
    signal_bars = pd.concat([early5, etf15], ignore_index=True, sort=False).sort_values(
        ["underlying_code", "datetime"]
    )
    token = None if args.no_fetch else get_access_token()
    headers = {"Content-Type": "application/json", "access_token": token} if token else {}

    trades: list[dict[str, Any]] = []
    option_cache: dict[tuple[str, str], pd.DataFrame] = {}
    for (underlying, trade_date), day_bars in signal_bars.groupby(["underlying_code", "trade_date"], sort=True):
        day_all_bars = etf15[(etf15["underlying_code"] == underlying) & (etf15["trade_date"] == trade_date)].copy()
        entries = 0
        day_direction: str | None = None
        entries_by_direction = {"call": 0, "put": 0}
        cooldown_until = {"call": pd.Timestamp.min, "put": pd.Timestamp.min}
        open_until_by_option: dict[str, pd.Timestamp] = {}
        day_selected_option: str | None = None
        day_bars = day_bars[(day_bars["time"] >= args.entry_start_time) & (day_bars["time"] <= "14:15")]
        day_bars = day_bars[(day_bars["time"] <= "11:00") | (day_bars["time"] >= "13:15")]
        iv_row = market_iv[(market_iv["underlying_code"] == underlying) & (market_iv["trade_date"] == trade_date)]
        if iv_row.empty:
            continue
        iv = float(iv_row.iloc[0]["market_iv"])
        iv_rank = float(iv_row.iloc[0]["iv_rank_252"])
        if iv < 0.20 or iv_rank >= 0.50:
            continue
        daily_dir_row = daily_direction[daily_direction["trade_date"] == trade_date]
        if daily_dir_row.empty:
            continue
        daily_row = daily_dir_row.iloc[0]
        daily_dir = str(daily_row["daily_direction"])
        ma_cluster = float(daily_row["daily_ref_ma_cluster"]) if pd.notna(daily_row["daily_ref_ma_cluster"]) else math.nan
        daily_volume_ratio20 = (
            float(daily_row["daily_ref_volume_ratio20"]) if pd.notna(daily_row["daily_ref_volume_ratio20"]) else math.nan
        )
        if pd.isna(ma_cluster) or ma_cluster < 0.015:
            continue
        if args.daily_volume_tiered and (
            pd.isna(daily_volume_ratio20) or daily_volume_ratio20 < 0.65
        ):
            continue
        if not args.daily_volume_tiered and pd.notna(daily_volume_ratio20) and daily_volume_ratio20 < 0.65:
            continue

        for bar in day_bars.itertuples(index=False):
            if entries >= 2:
                break
            bar_range = float(bar.high - bar.low)
            close_pos = float((bar.close - bar.low) / bar_range) if bar_range > 0 else 0.5
            is_early = str(bar.bar_interval) == "5m"
            elastic_call = bar.close > bar.open and close_pos >= (0.80 if is_early else 0.70)
            elastic_put = bar.close < bar.open and close_pos <= (0.20 if is_early else 0.30)
            progress_ratio = (
                float(bar.intraday_volume_progress_ratio)
                if pd.notna(bar.intraday_volume_progress_ratio)
                else math.nan
            )
            if pd.notna(progress_ratio) and progress_ratio < 0.80:
                continue
            if is_early:
                vol_threshold = 1.5
                vol_ok = pd.notna(progress_ratio) and progress_ratio >= 1.50
                etf_volume_ratio = progress_ratio if pd.notna(progress_ratio) else 0.0
                call_signal = elastic_call and bar.ema5 > bar.ema20 and bar.ema20_slope > 0 and vol_ok
                put_signal = elastic_put and bar.ema5 < bar.ema20 and bar.ema20_slope < 0 and vol_ok
            else:
                vol_threshold = 1.2 if elastic_call or elastic_put else 1.5
                vol_ok = pd.notna(bar.prev5_vol_mean) and bar.prev5_vol_mean > 0 and bar.volume >= vol_threshold * bar.prev5_vol_mean
                etf_volume_ratio = float(bar.volume / bar.prev5_vol_mean) if pd.notna(bar.prev5_vol_mean) and bar.prev5_vol_mean > 0 else 0.0
                call_signal = bar.close > bar.prev3_high and bar.ema5 > bar.ema20 and bar.ema20_slope > 0 and vol_ok
                put_signal = bar.close < bar.prev3_low and bar.ema5 < bar.ema20 and bar.ema20_slope < 0 and vol_ok
            direction = "call" if call_signal else "put" if put_signal else None
            if direction is None:
                continue
            if args.strong_signals_only and etf_volume_ratio < 2.0:
                continue
            if direction == "call" and close_pos < (0.80 if is_early else 0.75 if bar.time == "09:45" else 0.65):
                continue
            if direction == "put" and close_pos > (0.20 if is_early else 0.25 if bar.time == "09:45" else 0.35):
                continue
            allowed_daily_dir = daily_dir
            if allowed_daily_dir not in {"call", "put"}:
                allowed_daily_dir = daily_breakout_direction(daily_row, float(bar.close))
            if direction != allowed_daily_dir:
                continue
            if day_direction is not None and direction != day_direction:
                continue
            if entries_by_direction[direction] >= 2:
                continue
            if bar.datetime < cooldown_until[direction]:
                continue
            signal_time = pd.Timestamp(bar.datetime)
            delayed_0945_fill = (
                args.execute_0945_at_0946
                and str(bar.bar_interval) == "15m"
                and str(bar.time) == "09:45"
                and args.force_entry_time is None
            )
            execution_time = (
                signal_time + pd.Timedelta(minutes=1)
                if delayed_0945_fill
                else pd.Timestamp(f"{trade_date} {args.force_entry_time}:00")
                if args.force_entry_time
                else signal_time
            )

            candidates = option_candidates(daily, trade_date, underlying, direction, args.candidate_pool)
            if candidates.empty:
                continue

            ranked: list[dict[str, Any]] = []
            for opt in candidates.itertuples(index=False):
                option_code = str(opt.option_code).zfill(8)
                if open_until_by_option.get(option_code, pd.Timestamp.min) > execution_time:
                    continue
                key = (trade_date, opt.option_code)
                if key not in option_cache:
                    option_cache[key] = fetch_option_1m(
                        opt.option_code,
                        trade_date,
                        headers,
                        args.sleep,
                        args.retries,
                        args.refresh_cache,
                        args.no_fetch,
                    )
                opt1 = option_cache[key]
                if opt1.empty:
                    continue
                if is_early or args.force_entry_time:
                    opt_path = opt1[opt1["datetime"] <= signal_time].copy()
                    if opt_path.empty:
                        continue
                    opt_path["ema5"] = opt_path["close"].ewm(span=5, adjust=False).mean()
                    opt_path["ema20"] = opt_path["close"].ewm(span=20, adjust=False).mean()
                    r = opt_path.iloc[-1]
                else:
                    opt15 = resample_option_15m(opt1)
                    row = opt15[opt15["datetime"] == signal_time]
                    if row.empty:
                        continue
                    r = row.iloc[0]
                cum_vol = opt1[opt1["datetime"] <= signal_time]["volume"].sum()
                if cum_vol <= 0 or r["volume"] <= 0:
                    continue
                if not (r["close"] > r["ema5"] > r["ema20"]):
                    continue
                if delayed_0945_fill:
                    fill_rows = opt1[opt1["datetime"] >= execution_time].head(1)
                    if fill_rows.empty:
                        continue
                    fill_row = fill_rows.iloc[0]
                    fill_price = (
                        float(fill_row["open"])
                        if pd.notna(fill_row["open"]) and float(fill_row["open"]) > 0
                        else float(fill_row["close"])
                    )
                    fill_time = pd.Timestamp(fill_row["datetime"])
                else:
                    fill_price = float(r["close"])
                    fill_time = execution_time
                option_trend_strength = max(float(r["close"] / r["ema20"] - 1), 0.0)
                ranked.append(
                    {
                        "option_code": opt.option_code,
                        "contract_id": opt.contract_id,
                        "contract_symbol": opt.contract_symbol,
                        "entry_price": fill_price,
                        "signal_option_price": float(r["close"]),
                        "execution_time": fill_time,
                        "entry_price_source": "next_minute_open" if delayed_0945_fill else "signal_bar_close",
                        "entry_option_volume_15m": float(r["volume"]),
                        "cum_volume": float(cum_vol),
                        "option_trend_strength": option_trend_strength,
                        "dte": int(opt.dte),
                        "delta": float(opt.delta),
                        "implied_volatility": float(opt.implied_volatility),
                        "bars_1m": opt1,
                    }
                )
            ranked = score_option_candidates(ranked)
            if day_selected_option is not None:
                ranked = [item for item in ranked if str(item["option_code"]).zfill(8) == day_selected_option]
            if not ranked:
                continue
            chosen = ranked[0]
            execution_time = pd.Timestamp(chosen.pop("execution_time"))
            if day_selected_option is None:
                day_selected_option = str(chosen["option_code"]).zfill(8)
            position_pct, signal_strength = position_pct_for_signal(iv_rank, etf_volume_ratio)
            risk_flags: list[str] = []
            if ma_cluster < 0.022:
                position_pct, signal_strength = reduce_position(position_pct, signal_strength, "cluster")
                risk_flags.append("ma_cluster")
            if pd.notna(daily_volume_ratio20) and daily_volume_ratio20 < 0.80:
                if args.daily_volume_tiered:
                    position_pct *= 0.70
                    signal_strength = f"{signal_strength}_daily_volume_reduced"
                    risk_flags.append("daily_volume_70pct")
                elif signal_strength.startswith("strong"):
                    position_pct, signal_strength = 0.10, "normal_low_daily_volume"
                else:
                    position_pct, signal_strength = reduce_position(position_pct, signal_strength, "low_daily_volume")
                if not args.daily_volume_tiered:
                    risk_flags.append("low_daily_volume")
            if pd.notna(progress_ratio) and progress_ratio < 1.00:
                position_pct, signal_strength = reduce_position(position_pct, signal_strength, "low_intraday_volume")
                risk_flags.append("low_intraday_volume")
            if signal_strength.startswith("strong") and pd.notna(progress_ratio) and progress_ratio < 1.50:
                position_pct, signal_strength = 0.10, "normal_intraday_volume"
                risk_flags.append("strong_blocked_intraday_volume")
            if direction == "call" and pd.notna(daily_row["daily_ref_upper_shadow_ratio"]) and daily_row["daily_ref_upper_shadow_ratio"] > 0.45:
                position_pct, signal_strength = reduce_position(position_pct, signal_strength, "upper_shadow")
                risk_flags.append("upper_shadow")
            if direction == "put" and pd.notna(daily_row["daily_ref_lower_shadow_ratio"]) and daily_row["daily_ref_lower_shadow_ratio"] > 0.45:
                position_pct, signal_strength = reduce_position(position_pct, signal_strength, "lower_shadow")
                risk_flags.append("lower_shadow")
            exit_info = simulate_exit(
                chosen.pop("bars_1m"),
                day_all_bars,
                execution_time,
                chosen["entry_price"],
                direction,
                signal_strength,
                args.strong_trailing_pct,
            )
            if str(exit_info.get("exit_reason", "")).startswith("tp"):
                cooldown_until[direction] = pd.Timestamp(exit_info["exit_time"]) + pd.Timedelta(minutes=30)
            if day_direction is None:
                day_direction = direction
            open_until_by_option[str(chosen["option_code"]).zfill(8)] = pd.Timestamp(exit_info["exit_time"])
            trades.append(
                {
                    "trade_date": trade_date,
                    "underlying_code": underlying,
                    "direction": direction,
                    "entry_time": execution_time,
                    "signal_time": signal_time,
                    "etf_close": bar.close,
                    "etf_volume_15m": bar.volume,
                    "market_iv": iv,
                    "iv_rank_252": iv_rank,
                    "etf_volume_ratio": etf_volume_ratio,
                    "etf_intraday_volume_progress_ratio": progress_ratio,
                    "etf_vol_threshold": vol_threshold,
                    "etf_close_pos": close_pos,
                    "signal_strength": signal_strength,
                    "position_pct": position_pct,
                    "risk_flags": ",".join(risk_flags),
                    "daily_direction": daily_dir,
                    "daily_allowed_direction": allowed_daily_dir,
                    "daily_ref_date": daily_row["daily_ref_date"],
                    "daily_ref_close": float(daily_row["daily_ref_close"]),
                    "daily_ref_ma5": float(daily_row["daily_ref_ma5"]),
                    "daily_ref_ma10": float(daily_row["daily_ref_ma10"]),
                    "daily_ref_ma20": float(daily_row["daily_ref_ma20"]),
                    "daily_ref_ma5_slope": float(daily_row["daily_ref_ma5_slope"]),
                    "daily_ref_ma10_slope": float(daily_row["daily_ref_ma10_slope"]),
                    "daily_ref_ma20_slope": float(daily_row["daily_ref_ma20_slope"]),
                    "daily_ref_ma_cluster": ma_cluster,
                    "daily_ref_volume_ratio20": float(daily_volume_ratio20) if pd.notna(daily_volume_ratio20) else math.nan,
                    "daily_ref_upper_shadow_ratio": (
                        float(daily_row["daily_ref_upper_shadow_ratio"])
                        if pd.notna(daily_row["daily_ref_upper_shadow_ratio"])
                        else math.nan
                    ),
                    "daily_ref_lower_shadow_ratio": (
                        float(daily_row["daily_ref_lower_shadow_ratio"])
                        if pd.notna(daily_row["daily_ref_lower_shadow_ratio"])
                        else math.nan
                    ),
                    **chosen,
                    **exit_info,
                }
            )
            entries += 1
            entries_by_direction[direction] += 1

    trades_df = pd.DataFrame(trades)
    trades_path = args.output
    summary_path = args.summary
    trades_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    trades_df.to_csv(trades_path, index=False)
    if trades_df.empty:
        summary = pd.DataFrame([{"trades": 0, "start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d")}])
    else:
        summary = pd.DataFrame(
            [
                {
                    "start": start.strftime("%Y-%m-%d"),
                    "end": end.strftime("%Y-%m-%d"),
                    "underlying": args.underlying,
                    "trades": len(trades_df),
                    "win_rate": (trades_df["return"] > 0).mean(),
                    "avg_return": trades_df["return"].mean(),
                    "median_return": trades_df["return"].median(),
                    "total_simple_return": trades_df["return"].sum(),
                    "best_trade": trades_df["return"].max(),
                    "worst_trade": trades_df["return"].min(),
                }
            ]
        )
    summary.to_csv(summary_path, index=False)
    print(f"wrote {trades_path}")
    print(f"wrote {summary_path}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
