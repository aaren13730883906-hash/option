# -*- coding: utf-8 -*-
"""QMT immediate order/deal confirmation probe.

Run this in QMT to verify whether these APIs work right now:
- get_last_order_id(account, "STOCK_OPTION", "ORDER"/"DEAL", strategy_name)
- get_value_by_order_id(order_id, account, "STOCK_OPTION", "ORDER"/"DEAL")

It does NOT send orders. It only reads the latest option order/deal objects.
If the log prefix is not [QMT_CONFIRM_NOW], you are not running this probe.
"""

from __future__ import print_function

try:
    from qmt_local_config import QMT_ACCOUNT_ID as LOCAL_QMT_ACCOUNT_ID
except Exception:
    LOCAL_QMT_ACCOUNT_ID = ""

ACCOUNT_ID = LOCAL_QMT_ACCOUNT_ID
ACCOUNT_TYPE_TEXT = "STOCK_OPTION"
STRATEGY_NAME = "kcb_1032_live_sim"

UNDERLYINGS = ["588000.SH"]


def log(*items):
    print("[QMT_CONFIRM_NOW]", *items)


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


def obj_fields(obj):
    fields = [
        "m_strInstrumentID",
        "m_strExchangeID",
        "m_strOrderSysID",
        "m_strOrderRef",
        "m_strOrderStatus",
        "m_strStatusMsg",
        "m_strCancelTime",
        "m_strErrorMsg",
        "m_strOrderLocalID",
        "m_strOrderSubmitStatus",
        "m_strDirection",
        "m_strOffsetFlag",
        "m_nDirection",
        "m_nOffsetFlag",
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
            output.append("%s=%s" % (name, short_repr(getattr(obj, name), 100)))
        except Exception:
            pass
    return " ".join(output)


def dump_m_fields(obj, max_fields=120):
    names = []
    try:
        names = [name for name in dir(obj) if str(name).startswith("m_")]
    except Exception as exc:
        return "DIR_ERROR:%s" % repr(exc)
    output = []
    for name in names[:max_fields]:
        try:
            output.append("%s=%s" % (name, short_repr(getattr(obj, name), 120)))
        except Exception as exc:
            output.append("%s=ERR:%s" % (name, repr(exc)))
    return " ".join(output)


def query_one(datatype, use_strategy):
    label = datatype + ("_STRATEGY" if use_strategy else "_ALL")
    try:
        if use_strategy:
            order_id = get_last_order_id(ACCOUNT_ID, ACCOUNT_TYPE_TEXT, datatype, STRATEGY_NAME)
        else:
            order_id = get_last_order_id(ACCOUNT_ID, ACCOUNT_TYPE_TEXT, datatype)
        log("LAST_ID", label, "id=", short_repr(order_id))
    except Exception as exc:
        log("LAST_ID_ERROR", label, repr(exc))
        return
    if order_id is None or str(order_id) == "-1":
        log("NO_LAST_ID", label)
        return
    try:
        obj = get_value_by_order_id(str(order_id), ACCOUNT_ID, ACCOUNT_TYPE_TEXT, datatype)
        log("VALUE_BY_ID", label, "id=", short_repr(order_id), "obj=", short_repr(obj), "fields=", obj_fields(obj))
        log("VALUE_BY_ID_DUMP", label, "id=", short_repr(order_id), "m_fields=", dump_m_fields(obj))
    except Exception as exc:
        log("VALUE_BY_ID_ERROR", label, "id=", short_repr(order_id), "error=", repr(exc))


def run_probe(reason):
    log("RUN", reason, "account=", ACCOUNT_ID[:3] + "****" + ACCOUNT_ID[-3:], "account_type=", ACCOUNT_TYPE_TEXT, "strategy=", STRATEGY_NAME)
    for datatype in ["ORDER", "DEAL"]:
        query_one(datatype, False)
        query_one(datatype, True)


def init(ContextInfo):
    ContextInfo.set_universe(UNDERLYINGS)
    ContextInfo._confirm_now_done = False
    log("INIT", "probe_only_no_orders")
    run_probe("init")


def handlebar(ContextInfo):
    now_text, unused_date, unused_time = current_datetime(ContextInfo)
    if getattr(ContextInfo, "_confirm_now_done", False):
        return
    ContextInfo._confirm_now_done = True
    log("TIME", now_text)
    run_probe("first_bar")
