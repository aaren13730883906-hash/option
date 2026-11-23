#!/usr/bin/env python3
"""Create an HTML review page for the 1453.19% KCB strategy run."""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from backtest_kcb_put_flow_0945 import read_option_1m  # noqa: E402
from backtest_v02_recent_intraday import DEFAULT_SQLITE, load_etf_15m  # noqa: E402


RESEARCH_DIR = ROOT / "research"
DETAILS_CSV = RESEARCH_DIR / "strategy_1453_19_trade_details.csv"
TRADES_CSV = RESEARCH_DIR / "strategy_1453_19_trades.csv"
EVENTS_CSV = RESEARCH_DIR / "kcb_option_flow_15m_events.csv"
OUTPUT_HTML = RESEARCH_DIR / "strategy_1453_19_trade_review.html"


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def parse_strike(contract_id: Any, symbol: Any = "") -> float | None:
    text = str(contract_id)
    match = re.search(r"M(\d+)$", text)
    if match:
        return int(match.group(1)) / 1000.0
    symbol_text = str(symbol)
    match = re.search(r"(\d{3,4})$", symbol_text)
    if match:
        return int(match.group(1)) / 1000.0
    return None


def option_type(direction: Any) -> str:
    return "call" if str(direction).lower().startswith("call") else "put"


def compact_bars(df: pd.DataFrame) -> dict[str, list[Any]]:
    if df.empty:
        return {"x": [], "open": [], "high": [], "low": [], "close": [], "volume": []}
    out = df.dropna(subset=["datetime", "open", "high", "low", "close"]).copy()
    return {
        "x": out["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist(),
        "open": [round(float(x), 6) for x in out["open"]],
        "high": [round(float(x), 6) for x in out["high"]],
        "low": [round(float(x), 6) for x in out["low"]],
        "close": [round(float(x), 6) for x in out["close"]],
        "volume": [float(x) for x in out.get("volume", pd.Series([0] * len(out)))],
    }


def parse_exit_points(row: pd.Series) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    exit_time = pd.Timestamp(row["exit_time"]).strftime("%Y-%m-%d %H:%M:%S")
    text = str(row.get("exit_fills", ""))
    for part in text.split(";"):
        if "@" not in part:
            continue
        quantity, price = part.split("@", 1)
        points.append(
            {
                "x": exit_time,
                "quantity": quantity,
                "price": safe_float(price, 0.0),
            }
        )
    if not points:
        points.append({"x": exit_time, "quantity": "all", "price": safe_float(row.get("exit_price_2"), 0.0)})
    return points


def load_strike_grid() -> dict[tuple[str, str], list[float]]:
    if not EVENTS_CSV.exists():
        return {}
    events = pd.read_csv(EVENTS_CSV)
    grids: dict[tuple[str, str], list[float]] = {}
    if not {"trade_date", "option_type", "strike"}.issubset(events.columns):
        return grids
    for (trade_date, opt_type), group in events.groupby(["trade_date", "option_type"]):
        strikes = sorted({round(float(x), 6) for x in group["strike"].dropna() if float(x) > 0})
        if strikes:
            grids[(str(trade_date), str(opt_type).lower())] = strikes
    return grids


def moneyness_label(
    *,
    direction: str,
    strike: float | None,
    spot: float | None,
    strikes: list[float],
) -> tuple[str, int | None, float | None]:
    if strike is None or spot is None or spot <= 0:
        return "-", None, None
    if strikes and len(strikes) >= 2:
        atm = min(strikes, key=lambda x: abs(x - spot))
        diffs = [b - a for a, b in zip(strikes, strikes[1:]) if b > a]
        step = sorted(diffs)[len(diffs) // 2] if diffs else None
        levels = int(round(abs(strike - atm) / step)) if step and step > 0 else int(abs(strikes.index(strike) - strikes.index(atm))) if strike in strikes and atm in strikes else None
    else:
        # Some flow-event days contain only the selected strike for a side,
        # especially for historical Call trades.  KCB ETF options are listed
        # on a dense grid around the money; 0.05 is the practical near-ATM
        # strike step in these backtests, so use it only as a display fallback.
        step = 0.05
        atm = round(spot / step) * step
        levels = int(round(abs(strike - atm) / step))
    if levels == 0 or abs(strike / spot - 1.0) <= 0.005:
        return "平值", 0, strike / spot - 1.0
    is_call = direction == "call"
    out_of_money = strike > spot if is_call else strike < spot
    text = "虚值" if out_of_money else "实值"
    return text, levels, strike / spot - 1.0


def exit_price_for_marker(row: pd.Series) -> float:
    points = parse_exit_points(row)
    prices = [safe_float(point.get("price")) for point in points]
    clean = [x for x in prices if x is not None]
    return clean[-1] if clean else safe_float(row.get("exit_price_2"), 0.0) or 0.0


def build_items() -> list[dict[str, Any]]:
    details = pd.read_csv(DETAILS_CSV, parse_dates=["entry_time", "exit_time", "max_intraday_time", "min_intraday_time"])
    trades = pd.read_csv(TRADES_CSV, parse_dates=["entry_time", "exit_time"])
    merged = details.merge(
        trades[
            [
                "trade_date",
                "entry_time",
                "contract_id",
                "etf_close",
                "etf15_close",
                "entry_option_volume_15m",
                "cum_volume",
                "opening_high",
                "opening_low",
                "breakout_time",
                "breakout_vol_ratio",
                "selection_score",
            ]
        ],
        on=["trade_date", "entry_time", "contract_id"],
        how="left",
    )
    strike_grid = load_strike_grid()
    items: list[dict[str, Any]] = []
    for _, row in merged.sort_values("entry_time").iterrows():
        trade_date = str(row["trade_date"])
        direction = option_type(row["direction"])
        code = int(row["option_code"])
        option = read_option_1m(code, trade_date)
        etf = load_etf_15m(DEFAULT_SQLITE, ["588000"], trade_date, trade_date)
        entry_time = pd.Timestamp(row["entry_time"])
        exit_time = pd.Timestamp(row["exit_time"])
        strike = parse_strike(row.get("contract_id"), row.get("contract_symbol"))
        spot = safe_float(row.get("etf_close")) or safe_float(row.get("etf15_close"))
        if spot is None and not etf.empty:
            before = etf[etf["datetime"] <= entry_time].tail(1)
            if not before.empty:
                spot = safe_float(before.iloc[0]["close"])
        label, levels, strike_gap = moneyness_label(
            direction=direction,
            strike=strike,
            spot=spot,
            strikes=strike_grid.get((trade_date, direction), []),
        )
        level_text = "0档" if levels == 0 else f"{levels}档" if levels is not None else "-"
        entry_window_volume = safe_float(row.get("entry_option_volume_15m"))
        if entry_window_volume is None:
            entry_window_volume = safe_float(row.get("volume15"))
        if entry_window_volume is None and not option.empty:
            start = entry_time - pd.Timedelta(minutes=14)
            window = option[(option["datetime"] >= start) & (option["datetime"] <= entry_time)]
            entry_window_volume = float(window["volume"].sum()) if not window.empty else None
        items.append(
            {
                "seq": int(row["seq"]),
                "date": trade_date,
                "direction": direction,
                "openReason": str(row["open_reason"]),
                "signal": str(row.get("signal_strength", "")),
                "contractId": str(row["contract_id"]),
                "symbol": str(row.get("contract_symbol", "")),
                "optionCode": code,
                "strike": round(strike, 4) if strike is not None else None,
                "spot": round(spot, 4) if spot is not None else None,
                "moneyness": label,
                "moneynessLevels": level_text,
                "strikeGapPct": round(strike_gap * 100, 2) if strike_gap is not None else None,
                "entryWindowVolume": int(entry_window_volume) if entry_window_volume is not None and not math.isnan(entry_window_volume) else None,
                "cumVolume": int(safe_float(row.get("cum_volume"), 0.0) or 0.0),
                "volumeSharePct": round(safe_float(row.get("volume_share_pct"), 0.0) or 0.0, 2),
                "positionPct": round((safe_float(row["position_pct"], 0.0) or 0.0) * 100.0, 1),
                "contracts": int(row["contracts"]),
                "entryX": entry_time.strftime("%Y-%m-%d %H:%M:%S"),
                "exitX": exit_time.strftime("%Y-%m-%d %H:%M:%S"),
                "entryTime": entry_time.strftime("%H:%M"),
                "exitTime": exit_time.strftime("%H:%M"),
                "entryFill": round(float(row["entry_fill"]), 6),
                "exitReason": str(row["exit_reason"]),
                "exitFills": str(row.get("exit_fills", "")),
                "exitPoints": parse_exit_points(row),
                "netPnl": round(float(row["net_pnl"]), 2),
                "returnPct": round(float(row["return_on_premium_pct"]), 2),
                "maxFloatPct": round(float(row["max_intraday_return_pct"]), 2),
                "minFloatPct": round(float(row["min_intraday_return_pct"]), 2),
                "givebackPct": round(float(row["giveback_from_max_pct"]), 2),
                "maxFloatTime": pd.Timestamp(row["max_intraday_time"]).strftime("%H:%M") if pd.notna(row["max_intraday_time"]) else "-",
                "capitalBefore": round(float(row["capital_before"]), 2),
                "capitalAfter": round(float(row["capital_after"]), 2),
                "dte": safe_float(row.get("dte")),
                "delta": round(safe_float(row.get("delta"), 0.0) or 0.0, 3),
                "iv": round(safe_float(row.get("iv"), 0.0) or 0.0, 3),
                "etf": compact_bars(etf),
                "option": compact_bars(option),
            }
        )
    return items


def write_html(items: list[dict[str, Any]]) -> None:
    payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    total_pnl = sum(item["netPnl"] for item in items)
    wins = sum(1 for item in items if item["netPnl"] > 0)
    rows = "\n".join(
        "<tr>"
        f"<td>{item['seq']}</td>"
        f"<td><a href='#trade-{item['seq']}'>{item['date']}</a></td>"
        f"<td>{item['direction'].upper()}</td>"
        f"<td>{item['symbol']}<br><span>{item['moneyness']} {item['moneynessLevels']}｜量 {item['entryWindowVolume']}</span></td>"
        f"<td>{item['entryTime']} → {item['exitTime']}</td>"
        f"<td>{item['returnPct']:.2f}%</td>"
        f"<td>{item['maxFloatPct']:.2f}%</td>"
        f"<td>{item['exitReason']}</td>"
        f"<td>{item['positionPct']:.1f}%</td>"
        f"<td>{item['netPnl']:.2f}</td>"
        "</tr>"
        for item in items
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>1453.19% 科创期权策略逐笔交易复盘</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: Canvas;
      --fg: CanvasText;
      --muted: color-mix(in srgb, CanvasText 62%, Canvas);
      --border: color-mix(in srgb, CanvasText 18%, Canvas);
      --card: color-mix(in srgb, CanvasText 4%, Canvas);
      --green: #0f9d58;
      --red: #d93025;
      --blue: #1a73e8;
      --orange: #f29900;
    }}
    body {{ margin: 0; padding: 22px; background: var(--bg); color: var(--fg); font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    h1 {{ font-size: 23px; margin: 0 0 8px; }}
    h2 {{ font-size: 17px; margin: 22px 0 8px; }}
    .subtitle {{ color: var(--muted); margin-bottom: 16px; }}
    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(155px, 1fr)); gap: 10px; margin: 14px 0 18px; }}
    .stat, .trade {{ border: 1px solid var(--border); background: var(--card); border-radius: 14px; }}
    .stat {{ padding: 10px; }}
    .label {{ color: var(--muted); font-size: 12px; }}
    .value {{ font-size: 18px; font-weight: 650; margin-top: 2px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 10px 0 18px; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid var(--border); padding: 7px 6px; text-align: right; vertical-align: top; }}
    th:nth-child(2), td:nth-child(2), th:nth-child(4), td:nth-child(4), th:nth-child(8), td:nth-child(8) {{ text-align: left; }}
    td span {{ color: var(--muted); font-size: 12px; }}
    a {{ color: var(--blue); text-decoration: none; }}
    .trade {{ padding: 14px; margin: 0 0 20px; }}
    .trade-header {{ display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; margin-bottom: 8px; }}
    .title {{ font-weight: 650; }}
    .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(142px, 1fr)); gap: 8px; margin: 10px 0; }}
    .metric {{ border: 1px solid var(--border); border-radius: 10px; padding: 8px; background: color-mix(in srgb, CanvasText 2%, Canvas); }}
    .metric .value {{ font-size: 15px; }}
    .plot {{ width: 100%; height: 640px; }}
  </style>
</head>
<body>
  <h1>1453.19% 科创期权策略逐笔交易复盘</h1>
  <div class="subtitle">包含 74 笔实际成交。每笔展示 ETF 15分钟走势、所买期权 1分钟走势、买卖点、合约平/虚/实状态、距离平值几档、入场窗口期权成交量。</div>
  <div class="stats">
    <div class="stat"><div class="label">交易笔数</div><div class="value">{len(items)}</div></div>
    <div class="stat"><div class="label">胜率</div><div class="value">{wins / len(items) * 100:.2f}%</div></div>
    <div class="stat"><div class="label">净利润</div><div class="value">{total_pnl:,.2f}</div></div>
    <div class="stat"><div class="label">收益率口径</div><div class="value">1453.19%</div></div>
  </div>
  <h2>交易索引</h2>
  <table>
    <thead>
      <tr><th>#</th><th>日期</th><th>方向</th><th>合约/档位/量</th><th>买卖时间</th><th>收益</th><th>最大浮盈</th><th>退出原因</th><th>仓位</th><th>净利润</th></tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
  <div id="root"></div>
  <script>
    const trades = {payload};
    const root = document.getElementById('root');
    const css = getComputedStyle(document.documentElement);
    const fg = css.getPropertyValue('--fg').trim();
    const green = css.getPropertyValue('--green').trim();
    const red = css.getPropertyValue('--red').trim();
    const blue = css.getPropertyValue('--blue').trim();
    const orange = css.getPropertyValue('--orange').trim();
    const border = css.getPropertyValue('--border').trim();
    function el(cls, html='') {{
      const x = document.createElement('div');
      x.className = cls;
      x.innerHTML = html;
      return x;
    }}
    function metric(label, value) {{
      return `<div class="metric"><div class="label">${{label}}</div><div class="value">${{value ?? '-'}}</div></div>`;
    }}
    function money(x) {{ return Number(x).toLocaleString(undefined, {{maximumFractionDigits:2}}); }}
    function renderTrade(t) {{
      const card = el('trade');
      card.id = `trade-${{t.seq}}`;
      const pnlColor = t.netPnl >= 0 ? green : red;
      card.appendChild(el('trade-header',
        `<div class="title">${{t.seq}}. ${{t.date}} ${{t.direction.toUpperCase()}}　${{t.symbol}}（${{t.contractId}}）</div>` +
        `<div style="color:${{pnlColor}};font-weight:650">净利润 ${{money(t.netPnl)}}｜收益 ${{t.returnPct}}%</div>`
      ));
      card.appendChild(el('metrics',
        metric('买入合约状态', `${{t.moneyness}} ${{t.moneynessLevels}} ｜ 行权价 ${{t.strike}} ｜ ETF ${{t.spot}}`) +
        metric('入场窗口成交量', `${{t.entryWindowVolume ?? '-'}} 张 ｜ 占比 ${{t.volumeSharePct}}%`) +
        metric('买入 / 卖出', `${{t.entryTime}} @ ${{t.entryFill}} → ${{t.exitTime}}`) +
        metric('开仓理由', t.openReason) +
        metric('平仓理由', t.exitReason) +
        metric('仓位 / 张数', `${{t.positionPct}}% / ${{t.contracts}}张`) +
        metric('最大浮盈', `${{t.maxFloatPct}}% @ ${{t.maxFloatTime}}`) +
        metric('最大浮亏 / 回吐', `${{t.minFloatPct}}% / ${{t.givebackPct}}%`) +
        metric('Delta / IV / DTE', `${{t.delta}} / ${{t.iv}} / ${{t.dte ?? '-'}}`) +
        metric('资金变化', `${{money(t.capitalBefore)}} → ${{money(t.capitalAfter)}}`)
      ));
      const plot = el('plot');
      plot.id = `plot-${{t.seq}}`;
      card.appendChild(plot);
      root.appendChild(card);
      const traces = [
        {{type:'candlestick', name:'ETF 588000(15m)', x:t.etf.x, open:t.etf.open, high:t.etf.high, low:t.etf.low, close:t.etf.close, increasing:{{line:{{color:green}}}}, decreasing:{{line:{{color:red}}}}, xaxis:'x', yaxis:'y'}},
        {{type:'bar', name:'ETF成交量', x:t.etf.x, y:t.etf.volume, marker:{{color:'rgba(26,115,232,0.22)'}}, xaxis:'x', yaxis:'y2'}},
        {{type:'candlestick', name:'买入期权(1m)', x:t.option.x, open:t.option.open, high:t.option.high, low:t.option.low, close:t.option.close, increasing:{{line:{{color:green}}}}, decreasing:{{line:{{color:red}}}}, xaxis:'x2', yaxis:'y3'}},
        {{type:'bar', name:'期权成交量', x:t.option.x, y:t.option.volume, marker:{{color:'rgba(242,153,0,0.25)'}}, xaxis:'x2', yaxis:'y4'}},
        {{type:'scatter', mode:'markers+text', name:'买入', x:[t.entryX], y:[t.entryFill], text:['买'], textposition:'top center', marker:{{color:blue,size:10,symbol:'triangle-up'}}, xaxis:'x2', yaxis:'y3'}},
        {{type:'scatter', mode:'markers+text', name:'卖出', x:t.exitPoints.map(d=>d.x), y:t.exitPoints.map(d=>d.price), text:t.exitPoints.map(d=>d.quantity), textposition:'top center', marker:{{color:orange,size:10,symbol:'triangle-down'}}, xaxis:'x2', yaxis:'y3'}}
      ];
      const shapes = [
        {{type:'line', xref:'x', yref:'paper', x0:t.entryX, x1:t.entryX, y0:0, y1:1, line:{{color:blue,width:1.4,dash:'dot'}}}},
        {{type:'line', xref:'x', yref:'paper', x0:t.exitX, x1:t.exitX, y0:0, y1:1, line:{{color:orange,width:1.4,dash:'dot'}}}},
        {{type:'line', xref:'x2', yref:'paper', x0:t.entryX, x1:t.entryX, y0:0, y1:1, line:{{color:blue,width:1.4,dash:'dot'}}}},
        {{type:'line', xref:'x2', yref:'paper', x0:t.exitX, x1:t.exitX, y0:0, y1:1, line:{{color:orange,width:1.4,dash:'dot'}}}}
      ];
      const layout = {{
        paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)', font:{{color:fg}},
        margin:{{l:50,r:42,t:30,b:40}}, showlegend:true, legend:{{orientation:'h', x:0, y:1.08}},
        grid:{{rows:2, columns:1, pattern:'independent', roworder:'top to bottom'}},
        xaxis:{{domain:[0,1], type:'date', rangeslider:{{visible:false}}, showgrid:false, tickformat:'%H:%M'}},
        yaxis:{{domain:[0.62,1], title:'ETF价格', gridcolor:border}},
        yaxis2:{{domain:[0.62,0.76], overlaying:'y', side:'right', showgrid:false, title:'ETF量'}},
        xaxis2:{{domain:[0,1], type:'date', rangeslider:{{visible:false}}, showgrid:false, tickformat:'%H:%M'}},
        yaxis3:{{domain:[0,0.48], title:'期权价格', gridcolor:border}},
        yaxis4:{{domain:[0,0.18], overlaying:'y3', side:'right', showgrid:false, title:'期权量'}},
        shapes
      }};
      Plotly.newPlot(plot.id, traces, layout, {{responsive:true, displaylogo:false}});
    }}
    trades.forEach(renderTrade);
  </script>
</body>
</html>
"""
    OUTPUT_HTML.write_text(html, encoding="utf-8")


def main() -> None:
    items = build_items()
    write_html(items)
    print(OUTPUT_HTML)
    print("trades", len(items))
    print("wins", sum(1 for item in items if item["netPnl"] > 0))


if __name__ == "__main__":
    main()
