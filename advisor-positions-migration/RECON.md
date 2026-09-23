# Reconciliation Analysis

Reconciliation of legacy-derived positions against the migrated target as of 31 August 2026 identified 15 discrepancies across two categories.

### 1. missing_in_target (Count: 12)
* **Finding**: 12 active positions ($227,134.35 CAD) are missing from the target. All 12 belong to two accounts: `ACC-1027` (7 positions, $127,496.17 CAD) and `ACC-1034` (5 positions, $99,638.18 CAD). Both had active July 31 balances and August trades.
* **Most Likely Cause**: Upstream account extraction failure in the migration ETL pipeline (e.g., unintended client exclusion filter, status flag error, or dropped partition during export).
* **Action**: **Raise with the migration team**. This is a target omission defect. The pipeline must not fabricate or drop data; the migration team must fix the extraction query and reload both accounts before cutover.

### 2. value_mismatch (Count: 3)
* **Finding**: 3 positions show fractional unit and valuation variances in `FND-105` (Maple Money Market Fund, NAV = $10.00 CAD):
  * `ACC-1011`: legacy 2013.2983 units vs target 2013.0000 units (diff: -0.2983 units, -$2.98 CAD)
  * `ACC-1031`: legacy 294.3723 units vs target 294.0000 units (diff: -0.3723 units, -$3.72 CAD)
  * `ACC-1038`: legacy 207.7756 units vs target 207.0000 units (diff: -0.7756 units, -$7.76 CAD)
* **Most Likely Cause**: Decimal precision truncation or integer casting (`INT` instead of `DECIMAL(18,4)`) in target transformation logic for money market funds.
* **Action**: **Raise with the migration team**. The target schema must retain 4-decimal precision for fund units. Adjusting the pipeline to match target truncation would compromise financial accuracy.

### 3. missing_in_source (Count: 0)
* **Finding**: Zero phantom positions in target.
* **Most Likely Cause**: Target positions map to valid legacy accounts.
* **Action**: **No fix needed**. Enforce this zero-tolerance threshold in release gates.
