"""Dirección por HTTP: la ventana, la carga del equipo y el feed con sus cambios.

Los tests de ``test_direccion_tarjetas.py`` ejercitan las funciones puras; aquí
se fija el contrato de las rutas contra Postgres:

- ``/pursuits/direccion/carga`` responde y **no** la tapa ``/pursuits/{id}``
  (FastAPI casa rutas en orden, y un segmento literal declarado después de
  uno con parámetro devolvería 422).
- La carga tiene el mismo permiso que el cuadro: un `member` recibe 403.
- La ventana del cuadro se aplica en el servidor y una ventana invertida es
  un 422, no un cuadro vacío.
- El feed publica qué cambió, leído del ``payload_json`` del ledger.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest


def _ctx(user_id: int, email: str) -> dict[str, Any]:
    from shared.identity import user_key_from_email

    return {
        "user_id": user_id,
        "email": email,
        "display_name": email.split("@")[0],
        "is_admin": False,
        "auth_method": "session",
        "authenticated_at": datetime.now(UTC).isoformat(),
        "user_key": user_key_from_email(email, user_id),
    }


def _sembrar(db_mod: Any) -> dict[str, int]:
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    owner = create_user(
        email="dir-owner@example.test", password_hash="x"
    )  # pragma: allowlist secret
    member = create_user(
        email="dir-member@example.test", password_hash="x"
    )  # pragma: allowlist secret
    repo = OrganizationRepository()
    org = int(repo.create_organization("Equipo Dirección", owner)["id"])
    repo.add_membership(org, member, "member")

    with db_mod.connect() as c:
        for i, (status, outcome, closed_at) in enumerate(
            [
                ("won", "won", "2026-03-01T10:00:00+00:00"),
                ("lost", "lost", "2024-03-01T10:00:00+00:00"),
                ("preparing", "pending", None),
            ]
        ):
            id_externo = f"DIR-{i}"
            c.execute(
                "INSERT INTO licitaciones (id_externo, titulo, fecha_limite, fecha_extraccion) "
                "VALUES (%s, %s, %s, %s)",
                (id_externo, f"Expediente {i}", "2026-10-15", "2026-01-01T00:00:00+00:00"),
            )
            c.execute(
                "INSERT INTO pursuits (licitacion_id, organization_id, responsible_user_id, "
                " status, outcome, identified_at, closed_at, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    id_externo,
                    org,
                    owner,
                    status,
                    outcome,
                    "2024-01-01T00:00:00+00:00",
                    closed_at,
                    "2024-01-01T00:00:00+00:00",
                    "2024-01-01T00:00:00+00:00",
                ),
            )
        pursuit = int(
            c.execute("SELECT id FROM pursuits WHERE licitacion_id = 'DIR-2'").fetchone()[0]
        )
        c.execute(
            "INSERT INTO pursuit_events (pursuit_id, organization_id, event_type, "
            " actor_user_id, payload_json, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                pursuit,
                org,
                "pursuit.updated",
                owner,
                json.dumps(
                    {
                        "changes": {
                            "status": {"from": "qualifying", "to": "preparing"},
                            "outcome_reason": {"from": None, "to": "nota libre"},
                        }
                    }
                ),
                "2026-10-01T09:00:00+00:00",
            ),
        )
    return {"owner": owner, "member": member, "org": org}


@pytest.fixture
def direccion(client: Any, api_db: Any, tmp_db: Any) -> Iterator[tuple[Any, dict[str, int]]]:
    from api.app import app
    from api.routes.dual_auth import require_any_auth

    db_mod, _ = tmp_db
    semilla = _sembrar(db_mod)
    app.dependency_overrides[require_any_auth] = lambda: _ctx(
        semilla["owner"], "dir-owner@example.test"
    )
    try:
        yield client, semilla
    finally:
        app.dependency_overrides.pop(require_any_auth, None)


def _como(user_id: int, email: str) -> None:
    from api.app import app
    from api.routes.dual_auth import require_any_auth

    app.dependency_overrides[require_any_auth] = lambda: _ctx(user_id, email)


def test_la_carga_responde_y_no_la_tapa_la_ruta_por_id(direccion: Any) -> None:
    cliente, s = direccion
    resp = cliente.get("/api/v1/pursuits/direccion/carga", params={"organization_id": s["org"]})
    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["total_abiertas"] == 1
    personas = {r["user_id"]: r for r in cuerpo["responsables"]}
    # El member sale aunque no tenga nada: estar libre es parte de la respuesta.
    assert personas[s["member"]]["abiertas"] == 0
    assert personas[s["owner"]]["abiertas"] == 1


def test_un_member_no_ve_la_carga(direccion: Any) -> None:
    cliente, s = direccion
    _como(s["member"], "dir-member@example.test")
    resp = cliente.get("/api/v1/pursuits/direccion/carga", params={"organization_id": s["org"]})
    assert resp.status_code == 403


def test_la_ventana_del_cuadro_es_de_cierres(direccion: Any) -> None:
    cliente, s = direccion
    historico = cliente.get("/api/v1/pursuits/direccion", params={"organization_id": s["org"]})
    assert historico.status_code == 200, historico.text
    assert historico.json()["cierres"] == 2
    assert historico.json()["anterior_desde"] is None

    ventana = cliente.get(
        "/api/v1/pursuits/direccion",
        params={"organization_id": s["org"], "period_from": "2026-01-01T00:00:00Z"},
    )
    assert ventana.status_code == 200, ventana.text
    cuerpo = ventana.json()
    # Identificadas las dos en 2024; sólo una se cerró dentro de la ventana.
    assert cuerpo["cierres"] == 1
    assert cuerpo["cierres_historico"] == 2
    assert cuerpo["anterior_desde"].startswith("2025-01-01")
    assert [t["clave"] for t in cuerpo["tarjetas"]] == [
        "importe_adjudicado",
        "tasa_exito",
        "valor_ponderado",
        "ciclo_dias",
    ]


def test_una_ventana_invertida_es_un_422(direccion: Any) -> None:
    cliente, s = direccion
    resp = cliente.get(
        "/api/v1/pursuits/direccion",
        params={
            "organization_id": s["org"],
            "period_from": "2026-06-01T00:00:00Z",
            "period_to": "2026-01-01T00:00:00Z",
        },
    )
    assert resp.status_code == 422


def test_el_feed_dice_que_cambio(direccion: Any) -> None:
    cliente, s = direccion
    resp = cliente.get("/api/v1/pursuits/actividad", params={"organization_id": s["org"]})
    assert resp.status_code == 200, resp.text
    item = resp.json()["items"][0]
    # El texto libre (`outcome_reason`) no se publica; el cambio de etapa sí.
    assert item["cambios"] == [{"campo": "status", "desde": "qualifying", "hasta": "preparing"}]


@pytest.mark.parametrize(
    "params",
    [
        # Una fecha sin zona y otra con ella: comparadas tal cual darían 500.
        {"period_from": "2026-01-01T00:00:00", "period_to": "2026-06-01T00:00:00Z"},
        # El año 1 no tiene año anterior con el que comparar.
        {"period_from": "0001-01-01T00:00:00Z"},
    ],
)
def test_las_ventanas_extremas_no_son_un_500(direccion: Any, params: dict[str, str]) -> None:
    cliente, s = direccion
    resp = cliente.get("/api/v1/pursuits/direccion", params={"organization_id": s["org"], **params})
    assert resp.status_code == 200, resp.text
