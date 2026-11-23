#!/usr/bin/env python3
"""Generate a large SVG overview for the 549.60% dual-ETF option strategy."""

from __future__ import annotations

import csv
import datetime as dt
import html
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
START = dt.date(2024, 7, 1)
END = dt.date(2026, 6, 30)
WIDTH = 5600
HEIGHT = 5600
LEFT = 350
RIGHT = 210
PLOT_WIDTH = WIDTH - LEFT - RIGHT


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def date_value(text: str) -> dt.date:
    return dt.datetime.strptime(text[:10], "%Y-%m-%d").date()


def number(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def x_of(day: dt.date) -> float:
    total = (END - START).days
    return LEFT + (day - START).days / total * PLOT_WIDTH


def esc(value: object) -> str:
    return html.escape(str(value))


def line(x1: float, y1: float, x2: float, y2: float, stroke: str, width: float = 1, opacity: float = 1) -> str:
    return (
        f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
        f'stroke="{stroke}" stroke-width="{width}" opacity="{opacity}"/>'
    )


def text(x: float, y: float, value: object, size: int = 28, anchor: str = "start", fill: str = "#243447", weight: int = 400, rotate: float | None = None) -> str:
    transform = f' transform="rotate({rotate:.1f} {x:.2f} {y:.2f})"' if rotate is not None else ""
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" text-anchor="{anchor}" '
        f'fill="{fill}" font-weight="{weight}"{transform}>{esc(value)}</text>'
    )


def load_daily(path: Path, code: str) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for row in read_csv(path):
        if str(row.get("underlying_code", "")) != code:
            continue
        day = date_value(row["trade_date"])
        if START <= day <= END:
            output.append(
                {
                    "date": day,
                    "open": number(row.get("etf_open")),
                    "high": number(row.get("etf_high")),
                    "low": number(row.get("etf_low")),
                    "close": number(row.get("etf_close")),
                }
            )
    return sorted(output, key=lambda item: item["date"])


def month_ticks() -> list[dt.date]:
    ticks: list[dt.date] = []
    year, month = START.year, START.month
    while dt.date(year, month, 1) <= END:
        if month in (1, 3, 5, 7, 9, 11):
            ticks.append(dt.date(year, month, 1))
        month += 1
        if month == 13:
            year += 1
            month = 1
    return ticks


def panel_grid(y: float, height: float, low: float, high: float, title_value: str, ylabel: str) -> list[str]:
    items = [
        f'<rect x="{LEFT}" y="{y}" width="{PLOT_WIDTH}" height="{height}" fill="#ffffff" stroke="#c8d2dc" stroke-width="2"/>',
        text(LEFT, y - 38, title_value, 40, fill="#172b3a", weight=500),
        text(82, y + height / 2, ylabel, 31, anchor="middle", fill="#536779", rotate=-90),
    ]
    for idx in range(6):
        yy = y + height - idx / 5 * height
        value = low + idx / 5 * (high - low)
        items.append(line(LEFT, yy, LEFT + PLOT_WIDTH, yy, "#dfe6ec", 1.2))
        items.append(text(LEFT - 26, yy + 10, f"{value:,.3f}", 25, anchor="end", fill="#607486"))
    for tick in month_ticks():
        xx = x_of(tick)
        items.append(line(xx, y, xx, y + height, "#e7edf2", 1.1))
    return items


def candle_panel(rows: list[dict[str, object]], trades: list[dict[str, str]], y: float, height: float, title_value: str) -> list[str]:
    lows = [float(item["low"]) for item in rows]
    highs = [float(item["high"]) for item in rows]
    data_low, data_high = min(lows), max(highs)
    padding = (data_high - data_low) * 0.11
    low, high = data_low - padding, data_high + padding

    def py(value: float) -> float:
        return y + height - (value - low) / (high - low) * height

    items = panel_grid(y, height, low, high, title_value, "ETF价格（元）")
    candle_width = max(3.2, PLOT_WIDTH / max(len(rows), 1) * 0.52)
    by_date = {item["date"]: item for item in rows}
    for item in rows:
        xx = x_of(item["date"])
        open_value = float(item["open"])
        close_value = float(item["close"])
        color = "#d64b4b" if close_value >= open_value else "#169483"
        items.append(line(xx, py(float(item["high"])), xx, py(float(item["low"])), color, 2.1))
        top = min(py(open_value), py(close_value))
        body_height = max(abs(py(open_value) - py(close_value)), 2.2)
        items.append(
            f'<rect x="{xx - candle_width / 2:.2f}" y="{top:.2f}" width="{candle_width:.2f}" '
            f'height="{body_height:.2f}" fill="{color}" opacity="0.90"/>'
        )

    date_counts: dict[dt.date, int] = {}
    for index, trade in enumerate(trades):
        day = date_value(trade["trade_date"])
        bar = by_date.get(day)
        if bar is None:
            continue
        count = date_counts.get(day, 0)
        date_counts[day] = count + 1
        direction = str(trade["direction"]).lower()
        is_call = direction == "call"
        marker_color = "#c0392b" if is_call else "#167a9f"
        xx = x_of(day)
        marker_y = py(float(bar["low"]) - padding * 0.08) if is_call else py(float(bar["high"]) + padding * 0.08)
        if is_call:
            points = f"{xx:.1f},{marker_y - 20:.1f} {xx - 17:.1f},{marker_y + 14:.1f} {xx + 17:.1f},{marker_y + 14:.1f}"
        else:
            points = f"{xx:.1f},{marker_y + 20:.1f} {xx - 17:.1f},{marker_y - 14:.1f} {xx + 17:.1f},{marker_y - 14:.1f}"
        items.append(f'<polygon points="{points}" fill="{marker_color}" stroke="#ffffff" stroke-width="3"/>')
        day_return = number(trade.get("account_day_return")) * 100
        entry_time = str(trade.get("entry_time", ""))[11:16]
        label = f"{day:%m-%d} {entry_time} {'CALL' if is_call else 'PUT'} {day_return:+.1f}%"
        label_y = marker_y + (62 + count * 34 if is_call else -52 - count * 34)
        items.append(text(xx + 10, label_y, label, 22, fill=marker_color, weight=500, rotate=-28))
    return items


def capital_panel(dates: list[dt.date], values: list[float], y: float, height: float) -> list[str]:
    low = min(values) * 0.92
    high = max(values) * 1.06

    def py(value: float) -> float:
        return y + height - (value - low) / (high - low) * height

    items = panel_grid(y, height, low, high, "账户资产曲线", "账户资产（元）")
    points = " ".join(f"{x_of(day):.2f},{py(value):.2f}" for day, value in zip(dates, values))
    area = f"{LEFT},{y + height} {points} {LEFT + PLOT_WIDTH},{y + height}"
    items.append(f'<polygon points="{area}" fill="#4d78a8" opacity="0.10"/>')
    items.append(f'<polyline points="{points}" fill="none" stroke="#315f91" stroke-width="7" stroke-linejoin="round"/>')
    items.append(f'<circle cx="{x_of(dates[0]):.2f}" cy="{py(values[0]):.2f}" r="11" fill="#315f91"/>')
    items.append(f'<circle cx="{x_of(dates[-1]):.2f}" cy="{py(values[-1]):.2f}" r="14" fill="#c0392b"/>')
    items.append(text(x_of(dates[0]) + 18, py(values[0]) - 22, f"起始 {values[0]:,.0f}", 27, fill="#315f91", weight=500))
    items.append(text(x_of(dates[-1]) - 16, py(values[-1]) - 30, f"期末 {values[-1]:,.2f}", 30, anchor="end", fill="#c0392b", weight=500))
    return items


def main() -> None:
    kcb = load_daily(ROOT / "data" / "etf_daily_588000_588080.csv", "588000")
    cyb = load_daily(ROOT / "data" / "etf_daily_159915.csv", "159915")
    trades = read_csv(ROOT / "research" / "exp_cluster_put30_true_dual_trades.csv")
    capital = read_csv(ROOT / "research" / "exp_cluster_put30_true_dual_capital.csv")

    capital_by_date: dict[dt.date, float] = {}
    return_by_date: dict[dt.date, float] = {}
    for row in capital:
        day = date_value(row["trade_date"])
        capital_by_date[day] = number(row["capital_after_day"])
        before = number(row["capital_before_day"])
        return_by_date[day] = number(row["day_net_pnl"]) / before if before else 0.0
    for trade in trades:
        trade["account_day_return"] = str(return_by_date.get(date_value(trade["trade_date"]), 0.0))

    kcb_trades = [row for row in trades if str(row["underlying_code"]) == "588000"]
    cyb_trades = [row for row in trades if str(row["underlying_code"]) == "159915"]
    all_dates = sorted({item["date"] for item in kcb} | {item["date"] for item in cyb})
    asset_values: list[float] = []
    current = 100000.0
    for day in all_dates:
        if day in capital_by_date:
            current = capital_by_date[day]
        asset_values.append(current)

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        '<rect width="100%" height="100%" fill="#f7f9fb"/>',
        '<g font-family="PingFang SC, Microsoft YaHei, Arial Unicode MS, sans-serif">',
        text(WIDTH / 2, 82, "双创ETF期权日内策略：549.60%回测全景图", 58, anchor="middle", fill="#132b3a", weight=500),
        text(WIDTH / 2, 142, "2024-07-01 至 2026-06-30｜初始资金100,000元｜期末649,597.31元｜28笔｜胜率82.14%｜最大回撤13.21%", 30, anchor="middle", fill="#536779"),
        '<rect x="350" y="175" width="28" height="16" fill="#d64b4b"/>',
        text(390, 191, "上涨K线", 24, fill="#536779"),
        '<rect x="535" y="175" width="28" height="16" fill="#169483"/>',
        text(575, 191, "下跌K线", 24, fill="#536779"),
        '<polygon points="735,171 718,201 752,201" fill="#c0392b"/>',
        text(765, 194, "CALL开仓", 24, fill="#536779"),
        '<polygon points="940,202 923,172 957,172" fill="#167a9f"/>',
        text(970, 194, "PUT开仓", 24, fill="#536779"),
    ]
    svg.extend(candle_panel(kcb, kcb_trades, 270, 1370, "科创50 ETF（588000.SH）日K线与开仓标记"))
    svg.extend(candle_panel(cyb, cyb_trades, 1850, 1260, "创业板 ETF（159915.SZ）日K线与开仓标记"))
    svg.extend(capital_panel(all_dates, asset_values, 3340, 1500))
    for tick in month_ticks():
        xx = x_of(tick)
        svg.append(text(xx, 4920, f"{tick:%Y-%m}", 24, anchor="end", fill="#607486", rotate=-45))
    svg.append(text(WIDTH / 2, 5220, "回测时间", 32, anchor="middle", fill="#536779"))
    svg.append(text(WIDTH - RIGHT, 5480, "标注百分比为当日账户净收益（已含手续费与滑点）", 23, anchor="end", fill="#6c7f8f"))
    svg.extend(["</g>", "</svg>"])

    output = ROOT / "research" / "strategy_54960_kline_entries_equity.svg"
    output.write_text("\n".join(svg), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
