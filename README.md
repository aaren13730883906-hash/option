# 科创 ETF 期权日线数据

本目录保存科创 ETF 期权回测用数据。主表在 `data/kcb_option_daily.csv`。

## 数据文件

- `data/kcb_option_daily.csv`: 回测主表，按 `trade_date + option_code + contract_id` 组织，包含期权 OHLC、涨跌幅、交易所隐含波动率、Greeks、ETF OHLC、ETF 涨跌幅和历史波动率。
- `data/kcb_option_risk_indicators.csv`: 上交所期权风险指标原始整理表，包含 IV 和 Greeks。
- `data/etf_daily_588000_588080.csv`: 从本地 ETF 5 分钟 sqlite 聚合出的 ETF 日线和历史波动率。
- `data/kcb_option_daily_with_etf.csv`: 和主表等价的宽表，字段顺序略不同。
- `data/option_daily_failures.csv`: AkShare/新浪未返回日线的合约编码。
- `data/raw_cache/`: 按日期/合约缓存的原始下载结果，方便断点续跑。

## 口径

- 期权范围：`588000` 科创50ETF、`588080` 科创板50ETF 对应的上交所 ETF 期权。
- 覆盖范围：`2023-06-06` 到 `2026-05-25`。本地 ETF sqlite 缺 `2023-06-05`，所以主表从 `2023-06-06` 开始。
- 期权 OHLCV：AkShare `option_sse_daily_sina`。
- IV/Greeks：AkShare `option_risk_indicator_sse`，字段 `implied_volatility` 为交易所口径隐含波动率。
- ETF 日线：从 `/Users/aaren/ChinaETF/china-etf-strategy/cache/etf_5m_2020_202605.sqlite` 的 5 分钟数据聚合。
- ETF 历史波动率：ETF 日收盘收益率滚动标准差乘以 `sqrt(252)`，提供 `hv_20d`、`hv_30d`、`hv_60d`、`hv_120d`。

## 重新生成

```bash
PYTHONPATH=.deps python3 scripts/build_kcb_option_daily.py
```

脚本会优先读取 `data/raw_cache/`，已有数据不会重复下载。
