# -*- coding: utf-8 -*-
"""QMT live simulated-account implementation of the v1.2 dual-ETF strategy.

Run this model in QMT option strategy trading on a 1-minute chart. It reads
live market data, keeps a shadow ledger, and can send orders to a QMT
simulated option account after all startup checks pass.

The source intentionally contains ASCII characters only and uses only the
Python 3.6 standard library.
"""

from __future__ import print_function

import datetime
import math


# ---------------------------------------------------------------------------
# User configuration
# ---------------------------------------------------------------------------

# Current-contract replay validation:
# QMT currently exposes contracts that were active from 2026-06-17 onward.
# Change this to the actual live date before moving the model to paper trading.
PAPER_START_DATE = 20260703
HISTORICAL_PARITY_MODE = False
HISTORICAL_PARITY_END_DATE = 20260630
BUILD_ID = "V12_LIVE_SIM_20260703_R19"
INITIAL_CASH = 100000.0
FEE_PER_CONTRACT_PER_SIDE = 2.0
SLIPPAGE_TICK = 0.0001
CONTRACT_MULTIPLIER_DEFAULT = 10000

# Native QMT simulated-account orders. Keep disabled until the parity
# backtest passes and the broker confirms these option passorder parameters.
QMT_NATIVE_ORDER_ENABLED = True
QMT_ACCOUNT_ID = "210400032829"
QMT_OPTION_ACCOUNT_TYPE = 1101
QMT_BUY_OPEN_OP = 50
QMT_SELL_CLOSE_OP = 51
QMT_MARKET_PRICE_TYPE = 11
QMT_ORDER_CODE_WITH_SUFFIX = True
QMT_PASSORDER_STYLE = "official9"
QMT_STRATEGY_NAME = "v12_live_sim"
QMT_QUICK_TRADE = 1
QMT_PRICE_TICK = 0.0001
QMT_BUY_LIMIT_BUFFER = 0.0050
QMT_SELL_LIMIT_BUFFER = 0.0050

# First-live-day safety controls. Keep these values for the first simulated
# session. Raising them does not improve signal quality.
LIVE_MAX_CONTRACTS = 1
LIVE_MAX_TRADES_PER_DAY = 1
LIVE_REQUIRE_DAILY_BARS = 21
LIVE_REQUIRE_OPTION_POOL = True
LIVE_FAIL_CLOSED = True
LIVE_WALL_CLOCK_GATE = True
LIVE_BAR_CAPTURE_SECOND = 55
LIVE_BAR_MAX_SECONDS_TO_END = 10
LIVE_15M_SEED_VOLUME_DIVISOR = 100.0
LIVE_FAST_SKIP_BEFORE_START = True
LIVE_REQUIRE_LAST_BAR_FOR_ORDER = True
LIVE_CURRENT_BAR_ONLY = True
LIVE_MINUTE_MONITOR_ALL_DAY = True
HEARTBEAT_MINUTES = ["0930", "0945", "1000", "1030", "1100", "1130",
                     "1300", "1330", "1400", "1430", "1455", "1500"]

# One explicit live-sim order validates the QMT simulated-account order
# channel even when the strategy has no natural signal.  This calls passorder
# when QMT_NATIVE_ORDER_ENABLED is True.  Keep quantity limited by
# LIVE_MAX_CONTRACTS while testing.
EXECUTION_SMOKE_TEST = False
SMOKE_TEST_ALLOW_ORDERS = True
SMOKE_TEST_DATE = 0
SMOKE_TEST_TIME = "0931"
SMOKE_TEST_UNDERLYING = "588000.SH"
SMOKE_TEST_DIRECTION = "call"
SMOKE_TEST_AUTO_CLOSE = True
SMOKE_TEST_CLOSE_AFTER_MINUTES = 2

# Keep this empty for strategy testing.  Set to "call" or "put" only for a
# same-day plumbing test when fewer than 21 completed daily bars are loaded.
FORCE_TEST_DIRECTION = ""

UNDERLYINGS = ["588000.SH", "159915.SZ"]
KCB_CODE = "588000.SH"
CYB_CODE = "159915.SZ"

RANGE_THRESHOLD = {
    KCB_CODE: 0.0030,
    CYB_CODE: 0.0025,
}
BREAKOUT_VOLUME_MULT = {
    KCB_CODE: 1.30,
    CYB_CODE: 1.25,
}
BREAKOUT_VOLUME_MAX_MULT = 0.80

DTE_MIN = 10
DTE_MAX = 35
IV_MIN = 0.20
IV_MAX = 0.70
DELTA_MIN = 0.35
DELTA_MAX = 0.65
POOL_PER_SIDE = 4
REQUIRE_OPTION_TREND = True

OPENING_NORMAL_POSITION = 0.50
OPENING_STRONG_POSITION = 0.70
OPENING_FIRST_LEG_RATIO = 0.65
FALLBACK_BASE_POSITION = 0.50
POSITION_CAP = 0.70

HARD_STOP_FACTOR = 0.70
OPENING_SOFT_STOP_FACTOR = 0.75
FALLBACK_SOFT_STOP_FACTOR = 0.82
OPENING_SOFT_STOP_DELAY_MINUTES = 5
NORMAL_TP1_FACTOR = 1.35
NORMAL_TP2_FACTOR = 1.80
STRONG_TP1_FACTOR = 1.50
STRONG_TRAIL_BEFORE_1030 = 0.35
STRONG_TRAIL_AFTER_1030 = 0.25
EOD_EXIT_TIME = "1455"
FALLBACK_IV_RANK_MAX = 0.50
LATEST_KCB_MARKET_IV = 0.709
LATEST_KCB_IV_RANK = 0.990108803165183
LIVE_IV_ROLLING_MIN = 0.2085
LIVE_IV_ROLLING_MAX = 0.7140
HISTORICAL_KCB_IV_REGIME = {
    20260527: (0.5575, 0.8379351740696278),
    20260625: (0.6240, 0.9904648390941596),
    20260629: (0.7140, 1.0),
    20260630: (0.7090, 0.9901088031651830),
}

# QMT may invoke handlebar several times for the same forming minute and may
# not preserve arbitrary ContextInfo attributes between those callbacks.
# Module-level guards prevent duplicate bar processing and duplicate orders.
RUNTIME_LAST_PROCESSED_BAR = ""
RUNTIME_ORDER_KEYS = set()
RUNTIME_CONTEXT_STATE = None

# Embedded daily warmup through 2026-07-02. This avoids a pandas dependency
# inside QMT and is refreshed only when a new live build is prepared.
# Tuple: date, open, high, low, close, volume, amount.
LIVE_DAILY_SEED = {
    "588000.SH": [
        (20260528, 1.893, 1.954, 1.891, 1.942, 3883039052.0, 7480500717.099),
        (20260529, 1.944, 1.952, 1.820, 1.844, 4620430910.0, 8654625507.858),
        (20260601, 1.841, 1.850, 1.751, 1.754, 4195016494.0, 7517959823.856),
        (20260602, 1.756, 1.803, 1.728, 1.781, 3562692683.0, 6296506062.416),
        (20260603, 1.788, 1.872, 1.784, 1.823, 4106087727.0, 7513993876.839),
        (20260604, 1.794, 1.856, 1.789, 1.832, 2285373033.0, 4188280581.953),
        (20260605, 1.801, 1.829, 1.750, 1.763, 3036765522.0, 5429864189.830),
        (20260608, 1.690, 1.725, 1.665, 1.683, 3879251946.0, 6578187379.433),
        (20260609, 1.721, 1.760, 1.696, 1.755, 2879374620.0, 4978683139.246),
        (20260610, 1.748, 1.818, 1.724, 1.744, 3317234966.0, 5864140525.526),
        (20260611, 1.727, 1.771, 1.723, 1.756, 2661770721.0, 4645134517.937),
        (20260612, 1.825, 1.828, 1.751, 1.756, 3264831324.0, 5855055732.724),
        (20260615, 1.782, 1.845, 1.750, 1.844, 3001479396.0, 5441091921.274),
        (20260616, 1.845, 1.863, 1.823, 1.855, 2544244580.0, 4693669477.802),
        (20260617, 1.828, 1.940, 1.819, 1.939, 3474306997.0, 6547205597.370),
        (20260618, 1.935, 2.042, 1.932, 2.017, 4081671719.0, 8160146208.589),
        (20260622, 2.026, 2.070, 1.981, 2.056, 3609573754.0, 7321099001.517),
        (20260623, 2.040, 2.090, 1.992, 2.023, 3643158120.0, 7418469842.035),
        (20260624, 2.000, 2.105, 1.987, 2.096, 4244590621.0, 8748955894.640),
        (20260625, 2.114, 2.189, 2.106, 2.178, 3663353147.0, 7891953305.358),
        (20260626, 2.142, 2.188, 2.084, 2.133, 4048019931.0, 8667140757.093),
        (20260629, 2.143, 2.250, 2.124, 2.248, 3760094834.0, 8245833173.679),
        (20260630, 2.257, 2.349, 2.228, 2.344, 3084492727.0, 7100428840.356),
        (20260701, 2.346, 2.390, 2.252, 2.290, 4023150744.0, 9359368197.430),
        (20260702, 2.220, 2.240, 2.100, 2.119, 4850891100.0, 10527602202.000),
    ],
    "159915.SZ": [
        (20260528, 4.039, 4.148, 3.984, 4.138, 1401168181.0, 5679123150.340),
        (20260529, 4.143, 4.174, 4.022, 4.053, 1617188056.0, 6627594234.918),
        (20260601, 4.047, 4.094, 3.956, 3.964, 1322445104.0, 5325031114.047),
        (20260602, 3.981, 4.098, 3.959, 4.071, 1482175013.0, 5968727719.571),
        (20260603, 4.095, 4.230, 4.076, 4.145, 1649058134.0, 6853479731.095),
        (20260604, 4.074, 4.131, 4.065, 4.100, 1059912087.0, 4344953805.909),
        (20260605, 4.083, 4.122, 3.947, 3.977, 1466350474.0, 5925661224.953),
        (20260608, 3.830, 3.916, 3.790, 3.827, 1791638820.0, 6918765209.041),
        (20260609, 3.877, 3.975, 3.836, 3.972, 1578765256.0, 6169162413.896),
        (20260610, 3.925, 3.942, 3.835, 3.870, 1269815008.0, 4932052567.099),
        (20260611, 3.843, 3.925, 3.770, 3.830, 1513149151.0, 5811234668.286),
        (20260612, 3.932, 3.934, 3.835, 3.846, 1249608655.0, 4861543972.630),
        (20260615, 3.912, 4.053, 3.858, 4.045, 1461049638.0, 5783322879.484),
        (20260616, 4.068, 4.154, 4.063, 4.111, 1092149090.0, 4481671129.668),
        (20260617, 4.086, 4.183, 4.071, 4.183, 1093703625.0, 4511811472.394),
        (20260618, 4.169, 4.288, 4.160, 4.269, 1058053220.0, 4493982913.518),
        (20260622, 4.291, 4.379, 4.240, 4.379, 1592598007.0, 6869550101.297),
        (20260623, 4.379, 4.379, 4.170, 4.210, 1896738455.0, 8095279908.193),
        (20260624, 4.206, 4.271, 4.174, 4.258, 1663473156.0, 7032563317.731),
        (20260625, 4.287, 4.395, 4.254, 4.395, 1376051388.0, 5951167240.409),
        (20260626, 4.328, 4.344, 4.190, 4.215, 1536030375.0, 6542724816.546),
        (20260629, 4.200, 4.280, 4.118, 4.236, 1553590424.0, 6516025415.116),
        (20260630, 4.224, 4.370, 4.221, 4.364, 1108784875.0, 4776124320.222),
        (20260701, 4.364, 4.378, 4.234, 4.274, 1269215032.0, 5484765907.026),
        (20260702, 4.207, 4.207, 4.016, 4.036, 1876485200.0, 7700524802.000),
    ],
}

# The last 24 completed 15-minute bars through 2026-07-02. They warm EMA20
# and opening confirmation after old minute callbacks are fast-forwarded.
LIVE_15M_SEED = {
    "588000.SH": [
        ("20260701131500", "1315", 2.338, 2.338, 2.286, 2.287, 394167124.0, 911137329.817),
        ("20260701133000", "1330", 2.286, 2.325, 2.285, 2.293, 231927780.0, 534794640.013),
        ("20260701134500", "1345", 2.293, 2.306, 2.276, 2.277, 220900500.0, 506275599.060),
        ("20260701140000", "1400", 2.279, 2.294, 2.264, 2.294, 275984622.0, 628395582.240),
        ("20260701141500", "1415", 2.293, 2.300, 2.282, 2.282, 124097839.0, 284572166.387),
        ("20260701143000", "1430", 2.282, 2.282, 2.266, 2.268, 184437636.0, 419197776.421),
        ("20260701144500", "1445", 2.267, 2.286, 2.252, 2.286, 224569338.0, 509211325.515),
        ("20260701150000", "1500", 2.285, 2.292, 2.276, 2.290, 190669445.0, 435716307.620),
        ("20260702094500", "0945", 2.220, 2.220, 2.153, 2.173, 951845690.0, 2079580202.000),
        ("20260702100000", "1000", 2.173, 2.225, 2.165, 2.210, 460804010.0, 1013531400.000),
        ("20260702101500", "1015", 2.212, 2.240, 2.209, 2.225, 318896900.0, 710470200.000),
        ("20260702103000", "1030", 2.225, 2.227, 2.198, 2.202, 227794100.0, 502734300.000),
        ("20260702104500", "1045", 2.201, 2.230, 2.201, 2.217, 147538600.0, 327436900.000),
        ("20260702110000", "1100", 2.217, 2.221, 2.196, 2.196, 127008700.0, 280112200.000),
        ("20260702111500", "1115", 2.196, 2.209, 2.189, 2.208, 117385800.0, 257849800.000),
        ("20260702113000", "1130", 2.208, 2.214, 2.182, 2.187, 121649400.0, 267538500.000),
        ("20260702131500", "1315", 2.187, 2.189, 2.173, 2.179, 174044800.0, 379399900.000),
        ("20260702133000", "1330", 2.179, 2.179, 2.154, 2.154, 297317200.0, 643045300.000),
        ("20260702134500", "1345", 2.155, 2.157, 2.142, 2.144, 342772500.0, 736926900.000),
        ("20260702140000", "1400", 2.143, 2.155, 2.134, 2.149, 347003000.0, 744353800.000),
        ("20260702141500", "1415", 2.148, 2.157, 2.137, 2.144, 225284200.0, 483327000.000),
        ("20260702143000", "1430", 2.143, 2.144, 2.130, 2.131, 207207900.0, 442360400.000),
        ("20260702144500", "1445", 2.130, 2.141, 2.106, 2.112, 338607000.0, 718895600.000),
        ("20260702150000", "1500", 2.113, 2.123, 2.100, 2.119, 445731300.0, 940039800.000),
    ],
    "159915.SZ": [
        ("20260701131500", "1315", 4.340, 4.343, 4.308, 4.308, 71908900.0, 310929863.600),
        ("20260701133000", "1330", 4.308, 4.341, 4.304, 4.313, 62724455.0, 271128159.795),
        ("20260701134500", "1345", 4.312, 4.325, 4.284, 4.285, 70957100.0, 305671029.100),
        ("20260701140000", "1400", 4.286, 4.295, 4.262, 4.282, 95404000.0, 407946006.960),
        ("20260701141500", "1415", 4.279, 4.298, 4.275, 4.278, 50844200.0, 217860372.237),
        ("20260701143000", "1430", 4.277, 4.278, 4.252, 4.260, 54415100.0, 232066174.600),
        ("20260701144500", "1445", 4.261, 4.268, 4.234, 4.262, 72852700.0, 309569112.800),
        ("20260701150000", "1500", 4.260, 4.283, 4.259, 4.274, 69214363.0, 295442763.532),
        ("20260702094500", "0945", 4.207, 4.207, 4.101, 4.103, 447165980.0, 1846040102.000),
        ("20260702100000", "1000", 4.102, 4.157, 4.088, 4.138, 170654690.0, 703966400.000),
        ("20260702101500", "1015", 4.138, 4.172, 4.138, 4.164, 104740410.0, 435623700.000),
        ("20260702103000", "1030", 4.165, 4.167, 4.141, 4.156, 79654700.0, 330911000.000),
        ("20260702104500", "1045", 4.156, 4.185, 4.154, 4.171, 51529300.0, 214915400.000),
        ("20260702110000", "1100", 4.169, 4.176, 4.134, 4.134, 53423590.0, 222120300.000),
        ("20260702111500", "1115", 4.133, 4.157, 4.125, 4.157, 50102200.0, 207212600.000),
        ("20260702113000", "1130", 4.155, 4.166, 4.125, 4.129, 41195300.0, 170599200.000),
        ("20260702131500", "1315", 4.135, 4.135, 4.111, 4.115, 84323500.0, 347594900.000),
        ("20260702133000", "1330", 4.115, 4.115, 4.081, 4.083, 126553100.0, 518025600.000),
        ("20260702134500", "1345", 4.083, 4.084, 4.061, 4.062, 110853010.0, 451350600.000),
        ("20260702140000", "1400", 4.062, 4.078, 4.048, 4.062, 140404720.0, 570202700.000),
        ("20260702141500", "1415", 4.062, 4.089, 4.051, 4.072, 89143500.0, 362692300.000),
        ("20260702143000", "1430", 4.072, 4.073, 4.045, 4.048, 71535300.0, 290189400.000),
        ("20260702144500", "1445", 4.049, 4.059, 4.026, 4.033, 96113300.0, 388588300.000),
        ("20260702150000", "1500", 4.032, 4.036, 4.016, 4.036, 159092600.0, 640492300.000),
    ],
}

# QMT can read these expired contracts by code, but its historical option
# directory and detail API return no metadata. These records come from the
# same local daily option table used by the formal v1.2 backtest. Market bars
# and all fills are still read from QMT at each historical minute.
HISTORICAL_OPTION_POOL = {
    20260520: {
        "588000.SH": {
            "CALL": [
                {
                    "code": "10011558.SHO",
                    "strike": 1.95,
                    "dte": 35,
                    "rate": 0.02,
                    "multiplier": 10000,
                    "fixed_iv": 0.344,
                    "fixed_delta": 0.495,
                },
            ],
            "PUT": [],
        },
    },
    20260525: {
        "588000.SH": {
            "CALL": [
                {
                    "code": "10011603.SHO",
                    "strike": 2.00,
                    "dte": 30,
                    "rate": 0.02,
                    "multiplier": 10000,
                    "fixed_iv": 0.368,
                    "fixed_delta": 0.526,
                },
            ],
            "PUT": [],
        },
    },
}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

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


def median(values):
    clean = sorted(value for value in values if value is not None)
    size = len(clean)
    if size == 0:
        return None
    middle = size // 2
    if size % 2:
        return clean[middle]
    return (clean[middle - 1] + clean[middle]) / 2.0


def sma(values, window):
    if len(values) < window:
        return None
    return sum(values[-window:]) / float(window)


def ema_series(values, span):
    if not values:
        return []
    alpha = 2.0 / float(span + 1)
    output = [float(values[0])]
    for value in values[1:]:
        output.append(alpha * float(value) + (1.0 - alpha) * output[-1])
    return output


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


def implied_volatility(
    market_price,
    spot,
    strike,
    rate,
    dte,
    option_type,
):
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
    high_price = bs_price(
        spot,
        strike,
        rate,
        high,
        dte,
        option_type,
    )
    if high_price is None or high_price < market_price:
        return None
    for unused in range(70):
        middle = (low + high) / 2.0
        model_price = bs_price(
            spot,
            strike,
            rate,
            middle,
            dte,
            option_type,
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


def live_bar_is_in_future(current_date, time_text):
    if not LIVE_WALL_CLOCK_GATE:
        return False
    wall = datetime.datetime.now()
    try:
        bar_end = datetime.datetime.strptime(
            "%08d%s00" % (current_date, time_text),
            "%Y%m%d%H%M%S",
        )
    except Exception:
        return True
    seconds_to_bar_end = (bar_end - wall).total_seconds()
    if seconds_to_bar_end > LIVE_BAR_MAX_SECONDS_TO_END:
        return True
    if seconds_to_bar_end > 0:
        return wall.second < LIVE_BAR_CAPTURE_SECOND
    return False


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
            converted = timetag_to_datetime(
                safe_int(value),
                "%Y%m%d",
            )
            return safe_int(converted)
        except Exception:
            return 0
    return 0


def recursive_number(value, code, field_name):
    if isinstance(value, (int, float)):
        return safe_float(value)
    if not isinstance(value, dict):
        return None

    direct_keys = [
        field_name,
        code,
        code.split(".")[0],
    ]
    for key in direct_keys:
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


def read_option_iv(
    ContextInfo,
    code,
    spot=None,
    strike=None,
    rate=0.02,
    dte=0,
    option_type="CALL",
    market_price=None,
):
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


def log(*items):
    print("[V12_PAPER]", *items)


def round_order_price(value):
    number = safe_float(value)
    if number is None or number <= 0:
        return -1
    ticks = int(number / QMT_PRICE_TICK + 0.5)
    price = max(ticks * QMT_PRICE_TICK, QMT_PRICE_TICK)
    return round(price, 4)


def qmt_order_price(side, reference_price):
    reference = safe_float(reference_price)
    if reference is None or reference <= 0:
        return -1
    if side == "buy":
        return round_order_price(reference + QMT_BUY_LIMIT_BUFFER)
    return round_order_price(reference - QMT_SELL_LIMIT_BUFFER)


def submit_qmt_order(ContextInfo, side, code, quantity, reference_price=None):
    global RUNTIME_ORDER_KEYS
    if not QMT_NATIVE_ORDER_ENABLED:
        return True
    if not getattr(ContextInfo, "live_orders_allowed", False):
        log("QMT_ORDER_BLOCKED", "preflight_not_ready")
        return False
    if LIVE_REQUIRE_LAST_BAR_FOR_ORDER:
        try:
            is_last = bool(ContextInfo.is_last_bar())
        except Exception:
            is_last = False
        if not is_last:
            log(
                "QMT_ORDER_BLOCKED",
                "not_current_live_bar",
                side,
                code,
            )
            return False
    order_bar_text, unused_date, unused_time = current_datetime(ContextInfo)
    order_key = (
        str(order_bar_text),
        str(side),
        str(code),
        int(quantity),
    )
    if order_key in RUNTIME_ORDER_KEYS:
        log(
            "QMT_ORDER_BLOCKED",
            "duplicate_order_key",
            repr(order_key),
        )
        return False
    RUNTIME_ORDER_KEYS.add(order_key)
    account_id = getattr(ContextInfo, "live_account_id", QMT_ACCOUNT_ID)
    if not account_id:
        log("QMT_ORDER_BLOCKED", "missing_account_id")
        return False
    operation = (
        QMT_BUY_OPEN_OP
        if side == "buy"
        else QMT_SELL_CLOSE_OP
    )
    if QMT_ORDER_CODE_WITH_SUFFIX:
        order_code = str(code)
    else:
        order_code = str(code).split(".")[0]
    order_price = qmt_order_price(side, reference_price)
    log(
        "PASSORDER_ARGS",
        "style=",
        QMT_PASSORDER_STYLE,
        "operation=",
        operation,
        "account_type=",
        QMT_OPTION_ACCOUNT_TYPE,
        "account=",
        masked_account(account_id),
        "code=",
        order_code,
        "price_type=",
        QMT_MARKET_PRICE_TYPE,
        "price=",
        order_price,
        "ref_price=",
        round(reference_price, 6)
        if reference_price is not None
        else None,
        "qty=",
        int(quantity),
        "strategy=",
        QMT_STRATEGY_NAME,
        "quick=",
        QMT_QUICK_TRADE,
        "buy_buffer=",
        QMT_BUY_LIMIT_BUFFER,
        "sell_buffer=",
        QMT_SELL_LIMIT_BUFFER,
    )
    try:
        user_order_id = (
            "v12_%s_%s_%s" % (
                str(side),
                str(order_code).replace(".", ""),
                str(order_bar_text),
            )
        )
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
        elif QMT_PASSORDER_STYLE == "strategy11":
            result = passorder(
                operation,
                QMT_OPTION_ACCOUNT_TYPE,
                account_id,
                order_code,
                QMT_MARKET_PRICE_TYPE,
                order_price,
                int(quantity),
                QMT_STRATEGY_NAME,
                QMT_QUICK_TRADE,
                user_order_id,
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
        log(
            "QMT_ORDER_SENT",
            side,
            order_code,
            "qty=",
            int(quantity),
        )
        return True
    except Exception as exc:
        log(
            "QMT_ORDER_ERROR",
            side,
            order_code,
            repr(exc),
        )
        return False


def callback_value(value, names, default=None):
    for name in names:
        try:
            found = getattr(value, name)
            if found is not None:
                return found
        except Exception:
            pass
    return default


def order_callback(ContextInfo, orderInfo):
    log(
        "ORDER_CALLBACK",
        "code=",
        callback_value(
            orderInfo,
            ["m_strInstrumentID", "stock_code", "code"],
            "",
        ),
        "status=",
        callback_value(
            orderInfo,
            ["m_nOrderStatus", "order_status", "status"],
            "",
        ),
        "ordered=",
        callback_value(
            orderInfo,
            ["m_nOrderVolume", "order_volume", "volume"],
            "",
        ),
        "traded=",
        callback_value(
            orderInfo,
            ["m_nTradedVolume", "traded_volume"],
            "",
        ),
        "message=",
        callback_value(
            orderInfo,
            ["m_strStatusMsg", "status_msg", "message"],
            "",
        ),
    )


def deal_callback(ContextInfo, dealInfo):
    log(
        "DEAL_CALLBACK",
        "code=",
        callback_value(
            dealInfo,
            ["m_strInstrumentID", "stock_code", "code"],
            "",
        ),
        "qty=",
        callback_value(
            dealInfo,
            ["m_nVolume", "traded_volume", "volume"],
            "",
        ),
        "price=",
        callback_value(
            dealInfo,
            ["m_dPrice", "traded_price", "price"],
            "",
        ),
        "side=",
        callback_value(
            dealInfo,
            ["m_nOffsetFlag", "m_nDirection", "side"],
            "",
        ),
    )


# ---------------------------------------------------------------------------
# State and bar aggregation
# ---------------------------------------------------------------------------

def new_underlying_state(code):
    return {
        "code": code,
        "current_date": 0,
        "day_bars": [],
        "pending15": [],
        "bars15": embedded_15m_rows(code),
        "daily": [],
        "pool": {"CALL": [], "PUT": []},
        "option_bars": {},
        "pool_ready": False,
        "opening_signal": None,
        "opening_evaluated": False,
        "opening_trade_entered": False,
        "fallback_pending": None,
        "fallback_monitor_active": False,
        "last_iv_market": None,
        "last_iv_rank": None,
        "last_fallback_signal_time": "",
    }


def history_mapping_rows(mapping):
    if not isinstance(mapping, dict):
        return []
    required = ["open", "high", "low", "close"]
    rows = []

    # Shape A: {timetag: {open: ..., close: ...}}
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

    # Shape B: {open: {timetag: ...}, close: {timetag: ...}}
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

    # QMT get_market_data_ex usually returns a DataFrame-like object.
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
    return rows


def embedded_daily_rows(code):
    rows = []
    for values in LIVE_DAILY_SEED.get(code, []):
        rows.append(
            {
                "date": values[0],
                "open": values[1],
                "high": values[2],
                "low": values[3],
                "close": values[4],
                "volume": values[5],
                "amount": values[6],
            }
        )
    return rows


def embedded_15m_rows(code):
    rows = []
    for values in LIVE_15M_SEED.get(code, []):
        rows.append(
            {
                "datetime": values[0],
                "time": values[1],
                "open": values[2],
                "high": values[3],
                "low": values[4],
                "close": values[5],
                "volume": (
                    values[6] / LIVE_15M_SEED_VOLUME_DIVISOR
                ),
                "amount": values[7],
            }
        )
    return rows


def preload_daily_data(ContextInfo, state):
    code = state["code"]
    rows = embedded_daily_rows(code)
    log(
        "DAILY_SEED_LOADED",
        code,
        "days=",
        len(rows),
        "last_date=",
        rows[-1]["date"] if rows else 0,
    )
    if len(rows) >= LIVE_REQUIRE_DAILY_BARS:
        state["daily"] = rows[-280:]
        log("DAILY_PRELOAD_OK", code, "days=", len(state["daily"]))
        return
    try:
        raw = ContextInfo.get_market_data_ex(
            ["open", "high", "low", "close", "volume", "amount"],
            stock_code=[code],
            period="1d",
            start_time="20250101",
            end_time="",
            count=-1,
            dividend_type="none",
            fill_data=True,
            subscribe=False,
        )
        downloaded = standardized_daily_rows(raw, code)
        if downloaded:
            rows.extend(downloaded)
            log("DAILY_PRELOAD_SOURCE", code, "get_market_data_ex")
    except Exception as exc:
        log("DAILY_PRELOAD_EX_ERROR", code, repr(exc))

    if len(rows) < LIVE_REQUIRE_DAILY_BARS:
        try:
            raw = ContextInfo.get_local_data(
                stock_code=code,
                start_time="20250101",
                end_time="",
                period="1d",
                divid_type="none",
                count=-1,
            )
            downloaded = standardized_daily_rows(raw, code)
            if downloaded:
                rows.extend(downloaded)
                log("DAILY_PRELOAD_SOURCE", code, "get_local_data")
        except Exception as exc:
            log("DAILY_PRELOAD_LOCAL_ERROR", code, repr(exc))

    rows.sort(key=lambda item: item["date"])
    deduplicated = {}
    for row in rows:
        deduplicated[row["date"]] = row
    state["daily"] = [
        deduplicated[key]
        for key in sorted(deduplicated.keys())
    ][-280:]
    log("DAILY_PRELOAD_OK", code, "days=", len(state["daily"]))


def finish_daily_bar(state):
    bars = state.get("day_bars", [])
    if not bars:
        return
    first = bars[0]
    last = bars[-1]
    daily_bar = {
        "date": state.get("current_date", 0),
        "open": first["open"],
        "high": max(item["high"] for item in bars),
        "low": min(item["low"] for item in bars),
        "close": last["close"],
        "volume": sum(item["volume"] for item in bars),
        "amount": sum(item["amount"] for item in bars),
    }
    state["daily"].append(daily_bar)
    if len(state["daily"]) > 280:
        state["daily"] = state["daily"][-280:]


def reset_for_new_day(state, current_date):
    if state.get("current_date", 0) > 0:
        finish_daily_bar(state)
    state["current_date"] = current_date
    merged = {}
    for item in state.get("daily", []):
        if item.get("date", 0) < current_date:
            merged[item["date"]] = item
    # Embedded rows win over an incomplete after-hours replay of the same day.
    for item in embedded_daily_rows(state["code"]):
        if item.get("date", 0) < current_date:
            merged[item["date"]] = item
    state["daily"] = [
        merged[key]
        for key in sorted(merged.keys())
    ][-280:]
    state["day_bars"] = []
    state["pending15"] = []
    state["pool"] = {"CALL": [], "PUT": []}
    state["option_bars"] = {}
    state["pool_ready"] = False
    state["opening_signal"] = None
    state["opening_evaluated"] = False
    state["opening_trade_entered"] = False
    state["fallback_pending"] = None
    state["fallback_monitor_active"] = False
    state["last_iv_market"] = None
    state["last_iv_rank"] = None
    state["last_fallback_signal_time"] = ""


def append_etf_bar(state, now_text, time_text, bar):
    item = {
        "datetime": now_text,
        "time": time_text,
        "open": bar["open"],
        "high": bar["high"],
        "low": bar["low"],
        "close": bar["close"],
        "volume": bar["volume"],
        "amount": bar["amount"],
    }
    state["day_bars"].append(item)
    state["pending15"].append(item)


def append_15m_if_complete(state, time_text):
    if len(time_text) != 4:
        return False
    minute = safe_int(time_text[2:4], -1)
    if minute not in [0, 15, 30, 45]:
        return False
    if time_text in ["0930", "1300"]:
        return False
    pending = state.get("pending15", [])
    if len(pending) < 14:
        if pending:
            log(
                "BAR15_INCOMPLETE_SKIPPED",
                state["code"],
                time_text,
                "minute_bars=",
                len(pending),
            )
            state["pending15"] = []
        return False

    bar15 = {
        "datetime": pending[-1]["datetime"],
        "time": time_text,
        "open": pending[0]["open"],
        "high": max(item["high"] for item in pending),
        "low": min(item["low"] for item in pending),
        "close": pending[-1]["close"],
        "volume": sum(item["volume"] for item in pending),
        "amount": sum(item["amount"] for item in pending),
    }
    state["bars15"].append(bar15)
    if len(state["bars15"]) > 400:
        state["bars15"] = state["bars15"][-400:]
    state["pending15"] = []
    return True


def daily_context(state, current_price):
    daily = state.get("daily", [])
    if FORCE_TEST_DIRECTION in ["call", "put"]:
        return {
            "direction": FORCE_TEST_DIRECTION,
            "ma5": current_price,
            "ma10": current_price,
            "ma20": current_price,
            "ma5_slope": 0.001 if FORCE_TEST_DIRECTION == "call" else -0.001,
            "ma20_slope": 0.001 if FORCE_TEST_DIRECTION == "call" else -0.001,
            "cluster": 0.02,
            "volume_ratio20": 1.0,
            "upper_shadow": 0.0,
            "lower_shadow": 0.0,
            "ready": True,
            "forced": True,
        }
    if len(daily) < 21:
        return {"direction": "none", "ready": False, "forced": False}

    closes = [item["close"] for item in daily]
    volumes = [item["volume"] for item in daily]
    ma5 = sma(closes, 5)
    ma10 = sma(closes, 10)
    ma20 = sma(closes, 20)
    prev_ma5 = mean(closes[-6:-1])
    prev_ma20 = mean(closes[-21:-1])
    ma5_slope = ma5 - prev_ma5
    ma20_slope = ma20 - prev_ma20
    last = daily[-1]
    day_range = last["high"] - last["low"]
    upper_shadow = 0.0
    lower_shadow = 0.0
    if day_range > 0:
        upper_shadow = (
            last["high"] - max(last["open"], last["close"])
        ) / day_range
        lower_shadow = (
            min(last["open"], last["close"]) - last["low"]
        ) / day_range
    avg_volume20 = mean(volumes[-20:])
    volume_ratio20 = (
        last["volume"] / avg_volume20
        if avg_volume20 is not None and avg_volume20 > 0
        else None
    )
    cluster = (
        max(ma5, ma10, ma20) - min(ma5, ma10, ma20)
    ) / last["close"]

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
        "direction": direction,
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "ma5_slope": ma5_slope,
        "ma20_slope": ma20_slope,
        "cluster": cluster,
        "volume_ratio20": volume_ratio20,
        "upper_shadow": upper_shadow,
        "lower_shadow": lower_shadow,
        "ready": True,
        "forced": False,
    }


# ---------------------------------------------------------------------------
# Current option pool and selection
# ---------------------------------------------------------------------------

def build_option_pool(ContextInfo, state, current_date, spot):
    code = state["code"]
    historical = HISTORICAL_OPTION_POOL.get(
        current_date,
        {},
    ).get(code)
    if historical is not None:
        for option_type in ["CALL", "PUT"]:
            values = []
            for source in historical.get(option_type, []):
                item = dict(source)
                item["distance"] = abs(item["strike"] - spot)
                values.append(item)
                state["option_bars"].setdefault(item["code"], [])
            state["pool"][option_type] = values
        state["pool_ready"] = True
        log(
            "POOL_READY_HISTORICAL",
            current_date,
            code,
            "CALL",
            len(state["pool"]["CALL"]),
            "PUT",
            len(state["pool"]["PUT"]),
        )
        log_option_pool_detail(code, state["pool"])
        return
    if (
        HISTORICAL_PARITY_MODE
        and current_date <= HISTORICAL_PARITY_END_DATE
    ):
        state["pool"] = {"CALL": [], "PUT": []}
        state["pool_ready"] = True
        log("POOL_EMPTY_PARITY_DATE", current_date, code)
        return
    try:
        option_codes = ContextInfo.get_option_undl_data(code)
    except Exception as exc:
        log("POOL_ERROR", code, repr(exc))
        return
    if option_codes is None:
        option_codes = []

    by_type = {"CALL": [], "PUT": []}
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
        option_type = str(detail.get("optType", "")).upper()
        if (
            option_type not in ["CALL", "PUT"]
            or strike is None
            or strike <= 0
            or not (open_date <= current_date <= expire_date)
        ):
            continue
        dte = days_to_expiry(current_date, expire_date)
        if dte is None or dte < DTE_MIN or dte > DTE_MAX:
            continue
        rate = safe_float(detail.get("OptUndlRiskFreeRate"), 0.02)
        multiplier = safe_int(
            detail.get(
                "OptUnit",
                detail.get("VolumeMultiple", CONTRACT_MULTIPLIER_DEFAULT),
            ),
            CONTRACT_MULTIPLIER_DEFAULT,
        )
        by_type[option_type].append(
            {
                "code": str(option_code),
                "detail": detail,
                "open": open_date,
                "expire": expire_date,
                "strike": strike,
                "dte": dte,
                "rate": rate,
                "multiplier": multiplier,
                "distance": abs(strike - spot),
            }
        )

    for option_type in ["CALL", "PUT"]:
        values = sorted(
            by_type[option_type],
            key=lambda item: (
                item["distance"],
                item["dte"],
                item["strike"],
            ),
        )[:POOL_PER_SIDE]
        state["pool"][option_type] = values
        for item in values:
            state["option_bars"].setdefault(item["code"], [])
    state["pool_ready"] = True
    log(
        "POOL_READY",
        code,
        "CALL",
        len(state["pool"]["CALL"]),
        "PUT",
        len(state["pool"]["PUT"]),
    )
    log_option_pool_detail(code, state["pool"])


def option_name_from_detail(detail):
    if not isinstance(detail, dict):
        return ""
    for key in [
        "InstrumentName",
        "OptName",
        "Name",
        "SecurityName",
        "ContractName",
    ]:
        value = detail.get(key)
        if value:
            return str(value)
    return ""


def option_pool_item_text(item):
    name = option_name_from_detail(item.get("detail", {}))
    parts = [
        str(item.get("code", "")),
        "expire=%s" % str(item.get("expire", "")),
        "dte=%s" % str(item.get("dte", "")),
        "strike=%s" % str(item.get("strike", "")),
    ]
    if name:
        parts.append("name=%s" % name)
    return "|".join(parts)


def log_option_pool_detail(underlying, pool):
    for option_type in ["CALL", "PUT"]:
        values = pool.get(option_type, [])
        detail_text = ";".join(
            [option_pool_item_text(item) for item in values]
        )
        log(
            "POOL_DETAIL",
            underlying,
            option_type,
            "count=",
            len(values),
            "contracts=",
            detail_text,
        )


def update_option_bars(ContextInfo, state, now_text, time_text):
    for option_type in ["CALL", "PUT"]:
        for item in state["pool"].get(option_type, []):
            option_code = item["code"]
            bar = read_bar(ContextInfo, option_code)
            if bar is None:
                continue
            values = state["option_bars"].setdefault(option_code, [])
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
                state["option_bars"][option_code] = values[-300:]


def option_5m_trend(option_bars):
    if len(option_bars) < 6:
        return False, 0.0
    grouped = []
    bucket = None
    last_close = None
    for bar in option_bars:
        time_text = bar["time"]
        hour = safe_int(time_text[:2])
        minute = safe_int(time_text[2:4])
        this_bucket = hour * 12 + minute // 5
        if bucket is None:
            bucket = this_bucket
        if this_bucket != bucket:
            if last_close is not None:
                grouped.append(last_close)
            bucket = this_bucket
        last_close = bar["close"]
    if last_close is not None:
        grouped.append(last_close)
    if len(grouped) < 2:
        return False, 0.0
    ema5 = ema_series(grouped, 5)
    last = grouped[-1]
    strength = last / ema5[-1] - 1.0 if ema5[-1] > 0 else 0.0
    return last > ema5[-1] and ema5[-1] > ema5[-2], strength


def select_option(
    ContextInfo,
    state,
    direction,
    spot,
    asof_time=None,
):
    option_type = "CALL" if direction == "call" else "PUT"
    ranked = []
    rejected = {
        "no_bars": 0,
        "bad_price": 0,
        "iv": 0,
        "delta": 0,
        "trend": 0,
        "volume": 0,
    }
    for item in state["pool"].get(option_type, []):
        option_code = item["code"]
        bars = state["option_bars"].get(option_code, [])
        if asof_time is not None:
            bars = [
                bar
                for bar in bars
                if bar.get("time", "") <= asof_time
            ]
        if not bars:
            rejected["no_bars"] += 1
            continue
        last = bars[-1]
        if last["close"] <= 0:
            rejected["bad_price"] += 1
            continue
        if item.get("fixed_iv") is not None:
            iv = item["fixed_iv"]
            iv_source = "historical_metadata"
        else:
            iv, iv_source = read_option_iv(
                ContextInfo,
                option_code,
                spot,
                item["strike"],
                item["rate"],
                item["dte"],
                option_type,
                last["close"],
            )
        if iv is None or iv < IV_MIN or iv > IV_MAX:
            rejected["iv"] += 1
            continue
        delta = item.get("fixed_delta")
        if delta is None:
            delta = bs_delta(
                spot,
                item["strike"],
                item["rate"],
                iv,
                item["dte"],
                option_type,
            )
        if delta is None or not DELTA_MIN <= abs(delta) <= DELTA_MAX:
            rejected["delta"] += 1
            continue
        trend_ok, trend_strength = option_5m_trend(bars)
        if REQUIRE_OPTION_TREND and not trend_ok:
            rejected["trend"] += 1
            continue
        cum_volume = sum(bar["volume"] for bar in bars)
        if cum_volume <= 0:
            rejected["volume"] += 1
            continue
        ranked.append(
            {
                "code": option_code,
                "strike": item["strike"],
                "dte": item["dte"],
                "iv": iv,
                "iv_source": iv_source,
                "delta": delta,
                "multiplier": item["multiplier"],
                "cum_volume": cum_volume,
                "trend_strength": max(trend_strength, 0.0),
                "bar": last,
            }
        )
    if not ranked:
        log(
            "SELECT_NO_MATCH",
            state["code"],
            direction,
            repr(rejected),
        )
        return None

    max_volume = max(item["cum_volume"] for item in ranked)
    max_trend = max(item["trend_strength"] for item in ranked)
    if max_volume <= 0:
        max_volume = 1.0
    if max_trend <= 0:
        max_trend = 1.0
    for item in ranked:
        liquidity_score = item["cum_volume"] / max_volume
        delta_score = max(
            0.0,
            min(1.0, 1.0 - abs(abs(item["delta"]) - 0.50) / 0.15),
        )
        trend_score = item["trend_strength"] / max_trend
        dte_score = 1.0 if item["dte"] <= 25 else 0.65
        iv_score = max(
            0.0,
            min(1.0, 1.0 - max(item["iv"] - 0.40, 0.0) / 0.30),
        )
        item["score"] = (
            0.40 * liquidity_score
            + 0.25 * delta_score
            + 0.20 * trend_score
            + 0.10 * dte_score
            + 0.05 * iv_score
        )
    ranked.sort(key=lambda item: item["score"], reverse=True)
    log(
        "OPTION_SELECTED",
        state["code"],
        direction,
        ranked[0]["code"],
        "iv_source=",
        ranked[0]["iv_source"],
        "score=",
        round(ranked[0]["score"], 4),
    )
    return ranked[0]


def select_smoke_option(ContextInfo, state, direction, spot):
    selected = select_option(ContextInfo, state, direction, spot)
    if selected is not None:
        return selected

    option_type = "CALL" if direction == "call" else "PUT"
    for item in state["pool"].get(option_type, []):
        bars = state["option_bars"].get(item["code"], [])
        if not bars or bars[-1]["close"] <= 0:
            continue
        last = bars[-1]
        iv, iv_source = read_option_iv(
            ContextInfo,
            item["code"],
            spot,
            item["strike"],
            item["rate"],
            item["dte"],
            option_type,
            last["close"],
        )
        if iv is None:
            iv = 0.40
            iv_source = "smoke_default"
        delta = bs_delta(
            spot,
            item["strike"],
            item["rate"],
            iv,
            item["dte"],
            option_type,
        )
        log(
            "SMOKE_RELAXED_OPTION",
            item["code"],
            "iv_source=",
            iv_source,
            "delta=",
            round(delta, 4) if delta is not None else None,
        )
        return {
            "code": item["code"],
            "strike": item["strike"],
            "dte": item["dte"],
            "iv": iv,
            "iv_source": iv_source,
            "delta": delta if delta is not None else 0.50,
            "multiplier": item["multiplier"],
            "cum_volume": sum(bar["volume"] for bar in bars),
            "trend_strength": 0.0,
            "bar": last,
            "score": 0.0,
        }
    return None


# ---------------------------------------------------------------------------
# ETF signals
# ---------------------------------------------------------------------------

def bars_by_time(state):
    return dict((bar["time"], bar) for bar in state.get("day_bars", []))


def detect_opening_signal(state, daily_info):
    if not daily_info.get("ready"):
        return None
    direction = daily_info.get("direction", "none")
    if direction not in ["call", "put"]:
        return None
    mapping = bars_by_time(state)
    first_times = ["0930", "0931", "0932", "0933", "0934"]
    if any(time_text not in mapping for time_text in first_times):
        return None
    first5 = [mapping[time_text] for time_text in first_times]
    opening_high = max(item["high"] for item in first5)
    opening_low = min(item["low"] for item in first5)
    opening_amp = (
        (opening_high - opening_low) / opening_low
        if opening_low > 0
        else 0.0
    )
    threshold = RANGE_THRESHOLD[state["code"]]
    if opening_amp < threshold:
        return None
    vol_mean = mean([item["volume"] for item in first5])
    vol_max = max(item["volume"] for item in first5)
    if vol_mean is None or vol_mean <= 0:
        return None

    scan_times = ["0935", "0936", "0937", "0938", "0939", "0940"]
    ordered = state.get("day_bars", [])
    for scan_time in scan_times:
        row = mapping.get(scan_time)
        if row is None:
            continue
        broke = (
            direction == "call" and row["high"] > opening_high
        ) or (
            direction == "put" and row["low"] < opening_low
        )
        if not broke:
            continue
        volume_ok = (
            row["volume"]
            >= vol_mean * BREAKOUT_VOLUME_MULT[state["code"]]
            and row["volume"] >= vol_max * BREAKOUT_VOLUME_MAX_MULT
        )
        if not volume_ok:
            continue
        row_index = ordered.index(row)
        future = ordered[row_index + 1:row_index + 4]
        if len(future) < 3 or future[-1]["time"] > "0943":
            continue
        if direction == "call":
            stand_count = len(
                [item for item in future if item["close"] > opening_high]
            )
        else:
            stand_count = len(
                [item for item in future if item["close"] < opening_low]
            )
        if stand_count < 2:
            continue
        volume_ratio = row["volume"] / vol_mean
        normalized_strength = (
            opening_amp / threshold
        ) * (
            volume_ratio / BREAKOUT_VOLUME_MULT[state["code"]]
        )
        entry_minute = max(
            safe_int(row["time"]) + 3,
            940,
        )
        entry_time = "%04d" % entry_minute
        return {
            "underlying": state["code"],
            "direction": direction,
            "opening_high": opening_high,
            "opening_low": opening_low,
            "opening_amp": opening_amp,
            "breakout_time": row["time"],
            "breakout_volume_ratio": volume_ratio,
            "stand_count": stand_count,
            "normalized_strength": normalized_strength,
            "strong": volume_ratio >= 2.0,
            "entry_time": entry_time,
        }
    return None


def fallback_signal(state, daily_info):
    bars15 = state.get("bars15", [])
    if len(bars15) < 21:
        return None
    current = bars15[-1]
    time_text = current["time"]
    if time_text < "0945" or time_text > "1415":
        return None
    if not (time_text <= "1100" or time_text >= "1315"):
        return None
    if state.get("last_fallback_signal_time") == current["datetime"]:
        return None
    if not daily_info.get("ready"):
        return None
    if daily_info.get("cluster", 0.0) < 0.015:
        return None
    volume_ratio20 = daily_info.get("volume_ratio20")
    if volume_ratio20 is None or volume_ratio20 < 0.65:
        return None

    previous = bars15[:-1]
    closes = [bar["close"] for bar in bars15]
    ema5 = ema_series(closes, 5)
    ema20 = ema_series(closes, 20)
    ema20_slope = ema20[-1] - ema20[-2]
    prev3_high = max(bar["high"] for bar in previous[-3:])
    prev3_low = min(bar["low"] for bar in previous[-3:])
    prev5_volume = mean([bar["volume"] for bar in previous[-5:]])
    if prev5_volume is None or prev5_volume <= 0:
        return None
    ratio = current["volume"] / prev5_volume
    if ratio < 2.0:
        return None
    bar_range = current["high"] - current["low"]
    close_pos = (
        (current["close"] - current["low"]) / bar_range
        if bar_range > 0
        else 0.5
    )
    call_signal = (
        current["close"] > prev3_high
        and ema5[-1] > ema20[-1]
        and ema20_slope > 0
        and close_pos >= (0.75 if time_text == "0945" else 0.65)
    )
    put_signal = (
        current["close"] < prev3_low
        and ema5[-1] < ema20[-1]
        and ema20_slope < 0
        and close_pos <= (0.25 if time_text == "0945" else 0.35)
    )
    direction = "call" if call_signal else "put" if put_signal else None
    if direction is None or direction != daily_info.get("direction"):
        return None
    state["last_fallback_signal_time"] = current["datetime"]
    return {
        "underlying": state["code"],
        "direction": direction,
        "signal_time": current["datetime"],
        "signal_hhmm": time_text,
        "volume_ratio": ratio,
        "strong": True,
    }


def latest_15m_metrics(state):
    bars15 = state.get("bars15", [])
    if len(bars15) < 2:
        return None
    closes = [bar["close"] for bar in bars15]
    ema5 = ema_series(closes, 5)
    ema20 = ema_series(closes, 20)
    return {
        "close": closes[-1],
        "ema5": ema5[-1],
        "ema20": ema20[-1],
        "ema20_slope": ema20[-1] - ema20[-2],
    }


# ---------------------------------------------------------------------------
# Paper account and exits
# ---------------------------------------------------------------------------

def latest_option_bar(ContextInfo, position):
    state = ContextInfo.paper_states[position["underlying"]]
    bars = state["option_bars"].get(position["code"], [])
    if bars:
        return bars[-1]
    return read_bar(ContextInfo, position["code"])


def paper_equity(ContextInfo):
    equity = ContextInfo.paper_cash
    position = ContextInfo.paper_position
    if position is not None:
        bar = latest_option_bar(ContextInfo, position)
        mark = (
            bar.get("close")
            if isinstance(bar, dict)
            else None
        )
        if mark is None or mark <= 0:
            mark = position["avg_price"]
        equity += (
            position["quantity"]
            * mark
            * position["multiplier"]
        )
    return equity


def position_target_pct(path, strong, iv, daily_info):
    if path == "opening":
        pct = (
            OPENING_STRONG_POSITION
            if strong
            else OPENING_NORMAL_POSITION
        )
    else:
        pct = FALLBACK_BASE_POSITION
    reasons = []
    if iv is not None and iv >= 0.50:
        pct *= 0.70
        reasons.append("high_iv")
    volume_ratio20 = daily_info.get("volume_ratio20")
    if volume_ratio20 is not None and volume_ratio20 < 0.80:
        pct *= 0.70
        reasons.append("low_daily_volume")
    pct = min(pct, POSITION_CAP)
    return pct, ",".join(reasons)


def paper_open(
    ContextInfo,
    selected,
    underlying,
    direction,
    path,
    strong,
    daily_info,
    now_text,
    fill_price,
    allocation_factor,
):
    if ContextInfo.paper_position is not None:
        return False
    if (
        LIVE_MAX_TRADES_PER_DAY > 0
        and ContextInfo.paper_day_entries >= LIVE_MAX_TRADES_PER_DAY
    ):
        log("BUY_BLOCKED_DAILY_LIMIT", now_text)
        return False
    target_pct, risk_reasons = position_target_pct(
        path,
        strong,
        selected["iv"],
        daily_info,
    )
    equity = paper_equity(ContextInfo)
    target_cost = equity * target_pct
    buy_budget = target_cost * allocation_factor
    multiplier = selected["multiplier"]
    execution_price = qmt_order_price("buy", fill_price)
    quantity = int(
        buy_budget / float(execution_price * multiplier)
    )
    if quantity <= 0:
        log(
            "BUY_BLOCKED_SMALL_BUDGET",
            underlying,
            selected["code"],
            buy_budget,
        )
        return False
    premium = quantity * execution_price * multiplier
    fee = quantity * FEE_PER_CONTRACT_PER_SIDE
    if premium + fee > ContextInfo.paper_cash:
        quantity = int(
            max(
                0.0,
                ContextInfo.paper_cash - FEE_PER_CONTRACT_PER_SIDE,
            ) / float(execution_price * multiplier + FEE_PER_CONTRACT_PER_SIDE)
        )
        premium = quantity * execution_price * multiplier
        fee = quantity * FEE_PER_CONTRACT_PER_SIDE
    if LIVE_MAX_CONTRACTS > 0:
        quantity = min(quantity, LIVE_MAX_CONTRACTS)
        premium = quantity * execution_price * multiplier
        fee = quantity * FEE_PER_CONTRACT_PER_SIDE
    if quantity <= 0:
        return False
    if not submit_qmt_order(
        ContextInfo,
        "buy",
        selected["code"],
        quantity,
        fill_price,
    ):
        log("BUY_ABORTED_ORDER_NOT_SENT", now_text, selected["code"])
        return False

    ContextInfo.paper_cash -= premium + fee
    ContextInfo.paper_position = {
        "code": selected["code"],
        "underlying": underlying,
        "direction": direction,
        "path": path,
        "strong": bool(strong),
        "quantity": quantity,
        "initial_quantity": quantity,
        "avg_price": fill_price,
        "avg_fill_price": execution_price,
        "first_price": fill_price,
        "multiplier": multiplier,
        "target_pct": target_pct,
        "target_cost": target_cost,
        "risk_reasons": risk_reasons,
        "entry_time": now_text,
        "entry_minute": safe_int(now_text[8:12]),
        "opening_confirmed": path != "opening",
        "partial_done": False,
        "high_water": fill_price,
        "trailing_stop": None,
        "total_buy": premium,
        "total_sell": 0.0,
        "total_fees": fee,
    }
    ContextInfo.paper_day_locked = True
    ContextInfo.paper_day_entries += 1
    ContextInfo.paper_states[underlying]["opening_trade_entered"] = (
        path == "opening"
    )
    log(
        "BUY",
        now_text,
        path,
        underlying,
        direction,
        selected["code"],
        "qty=",
        quantity,
        "price=",
        round(fill_price, 6),
        "fill=",
        round(execution_price, 6),
        "target_pct=",
        round(target_pct, 4),
        "iv=",
        round(selected["iv"], 4),
        "delta=",
        round(selected["delta"], 4),
        "dte=",
        selected["dte"],
        "risk=",
        risk_reasons,
        "cash=",
        round(ContextInfo.paper_cash, 2),
    )
    log("SHADOW_FILL_ASSUMED", "buy", selected["code"], "qty=", quantity)
    return True


def paper_add_opening(ContextInfo, now_text, fill_price):
    position = ContextInfo.paper_position
    if position is None or position["path"] != "opening":
        return
    if fill_price > position["first_price"] * 1.03:
        log("ADD_SKIPPED_PRICE", now_text, round(fill_price, 6))
        position["opening_confirmed"] = True
        return
    weighted_mid = (
        position["first_price"] * OPENING_FIRST_LEG_RATIO
        + fill_price * (1.0 - OPENING_FIRST_LEG_RATIO)
    )
    weighted_fill = qmt_order_price("buy", weighted_mid)
    target_quantity = int(
        position["target_cost"]
        / float(weighted_fill * position["multiplier"])
    )
    quantity = max(target_quantity - position["quantity"], 0)
    if LIVE_MAX_CONTRACTS > 0:
        target_quantity = min(target_quantity, LIVE_MAX_CONTRACTS)
        quantity = max(target_quantity - position["quantity"], 0)
    target_premium = (
        target_quantity
        * weighted_fill
        * position["multiplier"]
    )
    premium = target_premium - position["total_buy"]
    fee = quantity * FEE_PER_CONTRACT_PER_SIDE
    if quantity <= 0 or premium + fee > ContextInfo.paper_cash:
        position["opening_confirmed"] = True
        return
    if not submit_qmt_order(
        ContextInfo,
        "buy",
        position["code"],
        quantity,
        fill_price,
    ):
        log("ADD_ABORTED_ORDER_NOT_SENT", now_text, position["code"])
        position["opening_confirmed"] = True
        return
    new_quantity = target_quantity
    position["avg_price"] = weighted_mid
    position["avg_fill_price"] = weighted_fill
    position["quantity"] = new_quantity
    position["initial_quantity"] = new_quantity
    position["total_buy"] = target_premium
    position["total_fees"] += fee
    position["opening_confirmed"] = True
    position["high_water"] = max(
        position["high_water"],
        position["avg_price"],
    )
    ContextInfo.paper_cash -= premium + fee
    log(
        "ADD",
        now_text,
        position["code"],
        "qty=",
        quantity,
        "price=",
        round(fill_price, 6),
        "total_qty=",
        new_quantity,
        "avg=",
        round(position["avg_price"], 6),
        "avg_fill=",
        round(position["avg_fill_price"], 6),
    )
    log("SHADOW_FILL_ASSUMED", "buy_add", position["code"], "qty=", quantity)


def paper_sell(ContextInfo, now_text, quantity, fill_price, reason):
    position = ContextInfo.paper_position
    if position is None:
        return
    quantity = min(max(safe_int(quantity), 0), position["quantity"])
    if quantity <= 0:
        return
    if not submit_qmt_order(
        ContextInfo,
        "sell",
        position["code"],
        quantity,
        fill_price,
    ):
        log("SELL_ABORTED_ORDER_NOT_SENT", now_text, position["code"])
        return
    execution_price = qmt_order_price("sell", fill_price)
    proceeds = quantity * execution_price * position["multiplier"]
    fee = quantity * FEE_PER_CONTRACT_PER_SIDE
    ContextInfo.paper_cash += proceeds - fee
    position["quantity"] -= quantity
    position["total_sell"] += proceeds
    position["total_fees"] += fee
    log(
        "SELL",
        now_text,
        position["code"],
        "qty=",
        quantity,
        "price=",
        round(fill_price, 6),
        "fill=",
        round(execution_price, 6),
        "reason=",
        reason,
        "remaining=",
        position["quantity"],
        "cash=",
        round(ContextInfo.paper_cash, 2),
    )
    log("SHADOW_FILL_ASSUMED", "sell", position["code"], "qty=", quantity)
    if position["quantity"] <= 0:
        pnl = (
            position["total_sell"]
            - position["total_buy"]
            - position["total_fees"]
        )
        ContextInfo.paper_trade_count += 1
        log(
            "TRADE_CLOSED",
            now_text,
            position["underlying"],
            position["path"],
            position["code"],
            "pnl=",
            round(pnl, 2),
            "equity=",
            round(ContextInfo.paper_cash, 2),
            "trades=",
            ContextInfo.paper_trade_count,
        )
        ContextInfo.paper_position = None


def minutes_since_entry(position, now_text):
    try:
        entry = datetime.datetime.strptime(
            position["entry_time"],
            "%Y%m%d%H%M%S",
        )
        current = datetime.datetime.strptime(now_text, "%Y%m%d%H%M%S")
        return int((current - entry).total_seconds() / 60.0)
    except Exception:
        return 999


def option_ema5_weak(ContextInfo, position):
    state = ContextInfo.paper_states[position["underlying"]]
    bars = state["option_bars"].get(position["code"], [])
    closes = [bar["close"] for bar in bars]
    if len(closes) < 2:
        return False
    ema5 = ema_series(closes, 5)
    return closes[-1] < ema5[-1]


def etf_reversal(ContextInfo, position):
    state = ContextInfo.paper_states[position["underlying"]]
    metrics = latest_15m_metrics(state)
    if metrics is None:
        return False
    if position["direction"] == "call":
        return (
            metrics["close"] < metrics["ema20"]
            and metrics["ema20_slope"] < 0
        )
    return (
        metrics["close"] > metrics["ema20"]
        and metrics["ema20_slope"] > 0
    )


def manage_position(ContextInfo, now_text, time_text):
    position = ContextInfo.paper_position
    if position is None:
        return
    if (
        now_text == position.get("entry_time")
        and time_text < EOD_EXIT_TIME
    ):
        return
    bar = latest_option_bar(ContextInfo, position)
    if bar is None:
        return
    entry = position["avg_price"]
    position["high_water"] = max(position["high_water"], bar["high"])
    option_weak = option_ema5_weak(ContextInfo, position)
    reversal = etf_reversal(ContextInfo, position)

    soft_factor = (
        OPENING_SOFT_STOP_FACTOR
        if position["path"] == "opening"
        else FALLBACK_SOFT_STOP_FACTOR
    )
    soft_delay = (
        OPENING_SOFT_STOP_DELAY_MINUTES
        if position["path"] == "opening"
        else 0
    )
    soft_price = entry * soft_factor
    hard_price = entry * HARD_STOP_FACTOR
    enough_time = minutes_since_entry(position, now_text) >= soft_delay

    if (
        not position["partial_done"]
        and enough_time
        and bar["low"] <= soft_price
        and (option_weak or reversal)
    ):
        paper_sell(
            ContextInfo,
            now_text,
            position["quantity"],
            soft_price,
            "soft_stop",
        )
        return
    if bar["low"] <= hard_price:
        paper_sell(
            ContextInfo,
            now_text,
            position["quantity"],
            hard_price,
            "hard_stop",
        )
        return

    if not position["strong"]:
        tp1 = round(entry * NORMAL_TP1_FACTOR, 6)
        tp2 = round(entry * NORMAL_TP2_FACTOR, 6)
        if not position["partial_done"] and bar["high"] >= tp1:
            quantity = max(
                1,
                int(round(position["initial_quantity"] * 0.50)),
            )
            quantity = min(quantity, position["quantity"])
            paper_sell(ContextInfo, now_text, quantity, tp1, "tp1")
            if ContextInfo.paper_position is None:
                return
            ContextInfo.paper_position["partial_done"] = True
        position = ContextInfo.paper_position
        if (
            position is not None
            and position["partial_done"]
            and bar["high"] >= tp2
        ):
            paper_sell(
                ContextInfo,
                now_text,
                position["quantity"],
                tp2,
                "tp2",
            )
            return
    else:
        tp1 = round(entry * STRONG_TP1_FACTOR, 6)
        if not position["partial_done"] and bar["high"] >= tp1:
            quantity = max(
                1,
                int(round(position["initial_quantity"] / 3.0)),
            )
            quantity = min(quantity, position["quantity"])
            paper_sell(ContextInfo, now_text, quantity, tp1, "tp1_strong")
            if ContextInfo.paper_position is None:
                return
            position = ContextInfo.paper_position
            position["partial_done"] = True
            position["high_water"] = max(position["high_water"], tp1)
        position = ContextInfo.paper_position
        if position is not None and position["partial_done"]:
            trail_pct = (
                STRONG_TRAIL_BEFORE_1030
                if time_text < "1030"
                else STRONG_TRAIL_AFTER_1030
            )
            candidate_stop = position["high_water"] * (1.0 - trail_pct)
            old_stop = position.get("trailing_stop")
            if old_stop is None:
                position["trailing_stop"] = candidate_stop
            else:
                position["trailing_stop"] = max(old_stop, candidate_stop)
            if bar["low"] <= position["trailing_stop"]:
                paper_sell(
                    ContextInfo,
                    now_text,
                    position["quantity"],
                    position["trailing_stop"],
                    "trailing_stop",
                )
                return

    position = ContextInfo.paper_position
    if position is not None and time_text >= EOD_EXIT_TIME:
        paper_sell(
            ContextInfo,
            now_text,
            position["quantity"],
            bar["close"],
            "eod",
        )


# ---------------------------------------------------------------------------
# Main event flow
# ---------------------------------------------------------------------------

def evaluate_dual_opening(ContextInfo, now_text):
    if ContextInfo.paper_opening_evaluated:
        return
    ContextInfo.paper_opening_evaluated = True
    signals = []
    for code in UNDERLYINGS:
        state = ContextInfo.paper_states[code]
        last_price = (
            state["day_bars"][-1]["close"]
            if state["day_bars"]
            else None
        )
        daily_info = daily_context(state, last_price)
        signal = detect_opening_signal(state, daily_info)
        state["opening_signal"] = signal
        state["opening_evaluated"] = True
        if signal is not None:
            signal["daily_info"] = daily_info
            signals.append(signal)
            log(
                "OPENING_SIGNAL",
                now_text,
                code,
                signal["direction"],
                "strength=",
                round(signal["normalized_strength"], 4),
                "breakout=",
                signal["breakout_time"],
            )
    if not signals:
        log("NO_DUAL_OPENING_SIGNAL", now_text)
        return
    signals.sort(
        key=lambda item: item["normalized_strength"],
        reverse=True,
    )
    chosen = signals[0]
    state = ContextInfo.paper_states[chosen["underlying"]]
    spot = state["day_bars"][-1]["close"]
    selected = select_option(
        ContextInfo,
        state,
        chosen["direction"],
        spot,
        chosen.get("breakout_time"),
    )
    if selected is None:
        log(
            "OPENING_NO_OPTION",
            now_text,
            chosen["underlying"],
            chosen["direction"],
        )
        return
    entry_hhmm = chosen.get("entry_time", now_text[8:12])
    entry_bar = None
    for candidate_bar in state["option_bars"].get(
        selected["code"],
        [],
    ):
        if candidate_bar.get("time") == entry_hhmm:
            entry_bar = candidate_bar
            break
    if entry_bar is None:
        log(
            "OPENING_ENTRY_BAR_MISSING",
            chosen["underlying"],
            selected["code"],
            entry_hhmm,
        )
        return
    fill_price = entry_bar["close"]
    entry_now_text = now_text[:8] + entry_hhmm + "00"
    paper_open(
        ContextInfo,
        selected,
        chosen["underlying"],
        chosen["direction"],
        "opening",
        chosen["strong"],
        chosen["daily_info"],
        entry_now_text,
        fill_price,
        OPENING_FIRST_LEG_RATIO,
    )


def confirm_opening_at_0945(ContextInfo, now_text):
    position = ContextInfo.paper_position
    if (
        position is None
        or position["path"] != "opening"
        or position["opening_confirmed"]
    ):
        return
    state = ContextInfo.paper_states[position["underlying"]]
    signal = state.get("opening_signal")
    metrics = latest_15m_metrics(state)
    current_close = state["day_bars"][-1]["close"]
    passed = False
    if signal is not None and metrics is not None:
        if position["direction"] == "call":
            passed = (
                current_close > signal["opening_high"]
                and metrics["close"] > metrics["ema5"]
            )
        else:
            passed = (
                current_close < signal["opening_low"]
                and metrics["close"] < metrics["ema5"]
            )
    option_bar = latest_option_bar(ContextInfo, position)
    if option_bar is None:
        return
    if not passed:
        paper_sell(
            ContextInfo,
            now_text,
            position["quantity"],
            option_bar["close"],
            "opening_confirm_fail",
        )
        return
    paper_add_opening(ContextInfo, now_text, option_bar["close"])
    log("OPENING_CONFIRMED", now_text, position["underlying"])


def live_kcb_iv_regime(ContextInfo, state, spot):
    values = []
    for option_type in ["CALL", "PUT"]:
        for item in state["pool"].get(option_type, []):
            if item["dte"] < 10 or item["dte"] > 45:
                continue
            if spot <= 0 or abs(item["strike"] / spot - 1.0) > 0.08:
                continue
            bars = state["option_bars"].get(item["code"], [])
            if not bars:
                continue
            price = bars[-1].get("close")
            iv = implied_volatility(
                price,
                spot,
                item["strike"],
                item["rate"],
                item["dte"],
                option_type,
            )
            if iv is not None:
                values.append(iv)
    market_iv = median(values)
    denominator = LIVE_IV_ROLLING_MAX - LIVE_IV_ROLLING_MIN
    if market_iv is None or denominator <= 0:
        return None
    iv_rank = (
        market_iv - LIVE_IV_ROLLING_MIN
    ) / denominator
    iv_rank = max(0.0, min(1.0, iv_rank))
    state["last_iv_market"] = market_iv
    state["last_iv_rank"] = iv_rank
    log(
        "LIVE_IV_REGIME",
        state.get("current_date", 0),
        "market_iv_proxy=",
        round(market_iv, 4),
        "iv_rank_proxy=",
        round(iv_rank, 4),
        "contracts=",
        len(values),
        "source=live_atm_option_median",
    )
    return market_iv, iv_rank


def schedule_kcb_fallback(ContextInfo, now_text):
    if ContextInfo.paper_day_locked or ContextInfo.paper_position is not None:
        return
    state = ContextInfo.paper_states[KCB_CODE]
    if state.get("fallback_pending") is not None:
        return
    if not state.get("day_bars"):
        return
    current_date = state.get("current_date", 0)
    regime = HISTORICAL_KCB_IV_REGIME.get(current_date)
    if not HISTORICAL_PARITY_MODE:
        spot = state["day_bars"][-1]["close"]
        regime = live_kcb_iv_regime(ContextInfo, state, spot)
        if regime is None and LIVE_FAIL_CLOSED:
            log("FALLBACK_BLOCKED_IV_MISSING", now_text)
            return
    if regime is not None:
        market_iv, iv_rank = regime
        if market_iv < IV_MIN or iv_rank >= FALLBACK_IV_RANK_MAX:
            log(
                "FALLBACK_BLOCKED_IV_REGIME",
                now_text,
                "market_iv=",
                round(market_iv, 4),
                "iv_rank=",
                round(iv_rank, 4),
            )
            return
    spot = state["day_bars"][-1]["close"]
    daily_info = daily_context(state, spot)
    signal = fallback_signal(state, daily_info)
    if signal is None:
        return
    signal["daily_info"] = daily_info
    state["fallback_pending"] = signal
    state["fallback_monitor_active"] = True
    log(
        "FALLBACK_SIGNAL",
        now_text,
        signal["direction"],
        "volume_ratio=",
        round(signal["volume_ratio"], 4),
        "execute_next_minute",
    )


def execute_pending_fallback(ContextInfo, now_text, time_text):
    if ContextInfo.paper_day_locked or ContextInfo.paper_position is not None:
        return
    state = ContextInfo.paper_states[KCB_CODE]
    signal = state.get("fallback_pending")
    if signal is None:
        return
    signal_hhmm = signal.get("signal_hhmm", "")
    if time_text <= signal_hhmm:
        return
    spot = state["day_bars"][-1]["close"]
    selected = select_option(
        ContextInfo,
        state,
        signal["direction"],
        spot,
    )
    state["fallback_pending"] = None
    if selected is None:
        log("FALLBACK_NO_OPTION", now_text, signal["direction"])
        return
    fill_price = selected["bar"].get("open")
    if fill_price is None or fill_price <= 0:
        fill_price = selected["bar"]["close"]
    paper_open(
        ContextInfo,
        selected,
        KCB_CODE,
        signal["direction"],
        "fallback",
        True,
        signal["daily_info"],
        now_text,
        fill_price,
        1.0,
    )


def execute_smoke_test(
    ContextInfo,
    current_date,
    now_text,
    time_text,
):
    if (
        not EXECUTION_SMOKE_TEST
        or ContextInfo.paper_smoke_executed
        or (
            SMOKE_TEST_DATE > 0
            and current_date != SMOKE_TEST_DATE
        )
        or time_text < SMOKE_TEST_TIME
        or ContextInfo.paper_position is not None
        or ContextInfo.paper_day_locked
    ):
        return
    state = ContextInfo.paper_states.get(SMOKE_TEST_UNDERLYING)
    if state is None or not state.get("pool_ready"):
        log("SMOKE_WAIT_POOL", now_text, SMOKE_TEST_UNDERLYING)
        return
    if not state.get("day_bars"):
        return
    spot = state["day_bars"][-1]["close"]
    selected = select_smoke_option(
        ContextInfo,
        state,
        SMOKE_TEST_DIRECTION,
        spot,
    )
    if selected is None:
        log(
            "SMOKE_NO_OPTION",
            now_text,
            SMOKE_TEST_UNDERLYING,
            SMOKE_TEST_DIRECTION,
        )
        return
    daily_info = daily_context(state, spot)
    if not daily_info.get("ready"):
        daily_info = {
            "ready": True,
            "direction": SMOKE_TEST_DIRECTION,
            "volume_ratio20": 1.0,
        }
    opened = paper_open(
        ContextInfo,
        selected,
        SMOKE_TEST_UNDERLYING,
        SMOKE_TEST_DIRECTION,
        "smoke_test",
        False,
        daily_info,
        now_text,
        selected["bar"]["close"],
        1.0,
    )
    if opened:
        ContextInfo.paper_smoke_executed = True
        log(
            "SMOKE_ORDER_OPENED",
            now_text,
            "qmt_order_channel_test",
            "auto_close=",
            SMOKE_TEST_AUTO_CLOSE,
            "close_after_minutes=",
            SMOKE_TEST_CLOSE_AFTER_MINUTES,
        )


def execute_smoke_auto_close(ContextInfo, now_text):
    if (
        not EXECUTION_SMOKE_TEST
        or not SMOKE_TEST_AUTO_CLOSE
        or ContextInfo.paper_smoke_close_sent
    ):
        return
    position = ContextInfo.paper_position
    if position is None or position.get("path") != "smoke_test":
        return
    if minutes_since_entry(position, now_text) < SMOKE_TEST_CLOSE_AFTER_MINUTES:
        return
    bar = latest_option_bar(ContextInfo, position)
    if bar is None or bar.get("close") is None or bar.get("close") <= 0:
        log("SMOKE_AUTO_CLOSE_WAIT_PRICE", now_text, position["code"])
        return
    ContextInfo.paper_smoke_close_sent = True
    log(
        "SMOKE_AUTO_CLOSE",
        now_text,
        position["code"],
        "qty=",
        position["quantity"],
        "close=",
        round(bar["close"], 6),
    )
    paper_sell(
        ContextInfo,
        now_text,
        position["quantity"],
        bar["close"],
        "smoke_auto_close",
    )


def resolve_bound_account(ContextInfo):
    if QMT_ACCOUNT_ID:
        return str(QMT_ACCOUNT_ID)
    for name in ["accountID", "account_id", "accID", "accid"]:
        try:
            value = getattr(ContextInfo, name)
            if value:
                return str(value)
        except Exception:
            pass
    return ""


def masked_account(account_id):
    text = str(account_id)
    if len(text) <= 4:
        return text
    return "*" * (len(text) - 4) + text[-4:]


def run_live_preflight(ContextInfo):
    issues = []
    account_id = resolve_bound_account(ContextInfo)
    ContextInfo.live_account_id = account_id
    if HISTORICAL_PARITY_MODE:
        issues.append("historical_parity_mode_on")
    if PAPER_START_DATE != 20260703:
        issues.append("unexpected_start_date")
    if not QMT_NATIVE_ORDER_ENABLED:
        issues.append("native_order_disabled")
    if not account_id:
        issues.append("missing_account_id")
    if EXECUTION_SMOKE_TEST and not SMOKE_TEST_ALLOW_ORDERS:
        issues.append("smoke_test_must_be_off")
    if FORCE_TEST_DIRECTION:
        issues.append("forced_direction_must_be_empty")
    for code in UNDERLYINGS:
        days = len(ContextInfo.paper_states[code].get("daily", []))
        if days < LIVE_REQUIRE_DAILY_BARS:
            issues.append("daily_warmup_%s_%s" % (code, days))
    ContextInfo.live_orders_allowed = not issues
    log(
        "LIVE_PREFLIGHT",
        "ready=",
        ContextInfo.live_orders_allowed,
        "account=",
        masked_account(account_id) if account_id else "MISSING",
        "issues=",
        repr(issues),
    )
    if not ContextInfo.live_orders_allowed:
        log("LIVE_FAIL_CLOSED", "orders_will_not_be_sent")


def print_live_heartbeat(ContextInfo, now_text, time_text):
    if time_text not in HEARTBEAT_MINUTES:
        return
    position = ContextInfo.paper_position
    log(
        "HEARTBEAT",
        now_text,
        "orders_allowed=",
        getattr(ContextInfo, "live_orders_allowed", False),
        "position=",
        position["code"] if position is not None else "NONE",
        "cash=",
        round(ContextInfo.paper_cash, 2),
        "day_entries=",
        ContextInfo.paper_day_entries,
    )
    for code in UNDERLYINGS:
        state = ContextInfo.paper_states[code]
        spot = (
            state["day_bars"][-1]["close"]
            if state.get("day_bars")
            else None
        )
        info = daily_context(state, spot)
        option_bar_count = sum(
            len(values)
            for values in state.get("option_bars", {}).values()
        )
        log(
            "HEARTBEAT_DATA",
            code,
            "etf_bars=",
            len(state.get("day_bars", [])),
            "daily_days=",
            len(state.get("daily", [])),
            "daily_ready=",
            info.get("ready", False),
            "direction=",
            info.get("direction", "none"),
            "pool_call=",
            len(state["pool"].get("CALL", [])),
            "pool_put=",
            len(state["pool"].get("PUT", [])),
            "option_bars=",
            option_bar_count,
        )


def option_side_snapshot(state, option_type, spot):
    pool = state["pool"].get(option_type, [])
    if not pool or spot is None or spot <= 0:
        return {
            "priced": 0,
            "code": "",
            "close": None,
            "iv": None,
            "delta": None,
            "trend": False,
        }
    priced = []
    for item in pool:
        bars = state["option_bars"].get(item["code"], [])
        if bars and bars[-1].get("close", 0) > 0:
            priced.append((item, bars))
    if not priced:
        return {
            "priced": 0,
            "code": "",
            "close": None,
            "iv": None,
            "delta": None,
            "trend": False,
        }
    item, bars = min(
        priced,
        key=lambda pair: abs(pair[0]["strike"] - spot),
    )
    close_value = bars[-1]["close"]
    iv = implied_volatility(
        close_value,
        spot,
        item["strike"],
        item["rate"],
        item["dte"],
        option_type,
    )
    delta = bs_delta(
        spot,
        item["strike"],
        item["rate"],
        iv,
        item["dte"],
        option_type,
    )
    trend_ok, unused_strength = option_5m_trend(bars)
    return {
        "priced": len(priced),
        "code": item["code"],
        "close": close_value,
        "iv": iv,
        "delta": delta,
        "trend": trend_ok,
    }


def print_minute_monitor(ContextInfo, now_text, time_text):
    opening_window = "0930" <= time_text <= "0945"
    trading_session = (
        "0930" <= time_text <= "1130"
        or "1300" <= time_text <= "1500"
    )
    all_day_debug = LIVE_MINUTE_MONITOR_ALL_DAY and trading_session
    fallback_active = ContextInfo.paper_states[KCB_CODE].get(
        "fallback_monitor_active",
        False,
    )
    position_active = ContextInfo.paper_position is not None
    if not (
        all_day_debug
        or opening_window
        or fallback_active
        or position_active
    ):
        return

    reasons = []
    if all_day_debug:
        reasons.append("all_day_debug")
    if opening_window:
        reasons.append("opening_window")
    if fallback_active:
        reasons.append("fallback_triggered")
    if position_active:
        reasons.append("position_active")
    position = ContextInfo.paper_position
    try:
        is_current_live_bar = bool(ContextInfo.is_last_bar())
    except Exception:
        is_current_live_bar = None
    log(
        "MINUTE_MONITOR",
        now_text,
        "reason=",
        ",".join(reasons),
        "orders_allowed=",
        getattr(ContextInfo, "live_orders_allowed", False),
        "position=",
        position["code"] if position is not None else "NONE",
        "qty=",
        position["quantity"] if position is not None else 0,
        "current_live_bar=",
        is_current_live_bar,
    )

    for code in UNDERLYINGS:
        state = ContextInfo.paper_states[code]
        bars = state.get("day_bars", [])
        latest = bars[-1] if bars else {}
        first5 = [
            bar
            for bar in bars
            if "0930" <= bar.get("time", "") <= "0934"
        ]
        opening_high = (
            max(bar["high"] for bar in first5)
            if first5
            else None
        )
        opening_low = (
            min(bar["low"] for bar in first5)
            if first5
            else None
        )
        opening_amp = (
            (opening_high - opening_low) / opening_low
            if opening_low is not None and opening_low > 0
            else None
        )
        daily_info = daily_context(
            state,
            latest.get("close"),
        )
        log(
            "MINUTE_DATA",
            code,
            "time=",
            time_text,
            "close=",
            round(latest.get("close"), 6)
            if latest.get("close") is not None
            else None,
            "volume=",
            round(latest.get("volume"), 2)
            if latest.get("volume") is not None
            else None,
            "daily_direction=",
            daily_info.get("direction", "none"),
            "opening_bars=",
            len(first5),
            "opening_high=",
            round(opening_high, 6)
            if opening_high is not None
            else None,
            "opening_low=",
            round(opening_low, 6)
            if opening_low is not None
            else None,
            "opening_amp=",
            round(opening_amp, 6)
            if opening_amp is not None
            else None,
            "pool_call=",
            len(state["pool"].get("CALL", [])),
            "pool_put=",
            len(state["pool"].get("PUT", [])),
        )

        direction = daily_info.get("direction", "none")
        threshold = RANGE_THRESHOLD[code]
        range_ok = (
            opening_amp is not None
            and opening_amp >= threshold
        )
        broke = False
        if latest and opening_high is not None and opening_low is not None:
            if direction == "call":
                broke = latest.get("high", 0) > opening_high
            elif direction == "put":
                broke = latest.get("low", 0) < opening_low
        first5_mean_volume = mean(
            [bar["volume"] for bar in first5]
        )
        first5_max_volume = (
            max(bar["volume"] for bar in first5)
            if first5
            else None
        )
        volume_ratio = (
            latest.get("volume") / first5_mean_volume
            if latest.get("volume") is not None
            and first5_mean_volume is not None
            and first5_mean_volume > 0
            else None
        )
        volume_ok = (
            volume_ratio is not None
            and volume_ratio >= BREAKOUT_VOLUME_MULT[code]
            and first5_max_volume is not None
            and latest.get("volume", 0)
            >= first5_max_volume * BREAKOUT_VOLUME_MAX_MULT
        )
        if time_text > "0943":
            opening_status = "window_closed"
        elif direction not in ["call", "put"]:
            opening_status = "blocked_daily_direction"
        elif len(first5) < 5:
            opening_status = "collecting_first5"
        elif not range_ok:
            opening_status = "blocked_opening_range"
        elif not broke:
            opening_status = "waiting_breakout"
        elif not volume_ok:
            opening_status = "blocked_breakout_volume"
        else:
            opening_status = "breakout_candidate"
        log(
            "OPEN_CHECK",
            code,
            "status=",
            opening_status,
            "direction=",
            direction,
            "range_ok=",
            range_ok,
            "range_threshold=",
            threshold,
            "breakout=",
            broke,
            "volume_ratio=",
            round(volume_ratio, 4)
            if volume_ratio is not None
            else None,
            "volume_ok=",
            volume_ok,
            "signal=",
            state.get("opening_signal") is not None,
        )

        spot = latest.get("close")
        call_scan = option_side_snapshot(state, "CALL", spot)
        put_scan = option_side_snapshot(state, "PUT", spot)
        log(
            "OPTION_SCAN",
            code,
            "CALL",
            call_scan["priced"],
            call_scan["code"],
            "close=",
            round(call_scan["close"], 6)
            if call_scan["close"] is not None
            else None,
            "iv=",
            round(call_scan["iv"], 4)
            if call_scan["iv"] is not None
            else None,
            "delta=",
            round(call_scan["delta"], 4)
            if call_scan["delta"] is not None
            else None,
            "trend=",
            call_scan["trend"],
            "PUT",
            put_scan["priced"],
            put_scan["code"],
            "close=",
            round(put_scan["close"], 6)
            if put_scan["close"] is not None
            else None,
            "iv=",
            round(put_scan["iv"], 4)
            if put_scan["iv"] is not None
            else None,
            "delta=",
            round(put_scan["delta"], 4)
            if put_scan["delta"] is not None
            else None,
            "trend=",
            put_scan["trend"],
        )

    kcb_state = ContextInfo.paper_states[KCB_CODE]
    kcb_bars = kcb_state.get("day_bars", [])
    kcb_spot = kcb_bars[-1]["close"] if kcb_bars else None
    kcb_daily = daily_context(kcb_state, kcb_spot)
    if kcb_spot is not None and kcb_state.get("pool_ready"):
        live_kcb_iv_regime(ContextInfo, kcb_state, kcb_spot)
    bars15 = kcb_state.get("bars15", [])
    current15 = bars15[-1] if bars15 else None
    current15_today = (
        current15 is not None
        and str(current15.get("datetime", "")).startswith(
            str(kcb_state.get("current_date", 0))
        )
    )
    fallback_time_ok = (
        "0945" <= time_text <= "1415"
        and (time_text <= "1100" or time_text >= "1315")
    )
    fallback_volume_ratio = None
    fallback_breakout_call = False
    fallback_breakout_put = False
    fallback_close_pos = None
    if current15_today and len(bars15) >= 21:
        previous = bars15[:-1]
        prev5_volume = mean(
            [bar["volume"] for bar in previous[-5:]]
        )
        if prev5_volume is not None and prev5_volume > 0:
            fallback_volume_ratio = (
                current15["volume"] / prev5_volume
            )
        prev3_high = max(bar["high"] for bar in previous[-3:])
        prev3_low = min(bar["low"] for bar in previous[-3:])
        closes15 = [bar["close"] for bar in bars15]
        ema5_values = ema_series(closes15, 5)
        ema20_values = ema_series(closes15, 20)
        ema20_slope = ema20_values[-1] - ema20_values[-2]
        bar_range = current15["high"] - current15["low"]
        fallback_close_pos = (
            (current15["close"] - current15["low"]) / bar_range
            if bar_range > 0
            else 0.5
        )
        fallback_breakout_call = (
            current15["close"] > prev3_high
            and ema5_values[-1] > ema20_values[-1]
            and ema20_slope > 0
            and fallback_close_pos
            >= (0.75 if current15["time"] == "0945" else 0.65)
        )
        fallback_breakout_put = (
            current15["close"] < prev3_low
            and ema5_values[-1] < ema20_values[-1]
            and ema20_slope < 0
            and fallback_close_pos
            <= (0.25 if current15["time"] == "0945" else 0.35)
        )
    cluster_ok = kcb_daily.get("cluster", 0.0) >= 0.015
    daily_volume_ratio = kcb_daily.get("volume_ratio20")
    daily_volume_ok = (
        daily_volume_ratio is not None
        and daily_volume_ratio >= 0.65
    )
    fallback_volume_ok = (
        fallback_volume_ratio is not None
        and fallback_volume_ratio >= 2.0
    )
    iv_market = kcb_state.get("last_iv_market")
    iv_rank = kcb_state.get("last_iv_rank")
    iv_ok = (
        iv_market is not None
        and iv_market >= IV_MIN
        and iv_rank is not None
        and iv_rank < FALLBACK_IV_RANK_MAX
    )
    fallback_direction = kcb_daily.get("direction", "none")
    direction_signal = (
        "call"
        if fallback_breakout_call
        else "put"
        if fallback_breakout_put
        else "none"
    )
    if not fallback_time_ok:
        fallback_status = "outside_time_window"
    elif not current15_today:
        fallback_status = "waiting_today_15m_bar"
    elif not cluster_ok:
        fallback_status = "blocked_ma_cluster"
    elif not daily_volume_ok:
        fallback_status = "blocked_daily_volume"
    elif not fallback_volume_ok:
        fallback_status = "blocked_15m_volume"
    elif direction_signal == "none":
        fallback_status = "waiting_15m_breakout"
    elif direction_signal != fallback_direction:
        fallback_status = "blocked_direction_mismatch"
    elif not iv_ok:
        fallback_status = "blocked_iv_regime"
    else:
        fallback_status = "fallback_candidate"
    log(
        "FALLBACK_CHECK",
        KCB_CODE,
        "status=",
        fallback_status,
        "time_ok=",
        fallback_time_ok,
        "bars15=",
        len(bars15),
        "daily_direction=",
        fallback_direction,
        "cluster=",
        round(kcb_daily.get("cluster"), 6)
        if kcb_daily.get("cluster") is not None
        else None,
        "cluster_ok=",
        cluster_ok,
        "daily_volume_ratio=",
        round(daily_volume_ratio, 4)
        if daily_volume_ratio is not None
        else None,
        "volume15_ratio=",
        round(fallback_volume_ratio, 4)
        if fallback_volume_ratio is not None
        else None,
        "direction_signal=",
        direction_signal,
        "close_pos=",
        round(fallback_close_pos, 4)
        if fallback_close_pos is not None
        else None,
        "market_iv_proxy=",
        round(iv_market, 4) if iv_market is not None else None,
        "iv_rank_proxy=",
        round(iv_rank, 4) if iv_rank is not None else None,
        "iv_ok=",
        iv_ok,
        "pending=",
        kcb_state.get("fallback_pending") is not None,
    )

    position = ContextInfo.paper_position
    if position is None:
        log(
            "POSITION_MARK",
            "NONE",
            "cash=",
            round(ContextInfo.paper_cash, 2),
            "equity=",
            round(paper_equity(ContextInfo), 2),
            "closed_trades=",
            ContextInfo.paper_trade_count,
        )
    else:
        position_state = ContextInfo.paper_states[
            position["underlying"]
        ]
        position_bars = position_state["option_bars"].get(
            position["code"],
            [],
        )
        mark = (
            position_bars[-1]["close"]
            if position_bars
            else position["avg_fill_price"]
        )
        gross_pnl = (
            mark - position["avg_fill_price"]
        ) * position["quantity"] * position["multiplier"]
        return_pct = (
            mark / position["avg_fill_price"] - 1.0
            if position["avg_fill_price"] > 0
            else 0.0
        )
        log(
            "POSITION_MARK",
            position["code"],
            "path=",
            position["path"],
            "qty=",
            position["quantity"],
            "avg_fill=",
            round(position["avg_fill_price"], 6),
            "mark=",
            round(mark, 6),
            "gross_pnl=",
            round(gross_pnl, 2),
            "return_pct=",
            round(return_pct, 6),
            "equity=",
            round(paper_equity(ContextInfo), 2),
        )


def runtime_state_fields():
    return [
        "paper_states",
        "paper_cash",
        "paper_position",
        "paper_trade_count",
        "paper_day_entries",
        "paper_current_date",
        "paper_day_locked",
        "paper_opening_evaluated",
        "paper_smoke_executed",
        "paper_parity_end_logged",
        "paper_last_bar_text",
        "paper_smoke_close_sent",
        "live_future_bar_logged",
        "live_history_skip_logged",
        "live_current_bar_logged",
        "live_account_id",
        "live_orders_allowed",
    ]


def save_runtime_context(ContextInfo):
    global RUNTIME_CONTEXT_STATE
    state = {}
    for name in runtime_state_fields():
        state[name] = getattr(ContextInfo, name, None)
    RUNTIME_CONTEXT_STATE = state


def load_runtime_context(ContextInfo):
    if RUNTIME_CONTEXT_STATE is None:
        return
    for name in runtime_state_fields():
        setattr(
            ContextInfo,
            name,
            RUNTIME_CONTEXT_STATE.get(name),
        )


def init(ContextInfo):
    global RUNTIME_LAST_PROCESSED_BAR
    global RUNTIME_ORDER_KEYS
    global RUNTIME_CONTEXT_STATE
    RUNTIME_LAST_PROCESSED_BAR = ""
    RUNTIME_ORDER_KEYS = set()
    RUNTIME_CONTEXT_STATE = None
    ContextInfo.paper_states = dict(
        (code, new_underlying_state(code))
        for code in UNDERLYINGS
    )
    ContextInfo.paper_cash = INITIAL_CASH
    ContextInfo.paper_position = None
    ContextInfo.paper_trade_count = 0
    ContextInfo.paper_day_entries = 0
    ContextInfo.paper_current_date = 0
    ContextInfo.paper_day_locked = False
    ContextInfo.paper_opening_evaluated = False
    ContextInfo.paper_smoke_executed = False
    ContextInfo.paper_smoke_close_sent = False
    ContextInfo.paper_parity_end_logged = False
    ContextInfo.live_future_bar_logged = ""
    ContextInfo.live_history_skip_logged = False
    ContextInfo.live_current_bar_logged = False
    ContextInfo.paper_last_bar_text = ""
    ContextInfo.set_universe(UNDERLYINGS)
    for code in UNDERLYINGS:
        preload_daily_data(ContextInfo, ContextInfo.paper_states[code])
        log(
            "BAR15_SEED_LOADED",
            code,
            "bars=",
            len(ContextInfo.paper_states[code]["bars15"]),
        )
    run_live_preflight(ContextInfo)
    log("BUILD_ID", BUILD_ID)
    log("INIT", "period=", getattr(ContextInfo, "period", None))
    log(
        "MODE",
        "QMT_NATIVE_SIM"
        if QMT_NATIVE_ORDER_ENABLED
        else "SHADOW_PAPER_NO_PASSORDER",
    )
    log(
        "QMT_NATIVE_ORDER_ENABLED",
        QMT_NATIVE_ORDER_ENABLED,
        "account_configured=",
        bool(ContextInfo.live_account_id),
    )
    log(
        "QMT_PASSORDER_STYLE",
        QMT_PASSORDER_STYLE,
        "code_with_suffix=",
        QMT_ORDER_CODE_WITH_SUFFIX,
        "strategy=",
        QMT_STRATEGY_NAME,
        "quick=",
        QMT_QUICK_TRADE,
    )
    log("INITIAL_CASH", INITIAL_CASH)
    log("PAPER_START_DATE", PAPER_START_DATE)
    log(
        "EXECUTION_SMOKE_TEST",
        EXECUTION_SMOKE_TEST,
        "date=",
        SMOKE_TEST_DATE,
        "time=",
        SMOKE_TEST_TIME,
    )
    if EXECUTION_SMOKE_TEST:
        log(
            "SMOKE_TEST_MODE",
            "qmt_passorder_channel",
            "allow_orders=",
            SMOKE_TEST_ALLOW_ORDERS,
            "underlying=",
            SMOKE_TEST_UNDERLYING,
            "direction=",
            SMOKE_TEST_DIRECTION,
            "auto_close=",
            SMOKE_TEST_AUTO_CLOSE,
            "close_after_minutes=",
            SMOKE_TEST_CLOSE_AFTER_MINUTES,
        )
    log("REQUIRES_1M_CHART")
    log("DAILY_WARMUP", "embedded_through_20260702")
    log(
        "FIRST_DAY_LIMITS",
        "max_contracts=",
        LIVE_MAX_CONTRACTS,
        "max_entries=",
        LIVE_MAX_TRADES_PER_DAY,
    )
    log("LIVE_ADAPTATION", "dual opening decisions execute at 09:43")
    log("CYB_FALLBACK", "disabled")
    log("KCB_FALLBACK", "enabled next-minute fill")
    log("LIVE_IV_GATE", "atm_option_median_proxy_fail_closed")
    log("ORDER_STATE", "shadow_fill_assumption_verify_callbacks")
    if FORCE_TEST_DIRECTION:
        log("WARNING_FORCE_TEST_DIRECTION", FORCE_TEST_DIRECTION)
    save_runtime_context(ContextInfo)


def handlebar(ContextInfo):
    global RUNTIME_LAST_PROCESSED_BAR
    load_runtime_context(ContextInfo)
    if LIVE_CURRENT_BAR_ONLY:
        try:
            if not bool(ContextInfo.is_last_bar()):
                return
        except Exception:
            pass
    now_text, current_date, time_text = current_datetime(ContextInfo)
    if current_date <= 0 or len(time_text) != 4:
        return
    if live_bar_is_in_future(current_date, time_text):
        return
    if (
        LIVE_FAST_SKIP_BEFORE_START
        and not HISTORICAL_PARITY_MODE
        and current_date < PAPER_START_DATE
    ):
        if not ContextInfo.live_history_skip_logged:
            ContextInfo.live_history_skip_logged = True
            log(
                "LIVE_FAST_FORWARD",
                "skip_before=",
                PAPER_START_DATE,
                "first_skipped_bar=",
                now_text,
            )
        return
    if now_text == RUNTIME_LAST_PROCESSED_BAR:
        return
    RUNTIME_LAST_PROCESSED_BAR = now_text
    if now_text == ContextInfo.paper_last_bar_text:
        return
    ContextInfo.paper_last_bar_text = now_text
    if not ContextInfo.live_current_bar_logged:
        ContextInfo.live_current_bar_logged = True
        log("LIVE_CURRENT_BAR_REACHED", now_text)
    if (
        HISTORICAL_PARITY_MODE
        and current_date > HISTORICAL_PARITY_END_DATE
    ):
        if not ContextInfo.paper_parity_end_logged:
            ContextInfo.paper_parity_end_logged = True
            log(
                "PARITY_RANGE_COMPLETE",
                "last_date=",
                HISTORICAL_PARITY_END_DATE,
                "strategy_stopped_before=",
                current_date,
            )
        return

    if current_date != ContextInfo.paper_current_date:
        ContextInfo.paper_current_date = current_date
        ContextInfo.paper_day_locked = False
        ContextInfo.paper_day_entries = 0
        ContextInfo.paper_opening_evaluated = False
        for code in UNDERLYINGS:
            reset_for_new_day(
                ContextInfo.paper_states[code],
                current_date,
            )
        if current_date >= PAPER_START_DATE:
            log(
                "NEW_DAY",
                current_date,
                "cash=",
                round(ContextInfo.paper_cash, 2),
            )
        else:
            completed_days = len(
                ContextInfo.paper_states[KCB_CODE]["daily"]
            )
            if completed_days in [1, 5, 10, 20] or (
                completed_days > 20 and completed_days % 40 == 0
            ):
                log(
                    "WARMUP_PROGRESS",
                    current_date,
                    "completed_days=",
                    completed_days,
                )

    completed_15m = {}
    for code in UNDERLYINGS:
        state = ContextInfo.paper_states[code]
        bar = read_bar(ContextInfo, code)
        if bar is None:
            log("ETF_BAR_MISSING", now_text, code)
            continue
        append_etf_bar(state, now_text, time_text, bar)
        completed_15m[code] = append_15m_if_complete(
            state,
            time_text,
        )
        if (
            current_date >= PAPER_START_DATE
            and not state["pool_ready"]
            and time_text >= "0930"
        ):
            build_option_pool(
                ContextInfo,
                state,
                current_date,
                bar["close"],
            )
        if current_date >= PAPER_START_DATE and state["pool_ready"]:
            update_option_bars(
                ContextInfo,
                state,
                now_text,
                time_text,
            )

    if current_date < PAPER_START_DATE:
        return

    if time_text == "0930":
        for code in UNDERLYINGS:
            state = ContextInfo.paper_states[code]
            info = daily_context(
                state,
                state["day_bars"][-1]["close"]
                if state["day_bars"]
                else None,
            )
            log(
                "DAILY_STATE",
                code,
                "completed_days=",
                len(state["daily"]),
                "ready=",
                info.get("ready", False),
                "direction=",
                info.get("direction", "none"),
            )

    if time_text == "0943":
        evaluate_dual_opening(ContextInfo, now_text)

    if time_text == "0945":
        confirm_opening_at_0945(ContextInfo, now_text)

    execute_smoke_test(
        ContextInfo,
        current_date,
        now_text,
        time_text,
    )

    execute_pending_fallback(ContextInfo, now_text, time_text)

    if completed_15m.get(KCB_CODE):
        schedule_kcb_fallback(ContextInfo, now_text)

    execute_smoke_auto_close(ContextInfo, now_text)

    manage_position(ContextInfo, now_text, time_text)

    print_minute_monitor(ContextInfo, now_text, time_text)
    print_live_heartbeat(ContextInfo, now_text, time_text)

    if time_text == "1500":
        log(
            "DAY_END",
            current_date,
            "cash=",
            round(ContextInfo.paper_cash, 2),
            "equity=",
            round(paper_equity(ContextInfo), 2),
            "trades=",
            ContextInfo.paper_trade_count,
        )
    save_runtime_context(ContextInfo)
