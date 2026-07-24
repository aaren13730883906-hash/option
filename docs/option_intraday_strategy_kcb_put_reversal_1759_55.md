# 科创 50 ETF 期权日内策略：1759.55% 版本

本文档只记录当前可复现的 `1759.55%` 策略口径，不混入历史实验过程。目标是：只看本文，即可知道这版收益由哪些规则、代码和结果文件产生。

## 1. 回测结果

| 指标 | 结果 |
|---|---:|
| 标的 | 科创 50 ETF，`588000` |
| 初始资金 | 100,000.00 元 |
| 期末资金 | 1,859,553.40 元 |
| 总收益率 | 1759.55% |
| 净利润 | 1,759,553.40 元 |
| 总成交交易数 | 73 |
| 容量跳过 | 13 |
| 胜率 | 80.82% |
| 最大回撤 | 8.69% |
| 主策略基准交易 | 22 |
| Put 反转增强成交 | 51 |
| Put 反转增强净利润 | 484,097.94 元 |
| 最大 15 分钟成交量占比 | 4.88% |
| 回测数据延长至 | 2026-07-23 |
| 最后一笔成交日期 | 2026-07-22 |

本版本是在 `753.37%` 科创-only 主策略基础上，叠加 `09:45 Put 反转增强：容量约束 + 动量选约 + 强势趋势快止盈 + 10:30 无跟随退出 + Put 反转尾盘 14:45 平仓` 得到。

## 2. 策略结构

策略只交易科创 50 ETF 期权，分为三条入场路径：

1. 早盘主策略；
2. 强 15 分钟备用策略；
3. `09:45 Put 反转增强`。

同一天若主策略已经有交易，则 Put 反转增强不再执行。所有交易都是日内交易，不隔夜。

## 3. 主策略基准口径

主策略基准沿用 `753.37%` 科创-only 版本。

关键规则：

- 标的：`588000` 科创 50 ETF。
- DTE：严格 `10–35`。
- 常规 IV：`20%–70%`。
- Delta：优先选择接近 `0.50` 绝对值的合约。
- 早盘 Call 开盘区间振幅门槛：`0.30%`。
- 早盘 Put 开盘区间振幅门槛：`0.60%`。
- 强 15 分钟备用策略量比：`1.8`。
- 高 IV 暴跌 Put 允许 IV 到 `90%`，单笔仓位上限 `25%`。
- 低聚拢度暴跌 Put 豁免：只允许 Put，局部 15 分钟量比 `>=3.0`，仓位上限 `25%`。
- 备用 Call 入场前做期权动量确认：
  - 最近 8 分钟高点回撤不得超过 `8%`；
  - 最近 3 分钟不得连续走弱；
  - 最近 3 分钟量能不得低于前段均量的 `70%`。
- 普通信号 TP2 提升到 `3.00` 倍。

主策略基准复现结果：

| 指标 | 结果 |
|---|---:|
| 期末资金 | 853,372.52 元 |
| 总收益率 | 753.37% |
| 交易数 | 22 |
| 胜率 | 86.36% |
| 最大回撤 | 8.06% |

## 4. 09:45 Put 反转增强

该模块寻找早盘冲高后回落的 Put 反转机会，不替代主策略，只在主策略当天没有成交时作为增强路径。

### 4.1 触发条件

- 时间：只看 `09:45` 已完成的 15 分钟窗口；
- 方向：只做 Put；
- ETF 条件：`09:45` 时 ETF 相对当日开盘涨幅 `>=0.50%`；
- 合约价格：`09:45` 期权价格 `>=0.03`；
- 合约成交量：`09:45` 15 分钟成交量 `>=1000` 张；
- Delta：`abs(delta)` 在 `0.45–0.60`；
- 仓位：目标权利金仓位 `20%`；
- 滑点：买入价加 `0.0003`，卖出价减 `0.0003`；
- 容量限制：计划买入张数不得超过该合约 `09:45` 15 分钟成交量的 `5%`。

### 4.2 动量选约

在满足基础过滤的候选 Put 合约里，按 `09:45` 15 分钟合约自身动量排序：

```text
momentum15 = option_09:45_close / option_09:45_open - 1
```

优先选择 `momentum15` 最大的合约。

如果第一名合约按当前资金和 `20%` 仓位计算后，计划买入张数超过该合约 `09:45` 成交量的 `5%`，则自动顺延到下一名动量候选；如果所有候选都超过容量限制，则当天跳过，记为 `capacity`。

### 4.3 强势趋势快止盈

当 Put 反转入场时，如果 ETF 处于明显强势趋势，则把这笔 Put 反转视作“回调交易”，不再贪尾盘。

条件：

- `09:45` ETF 收盘价 >= 前一日 MA20 × `1.03`。

执行：

- 若入场后期权价格达到入场价 × `1.10`，立即全部止盈；
- 平仓原因记为 `trend_quick_tp_10%`。

### 4.4 10:30 无跟随退出

该规则只作用于 Put 方向。

条件：

- 入场后至 `10:30` 前，期权最高价未达到入场价 × `1.05`；
- 且 `10:30` 附近期权收盘价 <= 入场价 × `0.97`。

执行：

- 在 `10:30` 附近提前平仓；
- 平仓原因记为 `early_no_follow_10:30_hi5%_cl-3%`。

### 4.5 Put 反转尾盘平仓时间

Put 反转增强若最终仍是尾盘退出，则不等到 `14:55`，而是在 `14:45` 平仓，降低最后 10 分钟流动性风险。

对应平仓原因：

- `eod_1445_putrev`；
- `tp1_eod_1445_putrev`。

## 5. 2026 年 7 月扩展结果

本次把数据补充到 `2026-07-23` 后，历史 1640.73% 基准不变，并新增 4 笔成交、1 笔容量跳过。

| 日期 | 合约 | 结果 | 净利润 |
|---|---|---|---:|
| 2026-07-01 | 10011945 | `trend_quick_tp_10%` | 32,550.00 |
| 2026-07-03 | 10011774 | `trend_quick_tp_10%` | 32,785.20 |
| 2026-07-07 | 10011774 | `trend_quick_tp_10%` | 32,599.60 |
| 2026-07-10 | 10011816 | `capacity` 跳过 | 0.00 |
| 2026-07-22 | 10011916 | `eod_1445_putrev` | 20,884.00 |

新增成交合计净利润：`118,818.80` 元。

## 6. 复现文件

主策略基准到 2026-07-23：

- `research/full_confirm_tp2_3p0_to_20260723_summary.csv`
- `research/full_confirm_tp2_3p0_to_20260723_trades.csv`
- `research/full_confirm_tp2_3p0_to_20260723_capital.csv`

1759.55% 版本：

- `research/putrev_selection_capacity_aware_momentum_to_20260723_summary.csv`
- `research/putrev_selection_capacity_aware_momentum_to_20260723_trades.csv`
- `research/putrev_selection_capacity_aware_momentum_to_20260723_capital.csv`

相关代码：

- `scripts/backtest_v11_opening_plus_strong15m.py`
- `scripts/backtest_strategy_1640_capacity_momentum_extend.py`
- `scripts/backtest_kcb_put_flow_0945.py`
- `scripts/analyze_kcb_option_flow_signals.py`
- `scripts/fetch_kcb_july_candidate_option_1m.py`

## 7. 复现命令

先复现主策略基准：

```bash
PYTHONPATH=scripts python3 scripts/backtest_v11_opening_plus_strong15m.py \
  --days 753 \
  --underlying 588000 \
  --put-range-threshold 0.006 \
  --late-trend-acceleration \
  --late-strong-volume-mult 1.8 \
  --high-iv-crash-put \
  --high-iv-put-min 0.70 \
  --high-iv-put-max 0.90 \
  --high-iv-put-position-cap 0.25 \
  --cluster-acceleration-exemption \
  --cluster-exemption-direction put \
  --cluster-exemption-volume-mult 3.0 \
  --cluster-exemption-position-cap 0.25 \
  --fallback-option-momentum-confirm \
  --fallback-option-momentum-direction call \
  --fallback-option-lookback-minutes 8 \
  --fallback-option-recent-minutes 3 \
  --fallback-option-pullback-max 0.08 \
  --fallback-option-volume-fade-ratio 0.70 \
  --normal-tp2-factor 3.0 \
  --output research/full_confirm_tp2_3p0_to_20260723_trades.csv \
  --capital-output research/full_confirm_tp2_3p0_to_20260723_capital.csv \
  --summary research/full_confirm_tp2_3p0_to_20260723_summary.csv
```

再复现 1759.55% 扩展版：

```bash
PYTHONPATH=scripts python3 scripts/backtest_strategy_1640_capacity_momentum_extend.py
```

## 8. 注意事项

- 本版本是科创-only，不包含创业板。
- `1759.55%` 是在本地历史数据与当前滑点/容量假设下的回测结果，不代表实盘可直接放大仓位。
- Put 反转增强依赖成交量占比控制，必须保留 `5%` 容量限制。
- `2026-07-10` 的 Put 反转信号因计划张数超过 15 分钟成交量 `5%` 被跳过，没有计入成交收益。
