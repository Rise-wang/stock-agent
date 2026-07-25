#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backtrader 回测脚本
==================
用 AkShare 新浪 A 股日线数据执行一个可参数化的均线交叉策略,输出文本绩效报告。

用法:
    python3 scripts/backtest_run.py --symbol 600519 --start 20240101 --end 20260724
    python3 scripts/backtest_run.py --symbol 300750 --fast 10 --slow 30 --cash 200000
"""

import argparse
import datetime as dt
import math
import sys
import time

import akshare as ak
import backtrader as bt
import pandas as pd

from watchlist_config import market_prefix


REQUEST_INTERVAL = 0.5


class MovingAverageCrossStrategy(bt.Strategy):
    params = (
        ("fast", 5),
        ("slow", 20),
        ("stake_pct", 0.95),
    )

    def __init__(self):
        if self.p.fast >= self.p.slow:
            raise ValueError("fast 必须小于 slow")
        self.order = None
        self.fast_ma = bt.ind.SMA(self.data.close, period=self.p.fast)
        self.slow_ma = bt.ind.SMA(self.data.close, period=self.p.slow)
        self.cross = bt.ind.CrossOver(self.fast_ma, self.slow_ma)

    def next(self):
        if self.order:
            return
        if not self.position and self.cross > 0:
            cash = self.broker.getcash()
            size = int((cash * self.p.stake_pct) / self.data.close[0] / 100) * 100
            if size > 0:
                self.order = self.buy(size=size)
        elif self.position and self.cross < 0:
            self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in (order.Completed, order.Canceled, order.Margin, order.Rejected):
            self.order = None


def fetch_daily_data(symbol, start, end, adjust):
    last_exc = None
    df = None
    market_symbol = market_prefix(symbol) + symbol
    for attempt in range(1, 4):
        try:
            time.sleep(REQUEST_INTERVAL * attempt)
            df = ak.stock_zh_a_daily(
                symbol=market_symbol, start_date=start, end_date=end, adjust=adjust)
            df = df.rename(columns={
                "date": "日期",
                "open": "开盘",
                "high": "最高",
                "low": "最低",
                "close": "收盘",
                "volume": "成交量",
            })
            break
        except Exception as exc:
            last_exc = exc
    else:
        raise RuntimeError(f"{symbol} 新浪日线获取失败: {type(last_exc).__name__}: {last_exc}")
    if df is None or df.empty:
        raise RuntimeError(f"{symbol} 日线接口返回空数据")

    required = ["日期", "开盘", "最高", "最低", "收盘", "成交量"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise RuntimeError(f"日线数据缺少字段: {','.join(missing)}")

    data = pd.DataFrame({
        "datetime": pd.to_datetime(df["日期"]),
        "open": pd.to_numeric(df["开盘"], errors="coerce"),
        "high": pd.to_numeric(df["最高"], errors="coerce"),
        "low": pd.to_numeric(df["最低"], errors="coerce"),
        "close": pd.to_numeric(df["收盘"], errors="coerce"),
        "volume": pd.to_numeric(df["成交量"], errors="coerce"),
        "openinterest": 0,
    }).dropna()
    data = data.sort_values("datetime").set_index("datetime")
    if data.empty:
        raise RuntimeError("清洗后没有可回测数据")
    return data


def run_backtest(args):
    symbol = args.symbol.zfill(6)
    data = fetch_daily_data(symbol, args.start, args.end, args.adjust)
    if len(data) <= args.slow + 2:
        raise RuntimeError(f"数据不足: {len(data)} 行, slow={args.slow}")

    cerebro = bt.Cerebro(stdstats=False)
    feed = bt.feeds.PandasData(dataname=data)
    cerebro.adddata(feed)
    cerebro.addstrategy(
        MovingAverageCrossStrategy,
        fast=args.fast,
        slow=args.slow,
        stake_pct=args.stake_pct,
    )
    cerebro.broker.setcash(args.cash)
    cerebro.broker.setcommission(commission=args.commission)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", timeframe=bt.TimeFrame.Days)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    start_value = cerebro.broker.getvalue()
    results = cerebro.run()
    end_value = cerebro.broker.getvalue()
    strat = results[0]

    days = max((data.index[-1].date() - data.index[0].date()).days, 1)
    total_return = end_value / start_value - 1
    annual_return = math.pow(1 + total_return, 365 / days) - 1
    drawdown = strat.analyzers.drawdown.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis().get("sharperatio")
    trades = strat.analyzers.trades.get_analysis()

    closed = int(trades.get("total", {}).get("closed", 0) or 0)
    won = int(trades.get("won", {}).get("total", 0) or 0)
    lost = int(trades.get("lost", {}).get("total", 0) or 0)
    win_rate = (won / closed * 100) if closed else 0.0

    return {
        "symbol": symbol,
        "start": data.index[0].strftime("%Y-%m-%d"),
        "end": data.index[-1].strftime("%Y-%m-%d"),
        "bars": len(data),
        "cash": start_value,
        "end_value": end_value,
        "total_return": total_return,
        "annual_return": annual_return,
        "max_drawdown": float(drawdown.get("max", {}).get("drawdown", 0) or 0),
        "sharpe": sharpe,
        "closed_trades": closed,
        "won": won,
        "lost": lost,
        "win_rate": win_rate,
        "fast": args.fast,
        "slow": args.slow,
        "commission": args.commission,
        "adjust": args.adjust,
    }


def print_report(report):
    sharpe_text = "N/A" if report["sharpe"] is None else f"{report['sharpe']:.3f}"
    print(f"Backtest Report: {report['symbol']}")
    print(f"Period: {report['start']} -> {report['end']} ({report['bars']} bars)")
    print(f"Strategy: SMA Cross fast={report['fast']} slow={report['slow']} adjust={report['adjust']}")
    print(f"Initial Cash: {report['cash']:.2f}")
    print(f"Final Value: {report['end_value']:.2f}")
    print(f"Total Return: {report['total_return'] * 100:+.2f}%")
    print(f"Annualized Return: {report['annual_return'] * 100:+.2f}%")
    print(f"Max Drawdown: {report['max_drawdown']:.2f}%")
    print(f"Sharpe Ratio: {sharpe_text}")
    print(
        f"Trades: closed={report['closed_trades']} won={report['won']} "
        f"lost={report['lost']} win_rate={report['win_rate']:.2f}%")


def main(argv=None):
    parser = argparse.ArgumentParser(description="用 AkShare 数据运行 Backtrader 均线交叉回测")
    parser.add_argument("--symbol", default="600519", help="A 股代码")
    parser.add_argument("--start", default="20240101", help="开始日期 YYYYMMDD")
    parser.add_argument("--end", default=dt.date.today().strftime("%Y%m%d"), help="结束日期 YYYYMMDD")
    parser.add_argument("--fast", type=int, default=5, help="快均线周期")
    parser.add_argument("--slow", type=int, default=20, help="慢均线周期")
    parser.add_argument("--cash", type=float, default=100000.0, help="初始资金")
    parser.add_argument("--stake-pct", type=float, default=0.95, help="单次买入可用现金比例")
    parser.add_argument("--commission", type=float, default=0.0003, help="单边佣金比例")
    parser.add_argument("--adjust", choices=["", "qfq", "hfq"], default="qfq", help="复权方式")
    args = parser.parse_args(argv)

    if args.fast <= 0 or args.slow <= 0:
        print("ERROR fast/slow 必须为正整数", file=sys.stderr)
        return 2
    if args.fast >= args.slow:
        print("ERROR fast 必须小于 slow", file=sys.stderr)
        return 2
    if not (0 < args.stake_pct <= 1):
        print("ERROR stake-pct 必须在 (0, 1] 范围内", file=sys.stderr)
        return 2

    try:
        report = run_backtest(args)
    except Exception as exc:
        print(f"ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
