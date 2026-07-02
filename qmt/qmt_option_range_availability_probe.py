# -*- coding: utf-8 -*-
"""Check historical option-contract availability over a QMT date range.

Run as a 1-minute backtest from 2025-11-10 through 2026-06-30.
The script scans once per trading day and never sends orders.
The source contains ASCII characters only for QMT editor compatibility.
"""

from __future__ import print_function

import datetime


START_DATE = 20251110
END_DATE = 20260630
UNDERLYINGS = ["588000.SH", "159915.SZ"]
DTE_MIN = 10
DTE_MAX = 35
SAMPLE_LIMIT = 6


def safe_int(value, default=0):
    try:
        return int(float(str(value).replace("-", "").replace("/", "")))
    except Exception:
        return default


def to_date(value):
    number = safe_int(value)
    text = str(number)
    if len(text) != 8:
        return None
    try:
        return datetime.date(
            int(text[0:4]),
            int(text[4:6]),
            int(text[6:8]),
        )
    except Exception:
        return None


def dte_between(current_date, expire_date):
    current_value = to_date(current_date)
    expire_value = to_date(expire_date)
    if current_value is None or expire_value is None:
        return None
    return (expire_value - current_value).days


def current_datetime(ContextInfo):
    try:
        tag = ContextInfo.get_bar_timetag(ContextInfo.barpos)
        text = timetag_to_datetime(tag, "%Y%m%d%H%M%S")
        return text, safe_int(text[:8])
    except Exception as exc:
        return "ERROR:%s" % repr(exc), 0


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
        return scalar_from_market_data(raw, field_name, code)
    except Exception:
        return None


def candidate_sort_key(item):
    return (
        safe_int(item.get("expire")),
        str(item.get("opt_type")),
        float(item.get("strike", 0.0)),
        str(item.get("code")),
    )


def scan_underlying(ContextInfo, undl_code, current_date):
    try:
        option_codes = ContextInfo.get_option_undl_data(undl_code)
    except Exception as exc:
        print(
            "[QMT_RANGE] UNIVERSE_ERROR",
            current_date,
            undl_code,
            repr(exc),
        )
        return {
            "directory": 0,
            "active": 0,
            "dte": 0,
            "priced": 0,
        }

    if option_codes is None:
        option_codes = []

    active_count = 0
    detail_error_count = 0
    candidates = []

    for code in option_codes:
        try:
            detail = ContextInfo.get_option_detail_data(code)
        except Exception:
            detail_error_count += 1
            continue
        if not isinstance(detail, dict) or not detail:
            detail_error_count += 1
            continue

        open_date = safe_int(detail.get("OpenDate", 0))
        expire_date = safe_int(detail.get("ExpireDate", 0))
        if not (open_date <= current_date <= expire_date):
            continue

        active_count += 1
        dte = dte_between(current_date, expire_date)
        if dte is None or dte < DTE_MIN or dte > DTE_MAX:
            continue

        candidates.append(
            {
                "code": str(code),
                "opt_type": str(detail.get("optType", "")),
                "open": open_date,
                "expire": expire_date,
                "dte": dte,
                "strike": float(detail.get("OptExercisePrice", 0.0)),
            }
        )

    candidates.sort(key=candidate_sort_key)
    priced_count = 0
    samples = []
    for item in candidates:
        close_value = read_field(ContextInfo, item["code"], "close")
        volume_value = read_field(ContextInfo, item["code"], "volume")
        if close_value is not None and close_value > 0:
            priced_count += 1
        if len(samples) < SAMPLE_LIMIT:
            samples.append(
                (
                    item["code"],
                    item["opt_type"],
                    item["expire"],
                    item["dte"],
                    item["strike"],
                    close_value,
                    volume_value,
                )
            )

    print(
        "[QMT_RANGE] DAY",
        current_date,
        undl_code,
        "directory=",
        len(option_codes),
        "active=",
        active_count,
        "dte_10_35=",
        len(candidates),
        "priced=",
        priced_count,
        "detail_errors=",
        detail_error_count,
    )
    for sample in samples:
        print(
            "[QMT_RANGE] SAMPLE",
            current_date,
            undl_code,
            "code=",
            sample[0],
            "type=",
            sample[1],
            "expire=",
            sample[2],
            "dte=",
            sample[3],
            "strike=",
            sample[4],
            "close=",
            sample[5],
            "volume=",
            sample[6],
        )

    return {
        "directory": len(option_codes),
        "active": active_count,
        "dte": len(candidates),
        "priced": priced_count,
    }


def print_summary(ContextInfo):
    print(
        "[QMT_RANGE] SUMMARY",
        "first_event_date=",
        ContextInfo.range_first_date,
        "last_event_date=",
        ContextInfo.range_last_date,
        "scanned_days=",
        ContextInfo.range_scanned_days,
    )
    for undl_code in UNDERLYINGS:
        stats = ContextInfo.range_stats[undl_code]
        print(
            "[QMT_RANGE] SUMMARY_UNDERLYING",
            undl_code,
            "days_with_active=",
            stats["days_active"],
            "days_with_dte_10_35=",
            stats["days_dte"],
            "days_with_priced_dte=",
            stats["days_priced"],
            "total_dte_contracts=",
            stats["total_dte"],
            "total_priced_contracts=",
            stats["total_priced"],
        )
    print("[QMT_RANGE] COMPLETE_COPY_ALL_RANGE_LOGS_TO_CODEX")


def init(ContextInfo):
    ContextInfo.range_last_scanned_date = 0
    ContextInfo.range_first_date = 0
    ContextInfo.range_last_date = 0
    ContextInfo.range_scanned_days = 0
    ContextInfo.range_summary_printed = False
    ContextInfo.range_stats = {}
    for undl_code in UNDERLYINGS:
        ContextInfo.range_stats[undl_code] = {
            "days_active": 0,
            "days_dte": 0,
            "days_priced": 0,
            "total_dte": 0,
            "total_priced": 0,
        }
    ContextInfo.set_universe(UNDERLYINGS)
    print("[QMT_RANGE] INIT period=", getattr(ContextInfo, "period", None))
    print("[QMT_RANGE] REQUIRED_RANGE 2025-11-10 to 2026-06-30")
    print("[QMT_RANGE] DTE_FILTER 10 to 35")
    print("[QMT_RANGE] NO_ORDERS_WILL_BE_SENT")


def handlebar(ContextInfo):
    now_text, current_date = current_datetime(ContextInfo)
    if current_date <= 0:
        return
    time_text = now_text[8:12] if len(now_text) >= 12 else ""

    if ContextInfo.range_first_date == 0:
        ContextInfo.range_first_date = current_date
        print(
            "[QMT_RANGE] FIRST_BAR",
            now_text,
            "barpos=",
            ContextInfo.barpos,
        )
    ContextInfo.range_last_date = current_date

    if (
        START_DATE <= current_date <= END_DATE
        and time_text >= "0946"
        and current_date != ContextInfo.range_last_scanned_date
    ):
        ContextInfo.range_last_scanned_date = current_date
        ContextInfo.range_scanned_days += 1
        print("[QMT_RANGE] SCAN_DATE", current_date, "scan_bar=", now_text)
        for undl_code in UNDERLYINGS:
            result = scan_underlying(ContextInfo, undl_code, current_date)
            stats = ContextInfo.range_stats[undl_code]
            if result["active"] > 0:
                stats["days_active"] += 1
            if result["dte"] > 0:
                stats["days_dte"] += 1
            if result["priced"] > 0:
                stats["days_priced"] += 1
            stats["total_dte"] += result["dte"]
            stats["total_priced"] += result["priced"]

    if (
        current_date == END_DATE
        and time_text >= "1459"
        and not ContextInfo.range_summary_printed
    ):
        ContextInfo.range_summary_printed = True
        print_summary(ContextInfo)
