"""Entry point. `python run.py` builds the pipeline and writes out/recon_report.json.

Exposes no client identifier (client_ref) in any output file.
Finishes in under two minutes and produces deterministic outputs.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# Adjust sys.path to ensure local imports succeed
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from pipeline import AdvisorPositionsPipeline, PipelineConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("run")


def validate_schema(report_path: Path, schema_path: Path) -> None:
    """Validate reconciliation report against schema."""
    with open(report_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Check basic schema assertions unconditionally
    required_keys = [
        "track",
        "legacy_position_count",
        "migrated_position_count",
        "total_market_value_cad",
        "market_value_cad_by_fund",
        "discrepancies",
    ]
    for key in required_keys:
        if key not in data:
            raise ValueError(f"Schema violation: missing required property '{key}'")

    if data["track"] not in ("azure", "aws"):
        raise ValueError(f"Invalid track: {data['track']}")

    for item in data["discrepancies"]:
        for d_key in ("account_id", "fund_code", "category", "detail"):
            if d_key not in item:
                raise ValueError(f"Discrepancy item missing required property '{d_key}'")
        if item["category"] not in ("missing_in_target", "missing_in_source", "value_mismatch"):
            raise ValueError(f"Invalid discrepancy category: {item['category']}")

    # If jsonschema is available, run full validation
    try:
        import jsonschema

        with open(schema_path, "r", encoding="utf-8") as sf:
            schema = json.load(sf)
        jsonschema.validate(instance=data, schema=schema)
        logger.info("JSON schema validation passed via jsonschema.")
    except ImportError:
        logger.info("JSON schema validation passed via built-in validator (jsonschema not installed).")


def main() -> None:
    start_time = time.perf_counter()

    parser = argparse.ArgumentParser(description="Advisor Positions Migration & Reconciliation")
    parser.add_argument(
        "--track",
        type=str,
        choices=["azure", "aws"],
        default=os.environ.get("RECON_TRACK", "azure"),
        help="Target cloud track (default: azure)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=CURRENT_DIR / "data",
        help="Path to data directory",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=CURRENT_DIR / "out",
        help="Path to output directory",
    )
    args = parser.parse_args()

    logger.info("Starting advisor positions reconciliation pipeline (track: %s)", args.track)

    config = PipelineConfig(
        data_dir=args.data_dir,
        out_dir=args.out_dir,
        track=args.track,
    )

    pipeline = AdvisorPositionsPipeline(config)
    report = pipeline.run()

    report_file = args.out_dir / "recon_report.json"
    schema_file = CURRENT_DIR / "schema" / "recon_report.schema.json"
    if schema_file.exists():
        validate_schema(report_file, schema_file)

    elapsed = time.perf_counter() - start_time
    logger.info("Pipeline completed successfully in %.2f seconds.", elapsed)
    logger.info(
        "Summary: legacy_positions=%d, migrated_positions=%d, total_mv_cad=%.2f, discrepancies=%d",
        report["legacy_position_count"],
        report["migrated_position_count"],
        report["total_market_value_cad"],
        len(report["discrepancies"]),
    )


if __name__ == "__main__":
    main()
