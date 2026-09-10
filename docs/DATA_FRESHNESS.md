# Dashboard Data Freshness & Source Outage Architecture
**SIH26017 — Infrastructure Delay & Cost Overrun Intelligence Platform**
**Division**: Infrastructure and Project Monitoring Division (IPMD) | Government of India

---

## 1. Truth in Government Telemetry (Anti-Deception Standard)
A core mandate of this platform is absolute transparency in state reporting. Commercial prototypes often display deceptive indicators such as glowing green "LIVE DATA" badges or animated counters simulating real-time activity. 

**Platform Standard**:
- If data reflects a monthly published snapshot, it **MUST** be explicitly labeled:
  `STATUS: HISTORICAL SNAPSHOT`
- The system **NEVER** displays fake "LIVE" status unless an actual, continuous real-time governmental telemetry feed is active.
- API connectivity is honestly reported as:
  `"READY FOR AUTHORIZED GOVERNMENT API CREDENTIALS"`

---

## 2. Global Data Freshness Indicator
The platform header features an institutional banner populated dynamically via `GET /api/v1/data/freshness`:

| Telemetry Element | Example Value | Provenance Rule |
| :--- | :--- | :--- |
| **Data Source** | `MoSPI PAIMANA` | Identifies publishing authority |
| **Latest Snapshot** | `April 2026 (Baseline)` / `May 2026` | Reflects actual registered snapshot date |
| **Monitored Projects** | `1,981` | Direct ground-truth row count |
| **Source Status** | `HISTORICAL SNAPSHOT` | Explicit non-realtime declaration |
| **API Adapter** | `READY FOR AUTHORIZED API CREDENTIALS` | Honest gateway declaration |
| **Official Disclaimer** | `Source: MoSPI PAIMANA official publication/data snapshot \| SIH26017 Prototype — Independent analytical layer` | Explicit statutory non-endorsement |

---

## 3. Telemetry Payload Contract (`GET /api/v1/data/freshness`)
```json
{
  "data_source": "MoSPI PAIMANA Central Sector Projects Repository",
  "organization": "Ministry of Statistics and Programme Implementation (MoSPI), Government of India",
  "source_url": "https://paimana.gov.in",
  "latest_snapshot_id": "paimana_2026_04",
  "latest_snapshot_date": "2026-04-30",
  "latest_snapshot_label": "PAIMANA April 2026 Baseline Snapshot",
  "last_ingested": "2026-09-10 20:55:00",
  "total_records": 1981,
  "status": "HISTORICAL SNAPSHOT",
  "official_status": "OFFICIAL_GOVERNMENT",
  "provenance": "[SOURCE — MoSPI PAIMANA]",
  "is_live": false,
  "api_integration_status": "READY FOR AUTHORIZED GOVERNMENT API CREDENTIALS",
  "disclaimer": "Source: MoSPI PAIMANA official publication/data snapshot | SIH26017 Prototype — Independent analytical layer"
}
```

---

## 4. Source Outage & Failure Recovery Protocol (Phase 24)
In the event that an upstream data provider, file repository, or governmental API endpoint is degraded or inaccessible:

1. **Zero Data Fabrication**: Under no circumstances will synthetic or hallucinated project records be generated to fill gaps.
2. **Snapshot Retention**: The dashboard continues serving the most recently validated snapshot (`paimana_2026_04` / `paimana_2026_05`).
3. **Outage Banner Notification**:
   - Status transitions from `VALIDATED` to:
     `"Source temporarily unavailable. Displaying verified snapshot from 2026-04-30."`
   - `last_successful_fetch` is displayed alongside `last_attempted_fetch`.
   - The dashboard never collapses or appears empty due to upstream downtime.
4. **Audit Incident Logging**: Every failed ingestion or connection timeout is logged to `ingestion_runs` with `status = 'FAILED'`, `error_message`, and stack trace for administrative review in the Data Update Center.
