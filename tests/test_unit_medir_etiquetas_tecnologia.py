"""Recuento y precisión de ``scripts/medir_etiquetas_tecnologia.py`` (sin BD)."""

from __future__ import annotations

import json
from unittest.mock import patch

from scripts.medir_etiquetas_tecnologia import (
    fuentes_por_etiqueta,
    main,
    muestra,
    precision,
    rehacer,
    repuntuar,
    resumir,
    vistas,
)

_OBSOLETAS = "scripts.medir_etiquetas_tecnologia._obsoletas"
_FASE = "scheduler.jobs.documentos_embeddings._run_tech_signal_phase"
_ML = "services.ml.classifier_training.precompute_ml_tecnologias"
_FUSION = "services.tech_signal.merge_doc_signals"


def test_repuntuar_recorre_las_obsoletas_hasta_vaciarlas() -> None:
    with (
        patch(_OBSOLETAS, side_effect=[["L1", "L2"], ["L3"], []]),
        patch(_FASE, return_value={"scored": 1, "no_signal": 0, "error": 0}) as fase,
    ):
        hecho = repuntuar(presupuesto_s=60, shard=1, shards=4)
    assert hecho == {"pliegos": {"scored": 2, "no_signal": 0, "error": 0}, "quedan": False}
    assert fase.call_args_list[0].kwargs == {"licitacion_ids": ["L1", "L2"]}


def test_repuntuar_para_si_un_lote_solo_falla() -> None:
    with (
        patch(_OBSOLETAS, return_value=["L1"]),
        patch(_FASE, return_value={"scored": 0, "no_signal": 0, "error": 1}) as fase,
    ):
        hecho = repuntuar(presupuesto_s=60)
    assert hecho["quedan"] is True
    fase.assert_called_once()


def test_repuntuar_para_al_agotar_el_presupuesto() -> None:
    with patch(_OBSOLETAS) as obsoletas, patch(_FASE) as fase:
        hecho = repuntuar(presupuesto_s=0)
    assert hecho["quedan"] is True
    obsoletas.assert_not_called()
    fase.assert_not_called()


def test_rehacer_no_toca_nada_con_obsoletas() -> None:
    """Rehacer antes de re-puntuar volvería a fundir las señales viejas."""
    with patch(_OBSOLETAS, return_value=["L1"]), patch(_ML) as ml, patch(_FUSION) as fusion:
        assert rehacer() == {"completo": False}
    ml.assert_not_called()
    fusion.assert_not_called()


def test_rehacer_sin_obsoletas_rehace_ml_y_funde() -> None:
    with (
        patch(_OBSOLETAS, return_value=[]),
        patch(_ML, return_value={"updated": 9}) as ml,
        patch(_FUSION, return_value={"licitaciones_merged": 3}) as fusion,
    ):
        hecho = rehacer()
    assert hecho["completo"] is True
    ml.assert_called_once_with(force=True)
    fusion.assert_called_once_with()


def _fila(**extra: object) -> dict[str, object]:
    fila: dict[str, object] = {
        "id_externo": "L1",
        "titulo": "Mantenimiento SAP S/4HANA",
        "cpv": "72267000",
        "tecnologia": "SAP",
        "ml_tecnologias": "SAP,CLOUD_INFRA",
        "ml_scores": [
            {"tecnologia": "SAP", "probabilidad": 0.9, "threshold_aplicado": 0.5},
            {"tecnologia": "ORACLE", "probabilidad": 0.1, "threshold_aplicado": 0.5},
        ],
        "pliego": [
            {
                "tecnologia": "CLOUD_INFRA",
                "method": "keywords",
                "score": 0.67,
                "matched_terms": '["backup", "cpd"]',
            },
            {"tecnologia": "GIS", "method": "keywords", "score": 0.34, "matched_terms": None},
            {"tecnologia": "DATOS_IA", "method": "llm_metadata", "score": 0.9},
        ],
    }
    fila.update(extra)
    return fila


def test_el_detalle_de_antes_listaba_todo_lo_que_puntuaba() -> None:
    v = vistas(_fila(), min_pliego=0.5)
    assert v["detalle_antes"] == {"SAP", "ORACLE", "CLOUD_INFRA", "GIS", "DATOS_IA"}
    assert v["detalle_ahora"] == {"SAP", "CLOUD_INFRA"}


def test_fuentes_por_etiqueta() -> None:
    assert fuentes_por_etiqueta(_fila(), min_pliego=0.5) == {
        "CLOUD_INFRA": ["pliego"],
        "SAP": ["ml", "titulo"],
    }


def test_resumir_cuenta_medias_y_terminos_del_pliego() -> None:
    r = resumir(
        [_fila(), _fila(id_externo="L2", tecnologia="", ml_tecnologias="SAP")], min_pliego=0.5
    )
    assert r["n"] == 2
    assert r["media"]["detalle_antes"] == 5.0
    assert r["por_etiqueta"]["CLOUD_INFRA"]["sin_titulo"] == 1
    assert ("CLOUD_INFRA: backup", 2) in r["terminos_solo_pliego"]


def test_muestra_deja_cada_etiqueta_por_revisar() -> None:
    [linea] = muestra([_fila()], n=5, min_pliego=0.5)
    assert linea["etiquetas"]["SAP"] == {"fuentes": ["ml", "titulo"], "correcta": None}
    assert linea["faltan"] == []


def test_precision_por_fuente_y_solo_pliego() -> None:
    lineas = [
        {
            "etiquetas": {
                "SAP": {"fuentes": ["ml", "titulo"], "correcta": True},
                "CLOUD_INFRA": {"fuentes": ["pliego"], "correcta": False},
                "GIS": {"fuentes": ["ml"], "correcta": None},
            },
            "faltan": ["ERP"],
        }
    ]
    r = precision(lineas)
    assert r["revisadas"] == 2
    assert r["sin_revisar"] == 1
    assert r["precision_global"] == 0.5
    assert r["por_fuente"]["solo_pliego"] == (0.0, 1)
    assert r["por_fuente"]["titulo"] == (1.0, 1)
    assert r["faltan"] == {"ERP": 1}


def test_precision_desde_la_linea_de_comandos(tmp_path, capsys) -> None:
    fichero = tmp_path / "revisada.jsonl"
    fichero.write_text(
        json.dumps({"etiquetas": {"SAP": {"fuentes": ["titulo"], "correcta": True}}}) + "\n",
        encoding="utf-8",
    )
    assert main(["precision", str(fichero)]) == 0
    assert "Precisión global: 100.0%" in capsys.readouterr().out
