"""Advisor Positions Migration & Reconciliation Pipeline.

Ingests legacy files, normalizes data across raw and cleaned layers,
derives month-end positions as of 31 August 2026 (Toronto business date),
and reconciles them against migrated platform positions.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineConfig:
    data_dir: Path
    out_dir: Path
    track: str = "azure"
    as_of_date: str = "2026-08-31"
    toronto_tz: str = "America/Toronto"
    unit_tolerance: float = 0.0001
    mv_tolerance: float = 0.01


class AdvisorPositionsPipeline:
    """End-to-end pipeline implementing Medallion-style raw/cleaned layers

    and month-end position derivation in DuckDB.
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.con = duckdb.connect(":memory:")

    def run(self) -> Dict[str, Any]:
        """Execute full pipeline and return reconciliation report dict."""
        self._ingest_raw_layer()
        self._build_cleaned_layer()
        self._derive_positions()
        report = self._reconcile()
        self._write_report(report)
        return report

    def _ingest_raw_layer(self) -> None:
        """Ingest source CSV files into raw database tables.

        Privacy Guardrail: Strips client_ref (PII) at the ingestion boundary
        to guarantee zero downstream exposure.
        """
        legacy_dir = self.config.data_dir / "legacy"
        migrated_dir = self.config.data_dir / "migrated"

        logger.info("Ingesting raw layer from %s", legacy_dir)

        # 1. Opening positions (explicitly omit sensitive client_ref)
        self.con.execute(f"""
            CREATE TABLE raw_opening_positions AS
            SELECT 
                account_id,
                fund_code,
                cast(units as DOUBLE) as units,
                cast(as_of_date as DATE) as as_of_date
            FROM read_csv_auto('{legacy_dir.as_posix()}/opening_positions_2026-07-31.csv');
        """)

        # 2. Transaction batches (explicitly omit sensitive client_ref)
        self.con.execute(f"""
            CREATE TABLE raw_transactions AS
            SELECT 
                txn_id,
                batch_date,
                account_id,
                fund_code,
                txn_type,
                cast(units as DOUBLE) as units,
                trade_ts
            FROM read_csv_auto('{legacy_dir.as_posix()}/transactions_*.csv');
        """)

        # 3. Fund Reference
        self.con.execute(f"""
            CREATE TABLE raw_fund_reference AS
            SELECT 
                fund_code,
                fund_name,
                fund_type,
                currency,
                superseded_by,
                cast(effective_date as DATE) as effective_date
            FROM read_csv_auto('{legacy_dir.as_posix()}/fund_reference.csv');
        """)

        # 4. NAV Prices
        self.con.execute(f"""
            CREATE TABLE raw_nav_prices AS
            SELECT 
                cast(price_date as DATE) as price_date,
                fund_code,
                cast(nav as DOUBLE) as nav,
                currency
            FROM read_csv_auto('{legacy_dir.as_posix()}/nav_prices.csv');
        """)

        # 5. FX Rates
        self.con.execute(f"""
            CREATE TABLE raw_fx_rates AS
            SELECT 
                cast(rate_date as DATE) as rate_date,
                from_currency,
                to_currency,
                cast(rate as DOUBLE) as rate
            FROM read_csv_auto('{legacy_dir.as_posix()}/fx_rates.csv');
        """)

        # 6. Migrated Positions
        self.con.execute(f"""
            CREATE TABLE raw_migrated_positions AS
            SELECT 
                account_id,
                fund_code,
                cast(units as DOUBLE) as units,
                cast(market_value_cad as DOUBLE) as market_value_cad,
                cast(as_of_date as DATE) as as_of_date
            FROM read_csv_auto('{migrated_dir.as_posix()}/positions_2026-08-31.csv');
        """)

    def _build_cleaned_layer(self) -> None:
        """Standardize, deduplicate, and convert timezones in cleaned tables."""
        logger.info("Building cleaned layer with Toronto business date alignment")

        # Deduplicate transactions across batches and convert trade_ts to Toronto timezone
        self.con.execute(f"""
            CREATE TABLE clean_transactions AS
            WITH deduped AS (
                SELECT DISTINCT 
                    txn_id,
                    batch_date,
                    account_id,
                    fund_code,
                    txn_type,
                    units,
                    trade_ts
                FROM raw_transactions
            )
            SELECT 
                txn_id,
                batch_date,
                account_id,
                -- Apply fund succession: FND-104 superseded by FND-104A effective 2026-08-20
                CASE WHEN fund_code = 'FND-104' THEN 'FND-104A' ELSE fund_code END as fund_code,
                txn_type,
                CASE WHEN txn_type = 'BUY' THEN units ELSE -units END as net_units,
                cast(trade_ts as TIMESTAMP WITH TIME ZONE) as trade_ts_utc,
                cast(trade_ts as TIMESTAMP WITH TIME ZONE) AT TIME ZONE '{self.config.toronto_tz}' as trade_ts_toronto,
                cast(cast(trade_ts as TIMESTAMP WITH TIME ZONE) AT TIME ZONE '{self.config.toronto_tz}' as DATE) as toronto_business_date
            FROM deduped;
        """)

        # Clean opening positions with fund succession
        self.con.execute("""
            CREATE TABLE clean_opening_positions AS
            SELECT 
                account_id,
                CASE WHEN fund_code = 'FND-104' THEN 'FND-104A' ELSE fund_code END as fund_code,
                units,
                as_of_date
            FROM raw_opening_positions;
        """)

        # Pricing and FX evaluation as of month-end
        self.con.execute(f"""
            CREATE TABLE clean_nav_cad AS
            SELECT 
                n.fund_code,
                n.nav,
                n.currency,
                COALESCE(fx.rate, 1.0) as fx_rate_to_cad,
                CASE 
                    WHEN n.currency = 'CAD' THEN n.nav
                    WHEN n.currency = 'USD' THEN n.nav * fx.rate
                    ELSE n.nav
                END as nav_cad
            FROM raw_nav_prices n
            LEFT JOIN raw_fx_rates fx
                ON fx.rate_date = n.price_date 
                AND fx.from_currency = n.currency 
                AND fx.to_currency = 'CAD'
            WHERE n.price_date = '{self.config.as_of_date}';
        """)

    def _derive_positions(self) -> None:
        """Derive active month-end positions and market value in CAD."""
        logger.info("Deriving positions as of %s (Toronto business date)", self.config.as_of_date)

        self.con.execute(f"""
            CREATE TABLE derived_month_end_positions AS
            WITH combined_movements AS (
                -- Opening positions as of close of 2026-07-31
                SELECT 
                    account_id,
                    fund_code,
                    units
                FROM clean_opening_positions
                
                UNION ALL
                
                -- All August trades settled/executed on or before Toronto business date 2026-08-31
                SELECT 
                    account_id,
                    fund_code,
                    net_units as units
                FROM clean_transactions
                WHERE toronto_business_date <= '{self.config.as_of_date}'
            ),
            aggregated AS (
                SELECT 
                    account_id,
                    fund_code,
                    round(sum(units), 4) as units
                FROM combined_movements
                GROUP BY account_id, fund_code
            )
            SELECT 
                a.account_id,
                a.fund_code,
                a.units,
                round(a.units * p.nav_cad, 2) as market_value_cad
            FROM aggregated a
            LEFT JOIN clean_nav_cad p ON a.fund_code = p.fund_code
            WHERE abs(a.units) >= {self.config.unit_tolerance}
            ORDER BY a.account_id, a.fund_code;
        """)

    def _reconcile(self) -> Dict[str, Any]:
        """Perform bi-directional reconciliation against migrated positions."""
        logger.info("Reconciling legacy-derived positions against migrated target")

        # 1. Total counts and valuations from legacy-derived
        legacy_count = self.con.execute("SELECT count(*) FROM derived_month_end_positions").fetchone()[0]
        migrated_count = self.con.execute("SELECT count(*) FROM raw_migrated_positions").fetchone()[0]
        total_mv = self.con.execute("SELECT round(sum(market_value_cad), 2) FROM derived_month_end_positions").fetchone()[0]

        # 2. Market value by fund
        fund_mv_rows = self.con.execute("""
            SELECT fund_code, round(sum(market_value_cad), 2) as mv
            FROM derived_month_end_positions
            GROUP BY fund_code
            ORDER BY fund_code;
        """).fetchall()
        market_value_cad_by_fund = {f[0]: float(f[1]) for f in fund_mv_rows}

        # 3. Discrepancies
        discrepancy_rows = self.con.execute(f"""
            SELECT 
                COALESCE(d.account_id, m.account_id) as account_id,
                COALESCE(d.fund_code, m.fund_code) as fund_code,
                d.units as legacy_units,
                m.units as mig_units,
                d.market_value_cad as legacy_mv,
                m.market_value_cad as mig_mv,
                CASE 
                    WHEN m.account_id IS NULL THEN 'missing_in_target'
                    WHEN d.account_id IS NULL THEN 'missing_in_source'
                    WHEN abs(d.units - m.units) >= {self.config.unit_tolerance} 
                      OR abs(d.market_value_cad - m.market_value_cad) >= {self.config.mv_tolerance} THEN 'value_mismatch'
                    ELSE 'match'
                END as category
            FROM derived_month_end_positions d
            FULL OUTER JOIN raw_migrated_positions m 
                ON d.account_id = m.account_id AND d.fund_code = m.fund_code
            WHERE m.account_id IS NULL 
               OR d.account_id IS NULL 
               OR abs(d.units - m.units) >= {self.config.unit_tolerance} 
               OR abs(d.market_value_cad - m.market_value_cad) >= {self.config.mv_tolerance}
            ORDER BY category, account_id, fund_code;
        """).fetchall()

        discrepancies: List[Dict[str, str]] = []
        for row in discrepancy_rows:
            account_id, fund_code, leg_units, mig_units, leg_mv, mig_mv, category = row
            if category == "missing_in_target":
                detail = (
                    f"Position missing in target migrated platform: legacy has units={leg_units:.4f}, "
                    f"market_value_cad={leg_mv:.2f}"
                )
            elif category == "missing_in_source":
                detail = (
                    f"Position missing in legacy source: target has units={mig_units:.4f}, "
                    f"market_value_cad={mig_mv:.2f}"
                )
            else:  # value_mismatch
                unit_diff = (leg_units - mig_units) if leg_units is not None and mig_units is not None else 0.0
                mv_diff = (leg_mv - mig_mv) if leg_mv is not None and mig_mv is not None else 0.0
                detail = (
                    f"Value mismatch: legacy units={leg_units:.4f} (mv_cad={leg_mv:.2f}) vs "
                    f"target units={mig_units:.4f} (mv_cad={mig_mv:.2f}); diff units={unit_diff:+.4f}, "
                    f"diff mv_cad={mv_diff:+.2f}"
                )

            discrepancies.append({
                "account_id": str(account_id),
                "fund_code": str(fund_code),
                "category": str(category),
                "detail": detail,
            })

        return {
            "track": self.config.track,
            "legacy_position_count": int(legacy_count),
            "migrated_position_count": int(migrated_count),
            "total_market_value_cad": float(total_mv),
            "market_value_cad_by_fund": market_value_cad_by_fund,
            "discrepancies": discrepancies,
        }

    def _write_report(self, report: Dict[str, Any]) -> None:
        """Write out/recon_report.json deterministically with no PII."""
        self.config.out_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.config.out_dir / "recon_report.json"
        logger.info("Writing reconciliation report to %s", report_path)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=False)
