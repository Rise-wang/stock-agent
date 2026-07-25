#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日报数据包完整性校验
==================
校验 daily_report.py 生成的 Markdown/JSON 数据包是否具备每日复盘所需的基本事实。

用法:
    python3 scripts/validate_report.py reports/report_20240719.json
    python3 scripts/validate_report.py 20240719
"""

import argparse
import json
import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REPORT_DIR = os.getenv("STOCK_REPORT_DIR", os.path.join(ROOT, "reports"))


def resolve_path(value):
    if value.endswith(".json"):
        return value
    return os.path.join(REPORT_DIR, f"report_{value}.json")


def check_report(data):
    errors = []
    warnings = []

    if not data.get("trade_date"):
        errors.append("missing trade_date")

    indexes = data.get("indexes") or []
    ok_indexes = [x for x in indexes if x.get("status") == "ok"]
    if len(ok_indexes) < 1:
        errors.append("no usable index data")
    elif len(ok_indexes) < 3:
        warnings.append(f"partial index data: {len(ok_indexes)}/3")

    sectors = data.get("sectors") or {}
    if sectors.get("status") != "ok":
        warnings.append("sector snapshot missing")
    elif not sectors.get("top") or not sectors.get("bottom"):
        warnings.append("sector top/bottom incomplete")

    stocks = data.get("stocks") or []
    if not stocks:
        errors.append("no stock blocks")

    for stock in stocks:
        code = stock.get("code", "UNKNOWN")
        name = stock.get("name", code)
        daily = stock.get("daily") or {}
        if daily.get("status") != "ok":
            errors.append(f"{name}({code}) daily quote missing")
        if len(stock.get("recent_5d") or []) < 5:
            warnings.append(f"{name}({code}) recent_5d incomplete")
        relative = stock.get("relative_strength") or {}
        if daily.get("status") == "ok" and relative.get("status") != "ok":
            warnings.append(f"{name}({code}) relative strength unavailable")
        signal = stock.get("candidate_signal") or {}
        if daily.get("status") == "ok" and signal.get("status") != "ok":
            warnings.append(f"{name}({code}) candidate signal unavailable")
        profile = stock.get("profile") or {}
        industry = stock.get("industry") or {}
        if profile.get("status") not in ("ok", "watchlist_only"):
            warnings.append(f"{name}({code}) profile missing")
        elif profile.get("industry") and industry.get("status") != "ok":
            warnings.append(f"{name}({code}) industry snapshot unmatched")
        fund_flow = stock.get("fund_flow") or {}
        if fund_flow.get("status") not in ("ok", "disabled"):
            warnings.append(f"{name}({code}) fund flow unavailable")
        news = stock.get("news")
        if isinstance(news, list):
            news_ok = bool(news)
        else:
            news = news or {}
            news_ok = news.get("status") in ("ok", "empty", "disabled")
        if not news_ok:
            warnings.append(f"{name}({code}) news unavailable")

    return errors, warnings


def main(argv=None):
    parser = argparse.ArgumentParser(description="校验 daily_report.py 生成的 JSON 数据包")
    parser.add_argument("report", help="JSON 路径或 YYYYMMDD")
    parser.add_argument("--strict", action="store_true", help="有 warning 时也返回失败")
    args = parser.parse_args(argv)

    path = resolve_path(args.report)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(f"ERROR cannot read {path}: {type(exc).__name__}: {exc}")
        return 2

    errors, warnings = check_report(data)
    for item in warnings:
        print(f"WARN {item}")
    for item in errors:
        print(f"ERROR {item}")

    if errors or (args.strict and warnings):
        return 1
    print(f"OK {path} stocks={len(data.get('stocks') or [])} warnings={len(warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
