#!/usr/bin/env python3
"""Create an HTML review page for the conservative KCB 09:45 Put reversal add-on."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

from backtest_kcb_put_flow_0945 import read_option_1m
from backtest_v02_recent_intraday import DEFAULT_SQLITE, load_etf_15m


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = ROOT / "research"
ETF_1M_DIR = ROOT / "data" / "etf_intraday_ifind"

PREFIX = (
    "put_reversal_0945_conservative20_cap5"
    "_etfup0.005_delta0.45_0.6_pos0.2_normal_rankvolume15"
    "_minp0.03_minv1000_slip0.0003_capshare0.05"
)
TRADES_CSV = RESEARCH_DIR / f"{PREFIX}_combined_trades.csv"
CAPITAL_CSV = RESEARCH_DIR / f"{PREFIX}_combined_capital.csv"
OUTPUT_HTML = RESEARCH_DIR / "put_reversal_0945_conservative20_trade_review.html"


def read_etf_bars(trade_date: str) -> tuple[pd.DataFrame, str]:
    path = ETF_1M_DIR / f"{trade_date}_588000_1m.csv"
    if path.exists():
        df = pd.read_csv(path)
        df["datetime"] = pd.to_datetime(df["datetime"])
        return df, "1m"
    df = load_etf_15m(DEFAULT_SQLITE, ["588000"], trade_date, trade_date)
    return df, "15m"


def parse_exit_points(row: pd.Series) -> list[dict[str, Any]]:
    text = str(row.get("exit_legs", ""))
    exit_dt = pd.Timestamp(row["exit_time"])
    exit_time = exit_dt.strftime("%H:%M")
    exit_x = exit_dt.strftime("%Y-%m-%d %H:%M:%S")
    points = []
    for part in text.split(";"):
        if "@" not in part:
            continue
        weight, price = part.split("@", 1)
        points.append(
            {
                "time": exit_time,
                "x": exit_x,
                "weight": float(weight),
                "price": float(price),
            }
        )
    if not points:
        points.append(
            {
                "time": exit_time,
                "x": exit_x,
                "weight": 1.0,
                "price": float(row["exit_price_2"]),
            }
        )
    return points


def compact_bars(df: pd.DataFrame) -> dict[str, list[Any]]:
    df = df.dropna(subset=["datetime", "open", "high", "low", "close"]).copy()
    return {
        "time": df["datetime"].dt.strftime("%H:%M").tolist(),
        "x": df["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist(),
        "open": [round(float(x), 6) for x in df["open"]],
        "high": [round(float(x), 6) for x in df["high"]],
        "low": [round(float(x), 6) for x in df["low"]],
        "close": [round(float(x), 6) for x in df["close"]],
        "volume": [float(x) for x in df.get("volume", pd.Series([0] * len(df)))],
    }


def pct(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except Exception:
        return ""


def load_review_items() -> list[dict[str, Any]]:
    trades = pd.read_csv(TRADES_CSV, parse_dates=["entry_time", "exit_time"])
    capital = pd.read_csv(CAPITAL_CSV, parse_dates=["entry_time"])
    addon = trades[trades["strategy_leg"].astype(str).eq("put_reversal_0945")].copy()
    cap_addon = capital[capital["contract_id"].astype(str).str.contains("P_REV", na=False)].copy()
    merged = addon.merge(
        cap_addon[
            [
                "trade_date",
                "entry_time",
                "contract_id",
                "contracts",
                "planned_contracts",
                "volume_share",
                "net_pnl",
                "return_on_premium",
                "capital_before",
                "capital_after",
                "skipped",
                "skip_reason",
                "exit_fills",
            ]
        ],
        on=["trade_date", "entry_time", "contract_id"],
        how="left",
    )
    merged = merged[~merged["skipped"].fillna(False)].copy()
    merged = merged.sort_values("entry_time")

    items: list[dict[str, Any]] = []
    for _, row in merged.iterrows():
        trade_date = str(row["trade_date"])
        option = read_option_1m(row["option_code"], trade_date)
        etf, etf_period = read_etf_bars(trade_date)
        entry_dt = pd.Timestamp(row["entry_time"])
        exit_dt = pd.Timestamp(row["exit_time"])
        entry_time = entry_dt.strftime("%H:%M")
        exit_time = exit_dt.strftime("%H:%M")
        entry_x = entry_dt.strftime("%Y-%m-%d %H:%M:%S")
        exit_x = exit_dt.strftime("%Y-%m-%d %H:%M:%S")
        option_entry = option[option["datetime"].dt.strftime("%H:%M") == entry_time]
        option_entry_price = (
            float(option_entry.iloc[-1]["close"])
            if not option_entry.empty
            else float(row["entry_price"])
        )
        etf_entry = etf[etf["datetime"].dt.strftime("%H:%M") == entry_time]
        etf_entry_close = float(etf_entry.iloc[-1]["close"]) if not etf_entry.empty else None
        etf_open = float(etf.iloc[0]["open"]) if not etf.empty else None
        option_after_entry = option[option["datetime"] >= pd.Timestamp(row["entry_time"])]
        max_gain_after_entry = (
            float(option_after_entry["high"].max()) / option_entry_price - 1.0
            if not option_after_entry.empty and option_entry_price > 0
            else None
        )

        items.append(
            {
                "date": trade_date,
                "code": int(row["option_code"]),
                "symbol": str(row.get("contract_symbol", "")),
                "entryTime": entry_time,
                "exitTime": exit_time,
                "entryX": entry_x,
                "exitX": exit_x,
                "entryPrice": round(float(row["entry_price"]), 6),
                "returnPct": round(float(row["return"]) * 100, 2),
                "returnOnPremiumPct": round(float(row["return_on_premium"]) * 100, 2),
                "maxGainAfterEntryPct": round(max_gain_after_entry * 100, 2)
                if max_gain_after_entry is not None
                else None,
                "exitReason": str(row["exit_reason"]),
                "exitLegs": parse_exit_points(row),
                "exitFills": str(row.get("exit_fills", "")),
                "positionPct": round(float(row["position_pct"]) * 100, 1),
                "contracts": int(row["contracts"]),
                "plannedContracts": int(row["planned_contracts"]),
                "netPnl": round(float(row["net_pnl"]), 2),
                "capitalBefore": round(float(row["capital_before"]), 2),
                "capitalAfter": round(float(row["capital_after"]), 2),
                "volumeSharePct": round(float(row["volume_share"]) * 100, 2),
                "volume15": int(float(row["volume15"])),
                "delta": round(float(row["delta"]), 3),
                "iv": round(float(row["implied_volatility"]), 3),
                "etfUpPct": round(float(row["etf_intraday_return"]) * 100, 2),
                "futureGainEodPct": round(float(row["future_gain_eod"]) * 100, 2),
                "dayMaxGainFromOpenPct": round(float(row["day_max_gain_from_open"]) * 100, 2),
                "etfEntryClose": round(etf_entry_close, 4) if etf_entry_close is not None else None,
                "etfOpen": round(etf_open, 4) if etf_open is not None else None,
                "etfPeriod": etf_period,
                "etf": compact_bars(etf),
                "option": compact_bars(option),
            }
        )
    return items


def write_html(items: list[dict[str, Any]]) -> None:
    wins = [item for item in items if item["netPnl"] > 0]
    losses = [item for item in items if item["netPnl"] <= 0]
    total_pnl = sum(item["netPnl"] for item in items)
    payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    rows_html = "\n".join(
        (
            "<tr>"
            f"<td>{i + 1}</td>"
            f"<td><a href='#trade-{i + 1}'>{item['date']}</a></td>"
            f"<td>{item['symbol']}<br><span>{item['code']}</span></td>"
            f"<td>{item['returnPct']:.2f}%</td>"
            f"<td>{item['returnOnPremiumPct']:.2f}%</td>"
            f"<td>{item['maxGainAfterEntryPct']:.2f}%</td>"
            f"<td>{item['exitReason']}</td>"
            f"<td>{item['volumeSharePct']:.2f}%</td>"
            f"<td>{item['netPnl']:.2f}</td>"
            "</tr>"
        )
        for i, item in enumerate(items)
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>科创 09:45 Put反转增强保守版交易复盘</title>
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
      padding: 22px;
      background: var(--bg);
      color: var(--fg);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    h1 {{ font-size: 22px; margin: 0 0 8px; }}
    h2 {{ font-size: 17px; margin: 22px 0 8px; }}
    .subtitle {{ color: var(--muted); margin-bottom: 16px; }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 10px;
      margin: 14px 0 18px;
    }}
    .stat, .trade {{
      border: 1px solid var(--border);
      background: var(--card);
      border-radius: 14px;
    }}
    .stat {{ padding: 10px; }}
    .label {{ color: var(--muted); font-size: 12px; }}
    .value {{ font-size: 18px; font-weight: 650; margin-top: 2px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 10px 0 18px; }}
    th, td {{ border-bottom: 1px solid var(--border); padding: 7px 6px; text-align: right; vertical-align: top; }}
    th:nth-child(2), td:nth-child(2), th:nth-child(3), td:nth-child(3), th:nth-child(7), td:nth-child(7) {{ text-align: left; }}
    td span {{ color: var(--muted); font-size: 12px; }}
    a {{ color: var(--blue); text-decoration: none; }}
    .trade {{ padding: 14px; margin: 0 0 20px; }}
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
    .metric .value {{ font-size: 15px; }}
    .plot {{ width: 100%; height: 640px; }}
  </style>
</head>
<body>
  <h1>科创 09:45 Put反转增强保守版交易复盘</h1>
  <div class="subtitle">只包含实际成交的增强 Put；规则为 20% 仓位、0.0003 滑点、最大成交量占比 5%。早期 ETF 图使用 15分钟线，2026-05-26 之后有本地 1分钟 ETF 数据。</div>
  <div class="stats">
    <div class="stat"><div class="label">增强成交笔数</div><div class="value">{len(items)}</div></div>
    <div class="stat"><div class="label">胜率</div><div class="value">{len(wins) / len(items) * 100:.2f}%</div></div>
    <div class="stat"><div class="label">增强净利润</div><div class="value">{total_pnl:,.2f}</div></div>
    <div class="stat"><div class="label">亏损笔数</div><div class="value">{len(losses)}</div></div>
  </div>
  <h2>交易列表</h2>
  <table>
    <thead>
      <tr><th>#</th><th>日期</th><th>合约</th><th>期权中价收益</th><th>实盘滑点后收益</th><th>入场后最大浮盈</th><th>退出</th><th>成交量占比</th><th>净利润</th></tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
  <div id="root"></div>
  <script>
    const trades = {payload};
    const root = document.getElementById('root');
    const css = getComputedStyle(document.documentElement);
    const fg = css.getPropertyValue('--fg').trim();
    const muted = css.getPropertyValue('--muted').trim();
    const green = css.getPropertyValue('--green').trim();
    const red = css.getPropertyValue('--red').trim();
    const blue = css.getPropertyValue('--blue').trim();
    const orange = css.getPropertyValue('--orange').trim();
    const border = css.getPropertyValue('--border').trim();

    function div(cls, html='') {{
      const el = document.createElement('div');
      el.className = cls;
      el.innerHTML = html;
      return el;
    }}
    function metric(label, value) {{
      return `<div class="metric"><div class="label">${{label}}</div><div class="value">${{value}}</div></div>`;
    }}
    function fmtMoney(x) {{ return Number(x).toLocaleString(undefined, {{maximumFractionDigits:2}}); }}
    function makeTrade(t, idx) {{
      const card = div('trade');
      card.id = `trade-${{idx + 1}}`;
      const retColor = t.netPnl >= 0 ? green : red;
      card.appendChild(div('trade-header',
        `<div class="title">${{idx + 1}}. ${{t.date}}　${{t.symbol}}（${{t.code}}）</div>` +
        `<div style="color:${{retColor}};font-weight:650">净利润 ${{fmtMoney(t.netPnl)}}，滑点后 ${{t.returnOnPremiumPct}}%</div>`
      ));
      card.appendChild(div('metrics',
        metric('入场 / 出场', `${{t.entryTime}} → ${{t.exitTime}}`) +
        metric('中价收益 / 最大浮盈', `${{t.returnPct}}% / ${{t.maxGainAfterEntryPct}}%`) +
        metric('退出原因', t.exitReason) +
        metric('张数 / 成交量占比', `${{t.contracts}} / ${{t.volumeSharePct}}%`) +
        metric('Delta / IV', `${{t.delta}} / ${{t.iv}}`) +
        metric('ETF早盘涨幅', `${{t.etfUpPct}}%`) +
        metric('当日期权最大涨幅', `${{t.dayMaxGainFromOpenPct}}%`) +
        metric('资金变化', `${{fmtMoney(t.capitalBefore)}} → ${{fmtMoney(t.capitalAfter)}}`)
      ));
      const plot = div('plot');
      plot.id = `plot-${{idx}}`;
      card.appendChild(plot);
      root.appendChild(card);

      const shapes = [
        {{type:'line', xref:'x', yref:'paper', x0:t.entryX, x1:t.entryX, y0:0, y1:1, line:{{color:blue,width:1.5,dash:'dot'}}}},
        {{type:'line', xref:'x', yref:'paper', x0:t.exitX, x1:t.exitX, y0:0, y1:1, line:{{color:orange,width:1.5,dash:'dot'}}}}
      ];
      const annotations = [
        {{xref:'x', yref:'paper', x:t.entryX, y:1.02, text:'买入', showarrow:false, font:{{color:blue}}}},
        {{xref:'x', yref:'paper', x:t.exitX, y:1.02, text:'卖出', showarrow:false, font:{{color:orange}}}}
      ];
      const traces = [
        {{
          type:'candlestick', name:`ETF 588000(${{t.etfPeriod}})`,
          x:t.etf.x, open:t.etf.open, high:t.etf.high, low:t.etf.low, close:t.etf.close,
          increasing:{{line:{{color:green}}}}, decreasing:{{line:{{color:red}}}},
          xaxis:'x', yaxis:'y'
        }},
        {{
          type:'bar', name:'ETF成交量',
          x:t.etf.x, y:t.etf.volume, marker:{{color:'rgba(26,115,232,0.20)'}},
          xaxis:'x', yaxis:'y2'
        }},
        {{
          type:'candlestick', name:'Put期权',
          x:t.option.x, open:t.option.open, high:t.option.high, low:t.option.low, close:t.option.close,
          increasing:{{line:{{color:green}}}}, decreasing:{{line:{{color:red}}}},
          xaxis:'x2', yaxis:'y3'
        }},
        {{
          type:'bar', name:'期权成交量',
          x:t.option.x, y:t.option.volume, marker:{{color:'rgba(242,153,0,0.24)'}},
          xaxis:'x2', yaxis:'y4'
        }},
        {{
          type:'scatter', mode:'markers+text', name:'买入点',
          x:[t.entryX], y:[t.entryPrice], text:['买'], textposition:'top center',
          marker:{{color:blue,size:10,symbol:'triangle-up'}}, xaxis:'x2', yaxis:'y3'
        }},
        {{
          type:'scatter', mode:'markers+text', name:'卖出腿',
          x:t.exitLegs.map(d=>d.x), y:t.exitLegs.map(d=>d.price),
          text:t.exitLegs.map(d=>`${{Math.round(d.weight*100)}}%`), textposition:'top center',
          marker:{{color:orange,size:10,symbol:'triangle-down'}}, xaxis:'x2', yaxis:'y3'
        }}
      ];
      const layout = {{
        paper_bgcolor:'rgba(0,0,0,0)',
        plot_bgcolor:'rgba(0,0,0,0)',
        font:{{color:fg}},
        margin:{{l:50,r:38,t:30,b:40}},
        showlegend:true,
        legend:{{orientation:'h', x:0, y:1.08}},
        grid:{{rows:2, columns:1, pattern:'independent', roworder:'top to bottom'}},
        xaxis:{{domain:[0,1], type:"date", rangeslider:{{visible:false}}, showgrid:false, tickformat:"%H:%M"}},
        yaxis:{{domain:[0.62,1], title:'ETF价格', gridcolor:border}},
        yaxis2:{{domain:[0.62,0.76], overlaying:'y', side:'right', showgrid:false, title:'ETF量'}},
        xaxis2:{{domain:[0,1], type:"date", rangeslider:{{visible:false}}, showgrid:false, tickformat:"%H:%M"}},
        yaxis3:{{domain:[0,0.48], title:'期权价格', gridcolor:border}},
        yaxis4:{{domain:[0,0.18], overlaying:'y3', side:'right', showgrid:false, title:'期权量'}},
        shapes,
        annotations
      }};
      Plotly.newPlot(plot.id, traces, layout, {{responsive:true, displaylogo:false}});
    }}
    trades.forEach(makeTrade);
  </script>
</body>
</html>
"""
    OUTPUT_HTML.write_text(html, encoding="utf-8")


def main() -> None:
    items = load_review_items()
    write_html(items)
    print(OUTPUT_HTML)
    print("trades", len(items))
    print("wins", sum(1 for item in items if item["netPnl"] > 0))
    print("losses", sum(1 for item in items if item["netPnl"] <= 0))


if __name__ == "__main__":
    main()
