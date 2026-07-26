# -*- coding: utf-8 -*-
"""QMT order-book probe for ETF/options.

ASCII-only version for QMT script parser.
Run this in QMT on a 1-minute chart. It does not send orders.

Important:
- In QMT Python, DYNAINFO formula fields may not be available.
- The useful path is usually ContextInfo.get_full_tick([code]).
- Historical replay may not include order-book depth. Run during live market
  if possible.
"""

from __future__ import print_function


UNDERLYINGS = ["588000.SH"]

# Add/remove option codes here after you know the current active contract.
OPTION_CODES = [
    "10011916.SHO",
    "10011916.SH",
]

PROBE_TIMES = [
    "0930", "0945", "1000", "1030", "1400", "1445", "1455",
]

PROBE_MARKET_DATA_FIELDS = False
PROBE_DYNAINFO = False


def log(*items):
    print("[QMT_ORDERBOOK_PROBE]", *items)


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


def try_call(label, fn):
    try:
        value = fn()
        log(label, repr(value))
        return value
    except Exception as exc:
        log(label + "_ERROR", repr(exc))
        return None


def safe_float(value, default=None):
    try:
        number = float(value)
        if number != number:
            return default
        return number
    except Exception:
        return default


def get_nested_tick(raw, code):
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


def first_number(value):
    if isinstance(value, (list, tuple)):
        for item in value:
            number = safe_float(item)
            if number is not None and number > 0:
                return number
        return None
    return safe_float(value)


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
        if str(key).lower() in lower:
            return lower.get(str(key).lower())
    return None


def summarize_tick(code, raw):
    row = get_nested_tick(raw, code)
    if not isinstance(row, dict):
        log("TICK_SUMMARY", code, "not_dict", repr(row))
        return
    keys = sorted([str(key) for key in row.keys()])
    log("TICK_KEYS", code, repr(keys))
    last_price = first_number(read_key(row, ["lastPrice", "last_price", "price", "close"]))
    bid1 = first_number(read_key(row, ["bidPrice", "bid_price", "bidPrice1", "bid1", "buyPrice", "buy1Price"]))
    ask1 = first_number(read_key(row, ["askPrice", "ask_price", "askPrice1", "ask1", "sellPrice", "sell1Price"]))
    bidv1 = first_number(read_key(row, ["bidVol", "bid_vol", "bidVol1", "bidVolume", "buyVol", "buy1Vol"]))
    askv1 = first_number(read_key(row, ["askVol", "ask_vol", "askVol1", "askVolume", "sellVol", "sell1Vol"]))
    log(
        "TICK_BBO",
        code,
        "last=", last_price,
        "bid1=", bid1,
        "bidv1=", bidv1,
        "ask1=", ask1,
        "askv1=", askv1,
    )


def probe_get_full_tick(ContextInfo, code):
    def call():
        return ContextInfo.get_full_tick([code])
    raw = try_call("FULL_TICK_RAW " + str(code), call)
    summarize_tick(code, raw)
    return raw


def probe_market_data_fields(ContextInfo, code):
    # Common QMT / vendor naming guesses. Some will fail or return None; that
    # is useful because it tells us exactly which spelling your install uses.
    fields = [
        "lastPrice",
        "open", "high", "low", "close", "volume", "amount",
        "bidPrice", "askPrice", "bidVol", "askVol",
        "bidPrice1", "bidPrice2", "bidPrice3", "bidPrice4", "bidPrice5",
        "askPrice1", "askPrice2", "askPrice3", "askPrice4", "askPrice5",
        "bidVol1", "bidVol2", "bidVol3", "bidVol4", "bidVol5",
        "askVol1", "askVol2", "askVol3", "askVol4", "askVol5",
    ]

    # This call often requires numpy in QMT and may fail in this installation.
    # Keep it as a compact one-shot diagnostic only.
    def call():
        return ContextInfo.get_market_data(fields, stock_code=[code], period=ContextInfo.period)
    try_call("MARKET_DATA_FIELDS_RAW " + str(code), call)


def probe_dynainfo(ContextInfo, code):
    # From QMT function list:
    # DYNAINFO(25/26/27): buy volume 1/2/3
    # DYNAINFO(28/29/30): buy price 1/2/3
    # DYNAINFO(31/32/33): sell volume 1/2/3
    # DYNAINFO(34/35/36): sell price 1/2/3
    dynainfo_items = [
        (28, "BID1_PRICE"),
        (34, "ASK1_PRICE"),
    ]
    for idx, name in dynainfo_items:
        expression = "DYNAINFO(%d)" % idx

        def call(expr=expression):
            return ContextInfo.get_market_data(
                [expr],
                stock_code=[code],
                period=ContextInfo.period,
            )
        try_call("DYNAINFO %s %s %s" % (str(code), idx, name), call)


def init(ContextInfo):
    universe = []
    for code in UNDERLYINGS + OPTION_CODES:
        if code not in universe:
            universe.append(code)
    ContextInfo.set_universe(universe)
    ContextInfo._orderbook_probe_last = ""
    log("INIT", "period=", getattr(ContextInfo, "period", None), "universe=", repr(universe))


def handlebar(ContextInfo):
    now_text, current_date, time_text = current_datetime(ContextInfo)
    if len(time_text) != 4:
        return
    if now_text == getattr(ContextInfo, "_orderbook_probe_last", ""):
        return
    ContextInfo._orderbook_probe_last = now_text
    if time_text not in PROBE_TIMES:
        return

    log("TIME", now_text)
    for code in UNDERLYINGS + OPTION_CODES:
        log("BEGIN_CODE", code)
        probe_get_full_tick(ContextInfo, code)
        if PROBE_MARKET_DATA_FIELDS:
            probe_market_data_fields(ContextInfo, code)
        if PROBE_DYNAINFO:
            probe_dynainfo(ContextInfo, code)
        log("END_CODE", code)
