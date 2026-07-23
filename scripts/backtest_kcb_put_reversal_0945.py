#!/usr/bin/env python3
"""Backtest a broad KCB 09:45 Put reversal candidate.

The signal intentionally does not require the prior-5-day daily-volume share.
It tests whether an ETF early-rally + near-ATM Put candidate is useful as a
separate add-on path.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from backtest_kcb_put_flow_0945 import read_option_1m
from backtest_v02_recent_intraday import DEFAULT_SQLITE, load_etf_15m, simulate_exit


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = ROOT / "research"
EVENTS_CSV = RESEARCH_DIR / "kcb_option_flow_15m_events.csv"
BASE_TRADES_CSV = RESEARCH_DIR / "full_confirm_tp2_3p0_trades.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, default=EVENTS_CSV)
    parser.add_argument("--base-trades", type=Path, default=BASE_TRADES_CSV)
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    parser.add_argument("--etf-up-min", type=float, default=0.005)
    parser.add_argument("--delta-min", type=float, default=0.45)
    parser.add_argument("--delta-max", type=float, default=0.60)
    parser.add_argument("--position-pct", type=float, default=0.25)
    parser.add_argument("--min-option-price", type=float, default=0.005)
    parser.add_argument("--min-volume15", type=float, default=100.0)
    parser.add_argument("--slippage-tick", type=float, default=0.0001)
    parser.add_argument("--max-volume-share", type=float, default=None)
    parser.add_argument("--exit-strength", choices=["strong", "normal"], default="strong")
    parser.add_argument("--normal-tp2-factor", type=float, default=3.0)
    parser.add_argument("--strong-trailing-pct", type=float, default=0.20)
    parser.add_argument("--rank-by", choices=["volume15", "volume_share"], default="volume15")
    parser.add_argument("--output-prefix", default="put_reversal_0945")
    return parser.parse_args()


def choose_events(events: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    df = events.copy()
    df = df[
        (df["time"] == "09:45")
        & (df["option_type"] == "put")
        & (df["close"] >= args.min_option_price)
        & (df["volume15"] >= args.min_volume15)
        & (df["etf_intraday_return"] >= args.etf_up_min)
        & (df["delta"].abs() >= args.delta_min)
        & (df["delta"].abs() <= args.delta_max)
    ].copy()
    if df.empty:
        return df
    rank_col = "volume15" if args.rank_by == "volume15" else "volume15_to_prior5_daily"
    df[rank_col] = pd.to_numeric(df[rank_col], errors="coerce").fillna(-1)
    df = df.sort_values(["trade_date", rank_col], ascending=[True, False])
    return df.groupby("trade_date", as_index=False).first()


def build_trade_rows(events: pd.DataFrame, etf_15m: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    rows = []
    signal_strength = "strong_put_reversal_0945" if args.exit_strength == "strong" else "normal_put_reversal_0945"
    for _, event in events.iterrows():
        trade_date = str(event["trade_date"])
        entry_time = pd.Timestamp(f"{trade_date} 09:45:00")
        bars = read_option_1m(event["option_code"], trade_date)
        if bars.empty:
            continue
        entry_rows = bars[bars["datetime"] == entry_time]
        if entry_rows.empty:
            entry_rows = bars[bars["datetime"] <= entry_time].tail(1)
        if entry_rows.empty:
            continue
        entry_price = float(entry_rows.iloc[-1]["close"])
        day_etf = etf_15m[etf_15m["datetime"].dt.date == pd.Timestamp(trade_date).date()].copy()
        exit_info = simulate_exit(
            bars,
            day_etf,
            entry_time,
            entry_price,
            direction="put",
            signal_strength=signal_strength,
            strong_trailing_pct=args.strong_trailing_pct,
            normal_tp2_factor=args.normal_tp2_factor,
            soft_stop_pct=0.82,
            soft_stop_delay_minutes=0,
        )
        rows.append(
            {
                "trade_date": trade_date,
                "underlying_code": "588000",
                "direction": "put",
                "entry_time": entry_time,
                "option_code": int(event["option_code"]),
                "contract_id": f"588000P_REV_{int(event['option_code'])}",
                "contract_symbol": event.get("contract_symbol", ""),
                "entry_price": entry_price,
                "position_pct": args.position_pct,
                "signal_strength": signal_strength,
                "strategy_leg": "put_reversal_0945",
                "dte": event.get("dte", 0),
                "delta": event.get("delta", 0),
                "implied_volatility": event.get("iv", 0),
                "iv_rank_252": 0,
                "volume15": event.get("volume15", 0),
                "volume15_to_prior5_daily": event.get("volume15_to_prior5_daily", 0),
                "etf_intraday_return": event.get("etf_intraday_return", 0),
                "future_gain_eod": event.get("future_gain_eod", 0),
                "day_max_gain_from_open": event.get("day_max_gain_from_open", 0),
                "exit_time": exit_info.get("exit_time"),
                "exit_price_1": exit_info.get("exit_price_1"),
                "exit_price_2": exit_info.get("exit_price_2"),
                "return": exit_info.get("return"),
                "exit_reason": exit_info.get("exit_reason"),
                "exit_legs": exit_info.get("exit_legs"),
                "tp1_time": exit_info.get("tp1_time", pd.NaT),
                "high_water": exit_info.get("high_water", pd.NA),
                "trailing_stop": exit_info.get("trailing_stop", pd.NA),
            }
        )
    return pd.DataFrame(rows)


def scenario_suffix(args: argparse.Namespace) -> str:
    return (
        f"_etfup{args.etf_up_min:g}"
        f"_delta{args.delta_min:g}_{args.delta_max:g}"
        f"_pos{args.position_pct:g}"
        f"_{args.exit_strength}"
        f"_rank{args.rank_by}"
        f"_minp{args.min_option_price:g}"
        f"_minv{args.min_volume15:g}"
        f"_slip{args.slippage_tick:g}"
        + (f"_capshare{args.max_volume_share:g}" if args.max_volume_share is not None else "")
    )


def parse_exit_legs(value: object) -> list[tuple[float, float]]:
    if isinstance(value, str) and value.strip():
        legs: list[tuple[float, float]] = []
        for part in value.split(";"):
            if "@" not in part:
                continue
            weight, price = part.split("@", 1)
            legs.append((float(weight), float(price)))
        total = sum(weight for weight, _ in legs)
        if total > 0:
            return [(weight / total, price) for weight, price in legs]
    return []


def calc_capital(
    trades: pd.DataFrame,
    initial: float = 100000.0,
    contract_multiplier: float = 10000.0,
    fee_per_contract_side: float = 2.0,
    slippage_tick: float = 0.0001,
    max_volume_share: float | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    capital = initial
    rows: list[dict[str, Any]] = []
    for _, trade in trades.sort_values("entry_time").iterrows():
        entry_mid = float(trade["entry_price"])
        entry_fill = entry_mid + slippage_tick
        position_pct = float(trade.get("position_pct", 0.10))
        planned_contracts = int((capital * position_pct) // (entry_fill * contract_multiplier))
        is_addon = str(trade.get("strategy_leg", "")) == "put_reversal_0945"
        volume15 = float(trade.get("volume15", 0.0) or 0.0)
        volume_share = planned_contracts / volume15 if is_addon and volume15 > 0 else 0.0
        skipped = False
        skip_reason = ""
        if (
            is_addon
            and max_volume_share is not None
            and planned_contracts > 0
            and volume_share > max_volume_share
        ):
            skipped = True
            skip_reason = "capacity"
            contracts = 0
        else:
            contracts = planned_contracts

        premium = contracts * entry_fill * contract_multiplier
        gross_sell = 0.0
        exit_leg_text: list[str] = []
        if contracts > 0:
            legs = parse_exit_legs(trade.get("exit_legs"))
            if not legs:
                legs = [(1.0, float(trade["exit_price_2"]))]
            remaining = contracts
            for idx, (weight, mid_price) in enumerate(legs):
                if idx == len(legs) - 1:
                    leg_contracts = remaining
                else:
                    leg_contracts = min(remaining, int(round(contracts * weight)))
                remaining -= leg_contracts
                fill_price = max(mid_price - slippage_tick, 0.0)
                gross_sell += leg_contracts * fill_price * contract_multiplier
                exit_leg_text.append(f"{leg_contracts}@{fill_price:.6f}")
        fee = contracts * fee_per_contract_side * 2.0
        net_pnl = gross_sell - premium - fee
        capital_before = capital
        capital += net_pnl
        rows.append(
            {
                "trade_date": trade["trade_date"],
                "entry_time": trade["entry_time"],
                "direction": trade["direction"],
                "contract_id": trade["contract_id"],
                "position_pct": position_pct,
                "entry_mid": entry_mid,
                "entry_fill": entry_fill,
                "contracts": contracts,
                "planned_contracts": planned_contracts,
                "volume15": volume15,
                "volume_share": volume_share,
                "premium": premium,
                "fee": fee,
                "gross_pnl": gross_sell - premium,
                "net_pnl": net_pnl,
                "return_on_premium": net_pnl / premium if premium else 0.0,
                "capital_before": capital_before,
                "capital_after": capital,
                "exit_reason": trade.get("exit_reason", ""),
                "exit_legs": trade.get("exit_legs", ""),
                "exit_fills": ";".join(exit_leg_text),
                "skipped": skipped,
                "skip_reason": skip_reason,
            }
        )

    out = pd.DataFrame(rows)
    active = out[~out["skipped"].fillna(False)].copy() if not out.empty else out
    curve = pd.concat([pd.Series([initial]), out["capital_after"]], ignore_index=True) if not out.empty else pd.Series([initial])
    drawdown = (curve.cummax() - curve) / curve.cummax()
    summary = {
        "initial_capital": initial,
        "final_capital": capital,
        "net_pnl": capital - initial,
        "total_return": capital / initial - 1,
        "trades": int(len(active)),
        "skipped_trades": int(out["skipped"].fillna(False).sum()) if not out.empty else 0,
        "win_rate": float((active["net_pnl"] > 0).mean()) if not active.empty else 0.0,
        "max_drawdown": float(drawdown.max()),
        "max_volume_share": float(active["volume_share"].max()) if not active.empty else 0.0,
        "p90_volume_share": float(active["volume_share"].quantile(0.90)) if not active.empty else 0.0,
        "p95_volume_share": float(active["volume_share"].quantile(0.95)) if not active.empty else 0.0,
    }
    return out, summary


def main() -> None:
    args = parse_args()
    events = pd.read_csv(args.events)
    chosen = choose_events(events, args)
    if chosen.empty:
        raise SystemExit("No events selected")
    start = str(chosen["trade_date"].min())
    end = str(chosen["trade_date"].max())
    etf_15m = load_etf_15m(args.sqlite, ["588000"], start, end)
    trades = build_trade_rows(chosen, etf_15m, args)

    suffix = scenario_suffix(args)
    prefix = RESEARCH_DIR / args.output_prefix
    trades_path = Path(f"{prefix}{suffix}_trades.csv")
    capital_path = Path(f"{prefix}{suffix}_capital.csv")
    summary_path = Path(f"{prefix}{suffix}_summary.csv")
    combined_path = Path(f"{prefix}{suffix}_combined_trades.csv")
    combined_summary_path = Path(f"{prefix}{suffix}_combined_summary.csv")
    combined_capital_path = Path(f"{prefix}{suffix}_combined_capital.csv")

    trades.to_csv(trades_path, index=False)
    capital, summary = calc_capital(
        trades,
        slippage_tick=args.slippage_tick,
        max_volume_share=args.max_volume_share,
    )
    capital.to_csv(capital_path, index=False)
    pd.DataFrame([summary]).to_csv(summary_path, index=False)

    combined_summary = {}
    if args.base_trades.exists():
        base = pd.read_csv(args.base_trades, parse_dates=["entry_time", "exit_time"])
        base_dates = set(base["trade_date"].astype(str))
        add_on = trades[~trades["trade_date"].astype(str).isin(base_dates)].copy()
        combined = pd.concat([base, add_on], ignore_index=True, sort=False).sort_values("entry_time")
        combined.to_csv(combined_path, index=False)
        combined_capital, combined_summary = calc_capital(
            combined,
            slippage_tick=args.slippage_tick,
            max_volume_share=args.max_volume_share,
        )
        combined_capital.to_csv(combined_capital_path, index=False)
        combined_summary["addon_selected"] = int(len(trades))
        combined_summary["addon_after_same_day_skip"] = int(len(add_on))
        combined_summary["addon_same_day_skipped"] = int(len(trades) - len(add_on))
        pd.DataFrame([combined_summary]).to_csv(combined_summary_path, index=False)

    print("trades", trades_path)
    print(pd.DataFrame([summary]).to_string(index=False))
    if combined_summary:
        print("combined", combined_summary_path)
        print(pd.DataFrame([combined_summary]).to_string(index=False))


if __name__ == "__main__":
    main()
