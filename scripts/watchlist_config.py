#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自选股配置读取工具。"""

import json
import os


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_WATCHLIST_PATH = os.path.join(ROOT, "config", "watchlist.json")
DEFAULT_WATCHLIST = {
    "600519": "贵州茅台",
    "300750": "宁德时代",
}


def normalize_code(code):
    code = str(code).strip()
    if code.startswith(("sh", "sz", "bj")) and len(code) >= 8:
        code = code[2:]
    code = code.zfill(6)
    if not code.isdigit() or len(code) != 6:
        raise ValueError(f"非法股票代码: {code}")
    return code


def parse_watchlist_text(raw):
    """Parse CODE:NAME pairs, e.g. 600519:贵州茅台,300750:宁德时代."""
    result = {}
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            code, name = item.split(":", 1)
        elif "=" in item:
            code, name = item.split("=", 1)
        else:
            code, name = item, item
        code = normalize_code(code)
        name = name.strip() or code
        result[code] = name
    return result


def parse_watchlist_json(data):
    """Support {"600519":"贵州茅台"} or [{"code":"600519","name":"贵州茅台"}]."""
    result = {}
    if isinstance(data, dict):
        items = data.items()
        for code, name in items:
            result[normalize_code(code)] = str(name).strip() or normalize_code(code)
    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                raise ValueError("watchlist list item must be an object")
            code = normalize_code(item.get("code", ""))
            name = str(item.get("name") or code).strip()
            result[code] = name
    else:
        raise ValueError("watchlist JSON must be object or list")
    return result


def load_watchlist(path=None, text=None, default=None):
    """Load watchlist in priority: explicit text/env, JSON file, default."""
    if text:
        result = parse_watchlist_text(text)
        if result:
            return result

    env_text = os.getenv("STOCK_WATCHLIST")
    if env_text:
        result = parse_watchlist_text(env_text)
        if result:
            return result

    path = path or os.getenv("STOCK_WATCHLIST_FILE") or DEFAULT_WATCHLIST_PATH
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            result = parse_watchlist_json(json.load(f))
        if result:
            return result

    return dict(default or DEFAULT_WATCHLIST)
