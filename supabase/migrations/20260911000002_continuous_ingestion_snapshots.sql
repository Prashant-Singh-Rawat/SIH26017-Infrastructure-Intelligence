-- ============================================================================
-- PM-OCMS Infrastructure Delay & Cost Overrun Intelligence Platform (SIH26017)
-- Continuous Ingestion, Historical Snapshots, and Change Detection Migration
-- Migration ID: 20260911000002_continuous_ingestion_snapshots.sql
-- ============================================================================

-- 1. DATA SOURCE REGISTRY
CREATE TABLE IF NOT EXISTS data_source_registry (
    id VARCHAR(64) PRIMARY KEY,
    source_name VARCHAR(255) NOT NULL,
    organization VARCHAR(255) NOT NULL,
    source_url TEXT,
    source_type VARCHAR(64) NOT NULL CHECK (source_type IN ('OFFICIAL_GOVERNMENT', 'OFFICIAL_API', 'OFFICIAL_CSV', 'OFFICIAL_XLSX', 'OFFICIAL_REPORT', 'DERIVED', 'DEMO')),
    access_method VARCHAR(64) NOT NULL CHECK (access_method IN ('SNAPSHOT_FILE_IMPORT', 'DIRECT_API', 'SCHEDULED_JOB', 'MANUAL_UPLOAD')),
    official_status VARCHAR(64) NOT NULL DEFAULT 'OFFICIAL_GOVERNMENT',
    update_frequency VARCHAR(64) NOT NULL DEFAULT 'MONTHLY',
    last_successful_fetch TIMESTAMPTZ,
    last_attempted_fetch TIMESTAMPTZ,
    schema_version VARCHAR(32) NOT NULL DEFAULT 'v2.1',
    status VARCHAR(32) NOT NULL DEFAULT 'AVAILABLE',
    provenance VARCHAR(64) NOT NULL DEFAULT '[SOURCE — MoSPI PAIMANA]',
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Seed Official MoSPI PAIMANA Registry Entry
INSERT INTO data_source_registry (
    id, source_name, organization, source_url, source_type, access_method,
    official_status, update_frequency, last_successful_fetch, last_attempted_fetch,
    schema_version, status, provenance, notes
) VALUES (
    'mospi_paimana',
    'MoSPI PAIMANA Central Sector Projects Repository',
    'Ministry of Statistics and Programme Implementation (MoSPI), Government of India',
    'https://paimana.gov.in',
    'OFFICIAL_GOVERNMENT',
    'SNAPSHOT_FILE_IMPORT',
    'OFFICIAL_GOVERNMENT',
    'MONTHLY',
    '2026-04-30 00:00:00+00',
    CURRENT_TIMESTAMP,
    'v2.1',
    'AVAILABLE',
    '[SOURCE — MoSPI PAIMANA]',
    'Monitors central sector infrastructure projects costing ₹150 crore and above. Ready for authorized government API credentials.'
) ON CONFLICT (id) DO UPDATE SET
    updated_at = CURRENT_TIMESTAMP;

-- 2. DATA SNAPSHOTS CATALOG
CREATE TABLE IF NOT EXISTS data_snapshots (
    id VARCHAR(64) PRIMARY KEY,
    source_id VARCHAR(64) REFERENCES data_source_registry(id),
    source_name VARCHAR(255) NOT NULL,
    snapshot_date DATE NOT NULL,
    snapshot_label VARCHAR(120) NOT NULL,
    retrieval_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    record_count INTEGER NOT NULL DEFAULT 0,
    delayed_count INTEGER NOT NULL DEFAULT 0,
    overrun_count INTEGER NOT NULL DEFAULT 0,
    total_original_cost_cr NUMERIC(14, 2) NOT NULL DEFAULT 0.0,
    total_expenditure_cr NUMERIC(14, 2) NOT NULL DEFAULT 0.0,
    source_checksum VARCHAR(64) NOT NULL,
    schema_version VARCHAR(32) NOT NULL DEFAULT 'v2.1',
    status VARCHAR(32) NOT NULL DEFAULT 'VALIDATED' CHECK (status IN ('PENDING', 'VALIDATED', 'FAILED', 'ARCHIVED')),
    is_baseline BOOLEAN NOT NULL DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_snapshots_date ON data_snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_snapshots_status ON data_snapshots(status);

-- 3. RAW DATA PRESERVATION LAYER
CREATE TABLE IF NOT EXISTS raw_data_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id VARCHAR(64) REFERENCES data_snapshots(id) ON DELETE CASCADE,
    source_reference VARCHAR(255) NOT NULL,
    filename_or_api VARCHAR(255) NOT NULL,
    retrieval_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    checksum VARCHAR(64) NOT NULL,
    raw_record_count INTEGER NOT NULL,
    file_size_bytes BIGINT NOT NULL DEFAULT 0,
    raw_payload_preview TEXT,
    processing_status VARCHAR(32) NOT NULL DEFAULT 'COMPLETED' CHECK (processing_status IN ('RAW_RECEIVED', 'VALIDATED', 'COMPLETED', 'FAILED')),
    quarantined_record_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_raw_snapshots_snap_id ON raw_data_snapshots(snapshot_id);

-- 4. PROJECT HISTORICAL VERSIONS (1:N snapshots per logical project)
CREATE TABLE IF NOT EXISTS project_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_code INTEGER NOT NULL,
    snapshot_id VARCHAR(64) REFERENCES data_snapshots(id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,
    project_name VARCHAR(500) NOT NULL,
    sector VARCHAR(120) NOT NULL,
    ministry VARCHAR(255) NOT NULL,
    state VARCHAR(120),
    original_cost NUMERIC(14, 2) NOT NULL,
    revised_cost NUMERIC(14, 2) NOT NULL DEFAULT 0.0,
    expenditure NUMERIC(14, 2) NOT NULL DEFAULT 0.0,
    original_completion_date DATE,
    revised_completion_date DATE,
    schedule_delay_days NUMERIC(10, 1),
    is_delayed BOOLEAN NOT NULL DEFAULT FALSE,
    cost_overrun_pct NUMERIC(8, 2),
    data_quality_flags VARCHAR(255) NOT NULL DEFAULT 'CLEAN',
    status_in_snapshot VARCHAR(32) NOT NULL DEFAULT 'ONGOING' CHECK (status_in_snapshot IN ('ONGOING', 'COMPLETED', 'NEW', 'STALLED')),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (project_code, snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_proj_ver_code ON project_versions(project_code);
CREATE INDEX IF NOT EXISTS idx_proj_ver_snap ON project_versions(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_proj_ver_date ON project_versions(snapshot_date);

-- 5. PROJECT CHANGE EVENTS (Snapshot-to-Snapshot Deltas)
CREATE TABLE IF NOT EXISTS project_change_events (
    id BIGSERIAL PRIMARY KEY,
    project_code INTEGER NOT NULL,
    from_snapshot_id VARCHAR(64) REFERENCES data_snapshots(id),
    to_snapshot_id VARCHAR(64) REFERENCES data_snapshots(id),
    change_type VARCHAR(32) NOT NULL CHECK (change_type IN ('NEW', 'UPDATED', 'UNCHANGED', 'COMPLETED', 'REMOVED_FROM_ACTIVE_SNAPSHOT')),
    cost_change_cr NUMERIC(14, 2) NOT NULL DEFAULT 0.0,
    revised_cost_change_cr NUMERIC(14, 2) NOT NULL DEFAULT 0.0,
    expenditure_change_cr NUMERIC(14, 2) NOT NULL DEFAULT 0.0,
    schedule_change_days NUMERIC(10, 1) NOT NULL DEFAULT 0.0,
    status_change VARCHAR(64),
    change_summary TEXT,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_change_events_code ON project_change_events(project_code);
CREATE INDEX IF NOT EXISTS idx_change_events_type ON project_change_events(change_type);
CREATE INDEX IF NOT EXISTS idx_change_events_snapshots ON project_change_events(from_snapshot_id, to_snapshot_id);

-- 6. TEMPORAL PREDICTION RISK HISTORY
CREATE TABLE IF NOT EXISTS prediction_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_code INTEGER NOT NULL,
    snapshot_id VARCHAR(64) REFERENCES data_snapshots(id),
    prediction_date DATE NOT NULL DEFAULT CURRENT_DATE,
    risk_probability NUMERIC(5, 4) NOT NULL CHECK (risk_probability BETWEEN 0 AND 1),
    risk_tier VARCHAR(32) NOT NULL CHECK (risk_tier IN ('Low Delay Risk', 'Medium Delay Risk', 'High Delay Risk', 'Critical Delay Risk')),
    expected_delay_days INTEGER NOT NULL CHECK (expected_delay_days >= 0),
    expected_delay_months NUMERIC(6, 1) NOT NULL CHECK (expected_delay_months >= 0),
    previous_risk_tier VARCHAR(32),
    risk_tier_change VARCHAR(32) DEFAULT 'UNCHANGED',
    model_version VARCHAR(32) NOT NULL DEFAULT 'v2.1.0',
    escalation_alert_created BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pred_hist_code ON prediction_history(project_code);
CREATE INDEX IF NOT EXISTS idx_pred_hist_snap ON prediction_history(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_pred_hist_date ON prediction_history(prediction_date);

-- 7. INGESTION RUNS & DATA QUALITY AUDIT RUNS
CREATE TABLE IF NOT EXISTS ingestion_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id VARCHAR(64) REFERENCES data_snapshots(id),
    source_name VARCHAR(255) NOT NULL,
    trigger_type VARCHAR(32) NOT NULL DEFAULT 'MANUAL' CHECK (trigger_type IN ('MANUAL', 'SCHEDULED', 'API_TRIGGER')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    status VARCHAR(32) NOT NULL DEFAULT 'IN_PROGRESS' CHECK (status IN ('IN_PROGRESS', 'SUCCESS', 'FAILED', 'PARTIAL')),
    total_records INTEGER NOT NULL DEFAULT 0,
    new_records INTEGER NOT NULL DEFAULT 0,
    updated_records INTEGER NOT NULL DEFAULT 0,
    unchanged_records INTEGER NOT NULL DEFAULT 0,
    quarantined_records INTEGER NOT NULL DEFAULT 0,
    executed_by VARCHAR(255) NOT NULL DEFAULT 'admin.infra@gov.in',
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS data_quality_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id VARCHAR(64) REFERENCES data_snapshots(id),
    check_name VARCHAR(120) NOT NULL,
    status VARCHAR(32) NOT NULL CHECK (status IN ('PASS', 'WARN', 'FAIL')),
    records_checked INTEGER NOT NULL DEFAULT 0,
    records_failed INTEGER NOT NULL DEFAULT 0,
    failure_rate_pct NUMERIC(5, 2) NOT NULL DEFAULT 0.0,
    details JSONB,
    run_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 8. ROW LEVEL SECURITY POLICIES FOR NEW TABLES
ALTER TABLE data_source_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_data_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_change_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE prediction_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingestion_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_quality_runs ENABLE ROW LEVEL SECURITY;

-- Public/All Read Policies
CREATE POLICY "Allow read on data_source_registry" ON data_source_registry FOR SELECT USING (true);
CREATE POLICY "Allow read on data_snapshots" ON data_snapshots FOR SELECT USING (true);
CREATE POLICY "Allow read on project_versions" ON project_versions FOR SELECT USING (true);
CREATE POLICY "Allow read on project_change_events" ON project_change_events FOR SELECT USING (true);
CREATE POLICY "Allow read on prediction_history" ON prediction_history FOR SELECT USING (true);
CREATE POLICY "Allow read on ingestion_runs" ON ingestion_runs FOR SELECT USING (true);
CREATE POLICY "Allow read on data_quality_runs" ON data_quality_runs FOR SELECT USING (true);

-- Authenticated Officer/Admin Write Policies
CREATE POLICY "Allow admin write on data_snapshots" ON data_snapshots FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY "Allow admin write on project_versions" ON project_versions FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY "Allow admin write on project_change_events" ON project_change_events FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY "Allow admin write on raw_data_snapshots" ON raw_data_snapshots FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY "Allow admin write on ingestion_runs" ON ingestion_runs FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY "Allow admin write on data_quality_runs" ON data_quality_runs FOR ALL TO authenticated USING (true) WITH CHECK (true);
