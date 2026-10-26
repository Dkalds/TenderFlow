"""Alerta por defecto (D53, B1 del plan 2026-10): qué reglas salen del ámbito.

Sin base de datos: ``reglas_por_defecto`` es pura, y la escritura se sustituye
por un doble para fijar a nombre de quién y con qué queda la regla. La
idempotencia contra Postgres la fija ``tests/test_alerta_por_defecto.py``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import services.watchlist_rules as mod
from shared.dto import OrganizationSettings


def test_una_regla_diaria_por_tecnologia() -> None:
    reglas = mod.reglas_por_defecto(OrganizationSettings(tecnologias=["sap", "Oracle"]))
    assert [r.tecnologia for r in reglas] == ["SAP", "ORACLE"]
    assert {r.frequency for r in reglas} == {"daily"}
    assert all(r.active for r in reglas)
    assert [r.nombre for r in reglas] == [
        "Alerta por defecto · SAP",
        "Alerta por defecto · ORACLE",
    ]
    # Sin CPV, CCAA ni importe declarados, la regla no filtra por ellos.
    assert all(r.cpv is None and r.ccaa is None and r.min_importe is None for r in reglas)


def test_cpv_y_ccaa_solo_si_hay_uno() -> None:
    """La regla guarda un valor; con varios declarados no filtra por ese campo."""
    uno = mod.reglas_por_defecto(
        OrganizationSettings(tecnologias=["SAP"], cpvs=["72"], ccaas=["Madrid"])
    )
    assert (uno[0].cpv, uno[0].ccaa) == ("72", "Madrid")

    varios = mod.reglas_por_defecto(
        OrganizationSettings(tecnologias=["SAP"], cpvs=["72", "48"], ccaas=["Madrid", "Galicia"])
    )
    assert (varios[0].cpv, varios[0].ccaa) == (None, None)


def test_el_importe_minimo_se_copia() -> None:
    (regla,) = mod.reglas_por_defecto(
        OrganizationSettings(tecnologias=["SAP"], importe_min=100_000)
    )
    assert regla.min_importe == 100_000
    (sin_minimo,) = mod.reglas_por_defecto(OrganizationSettings(tecnologias=["SAP"], importe_min=0))
    assert sin_minimo.min_importe is None


def test_como_mucho_cinco_reglas_en_el_orden_guardado() -> None:
    tecnologias = ["SAP", "ORACLE", "MICROSOFT", "SALESFORCE", "SERVICENOW", "WORKDAY", "IBM"]
    reglas = mod.reglas_por_defecto(OrganizationSettings(tecnologias=tecnologias))
    assert len(reglas) == mod.MAX_REGLAS_POR_DEFECTO == 5
    assert [r.tecnologia for r in reglas] == tecnologias[:5]


def test_sin_tecnologias_una_por_cpv() -> None:
    reglas = mod.reglas_por_defecto(OrganizationSettings(cpvs=["72", "48"], ccaas=["Madrid"]))
    assert [(r.cpv, r.tecnologia, r.ccaa) for r in reglas] == [
        ("72", None, "Madrid"),
        ("48", None, "Madrid"),
    ]
    assert reglas[0].nombre == "Alerta por defecto · CPV 72"


def test_sin_tecnologias_ni_cpvs_ninguna() -> None:
    """Una regla sin criterio casaría con el corpus entero."""
    assert mod.reglas_por_defecto(OrganizationSettings()) == []
    assert mod.reglas_por_defecto(OrganizationSettings(ccaas=["Madrid"], importe_min=1)) == []


def test_queda_a_nombre_de_quien_guarda_privada_y_con_su_correo() -> None:
    with (
        patch("db.users.get_user_by_id", return_value={"email": "owner@example.test"}),
        patch.object(mod, "crear_reglas_por_defecto", return_value=[41]) as crear,
    ):
        ids = mod.asegurar_alerta_por_defecto(7, 3, OrganizationSettings(tecnologias=["SAP"]))

    assert ids == [41]
    args: Any = crear.call_args
    organization_id, clave, valores = args.args
    assert organization_id == 7
    assert args.kwargs["user_id"] == 3
    assert args.kwargs["email"] == "owner@example.test"
    # La clave heredada es la del login de esa persona (ADR-030, escritura dual).
    from shared.identity import user_key_from_email

    assert clave == user_key_from_email("owner@example.test", 3)
    (valor,) = valores
    assert valor["tecnologia"] == "SAP"
    assert valor["frequency"] == "daily"
    assert valor["active"] == 1


def test_sin_correo_no_crea_nada() -> None:
    with (
        patch("db.users.get_user_by_id", return_value={"email": None}),
        patch.object(mod, "crear_reglas_por_defecto") as crear,
    ):
        assert (
            mod.asegurar_alerta_por_defecto(7, 3, OrganizationSettings(tecnologias=["SAP"])) == []
        )
    crear.assert_not_called()


def test_sin_ambito_ni_siquiera_lee_al_usuario() -> None:
    with (
        patch("db.users.get_user_by_id") as leer,
        patch.object(mod, "crear_reglas_por_defecto") as crear,
    ):
        assert mod.asegurar_alerta_por_defecto(7, 3, OrganizationSettings()) == []
    leer.assert_not_called()
    crear.assert_not_called()
