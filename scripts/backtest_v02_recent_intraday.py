#!/usr/bin/env python3
"""Backtest the v0.5 588000 ETF option intraday framework on recent data.

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
    parser.add_argument("--underlying", choices=["588000"], default="588000")
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--candidate-pool", type=int, default=8, help="Daily-volume shortlist before iFinD fetch.")
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--no-fetch", action="store_true", help="Only use existing intraday cache.")
    return parser.parse_args()


def position_pct_for_signal(iv_rank: float, etf_volume_ratio: float) -> tuple[float, str]:
    """Return premium allocation and signal label for v0.5 sizing."""
    strong = etf_volume_ratio >= 2.0
    if iv_rank >= 0.35:
        return (0.10, "strong_reduced") if strong else (0.07, "reduced")
    return (0.15, "strong") if strong else (0.10, "normal")


def load_daily_direction(underlying: str) -> pd.DataFrame:
    """Use the previous completed daily bar to decide the tradable direction."""
    df = pd.read_csv(ETF_DAILY_CSV, dtype={"underlying_code": str})
    df = df[df["underlying_code"] == underlying].copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values("trade_date")
    df["ma20"] = df["etf_close"].rolling(20).mean()
    df["ma20_slope"] = df["ma20"].diff()
    prev = df[["trade_date", "etf_close", "ma20", "ma20_slope"]].shift(1)
    out = df[["trade_date"]].copy()
    out["trade_date"] = out["trade_date"].dt.strftime("%Y-%m-%d")
    out["daily_ref_date"] = prev["trade_date"].dt.strftime("%Y-%m-%d")
    out["daily_ref_close"] = prev["etf_close"]
    out["daily_ref_ma20"] = prev["ma20"]
    out["daily_ref_ma20_slope"] = prev["ma20_slope"]
    out["daily_direction"] = "none"
    bullish = out["daily_ref_close"].gt(out["daily_ref_ma20"]) & out["daily_ref_ma20_slope"].gt(0)
    bearish = out["daily_ref_close"].lt(out["daily_ref_ma20"]) & out["daily_ref_ma20_slope"].lt(0)
    out.loc[bullish, "daily_direction"] = "call"
    out.loc[bearish, "daily_direction"] = "put"
    return out


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
        "codes": f"{option_code}.SH",
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
    symbols = [f"{code}.SH" for code in underlyings]
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
    out["ema5"] = out.groupby("underlying_code")["close"].transform(lambda s: s.ewm(span=5, adjust=False).mean())
    out["ema20"] = out.groupby("underlying_code")["close"].transform(lambda s: s.ewm(span=20, adjust=False).mean())
    out["ema20_slope"] = out.groupby("underlying_code")["ema20"].diff()
    out["prev5_vol_mean"] = out.groupby("underlying_code")["volume"].transform(lambda s: s.shift(1).rolling(5).mean())
    out["prev3_high"] = out.groupby("underlying_code")["high"].transform(lambda s: s.shift(1).rolling(3).max())
    out["prev3_low"] = out.groupby("underlying_code")["low"].transform(lambda s: s.shift(1).rolling(3).min())
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


def option_candidates(daily: pd.DataFrame, trade_date: str, underlying: str, direction: str, pool: int) -> pd.DataFrame:
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
    d = d[
        d["expiry_ym"].isin([cur_ym, nxt_ym])
        & d["dte"].between(10, 35)
        & d["abs_delta"].between(0.35, 0.65)
        & d["implied_volatility"].between(0.20, 0.70)
        & (d["option_volume"] > 0)
    ]
    return d.sort_values("option_volume", ascending=False).head(pool)


def simulate_exit(bars_1m: pd.DataFrame, entry_time: pd.Timestamp, entry_price: float) -> dict[str, Any]:
    stop = entry_price * 0.70
    tp1 = entry_price * 1.35
    tp2 = entry_price * 1.60
    eod = pd.Timestamp(f"{entry_time:%Y-%m-%d} 14:55:00")
    path = bars_1m[(bars_1m["datetime"] > entry_time) & (bars_1m["datetime"] <= eod)].copy()
    if path.empty:
        return {"exit_time": entry_time, "exit_price_1": entry_price, "exit_price_2": entry_price, "return": 0.0, "exit_reason": "no_path"}

    half1_done = False
    exit1_price = math.nan
    exit1_time = pd.NaT
    for row in path.itertuples(index=False):
        if row.low <= stop:
            if not half1_done:
                return {"exit_time": row.datetime, "exit_price_1": stop, "exit_price_2": stop, "return": -0.30, "exit_reason": "stop"}
            ret = 0.5 * (exit1_price / entry_price - 1) + 0.5 * (stop / entry_price - 1)
            return {"exit_time": row.datetime, "exit_price_1": exit1_price, "exit_price_2": stop, "return": ret, "exit_reason": "stop_after_tp1"}
        if not half1_done and row.high >= tp1:
            half1_done = True
            exit1_price = tp1
            exit1_time = row.datetime
        if half1_done and row.high >= tp2:
            ret = 0.5 * (exit1_price / entry_price - 1) + 0.5 * (tp2 / entry_price - 1)
            return {"exit_time": row.datetime, "exit_price_1": exit1_price, "exit_price_2": tp2, "return": ret, "exit_reason": "tp2"}

    last = path.iloc[-1]
    if not half1_done:
        ret = last["close"] / entry_price - 1
        return {"exit_time": last["datetime"], "exit_price_1": last["close"], "exit_price_2": last["close"], "return": ret, "exit_reason": "eod"}
    ret = 0.5 * (exit1_price / entry_price - 1) + 0.5 * (last["close"] / entry_price - 1)
    return {"exit_time": last["datetime"], "exit_price_1": exit1_price, "exit_price_2": last["close"], "return": ret, "exit_reason": "tp1_eod", "tp1_time": exit1_time}


def main() -> None:
    args = parse_args()
    ensure_dirs()
    daily = pd.read_csv(DAILY_CSV, dtype={"option_code": str, "contract_id": str, "underlying_code": str})
    market_iv = pd.read_csv(MARKET_IV_CSV, dtype={"underlying_code": str})
    end = pd.to_datetime(daily["trade_date"].max())
    start = end - pd.Timedelta(days=args.days)
    underlyings = [args.underlying]
    daily = daily[(daily["trade_date"] >= start.strftime("%Y-%m-%d")) & (daily["trade_date"] <= end.strftime("%Y-%m-%d"))]
    daily = daily[daily["underlying_code"].isin(underlyings)].copy()
    market_iv = market_iv[(market_iv["trade_date"] >= start.strftime("%Y-%m-%d")) & (market_iv["trade_date"] <= end.strftime("%Y-%m-%d"))]
    daily_direction = load_daily_direction(args.underlying)
    etf15 = load_etf_15m(args.sqlite, underlyings, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    token = None if args.no_fetch else get_access_token()
    headers = {"Content-Type": "application/json", "access_token": token} if token else {}

    trades: list[dict[str, Any]] = []
    option_cache: dict[tuple[str, str], pd.DataFrame] = {}
    for (underlying, trade_date), day_bars in etf15.groupby(["underlying_code", "trade_date"], sort=True):
        entries = 0
        day_direction: str | None = None
        entries_by_direction = {"call": 0, "put": 0}
        cooldown_until = {"call": pd.Timestamp.min, "put": pd.Timestamp.min}
        day_bars = day_bars[(day_bars["time"] >= "09:45") & (day_bars["time"] <= "14:15")]
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
        daily_dir = str(daily_dir_row.iloc[0]["daily_direction"])
        if daily_dir not in {"call", "put"}:
            continue

        for bar in day_bars.itertuples(index=False):
            if entries >= 2:
                break
            vol_ok = pd.notna(bar.prev5_vol_mean) and bar.prev5_vol_mean > 0 and bar.volume >= 1.5 * bar.prev5_vol_mean
            etf_volume_ratio = float(bar.volume / bar.prev5_vol_mean) if pd.notna(bar.prev5_vol_mean) and bar.prev5_vol_mean > 0 else 0.0
            call_signal = bar.close > bar.prev3_high and bar.ema5 > bar.ema20 and bar.ema20_slope > 0 and vol_ok
            put_signal = bar.close < bar.prev3_low and bar.ema5 < bar.ema20 and bar.ema20_slope < 0 and vol_ok
            direction = "call" if call_signal else "put" if put_signal else None
            if direction is None:
                continue
            if direction != daily_dir:
                continue
            if day_direction is not None and direction != day_direction:
                continue
            if entries_by_direction[direction] >= 2:
                continue
            if bar.datetime < cooldown_until[direction]:
                continue

            candidates = option_candidates(daily, trade_date, underlying, direction, args.candidate_pool)
            if candidates.empty:
                continue

            ranked: list[dict[str, Any]] = []
            for opt in candidates.itertuples(index=False):
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
                opt15 = resample_option_15m(opt1)
                row = opt15[opt15["datetime"] == bar.datetime]
                if row.empty:
                    continue
                r = row.iloc[0]
                cum_vol = opt1[opt1["datetime"] <= bar.datetime]["volume"].sum()
                if cum_vol <= 0 or r["volume"] <= 0:
                    continue
                if not (r["close"] > r["ema5"] > r["ema20"]):
                    continue
                ranked.append(
                    {
                        "option_code": opt.option_code,
                        "contract_id": opt.contract_id,
                        "contract_symbol": opt.contract_symbol,
                        "entry_price": float(r["close"]),
                        "entry_option_volume_15m": float(r["volume"]),
                        "cum_volume": float(cum_vol),
                        "dte": int(opt.dte),
                        "delta": float(opt.delta),
                        "implied_volatility": float(opt.implied_volatility),
                        "bars_1m": opt1,
                    }
                )
            ranked = sorted(ranked, key=lambda x: x["cum_volume"], reverse=True)[:3]
            if not ranked:
                continue
            chosen = ranked[0]
            exit_info = simulate_exit(chosen.pop("bars_1m"), bar.datetime, chosen["entry_price"])
            position_pct, signal_strength = position_pct_for_signal(iv_rank, etf_volume_ratio)
            if str(exit_info.get("exit_reason", "")).startswith("tp"):
                cooldown_until[direction] = pd.Timestamp(exit_info["exit_time"]) + pd.Timedelta(minutes=30)
            if day_direction is None:
                day_direction = direction
            trades.append(
                {
                    "trade_date": trade_date,
                    "underlying_code": underlying,
                    "direction": direction,
                    "entry_time": bar.datetime,
                    "etf_close": bar.close,
                    "etf_volume_15m": bar.volume,
                    "market_iv": iv,
                    "iv_rank_252": iv_rank,
                    "etf_volume_ratio": etf_volume_ratio,
                    "signal_strength": signal_strength,
                    "position_pct": position_pct,
                    "daily_direction": daily_dir,
                    "daily_ref_date": daily_dir_row.iloc[0]["daily_ref_date"],
                    "daily_ref_close": float(daily_dir_row.iloc[0]["daily_ref_close"]),
                    "daily_ref_ma20": float(daily_dir_row.iloc[0]["daily_ref_ma20"]),
                    "daily_ref_ma20_slope": float(daily_dir_row.iloc[0]["daily_ref_ma20_slope"]),
                    **chosen,
                    **exit_info,
                }
            )
            entries += 1
            entries_by_direction[direction] += 1

    trades_df = pd.DataFrame(trades)
    trades_path = RESEARCH_DIR / "backtest_v05_588000_recent1m_trades.csv"
    summary_path = RESEARCH_DIR / "backtest_v05_588000_recent1m_summary.csv"
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
