#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pathlib
import sys
import unittest

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import alert_watch
import backtest_run
import validate_report
import watchlist_config


class AlertWatchTest(unittest.TestCase):
    def test_parse_watchlist(self):
        self.assertEqual(
            alert_watch.parse_watchlist("1:平安银行,600519:贵州茅台"),
            {"000001": "平安银行", "600519": "贵州茅台"},
        )

    def test_build_alerts(self):
        df = pd.DataFrame([
            {"代码": "600519", "名称": "贵州茅台", "最新价": 1600.0, "涨跌幅": 4.2, "量比": 1.1},
            {"代码": "300750", "名称": "宁德时代", "最新价": 200.0, "涨跌幅": 0.5, "量比": 2.8},
        ])
        alerts, missing = alert_watch.build_alerts(
            df, {"600519": "贵州茅台", "300750": "宁德时代", "000001": "平安银行"}, 4.0, 2.0)
        self.assertEqual(missing, ["000001"])
        self.assertEqual(len(alerts), 2)
        self.assertIn("涨跌幅 +4.20%", alerts[0])
        self.assertIn("量比 2.80", alerts[1])


class WatchlistConfigTest(unittest.TestCase):
    def test_parse_watchlist_json_dict(self):
        self.assertEqual(
            watchlist_config.parse_watchlist_json({"1": "平安银行"}),
            {"000001": "平安银行"},
        )

    def test_parse_watchlist_json_list(self):
        self.assertEqual(
            watchlist_config.parse_watchlist_json([{"code": "sh600519", "name": "贵州茅台"}]),
            {"600519": "贵州茅台"},
        )


class BacktestRunTest(unittest.TestCase):
    def test_invalid_params(self):
        self.assertEqual(backtest_run.main(["--fast", "20", "--slow", "5"]), 2)

    def test_report_format(self):
        report = {
            "symbol": "600519",
            "start": "2024-01-01",
            "end": "2024-12-31",
            "bars": 200,
            "fast": 5,
            "slow": 20,
            "adjust": "qfq",
            "cash": 100000.0,
            "end_value": 110000.0,
            "total_return": 0.1,
            "annual_return": 0.11,
            "max_drawdown": 3.2,
            "sharpe": None,
            "closed_trades": 3,
            "won": 2,
            "lost": 1,
            "win_rate": 66.666,
        }
        backtest_run.print_report(report)


class ValidateReportTest(unittest.TestCase):
    def test_check_report_warns_missing_optional_data(self):
        data = {
            "trade_date": "20240719",
            "indexes": [{"status": "ok"}, {"status": "ok"}, {"status": "ok"}],
            "sectors": {"status": "ok", "top": [{"name": "半导体"}], "bottom": [{"name": "电力"}]},
            "stocks": [{
                "code": "600519",
                "name": "贵州茅台",
                "daily": {"status": "ok"},
                "recent_5d": [{"date": str(i)} for i in range(5)],
                "fund_flow": {"status": "failed"},
                "news": [],
            }],
        }
        errors, warnings = validate_report.check_report(data)
        self.assertEqual(errors, [])
        self.assertIn("贵州茅台(600519) fund flow unavailable", warnings)
        self.assertIn("贵州茅台(600519) news unavailable", warnings)


if __name__ == "__main__":
    unittest.main()
