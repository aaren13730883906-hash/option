#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Update the local QMT option monitor dashboard.

It reads monitor/state.json, optionally fetches 1-minute data from iFinD
QuantAPI, evaluates stop-loss / take-profit triggers, then writes state.json.

Usage:
  python3 scripts/update_option_monitor.py
  python3 scripts/update_option_monitor.py --loop --interval 60

Token lookup:
  - IFIND_ACCESS_TOKEN
  - IFIND_REFRESH_TOKEN
  - data_ifind_refresh_token/refresh- token.rtf
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "monitor" / "state.json"
MANUAL_QUOTES_PATH = ROOT / "monitor" / "manual_quotes.json"
CACHE_DIR = ROOT / "monitor" / "ifind_cache"
TOKEN_RTF = ROOT / "data_ifind_refresh_token" / "refresh- token.rtf"

GET_ACCESS_TOKEN_URL = "https://quantapi.51ifind.com/api/v1/get_access_token"
HIGH_FREQUENCY_URL = "https://quantapi.51ifind.com/api/v1/high_frequency"
INDICATORS = "open,high,low,close,volume,amount,changeRatio"


def now_sh() -> dt.datetime:
    # Host is already Asia/Shanghai in the user's setup; keep this stdlib-only.
    return dt.datetime.now()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_rtf_secret(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(errors="ignore")
    tokens = re.findall(r"[A-Za-z0-9_.=-]{50,}", text)
    return max(tokens, key=len) if tokens else None


def post_json(url: str, body: dict[str, Any] | None, headers: dict[str, str], timeout: int = 60) -> dict[str, Any]:
    payload = b"" if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return json.loads(response.read().decode("utf-8"))


def get_access_token() -> str:
    access_token = os.environ.get("IFIND_ACCESS_TOKEN")
    if access_token:
        return access_token.strip()
    refresh_token = os.environ.get("IFIND_REFRESH_TOKEN") or parse_rtf_secret(TOKEN_RTF)
    if not refresh_token:
        raise RuntimeError("No iFinD token found. Set IFIND_ACCESS_TOKEN / IFIND_REFRESH_TOKEN.")
    payload = post_json(
        GET_ACCESS_TOKEN_URL,
        None,
        {"Content-Type": "application/json", "refresh_token": refresh_token.strip()},
        timeout=30,
    )
    try:
        return payload["data"]["access_token"]
    except Exception as exc:
        raise RuntimeError("Failed to obtain iFinD access token: %r" % payload) from exc


def normalize_ifind_tables(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("errorcode") not in (0, None):
        raise RuntimeError("iFinD error %s: %s" % (payload.get("errorcode"), payload.get("errmsg")))
    tables = payload.get("tables") or payload.get("data", {}).get("tables") or []
    rows: list[dict[str, Any]] = []
    for table in tables:
        code = table.get("thscode") or table.get("code")
        data = table.get("table") or table.get("data") or {}
        if isinstance(data, dict):
            length = max([len(v) for v in data.values() if isinstance(v, list)] or [0])
            for idx in range(length):
                row = {"thscode": code}
                for key, values in data.items():
                    row[key] = values[idx] if isinstance(values, list) and idx < len(values) else values
                if "time" not in row and "time" in table:
                    table_time = table.get("time")
                    if isinstance(table_time, list) and idx < len(table_time):
                        row["time"] = table_time[idx]
                    else:
                        row["time"] = table_time
                rows.append(row)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    item = dict(item)
                    item.setdefault("thscode", code)
                    if "time" not in item and "time" in table:
                        item["time"] = table.get("time")
                    rows.append(item)
    return rows


def parse_datetime(value: Any, trade_date: str) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) >= 19 and "-" in text:
        return text[:19]
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 14:
        return "%s-%s-%s %s:%s:%s" % (
            digits[0:4],
            digits[4:6],
            digits[6:8],
            digits[8:10],
            digits[10:12],
            digits[12:14],
        )
    if len(digits) == 12 and digits[:8] == trade_date.replace("-", ""):
        return "%s %s:%s:00" % (trade_date, digits[8:10], digits[10:12])
    if len(digits) >= 6:
        return "%s %s:%s:%s" % (trade_date, digits[0:2], digits[2:4], digits[4:6])
    if len(digits) >= 4:
        return "%s %s:%s:00" % (trade_date, digits[0:2], digits[2:4])
    return None


def as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def fetch_1m(code: str, trade_date: str, refresh: bool = False) -> list[dict[str, Any]]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / ("%s_%s_1m.json" % (trade_date.replace("-", ""), code.replace(".", "_")))
    if cache_path.exists() and not refresh:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached:
            return cached
    token = get_access_token()
    body = {
        "codes": code,
        "indicators": INDICATORS,
        "starttime": "%s 09:30:00" % trade_date,
        "endtime": "%s 15:00:00" % trade_date,
        "functionpara": {"Fill": "Blank"},
    }
    payload = post_json(
        HIGH_FREQUENCY_URL,
        body,
        {"Content-Type": "application/json", "access_token": token},
        timeout=90,
    )
    rows = []
    for raw in normalize_ifind_tables(payload):
        timestamp = parse_datetime(raw.get("time") or raw.get("datetime") or raw.get("date"), trade_date)
        if not timestamp:
            continue
        row = {
            "datetime": timestamp,
            "time": timestamp[11:16],
            "open": as_float(raw.get("open")),
            "high": as_float(raw.get("high")),
            "low": as_float(raw.get("low")),
            "close": as_float(raw.get("close")),
            "volume": as_float(raw.get("volume")),
            "amount": as_float(raw.get("amount")),
        }
        if row["close"] is not None:
            rows.append(row)
    rows.sort(key=lambda item: item["datetime"])
    cache_path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows


def bars_after(bars: list[dict[str, Any]], hhmm: str) -> list[dict[str, Any]]:
    return [row for row in bars if row.get("time", "") >= hhmm]


def manual_quote_bar(code: str, trade_date: str) -> list[dict[str, Any]]:
    if not MANUAL_QUOTES_PATH.exists():
        return []
    data = load_json(MANUAL_QUOTES_PATH)
    quote = (data.get("quotes") or {}).get(code) or {}
    last = as_float(quote.get("last"))
    if last is None:
        return []
    high = as_float(quote.get("high"))
    low = as_float(quote.get("low"))
    hhmm = quote.get("time") or str(data.get("updated_at", ""))[11:16] or now_sh().strftime("%H:%M")
    return [{
        "datetime": "%s %s:00" % (trade_date, hhmm),
        "time": hhmm,
        "open": last,
        "high": high if high is not None else last,
        "low": low if low is not None else last,
        "close": last,
        "volume": None,
        "amount": None,
        "source": "manual_quotes",
    }]


def evaluate_triggers(position: dict[str, Any], bars: list[dict[str, Any]], rules: dict[str, Any]) -> str:
    event = evaluate_exit_event(position, bars, rules)
    return str(event.get("status") or "monitoring_no_exit_hit")


def evaluate_exit_event(position: dict[str, Any], bars: list[dict[str, Any]], rules: dict[str, Any]) -> dict[str, Any]:
    if not bars:
        return {"status": "waiting_market_data"}
    entry = float(position["entry_price"])
    hard_factor = float(position.get("hard_stop_factor", position.get("stop_factor", rules.get("hard_stop_factor", 0.70))))
    soft_raw = position.get("soft_stop_factor", rules.get("soft_stop_factor"))
    tp1_factor = float(position.get("tp1_factor", rules.get("tp1_factor", 1.35)))
    tp2_factor = float(position.get("tp2_factor", rules.get("tp2_factor", 3.0)))
    eod = str(position.get("eod_time") or position.get("exit_deadline") or rules.get("put_reversal_eod_time", "14:45"))
    hard = entry * hard_factor
    soft = entry * float(soft_raw) if soft_raw is not None else None
    tp1 = entry * tp1_factor
    tp2 = entry * tp2_factor
    for row in bars_after(bars, str(position.get("entry_time", "09:45"))[:5]):
        close = row.get("close")
        t = row.get("time", "")
        if close is not None and close <= hard:
            return {"status": "hard_stop_hit_%s" % t, "time": t, "price": close, "full_exit": True}
        if soft is not None and close is not None and close <= soft:
            return {"status": "soft_stop_hit_%s" % t, "time": t, "price": close, "full_exit": True}
        if close is not None and close >= tp2:
            return {"status": "tp2_hit_%s" % t, "time": t, "price": close, "full_exit": True}
        if close is not None and close >= tp1:
            return {"status": "tp1_hit_%s" % t, "time": t, "price": close, "full_exit": False}
        if t >= eod:
            return {"status": "eod_exit_due_%s" % eod, "time": t, "price": close, "full_exit": True}
    return {"status": "monitoring_no_exit_hit"}


def update_state(refresh: bool = False) -> dict[str, Any]:
    state = load_json(STATE_PATH)
    rules = state.get("strategy_rules", {})
    multiplier_default = float(rules.get("multiplier", 10000))

    positions = state.get("positions", [])
    active_positions = [
        p for p in positions
        if p.get("kind") == "missed_strategy_open" or p.get("status") in ["open", "monitoring", "missed_open_monitoring"]
    ]
    def position_time_key(pos: dict[str, Any]) -> str:
        return "%s %s" % (pos.get("trade_date") or "", pos.get("entry_time") or "")

    market_position = max(active_positions, key=position_time_key) if active_positions else (positions[0] if positions else {})
    trade_date = str(market_position.get("trade_date") or state.get("as_of", "2026-07-28")[:10])
    option_code = market_position.get("code") or state.get("market", {}).get("option_code") or "10011914.SH"
    underlying_code = state.get("market", {}).get("underlying_code") or "588000.SH"

    errors = []
    option_bars_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    market_option_bars: list[dict[str, Any]] = []
    underlying_bars: list[dict[str, Any]] = []
    for pos in positions:
        code = pos.get("code")
        pos_date = pos.get("trade_date")
        if not code or not pos_date:
            continue
        if pos.get("kind") != "missed_strategy_open" and pos.get("status") not in ["open", "monitoring", "missed_open_monitoring"]:
            continue
        key = (str(code), str(pos_date))
        if key in option_bars_by_key:
            continue
        bars: list[dict[str, Any]] = []
        try:
            bars = fetch_1m(key[0], key[1], refresh=refresh)
        except Exception as exc:
            errors.append("option %s %s: %s" % (key[0], key[1], exc))
        if not bars:
            bars = manual_quote_bar(key[0], key[1])
            if bars:
                errors.append("option %s %s: using manual_quotes fallback" % (key[0], key[1]))
            else:
                errors.append("option %s %s: no iFinD bars and no manual quote" % (key[0], key[1]))
        option_bars_by_key[key] = bars
    market_option_bars = option_bars_by_key.get((str(option_code), str(trade_date)), [])
    try:
        underlying_bars = fetch_1m(underlying_code, trade_date, refresh=refresh)
    except Exception as exc:
        errors.append("underlying %s: %s" % (underlying_code, exc))
    if not underlying_bars:
        underlying_bars = manual_quote_bar(underlying_code, trade_date)
        if underlying_bars:
            errors.append("underlying %s: using manual_quotes fallback" % underlying_code)
        else:
            errors.append("underlying %s: no iFinD bars and no manual quote" % underlying_code)

    state.setdefault("market", {})
    if market_position:
        state["market"]["option_code"] = option_code
        state["market"]["option_qmt_code"] = market_position.get("qmt_code") or str(option_code).replace(".SH", ".SHO")
        state["market"]["option_name"] = market_position.get("name") or state["market"].get("option_name")
    if market_option_bars:
        state["market"]["option_last"] = market_option_bars[-1]["close"]
        state["market"]["option_last_time"] = market_option_bars[-1]["time"]
        state["market"]["data_status"] = market_option_bars[-1].get("source", "ifind_1m")
    else:
        state["market"]["option_last"] = None
        state["market"]["option_last_time"] = None
        state["market"]["data_status"] = "no_option_market_data"
    if underlying_bars:
        state["market"]["underlying_last"] = underlying_bars[-1]["close"]
        state["market"]["underlying_last_time"] = underlying_bars[-1]["time"]
    else:
        state["market"]["underlying_last"] = None
        state["market"]["underlying_last_time"] = None

    actual_unrealized = 0.0
    opportunity_unrealized = 0.0
    closed_total = 0.0
    today_actual = 0.0
    for pos in positions:
        bars = option_bars_by_key.get((str(pos.get("code")), str(pos.get("trade_date"))), [])
        last_price = bars[-1]["close"] if bars else None
        if last_price is not None:
            pos["current_price"] = last_price
        qty = float(pos.get("qty") or 0)
        multiplier = float(pos.get("multiplier") or multiplier_default)
        entry = float(pos.get("entry_price") or 0)
        fees = float(pos.get("fees") or 0)
        if last_price is not None and qty > 0 and entry > 0:
            exit_event = evaluate_exit_event(pos, bars, rules)
            valuation_price = last_price
            close_fee = 0.0
            if exit_event.get("full_exit") and exit_event.get("price") is not None:
                valuation_price = float(exit_event["price"])
                pos["exit_time"] = exit_event.get("time")
                pos["exit_price"] = valuation_price
                close_fee = qty * float(rules.get("fee_per_contract_per_side", 0))
            market_value = valuation_price * qty * multiplier
            cost = entry * qty * multiplier
            pnl = market_value - cost - fees - close_fee
            pos["market_value"] = round(market_value, 2)
            pos["unrealized_pnl"] = round(pnl, 2)
            pos["return_pct"] = round(pnl / cost * 100.0, 4) if cost else None
            if pos.get("kind") == "missed_strategy_open":
                opportunity_unrealized += pnl
                if pos.get("count_in_total"):
                    if exit_event.get("full_exit"):
                        closed_total += pnl
                    else:
                        actual_unrealized += pnl
                    if str(pos.get("trade_date")) == trade_date:
                        today_actual += pnl
                pos["trigger_status"] = str(exit_event.get("status"))
            else:
                actual_unrealized += pnl
                pos["trigger_status"] = str(exit_event.get("status"))
        elif pos.get("kind") == "missed_strategy_open":
            pos["trigger_status"] = "waiting_market_data"
        if pos.get("kind") != "missed_strategy_open" and pos.get("status") in ["closed", "virtual_closed_by_strategy"]:
            closed_total += float(pos.get("unrealized_pnl") or pos.get("pnl") or 0)
            if str(pos.get("trade_date")) == trade_date:
                today_actual += float(pos.get("unrealized_pnl") or pos.get("pnl") or 0)
        elif pos.get("kind") != "missed_strategy_open" and str(pos.get("trade_date")) == trade_date:
            today_actual += float(pos.get("unrealized_pnl") or 0)

    state["unrealized_pnl"] = round(actual_unrealized, 2)
    state["total_pnl"] = round(closed_total + actual_unrealized, 2)
    state["today_pnl"] = round(today_actual, 2)
    initial_cash = float(state.get("initial_cash") or 100000)
    state["return_pct"] = round(state["total_pnl"] / initial_cash * 100.0, 4) if initial_cash else 0.0
    state["opportunity_pnl"] = round(opportunity_unrealized, 2)
    state["as_of"] = now_sh().strftime("%Y-%m-%d %H:%M:%S")
    state.setdefault("monitoring", {})
    state["monitoring"]["last_update_status"] = "updated" if not errors else "partial_update"
    state["monitoring"]["last_error"] = "; ".join(errors) if errors else None
    save_json(STATE_PATH, state)
    return state


def should_continue(until_hhmm: str) -> bool:
    now = now_sh()
    hh, mm = [int(x) for x in until_hhmm.split(":")[:2]]
    end = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return now <= end


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="keep updating until --until")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--until", default="15:00")
    parser.add_argument("--refresh", action="store_true", help="ignore local iFinD cache")
    args = parser.parse_args()

    if not args.loop:
        state = update_state(refresh=args.refresh)
        print("[OPTION_MONITOR]", state["as_of"], state["monitoring"]["last_update_status"], state["monitoring"].get("last_error"))
        return

    while should_continue(args.until):
        try:
            state = update_state(refresh=True)
            print("[OPTION_MONITOR]", state["as_of"], state["monitoring"]["last_update_status"], state["monitoring"].get("last_error"), flush=True)
        except (urllib.error.URLError, RuntimeError, OSError) as exc:
            state = load_json(STATE_PATH)
            state.setdefault("monitoring", {})
            state["as_of"] = now_sh().strftime("%Y-%m-%d %H:%M:%S")
            state["monitoring"]["last_update_status"] = "update_error"
            state["monitoring"]["last_error"] = str(exc)
            save_json(STATE_PATH, state)
            print("[OPTION_MONITOR_ERROR]", exc, flush=True)
        time.sleep(max(5, int(args.interval)))


if __name__ == "__main__":
    main()
