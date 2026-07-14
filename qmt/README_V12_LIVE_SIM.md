# QMT v1.2 live simulated-account checklist

Use `qmt_v12_dual_live_sim.py`. Do not use the historical parity file for
live simulated trading.

## Before enabling

1. Fill `QMT_ACCOUNT_ID` locally with the simulated option account ID.
2. Keep `QMT_NATIVE_ORDER_ENABLED = True`.
3. Keep `HISTORICAL_PARITY_MODE = False`.
4. Keep `EXECUTION_SMOKE_TEST = False`.
5. Keep `FORCE_TEST_DIRECTION = ""`.
6. QMT strategy type: `OPTION`.
7. Account type: stock option account.
8. Main chart: `588000.SH` (or `588000` if the UI accepts digits only).
9. Period: 1 minute.

For the first session, keep:

- `LIVE_MAX_CONTRACTS = 1`
- `LIVE_MAX_TRADES_PER_DAY = 1`

## Logs required before orders are allowed

The startup log must contain:

```text
[V12_PAPER] BUILD_ID V12_LIVE_SIM_20260703_R12
[V12_PAPER] LIVE_PREFLIGHT ready= True
[V12_PAPER] MODE QMT_NATIVE_SIM
[V12_PAPER] PAPER_START_DATE 20260703
```

If it contains `LIVE_FAIL_CLOSED`, the strategy remains observable but will
not send orders.

## Logs during the session

- `HEARTBEAT`: strategy event loop is alive.
- `MINUTE_MONITOR` / `MINUTE_DATA`: printed every trading minute.
- `OPEN_CHECK`: opening-rule pass/block status for both underlyings.
- `OPTION_SCAN`: current tracked CALL/PUT prices, IV, delta, and trend.
- `FALLBACK_CHECK`: KCB fallback-rule pass/block status.
- `POSITION_MARK`: current shadow mark, return, PnL, and equity.
- `HEARTBEAT_DATA`: ETF bars, daily warmup, option pool, and option bars.
- `POOL_READY`: current option directory and details are available.
- `NO_DUAL_OPENING_SIGNAL`: the strategy ran normally but found no opening.
- `OPENING_SIGNAL` / `FALLBACK_SIGNAL`: a natural strategy signal exists.
- `QMT_ORDER_SENT`: `passorder` was called.
- `ORDER_CALLBACK`: QMT returned an order-state update.
- `DEAL_CALLBACK`: QMT returned an actual fill.
- `QMT_ORDER_ERROR` or `QMT_ORDER_BLOCKED`: order path failed or was blocked.

`QMT_ORDER_SENT` without `DEAL_CALLBACK` is not proof of a fill.

## Automatic start

The strategy can be enabled after market close. Keep QMT logged in and the
strategy running. If QMT may restart before the open, enable terminal
auto-run and use an account-login delay such as 20 seconds. Verify the
startup preflight again after every restart.

The strategy does not promise a trade every day. A heartbeat plus
`NO_DUAL_OPENING_SIGNAL` is a valid no-trade result.
