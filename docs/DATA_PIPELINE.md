# MoSPI PAIMANA Continuous Data Ingestion Pipeline Architecture
**SIH26017 — Infrastructure Delay & Cost Overrun Intelligence Platform**
**Division**: Infrastructure and Project Monitoring Division (IPMD) | Government of India

---

## 1. Executive Summary & Philosophy
The Infrastructure Delay & Cost Overrun Intelligence Platform ingests, sanitizes, versions, and audits central sector infrastructure projects (costing ₹150 crore and above). The architecture upgrades static historical datasets into a **versioned, continuous government ingestion engine**.

The pipeline enforces six cardinal principles:
1. **Idempotence**: Reprocessing the same snapshot or file produces identical state with zero duplicate entities.
2. **Auditability & Traceability**: Raw source files are archived verbatim (`raw_data_snapshots`) with SHA-256 integrity checksums before normalization.
3. **Data Quality Gate**: Suspicious or corrupted records (negative costs, implausible dates beyond 2056, CSV formula injections) are quarantined into `data_quality_runs` rather than silently mutated.
4. **Zero-Leakage ML Separation**: Data ingestion runs independently from model retraining. Downstream indicators (cumulative expenditure, revised costs, elapsed delay) are strictly isolated from inception risk models.
5. **No Hallucinated or Fake Real-Time Claims**: Dashboards explicitly display `"HISTORICAL SNAPSHOT"` and declare `"READY FOR AUTHORIZED GOVERNMENT API CREDENTIALS"` rather than claiming unauthorized live API connectivity.
6. **Provenance Enforcement**: Every datum is stamped as `[SOURCE — MoSPI PAIMANA]`, `[DERIVED METRIC]`, `[AI PREDICTION]`, or `[DEMO/SIMULATION]`.

---

## 2. End-to-End Pipeline Topology

```
                  OFFICIAL GOVERNMENT SOURCES
             (MoSPI PAIMANA Open Reports / APIs)
                             │
                             ▼
                    SOURCE ADAPTERS
       (PaimanaAdapter: CSV / XLSX / REST Handlers)
                             │
                             ▼
                     RAW DATA SNAPSHOTS
       (raw_data_snapshots: SHA-256 Checksum, Size, Raw BLOB)
                             │
                             ▼
                    DATA QUALITY GATE
       (Schema Validation, Outlier Detection, CWE-1236 Defense)
             │                                   │
             │ [Passed Records]                  │ [Quarantined Records]
             ▼                                   ▼
      NORMALIZATION LAYER                data_quality_runs
    (project_versions v2.1)             (Quarantine Telemetry)
             │
             ▼
        SUPABASE DB
   (PostgreSQL / SQLite Dual-Engine)
             │
    ┌────────┼─────────────────┐
    ▼        ▼                 ▼
Analytics  History       Zero-Leakage ML
 (Macro) (Snapshots)  (Gradient Boosting)
    │        │                 │
    └────────┼─────────────────┘
             ▼
       EARLY WARNING
   (LOW → MED → HIGH → CRIT)
             │
             ▼
  CRITICAL ALERTS WATCHLIST
             │
             ▼
  WHAT-IF POLICY SIMULATOR
             │
             ▼
INSTITUTIONAL DECISION DASHBOARD
```

---

## 3. Detailed Ingestion Stages

### Stage 1: Source Acquisition & Ingestion Adapter
- **Adapter**: `backend/adapters/paimana_adapter.py`
- **Supported Channels**:
  - `OFFICIAL_CSV`: Official MoSPI project telemetry exports.
  - `OFFICIAL_XLSX`: Excel workbooks published by central ministries.
  - `OFFICIAL_API`: Pre-configured REST handler designed for secure token authentication once governmental API gateway credentials are provided.
- **Safety**: Safe parser converts numeric types, cleans whitespace, strips unsafe leading formula characters (`=`, `+`, `-`, `@`, `\t`, `\r`) to eliminate Formula Injection vulnerabilities (CWE-1236).

### Stage 2: Raw Data Layer & Checksums
- Every file received is hashed using standard **SHA-256**.
- The raw byte content, row count, and provenance reference are recorded in `raw_data_snapshots`.
- If a file with an identical SHA-256 checksum is resubmitted, the system flags it as idempotent and avoids re-allocating redundant project entities.

### Stage 3: Data Quality Gate
Every record is evaluated against programmatic validity criteria:
- **Project Identifier**: Must be positive non-zero integer.
- **Costs**: `original_cost_cr >= 0.0`. Negative outlays are quarantined immediately.
- **Milestone Dates**: Target completion dates must be valid ISO / Gregorian dates before year 2056. Implausible future dates trigger audit quarantine.
- **Cost Overruns**: Unrevised projects (`revised_cost_cr == 0.0`) are classified as `NOT_YET_REVISED_COST` sentinel values rather than negative cost overruns.
- **Quarantine Output**: Quarantined records are stored in `data_quality_runs` with failure reasons (`QUARANTINED_NEGATIVE_COST`, `QUARANTINED_INVALID_IDENTIFIER`).

### Stage 4: Project Versioning & Normalization
- Each accepted row creates an immutable snapshot entry in `project_versions` keyed by `(project_code, snapshot_id)`.
- The primary operational `projects` table is upserted with the latest confirmed values.
- Historical snapshots are preserved permanently; older project versions are never overwritten.

### Stage 5: Snapshot Change Detection Engine
- **Engine**: `backend/change_detection.py`
- Executes a full set comparison between the newly ingested snapshot and the chronologically preceding snapshot.
- Categorizes all projects into five discrete states:
  1. `NEW`: First time appearance in national monitoring.
  2. `UPDATED`: Existing project with cost escalation, schedule slippage, schedule recovery, or revised completion movement.
  3. `UNCHANGED`: Zero variance across financial and milestone parameters.
  4. `COMPLETED`: Successfully commissioned and transitioned off active monitoring.
  5. `REMOVED_FROM_ACTIVE_SNAPSHOT`: Omitted from current snapshot.
- Computes macro deltas (`cost_change_cr`, `revised_cost_change_cr`, `expenditure_change_cr`, `schedule_change_days`).
- Persists individual events in `project_change_events`.

### Stage 6: Temporal Risk Tracking & Alert Intelligence
- **Engine**: `backend/risk_tracker.py`
- Scores incoming projects through the `Zero-Leakage Inception Model`.
- Records point-in-time predictions in `prediction_history` keyed by `(prediction_id, project_code, snapshot_id, model_version)`.
- Compares previous risk tier with current risk tier:
  - Detects `LOW → MEDIUM`, `MEDIUM → HIGH`, and `HIGH → CRITICAL` transitions.
  - Automatically dispatches institutional alerts to `project_alerts` for immediate review by the Project Monitoring Group (PMG) and Cabinet Secretariat.

---

## 4. API Endpoints for Ingestion Governance
- `GET /api/v1/data/sources`: Lists registered official sources and access methods.
- `GET /api/v1/data/snapshots`: Returns chronologically ordered snapshots catalog with SHA-256 checksums.
- `GET /api/v1/data/snapshots/{id}`: Full breakdown of a single snapshot.
- `GET /api/v1/data/changes`: Deterministic delta statistics between two snapshots.
- `GET /api/v1/data/freshness`: Public telemetry verifying snapshot age, record count, and honest status.
- `POST /api/v1/data/ingest`: Protected ingestion endpoint (Enforces JWT Bearer authentication and `ADMIN` or `OFFICER` roles).
