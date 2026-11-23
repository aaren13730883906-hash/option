#!/usr/bin/env python3
"""Create an HTML review chart for KCB 09:45 Put-flow trades."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = ROOT / "research"
ETF_1M_DIR = ROOT / "data" / "etf_intraday_ifind"
FULL_KCB_1M_DIR = ROOT / "data" / "科创板 1 分钟数据（全）" / "华夏上证科创板50ETF"
TRADES_CSV = RESEARCH_DIR / "put_flow_0945_th0.1_pos0.35_etfup0.01_delta0.45_0.6_trades.csv"
OUTPUT_HTML = RESEARCH_DIR / "put_flow_0945_trade_review.html"


def read_option_1m(option_code: int | str, trade_date: str) -> pd.DataFrame:
    code = str(int(option_code))
    month = str(trade_date)[:7]
    csv_path = FULL_KCB_1M_DIR / month / f"SSE.{code}.csv"
    zip_path = FULL_KCB_1M_DIR / f"{month}.zip"
    if csv_path.exists():
        df = pd.read_csv(csv_path)
    elif zip_path.exists():
        member = f"SSE.{code}.csv"
        with zipfile.ZipFile(zip_path) as zf:
            candidates = [name for name in zf.namelist() if name.endswith(member)]
            if not candidates:
                raise FileNotFoundError(f"{member} not found in {zip_path}")
            with zf.open(candidates[0]) as handle:
                df = pd.read_csv(handle)
    else:
        raise FileNotFoundError(f"No option 1m file for {code} {trade_date}")
    df["datetime"] = pd.to_datetime(df["datetime"])
    day = pd.Timestamp(trade_date).date()
    df = df[df["datetime"].dt.date == day].copy()
    df["ema5"] = df["close"].ewm(span=5, adjust=False).mean()
    return df


def read_etf_1m(trade_date: str) -> pd.DataFrame:
    path = ETF_1M_DIR / f"{trade_date}_588000_1m.csv"
    df = pd.read_csv(path)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df


def parse_exit_points(row: pd.Series) -> list[dict[str, Any]]:
    text = str(row.get("exit_legs", ""))
    exit_time = pd.Timestamp(row["exit_time"])
    points = []
    for part in text.split(";"):
        if "@" not in part:
            continue
        weight, price = part.split("@", 1)
        points.append({"time": exit_time.strftime("%H:%M"), "weight": float(weight), "price": float(price)})
    return points


def compact_bars(df: pd.DataFrame) -> dict[str, list[Any]]:
    return {
        "time": df["datetime"].dt.strftime("%H:%M").tolist(),
        "open": [round(float(x), 6) for x in df["open"]],
        "high": [round(float(x), 6) for x in df["high"]],
        "low": [round(float(x), 6) for x in df["low"]],
        "close": [round(float(x), 6) for x in df["close"]],
        "volume": [float(x) for x in df["volume"]],
    }


def main() -> None:
    trades = pd.read_csv(TRADES_CSV, parse_dates=["entry_time", "exit_time"])
    items: list[dict[str, Any]] = []
    for _, row in trades.iterrows():
        trade_date = str(row["trade_date"])
        etf = read_etf_1m(trade_date)
        option = read_option_1m(row["option_code"], trade_date)
        entry_time = pd.Timestamp(row["entry_time"]).strftime("%H:%M")
        exit_time = pd.Timestamp(row["exit_time"]).strftime("%H:%M")
        etf_open = float(etf.iloc[0]["open"])
        etf_entry_row = etf[etf["datetime"].dt.strftime("%H:%M") == entry_time]
        etf_entry_close = float(etf_entry_row.iloc[-1]["close"]) if not etf_entry_row.empty else None
        items.append(
            {
                "date": trade_date,
                "code": int(row["option_code"]),
                "symbol": str(row.get("contract_symbol", "")),
                "entryTime": entry_time,
                "exitTime": exit_time,
                "entryPrice": round(float(row["entry_price"]), 6),
                "returnPct": round(float(row["return"]) * 100, 2),
                "exitReason": str(row["exit_reason"]),
                "exitLegs": parse_exit_points(row),
                "positionPct": round(float(row["position_pct"]) * 100, 1),
                "delta": round(float(row["delta"]), 3),
                "iv": round(float(row["implied_volatility"]), 3),
                "flowShare": round(float(row["volume15_to_prior5_daily"]) * 100, 1),
                "etfUp": round(float(row["etf_intraday_return"]) * 100, 2),
                "etfEntryClose": round(etf_entry_close, 4) if etf_entry_close is not None else None,
                "etfOpen": round(etf_open, 4),
                "etf": compact_bars(etf),
                "option": compact_bars(option),
            }
        )

    payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KCB 09:45 Put-flow trade review</title>
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
    body {{
      margin: 0;
      padding: 20px;
      background: var(--bg);
      color: var(--fg);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    h1 {{ font-size: 22px; margin: 0 0 8px; }}
    .subtitle {{ color: var(--muted); margin-bottom: 20px; }}
    .trade {{
      border: 1px solid var(--border);
      background: var(--card);
      border-radius: 14px;
      padding: 14px;
      margin: 0 0 18px;
    }}
    .trade-header {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 8px;
    }}
    .title {{ font-weight: 650; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 8px;
      margin: 10px 0;
    }}
    .metric {{
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 8px;
      background: color-mix(in srgb, CanvasText 2%, Canvas);
    }}
    .metric .label {{ color: var(--muted); font-size: 12px; }}
    .metric .value {{ font-size: 16px; font-weight: 650; margin-top: 2px; }}
    .plot {{ width: 100%; height: 560px; }}
  </style>
</head>
<body>
  <h1>科创 09:45 Put资金异动补充路径：5笔交易复盘</h1>
  <div class="subtitle">规则：09:45 Put，15分钟成交量/前5日日均量 ≥10%，ETF早盘涨幅 ≥1%，abs(delta) 0.45–0.60，仓位35%。</div>
  <div id="root"></div>
  <script>
    const trades = {payload};
    const root = document.getElementById('root');
    const css = getComputedStyle(document.documentElement);
    const fg = css.getPropertyValue('--fg').trim();
    const muted = css.getPropertyValue('--muted').trim();
    const border = css.getPropertyValue('--border').trim();
    const green = css.getPropertyValue('--green').trim();
    const red = css.getPropertyValue('--red').trim();
    const blue = css.getPropertyValue('--blue').trim();
    const orange = css.getPropertyValue('--orange').trim();

    function div(cls, html='') {{
      const el = document.createElement('div');
      el.className = cls;
      el.innerHTML = html;
      return el;
    }}
    function metric(label, value) {{
      return `<div class="metric"><div class="label">${{label}}</div><div class="value">${{value}}</div></div>`;
    }}
    function makeTrade(t, idx) {{
      const card = div('trade');
      const retColor = t.returnPct >= 0 ? green : red;
      card.appendChild(div('trade-header',
        `<div class="title">${{idx + 1}}. ${{t.date}}　${{t.symbol}}（${{t.code}}）</div>` +
        `<div style="color:${{retColor}};font-weight:650">收益 ${{t.returnPct}}%</div>`
      ));
      card.appendChild(div('metrics',
        metric('入场 / 出场', `${{t.entryTime}} → ${{t.exitTime}}`) +
        metric('期权入场价', t.entryPrice) +
        metric('退出原因', t.exitReason) +
        metric('仓位', `${{t.positionPct}}%`) +
        metric('Delta / IV', `${{t.delta}} / ${{t.iv}}`) +
        metric('15m量/5日日均量', `${{t.flowShare}}%`) +
        metric('ETF 09:45涨幅', `${{t.etfUp}}%`) +
        metric('ETF 开盘/入场', `${{t.etfOpen}} / ${{t.etfEntryClose}}`)
      ));
      const plot = div('plot');
      plot.id = `plot-${{idx}}`;
      card.appendChild(plot);
      root.appendChild(card);

      const shapes = [
        {{type:'line', xref:'x', yref:'paper', x0:t.entryTime, x1:t.entryTime, y0:0, y1:1, line:{{color:blue,width:1.5,dash:'dot'}}}},
        {{type:'line', xref:'x', yref:'paper', x0:t.exitTime, x1:t.exitTime, y0:0, y1:1, line:{{color:orange,width:1.5,dash:'dot'}}}}
      ];
      const annotations = [
        {{xref:'x', yref:'paper', x:t.entryTime, y:1.02, text:'买入', showarrow:false, font:{{color:blue}}}},
        {{xref:'x', yref:'paper', x:t.exitTime, y:1.02, text:'卖出', showarrow:false, font:{{color:orange}}}}
      ];
      const traces = [
        {{
          type:'candlestick', name:'ETF 588000',
          x:t.etf.time, open:t.etf.open, high:t.etf.high, low:t.etf.low, close:t.etf.close,
          increasing:{{line:{{color:green}}}}, decreasing:{{line:{{color:red}}}},
          xaxis:'x', yaxis:'y'
        }},
        {{
          type:'bar', name:'ETF成交量',
          x:t.etf.time, y:t.etf.volume, marker:{{color:'rgba(26,115,232,0.20)'}},
          xaxis:'x', yaxis:'y2'
        }},
        {{
          type:'candlestick', name:'Put期权',
          x:t.option.time, open:t.option.open, high:t.option.high, low:t.option.low, close:t.option.close,
          increasing:{{line:{{color:green}}}}, decreasing:{{line:{{color:red}}}},
          xaxis:'x2', yaxis:'y3'
        }},
        {{
          type:'bar', name:'期权成交量',
          x:t.option.time, y:t.option.volume, marker:{{color:'rgba(242,153,0,0.24)'}},
          xaxis:'x2', yaxis:'y4'
        }},
        {{
          type:'scatter', mode:'markers+text', name:'买入点',
          x:[t.entryTime], y:[t.entryPrice], text:['买'], textposition:'top center',
          marker:{{color:blue,size:10,symbol:'triangle-up'}}, xaxis:'x2', yaxis:'y3'
        }},
        {{
          type:'scatter', mode:'markers+text', name:'卖出腿',
          x:t.exitLegs.map(d=>d.time), y:t.exitLegs.map(d=>d.price),
          text:t.exitLegs.map(d=>`${{Math.round(d.weight*100)}}%`), textposition:'top center',
          marker:{{color:orange,size:10,symbol:'triangle-down'}}, xaxis:'x2', yaxis:'y3'
        }}
      ];
      const layout = {{
        paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)',
        font:{{color:fg}},
        margin:{{l:48,r:28,t:26,b:36}},
        showlegend:true,
        legend:{{orientation:'h', y:1.08, x:0}},
        grid:{{rows:2, columns:1, pattern:'independent', roworder:'top to bottom'}},
        xaxis:{{domain:[0,1], rangeslider:{{visible:false}}, showgrid:false, tickfont:{{color:muted}}}},
        yaxis:{{domain:[0.58,1], title:'ETF价格', gridcolor:border, zeroline:false}},
        yaxis2:{{domain:[0.58,1], overlaying:'y', side:'right', showgrid:false, title:'ETF量', tickfont:{{color:muted}}}},
        xaxis2:{{domain:[0,1], rangeslider:{{visible:false}}, showgrid:false, tickfont:{{color:muted}}}},
        yaxis3:{{domain:[0,0.42], title:'期权价格', gridcolor:border, zeroline:false}},
        yaxis4:{{domain:[0,0.42], overlaying:'y3', side:'right', showgrid:false, title:'期权量', tickfont:{{color:muted}}}},
        shapes, annotations
      }};
      Plotly.newPlot(plot, traces, layout, {{responsive:true, displayModeBar:false}});
    }}
    trades.forEach(makeTrade);
  </script>
</body>
</html>
"""
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(OUTPUT_HTML)


if __name__ == "__main__":
    main()
