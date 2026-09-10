# ML Feature Contract & Zero Data Leakage Specification
**Platform:** PM-OCMS Infrastructure Delay & Cost Overrun Intelligence Platform  
**Model Version:** `v1.0.0-champion`  
**Feature Schema Version:** `2026.09.1`  
**Standard:** Strict Temporal Separation of Pre-Sanction vs Post-Sanction Features

---

## 1. Feature Ingestion Contract

The Early Warning Model evaluates projects at **sanctioning time (Inception Phase)**. To guarantee zero data leakage, only information officially known before civil works and procurement begin is admitted into the feature vector.

### 1.1. Inception Feature Schema

| Field Name | Type | Allowed Values / Bounds | Encoding / Preprocessing | Description |
| :--- | :--- | :--- | :--- | :--- |
| `sector_name` | String | 22 MoSPI Sectors (`Railways`, `Road Transport and Highways`, `Power`, `Petroleum`, etc.) | `OneHotEncoder(handle_unknown='ignore')` | Primary infrastructure domain |
| `line_ministry` | String | Recognized central ministries (`Ministry of Railways`, `Ministry of Road Transport and Highways`, etc.) | `OneHotEncoder(handle_unknown='ignore')` | Administrative nodal ministry |
| `cost_scale_bucket` | String | `Tier 1 (< ₹100 Cr)`, `Tier 2 (₹100 - ₹500 Cr)`, `Tier 3 (₹500 - ₹2,000 Cr)`, `Tier 4 (₹2,000 - ₹10,000 Cr)`, `Tier 5 (> ₹10,000 Cr Mega)` | `OneHotEncoder(handle_unknown='ignore')` | Outlay magnitude category |
| `original_cost_cr` | Float | `> 0.0` (Crores INR) | `StandardScaler()` | Approved capital outlay sanctioned by CCEA |
| `log_original_cost` | Float | `ln(1 + original_cost_cr)` | `StandardScaler()` | Log-normalized outlay for variance stabilization |
| `original_end_year` | Integer | `2024 <= year <= 2050` | `StandardScaler()` | Sanctioned commissioning year |
| `original_end_quarter`| Integer | `1, 2, 3, 4` | `StandardScaler()` | Sanctioned commissioning fiscal quarter |
| `sector_delay_rate` | Float | `0.0 <= rate <= 1.0` | `StandardScaler()` | Empirical baseline delay rate across sector peers |
| `ministry_delay_rate`| Float | `0.0 <= rate <= 1.0` | `StandardScaler()` | Empirical baseline delay rate across ministry peers |

---

## 2. Quarantined Downstream Features (Strict Anti-Leakage List)

The following features exist in the monitoring dataset but are **strictly forbidden** from the inception prediction pipeline:

```
[STRICTLY FORBIDDEN FROM PRE-CONSTRUCTION INFERENCE]
├── revised_cost_cr             (Reveals financial overrun occurring years into execution)
├── expenditure_cr              (Reveals disbursement pace during construction)
├── expenditure_ratio           (Captures post-sanction fiscal absorption)
├── revised_end_date            (Reveals approved schedule extensions after delay onset)
├── physical_progress_pct       (Direct telemetry of construction execution)
├── has_cost_overrun            (Label-correlated financial failure metric)
└── schedule_delay_days         (Ground-truth target variable for regression)
```

---

## 3. Preprocessing Pipeline Consistency

The runtime inference endpoint (`POST /api/v1/predictions`) utilizes the exact serialized scikit-learn `Pipeline` objects created during training:
- `delay_classifier.joblib`: Contains the fitted `ColumnTransformer` (`OneHotEncoder` + `StandardScaler`) followed by `GradientBoostingClassifier`.
- `delay_regressor.joblib`: Contains the same fitted preprocessor followed by `RandomForestRegressor`.

This architecture prevents:
- **Feature Schema Mismatch**: Any unseen categorical value (e.g., a newly formed ministry) is safely handled by `handle_unknown='ignore'`.
- **Missing Column Failures**: Input dataframe rows are structured programmatically using the feature contract dictionary.
- **Categorical Drift**: Encoding indices are permanently frozen within the pipeline artifacts.

---

## 4. TreeSHAP Explainability Contract

- **Algorithm**: `shap.TreeExplainer` computed directly on the Gradient Boosting classification ensemble.
- **Output Schema**:
  ```json
  {
    "feature": "sector_delay_rate",
    "shap_value": 0.214,
    "direction": "RISK_INCREASE",
    "impact_pct": 21.4
  }
  ```
- **Graceful Error Fallback**: If TreeSHAP computation encounters an unexpected numerical anomaly, the API catches the exception and returns:
  ```json
  {
    "feature": "SHAP Explanation Notice",
    "shap_value": 0.0,
    "direction": "RISK_MITIGATING",
    "impact_pct": 0.0,
    "notice": "SHAP attribution explanation temporarily unavailable for this feature vector. Using institutional baseline priors."
  }
  ```
  **Zero Fake Explanations**: No randomized or synthetic values are ever substituted.
