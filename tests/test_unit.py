"""
Unit Tests — SIH26017
Tests feature engineering, zero-leakage constraints, risk tiering, action recommendations, and SHAP explainability.
"""

import os
import pytest
import pandas as pd
import numpy as np

from backend.feature_engineering import assign_cost_bucket
from backend.model_engine import (
    get_risk_tier,
    get_action_recommendations,
    explain_prediction_cached,
    CAT_FEATURES,
    NUM_FEATURES
)
from backend.server import classifier, regressor, shap_explainer, feature_names

def test_cost_bucket_assignment():
    assert assign_cost_bucket(50) == "Tier 1 (< ₹100 Cr)"
    assert assign_cost_bucket(250) == "Tier 2 (₹100 - ₹500 Cr)"
    assert assign_cost_bucket(1500) == "Tier 3 (₹500 - ₹2,000 Cr)"
    assert assign_cost_bucket(5000) == "Tier 4 (₹2,000 - ₹10,000 Cr)"
    assert assign_cost_bucket(25000) == "Tier 5 (> ₹10,000 Cr Mega)"

def test_risk_tier_classification():
    assert get_risk_tier(0.85) == "Critical Risk (Red)"
    assert get_risk_tier(0.65) == "High Risk (Amber)"
    assert get_risk_tier(0.40) == "Medium Risk (Yellow)"
    assert get_risk_tier(0.15) == "Low Risk (Green)"

def test_zero_leakage_feature_specification():
    """Verify that NO downstream/execution features are used in inception model."""
    forbidden_features = [
        "actual_end_date", "revised_end_date", "expenditure_cr",
        "expenditure_ratio", "schedule_delay_days", "has_cost_overrun",
        "cost_overrun_pct", "physical_progress", "contractor_payment"
    ]
    all_model_features = CAT_FEATURES + NUM_FEATURES
    for forbidden in forbidden_features:
        assert forbidden not in all_model_features, f"Data leakage detected! '{forbidden}' found in feature list."

def test_action_recommendations_generation():
    recs = get_action_recommendations(
        prob=0.88,
        delay_days=450,
        sector="Railways",
        ministry="Ministry of Railways",
        cost=3500.0
    )
    assert len(recs) >= 2
    priorities = [r["priority"] for r in recs]
    assert "IMMEDIATE (P1)" in priorities
    authorities = [r["authority"] for r in recs]
    assert any("Cabinet Secretariat" in a or "PIB" in a for a in authorities)

def test_cached_shap_explainability():
    test_input = pd.DataFrame([{
        "sector_name": "Roads & Highways",
        "line_ministry": "Ministry of Road Transport & Highways",
        "cost_scale_bucket": "Tier 3 (₹500 - ₹2,000 Cr)",
        "original_cost_cr": 1200.0,
        "log_original_cost": float(np.log1p(1200.0)),
        "original_end_year": 2027,
        "original_end_quarter": 2,
        "sector_delay_rate": 0.65,
        "ministry_delay_rate": 0.62
    }])
    
    factors = explain_prediction_cached(test_input, classifier, shap_explainer, feature_names)
    assert isinstance(factors, list)
    assert len(factors) > 0
    first_factor = factors[0]
    assert "feature" in first_factor
    assert "shap_value" in first_factor
    assert "direction" in first_factor
    assert first_factor["direction"] in ["RISK_INCREASE", "RISK_MITIGATING"]
