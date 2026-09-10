# Supabase Row-Level Security (RLS) Policy Specification
**Project:** PM-OCMS Infrastructure Delay & Cost Overrun Intelligence Platform (SIH26017)  
**Database:** Supabase PostgreSQL  
**Philosophy:** Principle of Least Privilege / Deny-by-Default

---

## 1. Overview & Security Architecture

In production, all exposed database tables have PostgreSQL Row-Level Security (`ENABLE ROW LEVEL SECURITY`) activated. This ensures that even if client-side code directly queries Supabase via the `SUPABASE_ANON_KEY`, data access is restricted according to authenticated JWT role claims (`auth.uid()` and `user_roles`).

```
                ┌─────────────────────────────────────────────────┐
                │          Inbound Database Request (Postgres)    │
                └────────────────────────┬────────────────────────┘
                                         │
                                         ▼
                ┌─────────────────────────────────────────────────┐
                │        Is Row Level Security (RLS) Enabled?     │
                │        (Enforced on all sensitive tables)       │
                └────────────────────────┬────────────────────────┘
                                         │
                         ┌───────────────┴───────────────┐
                         ▼                               ▼
                 [NO AUTH / VIEWER]             [AUTHENTICATED JWT]
                         │                               │
                         ▼                               ▼
               ┌───────────────────┐           ┌───────────────────┐
               │ Public READ-ONLY  │           │ Role Claim Check  │
               │ (Projects, Cards) │           │ (ADMIN, OFFICER,  │
               └───────────────────┘           │  ANALYST)         │
                         │                     └─────────┬─────────┘
                         ▼                               │
               ┌───────────────────┐                     ▼
               │ Disallowed Writes │           ┌───────────────────┐
               │ (DENIED 403)      │           │ Conditional WRITE │
               └───────────────────┘           │ (RLS Permitted)   │
                                               └───────────────────┘
```

---

## 2. Table-by-Table RLS Matrix

| Table Name | RLS Status | SELECT Policy | INSERT Policy | UPDATE Policy | DELETE Policy | Required Role for Mutations |
| :--- | :---: | :--- | :--- | :--- | :--- | :--- |
| **`projects`** | **ENABLED** | `USING (true)` (Public read) | `ADMIN` only | `ADMIN` only | `ADMIN` only | `ADMIN` |
| **`project_snapshots`** | **ENABLED** | `USING (true)` (Public read) | `ADMIN` only | `ADMIN` only | `ADMIN` only | `ADMIN` |
| **`simulation_records`**| **ENABLED** | `USING (true)` (Public read) | `ADMIN` only | `ADMIN` only | `ADMIN` only | `ADMIN` |
| **`sector_benchmarks`** | **ENABLED** | `USING (true)` (Public read) | `ADMIN` only | `ADMIN` only | `ADMIN` only | `ADMIN` |
| **`state_benchmarks`** | **ENABLED** | `USING (true)` (Public read) | `ADMIN` only | `ADMIN` only | `ADMIN` only | `ADMIN` |
| **`progress_brackets`** | **ENABLED** | `USING (true)` (Public read) | `ADMIN` only | `ADMIN` only | `ADMIN` only | `ADMIN` |
| **`alerts`** / **`project_alerts`** | **ENABLED** | `USING (true)` (Public read) | `OFFICER`, `ADMIN` | `OFFICER`, `ADMIN` | `ADMIN` only | `OFFICER`, `ADMIN` |
| **`project_predictions`**| **ENABLED** | `USING (true)` (Public read) | `ANALYST`, `OFFICER`, `ADMIN` | `ADMIN` only | `ADMIN` only | `ANALYST`, `OFFICER`, `ADMIN` |
| **`risk_factors`** | **ENABLED** | `USING (true)` (Public read) | `ANALYST`, `OFFICER`, `ADMIN` | `ADMIN` only | `ADMIN` only | `ANALYST`, `OFFICER`, `ADMIN` |
| **`recommendations`** | **ENABLED** | `USING (true)` (Public read) | `ANALYST`, `OFFICER`, `ADMIN` | `ADMIN` only | `ADMIN` only | `ANALYST`, `OFFICER`, `ADMIN` |
| **`policy_simulations`**| **ENABLED** | Owner / `ANALYST` / `ADMIN` | `ANALYST`, `OFFICER`, `ADMIN` | Owner / `ADMIN` | `ADMIN` only | `ANALYST`, `ADMIN` |
| **`audit_logs`** | **ENABLED** | `ADMIN` only (`auth.uid()`) | Backend trigger / Service Role | **DENIED** (Immutable) | **DENIED** (Immutable) | `ADMIN` (Read-only); System (Insert) |
| **`data_imports`** | **ENABLED** | `ADMIN` only | `ADMIN` only | `ADMIN` only | `ADMIN` only | `ADMIN` |
| **`data_import_errors`**| **ENABLED** | `ADMIN` only | `ADMIN` only | `ADMIN` only | `ADMIN` only | `ADMIN` |
| **`users`** | **ENABLED** | Self (`auth.uid() = id`) / `ADMIN` | `ADMIN` only | Self / `ADMIN` | `ADMIN` only | `ADMIN` |
| **`roles`** | **ENABLED** | Authenticated read | `ADMIN` only | `ADMIN` only | `ADMIN` only | `ADMIN` |
| **`user_roles`** | **ENABLED** | `ADMIN` only | `ADMIN` only | `ADMIN` only | `ADMIN` only | `ADMIN` |
| **`model_versions`** | **ENABLED** | `USING (true)` (Public read) | `ADMIN` only | `ADMIN` only | `ADMIN` only | `ADMIN` |

---

## 3. SQL Policy Definitions (Excerpt from Migration)

```sql
-- 1. Enable RLS across exposed tables
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE simulation_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_predictions ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_imports ENABLE ROW LEVEL SECURITY;

-- 2. Public Read Policies
CREATE POLICY "Allow public read on projects"
    ON projects FOR SELECT
    USING (true);

CREATE POLICY "Allow public read on simulation_records"
    ON simulation_records FOR SELECT
    USING (true);

CREATE POLICY "Allow read on alerts"
    ON alerts FOR SELECT
    USING (true);

-- 3. Audit logs restricted exclusively to ADMIN
CREATE POLICY "Admins read audit logs"
    ON audit_logs FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM user_roles ur
            JOIN roles r ON ur.role_id = r.id
            WHERE ur.user_id = auth.uid() AND r.name = 'ADMIN'
        )
    );

-- 4. Alert updates restricted to OFFICER and ADMIN
CREATE POLICY "Officers and Admins update alerts"
    ON alerts FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM user_roles ur
            JOIN roles r ON ur.role_id = r.id
            WHERE ur.user_id = auth.uid() AND r.name IN ('OFFICER', 'ADMIN')
        )
    );

-- 5. Data imports managed exclusively by ADMIN
CREATE POLICY "Admins manage data imports"
    ON data_imports FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM user_roles ur
            JOIN roles r ON ur.role_id = r.id
            WHERE ur.user_id = auth.uid() AND r.name = 'ADMIN'
        )
    );
```

---

## 4. Verification & Testing

RLS defenses are verified through automated integration tests:
1. **Anonymous Mutation Block**: Unauthenticated clients attempting to update alert status or access `/api/v1/audit-logs` receive `HTTP 401 Unauthorized`.
2. **Privilege Escalation Block**: `VIEWER` and `ANALYST` tokens attempting to acknowledge alerts or read audit logs receive `HTTP 403 Forbidden`.
3. **Immutability of Audit Logs**: Audit log records have zero `UPDATE` or `DELETE` policies, guaranteeing an append-only ledger.
