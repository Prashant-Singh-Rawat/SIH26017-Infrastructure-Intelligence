# Project History & Longitudinal Data Versioning
**SIH26017 — Infrastructure Delay & Cost Overrun Intelligence Platform**
**Division**: Infrastructure and Project Monitoring Division (IPMD) | Government of India

---

## 1. Logical Projects vs. Temporal Versions
In a national infrastructure repository, a single project (e.g. `702668: Udhampur-Srinagar-Baramulla Rail Link`) persists over many years across tens of monthly snapshots. 

**Core Rules**:
1. **Never Duplicate Logical Projects**: `project_code` is the canonical, immutable primary key representing the project entity.
2. **Never Overwrite Historical States**: Each snapshot creates an immutable child record in `project_versions`.
3. **Hierarchical Project Lineage**:
   ```
   Logical Project (project_code: 702668)
        │
        ├── Snapshot: paimana_2026_04 (Outlay: ₹37,012 Cr, Delay: +1,240 days)
        ├── Snapshot: paimana_2026_05 (Outlay: ₹37,012 Cr, Delay: +1,270 days, Exp: +₹410 Cr)
        └── Snapshot: paimana_2026_06 (Outlay: ₹37,200 Cr, Delay: +1,270 days, Cost Escalated)
   ```

---

## 2. Project Versioning Schema (`project_versions`)

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | `VARCHAR(128)` PRIMARY KEY | Compound key: `pv_{snapshot_id}_{project_code}`. |
| `project_code` | `INTEGER` NOT NULL | Canonical project identifier. |
| `snapshot_id` | `VARCHAR(64)` NOT NULL | Foreign key referencing `data_snapshots(id)`. |
| `snapshot_date` | `DATE` NOT NULL | Effective cutoff date. |
| `project_name` | `TEXT` NOT NULL | Sanctioned infrastructure title. |
| `sector` | `VARCHAR(128)` NOT NULL | Infrastructure sector (e.g. Railways, Highways). |
| `ministry` | `VARCHAR(255)` NOT NULL | Line ministry. |
| `original_cost` | `DOUBLE PRECISION` NOT NULL | Original Cabinet sanction outlay in Crores. |
| `revised_cost` | `DOUBLE PRECISION` NOT NULL | Formal CCEA revised outlay in Crores (or 0 if unrevised). |
| `expenditure` | `DOUBLE PRECISION` NOT NULL | Cumulative disbursed capital in Crores. |
| `original_completion_date`| `DATE` | Initial baseline milestone target. |
| `revised_completion_date` | `DATE` | Officially approved revised milestone target. |
| `schedule_delay_days` | `DOUBLE PRECISION` | Net schedule slippage relative to original sanction. |
| `is_delayed` | `SMALLINT` NOT NULL | `1` if slippage > 0, else `0`. |
| `cost_overrun_pct` | `DOUBLE PRECISION` | Percentage budget escalation. |
| `data_quality_flags` | `TEXT` | Audit flags (`CLEAN`, `SENTINEL_COST`, `OUTLIER_DATE`). |
| `status_in_snapshot` | `VARCHAR(64)` NOT NULL | `ONGOING`, `NEW`, `COMMISSIONED`, `OMITTED`. |

---

## 3. Snapshot Change Detection Engine (`backend/change_detection.py`)
When a new snapshot is registered, the Change Detection Engine runs full relational difference analysis against the prior snapshot.

### Change Classification Taxonomy:
1. **`NEW`**: Project code exists in snapshot $T$, but did not exist in snapshot $T-1$. Represents newly sanctioned capital investment.
2. **`UPDATED`**: Project code exists in both snapshots, with detectable variance in financial outlay, expenditure, or schedule timeline:
   - **Cost Escalation**: `revised_cost(T) > revised_cost(T-1)`
   - **Schedule Slippage**: `schedule_delay(T) > schedule_delay(T-1)`
   - **Schedule Recovery**: `schedule_delay(T) < schedule_delay(T-1)`
   - **Expenditure Progress**: `expenditure(T) > expenditure(T-1)`
3. **`UNCHANGED`**: Project code exists in both snapshots with zero delta across all monitored fields.
4. **`COMPLETED`**: Project completed all milestones and was transitioned to commercial operation.
5. **`REMOVED_FROM_ACTIVE_SNAPSHOT`**: Project absent from snapshot $T$, indicating project transfer, commissioning, or administrative omission.

### Change Summary Schema (`GET /api/v1/data/changes`):
```json
{
  "from_snapshot_id": "paimana_2026_04",
  "to_snapshot_id": "paimana_2026_05",
  "summary": {
    "new_projects": 6,
    "updated_projects": 850,
    "unchanged_projects": 1125,
    "removed_or_completed": 0,
    "total_projects_compared": 1987
  },
  "events": [
    {
      "project_code": 702668,
      "change_type": "UPDATED",
      "cost_change_cr": 0.0,
      "revised_cost_change_cr": 0.0,
      "expenditure_change_cr": 412.5,
      "schedule_change_days": 30.0,
      "status_change": "SCHEDULE_SLIPPED;EXPENDITURE_PROGRESSED",
      "change_summary": "Timeline slipped by +30 days; Disbursed additional ₹412 Cr"
    }
  ]
}
```

---

## 4. Longitudinal Project Querying (`GET /api/v1/projects/{code}/history`)
Consumers and analysts can track any project across all recorded snapshots via:
`GET /api/v1/projects/{code}/history`

Returns chronological project milestones, enabling time-series regression, trendline plotting, and audit trail generation without downloading monolithic multi-gigabyte snapshot archives into the browser.
