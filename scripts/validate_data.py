"""
Data Validation Pipeline — SIH26017
Performs strict schema, type, null, duplicate, and domain anomaly checks on raw government CSV files.
"""

import os
import sys
import re
import json
import argparse
import pandas as pd
import numpy as np
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")

EXPECTED_COLUMNS_PROJECTS = [
    "sr_no", "sector_name", "line_ministry", "project_code", "project_name",
    "original_cost_cr", "revised_cost_cr", "expenditure_cr",
    "original_end_date_str", "revised_end_date_str"
]

def validate_projects_csv(filepath: str, verbose: bool = False) -> dict:
    if not os.path.exists(filepath):
        return {"status": "FAIL", "error": f"File not found: {filepath}"}

    errors = []
    warnings = []
    anomalies = []
    
    try:
        df = pd.read_csv(filepath, skiprows=2, encoding="utf-8")
    except Exception as e:
        return {"status": "FAIL", "error": f"Could not read CSV: {e}"}

    total_rows = len(df)
    
    # 1. Schema Check
    if df.shape[1] < 10:
        errors.append(f"Insufficient columns: expected at least 10, found {df.shape[1]}")
        return {"status": "FAIL", "total_rows": total_rows, "errors": errors}

    df = df.iloc[:, :10]
    df.columns = EXPECTED_COLUMNS_PROJECTS

    # 2. Duplicate Detection
    dup_codes = df[df["project_code"].duplicated(keep=False)]["project_code"].unique()
    if len(dup_codes) > 0:
        warnings.append(f"Found {len(dup_codes)} duplicate project_code instances: {list(dup_codes)[:5]}")

    # 3. Row-by-Row Checks
    valid_rows = 0
    clean_rows = 0
    sentinel_count = 0
    missing_dates_count = 0
    overspent_count = 0
    extreme_dates_count = 0
    extreme_delay_count = 0

    for idx, row in df.iterrows():
        row_num = idx + 3 # accounting for skiprows
        row_flags = []

        # Type checks
        p_code = pd.to_numeric(row["project_code"], errors="coerce")
        if pd.isna(p_code) or int(p_code) <= 0:
            errors.append({"row": row_num, "field": "project_code", "issue": "Invalid/non-positive project code"})
            continue

        orig_cost = pd.to_numeric(row["original_cost_cr"], errors="coerce")
        if pd.isna(orig_cost) or orig_cost < 0:
            errors.append({"row": row_num, "field": "original_cost_cr", "issue": "Invalid or negative original cost"})

        rev_cost = pd.to_numeric(row["revised_cost_cr"], errors="coerce")
        if pd.isna(rev_cost) or rev_cost < 0:
            errors.append({"row": row_num, "field": "revised_cost_cr", "issue": "Invalid or negative revised cost"})

        expenditure = pd.to_numeric(row["expenditure_cr"], errors="coerce")
        if pd.isna(expenditure) or expenditure < 0:
            errors.append({"row": row_num, "field": "expenditure_cr", "issue": "Invalid or negative expenditure"})

        # Sentinel revised_cost = 0 check
        if rev_cost == 0.0:
            sentinel_count += 1
            row_flags.append("NOT_YET_REVISED_COST")

        # Missing date check
        orig_date = pd.to_datetime(row["original_end_date_str"], format="%d/%m/%Y", errors="coerce")
        rev_date = pd.to_datetime(row["revised_end_date_str"], format="%d/%m/%Y", errors="coerce")

        if pd.isna(orig_date):
            row_flags.append("MISSING_ORIGINAL_DATE")
        if pd.isna(rev_date):
            missing_dates_count += 1
            row_flags.append("MISSING_REVISED_DATE")

        # Expenditure exceeds original check
        if pd.notna(orig_cost) and pd.notna(expenditure) and expenditure > orig_cost:
            overspent_count += 1
            row_flags.append("EXPENDITURE_EXCEEDS_ORIGINAL")

        # Extreme future dates (>2050)
        if pd.notna(orig_date) and orig_date.year > 2050:
            extreme_dates_count += 1
            row_flags.append("IMPLAUSIBLE_FUTURE_DATE_2050+")

        # Extreme delay outliers (< -365 or > 3650 days)
        if pd.notna(orig_date) and pd.notna(rev_date):
            delay_days = (rev_date - orig_date).days
            if delay_days < -365 or delay_days > 3650:
                extreme_delay_count += 1
                row_flags.append("EXTREME_SCHEDULE_OUTLIER")

        if len(row_flags) == 0:
            clean_rows += 1
        else:
            anomalies.append({"row": row_num, "code": int(p_code), "flags": row_flags})
            
        valid_rows += 1

    report = {
        "status": "PASS" if len(errors) == 0 else "FAIL",
        "file": os.path.basename(filepath),
        "total_rows": total_rows,
        "valid_rows": valid_rows,
        "clean_rows": clean_rows,
        "flagged_anomalies": len(anomalies),
        "hard_errors": len(errors),
        "warnings": warnings,
        "summary_metrics": {
            "sentinel_zero_revised_cost": sentinel_count,
            "missing_revised_end_dates": missing_dates_count,
            "expenditure_exceeds_original": overspent_count,
            "extreme_dates_beyond_2050": extreme_dates_count,
            "extreme_schedule_outliers": extreme_delay_count
        }
    }
    return report

def validate_all_csvs(verbose: bool = False) -> dict:
    csv_files = [
        "Projects_Report.csv",
        "Sector-Wise-Report.csv",
        "State-Wise-Report.csv",
        "Physical-Progress-Report.csv",
        "Cost-Wise-Report.csv"
    ]
    results = {}
    overall_status = "PASS"
    for fname in csv_files:
        fpath = os.path.join(RAW_DIR, fname)
        if not os.path.exists(fpath):
            results[fname] = {"status": "MISSING", "error": "File not found"}
            overall_status = "FAIL"
            continue
        if fname == "Projects_Report.csv":
            res = validate_projects_csv(fpath, verbose=verbose)
        else:
            try:
                df = pd.read_csv(fpath, skiprows=2, header=None)
                res = {"status": "PASS", "file": fname, "rows": len(df), "columns": df.shape[1]}
            except Exception as e:
                res = {"status": "FAIL", "error": str(e)}
                overall_status = "FAIL"
        results[fname] = res
        if res.get("status") == "FAIL":
            overall_status = "FAIL"

    return {"overall_status": overall_status, "files": results}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SIH26017 CSV Data Validation Tool")
    parser.add_argument("--file", help="Path to specific CSV to validate")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    parser.add_argument("--verbose", action="store_true", help="Print verbose anomaly details")
    args = parser.parse_args()

    if args.file:
        res = validate_projects_csv(args.file, verbose=args.verbose)
    else:
        res = validate_all_csvs(verbose=args.verbose)

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print("\n=======================================================")
        print("  SIH26017 DATA VALIDATION REPORT")
        print("=======================================================")
        print(f"Overall Status: {res.get('overall_status', res.get('status'))}")
        if "summary_metrics" in res:
            sm = res["summary_metrics"]
            print(f"Total Rows:     {res['total_rows']}")
            print(f"Clean Rows:     {res['clean_rows']}")
            print(f"Flagged Rows:   {res['flagged_anomalies']}")
            print(f"Sentinel Zero:  {sm['sentinel_zero_revised_cost']}")
            print(f"Missing Dates:  {sm['missing_revised_end_dates']}")
            print(f"Overspent:      {sm['expenditure_exceeds_original']}")
        elif "files" in res:
            for k, v in res["files"].items():
                print(f"• {k}: {v.get('status')} (Rows: {v.get('total_rows', v.get('rows', '-'))})")
        print("=======================================================\n")
