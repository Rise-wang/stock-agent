# Contributing

Thanks for improving `stock-agent`.

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
make test
```

## Pull Requests

- Keep changes focused and small.
- Add or update tests for behavior changes.
- Do not commit generated files from `reports/` or local logs.
- Do not add API keys, private SSH keys, tokens, account cookies, or brokerage credentials.
- Keep review logic evidence-based: missing data must stay explicit rather than inferred.

## Data Source Changes

AkShare wrappers can change or become unstable. If you change a data source:

- Prefer sources that work without private credentials.
- Keep failures explicit in Markdown and JSON output.
- Update `README.md` and tests when fields or statuses change.
- Avoid adding dependencies on Eastmoney endpoints unless they are optional and disabled by default.
