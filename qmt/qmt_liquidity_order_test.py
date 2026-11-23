# -*- coding: utf-8 -*-
"""QMT one-shot liquidity-aware live order test.

Run on a 1-minute chart during live market.

Purpose:
- simulate the formal strategy saying: "planned position = 20 contracts";
- read full-tick order book for one option contract;
- buy only the quantity currently executable inside:
    buy limit = ask1 + BUY_LIMIT_BUFFER;
- optionally keep monitoring pending quantity, but by default this script
  sends at most one real order.

Safety:
- TEST_ORDER_ARMED is False by default. In that mode, it does NOT send orders.
- Set TEST_ORDER_ARMED = True only when you are ready for a real buy-open test.
- If log prefix is not [QMT_LIQ_ORDER_TEST], you are not running this script.
"""

from __future__ import print_function

import datetime
import math

try:
    from qmt_local_config import (
        LIQUIDITY_ORDER_TEST_ARMED,
        QMT_ACCOUNT_ID as LOCAL_QMT_ACCOUNT_ID,
    )
except Exception:
    LIQUIDITY_ORDER_TEST_ARMED = False
    LOCAL_QMT_ACCOUNT_ID = ""


# ---------------------------------------------------------------------------
# Test configuration
# ---------------------------------------------------------------------------

BUILD_ID = "QMT_LIQ_ORDER_TEST_20260728_R1"

TARGET_OPTION_CODE = "10011914.SHO"
UNDERLYING_CODE = "588000.SH"

# Real-order arming switch. Keep False for dry run / preview.
TEST_ORDER_ARMED = LIQUIDITY_ORDER_TEST_ARMED

# This mimics the strategy-planned position size.
PLANNED_QTY = 20

# If True, after the first accepted order, keep monitoring and send more
# orders for the remaining planned quantity. For first real test, False is
# safer because passorder_return only means accepted, not necessarily filled.
CONTINUE_PENDING_AFTER_ORDER = False

QMT_ACCOUNT_ID = LOCAL_QMT_ACCOUNT_ID
QMT_OPTION_ACCOUNT_TYPE = 1101
QMT_BUY_OPEN_OP = 50
QMT_MARKET_PRICE_TYPE = 11
QMT_QUICK_TRADE = 1
QMT_PASSORDER_STYLE = "official9"
QMT_ORDER_CODE_WITH_SUFFIX = True

QMT_PRICE_TICK = 0.0001
BUY_LIMIT_BUFFER = 0.0003
LIQUIDITY_LEVELS = 5
REQUIRE_LAST_BAR = True
CONTRACT_MULTIPLIER = 10000
FEE_PER_CONTRACT_PER_SIDE = 1.60
LOG_TRADE_DETAIL_AFTER_ORDER = True

SCAN_INTERVAL_SECONDS = 3
SCAN_WINDOWS = [
    ("0930", "1130"),
    ("1300", "1455"),
]


RUNTIME_ORDER_KEYS = set()
GLOBAL_ORDER_DONE = False
GLOBAL_SUBMITTED_QTY = 0


def log(*items):
    print("[QMT_LIQ_ORDER_TEST]", *items)


def masked_account(account_id):
    text = str(account_id)
    if len(text) <= 4:
        return "****"
    return text[:3] + "****" + text[-3:]


def short_repr(value, max_len=800):
    text = repr(value)
    if len(text) > max_len:
        return text[:max_len] + "...TRUNCATED"
    return text


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


def is_last_bar_safe(ContextInfo):
    if not REQUIRE_LAST_BAR:
        return True, "not_required"
    try:
        if ContextInfo.is_last_bar():
            return True, "last_bar"
        return False, "not_last_bar"
    except Exception as exc:
        return False, "last_bar_error:%s" % repr(exc)


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


def level_value(row, side, field_name, level_index):
    if side == "ask" and field_name == "price":
        base = read_key(row, ["askPrice", "ask_price", "ask", "sellPrice"])
        numbered = ["askPrice%d" % (level_index + 1), "ask%d" % (level_index + 1), "sellPrice%d" % (level_index + 1), "sell%dPrice" % (level_index + 1)]
    elif side == "ask" and field_name == "volume":
        base = read_key(row, ["askVol", "ask_vol", "askVolume", "sellVol"])
        numbered = ["askVol%d" % (level_index + 1), "askVolume%d" % (level_index + 1), "sellVol%d" % (level_index + 1), "sell%dVol" % (level_index + 1)]
    elif side == "bid" and field_name == "price":
        base = read_key(row, ["bidPrice", "bid_price", "bid", "buyPrice"])
        numbered = ["bidPrice%d" % (level_index + 1), "bid%d" % (level_index + 1), "buyPrice%d" % (level_index + 1), "buy%dPrice" % (level_index + 1)]
    else:
        base = read_key(row, ["bidVol", "bid_vol", "bidVolume", "buyVol"])
        numbered = ["bidVol%d" % (level_index + 1), "bidVolume%d" % (level_index + 1), "buyVol%d" % (level_index + 1), "buy%dVol" % (level_index + 1)]
    found = positive_at(base, level_index)
    if found is not None:
        return found
    return first_positive_number(read_key(row, numbered))


def side_levels(row, side):
    levels = []
    for idx in range(max(1, safe_int(LIQUIDITY_LEVELS, 5))):
        price = level_value(row, side, "price", idx)
        volume = level_value(row, side, "volume", idx)
        if price is not None and volume is not None and price > 0 and volume > 0:
            levels.append((price, volume))
    return levels


def fmt_levels(levels):
    text = []
    for idx, item in enumerate(levels or []):
        text.append("%d:%.4f/%d" % (idx + 1, item[0], int(item[1])))
    return ",".join(text)


def simulate_buy(ask_levels, quantity, limit_price):
    remaining = int(quantity)
    filled = 0
    notional = 0.0
    worst_price = None
    for price, volume in ask_levels or []:
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


def build_liquidity_order(ContextInfo, code, planned_qty):
    allowed, reason = is_last_bar_safe(ContextInfo)
    if not allowed:
        return {"ok": False, "reason": reason}
    row = read_full_tick_row(ContextInfo, code)
    if row is None:
        return {"ok": False, "reason": "no_full_tick"}
    bid_levels = side_levels(row, "bid")
    ask_levels = side_levels(row, "ask")
    if not ask_levels:
        return {"ok": False, "reason": "no_ask_levels", "keys": repr(sorted([str(k) for k in row.keys()]))}
    bid1 = bid_levels[0][0] if bid_levels else None
    ask1 = ask_levels[0][0]
    limit_price = round_order_price(ask1 + BUY_LIMIT_BUFFER)
    if limit_price is None:
        return {"ok": False, "reason": "bad_limit"}
    liq_qty, liq_avg, liq_worst, remaining = simulate_buy(ask_levels, planned_qty, limit_price)
    order_qty = min(max(0, safe_int(planned_qty)), max(0, safe_int(liq_qty)))
    return {
        "ok": order_qty > 0,
        "reason": "ok" if order_qty > 0 else "zero_liquidity",
        "code": code,
        "planned_qty": safe_int(planned_qty),
        "order_qty": order_qty,
        "pending_qty": max(0, safe_int(planned_qty) - order_qty),
        "limit_price": limit_price,
        "bid1": bid1,
        "ask1": ask1,
        "bid_levels": bid_levels,
        "ask_levels": ask_levels,
        "liq_qty": liq_qty,
        "liq_avg": liq_avg,
        "liq_worst": liq_worst,
    }


def submit_buy_open(ContextInfo, order):
    global RUNTIME_ORDER_KEYS
    now_text, unused_date, unused_time = current_datetime(ContextInfo)
    key = (now_text, order["code"], int(order["order_qty"]), order["limit_price"])
    if key in RUNTIME_ORDER_KEYS:
        log("ORDER_BLOCKED", "duplicate", repr(key))
        return False
    RUNTIME_ORDER_KEYS.add(key)
    order_code = str(order["code"]) if QMT_ORDER_CODE_WITH_SUFFIX else str(order["code"]).split(".")[0]
    log(
        "PASSORDER_ARGS",
        "style=", QMT_PASSORDER_STYLE,
        "operation=", QMT_BUY_OPEN_OP,
        "account_type=", QMT_OPTION_ACCOUNT_TYPE,
        "account=", masked_account(QMT_ACCOUNT_ID),
        "code=", order_code,
        "price_type=", QMT_MARKET_PRICE_TYPE,
        "price=", order["limit_price"],
        "qty=", int(order["order_qty"]),
    )
    log(
        "ORDER_EXPECTED_FILL",
        "code=", order["code"],
        "planned_qty=", order.get("planned_qty"),
        "order_qty=", order["order_qty"],
        "pending_qty=", order.get("pending_qty"),
        "limit=", order["limit_price"],
        "ask1=", order.get("ask1"),
        "liq_qty=", order.get("liq_qty"),
        "liq_avg=", round(order.get("liq_avg"), 6) if order.get("liq_avg") is not None else None,
        "liq_worst=", order.get("liq_worst"),
        "expected_amount=", round((order.get("liq_avg") or order["limit_price"]) * order["order_qty"] * CONTRACT_MULTIPLIER, 2),
        "expected_fee=", round(order["order_qty"] * FEE_PER_CONTRACT_PER_SIDE, 2),
        "ask_levels=", fmt_levels(order.get("ask_levels")),
    )
    try:
        if QMT_PASSORDER_STYLE == "official9":
            result = passorder(
                QMT_BUY_OPEN_OP,
                QMT_OPTION_ACCOUNT_TYPE,
                QMT_ACCOUNT_ID,
                order_code,
                QMT_MARKET_PRICE_TYPE,
                order["limit_price"],
                int(order["order_qty"]),
                QMT_QUICK_TRADE,
                ContextInfo,
            )
        else:
            result = passorder(
                QMT_BUY_OPEN_OP,
                QMT_OPTION_ACCOUNT_TYPE,
                QMT_ACCOUNT_ID,
                order_code,
                QMT_MARKET_PRICE_TYPE,
                order["limit_price"],
                int(order["order_qty"]),
                ContextInfo,
            )
        log("PASSORDER_RETURN", repr(result))
        log_trade_detail_snapshots(ContextInfo, "after_passorder")
        return True
    except Exception as exc:
        log("PASSORDER_ERROR", repr(exc))
        log_trade_detail_snapshots(ContextInfo, "after_passorder_error")
        return False


def read_trade_detail(kind):
    attempts = [
        (QMT_ACCOUNT_ID, QMT_OPTION_ACCOUNT_TYPE, kind),
        (QMT_ACCOUNT_ID, QMT_OPTION_ACCOUNT_TYPE, kind, "qmt_liq_order_test"),
    ]
    for args in attempts:
        try:
            return True, get_trade_detail_data(*args)
        except Exception as exc:
            last_error = repr(exc)
    return False, last_error


def log_trade_detail_snapshots(ContextInfo, label):
    if not LOG_TRADE_DETAIL_AFTER_ORDER:
        return
    for kind in ["order", "deal", "position", "account"]:
        ok, data = read_trade_detail(kind)
        log("TRADE_DETAIL", label, "kind=", kind, "ok=", ok, "data=", short_repr(data))


def should_scan(ContextInfo, time_text):
    if not in_scan_window(time_text):
        return False
    wall_key = wall_clock_key()
    last_key = getattr(ContextInfo, "_liq_order_last_wall", "")
    if last_key == "":
        ContextInfo._liq_order_last_wall = wall_key
        return True
    last_sec = safe_int(last_key[-2:])
    now_sec = safe_int(wall_key[-2:])
    last_min = safe_int(last_key[:4])
    now_min = safe_int(wall_key[:4])
    elapsed = (now_min - last_min) * 60 + (now_sec - last_sec)
    if elapsed < 0:
        elapsed += 3600
    if elapsed >= SCAN_INTERVAL_SECONDS:
        ContextInfo._liq_order_last_wall = wall_key
        return True
    return False


def init(ContextInfo):
    ContextInfo.set_universe([UNDERLYING_CODE, TARGET_OPTION_CODE])
    ContextInfo._liq_order_last_wall = ""
    ContextInfo._liq_order_submitted_qty = 0
    ContextInfo._liq_order_done = False
    log(
        "INIT",
        BUILD_ID,
        "period=", getattr(ContextInfo, "period", None),
        "code=", TARGET_OPTION_CODE,
        "planned_qty=", PLANNED_QTY,
        "armed=", TEST_ORDER_ARMED,
        "continue_pending=", CONTINUE_PENDING_AFTER_ORDER,
        "account=", masked_account(QMT_ACCOUNT_ID),
    )


def handlebar(ContextInfo):
    global GLOBAL_ORDER_DONE
    global GLOBAL_SUBMITTED_QTY
    now_text, current_date, time_text = current_datetime(ContextInfo)
    if len(time_text) != 4:
        return
    if GLOBAL_ORDER_DONE:
        return
    if getattr(ContextInfo, "_liq_order_done", False):
        return
    if not should_scan(ContextInfo, time_text):
        return

    submitted = max(safe_int(getattr(ContextInfo, "_liq_order_submitted_qty", 0)), safe_int(GLOBAL_SUBMITTED_QTY))
    remaining_plan = max(0, safe_int(PLANNED_QTY) - submitted)
    if remaining_plan <= 0:
        ContextInfo._liq_order_done = True
        return

    order = build_liquidity_order(ContextInfo, TARGET_OPTION_CODE, remaining_plan)
    if not order.get("ok"):
        log("ORDER_WAIT", "bar=", now_text, "reason=", order.get("reason"), "remaining_plan=", remaining_plan, "extra=", order.get("keys"))
        return

    log(
        "ORDER_PLAN",
        "bar=", now_text,
        "code=", TARGET_OPTION_CODE,
        "planned_total=", PLANNED_QTY,
        "remaining_plan=", remaining_plan,
        "order_qty=", order["order_qty"],
        "pending_after_order=", max(0, remaining_plan - order["order_qty"]),
        "limit=", order["limit_price"],
        "bid1=", order["bid1"],
        "ask1=", order["ask1"],
        "liq_qty=", order["liq_qty"],
        "liq_avg=", round(order["liq_avg"], 6) if order["liq_avg"] is not None else None,
        "liq_worst=", order["liq_worst"],
        "bid_levels=", fmt_levels(order["bid_levels"]),
        "ask_levels=", fmt_levels(order["ask_levels"]),
        "armed=", TEST_ORDER_ARMED,
    )

    if not TEST_ORDER_ARMED:
        log("DRY_RUN_NO_ORDER", "set_TEST_ORDER_ARMED_True_to_send_real_order")
        return

    if submit_buy_open(ContextInfo, order):
        ContextInfo._liq_order_submitted_qty = submitted + order["order_qty"]
        GLOBAL_SUBMITTED_QTY = ContextInfo._liq_order_submitted_qty
        log(
            "ORDER_TEST_SUMMARY",
            "bar=", now_text,
            "code=", TARGET_OPTION_CODE,
            "planned_total=", PLANNED_QTY,
            "submitted_qty=", ContextInfo._liq_order_submitted_qty,
            "pending_total=", max(0, safe_int(PLANNED_QTY) - ContextInfo._liq_order_submitted_qty),
            "limit=", order["limit_price"],
            "expected_avg=", round(order["liq_avg"], 6) if order["liq_avg"] is not None else None,
            "expected_worst=", order["liq_worst"],
            "expected_amount=", round((order.get("liq_avg") or order["limit_price"]) * order["order_qty"] * CONTRACT_MULTIPLIER, 2),
            "expected_fee=", round(order["order_qty"] * FEE_PER_CONTRACT_PER_SIDE, 2),
            "note=", "compare_with_QMT_deal_panel",
        )
        if not CONTINUE_PENDING_AFTER_ORDER:
            ContextInfo._liq_order_done = True
            GLOBAL_ORDER_DONE = True
            log("DONE_AFTER_ONE_ORDER", "submitted_qty=", ContextInfo._liq_order_submitted_qty, "global_done=", GLOBAL_ORDER_DONE, "note=", "check_QMT_order_and_fill_panel")
        else:
            log("ORDER_ACCEPTED_CONTINUE", "submitted_qty=", ContextInfo._liq_order_submitted_qty, "remaining_plan=", max(0, safe_int(PLANNED_QTY) - ContextInfo._liq_order_submitted_qty))
