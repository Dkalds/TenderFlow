"""Retención: censura de ventanas abiertas y una predicción por empresa.

Censura: con la ventana de sucesión ``[fin - 6, fin + 18]`` meses abierta en el
último dato cargado, la sucesora elegida es la más cercana *de las que ya
existen* y la etiqueta es provisional. Esos pares no entrenan ni cuentan en las
tasas del baseline; sí sirven para detectar un vencimiento ya resuelto.

Por empresa: Renovaciones pinta una fila por adjudicatario, así que el batch
puntúa cada ``(expediente, empresa)`` y la vista lee el riesgo de **su**
empresa (v175).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

import services.ml.retencion_labels as rl

_ORGANO = "Ayuntamiento de Prueba"


def _adj(
    lic_id: str, empresa_id: int, fecha_adj: str, fecha_fin: str | None = None
) -> dict[str, Any]:
    return {
        "licitacion_id": lic_id,
        "empresa_id": empresa_id,
        "nombre": f"Empresa {empresa_id}",
        "fecha_adjudicacion": fecha_adj,
        "importe_adjudicado": 90_000.0,
        "organo": _ORGANO,
        "cpv": "72000000",
        "ccaa": "Madrid",
        "importe": 100_000.0,
        "titulo": f"Servicio {lic_id}",
        "fecha_fin_efectiva": fecha_fin,
    }


def _historico() -> list[dict[str, Any]]:
    """Dos vencimientos con sucesora; el último dato es de 2025-06-01.

    - ``VIEJO`` vence el 2023-01-01: su ventana acabó en 2024-06, cerrada.
    - ``RECIENTE`` vence el 2025-03-01: su ventana llega a 2026-08, abierta.
    """
    return [
        _adj("VIEJO", 1, "2021-01-01", "2023-01-01"),
        _adj("VIEJO-SIG", 1, "2023-02-01"),
        _adj("RECIENTE", 2, "2023-03-01", "2025-03-01"),
        _adj("RECIENTE-SIG", 3, "2025-06-01"),
    ]


def _construir(adjudicaciones: list[dict[str, Any]]) -> list[rl.ParRetencion]:
    with (
        patch.object(rl, "_cargar_adjudicaciones", return_value=adjudicaciones),
        patch.object(rl, "_eventos_por_licitacion", return_value={}),
    ):
        return rl.construir_pares()


def test_el_corte_es_la_ultima_adjudicacion_cargada():
    assert rl._corte_de_datos(_historico()).strftime("%Y-%m-%d") == "2025-06-01"


def test_un_par_con_la_ventana_abierta_no_entrena():
    assert [p.licitacion_id for p in _construir(_historico())] == ["VIEJO"]


def test_las_tasas_solo_cuentan_pares_cerrados_pero_los_resueltos_si_ven_los_abiertos():
    etiquetas = rl.etiquetas_por_segmento(_historico())
    assert etiquetas.pares == 1
    assert etiquetas.con_sucesora == frozenset({"VIEJO", "RECIENTE"})


def test_cuando_los_datos_cubren_la_ventana_el_par_entra():
    historico = [*_historico(), _adj("OTRO", 9, "2026-09-01")]
    assert sorted(p.licitacion_id for p in _construir(historico)) == ["RECIENTE", "VIEJO"]


def test_la_poblacion_de_scoring_tiene_una_fila_por_empresa():
    historico = [
        _adj("MULTI", 1, "2024-01-01", "2026-12-01"),
        _adj("MULTI", 2, "2024-01-01", "2026-12-01"),
        # Mismo expediente y empresa en otro lote: no duplica.
        _adj("MULTI", 1, "2024-01-01", "2026-12-01"),
    ]
    filas = rl.vencimientos_proximos(historico, months_ahead=12, hoy="2026-06-01")
    assert sorted((f.licitacion_id, f.empresa_id) for f in filas) == [("MULTI", 1), ("MULTI", 2)]


# ---------------------------------------------------------------------------
# Contra Postgres: la clave de v175 y la lectura de Renovaciones
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def test_cada_adjudicatario_ve_su_propio_riesgo(db):
    from datetime import date, timedelta

    from db.repositories.predicciones import PrediccionesRepository
    from services.competitive.renovaciones import proximas_renovaciones

    fin = (date.today() + timedelta(days=60)).isoformat()
    with db.connect() as c:
        ids = [
            c.execute(
                "INSERT INTO empresas (nombre_canonico) VALUES (%s) RETURNING empresa_id", (n,)
            ).fetchone()[0]
            for n in ("Alfa SL", "Beta SA")
        ]
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, ccaa, "
            " importe, fecha_fin, fuente, fecha_publicacion, fecha_extraccion) "
            "VALUES ('MULTI', 'Servicio', 'Organo', '72000000', 'Madrid', 100000, %s, "
            " 'placsp', '2024-01-01', CURRENT_TIMESTAMP)",
            (fin,),
        )
        for empresa_id in ids:
            c.execute(
                "INSERT INTO adjudicaciones (licitacion_id, nombre, importe_adjudicado, "
                " fecha_adjudicacion, empresa_id, fecha_extraccion) "
                "VALUES ('MULTI', 'x', 50000, '2024-01-01', %s, CURRENT_TIMESTAMP)",
                (empresa_id,),
            )

    repo = PrediccionesRepository()
    filas = [("MULTI", ids[0], 0.8, 0.2, None, "t1"), ("MULTI", ids[1], 0.3, 0.7, None, "t1")]
    repo.guardar_retencion(filas, computed_at="t1")
    repo.guardar_retencion(filas, computed_at="t1")  # idempotente con la clave nueva

    riesgos = {
        r["empresa_id"]: r["riesgo_cambio"]
        for r in proximas_renovaciones(months_ahead=6)
        if r["licitacion_id"] == "MULTI"
    }
    assert riesgos == {ids[0]: pytest.approx(0.2), ids[1]: pytest.approx(0.7)}
