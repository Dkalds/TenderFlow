"""Tests de la auditoría de verdad del dato (``scripts/audit_domain_truth.py``).

La auditoría se escribió para medir cuatro defectos de dominio y hasta ahora
solo se ejecutaba a mano, sin ninguna prueba: nadie sabía si sus números eran
correctos. Al pasar a correr desatendida en un workflow programado, sus
umbrales deciden cuándo despertar a alguien, así que necesitan cobertura.

Estos tests siembran casos conocidos y verifican que la medición los reconoce
(no solo que la llamada no lanza).
"""

from __future__ import annotations

from typing import Any

from scripts.audit_domain_truth import (
    MAX_DELTA_BAJA_PUNTOS,
    MAX_PCT_FILAS_UTE,
    MAX_PCT_SIN_FECHA_LIMITE,
    MIN_LICITACIONES_PARA_EVALUAR,
    evaluar,
)


def _insertar_licitacion(
    conn: Any,
    id_externo: str,
    *,
    fuente: str = "test",
    importe: float = 100000.0,
    fecha_limite: str | None = "2026-07-01",
) -> None:
    conn.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, importe, estado, "
        "fuente, analysis_universe, fecha_limite, fecha_extraccion) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            id_externo,
            f"Licitación {id_externo}",
            "Órgano de prueba",
            importe,
            "ADJ",
            fuente,
            "technology_observed",
            fecha_limite,
            "2026-06-01T00:00:00+00:00",
        ),
    )


def _insertar_adjudicacion(conn: Any, licitacion_id: str, nif: str, importe: float) -> None:
    conn.execute(
        "INSERT INTO adjudicaciones (licitacion_id, nombre, nif, importe_adjudicado, "
        "fecha_adjudicacion, fecha_extraccion) VALUES (%s, %s, %s, %s, %s, %s)",
        (licitacion_id, f"Empresa {nif}", nif, importe, "2026-05-01", "2026-06-01T00:00:00+00:00"),
    )


def test_fecha_limite_gap_distingue_las_fuentes(tmp_db) -> None:
    """La sección (a) reporta el hueco por fuente, no un agregado global."""
    from db.domain_truth_audit import fecha_limite_gap_by_source

    db_mod, _ = tmp_db
    with db_mod.connect() as conn:
        for i in range(3):
            _insertar_licitacion(conn, f"CON-{i}", fuente="con_plazo", fecha_limite="2026-07-01")
        for i in range(2):
            _insertar_licitacion(conn, f"SIN-{i}", fuente="sin_plazo", fecha_limite=None)

    por_fuente = {fila["fuente"]: fila for fila in fecha_limite_gap_by_source()}

    assert por_fuente["con_plazo"]["sin_fecha_limite"] == 0
    assert float(por_fuente["con_plazo"]["pct_sin_fecha_limite"]) == 0.0
    assert por_fuente["sin_plazo"]["sin_fecha_limite"] == 2
    assert float(por_fuente["sin_plazo"]["pct_sin_fecha_limite"]) == 100.0


def test_ute_candidatas_cuenta_filas_y_proporcion(tmp_db) -> None:
    """La sección (c) detecta el grupo con dos NIF y lo expresa como % del total."""
    from db.domain_truth_audit import ute_candidate_stats

    db_mod, _ = tmp_db
    with db_mod.connect() as conn:
        _insertar_licitacion(conn, "LIC-UTE")
        _insertar_licitacion(conn, "LIC-NORMAL")
        # Misma licitación, misma fecha, mismo importe, dos NIF: una UTE
        # expandida en dos filas con el importe repetido entero.
        _insertar_adjudicacion(conn, "LIC-UTE", "A11111111", 50000.0)
        _insertar_adjudicacion(conn, "LIC-UTE", "B22222222", 50000.0)
        # Adjudicación normal: no debe contarse.
        _insertar_adjudicacion(conn, "LIC-NORMAL", "C33333333", 70000.0)

    stats = ute_candidate_stats()

    assert stats["grupos_candidatos"] == 1
    assert stats["filas_afectadas"] == 2
    assert stats["total_filas"] == 3
    assert stats["pct_filas_afectadas"] == round(200.0 / 3, 2)
    assert stats["muestra"][0]["licitacion_id"] == "LIC-UTE"


def test_baja_delta_detecta_el_efecto_multilote(tmp_db) -> None:
    """La sección (d) separa la baja por adjudicación de la agregada.

    Un expediente con dos adjudicaciones parciales: por adjudicación cada una
    se compara contra el presupuesto ENTERO (baja inflada); agregadas suman y
    dan la baja real. El delta es exactamente el efecto que mide la auditoría.
    """
    from db.domain_truth_audit import baja_media_delta

    db_mod, _ = tmp_db
    with db_mod.connect() as conn:
        _insertar_licitacion(conn, "LIC-LOTES", importe=100000.0)
        _insertar_adjudicacion(conn, "LIC-LOTES", "A11111111", 45000.0)
        _insertar_adjudicacion(conn, "LIC-LOTES", "B22222222", 45000.0)

    stats = baja_media_delta()

    # Por adjudicación: (100000-45000)/100000 = 55% cada una.
    assert round(float(stats["baja_media_pct_por_adjudicacion"])) == 55
    # Agregado: (100000-90000)/100000 = 10%.
    assert round(float(stats["baja_media_pct_por_licitacion"])) == 10
    assert stats["n_por_adjudicacion"] == 2
    assert stats["n_por_licitacion"] == 1


# ── Umbrales: `evaluar()` es lógica pura sobre el dict de mediciones ─────────


def _datos(**secciones: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "fecha_limite": {"por_fuente": []},
        "multi_lote": {"disponible": False, "motivo": "sin ZIP"},
        "ute": {"pct_filas_afectadas": 0.0, "filas_afectadas": 0, "total_filas": 0},
        "baja": {"delta_puntos": 0.0},
    }
    base.update(secciones)
    return base


def test_evaluar_no_reporta_nada_en_rango() -> None:
    assert evaluar(_datos()) == []


def test_evaluar_detecta_fuente_sin_plazo() -> None:
    datos = _datos(
        fecha_limite={
            "por_fuente": [
                {
                    "fuente": "placsp",
                    "total": MIN_LICITACIONES_PARA_EVALUAR + 1,
                    "sin_fecha_limite": MIN_LICITACIONES_PARA_EVALUAR,
                    "pct_sin_fecha_limite": MAX_PCT_SIN_FECHA_LIMITE + 10,
                }
            ]
        }
    )
    violaciones = evaluar(datos)
    assert len(violaciones) == 1
    assert "placsp" in violaciones[0]


def test_evaluar_ignora_fuentes_con_poco_volumen() -> None:
    """Una fuente con 4 licitaciones al 100% no dispara: el % no es señal."""
    datos = _datos(
        fecha_limite={
            "por_fuente": [
                {
                    "fuente": "regional_rss",
                    "total": MIN_LICITACIONES_PARA_EVALUAR - 1,
                    "sin_fecha_limite": MIN_LICITACIONES_PARA_EVALUAR - 1,
                    "pct_sin_fecha_limite": 100.0,
                }
            ]
        }
    )
    assert evaluar(datos) == []


def test_evaluar_detecta_ute_y_baja() -> None:
    datos = _datos(
        ute={
            "pct_filas_afectadas": MAX_PCT_FILAS_UTE + 1,
            "filas_afectadas": 100,
            "total_filas": 500,
        },
        baja={"delta_puntos": MAX_DELTA_BAJA_PUNTOS + 1},
    )
    violaciones = evaluar(datos)
    assert len(violaciones) == 2
    assert any("UTE" in v for v in violaciones)
    assert any("baja_media_pct" in v for v in violaciones)


def test_evaluar_reporta_una_seccion_que_no_pudo_medirse() -> None:
    """Un error de medición es una violación: silenciarlo dejaría el gate verde
    justo cuando la auditoría dejó de funcionar."""
    violaciones = evaluar(_datos(ute={"error": "relation does not exist"}))
    assert len(violaciones) == 1
    assert "no pudo medirse" in violaciones[0]


def test_evaluar_no_dispara_por_la_seccion_de_zips() -> None:
    """(b) depende de que haya ZIP en disco; en un runner efímero no los hay y
    eso no puede convertirse en una alerta sobre el dato."""
    datos = _datos(multi_lote={"disponible": False, "motivo": "Sin ZIP cacheados en /data"})
    assert evaluar(datos) == []
