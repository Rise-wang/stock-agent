---
name: daily-review
description: Execute the stock-agent daily A-share review workflow: run daily_report.py, validate the generated data package, read the Markdown/JSON facts, attribute moves with a stock-industry-market comparison framework, and produce a disciplined review with no fabricated data, no forecasts, and explicit uncertainty when causes are not supported.
---

# Daily Review

Use this skill when the user asks to execute a daily review, stock review, A-share after-market review, or asks to analyze the generated daily report.

## Workflow

1. Generate the data package.
   - For today/latest: `./scripts/run_daily_review.sh`
   - For a historical trade date: `./scripts/run_daily_review.sh YYYYMMDD`
   - User watchlist defaults to `config/watchlist.json`.
   - One-off override: `WATCHLIST="600519:贵州茅台,000001:平安银行" ./scripts/run_daily_review.sh YYYYMMDD`
   - The command prints the Markdown path and JSON path.

2. Read both outputs.
   - Prefer JSON for exact facts and availability status.
   - Use Markdown for human-readable context and news titles.

3. Validate before reasoning.
   - If validation reports `ERROR`, stop and explain which required facts are missing.
   - If validation reports `WARN`, continue only where facts are present and explicitly mark missing fields.

4. Attribute each stock using three layers in this order:
   - 个股: 当日涨跌幅、成交额/换手、近 5 日走势、龙虎榜；资金流和新闻仅在 JSON 状态可用时使用。
   - 行业: 所属行业或板块快照相对强弱；没有所属行业匹配时只能使用全市场行业概览。
   - 大盘: 上证指数、深证成指、创业板指同日表现。

5. Output one review file when asked to save results:
   - `reports/review_YYYYMMDD.md`

## Hard Rules

- Do not fabricate data.
- Do not predict future prices, rankings, or returns.
- Do not infer fund-flow reasons when fund-flow status is not `ok`.
- Do not infer news-driven reasons when the stock news list is empty.
- Do not invent industry attribution when stock industry is missing.
- If the data does not support a cause, say `未找到足够证据归因`.
- Separate observed facts from interpretation.
- Include a disclaimer that the review is based on public data and is not investment advice.

## Output Shape

Use this structure unless the user requests a different one:

```markdown
# 每日复盘 YYYY-MM-DD

## 数据完整性
- 数据包:
- 缺失项:

## 大盘背景
- ...

## 行业对比
- ...

## 个股复盘
### 股票名(代码)
- 个股事实:
- 行业对比:
- 大盘对比:
- 归因结论:

## 风险与不可归因项
- ...

免责声明: 本复盘仅基于公开数据和脚本抓取结果,不构成投资建议。
```
