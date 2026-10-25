"""``db.notifications.listar_alertas``: la lista completa de la campana.

Es la lectura de «Ver todas»: lo que el canal ``in_app`` dejó en
``user_notifications`` para una persona en una organización, paginado y con
filtro leído/no leído. Lo que se fija aquí:

- el filtro ``sin_leer``/``leidas``/``todas`` y el total de cada uno;
- ``sin_leer`` cuenta las no leídas aunque el filtro pida otra cosa (es el
  número del distintivo, no el de la página);
- el orden cronológico estable: marcar una como leída no la mueve de página;
- la frontera de persona y de organización.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def organizaciones(tmp_db) -> tuple[int, int]:
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    duena = create_user(
        email="campana-owner@example.test", password_hash="x"
    )  # pragma: allowlist secret
    repo = OrganizationRepository()
    una = int(repo.create_organization("Equipo campana", duena)["id"])
    otra = int(repo.create_organization("Otro equipo", duena)["id"])
    return una, otra


def _aviso(clave: str, org: int, n: int, *, leida: bool = False, user_id: int | None = None) -> int:
    from db.database import connect
    from db.notifications import insert_user_notification

    assert insert_user_notification(
        user_key=clave,
        user_id=user_id,
        type_=f"rule_match:{n}",
        title=f"Aviso {n}",
        body=None,
        licitacion_id=f"EXP-{n}",
        organization_id=org,
        # Marcas fijas: el orden no puede depender de la velocidad del test.
        created_at=f"2026-10-{n:02d}T09:00:00+00:00",
    )
    with connect() as c:
        # Con ``user_id`` la fila nace sin clave (v161): se localiza por el id.
        fila = c.execute(
            "SELECT id FROM user_notifications WHERE type = %s "
            "AND (user_id = %s OR (user_id IS NULL AND user_key = %s))",
            (f"rule_match:{n}", user_id, clave),
        ).fetchone()
        assert fila is not None
        if leida:
            c.execute(
                "UPDATE user_notifications SET read_at = %s WHERE id = %s",
                ("2026-10-20T10:00:00+00:00", fila[0]),
            )
    return int(fila[0])


def test_filtra_por_leidas_y_cuenta_cada_universo(organizaciones):
    from db.notifications import listar_alertas

    org, _ = organizaciones
    for n in (1, 2, 3):
        _aviso("ana", org, n)
    for n in (4, 5):
        _aviso("ana", org, n, leida=True)

    todas = listar_alertas("ana", org, estado="todas", limit=10, offset=0)
    assert todas["total"] == 5
    assert todas["sin_leer"] == 3
    # Cronológico, lo más reciente arriba.
    assert [a["title"] for a in todas["items"]] == [f"Aviso {n}" for n in (5, 4, 3, 2, 1)]

    sin_leer = listar_alertas("ana", org, estado="sin_leer", limit=10, offset=0)
    assert sin_leer["total"] == 3
    assert {a["title"] for a in sin_leer["items"]} == {"Aviso 1", "Aviso 2", "Aviso 3"}
    assert all(a["read_at"] is None for a in sin_leer["items"])

    leidas = listar_alertas("ana", org, estado="leidas", limit=10, offset=0)
    assert leidas["total"] == 2
    # El distintivo no depende del filtro.
    assert leidas["sin_leer"] == 3


def test_pagina_sin_saltos_aunque_cambie_el_estado_de_lectura(organizaciones):
    from db.notifications import listar_alertas
    from services.notifications import mark_alerts_read

    org, _ = organizaciones
    ids = {n: _aviso("ana", org, n) for n in range(1, 6)}

    primera = listar_alertas("ana", org, estado="todas", limit=2, offset=0)
    assert [a["title"] for a in primera["items"]] == ["Aviso 5", "Aviso 4"]

    # Abrir uno de la primera página no reordena: la segunda sigue donde estaba.
    mark_alerts_read("ana", [ids[5]], org)
    segunda = listar_alertas("ana", org, estado="todas", limit=2, offset=2)
    assert [a["title"] for a in segunda["items"]] == ["Aviso 3", "Aviso 2"]
    assert segunda["total"] == 5
    assert segunda["sin_leer"] == 4


def test_no_mezcla_personas_ni_organizaciones(organizaciones):
    from db.notifications import listar_alertas

    org, otra = organizaciones
    _aviso("ana", org, 1)
    _aviso("bea", org, 2)
    _aviso("ana", otra, 3)

    pagina = listar_alertas("ana", org, estado="todas", limit=10, offset=0)
    assert [a["title"] for a in pagina["items"]] == ["Aviso 1"]
    assert pagina["total"] == 1
    assert pagina["sin_leer"] == 1


def test_trae_la_oportunidad_del_expediente_si_existe(organizaciones):
    """Mismo enlace que la vista previa: a la ficha de la oportunidad."""
    from db.database import connect
    from db.notifications import listar_alertas

    org, _ = organizaciones
    _aviso("ana", org, 7)
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) VALUES (%s, %s, %s)",
            ("EXP-7", "Expediente siete", "2026-10-01"),
        )
        fila = c.execute(
            "INSERT INTO pursuits (organization_id, licitacion_id, status, created_at, "
            " updated_at) VALUES (%s, %s, 'identified', '2026-10-01', '2026-10-01') RETURNING id",
            (org, "EXP-7"),
        ).fetchone()
    assert fila is not None

    (alerta,) = listar_alertas("ana", org, estado="todas", limit=10, offset=0)["items"]
    assert alerta["pursuit_id"] == int(fila[0])


def test_identidad_dual_por_user_id(organizaciones):
    """Tras un cambio de correo la clave cambia; el id no (ADR-030)."""
    from db.notifications import listar_alertas
    from db.users import create_user

    org, _ = organizaciones
    uid = create_user(email="dual@example.test", password_hash="x")  # pragma: allowlist secret
    _aviso("clave-antigua", org, 1, user_id=uid)

    pagina = listar_alertas("clave-nueva", org, user_id=uid, estado="todas", limit=10, offset=0)
    assert pagina["total"] == 1
