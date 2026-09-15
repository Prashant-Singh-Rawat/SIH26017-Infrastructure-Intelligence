import re
from pathlib import Path

def test_html_dom_elements():
    html_path = Path(__file__).parent.parent / "frontend" / "index.html"
    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")

    # Form inputs
    inputs = [
        "eval-sector", "eval-ministry", "eval-cost", "eval-year",
        "eval-stage-select", "eval-land-req", "eval-land-acq",
        "eval-comp-disbursed", "eval-disputes", "eval-families",
        "eval-rehab-pkg", "eval-btn-submit", "eval-btn-reset",
        "eval-placeholder", "eval-output"
    ]
    for inp in inputs:
        assert f'id="{inp}"' in content, f"Missing input element id={inp} in index.html"

    # Error message targets
    error_ids = [
        "err-eval-sector", "err-eval-ministry", "err-eval-cost", "err-eval-year",
        "err-eval-land-req", "err-eval-land-acq", "err-eval-comp-disbursed",
        "err-eval-disputes", "err-eval-families", "err-eval-rehab-pkg"
    ]
    for err in error_ids:
        assert f'id="{err}"' in content, f"Missing error container id={err} in index.html"

    # Results panel targets
    result_ids = [
        "eval-tier-banner", "eval-tier-text", "eval-model-ver", "eval-conf-score",
        "eval-prob-val", "eval-delay-val", "eval-delay-sub",
        "eval-metric-total-land", "eval-metric-acq-land", "eval-metric-pending-land",
        "eval-metric-comp-gap", "eval-bottleneck-title", "eval-bottleneck-act",
        "eval-bottleneck-severity", "eval-bottleneck-evidence",
        "stage-box-admin", "stage-box-val", "stage-box-comp", "stage-box-rehab", "stage-box-poss",
        "eval-risk-drivers-list", "eval-shap-list",
        "eval-btn-alert", "eval-btn-simulate"
    ]
    for res_id in result_ids:
        assert f'id="{res_id}"' in content, f"Missing result container id={res_id} in index.html"

def test_app_js_evaluator_functions():
    js_path = Path(__file__).parent.parent / "frontend" / "app.js"
    assert js_path.exists()
    content = js_path.read_text(encoding="utf-8")

    # Functions defined
    functions = [
        "function onEvalSectorChange",
        "function validateField",
        "function validateEvaluatorInputs",
        "function runEarlyWarningEvaluation",
        "function resetEarlyWarningEvaluator",
        "function clearEvaluatorProjectContext",
        "function evaluateSelectedProject",
        "function addEvaluatorAlert",
        "function simulateEvaluatorParameters"
    ]
    for fn in functions:
        assert fn in content, f"Missing function '{fn}' in app.js"

    # Window exports
    window_exports = [
        "window.onEvalSectorChange = onEvalSectorChange;",
        "window.validateField = validateField;",
        "window.validateEvaluatorInputs = validateEvaluatorInputs;",
        "window.runEarlyWarningEvaluation = runEarlyWarningEvaluation;",
        "window.resetEarlyWarningEvaluator = resetEarlyWarningEvaluator;",
        "window.clearEvaluatorProjectContext = clearEvaluatorProjectContext;",
        "window.evaluateSelectedProject = evaluateSelectedProject;",
        "window.addEvaluatorAlert = addEvaluatorAlert;",
        "window.simulateEvaluatorParameters = simulateEvaluatorParameters;"
    ]
    for exp in window_exports:
        assert exp in content, f"Missing window export '{exp}' in app.js"

def test_sector_ministry_mapping():
    js_path = Path(__file__).parent.parent / "frontend" / "app.js"
    content = js_path.read_text(encoding="utf-8")
    assert "const SECTOR_MINISTRY_MAP" in content
    assert "Roads & Highways" in content
    assert "Ministry of Road Transport & Highways" in content
    assert "Railways" in content
    assert "Ministry of Railways" in content
    assert "Power" in content
    assert "Ministry of Power" in content
