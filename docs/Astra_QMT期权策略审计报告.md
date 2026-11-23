# Astra 审计报告：QMT 期权策略 R20 代码与实盘风险

## 审计范围与结论

- 审计日期为 2026 年 11 月 23 日。本文根据 GPT‑6.2 Astra 当天完成的只读审计整理，重点是 [科创板 ETF 期权 QMT 策略](../qmt/qmt_kcb_1032_live_sim.py)。审计对象的构建号为 `KCB_1606_LIVE_SIM_20260818_R20_OWNED_POSITION_REGISTRY`。
- Astra 审计时使用的是迁移前的工作树。归档时以 Git 提交 `dc90396` 复核了下表的代码位置。该提交已将原生委托开关改为本地配置，缺少本地配置时默认关闭。新电脑的实际开关、QMT 安装版本和运行入口需要单独核验。
- **R20 尚未达到真实资金运行的验收条件。** 优先处理委托与成交的对应关系、未完成退出和重启后的持仓恢复。即使信号正确，这些问题也可能让策略管理错误的仓位。原审计通过了 Python 语法和差异格式检查，仍需验证实际柜台的成交、撤单与恢复行为。
- 下表引用的历史日志是 Astra 在旧工作区看到的运行记录，部分来自早期版本。记录用于定位实盘故障类型，当前 R20 的风险另以源码核对。原始日志由本地保管。

## P0 真实委托前必须解决

| 问题 | 代码证据与影响 |
| --- | --- |
| 订单被受理后，影子账本可能立即按成交入账 | [`verify_last_order_not_rejected`](../qmt/qmt_kcb_1032_live_sim.py#L895) 匹配到委托且未看到拒单时可返回成功。[`paper_open`](../qmt/qmt_kcb_1032_live_sim.py#L2375) 和 [`paper_sell`](../qmt/qmt_kcb_1032_live_sim.py#L2649) 的确认分支可以据此更新影子账本。已报、部分成交或随后撤单会造成实际持仓与账本分叉。 |
| 委托与回报缺少唯一绑定 | 确认链路使用 `get_last_order_id`，并可回退扫描订单和成交明细。日期、合约、方向和数量能够排除部分错配，同日同合约的重复委托仍可能误匹配。历史 `0806.txt` 记录过最近订单实际属于另一合约。 |
| 持仓查询异常时，退出可能被阻塞或被推断完成 | [`native_position_snapshot`](../qmt/qmt_kcb_1032_live_sim.py#L967) 对读取失败和查不到正数持仓均返回 `None`。[`paper_sell`](../qmt/qmt_kcb_1032_live_sim.py#L2649) 可因此阻止卖出。开启的 [`infer_native_close_after_sell_attempt`](../qmt/qmt_kcb_1032_live_sim.py#L2606) 又允许根据先前卖出尝试推断平仓。历史 `0805.txt` 记录过连续的 `SELL_BLOCKED native_position_missing`。 |
| 待确认开仓超时后存在重复开仓风险 | [`reconcile_pending_open`](../qmt/qmt_kcb_1032_live_sim.py#L1397) 等待三个 bar 后可清除状态。[`clear_pending_open`](../qmt/qmt_kcb_1032_live_sim.py#L1352) 可解除 `day_locked`。旧委托若仍有效并在此后成交，可能与新开仓委托叠加。 |
| 日线方向数据过期 | [内置种子](../qmt/qmt_kcb_1032_live_sim.py#L247) 末日为 2026 年 7 月 23 日。[初始化与跨日更新](../qmt/qmt_kcb_1032_live_sim.py#L3222) 使用种子及运行中累积的数据。11 月 23 日从头启动时，需要核验前一交易日及其历史窗口是否完整，否则均线和 Call/Put 方向可能基于旧行情。 |
| 跨日重启可能漏管真实剩余仓位 | [`handlebar`](../qmt/qmt_kcb_1032_live_sim.py#L3261) 跨日重置本地状态。[持仓注册表](../qmt/qmt_kcb_1032_live_sim.py#L1088) 按交易日读取记录，自动恢复受注册合约范围限制。尾盘未成交的仓位可能在次日未被接管。 |

## P1 信号、盘口和期权选约

| 问题 | 代码证据与影响 |
| --- | --- |
| 09:45 二次确认缺少所需分钟窗口 | [`opening_confirm_ok`](../qmt/qmt_kcb_1032_live_sim.py#L2990) 要求 [`latest_15m_metrics`](../qmt/qmt_kcb_1032_live_sim.py#L2950) 至少有 5 根已完成的 15 分钟窗口。当前计算使用当日数据，09:45 只有第一根窗口，导致先期开仓可能进入确认失败的退出路径。备用策略也要到接近 11:00 才能满足该窗口要求。 |
| 补仓及对账没有完整反映真实成交 | [`paper_add_opening`](../qmt/qmt_kcb_1032_live_sim.py#L2483) 和 [`paper_add_liquidity_pending`](../qmt/qmt_kcb_1032_live_sim.py#L2528) 可按确认结果更新补仓。后续 [`sync_current_position_with_native`](../qmt/qmt_kcb_1032_live_sim.py#L2619) 主要调整数量和均价，现金、费用和已实现盈亏没有随实际成交完整重算。 |
| 五档累计深度会高估可成交张数 | [`executable_qty_from_levels`](../qmt/qmt_kcb_1032_live_sim.py#L1657) 累加限价内的可见挂量，[`cap_quantity_by_liquidity`](../qmt/qmt_kcb_1032_live_sim.py#L2319) 据此限制委托。一档深度是否充足主要用于日志。盘口撤单和报价变化可能让订单部分成交或挂住，止损和尾盘退出同样受影响。 |
| 盘口时效、价差和固定让价需要独立约束 | [`read_full_tick_bbo`](../qmt/qmt_kcb_1032_live_sim.py#L1689) 缺少明确的盘口最大龄和异常价差保护，bar 时间门控无法保证期权盘口同步。[固定让价 `0.0003`](../qmt/qmt_kcb_1032_live_sim.py#L61) 在期权价格为 `0.03` 时相当于 1%，放大低价合约的交易成本。 |
| IV 和 Delta 可能基于陈旧的期权成交价 | [`get_option_snapshot`](../qmt/qmt_kcb_1032_live_sim.py#L2077) 将期权 bar 收盘价用于选约和 IV 计算。低流动性合约的最近成交与当前盘口可能相距较大，进而影响 IV、Delta 和候选排序。需要分别记录成交时间、报价时间和估值来源。 |
| 两个 Put 路径的 IV 门槛和 DTE 口径待统一 | [`select_put_reversal`](../qmt/qmt_kcb_1032_live_sim.py#L2140) 与 [`select_opening_put_fail`](../qmt/qmt_kcb_1032_live_sim.py#L2240) 未套用常规 `IV_MIN` 至 `IV_MAX` 区间。[`days_to_expiry`](../qmt/qmt_kcb_1032_live_sim.py#L306) 使用自然日，研究文档对 `10–35` 的日期口径需要明确。 |
| 量能和普通选约与研究规则存在差异 | [`cumulative_volume_progress`](../qmt/qmt_kcb_1032_live_sim.py#L2979) 使用前一交易日的日线量比代理盘中同时间量能。[`select_option`](../qmt/qmt_kcb_1032_live_sim.py#L2103) 未落实研究框架里的当日成交量排名前三及最低 15 分钟成交量要求。两处都会改变信号或合约集合。 |

## P2 研究口径与验证缺口

- [1759.55% 研究版本](option_intraday_strategy_kcb_put_reversal_1759_55.md) 和 [1201.63% 研究版本](option_intraday_strategy_kcb_put_reversal_1201.md) 的 Put 反转排序口径有差异。R20 使用期权动量排序，并加入开盘下跌失败 Put、赢家持有、原生持仓注册和补单逻辑。原审计未找到覆盖这套执行规则的完整回测与逐笔成交回放。
- 历史 `0803.txt` 记录过 `get_trade_detail_data` 参数不匹配，同时出现 `SHADOW_FILL_ASSUMED`。当前代码尝试了多种参数组合。Windows 端仍需在实际券商 QMT 环境核对查询签名、订单与成交对象、原始委托量与已成交量字段，以及持仓返回语义。
- 盘口字段、时间戳单位、`09:45` bar 的时间口径，以及手续费、最小跳动和合约乘数都需在目标环境验证。运行说明还需记录 R20 的完整入场、选约、退出和异常处理规则。

## 修复与验收顺序

1. 保持原生委托关闭。先用只读探针在 Windows QMT 中核对行情、盘口、订单、成交和持仓接口。
2. 建立唯一委托标识和状态机。分别处理已提交、已报、部分成交、全成、已撤、拒单和查询异常。根据实际成交量、成交价和费用更新账本，未到终态的委托继续受控跟踪。
3. 用成交及持仓对账替代平仓推断。退出失败时保留仓位管理、重试与告警。回放同日、跨日重启和尾盘未平场景，差异未解决时暂停开仓。
4. 补齐最新日线预热，修复 09:45 确认和备用信号的时间依赖，逐项用研究规则比对。明确各入场路径的 IV、Delta、DTE、成交量及排序要求。
5. 验证盘口时间、买卖价差、一档和五档深度的质量。使用逐笔报价及成交回放评估滑点、部分成交、低价期权交易成本和尾盘退出，按结果校准让价。
6. 在离线回放中覆盖拒单、延迟、撤单、部分成交、无报价和重启恢复，再使用模拟账户进行单张验证。逐笔核对委托、成交、仓位和费用，记录通过条件与实测结果后再评估是否进入真实资金阶段。
