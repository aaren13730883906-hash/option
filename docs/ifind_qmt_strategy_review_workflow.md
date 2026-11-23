# iFinD/QMT 策略交易复核流程

本文档记录 2026-08-03 已验证成功的复核流程。以后把 QMT 策略信号、拒单或成交结果同步到监控台时，按这里检查，避免再次把 API 数据误判成“没有返回”。

## 1. 先从 QMT 日志确定交易事实

需要记录这些字段：

- 交易日期，例如 `2026-08-03`
- 策略路径，例如 `opening_put_fail`
- 合约代码，例如 QMT 代码 `10012156.SHO`
- 开仓时间，例如 `09:46`
- 策略开仓价格，例如 `0.1326`
- 计划张数，例如 `18`
- 仓位金额，例如 `0.1326 * 18 * 10000 = 23868`
- 委托/拒单诊断，例如柜台返回的错误文字

如果是 QMT 系统问题导致应开未开，但用户确认要计入策略盈亏，在 `monitor/state.json` 对应 position 中设置：

```json
"kind": "missed_strategy_open",
"count_in_total": true
```

## 2. QMT 合约代码到 iFinD 代码的映射

上海期权在 QMT 里常见是 `.SHO`，但同花顺/iFinD 分钟线接口用 `.SH`：

- QMT：`10012156.SHO`
- iFinD：`10012156.SH`

不要直接拿 `.SHO` 去调 iFinD。`.SHO` 可能返回 `-4210` 或空数据。

## 3. 拉取分钟线

监控脚本：

```bash
python3 scripts/update_option_monitor.py --refresh
```

脚本会调用 1 分钟高频行情，字段包括：

```text
open, high, low, close, volume, amount, changeRatio
```

日期范围使用交易日 `09:30:00` 到 `15:00:00`。正常整天数据应约为 241 根 1 分钟 K 线。

## 4. API 返回后的必要校验

复核时至少检查：

- `monitor/ifind_cache/YYYYMMDD_合约_SH_1m.json` 是否存在；
- `rows` 数量是否接近 241；
- 第一根是否为 `09:30`；
- 最后一根是否为 `15:00`；
- `market.data_status` 是否为 `ifind_1m`，而不是 `manual_quote` 或 `no_option_market_data`。

如果出现类似 `20:26:08` 这种时间，说明时间解析错了。iFinD 有时返回 12 位时间 `YYYYMMDDHHMM`，例如 `202608030930`，必须按 `YYYY-MM-DD HH:MM:00` 解析。

另一个已踩坑点：iFinD 返回表格时，时间可能在外层 `table["time"]`，每行 row 里没有单独时间。脚本必须把外层时间复制到每一行，否则会误判为空数据。

## 5. 策略盈亏计算规则

监控台应尽量和正式 QMT 策略一致：止盈止损判断使用 1 分钟 `close`，不是 `high/low`。

以 `opening_put_fail` 为例：

- 仓位：25%
- 止损：`entry * 0.88`
- TP1：`entry * 1.25`，卖一半
- TP2：`entry * 1.45`，清仓
- 尾盘退出：`14:45`
- 手续费：每张每边 2 元
- 乘数：10000

全平盈亏公式：

```text
exit_price * qty * 10000 - entry_price * qty * 10000 - 开仓手续费 - 平仓手续费
```

## 6. 2026-08-03 复核结果样例

交易事实：

- 策略路径：`opening_put_fail`
- 合约：`10012156.SHO` / `10012156.SH`
- 开仓时间：`09:46`
- 开仓价：`0.1326`
- 张数：`18`
- 仓位：`23868`，约占本金 `23.87%`

iFinD 复核：

- 合约分钟线：241 根，`09:30` 到 `15:00`
- 标的 `588000.SH` 分钟线：241 根，`09:30` 到 `15:00`
- 09:46 合约 close：`0.1319`，策略记录开仓价按 QMT 委托价 `0.1326`
- 14:45 合约 close：`0.1403`
- 没有触发止损、TP1、TP2
- 14:45 按尾盘退出

盈亏：

```text
18 * 0.1403 * 10000 - 18 * 0.1326 * 10000 - 72 = 1314
```

这笔已经按用户确认计入策略总盈亏。

## 7. 更新监控台后的最终检查

运行：

```bash
python3 scripts/update_option_monitor.py
```

再检查 `monitor/state.json`：

- `today_pnl` 是否包含当天确认计入的策略交易；
- `total_pnl` 是否等于历史已计入交易之和；
- `return_pct` 是否等于 `total_pnl / initial_cash * 100`；
- 对应 position 是否有 `count_in_total: true`；
- `market.data_status` 是否为 `ifind_1m`。

2026-08-03 当前口径：

```text
-1995 + 7910 + 1314 = 7229
7229 / 100000 = 7.229%
```
