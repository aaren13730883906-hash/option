# -*- coding: utf-8 -*-
"""Verify the two local-reference May 2026 option trades in QMT.

Run as a 1-minute backtest from 2026-05-15 through 2026-05-25.
Use 588000 as the benchmark.  This script never sends orders.
The source contains ASCII characters only for QMT compatibility.
"""

from __future__ import print_function


UNDERLYINGS = ["588000.SH", "159915.SZ"]
TARGETS = {
    20260520: {
        "code": "10011558.SHO",
        "times": {
            "0930": {
                "open": 0.0570,
                "high": 0.0570,
                "low": 0.0570,
                "close": 0.0570,
            },
            "0941": {
                "open": 0.0659,
                "high": 0.0674,
                "low": 0.0650,
                "close": 0.0665,
            },
            "0945": {
                "open": 0.0636,
                "high": 0.0657,
                "low": 0.0630,
                "close": 0.0648,
            },
            "1455": {
                "open": 0.0764,
                "high": 0.0768,
                "low": 0.0762,
                "close": 0.0768,
            },
        },
    },
    20260525: {
        "code": "10011603.SHO",
        "times": {
            "0930": None,
            "0943": {
                "open": 0.0582,
                "high": 0.0595,
                "low": 0.0579,
                "close": 0.0590,
            },
            "0945": {
                "open": 0.0605,
                "high": 0.0606,
                "low": 0.0574,
                "close": 0.0581,
            },
            "1322": {
                "open": 0.0789,
                "high": 0.0795,
                "low": 0.0765,
                "close": 0.0769,
            },
            "1455": {
                "open": 0.0853,
                "high": 0.0853,
                "low": 0.0848,
                "close": 0.0852,
            },
        },
    },
}
FIELDS = ["open", "high", "low", "close", "volume", "amount"]
PRICE_TOLERANCE = 0.000001


def safe_float(value, default=None):
    try:
        return float(value)
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


def recursive_number(value, code, field_name):
    if isinstance(value, (int, float)):
        return safe_float(value)
    if not isinstance(value, dict):
        return None
    for key in [field_name, code, code.split(".")[0]]:
        if key in value:
            found = recursive_number(value.get(key), code, field_name)
            if found is not None:
                return found
    for nested in value.values():
        if isinstance(nested, dict):
            found = recursive_number(nested, code, field_name)
            if found is not None:
                return found
    return None


def read_field(ContextInfo, code, field_name):
    try:
        raw = ContextInfo.get_market_data(
            [field_name],
            stock_code=[code],
            period=ContextInfo.period,
        )
        return recursive_number(raw, code, field_name), repr(raw)
    except Exception as exc:
        return None, "ERROR:%s" % repr(exc)


def print_detail(ContextInfo, current_date, code):
    try:
        detail = ContextInfo.get_option_detail_data(code)
        print(
            "[V12_PARITY] DETAIL",
            current_date,
            code,
            repr(detail),
        )
    except Exception as exc:
        print(
            "[V12_PARITY] DETAIL_ERROR",
            current_date,
            code,
            repr(exc),
        )


def check_target_bar(
    ContextInfo,
    now_text,
    code,
    expected,
):
    values = {}
    raw_values = {}
    for field_name in FIELDS:
        value, raw = read_field(ContextInfo, code, field_name)
        values[field_name] = value
        raw_values[field_name] = raw

    available = (
        values.get("close") is not None
        and values.get("close") > 0
    )
    matches = available
    if expected is not None and available:
        for field_name in ["open", "high", "low", "close"]:
            actual = values.get(field_name)
            target = expected.get(field_name)
            if (
                actual is None
                or abs(actual - target) > PRICE_TOLERANCE
            ):
                matches = False

    print(
        "[V12_PARITY] BAR",
        now_text,
        code,
        "available=",
        available,
        "matches_local=",
        matches if expected is not None else "not_checked",
        "open=",
        values.get("open"),
        "high=",
        values.get("high"),
        "low=",
        values.get("low"),
        "close=",
        values.get("close"),
        "volume=",
        values.get("volume"),
        "amount=",
        values.get("amount"),
    )
    if not available:
        print(
            "[V12_PARITY] BAR_RAW",
            now_text,
            code,
            repr(raw_values),
        )
    return available, matches


def print_summary(ContextInfo):
    print(
        "[V12_PARITY] SUMMARY",
        "target_bars=",
        ContextInfo.parity_target_bars,
        "available_bars=",
        ContextInfo.parity_available_bars,
        "matching_bars=",
        ContextInfo.parity_matching_bars,
    )
    if ContextInfo.parity_available_bars == 0:
        print(
            "[V12_PARITY] RESULT",
            "QMT_EXPIRED_OPTION_DATA_UNAVAILABLE",
        )
    elif (
        ContextInfo.parity_matching_bars
        == ContextInfo.parity_target_bars
    ):
        print(
            "[V12_PARITY] RESULT",
            "QMT_DATA_MATCHES_LOCAL_REFERENCE",
        )
    else:
        print(
            "[V12_PARITY] RESULT",
            "QMT_DATA_AVAILABLE_BUT_DIFFERS_FROM_LOCAL",
        )
    print("[V12_PARITY] COMPLETE_COPY_ALL_LOGS_TO_CODEX")


def init(ContextInfo):
    ContextInfo.parity_detail_dates = {}
    ContextInfo.parity_target_bars = 0
    ContextInfo.parity_available_bars = 0
    ContextInfo.parity_matching_bars = 0
    ContextInfo.parity_summary_printed = False
    ContextInfo.set_universe(UNDERLYINGS)
    print("[V12_PARITY] INIT period=", getattr(ContextInfo, "period", None))
    print("[V12_PARITY] REQUIRED_RANGE 2026-05-15 to 2026-05-25")
    print("[V12_PARITY] BENCHMARK 588000")
    print("[V12_PARITY] NO_ORDERS_WILL_BE_SENT")


def handlebar(ContextInfo):
    now_text, current_date, time_text = current_datetime(ContextInfo)
    target = TARGETS.get(current_date)
    if target is not None:
        code = target["code"]
        if not ContextInfo.parity_detail_dates.get(current_date):
            ContextInfo.parity_detail_dates[current_date] = True
            print_detail(ContextInfo, current_date, code)
        expected = target["times"].get(time_text)
        if time_text in target["times"]:
            if expected is not None:
                ContextInfo.parity_target_bars += 1
            available, matches = check_target_bar(
                ContextInfo,
                now_text,
                code,
                expected,
            )
            if available:
                ContextInfo.parity_available_bars += 1
            if expected is not None and matches:
                ContextInfo.parity_matching_bars += 1

    if (
        current_date == 20260525
        and time_text >= "1455"
        and not ContextInfo.parity_summary_printed
    ):
        ContextInfo.parity_summary_printed = True
        print_summary(ContextInfo)
