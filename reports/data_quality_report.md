# Data Quality Report -- SIH26017 Infrastructure Intelligence Platform
Generated: 2026-09-10 | Programmatic validation of all 5 official government CSVs

## 1. File Inventory and Deduplication
File | Rows | Unique PK | Hash Status
Projects_Report.csv | 1981 project rows | 1981 unique Project Codes | No duplicates
Sector-Wise-Report.csv | 22 rows | Sector Name | Unique
State-Wise-Report.csv | 34 rows | State Name | Unique
Physical-Progress-Report.csv | 11 rows | Progress Bracket | Unique
Cost-Wise-Report.csv | 1 row | N/A (totals only) | Unique

## 2. Missing Value Analysis (Projects_Report.csv)
Field | Missing Count | Pct | Treatment
Revised End Date | 354 | 17.9% | Quarantined from regression training; flagged MISSING_REVISED_DATE
Revised Cost (= 0) | 905 | 45.7% | Treated as sentinel NOT_YET_REVISED; NEVER as -100% overrun
All other fields | 0 | 0% | Complete

## 3. Date Range Verification
Field | Min | Max | Flag
Original End Date | 2005-03-31 | 2056-12-31 | 1 row flagged IMPLAUSIBLE_FUTURE_DATE_2050+
Revised End Date | 2013-09-30 | 2040-06-30 | None

## 4. Schedule Delay Distribution
Metric | Value
Raw delay range | -10867 to +9131 days
Projects delayed | 1267 (64.0%)
On schedule | 296 (14.9%)
Revised earlier | 64 (3.2%)
Missing revised date | 354 (17.9%)
Average delay (delayed only) | 931.7 days
Clipping for training | [-365, +3650] days

## 5. Data Quality Flags
Flag | Count
CLEAN | 764
NOT_YET_REVISED_COST | 905
MISSING_REVISED_DATE | 354
EXPENDITURE_EXCEEDS_ORIGINAL | 160
EXTREME_SCHEDULE_OUTLIER | 33
EXTREME_COST_OVERRUN_OUTLIER | 24
IMPLAUSIBLE_FUTURE_DATE_2050+ | 1

## 6. Model Performance (Verified)
Task | Algorithm | Metric | Score
Delay Classification | GBC 120 trees | ROC-AUC | 0.9189
Delay Classification | GBC | 5-Fold CV AUC | 0.9235 +/- 0.013
Delay Classification | GBC | F1 | 0.8928
Delay Regression | RF 150 trees | R-squared | 0.8848
Delay Regression | RF | MAE | 161.6 days

## 7. Zero-Leakage Guarantee
Excluded from model predictors: revised_end_date, revised_cost_cr, schedule_delay_days, is_delayed, cost_overrun_pct.
Features used: sector_name, line_ministry, cost_scale_bucket, original_cost_cr, log_original_cost, original_end_year, original_end_quarter, sector_delay_rate, ministry_delay_rate.

## 8. Demo/Simulation Layer
Fields NOT in any government CSV (labeled [DEMO/SIMULATION]):
- GPS coordinates, inferred state, land_required, land_acquired_pct, land_clearance_status, active_legal_disputes, affected_families_count, rehabilitation_package_cr
- These are NEVER used as model features or presented as government data
