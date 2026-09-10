# Data Dictionary & Schema Glossary
**Project:** PM-OCMS Infrastructure Delay & Cost Overrun Intelligence Platform (SIH26017)  
**Dataset Reference:** MoSPI Flash Reports & Project Monitoring Division Reports

---

## 1. Source CSV Datasets

| Filename | Row Count | Granularity | Key Metrics Covered |
|---|---|---|---|
| `Projects_Report.csv` | 1,981 | Individual Sanctioned Project | Outlay, Revised Cost, Expenditure, Dates, Line Ministry, Sector |
| `Sector-Wise-Report.csv` | 22 | Infrastructure Sector Aggregate | Sector Total Projects, Outlay, Spend |
| `State-Wise-Report.csv` | 34 | State / UT Aggregate | State Project Count, Sanction Outlay, Cumulative Spend |
| `Physical-Progress-Report.csv` | 11 | Progress Bracket Aggregate | Projects categorized by completion brackets (0-25%, 25-50%, etc.) |
| `Cost-Wise-Report.csv` | 1 | Portfolio Total Aggregate | Macro Outlay (₹ 37,12,662 Cr), Revised Outlay, Net Escalation |

---

## 2. Field Definitions: `projects` Table

| Field Name | Type | Provenance | Description & Handling Rule |
|---|---|---|---|
| `project_code` | INTEGER | `SOURCE` | Unique project tracking identifier assigned by MoSPI IPMD. |
| `project_name` | TEXT | `SOURCE` | Official sanctioned name of the infrastructure work. |
| `sector_name` | TEXT | `SOURCE` | Core infrastructure sector (e.g. Railways, Roads & Highways, Power). |
| `line_ministry` | TEXT | `SOURCE` | Sponsoring central union ministry (e.g. Ministry of Railways). |
| `original_cost_cr` | NUMERIC | `SOURCE` | Initial capital expenditure sanction in ₹ Crores. |
| `revised_cost_cr` | NUMERIC | `SOURCE` | Revised approved outlay in ₹ Crores. **Sentinel Rule**: A value of 0.0 indicates budget has *not yet been formally revised*, NOT 100% cost reduction. |
| `expenditure_cr` | NUMERIC | `SOURCE` | Cumulative funds disbursed on-ground to executing agencies. |
| `original_end_date` | DATE | `SOURCE` | Initial target date of commercial operation (COD). |
| `revised_end_date` | DATE | `SOURCE` | Extended target date of commissioning. Quarantined if missing. |
| `is_delayed` | BOOLEAN | `DERIVED` | Binary classification label: `TRUE` if `revised_end_date > original_end_date`. |
| `schedule_delay_days` | NUMERIC | `DERIVED` | Net slippage in days (`revised_end_date - original_end_date`). |
| `schedule_delay_days_clipped` | NUMERIC | `DERIVED` | Winsorized delay target bounded within `[-365, 3650]` days. |
| `has_cost_overrun` | BOOLEAN | `DERIVED` | `TRUE` if `revised_cost_is_set = 1` and `revised_cost_cr > original_cost_cr`. |
| `cost_overrun_pct` | NUMERIC | `DERIVED` | Percentage cost escalation over original sanction. |
| `revised_cost_is_set` | BOOLEAN | `DERIVED` | Flag: `1` if `revised_cost_cr > 0`, `0` if sentinel unrevised. |
| `revised_date_is_missing` | BOOLEAN | `DERIVED` | Flag: `1` if revised date was blank in the uploaded file. |
| `data_quality_flags` | TEXT | `DERIVED` | Semicolon-delimited validation flags (`CLEAN`, `NOT_YET_REVISED_COST`, `MISSING_REVISED_DATE`, `EXPENDITURE_EXCEEDS_ORIGINAL`, `IMPLAUSIBLE_FUTURE_DATE_2050+`, `EXTREME_SCHEDULE_OUTLIER`). |
| `data_provenance` | TEXT | `GOVERNANCE` | Fixed value `'SOURCE'`. |

---

## 3. Field Definitions: `simulation_records` Table

*All attributes in this table are explicitly tagged with `[DEMO/SIMULATION]`.*

| Field Name | Type | Provenance | Description |
|---|---|---|---|
| `inferred_state` | TEXT | `SIMULATION` | Statistically inferred state alignment for spatial demonstration. |
| `latitude` / `longitude` | NUMERIC | `SIMULATION` | Approximate GIS alignment centroids for map demonstration. |
| `land_required_acres` | NUMERIC | `SIMULATION` | Estimated Right-of-Way footprint. |
| `land_acquired_pct` | NUMERIC | `SIMULATION` | Handover possession percentage. |
| `land_clearance_status` | TEXT | `SIMULATION` | Stage: `Pending 3D Notice`, `Section 19 Award`, `Possession Handed`. |
| `active_legal_disputes` | INTEGER | `SIMULATION` | Synthetic title/compensation disputes pending in High Courts. |
| `affected_families_count`| INTEGER | `SIMULATION` | Resettlement population scope. |
| `rehabilitation_package_cr`| NUMERIC | `SIMULATION` | R&R financial compensation allocation in ₹ Crores. |
| `source_tag` | TEXT | `SIMULATION` | Tagged as `'[DEMO/SIMULATION]'`. |
