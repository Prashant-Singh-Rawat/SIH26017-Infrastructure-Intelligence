"""
Data Ingestion Pipeline — SIH26017
Idempotently ingests official government CSVs into the relational database, recording audit trails and validation errors.
"""

import os
import sys
import uuid
import json
import argparse
import pandas as pd
import numpy as np
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from backend.database import get_db_connection, init_db, record_audit_log, adapt_query, IS_POSTGRES
from scripts.validate_data import validate_projects_csv, RAW_DIR

def run_import(dry_run: bool = False, version: str = "v2026.09") -> dict:
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()

    import_id = str(uuid.uuid4())
    filename = "Projects_Report.csv"
    filepath = os.path.join(RAW_DIR, filename)

    print(f"\n[INGESTION] Starting import process for: {filename} (Version: {version}, Dry Run: {dry_run})")
    
    # 1. Validation phase
    val_report = validate_projects_csv(filepath)
    if val_report.get("status") == "FAIL":
        print(f"[INGESTION ABORTED] File validation failed: {val_report.get('error')}")
        return val_report

    df = pd.read_csv(filepath, skiprows=2, encoding="utf-8")
    df = df.iloc[:, :10]
    df.columns = [
        "sr_no", "sector_name", "line_ministry", "project_code", "project_name",
        "original_cost_cr", "revised_cost_cr", "expenditure_cr",
        "original_end_date_str", "revised_end_date_str"
    ]

    total_rows = len(df)
    successful_rows = 0
    failed_rows = 0
    duplicate_rows = 0
    errors_list = []

    # Check existing codes to track duplicate/upsert count
    cursor.execute("SELECT project_code FROM projects;")
    _rows = cursor.fetchall()
    # Handle both sqlite3.Row (index) and psycopg2 RealDictRow (key)
    existing_codes = set(r["project_code"] if IS_POSTGRES else r[0] for r in _rows)

    projects_to_insert = []
    
    for idx, row in df.iterrows():
        row_num = idx + 3
        try:
            p_code = int(float(row["project_code"]))
            if p_code in existing_codes:
                duplicate_rows += 1

            orig_cost = max(0.0, float(pd.to_numeric(row["original_cost_cr"], errors="coerce") or 0.0))
            rev_cost = max(0.0, float(pd.to_numeric(row["revised_cost_cr"], errors="coerce") or 0.0))
            expenditure = max(0.0, float(pd.to_numeric(row["expenditure_cr"], errors="coerce") or 0.0))

            rev_set = 1 if rev_cost > 0.0 else 0
            
            orig_date = pd.to_datetime(row["original_end_date_str"], format="%d/%m/%Y", errors="coerce")
            rev_date = pd.to_datetime(row["revised_end_date_str"], format="%d/%m/%Y", errors="coerce")
            rev_missing = 1 if pd.isna(rev_date) else 0

            # Delay & Overrun
            if pd.notna(orig_date) and pd.notna(rev_date):
                diff = (rev_date - orig_date).days
                is_del = 1 if diff > 0 else 0
                sched_delay = float(diff)
                sched_clipped = max(-365.0, min(3650.0, sched_delay))
            else:
                is_del = 0
                sched_delay = None
                sched_clipped = None

            if rev_set == 1 and orig_cost > 0:
                overrun_pct = round((rev_cost - orig_cost) / orig_cost * 100, 2)
                has_overrun = 1 if overrun_pct > 0 else 0
            else:
                overrun_pct = None
                has_overrun = 0

            # Audit flags
            flags = []
            if rev_set == 0:
                flags.append("NOT_YET_REVISED_COST")
            if rev_missing == 1:
                flags.append("MISSING_REVISED_DATE")
            if expenditure > orig_cost:
                flags.append("EXPENDITURE_EXCEEDS_ORIGINAL")
            if pd.notna(orig_date) and orig_date.year > 2050:
                flags.append("IMPLAUSIBLE_FUTURE_DATE_2050+")
            if sched_delay is not None and (sched_delay < -365 or sched_delay > 3650):
                flags.append("EXTREME_SCHEDULE_OUTLIER")
            if overrun_pct is not None and (overrun_pct < -50 or overrun_pct > 500):
                flags.append("EXTREME_COST_OVERRUN_OUTLIER")
            
            dq_flags = ";".join(flags) if flags else "CLEAN"

            orig_date_str = orig_date.strftime("%Y-%m-%d") if pd.notna(orig_date) else None
            rev_date_str = rev_date.strftime("%Y-%m-%d") if pd.notna(rev_date) else None
            orig_year = orig_date.year if pd.notna(orig_date) else 2026
            orig_quarter = orig_date.quarter if pd.notna(orig_date) else 2

            log_cost = float(np.log1p(orig_cost))
            exp_ratio = round(expenditure / orig_cost, 3) if orig_cost > 0 else 0.0

            if orig_cost < 100:
                bucket = "Tier 1 (< ₹100 Cr)"
            elif orig_cost < 500:
                bucket = "Tier 2 (₹100 - ₹500 Cr)"
            elif orig_cost < 2000:
                bucket = "Tier 3 (₹500 - ₹2,000 Cr)"
            elif orig_cost < 10000:
                bucket = "Tier 4 (₹2,000 - ₹10,000 Cr)"
            else:
                bucket = "Tier 5 (> ₹10,000 Cr Mega)"

            record = (
                p_code,
                int(row["sr_no"]) if pd.notna(row["sr_no"]) else idx + 1,
                str(row["sector_name"]).strip(),
                str(row["line_ministry"]).strip(),
                str(row["project_name"]).strip(),
                orig_cost,
                rev_cost,
                expenditure,
                orig_date_str,
                rev_date_str,
                orig_year,
                orig_quarter,
                bucket,
                log_cost,
                exp_ratio,
                is_del,
                sched_delay,
                sched_clipped,
                has_overrun,
                overrun_pct,
                rev_set,
                rev_missing,
                dq_flags,
                "SOURCE"
            )
            projects_to_insert.append(record)
            successful_rows += 1

        except Exception as ex:
            failed_rows += 1
            errors_list.append((import_id, row_num, "general", str(ex), str(row.to_dict())))

    # 2. Database transaction
    if not dry_run:
        if IS_POSTGRES:
            # PostgreSQL/Supabase: Use %s placeholders and ON CONFLICT (project_code)
            cursor.executemany("""
            INSERT INTO projects (
                project_code, sr_no, sector_name, line_ministry, project_name,
                original_cost_cr, revised_cost_cr, expenditure_cr,
                original_end_date, revised_end_date, original_end_year, original_end_quarter,
                cost_scale_bucket, log_original_cost, expenditure_ratio,
                is_delayed, schedule_delay_days, schedule_delay_days_clipped,
                has_cost_overrun, cost_overrun_pct, revised_cost_is_set,
                revised_date_is_missing, data_quality_flags, data_provenance
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (project_code) DO UPDATE SET
                project_name = EXCLUDED.project_name,
                sector_name = EXCLUDED.sector_name,
                line_ministry = EXCLUDED.line_ministry,
                original_cost_cr = EXCLUDED.original_cost_cr,
                revised_cost_cr = EXCLUDED.revised_cost_cr,
                expenditure_cr = EXCLUDED.expenditure_cr,
                original_end_date = EXCLUDED.original_end_date,
                revised_end_date = EXCLUDED.revised_end_date,
                is_delayed = EXCLUDED.is_delayed,
                schedule_delay_days = EXCLUDED.schedule_delay_days,
                has_cost_overrun = EXCLUDED.has_cost_overrun,
                data_quality_flags = EXCLUDED.data_quality_flags;
            """, projects_to_insert)
        else:
            # SQLite: Use ? placeholders and ON CONFLICT(project_code)
            cursor.executemany("""
            INSERT INTO projects (
                project_code, sr_no, sector_name, line_ministry, project_name,
                original_cost_cr, revised_cost_cr, expenditure_cr,
                original_end_date, revised_end_date, original_end_year, original_end_quarter,
                cost_scale_bucket, log_original_cost, expenditure_ratio,
                is_delayed, schedule_delay_days, schedule_delay_days_clipped,
                has_cost_overrun, cost_overrun_pct, revised_cost_is_set,
                revised_date_is_missing, data_quality_flags, data_provenance
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(project_code) DO UPDATE SET
                project_name = excluded.project_name,
                sector_name = excluded.sector_name,
                line_ministry = excluded.line_ministry,
                original_cost_cr = excluded.original_cost_cr,
                revised_cost_cr = excluded.revised_cost_cr,
                expenditure_cr = excluded.expenditure_cr,
                original_end_date = excluded.original_end_date,
                revised_end_date = excluded.revised_end_date,
                is_delayed = excluded.is_delayed,
                schedule_delay_days = excluded.schedule_delay_days,
                has_cost_overrun = excluded.has_cost_overrun,
                data_quality_flags = excluded.data_quality_flags;
            """, projects_to_insert)

        # Log import record with complete provenance metadata
        val_summary_str = json.dumps(val_report.get("summary_metrics", {}))
        now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor.execute(adapt_query("""
        INSERT INTO data_imports (
            id, file_name, source_name, source_type, source_timestamp,
            ingestion_timestamp, data_version, row_count, successful_rows,
            failed_rows, duplicate_rows, validation_summary, data_status, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'COMPLETED', 'COMPLETED');
        """), (
            import_id,
            filename,
            "Projects_Report.csv",
            "MoSPI Infrastructure Telemetry (CSV)",
            "2026-09-01T00:00:00Z",
            now_iso,
            version,
            total_rows,
            successful_rows,
            failed_rows,
            duplicate_rows,
            val_summary_str
        ))

        if errors_list:
            cursor.executemany(adapt_query("""
            INSERT INTO data_import_errors (import_id, row_number, field_name, error_reason, raw_value)
            VALUES (?, ?, ?, ?, ?);
            """), errors_list)

        conn.commit()

        record_audit_log(
            action="DATA_IMPORTED",
            resource_type="data_imports",
            resource_id=import_id,
            user_id="00000000-0000-0000-0000-000000000001",
            result="SUCCESS",
            metadata={
                "file_name": filename,
                "version": version,
                "successful_rows": successful_rows,
                "duplicates_upserted": duplicate_rows
            }
        )

    conn.close()

    result = {
        "import_id": import_id,
        "file_name": filename,
        "data_version": version,
        "dry_run": dry_run,
        "total_rows": total_rows,
        "successful_rows": successful_rows,
        "failed_rows": failed_rows,
        "duplicate_rows": duplicate_rows,
        "status": "COMPLETED" if failed_rows == 0 else "PARTIAL_SUCCESS"
    }
    print(f"[INGESTION SUCCESS] {successful_rows} rows processed, {duplicate_rows} existing updated. Status: {result['status']}\n")
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SIH26017 Data Ingestion Tool")
    parser.add_argument("--dry-run", action="store_true", help="Validate and parse without committing to DB")
    parser.add_argument("--version", default="v2026.09", help="Version tag for this data import")
    args = parser.parse_args()

    res = run_import(dry_run=args.dry_run, version=args.version)
    print(json.dumps(res, indent=2))
