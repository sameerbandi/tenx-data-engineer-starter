# Production Architecture & Migration Design (Azure / Microsoft Fabric)

## 1. Ingestion & Orchestration
* **Ingestion**: Azure Data Factory (ADF) / Fabric Data Pipelines ingest batch files (positions, transactions, NAV, FX) via ADLS Gen2/SFTP. Real-time intraday trades land via Azure Event Hubs into Fabric Eventstream.
* **Orchestration**: Fabric Data Pipelines orchestrate daily workflows on file arrival. Timezone logic aligns execution to Toronto business close (`America/Toronto`).

## 2. Storage Layers & Table Format
Built on Microsoft Fabric OneLake using **Delta Lake** (Parquet with ACID logs):
* **Bronze (Raw)**: Append-only raw landing zone preserving batch history. PII (`client_ref`) is hashed at ingestion.
* **Silver (Cleaned)**: Deduplicated (`txn_id`), validated, and typed tables. Timestamps convert to Toronto dates; fund replacements (e.g., `FND-104` to `FND-104A`) are applied.
* **Gold (Curated)**: Dimensional star schema models (`dim_account`, `dim_fund`, `fact_position_daily`) powering Direct Lake semantic models.

## 3. Incremental Load Strategy & Idempotency
* **Strategy**: Transactions load incrementally using a high-watermark on `trade_ts`.
* **Safe Reruns & Idempotency**: Silver updates use Delta Lake `MERGE` on `txn_id`. Daily positions in Gold use deterministic partition overwrites (`REPLACE WHERE as_of_date = 'YYYY-MM-DD'`). Replaying failed batches or resent files (`transactions_*_resend.csv`) produces identical state without duplicates.

## 4. Reconciliation as a Release Gate
Automated reconciliation runs after position derivation prior to Gold publishing:
* **Blocking Gates**:
  1. `missing_in_target > 0` or `missing_in_source > 0` (zero tolerance for dropped/phantom accounts).
  2. Discrepancies exceeding tolerance (>0.0001 units, >$0.01 CAD).
  3. Total portfolio CAD market value variance > 0.001%.
* **Enforcement**: Gate failure aborts the pipeline, halts semantic model refreshes, creates a Sev-1 incident, and blocks CD promotion.

## 5. Governance & Compliance
* **PII & Data Protection**: `client_ref` is salted and hashed (SHA-256) at Bronze entry; salt is secured in Azure Key Vault. Downstream layers only use surrogate keys, satisfying PIPEDA.
* **Access Control**: Fabric RBAC with Azure Entra ID. Row-Level Security (RLS) restricts advisors to assigned accounts.
* **Lineage & Audit**: Microsoft Purview captures automated end-to-end column lineage. Azure Monitor logs all read/write activities.

## 6. CI/CD & Day-One Monitoring
* **CI/CD**: Azure DevOps / GitHub Actions with Fabric Git integration. PRs trigger linting, unit tests, and reconciliation smoke tests against staging Lakehouses.
* **Day-One Alerts**:
  1. *Pipeline SLA Breach*: Batch incomplete by 21:00 Toronto time.
  2. *Reconciliation Gate Failure*: Discrepancy detected.
  3. *Volume Anomaly*: Record counts deviating >25% from 30-day mean.
  4. *Schema Drift / Poison Queue*: Malformed rows diverted to quarantine.

---

## Azure Track: Migration Plan to Microsoft Fabric

```
Assessment & Design  -->  Foundation & Build  -->  Dual-Run Shadow  -->  Cutover  -->  Decommission
    [2 Weeks]                  [4 Weeks]               [4 Weeks]         [1 Day]        [90 Days]
```

1. **Phase 1 — Assessment & Discovery (Weeks 1-2)**: Inventory legacy batch feeds, stored procs, and capacity sizing (Fabric F64+). *Validated*: Data dictionary, schema mappings, historical balance baselines.
2. **Phase 2 — Foundation & Build (Weeks 3-6)**: Provision OneLake, Lakehouse workspaces, Delta schemas, and pipelines with PII masking. *Validated*: Unit tests, data type precision (4-decimal units for money market funds).
3. **Phase 3 — Dual-Run & Shadow Validation (Weeks 7-10)**: Execute legacy and Fabric pipelines concurrently for 30 business days with daily automated reconciliation. *Validated*: 100% position match, zero valuation drift, SLA compliance (<15 min).
4. **Phase 4 — Cutover (Week 11, Weekend)**: Final delta sync, business sign-off, repointing advisor portals to Fabric Direct Lake. *Validated*: Smoke tests, advisor portal validation, operational sign-off.
5. **Phase 5 — Decommissioning (Post-Cutover, 90 Days)**: Legacy system set to read-only; historical data archived to immutable Azure cold storage. *Validated*: Regulatory archive compliance audit.
