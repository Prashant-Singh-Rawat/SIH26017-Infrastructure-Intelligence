-- ============================================================================
-- PM-OCMS Infrastructure Delay & Cost Overrun Intelligence Platform (SIH26017)
-- Production PostgreSQL Database Migration (Supabase Compatible)
-- Migration ID: 20260911000001_initial_schema.sql
-- ============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- 1. SECURITY, USERS & ROLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(32) UNIQUE NOT NULL,
    description TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO roles (name, description) VALUES
    ('ADMIN', 'Full system governance, audit access, import management, and model rollouts'),
    ('OFFICER', 'Nodal governance officer: project audits, alert acknowledgements, risk reviews'),
    ('ANALYST', 'Planning analyst: risk evaluation, ML predictions, policy simulations'),
    ('VIEWER', 'Read-only access to executive dashboards, benchmarks, and project registries')
ON CONFLICT (name) DO NOTHING;

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    department VARCHAR(255),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, role_id)
);

-- Seed an administrative user for system orchestration
INSERT INTO users (id, email, full_name, department, is_active) VALUES
    ('00000000-0000-0000-0000-000000000001', 'admin.infra@gov.in', 'Director General (Infrastructure Intelligence)', 'IPMD, MoSPI', TRUE),
    ('00000000-0000-0000-0000-000000000002', 'officer.railways@gov.in', 'Executive Director (Works)', 'Ministry of Railways', TRUE),
    ('00000000-0000-0000-0000-000000000003', 'analyst.gatishakti@gov.in', 'Lead Infrastructure Economist', 'PM GatiShakti Nodal Unit', TRUE),
    ('00000000-0000-0000-0000-000000000004', 'viewer.public@gov.in', 'Public Governance Auditor', 'Audit & Transparency Division', TRUE)
ON CONFLICT (id) DO NOTHING;

INSERT INTO user_roles (user_id, role_id) VALUES
    ('00000000-0000-0000-0000-000000000001', 1), -- ADMIN
    ('00000000-0000-0000-0000-000000000002', 3), -- OFFICER
    ('00000000-0000-0000-0000-000000000003', 2), -- ANALYST
    ('00000000-0000-0000-0000-000000000004', 4)  -- VIEWER
ON CONFLICT (user_id, role_id) DO NOTHING;

-- ============================================================================
-- 2. PROJECTS & DATA TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_code INTEGER UNIQUE NOT NULL,
    sr_no INTEGER,
    project_name VARCHAR(500) NOT NULL,
    sector VARCHAR(120) NOT NULL,
    ministry VARCHAR(255) NOT NULL,
    state VARCHAR(120),
    original_cost NUMERIC(14, 2) NOT NULL CHECK (original_cost >= 0),
    revised_cost NUMERIC(14, 2) NOT NULL DEFAULT 0.0 CHECK (revised_cost >= 0),
    expenditure NUMERIC(14, 2) NOT NULL DEFAULT 0.0 CHECK (expenditure >= 0),
    original_completion_date DATE,
    revised_completion_date DATE,
    original_end_year INTEGER,
    original_end_quarter INTEGER,
    cost_scale_bucket VARCHAR(64),
    log_original_cost NUMERIC(8, 4),
    expenditure_ratio NUMERIC(6, 3),
    is_delayed BOOLEAN NOT NULL DEFAULT FALSE,
    schedule_delay_days NUMERIC(10, 1),
    schedule_delay_days_clipped NUMERIC(10, 1),
    has_cost_overrun BOOLEAN NOT NULL DEFAULT FALSE,
    cost_overrun_pct NUMERIC(8, 2),
    revised_cost_is_set BOOLEAN NOT NULL DEFAULT FALSE,
    revised_date_is_missing BOOLEAN NOT NULL DEFAULT FALSE,
    data_quality_flags VARCHAR(255) NOT NULL DEFAULT 'CLEAN',
    sector_delay_rate NUMERIC(6, 4),
    ministry_delay_rate NUMERIC(6, 4),
    data_provenance VARCHAR(32) NOT NULL DEFAULT 'SOURCE' CHECK (data_provenance IN ('SOURCE', 'DERIVED', 'SIMULATION')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_projects_code ON projects(project_code);
CREATE INDEX IF NOT EXISTS idx_projects_sector ON projects(sector);
CREATE INDEX IF NOT EXISTS idx_projects_ministry ON projects(ministry);
CREATE INDEX IF NOT EXISTS idx_projects_state ON projects(state);
CREATE INDEX IF NOT EXISTS idx_projects_delayed ON projects(is_delayed);
CREATE INDEX IF NOT EXISTS idx_projects_cost ON projects(original_cost);
CREATE INDEX IF NOT EXISTS idx_projects_orig_date ON projects(original_completion_date);
CREATE INDEX IF NOT EXISTS idx_projects_rev_date ON projects(revised_completion_date);

-- Project Snapshot History
CREATE TABLE IF NOT EXISTS project_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
    cost_at_snapshot NUMERIC(14, 2) NOT NULL,
    expenditure_at_snapshot NUMERIC(14, 2) NOT NULL,
    delay_days_at_snapshot NUMERIC(10, 1),
    captured_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Simulated Land Acquisition & GIS Layer (Strictly DEMO/SIMULATION)
CREATE TABLE IF NOT EXISTS simulation_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_code INTEGER UNIQUE NOT NULL,
    source_tag VARCHAR(32) NOT NULL DEFAULT '[DEMO/SIMULATION]',
    inferred_state VARCHAR(120) NOT NULL,
    latitude NUMERIC(9, 6) NOT NULL,
    longitude NUMERIC(9, 6) NOT NULL,
    land_required_acres NUMERIC(10, 2) NOT NULL CHECK (land_required_acres >= 0),
    land_acquired_pct NUMERIC(5, 2) NOT NULL CHECK (land_acquired_pct BETWEEN 0 AND 100),
    land_clearance_status VARCHAR(64) NOT NULL,
    active_legal_disputes INTEGER NOT NULL DEFAULT 0 CHECK (active_legal_disputes >= 0),
    affected_families_count INTEGER NOT NULL DEFAULT 0 CHECK (affected_families_count >= 0),
    rehabilitation_package_cr NUMERIC(12, 2) NOT NULL DEFAULT 0.0 CHECK (rehabilitation_package_cr >= 0),
    provenance_note TEXT NOT NULL DEFAULT 'Simulated parameters for spatial early warning demonstration; not found in official CSV.',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sim_inferred_state ON simulation_records(inferred_state);

-- ============================================================================
-- 3. ML MODEL VERSIONING, PREDICTIONS & EXPLAINABILITY
-- ============================================================================

CREATE TABLE IF NOT EXISTS model_versions (
    id SERIAL PRIMARY KEY,
    version VARCHAR(32) UNIQUE NOT NULL,
    algorithm VARCHAR(120) NOT NULL,
    training_dataset_version VARCHAR(64) NOT NULL,
    trained_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metrics JSONB NOT NULL,
    feature_schema JSONB NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PRODUCTION' CHECK (status IN ('STAGING', 'PRODUCTION', 'ARCHIVED', 'FAILED'))
);

CREATE TABLE IF NOT EXISTS model_metrics (
    id SERIAL PRIMARY KEY,
    model_version_id INTEGER REFERENCES model_versions(id) ON DELETE CASCADE,
    metric_name VARCHAR(64) NOT NULL,
    metric_value NUMERIC(10, 4) NOT NULL,
    dataset_split VARCHAR(32) NOT NULL CHECK (dataset_split IN ('TRAIN', 'TEST', 'CV', 'HOLDOUT'))
);

CREATE TABLE IF NOT EXISTS project_predictions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_code INTEGER NOT NULL,
    model_version VARCHAR(32) NOT NULL,
    risk_probability NUMERIC(5, 4) NOT NULL CHECK (risk_probability BETWEEN 0 AND 1),
    risk_tier VARCHAR(32) NOT NULL,
    expected_delay_days INTEGER NOT NULL CHECK (expected_delay_days >= 0),
    expected_delay_months NUMERIC(6, 1) NOT NULL CHECK (expected_delay_months >= 0),
    provenance_tag VARCHAR(64) NOT NULL DEFAULT '[ZERO-LEAKAGE MODEL]',
    predicted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    prediction_status VARCHAR(32) NOT NULL DEFAULT 'COMPLETED'
);

CREATE INDEX IF NOT EXISTS idx_pred_project_code ON project_predictions(project_code);

CREATE TABLE IF NOT EXISTS risk_factors (
    id BIGSERIAL PRIMARY KEY,
    prediction_id UUID REFERENCES project_predictions(id) ON DELETE CASCADE,
    feature_name VARCHAR(120) NOT NULL,
    shap_value NUMERIC(10, 6) NOT NULL,
    impact_pct NUMERIC(6, 2) NOT NULL,
    direction VARCHAR(32) NOT NULL CHECK (direction IN ('RISK_INCREASE', 'RISK_DECREASE'))
);

CREATE TABLE IF NOT EXISTS recommendations (
    id BIGSERIAL PRIMARY KEY,
    prediction_id UUID REFERENCES project_predictions(id) ON DELETE CASCADE,
    action VARCHAR(255) NOT NULL,
    protocol TEXT NOT NULL,
    authority VARCHAR(255) NOT NULL,
    priority VARCHAR(32) NOT NULL CHECK (priority IN ('URGENT', 'HIGH', 'ROUTINE'))
);

-- ============================================================================
-- 4. ALERTS & WHAT-IF POLICY SIMULATIONS
-- ============================================================================

CREATE TABLE IF NOT EXISTS alerts (
    id SERIAL PRIMARY KEY,
    project_code INTEGER NOT NULL,
    alert_severity VARCHAR(32) NOT NULL CHECK (alert_severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    alert_category VARCHAR(120) NOT NULL,
    alert_title VARCHAR(255) NOT NULL,
    alert_description TEXT NOT NULL,
    escalation_authority VARCHAR(255) NOT NULL,
    assigned_authority VARCHAR(255) NOT NULL DEFAULT 'Project Monitoring Group (PMG)',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by UUID REFERENCES users(id),
    acknowledgement_notes TEXT,
    resolution_timestamp TIMESTAMPTZ,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'ACKNOWLEDGED', 'RESOLVED'))
);

CREATE INDEX IF NOT EXISTS idx_alerts_project ON alerts(project_code);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(alert_severity);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);

CREATE TABLE IF NOT EXISTS policy_simulations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    sector VARCHAR(120) NOT NULL,
    ministry VARCHAR(255) NOT NULL,
    original_cost NUMERIC(14, 2) NOT NULL,
    planned_year INTEGER NOT NULL,
    interventions JSONB NOT NULL,
    baseline_metrics JSONB NOT NULL,
    simulated_metrics JSONB NOT NULL,
    impact_metrics JSONB NOT NULL,
    simulated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    provenance_note TEXT NOT NULL DEFAULT 'MODEL SIMULATION — NOT AN OFFICIAL GOVERNMENT FORECAST'
);

-- ============================================================================
-- 5. BENCHMARK SUMMARY TABLES (Aggregates from Reports)
-- ============================================================================

CREATE TABLE IF NOT EXISTS sector_benchmarks (
    sr_no INTEGER,
    sector_name VARCHAR(120) PRIMARY KEY,
    project_count INTEGER NOT NULL,
    original_cost_cr NUMERIC(14, 2) NOT NULL,
    revised_cost_cr NUMERIC(14, 2) NOT NULL,
    expenditure_cr NUMERIC(14, 2) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS state_benchmarks (
    sr_no INTEGER,
    state_name VARCHAR(120) PRIMARY KEY,
    project_count INTEGER NOT NULL,
    original_cost_cr NUMERIC(14, 2) NOT NULL,
    revised_cost_cr NUMERIC(14, 2) NOT NULL,
    expenditure_cr NUMERIC(14, 2) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS progress_brackets (
    sr_no INTEGER,
    progress_bracket VARCHAR(64) PRIMARY KEY,
    project_count INTEGER NOT NULL,
    original_cost_cr NUMERIC(14, 2) NOT NULL,
    revised_cost_cr NUMERIC(14, 2) NOT NULL,
    expenditure_cr NUMERIC(14, 2) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 6. AUDITING, LOGGING & INGESTION TRACKING
-- ============================================================================

CREATE TABLE IF NOT EXISTS data_quality_audits (
    id SERIAL PRIMARY KEY,
    check_name VARCHAR(120) NOT NULL,
    status VARCHAR(32) NOT NULL,
    affected_rows INTEGER NOT NULL,
    severity VARCHAR(32) NOT NULL,
    details JSONB,
    run_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID,
    action VARCHAR(120) NOT NULL,
    resource_type VARCHAR(64) NOT NULL,
    resource_id VARCHAR(120),
    request_id VARCHAR(64),
    ip_address VARCHAR(45),
    result VARCHAR(32) NOT NULL CHECK (result IN ('SUCCESS', 'FORBIDDEN', 'ERROR', 'VALIDATION_FAILED')),
    metadata JSONB,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp);

CREATE TABLE IF NOT EXISTS data_imports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_name VARCHAR(255) NOT NULL,
    source_name VARCHAR(255) NOT NULL DEFAULT 'Projects_Report.csv',
    source_type VARCHAR(120) NOT NULL DEFAULT 'MoSPI Infrastructure Telemetry (CSV)',
    source_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ingestion_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    data_version VARCHAR(64) NOT NULL,
    row_count INTEGER NOT NULL,
    successful_rows INTEGER NOT NULL,
    failed_rows INTEGER NOT NULL,
    duplicate_rows INTEGER NOT NULL,
    validation_summary JSONB,
    imported_by UUID REFERENCES users(id),
    import_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    data_status VARCHAR(32) NOT NULL DEFAULT 'COMPLETED',
    status VARCHAR(32) NOT NULL DEFAULT 'COMPLETED' CHECK (status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED'))
);

CREATE TABLE IF NOT EXISTS data_import_errors (
    id BIGSERIAL PRIMARY KEY,
    import_id UUID REFERENCES data_imports(id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL,
    field_name VARCHAR(120),
    error_reason TEXT NOT NULL,
    raw_value TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Relational Views for Schema Specification Compliance (Phase 2)
CREATE OR REPLACE VIEW project_metrics AS SELECT * FROM project_snapshots;
CREATE OR REPLACE VIEW project_alerts AS SELECT * FROM alerts;
CREATE OR REPLACE VIEW project_recommendations AS SELECT * FROM recommendations;
CREATE OR REPLACE VIEW project_audit_logs AS SELECT * FROM audit_logs;
CREATE OR REPLACE VIEW model_predictions AS SELECT * FROM project_predictions;

-- ============================================================================
-- 7. ROW LEVEL SECURITY (RLS) POLICIES
-- ============================================================================

ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE simulation_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_predictions ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_imports ENABLE ROW LEVEL SECURITY;

-- 1. Public / Viewer Read Policies
CREATE POLICY "Allow public read on projects"
    ON projects FOR SELECT
    USING (true);

CREATE POLICY "Allow public read on simulation_records"
    ON simulation_records FOR SELECT
    USING (true);

CREATE POLICY "Allow public read on benchmarks"
    ON sector_benchmarks FOR SELECT
    USING (true);

CREATE POLICY "Allow read on alerts"
    ON alerts FOR SELECT
    USING (true);

-- 2. Audit logs restricted to ADMIN
CREATE POLICY "Admins read audit logs"
    ON audit_logs FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM user_roles ur
            JOIN roles r ON ur.role_id = r.id
            WHERE ur.user_id = auth.uid() AND r.name = 'ADMIN'
        )
    );

-- 3. Alert acknowledgement restricted to OFFICER and ADMIN
CREATE POLICY "Officers and Admins update alerts"
    ON alerts FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM user_roles ur
            JOIN roles r ON ur.role_id = r.id
            WHERE ur.user_id = auth.uid() AND r.name IN ('OFFICER', 'ADMIN')
        )
    );

-- 4. Data imports restricted to ADMIN
CREATE POLICY "Admins manage data imports"
    ON data_imports FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM user_roles ur
            JOIN roles r ON ur.role_id = r.id
            WHERE ur.user_id = auth.uid() AND r.name = 'ADMIN'
        )
    );
