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

from watchlist_config import DEFAULT_WATCHLIST, load_watchlist

# ============================================================
# 配置区
# ============================================================
NEWS_PER_STOCK = 8          # 每只股票抓取的新闻条数
OUTPUT_DIR = os.getenv(
    "STOCK_REPORT_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "reports")),
)
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


def fmt_pct(v):
    try:
        return f"{float(v):.2f}"
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
    return ("sh" if code.startswith(("6", "9")) else "sz") + code


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


def block_stock(code, name, date_str, sector_df):
    """单只股票的完整数据块。"""
    lines = [f"# {name}({code})"]
    payload = {
        "code": code,
        "name": name,
        "daily": {"status": "failed"},
        "recent_5d": [],
        "fund_flow": {"status": "unsupported", "reason": "未配置非东方财富资金流数据源"},
        "industry": None,
        "lhb": {"hit": False, "reasons": []},
        "news": [],
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
    lines.append("## 资金流向\n未配置非东方财富资金流数据源")

    # 3) 所属行业当日表现
    if sector_df is not None:
        lines.append("## 所属行业\n未配置非东方财富个股行业映射源")

    # 4) 龙虎榜
    lhb = safe(lambda: ak.stock_lhb_detail_daily_sina(date=date_str), "新浪龙虎榜")
    if lhb is not None and not lhb.empty and "股票代码" in lhb.columns:
        hit = lhb[lhb["股票代码"].astype(str).str.zfill(6) == code]
        if not hit.empty:
            reasons = ";".join(hit["指标"].astype(str).unique())
            lines.append(f"## 龙虎榜\n- 当日上榜,原因: {reasons}")
            payload["lhb"] = {"hit": True, "reasons": list(hit["指标"].astype(str).unique())}

    # 5) 个股新闻
    lines.append("## 相关新闻(近期)")
    lines.append("- 未配置非东方财富个股新闻数据源")

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
        "sectors": None,
        "stocks": [],
        "disclaimer": "以下为脚本抓取的公开数据,标注获取失败的项请在分析时忽略,不要臆测。",
    }

    sector_block, sector_df, sector_payload = block_sector_snapshot()
    payload["sectors"] = sector_payload
    parts.append(sector_block)

    for code, name in watchlist.items():
        log(f"抓取 {name}({code}) ...")
        stock_block, stock_payload = block_stock(code, name, date_str, sector_df)
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
