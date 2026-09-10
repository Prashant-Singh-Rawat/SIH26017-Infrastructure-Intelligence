"""
Project Risk Evolution & Early Warning Deterioration Engine — SIH26017
Tracks ML prediction risk transitions across government snapshots.
Automatically generates prioritized alert triggers for risk escalation (e.g. Medium -> High, High -> Critical).
"""

import time
from typing import Dict, Any, List, Optional
from backend.database import get_db_connection

TIER_SEVERITY_MAP = {
    "Low Delay Risk": {"rank": 1, "alert_severity": "LOW"},
    "Medium Delay Risk": {"rank": 2, "alert_severity": "MEDIUM"},
    "High Delay Risk": {"rank": 3, "alert_severity": "HIGH"},
    "Critical Delay Risk": {"rank": 4, "alert_severity": "CRITICAL"}
}

class RiskTracker:
    """
    Evaluates project risk trajectories across temporal snapshots and dispatches alerts.
    """

    @staticmethod
    def evaluate_and_record_prediction(
        project_code: int,
        risk_probability: float,
        risk_tier: str,
        expected_delay_days: int,
        expected_delay_months: float,
        snapshot_id: str = "paimana_2026_04",
        model_version: str = "v2.1.0"
    ) -> Dict[str, Any]:
        """
        Records prediction into prediction_history, checks for risk tier escalation,
        and creates an early warning alert if deterioration is detected.
        """
        conn = get_db_connection()
        cursor = conn.cursor()

        # Find immediate prior prediction
        cursor.execute("""
        SELECT risk_tier, risk_probability, snapshot_id FROM prediction_history
        WHERE project_code = ?
        ORDER BY prediction_date DESC, created_at DESC
        LIMIT 1;
        """, (project_code,))
        prev_row = cursor.fetchone()

        prev_tier = prev_row[0] if prev_row else None
        prev_prob = prev_row[1] if prev_row else None
        prev_snap = prev_row[2] if prev_row else None

        curr_rank = TIER_SEVERITY_MAP.get(risk_tier, {}).get("rank", 1)
        prev_rank = TIER_SEVERITY_MAP.get(prev_tier, {}).get("rank", curr_rank) if prev_tier else curr_rank

        escalated = False
        change_desc = "UNCHANGED"
        if prev_tier:
            if curr_rank > prev_rank:
                escalated = True
                change_desc = f"DETERIORATED ({prev_tier} → {risk_tier})"
            elif curr_rank < prev_rank:
                change_desc = f"IMPROVED ({prev_tier} → {risk_tier})"

        pred_id = f"ph_{project_code}_{int(time.time())}"

        cursor.execute("""
        INSERT INTO prediction_history (
            id, project_code, snapshot_id, prediction_date, risk_probability,
            risk_tier, expected_delay_days, expected_delay_months,
            previous_risk_tier, risk_tier_change, model_version, escalation_alert_created
        ) VALUES (?, ?, ?, DATE('now'), ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            pred_id, project_code, snapshot_id, risk_probability, risk_tier,
            expected_delay_days, expected_delay_months, prev_tier, change_desc,
            model_version, 1 if escalated else 0
        ))

        alert_created = None
        if escalated:
            # Create high-priority early warning alert
            alert_severity = TIER_SEVERITY_MAP.get(risk_tier, {}).get("alert_severity", "HIGH")
            alert_title = f"Early Warning: {change_desc}"
            alert_desc = (
                f"Automated risk monitoring detected escalation from {prev_tier} (Snapshot: {prev_snap or 'Inception'}) "
                f"to {risk_tier} in Snapshot {snapshot_id}. Delay probability shifted from {prev_prob*100:.1f}% to {risk_probability*100:.1f}% "
                f"(+{expected_delay_days} projected delay days)."
            )

            cursor.execute("""
            INSERT INTO project_alerts (
                project_code, alert_severity, alert_category, alert_title,
                alert_description, escalation_authority, status
            ) VALUES (?, ?, 'RISK_TRAJECTORY_ESCALATION', ?, ?, 'Project Monitoring Group (PMG)', 'ACTIVE');
            """, (project_code, alert_severity, alert_title, alert_desc))
            alert_id = cursor.lastrowid
            alert_created = {
                "alert_id": alert_id,
                "severity": alert_severity,
                "title": alert_title
            }

        conn.commit()
        conn.close()

        return {
            "prediction_id": pred_id,
            "project_code": project_code,
            "risk_tier": risk_tier,
            "previous_risk_tier": prev_tier,
            "risk_change": change_desc,
            "escalation_detected": escalated,
            "alert_created": alert_created
        }

    @staticmethod
    def get_risk_history_for_project(project_code: int) -> List[Dict[str, Any]]:
        """Returns chronological list of predictions and risk transitions."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT ph.*, ds.snapshot_label
        FROM prediction_history ph
        LEFT JOIN data_snapshots ds ON ph.snapshot_id = ds.id
        WHERE ph.project_code = ?
        ORDER BY ph.prediction_date ASC, ph.created_at ASC;
        """, (project_code,))
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows
