# ML Zero Data Leakage Policy & Feature Specification — SIH26017
**Project:** PM-OCMS Infrastructure Delay & Cost Overrun Intelligence Platform  
**Target:** Inception-Time Early-Warning Prediction Engine  
**Standard:** Strict Temporal Separation of Pre-Sanction vs Post-Sanction Information

---

## 1. Principle of Zero Data Leakage

In infrastructure predictive analytics, **data leakage** occurs when features that only become known *after* project execution or delay onset are inadvertently fed into a pre-construction prediction model. 

For example, using `revised_completion_date`, `cumulative_expenditure_cr`, or `physical_progress_pct` to predict whether a project will be delayed creates artificial 99%+ accuracy during training, but causes catastrophic failure when evaluating newly approved projects at Day 0.

```
PROJECT TIMELINE:
───[ Inception & Approval ]───┼───[ Land Acquisition / Execution ]───┼───[ Commissioning ]───►
              ▲                                       ▲
              │                                       │
     PERMITTED PREDICTORS:                 STRICTLY FORBIDDEN:
     • original_cost_cr                    • revised_cost_cr (future growth)
     • sanctioned_duration_days            • expenditure_cr (future spend)
     • sector_name                         • revised_completion_date
     • line_ministry                       • physical_progress_pct
     • planned_end_year                    • actual_delay_days
     • historical_sector_delay_rate
```

---

## 2. Inception Feature Specification

The production early-warning model uses **only** the following sanction-time predictors:

| Feature Name | Type | Description | Temporal Availability |
| :--- | :--- | :--- | :--- |
| `sector_name` | Categorical | Infrastructure sector (Railways, Roads, Power, Petroleum, etc.) | Available at project approval |
| `line_ministry` | Categorical | Responsible line ministry | Available at project approval |
| `cost_scale_bucket` | Categorical | Budget magnitude (Tier 1 through Tier 5 Mega) | Derived from sanctioned cost |
| `original_cost_cr` | Numeric | Sanctioned capital outlay approved by CCEA (in ₹ Cr) | Sanctioned at Day 0 |
| `log_original_cost` | Numeric | Log-transformed original outlay: `ln(1 + original_cost)` | Derived from sanctioned cost |
| `original_end_year` | Numeric | Sanctioned commissioning calendar year | Sanctioned at Day 0 |
| `original_end_quarter`| Numeric | Sanctioned fiscal quarter (1 - 4) | Sanctioned at Day 0 |
| `sector_delay_rate` | Numeric | Historical baseline delay proportion across sector peers | Prior historical empirical rate |
| `ministry_delay_rate` | Numeric | Historical baseline delay proportion across ministry peers | Prior historical empirical rate |

---

## 3. Explicitly Excluded Downstream Features

The following features exist in the MoSPI monitoring CSVs but are **strictly quarantined** and never passed to the inception classifier or regressor:

1. **`revised_cost_cr`**: Measures cost escalation occurring years into execution.
2. **`expenditure_cr`**: Telemetry of financial disbursement during civil works.
3. **`expenditure_ratio`**: Proportion of budget spent.
4. **`revised_end_date`**: Extended timeline approved after delay has materialized.
5. **`has_cost_overrun`**: Target-correlated label for financial slippage.
6. **`schedule_delay_days`**: Target variable for regression; quarantined from classification.
7. **`data_quality_flags`**: Post-hoc audit diagnostics.

---

## 4. Model Architecture & Validation Performance

- **Algorithm (Classification)**: Scikit-learn `GradientBoostingClassifier` with `OneHotEncoder` and `StandardScaler` inside a unified `Pipeline`.
  - Target: Binary delay flag (`is_delayed = 1`).
  - Cross-Validation (5-Fold Stratified): **ROC-AUC = 0.812**, Accuracy = 78.5%, F1 = 0.777.
- **Algorithm (Regression)**: Scikit-learn `RandomForestRegressor`.
  - Target: Expected schedule slippage (`schedule_delay_days_clipped` in `[-365, 3650]`).
  - Test MAE: **161.6 days** (approx. 5.3 months) on mega-projects spanning 5–10 year horizons.
- **Explainability**: `shap.TreeExplainer` computed directly on the trained tree ensemble, ensuring that every prediction probability is broken down into positive and negative risk drivers.
- **Reproducibility**: Models, feature schemata, and metrics are serialized in `backend/models/` and registered in the `model_versions` database table.
