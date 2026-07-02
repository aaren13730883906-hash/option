# -*- coding: utf-8 -*-
"""QMT historical ETF-option capability probe.

Run this script in QMT as a 1-minute backtest over 2025-07-23.
It never sends orders. Copy the complete QMT log back to Codex.

The script intentionally uses only the Python 3.6 standard library and never
calls get_market_data with count.
"""

from __future__ import print_function

import datetime


UNDERLYINGS = ["588000.SH", "159915.SZ"]
EXPECTED_DATE = 20250723

# Both contracts were alive on 2025-07-23 in the 320.23% reference backtest.
# Multiple suffix forms are tried because the Shenzhen option suffix has not
# yet been verified in this QMT installation.
HISTORICAL_TEST_CODES = {
    "588000.SH": ["10009568.SHO", "10009568.SH", "10009568"],
    "159915.SZ": ["90005721.SZO", "90005721.SZ", "90005721"],
}

PROBE_FIELDS = ["open", "high", "low", "close", "volume", "amount"]
MAX_DETAIL_PRINT = 3
PRICE_OBSERVE_BARS = 30


def safe_int(value, default=0):
    try:
        text = str(value).replace("-", "").replace("/", "")
        return int(float(text))
    except Exception:
        return default


def yyyymmdd_to_date(value):
    number = safe_int(value)
    if number <= 0:
        return None
    text = str(number)
    if len(text) != 8:
        return None
    try:
        return datetime.date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except Exception:
        return None


def days_between(start_yyyymmdd, end_yyyymmdd):
    start = yyyymmdd_to_date(start_yyyymmdd)
    end = yyyymmdd_to_date(end_yyyymmdd)
    if start is None or end is None:
        return None
    return (end - start).days


def scalar_from_market_data(value, field_name, code):
    """Flatten the common QMT return shapes without pandas/numpy."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        candidates = [
            value.get(code),
            value.get(code.split(".")[0]),
            value.get(field_name),
        ]
        for item in candidates:
            if isinstance(item, (int, float)):
                return float(item)
            if isinstance(item, dict):
                for key in [field_name, code, code.split(".")[0]]:
                    nested = item.get(key)
                    if isinstance(nested, (int, float)):
                        return float(nested)
        for item in value.values():
            if isinstance(item, (int, float)):
                return float(item)
            if isinstance(item, dict):
                for nested in item.values():
                    if isinstance(nested, (int, float)):
                        return float(nested)
    try:
        return float(value)
    except Exception:
        return None


def read_current_field(ContextInfo, code, field_name):
    try:
        raw = ContextInfo.get_market_data(
            [field_name],
            stock_code=[code],
            period=ContextInfo.period,
        )
        return scalar_from_market_data(raw, field_name, code), repr(raw)
    except Exception as exc:
        return None, "ERROR: %s" % repr(exc)


def current_datetime(ContextInfo):
    try:
        tag = ContextInfo.get_bar_timetag(ContextInfo.barpos)
        text = timetag_to_datetime(tag, "%Y%m%d%H%M%S")
        return text, safe_int(text[:8])
    except Exception as exc:
        return "ERROR:%s" % repr(exc), 0


def detail_dates_valid(detail, current_date):
    open_date = safe_int(detail.get("OpenDate", 0))
    expire_date = safe_int(detail.get("ExpireDate", 0))
    return open_date <= current_date <= expire_date


def print_underlying_probe(ContextInfo, undl_code, current_date):
    print("\n[QMT_PROBE] UNDERLYING", undl_code, "DATE", current_date)
    try:
        option_list = ContextInfo.get_option_undl_data(undl_code)
    except Exception as exc:
        print("[QMT_PROBE] OPTION_UNIVERSE_ERROR", undl_code, repr(exc))
        return

    if option_list is None:
        option_list = []
    print("[QMT_PROBE] OPTION_UNIVERSE_COUNT", undl_code, len(option_list))
    print("[QMT_PROBE] OPTION_UNIVERSE_HEAD", undl_code, list(option_list[:10]))

    active_count = 0
    dte_10_35_count = 0
    type_counts = {}
    printed = 0
    for code in option_list:
        try:
            detail = ContextInfo.get_option_detail_data(code)
        except Exception as exc:
            if printed < MAX_DETAIL_PRINT:
                print("[QMT_PROBE] DETAIL_ERROR", code, repr(exc))
            continue
        if not isinstance(detail, dict):
            continue
        if printed < MAX_DETAIL_PRINT:
            print("[QMT_PROBE] DETAIL", code, repr(detail))
            printed += 1
        opt_type = str(detail.get("optType", ""))
        type_counts[opt_type] = type_counts.get(opt_type, 0) + 1
        if detail_dates_valid(detail, current_date):
            active_count += 1
            dte = days_between(current_date, detail.get("ExpireDate", 0))
            if dte is not None and 10 <= dte <= 35:
                dte_10_35_count += 1

    print("[QMT_PROBE] OPTION_TYPE_VALUES", undl_code, repr(type_counts))
    print("[QMT_PROBE] ACTIVE_ON_DATE", undl_code, active_count)
    print("[QMT_PROBE] ACTIVE_DTE_10_35", undl_code, dte_10_35_count)

    for field_name in PROBE_FIELDS:
        value, raw = read_current_field(ContextInfo, undl_code, field_name)
        print(
            "[QMT_PROBE] UNDERLYING_FIELD",
            undl_code,
            field_name,
            value,
            raw,
        )


def print_historical_contract_probe(ContextInfo, undl_code):
    for code in HISTORICAL_TEST_CODES.get(undl_code, []):
        try:
            detail = ContextInfo.get_option_detail_data(code)
            print("[QMT_PROBE] HIST_DETAIL_OK", undl_code, code, repr(detail))
        except Exception as exc:
            print("[QMT_PROBE] HIST_DETAIL_FAIL", undl_code, code, repr(exc))
            detail = None

        close_value, close_raw = read_current_field(ContextInfo, code, "close")
        volume_value, volume_raw = read_current_field(ContextInfo, code, "volume")
        print(
            "[QMT_PROBE] HIST_MARKET",
            undl_code,
            code,
            "close=",
            close_value,
            close_raw,
            "volume=",
            volume_value,
            volume_raw,
        )
        if close_value is not None and close_value > 0:
            ContextInfo.probe_selected_code[undl_code] = code
            return


def init(ContextInfo):
    ContextInfo.probe_done = False
    ContextInfo.probe_bar_count = 0
    ContextInfo.probe_selected_code = {}
    ContextInfo.probe_prices = {}
    ContextInfo.set_universe(UNDERLYINGS)
    print("[QMT_PROBE] INIT period=", getattr(ContextInfo, "period", None))
    print("[QMT_PROBE] REQUIRED_BACKTEST_RANGE 2025-07-23 09:30-15:00")
    print("[QMT_PROBE] NO_ORDERS_WILL_BE_SENT")


def handlebar(ContextInfo):
    now_text, current_date = current_datetime(ContextInfo)
    ContextInfo.probe_bar_count += 1

    if not ContextInfo.probe_done:
        print("[QMT_PROBE] FIRST_BAR", now_text, "barpos=", ContextInfo.barpos)
        if current_date != EXPECTED_DATE:
            print(
                "[QMT_PROBE] FATAL_WRONG_BACKTEST_DATE",
                "expected=",
                EXPECTED_DATE,
                "actual=",
                current_date,
            )
            print(
                "[QMT_PROBE] STOP_AND_RERUN",
                "set both backtest dates to 2025-07-23",
            )
            ContextInfo.probe_done = True
            return
        for undl_code in UNDERLYINGS:
            print_underlying_probe(ContextInfo, undl_code, current_date)
            print_historical_contract_probe(ContextInfo, undl_code)
        ContextInfo.probe_done = True

    if ContextInfo.probe_bar_count <= PRICE_OBSERVE_BARS:
        for undl_code, code in ContextInfo.probe_selected_code.items():
            price, raw = read_current_field(ContextInfo, code, "close")
            values = ContextInfo.probe_prices.setdefault(code, [])
            values.append(price)
            print("[QMT_PROBE] PRICE_OBSERVE", now_text, code, price, raw)

    if ContextInfo.probe_bar_count == PRICE_OBSERVE_BARS:
        for code, values in ContextInfo.probe_prices.items():
            clean = [value for value in values if value is not None]
            unique = len(set(clean))
            print(
                "[QMT_PROBE] PRICE_CHANGE_SUMMARY",
                code,
                "bars=",
                len(clean),
                "unique_prices=",
                unique,
                "first=",
                clean[0] if clean else None,
                "last=",
                clean[-1] if clean else None,
            )
        print("[QMT_PROBE] COMPLETE_COPY_ALL_LOG_LINES_TO_CODEX")
