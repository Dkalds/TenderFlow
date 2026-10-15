"""Escenario de la campana: solo lo que te concierne, y leído cuando lo abres.

Recorrido completo por la API con sesión real. Ver ``tests/escenarios.py`` y
``docs/casos-de-uso.md``.

Dos piezas no las hace una persona y por eso el escenario las hace a mano, como
las haría la pasada: el job de reglas deja su alerta en la bandeja
(``scheduler/watchlist_rules_alerts.py``), y el despachador del outbox reparte
la mención (``scheduler/jobs/event_dispatch.dispatch_pending``).
"""

from __future__ import annotations

from datetime import UTC, datetime

from tests.escenarios import abrir_sesion, sembrar_licitacion


def _alerta_de_regla(sesion, organization_id: int, rule_id: int, licitacion_id: str) -> None:
    """Lo que deja el job de reglas cuando un expediente casa (una fila por regla y expediente)."""
    from db.notifications import insert_user_notification
    from shared.identity import user_key_from_email

    assert insert_user_notification(
        user_key=user_key_from_email(sesion.email, sesion.user_id),
        user_id=sesion.user_id,
        type_="watchlist_rule",
        title="Tu regla «SAP» encontró un expediente",
        body="Soporte SAP para el ayuntamiento",
        licitacion_id=licitacion_id,
        organization_id=organization_id,
        rule_id=rule_id,
    )


def _bandeja(sesion, oid: int, **params) -> dict:
    respuesta = sesion.get("/notifications/alerts", params={"organization_id": oid, **params})
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def test_cu29_la_campana_ensena_solo_lo_tuyo_y_lo_marca_al_abrirlo(client, api_db):
    """CU-29 — alertas propias, leídas una a una, todas a la vez, y la regla en pausa."""
    from scheduler.jobs.event_dispatch import dispatch_pending

    hoy = datetime.now(UTC).date().isoformat()
    sembrar_licitacion("EXP-CAMP-SAP", "Soporte SAP para el ayuntamiento")
    # Una novedad del mercado publicada hoy: no es de nadie, no va a la campana.
    sembrar_licitacion("EXP-CAMP-MERCADO", "Suministro de papel", fecha_publicacion=hoy)
    ana = abrir_sesion("campana-ana@example.com", client, nombre="Ana")
    bea = abrir_sesion("campana-bea@example.com", nombre="Bea")

    equipo = ana.post("/organizations", json={"name": "Consultora Campana"})
    assert equipo.status_code == 201, equipo.text
    oid = equipo.json()["id"]
    invitada = ana.post(
        f"/organizations/{oid}/members", json={"email": bea.email, "role": "member"}
    )
    assert invitada.status_code == 201, invitada.text

    # Lo de Ana: una regla suya que encontró algo…
    regla = ana.post(
        "/watchlist/rules", json={"nombre": "SAP", "keyword": "SAP", "organization_id": oid}
    )
    assert regla.status_code == 201, regla.text
    rule_id = regla.json()["id"]
    _alerta_de_regla(ana, oid, rule_id, "EXP-CAMP-SAP")
    # …y una mención de Bea en el hilo de una oportunidad del equipo.
    oportunidad = ana.post(
        "/pursuits", json={"licitacion_id": "EXP-CAMP-SAP", "organization_id": oid}
    )
    assert oportunidad.status_code == 201, oportunidad.text
    pid = oportunidad.json()["id"]
    comentario = bea.post(
        f"/pursuits/{pid}/comments",
        params={"organization_id": oid},
        json={"body": "@Ana ¿miras la solvencia técnica?"},
    )
    assert comentario.status_code == 201, comentario.text
    dispatch_pending()

    bandeja = _bandeja(ana, oid)
    assert bandeja["total"] == 2
    assert bandeja["sin_leer"] == 2
    por_tipo = {a["type"].split(":")[0]: a for a in bandeja["items"]}
    assert set(por_tipo) == {"watchlist_rule", "pursuit_mencion"}
    assert por_tipo["watchlist_rule"]["rule_id"] == rule_id
    # El expediente ya es una oportunidad: la campana enlaza a su ficha.
    assert por_tipo["pursuit_mencion"]["pursuit_id"] == pid
    assert "EXP-CAMP-MERCADO" not in {a["licitacion_id"] for a in bandeja["items"]}
    # El resumen antiguo ya no trae novedades de mercado (campo deprecado).
    resumen = ana.get("/notifications", params={"organization_id": oid}).json()
    assert resumen["items"] == []
    assert resumen["unread_count"] == 0

    # Mirar la campana no marca nada.
    assert _bandeja(ana, oid)["sin_leer"] == 2

    # Abrir la mención la marca a ella sola.
    mencion = por_tipo["pursuit_mencion"]["id"]
    leida = ana.post("/notifications/alerts/read", json={"ids": [mencion], "organization_id": oid})
    assert leida.status_code == 200, leida.text
    assert _bandeja(ana, oid)["sin_leer"] == 1
    assert [a["id"] for a in _bandeja(ana, oid, estado="leidas")["items"]] == [mencion]
    sin_leer = _bandeja(ana, oid, estado="sin_leer")
    assert [a["type"] for a in sin_leer["items"]] == ["watchlist_rule"]

    # «Ver todas» pagina sin perder ninguna.
    primera = _bandeja(ana, oid, limit=1)
    segunda = _bandeja(ana, oid, limit=1, offset=1)
    assert primera["total"] == segunda["total"] == 2
    assert {primera["items"][0]["id"], segunda["items"][0]["id"]} == {
        a["id"] for a in bandeja["items"]
    }

    # «Silenciar esta regla» con el endpoint de reglas de siempre: deja de avisar.
    (actual,) = [
        r
        for r in ana.get("/watchlist/rules", params={"organization_id": oid}).json()["items"]
        if r["id"] == rule_id
    ]
    criterios = (
        "nombre", "keyword", "cpv", "min_importe", "ccaa", "frequency", "tecnologia",
        "organo", "procedimiento", "tipo_contrato", "banda_min", "plazo_min_dias",
    )  # fmt: skip
    pausada = ana.put(
        f"/watchlist/rules/{rule_id}",
        json={**{c: actual[c] for c in criterios}, "active": False, "organization_id": oid},
    )
    assert pausada.status_code == 200, pausada.text
    (despues,) = [
        r
        for r in ana.get("/watchlist/rules", params={"organization_id": oid}).json()["items"]
        if r["id"] == rule_id
    ]
    assert despues["active"] is False
    assert despues["keyword"] == "SAP"

    # «Marcar todo como leído» es una acción explícita.
    todas = ana.post("/notifications/alerts/read", json={"all": True, "organization_id": oid})
    assert todas.status_code == 200, todas.text
    assert _bandeja(ana, oid)["sin_leer"] == 0
    assert _bandeja(ana, oid)["total"] == 2

    # La bandeja de Bea es la suya: mencionar no se avisa a quien menciona.
    assert _bandeja(bea, oid)["total"] == 0
