"""
Automated Ingestion Service — SIH26017
Orchestrates idempotent snapshot ingestion, data quality gating, raw data preservation,
project versioning, change detection, and audit logging.
"""

import os
import json
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime

from backend.database import get_db_connection, record_audit_log
from backend.adapters.paimana_adapter import PaimanaAdapter
from backend.change_detection import ChangeDetectionEngine

class IngestionService:
    """
    Continuous ingestion coordinator executing:
    fetch -> validate -> raw_store -> normalize -> deduplicate -> compare -> log
    """

    def __init__(self):
        self.adapter = PaimanaAdapter()

    def ingest_snapshot(
        self,
        file_content: bytes,
        filename: str,
        snapshot_id: str,
        snapshot_label: str,
        snapshot_date: str,
        executed_by: str = "admin.infra@gov.in",
        notes: str = "Ingested via Continuous Ingestion Pipeline"
    ) -> Dict[str, Any]:
        """
        Executes idempotent end-to-end ingestion pipeline.
        """
        run_id = str(uuid.uuid4())

        # Step 1: Validate & Quarantine
        valid_records, quarantined_records, summary = self.adapter.parse_and_validate_file(file_content, filename)

        if summary["status"] == "FAIL":
            return {
                "status": "ABORTED",
                "reason": "Data quality gate rejected all records in snapshot.",
                "summary": summary
            }

        checksum = summary["checksum"]
        total_valid = len(valid_records)
        delayed_cnt = sum(1 for r in valid_records if r.get("is_delayed") == 1)
        overrun_cnt = sum(1 for r in valid_records if r.get("cost_overrun_pct") and r.get("cost_overrun_pct") > 0)
        tot_orig = sum(r.get("original_cost_cr", 0.0) for r in valid_records)
        tot_exp = sum(r.get("expenditure_cr", 0.0) for r in valid_records)

        conn = get_db_connection()
        prior_id = None
        try:
            cursor = conn.cursor()

            # Step 2: Register or Update Snapshot
            cursor.execute("""
            INSERT INTO data_snapshots (
                id, source_id, source_name, snapshot_date, snapshot_label,
                record_count, delayed_count, overrun_count, total_original_cost_cr,
                total_expenditure_cr, source_checksum, schema_version, status, is_baseline, notes
            ) VALUES (?, 'mospi_paimana', 'MoSPI PAIMANA Central Sector Projects Repository',
                      ?, ?, ?, ?, ?, ?, ?, ?, 'v2.1', 'VALIDATED', 0, ?)
            ON CONFLICT (id) DO UPDATE SET
                record_count = excluded.record_count,
                delayed_count = excluded.delayed_count,
                overrun_count = excluded.overrun_count,
                total_original_cost_cr = excluded.total_original_cost_cr,
                total_expenditure_cr = excluded.total_expenditure_cr,
                source_checksum = excluded.source_checksum;
            """, (
                snapshot_id, snapshot_date, snapshot_label, total_valid, delayed_cnt,
                overrun_cnt, tot_orig, tot_exp, checksum, notes
            ))

            # Step 3: Raw Snapshot Record
            cursor.execute("""
            INSERT INTO raw_data_snapshots (
                id, snapshot_id, source_reference, filename_or_api, checksum,
                raw_record_count, file_size_bytes, processing_status, quarantined_record_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'COMPLETED', ?)
            ON CONFLICT (id) DO NOTHING;
            """, (
                f"raw_{snapshot_id}", snapshot_id, f"upload/{filename}", filename,
                checksum, summary["total_raw_rows"], summary["file_size_bytes"],
                len(quarantined_records)
            ))

            # Step 4: Record Data Quality Run
            cursor.execute("""
            INSERT INTO data_quality_runs (
                id, snapshot_id, check_name, status, records_checked,
                records_failed, failure_rate_pct, details
            ) VALUES (?, ?, 'PAIMANA_INGESTION_QUALITY_GATE', ?, ?, ?, ?, ?);
            """, (
                str(uuid.uuid4()), snapshot_id, summary["status"], summary["total_raw_rows"],
                len(quarantined_records), summary["quarantine_rate_pct"],
                json.dumps({"quarantined_sample": quarantined_records[:5]})
            ))

            # Step 5: Upsert Master Projects Table & Insert Project Versions
            for r in valid_records:
                p_code = r["project_code"]
                pv_id = f"pv_{snapshot_id}_{p_code}"

                cursor.execute("""
                INSERT INTO project_versions (
                    id, project_code, snapshot_id, snapshot_date, project_name,
                    sector, ministry, state, original_cost, revised_cost, expenditure,
                    original_completion_date, revised_completion_date, schedule_delay_days,
                    is_delayed, cost_overrun_pct, data_quality_flags, status_in_snapshot
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'Pan-India', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ONGOING')
                ON CONFLICT (project_code, snapshot_id) DO UPDATE SET
                    revised_cost = excluded.revised_cost,
                    expenditure = excluded.expenditure,
                    schedule_delay_days = excluded.schedule_delay_days,
                    is_delayed = excluded.is_delayed,
                    cost_overrun_pct = excluded.cost_overrun_pct;
                """, (
                    pv_id, p_code, snapshot_id, snapshot_date, r["project_name"],
                    r["sector_name"], r["line_ministry"], r["original_cost_cr"],
                    r["revised_cost_cr"], r["expenditure_cr"], r["original_end_date"],
                    r["revised_end_date"], r["schedule_delay_days"], r["is_delayed"],
                    r["cost_overrun_pct"], r["data_quality_flags"]
                ))

                cursor.execute("""
                INSERT INTO projects (
                    project_code, project_name, sector_name, line_ministry,
                    original_cost_cr, revised_cost_cr, expenditure_cr,
                    original_end_date, revised_end_date, is_delayed, schedule_delay_days,
                    cost_overrun_pct, data_quality_flags, data_provenance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (project_code) DO UPDATE SET
                    revised_cost_cr = excluded.revised_cost_cr,
                    expenditure_cr = excluded.expenditure_cr,
                    revised_end_date = excluded.revised_end_date,
                    is_delayed = excluded.is_delayed,
                    schedule_delay_days = excluded.schedule_delay_days,
                    cost_overrun_pct = excluded.cost_overrun_pct,
                    data_quality_flags = excluded.data_quality_flags;
                """, (
                    p_code, r["project_name"], r["sector_name"], r["line_ministry"],
                    r["original_cost_cr"], r["revised_cost_cr"], r["expenditure_cr"],
                    r["original_end_date"], r["revised_end_date"], r["is_delayed"],
                    r["schedule_delay_days"], r["cost_overrun_pct"], r["data_quality_flags"],
                    r["data_provenance"]
                ))

            # Retrieve prior snapshot id before closing connection
            cursor.execute("SELECT id FROM data_snapshots WHERE id != ? ORDER BY snapshot_date DESC LIMIT 1;", (snapshot_id,))
            prior_snap = cursor.fetchone()
            if prior_snap:
                prior_id = prior_snap[0]

            conn.commit()
        finally:
            conn.close()

        # Step 6: Trigger Change Detection against prior snapshot
        change_summary = {}
        if prior_id:
            comparison = ChangeDetectionEngine.compare_snapshots(prior_id, snapshot_id)
            ChangeDetectionEngine.persist_change_events(comparison)
            change_summary = comparison.get("summary", {})

        # Step 7: Record Ingestion Run
        conn_run = get_db_connection()
        try:
            cursor_run = conn_run.cursor()
            cursor_run.execute("""
            INSERT INTO ingestion_runs (
                id, snapshot_id, source_name, trigger_type, started_at, completed_at,
                status, total_records, new_records, updated_records, unchanged_records,
                quarantined_records, executed_by
            ) VALUES (?, ?, 'MoSPI PAIMANA', 'MANUAL', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                      'SUCCESS', ?, ?, ?, ?, ?, ?);
            """, (
                run_id, snapshot_id, total_valid,
                change_summary.get("new_projects", 0),
                change_summary.get("updated_projects", 0),
                change_summary.get("unchanged_projects", 0),
                len(quarantined_records), executed_by
            ))
            conn_run.commit()
        finally:
            conn_run.close()

        # Audit Log
        record_audit_log(
            action="DATA_SNAPSHOT_INGESTED",
            resource_type="DATA_SNAPSHOT",
            resource_id=snapshot_id,
            user_id=executed_by,
            result="SUCCESS",
            metadata={
                "snapshot_id": snapshot_id,
                "valid_records": total_valid,
                "quarantined_records": len(quarantined_records),
                "checksum": checksum
            }
        )

        return {
            "status": "SUCCESS",
            "snapshot_id": snapshot_id,
            "snapshot_label": snapshot_label,
            "valid_records_ingested": total_valid,
            "quarantined_records": len(quarantined_records),
            "changes_detected": change_summary,
            "checksum": checksum
        }
