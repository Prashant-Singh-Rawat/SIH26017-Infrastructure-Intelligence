"""
Land Acquisition Intelligence Engine — SIH26017
Statutory Stage Modeling under Right to Fair Compensation and Transparency in
Land Acquisition, Rehabilitation and Resettlement Act (RFCTLARR Act 2013) & PM GatiShakti.

Stages:
1. ADMIN_APPROVAL       - Administrative Sanction & Section 4/11 Preliminary Notification
2. COMPENSATION         - Section 19 Declaration & Section 23 Compensation Award Disbursement
3. LEGAL_DISPUTES       - Section 64 Reference to Authority & High Court Land Dispute Stays
4. REHAB_RESETTLEMENT   - Section 31 R&R Scheme Approval & Family Resettlement
5. PHYSICAL_POSSESSION  - Section 37/38 Encumbrance-Free Land Handover to Executing Agency
"""

import math
from typing import Dict, Any, List, Optional

LAND_STAGES = [
    {
        "stage_id": "ADMIN_APPROVAL",
        "stage_name": "Administrative Approval & Section 11 Notification",
        "statutory_act": "RFCTLARR Act 2013 (Section 4 Social Impact Assessment & Section 11 Preliminary Notification)",
        "sla_months": 12,
        "responsible_authority": "State Revenue Department & District Collector"
    },
    {
        "stage_id": "COMPENSATION",
        "stage_name": "Compensation Disbursement & Award Inquiry",
        "statutory_act": "RFCTLARR Act 2013 (Section 19 Declaration & Section 23/30 Award Determination)",
        "sla_months": 12,
        "responsible_authority": "Competent Authority for Land Acquisition (CALA) / Special Land Acquisition Officer (SLAO)"
    },
    {
        "stage_id": "LEGAL_DISPUTES",
        "stage_name": "Legal Dispute & Title Adjudication",
        "statutory_act": "RFCTLARR Act 2013 (Section 64 Reference to LARRA Authority / High Court Writ Stays)",
        "sla_months": 18,
        "responsible_authority": "Land Acquisition, Rehabilitation and Resettlement Authority (LARRA) / District Court"
    },
    {
        "stage_id": "REHAB_RESETTLEMENT",
        "stage_name": "Rehabilitation & Resettlement (R&R) Execution",
        "statutory_act": "RFCTLARR Act 2013 (Section 31 R&R Scheme & Second Schedule Infrastructure Amenities)",
        "sla_months": 18,
        "responsible_authority": "Administrator for Rehabilitation and Resettlement / Project Implementing Unit"
    },
    {
        "stage_id": "PHYSICAL_POSSESSION",
        "stage_name": "Physical Possession & Site Handover",
        "statutory_act": "RFCTLARR Act 2013 (Section 37/38 Taking Possession of Encumbrance-Free Land)",
        "sla_months": 6,
        "responsible_authority": "Executive Engineer / Project Director (Executing Ministry)"
    }
]

def evaluate_land_acquisition_bottleneck(
    land_required_acres: float = 100.0,
    land_acquired_pct: float = 50.0,
    compensation_disbursed_pct: Optional[float] = None,
    active_legal_disputes: int = 0,
    affected_families_count: int = 0,
    rehabilitation_package_cr: float = 0.0,
    land_clearance_status: str = "In Progress",
    cost_cr: float = 500.0
) -> Dict[str, Any]:
    """
    Evaluates statutory land acquisition risk parameters and deterministically
    isolates the primary bottleneck stage, confidence score, and specific directives.
    """
    # Fallback/inferred values if compensation disbursed % is not explicitly passed
    if compensation_disbursed_pct is None:
        # High correlation between land acquired and compensation disbursed with slight lag
        compensation_disbursed_pct = max(0.0, min(100.0, land_acquired_pct * 0.92))

    stage_scores = {}
    evidence_map = {}

    # 1. Evaluate Legal Disputes Stage
    dispute_risk = min(1.0, (active_legal_disputes * 0.28))
    if "court" in land_clearance_status.lower() or "dispute" in land_clearance_status.lower():
        dispute_risk = max(dispute_risk, 0.85)
    stage_scores["LEGAL_DISPUTES"] = dispute_risk
    evidence_map["LEGAL_DISPUTES"] = f"{active_legal_disputes} active land dispute petition(s) pending under Section 64/High Court writs"

    # 2. Evaluate Compensation Disbursement Stage
    comp_gap = max(0.0, (100.0 - compensation_disbursed_pct) / 100.0)
    # Higher penalty if land acquired is stalled while compensation is lagging
    comp_risk = comp_gap * 0.85
    stage_scores["COMPENSATION"] = comp_risk
    evidence_map["COMPENSATION"] = f"Compensation disbursed at {compensation_disbursed_pct:.1f}% vs planned 100% (Gap: {100.0 - compensation_disbursed_pct:.1f}%)"

    # 3. Evaluate Administrative Approval Stage
    if land_acquired_pct < 25.0:
        admin_risk = 0.78
        evidence_map["ADMIN_APPROVAL"] = f"Land acquired only {land_acquired_pct:.1f}%; Section 11 Gazette notification or SIA approval pending"
    elif "environmental" in land_clearance_status.lower() or "forest" in land_clearance_status.lower():
        admin_risk = 0.72
        evidence_map["ADMIN_APPROVAL"] = f"Statutory Stage 1/2 Forest & Environmental clearance bottleneck: {land_clearance_status}"
    else:
        admin_risk = 0.20
        evidence_map["ADMIN_APPROVAL"] = f"Section 11 Gazette notification completed; initial progress {land_acquired_pct:.1f}%"
    stage_scores["ADMIN_APPROVAL"] = admin_risk

    # 4. Evaluate Rehabilitation & Resettlement (R&R) Stage
    if affected_families_count > 100:
        rr_risk = min(0.90, (affected_families_count / 500.0) * 0.75)
        evidence_map["REHAB_RESETTLEMENT"] = f"{affected_families_count} project-affected families requiring Section 31 R&R infrastructure package (₹{rehabilitation_package_cr:.2f} Cr allocated)"
    else:
        rr_risk = 0.18
        evidence_map["REHAB_RESETTLEMENT"] = f"Low displacement intensity: {affected_families_count} families requiring standard resettlement assistance"
    stage_scores["REHAB_RESETTLEMENT"] = rr_risk

    # 5. Evaluate Physical Possession Stage
    possession_gap = max(0.0, (100.0 - land_acquired_pct) / 100.0)
    if land_acquired_pct >= 75.0 and compensation_disbursed_pct >= 80.0:
        # Last mile possession hold-up
        possession_risk = 0.65
        evidence_map["PHYSICAL_POSSESSION"] = f"Compensation complete but physical encumbrance-free site handover remaining on {100.0 - land_acquired_pct:.1f}% alignment"
    else:
        possession_risk = possession_gap * 0.50
        evidence_map["PHYSICAL_POSSESSION"] = f"Site possession dependent on prior award disbursement and boundary demarcation ({land_acquired_pct:.1f}% handed over)"
    stage_scores["PHYSICAL_POSSESSION"] = possession_risk

    # Isolate primary bottleneck
    sorted_stages = sorted(stage_scores.items(), key=lambda x: x[1], reverse=True)
    primary_stage_id, max_score = sorted_stages[0]

    # Find stage metadata
    stage_meta = next((s for s in LAND_STAGES if s["stage_id"] == primary_stage_id), LAND_STAGES[0])

    # Confidence calculation based on parameter availability
    confidence = 0.88
    if active_legal_disputes > 0 and land_required_acres > 0:
        confidence = 0.94
    if compensation_disbursed_pct is not None:
        confidence = min(0.96, confidence + 0.02)

    return {
        "bottleneck_stage_id": primary_stage_id,
        "bottleneck_stage_name": stage_meta["stage_name"],
        "statutory_act_reference": stage_meta["statutory_act"],
        "responsible_authority": stage_meta["responsible_authority"],
        "bottleneck_severity": "CRITICAL" if max_score >= 0.75 else ("HIGH" if max_score >= 0.50 else "MODERATE"),
        "stage_risk_score": round(max_score, 3),
        "stage_evidence": evidence_map.get(primary_stage_id, "Statutory process timeline divergence detected."),
        "confidence_score": round(confidence, 2),
        "stage_breakdown": [
            {
                "stage_id": s["stage_id"],
                "stage_name": s["stage_name"],
                "risk_score": round(stage_scores.get(s["stage_id"], 0.0), 3),
                "evidence": evidence_map.get(s["stage_id"], ""),
                "authority": s["responsible_authority"]
            }
            for s in LAND_STAGES
        ]
    }

def get_land_action_recommendations(
    bottleneck_stage: str,
    land_required_acres: float,
    land_acquired_pct: float,
    active_legal_disputes: int,
    affected_families_count: int,
    rehabilitation_package_cr: float,
    sector: str = "Infrastructure"
) -> List[Dict[str, Any]]:
    """
    Generates actionable, statutory recommendations aligned with RFCTLARR Act 2013 and PM GatiShakti protocols.
    """
    recs = []

    if bottleneck_stage == "LEGAL_DISPUTES" or active_legal_disputes > 0:
        recs.append({
            "priority": "CRITICAL (P0)",
            "action": "Constitute Special Lok Adalat & Section 64 Fast-Track Tribunal",
            "protocol": f"Empower District Legal Services Authority (DLSA) to conduct weekend Lok Adalats for {active_legal_disputes} pending land compensation disputes under RFCTLARR Section 64. Offer benchmark circle rate + 100% solatium to obtain consent decrees.",
            "authority": "Principal District Judge & Competent Authority for Land Acquisition (CALA)",
            "timeline": "30 Days",
            "expected_impact": "Resolves 60-70% of non-title litigation without High Court appellate hold-up."
        })

    if bottleneck_stage == "COMPENSATION" or land_acquired_pct < 70.0:
        pending_acres = round(land_required_acres * (1.0 - land_acquired_pct / 100.0), 1)
        recs.append({
            "priority": "IMMEDIATE (P1)",
            "action": "Direct Benefit Transfer (DBT) Escrow Release for Land Compensation",
            "protocol": f"Expedite Section 23/30 award disbursement for {pending_acres} pending acres. Establish dedicated PFMS-integrated escrow account to disburse compensation directly to authenticated Aadhaar-linked landholder accounts within 15 days.",
            "authority": "District Collector & Special Land Acquisition Officer (SLAO)",
            "timeline": "21 Days",
            "expected_impact": "Eliminates disbursement bottleneck and unlocks possession under Section 37."
        })

    if bottleneck_stage == "REHAB_RESETTLEMENT" or affected_families_count > 50:
        recs.append({
            "priority": "HIGH (P2)",
            "action": "Section 31 R&R Scheme Notification & Model Resettlement Colony Handover",
            "protocol": f"Notify approved R&R entitlement matrix under Second Schedule for {affected_families_count} families. Disburse one-time subsistence grants (₹36,000/family) and execute land-for-land allotments in municipal boundaries.",
            "authority": "Commissioner for Rehabilitation & Resettlement (State Government)",
            "timeline": "45 Days",
            "expected_impact": "Removes social resistance and secures peaceful site handover."
        })

    if bottleneck_stage == "ADMIN_APPROVAL" or land_acquired_pct < 30.0:
        recs.append({
            "priority": "IMMEDIATE (P1)",
            "action": "PM GatiShakti Network Planning Group (NPG) Alignment Clearance",
            "protocol": "Submit linear alignment coordinates to the PM GatiShakti National Master Plan GIS Portal to bypass overlapping forest, defense, and railway RoW clearances via automated inter-ministerial screening.",
            "authority": "Line Ministry Nodal Officer & Network Planning Group (DPIIT)",
            "timeline": "14 Days",
            "expected_impact": "Compresses statutory clearance timeline by 4-6 months."
        })

    if bottleneck_stage == "PHYSICAL_POSSESSION" or (land_acquired_pct >= 70.0 and land_acquired_pct < 100.0):
        recs.append({
            "priority": "STANDARD (P3)",
            "action": "Section 38 Summary Possession with Drone Demarcation",
            "protocol": "Deploy DGCA-certified drone survey team to establish geofenced boundary pillars on encumbrance-free parcels and issue Form-G Possession Certificate to Executing Agency.",
            "authority": "Sub-Divisional Magistrate (SDM) & Executive Engineer (PIU)",
            "timeline": "10 Days",
            "expected_impact": "Enables contractor mobilization on contiguous acquired stretches."
        })

    return recs
