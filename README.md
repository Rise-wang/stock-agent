# stock-agent

A-share daily review helper built around AkShare data sources.

## Features

- Generate daily Markdown and JSON data packages for a configurable watchlist.
- Monitor intraday abnormal moves with one-line `ALERT`/`OK` output.
- Run a Backtrader moving-average crossover backtest.
- Validate generated daily report data before review.
- Provide a `daily-review` Skill workflow with strict no-fabrication rules.

## Configure Watchlist

Edit `config/watchlist.json`:

```json
{
  "600519": "贵州茅台",
  "300750": "宁德时代"
}
```

You can also override it for one run:

```bash
python3 scripts/daily_report.py 20240719 --watchlist 000001:平安银行,600519:贵州茅台
```

## Usage

Generate and validate a daily report:

```bash
./scripts/run_daily_review.sh 20240719
```

Run intraday monitoring:

```bash
python3 scripts/alert_watch.py
```

Run a backtest:

```bash
python3 scripts/backtest_run.py --symbol 600519 --start 20240101 --end 20240719
```

Run tests:

```bash
make test
```

## Data Sources

The default scripts avoid Eastmoney endpoints because they were unreliable in the target environment. Current defaults use AkShare wrappers around Sina, Tonghuashun, and Tencent public data sources where available.

Unavailable fields such as non-Eastmoney individual fund flow and stock-specific news are explicitly marked as unsupported, and review workflows must not infer causes from missing data.

## Disclaimer

This project only processes public market data for review and research workflows. It does not provide investment advice.
