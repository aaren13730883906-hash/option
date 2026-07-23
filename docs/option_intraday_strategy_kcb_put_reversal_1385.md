# 科创 50 ETF 期权日内策略：主策略 + Put 反转增强 + 退出优化版

本文档只记录当前 `1385.10%` 回测版本的可复现口径，不混入历史尝试。

## 1. 回测结果

| 指标 | 结果 |
|---|---:|
| 标的 | 科创 50 ETF，`588000` |
| 初始资金 | 100,000.00 元 |
| 期末资金 | 1,485,100.36 元 |
| 总收益率 | 1385.10% |
| 净利润 | 1,385,100.36 元 |
| 实际成交交易数 | 75 |
| 胜率 | 77.33% |
| 最大回撤 | 8.68% |
| 容量跳过 | 7 |
| 最大 15 分钟成交量占比 | 4.88% |

该版本建立在两个已验证模块之上：

1. 主策略基准：`753.37%`；
2. 主策略 + `09:45 Put 反转增强保守版` 基准：`1201.63%`。

在 `1201.63%` 基准上加入两个退出优化后，结果提升至 `1385.10%`。

## 2. 策略结构

策略只交易科创 50 ETF 期权，分三条入场路径：

1. 早盘主策略；
2. 强 15 分钟备用策略；
3. `09:45 Put 反转增强保守版`。

同一天若主策略已有交易，则 `09:45 Put 反转增强` 不再执行。

所有持仓均为日内交易，不隔夜。若盘中没有触发止盈、止损或提前退出，尾盘 `14:55` 强制平仓，退出原因记为 `eod`。

## 3. 主策略基准规则

主策略使用 `research/full_confirm_tp2_3p0_*` 这一组结果文件复现。

核心口径：

- 标的：`588000`；
- DTE：严格 `10–35`；
- 早盘 Call 开盘区间振幅门槛：`0.30%`；
- 早盘 Put 开盘区间振幅门槛：`0.60%`；
- 备用策略 15 分钟放量倍数：`1.8`；
- 备用策略要求当日累计量能进度比 `>=1.15`；
- 启用高 IV 暴跌 Put：IV `70%–90%`，仓位上限 `25%`；
- 启用低聚拢度暴跌 Put 豁免：Put-only，15 分钟局部量比 `>=3.0`，仓位上限 `25%`；
- 启用备用 Call 期权动量确认：最近 `8` 分钟窗口，最近 `3` 分钟走弱、回撤 `8%`、量能衰减 `70%` 任一成立则过滤备用 Call；
- 普通信号 TP2 提高到 `3.0`。

## 4. 09:45 Put 反转增强保守版

该模块只在主策略当天没有交易时触发。

入场条件：

- 触发时间：`09:45`；
- 方向：只做 Put；
- ETF 相对当日开盘涨幅 `>=0.50%`；
- 候选 Put 合约 `abs(delta)` 在 `0.45–0.60`；
- 期权价格 `>=0.03`；
- `09:45` 15 分钟成交量 `>=1000` 张；
- 在满足条件的候选中，按 `09:45` 15 分钟成交量排序，选择成交量最大的合约。

执行约束：

- 目标权利金仓位：`20%`；
- 买入价：中价 + `0.0003`；
- 卖出价：中价 - `0.0003`；
- 计划买入张数不得超过该合约 `09:45` 15 分钟成交量的 `5%`；
- 超过 `5%` 时跳过该交易。

## 5. 新增退出优化

### 5.1 Put 反转强趋势快速止盈

该规则只作用于 `09:45 Put 反转增强`。

逻辑：如果 ETF 仍处于明显强上涨趋势，Put 反转只视为短线回调机会，不能恋战。

规则：

- `09:45` ETF 价格 `>=` 前一交易日 MA20 × `1.03`；
- 入场后期权浮盈达到 `+10%`；
- 立即全部止盈离场；
- 退出原因记为 `trend_quick_tp_10%`。

### 5.2 10:30 无跟随提前退出

该规则作用于全部 Put 日内持仓，包括：

- `09:45 Put 反转增强`；
- 早盘 Put；
- 15 分钟备用 Put。

逻辑：Put 入场后如果到 `10:30` 仍没有形成有效浮盈，并且价格已经走弱，说明下跌跟随失败，应提前退出，而不是继续等尾盘或软止损。

规则：

- 到 `10:30` 前，期权最高浮盈 `< +5%`；
- 且 `10:30` 附近期权收盘收益 `<= -3%`；
- 则在 `10:30` 附近提前全部退出；
- 退出原因记为 `early_no_follow_10:30_hi5%_cl-3%`。

## 6. 退出原因分布

`1385.10%` 版本的实际成交退出原因：

| 退出原因 | 笔数 |
|---|---:|
| eod | 30 |
| trend_quick_tp_10% | 15 |
| tp1_eod | 12 |
| soft_stop | 8 |
| early_no_follow_10:30_hi5%_cl-3% | 5 |
| trail_20% | 4 |
| trail_35% | 1 |

## 7. 复现文件

主策略基准：

- `research/full_confirm_tp2_3p0_summary.csv`
- `research/full_confirm_tp2_3p0_trades.csv`
- `research/full_confirm_tp2_3p0_capital.csv`

Put 反转增强基准：

- `research/put_reversal_0945_conservative20_cap5_etfup0.005_delta0.45_0.6_pos0.2_normal_rankvolume15_minp0.03_minv1000_slip0.0003_capshare0.05_combined_summary.csv`
- `research/put_reversal_0945_conservative20_cap5_etfup0.005_delta0.45_0.6_pos0.2_normal_rankvolume15_minp0.03_minv1000_slip0.0003_capshare0.05_combined_trades.csv`
- `research/put_reversal_0945_conservative20_cap5_etfup0.005_delta0.45_0.6_pos0.2_normal_rankvolume15_minp0.03_minv1000_slip0.0003_capshare0.05_combined_capital.csv`

退出优化测试：

- `research/put_reversal_exit_wick_summary.csv`
- `research/soft_stop_early_exit_summary.csv`
- `research/soft_stop_early_exit_combo_trendtp10_nofollow1030_capital.csv`
- `research/soft_stop_early_exit_5trade_review.csv`

代码：

- `scripts/backtest_v11_opening_plus_strong15m.py`
- `scripts/backtest_kcb_put_reversal_0945.py`
- `scripts/test_put_reversal_exit_wick_filters.py`
- `scripts/test_soft_stop_early_exit_signals.py`

## 8. 注意事项

- `10:30 无跟随提前退出` 当前测试口径是全部 Put 持仓，不是只限 Put 反转增强。
- `Put 反转强趋势快速止盈` 当前只限 `09:45 Put 反转增强`。
- 当前成交量容量限制为 15 分钟成交量 `5%`，模拟交易前不能随意放大。
- 该版本是科创-only，不包含创业板。
