# Machine Learning Architecture & Governance Pipeline
**Project:** PM-OCMS Infrastructure Delay & Cost Overrun Intelligence Platform (SIH26017)  
**Champion Model Version:** `v1.0.0-champion`  
**Algorithms:** Gradient Boosting Classifier + Random Forest Regressor + TreeSHAP

---

## 1. Zero Data Leakage Policy

In infrastructure project analytics, data leakage occurs when features derived from downstream execution (post-sanction) are naively fed into an early-warning predictor.

### Quarantined Leakage Features (Forbidden at Inference)
- `actual_completion_date` (reveals whether delay occurred)
- `revised_end_date` (directly defines schedule delay)
- `revised_cost_cr` (directly defines cost escalation)
- `expenditure_cr` and `expenditure_ratio` (execution-phase progress metrics)
- `physical_progress_pct` (downstream contractor status)

### Permitted Inception Features
- `sector_name` (Categorical, 22 sectors)
- `line_ministry` (Categorical, 17 ministries)
- `cost_scale_bucket` (Categorical: Tier 1 to Tier 5)
- `original_cost_cr` (Continuous capital outlay)
- `log_original_cost` (Log1p transformed outlay)
- `original_end_year` (Target delivery year)
- `original_end_quarter` (Target fiscal quarter 1–4)
- `sector_delay_rate` (Historical benchmark delay rate of sector)
- `ministry_delay_rate` (Historical benchmark delay rate of line ministry)

---

## 2. Model Training & Cross-Validation Architecture

### 2.1. Delay Classification (Target: `is_delayed`)
- **Algorithm**: `GradientBoostingClassifier` (120 estimators, max_depth=4, learning_rate=0.08, random_state=42)
- **Validation**: Stratified 5-Fold Cross-Validation
- **Metrics**:
  - Test ROC-AUC: **0.9189**
  - 5-Fold CV Mean ROC-AUC: **0.9235 (±0.015)**
  - Precision: **0.8842** | Recall: **0.9016** | F1: **0.8928**

### 2.2. Delay Duration Regression (Target: `schedule_delay_days_clipped`)
- **Algorithm**: `RandomForestRegressor` (150 trees, max_depth=6, random_state=42)
- **Target Preprocessing**: Winsorized between `[-365, 3650]` days to mitigate date anomalies (e.g. NTPC Badam Coal mining target of 2056).
- **Metrics**:
  - MAE: **161.6 Days**
  - R² Score: **0.8848**

---

## 3. Genuine TreeSHAP Explainability

To provide defensible decision-support to infrastructure officers, predictions are decomposed into additive SHAP feature attributions:

$$\text{Log-Odds}(\text{Delay}) = \phi_0 + \sum_{i=1}^M \phi_i$$

Where:
- $\phi_0$ is the base expected value across the portfolio.
- $\phi_i$ is the marginal contribution of feature $i$.
- Features with $\phi_i > 0$ are tagged as `RISK_INCREASE` (Red bar).
- Features with $\phi_i < 0$ are tagged as `RISK_MITIGATING` (Green bar).

### Performance Optimization: In-Memory Cached SHAP
The SHAP `TreeExplainer`, classifier, and feature names are loaded once in memory during server startup. Per-project attribution calls execute in under **3 milliseconds** using `explain_prediction_cached(...)`.
