# Production Deployment Guide: Supabase & Vercel
**Project:** PM-OCMS Infrastructure Delay & Cost Overrun Intelligence Platform (SIH26017)

---

## 1. Supabase PostgreSQL Provisioning

1. **Create Supabase Project**:
   - Log in to [supabase.com](https://supabase.com) and create a new organization / project.
   - Note the Project Reference ID and database password.

2. **Apply Database Migrations**:
   - Using the Supabase SQL Editor or the Supabase CLI, apply the initial schema migration:
     ```bash
     supabase db push
     # Or run the contents of supabase/migrations/20260911000001_initial_schema.sql in SQL Editor
     ```

3. **Obtain Connection Credentials**:
   - Navigate to **Project Settings** -> **Database**.
   - Copy the direct connection string (`postgresql://postgres:[PASSWORD]@db.[REF].supabase.co:5432/postgres`) or connection pooler URI (`port 6543`).
   - Copy the `SUPABASE_URL` and `SUPABASE_JWT_SECRET` from **API** settings.

4. **Populate Master CSV Data**:
   - Run the idempotent ingestion script pointing to the Supabase connection string:
     ```bash
     export DATABASE_URL="postgresql://postgres:[PASSWORD]@db.[REF].supabase.co:5432/postgres"
     python scripts/import_data.py
     ```

---

## 2. Vercel Deployment

1. **Connect Repository**:
   - Push this codebase to GitHub / GitLab.
   - Import the project into the [Vercel Dashboard](https://vercel.com).

2. **Configure Environment Variables in Vercel**:
   - Go to **Project Settings** -> **Environment Variables**:
     - `DATABASE_URL`: Supabase connection pooler URI.
     - `SUPABASE_URL`: `https://[REF].supabase.co`
     - `SUPABASE_JWT_SECRET`: Supabase JWT secret.
     - `ALLOWED_ORIGINS`: `https://[YOUR-VERCEL-DOMAIN].vercel.app,http://localhost:3000`
     - `ENVIRONMENT`: `production`

3. **Deploy & Build Configuration**:
   - `vercel.json` automatically configures:
     - Static assets from `frontend/`
     - Serverless Python FastAPI functions from `backend/server.py`
   - Click **Deploy**.

---

## 3. Post-Deployment Verification Checklist

Verify deployment health using curl or browser:

```bash
# 1. Check liveness
curl -i https://[YOUR-VERCEL-DOMAIN].vercel.app/health

# 2. Check readiness (Database + Models)
curl -i https://[YOUR-VERCEL-DOMAIN].vercel.app/ready

# 3. Check OpenAPI documentation
curl -i https://[YOUR-VERCEL-DOMAIN].vercel.app/docs

# 4. Check live project telemetry
curl -i https://[YOUR-VERCEL-DOMAIN].vercel.app/api/v1/summary
```
All endpoints should return HTTP 200 with standard JSON responses and security headers (`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy`).
