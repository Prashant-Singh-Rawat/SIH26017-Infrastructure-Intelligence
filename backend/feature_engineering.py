import os
import json
import sqlite3
import pandas as pd
import numpy as np
from backend.database import get_db_connection

PROCESSED_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "processed")

def assign_cost_bucket(cost):
    if cost < 100:
        return "Tier 1 (< ₹100 Cr)"
    elif cost < 500:
        return "Tier 2 (₹100 - ₹500 Cr)"
    elif cost < 2000:
        return "Tier 3 (₹500 - ₹2,000 Cr)"
    elif cost < 10000:
        return "Tier 4 (₹2,000 - ₹10,000 Cr)"
    else:
        return "Tier 5 (> ₹10,000 Cr Mega)"

def run_feature_engineering():
    cleaned_path = os.path.join(PROCESSED_DIR, "projects_cleaned.csv")
    df = pd.read_csv(cleaned_path)
    
    df["original_end_date"] = pd.to_datetime(df["original_end_date"])
    df["revised_end_date"] = pd.to_datetime(df["revised_end_date"])
    
    # 1. Targets
    delay_days = []
    is_delayed = []
    for _, row in df.iterrows():
        if pd.notna(row["original_end_date"]) and pd.notna(row["revised_end_date"]):
            diff = (row["revised_end_date"] - row["original_end_date"]).days
            delay_days.append(diff)
            is_delayed.append(1 if diff > 0 else 0)
        else:
            delay_days.append(np.nan)
            is_delayed.append(0)
            
    df["schedule_delay_days"] = delay_days
    df["is_delayed"] = is_delayed
    df["schedule_delay_days_clipped"] = df["schedule_delay_days"].clip(lower=-365, upper=3650)
    
    # Cost overrun %
    cost_overrun_pct = []
    has_cost_overrun = []
    for _, row in df.iterrows():
        if row["revised_cost_is_set"] == 1 and row["original_cost_cr"] > 0:
            overrun = (row["revised_cost_cr"] - row["original_cost_cr"]) / row["original_cost_cr"] * 100
            cost_overrun_pct.append(overrun)
            has_cost_overrun.append(1 if overrun > 0 else 0)
        else:
            cost_overrun_pct.append(np.nan)
            has_cost_overrun.append(0)
            
    df["cost_overrun_pct"] = cost_overrun_pct
    df["cost_overrun_pct_clipped"] = df["cost_overrun_pct"].clip(lower=-50, upper=300)
    df["has_cost_overrun"] = has_cost_overrun
    
    # Expenditure ratio
    df["expenditure_ratio"] = np.where(
        df["original_cost_cr"] > 0,
        (df["expenditure_cr"] / df["original_cost_cr"]).clip(0, 5),
        0.0
    )
    
    # 2. Inception / Pre-Construction Safe Features (Strict Zero Leakage)
    df["cost_scale_bucket"] = df["original_cost_cr"].apply(assign_cost_bucket)
    df["log_original_cost"] = np.log1p(df["original_cost_cr"])
    
    df["original_end_year"] = df["original_end_date"].dt.year.fillna(2026).astype(int)
    df["original_end_month"] = df["original_end_date"].dt.month.fillna(6).astype(int)
    df["original_end_quarter"] = df["original_end_date"].dt.quarter.fillna(2).astype(int)
    
    # Historical baseline rates
    valid_revised = df[df["revised_date_is_missing"] == 0]
    sector_stats = valid_revised.groupby("sector_name")["is_delayed"].agg(["count", "mean"]).reset_index()
    sector_stats.columns = ["sector_name", "sector_valid_projects", "sector_delay_rate"]
    df = df.merge(sector_stats, on="sector_name", how="left")
    df["sector_delay_rate"] = df["sector_delay_rate"].fillna(df["is_delayed"].mean())
    
    ministry_stats = valid_revised.groupby("line_ministry")["is_delayed"].agg(["count", "mean"]).reset_index()
    ministry_stats.columns = ["line_ministry", "ministry_valid_projects", "ministry_delay_rate"]
    df = df.merge(ministry_stats, on="line_ministry", how="left")
    df["ministry_delay_rate"] = df["ministry_delay_rate"].fillna(df["is_delayed"].mean())
    
    # Format date strings for SQLite
    df_db = df.copy()
    df_db["original_end_date"] = df_db["original_end_date"].dt.strftime("%Y-%m-%d")
    df_db["revised_end_date"] = df_db["revised_end_date"].dt.strftime("%Y-%m-%d")
    
    # Save CSV
    output_path = os.path.join(PROCESSED_DIR, "project_features.csv")
    df.to_csv(output_path, index=False)
    print(f"Features saved to CSV ({len(df)} rows).")
    
    # 3. Write projects to SQLite
    conn = get_db_connection()
    # Select columns matching SQLite schema
    cols_for_db = [
        "project_code", "sr_no", "sector_name", "line_ministry", "project_name",
        "original_cost_cr", "revised_cost_cr", "expenditure_cr",
        "original_end_date", "revised_end_date",
        "original_end_year", "original_end_quarter",
        "cost_scale_bucket", "log_original_cost", "expenditure_ratio",
        "is_delayed", "schedule_delay_days", "schedule_delay_days_clipped",
        "has_cost_overrun", "cost_overrun_pct",
        "revised_cost_is_set", "revised_date_is_missing",
        "data_quality_flags", "sector_delay_rate", "ministry_delay_rate"
    ]
    df_db[cols_for_db].to_sql("projects", conn, if_exists="replace", index=False)
    
    # 4. Generate & Save [DEMO/SIMULATION] Land & GIS Layer
    sim_df = generate_simulation_layer(df)
    sim_df.to_sql("simulated_land_gis", conn, if_exists="replace", index=False)
    
    # 5. Generate Project Alerts
    generate_project_alerts(df, sim_df, conn)
    
    conn.close()
    print("Feature engineering and database sync completed successfully.")

def generate_simulation_layer(df):
    """
    Explicitly labeled [DEMO/SIMULATION] layer for SIH Land Acquisition, R&R, and Map Coordinates.
    Does NOT falsify real government data.
    """
    np.random.seed(42)
    state_coords = {
        "Maharashtra": (19.7515, 75.7139),
        "Uttar Pradesh": (26.8467, 80.9462),
        "Andhra Pradesh": (15.9129, 79.7400),
        "Bihar": (25.0961, 85.3131),
        "Madhya Pradesh": (22.9734, 78.6569),
        "Karnataka": (15.3173, 75.7139),
        "Gujarat": (22.2587, 71.1924),
        "Odisha": (20.9517, 85.0985),
        "Jharkhand": (23.6102, 85.2799),
        "Telangana": (18.1124, 79.0193),
        "Assam": (26.2006, 92.9376),
        "West Bengal": (22.9868, 87.8550),
        "Rajasthan": (27.0238, 74.2179),
        "Chhattisgarh": (21.2787, 81.8661),
        "Tamil Nadu": (11.1271, 78.6569),
        "Punjab": (31.1471, 75.3412),
        "Uttarakhand": (30.0668, 79.0193),
        "Jammu & Kashmir": (33.7782, 76.5762),
        "Haryana": (29.0588, 76.0856),
        "Kerala": (10.8505, 76.2711),
        "Delhi": (28.7041, 77.1025)
    }
    states_list = list(state_coords.keys())
    
    sim_records = []
    for _, row in df.iterrows():
        pname = row["project_name"].lower()
        matched_state = "Delhi"
        for st in states_list:
            if st.lower() in pname:
                matched_state = st
                break
        else:
            matched_state = states_list[row["project_code"] % len(states_list)]
            
        base_lat, base_lng = state_coords.get(matched_state, (20.5937, 78.9629))
        jitter_lat = base_lat + ((row["project_code"] % 100) - 50) * 0.02
        jitter_lng = base_lng + (((row["project_code"] // 100) % 100) - 50) * 0.02
        
        cost = max(row["original_cost_cr"], 10.0)
        acres_needed = round(cost * 0.15 + (row["project_code"] % 120), 1)
        acquired_pct = round(min(100.0, max(15.0, (row["expenditure_ratio"] * 85.0) + (row["project_code"] % 25))), 1)
        disputes = (row["project_code"] % 4) if row["is_delayed"] else (row["project_code"] % 2)
        
        status_opts = ["Clearance Obtained", "In Progress", "Critical Environmental Delay", "Pending Public Hearing"]
        clearance_status = status_opts[row["project_code"] % len(status_opts)]
        
        sim_records.append({
            "project_code": int(row["project_code"]),
            "source_tag": "[DEMO/SIMULATION]",
            "inferred_state": matched_state,
            "latitude": round(jitter_lat, 4),
            "longitude": round(jitter_lng, 4),
            "land_required_acres": acres_needed,
            "land_acquired_pct": acquired_pct,
            "land_clearance_status": clearance_status,
            "active_legal_disputes": disputes,
            "affected_families_count": int(acres_needed * 1.8),
            "rehabilitation_package_cr": round(acres_needed * 0.08, 2)
        })
        
    sim_df = pd.DataFrame(sim_records)
    sim_path = os.path.join(PROCESSED_DIR, "simulated_land_gis.csv")
    sim_df.to_csv(sim_path, index=False)
    return sim_df

def generate_project_alerts(df, sim_df, conn):
    """
    Populates project_alerts table with institutional escalation triggers
    """
    cursor = conn.cursor()
    cursor.execute("DELETE FROM project_alerts;")
    
    alerts = []
    for _, row in df.iterrows():
        pcode = int(row["project_code"])
        pname = row["project_name"]
        delay = row["schedule_delay_days"]
        cost = row["original_cost_cr"]
        exp = row["expenditure_cr"]
        flags = str(row["data_quality_flags"])
        
        # 1. Critical Delay Alert (> 730 days / 2 years)
        if pd.notna(delay) and delay > 730:
            alerts.append((
                pcode,
                "CRITICAL",
                "SCHEDULE_SLIPPAGE",
                f"Severe Timeline Slippage ({int(delay)} Days past deadline)",
                f"Project has accumulated {int(delay)} days of schedule delay. Commissioning targets breached.",
                "Cabinet Secretariat / PMG High-Level Committee"
            ))
        elif pd.notna(delay) and delay > 365:
            alerts.append((
                pcode,
                "HIGH",
                "SCHEDULE_SLIPPAGE",
                f"Prolonged Schedule Delay ({int(delay)} Days)",
                f"Project delay exceeds 12 months. Requires nodal agency intervention.",
                "Ministry Nodal Officer / Secretary"
            ))
            
        # 2. Capital Exhaustion Alert (Expenditure > Original Cost)
        if exp > cost and cost > 0:
            overspent = exp - cost
            alerts.append((
                pcode,
                "CRITICAL" if overspent > 500 else "HIGH",
                "EXPENDITURE_ANOMALY",
                f"Sanctioned Capital Exhausted (+₹{overspent:,.1f} Cr over budget)",
                f"Cumulative disbursements (₹{exp:,.1f} Cr) have exceeded 100% of sanctioned outlay (₹{cost:,.1f} Cr). Revised sanction required.",
                "Ministry of Finance (Public Investment Board)"
            ))
            
        # 3. Sentinel Alert (Pending Revision)
        if "NOT_YET_REVISED_COST" in flags and pd.notna(delay) and delay > 365:
            alerts.append((
                pcode,
                "MEDIUM",
                "GOVERNANCE_LAG",
                "Unrevised Budget on Slipped Timeline",
                "Project is significantly delayed but revised estimates have not been formally notified to MoSPI.",
                "Line Ministry Administrative Division"
            ))
            
    cursor.executemany("""
    INSERT INTO project_alerts (
        project_code, alert_severity, alert_category, alert_title, alert_description, escalation_authority
    ) VALUES (?, ?, ?, ?, ?, ?);
    """, alerts)
    conn.commit()
    print(f"Generated {len(alerts)} institutional alerts in SQLite.")

if __name__ == "__main__":
    run_feature_engineering()
