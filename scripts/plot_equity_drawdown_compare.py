#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build an HTML equity/drawdown comparison report for KCB strategy variants.

The report compares:
- the published 1759.55% curve from the saved capital audit;
- the 1032.98% curve reconstructed from the same trade audit with
  premium_cap=150000, volume_share_cap=5%, scope=all;
- three strategy-leg contribution curves.

No external charting dependency is used.  The output is a self-contained HTML
file with inline SVG charts.
"""

from __future__ import annotations

import csv
import html
import math
from datetime import datetime
from pathlib import Path
from string import Template


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
INITIAL_CAPITAL = 100000.0
SLIPPAGE_TICK = 0.0003
MULTIPLIER = 10000.0
FEE_PER_CONTRACT_PER_SIDE = 2.0

TRADES_1759 = RESEARCH / "putrev_selection_capacity_aware_momentum_to_20260723_trades.csv"
CAPITAL_1759 = RESEARCH / "putrev_selection_capacity_aware_momentum_to_20260723_capital.csv"
CAPITAL_1032 = RESEARCH / "premium_cap150000_share5_all_to_20260723_capital.csv"
HTML_OUT = RESEARCH / "equity_drawdown_compare_1759_1032_three_paths.html"


COLORS = {
    "1759.55%": "#2563eb",
    "1032.98%": "#dc2626",
    "早盘主策略": "#7c3aed",
    "强15分钟备用": "#059669",
    "09:45 Put反转": "#ea580c",
}


def safe_float(value: object, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return default
        return number
    except Exception:
        return default


def safe_int(value: object, default: int = 0) -> int:
    number = safe_float(value)
    if number is None:
        return default
    return int(number)


def parse_time(value: str) -> datetime:
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass
    raise ValueError("cannot parse time: %r" % value)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_legs(value: object) -> list[tuple[float, float]]:
    if not isinstance(value, str) or not value.strip():
        return []
    legs: list[tuple[float, float]] = []
    for part in value.split(";"):
        if "@" not in part:
            continue
        weight, price = part.split("@", 1)
        weight_f = safe_float(weight)
        price_f = safe_float(price)
        if weight_f is not None and price_f is not None:
            legs.append((weight_f, price_f))
    total = sum(weight for weight, _ in legs)
    if total <= 0:
        return []
    return [(weight / total, price) for weight, price in legs]


def leg_category(row: dict[str, object]) -> str:
    leg = str(row.get("strategy_leg", "")).lower()
    contract_id = str(row.get("contract_id", "")).upper()
    exit_reason = str(row.get("exit_reason", "")).lower()
    if "put_reversal" in leg or "p_rev" in contract_id or "putrev" in exit_reason:
        return "09:45 Put反转"
    if "opening" in leg:
        return "早盘主策略"
    return "强15分钟备用"


def build_1032_capital() -> list[dict[str, object]]:
    """Reconstruct the 1032.98% pressure-test curve and persist the audit CSV."""
    trades = sorted(read_csv(TRADES_1759), key=lambda r: (r.get("entry_time", ""), r.get("contract_id", "")))
    capital = INITIAL_CAPITAL
    rows: list[dict[str, object]] = []
    for trade in trades:
        entry_mid = safe_float(trade.get("entry_price"), 0.0) or 0.0
        entry_fill = entry_mid + SLIPPAGE_TICK
        position_pct = safe_float(trade.get("position_pct"), 0.0) or 0.0
        strategy_leg = str(trade.get("strategy_leg", ""))
        is_putrev = strategy_leg == "put_reversal_0945"
        budget = min(capital * position_pct, 150000.0)
        planned = int(budget // (entry_fill * MULTIPLIER)) if entry_fill > 0 else 0
        skip_reason = ""
        contracts = planned
        volume15 = safe_float(trade.get("volume15"), 0.0) or 0.0
        if planned <= 0:
            skip_reason = "small_budget"
            contracts = 0
        elif is_putrev and (volume15 <= 0 or planned > volume15 * 0.05):
            skip_reason = "capacity"
            contracts = 0

        premium = contracts * entry_fill * MULTIPLIER
        gross_sell = 0.0
        if contracts > 0:
            remaining = contracts
            legs = parse_legs(trade.get("exit_legs"))
            if not legs:
                exit_price = safe_float(trade.get("exit_price_2"))
                if exit_price is not None:
                    legs = [(1.0, exit_price)]
            for idx, (weight, mid) in enumerate(legs):
                qty = remaining if idx == len(legs) - 1 else min(remaining, int(round(contracts * weight)))
                remaining -= qty
                fill = max(mid - SLIPPAGE_TICK, 0.0)
                gross_sell += qty * fill * MULTIPLIER
        fee = contracts * FEE_PER_CONTRACT_PER_SIDE * 2.0
        net_pnl = gross_sell - premium - fee
        before = capital
        capital += net_pnl
        rows.append(
            {
                "trade_date": trade.get("trade_date", ""),
                "entry_time": trade.get("entry_time", ""),
                "direction": trade.get("direction", ""),
                "contract_id": trade.get("contract_id", ""),
                "strategy_leg": strategy_leg,
                "position_pct": position_pct,
                "entry_mid": entry_mid,
                "entry_fill": entry_fill,
                "contracts": contracts,
                "planned_contracts": planned,
                "volume15": volume15,
                "volume_share": contracts / volume15 if is_putrev and volume15 > 0 and contracts > 0 else "",
                "premium": premium,
                "fee": fee,
                "gross_pnl": gross_sell - premium,
                "net_pnl": net_pnl,
                "return_on_premium": net_pnl / premium if premium > 0 else "",
                "capital_before": before,
                "capital_after": capital,
                "exit_reason": trade.get("exit_reason", ""),
                "exit_legs": trade.get("exit_legs", ""),
                "skipped": bool(skip_reason),
                "skip_reason": skip_reason,
                "category": leg_category(trade),
            }
        )
    write_csv(CAPITAL_1032, rows, list(rows[0].keys()))
    return rows


def load_1759_capital() -> list[dict[str, object]]:
    trades = read_csv(TRADES_1759)
    trade_by_key = {
        (row.get("entry_time", ""), row.get("contract_id", "")): row
        for row in trades
    }
    rows: list[dict[str, object]] = []
    for row in read_csv(CAPITAL_1759):
        key = (row.get("entry_time", ""), row.get("contract_id", ""))
        trade = trade_by_key.get(key, {})
        merged: dict[str, object] = dict(row)
        merged["strategy_leg"] = trade.get("strategy_leg", "")
        merged["category"] = leg_category(merged)
        rows.append(merged)
    return rows


def active_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    output = []
    for row in rows:
        skipped = str(row.get("skipped", "")).lower() == "true"
        contracts = safe_int(row.get("contracts"))
        if not skipped and contracts > 0:
            output.append(row)
    return output


def equity_points(rows: list[dict[str, object]], label: str) -> list[dict[str, object]]:
    points = [{"time": parse_time(rows[0]["entry_time"]) if rows else datetime(2023, 1, 1), "equity": INITIAL_CAPITAL, "label": label}]
    for row in rows:
        cap = safe_float(row.get("capital_after"))
        if cap is None:
            continue
        points.append({"time": parse_time(str(row.get("entry_time"))), "equity": cap, "label": label})
    return points


def drawdown_points(points: list[dict[str, object]], label: str) -> list[dict[str, object]]:
    peak = None
    output = []
    for point in points:
        value = float(point["equity"])
        if peak is None or value > peak:
            peak = value
        dd = 0.0 if not peak else (value / peak - 1.0) * 100.0
        output.append({"time": point["time"], "equity": dd, "label": label})
    return output


def return_points(points: list[dict[str, object]], label: str) -> list[dict[str, object]]:
    output = []
    for point in points:
        value = float(point["equity"])
        output.append({"time": point["time"], "equity": (value / INITIAL_CAPITAL - 1.0) * 100.0, "label": label})
    return output


def contribution_points(rows: list[dict[str, object]], category: str) -> list[dict[str, object]]:
    chosen = [row for row in active_rows(rows) if row.get("category") == category]
    chosen.sort(key=lambda row: (str(row.get("entry_time")), str(row.get("contract_id"))))
    start = parse_time(chosen[0]["entry_time"]) if chosen else datetime(2023, 1, 1)
    capital = INITIAL_CAPITAL
    points = [{"time": start, "equity": capital, "label": category}]
    for row in chosen:
        capital += safe_float(row.get("net_pnl"), 0.0) or 0.0
        points.append({"time": parse_time(str(row.get("entry_time"))), "equity": capital, "label": category})
    return points


def median(values: list[float]) -> float:
    clean = sorted(value for value in values if value is not None and math.isfinite(value))
    if not clean:
        return 0.0
    mid = len(clean) // 2
    if len(clean) % 2:
        return clean[mid]
    return (clean[mid - 1] + clean[mid]) / 2.0


def month_key(row: dict[str, object]) -> str:
    dt = parse_time(str(row.get("entry_time")))
    return dt.strftime("%Y-%m")


def month_datetime(month: str) -> datetime:
    return datetime.strptime(month + "-01", "%Y-%m-%d")


def deployed_pct(row: dict[str, object]) -> float:
    premium = safe_float(row.get("premium"), 0.0) or 0.0
    before = safe_float(row.get("capital_before"), 0.0) or 0.0
    return premium / before * 100.0 if before > 0 else 0.0


def monthly_groups(rows: list[dict[str, object]]) -> dict[tuple[str, str], list[dict[str, object]]]:
    groups: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in active_rows(rows):
        groups.setdefault((month_key(row), str(row.get("category", ""))), []).append(row)
    return groups


def monthly_table_rows(version: str, rows: list[dict[str, object]]) -> list[list[str]]:
    output = []
    groups = monthly_groups(rows)
    for month, category in sorted(groups):
        chosen = groups[(month, category)]
        config_pcts = [(safe_float(row.get("position_pct"), 0.0) or 0.0) * 100.0 for row in chosen]
        deployed_pcts = [deployed_pct(row) for row in chosen]
        premiums = [safe_float(row.get("premium"), 0.0) or 0.0 for row in chosen]
        contracts = [safe_float(row.get("contracts"), 0.0) or 0.0 for row in chosen]
        output.append(
            [
                html.escape(version),
                html.escape(month),
                html.escape(category),
                str(len(chosen)),
                fmt_pct(median(config_pcts)),
                fmt_pct(median(deployed_pcts)),
                fmt_money(median(premiums)),
                "{:.0f}".format(median(contracts)),
            ]
        )
    return output


def monthly_metric_points(rows: list[dict[str, object]], label: str, metric: str) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in active_rows(rows):
        grouped.setdefault(month_key(row), []).append(row)
    points = []
    for month in sorted(grouped):
        chosen = grouped[month]
        if metric == "count":
            value = float(len(chosen))
        elif metric == "median_deployed_pct":
            value = median([deployed_pct(row) for row in chosen])
        elif metric == "median_config_pct":
            value = median([(safe_float(row.get("position_pct"), 0.0) or 0.0) * 100.0 for row in chosen])
        else:
            value = median([safe_float(row.get("premium"), 0.0) or 0.0 for row in chosen])
        points.append({"time": month_datetime(month), "equity": value, "label": label})
    return points


def stats(rows: list[dict[str, object]], points: list[dict[str, object]]) -> dict[str, object]:
    active = active_rows(rows)
    pnls = [safe_float(row.get("net_pnl"), 0.0) or 0.0 for row in active]
    final = float(points[-1]["equity"]) if points else INITIAL_CAPITAL
    dds = drawdown_points(points, "")
    max_dd = min(float(row["equity"]) for row in dds) if dds else 0.0
    return {
        "final": final,
        "return_pct": (final / INITIAL_CAPITAL - 1.0) * 100.0,
        "trades": len(active),
        "wins": sum(1 for pnl in pnls if pnl > 0),
        "win_rate": sum(1 for pnl in pnls if pnl > 0) / len(pnls) * 100.0 if pnls else 0.0,
        "max_dd_pct": abs(max_dd),
        "net_pnl": sum(pnls),
        "skipped": len(rows) - len(active),
    }


def fmt_money(value: float) -> str:
    return "¥{:,.2f}".format(value)


def fmt_pct(value: float) -> str:
    return "{:.2f}%".format(value)


def nice_number(value: float) -> str:
    if abs(value) >= 1000000:
        return "{:.2f}M".format(value / 1000000.0)
    if abs(value) >= 1000:
        return "{:.0f}k".format(value / 1000.0)
    return "{:.0f}".format(value)


def svg_chart(
    title: str,
    series: list[tuple[str, list[dict[str, object]]]],
    height: int = 360,
    width: int = 1120,
    y_money: bool = False,
    y_pct: bool = False,
) -> str:
    all_points = [point for _, points in series for point in points]
    if not all_points:
        return ""
    min_time = min(point["time"] for point in all_points)
    max_time = max(point["time"] for point in all_points)
    min_x = min_time.timestamp()
    max_x = max_time.timestamp()
    if min_x == max_x:
        max_x = min_x + 1.0
    values = [float(point["equity"]) for point in all_points]
    min_y = min(values)
    max_y = max(values)
    pad_y = (max_y - min_y) * 0.08 or max(abs(max_y), 1.0) * 0.08
    min_y -= pad_y
    max_y += pad_y
    left, right, top, bottom = 82, 24, 38, 52
    plot_w = width - left - right
    plot_h = height - top - bottom

    def x_pos(dt: datetime) -> float:
        return left + (dt.timestamp() - min_x) / (max_x - min_x) * plot_w

    def y_pos(value: float) -> float:
        return top + (max_y - value) / (max_y - min_y) * plot_h

    def y_label(value: float) -> str:
        if y_money:
            return "¥" + nice_number(value)
        if y_pct:
            return "{:.1f}%".format(value)
        return nice_number(value)

    y_ticks = [min_y + (max_y - min_y) * i / 4.0 for i in range(5)]
    x_ticks = [min_time + (max_time - min_time) * i / 5 for i in range(6)]
    parts = [
        '<section class="chart-card">',
        '<h2>%s</h2>' % html.escape(title),
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="18" fill="#ffffff"/>',
    ]
    for tick in y_ticks:
        y = y_pos(tick)
        parts.append(f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" stroke="#e5e7eb" stroke-width="1"/>')
        parts.append(f'<text x="{left-10}" y="{y+4:.2f}" text-anchor="end" class="axis">{html.escape(y_label(tick))}</text>')
    for tick in x_ticks:
        x = x_pos(tick)
        parts.append(f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{height-bottom}" stroke="#f3f4f6" stroke-width="1"/>')
        parts.append(f'<text x="{x:.2f}" y="{height-20}" text-anchor="middle" class="axis">{tick.strftime("%Y-%m")}</text>')
    parts.append(f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#9ca3af"/>')
    parts.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#9ca3af"/>')

    legend_x = left
    for label, points in series:
        color = COLORS.get(label, "#111827")
        coords = " ".join(f'{x_pos(point["time"]):.2f},{y_pos(float(point["equity"])):.2f}' for point in points)
        parts.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>')
        last = points[-1]
        parts.append(f'<circle cx="{x_pos(last["time"]):.2f}" cy="{y_pos(float(last["equity"])):.2f}" r="3.5" fill="{color}"/>')
        parts.append(f'<rect x="{legend_x}" y="12" width="12" height="12" rx="3" fill="{color}"/>')
        parts.append(f'<text x="{legend_x+18}" y="23" class="legend">{html.escape(label)}</text>')
        legend_x += 150
    parts.extend(["</svg>", "</section>"])
    return "\n".join(parts)


def table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["<table>", "<thead><tr>"]
    out.extend("<th>%s</th>" % html.escape(h) for h in headers)
    out.append("</tr></thead><tbody>")
    for row in rows:
        out.append("<tr>" + "".join("<td>%s</td>" % cell for cell in row) + "</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def main() -> None:
    rows1759 = load_1759_capital()
    rows1032 = build_1032_capital()
    p1759 = equity_points(rows1759, "1759.55%")
    p1032 = equity_points(rows1032, "1032.98%")
    s1759 = stats(rows1759, p1759)
    s1032 = stats(rows1032, p1032)
    categories = ["早盘主策略", "强15分钟备用", "09:45 Put反转"]

    overview_rows = []
    for name, stat, source in [
        ("1759.55%", s1759, CAPITAL_1759.relative_to(ROOT).as_posix()),
        ("1032.98%", s1032, CAPITAL_1032.relative_to(ROOT).as_posix()),
    ]:
        overview_rows.append(
            [
                html.escape(name),
                fmt_money(float(stat["final"])),
                fmt_pct(float(stat["return_pct"])),
                str(stat["trades"]),
                fmt_pct(float(stat["win_rate"])),
                fmt_pct(float(stat["max_dd_pct"])),
                str(stat["skipped"]),
                "<code>%s</code>" % html.escape(source),
            ]
        )

    split_rows = []
    split_series_1759 = []
    split_dd_1759 = []
    split_series_1032 = []
    split_dd_1032 = []
    for category in categories:
        c1759 = contribution_points(rows1759, category)
        c1032 = contribution_points(rows1032, category)
        split_series_1759.append((category, c1759))
        split_dd_1759.append((category, drawdown_points(c1759, category)))
        split_series_1032.append((category, c1032))
        split_dd_1032.append((category, drawdown_points(c1032, category)))
        for version, points, source_rows in [("1759.55%", c1759, rows1759), ("1032.98%", c1032, rows1032)]:
            chosen = [row for row in active_rows(source_rows) if row.get("category") == category]
            pnls = [safe_float(row.get("net_pnl"), 0.0) or 0.0 for row in chosen]
            dd = drawdown_points(points, category)
            max_dd = abs(min(float(point["equity"]) for point in dd)) if dd else 0.0
            final = float(points[-1]["equity"]) if points else INITIAL_CAPITAL
            split_rows.append(
                [
                    html.escape(version),
                    html.escape(category),
                    fmt_money(final),
                    fmt_pct((final / INITIAL_CAPITAL - 1.0) * 100.0),
                    str(len(chosen)),
                    fmt_pct(sum(1 for pnl in pnls if pnl > 0) / len(pnls) * 100.0 if pnls else 0.0),
                    fmt_pct(max_dd),
                    fmt_money(sum(pnls)),
                ]
            )

    monthly_rows = []
    monthly_rows.extend(monthly_table_rows("1759.55%", rows1759))
    monthly_rows.extend(monthly_table_rows("1032.98%", rows1032))

    charts = [
        svg_chart("总累计收益率曲线：1759.55% vs 1032.98%", [("1759.55%", return_points(p1759, "1759.55%")), ("1032.98%", return_points(p1032, "1032.98%"))], y_pct=True),
        svg_chart("总回撤曲线：1759.55% vs 1032.98%", [("1759.55%", drawdown_points(p1759, "1759.55%")), ("1032.98%", drawdown_points(p1032, "1032.98%"))], y_pct=True),
        svg_chart("每月交易频次", [("1759.55%", monthly_metric_points(rows1759, "1759.55%", "count")), ("1032.98%", monthly_metric_points(rows1032, "1032.98%", "count"))]),
        svg_chart("每月实际使用仓位中位数", [("1759.55%", monthly_metric_points(rows1759, "1759.55%", "median_deployed_pct")), ("1032.98%", monthly_metric_points(rows1032, "1032.98%", "median_deployed_pct"))], y_pct=True),
        svg_chart("1759.55%：三类策略贡献收益率曲线", [(label, return_points(points, label)) for label, points in split_series_1759], y_pct=True),
        svg_chart("1759.55%：三类策略贡献回撤", split_dd_1759, y_pct=True),
        svg_chart("1032.98%：三类策略贡献收益率曲线", [(label, return_points(points, label)) for label, points in split_series_1032], y_pct=True),
        svg_chart("1032.98%：三类策略贡献回撤", split_dd_1032, y_pct=True),
    ]

    template = Template("""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KCB 策略权益/回撤对比</title>
<style>
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f8fafc; color: #111827; }
main { max-width: 1180px; margin: 0 auto; padding: 32px 24px 56px; }
h1 { font-size: 28px; margin: 0 0 8px; }
.sub { color: #64748b; margin-bottom: 24px; line-height: 1.7; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin: 18px 0 24px; }
.card { background: white; border: 1px solid #e5e7eb; border-radius: 18px; padding: 18px; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04); }
.metric { color: #64748b; font-size: 13px; }
.value { font-size: 26px; font-weight: 750; margin-top: 6px; }
.chart-card { background: white; border: 1px solid #e5e7eb; border-radius: 20px; padding: 16px; margin: 18px 0; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04); overflow-x: auto; }
.chart-card h2 { font-size: 18px; margin: 2px 0 12px; }
svg { width: 100%; min-width: 900px; height: auto; }
.axis { fill: #64748b; font-size: 12px; }
.legend { fill: #111827; font-size: 13px; font-weight: 650; }
table { width: 100%; border-collapse: collapse; background: white; border-radius: 16px; overflow: hidden; border: 1px solid #e5e7eb; margin: 14px 0 24px; }
th, td { padding: 10px 12px; border-bottom: 1px solid #e5e7eb; text-align: right; font-size: 13px; white-space: nowrap; }
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
th { background: #f1f5f9; color: #334155; font-weight: 700; }
code { background: #f1f5f9; border-radius: 6px; padding: 2px 5px; }
.note { background: #fffbeb; border: 1px solid #fde68a; border-radius: 16px; padding: 14px 16px; color: #92400e; line-height: 1.65; margin: 18px 0; }
</style>
</head>
<body>
<main>
<h1>KCB 期权策略权益曲线与回撤对比</h1>
<div class="sub">对比对象：1759.55% 版本、1032.98% 风控版本，以及三类策略腿：早盘主策略、强 15 分钟备用、09:45 Put 反转。生成时间：$generated_at。</div>
<div class="grid">
<div class="card"><div class="metric">1759.55% 最终权益</div><div class="value">$final_1759</div></div>
<div class="card"><div class="metric">1032.98% 最终权益</div><div class="value">$final_1032</div></div>
</div>
$charts
<h2>总体统计</h2>
$overview_table
<div class="note">说明：三类策略拆分图是“贡献曲线”，即从 100,000 起算，按该类别实际逐笔净盈亏累计，用来观察该类别的曲线形状和回撤压力；它不是重新按独立账户复利 sizing 后的独立回测。</div>
<h2>三类策略拆分统计</h2>
$split_table
<h2>每月交易频次与仓位中位数</h2>
$monthly_table
</main>
</body>
</html>
""")
    html_text = template.substitute(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        final_1759=fmt_money(float(s1759["final"])),
        final_1032=fmt_money(float(s1032["final"])),
        charts="\n".join(charts),
        overview_table=table(["版本", "最终权益", "总收益", "成交笔数", "胜率", "最大回撤", "跳过", "数据源"], overview_rows),
        split_table=table(["版本", "策略类别", "贡献终值", "贡献收益", "笔数", "胜率", "贡献最大回撤", "净盈亏"], split_rows),
        monthly_table=table(["版本", "月份", "策略类别", "交易次数", "配置仓位中位数", "实际使用仓位中位数", "权利金中位数", "合约数中位数"], monthly_rows),
    )
    HTML_OUT.write_text(html_text, encoding="utf-8")
    print("Wrote", HTML_OUT)
    print("Wrote", CAPITAL_1032)
    print("1759 final", s1759)
    print("1032 final", s1032)


if __name__ == "__main__":
    main()
