# -*- coding: utf-8 -*-
"""QMT liquidity pressure probe for ETF options.

Run on a 1-minute chart during live market. It does NOT send orders.

Purpose:
- read full-tick order book for selected option contracts;
- estimate how many contracts can be bought inside the same limit rule used
  by the KCB 1032 live script: buy limit = ask1 + 0.0003;
- print capacity and slippage for test quantities.

Important:
- This is a probe only. There is no passorder call in this file.
- If the log prefix is not [QMT_LIQ_PRESSURE], you are not running this probe.
- Edit OPTION_CODES after the live strategy identifies current active
  contracts. Keep the list short to avoid noisy logs.
"""

from __future__ import print_function

import datetime
import math


UNDERLYINGS = ["588000.SH"]

# Put the candidate / active option contracts here.
# Today's live-sim logs selected these two puts, so they are included by default.
OPTION_CODES = [
    "10011914.SHO",
    "10012108.SHO",
]

# Scan windows. The probe only works during these times.
SCAN_WINDOWS = [
    ("0930", "1000"),
    ("1000", "1030"),
    ("1030", "1100"),
    ("1315", "1415"),
    ("1445", "1455"),
]

# Real-time throttle. QMT may call handlebar every few seconds in live mode.
SCAN_INTERVAL_SECONDS = 3

QMT_PRICE_TICK = 0.0001
BUY_LIMIT_BUFFER = 0.0003

# Quantities to test. Add/remove numbers here as your target size changes.
TEST_QUANTITIES = [5, 10, 20, 30, 50, 80, 100]

# Optional planned size that mimics current 1032 script budget logic:
# qty = int(PREMIUM_BUDGET / ((ask1 + buffer) * multiplier))
PREMIUM_BUDGET = 50000.0
CONTRACT_MULTIPLIER = 10000


def log(*items):
    print("[QMT_LIQ_PRESSURE]", *items)


def safe_float(value, default=None):
    try:
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return default
        return number
    except Exception:
        return default


def safe_int(value, default=0):
    try:
        return int(float(str(value).replace("-", "").replace("/", "")))
    except Exception:
        return default


def current_datetime(ContextInfo):
    try:
        tag = ContextInfo.get_bar_timetag(ContextInfo.barpos)
        text = timetag_to_datetime(tag, "%Y%m%d%H%M%S")
        return text, safe_int(text[:8]), text[8:12]
    except Exception as exc:
        return "ERROR:%s" % repr(exc), 0, ""


def wall_clock_key():
    try:
        return datetime.datetime.now().strftime("%H%M%S")
    except Exception:
        return "000000"


def in_scan_window(time_text):
    for start, end in SCAN_WINDOWS:
        if time_text >= start and time_text <= end:
            return True
    return False


def round_order_price(value):
    number = safe_float(value)
    if number is None or number <= 0:
        return None
    ticks = int(number / QMT_PRICE_TICK + 0.5)
    return round(max(ticks * QMT_PRICE_TICK, QMT_PRICE_TICK), 4)


def read_key(row, keys):
    if not isinstance(row, dict):
        return None
    for key in keys:
        if key in row:
            return row.get(key)
    lower = {}
    for key, value in row.items():
        lower[str(key).lower()] = value
    for key in keys:
        found = lower.get(str(key).lower())
        if found is not None:
            return found
    return None


def nested_tick_row(raw, code):
    if raw is None:
        return None
    if isinstance(raw, dict):
        if code in raw:
            return raw.get(code)
        alt1 = str(code).replace(".SHO", ".SH")
        alt2 = str(code).replace(".SH", ".SHO")
        for alt in [alt1, alt2, str(code).split(".")[0]]:
            if alt in raw:
                return raw.get(alt)
    return raw


def first_positive_number(value):
    if isinstance(value, (list, tuple)):
        for item in value:
            number = safe_float(item)
            if number is not None and number > 0:
                return number
        return None
    number = safe_float(value)
    if number is not None and number > 0:
        return number
    return None


def positive_at(value, index):
    if isinstance(value, (list, tuple)):
        if index < len(value):
            number = safe_float(value[index])
            if number is not None and number > 0:
                return number
        return None
    if index == 0:
        return first_positive_number(value)
    return None


def level_value(row, side, field, level_index):
    # Try list-style first: askPrice[0..4], bidVol[0..4].
    if side == "ask" and field == "price":
        base = read_key(row, ["askPrice", "ask_price", "ask", "sellPrice"])
        numbered = ["askPrice%d" % (level_index + 1), "ask%d" % (level_index + 1), "sellPrice%d" % (level_index + 1)]
    elif side == "ask" and field == "vol":
        base = read_key(row, ["askVol", "ask_vol", "askVolume", "sellVol"])
        numbered = ["askVol%d" % (level_index + 1), "askVolume%d" % (level_index + 1), "sellVol%d" % (level_index + 1)]
    elif side == "bid" and field == "price":
        base = read_key(row, ["bidPrice", "bid_price", "bid", "buyPrice"])
        numbered = ["bidPrice%d" % (level_index + 1), "bid%d" % (level_index + 1), "buyPrice%d" % (level_index + 1)]
    else:
        base = read_key(row, ["bidVol", "bid_vol", "bidVolume", "buyVol"])
        numbered = ["bidVol%d" % (level_index + 1), "bidVolume%d" % (level_index + 1), "buyVol%d" % (level_index + 1)]

    from_base = positive_at(base, level_index)
    if from_base is not None:
        return from_base
    return first_positive_number(read_key(row, numbered))


def side_levels(row, side):
    levels = []
    for idx in range(5):
        price = level_value(row, side, "price", idx)
        volume = level_value(row, side, "vol", idx)
        if price is not None and volume is not None and price > 0 and volume > 0:
            levels.append((price, volume))
    return levels


def read_full_tick_row(ContextInfo, code):
    try:
        raw = ContextInfo.get_full_tick([code])
    except Exception as exc:
        log("FULL_TICK_ERROR", code, repr(exc))
        return None
    row = nested_tick_row(raw, code)
    if not isinstance(row, dict):
        log("FULL_TICK_EMPTY", code, repr(row))
        return None
    return row


def simulate_buy(ask_levels, quantity, limit_price):
    remaining = int(quantity)
    filled = 0
    notional = 0.0
    worst_price = None
    for price, volume in ask_levels:
        if price > limit_price:
            continue
        take = min(remaining, int(volume))
        if take <= 0:
            continue
        filled += take
        remaining -= take
        notional += take * price
        worst_price = price
        if remaining <= 0:
            break
    avg_price = notional / float(filled) if filled > 0 else None
    return filled, avg_price, worst_price, remaining


def fmt_levels(levels):
    text = []
    for idx, item in enumerate(levels):
        text.append("%d:%.4f/%d" % (idx + 1, item[0], int(item[1])))
    return ",".join(text)


def probe_code(ContextInfo, code, now_text, wall_key):
    row = read_full_tick_row(ContextInfo, code)
    if row is None:
        return

    bid_levels = side_levels(row, "bid")
    ask_levels = side_levels(row, "ask")
    if not ask_levels:
        log("NO_ASK_LEVELS", now_text, wall_key, code, "keys=", repr(sorted([str(k) for k in row.keys()])))
        return

    bid1 = bid_levels[0][0] if bid_levels else None
    ask1 = ask_levels[0][0]
    limit_price = round_order_price(ask1 + BUY_LIMIT_BUFFER)
    if limit_price is None:
        log("BAD_LIMIT", now_text, wall_key, code, "ask1=", ask1)
        return

    executable_qty, executable_avg, worst_price, unused = simulate_buy(ask_levels, 1000000, limit_price)
    planned_qty = int(PREMIUM_BUDGET / float(limit_price * CONTRACT_MULTIPLIER)) if limit_price > 0 else 0

    log(
        "BOOK",
        "bar=", now_text,
        "wall=", wall_key,
        "code=", code,
        "bid1=", bid1,
        "ask1=", ask1,
        "limit=", limit_price,
        "bid_levels=", fmt_levels(bid_levels),
        "ask_levels=", fmt_levels(ask_levels),
        "limit_qty=", executable_qty,
        "limit_avg=", round(executable_avg, 6) if executable_avg is not None else None,
        "limit_worst=", worst_price,
        "planned_qty=", planned_qty,
        "planned_safe=", planned_qty <= executable_qty,
    )

    for quantity in TEST_QUANTITIES:
        filled, avg_price, test_worst, remaining = simulate_buy(ask_levels, quantity, limit_price)
        safe = remaining <= 0
        slip_ticks = None
        if avg_price is not None:
            slip_ticks = round((avg_price - ask1) / QMT_PRICE_TICK, 2)
        log(
            "TEST",
            "bar=", now_text,
            "wall=", wall_key,
            "code=", code,
            "qty=", quantity,
            "safe=", safe,
            "filled=", filled,
            "remain=", remaining,
            "avg=", round(avg_price, 6) if avg_price is not None else None,
            "worst=", test_worst,
            "slip_ticks=", slip_ticks,
        )


def should_scan(ContextInfo, time_text):
    if not in_scan_window(time_text):
        return False
    wall_key = wall_clock_key()
    last_key = getattr(ContextInfo, "_liq_probe_last_wall", "")
    if last_key == "":
        ContextInfo._liq_probe_last_wall = wall_key
        return True
    last_sec = safe_int(last_key[-2:])
    now_sec = safe_int(wall_key[-2:])
    last_min = safe_int(last_key[:4])
    now_min = safe_int(wall_key[:4])
    elapsed = (now_min - last_min) * 60 + (now_sec - last_sec)
    if elapsed < 0:
        elapsed += 3600
    if elapsed >= SCAN_INTERVAL_SECONDS:
        ContextInfo._liq_probe_last_wall = wall_key
        return True
    return False


def init(ContextInfo):
    universe = []
    for code in UNDERLYINGS + OPTION_CODES:
        if code not in universe:
            universe.append(code)
    ContextInfo.set_universe(universe)
    ContextInfo._liq_probe_last_wall = ""
    log(
        "INIT",
        "period=", getattr(ContextInfo, "period", None),
        "universe=", repr(universe),
        "interval_sec=", SCAN_INTERVAL_SECONDS,
        "test_qty=", repr(TEST_QUANTITIES),
        "budget=", PREMIUM_BUDGET,
        "note=", "probe_only_no_orders",
    )


def handlebar(ContextInfo):
    now_text, current_date, time_text = current_datetime(ContextInfo)
    if len(time_text) != 4:
        return
    if not should_scan(ContextInfo, time_text):
        return

    wall_key = wall_clock_key()
    log("TIME", "bar=", now_text, "wall=", wall_key)
    for code in OPTION_CODES:
        probe_code(ContextInfo, code, now_text, wall_key)
