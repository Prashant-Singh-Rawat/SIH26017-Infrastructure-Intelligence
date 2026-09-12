"""
Pydantic v2 Request & Response Schemas — SIH26017
Enforces strict type validation, range constraints, forbidden extras, and sanitized errors.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class PredictRequest(StrictBaseModel):
    sector_name: str = Field(..., min_length=2, max_length=120, description="Infrastructure sector name")
    line_ministry: str = Field(..., min_length=2, max_length=255, description="Responsible line ministry")
    original_cost_cr: float = Field(..., gt=0.0, le=1000000.0, description="Original sanctioned outlay in Crores (INR)")
    planned_end_year: int = Field(..., ge=2000, le=2050, description="Planned completion calendar year")
    planned_end_quarter: int = Field(2, ge=1, le=4, description="Planned completion fiscal quarter (1-4)")
    # Land Acquisition Stage Parameters (RFCTLARR Act 2013)
    project_code: Optional[int] = Field(None, description="Existing project code if evaluating catalog asset")
    land_required_acres: Optional[float] = Field(None, ge=0.0, le=1000000.0, description="Total land required in acres")
    land_acquired_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Percentage of land acquired to date")
    compensation_disbursed_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Percentage of compensation disbursed")
    active_legal_disputes: Optional[int] = Field(None, ge=0, le=5000, description="Active court stays or Section 64 dispute petitions")
    affected_families_count: Optional[int] = Field(None, ge=0, le=500000, description="Number of project-affected families requiring R&R")
    rehabilitation_package_cr: Optional[float] = Field(None, ge=0.0, le=100000.0, description="R&R package outlay in Crores")
    current_land_stage: Optional[str] = Field(None, max_length=64, description="Current statutory stage ID")

class SimulateRequest(StrictBaseModel):
    sector_name: str = Field(..., min_length=2, max_length=120, description="Infrastructure sector name")
    line_ministry: str = Field(..., min_length=2, max_length=255, description="Responsible line ministry")
    original_cost_cr: float = Field(..., gt=0.0, le=1000000.0, description="Original sanctioned outlay in Crores (INR)")
    planned_end_year: int = Field(..., ge=2000, le=2050, description="Planned completion calendar year")
    planned_end_quarter: int = Field(2, ge=1, le=4, description="Planned completion fiscal quarter (1-4)")
    fast_track_clearance: bool = Field(False, description="Apply single-window fast track clearance")
    advance_land_row: bool = Field(False, description="Apply advance 100% RoW possession")
    milestone_funding: bool = Field(False, description="Apply milestone tranche disbursement")
    # Land Intervention Levers
    resolve_disputes: bool = Field(False, description="Constitute Section 64 Lok Adalat fast-track tribunal")
    dbt_compensation_release: bool = Field(False, description="PFMS direct escrow compensation release")
    drone_possession_handover: bool = Field(False, description="Accelerated Section 38 drone boundary demarcation")
    project_code: Optional[int] = Field(None, description="Optional project code for context")
    land_required_acres: Optional[float] = Field(None, ge=0.0, description="Land required in acres")
    land_acquired_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Current land acquired %")
    active_legal_disputes: Optional[int] = Field(None, ge=0, description="Active disputes count")

class EGoSDispatchPayload(StrictBaseModel):
    project_code: Optional[int] = Field(None, description="Project code")
    project_name: Optional[str] = Field(None, max_length=255, description="Project title")
    sector_name: Optional[str] = Field(None, max_length=120, description="Sector name")
    line_ministry: Optional[str] = Field(None, max_length=255, description="Line ministry")
    days_saved: int = Field(default=0, ge=0, description="Days recovered")
    cost_averted_cr: float = Field(default=0.0, ge=0.0, description="Cost escalation averted in Crores")
    selected_knobs: Optional[List[str]] = Field(default_factory=list, description="Selected policy intervention knobs")

class AlertAcknowledgeRequest(StrictBaseModel):
    notes: Optional[str] = Field(None, max_length=500, description="Officer audit or mitigation notes")
    status: str = Field("ACKNOWLEDGED", pattern="^(ACKNOWLEDGED|RESOLVED)$", description="Target alert status")

class AlertAssignRequest(StrictBaseModel):
    assigned_authority: str = Field(..., min_length=3, max_length=255, description="Assigned government officer or authority")
    assignment_notes: Optional[str] = Field(None, max_length=500, description="Assignment rationale and deadline directives")

class AlertCommentRequest(StrictBaseModel):
    comment_text: str = Field(..., min_length=3, max_length=1000, description="Officer note or audit comment")

class CreateAlertRequest(StrictBaseModel):
    project_code: int = Field(..., gt=0, description="Unique project code to associate alert with")
    severity: str = Field(..., pattern="^(CRITICAL|HIGH|MEDIUM|LOW)$", description="Alert severity level")
    reason: str = Field(..., min_length=5, max_length=500, description="Trigger reason and risk description")
    category: Optional[str] = Field("SCHEDULE_DELAY", max_length=120, description="Alert category")
    title: Optional[str] = Field(None, max_length=255, description="Brief alert title")
    assigned_authority: Optional[str] = Field("Project Monitoring Group (PMG)", max_length=255, description="Nodal monitoring body")

class SnapshotIngestPayload(StrictBaseModel):
    snapshot_id: str = Field(..., min_length=3, max_length=64, pattern="^[a-zA-Z0-9_-]+$", description="Unique alphanumeric snapshot identifier")
    snapshot_label: str = Field(..., min_length=3, max_length=120, description="Descriptive snapshot label")
    snapshot_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Snapshot date in YYYY-MM-DD format")
    csv_content: Optional[str] = Field(None, description="Raw CSV string content of the snapshot file")
    notes: Optional[str] = Field(None, max_length=500, description="Administrative ingestion notes")

class ErrorDetail(StrictBaseModel):
    code: str
    message: str
    request_id: Optional[str] = None
    details: Optional[Any] = None

class ErrorResponse(StrictBaseModel):
    error: ErrorDetail
