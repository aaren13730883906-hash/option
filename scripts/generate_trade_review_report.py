#!/usr/bin/env python3
"""Generate an HTML trade review report for v0.4 588000 option trades."""

from __future__ import annotations

import argparse
import html
import math
import re
import sqlite3
from pathlib import Path

import pandas as pd


ROOT = Path("/Users/aaren/策略/期权策略")
RESEARCH = ROOT / "research"
DATA = ROOT / "data"
INTRADAY = DATA / "intraday_cache"
SQLITE = Path("/Users/aaren/策略/china-etf-strategy/cache/etf_5m_2020_202605.sqlite")
TRADES = RESEARCH / "backtest_v05_588000_recent1m_trades.csv"
CAPITAL = RESEARCH / "backtest_v05_588000_capital_100k.csv"
MARKET_IV = DATA / "kcb_market_iv_daily.csv"
ETF_DAILY = DATA / "etf_daily_588000_588080.csv"
OUT = RESEARCH / "trade_review_v05_588000_recent1m.html"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=None, help="Filter trades from YYYY-MM-DD.")
    parser.add_argument("--end", default=None, help="Filter trades through YYYY-MM-DD.")
    parser.add_argument("--output", type=Path, default=OUT)
    return parser.parse_args()


def fmt(value: object, digits: int = 4) -> str:
    try:
        if pd.isna(value):
            return "-"
        return f"{float(value):.{digits}f}"
    except Exception:
        return str(value)


def pct(value: object) -> str:
    try:
        if pd.isna(value):
            return "-"
        return f"{float(value) * 100:.2f}%"
    except Exception:
        return str(value)


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(spot: float, strike: float, tau: float, rate: float, vol: float, option_type: str) -> float:
    if spot <= 0 or strike <= 0 or tau <= 0 or vol <= 0:
        return max(spot - strike, 0.0) if option_type == "call" else max(strike - spot, 0.0)
    sqrt_t = math.sqrt(tau)
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * tau) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    if option_type == "call":
        return spot * norm_cdf(d1) - strike * math.exp(-rate * tau) * norm_cdf(d2)
    return strike * math.exp(-rate * tau) * norm_cdf(-d2) - spot * norm_cdf(-d1)


def implied_vol(price: float, spot: float, strike: float, tau: float, option_type: str, rate: float = 0.02) -> float | None:
    if price <= 0 or spot <= 0 or strike <= 0 or tau <= 0:
        return None
    intrinsic = max(spot - strike, 0.0) if option_type == "call" else max(strike - spot, 0.0)
    if price < intrinsic * 0.995:
        return None
    lo, hi = 0.01, 3.0
    for _ in range(60):
        mid = (lo + hi) / 2
        val = bs_price(spot, strike, tau, rate, mid, option_type)
        if val > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def strike_from_contract(contract_id: str) -> float:
    match = re.search(r"M(\d+)$", str(contract_id))
    if not match:
        return math.nan
    return int(match.group(1)) / 1000


def option_type_from_contract(contract_id: str) -> str:
    return "call" if "C" in str(contract_id)[:8] else "put"


def load_etf_5m(start: str, end: str) -> pd.DataFrame:
    sql = """
        select dt, date, open, high, low, close, volume, amount
        from bars_5m
        where symbol = '588000.SH'
          and date between ? and ?
        order by dt
    """
    with sqlite3.connect(SQLITE) as conn:
        df = pd.read_sql_query(sql, conn, params=[start.replace("-", ""), end.replace("-", "")])
    df["datetime"] = pd.to_datetime(df["dt"])
    return df


def etf_15m_for_day(trade_date: str) -> pd.DataFrame:
    start = (pd.Timestamp(trade_date) - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    raw = load_etf_5m(start, trade_date)
    g = raw.set_index("datetime").sort_index()
    out = g.resample("15min", label="right", closed="right").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna(subset=["close"]).reset_index()
    out["ema5"] = out["close"].ewm(span=5, adjust=False).mean()
    out["ema20"] = out["close"].ewm(span=20, adjust=False).mean()
    out["ema20_slope"] = out["ema20"].diff()
    out["prev3_low"] = out["low"].shift(1).rolling(3).min()
    out["prev3_high"] = out["high"].shift(1).rolling(3).max()
    out["prev5_vol_mean"] = out["volume"].shift(1).rolling(5).mean()
    out["vol_ratio"] = out["volume"] / out["prev5_vol_mean"]
    day = out[out["datetime"].dt.strftime("%Y-%m-%d") == trade_date].copy()
    return day[(day["datetime"].dt.strftime("%H:%M") >= "09:30") & (day["datetime"].dt.strftime("%H:%M") <= "15:00")]


def etf_daily_window(trade_date: str, before: int = 30, after: int = 8) -> pd.DataFrame:
    df = pd.read_csv(ETF_DAILY, dtype={"underlying_code": str})
    df = df[df["underlying_code"] == "588000"].copy()
    df["datetime"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values("datetime").reset_index(drop=True)
    df = df.rename(
        columns={
            "etf_open": "open",
            "etf_high": "high",
            "etf_low": "low",
            "etf_close": "close",
            "etf_volume": "volume",
        }
    )
    for window in [5, 10, 20]:
        df[f"ema{window}"] = df["close"].rolling(window).mean()
    idx = df.index[df["trade_date"] == trade_date]
    if len(idx) == 0:
        return df.tail(before + after + 1)
    i = int(idx[0])
    return df.iloc[max(0, i - before) : min(len(df), i + after + 1)].copy()


def option_1m(trade_date: str, option_code: str) -> pd.DataFrame:
    path = INTRADAY / f"{trade_date}_{str(option_code).zfill(8)}_1m.csv"
    df = pd.read_csv(path, parse_dates=["datetime"], dtype={"option_code": str})
    df["ema5"] = df["close"].ewm(span=5, adjust=False).mean()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    return df


def option_15m(df: pd.DataFrame) -> pd.DataFrame:
    g = df.set_index("datetime").sort_index()
    out = g.resample("15min", label="right", closed="right").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna(subset=["close"]).reset_index()
    out["ema5"] = out["close"].ewm(span=5, adjust=False).mean()
    out["ema20"] = out["close"].ewm(span=20, adjust=False).mean()
    return out


def add_intraday_iv(opt: pd.DataFrame, etf5: pd.DataFrame, trade: pd.Series) -> pd.DataFrame:
    underlying = etf5[["datetime", "close"]].rename(columns={"close": "spot"}).set_index("datetime").sort_index()
    minutes = opt.set_index("datetime").join(underlying, how="left")
    minutes["spot"] = minutes["spot"].ffill().bfill()
    strike = strike_from_contract(trade["contract_id"])
    opt_type = option_type_from_contract(trade["contract_id"])
    dte = max(float(trade["dte"]), 1.0)
    tau = dte / 365.0
    ivs: list[float | None] = []
    for row in minutes.itertuples():
        ivs.append(implied_vol(float(row.close), float(row.spot), strike, tau, opt_type))
    minutes["iv_calc"] = ivs
    return minutes.reset_index()


def scale(values: pd.Series, lo_px: float, hi_px: float, pad: float = 0.08):
    finite = pd.to_numeric(values, errors="coerce").dropna()
    if finite.empty:
        return lambda _: (lo_px + hi_px) / 2
    mn, mx = float(finite.min()), float(finite.max())
    if math.isclose(mn, mx):
        mn -= 1
        mx += 1
    span = mx - mn
    mn -= span * pad
    mx += span * pad
    return lambda v: hi_px - (float(v) - mn) / (mx - mn) * (hi_px - lo_px)


def x_scale(times: pd.Series, left: float, right: float):
    vals = pd.to_datetime(times).map(lambda t: pd.Timestamp(t).timestamp())
    mn, mx = float(vals.min()), float(vals.max())
    if math.isclose(mn, mx):
        mx += 1
    return lambda t: left + (pd.Timestamp(t).timestamp() - mn) / (mx - mn) * (right - left)


def polyline(df: pd.DataFrame, x_fn, y_fn, col: str, color: str, width: float = 1.6) -> str:
    pts = []
    for row in df[["datetime", col]].dropna().itertuples(index=False):
        pts.append(f"{x_fn(row.datetime):.1f},{y_fn(row[1]):.1f}")
    if len(pts) < 2:
        return ""
    return f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round"/>'


def candle_svg(df: pd.DataFrame, title: str, entry_time, exit_time, entry_price, exit_price, *, width=1120, height=360, tick_format="%H:%M") -> str:
    left, right, top, price_bottom, vol_top, bottom = 58, width - 22, 34, 238, 260, height - 28
    x_fn = x_scale(df["datetime"], left, right)
    y_price = scale(pd.concat([df["high"], df["low"], df.get("ema5", df["close"]), df.get("ema20", df["close"])]), top, price_bottom)
    y_vol = scale(df["volume"], vol_top, bottom, pad=0)
    body_w = max(4, (right - left) / max(len(df), 1) * 0.55)
    parts = [
        f'<svg viewBox="0 0 {width} {height}" class="chart">',
        f'<text x="{left}" y="22" class="chart-title">{html.escape(title)}</text>',
        f'<line x1="{left}" y1="{price_bottom}" x2="{right}" y2="{price_bottom}" class="axis"/>',
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" class="axis"/>',
    ]
    for row in df.itertuples():
        x = x_fn(row.datetime)
        up = row.close >= row.open
        color = "#c23b3b" if up else "#137a63"
        y_o, y_c, y_h, y_l = y_price(row.open), y_price(row.close), y_price(row.high), y_price(row.low)
        parts.append(f'<line x1="{x:.1f}" y1="{y_h:.1f}" x2="{x:.1f}" y2="{y_l:.1f}" stroke="{color}" stroke-width="1"/>')
        parts.append(
            f'<rect x="{x - body_w / 2:.1f}" y="{min(y_o, y_c):.1f}" width="{body_w:.1f}" '
            f'height="{max(abs(y_o - y_c), 1):.1f}" fill="{color}" opacity="0.82"/>'
        )
        yv = y_vol(row.volume)
        parts.append(f'<rect x="{x - body_w / 2:.1f}" y="{yv:.1f}" width="{body_w:.1f}" height="{bottom - yv:.1f}" fill="#8aa0b8" opacity="0.38"/>')
    if "ema5" in df:
        parts.append(polyline(df, x_fn, y_price, "ema5", "#d9861c", 1.8))
    if "ema10" in df:
        parts.append(polyline(df, x_fn, y_price, "ema10", "#16a34a", 1.6))
    if "ema20" in df:
        parts.append(polyline(df, x_fn, y_price, "ema20", "#2f6fbb", 1.8))
    for label, t, p, color in [("ENTRY", entry_time, entry_price, "#7b3ff2"), ("EXIT", exit_time, exit_price, "#111827")]:
        x = x_fn(t)
        y = y_price(p)
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{bottom}" stroke="{color}" stroke-width="1.2" stroke-dasharray="4 3"/>')
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{color}"/>')
        parts.append(f'<text x="{x + 6:.1f}" y="{y - 8:.1f}" class="marker" fill="{color}">{label} {fmt(p)}</text>')
    tick_rows = df.iloc[:: max(len(df) // 6, 1)]
    for row in tick_rows.itertuples():
        x = x_fn(row.datetime)
        parts.append(f'<text x="{x:.1f}" y="{height - 8}" class="tick" text-anchor="middle">{pd.Timestamp(row.datetime).strftime(tick_format)}</text>')
    parts.append('<text x="900" y="22" class="legend"><tspan fill="#d9861c">MA/EMA5</tspan>  <tspan fill="#16a34a">MA10</tspan>  <tspan fill="#2f6fbb">MA/EMA20</tspan>  <tspan fill="#8aa0b8">Volume</tspan></text>')
    parts.append("</svg>")
    return "\n".join(parts)


def line_svg(df: pd.DataFrame, title: str, cols: list[tuple[str, str]], *, width=1120, height=260) -> str:
    left, right, top, bottom = 58, width - 22, 34, height - 34
    x_fn = x_scale(df["datetime"], left, right)
    y_fn = scale(pd.concat([df[c] for c, _ in cols if c in df]), top, bottom)
    parts = [
        f'<svg viewBox="0 0 {width} {height}" class="chart small">',
        f'<text x="{left}" y="22" class="chart-title">{html.escape(title)}</text>',
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" class="axis"/>',
    ]
    for col, color in cols:
        if col in df:
            parts.append(polyline(df, x_fn, y_fn, col, color, 1.8))
    tick_rows = df.iloc[:: max(len(df) // 6, 1)]
    for row in tick_rows.itertuples():
        x = x_fn(row.datetime)
        parts.append(f'<text x="{x:.1f}" y="{height - 10}" class="tick" text-anchor="middle">{pd.Timestamp(row.datetime).strftime("%H:%M")}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def market_iv_svg(market_iv: pd.DataFrame, trade_date: str) -> str:
    df = market_iv.copy()
    df["datetime"] = pd.to_datetime(df["trade_date"])
    return line_svg(df, "近一个月市场IV与IV Rank（日线）", [("market_iv", "#7b3ff2"), ("iv_rank_252", "#d9861c")], height=220)


def build_report(start_filter: str | None = None, end_filter: str | None = None) -> str:
    trades = pd.read_csv(TRADES, parse_dates=["entry_time", "exit_time"], dtype={"option_code": str})
    if start_filter:
        trades = trades[trades["trade_date"] >= start_filter]
    if end_filter:
        trades = trades[trades["trade_date"] <= end_filter]
    trades = trades.reset_index(drop=True)
    if trades.empty:
        raise RuntimeError("No trades matched the requested date range.")
    cap = pd.read_csv(CAPITAL, parse_dates=["entry_time"])
    if start_filter:
        cap = cap[cap["trade_date"] >= start_filter]
    if end_filter:
        cap = cap[cap["trade_date"] <= end_filter]
    start, end = trades["trade_date"].min(), trades["trade_date"].max()
    cap_lookup = cap.set_index(["trade_date", "contract_id", "entry_time"])
    sections = []
    for idx, trade in trades.iterrows():
        trade_date = str(trade["trade_date"])
        etf_daily = etf_daily_window(trade_date)
        etf15 = etf_15m_for_day(trade_date)
        etf5 = load_etf_5m(trade_date, trade_date)
        opt1 = option_1m(trade_date, str(trade["option_code"]))
        opt15 = option_15m(opt1)
        cap_key = (trade_date, trade["contract_id"], trade["entry_time"])
        cap_row = cap_lookup.loc[cap_key] if cap_key in cap_lookup.index else pd.Series(dtype=object)
        contracts = cap_row.get("contracts")
        contracts_text = "-" if pd.isna(contracts) else f"{int(contracts)}张"
        net_pnl = cap_row.get("net_pnl")
        premium_return = cap_row.get("return_on_premium")
        skip_reason = cap_row.get("skip_reason")
        pnl_text = (
            f"未成交 / {html.escape(str(skip_reason))}"
            if pd.notna(skip_reason)
            else f"{fmt(net_pnl, 2)} 元 / 权利金收益 {pct(premium_return)}"
        )
        entry_time = pd.Timestamp(trade["entry_time"])
        exit_time = pd.Timestamp(trade["exit_time"])
        entry_etf = float(trade["etf_close"])
        exit_etf_rows = etf15[etf15["datetime"] <= exit_time]
        exit_etf = float(exit_etf_rows.iloc[-1]["close"]) if not exit_etf_rows.empty else entry_etf
        entry_option = float(trade["entry_price"])
        exit_option = float(trade["exit_price_2"])
        entry_bar = etf15[etf15["datetime"] == entry_time]
        reason = ""
        if not entry_bar.empty:
            r = entry_bar.iloc[0]
            reason = (
                f"ETF收盘 {fmt(r['close'], 3)}；EMA5 {fmt(r['ema5'], 4)}，EMA20 {fmt(r['ema20'], 4)}；"
                f"EMA20斜率 {fmt(r['ema20_slope'], 5)}；量比 {fmt(r['vol_ratio'], 2)}；"
                f"前3高 {fmt(r['prev3_high'], 3)}，前3低 {fmt(r['prev3_low'], 3)}。"
            )
        header = f"{idx + 1}. {trade_date} {str(trade['direction']).upper()} {trade['contract_symbol']} {trade['contract_id']}"
        cards = f"""
        <div class="cards">
          <div><b>入场</b><span>{entry_time.strftime('%H:%M')} @ {fmt(entry_option)}</span></div>
          <div><b>出场</b><span>{exit_time.strftime('%H:%M')} / {html.escape(str(trade['exit_reason']))}</span></div>
          <div><b>合约</b><span>DTE {int(trade['dte'])} / Delta {fmt(trade['delta'], 3)} / IV {pct(trade['implied_volatility'])}</span></div>
          <div><b>市场IV</b><span>{pct(trade['market_iv'])} / Rank {pct(trade['iv_rank_252'])}</span></div>
          <div><b>仓位</b><span>{pct(trade['position_pct'])} / {html.escape(str(trade['signal_strength']))} / {contracts_text}</span></div>
          <div><b>盈亏</b><span>{pnl_text}</span></div>
        </div>
        <p class="reason">{html.escape(reason)}</p>
        """
        sections.append(
            f"""
            <section>
              <h2>{html.escape(header)}</h2>
              {cards}
              {candle_svg(etf_daily, '588000 ETF日K：价格、MA与成交量', pd.Timestamp(trade_date), pd.Timestamp(trade_date), entry_etf, entry_etf, tick_format="%m-%d")}
              {candle_svg(etf15, '588000 ETF 15分钟K线：价格、EMA与成交量', entry_time, exit_time, entry_etf, exit_etf)}
              {candle_svg(opt15, '期权15分钟K线：价格、EMA与成交量', entry_time, exit_time, entry_option, exit_option)}
            </section>
            """
        )
    style = """
    <style>
      body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;margin:0;background:#f5f7fb;color:#171923}
      header{padding:28px 36px;background:#111827;color:white}
      h1{margin:0 0 8px;font-size:28px} h2{margin:0 0 14px;font-size:20px}
      .sub{color:#cbd5e1;margin:0}
      section{margin:24px auto;padding:22px 24px;max-width:1180px;background:white;border:1px solid #e5e7eb;border-radius:8px}
      .cards{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:12px 0 10px}
      .cards div{border:1px solid #e5e7eb;border-radius:6px;padding:10px 12px;background:#fbfdff}
      .cards b{display:block;font-size:12px;color:#64748b;margin-bottom:4px}.cards span{font-size:14px}
      .reason{font-size:14px;color:#334155;background:#f8fafc;border-left:3px solid #7b3ff2;padding:10px 12px}
      .chart{width:100%;height:auto;margin-top:12px;background:#fff;border:1px solid #e5e7eb;border-radius:6px}
      .chart-title{font-weight:700;font-size:15px;fill:#111827}.axis{stroke:#d1d5db;stroke-width:1}.tick{font-size:10px;fill:#64748b}
      .legend{font-size:12px;fill:#64748b}.marker{font-size:11px;font-weight:700}.small{background:#fff}
      @media(max-width:800px){.cards{grid-template-columns:1fr} header{padding:22px} section{margin:14px;padding:14px}}
    </style>
    """
    return f"""<!doctype html>
    <html lang="zh-CN"><head><meta charset="utf-8"><title>v0.5 588000期权交易复盘</title>{style}</head>
    <body>
      <header>
        <h1>588000期权交易复盘</h1>
        <p class="sub">区间：{html.escape(start)} 至 {html.escape(end)}；每笔图表展示 ETF日K、ETF盘中、合约盘中、成交量、均线与入出场位置。</p>
      </header>
      {''.join(sections)}
    </body></html>"""


def main() -> None:
    args = parse_args()
    args.output.write_text(build_report(args.start, args.end), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
