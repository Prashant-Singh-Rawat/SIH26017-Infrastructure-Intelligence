# Disaster Recovery & Continuity Plan
**Project:** PM-OCMS Infrastructure Delay & Cost Overrun Intelligence Platform (SIH26017)

---

## 1. Resilience & Recovery Objectives

- **Recovery Point Objective (RPO)**: < 1 hour for transaction snapshots; 0 data loss for quarterly project records.
- **Recovery Time Objective (RTO)**: < 15 minutes for complete service restoration.

---

## 2. Backup Strategy

### 2.1. Supabase Automated Managed Backups
- Supabase automatically takes daily logical backups with Write-Ahead Logging (WAL) enabled on production plans, enabling Point-In-Time Recovery (PITR) up to 7 days.
- In addition, scheduled weekly exports can be triggered via `pg_dump`:
  ```bash
  pg_dump "$DATABASE_URL" --format=custom --file=infra_backup_$(date +%Y%m%d).dump
  ```

### 2.2. Offline Local SQLite Disaster Fallback
- If cloud PostgreSQL infrastructure becomes unavailable or network partitioned, the application automatically falls back to local SQLite storage at `data/infra_governance.db`.
- The SQLite database contains all 1,981 project records, historical benchmarks, and model artifacts, allowing the intelligence dashboard to function completely offline without service interruption.

---

## 3. Incident Rollback Protocols

### 3.1. Data Ingestion Rollback
Every batch import executed by `scripts/import_data.py` generates a unique `import_id` in `data_imports`. If an imported dataset contains corrupt values:
```sql
-- Revert specific import batch if needed
DELETE FROM projects WHERE data_provenance = 'SOURCE' AND project_code IN (...);
-- Re-run import with verified file
python scripts/import_data.py --version v2026.09_verified
```

### 3.2. Machine Learning Model Rollback
If a newly deployed model exhibits distribution drift or degraded accuracy, rollback to the champion model (`v1.0.0-champion`) without deploying new code:
```sql
UPDATE model_versions SET status = 'ARCHIVED' WHERE version = 'v2.0.0-failing';
UPDATE model_versions SET status = 'PRODUCTION' WHERE version = 'v1.0.0-champion';
```
The FastAPI application loads models referencing the active `PRODUCTION` version metadata.
