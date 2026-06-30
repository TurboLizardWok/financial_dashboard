# 全球金融 Dashboard

每天自动更新的全球金融市场综合看板，覆盖美债、BTC、黄金、A 股、CME FedWatch 利率预期、巴菲特指数、BTC/金价比、A 股申万行业集中度、股债利差等。

## 一键启动（推荐）

```bash
# macOS / Linux
sh run.sh

# Windows
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

启动后浏览器自动打开 http://localhost:8501

## 手动启动

```bash
# 1. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 2. 装依赖
pip install -r requirements.txt

# 3. 启动
streamlit run app.py
```

## 环境要求

- Python ≥ 3.10
- 稳定网络（需要能访问部分海外站点，详见下方"数据源说明"）

## 文件结构

```
financial_dashboard/
├── app.py                # 主程序（单文件，~1700 行）
├── requirements.txt      # 依赖列表
├── run.sh                # 一键启动脚本
├── README.md             # 本文件
└── data/                 # 历史 CSV 缓存（自动生成）
    ├── buffett_index_history.csv
    ├── btc_gold_ratio_history.csv
    ├── china_equity_bond_spread_history.csv
    ├── china_sector_turnover_concentration.csv
    └── us_yield_curve_history.csv
```

## 数据源说明

| 模块 | 数据源 | 状态要求 |
|------|--------|----------|
| 美债实时收益率 | Treasury.gov | ✅ 国内可直连 |
| 美债历史百分位 | Treasury.gov CSV | ✅ 国内可直连 |
| BTC / 黄金 | yfinance + CoinGecko | ✅ 国内可直连 |
| 沪深 300 / 10Y 国债 | akshare | ✅ 国内可直连 |
| A 股申万一级 31 行业 | akshare | ✅ 国内可直连 |
| CME FedWatch | `cme-fedwatch` 包 | ⚠️ 需要能访问 CME（包内置 curl_cffi 绕过） |
| 巴菲特指数 | yfinance `^W5000` + FRED GDP | ⚠️ FRED 需能访问（用 curl_cffi） |
| FINRA 保证金债务 | FINRA.org | ❌ 接口已下线，模块显示"暂不可用" |
| 美股行业集中度 | — | ❌ 缺数据源，模块显示"暂不可用" |
| AH 溢价 | — | ❌ 已删除（v2） |

> ✅ = 国内可直连 | ⚠️ = 需要能访问海外站点 | ❌ = 当前版本不可用

## 常见问题

### Q1: 启动后某个数据"获取失败"怎么办？

先确认网络：
```bash
# 测试几个关键站点
curl -I https://home.treasury.gov              # 美债
curl -I https://api.coingecko.com                # BTC
curl -I https://www.cmegroup.com                 # CME FedWatch
curl -I https://fred.stlouisfed.org              # FRED (GDP)
```

### Q2: `KeyError` / `ValueError` 之类的错误

90% 是 fetch 函数返回空数据（数据源临时不可用）。重启 streamlit 重试一次：
- macOS: `Ctrl+C` 停掉，再 `sh run.sh`
- Windows: 关掉终端，重新运行

### Q3: 启动很慢 / 卡在 "请等待"

第一次启动会同时跑 9 个数据源的拉取（带 5 分钟缓存），最坏情况要 30-60 秒。第二次会快很多（命中缓存）。

### Q4: 我朋友也想要一份

直接把整个 `financial_dashboard/` 文件夹发给他。如果他在不同网络环境（特别是海外），CME FedWatch 和 FRED 那两栏可能显示"不可用"是正常的，其他模块不受影响。

### Q5: `data/` 目录可以删吗？

可以。删了之后下次启动会重新拉取并生成。`@st.cache_data` 缓存也会清空。

## 排错速查

| 报错 | 原因 | 解法 |
|------|------|------|
| `ModuleNotFoundError: No module named 'akshare'` | 依赖没装全 | `pip install -r requirements.txt` |
| `KeyError: 'date'` | 老版本 bug，已修复 | 拉最新 `app.py` |
| `ValueError: DataFrame constructor not properly called!` | 老版本 bug，已修复 | 拉最新 `app.py` |
| `curl_cffi` 缺失 | 漏装 | `pip install curl-cffi` |
| 巴菲特指数一直 "暂不可用" | FRED 被墙 | 切换网络 / 用代理 |

## 更新日志

- **v0.2 (2026-06-30)**
  - 新增：巴菲特指数 / CME FedWatch 12 场会议 / A 股申万 31 行业 / 股债利差 / BTC-金价比多周期百分位 / 美债历史百分位
  - 删除：AH 溢价指数（数据源已死）
  - 修复：Series/DataFrame 双兼容, pivot_table 改 set_index
- **v0.1 (2026-06-30)**
  - 首次发布：美债 / BTC / 黄金 / A 股 / 新闻

## License

MIT# financial_dashboard
