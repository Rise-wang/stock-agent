#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
盘中异动监控脚本
================
抓取自选股实时行情,按涨跌幅和量比阈值输出一行监控结果,适合由 cron/心跳服务周期触发。
默认使用腾讯/新浪公开接口,不调用东方财富。

用法:
    python3 scripts/alert_watch.py
    python3 scripts/alert_watch.py --pct-threshold 5 --volume-ratio-threshold 2.5
    python3 scripts/alert_watch.py --date 20240719
    python3 scripts/alert_watch.py --watchlist-file config/watchlist.json
    STOCK_WATCHLIST="600519:贵州茅台,300750:宁德时代" python3 scripts/alert_watch.py

输出:
    ALERT 2026-07-25 10:30 贵州茅台(600519) 涨跌幅 +5.23%>=5.00%, 量比 2.80>=2.50; ...
    OK 2026-07-25 10:30 watch=2 no abnormal move
"""

import argparse
import datetime as dt
import os
import time

import akshare as ak
import pandas as pd

from watchlist_config import DEFAULT_WATCHLIST, load_watchlist, parse_watchlist_text


REQUEST_INTERVAL = 0.5


def parse_watchlist(raw):
    """Parse CODE:NAME pairs from env/CLI."""
    if not raw:
        return dict(DEFAULT_WATCHLIST)
    result = parse_watchlist_text(raw)
    if not result:
        raise ValueError("自选股为空")
    return result


def fetch_spot_quotes():
    df = retry(lambda: ak.stock_zh_a_spot_tx(), "腾讯实时行情")
    if df is None or df.empty:
        raise RuntimeError("实时行情接口返回空数据")
    return pd.DataFrame({
        "代码": df["code"].astype(str).str[-6:].str.zfill(6),
        "名称": df["name"],
        "最新价": pd.to_numeric(df["zxj"], errors="coerce"),
        "涨跌幅": pd.to_numeric(df["zdf"], errors="coerce"),
        "量比": pd.to_numeric(df["lb"], errors="coerce"),
    })


def retry(fn, desc, attempts=3):
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            time.sleep(REQUEST_INTERVAL * attempt)
            return fn()
        except Exception as exc:
            last_exc = exc
    raise RuntimeError(f"{desc}失败: {type(last_exc).__name__}: {last_exc}")


def as_float(value):
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_alerts(df, watchlist, pct_threshold, volume_ratio_threshold):
    alerts = []
    missing = []
    for code, configured_name in watchlist.items():
        rows = df[df["代码"] == code]
        if rows.empty:
            missing.append(code)
            continue
        row = rows.iloc[0]
        name = str(row.get("名称") or configured_name)
        pct = as_float(row.get("涨跌幅"))
        volume_ratio = as_float(row.get("量比"))
        price = as_float(row.get("最新价"))

        reasons = []
        if pct is not None and abs(pct) >= pct_threshold:
            reasons.append(f"涨跌幅 {pct:+.2f}%>={pct_threshold:.2f}%")
        if volume_ratio is not None and volume_ratio >= volume_ratio_threshold:
            reasons.append(f"量比 {volume_ratio:.2f}>={volume_ratio_threshold:.2f}")

        if reasons:
            price_text = f" 最新价 {price:.2f}" if price is not None else ""
            alerts.append(f"{name}({code}){price_text} " + ", ".join(reasons))
    return alerts, missing


def parse_yyyymmdd(value):
    return dt.datetime.strptime(value, "%Y%m%d").date()


def fetch_hist_quote(code, end_date):
    end_day = parse_yyyymmdd(end_date) if end_date else dt.date.today()
    end = end_day.strftime("%Y%m%d")
    start = (end_day - dt.timedelta(days=45)).strftime("%Y%m%d")
    symbol = ("sh" if code.startswith(("6", "9")) else "sz") + code
    df = retry(lambda: ak.stock_zh_a_daily(
        symbol=symbol, start_date=start, end_date=end, adjust="qfq"), f"{code} 新浪日线")
    df = df.rename(columns={
        "date": "日期",
        "close": "收盘",
        "volume": "成交量",
    })
    df["涨跌幅"] = pd.to_numeric(df["收盘"], errors="coerce").pct_change() * 100
    if df is None or df.empty or len(df) < 2:
        raise RuntimeError(f"{code} 日线数据不足")
    df = df.tail(20).copy()
    latest = df.iloc[-1]
    avg_volume = pd.to_numeric(df.iloc[:-1]["成交量"], errors="coerce").tail(5).mean()
    volume = as_float(latest.get("成交量"))
    volume_ratio = volume / avg_volume if avg_volume and volume is not None else None
    return {
        "代码": code,
        "最新价": latest.get("收盘"),
        "涨跌幅": latest.get("涨跌幅"),
        "量比": volume_ratio,
        "数据日期": str(latest.get("日期")),
    }


def build_alerts_from_hist(watchlist, pct_threshold, volume_ratio_threshold, end_date=None):
    rows = []
    missing = []
    for code in watchlist:
        try:
            rows.append(fetch_hist_quote(code, end_date))
        except Exception as exc:
            missing.append(code)
    if not rows:
        raise RuntimeError("实时行情和日线兜底均未获取到数据")
    df = pd.DataFrame(rows)
    alerts, more_missing = build_alerts(df, watchlist, pct_threshold, volume_ratio_threshold)
    return alerts, missing + more_missing, str(df["数据日期"].max())


def main(argv=None):
    parser = argparse.ArgumentParser(description="盘中异动监控,输出一行 ALERT/OK 文本")
    parser.add_argument("--watchlist", default=os.getenv("STOCK_WATCHLIST"),
                        help="自选股,格式 CODE:NAME,CODE:NAME；默认复用 daily_report.WATCHLIST")
    parser.add_argument("--watchlist-file", default=os.getenv("STOCK_WATCHLIST_FILE"),
                        help="自选股 JSON 文件；默认 config/watchlist.json")
    parser.add_argument("--pct-threshold", type=float,
                        default=float(os.getenv("ALERT_PCT_THRESHOLD", "4.0")),
                        help="涨跌幅绝对值阈值,单位 %%")
    parser.add_argument("--volume-ratio-threshold", type=float,
                        default=float(os.getenv("ALERT_VOLUME_RATIO_THRESHOLD", "2.0")),
                        help="量比阈值")
    parser.add_argument("--date", default=os.getenv("ALERT_DATE"),
                        help="日线兜底结束日期 YYYYMMDD；实时接口可用时忽略")
    args = parser.parse_args(argv)

    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    source = "spot"
    data_date = None
    try:
        watchlist = load_watchlist(path=args.watchlist_file, text=args.watchlist, default=DEFAULT_WATCHLIST)
        try:
            df = fetch_spot_quotes()
            alerts, missing = build_alerts(
                df, watchlist, args.pct_threshold, args.volume_ratio_threshold)
        except Exception:
            source = "hist"
            alerts, missing, data_date = build_alerts_from_hist(
                watchlist, args.pct_threshold, args.volume_ratio_threshold, args.date)
    except Exception as exc:
        print(f"ERROR {now} {type(exc).__name__}: {exc}")
        return 2

    source_text = f" source={source}" + (f" data_date={data_date}" if data_date else "")
    if alerts:
        suffix = f"; missing={','.join(missing)}" if missing else ""
        print(f"ALERT {now}{source_text} " + "; ".join(alerts) + suffix)
        return 1

    suffix = f" missing={','.join(missing)}" if missing else ""
    print(f"OK {now}{source_text} watch={len(watchlist)} no abnormal move{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
