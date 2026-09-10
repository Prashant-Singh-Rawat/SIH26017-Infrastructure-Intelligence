# Machine Learning Model Retraining Policy & Temporal Validation Protocol
**SIH26017 — Infrastructure Delay & Cost Overrun Intelligence Platform**
**Division**: Infrastructure and Project Monitoring Division (IPMD) | Government of India

---

## 1. Cardinal Governance Rule: Separation of Data Updates from Model Retraining
> [!CRITICAL]
> **A newly ingested government data snapshot is NOT automatically a machine learning training dataset.**
> Data ingestion and model retraining are decoupled architectural processes. 
> The arrival of monthly snapshots (e.g. May 2026, June 2026) updates operational telemetry and triggers change detection, but **MUST NEVER automatically trigger unattended model retraining**.

### Why Automated Retraining on Raw Snapshots is Prohibited:
1. **Unsettled Labels (Right-Censoring)**: Ongoing projects are right-censored. A project currently recorded as having zero delay may slip 18 months from now. Retraining on provisional mid-flight states introduces substantial label noise.
2. **Temporal Data Leakage**: Shuffling records from multiple chronological snapshots into random train/test splits causes cross-temporal leakage, yielding artificially inflated performance metrics that collapse in production.
3. **Downstream Feature Bleed**: If revised costs or cumulative expenditures are ingested into training features, the model learns trivial tautologies (predicting cost overrun from already-incurred revised cost) rather than learning pre-construction risk indicators.
4. **Model Drift & Instability**: Unsupervised automated retraining risks catastrophic forgetting or vulnerability to transient reporting revisions.

---

## 2. Model Retraining Eligibility Criteria
Model retraining may only be initiated when **all six gating conditions** are satisfied:

| Gate | Requirement | Verification Method |
| :--- | :--- | :--- |
| **Gate 1: Label Maturity** | Minimum of **250 newly commissioned or completed projects** with finalized ground-truth completion dates and final audited outlays. | SQL query on `status_in_snapshot = 'COMPLETED'` with audited final accounts. |
| **Gate 2: Feature Invariance** | Strict adherence to the `Zero-Leakage Inception Feature Contract`. Downstream telemetry (`expenditure_cr`, `revised_cost_cr`, `revised_end_date`) remains strictly quarantined. | Automated check in `backend/ml_engine.py` verifying feature schema checksum. |
| **Gate 3: Temporal Split Protocol** | Train/Validation/Test partitions must respect chronological boundaries without temporal leakage. | Walk-forward temporal splitter (`TimeBasedSplit`). |
| **Gate 4: Performance Hurdle** | Candidate model must achieve equal or superior test ROC-AUC (≥ 0.82) and Precision-Recall AUC (≥ 0.78) compared to baseline without degrading High-Risk recall. | Automated benchmark comparison script `scripts/benchmark_model.py`. |
| **Gate 5: SHAP Interpretability Check** | Top SHAP feature drivers must align with domain reality (e.g. Sector, Sanction Scale, Ministry Historical Rate). No single feature may command > 45% attribution. | TreeSHAP summary plot audit against institutional heuristic bounds. |
| **Gate 6: Administrative Sign-Off** | Lead Data Scientist and IPMD Advisory Board formal approval. | Cryptographic signature logged to `audit_logs`. |

---

## 3. Temporal Validation Protocol (Preventing Snapshot Leakage)

### Prohibited Strategy: Random K-Fold Cross-Validation
Randomly partitioning multi-snapshot datasets assigns Project X in April 2026 to Train and Project X in May 2026 to Test. The model memorizes project identity rather than generalizing risk patterns.

### Mandatory Protocol: Temporal Walk-Forward Validation

```
[===================== TRAIN SET =====================] [== VALIDATION ==] [==== TEST SET ====]
     Earlier Historical Snapshots (≤ 2024-12)                (2025-01–2025-12)     (≥ 2026-01 Held-Out)
```

1. **Training Partition**:
   - Comprises completed and sanctioned projects from earlier historical periods (e.g. sanctions up to December 2024).
2. **Validation Partition**:
   - Intermediate chronological window used exclusively for hyperparameter tuning and early stopping.
3. **Held-Out Test Partition**:
   - Latest unobserved temporal window (e.g. projects sanctioned or monitored post January 2026).
   - Zero observations from earlier snapshots of test projects may appear in the training partition.

---

## 4. Current Zero-Leakage Feature Specification
The production model (`GradientBoostingClassifier v2.1` and `RandomForestRegressor v2.1`) enforces an invariant feature boundary:

### Permitted Inception Features:
- `sector_name` (Categorical One-Hot / Frequency Encoded)
- `line_ministry` (Categorical One-Hot / Frequency Encoded)
- `original_cost_cr` (Continuous Capital Sanction in ₹ Cr)
- `log_original_cost` ($\ln(1 + \text{original\_cost\_cr})$)
- `cost_scale_bucket` (Micro, Small, Medium, Large, Mega)
- `original_end_year` (Target Sanction Completion Year)
- `original_end_quarter` (Target Sanction Calendar Quarter)
- `sector_delay_rate` (Historical baseline sectoral frequency)
- `ministry_delay_rate` (Historical baseline ministerial frequency)

### Quarantined Downstream Features (Strictly Excluded):
- `expenditure_cr` (Cumulative outlay to date)
- `expenditure_ratio` ($\text{expenditure} / \text{original\_cost}$)
- `revised_cost_cr` (Formal revision budget)
- `revised_end_date` (Revised target milestone)
- `schedule_delay_days` (Already elapsed delay)
- `has_cost_overrun` (Post-facto budget escalation indicator)

---

## 5. Model Rollback & Versioning Strategy
- Trained models are serialized with versioned artifacts:
  - `models/delay_classifier_v{MAJOR}.{MINOR}.pkl`
  - `models/cost_regressor_v{MAJOR}.{MINOR}.pkl`
  - `models/model_metadata_v{MAJOR}.{MINOR}.json`
- In the event of inference regression or anomalous predictions in production, the model serving pipeline can instantly revert to the previous baseline via configuration variable:
  `ACTIVE_MODEL_VERSION = "v2.1"`
- Old prediction records in `prediction_history` are never modified or purged.
