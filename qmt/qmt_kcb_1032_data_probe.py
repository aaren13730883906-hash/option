# -*- coding: utf-8 -*-
"""QMT data probe for the KCB 1032.98% executable baseline.

Run this script in QMT as a 1-minute backtest over 2026-07-24.
It never sends orders.  Copy the complete QMT log back to Codex.

Purpose:
- verify ETF 1m bars and daily warmup are available;
- verify current option universe/detail APIs are available;
- verify Put-reversal 09:45 candidate data can be built;
- verify option 1m bars, volume15, IV, Delta, DTE and capacity fields exist;
- verify 10:30 and 14:45 management data can be read.

The source intentionally uses only ASCII and the Python 3.6 standard library.
"""

from __future__ import print_function

import datetime
import math


EXPECTED_DATE = 20260724
KCB_CODE = "588000.SH"
UNDERLYINGS = [KCB_CODE]

INITIAL_CASH = 100000.0
POSITION_PCT = 0.20
ABS_PREMIUM_CAP = 150000.0
CAPACITY_VOLUME_SHARE = 0.05
CONTRACT_MULTIPLIER_DEFAULT = 10000

DTE_MIN = 10
DTE_MAX = 35
PUT_DELTA_MIN = 0.45
PUT_DELTA_MAX = 0.60
MIN_OPTION_PRICE = 0.03
MIN_VOLUME15 = 1000.0
ETF_UP_MIN = 0.005
TREND_MA20_DEV = 0.03

PROBE_TIMES = [
    "0930", "0935", "0940", "0945", "1000", "1030", "1445", "1455",
]
MAX_DETAIL_PRINT = 12

# QMT in this installation raises "No module named pandas" when calling
# get_market_data_ex for daily bars.  The executable strategy should therefore
# use an embedded warmup seed and append live daily bars from minute data.
# Tuple: date, open, high, low, close, volume, amount.
KCB_DAILY_SEED = [
    (20260427, 1.552000, 1.597000, 1.544000, 1.591000, 33052980.0, 5210584130.000),
    (20260428, 1.579000, 1.608000, 1.559000, 1.568000, 23183885.0, 3669559812.000),
    (20260429, 1.555000, 1.576000, 1.530000, 1.575000, 22938785.0, 3572909416.000),
    (20260430, 1.592000, 1.665000, 1.590000, 1.654000, 51410526.0, 8401295784.000),
    (20260506, 1.719000, 1.812000, 1.709000, 1.744000, 43376895.0, 7667042588.000),
    (20260507, 1.752000, 1.772000, 1.733000, 1.769000, 23533724.0, 4125315008.000),
    (20260508, 1.744000, 1.745000, 1.712000, 1.727000, 27678005.0, 4788138088.000),
    (20260511, 1.777000, 1.820000, 1.758000, 1.811000, 37053335.0, 6647081724.000),
    (20260512, 1.802000, 1.841000, 1.777000, 1.816000, 28999403.0, 5240256724.000),
    (20260513, 1.780000, 1.866000, 1.767000, 1.865000, 34174506.0, 6212086912.000),
    (20260514, 1.884000, 1.898000, 1.814000, 1.815000, 34701709.0, 6412216628.000),
    (20260515, 1.807000, 1.865000, 1.758000, 1.787000, 44180694.0, 7958614092.000),
    (20260518, 1.770000, 1.842000, 1.770000, 1.803000, 33138387.0, 5995788592.000),
    (20260519, 1.787000, 1.872000, 1.759000, 1.871000, 37991833.0, 6868976860.000),
    (20260520, 1.857000, 1.933000, 1.856000, 1.931000, 39558649.0, 7542789936.000),
    (20260521, 1.967000, 1.994000, 1.853000, 1.860000, 43811237.0, 8475584492.000),
    (20260522, 1.873000, 1.899000, 1.840000, 1.887000, 31913481.0, 5967880768.000),
    (20260525, 1.887000, 2.002000, 1.867000, 1.998000, 43284240.0, 8450888560.000),
    (20260526, 1.983000, 1.983000, 1.922000, 1.968000, 3723469406.0, 7266807369.059),
    (20260527, 1.972000, 2.003000, 1.905000, 1.911000, 3820345548.0, 7471395274.112),
    (20260528, 1.893000, 1.954000, 1.891000, 1.942000, 3883039052.0, 7480500717.099),
    (20260529, 1.944000, 1.952000, 1.820000, 1.844000, 4620430910.0, 8654625507.858),
    (20260601, 1.841000, 1.850000, 1.751000, 1.754000, 4195016494.0, 7517959823.856),
    (20260602, 1.756000, 1.803000, 1.728000, 1.781000, 3562692683.0, 6296506062.416),
    (20260603, 1.788000, 1.872000, 1.784000, 1.823000, 4106087727.0, 7513993876.839),
    (20260604, 1.794000, 1.856000, 1.789000, 1.832000, 2285373033.0, 4188280581.953),
    (20260605, 1.801000, 1.829000, 1.750000, 1.763000, 3036765522.0, 5429864189.830),
    (20260608, 1.690000, 1.725000, 1.665000, 1.683000, 3879251946.0, 6578187379.433),
    (20260609, 1.721000, 1.760000, 1.696000, 1.755000, 2879374620.0, 4978683139.246),
    (20260610, 1.748000, 1.818000, 1.724000, 1.744000, 3317234966.0, 5864140525.526),
    (20260611, 1.727000, 1.771000, 1.723000, 1.756000, 2661770721.0, 4645134517.937),
    (20260612, 1.825000, 1.828000, 1.751000, 1.756000, 3264831324.0, 5855055732.724),
    (20260615, 1.782000, 1.845000, 1.750000, 1.844000, 3001479396.0, 5441091921.274),
    (20260616, 1.845000, 1.863000, 1.823000, 1.855000, 2544244580.0, 4693669477.802),
    (20260617, 1.828000, 1.940000, 1.819000, 1.939000, 3474306997.0, 6547205597.370),
    (20260618, 1.935000, 2.042000, 1.932000, 2.017000, 4081671719.0, 8160146208.589),
    (20260622, 2.026000, 2.070000, 1.981000, 2.056000, 3609573754.0, 7321099001.517),
    (20260623, 2.040000, 2.090000, 1.992000, 2.023000, 3643158120.0, 7418469842.035),
    (20260624, 2.000000, 2.105000, 1.987000, 2.096000, 4244590621.0, 8748955894.640),
    (20260625, 2.114000, 2.189000, 2.106000, 2.178000, 3663353147.0, 7891953305.358),
    (20260626, 2.142000, 2.188000, 2.084000, 2.133000, 4048019931.0, 8667140757.093),
    (20260629, 2.143000, 2.250000, 2.124000, 2.248000, 3760094834.0, 8245833173.679),
    (20260630, 2.257000, 2.349000, 2.228000, 2.344000, 3084492727.0, 7100428840.356),
    (20260701, 2.346000, 2.390000, 2.252000, 2.290000, 4023150744.0, 9359368197.430),
    (20260702, 2.220000, 2.240000, 2.100000, 2.119000, 4850891100.0, 10527602202.000),
    (20260703, 2.089000, 2.165000, 2.068000, 2.102000, 3573377923.0, 7548907656.838),
    (20260706, 2.133000, 2.148000, 2.031000, 2.116000, 3603596819.0, 7576402940.941),
    (20260707, 2.080000, 2.162000, 2.073000, 2.126000, 3320794047.0, 7077642453.821),
    (20260708, 2.142000, 2.208000, 2.083000, 2.145000, 3574975191.0, 7689417203.229),
    (20260709, 2.166000, 2.333000, 2.150000, 2.328000, 4543445965.0, 10154782885.511),
    (20260710, 2.334000, 2.386000, 2.204000, 2.209000, 4702931900.0, 10899194362.038),
    (20260713, 2.160000, 2.226000, 2.081000, 2.100000, 4241823627.0, 9118631347.190),
    (20260714, 2.094000, 2.136000, 1.998000, 2.125000, 4574816118.0, 9512576606.932),
    (20260715, 2.133000, 2.141000, 2.011000, 2.028000, 4399923974.0, 9061939217.238),
    (20260716, 1.977000, 2.054000, 1.928000, 1.945000, 4547499903.0, 9033153320.530),
    (20260717, 1.922000, 1.945000, 1.791000, 1.807000, 7659884107.0, 14287477010.642),
    (20260720, 1.851000, 1.873000, 1.737000, 1.815000, 13058736297.0, 23452637629.945),
    (20260721, 1.832000, 2.017000, 1.755000, 2.016000, 9242914692.0, 17322012288.637),
    (20260722, 1.963000, 2.038000, 1.935000, 1.955000, 6906230322.0, 13736182063.762),
    (20260723, 1.970000, 1.979000, 1.867000, 1.888000, 5257464095.0, 10026719748.294),
]


def log(*items):
    print("[KCB_1032_PROBE]", *items)


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


def yyyymmdd_date(value):
    text = str(safe_int(value))
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


def days_to_expiry(current_date, expiry_date):
    current_value = yyyymmdd_date(current_date)
    expiry_value = yyyymmdd_date(expiry_date)
    if current_value is None or expiry_value is None:
        return None
    return (expiry_value - current_value).days


def mean(values):
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / float(len(clean))


def sma(values, window):
    if len(values) < window:
        return None
    return sum(values[-window:]) / float(window)


def normal_cdf(value):
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def bs_price(spot, strike, rate, iv, dte, option_type):
    if (
        spot is None
        or strike is None
        or iv is None
        or spot <= 0
        or strike <= 0
        or iv <= 0
        or dte <= 0
    ):
        return None
    years = float(dte) / 365.0
    root_time = math.sqrt(years)
    denominator = iv * root_time
    if denominator <= 0:
        return None
    d1 = (
        math.log(spot / strike)
        + (rate + 0.5 * iv * iv) * years
    ) / denominator
    d2 = d1 - denominator
    discounted_strike = strike * math.exp(-rate * years)
    if option_type == "CALL":
        return (
            spot * normal_cdf(d1)
            - discounted_strike * normal_cdf(d2)
        )
    return (
        discounted_strike * normal_cdf(-d2)
        - spot * normal_cdf(-d1)
    )


def implied_volatility(market_price, spot, strike, rate, dte, option_type):
    if (
        market_price is None
        or market_price <= 0
        or spot is None
        or spot <= 0
        or strike is None
        or strike <= 0
        or dte <= 0
    ):
        return None
    intrinsic = (
        max(spot - strike, 0.0)
        if option_type == "CALL"
        else max(strike - spot, 0.0)
    )
    if market_price + 0.000001 < intrinsic:
        return None
    low = 0.01
    high = 3.00
    high_price = bs_price(spot, strike, rate, high, dte, option_type)
    if high_price is None or high_price < market_price:
        return None
    for unused in range(70):
        middle = (low + high) / 2.0
        model_price = bs_price(
            spot, strike, rate, middle, dte, option_type
        )
        if model_price is None:
            return None
        if model_price > market_price:
            high = middle
        else:
            low = middle
    result = (low + high) / 2.0
    if result <= 0 or result > 3.0:
        return None
    return result


def bs_delta(spot, strike, rate, iv, dte, option_type):
    if (
        spot is None
        or strike is None
        or iv is None
        or spot <= 0
        or strike <= 0
        or iv <= 0
        or dte <= 0
    ):
        return None
    years = float(dte) / 365.0
    denominator = iv * math.sqrt(years)
    if denominator <= 0:
        return None
    d1 = (
        math.log(spot / strike)
        + (rate + 0.5 * iv * iv) * years
    ) / denominator
    if option_type == "CALL":
        return normal_cdf(d1)
    return normal_cdf(d1) - 1.0


def normalize_iv(value):
    number = safe_float(value)
    if number is None or number <= 0:
        return None
    if number > 3.0:
        number = number / 100.0
    return number


def current_datetime(ContextInfo):
    try:
        tag = ContextInfo.get_bar_timetag(ContextInfo.barpos)
        text = timetag_to_datetime(tag, "%Y%m%d%H%M%S")
        return text, safe_int(text[:8]), text[8:12]
    except Exception as exc:
        return "ERROR:%s" % repr(exc), 0, ""


def timetag_date(value):
    text = str(value)
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 8:
        return safe_int(digits)
    if (
        len(digits) >= 8
        and digits[:4] >= "1990"
        and digits[:4] <= "2099"
    ):
        return safe_int(digits[:8])
    if len(digits) >= 13:
        try:
            converted = timetag_to_datetime(safe_int(value), "%Y%m%d")
            return safe_int(converted)
        except Exception:
            return 0
    return 0


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
            if field_name in nested:
                found = recursive_number(
                    nested.get(field_name),
                    code,
                    field_name,
                )
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
        return recursive_number(raw, code, field_name)
    except Exception:
        return None


def read_bar(ContextInfo, code):
    fields = ["open", "high", "low", "close", "volume", "amount"]
    output = {}
    try:
        raw = ContextInfo.get_market_data(
            fields,
            stock_code=[code],
            period=ContextInfo.period,
        )
        if isinstance(raw, dict):
            for field_name in fields:
                output[field_name] = recursive_number(
                    raw,
                    code,
                    field_name,
                )
    except Exception:
        output = {}
    for field_name in fields:
        if output.get(field_name) is None:
            output[field_name] = read_field(ContextInfo, code, field_name)
    close_value = output.get("close")
    if close_value is None or close_value <= 0:
        return None
    for field_name in ["open", "high", "low"]:
        if output.get(field_name) is None or output.get(field_name) <= 0:
            output[field_name] = close_value
    if output.get("volume") is None:
        output["volume"] = 0.0
    if output.get("amount") is None:
        output["amount"] = 0.0
    return output


def history_mapping_rows(mapping):
    if not isinstance(mapping, dict):
        return []
    required = ["open", "high", "low", "close"]
    rows = []
    for tag, values in mapping.items():
        if not isinstance(values, dict):
            continue
        if not any(field_name in values for field_name in required):
            continue
        row = dict(values)
        row["_tag"] = tag
        rows.append(row)
    if rows:
        return rows
    if not all(field_name in mapping for field_name in required):
        return []
    tags = set()
    for field_name in required + ["volume", "amount"]:
        values = mapping.get(field_name)
        if isinstance(values, dict):
            tags.update(values.keys())
    for tag in tags:
        row = {"_tag": tag}
        for field_name in required + ["volume", "amount"]:
            values = mapping.get(field_name)
            if isinstance(values, dict):
                row[field_name] = values.get(tag)
        rows.append(row)
    return rows


def history_payload_rows(raw, code):
    if not isinstance(raw, dict):
        return []
    container = raw.get(code)
    if container is None:
        container = raw.get(code.split(".")[0])
    if container is None:
        container = raw
    if isinstance(container, dict):
        return history_mapping_rows(container)
    try:
        converted = container.to_dict("index")
        rows = history_mapping_rows(converted)
        if rows:
            return rows
    except Exception:
        pass
    try:
        converted = container.to_dict()
        rows = history_mapping_rows(converted)
        if rows:
            return rows
    except Exception:
        pass
    try:
        rows = []
        for tag, values in container.iterrows():
            if hasattr(values, "to_dict"):
                row = values.to_dict()
            else:
                row = dict(values)
            row["_tag"] = tag
            rows.append(row)
        return rows
    except Exception:
        return []


def standardized_daily_rows(raw, code):
    source_rows = history_payload_rows(raw, code)
    rows = []
    for values in source_rows:
        trade_date = timetag_date(values.get("_tag"))
        open_value = safe_float(values.get("open"))
        high_value = safe_float(values.get("high"))
        low_value = safe_float(values.get("low"))
        close_value = safe_float(values.get("close"))
        volume_value = safe_float(values.get("volume"), 0.0)
        amount_value = safe_float(values.get("amount"), 0.0)
        if (
            trade_date <= 0
            or open_value is None
            or high_value is None
            or low_value is None
            or close_value is None
            or close_value <= 0
        ):
            continue
        rows.append(
            {
                "date": trade_date,
                "open": open_value,
                "high": high_value,
                "low": low_value,
                "close": close_value,
                "volume": volume_value,
                "amount": amount_value,
            }
        )
    rows.sort(key=lambda item: item["date"])
    return rows


def preload_daily_data(ContextInfo):
    rows = []
    try:
        raw = ContextInfo.get_market_data_ex(
            ["open", "high", "low", "close", "volume", "amount"],
            stock_code=[KCB_CODE],
            period="1d",
            start_time="20250101",
            end_time="",
            count=-1,
            dividend_type="none",
            fill_data=True,
            subscribe=False,
        )
        rows = standardized_daily_rows(raw, KCB_CODE)
        if rows:
            log("DAILY_SOURCE", "get_market_data_ex")
    except Exception as exc:
        log("DAILY_EX_ERROR", repr(exc))
    if not rows:
        try:
            raw = ContextInfo.get_local_data(
                stock_code=KCB_CODE,
                start_time="20250101",
                end_time="",
                period="1d",
                divid_type="none",
                count=-1,
            )
            rows = standardized_daily_rows(raw, KCB_CODE)
            if rows:
                log("DAILY_SOURCE", "get_local_data")
        except Exception as exc:
            log("DAILY_LOCAL_ERROR", repr(exc))
    dedup = {}
    for row in rows:
        dedup[row["date"]] = row
    output = [dedup[key] for key in sorted(dedup.keys())]
    if not output:
        output = [
            {
                "date": item[0],
                "open": item[1],
                "high": item[2],
                "low": item[3],
                "close": item[4],
                "volume": item[5],
                "amount": item[6],
            }
            for item in KCB_DAILY_SEED
        ]
        log("DAILY_SOURCE", "embedded_seed")
    log("DAILY_PRELOAD", "rows=", len(output))
    return output


def daily_metrics(rows, current_date):
    completed = [row for row in rows if row.get("date", 0) < current_date]
    closes = [row["close"] for row in completed]
    volumes = [row["volume"] for row in completed]
    if len(completed) < 21:
        return {
            "ready": False,
            "completed": len(completed),
        }
    ma5 = sma(closes, 5)
    ma10 = sma(closes, 10)
    ma20 = sma(closes, 20)
    prev_ma5 = mean(closes[-6:-1])
    prev_ma20 = mean(closes[-21:-1])
    ma5_slope = ma5 - prev_ma5
    ma20_slope = ma20 - prev_ma20
    last = completed[-1]
    avg_volume20 = mean(volumes[-20:])
    volume_ratio20 = (
        last["volume"] / avg_volume20
        if avg_volume20 is not None and avg_volume20 > 0
        else None
    )
    direction = "none"
    if (
        last["close"] > ma5 > ma10 > ma20
        and ma5_slope > 0
        and ma20_slope >= 0
    ):
        direction = "call"
    elif (
        last["close"] < ma5 < ma10 < ma20
        and ma5_slope < 0
        and ma20_slope <= 0
    ):
        direction = "put"
    return {
        "ready": True,
        "completed": len(completed),
        "last_date": last["date"],
        "last_close": last["close"],
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "ma5_slope": ma5_slope,
        "ma20_slope": ma20_slope,
        "direction": direction,
        "volume_ratio20": volume_ratio20,
    }


def read_option_iv(ContextInfo, code, spot, strike, rate, dte, option_type,
                   market_price):
    reversed_iv = implied_volatility(
        market_price,
        spot,
        strike,
        rate,
        dte,
        option_type,
    )
    if reversed_iv is not None:
        return reversed_iv, "reversed"
    try:
        qmt_iv = normalize_iv(ContextInfo.get_option_iv(code))
        if qmt_iv is not None:
            return qmt_iv, "qmt"
    except Exception:
        pass
    return None, "missing"


def option_type_norm(value):
    text = str(value).upper()
    if text in ["CALL", "C", "1"]:
        return "CALL"
    if text in ["PUT", "P", "2"]:
        return "PUT"
    return text


def build_universe(ContextInfo, current_date, spot):
    try:
        option_codes = ContextInfo.get_option_undl_data(KCB_CODE)
    except Exception as exc:
        log("OPTION_UNIVERSE_ERROR", repr(exc))
        return []
    if option_codes is None:
        option_codes = []
    rows = []
    type_counts = {}
    active_count = 0
    dte_count = 0
    for option_code in option_codes:
        try:
            detail = ContextInfo.get_option_detail_data(option_code)
        except Exception:
            continue
        if not isinstance(detail, dict) or not detail:
            continue
        open_date = safe_int(detail.get("OpenDate", 0))
        expire_date = safe_int(detail.get("ExpireDate", 0))
        strike = safe_float(detail.get("OptExercisePrice"))
        option_type = option_type_norm(detail.get("optType", ""))
        type_counts[option_type] = type_counts.get(option_type, 0) + 1
        if (
            option_type not in ["CALL", "PUT"]
            or strike is None
            or strike <= 0
            or not (open_date <= current_date <= expire_date)
        ):
            continue
        active_count += 1
        dte = days_to_expiry(current_date, expire_date)
        if dte is None:
            continue
        if DTE_MIN <= dte <= DTE_MAX:
            dte_count += 1
        rate = safe_float(detail.get("OptUndlRiskFreeRate"), 0.02)
        multiplier = safe_int(
            detail.get(
                "OptUnit",
                detail.get("VolumeMultiple", CONTRACT_MULTIPLIER_DEFAULT),
            ),
            CONTRACT_MULTIPLIER_DEFAULT,
        )
        rows.append(
            {
                "code": str(option_code),
                "type": option_type,
                "strike": strike,
                "expire": expire_date,
                "dte": dte,
                "rate": rate,
                "multiplier": multiplier,
                "distance": abs(strike - spot) if spot is not None else 0.0,
                "detail": detail,
            }
        )
    rows.sort(key=lambda item: (item["type"], item["dte"], item["strike"]))
    log(
        "OPTION_UNIVERSE",
        "total=",
        len(option_codes),
        "parsed=",
        len(rows),
        "active=",
        active_count,
        "dte10_35=",
        dte_count,
        "types=",
        repr(type_counts),
    )
    for item in rows[:MAX_DETAIL_PRINT]:
        log(
            "OPTION_DETAIL",
            item["code"],
            item["type"],
            "strike=",
            item["strike"],
            "expire=",
            item["expire"],
            "dte=",
            item["dte"],
            "mult=",
            item["multiplier"],
        )
    return rows


def append_bar(store, code, now_text, time_text, bar):
    values = store.setdefault(code, [])
    values.append(
        {
            "datetime": now_text,
            "time": time_text,
            "open": bar["open"],
            "high": bar["high"],
            "low": bar["low"],
            "close": bar["close"],
            "volume": bar["volume"],
            "amount": bar["amount"],
        }
    )
    if len(values) > 300:
        store[code] = values[-300:]


def bars_between(values, start_time, end_time):
    return [
        row for row in values
        if row.get("time", "") >= start_time and row.get("time", "") <= end_time
    ]


def volume15(values):
    return sum(row["volume"] for row in bars_between(values, "0930", "0945"))


def first_bar(values):
    return values[0] if values else None


def last_bar_at_or_before(values, time_text):
    output = None
    for row in values:
        if row.get("time", "") <= time_text:
            output = row
    return output


def evaluate_0945(ContextInfo, current_date, now_text):
    state = ContextInfo.probe_state
    etf_values = state["bars"].get(KCB_CODE, [])
    if not etf_values:
        log("E0945_NO_ETF_BARS")
        return
    etf_open_bar = first_bar(etf_values)
    etf_last = last_bar_at_or_before(etf_values, "0945")
    if etf_open_bar is None or etf_last is None:
        log("E0945_ETF_INCOMPLETE")
        return
    spot = etf_last["close"]
    etf_return = (
        spot / etf_open_bar["open"] - 1.0
        if etf_open_bar["open"] > 0
        else None
    )
    daily = state.get("daily_metrics", {})
    ma20 = daily.get("ma20")
    ma20_dev = spot / ma20 - 1.0 if ma20 is not None and ma20 > 0 else None
    log(
        "ETF_0945",
        "open=",
        round(etf_open_bar["open"], 6),
        "close=",
        round(spot, 6),
        "return=",
        round(etf_return, 6) if etf_return is not None else None,
        "ma20=",
        round(ma20, 6) if ma20 is not None else None,
        "ma20_dev=",
        round(ma20_dev, 6) if ma20_dev is not None else None,
        "putrev_etf_ok=",
        etf_return is not None and etf_return >= ETF_UP_MIN,
        "trend_quick_zone=",
        ma20_dev is not None and ma20_dev >= TREND_MA20_DEV,
    )
    candidates = []
    rejects = {
        "type": 0,
        "dte": 0,
        "no_bar": 0,
        "price": 0,
        "iv": 0,
        "delta": 0,
        "volume15": 0,
    }
    for item in state.get("universe", []):
        if item["type"] != "PUT":
            rejects["type"] += 1
            continue
        if item["dte"] < DTE_MIN or item["dte"] > DTE_MAX:
            rejects["dte"] += 1
            continue
        option_values = state["bars"].get(item["code"], [])
        last = last_bar_at_or_before(option_values, "0945")
        if last is None:
            rejects["no_bar"] += 1
            continue
        price = last["close"]
        if price is None or price < MIN_OPTION_PRICE:
            rejects["price"] += 1
            continue
        iv, iv_source = read_option_iv(
            ContextInfo,
            item["code"],
            spot,
            item["strike"],
            item["rate"],
            item["dte"],
            item["type"],
            price,
        )
        if iv is None:
            rejects["iv"] += 1
            continue
        delta = bs_delta(
            spot,
            item["strike"],
            item["rate"],
            iv,
            item["dte"],
            item["type"],
        )
        if delta is None or not (PUT_DELTA_MIN <= abs(delta) <= PUT_DELTA_MAX):
            rejects["delta"] += 1
            continue
        vol15 = volume15(option_values)
        if vol15 < MIN_VOLUME15:
            rejects["volume15"] += 1
            continue
        open_bar = first_bar(option_values)
        momentum = (
            price / open_bar["open"] - 1.0
            if open_bar is not None and open_bar["open"] > 0
            else 0.0
        )
        budget = min(INITIAL_CASH * POSITION_PCT, ABS_PREMIUM_CAP)
        planned = int(budget / float(price * item["multiplier"]))
        cap_limit = vol15 * CAPACITY_VOLUME_SHARE
        candidates.append(
            {
                "code": item["code"],
                "strike": item["strike"],
                "dte": item["dte"],
                "price": price,
                "iv": iv,
                "iv_source": iv_source,
                "delta": delta,
                "volume15": vol15,
                "momentum": momentum,
                "planned": planned,
                "capacity_limit": cap_limit,
                "capacity_ok": planned > 0 and planned <= cap_limit,
                "multiplier": item["multiplier"],
            }
        )
    candidates.sort(key=lambda row: row["momentum"], reverse=True)
    log("PUTREV_REJECTS", repr(rejects))
    log("PUTREV_CANDIDATES", "count=", len(candidates))
    for row in candidates[:8]:
        log(
            "PUTREV_CAND",
            row["code"],
            "strike=",
            row["strike"],
            "dte=",
            row["dte"],
            "price=",
            round(row["price"], 6),
            "iv=",
            round(row["iv"], 4),
            "iv_source=",
            row["iv_source"],
            "delta=",
            round(row["delta"], 4),
            "vol15=",
            round(row["volume15"], 2),
            "momentum15=",
            round(row["momentum"], 6),
            "planned_100k=",
            row["planned"],
            "cap5pct=",
            round(row["capacity_limit"], 2),
            "capacity_ok=",
            row["capacity_ok"],
        )
    selected = None
    for row in candidates:
        if row["capacity_ok"]:
            selected = row
            break
    state["selected_putrev"] = selected
    if selected is None:
        log("PUTREV_SELECTED", "NONE")
    else:
        log(
            "PUTREV_SELECTED",
            selected["code"],
            "reason=",
            "momentum_capacity",
            "premium_cap=",
            ABS_PREMIUM_CAP,
            "position_pct=",
            POSITION_PCT,
        )


def evaluate_1030(now_text):
    state = ContextInfo_global.probe_state
    selected = state.get("selected_putrev")
    if selected is None:
        log("CHECK_1030", "no_selected_putrev")
        return
    values = state["bars"].get(selected["code"], [])
    entry = last_bar_at_or_before(values, "0945")
    check = last_bar_at_or_before(values, "1030")
    if entry is None or check is None:
        log("CHECK_1030", selected["code"], "missing_entry_or_1030")
        return
    path = [
        row for row in values
        if row["time"] > "0945" and row["time"] <= "1030"
    ]
    max_high = max([row["high"] for row in path]) if path else None
    no_follow = (
        max_high is not None
        and max_high < entry["close"] * 1.05
        and check["close"] <= entry["close"] * 0.97
    )
    log(
        "CHECK_1030",
        selected["code"],
        "entry=",
        round(entry["close"], 6),
        "max_high=",
        round(max_high, 6) if max_high is not None else None,
        "close1030=",
        round(check["close"], 6),
        "early_no_follow=",
        no_follow,
    )


def evaluate_exit_time(label, time_text):
    state = ContextInfo_global.probe_state
    selected = state.get("selected_putrev")
    if selected is None:
        log(label, "no_selected_putrev")
        return
    values = state["bars"].get(selected["code"], [])
    entry = last_bar_at_or_before(values, "0945")
    bar = last_bar_at_or_before(values, time_text)
    if entry is None or bar is None:
        log(label, selected["code"], "missing_bar")
        return
    ret = bar["close"] / entry["close"] - 1.0 if entry["close"] > 0 else None
    log(
        label,
        selected["code"],
        "close=",
        round(bar["close"], 6),
        "ret_from_0945=",
        round(ret, 6) if ret is not None else None,
        "volume_seen=",
        round(sum(row["volume"] for row in values), 2),
    )


ContextInfo_global = None


def init(ContextInfo):
    global ContextInfo_global
    ContextInfo_global = ContextInfo
    ContextInfo.probe_state = {
        "done_dates": {},
        "daily": preload_daily_data(ContextInfo),
        "daily_metrics": {},
        "bars": {},
        "universe": [],
        "selected_putrev": None,
        "last_bar_text": "",
    }
    ContextInfo.set_universe(UNDERLYINGS)
    log("INIT", "period=", getattr(ContextInfo, "period", None))
    log("EXPECTED_DATE", EXPECTED_DATE)
    log("NO_ORDERS_WILL_BE_SENT")
    log("BASELINE", "premium_cap=", ABS_PREMIUM_CAP, "volume_share=", CAPACITY_VOLUME_SHARE)


def handlebar(ContextInfo):
    global ContextInfo_global
    ContextInfo_global = ContextInfo
    now_text, current_date, time_text = current_datetime(ContextInfo)
    if current_date <= 0 or len(time_text) != 4:
        return
    if now_text == ContextInfo.probe_state.get("last_bar_text", ""):
        return
    ContextInfo.probe_state["last_bar_text"] = now_text
    if current_date != EXPECTED_DATE:
        if not ContextInfo.probe_state["done_dates"].get(current_date):
            log(
                "WRONG_DATE",
                "expected=",
                EXPECTED_DATE,
                "actual=",
                current_date,
                "rerun_backtest_on_expected_date",
            )
            ContextInfo.probe_state["done_dates"][current_date] = True
        return

    bar = read_bar(ContextInfo, KCB_CODE)
    if bar is None:
        log("ETF_BAR_MISSING", now_text)
        return
    append_bar(ContextInfo.probe_state["bars"], KCB_CODE, now_text, time_text, bar)

    if time_text == "0930":
        daily = daily_metrics(ContextInfo.probe_state["daily"], current_date)
        ContextInfo.probe_state["daily_metrics"] = daily
        log("FIRST_BAR", now_text, "barpos=", ContextInfo.barpos)
        log("ETF_0930_BAR", repr(bar))
        log(
            "DAILY_METRICS",
            "ready=",
            daily.get("ready"),
            "completed=",
            daily.get("completed"),
            "last_date=",
            daily.get("last_date"),
            "direction=",
            daily.get("direction"),
            "ma20=",
            round(daily.get("ma20"), 6) if daily.get("ma20") is not None else None,
            "volume_ratio20=",
            round(daily.get("volume_ratio20"), 4) if daily.get("volume_ratio20") is not None else None,
        )
        ContextInfo.probe_state["universe"] = build_universe(
            ContextInfo,
            current_date,
            bar["close"],
        )

    # Keep option bars only for DTE 10-35 candidates. This is enough for the
    # executable baseline data validation and keeps the QMT backtest light.
    for item in ContextInfo.probe_state.get("universe", []):
        if item["dte"] < DTE_MIN or item["dte"] > DTE_MAX:
            continue
        opt_bar = read_bar(ContextInfo, item["code"])
        if opt_bar is not None:
            append_bar(
                ContextInfo.probe_state["bars"],
                item["code"],
                now_text,
                time_text,
                opt_bar,
            )

    if time_text in PROBE_TIMES:
        log(
            "HEARTBEAT",
            now_text,
            "etf_bars=",
            len(ContextInfo.probe_state["bars"].get(KCB_CODE, [])),
            "universe=",
            len(ContextInfo.probe_state.get("universe", [])),
        )

    if time_text == "0945":
        evaluate_0945(ContextInfo, current_date, now_text)
    if time_text == "1030":
        evaluate_1030(now_text)
    if time_text == "1445":
        evaluate_exit_time("CHECK_1445", "1445")
    if time_text == "1455":
        evaluate_exit_time("CHECK_1455", "1455")
        log("COMPLETE_COPY_ALL_LOG_LINES_TO_CODEX")
