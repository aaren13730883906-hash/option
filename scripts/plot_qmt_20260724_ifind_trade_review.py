#!/usr/bin/env python3
"""Fetch iFinD 1m bars and plot the 2026-07-24 QMT trade review."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ETF_CACHE = DATA / "etf_intraday_ifind"
OPTION_CACHE = DATA / "intraday_cache"
OUTPUT_HTML = ROOT / "research" / "qmt_20260724_588000_10011916_trade_review.html"
TOKEN_RTF = ROOT / "data:ifind_refresh_token" / "refresh- token.rtf"

GET_ACCESS_TOKEN_URL = "https://quantapi.51ifind.com/api/v1/get_access_token"
HIGH_FREQUENCY_URL = "https://quantapi.51ifind.com/api/v1/high_frequency"
INDICATORS = "open,high,low,close,volume,amount,changeRatio"

TRADE_DATE = "2026-07-24"
ETF_CODE = "588000"
ETF_IFIND_CODE = "588000.SH"
OPTION_CODE = "10011916"
OPTION_IFIND_CODE = "10011916.SH"

BUY_TIME = "09:45"
SELL_TIME = "14:45"
BUY_REF = 0.1920
BUY_FILL = 0.1923
SELL_REF = 0.2006
SELL_FILL = 0.2003
QTY = 10
MULTIPLIER = 10000
FEE_PER_SIDE = 2.0
PNL = 760.0


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
        raise RuntimeError(
            "No iFinD token found. Set IFIND_ACCESS_TOKEN/IFIND_REFRESH_TOKEN "
            "or provide data:ifind_refresh_token/refresh- token.rtf"
        )
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


def standardize_hf(df: pd.DataFrame, code: str, include_option_code: bool) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.rename(columns={"changeRatio": "change_ratio"}).copy()
    time_col = next((c for c in ["time", "datetime", "date"] if c in out.columns), None)
    if time_col is None:
        return pd.DataFrame()
    out["datetime"] = pd.to_datetime(out[time_col], errors="coerce")
    keep = ["datetime", "open", "high", "low", "close", "volume", "amount", "change_ratio"]
    if include_option_code:
        out["option_code"] = str(code).zfill(8)
        keep.insert(1, "option_code")
    for col in keep:
        if col not in out.columns:
            out[col] = pd.NA
    out = out[keep].dropna(subset=["datetime"]).drop_duplicates(["datetime"], keep="last")
    for col in ["open", "high", "low", "close", "volume", "amount", "change_ratio"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["close"]).sort_values("datetime")
    return out


def fetch_1m(ifind_code: str, cache_path: Path, option_code: str | None, refresh: bool = False) -> pd.DataFrame:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists() and not refresh:
        return pd.read_csv(cache_path, parse_dates=["datetime"], dtype={"option_code": str})
    token = get_access_token()
    headers = {"Content-Type": "application/json", "access_token": token}
    body = {
        "codes": ifind_code,
        "indicators": INDICATORS,
        "starttime": f"{TRADE_DATE} 09:30:00",
        "endtime": f"{TRADE_DATE} 15:00:00",
        "functionpara": {"Fill": "Blank"},
    }
    response = requests.post(HIGH_FREQUENCY_URL, json=body, headers=headers, timeout=90)
    response.raise_for_status()
    out = standardize_hf(normalize_tables(response.json()), option_code or ifind_code, option_code is not None)
    if out.empty:
        raise RuntimeError(f"No 1m bars returned for {ifind_code} {TRADE_DATE}")
    out.to_csv(cache_path, index=False)
    time.sleep(0.15)
    return out


def compact_bars(df: pd.DataFrame) -> dict[str, list[Any]]:
    return {
        "time": df["datetime"].dt.strftime("%H:%M").tolist(),
        "open": [round(float(x), 6) for x in df["open"]],
        "high": [round(float(x), 6) for x in df["high"]],
        "low": [round(float(x), 6) for x in df["low"]],
        "close": [round(float(x), 6) for x in df["close"]],
        "volume": [0 if pd.isna(x) else float(x) for x in df["volume"]],
    }


def value_at(df: pd.DataFrame, hhmm: str, column: str = "close") -> float | None:
    rows = df[df["datetime"].dt.strftime("%H:%M") == hhmm]
    if rows.empty:
        return None
    return float(rows.iloc[-1][column])


def build_html(etf: pd.DataFrame, opt: pd.DataFrame) -> str:
    etf_open = float(etf.iloc[0]["open"])
    etf_buy = value_at(etf, BUY_TIME)
    etf_sell = value_at(etf, SELL_TIME)
    opt_buy = value_at(opt, BUY_TIME)
    opt_sell = value_at(opt, SELL_TIME)
    premium_buy = QTY * BUY_FILL * MULTIPLIER
    premium_sell = QTY * SELL_FILL * MULTIPLIER
    fee = QTY * FEE_PER_SIDE * 2
    trade_return = PNL / premium_buy if premium_buy else 0.0
    payload = json.dumps(
        {
            "tradeDate": TRADE_DATE,
            "etfCode": ETF_IFIND_CODE,
            "optionCode": OPTION_IFIND_CODE,
            "buyTime": BUY_TIME,
            "sellTime": SELL_TIME,
            "buyRef": BUY_REF,
            "buyFill": BUY_FILL,
            "sellRef": SELL_REF,
            "sellFill": SELL_FILL,
            "qty": QTY,
            "multiplier": MULTIPLIER,
            "premiumBuy": round(premium_buy, 2),
            "premiumSell": round(premium_sell, 2),
            "fee": round(fee, 2),
            "pnl": PNL,
            "tradeReturnPct": round(trade_return * 100, 2),
            "etfOpen": round(etf_open, 6),
            "etfBuy": round(etf_buy, 6) if etf_buy is not None else None,
            "etfSell": round(etf_sell, 6) if etf_sell is not None else None,
            "optBuy": round(opt_buy, 6) if opt_buy is not None else None,
            "optSell": round(opt_sell, 6) if opt_sell is not None else None,
            "etf": compact_bars(etf),
            "option": compact_bars(opt),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QMT 2026-07-24 交易复盘：588000 / 10011916</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: Canvas; --fg: CanvasText; --muted: color-mix(in srgb, CanvasText 60%, Canvas);
      --card: color-mix(in srgb, CanvasText 4%, Canvas); --border: color-mix(in srgb, CanvasText 16%, Canvas);
      --red: #d93025; --green: #0f9d58; --blue: #1a73e8; --orange: #f29900;
    }}
    body {{ margin: 0; padding: 22px; font: 14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background: var(--bg); color: var(--fg); }}
    h1 {{ margin: 0 0 6px; font-size: 23px; }}
    .sub {{ color: var(--muted); margin-bottom: 18px; }}
    .cards {{ display: grid; grid-template-columns: repeat(4, minmax(160px, 1fr)); gap: 12px; margin: 14px 0 18px; }}
    .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 12px; }}
    .k {{ color: var(--muted); font-size: 12px; }}
    .v {{ font-size: 20px; font-weight: 700; margin-top: 4px; }}
    .gain {{ color: var(--green); }}
    .loss {{ color: var(--red); }}
    .chart {{ height: 380px; margin: 14px 0 22px; border: 1px solid var(--border); border-radius: 14px; }}
    .note {{ color: var(--muted); font-size: 13px; }}
    @media (max-width: 900px) {{ .cards {{ grid-template-columns: repeat(2, 1fr); }} }}
  </style>
</head>
<body>
  <h1>QMT 实盘模拟复盘：2026-07-24 Put Reversal</h1>
  <div class="sub">数据：同花顺 QuantAPI 1分钟高频行情；交易日志：qmt/0725.txt；标的 {ETF_IFIND_CODE}，期权 {OPTION_IFIND_CODE}</div>
  <div class="cards">
    <div class="card"><div class="k">买入</div><div class="v">09:45 @ 0.1923</div><div class="note">参考价 0.1920，数量 10</div></div>
    <div class="card"><div class="k">卖出</div><div class="v">14:45 @ 0.2003</div><div class="note">参考价 0.2006，EOD</div></div>
    <div class="card"><div class="k">影子账面 PnL</div><div class="v gain">+¥760</div><div class="note">含手续费 ¥40</div></div>
    <div class="card"><div class="k">权利金收益率</div><div class="v gain">+3.95%</div><div class="note">买入权利金 ¥19,230</div></div>
  </div>
  <div id="etfChart" class="chart"></div>
  <div id="optChart" class="chart"></div>
  <div class="note">提示：买卖点按 QMT passorder 日志标注；fill 价格使用脚本中的限价成交假设，实际成交仍应以券商成交回报为准。</div>
  <script>
    const data = {payload};
    const css = getComputedStyle(document.documentElement);
    const grid = 'rgba(128,128,128,.18)';
    function candleTrace(bars, name, yaxis='y') {{
      return {{type:'candlestick', name, x:bars.time, open:bars.open, high:bars.high, low:bars.low, close:bars.close,
        increasing:{{line:{{color:'#d93025'}}, fillcolor:'#d93025'}},
        decreasing:{{line:{{color:'#0f9d58'}}, fillcolor:'#0f9d58'}}, yaxis}};
    }}
    function volumeTrace(bars, name) {{
      return {{type:'bar', name, x:bars.time, y:bars.volume, marker:{{color:'rgba(26,115,232,.25)'}}, yaxis:'y2'}};
    }}
    function shapes() {{
      return [
        {{type:'line', x0:data.buyTime, x1:data.buyTime, y0:0, y1:1, yref:'paper', line:{{color:'#f29900', width:2, dash:'dash'}}}},
        {{type:'line', x0:data.sellTime, x1:data.sellTime, y0:0, y1:1, yref:'paper', line:{{color:'#1a73e8', width:2, dash:'dash'}}}}
      ];
    }}
    function annotations(topText) {{
      return [
        {{x:data.buyTime, y:1, yref:'paper', text:'买入<br>09:45', showarrow:true, arrowhead:2, ax:-35, ay:-45, bgcolor:'rgba(242,153,0,.15)', bordercolor:'#f29900'}},
        {{x:data.sellTime, y:1, yref:'paper', text:'卖出<br>14:45', showarrow:true, arrowhead:2, ax:35, ay:-45, bgcolor:'rgba(26,115,232,.15)', bordercolor:'#1a73e8'}},
        {{x:0, y:1.12, xref:'paper', yref:'paper', text:topText, showarrow:false, align:'left'}}
      ];
    }}
    const baseLayout = {{
      margin:{{l:54,r:54,t:58,b:38}}, paper_bgcolor:'transparent', plot_bgcolor:'transparent',
      xaxis:{{rangeslider:{{visible:false}}, gridcolor:grid}},
      yaxis:{{domain:[.24,1], gridcolor:grid, fixedrange:false}},
      yaxis2:{{domain:[0,.18], gridcolor:grid, title:'量', fixedrange:true}},
      legend:{{orientation:'h'}},
      shapes: shapes(),
    }};
    Plotly.newPlot('etfChart', [candleTrace(data.etf, '588000 ETF K线'), volumeTrace(data.etf, 'ETF成交量')], {{
      ...baseLayout,
      title:'588000.SH 标的 1分钟 K线',
      annotations: annotations(`ETF：开盘 ${{data.etfOpen}}，09:45 ${{data.etfBuy}}，14:45 ${{data.etfSell}}`)
    }}, {{responsive:true}});
    Plotly.newPlot('optChart', [candleTrace(data.option, '10011916 期权K线'), volumeTrace(data.option, '期权成交量')], {{
      ...baseLayout,
      title:'10011916.SH 期权 1分钟价格走势',
      annotations: annotations(`期权：买入参考 ${{data.buyRef}} / fill ${{data.buyFill}}，卖出参考 ${{data.sellRef}} / fill ${{data.sellFill}}，PnL +¥${{data.pnl}}`)
    }}, {{responsive:true}});
  </script>
</body>
</html>
"""


def main() -> None:
    etf_cache = ETF_CACHE / f"{TRADE_DATE}_{ETF_CODE}_1m.csv"
    option_cache = OPTION_CACHE / f"{TRADE_DATE}_{OPTION_CODE}_1m.csv"
    etf = fetch_1m(ETF_IFIND_CODE, etf_cache, None)
    opt = fetch_1m(OPTION_IFIND_CODE, option_cache, OPTION_CODE)
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(build_html(etf, opt), encoding="utf-8")
    print(f"[ok] ETF rows={len(etf)} option rows={len(opt)}")
    print(f"[ok] wrote {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
