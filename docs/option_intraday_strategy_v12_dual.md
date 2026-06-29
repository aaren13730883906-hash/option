# 科创 50 + 创业板 ETF 期权双标策略 v1.2

## 组合规则

- 科创标的为 `588000.SH`，期权为上交所 ETF 期权。
- 创业板标的为 `159915.SZ`，期权为深交所创业板 ETF 期权。
- 两个标的分别使用 v1.1 的日线方向、早盘开盘区间和强 15 分钟备用规则。
- 两个标的分别选择合约和执行止盈、止损，不使用组合账户盈亏触发单笔退出。
- 同一交易日只有一个标的成交时，使用该标的原目标仓位。
- 回测从 `2025-07-04` 开始。
- 创业板早盘开盘区间振幅门槛为 `0.25%`，突破放量门槛为 `1.25` 倍。
- 科创板仍使用 `0.30%` 开盘区间振幅和 `1.30` 倍突破放量门槛。
- 同一交易日两个标的都有交易时，只保留标准化开盘强度更高的标的，不允许交易日期重合。
- 标准化开盘强度为 `(实际振幅 / 振幅门槛) × (实际放量倍数 / 放量门槛)`。

## 数据口径

- 回测目标区间：`2025-07-04` 至 `2026-05-25`。
- ETF 1 分钟数据来自本地按日 ZIP，ETF 5 分钟和日线来自本地 SQLite。
- 创业板历史合约数字编码、合约代码和 Greeks 来自深交所历史合约风险指标。
- 创业板期权日线 OHLCV 和 1 分钟行情来自 iFinD QuantAPI。
- 创业板市场 IV 使用创业板期权 QVIX 收盘值，`IV Rank` 使用 252 日滚动区间。
- 深交所风险指标不提供逐合约 IV，创业板候选表暂以当日 QVIX 作为合约 IV 代理，用于 `20%-70%` 过滤和高 IV 仓位折算。

## 当前回测结果

初始资金 `100,000` 元：

| 指标 | 结果 |
|---|---:|
| 期末资金 | 303,514.22 元 |
| 净利润 | 203,514.22 元 |
| 总收益率 | 203.51% |
| 最大回撤 | 8.45% |
| 总交易数 | 17 |
| 科创交易数 | 12 |
| 创业板交易数 | 5 |
| 净胜率 | 88.24% |
| 已消除的重合日期 | 2 |

原始信号重合、经择强后只保留科创的日期为：

- `2025-08-22`
- `2026-04-22`

## 数据问题与限制

- `2025-07-04` 至 `2026-05-25` 的 ETF 1 分钟数据完整，没有缺失交易日。
- 科创候选期权的所需分钟缓存完整，回测统计中的缺失缓存数为零。
- 创业板所需分钟缓存完整；最早实际需要缓存的日期是 `2025-07-23`。
- `2025-07-21` 有创业板 ETF 信号，但当月/下月没有 DTE 10–35 的合约，所以没有期权缓存和交易。
- 科创在 `2025-09-16`、`2026-03-16`、`2026-04-20` 出现早盘信号，但当月/下月同样没有 DTE 10–35 的合约。
- 深交所风险指标不含逐合约 IV，创业板暂以当日 QVIX 作为 IV 代理。该字段会影响 IV 过滤、仓位折算和候选评分，是当前最主要的数据口径限制。
- 创业板候选日表只覆盖 ETF 预筛出的信号日期，不是完整的逐日全市场期权数据库。
- iFinD 每份分钟文件都包含一行 `13:00` 的全空占位记录。实际交易时段价格覆盖完整、无重复时间戳；回测的重采样和成交逻辑会忽略该空行。

## 复现

```bash
PYTHONPATH=.deps python3 scripts/build_cyb_option_signal_data.py

PYTHONPATH=.deps python3 scripts/backtest_v10_opening_range_b.py \
  --days 325 \
  --underlying 159915 \
  --daily-csv data/cyb_option_signal_daily.csv \
  --market-iv-csv data/cyb_market_iv_daily.csv \
  --etf-daily-csv data/etf_daily_159915.csv \
  --range-threshold 0.0025 \
  --breakout-vol-mult 1.25 \
  --daily-volume-tiered \
  --fetch-missing \
  --output research/backtest_v12_159915_opening_trades.csv \
  --summary research/backtest_v12_159915_opening_summary.csv

PYTHONPATH=.deps python3 scripts/backtest_v11_opening_plus_strong15m.py --days 325
PYTHONPATH=.deps python3 scripts/backtest_v12_dual_underlying.py
```
