#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pathlib
import sys
import tempfile
import unittest

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import alert_watch
import backtest_run
import daily_report
import send_email
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

    def test_market_prefix(self):
        self.assertEqual(watchlist_config.market_prefix("560860"), "sh")
        self.assertEqual(watchlist_config.market_prefix("920809"), "bj")
        self.assertEqual(watchlist_config.market_prefix("002498"), "sz")


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
                "relative_strength": {"status": "ok"},
                "candidate_signal": {"status": "ok"},
                "profile": {"status": "watchlist_only"},
                "industry": {"status": "missing"},
                "fund_flow": {"status": "ok"},
                "news": {"status": "empty", "items": []},
            }],
        }
        errors, warnings = validate_report.check_report(data)
        self.assertEqual(errors, [])
        self.assertNotIn("贵州茅台(600519) profile missing", warnings)
        self.assertNotIn("贵州茅台(600519) fund flow unavailable", warnings)
        self.assertNotIn("贵州茅台(600519) news unavailable", warnings)

    def test_check_report_warns_failed_enrichment(self):
        data = {
            "trade_date": "20240719",
            "indexes": [{"status": "ok"}, {"status": "ok"}, {"status": "ok"}],
            "sectors": {"status": "ok", "top": [{"name": "半导体"}], "bottom": [{"name": "电力"}]},
            "stocks": [{
                "code": "600519",
                "name": "贵州茅台",
                "daily": {"status": "ok"},
                "recent_5d": [{"date": str(i)} for i in range(5)],
                "relative_strength": {"status": "ok"},
                "candidate_signal": {"status": "ok"},
                "profile": {"status": "watchlist_only"},
                "industry": {"status": "missing"},
                "fund_flow": {"status": "failed"},
                "news": {"status": "failed", "items": []},
            }],
        }
        errors, warnings = validate_report.check_report(data)
        self.assertEqual(errors, [])
        self.assertIn("贵州茅台(600519) fund flow unavailable", warnings)
        self.assertIn("贵州茅台(600519) news unavailable", warnings)

    def test_check_report_accepts_legacy_news_list(self):
        data = {
            "trade_date": "20240719",
            "indexes": [{"status": "ok"}, {"status": "ok"}, {"status": "ok"}],
            "sectors": {"status": "ok", "top": [{"name": "半导体"}], "bottom": [{"name": "电力"}]},
            "stocks": [{
                "code": "600519",
                "name": "贵州茅台",
                "daily": {"status": "ok"},
                "recent_5d": [{"date": str(i)} for i in range(5)],
                "relative_strength": {"status": "ok"},
                "candidate_signal": {"status": "ok"},
                "profile": {"status": "watchlist_only"},
                "industry": {"status": "missing"},
                "fund_flow": {"status": "disabled"},
                "news": [{"title": "测试新闻"}],
            }],
        }
        errors, warnings = validate_report.check_report(data)
        self.assertEqual(errors, [])
        self.assertNotIn("贵州茅台(600519) news unavailable", warnings)


class DailyReportMetricsTest(unittest.TestCase):
    def test_build_relative_metrics(self):
        hist = pd.DataFrame([
            {"涨跌幅": 1.0, "收盘": 10.0, "成交额": 100.0, "成交量": 10.0},
            {"涨跌幅": 2.0, "收盘": 10.2, "成交额": 100.0, "成交量": 10.0},
            {"涨跌幅": -1.0, "收盘": 10.1, "成交额": 100.0, "成交量": 10.0},
            {"涨跌幅": 3.0, "收盘": 10.4, "成交额": 100.0, "成交量": 10.0},
            {"涨跌幅": 0.5, "收盘": 10.45, "成交额": 150.0, "成交量": 12.0},
        ])
        row = hist.iloc[-1]
        metrics = daily_report.build_relative_metrics(hist, row, market_pct=-1.0, industry_pct=-0.5)
        self.assertEqual(metrics["status"], "ok")
        self.assertAlmostEqual(metrics["vs_market_pct"], 1.5)
        self.assertAlmostEqual(metrics["vs_industry_pct"], 1.0)
        self.assertAlmostEqual(metrics["amount_vs_5d_avg_pct"], 50.0)
        self.assertAlmostEqual(metrics["close_position_5d"], 1.0)

    def test_classify_candidate_stable_rebound(self):
        daily = {"status": "ok", "pct_change": -0.5, "turnover": 2.0, "amplitude": 4.0}
        metrics = {
            "status": "ok",
            "return_5d": 2.0,
            "prev_4d_return": 2.5,
            "close_position_5d": 0.8,
            "vs_market_pct": 1.7,
            "amount_vs_5d_avg_pct": 10.0,
        }
        signal = daily_report.classify_candidate("测试股份", daily, metrics, {"hit": False})
        self.assertEqual(signal["style"], "稳健修复")
        self.assertGreater(signal["score"], 0)

    def test_parse_cn_money(self):
        self.assertEqual(daily_report.parse_cn_money("1.25亿"), 125000000.0)
        self.assertEqual(daily_report.parse_cn_money("-252.21万"), -2522100.0)
        self.assertIsNone(daily_report.parse_cn_money("-"))

    def test_fund_flow_from_rank(self):
        df = pd.DataFrame([{
            "股票代码": "2498",
            "股票简称": "汉缆股份",
            "流入资金": "2.09亿",
            "流出资金": "2.76亿",
            "净额": "-6717.42万",
            "成交额": "4.85亿",
        }])
        payload = daily_report.fund_flow_from_rank("002498", "20260724", df)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["source"], "东方财富 stock_fund_flow_individual 即时排名")
        self.assertAlmostEqual(payload["net_inflow"], -67174200.0)
        self.assertAlmostEqual(payload["net_inflow_pct"], -13.850350515463917)


class SendEmailTest(unittest.TestCase):
    def test_missing_settings(self):
        missing = send_email.missing_settings({"smtp_host": "smtp.qq.com"})
        self.assertIn("smtp_user", missing)
        self.assertIn("smtp_password", missing)

    def test_qq_host_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "email.local.json"
            path.write_text(
                '{"smtp_user":"407473978@qq.com","smtp_password":"token","smtp_from":"407473978@qq.com"}',
                encoding="utf-8",
            )
            settings = send_email.load_settings(path)
        self.assertEqual(settings["smtp_host"], "smtp.qq.com")
        self.assertEqual(send_email.missing_settings(settings), [])

    def test_build_message(self):
        msg = send_email.build_message(
            "sender@example.com",
            ["to@example.com"],
            "测试主题",
            "正文",
        )
        self.assertEqual(msg["From"], "sender@example.com")
        self.assertEqual(msg["To"], "to@example.com")
        self.assertEqual(msg["Subject"], "测试主题")


if __name__ == "__main__":
    unittest.main()
