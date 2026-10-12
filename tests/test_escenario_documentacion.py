"""Escenario de la documentación acreditativa: declararla y enterarse antes de que caduque.

Recorrido completo por la API con sesión real. Ver ``tests/escenarios.py`` y
``docs/casos-de-uso.md``.

El aviso no lo pide nadie: lo escribe el paso ``documentacion_avisos`` del
cierre de la pasada y lo reparte el despachador del outbox. El escenario los
corre a mano, en ese orden, como lo haría la pasada.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tests.escenarios import abrir_sesion

HOY = datetime.now(UTC).date()


def _dentro_de(dias: int) -> str:
    return (HOY + timedelta(days=dias)).isoformat()


def _pasada() -> None:
    """El cierre: el paso diario escribe en el outbox y el despachador reparte."""
    from scheduler.jobs.event_dispatch import dispatch_pending
    from scheduler.pipeline_runs import _run_documentacion_avisos

    assert _run_documentacion_avisos() == "ok"
    dispatch_pending()


def _bandeja(sesion, oid: int) -> list[dict]:
    respuesta = sesion.get("/notifications/alerts", params={"organization_id": oid})
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()["items"]


def test_cu30_la_documentacion_avisa_antes_de_caducar_a_quien_la_renueva(client, api_db):
    """CU-30 — tipos de documento, estado por vigencia y avisos de caducidad una sola vez."""
    from services.documentacion_caducidad import emitir_avisos_de_caducidad

    duena = abrir_sesion("docs-duena@example.com", client, nombre="Duena")
    admin = abrir_sesion("docs-admin@example.com", nombre="Admin")
    miembro = abrir_sesion("docs-miembro@example.com", nombre="Miembro")
    equipo = duena.post("/organizations", json={"name": "Integradora Docs"})
    assert equipo.status_code == 201, equipo.text
    oid = equipo.json()["id"]
    for sesion, rol in ((admin, "admin"), (miembro, "member")):
        alta = duena.post(
            f"/organizations/{oid}/members", json={"email": sesion.email, "role": rol}
        )
        assert alta.status_code == 201, alta.text

    # La documentación administrativa no la acredita una persona.
    rechazo = duena.put(
        f"/organizations/{oid}/capabilities",
        json={"certificaciones": [{"nombre": "AEAT", "tipo": "corriente_aeat", "ambito": "team"}]},
    )
    assert rechazo.status_code == 422, rechazo.text

    perfil = {
        "certificaciones": [
            {"nombre": "ISO/IEC 27001", "vigente_hasta": _dentro_de(400)},
            {
                "nombre": "Certificado AEAT",
                "tipo": "corriente_aeat",
                "vigente_hasta": _dentro_de(20),
            },
            {
                "nombre": "Certificado Seguridad Social",
                "tipo": "corriente_seguridad_social",
                "vigente_hasta": _dentro_de(-3),
            },
            {"nombre": "Inscripción ROLECE", "tipo": "rolece"},
        ]
    }
    guardado = duena.put(f"/organizations/{oid}/capabilities", json=perfil)
    assert guardado.status_code == 200, guardado.text

    # Cualquiera del equipo ve el estado de cada documento, por la próxima caducidad.
    leido = miembro.get(f"/organizations/{oid}/capabilities")
    assert leido.status_code == 200, leido.text
    assert [(v["nombre"], v["estado"], v["dias_restantes"]) for v in leido.json()["vigencias"]] == [
        ("Certificado Seguridad Social", "caducado", -3),
        ("Certificado AEAT", "caduca_pronto", 20),
        ("ISO/IEC 27001", "vigente", 400),
        ("Inscripción ROLECE", "sin_caducidad", None),
    ]

    # La admin no quiere estos avisos en la campana: lo dice en Ajustes.
    apagado = admin.put(
        "/me/notification-preferences",
        json=[{"tipo": "organizacion.documento_caduca", "canal": "in_app", "frecuencia": "off"}],
    )
    assert apagado.status_code == 200, apagado.text

    _pasada()

    avisos = {a["title"]: a for a in _bandeja(duena, oid)}
    assert set(avisos) == {
        "Caduca en 20 días: Certificado AEAT",
        "Ha caducado: Certificado Seguridad Social",
    }
    assert all(a["type"].startswith("documentacion_caduca:") for a in avisos.values())
    assert all(a["licitacion_id"] is None and not a["read"] for a in avisos.values())
    # Ni a quien lo apagó ni a quien no puede renovarlo.
    assert _bandeja(admin, oid) == []
    assert _bandeja(miembro, oid) == []

    # Una vez por umbral y documento: otra pasada el mismo día no repite.
    assert emitir_avisos_de_caducidad() == 0

    # Renovado: deja de estar a punto de caducar y no hay nada que avisar.
    perfil["certificaciones"][1]["vigente_hasta"] = _dentro_de(300)
    renovado = duena.put(f"/organizations/{oid}/capabilities", json=perfil)
    assert renovado.status_code == 200, renovado.text
    aeat = next(v for v in renovado.json()["vigencias"] if v["nombre"] == "Certificado AEAT")
    assert aeat["estado"] == "vigente"
    assert emitir_avisos_de_caducidad() == 0
