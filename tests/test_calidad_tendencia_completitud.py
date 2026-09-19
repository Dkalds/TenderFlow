"""Tendencia de completitud por mes de publicación (RFC ux-calidad-datos #3).

Sin tabla de histórico: cada punto es la cohorte de un mes medida hoy. Estos
tests fijan la ventana, los porcentajes y el comportamiento best-effort; el
último siembra datos reales (``tmp_db``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import services.analytics.quality as q_mod
from services.analytics.quality import MESES_TENDENCIA, inicio_ventana_tendencia


def test_ventana_de_doce_meses_incluye_el_actual():
    assert MESES_TENDENCIA == 12
    assert inicio_ventana_tendencia(datetime(2026, 9, 19, tzinfo=UTC)) == "2025-10-01"
    assert inicio_ventana_tendencia(datetime(2026, 1, 5, tzinfo=UTC)) == "2025-02-01"
    assert inicio_ventana_tendencia(datetime(2026, 12, 31, tzinfo=UTC), meses=1) == "2026-12-01"


class _RepoFalso:
    def __init__(self, filas: list[dict[str, Any]] | Exception) -> None:
        self.filas = filas
        self.desde: str | None = None

    def quality_completitud_mensual(self, *, desde_iso: str) -> list[dict[str, Any]]:
        self.desde = desde_iso
        if isinstance(self.filas, Exception):
            raise self.filas
        return self.filas


def test_porcentajes_por_mes_y_meses_vacios_fuera(monkeypatch):
    repo = _RepoFalso(
        [
            {
                "mes": "2026-08",
                "total": 200,
                "con_cpv": 190,
                "con_importe": 100,
                "con_organo": 200,
                "con_fecha_limite": 3,
            },
            {"mes": "2026-09", "total": 0},
        ]
    )
    monkeypatch.setattr(q_mod, "_repo", repo)

    serie = q_mod._tendencia_completitud(datetime(2026, 9, 19, tzinfo=UTC))

    assert repo.desde == "2025-10-01"
    assert len(serie) == 1
    punto = serie[0]
    assert (punto.mes, punto.total) == ("2026-08", 200)
    assert (punto.pct_cpv, punto.pct_importe, punto.pct_organo) == (95.0, 50.0, 100.0)
    assert punto.pct_fecha_limite == 1.5


def test_fallo_de_la_consulta_deja_la_serie_vacia(monkeypatch):
    monkeypatch.setattr(q_mod, "_repo", _RepoFalso(RuntimeError("sin BD")))
    assert q_mod._tendencia_completitud() == []


def test_tendencia_con_datos_reales(tmp_db):
    from db.upsert import Licitacion, upsert_licitaciones

    mes = datetime.now(UTC).strftime("%Y-%m")
    upsert_licitaciones(
        [
            Licitacion(
                id_externo="T1",
                titulo="a",
                fecha_publicacion=f"{mes}-01",
                cpv="72000000",
                importe=10.0,
                organo_contratacion="Ayto",
            ),
            Licitacion(id_externo="T2", titulo="b", fecha_publicacion=f"{mes}-02"),
            # Fuera de la ventana de doce meses.
            Licitacion(id_externo="T3", titulo="c", fecha_publicacion="2001-01-01"),
        ]
    )
    serie = q_mod._tendencia_completitud()
    assert [p.mes for p in serie] == [mes]
    assert serie[0].total == 2
    assert serie[0].pct_cpv == 50.0
