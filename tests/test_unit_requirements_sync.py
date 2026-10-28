"""``scripts/check_requirements_sync.py``: una sola lista de dependencias.

Hasta 2026-10 ``pyproject.toml`` declaraba sus ``dependencies`` a mano y no
coincidían con ``requirements.in``. Ahora las lee de ahí; el check impide que
vuelva una segunda lista y que ``requirements.in`` deje de ser legible para
setuptools.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "check_requirements_sync.py"

_PYPROJECT_BUENO = """
[project]
name = "x"
dynamic = ["dependencies"]

[tool.setuptools.dynamic]
dependencies = { file = ["requirements.in"] }
"""


@pytest.fixture()
def sync() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_requirements_sync", _SCRIPT)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["check_requirements_sync"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture()
def simulado(sync: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Escribe un pyproject y un requirements.in de prueba y devuelve el check."""

    def _preparar(pyproject: str, requirements: str) -> int:
        (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
        (tmp_path / "requirements.in").write_text(requirements, encoding="utf-8")
        monkeypatch.setattr(sync, "PYPROJECT", tmp_path / "pyproject.toml")
        monkeypatch.setattr(sync, "REQUIREMENTS_IN", tmp_path / "requirements.in")
        return int(sync._comprueba_pyproject())

    return _preparar


def test_el_repo_de_hoy_pasa_el_check(sync: ModuleType) -> None:
    assert sync.main() == 0


def test_pyproject_lee_de_requirements_in(simulado) -> None:
    assert simulado(_PYPROJECT_BUENO, "# cabecera\nfastapi>=0.141,<1\n\nhttpx>=0.27,<1\n") == 0


def test_una_lista_a_mano_en_pyproject_falla(simulado, capsys) -> None:
    pyproject = _PYPROJECT_BUENO.replace(
        'dynamic = ["dependencies"]', 'dependencies = ["fastapi>=0.141,<1"]'
    )
    assert simulado(pyproject, "fastapi>=0.141,<1\n") == 1
    salida = capsys.readouterr().out
    assert "segunda lista" in salida
    assert "dynamic" in salida


def test_otro_fichero_en_el_dynamic_falla(simulado, capsys) -> None:
    pyproject = _PYPROJECT_BUENO.replace('["requirements.in"]', '["requirements.txt"]')
    assert simulado(pyproject, "fastapi>=0.141,<1\n") == 1
    assert "requirements.txt" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("linea", "motivo"),
    [
        ("-r requirements-api.in", "opción de pip"),
        ("--index-url https://example.invalid/simple", "opción de pip"),
        ("fastapi>=0.141,<1  # el suelo lo pide api/rutas.py", "comentario al final"),
    ],
)
def test_requirements_in_tiene_que_ser_legible_para_setuptools(
    simulado, capsys, linea: str, motivo: str
) -> None:
    assert simulado(_PYPROJECT_BUENO, f"httpx>=0.27,<1\n{linea}\n") == 1
    assert motivo in capsys.readouterr().out
