#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日复盘数据抓取脚本
====================
对自选股抓取最近一个交易日的真实数据,生成 Markdown 数据包供大模型分析。

数据来源: AKShare (新浪/同花顺等公开数据; 默认不调用东方财富接口)
用法:     python3 daily_report.py [YYYYMMDD]
          python3 daily_report.py --watchlist 600519:贵州茅台,300750:宁德时代
          python3 daily_report.py --watchlist-file config/watchlist.json
          不带参数时自动取最近一个交易日。
输出:     ~/stock-agent/reports/report_YYYYMMDD.md (路径打印到 stdout)

每个数据项独立容错:某一项抓取失败不影响整体,失败项会在数据包中标注。
"""

import os
import json
import math
import sys
import time
import datetime as dt

import pandas as pd
import akshare as ak

from watchlist_config import DEFAULT_WATCHLIST, load_watchlist, market_prefix

# ============================================================
# 配置区
# ============================================================
NEWS_PER_STOCK = 8          # 每只股票抓取的新闻条数
OUTPUT_DIR = os.getenv(
    "STOCK_REPORT_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "reports")),
)
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROFILE_PATH = os.getenv("STOCK_PROFILE_FILE", os.path.join(ROOT_DIR, "config", "stock_profiles.json"))
ENABLE_EASTMONEY_OPTIONAL = os.getenv("STOCK_ENABLE_EASTMONEY", "1").lower() not in ("0", "false", "no")
ENABLE_FUND_FLOW_DETAIL = os.getenv("STOCK_FUND_FLOW_DETAIL", "0").lower() in ("1", "true", "yes")
REQUEST_INTERVAL = 1.0      # 每次接口调用间隔秒数,做个有礼貌的爬取者
# ============================================================


def log(msg):
    print(f"[daily_report] {msg}", file=sys.stderr)


def safe(fn, desc):
    """统一容错包装:失败返回 None 并记录原因。"""
    last_exc = None
    for attempt in range(1, 4):
        try:
            time.sleep(REQUEST_INTERVAL * attempt)
            return fn()
        except Exception as e:
            last_exc = e
            log(f"抓取失败({desc},第 {attempt}/3 次): {type(e).__name__}: {e}")
    return None


def get_trade_date(arg_date=None):
    """确定要分析的交易日:优先命令行参数,否则取最近一个交易日。"""
    cal = safe(lambda: ak.tool_trade_date_hist_sina(), "交易日历")
    today = dt.date.today()
    if cal is not None:
        dates = pd.to_datetime(cal["trade_date"]).dt.date
        past = sorted(d for d in dates if d <= today)
        if arg_date:
            target = dt.datetime.strptime(arg_date, "%Y%m%d").date()
            if target in set(dates):
                return target
            log(f"{arg_date} 不是交易日,改用最近交易日")
        return past[-1]
    # 日历接口失败时的兜底:回退到最近的工作日
    d = today if arg_date is None else dt.datetime.strptime(arg_date, "%Y%m%d").date()
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def fmt_yi(v):
    """金额格式化为亿元。"""
    try:
        return f"{float(v) / 1e8:.2f}亿"
    except (TypeError, ValueError):
        return "N/A"


def parse_cn_money(value):
    """Parse money strings like 1.23亿 or 456.7万 into yuan."""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text == "-":
        return None
    multiplier = 1.0
    if text.endswith("亿"):
        multiplier = 1e8
        text = text[:-1]
    elif text.endswith("万"):
        multiplier = 1e4
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def fmt_pct(v):
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return "N/A"


def fmt_signed_pct(v):
    try:
        if pd.isna(v):
            return "N/A"
        return f"{float(v):+.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def json_value(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except TypeError:
        pass
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    return v


def row_value(row, key):
    return json_value(row.get(key))


def market_symbol(code):
    return market_prefix(code) + code


def cumulative_return(rows):
    value = 1.0
    got = False
    for row in rows:
        pct = row.get("涨跌幅") if hasattr(row, "get") else row.get("pct_change")
        try:
            if pd.isna(pct):
                continue
            value *= 1 + float(pct) / 100
            got = True
        except (TypeError, ValueError):
            continue
    return (value - 1) * 100 if got else None


def close_position(rows):
    closes = []
    for row in rows:
        close = row.get("收盘") if hasattr(row, "get") else row.get("close")
        try:
            if not pd.isna(close):
                closes.append(float(close))
        except (TypeError, ValueError):
            continue
    if not closes:
        return None
    low = min(closes)
    high = max(closes)
    if high == low:
        return 0.5
    return (closes[-1] - low) / (high - low)


def mean_numeric(values):
    nums = []
    for value in values:
        try:
            if not pd.isna(value):
                nums.append(float(value))
        except (TypeError, ValueError):
            continue
    if not nums:
        return None
    return sum(nums) / len(nums)


def pct_distance(value, base):
    try:
        if value is None or base in (None, 0) or pd.isna(value) or pd.isna(base):
            return None
        return (float(value) / float(base) - 1) * 100
    except (TypeError, ValueError):
        return None


def as_float(value, default=0.0):
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def load_stock_profiles(path=PROFILE_PATH):
    """Load optional stock profiles used for industry/theme attribution."""
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    result = {}
    if not isinstance(data, dict):
        return result
    profiles = data.get("profiles", data)
    if not isinstance(profiles, dict):
        return result
    for code, raw in profiles.items():
        if not isinstance(raw, dict):
            continue
        code = str(code).strip().zfill(6)
        industry = str(raw.get("industry") or "").strip()
        concepts = [str(x).strip() for x in raw.get("concepts", []) if str(x).strip()]
        keywords = [str(x).strip() for x in raw.get("keywords", []) if str(x).strip()]
        aliases = [str(x).strip() for x in raw.get("industry_aliases", []) if str(x).strip()]
        result[code] = {
            "status": "ok" if industry or concepts or keywords else "empty",
            "industry": industry,
            "industry_aliases": aliases,
            "concepts": concepts,
            "keywords": keywords,
            "source": os.path.abspath(path),
        }
    return result


def stock_profile(code, name, profiles):
    profile = dict(profiles.get(code) or {})
    if not profile:
        return {
            "status": "watchlist_only",
            "industry": "",
            "industry_aliases": [],
            "concepts": [],
            "keywords": [name, code],
            "source": "",
        }
    keywords = sorted(set([name, code] + profile.get("keywords", []) + profile.get("concepts", [])))
    profile["keywords"] = keywords
    profile.setdefault("industry_aliases", [])
    profile.setdefault("concepts", [])
    profile.setdefault("industry", "")
    profile.setdefault("status", "ok")
    return profile


def match_sector(profile, sector_df):
    if sector_df is None or not profile.get("industry"):
        return {"status": "missing", "reason": "未配置行业或行业快照不可用"}
    names = [profile.get("industry", "")] + list(profile.get("industry_aliases") or [])
    names = [x for x in names if x]
    for name in names:
        hit = sector_df[sector_df["板块名称"].astype(str) == name]
        if not hit.empty:
            row = hit.iloc[0]
            return {
                "status": "ok",
                "name": str(row["板块名称"]),
                "pct_change": row_value(row, "涨跌幅"),
                "source": "同花顺行业板块快照",
            }
    return {"status": "missing", "reason": "行业未匹配到同花顺板块快照", "name": profile.get("industry")}


def build_relative_metrics(hist, row, market_pct, industry_pct):
    if hist is None or row is None or hist.empty:
        return {"status": "failed", "reason": "行情历史不足"}
    metrics = {"status": "ok"}
    recent5 = hist.tail(5)
    recent10 = hist.tail(10)
    recent20 = hist.tail(20)
    metrics["return_5d"] = json_value(cumulative_return([r for _, r in recent5.iterrows()]))
    metrics["return_10d"] = json_value(cumulative_return([r for _, r in recent10.iterrows()])) if len(recent10) >= 10 else None
    metrics["return_20d"] = json_value(cumulative_return([r for _, r in recent20.iterrows()])) if len(recent20) >= 20 else None
    metrics["prev_4d_return"] = json_value(cumulative_return([r for _, r in recent5.iloc[:-1].iterrows()])) if len(recent5) >= 5 else None
    metrics["close_position_5d"] = json_value(close_position([r for _, r in recent5.iterrows()]))
    metrics["close_position_20d"] = json_value(close_position([r for _, r in recent20.iterrows()])) if len(recent20) >= 5 else None
    prev_amount_avg = mean_numeric(recent5.iloc[:-1]["成交额"]) if len(recent5) >= 2 and "成交额" in recent5 else None
    prev_volume_avg = mean_numeric(recent5.iloc[:-1]["成交量"]) if len(recent5) >= 2 and "成交量" in recent5 else None
    metrics["amount_vs_5d_avg_pct"] = json_value(pct_distance(row.get("成交额"), prev_amount_avg))
    metrics["volume_vs_5d_avg_pct"] = json_value(pct_distance(row.get("成交量"), prev_volume_avg))
    metrics["vs_market_pct"] = json_value(float(row.get("涨跌幅")) - float(market_pct)) if market_pct is not None else None
    metrics["vs_industry_pct"] = json_value(float(row.get("涨跌幅")) - float(industry_pct)) if industry_pct is not None else None
    return metrics


def classify_candidate(name, daily, metrics, lhb):
    if daily.get("status") != "ok" or metrics.get("status") != "ok":
        return {"status": "insufficient", "style": "数据不足", "score": None, "reasons": [], "risks": ["行情或指标缺失"]}
    pct = as_float(daily.get("pct_change"))
    turnover = as_float(daily.get("turnover"))
    amp = as_float(daily.get("amplitude"))
    ret5 = as_float(metrics.get("return_5d"))
    prev4 = as_float(metrics.get("prev_4d_return"))
    pos5 = metrics.get("close_position_5d")
    vs_market = as_float(metrics.get("vs_market_pct"))
    amount_vs = metrics.get("amount_vs_5d_avg_pct")
    score = 0.0
    score += vs_market * 1.5
    score += max(min(prev4, 8), -8) * 0.45
    if pos5 is not None:
        score += (pos5 - 0.5) * 4
    score += min(turnover, 12) * 0.12
    score -= max(ret5 - 15, 0) * 0.25
    risks = []
    reasons = []
    if vs_market > 1:
        reasons.append("当日相对大盘更强")
    if ret5 > 0:
        reasons.append("近5日累计为正")
    if pos5 is not None and pos5 >= 0.65:
        reasons.append("收盘处于近5日区间偏高位置")
    if amount_vs is not None and amount_vs > 50:
        reasons.append("成交额较近5日均值明显放大")
    if amount_vs is not None and amount_vs < -35:
        risks.append("成交额较近5日均值明显收缩")
    if amp and amp > 10:
        risks.append("当日振幅偏大")
    if lhb.get("hit"):
        risks.append("龙虎榜异动,次日分歧风险更高")
    if name.upper().startswith("*ST") or name.upper().startswith("ST"):
        risks.append("ST 标的风险更高")
        score -= 2
    if pct >= 9 and ret5 >= 15:
        style = "强势接力"
    elif pct > 0 and ret5 < -5:
        style = "跌深反抽"
    elif pct >= -1.5 and vs_market > 0 and ret5 >= 0:
        style = "稳健修复"
    elif pct < -4 and ret5 < 0:
        style = "弱势待确认"
    else:
        style = "观察"
    return {
        "status": "ok",
        "style": style,
        "score": json_value(score),
        "reasons": reasons or ["未形成明确优势信号"],
        "risks": risks,
    }


def stock_daily_sina(code, start, end):
    """新浪日线,字段转成统一格式。"""
    raw = safe(lambda: ak.stock_zh_a_daily(
        symbol=market_symbol(code), start_date=start, end_date=end, adjust="qfq"), f"{code} 新浪日线")
    if raw is None or raw.empty:
        return None
    df = raw.copy()
    df["日期"] = pd.to_datetime(df["date"]).dt.strftime("%Y%m%d")
    df["开盘"] = pd.to_numeric(df["open"], errors="coerce")
    df["最高"] = pd.to_numeric(df["high"], errors="coerce")
    df["最低"] = pd.to_numeric(df["low"], errors="coerce")
    df["收盘"] = pd.to_numeric(df["close"], errors="coerce")
    df["成交量"] = pd.to_numeric(df["volume"], errors="coerce")
    df["成交额"] = pd.to_numeric(df["amount"], errors="coerce")
    df["换手率"] = pd.to_numeric(df.get("turnover"), errors="coerce") * 100
    df["涨跌幅"] = df["收盘"].pct_change() * 100
    df["振幅"] = (df["最高"] - df["最低"]) / df["收盘"].shift(1) * 100
    return df[["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额", "换手率", "涨跌幅", "振幅"]].dropna(subset=["收盘"])


# ------------------------------------------------------------
# 各数据块
# ------------------------------------------------------------

def block_index_context(date_str):
    """大盘背景:主要指数当日表现。"""
    lines = ["## 大盘背景"]
    indexes = {"sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指"}
    got = False
    payload = []
    for code, name in indexes.items():
        df = safe(lambda c=code: ak.stock_zh_index_daily(symbol=c), f"指数 {name}")
        if df is None or df.empty:
            lines.append(f"- {name}: 数据获取失败")
            payload.append({"code": code, "name": name, "status": "failed"})
            continue
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y%m%d")
        row = df[df["date"] == date_str]
        if row.empty:
            lines.append(f"- {name}: 当日无数据")
            payload.append({"code": code, "name": name, "status": "missing"})
            continue
        row = row.iloc[0]
        idx = df.index[df["date"] == date_str][0]
        prev_close = df.loc[idx - 1, "close"] if idx > 0 else None
        pct = (row["close"] / prev_close - 1) * 100 if prev_close else None
        pct_s = f"{pct:+.2f}%" if pct is not None else "N/A"
        lines.append(f"- {name}: 收盘 {row['close']:.2f},涨跌幅 {pct_s}")
        payload.append({
            "code": code,
            "name": name,
            "status": "ok",
            "close": json_value(row["close"]),
            "pct_change": json_value(pct),
        })
        got = True
    if not got:
        lines.append("(大盘数据整体获取失败,归因时请忽略大盘因素)")
    return "\n".join(lines), payload


def block_sector_snapshot():
    """行业板块快照:领涨领跌各前5(注意:该接口为最新快照,收盘后运行即当日数据)。"""
    df = safe(lambda: ak.stock_board_industry_summary_ths(), "同花顺行业板块行情")
    lines = ["## 行业板块概览(收盘快照)"]
    source = "同花顺"
    if df is None or df.empty:
        lines.append("数据获取失败")
        return "\n".join(lines), None, {"status": "failed", "source": source, "top": [], "bottom": []}
    df = df.rename(columns={"板块": "板块名称"}).copy()
    df["涨跌幅"] = pd.to_numeric(df["涨跌幅"], errors="coerce")
    df = df.dropna(subset=["涨跌幅"])
    if df.empty:
        lines.append("数据获取失败")
        return "\n".join(lines), None, {"status": "failed", "source": source, "top": [], "bottom": []}
    df = df.sort_values("涨跌幅", ascending=False)
    top = df.head(5)
    bottom = df.tail(5)
    lines.append(f"数据源: {source}")
    lines.append("领涨行业: " + ",".join(
        f"{r['板块名称']}({r['涨跌幅']:+.2f}%)" for _, r in top.iterrows()))
    lines.append("领跌行业: " + ",".join(
        f"{r['板块名称']}({r['涨跌幅']:+.2f}%)" for _, r in bottom.iterrows()))
    payload = {
        "status": "ok",
        "source": source,
        "top": [
            {"name": str(r["板块名称"]), "pct_change": json_value(r["涨跌幅"])}
            for _, r in top.iterrows()
        ],
        "bottom": [
            {"name": str(r["板块名称"]), "pct_change": json_value(r["涨跌幅"])}
            for _, r in bottom.iterrows()
        ],
    }
    return "\n".join(lines), df, payload


def stock_daily_row(code, date_str):
    """个股当日 K 线行情。"""
    start = (dt.datetime.strptime(date_str, "%Y%m%d") - dt.timedelta(days=30)).strftime("%Y%m%d")
    df = stock_daily_sina(code, start, date_str)
    if df is None or df.empty:
        return None, None
    df["日期"] = pd.to_datetime(df["日期"]).dt.strftime("%Y%m%d")
    row = df[df["日期"] == date_str]
    if row.empty:
        return None, df
    return row.iloc[0], df


def date_to_yyyymmdd(value):
    try:
        return pd.to_datetime(value).strftime("%Y%m%d")
    except Exception:
        return ""


def block_fund_rank_snapshot():
    if not ENABLE_EASTMONEY_OPTIONAL:
        return None
    return safe(lambda: ak.stock_fund_flow_individual(symbol="即时"), "东方财富个股资金流排名")


def fund_flow_from_rank(code, date_str, fund_rank_df):
    if fund_rank_df is None or fund_rank_df.empty or "股票代码" not in fund_rank_df.columns:
        return None
    hit = fund_rank_df[fund_rank_df["股票代码"].astype(str).str.zfill(6) == code]
    if hit.empty:
        return None
    row = hit.iloc[0]
    net = parse_cn_money(row.get("净额"))
    amount = parse_cn_money(row.get("成交额"))
    inflow = parse_cn_money(row.get("流入资金"))
    outflow = parse_cn_money(row.get("流出资金"))
    net_pct = (net / amount * 100) if net is not None and amount else None
    return {
        "status": "ok",
        "source": "东方财富 stock_fund_flow_individual 即时排名",
        "date": date_str,
        "note": "备用源为最近交易日资金流快照,不含主力/大单拆分",
        "net_inflow": json_value(net),
        "net_inflow_pct": json_value(net_pct),
        "inflow": json_value(inflow),
        "outflow": json_value(outflow),
        "amount": json_value(amount),
        "main_net_inflow": None,
        "main_net_inflow_pct": None,
        "recent_5d": [],
    }


def block_fund_flow(code, date_str, fund_rank_df=None, allow_rank_fallback=False):
    """个股资金流。默认使用东方财富源,失败时显式标记。"""
    lines = ["## 资金流向"]
    if not ENABLE_EASTMONEY_OPTIONAL:
        payload = {"status": "disabled", "source": "东方财富", "reason": "STOCK_ENABLE_EASTMONEY=0"}
        lines.append("- 已禁用东方财富可选数据源")
        return "\n".join(lines), payload

    fallback = fund_flow_from_rank(code, date_str, fund_rank_df) if allow_rank_fallback else None
    if fallback and not ENABLE_FUND_FLOW_DETAIL:
        payload = fallback
        lines.append(
            f"- 资金净流入 {fmt_yi(payload['net_inflow'])},"
            f"净占比 {fmt_signed_pct(payload['net_inflow_pct'])}"
        )
        lines.append("- 快照源不含主力/大单拆分,归因时只能作为资金方向证据")
        return "\n".join(lines), payload

    df = safe(
        lambda: ak.stock_individual_fund_flow(stock=code, market=market_prefix(code)),
        f"{code} 东方财富个股资金流",
    )
    source = "东方财富 stock_individual_fund_flow"
    if df is None or df.empty:
        if fallback:
            payload = fallback
            lines.append(
                f"- 备用快照净流入 {fmt_yi(payload['net_inflow'])},"
                f"净占比 {fmt_signed_pct(payload['net_inflow_pct'])}"
            )
            lines.append("- 备用源不含主力/大单拆分,归因时只能作为弱证据")
            return "\n".join(lines), payload
        payload = {"status": "failed", "source": source, "reason": "接口无返回"}
        lines.append("- 获取失败")
        return "\n".join(lines), payload

    data = df.copy()
    data["日期_norm"] = data["日期"].map(date_to_yyyymmdd)
    row = data[data["日期_norm"] == date_str]
    if row.empty:
        fallback = fund_flow_from_rank(code, date_str, fund_rank_df) if allow_rank_fallback else None
        if fallback:
            payload = fallback
            lines.append(
                f"- 备用快照净流入 {fmt_yi(payload['net_inflow'])},"
                f"净占比 {fmt_signed_pct(payload['net_inflow_pct'])}"
            )
            lines.append("- 备用源不含主力/大单拆分,归因时只能作为弱证据")
            return "\n".join(lines), payload
        latest = data.tail(1).iloc[0] if not data.empty else None
        payload = {
            "status": "missing",
            "source": source,
            "reason": "目标交易日无资金流记录",
            "latest_date": row_value(latest, "日期_norm") if latest is not None else None,
        }
        lines.append("- 目标交易日无资金流记录")
        return "\n".join(lines), payload

    row = row.iloc[0]
    recent = data[data["日期_norm"] <= date_str].tail(5)
    recent_5d = [
        {
            "date": str(r["日期_norm"]),
            "main_net_inflow": row_value(r, "主力净流入-净额"),
            "main_net_inflow_pct": row_value(r, "主力净流入-净占比"),
        }
        for _, r in recent.iterrows()
    ]
    main_5d_sum = sum(float(x["main_net_inflow"] or 0) for x in recent_5d)
    payload = {
        "status": "ok",
        "source": source,
        "date": str(row["日期_norm"]),
        "main_net_inflow": row_value(row, "主力净流入-净额"),
        "main_net_inflow_pct": row_value(row, "主力净流入-净占比"),
        "super_large_net_inflow": row_value(row, "超大单净流入-净额"),
        "super_large_net_inflow_pct": row_value(row, "超大单净流入-净占比"),
        "large_net_inflow": row_value(row, "大单净流入-净额"),
        "large_net_inflow_pct": row_value(row, "大单净流入-净占比"),
        "medium_net_inflow": row_value(row, "中单净流入-净额"),
        "medium_net_inflow_pct": row_value(row, "中单净流入-净占比"),
        "small_net_inflow": row_value(row, "小单净流入-净额"),
        "small_net_inflow_pct": row_value(row, "小单净流入-净占比"),
        "recent_5d": recent_5d,
        "main_net_inflow_5d_sum": json_value(main_5d_sum),
    }
    lines.append(
        f"- 主力净流入 {fmt_yi(payload['main_net_inflow'])},"
        f"净占比 {fmt_signed_pct(payload['main_net_inflow_pct'])},"
        f"近5日主力净流入合计 {fmt_yi(main_5d_sum)}"
    )
    lines.append(
        f"- 超大单 {fmt_yi(payload['super_large_net_inflow'])},"
        f"大单 {fmt_yi(payload['large_net_inflow'])},"
        f"中单 {fmt_yi(payload['medium_net_inflow'])},"
        f"小单 {fmt_yi(payload['small_net_inflow'])}"
    )
    return "\n".join(lines), payload


def block_stock_news(code, date_str):
    """个股相关新闻。默认使用东方财富源,并过滤掉目标交易日之后的新闻。"""
    lines = ["## 相关新闻(近期)"]
    if not ENABLE_EASTMONEY_OPTIONAL:
        lines.append("- 已禁用东方财富可选数据源")
        return "\n".join(lines), {"status": "disabled", "source": "东方财富", "items": []}

    df = safe(lambda: ak.stock_news_em(symbol=code), f"{code} 东方财富个股新闻")
    source = "东方财富 stock_news_em"
    if df is None or df.empty:
        lines.append("- 获取失败")
        return "\n".join(lines), {"status": "failed", "source": source, "items": []}

    data = df.copy()
    data["发布时间_dt"] = pd.to_datetime(data.get("发布时间"), errors="coerce")
    cutoff = pd.to_datetime(date_str, format="%Y%m%d") + pd.Timedelta(days=1)
    data = data[(data["发布时间_dt"].isna()) | (data["发布时间_dt"] < cutoff)]
    data = data.sort_values("发布时间_dt", ascending=False, na_position="last").head(NEWS_PER_STOCK)
    items = []
    for _, r in data.iterrows():
        item = {
            "title": row_value(r, "新闻标题"),
            "published_at": row_value(r, "发布时间"),
            "source": row_value(r, "文章来源"),
            "url": row_value(r, "新闻链接"),
            "summary": row_value(r, "新闻内容"),
        }
        if item["title"]:
            items.append(item)

    if not items:
        lines.append("- 未找到目标交易日之前的相关新闻")
        return "\n".join(lines), {"status": "empty", "source": source, "items": []}

    for item in items[:3]:
        when = item.get("published_at") or "时间未知"
        src = item.get("source") or "来源未知"
        lines.append(f"- {when} {src}: {item['title']}")
    if len(items) > 3:
        lines.append(f"- 另有 {len(items) - 3} 条新闻见 JSON 数据包")
    return "\n".join(lines), {"status": "ok", "source": source, "items": items}


def block_stock(code, name, date_str, sector_df, profiles, market_pct, fund_rank_df=None, allow_fund_rank_fallback=False):
    """单只股票的完整数据块。"""
    lines = [f"# {name}({code})"]
    profile = stock_profile(code, name, profiles)
    payload = {
        "code": code,
        "name": name,
        "profile": profile,
        "daily": {"status": "failed"},
        "recent_5d": [],
        "relative_strength": {"status": "failed"},
        "candidate_signal": {"status": "insufficient", "style": "数据不足", "score": None, "reasons": [], "risks": []},
        "fund_flow": {"status": "failed"},
        "industry": None,
        "lhb": {"hit": False, "reasons": []},
        "news": {"status": "failed", "items": []},
    }

    # 1) 行情
    row, hist = stock_daily_row(code, date_str)
    if row is None:
        lines.append("当日行情获取失败(可能停牌或接口异常),以下其他数据仅供参考。")
    else:
        amp = row.get("振幅", "N/A")
        turnover = row.get("换手率", "N/A")
        lines.append(
            f"## 当日行情\n"
            f"- 收盘 {row['收盘']},涨跌幅 {row['涨跌幅']:+.2f}%,"
            f"开盘 {row['开盘']},最高 {row['最高']},最低 {row['最低']}\n"
            f"- 成交额 {fmt_yi(row['成交额'])},换手率 {fmt_pct(turnover)}%,振幅 {fmt_pct(amp)}%"
        )
        payload["daily"] = {
            "status": "ok",
            "close": row_value(row, "收盘"),
            "pct_change": row_value(row, "涨跌幅"),
            "open": row_value(row, "开盘"),
            "high": row_value(row, "最高"),
            "low": row_value(row, "最低"),
            "amount": row_value(row, "成交额"),
            "turnover": row_value(row, "换手率"),
            "amplitude": row_value(row, "振幅"),
        }
        # 近5日走势,给模型一点趋势背景
        if hist is not None and len(hist) >= 5:
            recent = hist.tail(5)
            trend = ",".join(
                f"{r['日期'][4:]}:{r['涨跌幅']:+.1f}%" for _, r in recent.iterrows())
            lines.append(f"- 近5交易日: {trend}")
            payload["recent_5d"] = [
                {"date": str(r["日期"]), "pct_change": row_value(r, "涨跌幅"), "close": row_value(r, "收盘")}
                for _, r in recent.iterrows()
            ]

    # 2) 资金流向
    fund_block, fund_payload = block_fund_flow(
        code,
        date_str,
        fund_rank_df=fund_rank_df,
        allow_rank_fallback=allow_fund_rank_fallback,
    )
    lines.append(fund_block)
    payload["fund_flow"] = fund_payload

    # 3) 所属行业当日表现
    industry = match_sector(profile, sector_df)
    payload["industry"] = industry
    lines.append("## 所属行业")
    if industry.get("status") == "ok":
        lines.append(f"- {industry['name']}: {industry['pct_change']:+.2f}%")
    elif profile.get("industry"):
        lines.append(f"- {profile['industry']}: 未匹配到行业快照")
    else:
        lines.append("- 未配置个股行业映射")

    industry_pct = industry.get("pct_change") if industry.get("status") == "ok" else None
    if row is not None:
        payload["relative_strength"] = build_relative_metrics(hist, row, market_pct, industry_pct)
        metrics = payload["relative_strength"]
        lines.append("## 相对强弱")
        if metrics.get("status") == "ok":
            amount_vs = metrics.get("amount_vs_5d_avg_pct")
            pos5 = metrics.get("close_position_5d")
            pos5_s = f"{pos5:.2f}" if pos5 is not None else "N/A"
            lines.append(
                f"- 近5日累计 {fmt_signed_pct(metrics.get('return_5d'))},"
                f"相对大盘 {fmt_signed_pct(metrics.get('vs_market_pct'))},"
                f"近5日收盘位置 {pos5_s},"
                f"成交额较近5日均值 {fmt_signed_pct(amount_vs)}"
            )
            if metrics.get("vs_industry_pct") is not None:
                lines.append(f"- 相对所属行业 {fmt_signed_pct(metrics.get('vs_industry_pct'))}")
        else:
            lines.append("- 行情历史不足,无法计算")

    # 4) 龙虎榜
    lhb = safe(lambda: ak.stock_lhb_detail_daily_sina(date=date_str), "新浪龙虎榜")
    if lhb is not None and not lhb.empty and "股票代码" in lhb.columns:
        hit = lhb[lhb["股票代码"].astype(str).str.zfill(6) == code]
        if not hit.empty:
            reasons = ";".join(hit["指标"].astype(str).unique())
            lines.append(f"## 龙虎榜\n- 当日上榜,原因: {reasons}")
            payload["lhb"] = {"hit": True, "reasons": list(hit["指标"].astype(str).unique())}

    payload["candidate_signal"] = classify_candidate(
        name, payload["daily"], payload["relative_strength"], payload["lhb"]
    )
    signal = payload["candidate_signal"]
    lines.append("## 候选分层")
    if signal.get("status") == "ok":
        score = signal.get("score")
        score_s = f"{score:.2f}" if score is not None else "N/A"
        lines.append(f"- 类型: {signal['style']},评分: {score_s}")
        lines.append("- 支持: " + ",".join(signal.get("reasons") or []))
        if signal.get("risks"):
            lines.append("- 风险: " + ",".join(signal["risks"]))
    else:
        lines.append("- 数据不足")

    # 5) 个股新闻
    news_block, news_payload = block_stock_news(code, date_str)
    lines.append(news_block)
    payload["news"] = news_payload

    return "\n".join(lines), payload


def parse_args(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    date_arg = None
    watchlist_text = None
    watchlist_file = None
    i = 0
    while i < len(args):
        item = args[i]
        if item == "--watchlist":
            i += 1
            if i >= len(args):
                raise SystemExit("--watchlist requires a value")
            watchlist_text = args[i]
        elif item == "--watchlist-file":
            i += 1
            if i >= len(args):
                raise SystemExit("--watchlist-file requires a path")
            watchlist_file = args[i]
        elif item in ("-h", "--help"):
            print(
                "用法: python3 scripts/daily_report.py [YYYYMMDD] "
                "[--watchlist CODE:NAME,...] [--watchlist-file PATH]"
            )
            raise SystemExit(0)
        elif item.startswith("-"):
            raise SystemExit(f"unknown option: {item}")
        elif date_arg is None:
            date_arg = item
        else:
            raise SystemExit(f"unexpected argument: {item}")
        i += 1
    return date_arg, watchlist_text, watchlist_file


def main(argv=None):
    arg_date, watchlist_text, watchlist_file = parse_args(argv)
    watchlist = load_watchlist(path=watchlist_file, text=watchlist_text, default=DEFAULT_WATCHLIST)
    trade_date = get_trade_date(arg_date)
    date_str = trade_date.strftime("%Y%m%d")
    log(f"分析交易日: {date_str},自选股 {len(watchlist)} 只")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    generated_at = dt.datetime.now().strftime('%Y-%m-%d %H:%M')
    index_block, index_payload = block_index_context(date_str)
    ok_index_pcts = [x.get("pct_change") for x in index_payload if x.get("status") == "ok" and x.get("pct_change") is not None]
    market_pct = sum(ok_index_pcts) / len(ok_index_pcts) if ok_index_pcts else None
    profiles = load_stock_profiles()
    parts = [
        f"# 每日复盘数据包 — {trade_date.strftime('%Y-%m-%d')}",
        f"生成时间: {generated_at}",
        "说明: 以下为脚本抓取的公开数据,标注'获取失败'的项请在分析时忽略,不要臆测。",
        index_block,
    ]
    payload = {
        "trade_date": date_str,
        "generated_at": generated_at,
        "watchlist": [{"code": code, "name": name} for code, name in watchlist.items()],
        "indexes": index_payload,
        "market": {"benchmark_pct_change": json_value(market_pct), "method": "三大指数等权平均"},
        "profile_source": os.path.abspath(PROFILE_PATH) if os.path.exists(PROFILE_PATH) else None,
        "sectors": None,
        "stocks": [],
        "disclaimer": "以下为脚本抓取的公开数据,标注获取失败的项请在分析时忽略,不要臆测。",
    }

    sector_block, sector_df, sector_payload = block_sector_snapshot()
    payload["sectors"] = sector_payload
    parts.append(sector_block)

    latest_trade_date = get_trade_date(None)
    allow_fund_rank_fallback = ENABLE_EASTMONEY_OPTIONAL and trade_date == latest_trade_date
    fund_rank_df = block_fund_rank_snapshot() if allow_fund_rank_fallback else None

    for code, name in watchlist.items():
        log(f"抓取 {name}({code}) ...")
        stock_block, stock_payload = block_stock(
            code,
            name,
            date_str,
            sector_df,
            profiles,
            market_pct,
            fund_rank_df=fund_rank_df,
            allow_fund_rank_fallback=allow_fund_rank_fallback,
        )
        parts.append(stock_block)
        payload["stocks"].append(stock_payload)

    out_path = os.path.join(OUTPUT_DIR, f"report_{date_str}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(parts) + "\n")
    json_path = os.path.join(OUTPUT_DIR, f"report_{date_str}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # stdout 只输出数据包路径,方便 Agent/脚本接续处理
    print(out_path)


if __name__ == "__main__":
    main()
