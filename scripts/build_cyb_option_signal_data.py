#!/usr/bin/env python3
"""Build the minimal 159915 option universe needed by the dual-ETF backtest.

The SZSE risk-indicator export supplies historical numeric option codes and
Greeks. iFinD supplies daily OHLCV for ranking candidates. Only locally
pre-screened signal dates are requested, keeping API usage small.
"""

from __future__ import annotations

import math
import sqlite3
import sys
from io import BytesIO
from pathlib import Path
from statistics import NormalDist
from typing import Any

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backtest_v02_recent_intraday as bt  # noqa: E402


DATA_DIR = ROOT / "data"
RISK_CACHE_DIR = DATA_DIR / "raw_cache" / "risk_indicator_szse"
DAILY_OUTPUT = DATA_DIR / "cyb_option_signal_daily.csv"
RISK_OUTPUT = DATA_DIR / "cyb_option_risk_signal_dates.csv"
ETF_OUTPUT = DATA_DIR / "etf_daily_159915.csv"
IV_OUTPUT = DATA_DIR / "cyb_market_iv_daily.csv"
SQLITE_PATH = Path("/Users/aaren/策略/china-etf-strategy/cache/etf_5m_2020_202605.sqlite")
SZSE_REPORT_URL = "https://www.sse.org.cn/api/report/ShowReport"
IFIND_HISTORY_URL = "https://quantapi.51ifind.com/api/v1/cmd_history_quotation"

# These dates are generated solely from local ETF data from 2025-07-04 onward.
# They are the union of the CYB opening-range signals and strong 15-minute
# fallback signals. The opening thresholds are 0.25% range amplitude and 1.25x
# breakout volume; the fallback starts with the completed 09:45 bar.
SIGNALS = {
    "2025-07-04": "call",
    "2025-07-09": "call",
    "2025-07-15": "call",
    "2025-07-16": "call",
    "2025-07-17": "call",
    "2025-07-21": "call",
    "2025-07-22": "call",
    "2025-07-23": "call",
    "2025-07-24": "call",
    "2025-07-28": "call",
    "2025-08-19": "call",
    "2025-08-22": "call",
    "2025-09-03": "call",
    "2025-09-11": "call",
    "2025-09-17": "call",
    "2025-09-19": "call",
    "2025-09-25": "call",
    "2025-09-29": "call",
    "2025-10-27": "call",
    "2025-10-29": "call",
    "2025-12-10": "call",
    "2025-12-11": "call",
    "2025-12-24": "call",
    "2026-01-06": "call",
    "2026-01-13": "call",
    "2026-01-15": "call",
    "2026-03-09": "put",
    "2026-03-11": "call",
    "2026-04-16": "call",
    "2026-04-17": "call",
    "2026-04-22": "call",
    "2026-05-11": "call",
}


def implied_volatility_from_greeks(
    delta: float,
    gamma: float,
    spot: float,
    dte: int,
    option_type: str,
    dividend_yield: float = 0.0,
) -> float:
    """Recover the Black-Scholes volatility used to produce Delta and Gamma."""
    values = [delta, gamma, spot, float(dte), dividend_yield]
    if not all(math.isfinite(float(value)) for value in values):
        return math.nan
    if gamma <= 0 or spot <= 0 or dte <= 0:
        return math.nan

    tau = dte / 365.0
    discount = math.exp(-dividend_yield * tau)
    delta_probability = delta / discount
    if option_type == "put":
        delta_probability += 1.0
    if not 0.0 < delta_probability < 1.0:
        return math.nan

    d1 = NormalDist().inv_cdf(delta_probability)
    normal_density = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    volatility = discount * normal_density / (spot * gamma * math.sqrt(tau))
    return volatility if 0.01 <= volatility <= 3.0 else math.nan


def fourth_wednesday(year: int, month: int) -> pd.Timestamp:
    first = pd.Timestamp(year=year, month=month, day=1)
    days = pd.date_range(first, first + pd.offsets.MonthEnd(0), freq="D")
    return days[days.weekday == 2][3]


def parse_contract(row: pd.Series) -> dict[str, Any]:
    contract_id = str(row["合约代码"])
    expiry_ym = int("20" + contract_id[7:11])
    expiry = fourth_wednesday(expiry_ym // 100, expiry_ym % 100)
    return {
        "trade_date": str(row["trade_date"]),
        "underlying_code": "159915",
        "option_code": str(int(row["合约编码"])).zfill(8),
        "contract_id": contract_id,
        "contract_symbol": str(row["合约简称"]),
        "option_type": "call" if contract_id[6] == "C" else "put",
        "expiry_ym": expiry_ym,
        "expiry_date": expiry,
        "strike": int(contract_id.split("M", 1)[1]) / 1000,
        "delta": float(row["Delta"]),
        "theta": float(row["Theta"]),
        "gamma": float(row["Gamma"]),
        "vega": float(row["Vega"]),
        "rho": float(row["Rho"]),
    }


def fetch_risk_date(trade_date: str) -> pd.DataFrame:
    RISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = RISK_CACHE_DIR / f"{trade_date}.csv"
    if cache.exists():
        return pd.read_csv(cache, dtype={"合约编码": str, "合约代码": str})

    response = requests.get(
        SZSE_REPORT_URL,
        params={
            "SHOWTYPE": "xlsx",
            "CATALOGID": "option_hyfxzb",
            "TABKEY": "tab1",
            "txtSearchDate": trade_date,
        },
        timeout=60,
    )
    response.raise_for_status()
    risk = pd.read_excel(BytesIO(response.content))
    risk = risk[risk["合约代码"].astype(str).str.startswith("159915")].copy()
    risk["trade_date"] = trade_date
    risk.to_csv(cache, index=False)
    return risk


def build_etf_daily() -> pd.DataFrame:
    with sqlite3.connect(SQLITE_PATH) as conn:
        bars = pd.read_sql_query(
            """
            select date, name, open, high, low, close, volume, amount
            from bars_5m
            where symbol = '159915.SZ'
              and date between '20240101' and '20260525'
            order by dt
            """,
            conn,
        )
    grouped = bars.groupby("date", sort=True)
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
    daily["underlying_code"] = "159915"
    daily["trade_date"] = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d")
    daily = daily.drop(columns="date")
    daily["etf_return"] = daily["etf_close"].pct_change()
    for window in [20, 30, 60, 120]:
        daily[f"hv_{window}d"] = daily["etf_return"].rolling(window).std() * math.sqrt(252)
    daily.to_csv(ETF_OUTPUT, index=False)
    return daily


def build_market_iv() -> pd.DataFrame:
    import akshare as ak

    qvix = ak.index_option_cyb_qvix().copy()
    qvix["trade_date"] = pd.to_datetime(qvix["date"]).dt.strftime("%Y-%m-%d")
    qvix["market_iv"] = pd.to_numeric(qvix["close"], errors="coerce") / 100
    qvix = qvix.dropna(subset=["market_iv"]).sort_values("trade_date")
    roll_min = qvix["market_iv"].rolling(252, min_periods=60).min()
    roll_max = qvix["market_iv"].rolling(252, min_periods=60).max()
    qvix["iv_rank_252"] = ((qvix["market_iv"] - roll_min) / (roll_max - roll_min)).clip(0, 1)
    qvix["iv_percentile_252"] = qvix["market_iv"].rolling(252, min_periods=60).apply(
        lambda values: (values <= values[-1]).mean(),
        raw=True,
    )
    qvix["underlying_code"] = "159915"
    out = qvix[
        ["underlying_code", "trade_date", "market_iv", "iv_rank_252", "iv_percentile_252"]
    ].copy()
    out.to_csv(IV_OUTPUT, index=False)
    return out


def fetch_daily_quotes(rows: pd.DataFrame, headers: dict[str, str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for trade_date, group in rows.groupby("trade_date", sort=True):
        codes = ",".join(bt.option_thscode(code) for code in group["option_code"])
        if not codes:
            continue
        body = {
            "codes": codes,
            "indicators": bt.INDICATORS,
            "startdate": trade_date,
            "enddate": trade_date,
            "functionpara": {"Fill": "Blank"},
        }
        response = requests.post(
            IFIND_HISTORY_URL,
            json=body,
            headers=headers,
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errorcode") not in (0, None):
            print(f"[warn] {trade_date}: {payload.get('errorcode')} {payload.get('errmsg')}", flush=True)
            continue
        raw = bt.normalize_tables(payload)
        if raw.empty:
            continue
        raw["trade_date"] = trade_date
        raw["option_code"] = raw["thscode"].astype(str).str.split(".").str[0].str.zfill(8)
        frames.append(raw)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates(["trade_date", "option_code"])


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    etf_daily = build_etf_daily()
    market_iv = build_market_iv()

    risk_frames: list[pd.DataFrame] = []
    for trade_date in SIGNALS:
        print(f"[szse-risk] {trade_date}", flush=True)
        raw = fetch_risk_date(trade_date)
        raw["trade_date"] = trade_date
        parsed = pd.DataFrame([parse_contract(row) for _, row in raw.iterrows()])
        parsed["dte"] = (parsed["expiry_date"] - pd.Timestamp(trade_date)).dt.days
        common = parsed[
            (parsed["option_type"] == SIGNALS[trade_date])
            & parsed["delta"].abs().between(0.35, 0.65)
        ].copy()
        normal = common[common["dte"].between(10, 35)].copy()
        if not normal.empty:
            normal["edge_dte_candidate"] = False
            normal["dte_position_factor"] = 1.0
            risk_frames.append(normal)
        else:
            edge = common[
                common["dte"].between(7, 9) | common["dte"].between(36, 40)
            ].copy()
            edge["edge_dte_candidate"] = True
            edge["dte_position_factor"] = 0.60
            risk_frames.append(edge)

    risk = pd.concat(risk_frames, ignore_index=True) if risk_frames else pd.DataFrame()
    risk.to_csv(RISK_OUTPUT, index=False)

    token = bt.get_access_token()
    headers = {"Content-Type": "application/json", "access_token": token}
    quotes = fetch_daily_quotes(risk, headers)
    daily = risk.merge(quotes, on=["trade_date", "option_code"], how="left")
    daily = daily.merge(
        market_iv[["trade_date", "market_iv", "iv_rank_252"]],
        on="trade_date",
        how="left",
    )
    daily = daily.merge(
        etf_daily[["trade_date", "etf_close"]],
        on="trade_date",
        how="left",
    )
    daily["implied_volatility"] = daily.apply(
        lambda row: implied_volatility_from_greeks(
            delta=float(row["delta"]),
            gamma=float(row["gamma"]),
            spot=float(row["etf_close"]),
            dte=int(row["dte"]),
            option_type=str(row["option_type"]),
        ),
        axis=1,
    )
    daily["iv_source"] = "szse_delta_gamma_derived"
    daily["iv_gap_vs_market"] = daily["implied_volatility"] - daily["market_iv"]
    rename = {
        "open": "option_open",
        "high": "option_high",
        "low": "option_low",
        "close": "option_close",
        "volume": "option_volume",
        "amount": "option_amount",
        "changeRatio": "option_return_pct",
    }
    daily = daily.rename(columns=rename)
    for col in ["option_open", "option_high", "option_low", "option_close", "option_volume"]:
        if col not in daily:
            daily[col] = pd.NA
        daily[col] = pd.to_numeric(daily[col], errors="coerce")
    daily["option_return"] = pd.to_numeric(daily.get("option_return_pct"), errors="coerce") / 100
    daily = daily.drop(columns=["expiry_date", "thscode"], errors="ignore")
    daily.to_csv(DAILY_OUTPUT, index=False)
    print(
        {
            "risk_rows": len(risk),
            "quoted_rows": int(daily["option_volume"].notna().sum()),
            "derived_iv_rows": int(daily["implied_volatility"].notna().sum()),
            "signal_dates": int(daily["trade_date"].nunique()),
            "output": str(DAILY_OUTPUT),
        },
        flush=True,
    )


if __name__ == "__main__":
    main()
