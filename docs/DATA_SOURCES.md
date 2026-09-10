# Official Data Sources & Registry Specifications
**SIH26017 — Infrastructure Delay & Cost Overrun Intelligence Platform**
**Division**: Infrastructure and Project Monitoring Division (IPMD) | Government of India

---

## 1. Official Data Source Registry Overview
The system maintains an explicit catalog of verified public sector information channels. No arbitrary or unverified data sources may be imported without registration in `data_source_registry`.

### Legal & Institutional Disclaimer
> **IMPORTANT NOTICE REGARDING GOVERNMENT ENDORSEMENT**
> This software is an independent analytical prototype developed for the **Smart India Hackathon (SIH26017)**.
> All baseline data is extracted from officially published data snapshots released by the Ministry of Statistics and Programme Implementation (MoSPI).
> Use of government data does **NOT** imply official endorsement, certification, or operational commissioning by the Government of India, MoSPI, or any affiliated ministry.

---

## 2. Registered Data Sources

### Primary Source: MoSPI PAIMANA
- **Source Identifier**: `mospi_paimana`
- **Source Name**: MoSPI PAIMANA Central Sector Projects Repository
- **Governing Body**: Ministry of Statistics and Programme Implementation (MoSPI), Government of India
- **Mandate**: Monitors Central Sector Infrastructure Projects costing ₹150 crore and above under the PAIMANA / OCMS framework.
- **Official URL**: `https://paimana.gov.in`
- **Source Type**: `OFFICIAL_GOVERNMENT`
- **Access Method**: `OFFICIAL_CSV / XLSX / REST_ADAPTER`
- **Current Official Status**: `OFFICIAL_GOVERNMENT`
- **Update Frequency**: `MONTHLY`
- **Current Schema Version**: `v2.1`
- **Operational Status**: `AVAILABLE`
- **Mandatory Provenance Tag**: `[SOURCE — MoSPI PAIMANA]`
- **API Status**: `"READY FOR AUTHORIZED GOVERNMENT API CREDENTIALS"`
- **Notes**: Baseline dataset contains 1,981 central sector projects representing national infrastructure monitoring as of the April 2026 snapshot.

---

## 3. Data Source Registry Schema
The database table `data_source_registry` enforces the following structure:

| Field Name | Type | Description |
| :--- | :--- | :--- |
| `id` | `VARCHAR(64)` PRIMARY KEY | Unique machine-readable identifier (e.g. `mospi_paimana`). |
| `source_name` | `VARCHAR(255)` NOT NULL | Official name of data publishing system. |
| `organization` | `VARCHAR(255)` NOT NULL | Government department or public agency. |
| `source_url` | `VARCHAR(512)` | Publicly accessible portal reference. |
| `source_type` | `VARCHAR(64)` NOT NULL | `OFFICIAL_GOVERNMENT`, `OFFICIAL_API`, `OFFICIAL_CSV`, `DERIVED`, `DEMO`. |
| `access_method` | `VARCHAR(64)` NOT NULL | Ingestion vector (`REST_API`, `FILE_UPLOAD`, `AUTOMATED_JOB`). |
| `official_status`| `VARCHAR(64)` NOT NULL | Verification classification. |
| `update_frequency`| `VARCHAR(32)` NOT NULL | Update cadence (`DAILY`, `WEEKLY`, `MONTHLY`, `QUARTERLY`). |
| `last_successful_fetch` | `TIMESTAMPTZ` | Timestamp of most recent validated ingestion. |
| `last_attempted_fetch` | `TIMESTAMPTZ` | Timestamp of most recent ingestion attempt. |
| `schema_version` | `VARCHAR(32)` NOT NULL | Data contract revision (e.g. `v2.1`). |
| `status` | `VARCHAR(32)` NOT NULL | Health flag (`AVAILABLE`, `DEGRADED`, `UNAVAILABLE`). |
| `provenance` | `VARCHAR(128)` NOT NULL | Display tag prefix (e.g. `[SOURCE — MoSPI PAIMANA]`). |
| `notes` | `TEXT` | Architectural and administrative commentary. |

---

## 4. Permitted Ingestion Vectors & Rate Limits

1. **Official File Upload (CSV / XLSX)**:
   - Permitted through administrative UI (`Data Update Center`) or `POST /api/v1/data/ingest`.
   - Payload limit: **15 MB**.
   - Maximum rows per upload: **100,000 records**.
   - Rate limit: **5 uploads per hour** for authenticated administrative tokens.

2. **Authorized API Ingestion (REST Gateway)**:
   - Configured in `backend/adapters/paimana_adapter.py`.
   - Supports mutual TLS (mTLS), HMAC header signing, and Bearer token exchanges.
   - Strictly disabled from unauthorized scraping. Must only connect when genuine government endpoint credentials (`PAIMANA_API_KEY`, `PAIMANA_API_ENDPOINT`) are supplied via environment variables.

3. **Fallback & Source Outage Handling**:
   - If the official portal or upstream gateway is unreachable, the system maintains the last validated snapshot (`paimana_2026_04`).
   - The UI displays: `"Source temporarily unavailable. Displaying last verified snapshot."`
   - Zero synthetic or hallucinated project entities are ever inserted to patch outages.
