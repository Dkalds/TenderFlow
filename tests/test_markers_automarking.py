"""Tests unitarios para la inferencia de markers automática."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_test_conftest_module():
    conftest_path = Path(__file__).with_name("conftest.py")
    spec = importlib.util.spec_from_file_location("tests_conftest_module", conftest_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("No se pudo cargar tests/conftest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_infer_marker_unit_default():
    conftest_mod = _load_test_conftest_module()
    assert conftest_mod._infer_marker("tests/test_stats.py", "test_calcula_kpi") == "unit"


def test_infer_marker_e2e_has_priority():
    conftest_mod = _load_test_conftest_module()
    assert (
        conftest_mod._infer_marker(
            "tests/test_dashboard_smoke.py",
            "test_dashboard_smoke_load_property_integration",
        )
        == "e2e"
    )


def test_infer_marker_load():
    conftest_mod = _load_test_conftest_module()
    assert conftest_mod._infer_marker("tests/test_performance.py", "test_api_load") == "load"


def test_infer_marker_property():
    conftest_mod = _load_test_conftest_module()
    assert (
        conftest_mod._infer_marker("tests/test_property_based.py", "test_parser_properties")
        == "property"
    )


def test_infer_marker_integration_by_path_token():
    conftest_mod = _load_test_conftest_module()
    assert (
        conftest_mod._infer_marker("tests/integration/test_api_contract.py", "test_contract")
        == "integration"
    )


def test_infer_marker_integration_by_name_pattern():
    conftest_mod = _load_test_conftest_module()
    assert (
        conftest_mod._infer_marker("tests/test_api_contract.py", "test_integration_webhook")
        == "integration"
    )
