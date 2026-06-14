# Data Dictionary

## Dimensions

### `dim_customer`

| Column | Type | Description |
|---|---|---|
| `customer_key` | integer | Stable warehouse hash of `customer_id` |
| `customer_id` | string | Synthetic customer business key |
| `email_hash` | string | SHA-256 email digest with a project salt |
| `phone_masked` | string | Last four digits only |
| `customer_city` | string | City-level location |
| `customer_segment` | string | `new`, `regular`, `loyal`, or `vip` |

### `dim_product`

| Column | Type | Description |
|---|---|---|
| `product_key` | integer | Stable warehouse hash of `product_id` |
| `product_id` | string | Product business key |
| `product_name` | string | Synthetic product name |
| `category` | string | Product reporting category |
| `current_unit_price` | decimal | Current synthetic catalogue price |
| `is_active` | boolean | Product activity flag |

### `dim_date`

One row per order or campaign calendar date with year, quarter, month, day,
day-of-week, and weekend attributes.

### `dim_channel`

One row per campaign channel: email, social, search, or affiliate.

## Facts

### `fact_sales`

Grain: one row per order item.

Measures: quantity, unit price, and gross amount. Degenerate attributes include
order status and payment method. Customer, product, and date dimensions are joined
by warehouse keys.

### `fact_campaign_events`

Grain: one row per campaign event.

Measures: attributed revenue. Attributes include campaign, channel, and event type.

## Serving Views

| View | Purpose |
|---|---|
| `vw_executive_summary` | Revenue, orders, average order value, and units |
| `vw_daily_sales` | Daily revenue and order trend |
| `vw_product_performance` | Revenue and units by product and category |
| `vw_customer_segments` | Customers, orders, and revenue by segment |
| `vw_campaign_performance` | Clicks, conversions, attributed revenue, and rate |
