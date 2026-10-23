"""Resumen tipado de la auditoría de verdad del dato (``services/verdad_dominio.py``).

La consola enseña las mismas secciones que el correo del cron. Lo que se fija
aquí es que las dos vistas no puedan discrepar: una sección sale en
``violacion`` exactamente cuando :func:`evaluar` la denuncia.
"""

from __future__ import annotations

from typing import Any

from services.verdad_dominio import (
    MIN_LICITACIONES_PARA_EVALUAR,
    UMBRAL_UTE,
    UMBRALES_FECHA_LIMITE,
    evaluar,
    resumir,
)


def _datos(**overrides: Any) -> dict[str, Any]:
    """Una medición entera dentro de rango, como la devolvería ``medir_bd``."""
    datos: dict[str, Any] = {
        "fecha_limite": {
            "por_fuente": [
                {
                    "fuente": "placsp",
                    "total": 1000,
                    "sin_fecha_limite": 100,
                    "pct_sin_fecha_limite": 10.0,
                },
                {"fuente": "nueva", "total": 3, "sin_fecha_limite": 3, "pct_sin_fecha_limite": 100},
            ]
        },
        "ute": {"pct_filas_afectadas": 0.0, "filas_afectadas": 0, "total_filas": 10},
        "baja": {
            "baja_media_pct_por_adjudicacion": 20.0,
            "baja_media_pct_por_licitacion": 19.5,
            "delta_puntos": 0.5,
        },
        "ml_proba": {
            "umbral": 0.7,
            "puntuadas": 10,
            "por_encima": 2,
            "pct_puntuadas_por_encima": 20.0,
            "fuera_poblacion": {"total": 5, "puntuadas": 0},
        },
        "fechas_imposibles": {"antes_de_1990": 10},
        "importe_tipo": {"desde": "2026-09-06", "sin_tipo": 0},
        "fechas_iso": {"total_no_iso": 0, "por_columna": []},
    }
    datos.update(overrides)
    return datos


def test_todo_en_rango_es_ok_y_evaluar_no_dice_nada() -> None:
    secciones = resumir(_datos())

    assert evaluar(_datos()) == []
    assert [s.clave for s in secciones] == [
        "fecha_limite",
        "ute",
        "baja",
        "ml_proba",
        "fechas_imposibles",
        "importe_tipo",
        "fechas_iso",
    ]
    assert {s.estado for s in secciones} == {"ok"}


def test_una_fuente_con_poco_volumen_se_informa_sin_limite() -> None:
    fecha_limite = resumir(_datos())[0]

    placsp, nueva = fecha_limite.metricas
    assert placsp.limite == UMBRALES_FECHA_LIMITE["placsp"].limite
    assert placsp.detalle == "100 de 1000"
    # 3 de 3 sin plazo es 100 %, pero con menos de MIN no se evalúa.
    assert MIN_LICITACIONES_PARA_EVALUAR > 3
    assert nueva.valor == 100 and nueva.limite is None and nueva.supera is False


def test_la_violacion_coincide_con_la_de_evaluar() -> None:
    pct = UMBRAL_UTE.limite + 1
    datos = _datos(ute={"pct_filas_afectadas": pct, "filas_afectadas": 9, "total_filas": 10})

    por_clave = {s.clave: s for s in resumir(datos)}

    assert por_clave["ute"].estado == "violacion"
    assert por_clave["ute"].metricas[0].supera is True
    assert [v for v in evaluar(datos) if v.startswith("UTE")]
    assert {s.estado for c, s in por_clave.items() if c != "ute"} == {"ok"}


def test_los_conteos_saltan_al_pasar_su_limite() -> None:
    datos = _datos(
        importe_tipo={"desde": "2026-09-06", "sin_tipo": 3},
        fechas_iso={"total_no_iso": 2, "por_columna": []},
    )

    por_clave = {s.clave: s for s in resumir(datos)}

    assert por_clave["importe_tipo"].estado == "violacion"
    assert por_clave["importe_tipo"].metricas[0].detalle == "ingeridas desde 2026-09-06"
    assert por_clave["fechas_iso"].estado == "violacion"
    assert len(evaluar(datos)) == 2


def test_una_seccion_que_no_pudo_medirse_es_error_y_no_tumba_las_demas() -> None:
    datos = _datos(ute={"error": "statement timeout"}, multi_lote={"disponible": False})

    secciones = resumir(datos)
    por_clave = {s.clave: s for s in secciones}

    assert por_clave["ute"].estado == "error"
    assert por_clave["ute"].error == "statement timeout"
    # La (b) es del script (lee ZIP en disco): la consola no la resume.
    assert "multi_lote" not in por_clave
    assert por_clave["baja"].estado == "ok"


def test_sin_dato_no_hay_metrica() -> None:
    datos = _datos(baja={"delta_puntos": None}, fechas_imposibles={})

    por_clave = {s.clave: s for s in resumir(datos)}

    assert por_clave["baja"].metricas[0].valor is None
    assert por_clave["baja"].estado == "ok"
    assert por_clave["fechas_imposibles"].estado == "sin_datos"
