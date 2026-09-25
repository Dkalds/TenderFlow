"""«Contra mí» cruza todas las identidades del competidor, no sólo la de la ficha.

Competencia cuenta como un solo competidor las identidades del maestro que
comparten NIF o nombre normalizado, y la ficha suma la actividad de todas
(`empresa_ids`). «Contra mí» recibía una sola clave: los expedientes que ganó
la otra identidad sólo aparecían si la de la ficha también tenía una
adjudicación en ellos, y entonces contaban como «perdimos» a secas, no como
victoria suya.

Fija las cuatro capas: la clasificación, el cableado del servicio, la consulta
contra Postgres y la ruta.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from services.competitive.batallas import BatallasContraMi, batallas_de_usuario, construir_batallas
from services.pursuit_awards import IdentidadFiscal


def _cruce(adjudicatario: str, **campos: Any) -> dict[str, Any]:
    return {
        "licitacion_id": f"LIC-{adjudicatario}",
        "importe": 100000.0,
        "offer_price_eur": 90000.0,
        "importe_adjudicado": 88000.0,
        "outcome": "lost",
        "adjudicatario_key": adjudicatario,
        **campos,
    }


# ── Clasificación ───────────────────────────────────────────────────────────


def test_lo_que_gana_otra_identidad_del_grupo_es_victoria_suya() -> None:
    resultado = construir_batallas("7", [_cruce("8")], grupo=["8"])
    assert resultado.batallas[0].resultado == "ellos_ganaron"


def test_sin_grupo_la_otra_identidad_cuenta_como_un_tercero() -> None:
    resultado = construir_batallas("7", [_cruce("8")])
    assert resultado.batallas[0].resultado == "perdimos"


def test_con_grupo_un_tercero_sigue_siendo_un_tercero() -> None:
    resultado = construir_batallas("7", [_cruce("9")], grupo=["8"])
    assert resultado.batallas[0].resultado == "perdimos"


def test_declara_las_claves_cruzadas_sin_repetir() -> None:
    # La ficha manda el grupo entero, con su propio id dentro.
    assert construir_batallas("7", [], grupo=["7", "8", "8", ""]).claves == ["7", "8"]
    assert construir_batallas("7", []).claves == ["7"]


# ── Servicio ────────────────────────────────────────────────────────────────


def test_batallas_de_usuario_consulta_todas_las_claves() -> None:
    with (
        patch("services.organizations.resolve_organization", return_value=(5, "owner")),
        patch(
            "db.repositories.pursuits.PursuitRepository.cruces_con_competidor",
            return_value=[_cruce("8")],
        ) as cruces,
        patch("services.pursuit_awards.identidad_fiscal", return_value=IdentidadFiscal()),
    ):
        resultado = batallas_de_usuario(3, "7", organization_id=5, grupo=["7", "8"])

    assert cruces.call_args.args == (5, ("7", "8"))
    assert resultado.claves == ["7", "8"]
    assert resultado.batallas[0].resultado == "ellos_ganaron"


# ── Consulta ────────────────────────────────────────────────────────────────


def _organizacion(nombre: str) -> int:
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    owner = create_user(
        email=f"{nombre}@example.test",
        password_hash="test-hash",  # pragma: allowlist secret -- literal de test
        display_name=nombre,
    )
    return int(OrganizationRepository().create_organization(nombre, owner)["id"])


def _expediente_presentado(
    organization_id: int, licitacion_id: str, nif_adjudicatario: str
) -> None:
    """Un expediente al que presentamos oferta y que se adjudicó a ese NIF.

    Sin `empresa_id` en la adjudicación, la clave del competidor es su NIF
    normalizado (`empresa_key_sql`): la consulta es la misma que con ids.
    """
    from db.database import connect
    from db.upsert import (
        Adjudicacion,
        Licitacion,
        replace_adjudicaciones_batch,
        upsert_licitaciones,
    )

    upsert_licitaciones(
        [Licitacion(id_externo=licitacion_id, titulo=f"Servicio {licitacion_id}", importe=100000.0)]
    )
    _total, _descartadas, fallidas = replace_adjudicaciones_batch(
        {
            licitacion_id: [
                Adjudicacion(
                    licitacion_id=licitacion_id,
                    nombre=f"Adjudicataria {nif_adjudicatario}",
                    nif=nif_adjudicatario,
                    importe_adjudicado=88000.0,
                    fecha_adjudicacion="2026-06-01",
                )
            ]
        }
    )
    assert fallidas == 0
    with connect() as c:
        c.execute(
            "INSERT INTO pursuits (organization_id, licitacion_id, status, outcome, "
            " offer_price_eur, identified_at, submitted_at, created_at, updated_at) "
            "VALUES (%s, %s, 'lost', 'lost', 90000, '2026-05-01', '2026-05-15', "
            " '2026-05-01', '2026-06-02')",
            (organization_id, licitacion_id),
        )


def test_la_consulta_cruza_las_adjudicaciones_de_todas_las_claves(tmp_db) -> None:
    from db.repositories.pursuits import PursuitRepository

    equipo = _organizacion("contra-mi-grupo")
    _expediente_presentado(equipo, "GRP-1", "A11111111")
    _expediente_presentado(equipo, "GRP-2", "B22222222")
    _expediente_presentado(equipo, "GRP-3", "C33333333")

    repo = PursuitRepository()
    grupo = repo.cruces_con_competidor(equipo, ["A11111111", "B22222222"], desde_iso="2026-01-01")
    solo_una = repo.cruces_con_competidor(equipo, ["A11111111"], desde_iso="2026-01-01")

    assert sorted(fila["licitacion_id"] for fila in grupo) == ["GRP-1", "GRP-2"]
    assert [fila["licitacion_id"] for fila in solo_una] == ["GRP-1"]
    assert repo.cruces_con_competidor(equipo, [], desde_iso="2026-01-01") == []


# ── Ruta ────────────────────────────────────────────────────────────────────


def test_la_ruta_pasa_el_grupo_al_servicio(client, auth) -> None:
    with patch(
        "api.routes.competitive.batallas_de_usuario",
        return_value=BatallasContraMi(empresa_key="7", claves=["7", "8"]),
    ) as servicio:
        r = client.get(
            "/api/v1/competitive/empresas/7/contra-mi?empresa_ids=7,8&meses=12",
            headers=auth,
        )

    assert r.status_code == 200, r.text
    assert r.json()["claves"] == ["7", "8"]
    assert servicio.call_args.kwargs["grupo"] == ["7", "8"]
    assert servicio.call_args.kwargs["meses"] == 12


def test_la_ruta_sin_grupo_cruza_solo_la_clave_pedida(client, auth) -> None:
    with patch(
        "api.routes.competitive.batallas_de_usuario",
        return_value=BatallasContraMi(empresa_key="7", claves=["7"]),
    ) as servicio:
        r = client.get("/api/v1/competitive/empresas/7/contra-mi", headers=auth)

    assert r.status_code == 200, r.text
    assert servicio.call_args.kwargs["grupo"] == []


def test_la_ruta_rechaza_ids_que_no_son_numeros(client, auth) -> None:
    r = client.get("/api/v1/competitive/empresas/7/contra-mi?empresa_ids=7,abc", headers=auth)
    assert r.status_code == 400
