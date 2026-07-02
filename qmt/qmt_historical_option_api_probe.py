# -*- coding: utf-8 -*-
"""Probe QMT historical option-list APIs.

Run on any available 1-minute backtest date.
This script never sends orders and contains ASCII characters only.
"""

from __future__ import print_function


UNDERLYINGS = ["588000.SH", "159915.SZ"]
MARKETS = ["SHO", "SZO"]
TEST_DATES = [
    "20250723",
    "20251110",
    "20251224",
    "20260309",
    "20260422",
    "20260525",
]
KNOWN_EXPIRED_CODES = ["10009568.SHO", "90005721.SZO"]
HEAD_LIMIT = 10


def safe_list(value):
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def call_option_list(ContextInfo, undl_code, date_text, isavailable):
    try:
        value = ContextInfo.get_option_list(
            undl_code,
            date_text,
            "",
            isavailable,
        )
        items = safe_list(value)
        print(
            "[QMT_HIST_API] OPTION_LIST",
            undl_code,
            date_text,
            "isavailable=",
            isavailable,
            "count=",
            len(items),
            "head=",
            repr(items[:HEAD_LIMIT]),
        )
        return items
    except Exception as exc:
        print(
            "[QMT_HIST_API] OPTION_LIST_ERROR",
            undl_code,
            date_text,
            "isavailable=",
            isavailable,
            repr(exc),
        )
        return []


def call_his_contract_list(ContextInfo, market):
    try:
        value = ContextInfo.get_his_contract_list(market)
        items = safe_list(value)
        print(
            "[QMT_HIST_API] HIS_CONTRACT_LIST",
            market,
            "count=",
            len(items),
            "head=",
            repr(items[:HEAD_LIMIT]),
        )
        return items
    except Exception as exc:
        print(
            "[QMT_HIST_API] HIS_CONTRACT_LIST_ERROR",
            market,
            repr(exc),
        )
        return []


def init(ContextInfo):
    ContextInfo.hist_api_probe_done = False
    ContextInfo.set_universe(UNDERLYINGS)
    print("[QMT_HIST_API] INIT period=", getattr(ContextInfo, "period", None))
    print("[QMT_HIST_API] NO_ORDERS_WILL_BE_SENT")


def handlebar(ContextInfo):
    if ContextInfo.hist_api_probe_done:
        return
    ContextInfo.hist_api_probe_done = True

    print(
        "[QMT_HIST_API] HAS_GET_OPTION_LIST",
        callable(getattr(ContextInfo, "get_option_list", None)),
    )
    print(
        "[QMT_HIST_API] HAS_GET_HIS_CONTRACT_LIST",
        callable(getattr(ContextInfo, "get_his_contract_list", None)),
    )

    historical_by_market = {}
    for market in MARKETS:
        historical_by_market[market] = call_his_contract_list(
            ContextInfo,
            market,
        )

    for known_code in KNOWN_EXPIRED_CODES:
        market = known_code.split(".")[-1]
        print(
            "[QMT_HIST_API] KNOWN_CODE_IN_HISTORY",
            known_code,
            known_code in historical_by_market.get(market, []),
        )
        try:
            detail = ContextInfo.get_option_detail_data(known_code)
            print(
                "[QMT_HIST_API] KNOWN_DETAIL",
                known_code,
                repr(detail),
            )
        except Exception as exc:
            print(
                "[QMT_HIST_API] KNOWN_DETAIL_ERROR",
                known_code,
                repr(exc),
            )

    for date_text in TEST_DATES:
        for undl_code in UNDERLYINGS:
            call_option_list(ContextInfo, undl_code, date_text, True)
            call_option_list(ContextInfo, undl_code, date_text, False)

    print("[QMT_HIST_API] COMPLETE_COPY_ALL_LOGS_TO_CODEX")
