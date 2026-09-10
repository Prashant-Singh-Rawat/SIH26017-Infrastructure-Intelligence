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
    planned_end_year: int = Field(..., ge=2024, le=2050, description="Planned completion calendar year")
    planned_end_quarter: int = Field(2, ge=1, le=4, description="Planned completion fiscal quarter (1-4)")

class SimulateRequest(StrictBaseModel):
    sector_name: str = Field(..., min_length=2, max_length=120, description="Infrastructure sector name")
    line_ministry: str = Field(..., min_length=2, max_length=255, description="Responsible line ministry")
    original_cost_cr: float = Field(..., gt=0.0, le=1000000.0, description="Original sanctioned outlay in Crores (INR)")
    planned_end_year: int = Field(..., ge=2024, le=2050, description="Planned completion calendar year")
    planned_end_quarter: int = Field(2, ge=1, le=4, description="Planned completion fiscal quarter (1-4)")
    fast_track_clearance: bool = Field(False, description="Apply single-window fast track clearance")
    advance_land_row: bool = Field(False, description="Apply advance 100% RoW possession")
    milestone_funding: bool = Field(False, description="Apply milestone tranche disbursement")

class AlertAcknowledgeRequest(StrictBaseModel):
    notes: Optional[str] = Field(None, max_length=500, description="Officer audit or mitigation notes")
    status: str = Field("ACKNOWLEDGED", pattern="^(ACKNOWLEDGED|RESOLVED)$", description="Target alert status")

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
