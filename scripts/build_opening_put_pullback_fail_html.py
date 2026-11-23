#!/usr/bin/env python3
"""Build an HTML review dashboard for opening-put-pullback-fail trades."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd

from backtest_kcb_put_flow_0945 import read_option_1m
from backtest_v02_recent_intraday import DEFAULT_SQLITE, load_etf_5m


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = ROOT / "research"
TRADES_CSV = RESEARCH_DIR / "opening_put_pullback_fail_best_trades.csv"
OUTPUT_HTML = RESEARCH_DIR / "opening_put_pullback_fail_18_trades.html"


def clean_number(value: Any, digits: int = 6) -> float | None:
    try:
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return round(number, digits)
    except Exception:
        return None


def compact_rows(df: pd.DataFrame, fields: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in df.itertuples(index=False):
        item: dict[str, Any] = {}
        for field in fields:
            value = getattr(row, field)
            if field == "datetime":
                item[field] = pd.Timestamp(value).strftime("%H:%M")
            else:
                item[field] = clean_number(value, 6)
        out.append(item)
    return out


def parse_exit_legs(text: Any) -> list[tuple[float, float]]:
    if not isinstance(text, str) or not text.strip():
        return []
    legs: list[tuple[float, float]] = []
    for part in text.split(";"):
        m = re.match(r"\s*([0-9.]+)@([0-9.]+)\s*", part)
        if not m:
            continue
        legs.append((float(m.group(1)), float(m.group(2))))
    return legs


def build_exit_markers(trade: pd.Series) -> list[dict[str, Any]]:
    legs = parse_exit_legs(trade.get("exit_legs"))
    exit_time = pd.Timestamp(trade["exit_time"]).strftime("%H:%M")
    tp1_time = trade.get("tp1_time")
    tp1_text = ""
    if pd.notna(tp1_time):
        tp1_text = pd.Timestamp(tp1_time).strftime("%H:%M")
    markers: list[dict[str, Any]] = []
    if len(legs) >= 2 and tp1_text:
        markers.append({"time": tp1_text, "price": round(legs[0][1], 6), "label": "卖出1/2"})
        markers.append({"time": exit_time, "price": round(legs[-1][1], 6), "label": "尾仓卖出"})
    elif legs:
        markers.append({"time": exit_time, "price": round(legs[-1][1], 6), "label": "卖出"})
    else:
        price = clean_number(trade.get("exit_price_2"), 6)
        markers.append({"time": exit_time, "price": price, "label": "卖出"})
    return markers


def trade_payload(trades: pd.DataFrame, etf_5m: pd.DataFrame) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for index, trade in trades.iterrows():
        trade_date = str(trade["trade_date"])
        option_code = str(int(trade["option_code"]))
        option = read_option_1m(option_code, trade_date)
        option = option.sort_values("datetime")
        etf = etf_5m[etf_5m["trade_date"].astype(str) == trade_date].sort_values("datetime")
        entry_time = pd.Timestamp(trade["entry_time"]).strftime("%H:%M")
        exit_time = pd.Timestamp(trade["exit_time"]).strftime("%H:%M")
        payload.append(
            {
                "id": int(index + 1),
                "tradeDate": trade_date,
                "optionCode": option_code,
                "contractSymbol": str(trade.get("contract_symbol", "")),
                "entryTime": entry_time,
                "entryPrice": clean_number(trade["entry_price"], 6),
                "exitTime": exit_time,
                "exitReason": str(trade["exit_reason"]),
                "ret": clean_number(float(trade["return"]) * 100.0, 2),
                "positionPct": clean_number(float(trade["position_pct"]) * 100.0, 1),
                "etfDrop945": clean_number(float(trade["etf_open_ret_945"]) * 100.0, 2),
                "closePos945": clean_number(float(trade["etf_close_pos_945"]) * 100.0, 1),
                "volume15": int(float(trade["volume15"])),
                "entryMarker": {
                    "time": entry_time,
                    "price": clean_number(trade["entry_price"], 6),
                    "label": "买入",
                },
                "exitMarkers": build_exit_markers(trade),
                "etfMarkers": [
                    {"time": "09:45", "label": "09:45确认", "price": None},
                    {"time": entry_time, "label": "买入时刻", "price": None},
                    {"time": exit_time, "label": "卖出时刻", "price": None},
                ],
                "etf": compact_rows(etf, ["datetime", "open", "high", "low", "close"]),
                "option": compact_rows(option, ["datetime", "open", "high", "low", "close"]),
            }
        )
    return payload


def html_template(data: list[dict[str, Any]]) -> str:
    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>开盘下杀弱反抽失败 Put 交易复盘</title>
<style>
:root {{
  color-scheme: light dark;
  --bg: #0b1020;
  --panel: #121a2f;
  --panel2: #17213a;
  --text: #e8eefc;
  --muted: #9aa8c7;
  --grid: rgba(154,168,199,.22);
  --line: #7dd3fc;
  --option: #fbbf24;
  --buy: #ef4444;
  --sell: #22c55e;
  --border: rgba(154,168,199,.25);
}}
@media (prefers-color-scheme: light) {{
  :root {{
    --bg: #f6f8fc;
    --panel: #ffffff;
    --panel2: #eef3fb;
    --text: #182033;
    --muted: #5d6b86;
    --grid: rgba(93,107,134,.22);
    --line: #0369a1;
    --option: #b45309;
    --border: rgba(93,107,134,.22);
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
.wrap {{ max-width: 1320px; margin: 0 auto; padding: 20px; }}
.top {{ display: flex; gap: 14px; align-items: end; flex-wrap: wrap; margin-bottom: 14px; }}
h1 {{ margin: 0; font-size: 22px; font-weight: 650; }}
.hint {{ color: var(--muted); font-size: 13px; margin-top: 4px; }}
select {{ min-width: 360px; max-width: 100%; padding: 9px 10px; border-radius: 10px; border: 1px solid var(--border); color: var(--text); background: var(--panel); }}
.metrics {{ display: grid; grid-template-columns: repeat(6, minmax(120px, 1fr)); gap: 10px; margin: 12px 0 16px; }}
.metric {{ background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 10px 12px; }}
.metric .k {{ color: var(--muted); font-size: 12px; }}
.metric .v {{ margin-top: 4px; font-size: 18px; font-weight: 650; }}
.red {{ color: var(--buy); }}
.green {{ color: var(--sell); }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
.card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 12px; min-width: 0; }}
.card h2 {{ margin: 0 0 8px; font-size: 15px; font-weight: 650; }}
svg {{ display: block; width: 100%; height: 360px; overflow: visible; }}
.axis, .axis text {{ fill: var(--muted); font-size: 11px; }}
.axis line, .axis path {{ stroke: var(--grid); }}
.gridline {{ stroke: var(--grid); stroke-width: 1; }}
.line {{ fill: none; stroke-width: 2; }}
.marker-label {{ font-size: 11px; fill: var(--text); paint-order: stroke; stroke: var(--panel); stroke-width: 3; }}
.legend {{ color: var(--muted); font-size: 12px; margin-top: 4px; display: flex; gap: 16px; flex-wrap: wrap; }}
.dot {{ display: inline-block; width: 9px; height: 9px; border-radius: 99px; margin-right: 5px; }}
@media (max-width: 900px) {{
  .grid {{ grid-template-columns: 1fr; }}
  .metrics {{ grid-template-columns: repeat(2, minmax(120px, 1fr)); }}
  svg {{ height: 320px; }}
}}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div>
      <h1>开盘下杀弱反抽失败 Put：18 笔交易买卖点复盘</h1>
      <div class="hint">红色=买入，绿色=卖出；ETF 用 5 分钟线，期权用 1 分钟线。</div>
    </div>
    <select id="tradeSelect" aria-label="选择交易"></select>
  </div>
  <div class="metrics" id="metrics"></div>
  <div class="grid">
    <section class="card">
      <h2>ETF 当日走势：588000.SH</h2>
      <svg id="etfChart" role="img" aria-label="ETF 当日走势"></svg>
      <div class="legend"><span><i class="dot" style="background:var(--line)"></i>ETF close</span><span><i class="dot" style="background:var(--buy)"></i>买入时刻</span><span><i class="dot" style="background:var(--sell)"></i>卖出时刻</span></div>
    </section>
    <section class="card">
      <h2>期权合约走势与买卖点</h2>
      <svg id="optionChart" role="img" aria-label="期权走势与买卖点"></svg>
      <div class="legend"><span><i class="dot" style="background:var(--option)"></i>option close</span><span><i class="dot" style="background:var(--buy)"></i>买入</span><span><i class="dot" style="background:var(--sell)"></i>卖出</span></div>
    </section>
  </div>
</div>
<script>
const trades = {data_json};
const select = document.getElementById('tradeSelect');
const metrics = document.getElementById('metrics');
const etfSvg = document.getElementById('etfChart');
const optionSvg = document.getElementById('optionChart');

function timeToMinute(t) {{
  const [h, m] = t.split(':').map(Number);
  return h * 60 + m;
}}
function fmt(v, d=4) {{ return Number(v).toFixed(d); }}
function linePath(points, x, y) {{
  return points.map((p, i) => `${{i ? 'L' : 'M'}}${{x(timeToMinute(p.datetime)).toFixed(1)}},${{y(p.close).toFixed(1)}}`).join(' ');
}}
function nearestPrice(rows, time) {{
  const target = timeToMinute(time);
  let best = rows[0], bestDist = Math.abs(timeToMinute(rows[0].datetime) - target);
  for (const row of rows) {{
    const dist = Math.abs(timeToMinute(row.datetime) - target);
    if (dist < bestDist) {{ best = row; bestDist = dist; }}
  }}
  return best ? best.close : null;
}}
function clear(svg) {{ while (svg.firstChild) svg.removeChild(svg.firstChild); }}
function el(name, attrs={{}}) {{
  const node = document.createElementNS('http://www.w3.org/2000/svg', name);
  for (const [k,v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}}
function chart(svg, rows, color, markers, mode) {{
  clear(svg);
  const width = svg.clientWidth || 600, height = svg.clientHeight || 360;
  const margin = {{left: 52, right: 20, top: 20, bottom: 34}};
  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;
  svg.setAttribute('viewBox', `0 0 ${{width}} ${{height}}`);
  const xs = rows.map(r => timeToMinute(r.datetime));
  const ys = rows.flatMap(r => [r.low, r.high, r.close]).filter(v => v !== null && v !== undefined);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  let minY = Math.min(...ys), maxY = Math.max(...ys);
  const padY = (maxY - minY) * 0.08 || maxY * 0.01 || 0.01;
  minY -= padY; maxY += padY;
  const x = v => margin.left + (v - minX) / (maxX - minX || 1) * innerW;
  const y = v => margin.top + (maxY - v) / (maxY - minY || 1) * innerH;
  for (let i = 0; i <= 4; i++) {{
    const yy = margin.top + innerH * i / 4;
    svg.appendChild(el('line', {{x1: margin.left, x2: width - margin.right, y1: yy, y2: yy, class: 'gridline'}}));
    const val = maxY - (maxY - minY) * i / 4;
    svg.appendChild(el('text', {{x: 8, y: yy + 4, class: 'axis'}})).textContent = fmt(val, mode === 'etf' ? 3 : 4);
  }}
  const tickTimes = ['09:30','10:00','10:30','11:00','13:30','14:00','14:30','15:00'];
  for (const t of tickTimes) {{
    const tx = timeToMinute(t);
    if (tx < minX || tx > maxX) continue;
    const xx = x(tx);
    svg.appendChild(el('line', {{x1: xx, x2: xx, y1: margin.top, y2: height - margin.bottom, class: 'gridline'}}));
    const text = el('text', {{x: xx - 14, y: height - 10, class: 'axis'}});
    text.textContent = t;
    svg.appendChild(text);
  }}
  svg.appendChild(el('path', {{d: linePath(rows, x, y), class: 'line', stroke: color}}));
  for (const m of markers) {{
    const price = m.price ?? nearestPrice(rows, m.time);
    if (price === null || price === undefined) continue;
    const xx = x(timeToMinute(m.time));
    const yy = y(price);
    const isBuy = m.label.includes('买');
    const fill = isBuy ? 'var(--buy)' : (m.label.includes('确认') ? 'var(--muted)' : 'var(--sell)');
    svg.appendChild(el('circle', {{cx: xx, cy: yy, r: 5, fill}}));
    const label = el('text', {{x: xx + 7, y: yy - 7, class: 'marker-label'}});
    label.textContent = `${{m.label}} ${{m.time}}`;
    svg.appendChild(label);
  }}
}}
function render(i) {{
  const t = trades[i];
  metrics.innerHTML = '';
  const cells = [
    ['日期', t.tradeDate],
    ['合约', `${{t.optionCode}}`],
    ['仓位', `${{t.positionPct}}%`],
    ['收益', `${{t.ret}}%`, t.ret >= 0 ? 'red' : 'green'],
    ['09:45 ETF跌幅', `${{t.etfDrop945}}%`],
    ['退出原因', t.exitReason],
  ];
  for (const [k,v,cls] of cells) {{
    const div = document.createElement('div');
    div.className = 'metric';
    div.innerHTML = `<div class="k">${{k}}</div><div class="v ${{cls || ''}}">${{v}}</div>`;
    metrics.appendChild(div);
  }}
  const etfMarkers = t.etfMarkers.map(m => ({{...m}}));
  chart(etfSvg, t.etf, 'var(--line)', etfMarkers, 'etf');
  chart(optionSvg, t.option, 'var(--option)', [t.entryMarker, ...t.exitMarkers], 'option');
}}
trades.forEach((t, i) => {{
  const opt = document.createElement('option');
  opt.value = String(i);
  opt.textContent = `${{t.tradeDate}}  ${{t.optionCode}}  ${{t.entryTime}}买入  收益${{t.ret}}%`;
  select.appendChild(opt);
}});
select.addEventListener('change', () => render(Number(select.value)));
window.addEventListener('resize', () => render(Number(select.value || 0)));
render(0);
</script>
</body>
</html>
"""


def main() -> None:
    trades = pd.read_csv(TRADES_CSV, parse_dates=["entry_time", "exit_time", "tp1_time"])
    start = str(trades["trade_date"].min())
    end = str(trades["trade_date"].max())
    etf_5m = load_etf_5m(DEFAULT_SQLITE, ["588000"], start, end)
    payload = trade_payload(trades, etf_5m)
    OUTPUT_HTML.write_text(html_template(payload), encoding="utf-8")
    print(OUTPUT_HTML)


if __name__ == "__main__":
    main()
