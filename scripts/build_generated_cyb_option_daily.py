#!/usr/bin/env python3
"""Generate a CYB option daily candidate table from local full 1m archives.

The full local archives contain minute OHLCV but not greeks.  This script uses
contract names from the iFinD wide Excel headers to recover option type,
expiry month and strike, aggregates the local minute files to daily bars, and
derives implied volatility / delta from option close and ETF close.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sqlite3
import sys
import zipfile
from pathlib import Path
from typing import Any

import openpyxl
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backtest_v02_recent_intraday as bt  # noqa: E402


DATA = ROOT / "data"
RESEARCH = ROOT / "research"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--end", default="2026-06-30")
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=DATA / "创业板 1 分钟数据（全）" / "易方达创业板ETF",
    )
    parser.add_argument(
        "--wide-root",
        type=Path,
        default=DATA / "双创补充期权数据",
    )
    parser.add_argument(
        "--contract-info",
        type=Path,
        default=DATA / "合约信息" / "易方达创业板ETF.csv",
    )
    parser.add_argument(
        "--etf-5m-sqlite",
        type=Path,
        default=Path(
            os.environ.get(
                "OPTION_ETF_SQLITE_PATH",
                "/Users/aaren/策略/china-etf-strategy/cache/etf_5m_2020_202605.sqlite",
            )
        ),
    )
    parser.add_argument(
        "--etf-daily-extra",
        type=Path,
        default=DATA / "etf_daily_159915.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DATA / "cyb_option_daily_generated.csv",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=RESEARCH / "cyb_option_daily_generated_summary.csv",
    )
    parser.add_argument("--risk-free-rate", type=float, default=0.02)
    return parser.parse_args()


def normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def bs_price(spot: float, strike: float, rate: float, iv: float, dte: int, option_type: str) -> float | None:
    if spot <= 0 or strike <= 0 or iv <= 0 or dte <= 0:
        return None
    years = dte / 365.0
    root_time = math.sqrt(years)
    denominator = iv * root_time
    if denominator <= 0:
        return None
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * years) / denominator
    d2 = d1 - denominator
    discounted = strike * math.exp(-rate * years)
    if option_type == "call":
        return spot * normal_cdf(d1) - discounted * normal_cdf(d2)
    return discounted * normal_cdf(-d2) - spot * normal_cdf(-d1)


def implied_volatility(price: float, spot: float, strike: float, rate: float, dte: int, option_type: str) -> float | None:
    if price <= 0 or spot <= 0 or strike <= 0 or dte <= 0:
        return None
    intrinsic = max(spot - strike, 0.0) if option_type == "call" else max(strike - spot, 0.0)
    if price + 1e-8 < intrinsic:
        return None
    low, high = 0.01, 3.00
    high_price = bs_price(spot, strike, rate, high, dte, option_type)
    if high_price is None or high_price < price:
        return None
    for _ in range(70):
        mid = (low + high) / 2.0
        model = bs_price(spot, strike, rate, mid, dte, option_type)
        if model is None:
            return None
        if model > price:
            high = mid
        else:
            low = mid
    return (low + high) / 2.0


def bs_delta(spot: float, strike: float, rate: float, iv: float, dte: int, option_type: str) -> float | None:
    if spot <= 0 or strike <= 0 or iv <= 0 or dte <= 0:
        return None
    years = dte / 365.0
    denominator = iv * math.sqrt(years)
    if denominator <= 0:
        return None
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * years) / denominator
    if option_type == "call":
        return normal_cdf(d1)
    return normal_cdf(d1) - 1.0


def parse_contract_name(code: str, name: str) -> dict[str, Any] | None:
    match = re.search(r"(购|沽)(\d{4})年(\d{1,2})月(\d+)", str(name))
    if not match:
        return None
    option_type = "call" if match.group(1) == "购" else "put"
    year = int(match.group(2))
    month = int(match.group(3))
    raw_strike = int(match.group(4))
    return {
        "option_code": str(code).split(".")[0].zfill(8),
        "contract_symbol": str(name),
        "option_type": option_type,
        "expiry_ym": year * 100 + month,
        "strike": raw_strike / 1000.0,
        "contract_id": "159915{}{:02d}{:02d}M{:06d}".format(
            "C" if option_type == "call" else "P",
            year % 100,
            month,
            raw_strike,
        ),
    }


def load_contract_map(wide_root: Path) -> pd.DataFrame:
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(wide_root.glob("创业板期权*.xlsx")):
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        # iFinD wide export repeats each contract every 15 columns.
        for col in range(1, ws.max_column + 1, 15):
            code = ws.cell(1, col).value
            name = ws.cell(1, col + 1).value if col + 1 <= ws.max_column else None
            if not code or not name:
                continue
            parsed = parse_contract_name(str(code), str(name))
            if parsed is not None:
                rows[parsed["option_code"]] = parsed
    out = pd.DataFrame(rows.values())
    if out.empty:
        raise RuntimeError(f"No CYB contract headers parsed from {wide_root}")
    return out


def load_contract_info(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    raw = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    required = ["合约代码", "合约名称", "到期日", "行权价", "期权类型"]
    if not all(col in raw.columns for col in required):
        return pd.DataFrame()
    out = pd.DataFrame()
    out["option_code"] = raw["合约代码"].astype(str).str.split(".").str[-1].str.zfill(8)
    out["contract_symbol"] = raw["合约名称"].astype(str)
    out["option_type"] = raw["期权类型"].map({"看涨": "call", "看跌": "put"})
    expiry = pd.to_datetime(raw["到期日"], errors="coerce")
    out["expiry_ym"] = expiry.dt.year * 100 + expiry.dt.month
    out["strike"] = pd.to_numeric(raw["行权价"], errors="coerce")
    out["contract_id"] = [
        "159915{}{:02d}{:02d}M{:06d}".format(
            "C" if option_type == "call" else "P",
            int(exp.year) % 100,
            int(exp.month),
            int(round(float(strike) * 1000)),
        )
        if pd.notna(exp) and pd.notna(strike) and option_type in ["call", "put"]
        else None
        for exp, strike, option_type in zip(expiry, out["strike"], out["option_type"])
    ]
    out = out.dropna(subset=["option_type", "expiry_ym", "strike", "contract_id"])
    out["expiry_ym"] = out["expiry_ym"].astype(int)
    return out.drop_duplicates("option_code", keep="last")


def load_etf_daily_from_sqlite(sqlite_path: Path, start: str, end: str) -> pd.DataFrame:
    sql = """
        select date, open, high, low, close, volume, amount
        from bars_5m
        where symbol = '159915.SZ'
          and date between ? and ?
        order by date, dt
    """
    with sqlite3.connect(sqlite_path) as conn:
        bars = pd.read_sql_query(sql, conn, params=[start.replace("-", ""), end.replace("-", "")])
    if bars.empty:
        return pd.DataFrame()
    bars["trade_date"] = pd.to_datetime(bars["date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
    grouped = bars.groupby("trade_date", as_index=False).agg(
        etf_open=("open", "first"),
        etf_high=("high", "max"),
        etf_low=("low", "min"),
        etf_close=("close", "last"),
        etf_volume=("volume", "sum"),
        etf_amount=("amount", "sum"),
    )
    grouped["underlying_code"] = "159915"
    return grouped


def load_etf_daily(extra_csv: Path, sqlite_path: Path, start: str, end: str) -> pd.DataFrame:
    frames = [load_etf_daily_from_sqlite(sqlite_path, start, end)]
    if extra_csv.exists():
        extra = pd.read_csv(extra_csv, dtype={"underlying_code": str})
        extra = extra[extra["underlying_code"].astype(str).str.split(".").str[0] == "159915"].copy()
        extra["trade_date"] = pd.to_datetime(extra["trade_date"]).dt.strftime("%Y-%m-%d")
        frames.append(extra)
    out = pd.concat([item for item in frames if not item.empty], ignore_index=True)
    out = out.drop_duplicates("trade_date", keep="last").sort_values("trade_date")
    return out[(out["trade_date"] >= start) & (out["trade_date"] <= end)].copy()


def aggregate_member(zip_file: zipfile.ZipFile, member: str, code: str, start: str, end: str) -> pd.DataFrame:
    with zip_file.open(member) as handle:
        df = pd.read_csv(handle, parse_dates=["datetime"])
    if df.empty:
        return pd.DataFrame()
    df = df[(df["datetime"] >= start) & (df["datetime"] <= f"{end} 23:59:59")].copy()
    if df.empty:
        return pd.DataFrame()
    df["trade_date"] = df["datetime"].dt.strftime("%Y-%m-%d")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.groupby("trade_date", as_index=False).agg(
        option_open=("open", "first"),
        option_high=("high", "max"),
        option_low=("low", "min"),
        option_close=("close", "last"),
        option_volume=("volume", "sum"),
        option_bar_count=("close", "count"),
    ).assign(option_code=code)


def build_option_daily(args: argparse.Namespace, contract_map: pd.DataFrame, etf_daily: pd.DataFrame) -> pd.DataFrame:
    mapping = contract_map.set_index("option_code").to_dict("index")
    etf_by_date = etf_daily.set_index("trade_date").to_dict("index")
    rows: list[pd.DataFrame] = []
    start_ym = args.start[:7]
    end_ym = args.end[:7]
    for archive in sorted(args.archive_root.glob("*.zip")):
        month = archive.stem
        if month < start_ym or month > end_ym:
            continue
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                if not member.endswith(".csv"):
                    continue
                code = Path(member).stem.split(".")[-1].zfill(8)
                if code not in mapping:
                    continue
                daily = aggregate_member(zf, member, code, args.start, args.end)
                if not daily.empty:
                    rows.append(daily)
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    meta = contract_map.copy()
    out = out.merge(meta, on="option_code", how="inner")
    out["underlying_code"] = "159915"
    out["underlying_name"] = "创业板ETF易方达"
    out["expiry_date"] = out["expiry_ym"].map(bt.expiry_date)
    out["trade_ts"] = pd.to_datetime(out["trade_date"])
    out["dte"] = (out["expiry_date"] - out["trade_ts"]).dt.days
    out = out[out["dte"] > 0].copy()
    etf = etf_daily[
        [
            "trade_date",
            "etf_open",
            "etf_high",
            "etf_low",
            "etf_close",
            "etf_volume",
            "etf_amount",
        ]
    ]
    out = out.merge(etf, on="trade_date", how="inner")
    ivs: list[float | None] = []
    deltas: list[float | None] = []
    for row in out.itertuples(index=False):
        iv = implied_volatility(
            float(row.option_close),
            float(row.etf_close),
            float(row.strike),
            args.risk_free_rate,
            int(row.dte),
            str(row.option_type),
        )
        delta = None
        if iv is not None:
            delta = bs_delta(
                float(row.etf_close),
                float(row.strike),
                args.risk_free_rate,
                iv,
                int(row.dte),
                str(row.option_type),
            )
        ivs.append(iv)
        deltas.append(delta)
    out["implied_volatility"] = ivs
    out["delta"] = deltas
    out["option_return"] = out.groupby("option_code")["option_close"].pct_change()
    out["option_amount"] = pd.NA
    out["theta"] = pd.NA
    out["gamma"] = pd.NA
    out["vega"] = pd.NA
    out["rho"] = pd.NA
    return out


def add_daily_direction(option_daily: pd.DataFrame, etf_daily_csv: Path) -> pd.DataFrame:
    directions = bt.load_daily_direction("159915", etf_daily_csv=etf_daily_csv)
    return option_daily.merge(directions, on="trade_date", how="left")


def main() -> None:
    args = parse_args()
    contract_map = load_contract_info(args.contract_info)
    if contract_map.empty:
        contract_map = load_contract_map(args.wide_root)
    etf_daily = load_etf_daily(args.etf_daily_extra, args.etf_5m_sqlite, args.start, args.end)
    if etf_daily.empty:
        raise RuntimeError("No 159915 ETF daily data available")
    # Persist the enriched ETF daily table so the normal backtest can use the
    # same source, including 2023 dates that are missing from the prior CSV.
    etf_generated = DATA / "etf_daily_159915_generated.csv"
    etf_daily.to_csv(etf_generated, index=False)

    option_daily = build_option_daily(args, contract_map, etf_daily)
    option_daily = add_daily_direction(option_daily, etf_generated)
    keep = [
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
        "option_amount",
        "implied_volatility",
        "delta",
        "theta",
        "gamma",
        "vega",
        "rho",
        "dte",
        "etf_open",
        "etf_high",
        "etf_low",
        "etf_close",
        "etf_volume",
        "etf_amount",
        "daily_ref_date",
        "daily_ref_close",
        "daily_ref_ma5",
        "daily_ref_ma10",
        "daily_ref_ma20",
        "daily_ref_ma5_slope",
        "daily_ref_ma10_slope",
        "daily_ref_ma20_slope",
        "daily_ref_ma_cluster",
        "daily_ref_upper_shadow_ratio",
        "daily_ref_lower_shadow_ratio",
        "daily_ref_volume_ratio20",
        "daily_direction",
    ]
    for col in keep:
        if col not in option_daily.columns:
            option_daily[col] = pd.NA
    option_daily = option_daily[keep].sort_values(["trade_date", "option_code"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    option_daily.to_csv(args.output, index=False)
    summary = pd.DataFrame(
        [
            {
                "output": str(args.output),
                "etf_daily": str(etf_generated),
                "rows": int(len(option_daily)),
                "dates": int(option_daily["trade_date"].nunique()) if not option_daily.empty else 0,
                "min_date": option_daily["trade_date"].min() if not option_daily.empty else None,
                "max_date": option_daily["trade_date"].max() if not option_daily.empty else None,
                "contracts": int(option_daily["option_code"].nunique()) if not option_daily.empty else 0,
                "iv_nonnull": int(option_daily["implied_volatility"].notna().sum()) if not option_daily.empty else 0,
                "delta_nonnull": int(option_daily["delta"].notna().sum()) if not option_daily.empty else 0,
            }
        ]
    )
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.summary, index=False)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
