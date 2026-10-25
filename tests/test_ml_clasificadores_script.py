"""``scripts/ml_clasificadores.py``: el CLI que vivía dentro de ``sap_classifier``.

Sin BD: se prueba el despacho, el formateo de los informes y que la entrada de
siempre (``python -m services.ml.sap_classifier``) sigue llegando al CLI.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_RUTA = _ROOT / "scripts" / "ml_clasificadores.py"
_spec = importlib.util.spec_from_file_location("ml_clasificadores", _RUTA)
assert _spec is not None and _spec.loader is not None
cli = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = cli
_spec.loader.exec_module(cli)


def test_help_sale_con_cero_y_lista_los_comandos(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--help"]) == 0

    salida = capsys.readouterr().out
    for comando in cli.COMANDOS:
        assert comando in salida


def test_un_comando_desconocido_sale_con_uno(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["entrenar-todo"]) == 1

    assert "Comando desconocido: entrenar-todo" in capsys.readouterr().out


def test_sin_comando_entrena(monkeypatch: pytest.MonkeyPatch) -> None:
    """El default de siempre: ``python -m services.ml.sap_classifier`` a secas era ``train``."""
    llamados: list[list[str]] = []
    monkeypatch.setitem(cli._DESPACHO, "train", lambda argv: llamados.append(list(argv)) or 0)

    assert cli.main([]) == 0
    assert llamados == [[]]


def test_precompute_pasa_force(monkeypatch: pytest.MonkeyPatch) -> None:
    vistos: list[bool] = []

    def _precompute(*, force: bool) -> dict[str, int]:
        vistos.append(force)
        return {"updated": 3}

    monkeypatch.setattr("services.ml.classifier_training.precompute_ml_proba", _precompute)

    assert cli.main(["precompute", "--force"]) == 0
    assert vistos == [True]


def test_el_informe_de_entrenamiento_sap() -> None:
    ruta = Path("data/models/sap_classifier.pkl")

    ok = cli.lineas_entrenamiento_sap({"f1": 0.9}, min_muestras=50, ruta_modelo=ruta)
    assert ok[0] == "  f1: 0.9"
    assert ok[-1] == f"Modelo guardado en: {ruta}"

    una_clase = cli.lineas_entrenamiento_sap(
        {"error": "single_class", "n_positive": 80, "n_negative": 0},
        min_muestras=50,
        ruta_modelo=ruta,
    )
    assert any("clase única" in linea for linea in una_clase)
    assert una_clase[-1].endswith(f"{cli.PROGRAMA} seed-negatives")

    pocas = cli.lineas_entrenamiento_sap(
        {"error": "insufficient_data", "n_samples": 12}, min_muestras=50, ruta_modelo=ruta
    )
    assert "12 muestras (mínimo 50)" in pocas[-1]


def test_el_informe_de_entrenamiento_tech_desglosa_por_tecnologia() -> None:
    metricas = {
        "micro_f1_all_labels": 0.8,
        "labels_circulares": False,
        "per_tech": {
            "SAP": {"tier": "ml", "n_positive": 120, "threshold": 0.5, "f1": 0.91234},
            "Salesforce": {"tier": "rules", "n_positive": 3, "threshold": None, "f1": None},
        },
    }

    lineas = cli.lineas_entrenamiento_tech(metricas, ruta_modelo=Path("m.pkl"))

    sap = next(linea for linea in lineas if "- SAP" in linea)
    assert "F1=0.912" in sap
    salesforce = next(linea for linea in lineas if "- Salesforce" in linea)
    assert "F1=—" in salesforce
    assert cli.lineas_entrenamiento_tech({"error": "x"}, ruta_modelo=Path("m.pkl"))[-1].startswith(
        "[ERROR]"
    )


def test_python_m_del_modulo_de_dominio_delega_en_el_cli() -> None:
    """La entrada de siempre sigue viva: README antiguos, runbooks y manos."""
    proceso = subprocess.run(
        [sys.executable, "-m", "services.ml.sap_classifier", "--help"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert proceso.returncode == 0, proceso.stderr
    assert "scripts/ml_clasificadores.py" in proceso.stdout
