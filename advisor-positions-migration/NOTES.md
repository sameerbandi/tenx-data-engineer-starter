# Notes

## What I don't trust
1. **Fund Succession Mechanics**: I mapped `FND-104` to `FND-104A` assuming 1:1 units without an exchange ratio. In production corporate actions (fund mergers or series conversions), unit ratios often differ from 1.0 or involve cash-in-lieu. I would verify the prospectus and transfer agency notices.
2. **Missing FX Fallback**: The pipeline assumes FX rates exist for every pricing date. During bank holidays or feed delays, missing rates could yield null market values. I would verify holiday calendars and implement a prior-business-day carry-forward rule.
3. **Target Truncation Scope**: I inferred the 3 `FND-105` value mismatches stem from integer truncation in the migrated system. I would verify with target engineers whether this is an intentional convention or an unintended schema cast (`INT` vs `DECIMAL`).

## AI use
I used AI assistance within Google Antigravity IDE to accelerate exploratory data analysis (identifying the duplicate August 14 batch and September 1 timezone boundary trades), generate boilerplate for JSON schema validation, and outline technical documentation. All calculation logic, DuckDB transformations, reconciliation tolerances, and architectural proposals were rigorously reviewed, tested, and verified against the repository data.
