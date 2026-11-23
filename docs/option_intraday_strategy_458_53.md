# 双创 ETF 期权日内策略—458.53% 固化版

## 1. 文档用途

本文档只定义产生 `458.53%` 历史回测结果的唯一策略口径。按本文档的数据、参数、交易规则和三步复现命令执行，应得到下列结果。

| 项目 | 结果 |
|---|---:|
| 回测区间 | 2024-07-01～2026-06-30 |
| 初始资金 | 100,000.00 元 |
| 期末资金 | 558,534.09 元 |
| 净利润 | 458,534.09 元 |
| 总收益率 | 458.53% |
| 总交易数 | 27 笔 |
| 科创 50 ETF 期权 | 22 笔 |
| 创业板 ETF 期权 | 5 笔 |
| 净胜率 | 81.48% |
| 最大回撤 | 13.21% |

## 2. 交易对象和策略结构

- 科创 50 ETF：`588000.SH`，交易上交所 ETF 期权。
- 创业板 ETF：`159915.SZ`，交易深交所 ETF 期权。
- 两个标的都执行早盘主策略。
- 只有科创 50 ETF 执行强 15 分钟备用策略。
- 科创当日已执行早盘交易时，当日不再接受备用交易。
- 两个标的同日出现交易时，按第 8 节的冲突规则只保留一个标的。

## 3. 数据口径

回测必须使用下列本地数据，不在回测中临时请求 iFinD：

- ETF 1 分钟：本地按日 ZIP 及 `data/etf_intraday_ifind/` 补充数据。
- ETF 5 分钟和日线：`/Users/aaren/策略/china-etf-strategy/cache/etf_5m_2020_202605.sqlite` 及本项目 ETF 日线 CSV。
- 科创期权日级候选：`data/kcb_option_daily.csv`。
- 科创市场 IV：`data/kcb_market_iv_daily.csv`。
- 科创 ETF 日线：`data/etf_daily_588000_588080.csv`。
- 创业板期权日级候选：`data/cyb_option_signal_daily.csv`。
- 创业板市场 IV：`data/cyb_market_iv_daily.csv`。
- 创业板 ETF 日线：`data/etf_daily_159915.csv`。
- 期权 1 分钟执行数据：`data/intraday_cache/`。

所有日线方向和日级风控只使用上一个已完成交易日的数据。ETF 15 分钟 EMA 在正式回测起点前强制加载 `20` 个交易日预热；预热不足直接报错。

## 4. 日线方向

以上一个交易日收盘数据计算 MA5、MA10、MA20 及斜率：

- Call：收盘价 `> MA5 > MA10 > MA20`，且 MA5 斜率 `> 0`、MA20 斜率 `>= 0`。
- Put：收盘价 `< MA5 < MA10 < MA20`，且 MA5 斜率 `< 0`、MA20 斜率 `<= 0`。
- 其余情况为 `none`，早盘主策略不开仓。

备用策略在日线均线未完全排列时，允许用当前 ETF 价格相对上一日 MA5、MA10、MA20 的全部突破方向补充判定，但 MA5 和 MA20 斜率仍必须同方向。

## 5. 早盘主策略

### 5.1 开盘区间

- 用 `09:30～09:34` 五根 ETF 1 分钟 K 线定义开盘高点、低点和振幅。
- 科创 Call 振幅门槛：`0.30%`。
- 创业板 Call 振幅门槛：`0.25%`。
- 两个标的 Put 振幅门槛：`0.60%`。

### 5.2 突破与放量

在 `09:35～09:40` 逐分钟扫描：

- Call 要求当分钟最高价突破开盘高点。
- Put 要求当分钟最低价跌破开盘低点。
- 科创当分钟成交量至少为开盘五分钟平均量的 `1.30` 倍。
- 创业板当分钟成交量至少为开盘五分钟平均量的 `1.25` 倍。
- 同时必须不低于开盘五分钟单根最大成交量的 `0.80` 倍。
- 突破后三根 1 分钟收盘价至少有两根站在突破位之外。
- 首次入场时间为突破后第三分钟，但不早于 `09:40`、不晚于 `09:45`。

### 5.3 分批入场

- 突破量比 `< 2.0` 为 normal，目标权利金仓位 `50%`。
- 突破量比 `>= 2.0` 为 strong，目标权利金仓位 `70%`。
- 选中合约 IV `>= 50%` 时，目标仓位乘 `0.70`。
- 上一日成交量/过去 20 日均量 `< 0.65` 时禁止交易；在 `[0.65, 0.80)` 时目标仓位再乘 `0.70`。
- 首笔使用目标仓位的 `65%`。
- `09:45` 确认：Call 要求 ETF 仍收在开盘高点上方且 15 分钟收盘高于 EMA5；Put 反向判定。
- 确认失败则在 `09:45` 全部退出。
- 确认成功且 `09:45` 期权价格不高于首笔价格的 `103%` 时，补齐剩余 `35%` 目标仓位。

## 6. 科创强 15 分钟备用策略

### 6.1 启用条件和时间

- 只在科创当日没有执行早盘主策略时启用。
- 信号时间为 `09:45～11:00` 和 `13:15～14:15` 的已完成 15 分钟 K 线。
- `09:45` 信号在 `09:46` 期权 1 分钟 K 线的开盘价成交；其余信号按信号 K 线收盘价成交。
- 每日最多两笔，且当日只交易第一次选中的同一张期权合约。

### 6.2 前置过滤

- 市场 IV `>= 20%`。
- 252 日 IV Rank `< 50%`。
- 上一日 MA5、MA10、MA20 最大值与最小值之差/收盘价 `>= 1.5%`。
- 上一日成交量/过去 20 日均量 `>= 0.65`。

### 6.3 strong 信号

- Call：收盘突破前 3 根 15 分钟最高价，EMA5 `> EMA20`，EMA20 斜率 `> 0`。
- Put：收盘跌破前 3 根 15 分钟最低价，EMA5 `< EMA20`，EMA20 斜率 `< 0`。
- 当根 15 分钟量/前 5 根 15 分钟平均量 `>= 1.8`。
- 当日截至当时累计量/过去 20 日同时刻平均累计量 `>= 1.15`。
- `09:45` 的 Call 收盘位置必须 `>= 0.75`，Put 必须 `<= 0.25`。
- 其余时间 Call 收盘位置必须 `>= 0.65`，Put 必须 `<= 0.35`。
- 信号方向必须与第 4 节日线允许方向一致。
- 本策略的备用路径只接受 strong，任一条件不满足都不交易。

## 7. 期权合约筛选和仓位

### 7.1 硬过滤

- 只选当月或次月合约。
- DTE：`10～35` 个自然日。
- `|Delta|`：`0.35～0.65`。
- Call 和普通 Put 的逐合约 IV：`20%～70%`。
- 备用 Put 允许逐合约 IV：`70%～90%`。
- 日成交量和入场前累计成交量都必须大于零。
- 不启用边缘 DTE 扩展。

### 7.2 期权分钟趋势

- 早盘路径：期权 5 分钟收盘价 `> EMA5`，且 EMA5 向上。
- 备用路径：期权对应周期收盘价 `> EMA5 > EMA20`。

### 7.3 排名公式

日成交量初选后，对通过分钟趋势确认的候选按以下分数降序选第一名：

`0.40×流动性 + 0.25×Delta贴近0.50 + 0.20×期权趋势 + 0.10×DTE + 0.05×IV`

其中 DTE `10～25` 得 1.0，DTE `26～35` 得 0.65；IV 越高得分越低。

### 7.4 备用仓位

- 备用信号先按 IV Rank、均线聚拢度、日成交量、盘中累计量和前日影线做风险折算。
- 折算后仓位乘 `2.5`，普通备用交易的权利金仓位上限为 `50%`。
- 逐合约 IV 在 `70%～90%` 的高 IV Put，权利金仓位上限为 `25%`。

## 8. 双标的冲突规则

同一交易日两个标的都有交易时：

1. 只要存在早盘主策略交易，就优先在早盘交易中选择。
2. 早盘强度分数为：`(实际振幅/标的基础振幅门槛) × (实际突破量比/标的放量门槛)`。冲突排名中科创基础振幅使用 `0.30%`，创业板使用 `0.25%`。
3. 如果当日只有备用交易，先选最早信号，再按局部量比和收盘位置的标准化强度选择。
4. 最终每日只保留一个标的的交易路径。

## 9. 退出规则

### 9.1 通用规则

- 硬止损：期权价格达到平均入场价的 `70%`。
- 软止损需同时满足价格门槛，以及“期权收盘低于期权 EMA5”或“ETF 15 分钟反向跌破/突破 EMA20 且 EMA20 斜率反向”。
- `14:55` 仍有持仓时全部平仓。

### 9.2 早盘交易

- 软止损价为平均入场价的 `75%`，入场 5 分钟后才生效。
- normal：涨至 `135%` 时卖出一半，剩余仓位在 `180%` 卖出。
- strong：涨至 `150%` 时卖出三分之一；剩余仓位用最高价回撤止盈，`10:30` 前回撤 `35%`，`10:30` 后回撤 `25%`。

### 9.3 备用交易

- 软止损价为入场价的 `82%`，立即生效。
- 备用路径全部为 strong：涨至 `150%` 时卖出三分之一；剩余仓位用最高价回撤止盈，`10:30` 前回撤 `35%`，`10:30` 后回撤 `20%`。

## 10. 资金回测口径

- 初始资金：`100,000` 元。
- 合约乘数：`10,000`。
- 买入成交价：策略价格 `+0.0001`。
- 卖出成交价：策略价格 `-0.0001`。
- 手续费：每张每边 `2` 元，完整买卖往返每张 `4` 元。
- 合约张数：`向下取整(当日期初资金×目标仓位/(买入成交价×10000))`。
- 同日多笔交易都以当日期初资金计算张数，日末统一更新资金。

## 11. 完整复现命令

在项目根目录 `/Users/aaren/策略/期权策略` 执行。

### 第一步：生成科创交易

```bash
PYTHONPATH=.deps python3 scripts/backtest_v11_opening_plus_strong15m.py \
  --days 730 \
  --underlying 588000 \
  --daily-csv data/kcb_option_daily.csv \
  --market-iv-csv data/kcb_market_iv_daily.csv \
  --etf-daily-csv data/etf_daily_588000_588080.csv \
  --range-threshold 0.0030 \
  --put-range-threshold 0.0060 \
  --breakout-vol-mult 1.30 \
  --warmup-trading-days 20 \
  --fallback-progress-min 1.15 \
  --fallback-position-multiplier 2.5 \
  --fallback-position-cap 0.50 \
  --late-trend-acceleration \
  --late-strong-volume-mult 1.8 \
  --high-iv-crash-put \
  --high-iv-put-min 0.70 \
  --high-iv-put-max 0.90 \
  --high-iv-put-position-cap 0.25 \
  --output research/exp_combo_put006_late18_highiv_dual_trades.csv \
  --capital-output research/exp_combo_put006_late18_highiv_dual_capital.csv \
  --summary research/exp_combo_put006_late18_highiv_dual_summary.csv
```

### 第二步：生成创业板交易

```bash
PYTHONPATH=.deps python3 scripts/backtest_v11_opening_plus_strong15m.py \
  --days 730 \
  --underlying 159915 \
  --daily-csv data/cyb_option_signal_daily.csv \
  --market-iv-csv data/cyb_market_iv_daily.csv \
  --etf-daily-csv data/etf_daily_159915.csv \
  --range-threshold 0.0025 \
  --put-range-threshold 0.0060 \
  --breakout-vol-mult 1.25 \
  --warmup-trading-days 20 \
  --disable-fallback \
  --output research/exp_combo_put006_late18_highiv_cyb_trades.csv \
  --capital-output research/exp_combo_put006_late18_highiv_cyb_capital.csv \
  --summary research/exp_combo_put006_late18_highiv_cyb_summary.csv
```

### 第三步：合并双标的并计算资金曲线

```bash
PYTHONPATH=.deps python3 scripts/backtest_v12_dual_underlying.py \
  --kcb-trades research/exp_combo_put006_late18_highiv_dual_trades.csv \
  --cyb-trades research/exp_combo_put006_late18_highiv_cyb_trades.csv \
  --start-date 2024-07-01 \
  --end-date 2026-06-30 \
  --initial-capital 100000 \
  --contract-multiplier 10000 \
  --fee-per-contract-side 2 \
  --slippage-tick 0.0001 \
  --output research/exp_combo_put006_late18_highiv_true_dual_trades.csv \
  --capital-output research/exp_combo_put006_late18_highiv_true_dual_capital.csv \
  --summary research/exp_combo_put006_late18_highiv_true_dual_summary.csv
```

## 12. 结果校验

第三步完成后，`research/exp_combo_put006_late18_highiv_true_dual_summary.csv` 应包含：

```text
initial_capital = 100000.0
final_capital = 558534.09
net_pnl = 458534.09
total_return = 4.5853409
trades = 27
kcb_trades = 22
cyb_trades = 5
win_rate_net = 0.8148148148
max_drawdown = 0.1321409460
```

若任一数值不一致，先检查数据文件版本、本地期权 1 分钟缓存、SQLite 路径、回测起止日期、手续费和滑点参数。

## 13. 结果边界

`458.53%` 是上述固定数据区间和固定参数下的历史回测结果，不是实盘收益保证。高 IV Put 对单一极端行情日的收益贡献较大，后续必须保持相同规则做样本外监测，不得根据新结果临时回改参数。
