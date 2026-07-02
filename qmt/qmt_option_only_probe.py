# -*- coding: utf-8 -*-
"""Probe expired option minute data directly in QMT.

Run as a 1-minute backtest on 2025-07-23 only.
This script never sends orders and contains ASCII characters only.
"""

from __future__ import print_function


EXPECTED_DATE = 20250723
OPTION_CODES = ["10009568.SHO", "90005721.SZO"]
FIELDS = ["open", "high", "low", "close", "volume", "amount"]
OBSERVE_BARS = 30


def safe_int(value, default=0):
    try:
        return int(float(str(value).replace("-", "").replace("/", "")))
    except Exception:
        return default


def scalar_from_market_data(value, field_name, code):
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


def read_field(ContextInfo, code, field_name):
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


def init(ContextInfo):
    ContextInfo.probe_bar_count = 0
    ContextInfo.probe_stopped = False
    ContextInfo.probe_prices = {}
    ContextInfo.set_universe(OPTION_CODES)
    print("[QMT_OPTION_ONLY] INIT period=", getattr(ContextInfo, "period", None))
    print("[QMT_OPTION_ONLY] UNIVERSE", repr(OPTION_CODES))
    print("[QMT_OPTION_ONLY] REQUIRED_RANGE 2025-07-23 09:30-15:00")
    print("[QMT_OPTION_ONLY] NO_ORDERS_WILL_BE_SENT")


def handlebar(ContextInfo):
    if ContextInfo.probe_stopped:
        return

    now_text, current_date = current_datetime(ContextInfo)
    ContextInfo.probe_bar_count += 1

    if ContextInfo.probe_bar_count == 1:
        print(
            "[QMT_OPTION_ONLY] FIRST_BAR",
            now_text,
            "barpos=",
            ContextInfo.barpos,
        )
        if current_date != EXPECTED_DATE:
            print(
                "[QMT_OPTION_ONLY] WRONG_FIRST_DATE",
                "expected=",
                EXPECTED_DATE,
                "actual=",
                current_date,
            )
            print(
                "[QMT_OPTION_ONLY] RESULT",
                "no option minute bar was supplied on the requested date",
            )
            ContextInfo.probe_stopped = True
            return

        for code in OPTION_CODES:
            try:
                detail = ContextInfo.get_option_detail_data(code)
                print("[QMT_OPTION_ONLY] DETAIL", code, repr(detail))
            except Exception as exc:
                print("[QMT_OPTION_ONLY] DETAIL_ERROR", code, repr(exc))

            for field_name in FIELDS:
                value, raw = read_field(ContextInfo, code, field_name)
                print(
                    "[QMT_OPTION_ONLY] FIELD",
                    code,
                    field_name,
                    value,
                    raw,
                )

    if ContextInfo.probe_bar_count <= OBSERVE_BARS:
        for code in OPTION_CODES:
            close_value, raw = read_field(ContextInfo, code, "close")
            ContextInfo.probe_prices.setdefault(code, []).append(close_value)
            print(
                "[QMT_OPTION_ONLY] OBSERVE",
                now_text,
                code,
                close_value,
                raw,
            )

    if ContextInfo.probe_bar_count == OBSERVE_BARS:
        for code in OPTION_CODES:
            values = ContextInfo.probe_prices.get(code, [])
            positive = [
                value for value in values
                if value is not None and value > 0
            ]
            print(
                "[QMT_OPTION_ONLY] SUMMARY",
                code,
                "positive_bars=",
                len(positive),
                "unique_prices=",
                len(set(positive)),
                "first=",
                positive[0] if positive else None,
                "last=",
                positive[-1] if positive else None,
            )
        print("[QMT_OPTION_ONLY] COMPLETE_COPY_LOG_TO_CODEX")
