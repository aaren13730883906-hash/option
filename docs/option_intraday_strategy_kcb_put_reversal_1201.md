# 科创 50 ETF 期权日内策略：主策略 + 09:45 Put 反转增强保守版

本文档只记录当前可复现的最终策略口径，不包含历史实验过程。目标是：只看本文，即可理解 `1201.63%` 回测结果由哪些规则产生。

## 1. 回测结果

| 指标 | 结果 |
|---|---:|
| 标的 | 科创 50 ETF，`588000` |
| 初始资金 | 100,000.00 元 |
| 期末资金 | 1,301,625.36 元 |
| 总收益率 | 1201.63% |
| 净利润 | 1,201,625.36 元 |
| 总交易数 | 76 |
| 胜率 | 69.74% |
| 最大回撤 | 9.85% |
| 主策略交易 | 22 |
| Put 反转增强实际成交 | 54 |
| Put 反转增强容量跳过 | 6 |
| Put 反转增强最大成交量占比 | 4.94% |

主策略基准为 `753.37%`，叠加 `09:45 Put 反转增强保守版` 后为 `1201.63%`。

## 2. 策略结构

策略只交易科创 50 ETF 期权，分为三条入场路径：

1. 早盘主策略；
2. 强 15 分钟备用策略；
3. `09:45 Put 反转增强保守版`。

同一天若主策略已经有交易，则 Put 反转增强信号不再执行。

所有交易都是日内交易，不隔夜。若盘中没有触发止盈或止损，尾盘 `14:55` 强制平仓，退出原因记为 `eod`。

## 3. 基础合约过滤

所有路径共用以下基础过滤：

- 标的：`588000` 科创 50 ETF。
- 期权方向：根据路径信号选择 Call 或 Put。
- DTE：只允许 `10–35`。
- IV：常规合约要求 `20%–70%`。
- Delta：优先选择接近 `0.50` 绝对值的合约。
- 合约池：每个方向保留距离平值最近的候选合约，再按流动性、Delta、趋势、DTE 和 IV 评分。
- 日内成交按权利金金额控制仓位。

## 4. 早盘主策略

早盘主策略用于捕捉开盘后的标准突破行情。

### 4.1 日线方向

在正式交易日前预热 `20` 个 ETF 交易日，计算日线均线和 15 分钟 EMA。方向判断只使用已完成的历史数据。

Call 方向要求：

- 前一交易日收盘价位于 MA5、MA10、MA20 上方；
- MA5 > MA10 > MA20；
- MA5 斜率为正；
- MA20 斜率不为负。

Put 方向要求反向成立：

- 前一交易日收盘价位于 MA5、MA10、MA20 下方；
- MA5 < MA10 < MA20；
- MA5 斜率为负；
- MA20 斜率不为正。

### 4.2 开盘区间

使用 `09:30–09:34` 的 5 根 1 分钟 K 线形成开盘区间。

- Call 振幅门槛：`0.30%`。
- Put 振幅门槛：`0.60%`。
- 突破放量门槛：突破分钟成交量 >= 前 5 分钟均量 × `1.30`。
- 同时要求突破分钟成交量不低于前 5 分钟最大量的 `80%`。

### 4.3 入场确认

在 `09:35–09:40` 扫描突破。

Call：

- 突破开盘高点；
- 后续 3 分钟内至少 2 分钟收盘站上开盘高点。

Put：

- 跌破开盘低点；
- 后续 3 分钟内至少 2 分钟收盘跌破开盘低点。

### 4.4 仓位

早盘目标权利金仓位：

- 普通信号：`50%`；
- strong 信号：`70%`；
- 首笔先执行目标仓位的 `65%`；
- `09:45` 二次确认通过后再补足剩余 `35%`。

如 IV 较高或日线量能偏弱，则按风控规则折减仓位。

### 4.5 09:45 二次确认

`09:45` 对早盘仓位做确认。

Call 确认：

- ETF 仍在开盘高点上方；
- 15 分钟指标仍支持上涨。

Put 确认：

- ETF 仍在开盘低点下方；
- 15 分钟指标仍支持下跌。

确认失败则在 `09:45` 平掉首笔；确认成功则按计划补仓。

### 4.6 科创早盘 Call 多头透支过滤

该过滤只作用于科创早盘 Call。

- 计算前两个完整交易日累计涨幅：`T-1 close / T-3 close - 1`。
- 若累计涨幅 `>=5%`，当日早盘 Call 不开仓。
- Put 不受影响。
- 15 分钟备用策略不受影响。
- Put 反转增强策略不受影响。

## 5. 强 15 分钟备用策略

备用策略只在当天早盘主策略没有成交时启用。

### 5.1 扫描时间

- 上午：`09:45–11:00`；
- 下午：`13:15–14:15`。

`09:45` 信号使用 `09:46` 的期权分钟 K 线开盘价成交；其他时点按信号 K 线收盘口径成交。

### 5.2 方向条件

备用方向必须与日线方向一致。

### 5.3 15 分钟强信号

Call 需要：

- 当前 15 分钟 K 线收盘价突破前 3 根 15 分钟高点；
- EMA5 > EMA20；
- EMA20 斜率为正；
- 当前 15 分钟成交量 / 前 5 根 15 分钟均量 >= `1.8`；
- 当日累计量能进度比 >= `1.15`；
- 收盘位置靠近高位。

Put 需要反向成立：

- 当前 15 分钟 K 线收盘价跌破前 3 根 15 分钟低点；
- EMA5 < EMA20；
- EMA20 斜率为负；
- 当前 15 分钟成交量 / 前 5 根 15 分钟均量 >= `1.8`；
- 当日累计量能进度比 >= `1.15`；
- 收盘位置靠近低位。

### 5.4 高 IV 暴跌 Put

备用 Put 在极端下跌场景允许更高 IV。

- 普通 IV 上限：`70%`；
- 高 IV 暴跌 Put 允许 IV 到 `90%`；
- 高 IV Put 的单笔权利金仓位上限为 `25%`。

### 5.5 低聚拢度暴跌 Put 豁免

当普通备用 Put 仅因为前一日均线聚拢度不足而被拦截时，允许一个 Put-only 豁免。

条件：

- 只允许 Put；
- 15 分钟局部量比 `>=3.0`；
- 当日累计量能进度比 `>=1.15`；
- 收盘跌破前 3 根 15 分钟最低价；
- EMA5 < EMA20；
- EMA20 斜率 < 0；
- 收盘位置靠近低位；
- 当前 ETF 价格低于上一日 MA5、MA10、MA20；
- 每日最多 1 笔；
- 权利金仓位上限 `25%`。

## 6. 备用 Call 期权动量确认

该规则只作用于 15 分钟备用 Call，目的是过滤 ETF 仍满足信号但 Call 期权本身已经走弱的假突破。

备用 Call 入场前读取所选期权最近 `8` 根 1 分钟 K 线。

若出现以下任一情况，则过滤该备用 Call：

- 当前期权价格距离最近 8 分钟高点回撤超过 `8%`；
- 最近 `3` 根 1 分钟期权收盘价连续走低；
- 最近 3 分钟平均成交量低于前段均量的 `70%`。

该规则不作用于 Put。

## 7. 09:45 Put 反转增强保守版

这是本版本的新增增强路径。它不是主策略的替代，而是在主策略当天没有交易时，额外寻找早盘冲高后可能回落的 Put 反转机会。

### 7.1 触发时间

只看 `09:45` 已完成的 15 分钟窗口。

### 7.2 标的与方向

- 标的：`588000`；
- 方向：只做 Put；
- 若主策略当天已有交易，则跳过。

### 7.3 ETF 条件

`09:45` 时，ETF 相对当日开盘涨幅必须 `>=0.50%`。

### 7.4 合约条件

候选 Put 合约必须满足：

- `abs(delta)` 在 `0.45–0.60`；
- 期权价格 `>=0.03`；
- `09:45` 这根 15 分钟成交量 `>=1000` 张；
- 在满足条件的候选中，按 `09:45` 15 分钟成交量排序，选择成交量最大的 1 张合约。

### 7.5 仓位与滑点

- 目标权利金仓位：`20%`；
- 买入价：中价基础上加 `0.0003`；
- 卖出价：中价基础上减 `0.0003`；
- 计划买入张数不得超过该合约 `09:45` 15 分钟成交量的 `5%`；
- 若超过 `5%`，该增强信号跳过。

### 7.6 退出

Put 反转增强作为 `normal_put_reversal_0945` 处理，沿用现有日内退出模型。

## 8. 退出规则

### 8.1 普通信号

- TP1：期权价格达到入场均价 × `1.35`，卖出 `50%`；
- TP2：期权价格达到入场均价 × `3.00`，卖出剩余 `50%`；
- 若未触发 TP2，`14:55` 尾盘平仓。

### 8.2 strong 信号

- TP1：期权价格达到入场均价 × `1.50`，卖出 `1/3`；
- 剩余 `2/3` 使用移动止盈；
- `10:30` 前移动止盈回撤阈值为 `35%`；
- `10:30` 后移动止盈回撤阈值为 `20%`。

### 8.3 止损

- 软止损：根据路径使用当前策略的软止损阈值；
- 硬止损：期权价格跌至入场均价 × `0.70` 时强制止损；
- 所有未退出持仓在 `14:55` 强制平仓，记为 `eod`。

## 9. 复现文件

主策略基准：

- `research/full_confirm_tp2_3p0_summary.csv`
- `research/full_confirm_tp2_3p0_trades.csv`
- `research/full_confirm_tp2_3p0_capital.csv`

主策略 + Put 反转增强保守版：

- `research/put_reversal_0945_conservative20_cap5_etfup0.005_delta0.45_0.6_pos0.2_normal_rankvolume15_minp0.03_minv1000_slip0.0003_capshare0.05_combined_summary.csv`
- `research/put_reversal_0945_conservative20_cap5_etfup0.005_delta0.45_0.6_pos0.2_normal_rankvolume15_minp0.03_minv1000_slip0.0003_capshare0.05_combined_trades.csv`
- `research/put_reversal_0945_conservative20_cap5_etfup0.005_delta0.45_0.6_pos0.2_normal_rankvolume15_minp0.03_minv1000_slip0.0003_capshare0.05_combined_capital.csv`

交易复盘图：

- `research/put_reversal_0945_conservative20_trade_review.html`

代码：

- `scripts/backtest_v11_opening_plus_strong15m.py`
- `scripts/backtest_kcb_put_reversal_0945.py`
- `scripts/plot_put_reversal_0945_conservative_review.py`

## 10. 复现命令

先复现主策略 `753.37%`：

```bash
PYTHONPATH=scripts python3 scripts/backtest_v11_opening_plus_strong15m.py \
  --days 730 \
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
  --output research/full_confirm_tp2_3p0_trades.csv \
  --capital-output research/full_confirm_tp2_3p0_capital.csv \
  --summary research/full_confirm_tp2_3p0_summary.csv
```

再叠加 Put 反转增强保守版：

```bash
PYTHONPATH=scripts python3 scripts/backtest_kcb_put_reversal_0945.py \
  --base-trades research/full_confirm_tp2_3p0_trades.csv \
  --etf-up-min 0.005 \
  --delta-min 0.45 \
  --delta-max 0.60 \
  --position-pct 0.20 \
  --min-option-price 0.03 \
  --min-volume15 1000 \
  --slippage-tick 0.0003 \
  --max-volume-share 0.05 \
  --exit-strength normal \
  --rank-by volume15 \
  --output-prefix put_reversal_0945_conservative20_cap5
```

生成复盘图：

```bash
PYTHONPATH=scripts python3 scripts/plot_put_reversal_0945_conservative_review.py
```

## 11. 当前注意事项

- Put 反转增强模块胜率低于主策略，收益主要依赖部分大盈利日，因此必须保留成交量占比限制。
- 当前保守版最大成交量占比控制在 `5%` 以内，仍需后续用模拟交易验证真实滑点。
- 该策略是科创-only 版本，不包含创业板。
- 本文档记录的是当前研究口径，不代表可以直接放大仓位实盘交易。
