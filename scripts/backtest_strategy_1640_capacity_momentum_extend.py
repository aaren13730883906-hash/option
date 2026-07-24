#!/usr/bin/env python3
"""Extend the 1640.73% KCB strategy with capacity-aware Put-reversal trades."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

import backtest_v02_recent_intraday as bt
from backtest_v02_recent_intraday import DEFAULT_SQLITE, load_etf_15m, simulate_exit


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
BASE_TRADES = RESEARCH / "putrev_selection_capacity_aware_momentum_trades.csv"
BASE_CAPITAL = RESEARCH / "putrev_selection_capacity_aware_momentum_capital.csv"
EVENTS = RESEARCH / "kcb_option_flow_15m_events.csv"
DAILY = ROOT / "data" / "etf_daily_588000_588080.csv"

OUT_PREFIX = RESEARCH / "putrev_selection_capacity_aware_momentum_to_20260723"


def read_option_1m(option_code: int | str, trade_date: str) -> pd.DataFrame:
    code = str(int(option_code)).zfill(8)
    cache = bt.INTRADAY_CACHE / f"{trade_date}_{code}_1m.csv"
    if cache.exists():
        df = pd.read_csv(cache, parse_dates=["datetime"], dtype={"option_code": str})
        if "ema5" not in df:
            df["ema5"] = df["close"].ewm(span=5, adjust=False).mean()
        return df
    from backtest_kcb_put_flow_0945 import read_option_1m as read_full_option_1m

    return read_full_option_1m(option_code, trade_date)


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or pd.isna(value):
            return default
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return default
        return number
    except Exception:
        return default


def load_prev_ma20() -> pd.DataFrame:
    daily = pd.read_csv(DAILY, dtype={"underlying_code": str})
    daily = daily[daily["underlying_code"].eq("588000")].copy()
    daily["trade_date"] = pd.to_datetime(daily["trade_date"])
    daily = daily.sort_values("trade_date")
    daily["prev_ma20"] = daily["etf_close"].rolling(20).mean().shift(1)
    return daily[["trade_date", "prev_ma20"]]


def option_price_at_or_before(option_code: int, trade_date: str, end_time: pd.Timestamp, after: pd.Timestamp) -> tuple[pd.Timestamp, float] | None:
    bars = read_option_1m(option_code, trade_date)
    window = bars[(bars["datetime"] > after) & (bars["datetime"] <= end_time)].copy()
    if window.empty:
        return None
    row = window.iloc[-1]
    return pd.Timestamp(row["datetime"]), float(row["close"])


def apply_trend_quick_tp(row: pd.Series) -> pd.Series:
    if not bool(row.get("above_prev_ma20_3pct", False)):
        return row
    entry = float(row["entry_price"])
    target = entry * 1.10
    trade_date = str(row["trade_date"])
    entry_time = pd.Timestamp(row["entry_time"])
    exit_time = pd.Timestamp(row["exit_time"])
    bars = read_option_1m(int(row["option_code"]), trade_date)
    path = bars[(bars["datetime"] > entry_time) & (bars["datetime"] <= exit_time)].copy()
    hit = path[path["high"] >= target]
    if hit.empty:
        return row
    first = hit.iloc[0]
    out = row.copy()
    out["exit_time"] = pd.Timestamp(first["datetime"])
    out["exit_price_1"] = target
    out["exit_price_2"] = target
    out["return"] = 0.10
    out["exit_reason"] = "trend_quick_tp_10%"
    out["exit_legs"] = f"1.0@{target:.6f}"
    out["tp1_time"] = pd.Timestamp(first["datetime"])
    out["exit_modified"] = True
    return out


def apply_early_no_follow(row: pd.Series) -> pd.Series:
    if str(row.get("direction", "")).lower() != "put":
        return row
    trade_date = str(row["trade_date"])
    entry = float(row["entry_price"])
    entry_time = pd.Timestamp(row["entry_time"])
    check_time = pd.Timestamp(f"{trade_date} 10:30:00")
    exit_time = pd.Timestamp(row["exit_time"])
    if entry_time >= check_time or exit_time <= check_time:
        return row
    bars = read_option_1m(int(row["option_code"]), trade_date)
    path = bars[(bars["datetime"] > entry_time) & (bars["datetime"] <= check_time)].copy()
    if path.empty:
        return row
    max_hi = float(path["high"].max())
    close_rows = path[path["datetime"] <= check_time].tail(1)
    if close_rows.empty:
        return row
    close = float(close_rows.iloc[-1]["close"])
    if max_hi < entry * 1.05 and close <= entry * 0.97:
        out = row.copy()
        out["exit_time"] = pd.Timestamp(close_rows.iloc[-1]["datetime"])
        out["exit_price_1"] = close
        out["exit_price_2"] = close
        out["return"] = close / entry - 1.0
        out["exit_reason"] = "early_no_follow_10:30_hi5%_cl-3%"
        out["exit_legs"] = f"1.0@{close:.6f}"
        out["early_exit_modified"] = True
        return out
    return row


def apply_putrev_eod_1445(row: pd.Series) -> pd.Series:
    if str(row.get("strategy_leg", "")) != "put_reversal_0945":
        return row
    reason = str(row.get("exit_reason", ""))
    if reason not in ["eod", "tp1_eod"]:
        return row
    trade_date = str(row["trade_date"])
    entry_time = pd.Timestamp(row["entry_time"])
    original_exit = pd.Timestamp(row["exit_time"])
    cutoff = pd.Timestamp(f"{trade_date} 14:45:00")
    if original_exit <= cutoff:
        return row
    forced = option_price_at_or_before(int(row["option_code"]), trade_date, cutoff, entry_time)
    if forced is None:
        return row
    forced_time, forced_price = forced
    out = row.copy()
    if reason == "tp1_eod":
        # Keep the original TP1 leg and move only the remaining runner.
        legs = str(row.get("exit_legs", "")).split(";")
        if legs and "@" in legs[0]:
            first = legs[0]
            out["exit_legs"] = f"{first};0.5@{forced_price:.6f}"
            try:
                _, p1 = first.split("@", 1)
                entry = float(row["entry_price"])
                out["return"] = 0.5 * (float(p1) / entry - 1.0) + 0.5 * (forced_price / entry - 1.0)
            except Exception:
                pass
        else:
            out["exit_legs"] = f"1.0@{forced_price:.6f}"
            out["return"] = forced_price / float(row["entry_price"]) - 1.0
        out["exit_reason"] = "tp1_eod_1445_putrev"
    else:
        out["exit_legs"] = f"1.0@{forced_price:.6f}"
        out["return"] = forced_price / float(row["entry_price"]) - 1.0
        out["exit_reason"] = "eod_1445_putrev"
    out["exit_time"] = forced_time
    out["exit_price_2"] = forced_price
    out["exit_modified"] = True
    return out


def parse_exit_legs(value: object) -> list[tuple[float, float]]:
    if not isinstance(value, str) or not value.strip():
        return []
    legs: list[tuple[float, float]] = []
    for part in value.split(";"):
        if "@" not in part:
            continue
        w, p = part.split("@", 1)
        legs.append((float(w), float(p)))
    total = sum(w for w, _ in legs)
    return [(w / total, p) for w, p in legs] if total > 0 else []


def capital_row(trade: pd.Series, capital: float, slippage_tick: float = 0.0003) -> tuple[dict[str, Any], float]:
    entry_mid = float(trade["entry_price"])
    entry_fill = entry_mid + slippage_tick
    position_pct = float(trade.get("position_pct", 0.20))
    planned = int((capital * position_pct) // (entry_fill * 10000.0))
    volume15 = float(trade.get("volume15", 0.0) or 0.0)
    share = planned / volume15 if volume15 > 0 else 0.0
    contracts = planned
    premium = contracts * entry_fill * 10000.0
    gross_sell = 0.0
    exit_fills: list[str] = []
    if contracts > 0:
        legs = parse_exit_legs(trade.get("exit_legs"))
        if not legs:
            legs = [(1.0, float(trade["exit_price_2"]))]
        remaining = contracts
        for idx, (weight, mid) in enumerate(legs):
            qty = remaining if idx == len(legs) - 1 else min(remaining, int(round(contracts * weight)))
            remaining -= qty
            fill = max(float(mid) - slippage_tick, 0.0)
            gross_sell += qty * fill * 10000.0
            exit_fills.append(f"{qty}@{fill:.6f}")
    fee = contracts * 2.0 * 2.0
    net = gross_sell - premium - fee
    before = capital
    after = capital + net
    return {
        "trade_date": trade["trade_date"],
        "entry_time": trade["entry_time"],
        "direction": trade["direction"],
        "contract_id": trade["contract_id"],
        "position_pct": position_pct,
        "entry_mid": entry_mid,
        "entry_fill": entry_fill,
        "contracts": contracts,
        "planned_contracts": planned,
        "volume15": volume15,
        "volume_share": share,
        "premium": premium,
        "fee": fee,
        "gross_pnl": gross_sell - premium,
        "net_pnl": net,
        "return_on_premium": net / premium if premium else 0.0,
        "capital_before": before,
        "capital_after": after,
        "exit_reason": trade.get("exit_reason", ""),
        "exit_legs": trade.get("exit_legs", ""),
        "exit_fills": ";".join(exit_fills),
        "skipped": False,
        "skip_reason": "",
    }, after


def build_candidate_trade(event: pd.Series, etf_15m: pd.DataFrame, ma20_map: dict[str, float]) -> pd.Series:
    trade_date = str(event["trade_date"])
    entry_time = pd.Timestamp(f"{trade_date} 09:45:00")
    bars = read_option_1m(int(event["option_code"]), trade_date)
    entry_rows = bars[bars["datetime"] == entry_time]
    if entry_rows.empty:
        entry_rows = bars[bars["datetime"] <= entry_time].tail(1)
    entry_price = float(entry_rows.iloc[-1]["close"])
    day_etf = etf_15m[etf_15m["datetime"].dt.date == pd.Timestamp(trade_date).date()].copy()
    exit_info = simulate_exit(
        bars,
        day_etf,
        entry_time,
        entry_price,
        direction="put",
        signal_strength="normal_put_reversal_0945",
        strong_trailing_pct=0.20,
        normal_tp2_factor=3.0,
        soft_stop_pct=0.82,
        soft_stop_delay_minutes=0,
    )
    row = pd.Series(
        {
            "trade_date": trade_date,
            "underlying_code": "588000",
            "direction": "put",
            "entry_time": entry_time,
            "option_code": int(event["option_code"]),
            "contract_id": f"588000P_REV_{int(event['option_code'])}",
            "contract_symbol": event.get("contract_symbol", ""),
            "entry_price": entry_price,
            "position_pct": 0.20,
            "signal_strength": "normal_put_reversal_0945",
            "strategy_leg": "put_reversal_0945",
            "dte": event.get("dte", 0),
            "delta": event.get("delta", 0),
            "implied_volatility": event.get("iv", 0),
            "iv": event.get("iv", 0),
            "iv_rank_252": 0,
            "volume15": event.get("volume15", 0),
            "volume15_to_prior5_daily": event.get("volume15_to_prior5_daily", 0),
            "etf_intraday_return": event.get("etf_intraday_return", 0),
            "future_gain_eod": event.get("future_gain_eod", 0),
            "day_max_gain_from_open": event.get("day_max_gain_from_open", 0),
            "prev_ma20": ma20_map.get(trade_date, math.nan),
            "etf15_close": event.get("etf15_close", math.nan),
            "ma20_deviation_0945": (
                float(event.get("etf15_close")) / ma20_map[trade_date] - 1.0
                if trade_date in ma20_map and ma20_map[trade_date] and pd.notna(event.get("etf15_close"))
                else math.nan
            ),
            "above_prev_ma20_3pct": (
                float(event.get("etf15_close")) >= ma20_map[trade_date] * 1.03
                if trade_date in ma20_map and ma20_map[trade_date] and pd.notna(event.get("etf15_close"))
                else False
            ),
            "momentum15": float(event.get("close")) / float(event.get("open")) - 1.0,
            "event_open": event.get("open"),
            "event_close": event.get("close"),
            "event_volume15": event.get("volume15"),
            "contract_symbol_event": event.get("contract_symbol", ""),
            "delta_event": event.get("delta", 0),
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
    row = apply_trend_quick_tp(row)
    row = apply_early_no_follow(row)
    row = apply_putrev_eod_1445(row)
    return row


def drawdown_from_capital(capital_rows: pd.DataFrame, initial: float = 100000.0) -> float:
    curve = pd.concat([pd.Series([initial]), capital_rows["capital_after"]], ignore_index=True)
    dd = (curve.cummax() - curve) / curve.cummax()
    return float(dd.max())


def main() -> None:
    base_trades = pd.read_csv(BASE_TRADES, parse_dates=["entry_time", "exit_time"])
    base_capital = pd.read_csv(BASE_CAPITAL, parse_dates=["entry_time"])
    rows = [row.to_dict() for _, row in base_trades.iterrows()]
    cap_rows = [row.to_dict() for _, row in base_capital.iterrows()]
    capital = float(base_capital.iloc[-1]["capital_after"])
    last_date = str(pd.to_datetime(base_trades["trade_date"]).max().date())

    events = pd.read_csv(EVENTS)
    events["trade_date"] = events["trade_date"].astype(str)
    future = events[
        (events["trade_date"] > last_date)
        & (events["time"] == "09:45")
        & (events["option_type"] == "put")
        & (pd.to_numeric(events["close"], errors="coerce") >= 0.03)
        & (pd.to_numeric(events["volume15"], errors="coerce") >= 1000)
        & (pd.to_numeric(events["etf_intraday_return"], errors="coerce") >= 0.005)
        & (pd.to_numeric(events["delta"], errors="coerce").abs().between(0.45, 0.60))
    ].copy()
    future["momentum15"] = pd.to_numeric(future["close"], errors="coerce") / pd.to_numeric(future["open"], errors="coerce") - 1.0
    future = future.sort_values(["trade_date", "momentum15"], ascending=[True, False])

    ma20 = load_prev_ma20()
    ma20_map = dict(zip(ma20["trade_date"].dt.strftime("%Y-%m-%d"), ma20["prev_ma20"]))
    if not future.empty:
        etf_15m = load_etf_15m(DEFAULT_SQLITE, ["588000"], str(future["trade_date"].min()), str(future["trade_date"].max()))
    else:
        etf_15m = pd.DataFrame()

    selected = 0
    unselected = 0
    for trade_date, group in future.groupby("trade_date", sort=True):
        chosen: pd.Series | None = None
        audit_candidates = []
        for rank, (_, event) in enumerate(group.iterrows(), start=1):
            trade = build_candidate_trade(event, etf_15m, ma20_map)
            entry_fill = float(trade["entry_price"]) + 0.0003
            planned = int((capital * 0.20) // (entry_fill * 10000.0))
            limit = float(event["volume15"]) * 0.05
            audit_candidates.append((rank, trade, planned, limit))
            if planned > 0 and planned <= limit:
                chosen = trade.copy()
                chosen["capacity_selected_rank"] = rank
                chosen["capacity_planned_contracts"] = planned
                chosen["capacity_limit_contracts"] = limit
                break
        if chosen is None:
            rank, trade, planned, limit = audit_candidates[0]
            skipped = trade.copy()
            skipped["capacity_selected_rank"] = rank
            skipped["capacity_planned_contracts"] = planned
            skipped["capacity_limit_contracts"] = limit
            rows.append(skipped.to_dict())
            cap_rows.append(
                {
                    "trade_date": trade_date,
                    "entry_time": skipped["entry_time"],
                    "direction": "put",
                    "contract_id": skipped["contract_id"],
                    "position_pct": 0.20,
                    "entry_mid": skipped["entry_price"],
                    "entry_fill": float(skipped["entry_price"]) + 0.0003,
                    "contracts": 0,
                    "planned_contracts": planned,
                    "volume15": float(skipped["volume15"]),
                    "volume_share": planned / float(skipped["volume15"]) if float(skipped["volume15"]) > 0 else 0.0,
                    "premium": 0.0,
                    "fee": 0.0,
                    "gross_pnl": 0.0,
                    "net_pnl": 0.0,
                    "return_on_premium": 0.0,
                    "capital_before": capital,
                    "capital_after": capital,
                    "exit_reason": skipped["exit_reason"],
                    "exit_legs": skipped["exit_legs"],
                    "exit_fills": "",
                    "skipped": True,
                    "skip_reason": "capacity",
                }
            )
            unselected += 1
            continue
        cap, capital = capital_row(chosen, capital)
        rows.append(chosen.to_dict())
        cap_rows.append(cap)
        selected += 1

    trades_out = pd.DataFrame(rows).sort_values(["entry_time", "contract_id"])
    capital_out = pd.DataFrame(cap_rows).sort_values(["entry_time", "contract_id"])
    active = capital_out[~capital_out["skipped"].fillna(False)].copy()
    summary = {
        "scenario": "capacity_aware_momentum_to_20260723",
        "final_capital": float(capital_out.iloc[-1]["capital_after"]),
        "total_return_pct": float(capital_out.iloc[-1]["capital_after"] / 100000.0 - 1.0) * 100.0,
        "trades": int(len(active)),
        "skipped": int(capital_out["skipped"].fillna(False).sum()),
        "win_rate_pct": float((active["net_pnl"] > 0).mean()) * 100.0,
        "max_dd_pct": drawdown_from_capital(capital_out) * 100.0,
        "addon_trades": int(active["contract_id"].astype(str).str.contains("P_REV", na=False).sum()),
        "addon_pnl": float(active.loc[active["contract_id"].astype(str).str.contains("P_REV", na=False), "net_pnl"].sum()),
        "max_vol_share_pct": float(active["volume_share"].max()) * 100.0,
        "new_selected_after_base_end": selected,
        "new_unselected_after_base_end": unselected,
        "base_end_date": last_date,
        "extended_end_date": str(trades_out["trade_date"].max()),
    }
    trades_out.to_csv(f"{OUT_PREFIX}_trades.csv", index=False)
    capital_out.to_csv(f"{OUT_PREFIX}_capital.csv", index=False)
    pd.DataFrame([summary]).to_csv(f"{OUT_PREFIX}_summary.csv", index=False)
    print(pd.DataFrame([summary]).to_string(index=False))
    new_rows = trades_out[trades_out["trade_date"].astype(str) > last_date].copy()
    if not new_rows.empty:
        print(new_rows[["trade_date", "contract_symbol", "entry_time", "entry_price", "exit_time", "exit_reason", "return", "volume15", "capacity_selected_rank"]].to_string(index=False))
    print(f"Wrote {OUT_PREFIX}_trades.csv")
    print(f"Wrote {OUT_PREFIX}_capital.csv")
    print(f"Wrote {OUT_PREFIX}_summary.csv")


if __name__ == "__main__":
    main()
