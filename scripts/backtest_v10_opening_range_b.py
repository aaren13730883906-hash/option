#!/usr/bin/env python3
"""Strict v1.0B opening-range backtest for 588000 ETF options.

This script uses:
  - local 588000 ETF 1m archives for the 09:30-09:45 opening signal;
  - cached option 1m bars under data/intraday_cache for execution;
  - optional iFinD fetches only for missing option caches.
"""

from __future__ import annotations

import argparse
import math
import sys
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backtest_v02_recent_intraday as bt  # noqa: E402


RESEARCH_DIR = ROOT / "research"
ETF_1M_ROOT = Path("/Users/aaren/策略/A股数据/基金_分钟数据/ETF_分钟数据/1分钟_按月归档")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=366)
    parser.add_argument("--underlying", choices=["588000", "159915"], default="588000")
    parser.add_argument("--sqlite", type=Path, default=bt.DEFAULT_SQLITE)
    parser.add_argument("--etf-1m-root", type=Path, default=ETF_1M_ROOT)
    parser.add_argument("--daily-csv", type=Path, default=bt.DAILY_CSV)
    parser.add_argument("--market-iv-csv", type=Path, default=bt.MARKET_IV_CSV)
    parser.add_argument("--etf-daily-csv", type=Path, default=bt.ETF_DAILY_CSV)
    parser.add_argument("--candidate-pool", type=int, default=8)
    parser.add_argument("--strong-trailing-pct", type=float, default=0.25)
    parser.add_argument("--normal-tp2-factor", type=float, default=1.80)
    parser.add_argument("--range-threshold", type=float, default=0.003)
    parser.add_argument(
        "--put-range-threshold",
        type=float,
        default=None,
        help="Independent Put opening-range threshold; defaults to --range-threshold.",
    )
    parser.add_argument(
        "--warmup-trading-days",
        type=int,
        default=20,
        help="ETF trading days loaded before the tradable start for 15m EMA warmup.",
    )
    parser.add_argument("--breakout-vol-mult", type=float, default=1.3)
    parser.add_argument("--breakout-volmax-mult", type=float, default=0.8)
    parser.add_argument("--first-leg-ratio", type=float, default=0.65)
    parser.add_argument("--normal-position-pct", type=float, default=0.50)
    parser.add_argument("--strong-position-pct", type=float, default=0.70)
    parser.add_argument("--soft-stop-pct", type=float, default=0.75)
    parser.add_argument("--soft-stop-delay-minutes", type=int, default=5)
    parser.add_argument(
        "--daily-volume-tiered",
        action="store_true",
        help="Block prior-day volume ratio below 0.65 and multiply position by 0.70 below 0.80.",
    )
    parser.add_argument(
        "--edge-dte-fallback",
        action="store_true",
        help="If DTE 10-35 is empty, allow DTE 7-9 or 36-40 at 60% size.",
    )
    parser.add_argument(
        "--long-exhaustion-filter",
        action="store_true",
        help="Deprecated compatibility flag; the long-exhaustion filter is enabled by default.",
    )
    parser.add_argument(
        "--disable-long-exhaustion-filter",
        action="store_true",
        help="Disable the default 588000 opening-Call long-exhaustion filter.",
    )
    parser.add_argument("--long-exhaustion-price-threshold", type=float, default=0.05)
    parser.add_argument("--fetch-missing", action="store_true", help="Fetch only missing option 1m caches via iFinD.")
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--output", type=Path, default=RESEARCH_DIR / "backtest_v10_opening_range_b_trades.csv")
    parser.add_argument("--summary", type=Path, default=RESEARCH_DIR / "backtest_v10_opening_range_b_summary.csv")
    return parser.parse_args()


def load_etf_1m(root: Path, trade_date: str, underlying: str) -> pd.DataFrame:
    ym = trade_date[:7]
    ymd = trade_date.replace("-", "")
    zip_path = root / ym / f"{ymd}_1min.zip"
    member = f"{bt.market_symbol(underlying)}.csv"
    if zip_path.exists():
        with zipfile.ZipFile(zip_path) as zf:
            if member in zf.namelist():
                with zf.open(member) as fh:
                    raw = pd.read_csv(fh, encoding="utf-8-sig")
            else:
                raw = pd.DataFrame()
    else:
        raw = pd.DataFrame()
    if raw.empty:
        supplemental = bt.ETF_INTRADAY_IFIND / f"{trade_date}_{underlying}_1m.csv"
        if not supplemental.exists():
            return pd.DataFrame()
        raw = pd.read_csv(supplemental)
    raw = raw.rename(
        columns={
            "时间": "datetime",
            "代码": "symbol",
            "名称": "name",
            "开盘价": "open",
            "收盘价": "close",
            "最高价": "high",
            "最低价": "low",
            "成交量": "volume",
            "成交额": "amount",
            "涨幅": "change_ratio",
            "振幅": "amplitude",
        }
    )
    raw["datetime"] = pd.to_datetime(raw["datetime"], errors="coerce")
    for col in ["open", "close", "high", "low", "volume", "amount"]:
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    out = raw.dropna(subset=["datetime", "close"]).copy()
    out["underlying_code"] = underlying
    out["trade_date"] = out["datetime"].dt.strftime("%Y-%m-%d")
    out["time"] = out["datetime"].dt.strftime("%H:%M")
    return out.sort_values("datetime")


def load_etf_daily_history(path: Path, underlying: str) -> pd.DataFrame:
    raw = pd.read_csv(path, dtype={"underlying_code": str})
    raw = raw[raw["underlying_code"] == underlying].copy()
    raw["trade_date"] = pd.to_datetime(raw["trade_date"], errors="coerce")
    for col in ["etf_open", "etf_high", "etf_low", "etf_close", "etf_volume"]:
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    raw = raw.dropna(subset=["trade_date", "etf_close"]).sort_values("trade_date")
    return raw


def long_exhaustion_score(
    daily_history: pd.DataFrame,
    trade_date: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    result = {
        "long_exhaustion_score": 0,
        "long_exhaustion_price": False,
        "long_exhaustion_action": "normal",
        "long_exhaustion_2d_return": math.nan,
    }
    current_date = pd.Timestamp(trade_date)
    prior = daily_history[daily_history["trade_date"] < current_date].tail(21).copy()
    if len(prior) >= 3:
        result["long_exhaustion_2d_return"] = float(prior.iloc[-1]["etf_close"] / prior.iloc[-3]["etf_close"] - 1)
        result["long_exhaustion_price"] = (
            result["long_exhaustion_2d_return"] >= args.long_exhaustion_price_threshold
        )
    result["long_exhaustion_score"] = 3 if result["long_exhaustion_price"] else 0
    if result["long_exhaustion_price"]:
        result["long_exhaustion_action"] = "block"
    return result


def find_opening_breakout(etf1: pd.DataFrame, daily_direction: str, args: argparse.Namespace) -> dict[str, Any] | None:
    first5 = etf1[(etf1["time"] >= "09:30") & (etf1["time"] <= "09:34")].copy()
    if len(first5) < 5:
        return None
    h = float(first5["high"].max())
    l = float(first5["low"].min())
    opening_amp = (h - l) / l if l > 0 else math.nan
    range_threshold = (
        args.put_range_threshold
        if daily_direction == "put" and args.put_range_threshold is not None
        else args.range_threshold
    )
    if not pd.notna(opening_amp) or opening_amp < range_threshold:
        return None
    if daily_direction not in {"call", "put"}:
        return None

    vol_mean = float(first5["volume"].mean())
    vol_max = float(first5["volume"].max())
    scan = etf1[(etf1["time"] >= "09:35") & (etf1["time"] <= "09:40")].copy()
    for row in scan.itertuples(index=False):
        broke = (daily_direction == "call" and float(row.high) > h) or (
            daily_direction == "put" and float(row.low) < l
        )
        if not broke:
            continue
        vol_ok = float(row.volume) >= vol_mean * args.breakout_vol_mult and float(row.volume) >= vol_max * args.breakout_volmax_mult
        if not vol_ok:
            continue
        future = etf1[etf1["datetime"] > row.datetime].head(3)
        if len(future) < 3 or future["time"].iloc[-1] > "09:43":
            continue
        if daily_direction == "call":
            stand_count = int((future["close"] > h).sum())
        else:
            stand_count = int((future["close"] < l).sum())
        if stand_count < 2:
            continue
        entry_time = max(pd.Timestamp(row.datetime) + pd.Timedelta(minutes=3), pd.Timestamp(f"{row.trade_date} 09:40"))
        if entry_time > pd.Timestamp(f"{row.trade_date} 09:45"):
            continue
        return {
            "direction": daily_direction,
            "opening_high": h,
            "opening_low": l,
            "opening_amp": opening_amp,
            "opening_vol_mean": vol_mean,
            "opening_vol_max": vol_max,
            "breakout_time": pd.Timestamp(row.datetime),
            "breakout_price": float(row.close),
            "breakout_volume": float(row.volume),
            "breakout_vol_ratio": float(row.volume) / vol_mean if vol_mean else math.nan,
            "stand_count": stand_count,
            "entry_time": entry_time,
        }
    return None


def option_5m_confirm(bars: pd.DataFrame, ts: pd.Timestamp) -> tuple[bool, float]:
    hist = bars[bars["datetime"] <= ts].copy()
    if hist.empty:
        return False, math.nan
    g = hist.set_index("datetime").sort_index()
    five = g.resample("5min", label="right", closed="right").agg(close=("close", "last"))
    five = five.dropna(subset=["close"])
    if len(five) < 2:
        return False, math.nan
    five["ema5"] = five["close"].ewm(span=5, adjust=False).mean()
    last = five.iloc[-1]
    prev = five.iloc[-2]
    strength = float(last["close"] / last["ema5"] - 1) if last["ema5"] else math.nan
    return bool(last["close"] > last["ema5"] and last["ema5"] > prev["ema5"]), strength


def load_option_cache(trade_date: str, option_code: str) -> pd.DataFrame:
    path = bt.INTRADAY_CACHE / f"{trade_date}_{str(option_code).zfill(8)}_1m.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, parse_dates=["datetime"], dtype={"option_code": str})


def value_at_or_before(bars: pd.DataFrame, ts: pd.Timestamp) -> pd.Series | None:
    rows = bars[bars["datetime"] <= ts].tail(1)
    if rows.empty:
        return None
    return rows.iloc[0]


def select_contract(
    daily: pd.DataFrame,
    trade_date: str,
    underlying: str,
    direction: str,
    breakout_time: pd.Timestamp,
    candidate_pool: int,
    headers: dict[str, str] | None = None,
    fetch_missing: bool = False,
    sleep: float = 0.15,
    retries: int = 3,
    allow_edge_dte: bool = False,
) -> tuple[dict[str, Any] | None, int, int]:
    daily_candidates = bt.option_candidates(
        daily,
        trade_date,
        underlying,
        direction,
        candidate_pool,
        allow_edge_dte=allow_edge_dte,
    )
    if daily_candidates.empty:
        return None, 0, 0
    daily_candidates = daily_candidates.head(3)
    ranked: list[dict[str, Any]] = []
    missing_cache = 0
    fetched_cache = 0
    for opt in daily_candidates.itertuples(index=False):
        bars = load_option_cache(trade_date, opt.option_code)
        if bars.empty:
            missing_cache += 1
            if fetch_missing and headers is not None:
                bars = bt.fetch_option_1m(
                    option_code=opt.option_code,
                    trade_date=trade_date,
                    headers=headers,
                    sleep=sleep,
                    retries=retries,
                    refresh=False,
                    no_fetch=False,
                )
                if not bars.empty:
                    fetched_cache += 1
                else:
                    continue
            else:
                continue
        last = value_at_or_before(bars, breakout_time)
        if last is None or pd.isna(last["close"]) or float(last["close"]) <= 0:
            continue
        ok, trend_strength = option_5m_confirm(bars, breakout_time)
        if not ok:
            continue
        cum_volume = float(bars[bars["datetime"] <= breakout_time]["volume"].sum())
        if cum_volume <= 0:
            continue
        row = opt._asdict()
        row.update(
            {
                "bars": bars,
                "cum_volume": cum_volume,
                "option_trend_strength": trend_strength,
                "breakout_option_price": float(last["close"]),
            }
        )
        ranked.append(row)
    if not ranked:
        return None, missing_cache, fetched_cache
    ranked = bt.score_option_candidates(ranked)
    return ranked[0], missing_cache, fetched_cache


def confirm_0945(etf1: pd.DataFrame, etf15_day: pd.DataFrame, signal: dict[str, Any]) -> bool:
    confirm_ts = pd.Timestamp(f"{signal['entry_time']:%Y-%m-%d} 09:45")
    row1 = value_at_or_before(etf1, confirm_ts)
    row15 = value_at_or_before(etf15_day, confirm_ts)
    if row1 is None or row15 is None or pd.isna(row15.get("ema5")):
        return False
    if signal["direction"] == "call":
        return bool(float(row1["close"]) > signal["opening_high"] and float(row15["close"]) > float(row15["ema5"]))
    return bool(float(row1["close"]) < signal["opening_low"] and float(row15["close"]) < float(row15["ema5"]))


def early_position_pct(
    signal: dict[str, Any],
    selected: dict[str, Any],
    daily_row: pd.Series,
    args: argparse.Namespace,
) -> tuple[float, str]:
    strong = signal["breakout_vol_ratio"] >= 2.0
    pct = args.strong_position_pct if strong else args.normal_position_pct
    label = "strong" if strong else "normal"
    iv = float(selected.get("implied_volatility", math.nan))
    if pd.notna(iv) and iv >= 0.50:
        pct *= 0.70
        label += "_iv_reduced"
    daily_volume_ratio20 = daily_row.get("daily_ref_volume_ratio20", math.nan)
    if args.daily_volume_tiered and pd.notna(daily_volume_ratio20) and float(daily_volume_ratio20) < 0.80:
        pct *= 0.70
        label += "_daily_volume_reduced"
    dte_factor = float(selected.get("dte_position_factor", 1.0))
    if dte_factor < 1.0:
        pct *= dte_factor
        label += "_edge_dte_reduced"
    return pct, label


def build_trade(
    trade_date: str,
    underlying: str,
    signal: dict[str, Any],
    selected: dict[str, Any],
    etf1: pd.DataFrame,
    etf15_day: pd.DataFrame,
    daily_row: pd.Series,
    iv_row: pd.Series | None,
    args: argparse.Namespace,
) -> dict[str, Any] | None:
    bars = selected["bars"].copy()
    bars["ema5"] = bars["close"].ewm(span=5, adjust=False).mean()
    first_entry_time = signal["entry_time"]
    first = value_at_or_before(bars, first_entry_time)
    if first is None or float(first["close"]) <= 0:
        return None
    first_price = float(first["close"])
    target_pct, signal_strength = early_position_pct(signal, selected, daily_row, args)
    first_pct = target_pct * args.first_leg_ratio
    actual_pct = first_pct
    entry_price = first_price
    add_price = math.nan
    add_pct = 0.0
    add_time = pd.NaT
    confirm_pass = confirm_0945(etf1, etf15_day, signal)
    confirm_time = pd.Timestamp(f"{trade_date} 09:45")

    if not confirm_pass:
        exit_row = value_at_or_before(bars, confirm_time)
        exit_price = first_price if exit_row is None else float(exit_row["close"])
        exit_info = {
            "exit_time": confirm_time,
            "exit_price_1": exit_price,
            "exit_price_2": exit_price,
            "return": exit_price / first_price - 1,
            "exit_reason": "opening_confirm_fail",
            "exit_legs": f"1.0@{exit_price:.6f}",
        }
    else:
        add_row = value_at_or_before(bars, confirm_time)
        remaining_pct = target_pct - first_pct
        if add_row is not None and float(add_row["close"]) <= first_price * 1.03 and remaining_pct > 0:
            add_price = float(add_row["close"])
            add_pct = remaining_pct
            add_time = confirm_time
            actual_pct = target_pct
            entry_price = (first_pct * first_price + add_pct * add_price) / actual_pct
        exit_info = bt.simulate_exit(
            bars_1m=bars,
            etf_15m=etf15_day,
            entry_time=confirm_time,
            entry_price=entry_price,
            direction=signal["direction"],
            signal_strength=signal_strength,
            strong_trailing_pct=args.strong_trailing_pct,
            normal_tp2_factor=args.normal_tp2_factor,
            soft_stop_pct=args.soft_stop_pct,
            soft_stop_delay_minutes=args.soft_stop_delay_minutes,
        )

    trade = {
        "trade_date": trade_date,
        "underlying_code": underlying,
        "direction": signal["direction"],
        "entry_time": first_entry_time,
        "etf_close": signal["breakout_price"],
        "etf_volume_15m": signal["breakout_volume"],
        "market_iv": float(iv_row["market_iv"]) if iv_row is not None and "market_iv" in iv_row else math.nan,
        "iv_rank_252": float(iv_row["iv_rank_252"]) if iv_row is not None and "iv_rank_252" in iv_row else math.nan,
        "etf_volume_ratio": signal["breakout_vol_ratio"],
        "signal_strength": signal_strength,
        "position_pct": actual_pct,
        "daily_direction": daily_row.get("daily_direction", ""),
        "daily_allowed_direction": daily_row.get("daily_direction", ""),
        "daily_ref_date": daily_row.get("daily_ref_date", ""),
        "daily_ref_close": daily_row.get("daily_ref_close", math.nan),
        "daily_ref_ma5": daily_row.get("daily_ref_ma5", math.nan),
        "daily_ref_ma10": daily_row.get("daily_ref_ma10", math.nan),
        "daily_ref_ma20": daily_row.get("daily_ref_ma20", math.nan),
        "daily_ref_ma5_slope": daily_row.get("daily_ref_ma5_slope", math.nan),
        "daily_ref_ma10_slope": daily_row.get("daily_ref_ma10_slope", math.nan),
        "daily_ref_ma20_slope": daily_row.get("daily_ref_ma20_slope", math.nan),
        "daily_ref_ma_cluster": daily_row.get("daily_ref_ma_cluster", math.nan),
        "daily_ref_volume_ratio20": daily_row.get("daily_ref_volume_ratio20", math.nan),
        "option_code": str(selected["option_code"]).zfill(8),
        "contract_id": selected["contract_id"],
        "contract_symbol": selected.get("contract_symbol", selected["contract_id"]),
        "entry_price": entry_price,
        "first_entry_price": first_price,
        "first_position_pct": first_pct,
        "add_time": add_time,
        "add_price": add_price,
        "add_position_pct": add_pct,
        "opening_confirm_pass": confirm_pass,
        "opening_high": signal["opening_high"],
        "opening_low": signal["opening_low"],
        "opening_amp": signal["opening_amp"],
        "long_exhaustion_score": signal.get("long_exhaustion_score", 0),
        "long_exhaustion_action": signal.get("long_exhaustion_action", "normal"),
        "long_exhaustion_price": signal.get("long_exhaustion_price", False),
        "long_exhaustion_2d_return": signal.get("long_exhaustion_2d_return", math.nan),
        "breakout_time": signal["breakout_time"],
        "breakout_volume": signal["breakout_volume"],
        "breakout_vol_ratio": signal["breakout_vol_ratio"],
        "stand_count": signal["stand_count"],
        "entry_option_volume_15m": selected["cum_volume"],
        "cum_volume": selected["cum_volume"],
        "option_trend_strength": selected["option_trend_strength"],
        "dte": selected["dte"],
        "delta": selected["delta"],
        "implied_volatility": selected["implied_volatility"],
        "edge_dte_candidate": bool(selected.get("edge_dte_candidate", False)),
        "dte_position_factor": float(selected.get("dte_position_factor", 1.0)),
    }
    trade.update(exit_info)
    return trade


def main() -> None:
    args = parse_args()
    if args.range_threshold <= 0:
        raise ValueError("range-threshold must be positive")
    if args.put_range_threshold is not None and args.put_range_threshold <= 0:
        raise ValueError("put-range-threshold must be positive")
    bt.ensure_dirs()
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)

    daily = pd.read_csv(args.daily_csv, dtype={"option_code": str, "contract_id": str, "underlying_code": str})
    market_iv = pd.read_csv(args.market_iv_csv, dtype={"underlying_code": str})
    etf_daily_history = load_etf_daily_history(args.etf_daily_csv, args.underlying)
    end = pd.to_datetime(daily["trade_date"].max())
    start = end - pd.Timedelta(days=args.days)
    daily = daily[(daily["trade_date"] >= start.strftime("%Y-%m-%d")) & (daily["trade_date"] <= end.strftime("%Y-%m-%d"))]
    daily = daily[daily["underlying_code"] == args.underlying].copy()
    market_iv = market_iv[(market_iv["trade_date"] >= start.strftime("%Y-%m-%d")) & (market_iv["trade_date"] <= end.strftime("%Y-%m-%d"))]
    daily_direction = bt.load_daily_direction(args.underlying, args.etf_daily_csv)
    direction_dates = pd.to_datetime(daily_direction["trade_date"])
    prior_dates = direction_dates[direction_dates < start].drop_duplicates().sort_values()
    if args.warmup_trading_days < 20:
        raise ValueError("warmup-trading-days must be at least 20")
    if len(prior_dates) < args.warmup_trading_days:
        raise RuntimeError(
            "Insufficient ETF history for {} opening EMA warmup trading days before {}".format(
                args.warmup_trading_days,
                start.strftime("%Y-%m-%d"),
            )
        )
    indicator_start = prior_dates.iloc[-args.warmup_trading_days]
    etf15 = bt.load_etf_15m(
        args.sqlite,
        [args.underlying],
        indicator_start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
    )
    headers = None
    if args.fetch_missing:
        token = bt.get_access_token()
        headers = {"Content-Type": "application/json", "access_token": token}

    trades: list[dict[str, Any]] = []
    stats = {
        "dates": 0,
        "missing_etf_1m": 0,
        "no_opening_signal": 0,
        "no_contract": 0,
        "daily_volume_blocked": 0,
        "long_exhaustion_blocked": 0,
        "missing_option_cache": 0,
        "fetched_option_cache": 0,
    }
    for trade_date in sorted(daily["trade_date"].unique()):
        stats["dates"] += 1
        etf1 = load_etf_1m(args.etf_1m_root, trade_date, args.underlying)
        if etf1.empty:
            stats["missing_etf_1m"] += 1
            continue
        daily_dir_row = daily_direction[daily_direction["trade_date"] == trade_date]
        if daily_dir_row.empty:
            stats["no_opening_signal"] += 1
            continue
        daily_row = daily_dir_row.iloc[0]
        daily_volume_ratio20 = daily_row.get("daily_ref_volume_ratio20", math.nan)
        if (
            args.daily_volume_tiered
            and (pd.isna(daily_volume_ratio20) or float(daily_volume_ratio20) < 0.65)
        ):
            stats["daily_volume_blocked"] += 1
            continue
        direction = str(daily_row["daily_direction"])
        signal = find_opening_breakout(etf1, direction, args)
        if signal is None:
            stats["no_opening_signal"] += 1
            continue
        long_exhaustion_enabled = (
            not args.disable_long_exhaustion_filter
            or args.long_exhaustion_filter
        )
        if (
            long_exhaustion_enabled
            and args.underlying == "588000"
            and signal["direction"] == "call"
        ):
            exhaustion = long_exhaustion_score(
                etf_daily_history,
                trade_date,
                args,
            )
            signal.update(exhaustion)
            if exhaustion["long_exhaustion_action"] == "block":
                stats["long_exhaustion_blocked"] += 1
                continue
        selected, missing_cache, fetched_cache = select_contract(
            daily=daily,
            trade_date=trade_date,
            underlying=args.underlying,
            direction=signal["direction"],
            breakout_time=signal["breakout_time"],
            candidate_pool=args.candidate_pool,
            headers=headers,
            fetch_missing=args.fetch_missing,
            sleep=args.sleep,
            retries=args.retries,
            allow_edge_dte=args.edge_dte_fallback,
        )
        stats["missing_option_cache"] += missing_cache
        stats["fetched_option_cache"] += fetched_cache
        if selected is None:
            stats["no_contract"] += 1
            continue
        etf15_day = etf15[(etf15["underlying_code"] == args.underlying) & (etf15["trade_date"] == trade_date)].copy()
        iv_matches = market_iv[(market_iv["underlying_code"] == args.underlying) & (market_iv["trade_date"] == trade_date)]
        iv_row = None if iv_matches.empty else iv_matches.iloc[0]
        trade = build_trade(trade_date, args.underlying, signal, selected, etf1, etf15_day, daily_row, iv_row, args)
        if trade is not None:
            trades.append(trade)

    out = pd.DataFrame(trades).sort_values("entry_time") if trades else pd.DataFrame()
    out.to_csv(args.output, index=False)
    summary = {
        "strategy_version": "v1.0B_opening_range",
        "underlying": args.underlying,
        "start": start.strftime("%Y-%m-%d"),
        "end": end.strftime("%Y-%m-%d"),
        "trades": int(len(out)),
        "call_range_threshold": args.range_threshold,
        "put_range_threshold": (
            args.put_range_threshold
            if args.put_range_threshold is not None
            else args.range_threshold
        ),
        "warmup_trading_days": args.warmup_trading_days,
        "long_exhaustion_filter": not args.disable_long_exhaustion_filter,
        "long_exhaustion_price_threshold": args.long_exhaustion_price_threshold,
        **stats,
    }
    pd.DataFrame([summary]).to_csv(args.summary, index=False)
    print(pd.DataFrame([summary]).to_string(index=False))
    if not out.empty:
        print(out[["trade_date", "direction", "entry_time", "contract_id", "position_pct", "entry_price", "exit_time", "exit_reason", "return"]].to_string(index=False))


if __name__ == "__main__":
    main()
