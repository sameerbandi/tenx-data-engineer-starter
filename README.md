# advisor-positions-migration — seed repository

Legacy advisor investment data (mutual funds and ETFs) for August 2026, and the month-end positions produced by the migrated platform. The full task is in the challenge document on tenx.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

DuckDB and pandas are listed in `requirements.txt`. Local PySpark is also acceptable; add it yourself if you use it. No cloud account is needed.

## Data

All files are CSV with a header row. Timestamps are ISO 8601. Units are fund units to 4 decimal places.

### data/legacy/opening_positions_2026-07-31.csv

Positions held at the close of 31 July 2026.

| Column | Meaning |
| --- | --- |
| account_id | Advisor client account |
| client_ref | Client identifier (sensitive) |
| fund_code | Fund held |
| units | Units held |
| as_of_date | Position date |

### data/legacy/transactions_*.csv

Transaction batches delivered by the legacy platform. Each file is one delivered batch.

| Column | Meaning |
| --- | --- |
| txn_id | Transaction identifier |
| batch_date | Date of the delivered batch |
| account_id | Advisor client account |
| client_ref | Client identifier (sensitive) |
| fund_code | Fund traded |
| txn_type | BUY adds units, SELL removes units |
| units | Units traded (always positive) |
| trade_ts | Execution timestamp |

### data/legacy/fund_reference.csv

| Column | Meaning |
| --- | --- |
| fund_code | Fund code |
| fund_name | Fund name |
| fund_type | MF (mutual fund) or ETF |
| currency | Pricing currency |
| superseded_by | Replacement fund code, if any |
| effective_date | Date the replacement took effect |

### data/legacy/nav_prices.csv

Daily net asset value per unit, in the fund's pricing currency: `price_date`, `fund_code`, `nav`, `currency`.

### data/legacy/fx_rates.csv

Daily exchange rates: `rate_date`, `from_currency`, `to_currency`, `rate` (1 unit of `from_currency` in `to_currency`).

### data/migrated/positions_2026-08-31.csv

Month-end positions from the migrated platform: `account_id`, `fund_code`, `units`, `market_value_cad`, `as_of_date`.

## Conventions

- The bank's business day is defined in Toronto (America/Toronto).
- Month-end market value = units × NAV on the as-of date, converted to CAD at that date's rate where needed. `market_value_cad` is rounded to 2 decimals.
- Treat differences below 0.0001 units and below 0.01 CAD as matching.
- Report totals (`total_market_value_cad`, `market_value_cad_by_fund`) come from your legacy-derived positions.

## Output

`python run.py` must write `out/recon_report.json` matching `schema/recon_report.schema.json`.
