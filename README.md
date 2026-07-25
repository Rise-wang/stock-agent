# stock-agent

A-share daily review agent toolkit built around AkShare public data sources.

## Features

- Generate daily Markdown and JSON data packages for a configurable watchlist.
- Monitor intraday abnormal moves with one-line `ALERT`/`OK` output.
- Run a Backtrader moving-average crossover backtest.
- Validate generated daily report data before review.
- Provide a `daily-review` Skill workflow with strict no-fabrication rules.

## Requirements

- Python 3.9+
- Network access to public market data sources used by AkShare

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

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

Or with an environment variable:

```bash
STOCK_WATCHLIST="000001:平安银行,600519:贵州茅台" ./scripts/run_daily_review.sh 20240719
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

## Output Files

Generated reports are written to `reports/` and ignored by git:

- `reports/report_YYYYMMDD.md`
- `reports/report_YYYYMMDD.json`
- `reports/review_YYYYMMDD.md` when a review is saved

See `examples/` for a shortened sample report.

## Data Sources

The default scripts avoid Eastmoney endpoints because they were unreliable in the target environment. Current defaults use AkShare wrappers around Sina, Tonghuashun, and Tencent public data sources where available.

Unavailable fields such as non-Eastmoney individual fund flow and stock-specific news are explicitly marked as unsupported, and review workflows must not infer causes from missing data.

## Daily Review Skill

The repository includes a Codex Skill at `.agents/skills/daily-review/SKILL.md`.

When triggered, the expected workflow is:

1. Run `./scripts/run_daily_review.sh [YYYYMMDD]`.
2. Read the generated Markdown and JSON files.
3. Validate data availability.
4. Attribute stock moves through stock, industry, and market layers.
5. Explicitly say when the data does not support a cause.

## Development

```bash
make test
```

CI runs the same offline test target on push and pull request. Tests avoid live market data calls.

## Contributing

See `CONTRIBUTING.md`.

## Security

See `SECURITY.md`.

## License

MIT. See `LICENSE`.

## Disclaimer

This project only processes public market data for review and research workflows. It is not investment advice. Data may be delayed, incomplete, unavailable, or wrong. Users are responsible for their own investment decisions and risk controls.
