# -*- coding: utf-8 -*-
"""QMT executable script for the KCB 1606.57% baseline.

Run in QMT option strategy trading on a 1-minute chart.

This file is intentionally conservative:
- KCB only: 588000.SH
- one strategy trade per day;
- single-trade premium budget is min(equity * path_pct, 150000);
- 09:45 put-reversal uses momentum ranking, then capacity fallback;
- opening_put_fail catches opening-down weak-pullback failures;
- liquidity-aware orders cap submitted size by current full-tick book depth;
- native QMT orders are sent through the passorder style that was validated
  in the earlier QMT live-sim script.

The script keeps a shadow ledger. QMT order acknowledgements are logged, but
actual broker fills should still be checked in the QMT account/order panel.
"""

from __future__ import print_function

import datetime
import math


# ---------------------------------------------------------------------------
# User configuration
# ---------------------------------------------------------------------------

BUILD_ID = "KCB_1606_LIVE_SIM_20260729_R7_OPENING_PUT_FAIL_P0P1"
KCB_CODE = "588000.SH"
UNDERLYINGS = [KCB_CODE]

INITIAL_CASH = 100000.0
ABS_PREMIUM_CAP = 150000.0
FEE_PER_CONTRACT_PER_SIDE = 2.0
CONTRACT_MULTIPLIER_DEFAULT = 10000

QMT_NATIVE_ORDER_ENABLED = True
QMT_ACCOUNT_ID = "210400032829"
QMT_OPTION_ACCOUNT_TYPE = 1101
QMT_BUY_OPEN_OP = 50
QMT_SELL_CLOSE_OP = 51
QMT_MARKET_PRICE_TYPE = 11
QMT_ORDER_CODE_WITH_SUFFIX = True
QMT_PASSORDER_STYLE = "official9"
QMT_STRATEGY_NAME = "kcb_1032_live_sim"
QMT_QUICK_TRADE = 1
QMT_PRICE_TICK = 0.0001
QMT_BUY_LIMIT_BUFFER = 0.0003
QMT_SELL_LIMIT_BUFFER = 0.0003
QMT_USE_FULL_TICK_BBO = True
QMT_BBO_REQUIRE_LAST_BAR = True
QMT_BBO_MIN_ASK_VOL = 1.0
QMT_BBO_MIN_BID_VOL = 1.0
QMT_LIQUIDITY_AWARE_ORDER = True
QMT_LIQUIDITY_REQUIRE_FULL_TICK = True
QMT_LIQUIDITY_LEVELS = 5
QMT_LIQUIDITY_CONTINUE_ADD = True
QMT_LIQUIDITY_ADD_MAX_PRICE_FACTOR = 1.03
QMT_LIQUIDITY_ADD_MIN_PRICE_FACTOR = 0.98
QMT_LIQUIDITY_ADD_REQUIRE_SIGNAL_ALIVE = True
QMT_LOG_TRADE_DETAIL_AFTER_ORDER = True

LIVE_MAX_TRADES_PER_DAY = 1
LIVE_MAX_CONTRACTS = 0
LIVE_REQUIRE_LAST_BAR_FOR_ORDER = False
LIVE_WALL_CLOCK_GATE = True
LIVE_TRADE_DATE_OVERRIDE = 0

DTE_MIN = 10
DTE_MAX = 35
IV_MIN = 0.20
IV_MAX = 0.70
HIGH_IV_PUT_MAX = 0.90
DELTA_MIN = 0.35
DELTA_MAX = 0.65
PUT_REV_DELTA_MIN = 0.45
PUT_REV_DELTA_MAX = 0.60

OPENING_CALL_RANGE = 0.0030
OPENING_PUT_RANGE = 0.0060
BREAKOUT_VOLUME_MULT = 1.30
BREAKOUT_VOLUME_MAX_MULT = 0.80
OPENING_NORMAL_POSITION = 0.50
OPENING_STRONG_POSITION = 0.70
OPENING_FIRST_LEG_RATIO = 0.65
EARLY_CALL_EXHAUSTION_2D = 0.05

FALLBACK_BASE_POSITION = 0.50
FALLBACK_HIGH_IV_PUT_POSITION = 0.25
FALLBACK_CLUSTER_PUT_POSITION = 0.25
FALLBACK_VOLUME_MULT = 1.80
FALLBACK_VOLUME_PROGRESS = 1.15
FALLBACK_CLUSTER_VOLUME_MULT = 3.0
FALLBACK_SCAN_START_1 = "0945"
FALLBACK_SCAN_END_1 = "1100"
FALLBACK_SCAN_START_2 = "1315"
FALLBACK_SCAN_END_2 = "1415"

PUT_REV_POSITION = 0.20
PUT_REV_ETF_UP_MIN = 0.005
PUT_REV_MIN_PRICE = 0.03
PUT_REV_MIN_VOLUME15 = 1000.0
PUT_REV_MAX_VOLUME_SHARE = 0.05
PUT_REV_TREND_MA20_DEV = 0.03

HARD_STOP_FACTOR = 0.70
OPENING_SOFT_STOP_FACTOR = 0.75
FALLBACK_SOFT_STOP_FACTOR = 0.82
PUT_REV_SOFT_STOP_FACTOR = 0.82
SOFT_STOP_DELAY_MINUTES = 5
NORMAL_TP1_FACTOR = 1.35
NORMAL_TP2_FACTOR = 3.00
STRONG_TP1_FACTOR = 1.50
TRAIL_BEFORE_1030 = 0.35
TRAIL_AFTER_1030 = 0.20
PUT_REV_TREND_QUICK_TP = 1.10
PUT_REV_NO_FOLLOW_HIGH = 1.05
PUT_REV_NO_FOLLOW_CLOSE = 0.97
PUT_REV_HOLD_WINNER_ENABLED = True
PUT_REV_HOLD_TRIGGER_FACTOR = 1.35
PUT_REV_HOLD_SCALE_FACTOR = 1.50
PUT_REV_HOLD_SCALE_RATIO = 1.0 / 3.0
PUT_REV_HOLD_TRAIL = 0.12
PUT_REV_HOLD_CLOSE_NEAR_HIGH = 0.92
PUT_REV_HOLD_ETF_FOLLOW_MIN = 0.0
PUT_REV_HOLD_LATEST_TRIGGER_TIME = "1430"

OPENING_PUT_FAIL_ENABLED = True
OPENING_PUT_FAIL_POSITION = 0.25
OPENING_PUT_FAIL_POSITION_CAP = 25000.0
OPENING_PUT_FAIL_ETF_DOWN_MIN = 0.006
OPENING_PUT_FAIL_CLOSE_POS_MAX = 0.35
OPENING_PUT_FAIL_SCAN_START = "0946"
OPENING_PUT_FAIL_SCAN_END = "1000"
OPENING_PUT_FAIL_MAX_REBOUND = 0.005
OPENING_PUT_FAIL_BREAK_CONFIRM = 0.001
OPENING_PUT_FAIL_MIN_PRICE = 0.03
OPENING_PUT_FAIL_MIN_VOLUME15 = 1000.0
OPENING_PUT_FAIL_MAX_VOLUME_SHARE = 0.05
OPENING_PUT_FAIL_DELTA_MIN = 0.45
OPENING_PUT_FAIL_DELTA_MAX = 0.60
OPENING_PUT_FAIL_STOP_FACTOR = 0.88
OPENING_PUT_FAIL_TP1_FACTOR = 1.25
OPENING_PUT_FAIL_TP2_FACTOR = 1.45
OPENING_PUT_FAIL_TRAIL = 0.12
OPENING_PUT_FAIL_EOD_TIME = "1445"

PUT_REV_EOD_TIME = "1445"
NORMAL_EOD_TIME = "1455"

HEARTBEAT_MINUTES = [
    "0930", "0935", "0940", "0945", "1000", "1030",
    "1100", "1315", "1400", "1445", "1455", "1500",
]


# Daily warmup seed through 2026-07-23. The probe showed that this QMT
# installation raises "No module named pandas" for get_market_data_ex daily
# bars, so the executable script uses this seed and live minute aggregation.
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


RUNTIME_ORDER_KEYS = set()


def log(*items):
    print("[KCB_1032_EXEC]", *items)


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


def yyyymmdd_date(value):
    text = str(safe_int(value))
    if len(text) != 8:
        return None
    try:
        return datetime.date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except Exception:
        return None


def days_to_expiry(current_date, expiry_date):
    left = yyyymmdd_date(current_date)
    right = yyyymmdd_date(expiry_date)
    if left is None or right is None:
        return None
    return (right - left).days


def mean(values):
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / float(len(clean))


def sma(values, window):
    if len(values) < window:
        return None
    return sum(values[-window:]) / float(window)


def ema_series(values, span):
    if not values:
        return []
    alpha = 2.0 / float(span + 1)
    output = [values[0]]
    for value in values[1:]:
        output.append(value * alpha + output[-1] * (1.0 - alpha))
    return output


def normal_cdf(value):
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def bs_price(spot, strike, rate, iv, dte, option_type):
    if spot is None or strike is None or iv is None:
        return None
    if spot <= 0 or strike <= 0 or iv <= 0 or dte <= 0:
        return None
    years = float(dte) / 365.0
    root_time = math.sqrt(years)
    denominator = iv * root_time
    if denominator <= 0:
        return None
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * years) / denominator
    d2 = d1 - denominator
    discounted_strike = strike * math.exp(-rate * years)
    if option_type == "CALL":
        return spot * normal_cdf(d1) - discounted_strike * normal_cdf(d2)
    return discounted_strike * normal_cdf(-d2) - spot * normal_cdf(-d1)


def implied_volatility(market_price, spot, strike, rate, dte, option_type):
    if market_price is None or market_price <= 0:
        return None
    intrinsic = max(strike - spot, 0.0) if option_type == "PUT" else max(spot - strike, 0.0)
    if market_price + 0.000001 < intrinsic:
        return None
    low = 0.01
    high = 3.0
    high_price = bs_price(spot, strike, rate, high, dte, option_type)
    if high_price is None or high_price < market_price:
        return None
    for unused in range(70):
        middle = (low + high) / 2.0
        model_price = bs_price(spot, strike, rate, middle, dte, option_type)
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
    if spot is None or strike is None or iv is None:
        return None
    if spot <= 0 or strike <= 0 or iv <= 0 or dte <= 0:
        return None
    years = float(dte) / 365.0
    denominator = iv * math.sqrt(years)
    if denominator <= 0:
        return None
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * years) / denominator
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


def wall_clock_date():
    try:
        return safe_int(datetime.datetime.now().strftime("%Y%m%d"))
    except Exception:
        return 0


def live_trade_date():
    override = safe_int(LIVE_TRADE_DATE_OVERRIDE)
    if override > 0:
        return override
    return wall_clock_date()


def live_date_gate_allows(ContextInfo, now_text, current_date):
    if not LIVE_WALL_CLOCK_GATE:
        return True
    target_date = live_trade_date()
    if target_date <= 0:
        return True
    if current_date == target_date:
        return True
    if not getattr(ContextInfo, "live_date_gate_skip_logged", False):
        ContextInfo.live_date_gate_skip_logged = True
        log(
            "LIVE_DATE_GATE_SKIP",
            "target_date=", target_date,
            "first_skipped_bar=", now_text,
            "bar_date=", current_date,
            "note=", "historical_bar_ignored",
        )
    return False


def read_native_account_snapshot():
    attempts = [
        (QMT_ACCOUNT_ID, QMT_OPTION_ACCOUNT_TYPE, "account"),
        (QMT_ACCOUNT_ID, QMT_OPTION_ACCOUNT_TYPE, "account", QMT_STRATEGY_NAME),
    ]
    for args in attempts:
        try:
            return True, get_trade_detail_data(*args)
        except Exception:
            pass
    return False, None


def read_native_trade_detail(kind):
    attempts = [
        (QMT_ACCOUNT_ID, QMT_OPTION_ACCOUNT_TYPE, kind),
        (QMT_ACCOUNT_ID, QMT_OPTION_ACCOUNT_TYPE, kind, QMT_STRATEGY_NAME),
    ]
    last_error = None
    for args in attempts:
        try:
            return True, get_trade_detail_data(*args)
        except Exception as exc:
            last_error = repr(exc)
    return False, last_error


def log_trade_detail_snapshots(ContextInfo, label):
    if not QMT_LOG_TRADE_DETAIL_AFTER_ORDER:
        return
    for kind in ["order", "deal", "position", "account"]:
        ok, data = read_native_trade_detail(kind)
        log("TRADE_DETAIL", label, "kind=", kind, "ok=", ok, "data=", short_repr(data))


def log_live_account_status(ContextInfo, label):
    native_ok, native_snapshot = read_native_account_snapshot()
    position_code = ContextInfo.position["code"] if ContextInfo.position else "NONE"
    snapshot_text = repr(native_snapshot)
    if len(snapshot_text) > 500:
        snapshot_text = snapshot_text[:500] + "...TRUNCATED"
    log(
        "LIVE_ACCOUNT_STATUS",
        label,
        "account=", masked_account(QMT_ACCOUNT_ID),
        "native_ok=", native_ok,
        "native=", snapshot_text,
        "shadow_cash=", round(ContextInfo.cash, 2),
        "shadow_equity=", round(paper_equity(ContextInfo), 2),
        "shadow_position=", position_code,
        "day_entries=", ContextInfo.day_entries,
        "trade_count=", ContextInfo.trade_count,
    )


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
                found = recursive_number(nested.get(field_name), code, field_name)
                if found is not None:
                    return found
    return None


def read_field(ContextInfo, code, field_name):
    try:
        raw = ContextInfo.get_market_data([field_name], stock_code=[code], period=ContextInfo.period)
        return recursive_number(raw, code, field_name)
    except Exception:
        return None


def read_bar(ContextInfo, code):
    fields = ["open", "high", "low", "close", "volume", "amount"]
    output = {}
    try:
        raw = ContextInfo.get_market_data(fields, stock_code=[code], period=ContextInfo.period)
        for field_name in fields:
            output[field_name] = recursive_number(raw, code, field_name)
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


def option_type_norm(value):
    text = str(value).upper()
    if text in ["CALL", "C", "1"]:
        return "CALL"
    if text in ["PUT", "P", "2"]:
        return "PUT"
    return text


def read_option_iv(ContextInfo, code, spot, strike, rate, dte, option_type, market_price):
    reversed_iv = implied_volatility(market_price, spot, strike, rate, dte, option_type)
    if reversed_iv is not None:
        return reversed_iv, "reversed"
    try:
        qmt_iv = normalize_iv(ContextInfo.get_option_iv(code))
        if qmt_iv is not None:
            return qmt_iv, "qmt"
    except Exception:
        pass
    return None, "missing"


def round_order_price(value):
    number = safe_float(value)
    if number is None or number <= 0:
        return -1
    ticks = int(number / QMT_PRICE_TICK + 0.5)
    return round(max(ticks * QMT_PRICE_TICK, QMT_PRICE_TICK), 4)


def qmt_order_price(side, reference_price):
    reference = safe_float(reference_price)
    if reference is None or reference <= 0:
        return -1
    if side == "buy":
        return round_order_price(reference + QMT_BUY_LIMIT_BUFFER)
    return round_order_price(reference - QMT_SELL_LIMIT_BUFFER)


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


def positive_number_at(value, index):
    if isinstance(value, (list, tuple)):
        if index < len(value):
            number = safe_float(value[index])
            if number is not None and number > 0:
                return number
        return None
    if index == 0:
        return first_positive_number(value)
    return None


def read_tick_key(row, keys):
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


def tick_level_value(row, side, field_name, level_index):
    if side == "ask" and field_name == "price":
        base = read_tick_key(row, ["askPrice", "ask_price", "ask", "sellPrice"])
        numbered = [
            "askPrice%d" % (level_index + 1),
            "ask%d" % (level_index + 1),
            "sellPrice%d" % (level_index + 1),
            "sell%dPrice" % (level_index + 1),
        ]
    elif side == "ask" and field_name == "volume":
        base = read_tick_key(row, ["askVol", "ask_vol", "askVolume", "sellVol"])
        numbered = [
            "askVol%d" % (level_index + 1),
            "askVolume%d" % (level_index + 1),
            "sellVol%d" % (level_index + 1),
            "sell%dVol" % (level_index + 1),
        ]
    elif side == "bid" and field_name == "price":
        base = read_tick_key(row, ["bidPrice", "bid_price", "bid", "buyPrice"])
        numbered = [
            "bidPrice%d" % (level_index + 1),
            "bid%d" % (level_index + 1),
            "buyPrice%d" % (level_index + 1),
            "buy%dPrice" % (level_index + 1),
        ]
    else:
        base = read_tick_key(row, ["bidVol", "bid_vol", "bidVolume", "buyVol"])
        numbered = [
            "bidVol%d" % (level_index + 1),
            "bidVolume%d" % (level_index + 1),
            "buyVol%d" % (level_index + 1),
            "buy%dVol" % (level_index + 1),
        ]
    found = positive_number_at(base, level_index)
    if found is not None:
        return found
    return first_positive_number(read_tick_key(row, numbered))


def tick_side_levels(row, side):
    levels = []
    for idx in range(max(1, safe_int(QMT_LIQUIDITY_LEVELS, 5))):
        price = tick_level_value(row, side, "price", idx)
        volume = tick_level_value(row, side, "volume", idx)
        if price is not None and price > 0 and volume is not None and volume > 0:
            levels.append((price, volume))
    return levels


def format_levels(levels):
    text = []
    for idx, item in enumerate(levels or []):
        text.append("%d:%.4f/%d" % (idx + 1, item[0], int(item[1])))
    return ",".join(text)


def executable_qty_from_levels(side, levels, limit_price):
    quantity = 0
    notional = 0.0
    worst_price = None
    for price, volume in levels or []:
        if side == "buy" and price > limit_price:
            continue
        if side == "sell" and price < limit_price:
            continue
        take = int(volume)
        if take <= 0:
            continue
        quantity += take
        notional += take * price
        worst_price = price
    avg_price = notional / float(quantity) if quantity > 0 else None
    return quantity, avg_price, worst_price


def can_use_bbo_now(ContextInfo):
    if not QMT_USE_FULL_TICK_BBO:
        return False, "disabled"
    if not QMT_BBO_REQUIRE_LAST_BAR:
        return True, "enabled"
    try:
        if ContextInfo.is_last_bar():
            return True, "last_bar"
        return False, "not_last_bar"
    except Exception as exc:
        return False, "last_bar_check_error:%s" % repr(exc)


def read_full_tick_bbo(ContextInfo, code):
    allowed, reason = can_use_bbo_now(ContextInfo)
    if not allowed:
        return {"ok": False, "source": reason}
    try:
        raw = ContextInfo.get_full_tick([code])
    except Exception as exc:
        return {"ok": False, "source": "full_tick_error", "error": repr(exc)}
    row = nested_tick_row(raw, code)
    if not isinstance(row, dict):
        return {"ok": False, "source": "full_tick_empty"}
    bid1 = first_positive_number(read_tick_key(row, ["bidPrice", "bid_price", "bidPrice1", "bid1", "buyPrice", "buy1Price"]))
    ask1 = first_positive_number(read_tick_key(row, ["askPrice", "ask_price", "askPrice1", "ask1", "sellPrice", "sell1Price"]))
    bidv1 = first_positive_number(read_tick_key(row, ["bidVol", "bid_vol", "bidVol1", "bidVolume", "buyVol", "buy1Vol"]))
    askv1 = first_positive_number(read_tick_key(row, ["askVol", "ask_vol", "askVol1", "askVolume", "sellVol", "sell1Vol"]))
    last_price = first_positive_number(read_tick_key(row, ["lastPrice", "last_price", "price", "close"]))
    bid_levels = tick_side_levels(row, "bid")
    ask_levels = tick_side_levels(row, "ask")
    if bid1 is None and bid_levels:
        bid1 = bid_levels[0][0]
    if bidv1 is None and bid_levels:
        bidv1 = bid_levels[0][1]
    if ask1 is None and ask_levels:
        ask1 = ask_levels[0][0]
    if askv1 is None and ask_levels:
        askv1 = ask_levels[0][1]
    return {
        "ok": bid1 is not None or ask1 is not None,
        "source": "full_tick",
        "bid1": bid1,
        "ask1": ask1,
        "bidv1": bidv1,
        "askv1": askv1,
        "bid_levels": bid_levels,
        "ask_levels": ask_levels,
        "last": last_price,
        "time": read_tick_key(row, ["time", "timetag"]),
    }


def build_order_quote(ContextInfo, side, code, reference_price):
    bbo = read_full_tick_bbo(ContextInfo, code)
    source = "bar_close_fallback"
    reference = safe_float(reference_price)
    available_qty = None
    if side == "buy" and bbo.get("ask1") is not None:
        reference = bbo.get("ask1")
        source = "ask1"
        available_qty = bbo.get("askv1")
    elif side == "sell" and bbo.get("bid1") is not None:
        reference = bbo.get("bid1")
        source = "bid1"
        available_qty = bbo.get("bidv1")
    order_price = qmt_order_price(side, reference)
    if order_price <= 0:
        order_price = qmt_order_price(side, reference_price)
        source = "bar_close_fallback"
    output = {
        "order_price": order_price,
        "quote_ref": reference,
        "quote_source": source,
        "available_qty": available_qty,
        "bid1": bbo.get("bid1"),
        "ask1": bbo.get("ask1"),
        "bidv1": bbo.get("bidv1"),
        "askv1": bbo.get("askv1"),
        "bid_levels": bbo.get("bid_levels", []),
        "ask_levels": bbo.get("ask_levels", []),
        "last": bbo.get("last"),
        "tick_time": bbo.get("time"),
        "bbo_source": bbo.get("source"),
    }
    if order_price > 0:
        levels = output.get("ask_levels") if side == "buy" else output.get("bid_levels")
        liq_qty, liq_avg, liq_worst = executable_qty_from_levels(side, levels, order_price)
        output["liquidity_qty"] = liq_qty
        output["liquidity_avg"] = liq_avg
        output["liquidity_worst"] = liq_worst
    else:
        output["liquidity_qty"] = None
        output["liquidity_avg"] = None
        output["liquidity_worst"] = None
    return output


def log_order_quote(side, code, quantity, quote):
    available = quote.get("available_qty")
    if side == "buy":
        enough = available is not None and available >= max(QMT_BBO_MIN_ASK_VOL, quantity)
    else:
        enough = available is not None and available >= max(QMT_BBO_MIN_BID_VOL, quantity)
    log(
        "ORDER_QUOTE_BBO",
        side,
        code,
        "qty=", int(quantity),
        "source=", quote.get("quote_source"),
        "order_price=", quote.get("order_price"),
        "quote_ref=", round(quote.get("quote_ref"), 6) if quote.get("quote_ref") is not None else None,
        "bid1=", quote.get("bid1"),
        "bidv1=", quote.get("bidv1"),
        "ask1=", quote.get("ask1"),
        "askv1=", quote.get("askv1"),
        "bbo_enough=", enough,
        "liq_qty=", quote.get("liquidity_qty"),
        "liq_avg=", round(quote.get("liquidity_avg"), 6) if quote.get("liquidity_avg") is not None else None,
        "liq_worst=", quote.get("liquidity_worst"),
        "bid_levels=", format_levels(quote.get("bid_levels")),
        "ask_levels=", format_levels(quote.get("ask_levels")),
        "tick_time=", quote.get("tick_time"),
        "bbo_source=", quote.get("bbo_source"),
    )


def log_order_expected_fill(side, code, quantity, quote, label):
    reference_price = quote.get("liquidity_avg")
    if reference_price is None:
        reference_price = quote.get("quote_ref")
    if reference_price is None:
        reference_price = quote.get("order_price")
    multiplier = safe_int(quote.get("multiplier"), CONTRACT_MULTIPLIER_DEFAULT)
    expected_amount = None
    if reference_price is not None:
        expected_amount = reference_price * quantity * multiplier
    log(
        "ORDER_EXPECTED_FILL",
        label,
        side,
        code,
        "qty=", int(quantity),
        "order_price=", quote.get("order_price"),
        "quote_source=", quote.get("quote_source"),
        "bid1=", quote.get("bid1"),
        "ask1=", quote.get("ask1"),
        "liq_qty=", quote.get("liquidity_qty"),
        "liq_avg=", round(quote.get("liquidity_avg"), 6) if quote.get("liquidity_avg") is not None else None,
        "liq_worst=", quote.get("liquidity_worst"),
        "expected_amount=", round(expected_amount, 2) if expected_amount is not None else None,
        "expected_fee=", round(quantity * FEE_PER_CONTRACT_PER_SIDE, 2),
        "bid_levels=", format_levels(quote.get("bid_levels")),
        "ask_levels=", format_levels(quote.get("ask_levels")),
    )


def submit_qmt_order(ContextInfo, side, code, quantity, reference_price, quote=None):
    global RUNTIME_ORDER_KEYS
    if quote is None:
        quote = build_order_quote(ContextInfo, side, code, reference_price)
    log_order_quote(side, code, quantity, quote)
    log_order_expected_fill(side, code, quantity, quote, "before_submit")
    if not QMT_NATIVE_ORDER_ENABLED:
        log("ORDER_DRY_RUN", side, code, "qty=", int(quantity))
        return True
    if LIVE_REQUIRE_LAST_BAR_FOR_ORDER:
        try:
            if not ContextInfo.is_last_bar():
                log("QMT_ORDER_BLOCKED", "not_last_bar", side, code)
                return False
        except Exception:
            pass
    now_text, unused_date, unused_time = current_datetime(ContextInfo)
    key = (now_text, side, str(code), int(quantity))
    if key in RUNTIME_ORDER_KEYS:
        log("QMT_ORDER_BLOCKED", "duplicate", repr(key))
        return False
    RUNTIME_ORDER_KEYS.add(key)
    account_id = getattr(ContextInfo, "live_account_id", QMT_ACCOUNT_ID)
    operation = QMT_BUY_OPEN_OP if side == "buy" else QMT_SELL_CLOSE_OP
    order_code = str(code) if QMT_ORDER_CODE_WITH_SUFFIX else str(code).split(".")[0]
    order_price = quote.get("order_price")
    log(
        "PASSORDER_ARGS",
        "style=", QMT_PASSORDER_STYLE,
        "operation=", operation,
        "account_type=", QMT_OPTION_ACCOUNT_TYPE,
        "account=", masked_account(account_id),
        "code=", order_code,
        "price_type=", QMT_MARKET_PRICE_TYPE,
        "price=", order_price,
        "ref_price=", round(reference_price, 6) if reference_price is not None else None,
        "quote_source=", quote.get("quote_source"),
        "quote_ref=", round(quote.get("quote_ref"), 6) if quote.get("quote_ref") is not None else None,
        "qty=", int(quantity),
        "strategy=", QMT_STRATEGY_NAME,
    )
    try:
        if QMT_PASSORDER_STYLE == "official9":
            result = passorder(
                operation,
                QMT_OPTION_ACCOUNT_TYPE,
                account_id,
                order_code,
                QMT_MARKET_PRICE_TYPE,
                order_price,
                int(quantity),
                QMT_QUICK_TRADE,
                ContextInfo,
            )
        else:
            result = passorder(
                operation,
                QMT_OPTION_ACCOUNT_TYPE,
                account_id,
                order_code,
                QMT_MARKET_PRICE_TYPE,
                order_price,
                int(quantity),
                ContextInfo,
            )
        log("PASSORDER_RETURN", repr(result))
        log_trade_detail_snapshots(ContextInfo, "after_passorder_%s_%s" % (side, str(code)))
        return True
    except Exception as exc:
        log("PASSORDER_ERROR", repr(exc))
        log_trade_detail_snapshots(ContextInfo, "after_passorder_error_%s_%s" % (side, str(code)))
        return False


def seed_daily_rows():
    rows = []
    for item in KCB_DAILY_SEED:
        rows.append({
            "date": item[0],
            "open": item[1],
            "high": item[2],
            "low": item[3],
            "close": item[4],
            "volume": item[5],
            "amount": item[6],
        })
    rows.sort(key=lambda row: row["date"])
    return rows


def daily_metrics(rows, current_date):
    completed = [row for row in rows if row.get("date", 0) < current_date]
    closes = [row["close"] for row in completed]
    volumes = [row["volume"] for row in completed]
    if len(completed) < 21:
        return {"ready": False, "completed": len(completed)}
    ma5 = sma(closes, 5)
    ma10 = sma(closes, 10)
    ma20 = sma(closes, 20)
    prev_ma5 = mean(closes[-6:-1])
    prev_ma20 = mean(closes[-21:-1])
    ma5_slope = ma5 - prev_ma5
    ma20_slope = ma20 - prev_ma20
    last = completed[-1]
    avg_volume20 = mean(volumes[-20:])
    volume_ratio20 = last["volume"] / avg_volume20 if avg_volume20 else None
    direction = "none"
    if last["close"] > ma5 > ma10 > ma20 and ma5_slope > 0 and ma20_slope >= 0:
        direction = "call"
    elif last["close"] < ma5 < ma10 < ma20 and ma5_slope < 0 and ma20_slope <= 0:
        direction = "put"
    two_day_return = None
    if len(completed) >= 3 and completed[-3]["close"] > 0:
        two_day_return = completed[-1]["close"] / completed[-3]["close"] - 1.0
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
        "two_day_return": two_day_return,
    }


def append_bar(store, code, now_text, time_text, bar):
    values = store.setdefault(code, [])
    values.append({
        "datetime": now_text,
        "time": time_text,
        "open": bar["open"],
        "high": bar["high"],
        "low": bar["low"],
        "close": bar["close"],
        "volume": bar["volume"],
        "amount": bar["amount"],
    })
    if len(values) > 320:
        store[code] = values[-320:]


def bars_between(values, start_time, end_time):
    return [row for row in values if row.get("time", "") >= start_time and row.get("time", "") <= end_time]


def first_bar(values):
    return values[0] if values else None


def last_bar_at_or_before(values, time_text):
    output = None
    for row in values:
        if row.get("time", "") <= time_text:
            output = row
    return output


def volume15(values):
    return sum(row["volume"] for row in bars_between(values, "0930", "0945"))


def build_universe(ContextInfo, current_date, spot):
    try:
        option_codes = ContextInfo.get_option_undl_data(KCB_CODE)
    except Exception as exc:
        log("OPTION_UNIVERSE_ERROR", repr(exc))
        return []
    rows = []
    type_counts = {}
    for option_code in option_codes or []:
        try:
            detail = ContextInfo.get_option_detail_data(option_code)
        except Exception:
            continue
        if not isinstance(detail, dict):
            continue
        open_date = safe_int(detail.get("OpenDate", 0))
        expire_date = safe_int(detail.get("ExpireDate", 0))
        strike = safe_float(detail.get("OptExercisePrice"))
        option_type = option_type_norm(detail.get("optType", ""))
        type_counts[option_type] = type_counts.get(option_type, 0) + 1
        if option_type not in ["CALL", "PUT"]:
            continue
        if strike is None or strike <= 0:
            continue
        if not (open_date <= current_date <= expire_date):
            continue
        dte = days_to_expiry(current_date, expire_date)
        if dte is None:
            continue
        rate = safe_float(detail.get("OptUndlRiskFreeRate"), 0.02)
        multiplier = safe_int(detail.get("OptUnit", detail.get("VolumeMultiple", CONTRACT_MULTIPLIER_DEFAULT)), CONTRACT_MULTIPLIER_DEFAULT)
        rows.append({
            "code": str(option_code),
            "type": option_type,
            "strike": strike,
            "expire": expire_date,
            "dte": dte,
            "rate": rate,
            "multiplier": multiplier,
            "distance": abs(strike - spot) if spot is not None else 0.0,
        })
    rows.sort(key=lambda row: (row["type"], row["dte"], row["strike"]))
    log("OPTION_UNIVERSE", "total=", len(option_codes or []), "parsed=", len(rows), "types=", repr(type_counts))
    return rows


def get_option_snapshot(ContextInfo, item, spot, time_text):
    values = ContextInfo.state["bars"].get(item["code"], [])
    bar = last_bar_at_or_before(values, time_text)
    if bar is None:
        return None
    price = bar.get("close")
    if price is None or price <= 0:
        return None
    iv, iv_source = read_option_iv(ContextInfo, item["code"], spot, item["strike"], item["rate"], item["dte"], item["type"], price)
    if iv is None:
        return None
    delta = bs_delta(spot, item["strike"], item["rate"], iv, item["dte"], item["type"])
    if delta is None:
        return None
    result = dict(item)
    result.update({
        "price": price,
        "iv": iv,
        "iv_source": iv_source,
        "delta": delta,
        "volume15": volume15(values),
        "bars": values,
    })
    return result


def select_option(ContextInfo, direction, spot, time_text, allow_high_iv_put):
    target_type = "CALL" if direction == "call" else "PUT"
    candidates = []
    for item in ContextInfo.state.get("universe", []):
        if item["type"] != target_type:
            continue
        if item["dte"] < DTE_MIN or item["dte"] > DTE_MAX:
            continue
        snap = get_option_snapshot(ContextInfo, item, spot, time_text)
        if snap is None:
            continue
        iv_max = HIGH_IV_PUT_MAX if (allow_high_iv_put and target_type == "PUT") else IV_MAX
        if snap["iv"] < IV_MIN or snap["iv"] > iv_max:
            continue
        if abs(snap["delta"]) < DELTA_MIN or abs(snap["delta"]) > DELTA_MAX:
            continue
        values = snap.get("bars", [])
        recent = values[-8:]
        trend_score = 0.0
        if len(recent) >= 3:
            trend_score = recent[-1]["close"] / recent[0]["open"] - 1.0 if recent[0]["open"] > 0 else 0.0
        score = (
            -abs(abs(snap["delta"]) - 0.50) * 10.0
            - abs(snap["dte"] - 20) * 0.02
            + math.log(max(snap["volume15"], 1.0)) * 0.05
            + trend_score
        )
        snap["score"] = score
        candidates.append(snap)
    candidates.sort(key=lambda row: row["score"], reverse=True)
    if candidates:
        log("SELECT_OPTION", direction, candidates[0]["code"], "price=", round(candidates[0]["price"], 6), "iv=", round(candidates[0]["iv"], 4), "delta=", round(candidates[0]["delta"], 4), "score=", round(candidates[0]["score"], 4))
        return candidates[0]
    log("SELECT_OPTION_NONE", direction, "allow_high_iv=", allow_high_iv_put)
    return None


def select_put_reversal(ContextInfo, spot, time_text):
    candidates = []
    rejects = {"dte": 0, "price": 0, "iv": 0, "delta": 0, "volume15": 0, "capacity": 0}
    for item in ContextInfo.state.get("universe", []):
        if item["type"] != "PUT":
            continue
        if item["dte"] < DTE_MIN or item["dte"] > DTE_MAX:
            rejects["dte"] += 1
            continue
        snap = get_option_snapshot(ContextInfo, item, spot, time_text)
        if snap is None:
            rejects["iv"] += 1
            continue
        if snap["price"] < PUT_REV_MIN_PRICE:
            rejects["price"] += 1
            continue
        if abs(snap["delta"]) < PUT_REV_DELTA_MIN or abs(snap["delta"]) > PUT_REV_DELTA_MAX:
            rejects["delta"] += 1
            continue
        if snap["volume15"] < PUT_REV_MIN_VOLUME15:
            rejects["volume15"] += 1
            continue
        open_bar = first_bar(snap["bars"])
        momentum = snap["price"] / open_bar["open"] - 1.0 if open_bar and open_bar["open"] > 0 else 0.0
        snap["momentum15"] = momentum
        candidates.append(snap)
    candidates.sort(key=lambda row: row["momentum15"], reverse=True)
    budget = min(paper_equity(ContextInfo) * PUT_REV_POSITION, ABS_PREMIUM_CAP)
    selected = None
    for row in candidates:
        planned = int(budget / float((row["price"] + QMT_BUY_LIMIT_BUFFER) * row["multiplier"]))
        cap_limit = row["volume15"] * PUT_REV_MAX_VOLUME_SHARE
        row["planned_qty"] = planned
        row["cap_limit"] = cap_limit
        row["capacity_ok"] = planned > 0 and planned <= cap_limit
        if selected is None and row["capacity_ok"]:
            selected = row
        elif not row["capacity_ok"]:
            rejects["capacity"] += 1
    log("PUTREV_REJECTS", repr(rejects), "candidates=", len(candidates))
    for row in candidates[:5]:
        log("PUTREV_CAND", row["code"], "strike=", row["strike"], "price=", round(row["price"], 6), "delta=", round(row["delta"], 4), "iv=", round(row["iv"], 4), "vol15=", round(row["volume15"], 2), "mom=", round(row["momentum15"], 6), "planned=", row.get("planned_qty"), "cap=", round(row.get("cap_limit", 0), 2))
    if selected:
        log("PUTREV_SELECTED", selected["code"], "reason=", "momentum_capacity")
    else:
        log("PUTREV_SELECTED", "NONE")
    return selected


def opening_put_fail_stats(ContextInfo):
    etf_bars = ContextInfo.state["bars"].get(KCB_CODE, [])
    first15 = bars_between(etf_bars, "0930", "0945")
    open_bar = first_bar(etf_bars)
    bar945 = last_bar_at_or_before(etf_bars, "0945")
    if not first15 or open_bar is None or bar945 is None or open_bar["open"] <= 0:
        return None
    high15 = max(row["high"] for row in first15)
    low15 = min(row["low"] for row in first15)
    width = high15 - low15
    close945 = bar945["close"]
    close_pos = (close945 - low15) / width if width > 0 else 0.5
    etf_return = close945 / open_bar["open"] - 1.0
    return {
        "open": open_bar["open"],
        "close945": close945,
        "high15": high15,
        "low15": low15,
        "close_pos": close_pos,
        "return945": etf_return,
    }


def opening_put_fail_trigger_ok(ContextInfo, time_text):
    stats = opening_put_fail_stats(ContextInfo)
    if stats is None:
        return False, None
    if stats["return945"] > -OPENING_PUT_FAIL_ETF_DOWN_MIN:
        return False, stats
    if stats["close_pos"] > OPENING_PUT_FAIL_CLOSE_POS_MAX:
        return False, stats
    etf_bars = ContextInfo.state["bars"].get(KCB_CODE, [])
    path = [row for row in etf_bars if row["time"] > "0945" and row["time"] <= time_text]
    if not path:
        return False, stats
    max_rebound = max(row["high"] for row in path) / stats["close945"] - 1.0 if stats["close945"] > 0 else 999.0
    if max_rebound > OPENING_PUT_FAIL_MAX_REBOUND:
        stats["max_rebound"] = max_rebound
        return False, stats
    last = last_bar_at_or_before(etf_bars, time_text)
    if last is None:
        return False, stats
    trigger_level = stats["close945"] * (1.0 - OPENING_PUT_FAIL_BREAK_CONFIRM)
    stats["max_rebound"] = max_rebound
    stats["trigger_level"] = trigger_level
    stats["last_close"] = last["close"]
    if last["close"] > trigger_level:
        return False, stats
    return True, stats


def select_opening_put_fail(ContextInfo, spot, time_text):
    candidates = []
    rejects = {"dte": 0, "price": 0, "iv": 0, "delta": 0, "volume15": 0, "capacity": 0}
    budget = min(paper_equity(ContextInfo) * OPENING_PUT_FAIL_POSITION, OPENING_PUT_FAIL_POSITION_CAP, ABS_PREMIUM_CAP)
    for item in ContextInfo.state.get("universe", []):
        if item["type"] != "PUT":
            continue
        if item["dte"] < DTE_MIN or item["dte"] > DTE_MAX:
            rejects["dte"] += 1
            continue
        snap = get_option_snapshot(ContextInfo, item, spot, time_text)
        if snap is None:
            rejects["iv"] += 1
            continue
        if snap["price"] < OPENING_PUT_FAIL_MIN_PRICE:
            rejects["price"] += 1
            continue
        if abs(snap["delta"]) < OPENING_PUT_FAIL_DELTA_MIN or abs(snap["delta"]) > OPENING_PUT_FAIL_DELTA_MAX:
            rejects["delta"] += 1
            continue
        if snap["volume15"] < OPENING_PUT_FAIL_MIN_VOLUME15:
            rejects["volume15"] += 1
            continue
        open_bar = first_bar(snap["bars"])
        momentum = snap["price"] / open_bar["open"] - 1.0 if open_bar and open_bar["open"] > 0 else 0.0
        planned = int(budget / float((snap["price"] + QMT_BUY_LIMIT_BUFFER) * snap["multiplier"]))
        cap_limit = snap["volume15"] * OPENING_PUT_FAIL_MAX_VOLUME_SHARE
        snap["momentum_to_entry"] = momentum
        snap["planned_qty"] = planned
        snap["cap_limit"] = cap_limit
        snap["capacity_ok"] = planned > 0 and planned <= cap_limit
        if not snap["capacity_ok"]:
            rejects["capacity"] += 1
            continue
        score = (
            -abs(abs(snap["delta"]) - 0.50) * 10.0
            - abs(snap["dte"] - 20) * 0.02
            + math.log(max(snap["volume15"], 1.0)) * 0.05
            + momentum
        )
        snap["score"] = score
        candidates.append(snap)
    candidates.sort(key=lambda row: row["score"], reverse=True)
    log("OPENPUTFAIL_REJECTS", repr(rejects), "candidates=", len(candidates))
    for row in candidates[:5]:
        log("OPENPUTFAIL_CAND", row["code"], "strike=", row["strike"], "price=", round(row["price"], 6), "delta=", round(row["delta"], 4), "iv=", round(row["iv"], 4), "vol15=", round(row["volume15"], 2), "mom=", round(row["momentum_to_entry"], 6), "planned=", row.get("planned_qty"), "cap=", round(row.get("cap_limit", 0), 2), "score=", round(row.get("score", 0), 4))
    if candidates:
        log("OPENPUTFAIL_SELECTED", candidates[0]["code"], "reason=", "pullback_fail_score_capacity")
        return candidates[0]
    log("OPENPUTFAIL_SELECTED", "NONE")
    return None


def paper_equity(ContextInfo):
    equity = ContextInfo.cash
    pos = ContextInfo.position
    if pos is not None:
        bar = last_bar_at_or_before(ContextInfo.state["bars"].get(pos["code"], []), ContextInfo.state.get("time", ""))
        mark = bar["close"] if bar is not None else pos["avg_price"]
        equity += pos["quantity"] * mark * pos["multiplier"]
    return equity


def position_pct(path, strong, iv):
    if path == "put_reversal_0945":
        return PUT_REV_POSITION
    if path == "opening_put_fail":
        return OPENING_PUT_FAIL_POSITION
    if path == "opening":
        return OPENING_STRONG_POSITION if strong else OPENING_NORMAL_POSITION
    if path == "fallback_high_iv_put":
        return FALLBACK_HIGH_IV_PUT_POSITION
    if path == "fallback_cluster_put":
        return FALLBACK_CLUSTER_PUT_POSITION
    return FALLBACK_BASE_POSITION


def cap_quantity_by_liquidity(side, desired_quantity, quote, label):
    desired = safe_int(desired_quantity)
    if desired <= 0:
        return 0, 0
    if not QMT_LIQUIDITY_AWARE_ORDER:
        return desired, desired
    if quote.get("bbo_source") != "full_tick":
        log("LIQUIDITY_CAP_SKIPPED", label, "source=", quote.get("bbo_source"), "desired=", desired)
        if QMT_LIQUIDITY_REQUIRE_FULL_TICK:
            return 0, desired
        return desired, desired
    liquidity_qty = quote.get("liquidity_qty")
    if liquidity_qty is None:
        log("LIQUIDITY_CAP_SKIPPED", label, "no_liquidity_qty", "desired=", desired)
        return desired, desired
    capped = min(desired, max(0, safe_int(liquidity_qty)))
    log(
        "LIQUIDITY_CAP",
        label,
        "side=", side,
        "desired=", desired,
        "capped=", capped,
        "liq_qty=", liquidity_qty,
        "order_price=", quote.get("order_price"),
        "liq_avg=", round(quote.get("liquidity_avg"), 6) if quote.get("liquidity_avg") is not None else None,
        "liq_worst=", quote.get("liquidity_worst"),
    )
    return capped, desired


def affordable_quantity(ContextInfo, execution_price, multiplier, desired_quantity):
    quantity = safe_int(desired_quantity)
    if quantity <= 0 or execution_price is None or execution_price <= 0:
        return 0
    cost_per_contract = execution_price * multiplier + FEE_PER_CONTRACT_PER_SIDE
    if cost_per_contract <= 0:
        return 0
    return min(quantity, int(max(0.0, ContextInfo.cash) / float(cost_per_contract)))


def apply_buy_fill_to_position(ContextInfo, pos, quantity, fill_price, execution_price):
    premium = quantity * execution_price * pos["multiplier"]
    fee = quantity * FEE_PER_CONTRACT_PER_SIDE
    old_quantity = pos["quantity"]
    old_cost = pos.get("avg_fill_price", pos["avg_price"]) * old_quantity * pos["multiplier"]
    old_signal_cost = pos["avg_price"] * old_quantity * pos["multiplier"]
    ContextInfo.cash -= premium + fee
    pos["quantity"] += quantity
    pos["initial_quantity"] += quantity
    pos["avg_fill_price"] = (old_cost + premium) / float(pos["quantity"] * pos["multiplier"])
    pos["avg_price"] = (old_signal_cost + fill_price * quantity * pos["multiplier"]) / float(pos["quantity"] * pos["multiplier"])
    pos["total_buy"] += premium
    pos["total_fees"] += fee
    pos["high_water"] = max(pos["high_water"], fill_price)


def paper_open(ContextInfo, selected, direction, path, strong, now_text, fill_price, allocation_factor):
    if ContextInfo.position is not None or ContextInfo.day_locked:
        log("BUY_BLOCKED", "position_or_day_locked", now_text, path)
        return False
    if LIVE_MAX_TRADES_PER_DAY > 0 and ContextInfo.day_entries >= LIVE_MAX_TRADES_PER_DAY:
        log("BUY_BLOCKED", "daily_limit", now_text)
        return False
    pct = position_pct(path, strong, selected.get("iv"))
    equity = paper_equity(ContextInfo)
    target_cost = min(equity * pct, ABS_PREMIUM_CAP)
    if path == "opening_put_fail":
        target_cost = min(target_cost, OPENING_PUT_FAIL_POSITION_CAP)
    buy_budget = target_cost * allocation_factor
    quote = build_order_quote(ContextInfo, "buy", selected["code"], fill_price)
    quote["multiplier"] = selected["multiplier"]
    execution_price = quote.get("order_price")
    if execution_price is None or execution_price <= 0:
        log("BUY_BLOCKED", "bad_order_price", path, selected["code"], "price=", fill_price)
        return False
    planned_quantity = int(buy_budget / float(execution_price * selected["multiplier"]))
    if LIVE_MAX_CONTRACTS > 0:
        planned_quantity = min(planned_quantity, LIVE_MAX_CONTRACTS)
    planned_quantity = affordable_quantity(ContextInfo, execution_price, selected["multiplier"], planned_quantity)
    quantity, target_quantity = cap_quantity_by_liquidity("buy", planned_quantity, quote, path)
    if quantity <= 0:
        log("BUY_BLOCKED", "small_or_no_liquidity", path, selected["code"], "budget=", round(buy_budget, 2), "planned=", planned_quantity, "liq_qty=", quote.get("liquidity_qty"))
        return False
    premium = quantity * execution_price * selected["multiplier"]
    fee = quantity * FEE_PER_CONTRACT_PER_SIDE
    if quantity <= 0:
        return False
    if not submit_qmt_order(ContextInfo, "buy", selected["code"], quantity, fill_price, quote):
        log("BUY_ABORTED_ORDER_NOT_SENT", now_text, selected["code"])
        return False
    ContextInfo.cash -= premium + fee
    ContextInfo.position = {
        "code": selected["code"],
        "direction": direction,
        "path": path,
        "strong": bool(strong),
        "quantity": quantity,
        "initial_quantity": quantity,
        "avg_price": fill_price,
        "avg_fill_price": execution_price,
        "first_price": fill_price,
        "multiplier": selected["multiplier"],
        "target_cost": target_cost,
        "entry_time": now_text,
        "entry_minute": safe_int(now_text[8:12]),
        "opening_confirmed": path != "opening",
        "partial_done": False,
        "high_water": fill_price,
        "total_buy": premium,
        "total_sell": 0.0,
        "total_fees": fee,
        "entry_etf": ContextInfo.state.get("last_etf_close"),
        "entry_ma20": ContextInfo.daily_info.get("ma20"),
        "entry_quote_source": quote.get("quote_source"),
        "entry_bid1": quote.get("bid1"),
        "entry_ask1": quote.get("ask1"),
        "entry_bidv1": quote.get("bidv1"),
        "entry_askv1": quote.get("askv1"),
        "liquidity_target_quantity": target_quantity,
        "liquidity_pending_quantity": max(0, target_quantity - quantity),
        "liquidity_add_enabled": QMT_LIQUIDITY_CONTINUE_ADD,
        "last_liquidity_add_bar": "",
        "put_rev_hold_mode": False,
        "put_rev_hold_scale_done": False,
        "put_rev_hold_trailing_stop": None,
        "opening_put_fail_trailing_stop": None,
        "opening_put_fail_hold_mode": False,
    }
    ContextInfo.day_locked = True
    ContextInfo.day_entries += 1
    log("BUY", now_text, path, direction, selected["code"], "qty=", quantity, "planned=", planned_quantity, "pending=", max(0, target_quantity - quantity), "price=", round(fill_price, 6), "fill=", round(execution_price, 6), "pct=", pct, "target_cost=", round(target_cost, 2), "iv=", round(selected.get("iv", 0), 4), "delta=", round(selected.get("delta", 0), 4), "dte=", selected.get("dte"))
    log("ORDER_EXECUTION_SUMMARY", "buy_open", "time=", now_text, "path=", path, "code=", selected["code"], "planned=", planned_quantity, "submitted=", quantity, "pending=", max(0, target_quantity - quantity), "limit=", execution_price, "expected_avg=", round(quote.get("liquidity_avg"), 6) if quote.get("liquidity_avg") is not None else None, "expected_worst=", quote.get("liquidity_worst"), "liq_qty=", quote.get("liquidity_qty"), "expected_amount=", round(premium, 2), "expected_fee=", round(fee, 2), "note=", "compare_with_QMT_deal_panel")
    log("SHADOW_FILL_ASSUMED", "buy", selected["code"], "qty=", quantity)
    return True


def paper_add_opening(ContextInfo, now_text, fill_price):
    pos = ContextInfo.position
    if pos is None or pos["path"] != "opening" or pos["opening_confirmed"]:
        return
    if fill_price > pos["first_price"] * 1.03:
        log("ADD_SKIPPED_PRICE", now_text, "price=", round(fill_price, 6))
        pos["opening_confirmed"] = True
        return
    weighted_mid = pos["first_price"] * OPENING_FIRST_LEG_RATIO + fill_price * (1.0 - OPENING_FIRST_LEG_RATIO)
    quote = build_order_quote(ContextInfo, "buy", pos["code"], fill_price)
    quote["multiplier"] = pos["multiplier"]
    execution_price = quote.get("order_price")
    if execution_price is None or execution_price <= 0:
        pos["opening_confirmed"] = True
        return
    target_qty = int(pos["target_cost"] / float(execution_price * pos["multiplier"]))
    if LIVE_MAX_CONTRACTS > 0:
        target_qty = min(target_qty, LIVE_MAX_CONTRACTS)
    quantity = max(target_qty - pos["quantity"], 0)
    pos["liquidity_target_quantity"] = max(pos.get("liquidity_target_quantity", 0), target_qty)
    if quantity <= 0:
        pos["opening_confirmed"] = True
        return
    quantity = affordable_quantity(ContextInfo, execution_price, pos["multiplier"], quantity)
    quantity, desired_quantity = cap_quantity_by_liquidity("buy", quantity, quote, "opening_confirm_add")
    if quantity <= 0:
        pos["liquidity_pending_quantity"] = max(0, pos.get("liquidity_target_quantity", target_qty) - pos["quantity"])
        log("ADD_SKIPPED_LIQUIDITY", now_text, pos["code"], "desired=", desired_quantity, "pending=", pos["liquidity_pending_quantity"])
        pos["opening_confirmed"] = True
        return
    if not submit_qmt_order(ContextInfo, "buy", pos["code"], quantity, fill_price, quote):
        pos["opening_confirmed"] = True
        return
    apply_buy_fill_to_position(ContextInfo, pos, quantity, fill_price, execution_price)
    pos["opening_confirmed"] = True
    pos["liquidity_pending_quantity"] = max(0, pos.get("liquidity_target_quantity", target_qty) - pos["quantity"])
    log("ADD", now_text, pos["code"], "qty=", quantity, "target=", target_qty, "pending=", pos["liquidity_pending_quantity"], "price=", round(fill_price, 6), "fill=", round(execution_price, 6), "new_qty=", pos["quantity"], "avg=", round(pos["avg_price"], 6), "avg_fill=", round(pos["avg_fill_price"], 6))
    log("ORDER_EXECUTION_SUMMARY", "opening_confirm_add", "time=", now_text, "code=", pos["code"], "target=", target_qty, "submitted=", quantity, "pending=", pos["liquidity_pending_quantity"], "limit=", execution_price, "expected_avg=", round(quote.get("liquidity_avg"), 6) if quote.get("liquidity_avg") is not None else None, "expected_worst=", quote.get("liquidity_worst"), "liq_qty=", quote.get("liquidity_qty"), "new_shadow_qty=", pos["quantity"], "note=", "compare_with_QMT_deal_panel")


def paper_add_liquidity_pending(ContextInfo, now_text, time_text, fill_price):
    pos = ContextInfo.position
    if pos is None or not pos.get("liquidity_add_enabled", False):
        return False
    if pos.get("partial_done"):
        return False
    if pos.get("last_liquidity_add_bar") == now_text:
        return False
    target_qty = safe_int(pos.get("liquidity_target_quantity", 0))
    pending = max(0, target_qty - pos["quantity"])
    if pending <= 0:
        pos["liquidity_pending_quantity"] = 0
        return False
    if pos["path"] == "put_reversal_0945":
        eod_time = PUT_REV_EOD_TIME
    elif pos["path"] == "opening_put_fail":
        eod_time = OPENING_PUT_FAIL_EOD_TIME
    else:
        eod_time = NORMAL_EOD_TIME
    if time_text >= eod_time:
        return False
    if fill_price > pos["first_price"] * QMT_LIQUIDITY_ADD_MAX_PRICE_FACTOR:
        log("LIQUIDITY_ADD_SKIPPED_PRICE", now_text, pos["code"], "price=", round(fill_price, 6), "first=", round(pos["first_price"], 6), "pending=", pending)
        return False
    if QMT_LIQUIDITY_ADD_REQUIRE_SIGNAL_ALIVE:
        if pos["path"] == "opening" and not pos.get("opening_confirmed"):
            log("LIQUIDITY_ADD_WAIT", now_text, pos["code"], "pending=", pending, "reason=", "opening_not_confirmed")
            return False
        if fill_price < pos["avg_price"] * QMT_LIQUIDITY_ADD_MIN_PRICE_FACTOR:
            log("LIQUIDITY_ADD_WAIT", now_text, pos["code"], "pending=", pending, "reason=", "option_price_weak", "price=", round(fill_price, 6), "avg=", round(pos["avg_price"], 6))
            return False
    quote = build_order_quote(ContextInfo, "buy", pos["code"], fill_price)
    quote["multiplier"] = pos["multiplier"]
    execution_price = quote.get("order_price")
    if execution_price is None or execution_price <= 0:
        return False
    desired = affordable_quantity(ContextInfo, execution_price, pos["multiplier"], pending)
    quantity, desired_quantity = cap_quantity_by_liquidity("buy", desired, quote, "liquidity_continue_add")
    if quantity <= 0:
        pos["liquidity_pending_quantity"] = pending
        log("LIQUIDITY_ADD_WAIT", now_text, pos["code"], "pending=", pending, "desired=", desired_quantity, "liq_qty=", quote.get("liquidity_qty"))
        return False
    if not submit_qmt_order(ContextInfo, "buy", pos["code"], quantity, fill_price, quote):
        return False
    apply_buy_fill_to_position(ContextInfo, pos, quantity, fill_price, execution_price)
    pos["last_liquidity_add_bar"] = now_text
    pos["liquidity_pending_quantity"] = max(0, target_qty - pos["quantity"])
    log("LIQUIDITY_ADD", now_text, pos["code"], "qty=", quantity, "target=", target_qty, "pending=", pos["liquidity_pending_quantity"], "price=", round(fill_price, 6), "fill=", round(execution_price, 6), "new_qty=", pos["quantity"], "avg=", round(pos["avg_price"], 6), "avg_fill=", round(pos["avg_fill_price"], 6))
    log("ORDER_EXECUTION_SUMMARY", "liquidity_continue_add", "time=", now_text, "code=", pos["code"], "target=", target_qty, "submitted=", quantity, "pending=", pos["liquidity_pending_quantity"], "limit=", execution_price, "expected_avg=", round(quote.get("liquidity_avg"), 6) if quote.get("liquidity_avg") is not None else None, "expected_worst=", quote.get("liquidity_worst"), "liq_qty=", quote.get("liquidity_qty"), "new_shadow_qty=", pos["quantity"], "note=", "compare_with_QMT_deal_panel")
    return True


def paper_sell(ContextInfo, now_text, quantity, fill_price, reason):
    pos = ContextInfo.position
    if pos is None:
        return
    quantity = min(max(safe_int(quantity), 0), pos["quantity"])
    if quantity <= 0:
        return
    quote = build_order_quote(ContextInfo, "sell", pos["code"], fill_price)
    quote["multiplier"] = pos["multiplier"]
    execution_price = quote.get("order_price")
    if execution_price is None or execution_price <= 0:
        log("SELL_ABORTED_BAD_PRICE", now_text, pos["code"], reason)
        return
    if not submit_qmt_order(ContextInfo, "sell", pos["code"], quantity, fill_price, quote):
        log("SELL_ABORTED_ORDER_NOT_SENT", now_text, pos["code"], reason)
        return
    proceeds = quantity * execution_price * pos["multiplier"]
    fee = quantity * FEE_PER_CONTRACT_PER_SIDE
    ContextInfo.cash += proceeds - fee
    pos["quantity"] -= quantity
    pos["total_sell"] += proceeds
    pos["total_fees"] += fee
    log("SELL", now_text, pos["code"], "qty=", quantity, "price=", round(fill_price, 6), "fill=", round(execution_price, 6), "reason=", reason, "remaining=", pos["quantity"], "cash=", round(ContextInfo.cash, 2))
    log("ORDER_EXECUTION_SUMMARY", "sell_close", "time=", now_text, "code=", pos["code"], "submitted=", quantity, "remaining=", pos["quantity"], "limit=", execution_price, "reason=", reason, "expected_avg=", round(quote.get("liquidity_avg"), 6) if quote.get("liquidity_avg") is not None else None, "expected_worst=", quote.get("liquidity_worst"), "liq_qty=", quote.get("liquidity_qty"), "expected_amount=", round(proceeds, 2), "expected_fee=", round(fee, 2), "note=", "compare_with_QMT_deal_panel")
    if pos["quantity"] <= 0:
        pnl = pos["total_sell"] - pos["total_buy"] - pos["total_fees"]
        ContextInfo.trade_count += 1
        log("TRADE_CLOSED", now_text, pos["path"], pos["code"], "pnl=", round(pnl, 2), "equity=", round(ContextInfo.cash, 2), "trades=", ContextInfo.trade_count)
        ContextInfo.position = None


def minutes_since_entry(pos, now_text):
    try:
        entry = datetime.datetime.strptime(pos["entry_time"], "%Y%m%d%H%M%S")
        current = datetime.datetime.strptime(now_text, "%Y%m%d%H%M%S")
        return int((current - entry).total_seconds() / 60.0)
    except Exception:
        return 999


def manage_position(ContextInfo, now_text, time_text):
    pos = ContextInfo.position
    if pos is None:
        return
    bar = last_bar_at_or_before(ContextInfo.state["bars"].get(pos["code"], []), time_text)
    if bar is None:
        return
    price = bar["close"]
    pos["high_water"] = max(pos["high_water"], bar["high"], price)
    if pos["path"] == "opening" and time_text == "0945" and not pos["opening_confirmed"]:
        if opening_confirm_ok(ContextInfo, pos["direction"]):
            paper_add_opening(ContextInfo, now_text, price)
        else:
            paper_sell(ContextInfo, now_text, pos["quantity"], price, "opening_confirm_fail")
        return
    if price <= pos["avg_price"] * HARD_STOP_FACTOR:
        paper_sell(ContextInfo, now_text, pos["quantity"], price, "hard_stop_70%")
        return
    if pos["path"] == "opening_put_fail":
        if manage_opening_put_fail(ContextInfo, pos, price, time_text, now_text):
            return
    soft = PUT_REV_SOFT_STOP_FACTOR if pos["path"] == "put_reversal_0945" else (OPENING_SOFT_STOP_FACTOR if pos["path"] == "opening" else FALLBACK_SOFT_STOP_FACTOR)
    if minutes_since_entry(pos, now_text) >= SOFT_STOP_DELAY_MINUTES and price <= pos["avg_price"] * soft:
        paper_sell(ContextInfo, now_text, pos["quantity"], price, "soft_stop")
        return
    if pos["path"] == "put_reversal_0945":
        if put_reversal_special_exit(ContextInfo, pos, price, time_text, now_text):
            return
    if paper_add_liquidity_pending(ContextInfo, now_text, time_text, price):
        return
    if manage_put_reversal_hold_winner(ContextInfo, pos, price, time_text, now_text):
        return
    if pos["strong"]:
        if not pos["partial_done"] and price >= pos["avg_price"] * STRONG_TP1_FACTOR:
            qty = max(1, int(pos["initial_quantity"] / 3))
            paper_sell(ContextInfo, now_text, qty, price, "strong_tp1_50%_sell_1_3")
            if ContextInfo.position is not None:
                ContextInfo.position["partial_done"] = True
            return
        if pos["partial_done"]:
            trail = TRAIL_BEFORE_1030 if time_text < "1030" else TRAIL_AFTER_1030
            if price <= pos["high_water"] * (1.0 - trail):
                paper_sell(ContextInfo, now_text, pos["quantity"], price, "strong_trailing_%d%%" % int(trail * 100))
                return
    else:
        if not pos["partial_done"] and price >= pos["avg_price"] * NORMAL_TP1_FACTOR:
            qty = max(1, int(pos["initial_quantity"] * 0.5))
            paper_sell(ContextInfo, now_text, qty, price, "normal_tp1_35%_sell_half")
            if ContextInfo.position is not None:
                ContextInfo.position["partial_done"] = True
            return
        if pos["partial_done"] and price >= pos["avg_price"] * NORMAL_TP2_FACTOR:
            paper_sell(ContextInfo, now_text, pos["quantity"], price, "normal_tp2_300%")
            return
    if pos["path"] == "put_reversal_0945":
        eod_time = PUT_REV_EOD_TIME
    elif pos["path"] == "opening_put_fail":
        eod_time = OPENING_PUT_FAIL_EOD_TIME
    else:
        eod_time = NORMAL_EOD_TIME
    if time_text >= eod_time:
        paper_sell(ContextInfo, now_text, pos["quantity"], price, "eod_%s" % eod_time)


def put_reversal_special_exit(ContextInfo, pos, price, time_text, now_text):
    entry_etf = pos.get("entry_etf")
    ma20 = pos.get("entry_ma20")
    trend_zone = entry_etf is not None and ma20 is not None and ma20 > 0 and entry_etf >= ma20 * (1.0 + PUT_REV_TREND_MA20_DEV)
    if trend_zone and price >= pos["avg_price"] * PUT_REV_TREND_QUICK_TP:
        paper_sell(ContextInfo, now_text, pos["quantity"], price, "trend_quick_tp_10%")
        return True
    if time_text == "1030":
        values = ContextInfo.state["bars"].get(pos["code"], [])
        path = [row for row in values if row["time"] > "0945" and row["time"] <= "1030"]
        max_high = max([row["high"] for row in path]) if path else None
        if max_high is not None and max_high < pos["avg_price"] * PUT_REV_NO_FOLLOW_HIGH and price <= pos["avg_price"] * PUT_REV_NO_FOLLOW_CLOSE:
            paper_sell(ContextInfo, now_text, pos["quantity"], price, "early_no_follow_1030")
            return True
    return False


def manage_opening_put_fail(ContextInfo, pos, price, time_text, now_text):
    if pos.get("path") != "opening_put_fail":
        return False
    avg_price = safe_float(pos.get("avg_price"))
    if avg_price is None or avg_price <= 0:
        return True

    if price <= avg_price * OPENING_PUT_FAIL_STOP_FACTOR:
        paper_sell(ContextInfo, now_text, pos["quantity"], price, "opening_put_fail_fast_stop_12%")
        return True

    if time_text >= OPENING_PUT_FAIL_EOD_TIME:
        paper_sell(ContextInfo, now_text, pos["quantity"], price, "opening_put_fail_eod_%s" % OPENING_PUT_FAIL_EOD_TIME)
        return True

    if paper_add_liquidity_pending(ContextInfo, now_text, time_text, price):
        return True

    high_water = safe_float(pos.get("high_water"), price)
    trail_stop = max(
        safe_float(pos.get("opening_put_fail_trailing_stop"), avg_price * OPENING_PUT_FAIL_STOP_FACTOR),
        high_water * (1.0 - OPENING_PUT_FAIL_TRAIL),
        avg_price * OPENING_PUT_FAIL_STOP_FACTOR,
    )

    if pos.get("opening_put_fail_hold_mode", False):
        pos["opening_put_fail_trailing_stop"] = trail_stop
        if price <= trail_stop:
            paper_sell(ContextInfo, now_text, pos["quantity"], price, "opening_put_fail_strong_trailing_%d%%" % int(OPENING_PUT_FAIL_TRAIL * 100))
        return True

    if not pos.get("partial_done", False) and price >= avg_price * OPENING_PUT_FAIL_TP1_FACTOR:
        if price >= avg_price * OPENING_PUT_FAIL_TP2_FACTOR:
            pos["opening_put_fail_hold_mode"] = True
            pos["opening_put_fail_trailing_stop"] = trail_stop
            log(
                "OPENPUTFAIL_HOLD_MODE",
                now_text,
                pos["code"],
                "price=", round(price, 6),
                "avg=", round(avg_price, 6),
                "high_water=", round(high_water, 6),
                "trail=", OPENING_PUT_FAIL_TRAIL,
                "reason=", "fast_strong_put_skip_half",
            )
            return True
        qty = max(1, int(pos["initial_quantity"] * 0.5))
        paper_sell(ContextInfo, now_text, qty, price, "opening_put_fail_tp25_sell_half")
        if ContextInfo.position is not None:
            ContextInfo.position["partial_done"] = True
        return True

    if pos.get("partial_done", False) and price >= avg_price * OPENING_PUT_FAIL_TP2_FACTOR:
        paper_sell(ContextInfo, now_text, pos["quantity"], price, "opening_put_fail_tp45")
        return True

    return True


def put_reversal_hold_winner_context_ok(ContextInfo, pos, price, time_text):
    if time_text >= PUT_REV_HOLD_LATEST_TRIGGER_TIME:
        return False
    high_water = safe_float(pos.get("high_water"))
    avg_price = safe_float(pos.get("avg_price"))
    if high_water is None or high_water <= 0 or avg_price is None or avg_price <= 0:
        return False
    if price < high_water * PUT_REV_HOLD_CLOSE_NEAR_HIGH:
        return False
    if price < avg_price * PUT_REV_HOLD_TRIGGER_FACTOR:
        return False
    entry_etf = safe_float(pos.get("entry_etf"))
    current_etf = safe_float(ContextInfo.state.get("last_etf_close"))
    if entry_etf is not None and entry_etf > 0 and current_etf is not None and PUT_REV_HOLD_ETF_FOLLOW_MIN is not None:
        if current_etf > entry_etf * (1.0 - PUT_REV_HOLD_ETF_FOLLOW_MIN):
            return False
    return True


def manage_put_reversal_hold_winner(ContextInfo, pos, price, time_text, now_text):
    if not PUT_REV_HOLD_WINNER_ENABLED:
        return False
    if pos.get("path") != "put_reversal_0945":
        return False
    if pos.get("partial_done") and not pos.get("put_rev_hold_mode"):
        return False
    avg_price = safe_float(pos.get("avg_price"))
    if avg_price is None or avg_price <= 0:
        return False

    if not pos.get("put_rev_hold_mode", False):
        if pos.get("partial_done"):
            return False
        if price < avg_price * PUT_REV_HOLD_TRIGGER_FACTOR:
            return False
        if not put_reversal_hold_winner_context_ok(ContextInfo, pos, price, time_text):
            return False
        pos["put_rev_hold_mode"] = True
        pos["put_rev_hold_trailing_stop"] = max(
            avg_price * HARD_STOP_FACTOR,
            safe_float(pos.get("high_water"), price) * (1.0 - PUT_REV_HOLD_TRAIL),
        )
        log(
            "PUTREV_HOLD_MODE",
            now_text,
            pos["code"],
            "price=", round(price, 6),
            "avg=", round(avg_price, 6),
            "high_water=", round(pos.get("high_water"), 6) if pos.get("high_water") is not None else None,
            "trail=", PUT_REV_HOLD_TRAIL,
            "scale_factor=", PUT_REV_HOLD_SCALE_FACTOR,
            "reason=", "strong_context_skip_35pct_half",
        )

    if time_text >= PUT_REV_EOD_TIME:
        paper_sell(ContextInfo, now_text, pos["quantity"], price, "putrev_hold_eod_%s" % PUT_REV_EOD_TIME)
        return True

    trail_stop = max(
        safe_float(pos.get("put_rev_hold_trailing_stop"), avg_price * HARD_STOP_FACTOR),
        safe_float(pos.get("high_water"), price) * (1.0 - PUT_REV_HOLD_TRAIL),
        avg_price * HARD_STOP_FACTOR,
    )
    pos["put_rev_hold_trailing_stop"] = trail_stop

    if not pos.get("put_rev_hold_scale_done", False) and price >= avg_price * PUT_REV_HOLD_SCALE_FACTOR:
        qty = max(1, int(pos["initial_quantity"] * PUT_REV_HOLD_SCALE_RATIO + 0.5))
        qty = min(qty, pos["quantity"])
        paper_sell(ContextInfo, now_text, qty, price, "putrev_hold_scale_50pct_sell_1_3")
        if ContextInfo.position is not None:
            ContextInfo.position["put_rev_hold_scale_done"] = True
            ContextInfo.position["partial_done"] = True
        return True

    if price <= trail_stop:
        paper_sell(ContextInfo, now_text, pos["quantity"], price, "putrev_hold_trailing_%d%%" % int(PUT_REV_HOLD_TRAIL * 100))
        return True

    return True


def aggregate_15m(etf_bars):
    groups = []
    windows = [
        ("0930", "0945"), ("0945", "1000"), ("1000", "1015"), ("1015", "1030"),
        ("1030", "1045"), ("1045", "1100"), ("1100", "1115"), ("1115", "1130"),
        ("1300", "1315"), ("1315", "1330"), ("1330", "1345"), ("1345", "1400"),
        ("1400", "1415"), ("1415", "1430"), ("1430", "1445"), ("1445", "1500"),
    ]
    for start, end in windows:
        rows = [row for row in etf_bars if row["time"] >= start and row["time"] < end]
        if not rows:
            continue
        groups.append({
            "start": start,
            "end": end,
            "open": rows[0]["open"],
            "high": max(row["high"] for row in rows),
            "low": min(row["low"] for row in rows),
            "close": rows[-1]["close"],
            "volume": sum(row["volume"] for row in rows),
        })
    return groups


def latest_15m_metrics(ContextInfo, time_text):
    groups = aggregate_15m(ContextInfo.state["bars"].get(KCB_CODE, []))
    completed = [row for row in groups if row["end"] <= time_text]
    if len(completed) < 5:
        return None
    closes = [row["close"] for row in completed]
    ema5 = ema_series(closes, 5)
    ema20 = ema_series(closes, 20)
    current = completed[-1]
    prev = completed[:-1]
    prev3 = prev[-3:] if len(prev) >= 3 else prev
    avg5_volume = mean([row["volume"] for row in prev[-5:]]) if prev else None
    volume_mult = current["volume"] / avg5_volume if avg5_volume and avg5_volume > 0 else None
    high3 = max(row["high"] for row in prev3) if prev3 else None
    low3 = min(row["low"] for row in prev3) if prev3 else None
    range_value = current["high"] - current["low"]
    close_pos = (current["close"] - current["low"]) / range_value if range_value > 0 else 0.5
    return {
        "bar": current,
        "prev3_high": high3,
        "prev3_low": low3,
        "ema5": ema5[-1],
        "ema20": ema20[-1],
        "ema20_slope": ema20[-1] - ema20[-2] if len(ema20) >= 2 else 0.0,
        "volume_mult": volume_mult,
        "close_pos": close_pos,
    }


def cumulative_volume_progress(ContextInfo, time_text):
    daily_info = ContextInfo.daily_info
    volume20 = daily_info.get("volume_ratio20")
    if volume20 is None:
        return 1.0
    # In live QMT we do not have a clean historical intraday volume curve.
    # Use a conservative proxy: if prior daily volume was normal, allow the
    # 15m local volume gate to dominate; if it was weak, suppress fallback.
    return max(0.0, volume20)


def opening_confirm_ok(ContextInfo, direction):
    etf_bars = ContextInfo.state["bars"].get(KCB_CODE, [])
    first5 = bars_between(etf_bars, "0930", "0934")
    last = last_bar_at_or_before(etf_bars, "0945")
    metrics = latest_15m_metrics(ContextInfo, "0945")
    if not first5 or last is None or metrics is None:
        return False
    high0 = max(row["high"] for row in first5)
    low0 = min(row["low"] for row in first5)
    if direction == "call":
        return last["close"] > high0 and metrics["ema5"] > metrics["ema20"]
    return last["close"] < low0 and metrics["ema5"] < metrics["ema20"]


def evaluate_opening(ContextInfo, now_text, time_text):
    if ContextInfo.day_locked or ContextInfo.position is not None:
        return
    daily = ContextInfo.daily_info
    if not daily.get("ready") or daily.get("direction") not in ["call", "put"]:
        return
    direction = daily["direction"]
    etf_bars = ContextInfo.state["bars"].get(KCB_CODE, [])
    first5 = bars_between(etf_bars, "0930", "0934")
    if len(first5) < 5:
        return
    high0 = max(row["high"] for row in first5)
    low0 = min(row["low"] for row in first5)
    open0 = first5[0]["open"]
    range_ratio = (high0 - low0) / open0 if open0 > 0 else 0.0
    threshold = OPENING_CALL_RANGE if direction == "call" else OPENING_PUT_RANGE
    if range_ratio < threshold:
        return
    if direction == "call" and daily.get("two_day_return") is not None and daily["two_day_return"] >= EARLY_CALL_EXHAUSTION_2D:
        log("OPENING_CALL_FILTERED", "two_day_return=", round(daily["two_day_return"], 4))
        return
    scan = [row for row in etf_bars if row["time"] >= "0935" and row["time"] <= "0940"]
    avg_vol = mean([row["volume"] for row in first5])
    max_vol = max(row["volume"] for row in first5)
    trigger = None
    for row in scan:
        volume_ok = row["volume"] >= avg_vol * BREAKOUT_VOLUME_MULT and row["volume"] >= max_vol * BREAKOUT_VOLUME_MAX_MULT
        if direction == "call" and row["close"] > high0 and volume_ok:
            trigger = row
            break
        if direction == "put" and row["close"] < low0 and volume_ok:
            trigger = row
            break
    if trigger is None:
        return
    follow = [row for row in etf_bars if row["time"] > trigger["time"] and row["time"] <= "0943"]
    if direction == "call":
        ok_count = len([row for row in follow if row["close"] > high0])
    else:
        ok_count = len([row for row in follow if row["close"] < low0])
    if ok_count < 2:
        return
    selected = select_option(ContextInfo, direction, trigger["close"], time_text, False)
    if selected is None:
        return
    paper_open(ContextInfo, selected, direction, "opening", False, now_text, selected["price"], OPENING_FIRST_LEG_RATIO)


def fallback_call_option_confirm(selected):
    values = selected.get("bars", [])
    recent = values[-8:]
    if len(recent) < 8:
        return True
    current = recent[-1]["close"]
    high8 = max(row["high"] for row in recent)
    if high8 > 0 and current < high8 * (1.0 - 0.08):
        return False
    closes3 = [row["close"] for row in recent[-3:]]
    if closes3[0] > closes3[1] > closes3[2]:
        return False
    prev_vol = mean([row["volume"] for row in recent[:-3]])
    recent_vol = mean([row["volume"] for row in recent[-3:]])
    if prev_vol and recent_vol is not None and recent_vol < prev_vol * 0.70:
        return False
    return True


def evaluate_fallback(ContextInfo, now_text, time_text):
    if ContextInfo.day_locked or ContextInfo.position is not None:
        return
    if not ((time_text >= FALLBACK_SCAN_START_1 and time_text <= FALLBACK_SCAN_END_1) or (time_text >= FALLBACK_SCAN_START_2 and time_text <= FALLBACK_SCAN_END_2)):
        return
    daily = ContextInfo.daily_info
    direction = daily.get("direction")
    if direction not in ["call", "put"]:
        return
    metrics = latest_15m_metrics(ContextInfo, time_text)
    if metrics is None:
        return
    bar = metrics["bar"]
    volume_mult = metrics["volume_mult"]
    progress = cumulative_volume_progress(ContextInfo, time_text)
    if volume_mult is None:
        return
    strong = False
    path = "fallback_strong15m"
    allow_high_iv_put = False
    if direction == "call":
        strong = (
            metrics["prev3_high"] is not None and bar["close"] > metrics["prev3_high"]
            and metrics["ema5"] > metrics["ema20"]
            and metrics["ema20_slope"] > 0
            and volume_mult >= FALLBACK_VOLUME_MULT
            and progress >= FALLBACK_VOLUME_PROGRESS
            and metrics["close_pos"] >= 0.65
        )
    else:
        strong = (
            metrics["prev3_low"] is not None and bar["close"] < metrics["prev3_low"]
            and metrics["ema5"] < metrics["ema20"]
            and metrics["ema20_slope"] < 0
            and volume_mult >= FALLBACK_VOLUME_MULT
            and progress >= FALLBACK_VOLUME_PROGRESS
            and metrics["close_pos"] <= 0.35
        )
        if strong:
            allow_high_iv_put = True
            path = "fallback_high_iv_put"
        elif (
            metrics["prev3_low"] is not None and bar["close"] < metrics["prev3_low"]
            and metrics["ema5"] < metrics["ema20"]
            and metrics["ema20_slope"] < 0
            and volume_mult >= FALLBACK_CLUSTER_VOLUME_MULT
            and progress >= FALLBACK_VOLUME_PROGRESS
            and metrics["close_pos"] <= 0.35
            and bar["close"] < daily.get("ma5", 999)
            and bar["close"] < daily.get("ma10", 999)
            and bar["close"] < daily.get("ma20", 999)
        ):
            strong = True
            allow_high_iv_put = True
            path = "fallback_cluster_put"
    if not strong:
        return
    selected = select_option(ContextInfo, direction, bar["close"], time_text, allow_high_iv_put)
    if selected is None:
        return
    if direction == "call" and not fallback_call_option_confirm(selected):
        log("FALLBACK_CALL_FILTERED", "option_momentum_confirm", selected["code"])
        return
    paper_open(ContextInfo, selected, direction, path, True, now_text, selected["price"], 1.0)


def evaluate_put_reversal(ContextInfo, now_text, time_text):
    if time_text != "0945":
        return
    if ContextInfo.day_locked or ContextInfo.position is not None:
        return
    etf_bars = ContextInfo.state["bars"].get(KCB_CODE, [])
    open_bar = first_bar(etf_bars)
    last = last_bar_at_or_before(etf_bars, "0945")
    if open_bar is None or last is None or open_bar["open"] <= 0:
        return
    etf_return = last["close"] / open_bar["open"] - 1.0
    ContextInfo.state["last_etf_close"] = last["close"]
    log("PUTREV_ETF", "open=", round(open_bar["open"], 6), "close=", round(last["close"], 6), "return=", round(etf_return, 6))
    if etf_return < PUT_REV_ETF_UP_MIN:
        return
    selected = select_put_reversal(ContextInfo, last["close"], "0945")
    if selected is None:
        return
    paper_open(ContextInfo, selected, "put", "put_reversal_0945", False, now_text, selected["price"], 1.0)


def evaluate_opening_put_fail(ContextInfo, now_text, time_text):
    if not OPENING_PUT_FAIL_ENABLED:
        return
    if time_text < OPENING_PUT_FAIL_SCAN_START or time_text > OPENING_PUT_FAIL_SCAN_END:
        return
    if ContextInfo.day_locked or ContextInfo.position is not None:
        return
    ok, stats = opening_put_fail_trigger_ok(ContextInfo, time_text)
    if stats is not None and time_text == OPENING_PUT_FAIL_SCAN_START:
        log(
            "OPENPUTFAIL_BASE",
            "open=", round(stats.get("open"), 6) if stats.get("open") is not None else None,
            "close945=", round(stats.get("close945"), 6) if stats.get("close945") is not None else None,
            "return945=", round(stats.get("return945"), 6) if stats.get("return945") is not None else None,
            "close_pos=", round(stats.get("close_pos"), 4) if stats.get("close_pos") is not None else None,
        )
    if not ok:
        return
    log(
        "OPENPUTFAIL_TRIGGER",
        now_text,
        "return945=", round(stats.get("return945"), 6) if stats else None,
        "close_pos=", round(stats.get("close_pos"), 4) if stats else None,
        "max_rebound=", round(stats.get("max_rebound"), 6) if stats and stats.get("max_rebound") is not None else None,
        "last_close=", round(stats.get("last_close"), 6) if stats and stats.get("last_close") is not None else None,
        "trigger_level=", round(stats.get("trigger_level"), 6) if stats and stats.get("trigger_level") is not None else None,
    )
    selected = select_opening_put_fail(ContextInfo, ContextInfo.state.get("last_etf_close"), time_text)
    if selected is None:
        return
    paper_open(ContextInfo, selected, "put", "opening_put_fail", True, now_text, selected["price"], 1.0)


def update_daily_from_minute(ContextInfo, current_date):
    etf_bars = ContextInfo.state["bars"].get(KCB_CODE, [])
    if not etf_bars:
        return
    exists = [row for row in ContextInfo.daily_rows if row["date"] == current_date]
    row = {
        "date": current_date,
        "open": etf_bars[0]["open"],
        "high": max(bar["high"] for bar in etf_bars),
        "low": min(bar["low"] for bar in etf_bars),
        "close": etf_bars[-1]["close"],
        "volume": sum(bar["volume"] for bar in etf_bars),
        "amount": sum(bar["amount"] for bar in etf_bars),
    }
    if exists:
        exists[0].update(row)
    else:
        ContextInfo.daily_rows.append(row)
        ContextInfo.daily_rows.sort(key=lambda item: item["date"])


def init(ContextInfo):
    ContextInfo.live_account_id = QMT_ACCOUNT_ID
    ContextInfo.set_universe(UNDERLYINGS)
    ContextInfo.cash = INITIAL_CASH
    ContextInfo.position = None
    ContextInfo.trade_count = 0
    ContextInfo.day_entries = 0
    ContextInfo.day_locked = False
    ContextInfo.current_date = 0
    ContextInfo.daily_rows = seed_daily_rows()
    ContextInfo.daily_info = {}
    ContextInfo.state = {
        "bars": {},
        "universe": [],
        "last_bar_text": "",
        "time": "",
        "last_etf_close": None,
    }
    ContextInfo.live_date_gate_skip_logged = False
    ContextInfo.live_account_status_logged = False
    log("INIT", BUILD_ID, "period=", getattr(ContextInfo, "period", None))
    log("ACCOUNT", masked_account(QMT_ACCOUNT_ID), "native_order=", QMT_NATIVE_ORDER_ENABLED)
    log("LIVE_DATE_GATE", "enabled=", LIVE_WALL_CLOCK_GATE, "target_date=", live_trade_date(), "override=", LIVE_TRADE_DATE_OVERRIDE)
    log("BBO", "use_full_tick=", QMT_USE_FULL_TICK_BBO, "require_last_bar=", QMT_BBO_REQUIRE_LAST_BAR)
    log("RISK", "initial_cash=", INITIAL_CASH, "premium_cap=", ABS_PREMIUM_CAP, "max_trades_day=", LIVE_MAX_TRADES_PER_DAY)
    log_live_account_status(ContextInfo, "init")


def handlebar(ContextInfo):
    now_text, current_date, time_text = current_datetime(ContextInfo)
    if current_date <= 0 or len(time_text) != 4:
        return
    if not live_date_gate_allows(ContextInfo, now_text, current_date):
        return
    if now_text == ContextInfo.state.get("last_bar_text", ""):
        return
    ContextInfo.state["last_bar_text"] = now_text
    ContextInfo.state["time"] = time_text
    if not getattr(ContextInfo, "live_account_status_logged", False):
        ContextInfo.live_account_status_logged = True
        log_live_account_status(ContextInfo, "first_live_bar_%s" % now_text)
    if current_date != ContextInfo.current_date:
        if ContextInfo.current_date:
            update_daily_from_minute(ContextInfo, ContextInfo.current_date)
        ContextInfo.current_date = current_date
        ContextInfo.day_entries = 0
        ContextInfo.day_locked = False
        ContextInfo.position = None
        ContextInfo.state["bars"] = {}
        ContextInfo.state["universe"] = []
        ContextInfo.daily_info = daily_metrics(ContextInfo.daily_rows, current_date)
        log("NEW_DAY", current_date, "daily_ready=", ContextInfo.daily_info.get("ready"), "direction=", ContextInfo.daily_info.get("direction"), "ma20=", round(ContextInfo.daily_info.get("ma20"), 6) if ContextInfo.daily_info.get("ma20") is not None else None)
    etf_bar = read_bar(ContextInfo, KCB_CODE)
    if etf_bar is None:
        log("ETF_BAR_MISSING", now_text)
        return
    append_bar(ContextInfo.state["bars"], KCB_CODE, now_text, time_text, etf_bar)
    ContextInfo.state["last_etf_close"] = etf_bar["close"]
    if time_text == "0930":
        ContextInfo.state["universe"] = build_universe(ContextInfo, current_date, etf_bar["close"])
    for item in ContextInfo.state.get("universe", []):
        if item["dte"] < DTE_MIN or item["dte"] > DTE_MAX:
            continue
        opt_bar = read_bar(ContextInfo, item["code"])
        if opt_bar is not None:
            append_bar(ContextInfo.state["bars"], item["code"], now_text, time_text, opt_bar)
    if time_text in HEARTBEAT_MINUTES:
        log("HEARTBEAT", now_text, "etf=", round(etf_bar["close"], 6), "bars=", len(ContextInfo.state["bars"].get(KCB_CODE, [])), "universe=", len(ContextInfo.state.get("universe", [])), "position=", ContextInfo.position["code"] if ContextInfo.position else "NONE", "cash=", round(ContextInfo.cash, 2), "equity=", round(paper_equity(ContextInfo), 2))
    manage_position(ContextInfo, now_text, time_text)
    if ContextInfo.position is None:
        evaluate_opening(ContextInfo, now_text, time_text)
    if ContextInfo.position is None:
        evaluate_put_reversal(ContextInfo, now_text, time_text)
    if ContextInfo.position is None:
        evaluate_opening_put_fail(ContextInfo, now_text, time_text)
    if ContextInfo.position is None:
        evaluate_fallback(ContextInfo, now_text, time_text)
    if time_text >= "1459":
        update_daily_from_minute(ContextInfo, current_date)
