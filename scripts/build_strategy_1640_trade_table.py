#!/usr/bin/env python3
"""Build a plain HTML trade-detail table for the 1640.73% KCB run."""

from __future__ import annotations

import html
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


RESEARCH_DIR = ROOT / "research"
TRADES_CSV = RESEARCH_DIR / "putrev_selection_capacity_aware_momentum_trades.csv"
CAPITAL_CSV = RESEARCH_DIR / "putrev_selection_capacity_aware_momentum_capital.csv"
SUMMARY_CSV = RESEARCH_DIR / "putrev_selection_capacity_aware_momentum_summary.csv"
OUTPUT_HTML = RESEARCH_DIR / "strategy_1640_73_trade_table.html"
OUTPUT_CSV = RESEARCH_DIR / "strategy_1640_73_trade_details.csv"


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or pd.isna(value) or value == "":
            return default
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return default
        return number
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    number = safe_float(value)
    if number is None:
        return default
    return int(number)


def pct(value: Any, digits: int = 2) -> str:
    number = safe_float(value)
    if number is None:
        return "-"
    return f"{number * 100:.{digits}f}%"


def money(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return "-"
    return f"{number:,.2f}"


def price(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return "-"
    return f"{number:.4f}"


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


def direction_text(value: Any) -> str:
    text = str(value).lower()
    return "Call" if text.startswith("call") else "Put"


def strategy_text(row: pd.Series) -> str:
    leg = str(row.get("strategy_leg", ""))
    signal = str(row.get("signal_strength", ""))
    if leg == "put_reversal_0945":
        return "09:45 Put反转"
    if "fallback" in signal or "fallback" in leg:
        return "15分钟备用"
    if "opening" in signal or "opening" in leg:
        return "早盘主策略"
    return leg or signal or "-"


def moneyness_label(row: pd.Series) -> tuple[str, str, float | None]:
    strike = parse_strike(row.get("contract_id"), row.get("contract_symbol"))
    spot = (
        safe_float(row.get("etf_close"))
        or safe_float(row.get("etf15_close"))
        or safe_float(row.get("etf15_close_real"))
    )
    if strike is None or spot is None or spot <= 0:
        return "-", "-", None
    step = 0.05
    atm = round(spot / step) * step
    levels = int(round(abs(strike - atm) / step))
    gap = strike / spot - 1.0
    if levels == 0 or abs(gap) <= 0.005:
        return "平值", "0档", gap
    is_call = direction_text(row.get("direction")) == "Call"
    out_of_money = strike > spot if is_call else strike < spot
    return ("虚值" if out_of_money else "实值"), f"{levels}档", gap


def option_intraday_stats(row: pd.Series) -> dict[str, Any]:
    option_code = safe_int(row.get("option_code"))
    trade_date = str(row.get("trade_date"))
    entry_time = pd.Timestamp(row.get("entry_time"))
    exit_time = pd.Timestamp(row.get("exit_time"))
    entry_fill = safe_float(row.get("entry_fill"))
    if option_code <= 0 or entry_fill is None:
        return {}
    try:
        bars = read_option_1m(option_code, trade_date)
    except Exception:
        return {}
    if bars.empty:
        return {}
    window = bars[(bars["datetime"] >= entry_time) & (bars["datetime"] <= exit_time)].copy()
    if window.empty:
        return {}
    high_idx = window["high"].idxmax()
    low_idx = window["low"].idxmin()
    max_price = float(window.loc[high_idx, "high"])
    min_price = float(window.loc[low_idx, "low"])
    max_return = max_price / entry_fill - 1.0
    min_return = min_price / entry_fill - 1.0
    bars_held = len(window)
    return {
        "max_intraday_price": max_price,
        "max_intraday_time": pd.Timestamp(window.loc[high_idx, "datetime"]),
        "max_intraday_return": max_return,
        "min_intraday_price": min_price,
        "min_intraday_time": pd.Timestamp(window.loc[low_idx, "datetime"]),
        "min_intraday_return": min_return,
        "bars_held": bars_held,
    }


def load_active_trades() -> pd.DataFrame:
    trades = pd.read_csv(TRADES_CSV, parse_dates=["entry_time", "exit_time"])
    capital = pd.read_csv(CAPITAL_CSV, parse_dates=["entry_time"])
    merged = trades.merge(
        capital[
            [
                "trade_date",
                "entry_time",
                "contract_id",
                "entry_mid",
                "entry_fill",
                "contracts",
                "planned_contracts",
                "volume_share",
                "premium",
                "fee",
                "gross_pnl",
                "net_pnl",
                "return_on_premium",
                "capital_before",
                "capital_after",
                "exit_fills",
                "skipped",
                "skip_reason",
            ]
        ],
        on=["trade_date", "entry_time", "contract_id"],
        how="left",
        suffixes=("", "_capital"),
    )
    active = merged[merged["skipped"].astype(str).str.lower() != "true"].copy()
    active = active.sort_values(["entry_time", "contract_id"]).reset_index(drop=True)
    active.insert(0, "seq", range(1, len(active) + 1))
    return active


def build_details() -> pd.DataFrame:
    active = load_active_trades()
    rows: list[dict[str, Any]] = []
    for _, row in active.iterrows():
        money_label, money_level, strike_gap = moneyness_label(row)
        stats = option_intraday_stats(row)
        entry_volume = (
            safe_float(row.get("event_volume15"))
            or safe_float(row.get("volume15"))
            or safe_float(row.get("entry_option_volume_15m"))
        )
        exit_time = pd.Timestamp(row["exit_time"]) if not pd.isna(row["exit_time"]) else pd.NaT
        max_time = stats.get("max_intraday_time")
        min_time = stats.get("min_intraday_time")
        rows.append(
            {
                "seq": safe_int(row["seq"]),
                "trade_date": str(row["trade_date"]),
                "path": strategy_text(row),
                "direction": direction_text(row.get("direction")),
                "signal": str(row.get("signal_strength", "")),
                "contract_id": str(row.get("contract_id", "")),
                "contract_symbol": str(row.get("contract_symbol", "")),
                "option_code": safe_int(row.get("option_code")),
                "moneyness": money_label,
                "moneyness_level": money_level,
                "strike_gap_pct": (strike_gap * 100.0 if strike_gap is not None else None),
                "dte": safe_int(row.get("dte")),
                "delta": safe_float(row.get("delta")),
                "iv": safe_float(row.get("iv")) or safe_float(row.get("implied_volatility")),
                "position_pct": safe_float(row.get("position_pct")),
                "planned_contracts": safe_int(row.get("planned_contracts")),
                "contracts": safe_int(row.get("contracts")),
                "entry_time": pd.Timestamp(row["entry_time"]).strftime("%Y-%m-%d %H:%M"),
                "entry_mid": safe_float(row.get("entry_mid")),
                "entry_fill": safe_float(row.get("entry_fill")),
                "exit_time": exit_time.strftime("%Y-%m-%d %H:%M") if not pd.isna(exit_time) else "",
                "exit_reason": str(row.get("exit_reason", "")),
                "exit_fills": str(row.get("exit_fills", "")),
                "premium": safe_float(row.get("premium")),
                "fee": safe_float(row.get("fee")),
                "gross_pnl": safe_float(row.get("gross_pnl")),
                "net_pnl": safe_float(row.get("net_pnl")),
                "return_on_premium": safe_float(row.get("return_on_premium")),
                "capital_before": safe_float(row.get("capital_before")),
                "capital_after": safe_float(row.get("capital_after")),
                "entry_volume15": entry_volume,
                "volume_share": safe_float(row.get("volume_share")),
                "capacity_selected_rank": safe_float(row.get("capacity_selected_rank")),
                "momentum15": safe_float(row.get("momentum15")),
                "etf_intraday_return": safe_float(row.get("etf_intraday_return")),
                "ma20_deviation_0945": safe_float(row.get("ma20_deviation_0945")),
                "max_intraday_price": stats.get("max_intraday_price"),
                "max_intraday_time": max_time.strftime("%Y-%m-%d %H:%M") if isinstance(max_time, pd.Timestamp) else "",
                "max_intraday_return": stats.get("max_intraday_return"),
                "min_intraday_price": stats.get("min_intraday_price"),
                "min_intraday_time": min_time.strftime("%Y-%m-%d %H:%M") if isinstance(min_time, pd.Timestamp) else "",
                "min_intraday_return": stats.get("min_intraday_return"),
                "bars_held": stats.get("bars_held"),
            }
        )
    return pd.DataFrame(rows)


def cell(value: Any, klass: str = "") -> str:
    return f'<td class="{klass}">{html.escape(str(value))}</td>'


def build_html(details: pd.DataFrame) -> str:
    summary = pd.read_csv(SUMMARY_CSV).iloc[0].to_dict()
    total_pnl = details["net_pnl"].sum()
    win_rate = (details["net_pnl"] > 0).mean() * 100.0
    path_counts = details.groupby("path")["seq"].count().to_dict()
    path_pnl = details.groupby("path")["net_pnl"].sum().to_dict()

    rows_html = []
    for _, row in details.iterrows():
        pnl = safe_float(row["net_pnl"], 0.0) or 0.0
        klass = "pos" if pnl > 0 else "neg" if pnl < 0 else ""
        rows_html.append(
            "<tr>"
            + cell(row["seq"])
            + cell(row["trade_date"])
            + cell(row["path"])
            + cell(row["direction"])
            + cell(row["contract_symbol"])
            + cell(row["contract_id"])
            + cell(f"{row['moneyness']} {row['moneyness_level']}")
            + cell("-" if pd.isna(row["strike_gap_pct"]) else f"{row['strike_gap_pct']:.2f}%")
            + cell(row["dte"])
            + cell("-" if pd.isna(row["delta"]) else f"{row['delta']:.3f}")
            + cell("-" if pd.isna(row["iv"]) else f"{row['iv']:.3f}")
            + cell(pct(row["position_pct"]))
            + cell(row["contracts"])
            + cell(row["entry_time"])
            + cell(price(row["entry_fill"]))
            + cell(row["exit_time"])
            + cell(row["exit_reason"])
            + cell(row["exit_fills"])
            + cell(money(row["premium"]))
            + cell(money(row["net_pnl"]), klass)
            + cell(pct(row["return_on_premium"]), klass)
            + cell(money(row["capital_before"]))
            + cell(money(row["capital_after"]))
            + cell("-" if pd.isna(row["entry_volume15"]) else f"{int(row['entry_volume15']):,}")
            + cell("-" if pd.isna(row["volume_share"]) else f"{row['volume_share'] * 100:.2f}%")
            + cell("-" if pd.isna(row["capacity_selected_rank"]) else f"{row['capacity_selected_rank']:.0f}")
            + cell("-" if pd.isna(row["momentum15"]) else f"{row['momentum15'] * 100:.2f}%")
            + cell("-" if pd.isna(row["etf_intraday_return"]) else f"{row['etf_intraday_return'] * 100:.2f}%")
            + cell("-" if pd.isna(row["ma20_deviation_0945"]) else f"{row['ma20_deviation_0945'] * 100:.2f}%")
            + cell("-" if pd.isna(row["max_intraday_return"]) else f"{row['max_intraday_return'] * 100:.2f}%")
            + cell(row["max_intraday_time"])
            + cell("-" if pd.isna(row["min_intraday_return"]) else f"{row['min_intraday_return'] * 100:.2f}%")
            + cell(row["min_intraday_time"])
            + "</tr>"
        )

    def card(title: str, value: str) -> str:
        return f'<div class="card"><div class="k">{html.escape(title)}</div><div class="v">{html.escape(value)}</div></div>'

    cards = [
        card("总收益率", f"{safe_float(summary.get('total_return_pct'), 0.0):.2f}%"),
        card("期末资金", money(summary.get("final_capital"))),
        card("成交笔数", str(len(details))),
        card("胜率", f"{win_rate:.2f}%"),
        card("最大回撤", f"{safe_float(summary.get('max_dd_pct'), 0.0):.2f}%"),
        card("净利润", money(total_pnl)),
        card("主/备用/Put反转", " / ".join(f"{k}:{path_counts[k]}" for k in sorted(path_counts))),
        card("路径净利润", "；".join(f"{k}:{path_pnl[k]:,.0f}" for k in sorted(path_pnl))),
    ]

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>1640.73% 科创期权策略交易明细</title>
<style>
body {{ margin: 28px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f7f8fb; color: #16181d; }}
h1 {{ margin-bottom: 8px; }}
.note {{ color: #5d6470; margin-bottom: 18px; }}
.cards {{ display: grid; grid-template-columns: repeat(4, minmax(180px, 1fr)); gap: 12px; margin: 18px 0 24px; }}
.card {{ background: white; border: 1px solid #dfe3ea; border-radius: 12px; padding: 14px 16px; }}
.k {{ color: #667085; font-size: 13px; }}
.v {{ font-size: 20px; font-weight: 700; margin-top: 5px; }}
.table-wrap {{ overflow: auto; border: 1px solid #dfe3ea; border-radius: 12px; background: white; }}
table {{ border-collapse: collapse; min-width: 3000px; width: 100%; font-size: 12px; }}
th, td {{ border-bottom: 1px solid #eef1f5; border-right: 1px solid #eef1f5; padding: 7px 8px; white-space: nowrap; text-align: right; }}
th {{ position: sticky; top: 0; background: #eef4ff; z-index: 1; color: #1f2937; }}
td:nth-child(2), td:nth-child(3), td:nth-child(5), td:nth-child(6), td:nth-child(7), td:nth-child(14), td:nth-child(16), td:nth-child(17), td:nth-child(18), td:nth-child(31), td:nth-child(33) {{ text-align: left; }}
.pos {{ color: #087443; font-weight: 700; }}
.neg {{ color: #b42318; font-weight: 700; }}
</style>
</head>
<body>
<h1>1640.73% 科创50ETF期权策略交易明细</h1>
<div class="note">口径：主策略 753.37% + 09:45 Put反转容量感知动量选合约；仅展示实际成交的 69 笔，跳过信号不混入交易列表。</div>
<div class="cards">{''.join(cards)}</div>
<div class="table-wrap">
<table>
<thead><tr>
<th>#</th><th>日期</th><th>路径</th><th>方向</th><th>合约名</th><th>合约ID</th><th>虚实值</th><th>行权价偏离</th><th>DTE</th><th>Delta</th><th>IV</th><th>仓位</th><th>张数</th><th>买入时间</th><th>买入价</th><th>卖出时间</th><th>平仓理由</th><th>卖出明细</th><th>权利金</th><th>净收益</th><th>权利金收益率</th><th>开仓前资金</th><th>平仓后资金</th><th>入场窗口成交量</th><th>成交量占比</th><th>动量候选排名</th><th>09:45期权动量</th><th>ETF早盘涨幅</th><th>MA20偏离</th><th>最大浮盈</th><th>最高时间</th><th>最大浮亏</th><th>最低时间</th>
</tr></thead>
<tbody>
{''.join(rows_html)}
</tbody>
</table>
</div>
</body>
</html>"""


def main() -> None:
    details = build_details()
    details.to_csv(OUTPUT_CSV, index=False)
    OUTPUT_HTML.write_text(build_html(details), encoding="utf-8")
    print(f"WROTE {OUTPUT_HTML}")
    print(f"WROTE {OUTPUT_CSV}")
    print(f"active_trades={len(details)} net_pnl={details['net_pnl'].sum():.2f}")


if __name__ == "__main__":
    main()
