"""``PursuitRepository.deadline_rows`` contra Postgres: el horizonte del recurso.

El plazo para recurrir los pliegos corre desde la publicación, no desde la
presentación. Una oportunidad cuyo expediente se publicó hace poco tiene que
llegar a los recordatorios aunque su presentación quede a 60 días, fuera del
rango de ``fecha_limite``; y sin ``publicadas_desde`` la consulta se queda como
estaba.
"""

from __future__ import annotations

from typing import Any

import pytest

from db.repositories.organizations import OrganizationRepository
from db.repositories.pursuits import PursuitRepository
from shared.dto import PursuitCreate

_RECIENTE = "LIC-REC-RECIENTE"
_ANTIGUA = "LIC-REC-ANTIGUA"


def _licitacion(id_externo: str, *, publicada: str) -> None:
    from db.database import connect

    with connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_publicacion, fecha_limite, "
            "fecha_extraccion) VALUES (%s, %s, %s, %s, %s)",
            (
                id_externo,
                f"Expediente {id_externo}",
                publicada,
                "2027-01-30T10:00:00+00:00",
                "2026-11-01T10:00:00+00:00",
            ),
        )


@pytest.fixture()
def oportunidades(tmp_db: Any) -> None:
    from db.users import create_user
    from services.pursuits import create_pursuit

    hash_falso = "test-hash"  # pragma: allowlist secret
    owner = create_user(email="recurso@example.test", password_hash=hash_falso)
    organizacion = int(OrganizationRepository().create_organization("Equipo recurso", owner)["id"])
    _licitacion(_RECIENTE, publicada="2026-11-25")
    _licitacion(_ANTIGUA, publicada="2026-09-01")
    for licitacion_id in (_RECIENTE, _ANTIGUA):
        create_pursuit(
            owner,
            PursuitCreate(
                licitacion_id=licitacion_id,
                organization_id=organizacion,
                responsible_user_id=owner,
            ),
        )


def _ids(**kwargs: Any) -> set[str]:
    return {fila["licitacion_id"] for fila in PursuitRepository().deadline_rows(**kwargs)}


def test_lo_publicado_desde_el_horizonte_entra_aunque_cierre_lejos(oportunidades: None) -> None:
    filas = PursuitRepository().deadline_rows(
        desde="2026-12-01", hasta="2026-12-31", publicadas_desde="2026-11-01"
    )

    assert {f["licitacion_id"] for f in filas} == {_RECIENTE}
    assert filas[0]["fecha_publicacion"] == "2026-11-25"


def test_sin_publicadas_desde_solo_cuenta_el_rango_de_fechas(oportunidades: None) -> None:
    assert _ids(desde="2026-12-01", hasta="2026-12-31") == set()
