#!/usr/bin/env python3
"""Build daily KCB ETF option datasets for backtests.

Outputs are written under ./data:
  - etf_daily_588000_588080.csv
  - kcb_option_risk_indicators.csv
  - kcb_option_daily.csv
  - kcb_option_daily_with_etf.csv
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import time
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "raw_cache"
RISK_DIR = CACHE_DIR / "risk_indicator_sse"
OPTION_DAILY_DIR = CACHE_DIR / "option_daily_sina"

DEFAULT_SQLITE = Path(
    "/Users/aaren/ChinaETF/china-etf-strategy/cache/etf_5m_2020_202605.sqlite"
)
UNDERLYINGS = {
    "588000": "科创50ETF",
    "588080": "科创板50ETF",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    parser.add_argument("--start", default="20230605")
    parser.add_argument("--end", default=None)
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--limit-dates", type=int, default=None)
    parser.add_argument("--limit-contracts", type=int, default=None)
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args()


def ensure_dirs() -> None:
    for path in [DATA_DIR, RISK_DIR, OPTION_DAILY_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def ymd_to_iso(value: str) -> str:
    value = str(value)
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def iso_to_ymd(value: object) -> str:
    return pd.to_datetime(value).strftime("%Y%m%d")


def call_with_retry(func, *, retries: int, sleep: float, **kwargs):
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return func(**kwargs)
        except Exception as exc:  # noqa: BLE001 - cacheable data fetch boundary.
            last_error = exc
            if attempt < retries:
                time.sleep(sleep * attempt * 3)
    raise RuntimeError(f"{func.__name__} failed after {retries} attempts: {last_error}")


def build_etf_daily(sqlite_path: Path, start: str, end: str | None) -> pd.DataFrame:
    symbols = [f"{code}.SH" for code in UNDERLYINGS]
    params: list[object] = symbols + [start]
    end_clause = ""
    if end:
        end_clause = "and date <= ?"
        params.append(end)

    sql = f"""
        select symbol, dt, date, name, open, high, low, close, volume, amount
        from bars_5m
        where symbol in ({",".join("?" for _ in symbols)})
          and date >= ?
          {end_clause}
        order by symbol, dt
    """

    with sqlite3.connect(sqlite_path) as conn:
        bars = pd.read_sql_query(sql, conn, params=params)

    if bars.empty:
        raise RuntimeError(f"No ETF bars found in {sqlite_path}")

    bars["underlying_code"] = bars["symbol"].str.slice(0, 6)
    grouped = bars.groupby(["underlying_code", "date"], sort=True)
    daily = grouped.agg(
        underlying_name=("name", "last"),
        etf_open=("open", "first"),
        etf_high=("high", "max"),
        etf_low=("low", "min"),
        etf_close=("close", "last"),
        etf_volume=("volume", "sum"),
        etf_amount=("amount", "sum"),
        etf_bar_count=("close", "size"),
    ).reset_index()

    daily["trade_date"] = daily["date"].map(ymd_to_iso)
    daily = daily.drop(columns=["date"])
    daily = daily.sort_values(["underlying_code", "trade_date"]).reset_index(drop=True)
    daily["etf_return"] = daily.groupby("underlying_code")["etf_close"].pct_change()
    for window in [20, 30, 60, 120]:
        daily[f"hv_{window}d"] = (
            daily.groupby("underlying_code")["etf_return"]
            .rolling(window)
            .std()
            .reset_index(level=0, drop=True)
            * math.sqrt(252)
        )
    return daily


def fetch_risk_indicators(dates: list[str], retries: int, sleep: float, refresh: bool) -> pd.DataFrame:
    import akshare as ak

    frames: list[pd.DataFrame] = []
    for idx, date in enumerate(dates, start=1):
        cache_path = RISK_DIR / f"{date}.csv"
        if cache_path.exists() and not refresh:
            df = pd.read_csv(cache_path, dtype=str)
        else:
            print(f"[risk] {idx}/{len(dates)} {date}", flush=True)
            df = call_with_retry(
                ak.option_risk_indicator_sse,
                retries=retries,
                sleep=sleep,
                date=date,
            )
            df.to_csv(cache_path, index=False)
            time.sleep(sleep)
        if not df.empty:
            frames.append(df)

    if not frames:
        return pd.DataFrame()

    risk = pd.concat(frames, ignore_index=True)
    risk["CONTRACT_ID"] = risk["CONTRACT_ID"].astype(str)
    risk = risk[risk["CONTRACT_ID"].str.startswith(tuple(UNDERLYINGS))]
    return risk.reset_index(drop=True)


def normalize_risk(risk: pd.DataFrame) -> pd.DataFrame:
    if risk.empty:
        return risk

    out = risk.rename(
        columns={
            "TRADE_DATE": "trade_date",
            "SECURITY_ID": "option_code",
            "CONTRACT_ID": "contract_id",
            "CONTRACT_SYMBOL": "contract_symbol",
            "DELTA_VALUE": "delta",
            "THETA_VALUE": "theta",
            "GAMMA_VALUE": "gamma",
            "VEGA_VALUE": "vega",
            "RHO_VALUE": "rho",
            "IMPLC_VOLATLTY": "implied_volatility",
        }
    ).copy()
    out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.strftime("%Y-%m-%d")
    out["option_code"] = out["option_code"].astype(str).str.zfill(8)
    out["underlying_code"] = out["contract_id"].astype(str).str.slice(0, 6)
    out["option_type"] = out["contract_id"].astype(str).str[6].map({"C": "call", "P": "put"})
    out["expiry_ym"] = "20" + out["contract_id"].astype(str).str.slice(7, 11)
    out["strike_raw"] = out["contract_id"].astype(str).str.extract(r"M(\d+)$", expand=False)
    out["strike"] = pd.to_numeric(out["strike_raw"], errors="coerce") / 1000
    for col in ["delta", "theta", "gamma", "vega", "rho", "implied_volatility"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out[
        [
            "trade_date",
            "underlying_code",
            "option_code",
            "contract_id",
            "contract_symbol",
            "option_type",
            "expiry_ym",
            "strike",
            "delta",
            "theta",
            "gamma",
            "vega",
            "rho",
            "implied_volatility",
        ]
    ].sort_values(["trade_date", "underlying_code", "contract_id"])


def fetch_option_daily(codes: list[str], retries: int, sleep: float, refresh: bool) -> pd.DataFrame:
    import akshare as ak

    frames: list[pd.DataFrame] = []
    failures: list[dict[str, str]] = []
    for idx, code in enumerate(codes, start=1):
        cache_path = OPTION_DAILY_DIR / f"{code}.csv"
        if cache_path.exists() and not refresh:
            df = pd.read_csv(cache_path)
        else:
            print(f"[daily] {idx}/{len(codes)} {code}", flush=True)
            try:
                df = call_with_retry(
                    ak.option_sse_daily_sina,
                    retries=retries,
                    sleep=sleep,
                    symbol=code,
                )
            except Exception as exc:  # noqa: BLE001 - keep the batch resumable.
                failures.append({"option_code": str(code).zfill(8), "error": str(exc)})
                df = pd.DataFrame(columns=["日期", "开盘", "最高", "最低", "收盘", "成交量"])
            df.to_csv(cache_path, index=False)
            time.sleep(sleep)
        if not df.empty:
            df = df.copy()
            df["option_code"] = str(code).zfill(8)
            frames.append(df)

    if failures:
        pd.DataFrame(failures).to_csv(DATA_DIR / "option_daily_failures.csv", index=False)

    if not frames:
        return pd.DataFrame()

    daily = pd.concat(frames, ignore_index=True)
    daily = daily.rename(
        columns={
            "日期": "trade_date",
            "开盘": "option_open",
            "最高": "option_high",
            "最低": "option_low",
            "收盘": "option_close",
            "成交量": "option_volume",
        }
    )
    daily["trade_date"] = pd.to_datetime(daily["trade_date"]).dt.strftime("%Y-%m-%d")
    daily["option_code"] = daily["option_code"].astype(str).str.zfill(8)
    for col in ["option_open", "option_high", "option_low", "option_close", "option_volume"]:
        daily[col] = pd.to_numeric(daily[col], errors="coerce")
    daily = daily.drop_duplicates(["option_code", "trade_date"], keep="last")
    daily = daily.sort_values(["option_code", "trade_date"]).reset_index(drop=True)
    daily["option_return"] = daily.groupby("option_code")["option_close"].pct_change()
    return daily


def write_outputs(etf: pd.DataFrame, risk: pd.DataFrame, option_daily: pd.DataFrame) -> None:
    etf_path = DATA_DIR / "etf_daily_588000_588080.csv"
    risk_path = DATA_DIR / "kcb_option_risk_indicators.csv"
    daily_path = DATA_DIR / "kcb_option_daily.csv"
    merged_path = DATA_DIR / "kcb_option_daily_with_etf.csv"

    etf.to_csv(etf_path, index=False)
    risk.to_csv(risk_path, index=False)

    merged = risk.merge(option_daily, on=["trade_date", "option_code"], how="left")
    merged = merged.merge(etf, on=["trade_date", "underlying_code"], how="left")
    merged = merged.sort_values(["trade_date", "underlying_code", "contract_id"]).reset_index(drop=True)

    daily_cols = [
        "trade_date",
        "underlying_code",
        "underlying_name",
        "option_code",
        "contract_id",
        "contract_symbol",
        "option_type",
        "expiry_ym",
        "strike",
        "option_open",
        "option_high",
        "option_low",
        "option_close",
        "option_return",
        "option_volume",
        "implied_volatility",
        "hv_20d",
        "hv_30d",
        "hv_60d",
        "hv_120d",
        "delta",
        "theta",
        "gamma",
        "vega",
        "rho",
        "etf_open",
        "etf_high",
        "etf_low",
        "etf_close",
        "etf_return",
        "etf_volume",
        "etf_amount",
        "etf_bar_count",
    ]
    merged[daily_cols].to_csv(daily_path, index=False)
    merged.to_csv(merged_path, index=False)

    summary = pd.DataFrame(
        [
            {
                "file": etf_path.name,
                "rows": len(etf),
                "start": etf["trade_date"].min(),
                "end": etf["trade_date"].max(),
            },
            {
                "file": risk_path.name,
                "rows": len(risk),
                "start": risk["trade_date"].min(),
                "end": risk["trade_date"].max(),
            },
            {
                "file": daily_path.name,
                "rows": len(merged),
                "start": merged["trade_date"].min(),
                "end": merged["trade_date"].max(),
            },
        ]
    )
    summary.to_csv(DATA_DIR / "summary.csv", index=False)
    print(summary.to_string(index=False), flush=True)


def main() -> None:
    args = parse_args()
    ensure_dirs()

    etf = build_etf_daily(args.sqlite, args.start, args.end)
    dates = sorted(etf["trade_date"].map(iso_to_ymd).unique().tolist())
    if args.limit_dates:
        dates = dates[: args.limit_dates]

    risk_raw = fetch_risk_indicators(dates, args.retries, args.sleep, args.refresh)
    risk = normalize_risk(risk_raw)
    if risk.empty:
        raise RuntimeError("No KCB option risk rows were fetched.")

    codes = sorted(risk["option_code"].dropna().astype(str).unique().tolist())
    if args.limit_contracts:
        codes = codes[: args.limit_contracts]
        risk = risk[risk["option_code"].isin(codes)]

    option_daily = fetch_option_daily(codes, args.retries, args.sleep, args.refresh)
    write_outputs(etf, risk, option_daily)


if __name__ == "__main__":
    main()
