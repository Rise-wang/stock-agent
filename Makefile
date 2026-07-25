.PHONY: daily-review daily-report validate test alert backtest

DATE ?=
REPORT ?=
WATCHLIST ?=
WATCHLIST_FILE ?=
SYMBOL ?= 600519
START ?= 20240101
END ?= 20240719
FAST ?= 5
SLOW ?= 20

daily-review:
	WATCHLIST="$(WATCHLIST)" WATCHLIST_FILE="$(WATCHLIST_FILE)" ./scripts/run_daily_review.sh $(DATE)

daily-report:
	python3 scripts/daily_report.py $(DATE) $(if $(WATCHLIST),--watchlist "$(WATCHLIST)",) $(if $(WATCHLIST_FILE),--watchlist-file "$(WATCHLIST_FILE)",)

validate:
	python3 scripts/validate_report.py $(REPORT)

test:
	PYTHONPYCACHEPREFIX=/private/tmp/pycache-stock-agent python3 -m py_compile scripts/daily_report.py scripts/alert_watch.py scripts/backtest_run.py scripts/validate_report.py
	python3 -m unittest tests/test_scripts.py

alert:
	python3 scripts/alert_watch.py

backtest:
	python3 scripts/backtest_run.py --symbol $(SYMBOL) --start $(START) --end $(END) --fast $(FAST) --slow $(SLOW)
