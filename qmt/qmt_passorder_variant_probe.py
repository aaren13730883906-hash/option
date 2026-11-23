# -*- coding: utf-8 -*-
"""QMT passorder variant probe for stock options.

ASCII-only. Run in QMT on a 1-minute chart.

Purpose:
- test exactly one passorder parameter variant;
- send at most one buy-open order when TEST_ORDER_ARMED is True;
- immediately read latest ORDER object and print reject/accept details.

Keep TEST_ORDER_ARMED False until you intentionally test one contract.
"""

from __future__ import print_function

try:
    from qmt_local_config import (
        PASSORDER_PROBE_ARMED,
        QMT_ACCOUNT_ID as LOCAL_QMT_ACCOUNT_ID,
    )
except Exception:
    PASSORDER_PROBE_ARMED = False
    LOCAL_QMT_ACCOUNT_ID = ""


BUILD_ID = "QMT_PASSORDER_VARIANT_PROBE_20260804_R2_ARMED_VARIANT1"

ACCOUNT_ID = LOCAL_QMT_ACCOUNT_ID
ACCOUNT_TYPE_INT = 1101
ACCOUNT_TYPE_TEXT = "STOCK_OPTION"
STRATEGY_NAME = "kcb_1032_live_sim"

TARGET_CODE = "10012156.SHO"
TARGET_PRICE = 0.1125
TARGET_QTY = 1

# WARNING: True means this probe will send ONE real/sim buy-open test order.
TEST_ORDER_ARMED = PASSORDER_PROBE_ARMED

# 1 = root code + price_type 11 + quickTrade + ContextInfo.
# This tests whether removing the .SHO suffix fixes the QMT rejection.
VARIANT_INDEX = 1

BUY_OPEN_OP = 50
QUICK_TRADE = 1

UNDERLYINGS = ["588000.SH"]

VARIANTS = [
    {
        "name": "current_suffix_pt11_quick_ctx",
        "code_mode": "suffix",
        "price_type": 11,
        "price_mode": "limit",
        "call_style": "quick_ctx",
    },
    {
        "name": "root_pt11_quick_ctx",
        "code_mode": "root",
        "price_type": 11,
        "price_mode": "limit",
        "call_style": "quick_ctx",
    },
    {
        "name": "root_pt5_price_minus1_ctx",
        "code_mode": "root",
        "price_type": 5,
        "price_mode": "minus1",
        "call_style": "ctx",
    },
    {
        "name": "suffix_pt5_price_minus1_ctx",
        "code_mode": "suffix",
        "price_type": 5,
        "price_mode": "minus1",
        "call_style": "ctx",
    },
]

RUNTIME_DONE = False


def log(*items):
    print("[QMT_PASSORDER_VARIANT]", *items)


def safe_int(value, default=0):
    try:
        return int(float(str(value).replace("-", "").replace("/", "")))
    except Exception:
        return default


def short_repr(value, max_len=600):
    text = repr(value)
    if len(text) > max_len:
        return text[:max_len] + "...TRUNCATED"
    return text


def current_datetime(ContextInfo):
    try:
        tag = ContextInfo.get_bar_timetag(ContextInfo.barpos)
        text = timetag_to_datetime(tag, "%Y%m%d%H%M%S")
        return text, safe_int(text[:8]), text[8:12]
    except Exception as exc:
        return "ERROR:%s" % repr(exc), 0, ""


def order_code_for_variant(variant):
    if variant.get("code_mode") == "root":
        return str(TARGET_CODE).split(".")[0]
    return str(TARGET_CODE)


def order_price_for_variant(variant):
    if variant.get("price_mode") == "minus1":
        return -1
    return TARGET_PRICE


def get_obj_fields(obj):
    if obj is None:
        return "None"
    fields = [
        "m_strInstrumentID",
        "m_strExchangeID",
        "m_strOrderSysID",
        "m_strOrderRef",
        "m_strCancelInfo",
        "m_strStatusMsg",
        "m_strErrMsg",
        "m_strErrorMsg",
        "m_strOrderStatus",
        "m_strOrderSubmitStatus",
        "m_nDirection",
        "m_nOffsetFlag",
        "m_nOrderPriceType",
        "m_nOrderStatus",
        "m_nOrderSubmitStatus",
        "m_nVolumeTotalOriginal",
        "m_nVolumeTraded",
        "m_nVolumeTotal",
        "m_dLimitPrice",
        "m_dTradePrice",
        "m_dTradeAmount",
        "m_strInsertDate",
        "m_strInsertTime",
        "m_strTradeDate",
        "m_strTradeTime",
    ]
    output = []
    for name in fields:
        try:
            output.append("%s=%s" % (name, short_repr(getattr(obj, name), 120)))
        except Exception:
            pass
    return " ".join(output)


def read_last(datatype, label):
    try:
        order_id = get_last_order_id(ACCOUNT_ID, ACCOUNT_TYPE_TEXT, datatype)
        log("LAST_ID", label, datatype, "all", short_repr(order_id))
    except Exception as exc:
        log("LAST_ID_ERROR", label, datatype, "all", repr(exc))
        order_id = None
    if order_id is None or str(order_id) == "-1":
        try:
            order_id = get_last_order_id(ACCOUNT_ID, ACCOUNT_TYPE_TEXT, datatype, STRATEGY_NAME)
            log("LAST_ID", label, datatype, "strategy", short_repr(order_id))
        except Exception as exc:
            log("LAST_ID_ERROR", label, datatype, "strategy", repr(exc))
            return
    if order_id is None or str(order_id) == "-1":
        log("NO_LAST_ID", label, datatype)
        return
    try:
        obj = get_value_by_order_id(str(order_id), ACCOUNT_ID, ACCOUNT_TYPE_TEXT, datatype)
        log("VALUE_BY_ID", label, datatype, "id=", short_repr(order_id), "obj=", short_repr(obj), "fields=", get_obj_fields(obj))
    except Exception as exc:
        log("VALUE_BY_ID_ERROR", label, datatype, "id=", short_repr(order_id), "error=", repr(exc))


def run_probe(ContextInfo, reason):
    index = safe_int(VARIANT_INDEX)
    if index < 0 or index >= len(VARIANTS):
        log("BAD_VARIANT_INDEX", VARIANT_INDEX, "count=", len(VARIANTS))
        return
    variant = VARIANTS[index]
    code = order_code_for_variant(variant)
    price = order_price_for_variant(variant)
    log(
        "RUN",
        reason,
        "build=", BUILD_ID,
        "armed=", TEST_ORDER_ARMED,
        "variant_index=", index,
        "variant=", variant.get("name"),
        "account=", ACCOUNT_ID[:3] + "****" + ACCOUNT_ID[-3:],
        "code=", code,
        "price_type=", variant.get("price_type"),
        "price=", price,
        "qty=", TARGET_QTY,
    )
    if not TEST_ORDER_ARMED:
        log("DRY_RUN_NO_ORDER", "set_TEST_ORDER_ARMED_True_to_send_one_test_order")
        read_last("ORDER", "before_or_dry")
        read_last("DEAL", "before_or_dry")
        return
    try:
        if variant.get("call_style") == "quick_ctx":
            result = passorder(
                BUY_OPEN_OP,
                ACCOUNT_TYPE_INT,
                ACCOUNT_ID,
                code,
                variant.get("price_type"),
                price,
                int(TARGET_QTY),
                QUICK_TRADE,
                ContextInfo,
            )
        else:
            result = passorder(
                BUY_OPEN_OP,
                ACCOUNT_TYPE_INT,
                ACCOUNT_ID,
                code,
                variant.get("price_type"),
                price,
                int(TARGET_QTY),
                ContextInfo,
            )
        log("PASSORDER_RETURN", short_repr(result))
    except Exception as exc:
        log("PASSORDER_ERROR", repr(exc))
    read_last("ORDER", "after_passorder")
    read_last("DEAL", "after_passorder")


def init(ContextInfo):
    ContextInfo.set_universe(UNDERLYINGS)
    ContextInfo._variant_probe_done = False
    log("INIT", BUILD_ID)


def handlebar(ContextInfo):
    global RUNTIME_DONE
    now_text, unused_date, unused_time = current_datetime(ContextInfo)
    if RUNTIME_DONE or getattr(ContextInfo, "_variant_probe_done", False):
        return
    RUNTIME_DONE = True
    ContextInfo._variant_probe_done = True
    log("TIME", now_text)
    run_probe(ContextInfo, "first_bar")
