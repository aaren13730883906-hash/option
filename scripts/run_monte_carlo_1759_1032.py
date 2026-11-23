#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Monte Carlo robustness report for the KCB 1759.55% and 1032.98% curves."""

from __future__ import annotations

import html
import math
import random
from pathlib import Path
from statistics import mean
from string import Template

from plot_equity_drawdown_compare import (
    INITIAL_CAPITAL,
    RESEARCH,
    active_rows,
    build_1032_capital,
    fmt_money,
    fmt_pct,
    leg_category,
    load_1759_capital,
    month_key,
    safe_float,
    table,
)


SEED = 20260726
SIMS = 10000
OUT = RESEARCH / "monte_carlo_1759_1032.html"

CATEGORIES = ["早盘主策略", "强15分钟备用", "09:45 Put反转"]
COLORS = {
    "1759.55% P5": "#93c5fd",
    "1759.55% P50": "#2563eb",
    "1759.55% P95": "#1e3a8a",
    "1032.98% P5": "#fecaca",
    "1032.98% P50": "#dc2626",
    "1032.98% P95": "#7f1d1d",
}


def pctile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    clean = sorted(values)
    if len(clean) == 1:
        return clean[0]
    pos = (len(clean) - 1) * pct / 100.0
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return clean[lo]
    return clean[lo] * (hi - pos) + clean[hi] * (pos - lo)


def max_drawdown_from_equity(curve: list[float]) -> float:
    peak = curve[0]
    worst = 0.0
    for value in curve:
        if value > peak:
            peak = value
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst * 100.0


def row_return(row: dict[str, object]) -> float:
    before = safe_float(row.get("capital_before"), 0.0) or 0.0
    pnl = safe_float(row.get("net_pnl"), 0.0) or 0.0
    return pnl / before if before > 0 else 0.0


def row_premium_return_drag(row: dict[str, object]) -> float:
    before = safe_float(row.get("capital_before"), 0.0) or 0.0
    premium = safe_float(row.get("premium"), 0.0) or 0.0
    return premium / before if before > 0 else 0.0


def compound_curve(returns: list[float]) -> list[float]:
    equity = INITIAL_CAPITAL
    curve = [equity]
    for ret in returns:
        equity *= max(0.0, 1.0 + ret)
        curve.append(equity)
    return curve


def permuted_returns(base: list[dict[str, object]], rng: random.Random) -> list[float]:
    returns = [row_return(row) for row in base]
    rng.shuffle(returns)
    return returns


def bootstrap_returns(base: list[dict[str, object]], rng: random.Random) -> list[float]:
    return [row_return(rng.choice(base)) for _ in base]


def block_bootstrap_returns(base: list[dict[str, object]], rng: random.Random) -> list[float]:
    by_month: dict[str, list[dict[str, object]]] = {}
    for row in base:
        by_month.setdefault(month_key(row), []).append(row)
    months = sorted(by_month)
    output: list[float] = []
    while len(output) < len(base):
        month = rng.choice(months)
        output.extend(row_return(row) for row in by_month[month])
    return output[: len(base)]


def stress_returns(base: list[dict[str, object]], rng: random.Random) -> list[float]:
    output: list[float] = []
    for _ in base:
        row = rng.choice(base)
        ret = row_return(row)
        premium_drag = row_premium_return_drag(row)
        category = leg_category(row)
        if ret > 0 and rng.random() < 0.10:
            ret = 0.0
        if category == "09:45 Put反转" and rng.random() < 0.10:
            ret = 0.0
        ret -= premium_drag * 0.02
        output.append(ret)
    return output


def summarize(final_returns: list[float], drawdowns: list[float]) -> dict[str, float]:
    return {
        "ret_p5": pctile(final_returns, 5),
        "ret_p25": pctile(final_returns, 25),
        "ret_p50": pctile(final_returns, 50),
        "ret_p75": pctile(final_returns, 75),
        "ret_p95": pctile(final_returns, 95),
        "dd_p50": pctile(drawdowns, 50),
        "dd_p75": pctile(drawdowns, 75),
        "dd_p90": pctile(drawdowns, 90),
        "dd_p95": pctile(drawdowns, 95),
        "prob_loss": sum(1 for value in final_returns if value < 0.0) / len(final_returns) * 100.0,
        "prob_lt_300": sum(1 for value in final_returns if value < 300.0) / len(final_returns) * 100.0,
        "prob_lt_500": sum(1 for value in final_returns if value < 500.0) / len(final_returns) * 100.0,
        "prob_lt_1000": sum(1 for value in final_returns if value < 1000.0) / len(final_returns) * 100.0,
    }


def simulate(
    base: list[dict[str, object]],
    variant: str,
    version: str,
    make_returns,
    keep_paths: bool,
) -> dict[str, object]:
    final_returns: list[float] = []
    drawdowns: list[float] = []
    sampled_paths: list[list[float]] = []
    rng = random.Random("%s-%s-%s" % (SEED, version, variant))
    for _ in range(SIMS):
        returns = make_returns(base, rng)
        curve = compound_curve(returns)
        final_returns.append((curve[-1] / INITIAL_CAPITAL - 1.0) * 100.0)
        drawdowns.append(max_drawdown_from_equity(curve))
        if keep_paths:
            sampled_paths.append([(value / INITIAL_CAPITAL - 1.0) * 100.0 for value in curve])
    result = summarize(final_returns, drawdowns)
    result.update(
        {
            "variant": variant,
            "version": version,
            "n_trades": len(base),
            "mean_ret": mean(final_returns),
            "paths": path_quantiles(sampled_paths) if keep_paths else {},
        }
    )
    return result


def path_quantiles(paths: list[list[float]]) -> dict[str, list[float]]:
    if not paths:
        return {}
    length = len(paths[0])
    output = {"P5": [], "P50": [], "P95": []}
    for idx in range(length):
        values = [path[idx] for path in paths]
        output["P5"].append(pctile(values, 5))
        output["P50"].append(pctile(values, 50))
        output["P95"].append(pctile(values, 95))
    return output


def path_svg(title: str, left_paths: dict[str, list[float]], right_paths: dict[str, list[float]]) -> str:
    series: list[tuple[str, list[float]]] = []
    for q in ["P5", "P50", "P95"]:
        series.append(("1759.55% " + q, left_paths.get(q, [])))
    for q in ["P5", "P50", "P95"]:
        series.append(("1032.98% " + q, right_paths.get(q, [])))
    all_values = [v for _, values in series for v in values]
    if not all_values:
        return ""
    width, height = 1120, 390
    left, right, top, bottom = 72, 24, 40, 48
    plot_w = width - left - right
    plot_h = height - top - bottom
    min_y = min(all_values)
    max_y = max(all_values)
    pad = (max_y - min_y) * 0.08 or 10.0
    min_y -= pad
    max_y += pad
    max_len = max(len(values) for _, values in series if values)

    def x_pos(idx: int, n: int) -> float:
        if n <= 1:
            return left
        return left + idx / float(n - 1) * plot_w

    def y_pos(value: float) -> float:
        return top + (max_y - value) / (max_y - min_y) * plot_h

    parts = [
        '<section class="chart-card">',
        '<h2>%s</h2>' % html.escape(title),
        f'<svg viewBox="0 0 {width} {height}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="18" fill="#ffffff"/>',
    ]
    for i in range(5):
        value = min_y + (max_y - min_y) * i / 4
        y = y_pos(value)
        parts.append(f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" stroke="#e5e7eb"/>')
        parts.append(f'<text x="{left-10}" y="{y+4:.2f}" text-anchor="end" class="axis">{value:.0f}%</text>')
    for i in range(6):
        x = left + plot_w * i / 5
        step = int((max_len - 1) * i / 5)
        parts.append(f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{height-bottom}" stroke="#f3f4f6"/>')
        parts.append(f'<text x="{x:.2f}" y="{height-18}" text-anchor="middle" class="axis">{step}</text>')
    legend_x = left
    for label, values in series:
        if not values:
            continue
        color = COLORS.get(label, "#111827")
        stroke_width = "3.0" if "P50" in label else "1.8"
        opacity = "1.0" if "P50" in label else "0.72"
        coords = " ".join(f"{x_pos(i, len(values)):.2f},{y_pos(value):.2f}" for i, value in enumerate(values))
        parts.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="{stroke_width}" opacity="{opacity}" stroke-linecap="round" stroke-linejoin="round"/>')
        parts.append(f'<rect x="{legend_x}" y="12" width="12" height="12" rx="3" fill="{color}" opacity="{opacity}"/>')
        parts.append(f'<text x="{legend_x+18}" y="23" class="legend">{html.escape(label)}</text>')
        legend_x += 145
    parts.extend(["</svg>", "</section>"])
    return "\n".join(parts)


def risk_svg(title: str, rows: list[dict[str, object]]) -> str:
    width, height = 1120, 390
    left, right, top, bottom = 170, 26, 40, 42
    plot_w = width - left - right
    row_h = 28
    values = []
    labels = []
    for row in rows:
        label = "%s %s" % (row["version"], row["variant"])
        labels.append(label)
        values.append((float(row["dd_p50"]), float(row["dd_p90"]), float(row["dd_p95"])))
    max_x = max(v for triple in values for v in triple) * 1.12 if values else 1.0

    def x_pos(value: float) -> float:
        return left + value / max_x * plot_w

    parts = [
        '<section class="chart-card">',
        '<h2>%s</h2>' % html.escape(title),
        f'<svg viewBox="0 0 {width} {height}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="18" fill="#ffffff"/>',
    ]
    for i in range(6):
        value = max_x * i / 5
        x = x_pos(value)
        parts.append(f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{height-bottom}" stroke="#f3f4f6"/>')
        parts.append(f'<text x="{x:.2f}" y="{height-16}" text-anchor="middle" class="axis">{value:.1f}%</text>')
    for idx, (label, triple) in enumerate(zip(labels, values)):
        y = top + idx * row_h + 10
        p50, p90, p95 = triple
        color = "#2563eb" if label.startswith("1759") else "#dc2626"
        parts.append(f'<text x="{left-12}" y="{y+4}" text-anchor="end" class="axis">{html.escape(label)}</text>')
        parts.append(f'<line x1="{x_pos(p50):.2f}" y1="{y}" x2="{x_pos(p95):.2f}" y2="{y}" stroke="{color}" stroke-width="5" opacity="0.25"/>')
        parts.append(f'<line x1="{x_pos(p50):.2f}" y1="{y}" x2="{x_pos(p90):.2f}" y2="{y}" stroke="{color}" stroke-width="5" opacity="0.55"/>')
        parts.append(f'<circle cx="{x_pos(p50):.2f}" cy="{y}" r="5" fill="{color}"/>')
    parts.extend(["</svg>", "</section>"])
    return "\n".join(parts)


def fmt_num(value: float) -> str:
    return "{:.2f}".format(value)


def result_table(results: list[dict[str, object]]) -> str:
    rows = []
    for row in results:
        rows.append(
            [
                html.escape(str(row["version"])),
                html.escape(str(row["variant"])),
                str(row["n_trades"]),
                fmt_pct(float(row["ret_p5"])),
                fmt_pct(float(row["ret_p25"])),
                fmt_pct(float(row["ret_p50"])),
                fmt_pct(float(row["ret_p75"])),
                fmt_pct(float(row["ret_p95"])),
                fmt_pct(float(row["dd_p50"])),
                fmt_pct(float(row["dd_p90"])),
                fmt_pct(float(row["dd_p95"])),
                fmt_pct(float(row["prob_loss"])),
                fmt_pct(float(row["prob_lt_500"])),
                fmt_pct(float(row["prob_lt_1000"])),
            ]
        )
    return table(
        ["版本", "MC 类型", "笔数", "收益P5", "P25", "P50", "P75", "P95", "回撤P50", "P90", "P95", "亏本金概率", "收益<500%", "收益<1000%"],
        rows,
    )


def category_table(results: list[dict[str, object]]) -> str:
    rows = []
    for row in results:
        rows.append(
            [
                html.escape(str(row["version"])),
                html.escape(str(row["category"])),
                str(row["n_trades"]),
                fmt_pct(float(row["ret_p5"])),
                fmt_pct(float(row["ret_p50"])),
                fmt_pct(float(row["ret_p95"])),
                fmt_pct(float(row["dd_p50"])),
                fmt_pct(float(row["dd_p95"])),
                fmt_pct(float(row["prob_loss"])),
            ]
        )
    return table(["版本", "策略类别", "笔数", "收益P5", "收益P50", "收益P95", "回撤P50", "回撤P95", "亏本金概率"], rows)


def main() -> None:
    rows1759 = active_rows(load_1759_capital())
    rows1032 = active_rows(build_1032_capital())
    variants = [
        ("顺序重排", permuted_returns),
        ("逐笔Bootstrap", bootstrap_returns),
        ("按月BlockBootstrap", block_bootstrap_returns),
        ("压力扰动", stress_returns),
    ]

    results: list[dict[str, object]] = []
    path_left = {}
    path_right = {}
    for version, rows in [("1759.55%", rows1759), ("1032.98%", rows1032)]:
        for variant, maker in variants:
            keep_paths = variant == "逐笔Bootstrap"
            result = simulate(rows, variant, version, maker, keep_paths=keep_paths)
            results.append(result)
            if keep_paths and version == "1759.55%":
                path_left = result["paths"]
            if keep_paths and version == "1032.98%":
                path_right = result["paths"]

    cat_results: list[dict[str, object]] = []
    for version, rows in [("1759.55%", rows1759), ("1032.98%", rows1032)]:
        for category in CATEGORIES:
            chosen = [row for row in rows if leg_category(row) == category]
            if not chosen:
                continue
            result = simulate(chosen, "类别Bootstrap", version, bootstrap_returns, keep_paths=False)
            result["category"] = category
            cat_results.append(result)

    charts = "\n".join(
        [
            path_svg("逐笔 Bootstrap 收益率路径锥：P5 / P50 / P95", path_left, path_right),
            risk_svg("最大回撤分布：圆点=P50，深线=P90，浅线=P95", results),
        ]
    )
    best_note = ""
    stress_1032 = [row for row in results if row["version"] == "1032.98%" and row["variant"] == "压力扰动"][0]
    stress_1759 = [row for row in results if row["version"] == "1759.55%" and row["variant"] == "压力扰动"][0]
    best_note = (
        "压力扰动下，1759.55% 的收益中位数为 "
        + fmt_pct(float(stress_1759["ret_p50"]))
        + "、回撤P95为 "
        + fmt_pct(float(stress_1759["dd_p95"]))
        + "；1032.98% 的收益中位数为 "
        + fmt_pct(float(stress_1032["ret_p50"]))
        + "、回撤P95为 "
        + fmt_pct(float(stress_1032["dd_p95"]))
        + "。"
    )

    doc = Template("""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KCB Monte Carlo 鲁棒性测试</title>
<style>
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f8fafc; color: #111827; }
main { max-width: 1180px; margin: 0 auto; padding: 32px 24px 56px; }
h1 { font-size: 28px; margin: 0 0 8px; }
h2 { font-size: 18px; margin: 26px 0 12px; }
.sub { color: #64748b; margin-bottom: 18px; line-height: 1.7; }
.note { background: #ecfeff; border: 1px solid #a5f3fc; border-radius: 16px; padding: 14px 16px; color: #155e75; line-height: 1.65; margin: 18px 0; }
.warn { background: #fffbeb; border: 1px solid #fde68a; border-radius: 16px; padding: 14px 16px; color: #92400e; line-height: 1.65; margin: 18px 0; }
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
</style>
</head>
<body>
<main>
<h1>KCB 1759.55% / 1032.98% Monte Carlo 鲁棒性测试</h1>
<div class="sub">模拟次数：$sims；随机种子：$seed。收益率均以初始资金 100,000 计，回撤为模拟路径内最大回撤。</div>
<div class="note">$best_note</div>
<div class="warn">压力扰动口径：逐笔 bootstrap；盈利交易有 10% 概率视作没成交；09:45 Put 反转另有 10% 容量/成交跳过概率；每笔额外扣减 2% 权利金摩擦。这个口径是“安全边际压力测试”，不是预测。</div>
$charts
<h2>总策略 Monte Carlo 分布</h2>
$summary_table
<h2>三类策略腿 Bootstrap 分布</h2>
$category_table
</main>
</body>
</html>
""").substitute(
        sims=SIMS,
        seed=SEED,
        best_note=html.escape(best_note),
        charts=charts,
        summary_table=result_table(results),
        category_table=category_table(cat_results),
    )
    OUT.write_text(doc, encoding="utf-8")
    print("Wrote", OUT)
    for row in results:
        print(row["version"], row["variant"], "ret_p50", fmt_num(float(row["ret_p50"])), "dd_p95", fmt_num(float(row["dd_p95"])))


if __name__ == "__main__":
    main()
