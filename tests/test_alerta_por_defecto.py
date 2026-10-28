"""Alerta por defecto (D53, B1 del plan 2026-10), contra Postgres.

Guardar el ámbito de una organización sin reglas le crea una alerta diaria a
nombre de quien guarda; volver a guardar no la duplica, y borrarla es una baja
definitiva. ``scripts/crear_alertas_por_defecto.py`` hace lo mismo con las
organizaciones que ya existían. Lo puro (qué reglas salen del ámbito) está en
``tests/test_unit_alerta_por_defecto.py``.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from db.database import connect_read
from db.repositories.organizations import OrganizationRepository
from services.organizations import update_settings
from services.watchlist_rules import WatchlistRule, create_rule, delete_rule
from shared.dto import OrganizationSettings
from shared.identity import user_key_from_email


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(
        email=email,
        password_hash="test-hash",  # pragma: allowlist secret
        display_name=email.split("@")[0],
    )


@pytest.fixture()
def equipo(api_db: Any) -> dict[str, int]:
    owner = _user("alerta-owner@example.test")
    admin = _user("alerta-admin@example.test")
    organizations = OrganizationRepository()
    org = int(organizations.create_organization("Equipo con alerta", owner)["id"])
    organizations.add_membership(org, admin, "admin")
    return {"owner": owner, "admin": admin, "org": org}


def _reglas(org: int) -> list[dict[str, Any]]:
    with connect_read() as c:
        cur = c.execute(
            "SELECT id, user_id, user_key, nombre, tecnologia, cpv, ccaa, frequency, active, "
            "email, visibility FROM watchlist_rules WHERE organization_id = %s ORDER BY id",
            (org,),
        )
        nombres = [d[0] for d in cur.description]
        return [dict(zip(nombres, fila, strict=True)) for fila in cur.fetchall()]


def test_guardar_las_tecnologias_crea_la_alerta_de_quien_guarda(equipo: dict[str, int]) -> None:
    update_settings(
        equipo["admin"],
        equipo["org"],
        OrganizationSettings(tecnologias=["SAP", "ORACLE"], cpvs=["72"], ccaas=["Madrid"]),
    )

    reglas = _reglas(equipo["org"])
    assert [r["tecnologia"] for r in reglas] == ["SAP", "ORACLE"]
    for regla in reglas:
        assert regla["user_id"] == equipo["admin"]
        assert regla["user_key"] == user_key_from_email(
            "alerta-admin@example.test", equipo["admin"]
        )
        assert regla["email"] == "alerta-admin@example.test"
        assert regla["visibility"] == "private"
        assert (regla["frequency"], regla["active"]) == ("daily", 1)
        assert (regla["cpv"], regla["ccaa"]) == ("72", "Madrid")


def test_la_alerta_se_ve_en_mi_watchlist_de_quien_guarda(equipo: dict[str, int]) -> None:
    """Lo que lista /mi-watchlist: ``list_rules`` con la identidad del login."""
    from services.watchlist_rules import list_rules

    update_settings(equipo["owner"], equipo["org"], OrganizationSettings(tecnologias=["SAP"]))

    clave = user_key_from_email("alerta-owner@example.test", equipo["owner"])
    (regla,) = list_rules(clave, equipo["org"], user_id=equipo["owner"])
    assert regla.tecnologia == "SAP"
    # El admin no la ve: es privada de quien la recibe.
    clave_admin = user_key_from_email("alerta-admin@example.test", equipo["admin"])
    assert list_rules(clave_admin, equipo["org"], user_id=equipo["admin"]) == []


def test_volver_a_guardar_no_duplica(equipo: dict[str, int]) -> None:
    ajustes = OrganizationSettings(tecnologias=["SAP"])
    update_settings(equipo["owner"], equipo["org"], ajustes)
    update_settings(equipo["owner"], equipo["org"], ajustes)
    update_settings(equipo["admin"], equipo["org"], OrganizationSettings(tecnologias=["IBM"]))

    assert [r["tecnologia"] for r in _reglas(equipo["org"])] == ["SAP"]


def test_borrarla_es_una_baja_definitiva(equipo: dict[str, int]) -> None:
    update_settings(equipo["owner"], equipo["org"], OrganizationSettings(tecnologias=["SAP"]))
    (regla,) = _reglas(equipo["org"])
    clave = user_key_from_email("alerta-owner@example.test", equipo["owner"])
    assert delete_rule(clave, int(regla["id"]), equipo["org"], user_id=equipo["owner"])

    update_settings(equipo["owner"], equipo["org"], OrganizationSettings(tecnologias=["SAP"]))
    assert _reglas(equipo["org"]) == []


def test_con_alguna_regla_en_la_organizacion_no_crea(equipo: dict[str, int]) -> None:
    clave = user_key_from_email("alerta-admin@example.test", equipo["admin"])
    create_rule(
        clave,
        WatchlistRule(nombre="La mía", keyword="erp"),
        user_id=equipo["admin"],
        organization_id=equipo["org"],
    )

    update_settings(equipo["owner"], equipo["org"], OrganizationSettings(tecnologias=["SAP"]))

    assert [r["nombre"] for r in _reglas(equipo["org"])] == ["La mía"]


def test_sin_tecnologias_ni_cpvs_no_crea(equipo: dict[str, int]) -> None:
    update_settings(equipo["owner"], equipo["org"], OrganizationSettings(ccaas=["Madrid"]))
    assert _reglas(equipo["org"]) == []


def test_el_script_cuenta_sin_escribir_y_aplica_al_owner(equipo: dict[str, int]) -> None:
    # Una organización configurada antes de B1: tecnologías guardadas, sin alerta.
    OrganizationRepository().update_settings(equipo["org"], {"tecnologias": ["SAP"]})
    script = importlib.import_module("scripts.crear_alertas_por_defecto")

    cuenta = script.recorrer(aplicar=False)
    assert [p["organization_id"] for p in cuenta["pendientes"]] == [equipo["org"]]
    assert cuenta["reglas_creadas"] == 0
    assert _reglas(equipo["org"]) == []

    aplicado = script.recorrer(aplicar=True)
    assert aplicado["reglas_creadas"] == 1
    (regla,) = _reglas(equipo["org"])
    assert regla["user_id"] == equipo["owner"]
    assert regla["tecnologia"] == "SAP"

    # Idempotente: la segunda pasada ya no encuentra nada que hacer.
    otra = script.recorrer(aplicar=True)
    assert otra["pendientes"] == []
    assert otra["ya_tuvo_alerta"] >= 1
    assert len(_reglas(equipo["org"])) == 1
