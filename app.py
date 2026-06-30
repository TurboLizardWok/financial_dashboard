"""
Global Financial Dashboard - v0.1
Streamlit 单文件金融仪表盘
运行方式: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go
import yfinance as yf
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from io import StringIO
import socket
import time as _time
import os

# ============================================================
# 可选依赖: akshare (用于中国国债收益率、沪深300 PE)
# ============================================================
try:
    import akshare as ak
    AKSHARE_OK = True
except Exception:
    AKSHARE_OK = False

socket.setdefaulttimeout(30)

# ============================================================
# 常量
# ============================================================
GOLD_ABOVE_GROUND_TONNES = 216265       # World Gold Council, end 2024
TROY_OZ_PER_TONNE = 32150.7
GOLD_TOTAL_OZ = GOLD_ABOVE_GROUND_TONNES * TROY_OZ_PER_TONNE  # ~6.95B oz
BTC_SUPPLY = 19_700_000                  # 近似流通量 (2024)

MATURITIES = ['1M', '3M', '6M', '1Y', '2Y', '3Y', '5Y', '7Y', '10Y', '20Y', '30Y']
TREASURY_COL_MAP = {
    '1 Mo': '1M', '3 Mo': '3M', '6 Mo': '6M',
    '1 Yr': '1Y', '2 Yr': '2Y', '3 Yr': '3Y',
    '5 Yr': '5Y', '7 Yr': '7Y', '10 Yr': '10Y',
    '20 Yr': '20Y', '30 Yr': '30Y',
}

# ============================================================
# 页面配置
# ============================================================
st.set_page_config(
    page_title="Global Financial Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ============================================================
# 辅助函数
# ============================================================
def _yf_download(ticker, period='1y'):
    """从 yfinance 下载日频数据，处理 MultiIndex 列。"""
    try:
        hist = yf.download(ticker, period=period, interval='1d', progress=False)
        if hist is None or hist.empty:
            return None
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        hist.index = pd.to_datetime(hist.index).normalize()
        return hist
    except Exception:
        return None


def _latest_close(hist):
    """从 yfinance DataFrame 获取最新收盘价。"""
    if hist is None or hist.empty:
        return None
    try:
        val = hist['Close'].iloc[-1]
        if isinstance(val, pd.Series):
            val = val.iloc[0]
        return float(val) if pd.notna(val) else None
    except Exception:
        return None


# ============================================================
# 数据抓取函数
# ============================================================

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_treasury_yields():
    """从美国财政部获取国债收益率曲线。"""
    try:
        year = datetime.now().year
        url = (
            f"https://home.treasury.gov/resource-center/data-chart-center/"
            f"interest-rates/daily-treasury-rates.csv/{year}/all?"
            f"type=daily_treasury_yield_curve&field_tdr_date_value={year}"
            f"&page&_format=csv"
        )
        r = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
        df['Date'] = pd.to_datetime(df['Date'], format='%m/%d/%Y')
        df = df.sort_values('Date', ascending=False).reset_index(drop=True)

        latest = df.iloc[0]
        latest_date = latest['Date']

        yields_today = {}
        for col, label in TREASURY_COL_MAP.items():
            if col in df.columns:
                v = latest[col]
                yields_today[label] = float(v) if pd.notna(v) else None
            else:
                yields_today[label] = None

        comparisons = {}
        # 昨日 = 前一个交易日
        if len(df) > 1:
            prev = df.iloc[1]
            comp = {}
            for col, label in TREASURY_COL_MAP.items():
                if col in df.columns:
                    v = prev[col]
                    comp[label] = float(v) if pd.notna(v) else None
                else:
                    comp[label] = None
            comparisons['yesterday'] = {'yields': comp, 'date': prev['Date']}
        else:
            comparisons['yesterday'] = None

        # 1周前、1月前
        for key, days in [('1_week', 7), ('1_month', 30)]:
            target = latest_date - timedelta(days=days)
            mask = df['Date'] <= target
            if mask.any():
                row = df[mask].iloc[0]
                comp = {}
                for col, label in TREASURY_COL_MAP.items():
                    if col in df.columns:
                        v = row[col]
                        comp[label] = float(v) if pd.notna(v) else None
                    else:
                        comp[label] = None
                comparisons[key] = {'yields': comp, 'date': row['Date']}
            else:
                comparisons[key] = None

        # 历史30天趋势
        hist_df = df.head(30).sort_values('Date')
        hist_data = {}
        for col, label in TREASURY_COL_MAP.items():
            if col in df.columns:
                h = hist_df[['Date', col]].dropna()
                h.columns = ['Date', 'Yield']
                hist_data[label] = h

        return {
            'success': True,
            'yields': yields_today,
            'comparisons': comparisons,
            'history': hist_data,
            'latest_date': latest_date,
            'source': 'U.S. Department of the Treasury',
        }
    except Exception as e:
        return {'success': False, 'error': str(e),
                'source': 'U.S. Department of the Treasury'}


@st.cache_data(ttl=300, show_spinner=False)
def fetch_btc():
    """从 CoinGecko 获取 BTC 当前数据，yfinance 获取历史。"""
    try:
        url = (
            "https://api.coingecko.com/api/v3/simple/price?"
            "ids=bitcoin&vs_currencies=usd"
            "&include_24hr_change=true&include_market_cap=true"
            "&include_24hr_vol=true"
        )
        r = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        d = r.json()['bitcoin']

        hist = _yf_download('BTC-USD', period='1y')

        return {
            'success': True,
            'price': float(d['usd']),
            'market_cap': float(d['usd_market_cap']),
            'change_24h': float(d['usd_24h_change']),
            'volume_24h': float(d['usd_24h_vol']),
            'history': hist,
            'source': 'CoinGecko API (实时) + yfinance (历史)',
        }
    except Exception as e:
        return {'success': False, 'error': str(e), 'source': 'CoinGecko API'}


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_gold():
    """从 yfinance 获取黄金期货价格 (GC=F)。"""
    try:
        hist = _yf_download('GC=F', period='1y')
        price = _latest_close(hist)
        if price is None:
            raise ValueError("无黄金价格数据")
        return {
            'success': True,
            'price': price,
            'market_cap': price * GOLD_TOTAL_OZ,
            'history': hist,
            'source': 'yfinance (GC=F, COMEX黄金期货)',
        }
    except Exception as e:
        return {'success': False, 'error': str(e), 'source': 'yfinance (GC=F)'}


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_csi300():
    """沪深300指数 (yfinance) + PE (akshare)。"""
    try:
        hist = _yf_download('000300.SS', period='1y')
        price = _latest_close(hist)
        if price is None:
            raise ValueError("无沪深300数据")

        pe = None
        pe_date = None
        if AKSHARE_OK:
            try:
                pe_df = ak.stock_index_pe_lg(symbol="沪深300")
                if pe_df is not None and not pe_df.empty:
                    pe = float(pe_df.iloc[-1]['滚动市盈率'])
                    pe_date = str(pe_df.iloc[-1]['日期'])
            except Exception:
                pass

        ey = (1.0 / pe * 100) if pe and pe > 0 else None

        return {
            'success': True,
            'price': price,
            'pe': pe,
            'pe_date': pe_date,
            'earnings_yield': ey,
            'history': hist,
            'source': 'yfinance (000300.SS) + akshare (PE)',
        }
    except Exception as e:
        return {'success': False, 'error': str(e), 'source': 'yfinance (000300.SS)'}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_china_bond():
    """中国/美国国债收益率 (akshare)。"""
    if not AKSHARE_OK:
        return {'success': False, 'error': 'akshare未安装', 'source': 'akshare'}
    try:
        df = ak.bond_zh_us_rate(start_date="2024-01-01")
        if df is None or df.empty:
            raise ValueError("无国债数据")
        row = df.iloc[-1]

        cn_10y = float(row['中国国债收益率10年']) if pd.notna(row.get('中国国债收益率10年')) else None
        cn_2y = float(row['中国国债收益率2年']) if pd.notna(row.get('中国国债收益率2年')) else None
        us_10y = float(row['美国国债收益率10年']) if pd.notna(row.get('美国国债收益率10年')) else None
        us_2y = float(row['美国国债收益率2年']) if pd.notna(row.get('美国国债收益率2年')) else None

        return {
            'success': True,
            'cn_10y': cn_10y,
            'cn_2y': cn_2y,
            'us_10y': us_10y,
            'us_2y': us_2y,
            'latest_date': str(row['日期']),
            'source': 'akshare (中美国债收益率)',
        }
    except Exception as e:
        return {'success': False, 'error': str(e), 'source': 'akshare'}


# 申万一级行业 2021 分类 — 以 akshare sw_index_first_info() 官方口径为准 (31 个)
# 重要: 行业代码-名称对应是固定的, 不要凭印象写。
SW_L1_CODES = {
    '801010': '农林牧渔', '801030': '基础化工', '801040': '钢铁',
    '801050': '有色金属', '801080': '电子',     '801110': '家用电器',
    '801120': '食品饮料', '801130': '纺织服饰', '801140': '轻工制造',
    '801150': '医药生物', '801160': '公用事业', '801170': '交通运输',
    '801180': '房地产',   '801200': '商贸零售', '801210': '社会服务',
    '801230': '综合',     '801710': '建筑材料', '801720': '建筑装饰',
    '801730': '电力设备', '801740': '国防军工', '801750': '计算机',
    '801760': '传媒',     '801770': '通信',     '801780': '银行',
    '801790': '非银金融', '801880': '汽车',     '801890': '机械设备',
    '801950': '煤炭',     '801960': '石油石化', '801970': '环保',
    '801980': '美容护理',
}


def _try_tushare_sw_realtime():
    """Tushare Pro 路径: rt_sw_k (申万行业实时) + sw_daily。
    需要 tushare 包 + 有效 token (积分要求 sw_daily >= 2000)。
    """
    try:
        import tushare as ts
    except ImportError:
        return None
    token = os.environ.get('TUSHARE_TOKEN', '').strip()
    if not token:
        return None
    try:
        pro = ts.pro_api(token)
        # rt_sw_k 是分钟/实时级别, 不一定有日线收盘后的总成交
        # sw_daily 是日线, 当日数据不完整但历史可用
        # 这里用 sw_daily 取最近一个交易日 (历史稳定)
        df = pro.sw_daily(
            ts_code=','.join([f'{c}.SW' for c in SW_L1_CODES.keys()]),
            trade_date=datetime.now().strftime('%Y%m%d'),
        )
        if df is None or df.empty:
            df = pro.sw_daily(trade_date=datetime.now().strftime('%Y%m%d'))
        if df is None or df.empty:
            return None
        return df
    except Exception:
        return None


def _try_akshare_sw_l1_hist():
    """AkShare 路径 1: index_hist_sw 拉每个申万一级最新一行 (单位: 亿元)。
    31 次网络请求, 慢 (~50s), 但与历史 CSV 同源同口径, 是最稳的 L1 实时路径。
    """
    if not AKSHARE_OK:
        return None
    rows = []
    for code in SW_L1_CODES.keys():
        try:
            df = ak.index_hist_sw(symbol=code, period='day')
            if df is None or df.empty:
                continue
            row = df.iloc[-1]
            rows.append({
                'industry_code': code,
                'industry_name': SW_L1_CODES[code],
                'price': float(row['收盘']) if pd.notna(row['收盘']) else None,
                'turnover_yi': float(row['成交额']) if pd.notna(row['成交额']) else None,
                'date': str(row['日期']),
            })
        except Exception:
            continue
    if not rows:
        return None
    return pd.DataFrame(rows)


def _try_akshare_sw_l2_aggregate():
    """AkShare 路径 2: index_realtime_sw (L2+L3) → sw_index_second_info 父行业聚合。
    单次拉取 (~30s), 但 L3 子行业漏算 (占比通常 < 5%)。
    """
    if not AKSHARE_OK:
        return None
    try:
        rt = ak.index_realtime_sw()
        if rt is None or rt.empty:
            return None
        l2_info = ak.sw_index_second_info()
        if l2_info is None or l2_info.empty:
            return None
        l2_to_l1 = {}
        for _, row in l2_info.iterrows():
            l2_code = str(row['行业代码']).split('.')[0]
            l1_name = row['上级行业']
            l2_to_l1[l2_code] = l1_name
        l1_name_to_code = {v: k for k, v in SW_L1_CODES.items()}

        rt['代码'] = rt['指数代码'].astype(str).str.strip()
        rt['L1_name'] = rt['代码'].map(l2_to_l1)
        rt_l2 = rt[rt['L1_name'].notna()].copy()
        if rt_l2.empty:
            return None

        # 成交额单位经验: 2792.02 = 27.92 亿元, 即 /100
        rt_l2['turnover_yi'] = pd.to_numeric(rt_l2['成交额'], errors='coerce') / 100
        rt_l2 = rt_l2.dropna(subset=['turnover_yi'])
        rt_l2 = rt_l2[rt_l2['turnover_yi'] > 0]

        grouped = rt_l2.groupby('L1_name').agg(
            turnover_yi=('turnover_yi', 'sum'),
            price=('最新价', 'mean'),
            stock_count=('代码', 'count'),
        ).reset_index()
        grouped['industry_code'] = grouped['L1_name'].map(l1_name_to_code)
        grouped['industry_name'] = grouped['L1_name']
        grouped = grouped.dropna(subset=['industry_code'])
        return grouped[['industry_code', 'industry_name', 'turnover_yi', 'price', 'stock_count']]
    except Exception:
        return None


def _try_akshare_all_a_groupby():
    """第三优先: 全A个股实时 + 申万一级成份股 (index_component_sw) → groupby 聚合成交额。
    慢 (31 × N 网络请求), 仅在前两个路径失败时使用。
    """
    if not AKSHARE_OK:
        return None
    try:
        # 1) 全A实时 (注意: 此接口依赖东财, 网络差时会失败)
        all_a = ak.stock_zh_a_spot_em()
        if all_a is None or all_a.empty:
            return None
        # 统一代码格式
        all_a['代码'] = all_a['代码'].astype(str).str.zfill(6)
        # 找 成交额 列
        turn_col = None
        for c in ['成交额', '成交额(元)', '成交额（元）']:
            if c in all_a.columns:
                turn_col = c
                break
        if turn_col is None:
            return None
        all_a['成交额_元'] = pd.to_numeric(all_a[turn_col], errors='coerce')
        all_a = all_a.dropna(subset=['成交额_元'])
        all_a = all_a[all_a['成交额_元'] > 0]

        # 2) 拉 31 个申万一级 的成份股, 构造 code→industry_name 映射
        code_to_industry = {}
        for sw_code, sw_name in SW_L1_CODES.items():
            try:
                cons = ak.index_component_sw(symbol=sw_code)
                if cons is None or cons.empty:
                    continue
                for stock_code in cons['证券代码'].astype(str).str.zfill(6):
                    code_to_industry[stock_code] = (sw_code, sw_name)
            except Exception:
                continue

        if not code_to_industry:
            return None

        # 3) groupby
        all_a['industry_code'] = all_a['代码'].map(
            lambda c: code_to_industry.get(c, (None, None))[0]
        )
        all_a['industry_name'] = all_a['代码'].map(
            lambda c: code_to_industry.get(c, (None, None))[1]
        )
        all_a = all_a.dropna(subset=['industry_code'])

        grouped = all_a.groupby(['industry_code', 'industry_name']).agg(
            turnover_yi=('成交额_元', lambda x: x.sum() / 1e8),
            stock_count=('代码', 'count'),
        ).reset_index()
        # 重新按 SW_L1_CODES 顺序排
        grouped['order'] = grouped['industry_code'].map({c: i for i, c in enumerate(SW_L1_CODES)})
        grouped = grouped.sort_values('order').drop(columns='order').reset_index(drop=True)
        grouped['price'] = None
        return grouped[['industry_code', 'industry_name', 'turnover_yi', 'price', 'stock_count']]
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_china_sector_turnover():
    """A 股申万一级行业成交额 (实时 + 集中度)。

    计算口径: 每日按 31 个申万一级行业汇总成交额, 取占比最高行业作为
             "最大行业成交集中度"。历史百分位是"每日最大行业占比"时间序列
             (不固定行业)。历史 CSV 列: date,industry_code,industry_name,turnover_yi。

    数据源优先级:
      1) Tushare Pro `sw_daily`           (需 TUSHARE_TOKEN + sw_daily 积分 >= 2000)
      2) AkShare `index_hist_sw` × 31 L1   (单位: 亿元, 与历史 CSV 同源, 慢 ~50s)
      3) AkShare `index_realtime_sw` + `sw_index_second_info` 父行业聚合
         (L3 子行业漏算, 占比 < 5%, 速度 ~30s)
      4) AkShare `stock_zh_a_spot_em` + `index_component_sw` groupby
         (依赖东财全 A 接口, 仅前 3 失败时用)
    """
    df = None
    source = None

    # 路径 1: Tushare
    tushare_df = _try_tushare_sw_realtime()
    if tushare_df is not None and not tushare_df.empty:
        out = []
        for _, row in tushare_df.iterrows():
            code = str(row.get('ts_code', '')).split('.')[0]
            if code not in SW_L1_CODES:
                continue
            out.append({
                'industry_code': code,
                'industry_name': row.get('name', SW_L1_CODES[code]),
                'turnover_yi': float(row.get('amount', 0)) / 1e5,  # 千元 → 亿元
                'price': float(row.get('close', 0)) if pd.notna(row.get('close')) else None,
                'date': str(row.get('trade_date', '')),
            })
        if out:
            df = pd.DataFrame(out)
            source = 'Tushare Pro (sw_daily, 申万一级 2021)'

    # 路径 2: AkShare L1 hist (31 个 L1 各拉一次)
    if (df is None or df.empty) and AKSHARE_OK:
        df = _try_akshare_sw_l1_hist()
        if df is not None and not df.empty:
            source = 'AkShare (index_hist_sw × 31 L1, 单位: 亿元)'

    # 路径 3: AkShare L2 实时 + 父行业聚合
    if (df is None or df.empty) and AKSHARE_OK:
        df = _try_akshare_sw_l2_aggregate()
        if df is not None and not df.empty:
            source = 'AkShare (index_realtime_sw L2 + sw_index_second_info 父行业聚合)'

    # 路径 4: 全 A 个股 + groupby (最后兜底)
    if (df is None or df.empty) and AKSHARE_OK:
        df = _try_akshare_all_a_groupby()
        if df is not None and not df.empty:
            source = 'AkShare (stock_zh_a_spot_em + index_component_sw, groupby 聚合)'

    if df is None or df.empty:
        return {
            'success': False,
            'error': '四个数据源全部失败 (Tushare / AkShare L1 hist / L2 聚合 / 全A groupby)',
            'source': 'Tushare / AkShare',
        }

    # 计算集中度
    df = df.copy()
    total = df['turnover_yi'].sum()
    df['share_pct'] = df['turnover_yi'] / total * 100
    df = df.sort_values('turnover_yi', ascending=False).reset_index(drop=True)
    df['cumulative_pct'] = df['share_pct'].cumsum()

    top1 = df.iloc[0] if len(df) > 0 else None
    hhi = (df['share_pct'] / 100).pow(2).sum() * 10000  # 行业 HHI (0-10000)

    return {
        'success': True,
        'df': df,  # DataFrame: industry_code, industry_name, turnover_yi, price, share_pct, cumulative_pct
        'total_turnover_yi': float(total),
        'top1_industry': top1['industry_name'] if top1 is not None else None,
        'top1_pct': float(top1['share_pct']) if top1 is not None else None,
        'top3_pct': float(df.head(3)['share_pct'].sum()),
        'top5_pct': float(df.head(5)['share_pct'].sum()),
        'top10_pct': float(df.head(10)['share_pct'].sum()),
        'hhi': float(hhi),
        'industry_count': int(len(df)),
        'source': source,
    }


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_china_sector_turnover_history(symbol: str = '801010', name: str = '农林牧渔'):
    """单行业历史成交额，用于累计历史 CSV。

    注: index_hist_sw 的 成交额 字段单位是 亿元 (raw value = 亿元), 不需再除以 1e8。
    """
    if not AKSHARE_OK:
        return pd.DataFrame()
    try:
        df = ak.index_hist_sw(symbol=symbol, period='day')
        if df is None or df.empty:
            return pd.DataFrame()
        df['日期'] = pd.to_datetime(df['日期'])
        df = df.sort_values('日期').reset_index(drop=True)
        out = pd.DataFrame({
            'date': df['日期'].dt.strftime('%Y-%m-%d'),
            'industry_code': symbol,
            'industry_name': name,
            'turnover_yi': df['成交额'],  # 单位: 亿元
        })
        return out
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_us_sector_turnover():
    """美股行业成交集中度 — 当前免费数据源不可用 (用户选 C 方案)。"""
    return {
        'success': False,
        'unavailable': True,
        'error': '美股端无稳定免费的行业分类成交额数据源。ETF 代理被拒绝。',
        'source': '— (暂不可用)',
        'reference_url': 'https://www.tradingview.com/markets/stocks-usa/sectorandindustry-sector/',
    }


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_margin_debt():
    """FINRA Margin Debt — 当前免费数据源不可用 (用户选 B 方案)。"""
    return {
        'success': False,
        'unavailable': True,
        'error': 'FINRA 公开页面已 404；FRED 系列 BOGZ1FL663067003Q 在当前网络环境下不可达。',
        'source': '— (暂不可用)',
        'reference_url': 'https://www.finra.org/finra-data/fixed-income/corp-and-agency',
    }


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_buffett_index():
    """巴菲特指数 (Wilshire 5000 / GDP)。

    口径与 longtermtrends.com 完全一致：
    - Wilshire 5000 Total Market Cap (USD) — yfinance ^W5000 直接返回万亿美元市值(73.86T)
    - US GDP (current, BEA 季调, 十亿美元) — FRED GDP series

    注: yfinance 的 ^W5000 数据集本身已是以 "万亿美元" 计的市值口径
    (e.g. 73,861 = $73.86T), 与 longtermtrends 显示完全一致。
    GDP 走 FRED 公开 CSV (curl_cffi 绕过代理)。
    """
    try:
        w5000 = _yf_download('^W5000', period='5y')
        w5000_market_cap_b = _latest_close(w5000)  # 单位: 10亿美元 (Billions USD)
        if w5000_market_cap_b is None:
            raise ValueError("Wilshire 5000 无数据")

        from curl_cffi import requests as ccr
        gdp_resp = ccr.get(
            'https://fred.stlouisfed.org/graph/fredgraph.csv',
            params={'id': 'GDP',
                    'cosd': (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d'),
                    'coed': datetime.now().strftime('%Y-%m-%d')},
            impersonate='chrome',
            timeout=20,
        )
        gdp_resp.raise_for_status()
        gdp_lines = [l for l in gdp_resp.text.strip().split('\n')[1:]
                     if ',' in l and l.split(',')[1] not in ('.', '')]
        if not gdp_lines:
            raise ValueError("FRED GDP 数据为空")
        latest_line = gdp_lines[-1]
        gdp_date, gdp_value = latest_line.split(',', 1)
        gdp_billions = float(gdp_value)

        # 巴菲特指数 = Wilshire 5000 市值 / GDP × 100%
        buffett_pct = w5000_market_cap_b / gdp_billions * 100

        history = load_csv_history('buffett_index_history')
        row = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'w5000_market_cap_b': round(w5000_market_cap_b, 2),
            'gdp_billions_usd': round(gdp_billions, 3),
            'gdp_period': gdp_date,
            'buffett_pct': round(buffett_pct, 2),
        }
        append_csv_history('buffett_index_history', row)

        return {
            'success': True,
            'w5000_market_cap_b': w5000_market_cap_b,
            'w5000_market_cap_t': w5000_market_cap_b / 1000,  # 万亿
            'gdp_billions_usd': gdp_billions,
            'gdp_period': gdp_date,
            'buffett_pct': round(buffett_pct, 2),
            'note': 'Wilshire 5000 (Total Market Cap) / US GDP (current, BEA 季调)。与 longtermtrends.com 同口径。',
            'source': 'yfinance (^W5000) + FRED (GDP)',
            'reference_url': 'https://www.longtermtrends.com/market-cap-to-gdp-the-buffett-indicator/',
        }
    except Exception as e:
        return {'success': False, 'error': str(e),
                'source': 'yfinance + FRED'}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_fedwatch():
    """CME FedWatch 隐含利率概率 (cme-fedwatch 包，绕过 IP 封禁)。"""
    try:
        import cme_fedwatch
        data = cme_fedwatch.get_probabilities()
        return {
            'success': True,
            'effr': data.get('effr'),
            'current_target': data.get('current_target'),
            'schedule_status': data.get('schedule_status', {}),
            'meetings': data.get('meetings', []),
            'source': 'cme-fedwatch (基于 CME 30D Fed Funds Futures settlements)',
        }
    except Exception as e:
        return {'success': False, 'error': str(e),
                'source': 'cme-fedwatch'}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_fedwatch_history():
    """FedWatch 历史快照 (cme-fedwatch)。
    cme-fedwatch 的 get_history() 逐日重建非常慢，
    本函数仅返回当前 12 个会议的实时概率 + EFFR/target range，
    并尝试获取 1 个最近会议的简短 lookback（lookback 抓取失败不影响主流程）。
    """
    try:
        import cme_fedwatch
        all_data = cme_fedwatch.get_probabilities()
        if not all_data.get('meetings'):
            return {'success': False, 'error': '无可用会议',
                    'source': 'cme-fedwatch'}

        # 主结果：12 个会议的当前概率
        meetings_prob = all_data['meetings']

        # 尝试拿下一个会议的 7 天 lookback（限时）
        lookback = None
        if meetings_prob:
            next_date = meetings_prob[0]['date']
            try:
                hist = cme_fedwatch.get_history(next_date, days=7)
                lookback = hist.get('lookback', [])
            except Exception:
                pass  # 不影响主流程

        return {
            'success': True,
            'meetings_history': {m['date']: m for m in meetings_prob},
            'next_meeting_lookback': lookback,
            'source': 'cme-fedwatch (current 12 FOMC meetings + 1 lookback)',
        }
    except Exception as e:
        return {'success': False, 'error': str(e),
                'source': 'cme-fedwatch'}


# ============================================================
# v0.2 新增: 增强 BTC/金价比 + 股债利差
# ============================================================
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_btc_gold_ratio_with_history():
    """BTC/黄金市值比 + 多周期历史百分位。

    使用 v0.1 已有的 BTC 和黄金数据；额外用 yfinance 拉 5 年历史计算。
    """
    try:
        btc_h = _yf_download('BTC-USD', period='5y')
        gold_h = _yf_download('GC=F', period='5y')
        if btc_h is None or gold_h is None or btc_h.empty or gold_h.empty:
            return {'success': False, 'error': '历史数据不足', 'source': 'yfinance'}

        common = btc_h.index.intersection(gold_h.index)
        if len(common) < 30:
            return {'success': False, 'error': '共同交易日 < 30', 'source': 'yfinance'}

        ratio_series = (btc_h['Close'].loc[common] * BTC_SUPPLY) / (
            gold_h['Close'].loc[common] * GOLD_TOTAL_OZ
        )
        ratio_series = ratio_series.dropna()

        current_ratio = float(ratio_series.iloc[-1])
        pct = calculate_multi_period_percentiles(current_ratio, ratio_series)

        for d, v in ratio_series.items():
            try:
                append_csv_history('btc_gold_ratio_history', {
                    'date': pd.Timestamp(d).strftime('%Y-%m-%d'),
                    'ratio': round(float(v), 6),
                })
            except Exception:
                pass

        return {
            'success': True,
            'current_ratio': current_ratio,
            'percentiles': pct,
            'history': ratio_series,
            'source': 'yfinance (BTC-USD × 1970万 / GC=F × 69.5亿 oz)',
        }
    except Exception as e:
        return {'success': False, 'error': str(e), 'source': 'yfinance'}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_china_equity_bond_spread_history():
    """中国股债利差历史 — 同时返回 E/P - 10Y 和 股息率 - 10Y，并写入 CSV。"""
    if not AKSHARE_OK:
        return {'success': False, 'error': 'akshare未安装', 'source': 'akshare'}
    try:
        bond_df = ak.bond_zh_us_rate(start_date="2018-01-01")
        if bond_df is None or bond_df.empty:
            return {'success': False, 'error': '国债历史数据为空', 'source': 'akshare'}

        bond_df['日期'] = pd.to_datetime(bond_df['日期'])
        bond_df = bond_df.sort_values('日期').reset_index(drop=True)

        try:
            csi300_pe = ak.stock_index_pe_lg(symbol="沪深300")
            if csi300_pe is None or csi300_pe.empty:
                raise ValueError("PE 历史数据为空")
            csi300_pe['日期'] = pd.to_datetime(csi300_pe['日期'])
            csi300_pe = csi300_pe.sort_values('日期').reset_index(drop=True)
        except Exception:
            return {'success': False, 'error': 'PE 历史数据获取失败', 'source': 'akshare'}

        merged = pd.merge(
            csi300_pe[['日期', '滚动市盈率']].rename(columns={'滚动市盈率': 'pe'}),
            bond_df[['日期', '中国国债收益率10年']].rename(columns={'中国国债收益率10年': 'cn10y'}),
            on='日期', how='inner',
        ).dropna()

        if len(merged) < 30:
            return {'success': False, 'error': '合并后样本 < 30', 'source': 'akshare'}

        merged['ep'] = 1.0 / merged['pe'] * 100
        merged['spread_ep'] = merged['ep'] - merged['cn10y']

        for _, r in merged.iterrows():
            try:
                append_csv_history('china_equity_bond_spread_history', {
                    'date': r['日期'].strftime('%Y-%m-%d'),
                    'pe': round(float(r['pe']), 2),
                    'ep': round(float(r['ep']), 2),
                    'cn10y': round(float(r['cn10y']), 2),
                    'spread_ep': round(float(r['spread_ep']), 2),
                })
            except Exception:
                pass

        latest = merged.iloc[-1]
        spread_series = merged.set_index('日期')['spread_ep']
        pct = calculate_multi_period_percentiles(latest['spread_ep'], spread_series)

        return {
            'success': True,
            'pe': float(latest['pe']),
            'ep': float(latest['ep']),
            'cn10y': float(latest['cn10y']),
            'spread_ep': float(latest['spread_ep']),
            'percentiles': pct,
            'history': spread_series,
            'date': latest['日期'].strftime('%Y-%m-%d'),
            'source': 'akshare (stock_index_pe_lg + bond_zh_us_rate)',
        }
    except Exception as e:
        return {'success': False, 'error': str(e), 'source': 'akshare'}


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_us_yield_curve_history_csv():
    """把 Treasury 收益率历史批量写入本地 CSV。"""
    try:
        year = datetime.now().year
        url = (
            f"https://home.treasury.gov/resource-center/data-chart-center/"
            f"interest-rates/daily-treasury-rates.csv/{year}/all?"
            f"type=daily_treasury_yield_curve&field_tdr_date_value={year}"
            f"&page&_format=csv"
        )
        r = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
        df['Date'] = pd.to_datetime(df['Date'], format='%m/%d/%Y')
        rows = []
        for _, row in df.iterrows():
            rec = {'date': row['Date'].strftime('%Y-%m-%d')}
            for col, label in TREASURY_COL_MAP.items():
                v = row.get(col)
                rec[label] = float(v) if pd.notna(v) else None
            rec['spread_2y10y'] = (
                rec.get('10Y') - rec.get('2Y')
                if rec.get('10Y') is not None and rec.get('2Y') is not None
                else None
            )
            append_csv_history('us_yield_curve_history', rec)
            rows.append(rec)
        return {'success': True, 'rows': rows, 'count': len(df), 'source': 'Treasury.gov'}
    except Exception as e:
        return {'success': False, 'error': str(e), 'source': 'Treasury.gov'}


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_china_sector_history_batch():
    """拉 31 个申万一级行业近 5 年历史并写 CSV。"""
    if not AKSHARE_OK:
        return {'success': False, 'error': 'akshare未安装', 'source': 'akshare'}

    SW_INDUSTRIES = SW_L1_CODES  # 复用前面定义的 31 个 L1 行业

    saved = 0
    for code, name in SW_INDUSTRIES.items():
        try:
            df = ak.index_hist_sw(symbol=code, period='day')
            if df is None or df.empty:
                continue
            df['日期'] = pd.to_datetime(df['日期'])
            for _, row in df.iterrows():
                append_csv_history('china_sector_turnover_concentration', {
                    'date': row['日期'].strftime('%Y-%m-%d'),
                    'industry_code': code,
                    'industry_name': name,
                    'turnover_yi': float(row['成交额']),  # 单位: 亿元
                })
            saved += 1
        except Exception:
            continue

    return {'success': True, 'industries_saved': saved,
            'source': 'akshare (申万一级历史, 单位: 亿元)'}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_news():
    """从多个 RSS 源获取金融新闻。"""
    feeds = [
        ('CNBC',
         'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114'),
        ('Google News',
         'https://news.google.com/rss/search?q=stock+market+OR+finance+OR+economy&hl=en-US&gl=US&ceid=US:en'),
        ('NPR Business', 'https://feeds.npr.org/1006/rss.xml'),
        ('MarketWatch',
         'https://feeds.content.dowjones.io/public/rss/mw_topstories'),
    ]
    all_items = []
    for name, url in feeds:
        try:
            r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            feed = feedparser.parse(r.content)
            for entry in feed.entries[:15]:
                raw = entry.get('summary', entry.get('description', ''))
                summary = BeautifulSoup(raw, 'html.parser').get_text(strip=True)[:300]
                pp = entry.get('published_parsed')
                ts = _time.mktime(pp) if pp else 0
                all_items.append({
                    'title': entry.get('title', 'No title'),
                    'link': entry.get('link', ''),
                    'published': entry.get('published', 'Unknown'),
                    'timestamp': ts,
                    'summary': summary,
                    'source': name,
                })
        except Exception:
            continue

    all_items.sort(key=lambda x: x['timestamp'], reverse=True)
    if not all_items:
        return {'success': False, 'error': '未获取到新闻', 'source': 'RSS feeds'}
    return {
        'success': True,
        'items': all_items[:5],
        'source': 'CNBC / Google News / NPR Business / MarketWatch (RSS)',
    }


# ============================================================
# 计算函数
# ============================================================
def calc_btc_gold_ratio(btc_mc, gold_mc):
    if btc_mc and gold_mc and gold_mc > 0:
        return btc_mc / gold_mc
    return None


def calc_spread(yields, short, long):
    s = yields.get(short)
    l = yields.get(long)
    if s is not None and l is not None:
        return l - s
    return None


# ============================================================
# v0.2 新增辅助: 数据目录与 CSV 历史
# ============================================================
import os as _os

DATA_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'data')

_CSV_HISTORY_FILES = {
    'us_yield_curve_history': 'us_yield_curve_history.csv',
    'china_equity_bond_spread_history': 'china_equity_bond_spread_history.csv',
    'us_sector_turnover_concentration': 'us_sector_turnover_concentration.csv',
    'china_sector_turnover_concentration': 'china_sector_turnover_concentration.csv',
    'btc_gold_ratio_history': 'btc_gold_ratio_history.csv',
    'buffett_index_history': 'buffett_index_history.csv',
}


def init_data_dir():
    """自动创建 data/ 目录。"""
    try:
        _os.makedirs(DATA_DIR, exist_ok=True)
    except Exception:
        pass


def _csv_path(key: str) -> str:
    fname = _CSV_HISTORY_FILES.get(key)
    if not fname:
        raise ValueError(f"未知 CSV key: {key}")
    return _os.path.join(DATA_DIR, fname)


def load_csv_history(key: str) -> pd.DataFrame:
    """读取历史 CSV，不存在则返回空 DataFrame。"""
    try:
        path = _csv_path(key)
        if _os.path.exists(path):
            df = pd.read_csv(path)
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'], errors='coerce')
                df = df.dropna(subset=['date']).sort_values('date').reset_index(drop=True)
            return df
    except Exception:
        pass
    return pd.DataFrame()


def append_csv_history(key: str, row: dict, dedup_by_date: bool = True) -> bool:
    """追加一行到 CSV。同一天重复时覆盖（保留最新值）。

    Returns:
        True 表示成功追加/更新；False 表示失败。
    """
    try:
        init_data_dir()
        path = _csv_path(key)
        existing = load_csv_history(key)
        new_df = pd.DataFrame([row])
        if dedup_by_date and 'date' in row and not existing.empty and 'date' in existing.columns:
            new_date = pd.to_datetime(row['date'])
            mask = pd.to_datetime(existing['date']) == new_date
            if mask.any():
                existing = existing[~mask].reset_index(drop=True)
        combined = pd.concat([existing, new_df], ignore_index=True)
        if 'date' in combined.columns:
            combined['date'] = pd.to_datetime(combined['date']).dt.strftime('%Y-%m-%d')
        combined.to_csv(path, index=False)
        return True
    except Exception:
        return False


# ============================================================
# v0.2 新增辅助: 百分位计算
# ============================================================
def calculate_percentile(value: float, history: pd.Series) -> float:
    """计算当前值在历史序列中的百分位排名 (0-100)。

    Returns:
        百分位 (0-100)；当历史数据不足或值为 None 时返回 None。
    """
    try:
        if value is None or history is None:
            return None
        h = pd.Series(history).dropna()
        if len(h) < 5:
            return None
        v = float(value)
        rank = (h < v).sum()
        return round(rank / len(h) * 100, 1)
    except Exception:
        return None


def calculate_multi_period_percentiles(value: float, history: pd.Series, periods: dict = None) -> dict:
    """对当前值计算多个时间窗口的百分位排名。

    Args:
        value: 当前值
        history: 完整历史序列 (pd.Series, index 应为 datetime)
        periods: dict, e.g. {'1Y': 365, '3Y': 365*3, '5Y': 365*5, 'All': None}
                 None 表示全部历史

    Returns:
        dict: {'1Y': 12.3, '3Y': 45.6, '5Y': 78.9, 'All': 50.0}
              失败的窗口值为 None
    """
    if periods is None:
        periods = {'1Y': 365, '3Y': 365 * 3, '5Y': 365 * 5, 'All': None}
    if value is None or history is None or len(history) == 0:
        return {k: None for k in periods}

    result = {}
    if not isinstance(history.index, pd.DatetimeIndex):
        try:
            history = history.copy()
            history.index = pd.to_datetime(history.index)
        except Exception:
            return {k: None for k in periods}

    latest_date = history.index.max()

    for label, days in periods.items():
        try:
            if days is None:
                window = history
            else:
                cutoff = latest_date - pd.Timedelta(days=days)
                window = history[history.index >= cutoff]
            result[label] = calculate_percentile(value, window)
        except Exception:
            result[label] = None
    return result


# ============================================================
# 页面主体
# ============================================================
st.title("📊 Global Financial Dashboard")
st.caption("全球金融市场每日仪表盘 · 数据保真 · 口径透明")

# ---- 顶部栏 ----
top_c1, top_c2, top_c3 = st.columns([3, 2, 1])
with top_c1:
    st.write(f"**页面加载时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
with top_c2:
    st.write("**数据状态:** 加载中…")
with top_c3:
    if st.button("🔄 刷新数据", type="primary"):
        st.cache_data.clear()
        st.rerun()

st.divider()

# ---- 抓取所有数据 ----
with st.spinner("正在获取全球金融数据…"):
    treasury = fetch_treasury_yields()
    btc = fetch_btc()
    gold = fetch_gold()
    csi300 = fetch_csi300()
    cn_bond = fetch_china_bond()
    news = fetch_news()

# ---- 计算衍生指标 ----
btc_gold_ratio = calc_btc_gold_ratio(
    btc.get('market_cap'), gold.get('market_cap')
) if btc['success'] and gold['success'] else None

equity_bond_spread = None
if csi300['success'] and cn_bond['success']:
    ey = csi300.get('earnings_yield')
    cn10 = cn_bond.get('cn_10y')
    if ey is not None and cn10 is not None:
        equity_bond_spread = ey - cn10

# ---- v0.2 新增模块数据抓取 ----
buffett = fetch_buffett_index()
margin_debt = fetch_margin_debt()
us_sector_turn = fetch_us_sector_turnover()
china_sector_turn = fetch_china_sector_turnover()
china_sector_turn_hist = fetch_china_sector_turnover_history()
fedwatch = fetch_fedwatch()
fedwatch_hist = fetch_fedwatch_history()
china_eq_bond = fetch_china_equity_bond_spread_history()
btc_gold_v2 = fetch_btc_gold_ratio_with_history()
us_yield_hist = fetch_us_yield_curve_history_csv()

# ---- 数据状态汇总 ----
_src_status = {
    '美债收益率': treasury['success'],
    'BTC': btc['success'],
    '黄金': gold['success'],
    '沪深300': csi300['success'],
    '中国国债': cn_bond['success'],
    '新闻': news['success'],
    # v0.2
    '巴菲特指数': buffett.get('success', False),
    'A股行业集中度': china_sector_turn.get('success', False),
    'CME FedWatch': fedwatch.get('success', False),
    '中国股债利差': china_eq_bond.get('success', False),
    'BTC/金价比': btc_gold_v2.get('success', False),
    '美债历史': us_yield_hist.get('success', False),
}
_ok = sum(_src_status.values())
_total = len(_src_status)
if _ok == _total:
    _status = f"✅ {_ok}/{_total} 数据源正常"
else:
    _failed = [k for k, v in _src_status.items() if not v]
    _status = f"⚠️ {_ok}/{_total} 正常 · 失败: {', '.join(_failed)}"
top_c2.write(f"**数据状态:** {_status}")

# ============================================================
# 核心指标卡片
# ============================================================
st.subheader("📌 核心指标速览")
mc1, mc2, mc3, mc4 = st.columns(4)

with mc1:
    if treasury['success'] and treasury['yields'].get('10Y') is not None:
        st.metric("美债 10Y", f"{treasury['yields']['10Y']:.2f}%")
    else:
        st.metric("美债 10Y", "N/A")
    sp_2y10y = calc_spread(treasury['yields'], '2Y', '10Y') if treasury['success'] else None
    st.metric("2Y-10Y 利差", f"{sp_2y10y:.2f}%" if sp_2y10y is not None else "N/A")

with mc2:
    if csi300['success']:
        st.metric("沪深 300", f"{csi300['price']:,.2f}")
    else:
        st.metric("沪深 300", "N/A")
    if cn_bond['success'] and cn_bond.get('cn_10y') is not None:
        st.metric("中国 10Y 国债", f"{cn_bond['cn_10y']:.2f}%")
    else:
        st.metric("中国 10Y 国债", "N/A")

with mc3:
    if btc['success']:
        st.metric("BTC", f"${btc['price']:,.0f}", f"{btc['change_24h']:.2f}%")
    else:
        st.metric("BTC", "N/A")
    if gold['success']:
        st.metric("黄金", f"${gold['price']:,.2f}")
    else:
        st.metric("黄金", "N/A")

with mc4:
    if btc_gold_ratio is not None:
        st.metric("BTC/黄金市值比", f"{btc_gold_ratio:.4f}")
    else:
        st.metric("BTC/黄金市值比", "N/A")
    if equity_bond_spread is not None:
        st.metric("股债利差 E/P-10Y", f"{equity_bond_spread:.2f}%")
    else:
        st.metric("股债利差", "N/A")

st.divider()

# ============================================================
# 1. 全球新闻
# ============================================================
st.header("📰 全球重要金融新闻")

if news['success']:
    for i, item in enumerate(news['items'], 1):
        st.markdown(f"**{i}. [{item['title']}]({item['link']})**")
        st.write(f"📌 来源: {item['source']}　🕐 {item['published']}")
        st.write(f"📝 {item['summary']}")
        if i < len(news['items']):
            st.divider()
    with st.expander("📋 新闻数据源说明"):
        st.info(
            "- **数据源**: CNBC / Google News / NPR Business / MarketWatch (RSS)\n"
            "- **排序**: 按发布时间倒序（非市场重要性排序）\n"
            "- **摘要**: RSS feed 原始描述，非 AI 生成\n"
            "- **限制**: 中文摘要需接入翻译/LLM API（v0.2 计划）"
        )
else:
    st.warning("⚠️ 新闻数据暂不可用，请稍后刷新重试。")

st.divider()

# ============================================================
# 2. 美国市场
# ============================================================
st.header("🇺🇸 美国市场")
st.subheader("美国国债收益率曲线")

if treasury['success']:
    yt = treasury['yields']
    cmps = treasury['comparisons']

    # --- 收益率曲线图 ---
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=MATURITIES, y=[yt.get(m) for m in MATURITIES],
        mode='lines+markers',
        name=f"今日 ({treasury['latest_date'].strftime('%m/%d')})",
        line=dict(width=3, color='#1f77b4'),
    ))
    _comp_cfg = [
        ('yesterday', '昨日', '#ff7f0e'),
        ('1_week', '1周前', '#2ca02c'),
        ('1_month', '1月前', '#d62728'),
    ]
    for key, label, color in _comp_cfg:
        c = cmps.get(key)
        if c:
            ds = c['date'].strftime('%m/%d') if hasattr(c['date'], 'strftime') else str(c['date'])
            fig.add_trace(go.Scatter(
                x=MATURITIES, y=[c['yields'].get(m) for m in MATURITIES],
                mode='lines+markers', name=f"{label} ({ds})",
                line=dict(width=1.5, color=color, dash='dash'),
            ))
    fig.update_layout(
        title="美国国债收益率曲线", xaxis_title="期限",
        yaxis_title="收益率 (%)", height=420, hovermode='x unified',
    )
    st.plotly_chart(fig, use_container_width=True)

    # --- 关键利差 ---
    sc1, sc2, sc3 = st.columns(3)
    _s_2y10y = calc_spread(yt, '2Y', '10Y')
    _s_3m10y = calc_spread(yt, '3M', '10Y')
    _s_10y30y = calc_spread(yt, '10Y', '30Y')

    with sc1:
        st.metric("2Y-10Y 利差", f"{_s_2y10y:.2f}%" if _s_2y10y is not None else "N/A")
        if _s_2y10y is not None and _s_2y10y < 0:
            st.warning("⚠️ 2Y-10Y 倒挂")
    with sc2:
        st.metric("3M-10Y 利差", f"{_s_3m10y:.2f}%" if _s_3m10y is not None else "N/A")
        if _s_3m10y is not None and _s_3m10y < 0:
            st.warning("⚠️ 3M-10Y 倒挂")
    with sc3:
        st.metric("10Y-30Y 利差", f"{_s_10y30y:.2f}%" if _s_10y30y is not None else "N/A")

    # --- 收益率明细表 ---
    _tbl = {'期限': MATURITIES, '今日 (%)': [yt.get(m) for m in MATURITIES]}
    if cmps.get('yesterday'):
        _tbl['昨日 (%)'] = [cmps['yesterday']['yields'].get(m) for m in MATURITIES]
    if cmps.get('1_week'):
        _tbl['1周前 (%)'] = [cmps['1_week']['yields'].get(m) for m in MATURITIES]
    if cmps.get('1_month'):
        _tbl['1月前 (%)'] = [cmps['1_month']['yields'].get(m) for m in MATURITIES]
    st.dataframe(pd.DataFrame(_tbl), use_container_width=True, hide_index=True)

    with st.expander("📋 数据源与口径说明"):
        st.info(
            f"- **数据源**: U.S. Department of the Treasury\n"
            f"- **频率**: 日频（每个工作日）\n"
            f"- **最新日期**: {treasury['latest_date'].strftime('%Y-%m-%d')}\n"
            f"- **口径**: Par Yield（票面收益率），非 Zero-Coupon Yield\n"
            f"- **利差公式**: 长期收益率 − 短期收益率\n"
            f"- **倒挂**: 短期 > 长期（利差为负）\n"
            f"- **URL**: home.treasury.gov/resource-center/data-chart-center/interest-rates/\n"
            f"- **限制**: 仅当年数据；非工作日无数据；部分期限可能缺失"
        )
else:
    st.error(f"⚠️ 美国国债收益率数据获取失败: {treasury.get('error', 'Unknown')}")

st.divider()

# ============================================================
# 3. 中国市场
# ============================================================
st.header("🇨🇳 中国市场")
st.subheader("沪深300与股债利差")

cn_col1, cn_col2 = st.columns(2)

with cn_col1:
    if csi300['success']:
        st.metric("沪深300指数", f"{csi300['price']:,.2f}")
        if csi300.get('pe') is not None:
            st.metric("沪深300 PE (TTM)", f"{csi300['pe']:.2f}")
            if csi300.get('earnings_yield') is not None:
                st.metric("盈利收益率 E/P", f"{csi300['earnings_yield']:.2f}%")
        else:
            st.info("PE 数据暂不可用")

        if csi300.get('history') is not None:
            h = csi300['history']
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=h.index, y=h['Close'], mode='lines', name='CSI 300',
                line=dict(color='#e74c3c', width=2),
            ))
            fig.update_layout(
                title="沪深300指数走势（近1年）",
                xaxis_title="日期", yaxis_title="指数", height=320,
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.error(f"⚠️ 沪深300数据获取失败: {csi300.get('error', 'Unknown')}")

with cn_col2:
    if cn_bond['success']:
        st.metric("中国10年国债收益率", f"{cn_bond['cn_10y']:.2f}%")
        if cn_bond.get('cn_2y') is not None:
            st.metric("中国2年国债收益率", f"{cn_bond['cn_2y']:.2f}%")
            st.metric("10Y-2Y 利差", f"{cn_bond['cn_10y'] - cn_bond['cn_2y']:.2f}%")
        st.write(f"**最新数据日期:** {cn_bond['latest_date']}")
        if cn_bond.get('us_10y') is not None:
            st.write(f"**交叉验证 · 美债10Y (akshare):** {cn_bond['us_10y']:.2f}%")
    else:
        st.error(f"⚠️ 中国国债收益率获取失败: {cn_bond.get('error', 'Unknown')}")

# 股债利差
st.write("---")
st.write("**股债利差**")
if equity_bond_spread is not None:
    st.metric(
        "股债利差 (盈利收益率 − 10Y国债)",
        f"{equity_bond_spread:.2f}%",
        help="盈利收益率 E/P = 1/PE × 100%，减去中国10年国债收益率",
    )
    st.info(
        f"**计算公式:** 股债利差 = 沪深300盈利收益率(E/P) − 中国10年国债收益率\n\n"
        f"**当前值:** {csi300.get('earnings_yield', 0):.2f}% − "
        f"{cn_bond.get('cn_10y', 0):.2f}% = **{equity_bond_spread:.2f}%**\n\n"
        f"**PE数据日期:** {csi300.get('pe_date', 'N/A')}"
    )
else:
    st.warning("⚠️ 股债利差暂不可用（需要沪深300 PE 和中国10年国债收益率）")

with st.expander("📋 数据源与口径说明"):
    st.info(
        "**沪深300指数:**\n"
        "- 数据源: yfinance (000300.SS)\n"
        "- 频率: 日频\n\n"
        "**沪深300 PE:**\n"
        "- 数据源: akshare (韭圈儿 stock_index_pe_lg)\n"
        "- 口径: 滚动市盈率 (TTM PE)\n\n"
        "**中国10年国债收益率:**\n"
        "- 数据源: akshare (bond_zh_us_rate)\n"
        "- 频率: 日频\n"
        "- 交叉验证: 同时返回美债收益率数据\n\n"
        "**股债利差:**\n"
        "- 公式: 盈利收益率(E/P) − 10年国债收益率\n"
        "- E/P = 1/PE × 100%\n"
        "- 注意: 使用盈利收益率口径，非股息率口径\n"
        "- 历史百分位: v0.2 计划实现"
    )

st.divider()

# ============================================================
# 4. 大类资产
# ============================================================
st.header("💎 大类资产")

# --- BTC ---
st.subheader("Bitcoin (BTC)")
if btc['success']:
    bc1, bc2, bc3, bc4 = st.columns(4)
    bc1.metric("BTC 价格", f"${btc['price']:,.0f}", f"{btc['change_24h']:.2f}%")
    bc2.metric("BTC 市值", f"${btc['market_cap'] / 1e9:.2f}B")
    bc3.metric("24h 涨跌幅", f"{btc['change_24h']:.2f}%")
    bc4.metric("24h 成交额", f"${btc['volume_24h'] / 1e9:.2f}B")

    if btc.get('history') is not None:
        h = btc['history']
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=h.index, y=h['Close'], mode='lines', name='BTC',
            line=dict(color='#f7931a', width=2),
        ))
        fig.update_layout(
            title="BTC 价格走势（近1年）",
            xaxis_title="日期", yaxis_title="价格 (USD)", height=320,
        )
        st.plotly_chart(fig, use_container_width=True)
else:
    st.error(f"⚠️ BTC 数据获取失败: {btc.get('error', 'Unknown')}")

st.write("")

# --- 黄金 ---
st.subheader("黄金 Gold (XAU/USD)")
if gold['success']:
    gc1, gc2 = st.columns(2)
    gc1.metric("黄金价格", f"${gold['price']:,.2f}/oz")
    gc2.metric("黄金估算市值", f"${gold['market_cap'] / 1e12:.2f}T")

    st.info(
        f"**黄金市值估算公式:**\n\n"
        f"黄金市值 = 地上黄金存量 × 每盎司金价\n\n"
        f"= {GOLD_ABOVE_GROUND_TONNES:,} 吨 × {TROY_OZ_PER_TONNE:,.1f} oz/吨 "
        f"× ${gold['price']:,.2f}/oz\n\n"
        f"= ${gold['market_cap']:,.0f}\n\n"
        f"**注意:** 地上黄金存量为 World Gold Council 年度估算值，非每日实时变化"
    )

    if gold.get('history') is not None:
        h = gold['history']
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=h.index, y=h['Close'], mode='lines', name='Gold',
            line=dict(color='#daa520', width=2),
        ))
        fig.update_layout(
            title="黄金价格走势（近1年）",
            xaxis_title="日期", yaxis_title="价格 (USD/oz)", height=320,
        )
        st.plotly_chart(fig, use_container_width=True)
else:
    st.error(f"⚠️ 黄金数据获取失败: {gold.get('error', 'Unknown')}")

st.write("")

# --- BTC / 黄金 ---
st.subheader("BTC / 黄金总市值比值")
if btc_gold_ratio is not None:
    st.metric("BTC / 黄金市值比", f"{btc_gold_ratio:.4f}")
    st.metric("百分比", f"{btc_gold_ratio * 100:.2f}%")

    st.info(
        f"**计算公式:**\n\n"
        f"BTC/黄金 = BTC市值 / 黄金市值\n\n"
        f"= ${btc['market_cap'] / 1e9:.2f}B / ${gold['market_cap'] / 1e12:.2f}T\n\n"
        f"= {btc_gold_ratio:.4f}\n\n"
        f"**注意:** 黄金市值为估算值（年度存量），BTC市值为实时值，精度不同\n"
        f"**历史百分位:** v0.2 计划实现"
    )

    # 历史走势
    if btc.get('history') is not None and gold.get('history') is not None:
        btc_s = btc['history']['Close']
        gold_s = gold['history']['Close']
        common = btc_s.index.intersection(gold_s.index)
        if len(common) > 5:
            ba = btc_s.loc[common]
            ga = gold_s.loc[common]
            ratio_hist = (ba * BTC_SUPPLY) / (ga * GOLD_TOTAL_OZ)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=ratio_hist.index, y=ratio_hist.values,
                mode='lines', name='BTC/Gold',
                line=dict(color='#9b59b6', width=2),
            ))
            fig.update_layout(
                title="BTC/黄金市值比走势（近1年）",
                xaxis_title="日期", yaxis_title="比值", height=320,
            )
            st.plotly_chart(fig, use_container_width=True)
else:
    st.warning("⚠️ BTC/黄金市值比暂不可用（需要 BTC 和黄金数据）")

with st.expander("📋 数据源与口径说明"):
    st.info(
        "**BTC:**\n"
        "- 当前: CoinGecko API（价格、市值、24h涨跌幅、成交额）\n"
        "- 历史: yfinance (BTC-USD)\n"
        "- 市值: CoinGecko 实时返回值\n"
        "- 历史图表中 BTC 流通量按近似值 1970万 计算\n\n"
        "**黄金:**\n"
        "- 数据源: yfinance (GC=F, COMEX黄金期货)\n"
        "- 注意: GC=F 为期货价格，与现货 XAU/USD 可能有微小差异\n"
        "- 市值: 地上存量(216,265吨, WGC) × 金价\n"
        "- 地上存量为年度估算，非每日更新\n\n"
        "**BTC/黄金市值比:**\n"
        "- 公式: BTC市值 / 黄金市值\n"
        "- 黄金市值精度(年度估算) < BTC市值精度(链上实时)"
    )

st.divider()

# ============================================================
# 5. v0.2 新增模块（巴菲特/Margin/行业集中度/CME FedWatch）
# ============================================================

# ---------- 5.1 巴菲特指数 ----------
st.header("📊 v0.2 新增：全球资产估值")
st.subheader("巴菲特指数 (Wilshire 5000 总市值 / GDP)")

if buffett.get('success'):
    bk1, bk2, bk3 = st.columns(3)
    bk1.metric("Wilshire 5000 总市值",
               f"${buffett['w5000_market_cap_t']:,.2f}T",
               help=f"≈ {buffett['w5000_market_cap_b']:,.0f} 十亿美元")
    bk2.metric("美国名义 GDP (季度)",
               f"${buffett['gdp_billions_usd']:,.0f}B",
               buffett.get('gdp_period', ''))
    bk3.metric("巴菲特指数",
               f"{buffett['buffett_pct']:.2f}%",
               help="Wilshire 5000 总市值 ÷ 季度名义GDP (BEA 季调现价)")

    # 加载历史并计算百分位
    history_df = load_csv_history('buffett_index_history')
    pctls = None
    if history_df is not None and len(history_df) > 5:
        if 'buffett_pct' in history_df.columns:
            hist_series = history_df['buffett_pct'].dropna().astype(float)
            pctls = calculate_multi_period_percentiles(buffett['buffett_pct'], hist_series)

    if pctls:
        pc1, pc2, pc3, pc4 = st.columns(4)
        pc1.metric("1Y 百分位", f"{pctls.get('1Y', 0):.1f}%")
        pc2.metric("3Y 百分位", f"{pctls.get('3Y', 0):.1f}%")
        pc3.metric("5Y 百分位", f"{pctls.get('5Y', 0):.1f}%")
        pc4.metric("All 百分位", f"{pctls.get('All', 0):.1f}%")

    if history_df is not None and len(history_df) > 1 and 'buffett_pct' in history_df.columns:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=history_df['date'], y=history_df['buffett_pct'],
            mode='lines+markers', name='Buffett Index',
            line=dict(color='#e67e22', width=2),
        ))
        fig.update_layout(
            title="巴菲特指数历史走势 (本地 CSV)",
            xaxis_title="日期", yaxis_title="指数 (%)", height=320,
        )
        st.plotly_chart(fig, use_container_width=True)

    st.caption(f"📌 {buffett.get('note', '')}")
    st.caption(f"🔗 数据源: {buffett.get('source', '')}")
    st.markdown(f"📎 参考网站: [longtermtrends.com]({buffett.get('reference_url', '')})")
else:
    st.error(f"⚠️ 巴菲特指数数据获取失败: {buffett.get('error', 'Unknown')}")
    st.caption(f"🔗 {buffett.get('source', '')}")
    st.markdown("📎 参考网站: [longtermtrends.com](https://www.longtermtrends.com/market-cap-to-gdp-the-buffett-indicator/)")

st.write("---")

# ---------- 5.2 FINRA Margin Debt ----------
st.subheader("FINRA Margin Debt（融资融券余额）")
if margin_debt.get('unavailable'):
    st.info(margin_debt.get('error', 'FINRA Margin Debt 暂不可用'))
    st.caption(f"🔗 {margin_debt.get('source', '')}")
    st.markdown(f"📎 查看: [FINRA 官方]({margin_debt.get('reference_url', '')})")
else:
    st.json(margin_debt)

st.write("---")

# ---------- 5.3 美国行业成交集中度 ----------
st.subheader("美国行业成交集中度")
if us_sector_turn.get('unavailable'):
    st.info(us_sector_turn.get('error', '美股行业成交集中度暂不可用'))
    st.caption(f"🔗 {us_sector_turn.get('source', '')}")
    st.markdown(f"📎 查看: [TradingView Sectors]({us_sector_turn.get('reference_url', '')})")
else:
    st.dataframe(us_sector_turn.get('data', pd.DataFrame()), use_container_width=True)

st.write("---")

# ---------- 5.4 A股行业成交集中度 (申万一级 2021) ----------
st.subheader("A股行业成交集中度（申万一级 2021）")
st.caption("📐 计算口径: 每日按 31 个申万一级行业汇总成交额, 取占比最高的行业"
           "作为\"最大行业成交集中度\"。历史百分位是\"每日最大行业占比\"时间序列"
           "(不固定行业), 数据源: Tushare Pro sw_daily > AkShare 申万 > 全A+groupby。")

if china_sector_turn.get('success'):
    cst = china_sector_turn
    if cst.get('df') is not None and not cst['df'].empty:
        df_sorted = cst['df']  # 已按 turnover_yi 降序, 已含 share_pct / cumulative_pct
        total = cst['total_turnover_yi']
        top1_name = cst.get('top1_industry', '—')
        top1_pct = cst.get('top1_pct', 0)
        top5_pct = cst.get('top5_pct', 0)
        hhi = cst.get('hhi', 0)
        industry_count = cst.get('industry_count', 0)

        # 顶部 metrics — 把"最大行业成交集中度"放最显眼位置
        cs0, cs1, cs2, cs3 = st.columns([2, 2, 1.5, 1.5])
        cs0.metric(
            "🎯 最大行业成交集中度",
            f"{top1_pct:.2f}%",
            f"{top1_name} (申万一级)",
            help="当天成交额占比最高的申万一级行业, 数值=该行业成交额/A股总成交额×100",
        )
        cs1.metric("Top 5 行业累计占比", f"{top5_pct:.2f}%",
                   help="当天成交额前 5 名行业占 A股总成交额比例")
        cs2.metric("全市场成交额", f"{total:,.0f} 亿元")
        cs3.metric("行业 HHI", f"{hhi:,.0f}",
                   help="行业成交额 HHI 指数 (0–10000), 越高越集中")

        st.write(f"**当日 {industry_count} 个申万一级行业成交额排序 (Top 10):**")
        st.dataframe(
            df_sorted.head(10)[['industry_name', 'turnover_yi', 'price', 'share_pct', 'cumulative_pct']]
            .rename(columns={
                'industry_name': '行业',
                'turnover_yi': '成交额(亿元)',
                'price': '指数点位',
                'share_pct': '占比(%)',
                'cumulative_pct': '累计占比(%)',
            }),
            use_container_width=True, hide_index=True,
        )

        # Bar chart: Top 15
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df_sorted.head(15)['industry_name'],
            y=df_sorted.head(15)['turnover_yi'],
            marker_color=['#e74c3c' if i == 0 else '#3498db' for i in range(min(15, len(df_sorted)))],
            text=[f"{v:,.0f}" for v in df_sorted.head(15)['turnover_yi']],
            textposition='outside',
        ))
        fig.update_layout(
            title="申万一级行业成交额 (Top 15, 亿元, 红色=最大行业)",
            xaxis_title="行业", yaxis_title="成交额 (亿元)",
            height=400, xaxis_tickangle=-45,
        )
        st.plotly_chart(fig, use_container_width=True)

        # 历史百分位: 每日 Top 1 行业占比 (不固定行业)
        if china_sector_turn_hist.get('success'):
            hist = load_csv_history('china_sector_turnover_concentration')
            if hist is not None and len(hist) > 5:
                hist_sorted = hist.sort_values(['date', 'turnover_yi'], ascending=[True, False])
                top1_by_day = hist_sorted.groupby('date').agg(
                    top1_share=('turnover_yi', lambda x: x.iloc[0] / x.sum() * 100),
                    top5_share=('turnover_yi', lambda x: x.head(5).sum() / x.sum() * 100),
                ).reset_index()
                top1_series = top1_by_day['top1_share']
                top1_pctls = calculate_multi_period_percentiles(top1_pct, top1_series)
                top5_pctls = calculate_multi_period_percentiles(top5_pct, top1_by_day['top5_share'])
                if top1_pctls:
                    st.write("**当日最大行业占比 在历史上的位置 (1Y / 3Y / 5Y / All 百分位):**")
                    tk1, tk2, tk3, tk4 = st.columns(4)
                    tk1.metric("Top1 占比 · 1Y", f"{top1_pctls.get('1Y', 0):.1f}%")
                    tk2.metric("Top1 占比 · 3Y", f"{top1_pctls.get('3Y', 0):.1f}%")
                    tk3.metric("Top1 占比 · 5Y", f"{top1_pctls.get('5Y', 0):.1f}%")
                    tk4.metric("Top1 占比 · All", f"{top1_pctls.get('All', 0):.1f}%")

                if len(top1_by_day) > 5:
                    fig2 = go.Figure()
                    fig2.add_trace(go.Scatter(
                        x=top1_by_day['date'], y=top1_by_day['top1_share'],
                        mode='lines', name='每日最大行业占比(%)',
                        line=dict(color='#e74c3c', width=1.5),
                    ))
                    fig2.add_trace(go.Scatter(
                        x=top1_by_day['date'], y=top1_by_day['top5_share'],
                        mode='lines', name='每日 Top 5 累计占比(%)',
                        line=dict(color='#3498db', width=1.5),
                    ))
                    fig2.update_layout(
                        title="申万一级行业成交集中度历史 (本地 CSV)",
                        xaxis_title="日期", yaxis_title="占比 (%)", height=320,
                    )
                    st.plotly_chart(fig2, use_container_width=True)

                st.caption(f"📊 历史样本数: {len(top1_by_day)} 天 (来自本地 CSV, "
                           f"覆盖 {pd.to_datetime(top1_by_day['date']).min().date()} ~ "
                           f"{pd.to_datetime(top1_by_day['date']).max().date()})")
        else:
            st.info("📥 历史 CSV 暂无数据 — 当前仅显示当日截面")

        st.caption(f"🔗 数据源: {cst.get('source', '')}")
        st.markdown("📎 参考: [申万行业指数 - 东方财富](http://www.swsindex.com/) | "
                    "[同花顺 - 申万一级行业](https://q.10jqka.com.cn/thsft/)")
    else:
        st.warning("申万一级行业成交额数据为空")
else:
    st.error(f"⚠️ A股行业成交集中度获取失败: {china_sector_turn.get('error', 'Unknown')}")
    st.caption(f"🔗 {china_sector_turn.get('source', '')}")
    st.markdown("📎 参考: [申万行业指数 - 东方财富](http://www.swsindex.com/) | "
                "[同花顺 - 申万一级行业](https://q.10jqka.com.cn/thsft/)")

st.write("---")

# ---------- 5.5 CME FedWatch 隐含利率 ----------
st.subheader("CME FedWatch — FOMC 隐含利率概率")

if fedwatch.get('success'):
    fw1, fw2 = st.columns(2)
    fw1.metric("当前 EFFR", f"{fedwatch.get('effr', 'N/A')}%")
    fw2.metric("当前目标区间", fedwatch.get('current_target', 'N/A'))

    meetings = fedwatch.get('meetings', [])
    if meetings:
        st.write(f"**未来 12 个 FOMC 会议隐含利率概率:**")

        # 构造表格: 行=会议日期, 列=目标利率, 值=概率
        all_targets = set()
        rows = []
        for m in meetings:
            row = {'FOMC 会议日期': m['date'], '合约': m.get('contract', '')}
            for tgt, prob in m.get('probabilities', {}).items():
                row[tgt] = prob
                all_targets.add(tgt)
            rows.append(row)
        df_meetings = pd.DataFrame(rows)
        # 排序
        all_targets = sorted(all_targets)
        cols = ['FOMC 会议日期', '合约'] + all_targets
        df_meetings = df_meetings[cols]
        st.dataframe(
            df_meetings.style.format({c: '{:.1f}%' for c in all_targets}, na_rep='-'),
            use_container_width=True, hide_index=True,
        )

        # 下次会议 7 天 lookback
        lookback = fedwatch_hist.get('next_meeting_lookback', []) if fedwatch_hist.get('success') else []
        if lookback:
            with st.expander(f"📈 下次会议 ({meetings[0]['date']}) 7 天 lookback"):
                df_lb = pd.DataFrame(lookback)
                st.dataframe(df_lb, use_container_width=True)

    st.caption(f"🔗 {fedwatch.get('source', '')}")
    st.markdown("📎 官网: [CME FedWatch Tool](https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html)")
else:
    st.error(f"⚠️ CME FedWatch 数据获取失败: {fedwatch.get('error', 'Unknown')}")
    st.caption(f"🔗 {fedwatch.get('source', '')}")
    st.markdown("📎 官网: [CME FedWatch Tool](https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html)")

st.write("---")

# ---------- 5.6 中国股债利差增强 ----------
st.subheader("中国股债利差 · 增强 (沪深300 E/P vs 10Y国债)")

if china_eq_bond.get('success'):
    ce1, ce2, ce3 = st.columns(3)
    ce1.metric("沪深300 PE (TTM)", f"{china_eq_bond['pe']:.2f}" if china_eq_bond.get('pe') else "N/A")
    ce2.metric("盈利收益率 E/P", f"{china_eq_bond['ep']:.2f}%" if china_eq_bond.get('ep') else "N/A")
    ce3.metric("中国 10Y 国债", f"{china_eq_bond['cn10y']:.2f}%" if china_eq_bond.get('cn10y') else "N/A")

    spread_ep = china_eq_bond.get('spread_ep')
    if spread_ep is not None:
        st.metric("**股债利差 (E/P − 10Y)**", f"{spread_ep:.2f}%",
                  help="沪深300盈利收益率 - 中国10年期国债收益率；正值越大股票相对债券越便宜")

        pctls = china_eq_bond.get('percentiles', {})
        if pctls:
            pc1, pc2, pc3, pc4 = st.columns(4)
            pc1.metric("1Y 百分位", f"{pctls.get('1Y', 0):.1f}%")
            pc2.metric("3Y 百分位", f"{pctls.get('3Y', 0):.1f}%")
            pc3.metric("5Y 百分位", f"{pctls.get('5Y', 0):.1f}%")
            pc4.metric("All 百分位", f"{pctls.get('All', 0):.1f}%")

    history_df = china_eq_bond.get('history')
    if history_df is not None and len(history_df) > 1:
        # 兼容 Series/DatetimeIndex 和 DataFrame 两种返回
        if isinstance(history_df, pd.Series):
            history_df = history_df.reset_index()
            history_df.columns = ['date', 'spread_ep'] + (
                list(history_df.columns[2:]) if len(history_df.columns) > 2 else []
            )
        else:
            history_df = history_df.reset_index() if 'date' not in history_df.columns else history_df
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=history_df['date'], y=history_df['spread_ep'],
            mode='lines', name='股债利差 (E/P − 10Y)',
            line=dict(color='#16a085', width=2),
        ))
        fig.update_layout(
            title="中国股债利差历史 (本地 CSV)",
            xaxis_title="日期", yaxis_title="利差 (%)", height=320,
        )
        st.plotly_chart(fig, use_container_width=True)

    st.caption(f"🔗 {china_eq_bond.get('source', '')}")
    st.markdown("📎 参考: [FED 股债利差 (Tengxun)](https://www.fedchina.com/risk-premium)")
else:
    st.error(f"⚠️ 中国股债利差数据获取失败: {china_eq_bond.get('error', 'Unknown')}")
    st.markdown("📎 参考: [FED 股债利差 (Tengxun)](https://www.fedchina.com/risk-premium)")

st.write("---")

# ---------- 5.7 BTC/金价比 增强 ----------
st.subheader("BTC/金价比 · 增强 (市值比 + 多周期百分位)")

if btc_gold_v2.get('success'):
    bg1, bg2 = st.columns(2)
    bg1.metric("BTC/金价比 (市值)", f"{btc_gold_v2['current_ratio']:.4f}")
    bg2.metric("百分比", f"{btc_gold_v2['current_ratio'] * 100:.2f}%")

    pctls = btc_gold_v2.get('percentiles', {})
    if pctls:
        pp1, pp2, pp3, pp4 = st.columns(4)
        pp1.metric("1Y 百分位", f"{pctls.get('1Y', 0):.1f}%")
        pp2.metric("3Y 百分位", f"{pctls.get('3Y', 0):.1f}%")
        pp3.metric("5Y 百分位", f"{pctls.get('5Y', 0):.1f}%")
        pp4.metric("All 百分位", f"{pctls.get('All', 0):.1f}%")

    history_df = btc_gold_v2.get('history')
    if history_df is not None and len(history_df) > 1:
        if isinstance(history_df, pd.Series):
            history_df = history_df.reset_index()
            history_df.columns = ['date', 'ratio'] + (
                list(history_df.columns[2:]) if len(history_df.columns) > 2 else []
            )
        else:
            history_df = history_df.reset_index() if 'date' not in history_df.columns else history_df
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=history_df['date'], y=history_df['ratio'],
            mode='lines', name='BTC/Gold 市值比',
            line=dict(color='#9b59b6', width=1.5),
        ))
        fig.update_layout(
            title="BTC/金价比历史 (5Y, yfinance)",
            xaxis_title="日期", yaxis_title="比值", height=320,
        )
        st.plotly_chart(fig, use_container_width=True)

    st.caption(f"🔗 {btc_gold_v2.get('source', '')}")
else:
    st.error(f"⚠️ BTC/金价比数据获取失败: {btc_gold_v2.get('error', 'Unknown')}")

st.write("---")

# ---------- 5.8 美债收益率历史百分位 ----------
st.subheader("美国国债收益率 · 历史百分位")

if us_yield_hist.get('success'):
    rows = us_yield_hist.get('rows')
    if not rows:
        # 兜底：从 CSV 历史读
        csv_df = load_csv_history('us_yield_curve_history')
        if not csv_df.empty and 'date' in csv_df.columns:
            rows = csv_df.to_dict('records')
    if rows:
        rows_df = pd.DataFrame(rows)
    else:
        rows_df = pd.DataFrame()
    if not rows_df.empty and 'date' in rows_df.columns:
        # rows 是 wide 格式: 每行一条 record, 列为 date/1M/3M/.../30Y/spread_2y10y
        pivot_df = rows_df.set_index('date').sort_index()
        # 关键期限
        key_mats = ['3M', '2Y', '5Y', '10Y', '30Y']
        # 主展示: 10Y
        if '10Y' in pivot_df.columns:
            s10 = pd.to_numeric(pivot_df['10Y'], errors='coerce').dropna()
            if len(s10) >= 30:
                cur_10y = s10.iloc[-1]
                p10 = calculate_multi_period_percentiles(cur_10y, s10)
                if p10:
                    yy1, yy2, yy3, yy4 = st.columns(4)
                    yy1.metric("10Y 当前", f"{cur_10y:.2f}%")
                    yy2.metric("1Y 百分位", f"{p10.get('1Y', 0):.1f}%")
                    yy3.metric("3Y 百分位", f"{p10.get('3Y', 0):.1f}%")
                    yy4.metric("5Y 百分位", f"{p10.get('5Y', 0):.1f}%")
        fig = go.Figure()
        plotted = 0
        for mm in key_mats:
            if mm in pivot_df.columns:
                col = pd.to_numeric(pivot_df[mm], errors='coerce').dropna()
                if len(col) >= 1:
                    fig.add_trace(go.Scatter(
                        x=col.index, y=col.values,
                        mode='lines', name=mm, line=dict(width=1.5),
                    ))
                    plotted += 1
        if plotted > 0:
            fig.update_layout(
                title="美国关键期限国债收益率历史 (本地 CSV)",
                xaxis_title="日期", yaxis_title="收益率 (%)", height=400,
            )
            st.plotly_chart(fig, use_container_width=True)
    st.caption(f"🔗 {us_yield_hist.get('source', '')}")
else:
    st.error(f"⚠️ 美债历史数据获取失败: {us_yield_hist.get('error', 'Unknown')}")

st.divider()

# ============================================================
# 7. 数据源总表
# ============================================================
st.header("📖 数据源与口径说明总表")

_source_df = pd.DataFrame({
    '指标': [
        '美债收益率曲线', 'BTC (当前)', 'BTC (历史)', '黄金价格',
        '沪深300指数', '沪深300 PE', '中国10Y国债',
        '全球新闻',
        # v0.2
        '巴菲特指数 (真实)', 'FINRA Margin Debt', '美股行业成交集中度',
        'A股行业成交集中度 (申万一级 2021)', 'CME FedWatch 隐含利率',
        '中国股债利差 (E/P-10Y) 增强', 'BTC/金价比 (市值) 增强',
        '美债收益率历史百分位',
    ],
    '数据源': [
        'Treasury.gov', 'CoinGecko API', 'yfinance (BTC-USD)',
        'yfinance (GC=F)', 'yfinance (000300.SS)', 'akshare (韭圈儿)',
        'akshare (bond_zh_us_rate)', 'RSS (CNBC/Google/NPR/MW)',
        # v0.2
        'yfinance (^W5000 全市场值) + FRED (GDP)', '暂不可用 (FINRA.org 需 JS)',
        '暂不可用 (无免费源)', 'Tushare sw_daily > AkShare index_realtime_sw > 全A+groupby',
        'cme-fedwatch (CME 30D Fed Funds settlements)',
        'akshare + 本地 CSV', 'yfinance + 本地 CSV', '本地 CSV (US Treasury Yield)',
    ],
    '频率': ['日频', '实时', '日频', '日频', '日频', '日频', '日频', '实时',
             '日频', '—', '—', '实时+日频', '实时+日频', '日频', '日频', '日频'],
    '免费': ['✅'] * 8 + ['✅', '—', '—', '✅', '✅', '✅', '✅', '✅'],
    '限制': [
        '仅当年数据', '可能限流', 'yfinance可能不稳定',
        'GC=F期货非现货', '可能延迟', '韭圈儿数据可能滞后',
        'akshare接口可能变化', '摘要为英文原文',
        # v0.2
        '^W5000 实际为全市场值口径 (非价格指数)', '需要 FRED API key', '美股端无免费源',
        '三级 fallback: Tushare积分2000+/AkShare/全A groupby',
        'chrome TLS 指纹绕过 IP 封禁',
        'PE 频率决定更新粒度', '5Y 历史', 'CSV 增量累积',
    ],
})
st.dataframe(_source_df, use_container_width=True, hide_index=True)

st.write("---")
st.write("**⚠️ 重要提醒:**")
st.write("- 所有数据均来自公开免费数据源，可能存在延迟或不稳定")
st.write("- 页面显示的数据日期为实际数据日期，非当前日期")
st.write("- 不编造数据，不硬编码金融数据，数据源不可用时如实标注")
st.write("- 如某项数据持续不可用，请检查网络连接或数据源是否变更")

st.write("---")
st.write(f"**Dashboard 最后加载时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
