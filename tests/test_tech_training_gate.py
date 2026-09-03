"""Gate de publicación del clasificador multi-tecnología (``train-tech.yml``).

Publicar un modelo entrenado sobre ``licitaciones.tecnologia`` es publicar una
copia del regex ``matches_technology()``, porque esa columna la escriben los
conectores aplicando ese mismo regex al mismo texto que ve el modelo. Y sería
peor que inútil: ``precompute_ml_tecnologias`` sobreescribe
``ml_tecnologias``/``ml_proba_max``/``ml_tech_principal`` en toda fila con
``ml_proba_max IS NULL``, así que el regex acabaría pisando la señal de pliego
que ``tech_signal_merge`` funde sobre esas mismas tres columnas.

El caso que da nombre a la mitad de esta suite: el flag ``labels_circulares``
que emite ``train`` se apaga con **una sola** fila etiquetada a mano, así que no
sirve de gate por sí solo. Producción tenía 33 licitaciones con etiqueta humana
y ninguna del LLM el 2026-09-03.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from scheduler.jobs import tech_training_run
from scheduler.jobs.tech_training_run import (
    MOTIVO_SIN_ETIQUETAS,
    _emitir_salida_github,
    artefactos,
    motivo_rechazo,
    pct_keywords,
    publicable,
    run,
)


def _metrics(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "labels_circulares": False,
        "n_models": 3,
        "n_samples": 5000,
        "label_column": "tecnologia_resuelta",
        "label_source_counts": {"human": 400, "llm": 300, "keywords": 300, "sin_etiqueta": 4000},
        "macro_f1_all_labels": 0.61,
        "n_etiquetas_independientes": 700,
        "umbral_etiquetas_independientes": 50,
    }
    base.update(overrides)
    return base


def test_publica_con_etiquetas_independientes_de_sobra() -> None:
    assert publicable(_metrics()) is True


def test_no_publica_con_etiquetas_circulares() -> None:
    assert publicable(_metrics(labels_circulares=True)) is False


def test_no_publica_sin_ningun_tier_ml() -> None:
    """Solo reglas es el fallback, no un artefacto que merezca servirse."""
    assert publicable(_metrics(n_models=0)) is False


def test_una_sola_etiqueta_humana_no_abre_la_puerta() -> None:
    """El caso real de 2026-09-03: 33 humanas contra ~1.400 de keywords.

    ``labels_circulares`` sale False —hay etiquetas independientes— sobre un
    modelo que es el regex con un redondeo humano encima. Sin el suelo
    absoluto, el gate lo habría publicado.
    """
    metrics = _metrics(
        labels_circulares=False,
        label_source_counts={"human": 33, "llm": 0, "keywords": 1405, "sin_etiqueta": 0},
    )
    assert publicable(metrics) is False
    assert pct_keywords(metrics) == 97.71
    assert "33 filas" in motivo_rechazo(metrics)


def test_no_publica_si_no_se_llego_a_entrenar() -> None:
    saltado = {
        "skipped": MOTIVO_SIN_ETIQUETAS,
        "n_etiquetas_independientes": 33,
        "umbral_etiquetas_independientes": 50,
    }
    assert publicable(saltado) is False
    assert "no se entrenó" in motivo_rechazo(saltado)


def test_run_no_entrena_por_debajo_del_suelo() -> None:
    """Entrenar sobre ~700k filas para tirar el resultado cuesta media hora."""
    with (
        patch.object(tech_training_run, "contar_etiquetas_independientes", return_value=33),
        patch.object(tech_training_run, "umbral_etiquetas_independientes", return_value=50),
        patch("scraper.tech_classifier.train_from_db") as entrenar,
    ):
        resultado = run()

    entrenar.assert_not_called()
    assert resultado["skipped"] == MOTIVO_SIN_ETIQUETAS
    assert resultado["n_etiquetas_independientes"] == 33


def test_run_entrena_cuando_hay_etiquetas() -> None:
    with (
        patch.object(tech_training_run, "contar_etiquetas_independientes", return_value=700),
        patch.object(tech_training_run, "umbral_etiquetas_independientes", return_value=50),
        patch("scraper.tech_classifier.train_from_db", return_value=_metrics()) as entrenar,
    ):
        resultado = run()

    entrenar.assert_called_once()
    assert resultado["n_etiquetas_independientes"] == 700


def test_artefactos_incluye_el_checksum_co_ubicado() -> None:
    """Sin el ``.sha256``, ``load()`` con ENV=prod rechaza el artefacto."""
    rutas = artefactos(_metrics())
    assert len(rutas) == 2
    assert rutas[0].endswith("tech_classifier.pkl")
    assert rutas[1].endswith("tech_classifier.sha256")


def test_artefactos_vacio_si_el_gate_rechaza() -> None:
    assert artefactos(_metrics(labels_circulares=True)) == []


def test_salida_github_distingue_rechazo_de_fallo(tmp_path, monkeypatch) -> None:
    """El YAML necesita separar «el gate rechazó» de «el train reventó».

    En disco los dos casos se parecen: no hay artefacto nuevo que subir.
    """
    destino = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(destino))

    _emitir_salida_github(_metrics(labels_circulares=True))
    lineas = destino.read_text(encoding="utf-8").splitlines()

    assert "publicable=false" in lineas
    assert "artefactos=" in lineas
    assert any(linea.startswith("motivo=") and len(linea) > len("motivo=") for linea in lineas)


def test_salida_github_publica_las_rutas(tmp_path, monkeypatch) -> None:
    destino = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(destino))

    _emitir_salida_github(_metrics())
    lineas = destino.read_text(encoding="utf-8").splitlines()

    assert "publicable=true" in lineas
    assert "motivo=" in lineas  # sin motivo: no hay rechazo que explicar
    # Una línea por output: un valor multilínea necesitaría heredoc y aquí
    # ninguno lo es.
    for linea in lineas:
        assert "=" in linea
