# Historical Snapshot Architecture & Raw Data Preservation
**SIH26017 — Infrastructure Delay & Cost Overrun Intelligence Platform**
**Division**: Infrastructure and Project Monitoring Division (IPMD) | Government of India

---

## 1. Architectural Philosophy: The Non-Cumulative Nature of Snapshots
The platform monitors Central Sector infrastructure projects. A fundamental error in naive infrastructure tracking is treating snapshot project counts as cumulative totals. 

**Official Project Snapshot Reality:**
- An infrastructure snapshot is a **cross-sectional census** of active, sanctioned projects at a specific moment in time.
- As projects achieve commissioning, complete construction, or exit central sector jurisdiction, they are retired from active monitoring.
- As new capital works are sanctioned by the Cabinet Committee on Economic Affairs (CCEA), new project codes appear.
- Therefore, project counts fluctuate naturally:
  - `paimana_2026_04`: **1,981 projects** (Official April 2026 Baseline)
  - `paimana_2026_05`: **1,987 projects** (May 2026 Progression: +6 New Projects)
  - `paimana_2026_06`: Hypothetical ~1,847 projects (Commissioned works removed)
  - `paimana_2026_07`: Hypothetical ~1,775 projects

The system **never overwrites historical snapshots**. Older project states remain fully queryable for longitudinal auditing and trajectory analysis.

---

## 2. Raw Data Layer (`raw_data_snapshots`)
Before any record is parsed, transformed, or loaded into production relations, the raw payload is preserved in `raw_data_snapshots`:

```sql
CREATE TABLE raw_data_snapshots (
    id VARCHAR(64) PRIMARY KEY,
    snapshot_id VARCHAR(64) NOT NULL,
    source_reference VARCHAR(512) NOT NULL,
    filename_or_api VARCHAR(255) NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    raw_record_count INTEGER NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    processing_status VARCHAR(32) NOT NULL DEFAULT 'COMPLETED',
    quarantined_record_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### Tamper-Evidence via SHA-256 Checksums
- For every incoming snapshot, the SHA-256 hash is computed across the raw byte stream:
  `sha256 = hashlib.sha256(raw_bytes).hexdigest()`
- Checksums are stored with `sha256:` prefix in `data_snapshots.source_checksum` and `raw_data_snapshots.checksum`.
- Any external modification to an archived snapshot file is immediately detectable via checksum divergence during automated integrity audits.

---

## 3. Idempotent Ingestion Protocol
A mission-critical requirement for government systems is idempotence: **ingesting the exact same file twice must produce identical database state with zero record duplication**.

The pipeline achieves idempotence through compound unique constraints and upsert logic:
1. `data_snapshots (id)`: `ON CONFLICT (id) DO UPDATE SET record_count = excluded.record_count ...`
2. `project_versions (project_code, snapshot_id)`: `ON CONFLICT (project_code, snapshot_id) DO UPDATE SET revised_cost = excluded.revised_cost ...`
3. `projects (project_code)`: `ON CONFLICT (project_code) DO UPDATE SET ...`
4. `project_change_events (from_snapshot_id, to_snapshot_id)`: Pre-existing change event sets for that specific pair are pruned and regenerated deterministically.

---

## 4. Snapshot Catalog Schema (`data_snapshots`)

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | `VARCHAR(64)` PRIMARY KEY | Standard slug (e.g. `paimana_2026_04`). |
| `source_id` | `VARCHAR(64)` | Foreign key referencing `data_source_registry(id)`. |
| `source_name` | `VARCHAR(255)` NOT NULL | Source name. |
| `snapshot_date` | `DATE` NOT NULL | Effective cutoff date for the telemetry snapshot. |
| `snapshot_label` | `VARCHAR(255)` NOT NULL | Institutional display label. |
| `record_count` | `INTEGER` NOT NULL | Validated active project count in this snapshot. |
| `delayed_count` | `INTEGER` NOT NULL | Count of projects experiencing schedule delay. |
| `overrun_count` | `INTEGER` NOT NULL | Count of projects with approved or incurred cost overruns. |
| `total_original_cost_cr` | `DOUBLE PRECISION` | Aggregate original budget sanction in Crores. |
| `total_expenditure_cr` | `DOUBLE PRECISION` | Aggregate cumulative expenditure in Crores. |
| `source_checksum` | `VARCHAR(128)` NOT NULL | Tamper-evident SHA-256 hash. |
| `schema_version` | `VARCHAR(32)` NOT NULL | Schema version (currently `v2.1`). |
| `status` | `VARCHAR(32)` NOT NULL | Validation outcome (`VALIDATED`, `PROVISIONAL`, `QUARANTINED`). |
| `is_baseline` | `SMALLINT` NOT NULL | `1` if designated official historical benchmark (April 2026). |
| `notes` | `TEXT` | Administrative documentation. |

---

## 5. Storage & High-Scale Evolution
The initial prototype manages ~2,000 projects across snapshots. To scale seamlessly to **100,000+** and **1,000,000+** project telemetry records over multi-year national lifecycles, the database schema implements:
- B-Tree compound index on `(project_code, snapshot_id)`.
- Temporal partitioning readiness on `project_versions` by `snapshot_date`.
- Server-side cursor pagination and indexed delta aggregations.
