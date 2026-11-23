# 本地数据包迁移清单

本清单记录需要从旧电脑单独迁移、且不进入 GitHub 的本地文件。路径均以旧电脑
项目根目录 `/Users/aaren/策略/期权策略` 为基准，外部数据为绝对路径。

## 一、项目内数据目录

| 路径 | 大小 | 说明 |
|---|---:|---|
| `data/` | 2.4 GiB | 期权、ETF、分钟数据、缓存和合约信息 |
| `research/` | 76.8 MiB | 1011 个历史回测结果、复盘 CSV、HTML 和 Markdown |
| `monitor/` | 约 356 KiB | 监控状态、手工报价、iFinD 缓存和监控网页 |
| `qmt/` 下的日志和 `.numbers` | 约 1.7 MiB | QMT 历史运行日志和研究附件 |

## 二、data/ 内部分项

### 核心回测主表

| 路径 | 大小 |
|---|---:|
| `data/kcb_option_daily.csv` | 48 MiB |
| `data/kcb_option_daily_with_etf.csv` | 48 MiB |
| `data/kcb_option_risk_indicators.csv` | 18 MiB |
| `data/cyb_option_daily_generated.csv` | 50 MiB |
| `data/cyb_option_signal_daily.csv` | 24 KiB |
| `data/cyb_option_risk_signal_dates.csv` | 12 KiB |
| `data/cyb_market_iv_daily.csv` | 60 KiB |
| `data/kcb_market_iv_daily.csv` | 140 KiB |
| `data/etf_daily_588000_588080.csv` | 264 KiB |
| `data/etf_daily_159915.csv` | 112 KiB |
| `data/etf_daily_159915_generated.csv` | 136 KiB |
| `data/summary.csv` | 4 KiB |
| `data/option_daily_failures.csv` | 4 KiB |

### 分钟数据和缓存

| 路径 | 大小 | 说明 |
|---|---:|---|
| `data/intraday_cache/` | 80 MiB | 按日期的期权 1 分钟缓存 |
| `data/raw_cache/` | 55 MiB | AkShare 原始下载缓存 |
| `data/etf_intraday_ifind/` | 1.3 MiB | iFinD ETF 分钟缓存 |
| `data/科创板 1 分钟数据（全）/` | 149 MiB | 科创 ETF 期权分钟归档 |
| `data/创业板 1 分钟数据（全）/` | 179 MiB | 创业板 ETF 期权分钟归档 |

### 大体积原始 Excel

| 路径 | 大小 | 说明 |
|---|---:|---|
| `data/双创补充期权数据/` | 938 MiB | 5 个 iFinD 宽表 Excel |
| `data/双创补充期权数据.zip` | 932 MiB | 上面目录的压缩包，可选 |

`data/双创补充期权数据.zip` 与目录内容对应同一批 5 个 Excel。可以只迁移目录，
压缩包作为备份可选。两者合计会多占约 932 MiB。

### 合约信息

| 路径 | 大小 |
|---|---:|
| `data/合约信息/华夏上证科创板50ETF.csv` | 117 KiB |
| `data/合约信息/易方达创业板ETF.csv` | 177 KiB |

## 三、外部数据

| 路径 | 大小 | 说明 |
|---|---:|---|
| `/Users/aaren/策略/china-etf-strategy/cache/etf_5m_2020_202605.sqlite` | 782 MiB | ETF 5 分钟 SQLite，回测硬依赖 |
| `/Users/aaren/策略/A股数据/基金_分钟数据/ETF_分钟数据/1分钟_按月归档/` | 3.2 GiB | ETF 1 分钟按月归档 |

新电脑通过环境变量指定：

```bash
export OPTION_ETF_SQLITE_PATH="/新电脑路径/etf_5m_2020_202605.sqlite"
export OPTION_ETF_1M_ROOT="/新电脑路径/1分钟_按月归档"
```

如果新电脑是 Windows PowerShell，当前已知 ETF 1 分钟数据根目录可以先这样配置：

```powershell
$env:OPTION_ETF_1M_ROOT = 'D:\A股数据\基金_分钟数据\ETF_分钟数据\1分钟_按月归档'
```

如果 `1分钟_按月归档` 不是该路径下的实际目录，而是月份目录直接位于
`D:\A股数据\基金_分钟数据\ETF_分钟数据`，就把环境变量设置为后者。需要先用
`Test-Path` 确认目录层级。

这个目录只提供 ETF 标的端的 1 分钟数据。它不包含项目内的期权分钟归档、
期权日级候选表、IV/Greeks 表或外部 ETF 5 分钟 SQLite。

## 四、凭证和本地配置

| 路径 | 说明 |
|---|---|
| `data:ifind_refresh_token/refresh- token.rtf` | iFinD refresh token |
| `data:ifind_refresh_token/VIP.rtf` | iFinD VIP 凭证 |
| `qmt/qmt_local_config.py` | QMT 本地账户和下单开关 |

这三项不能进入 Git。迁移时必须单独安全复制，并在新电脑重新验证。

## 五、运行状态和日志

| 路径 | 说明 |
|---|---|
| `monitor/state.json` | 监控持仓状态 |
| `monitor/manual_quotes.json` | 手工报价 |
| `monitor/today_0945_strategy_result.json` | 当日策略结果 |
| `monitor/ifind_cache/` | 监控 iFinD 缓存 |
| `monitor/option_dashboard.html` | 监控网页 |
| `qmt/0707日志.txt` 至 `qmt/0818.txt` | QMT 历史运行日志 |
| `qmt/exp_combo_put006_late18_highiv_true_dual_trades.numbers` | 研究附件 |
| `qmt/新建 文本文档.txt` | 临时文本，建议人工确认后删除 |

运行状态文件可选迁移。新电脑恢复策略前应按券商实际持仓重新核对，不要直接信任
旧状态文件。

## 六、建议打包方式

### 最小可用包

- `data/kcb_option_daily*.csv`
- `data/kcb_option_risk_indicators.csv`
- `data/cyb_option_*.csv`
- `data/kcb_market_iv_daily.csv`
- `data/cyb_market_iv_daily.csv`
- `data/etf_daily_*.csv`
- `data/合约信息/`
- `data/intraday_cache/`
- `data/raw_cache/`
- `data/科创板 1 分钟数据（全）/`
- `data/创业板 1 分钟数据（全）/`
- `research/`
- 外部 SQLite

### 完整归档包

- 整个 `data/`，包含 `双创补充期权数据/`
- 整个 `research/`
- 整个 `monitor/`
- 外部 SQLite
- 外部 ETF 1 分钟归档
- iFinD 凭证
- QMT 本地配置和日志

### 不建议打包

- `.deps/`，建议新电脑重新安装依赖
- `__pycache__/`、`.DS_Store`
- `data/双创补充期权数据.zip`，除非需要压缩备份

## 七、复制后校验

```bash
find data -type f | wc -l
find research -type f | wc -l
du -sh data research
shasum -a 256 data/kcb_option_daily.csv research/*.csv > /tmp/local_package.sha256
```

旧电脑参考值：

- `data/` 约 8430 个文件；
- `research/` 1011 个文件；
- `data/` 合计约 2.4 GiB，不含 `双创补充期权数据.zip` 时约 1.5 GiB；
- 加外部 SQLite 和 ETF 1 分钟归档后，完整数据约 7 GiB。
