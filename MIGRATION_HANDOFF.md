# 期权研究项目迁移交接单

这份文件交给新电脑上的 Codex。请先完整阅读，再执行部署。当前交接单描述的是
2026 年 11 月 23 日这台旧电脑上的项目状态。

## 目标

在新电脑上恢复以下能力：

- 期权研究脚本和历史文档；
- 科创板、创业板 ETF 期权回测环境；
- QMT 探针、影子模拟和实盘前检查工具；
- 可重复的本地数据路径配置；
- 不把 iFinD 凭证、QMT 账户和交易状态放入 GitHub。

真实委托必须在新电脑完成 QMT 登录、行情验证和模拟验证后单独开启。

## 当前仓库

- 项目目录：`/Users/aaren/策略/期权策略`
- Git 分支：`main`
- GitHub origin：`https://github.com/aaren13730883906-hash/option.git`
- 当前已知基线提交：`f4f7567 Add QMT passorder variant probe`
- 旧电脑当前工作区存在未提交修改和未跟踪文件。新电脑不能假设 GitHub 已包含旧电脑最新状态。
- 当前没有唯一的正式 QMT 入口。根据本地最新修改，暂把
  `qmt/qmt_kcb_1032_live_sim.py` 的 `R20` 作为迁移主候选，把
  `qmt/qmt_v12_dual_live_sim.py` 的 `R19` 作为备用和对照版本。新电脑在任何下单
  测试前仍必须确认这一选择。
- `qmt/qmt_v12_dual_live_sim.py` 当前包含 `PAPER_START_DATE = 20260703` 的历史
  回放门控。当前日期为 2026 年 11 月 23 日，新电脑不能直接把这个日期当作当前
  实盘日期。

在新电脑首先执行：

```bash
git status --short --branch
python3 scripts/migration_inventory.py --output migration_inventory_new.json
```

如果 GitHub 尚未包含旧电脑的新提交，先使用旧电脑交接的代码包或等待旧电脑完成
人工审查后的提交。不要自行把所有未跟踪文件加入 Git。

## 旧电脑已完成的准备

本次准备已经完成以下事项：

- 增加 `requirements-research.txt`，列出研究环境依赖；
- 增加 `config/migration_paths.example.env`，统一外部数据路径和 iFinD 环境变量；
- 增加 `qmt/qmt_local_config.example.py`，把 QMT 账户配置改为本地文件模板；
- 创建旧电脑本地的 `qmt/qmt_local_config.py`，该文件被 Git 忽略；
- 关键 QMT 策略和探针读取本地 QMT 配置；
- 两个主要 QMT 策略的 `QMT_NATIVE_ORDER_ENABLED` 由本地配置控制，缺少本地配置时
  默认关闭；
- `qmt_passorder_variant_probe.py` 和流动性下单测试默认保持未武装；
- 关键研究脚本支持 `OPTION_ETF_SQLITE_PATH`；
- `backtest_v10_opening_range_b.py` 支持 `OPTION_ETF_1M_ROOT`；
- 增加只读盘点脚本 `scripts/migration_inventory.py`。

这些改动只处理迁移和安全配置。没有改变策略信号、期权筛选条件或退出逻辑。

## 代码部署

如果新电脑可以访问 GitHub：

```bash
git clone https://github.com/aaren13730883906-hash/option.git
cd option
```

如果仓库已存在：

```bash
git fetch origin
git status --short --branch
git pull --ff-only origin main
```

如果 GitHub 没有旧电脑最新提交，使用旧电脑导出的经过审查的代码包补齐。优先补齐
以下目录和文件：

- `scripts/`
- `qmt/`
- `docs/`
- `README.md`
- `requirements-research.txt`
- `config/migration_paths.example.env`
- `MIGRATION_HANDOFF.md`

不要把以下内容直接加入公共 Git 历史：

- `data/`
- `research/`
- `.deps/`
- `data:ifind_refresh_token/`
- `qmt/qmt_local_config.py`
- `.env`
- QMT 运行日志和个人账户截图

## 研究环境

研究脚本建议使用独立 Python 环境。当前脚本使用现代 Python 类型标注，建议
Python 3.10 或更高版本。QMT 自带的 Python 运行时单独处理，不要把研究依赖强行
安装进 QMT 内置环境。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-research.txt
```

数据路径配置：

```bash
export OPTION_ETF_SQLITE_PATH="/absolute/path/to/etf_5m_2020_202605.sqlite"
export OPTION_ETF_1M_ROOT="/absolute/path/to/1-minute-etf-archive"
```

如需使用 iFinD：

```bash
export IFIND_ACCESS_TOKEN="..."
```

或者：

```bash
export IFIND_REFRESH_TOKEN="..."
```

不要把 token 写入提交文件。仓库中的部分旧脚本仍会读取本地 token 文件，只有在
确认文件位于新电脑且被 `.gitignore` 忽略后才能运行。

## 本地数据迁移

旧电脑目前已知数据规模如下，实际以旧电脑运行的盘点脚本为准：

- `data/` 约 2.4 GB，约 8430 个文件；
- `research/` 约 79 MB，约 1011 个文件；
- `.deps/` 约 234 MB；
- 外部 ETF SQLite 数据库不在本仓库；
- 外部 ETF 1 分钟归档目录不在本仓库。

建议复制两份数据：

### 核心研究数据包

用于先恢复回测：

- `data/kcb_option_daily.csv`
- `data/kcb_option_daily_with_etf.csv`
- `data/kcb_option_risk_indicators.csv`
- `data/etf_daily_588000_588080.csv`
- `data/etf_daily_159915.csv`
- `data/cyb_option_signal_daily.csv`，如果存在
- `data/cyb_option_daily_generated.csv`，如果存在
- `data/合约信息/`
- `data/intraday_cache/`
- `data/raw_cache/` 中当前回测依赖的缓存

### 完整历史归档包

用于保留可复现材料：

- 整个 `data/`
- 整个 `research/`
- 外部 ETF SQLite 数据库
- 外部 ETF 1 分钟归档目录
- 旧电脑上的研究结果和回测报告

复制后在两台电脑上生成校验和。不要只看文件夹大小。压缩包可以通过外接硬盘、
局域网、NAS或加密云盘转移。

## 外部数据路径

项目历史上使用过以下旧电脑路径：

```text
/Users/aaren/ChinaETF/china-etf-strategy/cache/etf_5m_2020_202605.sqlite
/Users/aaren/策略/china-etf-strategy/cache/etf_5m_2020_202605.sqlite
/Users/aaren/策略/A股数据/基金_分钟数据/ETF_分钟数据/1分钟_按月归档
```

新电脑不需要复刻这些绝对路径。优先使用：

- `OPTION_ETF_SQLITE_PATH`
- `OPTION_ETF_1M_ROOT`
- 具体脚本的 `--sqlite`
- 具体脚本的 `--etf-1m-root`

如果数据不存在，先停止在数据检查阶段并报告缺失路径。不要创建空文件冒充数据。

## QMT 部署

QMT 脚本不能只靠 GitHub 完整恢复。新电脑还需要：

1. 安装与旧电脑兼容的 QMT 版本；
2. 登录对应券商账户；
3. 确认股票期权账户权限；
4. 配置 QMT 策略目录；
5. 将 `qmt/*.py` 复制到 QMT 策略目录；
6. 同时复制 `qmt/qmt_local_config.example.py` 为
   `qmt_local_config.py`，在本地填入账户；
7. 确认 QMT 能读取策略目录中的 CSV；
8. 确认 QMT 能返回 ETF、期权和盘口数据。

本地配置示例：

```python
QMT_ACCOUNT_ID = ""
QMT_NATIVE_ORDER_ENABLED = False
PASSORDER_PROBE_ARMED = False
LIQUIDITY_ORDER_TEST_ARMED = False
```

先保留空账户或填入模拟账户。账户号不要提交到 GitHub。只有完成无下单探针、影子
模拟和人工核对后的单次模拟订单测试，才允许在本地配置中打开
`QMT_NATIVE_ORDER_ENABLED`。

旧电脑历史日志出现过 `PASSORDER_RETURN 0` 后订单和成交查询失败的情况。新电脑
必须单独验证 `get_trade_detail_data` 的实际参数签名、订单对象、成交对象、持仓对象、
部分成交、拒单和撤单结果。`PASSORDER_RETURN` 不是成交证明。

## QMT 验证顺序

按以下顺序运行，任何一步失败都先修复，不要跳到真实委托：

1. `qmt_option_history_probe.py`
2. `qmt_option_only_probe.py`
3. `qmt_option_range_availability_probe.py`
4. `qmt_historical_option_api_probe.py`
5. `qmt_orderbook_probe.py`
6. `qmt_order_confirm_now_probe.py`
7. `qmt_v12_dual_live_paper.py`
8. `qmt_v12_dual_live_sim.py`
9. `qmt_kcb_1032_live_sim.py`

`qmt_passorder_variant_probe.py` 默认未武装。只有在用户明确准备做单次模拟账户
测试时，才在本地配置中将 `PASSORDER_PROBE_ARMED` 设为 `True`，并把数量保持为
一张。流动性下单测试同理。

重点记录并回传给主 Codex：

- QMT 版本和券商；
- 回测日期是否正确；
- 期权合约列表数量；
- 期权 1 分钟 OHLCV；
- 买一卖一价格和数量；
- `passorder` 返回值；
- `ORDER_CALLBACK`；
- `DEAL_CALLBACK`；
- 账户、持仓和成交查询结果；
- 是否出现空盘口、延迟K线、重复下单或撤单失败。

`QMT_ORDER_SENT` 只表示调用了下单接口。必须看到 QMT 成交回报或账户成交查询，
才可以认为订单成交。

在启用任何原生下单前，检查以下开关：

- `QMT_NATIVE_ORDER_ENABLED`
- `EXECUTION_SMOKE_TEST`
- `FORCE_TEST_DIRECTION`
- `PASSORDER_PROBE_ARMED`
- `LIQUIDITY_ORDER_TEST_ARMED`
- `QMT_INFER_CLOSE_WHEN_NATIVE_POSITION_MISSING_AFTER_SELL`

`QMT_INFER_CLOSE_WHEN_NATIVE_POSITION_MISSING_AFTER_SELL` 涉及卖出后持仓查询缺失
时的状态推断。没有确认新电脑的持仓查询可靠前，不要把它当作实盘成交依据。

`qmt_kcb_1032_live_sim.py` 使用相对文件
`kcb_1606_owned_positions.csv` 保存策略持仓登记。新电脑必须确认 QMT 当前工作目录
和该文件的真实写入位置，并在启动前与券商账户实际持仓逐项核对，防止旧登记文件导致
重复开仓或错误平仓。

## 研究验收

先运行一个短回测：

```bash
PYTHONPATH=. python scripts/backtest_v02_recent_intraday.py --days 5 --no-fetch
```

如果项目数据布局允许，再运行：

```bash
PYTHONPATH=. python scripts/build_kcb_option_daily.py --limit-dates 1 --limit-contracts 1
```

验收时对比旧电脑和新电脑的：

- 数据文件行数；
- 可用交易日；
- 期权合约数量；
- 交易数量；
- 期末资金；
- 最大回撤；
- 关键交易日期；
- 资金曲线和报告文件。

数据源、Python 版本、依赖版本或 SQLite 内容不同都会导致结果变化。结果不同
时先比较输入数据和参数，再判断代码问题。

## 部署检查清单

- [ ] 已确认唯一正式 QMT 入口，并记录其 `BUILD_ID`；
- [ ] 已记录正式入口的 Git 提交号和文件校验和；
- [ ] 已确认工作区未提交修改已经纳入迁移包；
- [ ] 已检查全部 `passorder` 调用位置；
- [ ] 已确认订单测试脚本默认未武装；
- [ ] 已确认原生下单、影子模拟和测试方向开关；
- [ ] 已确认使用模拟账户还是实盘账户；
- [ ] 已完成账户、持仓、订单、成交和撤单接口探针；
- [ ] 已确认 `PASSORDER_RETURN` 不被当作成交证明；
- [ ] 已确认部分成交、拒单、撤单和断线重连行为；
- [ ] 已确认期权代码后缀、买一卖一、五档盘口和价格跳动单位；
- [ ] 已确认 QMT 为 1 分钟周期和 `OPTION` 策略类型；
- [ ] 已确认当前期权合约池和 DTE 10 至 35 合约数量；
- [ ] 已确认日线预热数据满足正式策略要求；
- [ ] 已确认外部 SQLite、ETF 分钟数据、`data/` 和 `research/` 校验和；
- [ ] 已重新配置 iFinD，且 token 未进入 Git；
- [ ] 已确认 `monitor/` 和持仓登记文件实际路径；
- [ ] 已确认旧的 `PAPER_START_DATE` 和历史回测日期门控不会误导当前运行；
- [ ] 已完成无下单探针和内部影子模拟；
- [ ] 已完成单合约、单次、可人工核对的模拟订单测试；
- [ ] 已确认真实委托开关保持关闭，直到全部检查完成；
- [ ] 旧电脑仍保留完整代码、数据、日志和可回滚环境。

## 交接完成条件

新电脑 Codex 在完成部署后，需要输出一份验收报告，至少包含：

- Git commit；
- Python 和依赖版本；
- 数据目录和校验和；
- 外部 SQLite 路径；
- iFinD 配置状态；
- QMT 版本、账户类型和策略目录；
- 每个探针的结果；
- 短回测结果；
- 未解决问题；
- 真实委托开关当前是否关闭。

真实委托开关没有经过明确检查前，保持关闭。
