"""
Snapshot Change Detection Engine — SIH26017
Computes deterministic project-level deltas between chronological government snapshots.
Identifies NEW, UPDATED, UNCHANGED, COMPLETED, and REMOVED projects without fabricating data.
"""

from typing import Dict, Any, List, Optional, Tuple
from backend.database import get_db_connection

class ChangeDetectionEngine:
    """
    Compares two registered government snapshots and detects financial,
    timeline, and operational changes.
    """

    @staticmethod
    def compare_snapshots(from_snapshot_id: str, to_snapshot_id: str) -> Dict[str, Any]:
        """
        Queries project_versions for both snapshots and calculates deltas.
        """
        conn = get_db_connection()
        cursor = conn.cursor()

        # Fetch records for from_snapshot
        cursor.execute("""
        SELECT project_code, project_name, sector, ministry, original_cost, revised_cost,
               expenditure, schedule_delay_days, is_delayed, status_in_snapshot
        FROM project_versions
        WHERE snapshot_id = ?;
        """, (from_snapshot_id,))
        from_records = {r[0]: dict(r) for r in cursor.fetchall()}

        # Fetch records for to_snapshot
        cursor.execute("""
        SELECT project_code, project_name, sector, ministry, original_cost, revised_cost,
               expenditure, schedule_delay_days, is_delayed, status_in_snapshot
        FROM project_versions
        WHERE snapshot_id = ?;
        """, (to_snapshot_id,))
        to_records = {r[0]: dict(r) for r in cursor.fetchall()}

        conn.close()

        all_codes = set(from_records.keys()).union(set(to_records.keys()))

        events = []
        new_count = 0
        updated_count = 0
        unchanged_count = 0
        removed_count = 0

        for p_code in all_codes:
            in_from = p_code in from_records
            in_to = p_code in to_records

            if not in_from and in_to:
                # NEW project in to_snapshot
                curr = to_records[p_code]
                new_count += 1
                events.append({
                    "project_code": p_code,
                    "from_snapshot_id": from_snapshot_id,
                    "to_snapshot_id": to_snapshot_id,
                    "change_type": "NEW",
                    "cost_change_cr": float(curr["original_cost"]),
                    "revised_cost_change_cr": float(curr["revised_cost"]),
                    "expenditure_change_cr": float(curr["expenditure"]),
                    "schedule_change_days": float(curr["schedule_delay_days"] or 0.0),
                    "status_change": "NEWLY_SANCTIONED",
                    "change_summary": f"Project entered active monitoring in snapshot {to_snapshot_id} (Sanctioned: ₹{curr['original_cost']:,.0f} Cr)."
                })

            elif in_from and not in_to:
                # REMOVED or COMPLETED
                prev = from_records[p_code]
                removed_count += 1
                events.append({
                    "project_code": p_code,
                    "from_snapshot_id": from_snapshot_id,
                    "to_snapshot_id": to_snapshot_id,
                    "change_type": "REMOVED_FROM_ACTIVE_SNAPSHOT",
                    "cost_change_cr": 0.0,
                    "revised_cost_change_cr": 0.0,
                    "expenditure_change_cr": 0.0,
                    "schedule_change_days": 0.0,
                    "status_change": "OMITTED_OR_COMMISSIONED",
                    "change_summary": f"Project no longer present in active monitoring snapshot {to_snapshot_id} (Commissioned or Transferred)."
                })

            else:
                # Project present in both — compute deltas
                prev = from_records[p_code]
                curr = to_records[p_code]

                cost_delta = round(float(curr["original_cost"]) - float(prev["original_cost"]), 2)
                rev_delta = round(float(curr["revised_cost"]) - float(prev["revised_cost"]), 2)
                exp_delta = round(float(curr["expenditure"]) - float(prev["expenditure"]), 2)
                
                prev_delay = float(prev["schedule_delay_days"] or 0.0)
                curr_delay = float(curr["schedule_delay_days"] or 0.0)
                sched_delta = round(curr_delay - prev_delay, 1)

                has_change = (abs(cost_delta) > 0.01 or abs(rev_delta) > 0.01 or abs(exp_delta) > 0.01 or abs(sched_delta) > 0.1)

                if has_change:
                    updated_count += 1
                    status_parts = []
                    summary_parts = []

                    if rev_delta > 0:
                        status_parts.append("COST_ESCALATED")
                        summary_parts.append(f"Revised cost increased by +₹{rev_delta:,.0f} Cr")
                    if sched_delta > 0:
                        status_parts.append("SCHEDULE_SLIPPED")
                        summary_parts.append(f"Timeline slipped by +{sched_delta:.0f} days")
                    elif sched_delta < 0:
                        status_parts.append("SCHEDULE_RECOVERED")
                        summary_parts.append(f"Schedule recovered by {abs(sched_delta):.0f} days")
                    if exp_delta > 0:
                        status_parts.append("EXPENDITURE_PROGRESSED")
                        summary_parts.append(f"Disbursed additional ₹{exp_delta:,.0f} Cr")

                    events.append({
                        "project_code": p_code,
                        "from_snapshot_id": from_snapshot_id,
                        "to_snapshot_id": to_snapshot_id,
                        "change_type": "UPDATED",
                        "cost_change_cr": cost_delta,
                        "revised_cost_change_cr": rev_delta,
                        "expenditure_change_cr": exp_delta,
                        "schedule_change_days": sched_delta,
                        "status_change": ";".join(status_parts) if status_parts else "UPDATED",
                        "change_summary": "; ".join(summary_parts) if summary_parts else "Telemetry updated."
                    })
                else:
                    unchanged_count += 1

        return {
            "from_snapshot_id": from_snapshot_id,
            "to_snapshot_id": to_snapshot_id,
            "summary": {
                "new_projects": new_count,
                "updated_projects": updated_count,
                "unchanged_projects": unchanged_count,
                "removed_or_completed": removed_count,
                "total_projects_compared": len(all_codes)
            },
            "events": events
        }

    @staticmethod
    def persist_change_events(comparison_result: Dict[str, Any]):
        """
        Saves computed change events into project_change_events table idempotently.
        """
        from_id = comparison_result["from_snapshot_id"]
        to_id = comparison_result["to_snapshot_id"]
        events = comparison_result.get("events", [])

        if not events:
            return

        conn = get_db_connection()
        cursor = conn.cursor()

        # Delete existing events for this pair to remain idempotent
        cursor.execute("""
        DELETE FROM project_change_events 
        WHERE from_snapshot_id = ? AND to_snapshot_id = ?;
        """, (from_id, to_id))

        for e in events:
            cursor.execute("""
            INSERT INTO project_change_events (
                project_code, from_snapshot_id, to_snapshot_id, change_type,
                cost_change_cr, revised_cost_change_cr, expenditure_change_cr,
                schedule_change_days, status_change, change_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                e["project_code"], from_id, to_id, e["change_type"],
                e["cost_change_cr"], e["revised_cost_change_cr"],
                e["expenditure_change_cr"], e["schedule_change_days"],
                e["status_change"], e["change_summary"]
            ))

        conn.commit()
        conn.close()
