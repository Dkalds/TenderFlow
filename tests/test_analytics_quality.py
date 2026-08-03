"""Tests for the Data Quality analytics service.

Caracterización de la migración pandas -> SQL (ADR-023): siembran licitaciones
reales en el schema aislado (``tmp_db``) — la completitud y el check de formato
la resuelve ``AggregateRepository.quality_completitud`` — y afirman los mismos
valores que daba el motor pandas. Cubre además los arreglos de integridad:

- **DLQ real**: ``dlq_count`` consulta ``failed_extractions`` en vez del stub que
  devolvía siempre 0 (el panel veía 0 pérdidas aunque hubiera fallos).
- **Formato de fecha** (no completitud): una fecha presente pero ``DD/MM/YYYY``
  cuenta como completa, pero NO como ISO → ``pct_fecha_iso``/``fechas_no_iso``.
  El check ahora corre en SQL sobre el string crudo — el camino pandas lo perdía
  al convertir la columna a ``Timestamp`` (ítem del backlog cerrado 2026-08-03).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import services.analytics.quality as q_mod

pytestmark = pytest.mark.usefixtures("tmp_db")


def _seed(rows: list[dict]) -> None:
    from db.upsert import Licitacion, upsert_licitaciones

    upsert_licitaciones(
        [
            Licitacion(
                id_externo=r["id_externo"],
                titulo=r.get("titulo", "t"),
                fecha_publicacion=r.get("fecha_publicacion"),
                importe=r.get("importe"),
                cpv=r.get("cpv"),
                estado=r.get("estado"),
                ccaa=r.get("ccaa"),
            )
            for r in rows
        ]
    )


def _rows() -> list[dict]:
    return [
        {
            "id_externo": "A",
            "titulo": "x",
            "fecha_publicacion": "2026-03-01T00:00:00+00:00",  # ISO con hora
            "importe": 1.0,
            "cpv": "72000000",
            "estado": "PUB",
            "ccaa": "Madrid",
        },
        {
            "id_externo": "B",
            "titulo": "y",
            "fecha_publicacion": "2026-03-02",  # ISO fecha
            "importe": 2.0,
            "cpv": "72000000",
            "estado": "PUB",
            "ccaa": "Madrid",
        },
        {
            "id_externo": "C",
            "titulo": "z",
            "fecha_publicacion": "31/12/2025",  # legacy DD/MM/YYYY → no-ISO
            "importe": 3.0,
            "cpv": "72000000",
            "estado": "PUB",
            "ccaa": "Madrid",
        },
        {
            "id_externo": "D",
            "titulo": "w",
            "fecha_publicacion": None,  # nulo → fuera del denominador de formato
            "importe": 4.0,
            "cpv": "72000000",
            "estado": "PUB",
            "ccaa": "Madrid",
        },
    ]


def test_quality_date_format_vs_completeness():
    """pct_fecha (completitud) y pct_fecha_iso (formato) son métricas distintas."""
    _seed(_rows())
    with patch("db.dlq.count_unresolved", return_value=0):
        res = q_mod.get_quality()

    # Completitud: 3 de 4 no nulas = 75%.
    assert round(res.pct_fecha, 1) == 75.0
    # Formato: de las 3 presentes, 2 son ISO = 66.7%; 1 es no-ISO (la DD/MM/YYYY).
    assert round(res.pct_fecha_iso, 1) == 66.7
    assert res.fechas_no_iso == 1


def test_quality_completitud_columnas_incluye_importe():
    """El desglose por columna refleja los conteos reales (importe 100%, cpv 100%)."""
    _seed(_rows())
    with patch("db.dlq.count_unresolved", return_value=0):
        res = q_mod.get_quality()

    por_col = {c.columna: c.pct for c in res.completitud_columnas}
    assert por_col["importe"] == 100.0
    assert por_col["cpv"] == 100.0
    assert por_col["fecha_publicacion"] == 75.0
    # Columnas nunca sembradas → 0%.
    assert por_col["url"] == 0.0


def test_quality_dlq_count_is_real_not_stub():
    """dlq_count refleja la DLQ real (antes era un stub fijo en 0)."""
    _seed(_rows())
    with patch("db.dlq.count_unresolved", return_value=7):
        res = q_mod.get_quality()
    assert res.dlq_count == 7


def test_quality_dlq_count_on_empty_dataset():
    """Sin registros analíticos, el conteo de DLQ sigue siendo real."""
    with patch("db.dlq.count_unresolved", return_value=3):
        res = q_mod.get_quality()
    assert res.total_records == 0
    assert res.dlq_count == 3


def test_quality_dlq_count_best_effort_on_error():
    """Si la DLQ no está disponible, dlq_count cae a 0 sin romper el panel."""
    _seed(_rows())
    with patch("db.dlq.count_unresolved", side_effect=RuntimeError("no table")):
        res = q_mod.get_quality()
    assert res.dlq_count == 0
    # El resto de métricas se calcula igualmente.
    assert res.total_records == 4


def test_quality_all_iso_dates():
    _seed(
        [
            {"id_externo": "A", "fecha_publicacion": "2026-01-01", "importe": 1.0},
            {"id_externo": "B", "fecha_publicacion": "2026-01-02T10:00:00+00:00", "importe": 2.0},
        ]
    )
    with patch("db.dlq.count_unresolved", return_value=0):
        res = q_mod.get_quality()
    assert res.pct_fecha_iso == 100.0
    assert res.fechas_no_iso == 0


def test_quality_organization_scope_counts_real_rows(tmp_db):
    """pct_organization_scoped/filas_sin_organizacion reflejan filas reales,
    no el best-effort fallback (ver test_quality_dlq_count_best_effort_on_error
    para el caso sin tablas)."""
    db_mod, _ = tmp_db
    from db.users import create_user

    user_id = create_user(
        email="quality-scope@example.test", password_hash="x"
    )  # pragma: allowlist secret
    with db_mod.connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) VALUES (?, ?, ?)",
            ("QUALITY-1", "x", "2026-07-30T10:00:00+00:00"),
        )

    from db.repositories.organizations import OrganizationRepository
    from db.repositories.watchlist import WatchlistRepository

    org_id = int(OrganizationRepository().create_organization("Quality org", user_id)["id"])
    repo = WatchlistRepository()
    repo.add_item("scoped-key", user_id, "QUALITY-1", org_id, "private")
    # Fila legacy sin organización -- add_item con organization_id=None omite
    # las columnas organization_id/visibility en el INSERT (quedan NULL).
    repo.add_item("legacy-key", user_id, "QUALITY-1", None)

    with patch("db.dlq.count_unresolved", return_value=0):
        res = q_mod.get_quality()

    assert res.filas_sin_organizacion >= 1
    assert 0.0 <= res.pct_organization_scoped < 100.0


def test_quality_organization_scope_best_effort_without_tables():
    """Sin tablas escopadas disponibles, cae a 100%/0 sin romper el panel."""
    with (
        patch("db.dlq.count_unresolved", return_value=0),
        patch(
            "db.repositories.organizations.OrganizationRepository.scope_coverage",
            side_effect=RuntimeError("no table"),
        ),
    ):
        res = q_mod.get_quality()
    assert res.pct_organization_scoped == 100.0
    assert res.filas_sin_organizacion == 0
