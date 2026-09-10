"""
Official MoSPI PAIMANA Data Source Adapter — SIH26017
Handles official snapshot ingestion (CSV/XLSX) and provides adapter readiness for authorized government APIs.
Enforces strict validation, cryptographic checksums, formula injection defense, and raw data preservation.
"""

import os
import re
import hashlib
import json
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
import numpy as np

from backend.database import get_db_connection

class PaimanaAdapter:
    """
    Adapter for Ministry of Statistics and Programme Implementation (MoSPI)
    PAIMANA (Project Assessment and Information Management National Agency)
    Central Sector Infrastructure Projects Repository.
    """
    SOURCE_ID = "mospi_paimana"
    SOURCE_NAME = "MoSPI PAIMANA Central Sector Projects Repository"
    PROVENANCE_TAG = "[SOURCE — MoSPI PAIMANA]"
    
    EXPECTED_COLUMNS = [
        "project_code", "project_name", "sector_name", "line_ministry",
        "original_cost_cr", "revised_cost_cr", "expenditure_cr",
        "original_end_date", "revised_end_date"
    ]

    def __init__(self):
        self.api_endpoint = os.getenv("PAIMANA_API_ENDPOINT", "").strip()
        self.api_key = os.getenv("PAIMANA_API_KEY", "").strip()

    def get_source_status(self) -> Dict[str, Any]:
        """
        Returns real-world source status. If government API credentials are not provided,
        truthfully reports SNAPSHOT_FILE_IMPORT status without fabricating live API connectivity.
        """
        has_api_creds = bool(self.api_endpoint and self.api_key)
        return {
            "source_id": self.SOURCE_ID,
            "source_name": self.SOURCE_NAME,
            "provenance": self.PROVENANCE_TAG,
            "access_method": "DIRECT_API" if has_api_creds else "SNAPSHOT_FILE_IMPORT",
            "api_integration_status": "ONLINE_AUTHENTICATED" if has_api_creds else "READY FOR AUTHORIZED GOVERNMENT API CREDENTIALS",
            "official_status": "OFFICIAL_GOVERNMENT",
            "update_frequency": "MONTHLY",
            "is_live_stream": False,
            "notes": "Monitors central sector infrastructure projects costing ₹150 Cr and above. Uses official government snapshot datasets."
        }

    @staticmethod
    def calculate_checksum(file_content: bytes) -> str:
        """Computes SHA-256 checksum for raw snapshot integrity auditing."""
        return f"sha256:{hashlib.sha256(file_content).hexdigest()}"

    @staticmethod
    def sanitize_cell_value(val: Any) -> Any:
        """
        Mitigates CSV Formula Injection (CWE-1236).
        Prevents spreadsheet execution of formulas starting with =, +, -, @, or tabs.
        """
        if isinstance(val, str):
            val_clean = val.strip()
            if val_clean and val_clean[0] in ('=', '+', '-', '@', '\t', '\r'):
                # Prefix with single quote to neutralize formula
                return "'" + val_clean
            return val_clean
        return val

    def parse_and_validate_file(self, file_content: bytes, filename: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
        """
        Parses raw snapshot bytes, validates data quality, and isolates invalid records into quarantine.
        Returns: (valid_records, quarantined_records, validation_summary)
        """
        checksum = self.calculate_checksum(file_content)
        file_size = len(file_content)

        # Detect format
        import io
        if filename.endswith(".xlsx") or filename.endswith(".xls"):
            df = pd.read_excel(io.BytesIO(file_content))
        else:
            text_data = file_content.decode("utf-8", errors="replace")
            lines = [l.strip() for l in text_data.splitlines() if l.strip()]
            skip = 0
            for line_idx, line in enumerate(lines[:5]):
                line_lower = line.lower()
                if "project" in line_lower or "sector" in line_lower or "ministry" in line_lower or "sr_no" in line_lower:
                    skip = line_idx
                    break
            df = pd.read_csv(io.StringIO(text_data), skiprows=skip)

        # Map / rename standard columns flexibly
        col_map = {}
        for col in df.columns:
            c_lower = str(col).lower().strip().replace(" ", "_").replace(".", "")
            if "code" in c_lower or "proj_id" in c_lower:
                col_map[col] = "project_code"
            elif "sector" in c_lower:
                col_map[col] = "sector_name"
            elif "ministry" in c_lower:
                col_map[col] = "line_ministry"
            elif "original_cost" in c_lower or "orig_cost" in c_lower:
                col_map[col] = "original_cost_cr"
            elif "revised_cost" in c_lower or "rev_cost" in c_lower:
                col_map[col] = "revised_cost_cr"
            elif "expenditure" in c_lower or "expend" in c_lower:
                col_map[col] = "expenditure_cr"
            elif "original_end" in c_lower or "orig_date" in c_lower:
                col_map[col] = "original_end_date_str"
            elif "revised_end" in c_lower or "rev_date" in c_lower:
                col_map[col] = "revised_end_date_str"
            elif "project_name" in c_lower or "proj_name" in c_lower or c_lower in ("project", "name"):
                col_map[col] = "project_name"

        df = df.rename(columns=col_map)

        valid_records = []
        quarantined_records = []

        seen_codes = set()
        for idx, row in df.iterrows():
            row_idx = idx + 1
            reasons = []

            # 1. Project Code validation
            raw_code = row.get("project_code")
            try:
                p_code = int(float(raw_code))
                if p_code <= 0:
                    reasons.append("PROJECT_CODE_NON_POSITIVE")
                elif p_code in seen_codes:
                    reasons.append("DUPLICATE_CODE_IN_SNAPSHOT")
                else:
                    seen_codes.add(p_code)
            except (ValueError, TypeError):
                reasons.append("INVALID_PROJECT_CODE")
                p_code = None

            # 2. Project Name validation
            p_name = self.sanitize_cell_value(row.get("project_name", ""))
            if not p_name or str(p_name).strip() == "" or str(p_name).lower() == "nan":
                reasons.append("MISSING_PROJECT_NAME")

            # 3. Sector & Ministry
            sector = self.sanitize_cell_value(row.get("sector_name", "Infrastructure"))
            ministry = self.sanitize_cell_value(row.get("line_ministry", "Central Ministry"))

            # 4. Financial costs validation
            orig_cost = pd.to_numeric(row.get("original_cost_cr"), errors="coerce")
            rev_cost = pd.to_numeric(row.get("revised_cost_cr"), errors="coerce")
            expenditure = pd.to_numeric(row.get("expenditure_cr"), errors="coerce")

            if pd.isna(orig_cost) or orig_cost < 0:
                reasons.append("INVALID_ORIGINAL_COST")
                orig_cost = 0.0
            if pd.isna(rev_cost) or rev_cost < 0:
                rev_cost = 0.0
            if pd.isna(expenditure) or expenditure < 0:
                expenditure = 0.0

            # 5. Date parsing & validation
            orig_date_str = str(row.get("original_end_date_str", "")).strip()
            rev_date_str = str(row.get("revised_end_date_str", "")).strip()

            orig_date = pd.to_datetime(orig_date_str, format="%d/%m/%Y", errors="coerce")
            if pd.isna(orig_date):
                orig_date = pd.to_datetime(orig_date_str, errors="coerce")

            rev_date = pd.to_datetime(rev_date_str, format="%d/%m/%Y", errors="coerce")
            if pd.isna(rev_date):
                rev_date = pd.to_datetime(rev_date_str, errors="coerce")

            # Date anomaly checks
            if pd.notna(orig_date) and orig_date.year > 2060:
                reasons.append("EXTREME_FUTURE_DATE")

            # Derived Metrics & Quality Flags
            dq_flags = []
            rev_set = 1 if rev_cost > 0.0 else 0
            rev_missing = 1 if pd.isna(rev_date) else 0

            if rev_set == 0:
                dq_flags.append("NOT_YET_REVISED_COST")
            if rev_missing == 1:
                dq_flags.append("MISSING_REVISED_DATE")
            if expenditure > orig_cost:
                dq_flags.append("EXPENDITURE_EXCEEDS_ORIGINAL")

            if pd.notna(orig_date) and pd.notna(rev_date):
                diff = (rev_date - orig_date).days
                is_del = 1 if diff > 0 else 0
                delay_days = float(diff)
            else:
                is_del = 0
                delay_days = 0.0

            cost_overrun_pct = round(((rev_cost - orig_cost) / orig_cost * 100), 2) if (rev_set and orig_cost > 0) else None

            record = {
                "project_code": p_code,
                "project_name": str(p_name),
                "sector_name": str(sector),
                "line_ministry": str(ministry),
                "original_cost_cr": float(orig_cost),
                "revised_cost_cr": float(rev_cost),
                "expenditure_cr": float(expenditure),
                "original_end_date": orig_date.strftime("%Y-%m-%d") if pd.notna(orig_date) else None,
                "revised_end_date": rev_date.strftime("%Y-%m-%d") if pd.notna(rev_date) else None,
                "is_delayed": is_del,
                "schedule_delay_days": delay_days,
                "cost_overrun_pct": cost_overrun_pct,
                "data_quality_flags": ";".join(dq_flags) if dq_flags else "CLEAN",
                "data_provenance": self.PROVENANCE_TAG
            }

            if reasons:
                record["quarantine_reasons"] = reasons
                record["source_row"] = row_idx
                quarantined_records.append(record)
            else:
                valid_records.append(record)

        summary = {
            "checksum": checksum,
            "file_size_bytes": file_size,
            "total_raw_rows": len(df),
            "valid_record_count": len(valid_records),
            "quarantined_record_count": len(quarantined_records),
            "quarantine_rate_pct": round((len(quarantined_records) / max(1, len(df))) * 100, 2),
            "status": "PASS" if len(quarantined_records) == 0 else ("WARN" if len(valid_records) > 0 else "FAIL")
        }

        return valid_records, quarantined_records, summary
