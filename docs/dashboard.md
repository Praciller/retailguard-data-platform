# Dashboard Specification

## Report

Name: `RetailGuard Executive Dashboard`

Live report:
[https://datastudio.google.com/u/5/reporting/8e913aa6-d7c0-4367-991d-c173c8f05abb/page/2pS1F](https://datastudio.google.com/u/5/reporting/8e913aa6-d7c0-4367-991d-c173c8f05abb/page/2pS1F)

The report is a one-page executive view backed only by BigQuery serving views. It
does not connect directly to Bronze or raw source tables.

## Implemented Components

Verified in Looker Studio view mode on 2026-06-17:

| Component | BigQuery view | Dimensions | Metrics |
|---|---|---|---|
| Revenue scorecard | `vw_daily_sales` | None | `revenue` |
| Orders scorecard | `vw_daily_sales` | None | `orders` |
| Units scorecard | `vw_daily_sales` | None | `units` |
| AOV scorecard | `vw_executive_summary` | None | `average_order_value` |
| Daily revenue time series | `vw_daily_sales` | `calendar_date` | `revenue` |

The AOV scorecard uses `vw_executive_summary` because the daily AOV field should
not be summed across dates.

## Target Components

| Component | BigQuery view | Dimensions | Metrics |
|---|---|---|---|
| Revenue scorecard | `vw_executive_summary` | None | `revenue` |
| Orders scorecard | `vw_executive_summary` | None | `orders` |
| AOV scorecard | `vw_executive_summary` | None | `average_order_value` |
| Units scorecard | `vw_executive_summary` | None | `units` |
| Daily sales time series | `vw_daily_sales` | `calendar_date` | `revenue`, `orders` |
| Category performance bar | `vw_product_performance` | `category` | `revenue` |
| Customer segment chart | `vw_customer_segments` | `customer_segment` | `revenue` |
| Campaign table | `vw_campaign_performance` | `campaign_id`, `channel` | `clicks`, `conversions`, `conversion_rate_percent`, `attributed_revenue` |

## Formatting

- Currency: Thai baht with two decimals.
- Conversion rate: percent with two decimals.
- Date range: all available synthetic dates by default.
- Sort product and segment charts by revenue descending.
- Use a neutral blue palette and avoid red/green-only encodings.

## Verified Executive Metrics

The first cloud publication produced:

| Metric | Value |
|---|---:|
| Revenue excluding cancelled orders | THB 1,575,759.00 |
| Orders excluding cancelled orders | 479 |
| Average order value | THB 3,289.68 |
| Units | 3,005 |
