# stock-agent

A-share daily review agent toolkit built around AkShare public data sources.

## Features

- Generate daily Markdown and JSON data packages for a configurable watchlist.
- Add relative-strength metrics and candidate labels for rebound/continuation screening.
- Optionally enrich reports with Eastmoney individual fund-flow and stock-news data.
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

Optionally enrich attribution with `config/stock_profiles.json`:

```json
{
  "profiles": {
    "600519": {
      "industry": "白酒",
      "industry_aliases": ["酿酒"],
      "concepts": ["消费"],
      "keywords": ["高端白酒"]
    }
  }
}
```

Profiles are used for industry matching, hot-topic keyword expansion, and cleaner attribution. Missing profiles are reported as warnings, not hard errors.

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

Optional Eastmoney enrichment is enabled by default for fund flow and stock news. For the latest trade date, fund flow uses the more reliable all-stock snapshot by default; for historical trade dates it uses the individual daily fund-flow source when available. Disable Eastmoney enrichment when the upstream source is unstable:

```bash
STOCK_ENABLE_EASTMONEY=0 ./scripts/run_daily_review.sh 20240719
```

Try the detailed individual daily fund-flow source for the latest trade date:

```bash
STOCK_FUND_FLOW_DETAIL=1 ./scripts/run_daily_review.sh
```

Send a report by authenticated SMTP:

```bash
cp config/email.example.json config/email.local.json
# Edit config/email.local.json with your sender address and SMTP authorization code.
python3 scripts/send_email.py \
  --subject "每日股票与热点复盘 2026-07-25" \
  --body-file reports/email_digest_20260725.md
```

For QQ Mail, enable SMTP in mailbox settings and use the generated authorization code as `smtp_password`. The local `mail` command may be rejected by public mail providers because it sends from a local hostname such as `*.local`.

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

The JSON stock blocks include:

- `relative_strength`: 5/10/20-day returns, market/industry relative strength, close position, and volume/amount expansion.
- `candidate_signal`: a screening label such as `稳健修复`, `强势接力`, `跌深反抽`, or `弱势待确认`, plus supporting facts and risk flags.
- `fund_flow`: Eastmoney fund-flow status. Latest-date snapshot includes net inflow/inflow/outflow; detailed daily source includes main/super-large/large/medium/small order flow when available.
- `news`: Eastmoney stock-news status and recent items filtered to the report trade date or earlier.

See `examples/` for a shortened sample report.

## Data Sources

The default scripts use AkShare wrappers around Sina, Tonghuashun, Tencent, and optional Eastmoney public data sources where available.

Eastmoney enrichment is best-effort. If fund flow or stock news fails, the JSON status is marked explicitly and review workflows must not infer causes from missing data.

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
