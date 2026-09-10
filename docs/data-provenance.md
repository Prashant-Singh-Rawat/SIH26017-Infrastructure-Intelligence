# Data Provenance & Integrity Policy — SIH26017
**Project:** PM-OCMS Infrastructure Delay & Cost Overrun Intelligence Platform  
**Problem Statement:** SIH26017 – Predictive Analytics System for Early Detection of Delays  
**Compliance Standard:** Smart India Hackathon Prototype Honesty & Transparency Guidelines

---

## 1. Provenance Classification Framework

Every data attribute displayed in the dashboard or returned by the API is explicitly categorized into one of three provenance classes:

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           DATA PROVENANCE TIERS                          │
├──────────────────────────┬───────────────────────┬───────────────────────┤
│         SOURCE           │        DERIVED        │    DEMO/SIMULATION    │
│  [DATA FOUND IN UPLOAD]  │   [DERIVED METRIC]    │   [DEMO/SIMULATION]   │
├──────────────────────────┼───────────────────────┼───────────────────────┤
│ Ground-truth telemetry   │ Statistically computed│ Synthetic demonstration│
│ extracted directly from  │ from source records   │ layer created to model│
│ official MoSPI reports   │ using standardized GoI│ spatial early-warning │
│ with zero modification.  │ governance formulas.  │ workflows for SIH.    │
└──────────────────────────┴───────────────────────┴───────────────────────┘
```

---

## 2. Detailed Attribute Mapping

### 2.1. `[DATA FOUND IN UPLOADED FILE]` (SOURCE)
These fields are extracted directly from official Ministry of Statistics and Programme Implementation (MoSPI) central sector project monitoring reports (`data/raw/Projects_Report.csv`):
- **`project_code`**: Unique national identifier assigned by MoSPI (e.g., `400277`).
- **`project_name`**: Official project title (e.g., *"Belgharia Expressway 4 Laning"*).
- **`sector_name`**: Infrastructure sector classification (e.g., *"Road Transport and Highways"*, *"Railways"*, *"Power"*).
- **`line_ministry`**: Responsible administrative ministry (e.g., *"Ministry of Road Transport and Highways"*).
- **`original_cost_cr`**: Sanctioned financial outlay approved by the Cabinet/CCEA (in ₹ Crores).
- **`revised_cost_cr`**: Current sanctioned revised cost (in ₹ Crores; `0` denotes an unrevised project).
- **`expenditure_cr`**: Actual cumulative fiscal expenditure disbursed to date (in ₹ Crores).
- **`original_end_date`**: Original targeted commissioning date sanctioned at inception.
- **`revised_end_date`**: Currently projected commissioning date.

### 2.2. `[DERIVED METRIC]` (DERIVED)
These fields are calculated deterministically from source fields during ingestion and data validation:
- **`schedule_delay_days`**: Calculated as `revised_end_date - original_end_date`. Positive values indicate schedule slippage.
- **`is_delayed`**: Binary indicator (`1` if `schedule_delay_days > 0`, otherwise `0`).
- **`has_cost_overrun`**: Binary indicator (`1` if `revised_cost_cr > original_cost_cr > 0`, otherwise `0`).
- **`cost_overrun_pct`**: Net percentage cost growth: `((revised_cost - original_cost) / original_cost) * 100`.
- **`cost_scale_bucket`**: Tiered categorization (`Tier 1 (< ₹100 Cr)` through `Tier 5 (> ₹10,000 Cr Mega)`).
- **`expenditure_ratio`**: Capital absorption rate: `expenditure_cr / original_cost_cr`.
- **`sector_delay_rate`**: Historical delay rate across the project's sector peers.
- **`data_quality_flags`**: Programmatic audit tags (`MISSING_REVISED_DATE`, `EXPENDITURE_EXCEEDS_ORIGINAL`, `CLEAN`).

### 2.3. `[DEMO/SIMULATION]` (SIMULATION)
> [!WARNING]
> **Strict Ethical Disclosure for Hackathon Evaluators**:
> The official MoSPI monitoring reports **do NOT** publish parcel-level cadastral plots, affected families counts, district-level GPS coordinates, or Rehabilitation & Resettlement (R&R) compensation ledgers.

To demonstrate the intended end-state spatial early-warning workflow required by SIH problem statement SIH26017, synthetic simulation attributes are generated for Tab 6 (*Land & GIS Demonstration*):
- **`land_required_acres`**: Simulated total land acquisition acreage.
- **`land_acquired_pct`**: Simulated possession percentage.
- **`active_legal_disputes`**: Simulated high court / district court dispute count.
- **`affected_families_count`**: Simulated Rehabilitation & Resettlement caseload.
- **`rehabilitation_package_cr`**: Simulated compensation fund requirement.
- **`latitude` / `longitude`**: State and regional centroids inferred from project titles and state names.

Every UI card, table cell, map popup, and API response returning these fields is tagged with `[DEMO/SIMULATION]`.

---

## 3. UI Display Standards

1. **Table Badges**: Every table column header or record cell displays a pill badge:
   - Green pill: `[SOURCE]`
   - Blue pill: `[DERIVED]`
   - Orange/Red pill: `[DEMO/SIMULATION]`
2. **Project Detail Modal**: The audit modal displays separate sections for *"Official Project Telemetry [SOURCE]"*, *"Derived Risk & Governance Analytics [DERIVED]"*, and *"Simulated Land Acquisition Early Warning [DEMO/SIMULATION]"*.
3. **What-If Policy Simulator**: Simulation outcomes prominently display the mandatory footer:
   `"MODEL SIMULATION — NOT AN OFFICIAL GOVERNMENT FORECAST"`.
