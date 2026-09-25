"""Tests unitarios para la inferencia de markers automática."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def _load_test_conftest_module() -> ModuleType:
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


class _ItemFalso:
    """Lo mínimo de un ``pytest.Item`` que lee `pytest_collection_modifyitems`."""

    def __init__(self, path: Path, name: str) -> None:
        self.path = path
        self.name = name
        self.fixturenames: tuple[str, ...] = ()
        self.marcas: list[str] = []

    def iter_markers(self) -> Iterator[pytest.Mark]:
        return iter(())

    def add_marker(self, marker: pytest.MarkDecorator) -> None:
        self.marcas.append(marker.name)


def _marcas_del_hook(modulo: Path, raiz: Path) -> list[str]:
    """Pasa un item con ruta absoluta por el hook real, como hace pytest."""
    conftest_mod = _load_test_conftest_module()
    item = _ItemFalso(modulo, "test_calcula_kpi")
    conftest_mod.pytest_collection_modifyitems(SimpleNamespace(rootpath=raiz), [item])
    return item.marcas


# Un padre por familia de tokens; `Downloads` es el más fácil de pisar sin
# querer, porque contiene `load`. Los ids no llevan tokens a propósito: entran
# en `item.name`, y un `_e2e` o un `integration_` ahí marcaría a ESTE test como
# e2e/integration y lo sacaría de `make test-unit`.
@pytest.mark.parametrize(
    ("padre", "modulo", "esperado"),
    [
        pytest.param("work-performance", "test_foo.py", "unit", id="padre-rendimiento"),
        pytest.param("work-performance", "test_performance.py", "load", id="modulo-rendimiento"),
        pytest.param("Downloads", "test_foo.py", "unit", id="padre-descargas"),
        pytest.param("property-lab", "test_foo.py", "unit", id="padre-propiedades"),
        pytest.param("property-lab", "test_property_based.py", "property", id="modulo-propiedades"),
        pytest.param("demo_e2e", "test_foo.py", "unit", id="padre-extremo-a-extremo"),
        pytest.param("integration", "test_foo.py", "unit", id="padre-integracion"),
    ],
)
def test_marker_ignora_los_directorios_padre_del_checkout(
    padre: str, modulo: str, esperado: str
) -> None:
    raiz = Path("/home/u") / padre / "repo"

    assert _marcas_del_hook(raiz / "tests" / modulo, raiz) == [esperado]


def test_marker_con_el_modulo_fuera_de_la_raiz_mira_solo_su_nombre() -> None:
    """Un ``--rootdir`` que apunta a otro sitio no devuelve los padres al juego."""
    modulo = Path("/home/u/work-performance/repo/tests/test_foo.py")

    assert _marcas_del_hook(modulo, Path("/otra/raiz")) == ["unit"]
