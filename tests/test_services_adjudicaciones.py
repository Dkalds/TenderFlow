"""Tests para services/adjudicaciones.py con BD real (tmp_db).

Los loaders full-table (``load_adjudicaciones``/``load_raw_adjudicaciones`` y
su caché) se retiraron al completar ADR-023 — sus comportamientos viven ahora
en SQL y se prueban donde se consumen: baja_pct y lead-time en
``test_analytics_organos.py``, patrón UTE en ``test_analytics_utes.py`` /
``test_analytics_ecosistema_partners.py``, identidad canónica en
``test_analytics_red_organo_empresa.py``, filtros de competidores en
``test_analytics_competitors_sql_filters.py``. Aquí quedan los caminos vivos
del servicio (``load_licitadores``) y las garantías de persistencia
(idempotencia, lotes múltiples) vía ``AdjudicacionRepository``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("tmp_db")


# ---------------------------------------------------------------------------
# Helpers de seed (mismo patrón que test_services_licitaciones.py)
# ---------------------------------------------------------------------------


def _seed_licitacion(id_externo: str = "ADJ-TEST-001") -> None:
    """Inserta una licitación de referencia para poder adjudicar."""
    from db.upsert import Licitacion, upsert_licitaciones

    upsert_licitaciones(
        [
            Licitacion(
                id_externo=id_externo,
                titulo="Implantación SAP ERP",
                descripcion="Proyecto piloto",
                organo_contratacion="Ministerio de Hacienda",
                importe=500_000.0,
                estado="ADJ",
                fecha_publicacion="2024-01-10",
                tecnologia="SAP",
                ccaa="Madrid",
            )
        ]
    )


def _seed_adjudicacion(
    licitacion_id: str = "ADJ-TEST-001",
    *,
    nombre: str = "Empresa SAP SL",
    nif: str = "B12345678",  # pragma: allowlist secret
    importe_adjudicado: float = 420_000.0,
    fecha_adj: str = "2024-03-15",
    n_ofertas: int = 4,
    ccaa: str | None = "Madrid",
) -> None:
    from db.upsert import Adjudicacion, replace_adjudicaciones

    replace_adjudicaciones(
        licitacion_id,
        [
            Adjudicacion(
                licitacion_id=licitacion_id,
                nombre=nombre,
                nif=nif,
                importe_adjudicado=importe_adjudicado,
                fecha_adjudicacion=fecha_adj,
                n_ofertas_recibidas=n_ofertas,
                ccaa=ccaa,
            )
        ],
    )


def _rows_for(licitacion_id: str) -> list[dict]:
    from db.repositories.adjudicaciones import AdjudicacionRepository

    items, _total = AdjudicacionRepository().list_paginated(licitacion_id=licitacion_id)
    return items


# ---------------------------------------------------------------------------
# replace_adjudicaciones es idempotente (upsert)
# ---------------------------------------------------------------------------


def test_adjudicaciones_replace_idempotente():
    """Llamar replace_adjudicaciones dos veces con los mismos datos no duplica."""
    _seed_licitacion("ADJ-IDEM-001")
    _seed_adjudicacion("ADJ-IDEM-001")
    _seed_adjudicacion("ADJ-IDEM-001")  # segunda vez con mismos datos

    assert len(_rows_for("ADJ-IDEM-001")) == 1


# ---------------------------------------------------------------------------
# Múltiples adjudicaciones para una licitación
# ---------------------------------------------------------------------------


def test_adjudicaciones_multiples_por_licitacion():
    """Una licitación puede tener varias adjudicaciones (lotes)."""
    from db.upsert import Adjudicacion, Licitacion, replace_adjudicaciones, upsert_licitaciones

    upsert_licitaciones(
        [
            Licitacion(
                id_externo="ADJ-MULTI-001",
                titulo="Licitación con múltiples lotes",
                estado="ADJ",
                importe=1_000_000.0,
            )
        ]
    )
    replace_adjudicaciones(
        "ADJ-MULTI-001",
        [
            Adjudicacion(
                licitacion_id="ADJ-MULTI-001",
                nombre="Empresa Lote 1",
                nif="B11111111",
                importe_adjudicado=400_000.0,
                fecha_adjudicacion="2024-04-01",
            ),
            Adjudicacion(
                licitacion_id="ADJ-MULTI-001",
                nombre="Empresa Lote 2",
                nif="B22222222",
                importe_adjudicado=600_000.0,
                fecha_adjudicacion="2024-04-01",
            ),
        ],
    )

    assert len(_rows_for("ADJ-MULTI-001")) == 2


# ---------------------------------------------------------------------------
# load_licitadores: proyección acotada con datos de la licitación
# ---------------------------------------------------------------------------


def test_load_licitadores_incluye_datos_de_licitacion():
    _seed_licitacion("ADJ-LIC-001")
    _seed_adjudicacion("ADJ-LIC-001")

    from services.adjudicaciones import load_licitadores

    rows = load_licitadores()
    fila = next(r for r in rows if r["licitacion_id"] == "ADJ-LIC-001")
    assert fila["nombre"] == "Empresa SAP SL"
    assert fila["titulo"] == "Implantación SAP ERP"
    assert fila["organo_contratacion"] == "Ministerio de Hacienda"
    assert fila["tecnologia"] == "SAP"


def test_load_licitadores_filtra_por_ccaa():
    _seed_licitacion("ADJ-CCAA-MAD")
    _seed_adjudicacion("ADJ-CCAA-MAD", ccaa="Madrid")
    _seed_licitacion("ADJ-CCAA-CAT")
    _seed_adjudicacion("ADJ-CCAA-CAT", nombre="Empresa Catalana", ccaa="Cataluña")

    from services.adjudicaciones import load_licitadores

    rows = load_licitadores(ccaa_filter=("Madrid",))
    ids = {r["licitacion_id"] for r in rows}
    assert "ADJ-CCAA-MAD" in ids
    assert "ADJ-CCAA-CAT" not in ids
