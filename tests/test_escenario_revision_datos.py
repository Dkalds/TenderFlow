"""Escenario de administración: vaciar las colas de revisión del dato.

Recorrido completo por la API con sesión real. Ver ``tests/escenarios.py`` y
``docs/casos-de-uso.md``. Las colas las llenan la ingesta y sus detectores, así
que los pares y las grafías dudosas se siembran como los dejarían ellos.
"""

from __future__ import annotations

from tests.escenarios import abrir_sesion, sembrar_licitacion


def _sembrar_colas() -> None:
    """Dos pares de duplicados pendientes y una grafía de órgano en la cola."""
    from db.database import connect
    from db.repositories import organos as repo_organos

    for sufijo in ("A", "B"):
        sembrar_licitacion(
            f"EXP-REV-{sufijo}",
            f"Soporte SAP del servicio de salud {sufijo}",
            tecnologia="SAP",
        )
        sembrar_licitacion(
            f"pscp:EXP-REV-{sufijo}",
            f"Soporte SAP del servicio de salud {sufijo}",
            tecnologia="SAP",
            fuente="pscp",
        )
    with connect() as c:
        for sufijo in ("A", "B"):
            c.execute(
                "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, "
                " clave_match, confianza, status) VALUES (%s, %s, 'clave', 0.8, 'pending')",
                (f"pscp:EXP-REV-{sufijo}", f"EXP-REV-{sufijo}"),
            )

    candidato = repo_organos.crear(
        nombre_canonico="Servicio Madrileño de Salud",
        nombre_normalizado="servicio madrileno de salud",
    )
    repo_organos.encolar_revision(
        nombre_original="Servicio Madrileño Salud",
        alias_normalizado="servicio madrileno salud",
        candidato_organo_id=candidato,
        score=0.9,
    )
    sembrar_licitacion(
        "EXP-REV-ORG",
        "Licencias SAP del servicio de salud",
        tecnologia="SAP",
        organo_contratacion="Servicio Madrileño Salud",
    )


def _ids_listados(sesion) -> set[str]:
    """Lo que enseña el listado de `/licitaciones` de la consola."""
    r = sesion.get("/licitaciones", params={"q": "servicio de salud", "limit": 50})
    assert r.status_code == 200, r.text
    return {i["id_externo"] for i in r.json()["items"]}


def test_cu20_el_administrador_decide_duplicados_y_organos(client, api_db):
    """CU-20 — de las colas de revisión del dato a un listado que cuenta cada contrato una vez."""
    _sembrar_colas()
    from db.database import connect

    curiosa = abrir_sesion("curiosa@example.com", client)
    admin = abrir_sesion("admin-datos@example.com", client=None)
    with connect() as c:
        c.execute("UPDATE users SET is_admin = 1 WHERE id = %s", (admin.user_id,))

    # Quien no es administrador no ve las colas ni puede decidir nada.
    assert curiosa.get("/admin/revision/duplicados").status_code == 403
    assert (
        curiosa.post(
            "/admin/revision/duplicados/pscp:EXP-REV-A/resolver", json={"aceptar": True}
        ).status_code
        == 403
    )
    assert curiosa.get("/admin/revision/verdad").status_code == 403

    # Un par pendiente ya no sale en los listados, pero sigue en la cola y en
    # el panel de calidad hasta que alguien decide.
    assert _ids_listados(admin) == {"EXP-REV-A", "EXP-REV-B", "EXP-REV-ORG"}
    calidad = admin.get("/analytics/quality").json()
    assert calidad["duplicados_pendientes"] == 2
    assert calidad["organos_revision_pendiente"] == 1

    cola = admin.get("/admin/revision/duplicados")
    assert cola.status_code == 200, cola.text
    assert cola.json()["total"] == 2
    par = next(i for i in cola.json()["items"] if i["licitacion_id"] == "pscp:EXP-REV-A")
    assert par["canonical_id"] == "EXP-REV-A"
    assert (par["fuente"], par["fuente_canonica"]) == ("pscp", "placsp")

    # Confirmar uno lo deja fuera para siempre; rechazar el otro lo devuelve.
    confirmado = admin.post(
        "/admin/revision/duplicados/pscp:EXP-REV-A/resolver", json={"aceptar": True}
    )
    assert confirmado.status_code == 200, confirmado.text
    assert confirmado.json()["estado"] == "confirmed"
    rechazado = admin.post(
        "/admin/revision/duplicados/pscp:EXP-REV-B/resolver", json={"aceptar": False}
    )
    assert rechazado.json()["estado"] == "rejected"
    assert _ids_listados(admin) == {"EXP-REV-A", "EXP-REV-B", "pscp:EXP-REV-B", "EXP-REV-ORG"}
    # Una decisión tomada no se reabre.
    otra = admin.post("/admin/revision/duplicados/pscp:EXP-REV-A/resolver", json={"aceptar": False})
    assert otra.status_code == 404

    # La grafía dudosa llega con su candidato, y aceptarla rellena el órgano
    # de las licitaciones que la esperaban.
    organos = admin.get("/admin/revision/organos").json()
    [dudosa] = organos["items"]
    assert dudosa["candidato_nombre"] == "Servicio Madrileño de Salud"
    resuelta = admin.post(
        f"/admin/revision/organos/{dudosa['id']}/resolver", json={"aceptar": True}
    )
    assert resuelta.status_code == 200, resuelta.text
    assert resuelta.json()["organo_id"] == dudosa["candidato_organo_id"]
    assert resuelta.json()["filas_asignadas"] == 1
    with connect() as c:
        organo_id = c.execute(
            "SELECT organo_id FROM licitaciones WHERE id_externo = 'EXP-REV-ORG'"
        ).fetchone()[0]
        auditado = {
            r[0]
            for r in c.execute(
                "SELECT action, user_id FROM audit_log WHERE action = ANY(%s)",
                (["dedupe.review_resolved", "organo.review_resolved"],),
            ).fetchall()
            # El actor es el id del administrador, nunca su correo (ADR-030 §D).
            if r[1] == admin.user_id
        }
    assert organo_id == dudosa["candidato_organo_id"]
    assert auditado == {"dedupe.review_resolved", "organo.review_resolved"}

    calidad = admin.get("/analytics/quality").json()
    assert calidad["duplicados_pendientes"] == 0
    assert calidad["organos_revision_pendiente"] == 0

    # El panel de verdad del dato dice qué sección está fuera de su umbral.
    verdad = admin.get("/admin/revision/verdad")
    assert verdad.status_code == 200, verdad.text
    claves = {s["clave"] for s in verdad.json()["secciones"]}
    assert {"fecha_limite", "ute", "baja", "importe_tipo", "fechas_iso"} <= claves
    assert all(
        s["estado"] in {"ok", "violacion", "error", "sin_datos"} for s in verdad.json()["secciones"]
    )
