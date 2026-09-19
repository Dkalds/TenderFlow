"""Despachador cableado y avisos del outbox contra Postgres (S4.1, F1.5, F5.1–F5.3).

Integración (``tmp_db``). Complementa a ``test_event_dispatch_cableado.py`` y
``test_avisos_outbox.py``, que prueban la política sin BD: aquí se prueba el
SQL —la caducidad por ``created_at``, la identidad por ``source_hash`` de los
documentos, el cruce de cuentas por órgano plegado y la lectura del digest con
``entry_id`` negativo—.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from db.database import connect, set_cursor
from db.events import append_domain_event, caducar_pendientes, count_pending_events
from scheduler.jobs import event_dispatch
from services import avisos_outbox

_ID = "G1-EXP-1"


def _usuario(email: str) -> tuple[int, int, str]:
    """Crea usuario + organización personal. ``(user_id, org_id, clave)``."""
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user
    from shared.identity import user_key_from_email

    user_id = create_user(
        email=email,
        password_hash="test-hash",  # pragma: allowlist secret
        display_name=email.split("@")[0],
    )
    org_id = int(OrganizationRepository().ensure_personal_organization(user_id)["id"])
    return user_id, org_id, user_key_from_email(email, user_id)


def _lic(
    id_externo: str,
    *,
    organo: str = "Órgano de prueba",
    primera_extraccion: str = "2026-09-01T00:00:00+00:00",
    fecha_fin: str | None = None,
) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, estado, organo_contratacion, fecha_publicacion, "
            " fecha_extraccion, primera_extraccion, fecha_fin) "
            "VALUES (%s, %s, 'PUB', %s, '2026-09-01', '2026-09-01', %s, %s)",
            (id_externo, f"Expediente {id_externo}", organo, primera_extraccion, fecha_fin),
        )


def _seguir(id_externo: str, *, clave: str, user_id: int, org_id: int) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO watchlist_items (user_key, user_id, id_externo, created_at, "
            " organization_id) VALUES (%s, %s, %s, '2026-09-01', %s)",
            (clave, user_id, id_externo, org_id),
        )


def _documento(id_externo: str, *, tipo: str, uri: str, source_hash: str | None) -> int:
    with connect() as c:
        row = c.execute(
            "INSERT INTO documentos (licitacion_id, tipo, uri, status, created_at, "
            " updated_at, source_hash) "
            "VALUES (%s, %s, %s, 'pending', '2026-09-19', '2026-09-19', %s) RETURNING id",
            (id_externo, tipo, uri, source_hash),
        ).fetchone()
    return int(row[0])


def _eventos(tipo: str) -> list[dict[str, Any]]:
    from db.events import get_events_by_type

    return get_events_by_type(tipo)


@pytest.fixture()
def sin_salidas_externas(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """Ni SMTP ni webhooks ni señal de caché: sólo lo que queda en la BD."""
    correos: list[dict[str, str]] = []

    def _enviar(*, to_addr: str, subject: str, texto: str, html: str) -> bool:
        correos.append({"to": to_addr, "subject": subject})
        return True

    monkeypatch.setattr("observability.alerts.enviar_email_transaccional", _enviar)
    monkeypatch.setattr(event_dispatch, "_canal_webhook", lambda _e, _s: 0)
    monkeypatch.setattr(event_dispatch, "_canal_cache", lambda: None)
    return correos


# ── S4.1: antigüedad máxima ──────────────────────────────────────────────────


def _envejecer(event_id: int, horas: int) -> None:
    marca = (datetime.now(UTC) - timedelta(hours=horas)).isoformat()
    with connect() as c:
        c.execute("UPDATE domain_events SET created_at = %s WHERE id = %s", (marca, event_id))


def _creada(n: int) -> int:
    return append_domain_event(
        "pursuit.created",
        n,
        "pursuit",
        {"pursuit_id": n, "licitacion_id": f"G1-{n}", "organization_id": 7},
        organization_id=7,
    )


def test_caducar_pendientes_solo_toca_lo_anterior_al_corte(tmp_db):
    viejo = _creada(1)
    _creada(2)
    _envejecer(viejo, 72)

    corte = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    assert caducar_pendientes(corte) == {"pursuit.created": 1}
    assert count_pending_events() == 1
    # Idempotente: lo ya caducado no vuelve a contar.
    assert caducar_pendientes(corte) == {}


def test_la_cola_acumulada_no_se_entrega_y_lo_reciente_si(
    tmp_db, sin_salidas_externas, monkeypatch: pytest.MonkeyPatch
):
    """La decisión de S4.1 sobre la cola histórica: lo que supera la antigüedad
    máxima sale de la cola sin entregarse; lo reciente se reparte."""
    viejo = _creada(1)
    reciente = _creada(2)
    _envejecer(viejo, 24 * 10)
    repartidos: list[int] = []
    monkeypatch.setattr(
        event_dispatch, "_canal_webhook", lambda evento, _s: repartidos.append(evento["id"]) or 1
    )

    resultado = event_dispatch.dispatch_pending(max_age_hours=48)

    assert resultado.caducados == 1
    assert resultado.procesados == 1
    assert repartidos == [reciente]
    assert count_pending_events() == 0


# ── F5.1: documentos nuevos ──────────────────────────────────────────────────


@pytest.fixture()
def seguidora(tmp_db) -> tuple[int, int, str]:
    user_id, org_id, clave = _usuario("g1-seguidora@example.test")
    _lic(_ID)
    _seguir(_ID, clave=clave, user_id=user_id, org_id=org_id)
    return user_id, org_id, clave


def test_un_pliego_con_el_token_rotado_no_es_un_documento_nuevo(seguidora):
    """Identidad por ``source_hash`` (v88): la misma huella con otra URL es el
    mismo pliego, y el aviso sería ruido diario."""
    primero = _documento(_ID, tipo="legal", uri="https://x/pcap?t=1", source_hash="H1")
    set_cursor(avisos_outbox.CURSOR_DOCUMENTOS, last_entry_id=str(primero))
    _documento(_ID, tipo="additional", uri="https://x/pcap?t=2", source_hash="H1")
    nuevo = _documento(_ID, tipo="technical", uri="https://x/ppt?t=1", source_hash="H2")

    assert avisos_outbox.emitir_documentos_nuevos() == 1

    eventos = _eventos("licitacion.documento_nuevo")
    assert [e["payload"]["documento_id"] for e in eventos] == [nuevo]
    assert eventos[0]["payload"]["tipo"] == "technical"
    # Segunda pasada sin nada nuevo: no repite.
    assert avisos_outbox.emitir_documentos_nuevos() == 0


def test_el_documento_nuevo_llega_a_la_campana_y_al_digest(seguidora, sin_salidas_externas):
    from db.repositories.watchlist import WatchlistRepository
    from services.notifications import get_user_alerts

    user_id, org_id, clave = seguidora
    set_cursor(avisos_outbox.CURSOR_DOCUMENTOS, last_entry_id="0")
    _documento(_ID, tipo="technical", uri="https://x/ppt", source_hash="H9")
    avisos_outbox.emitir_documentos_nuevos()

    event_dispatch.dispatch_pending()

    alertas = get_user_alerts(clave, organization_id=org_id, user_id=user_id)
    assert len(alertas) == 1
    assert alertas[0]["title"].startswith("Documento nuevo: technical")
    # Por defecto `daily`: una línea en el digest, con el evento cruzado.
    filas = WatchlistRepository().load_pending_digests("daily")
    assert len(filas) == 1
    assert int(filas[0]["entry_id"]) < 0
    assert filas[0]["evento_tipo"] == "licitacion.documento_nuevo"
    assert sin_salidas_externas == []


def test_dos_seguidores_del_mismo_expediente_tienen_su_linea_de_digest(
    seguidora, sin_salidas_externas
):
    """El único de ``pending_digests`` es (entry_id, licitacion_id): con un
    ``entry_id`` por evento el segundo seguidor se perdía en silencio."""
    from db.repositories.watchlist import WatchlistRepository

    _, org_id, _ = seguidora
    otro_id, _, otra_clave = _usuario("g1-otro@example.test")
    _seguir(_ID, clave=otra_clave, user_id=otro_id, org_id=org_id)
    set_cursor(avisos_outbox.CURSOR_DOCUMENTOS, last_entry_id="0")
    _documento(_ID, tipo="legal", uri="https://x/pcap", source_hash="H7")
    avisos_outbox.emitir_documentos_nuevos()

    event_dispatch.dispatch_pending()

    destinatarios = {
        str(f["recipient_email"]) for f in WatchlistRepository().load_pending_digests("daily")
    }
    assert destinatarios == {"g1-seguidora@example.test", "g1-otro@example.test"}


# ── F5.2: recursos ───────────────────────────────────────────────────────────


def test_un_recurso_sobre_un_expediente_seguido_emite_con_su_sentido(seguidora):
    set_cursor(avisos_outbox.CURSOR_RECURSOS, last_entry_id="0")
    with connect() as c:
        c.execute(
            "INSERT INTO resoluciones_recurso (tribunal, numero_resolucion, fecha, sentido, "
            " licitacion_id, fecha_extraccion) "
            "VALUES ('TACRC', '123/2026', '2026-09-18', 'estimado', %s, '2026-09-19')",
            (_ID,),
        )
        c.execute(
            "INSERT INTO resoluciones_recurso (tribunal, numero_resolucion, fecha, sentido, "
            " licitacion_id, fecha_extraccion) "
            "VALUES ('TACRC', '124/2026', '2026-09-18', 'desestimado', 'NADIE-LO-SIGUE', "
            " '2026-09-19')"
        )

    assert avisos_outbox.emitir_recursos() == 1

    evento = _eventos("licitacion.recurso")[0]
    assert evento["payload"]["sentido"] == "estimado"
    assert evento["payload"]["aviso_titulo"] == "Recurso estimado"


# ── F1.5: cuentas objetivo ───────────────────────────────────────────────────


@pytest.fixture()
def cuenta(tmp_db) -> tuple[int, int]:
    from db.repositories.cuentas import CuentasRepository

    user_id, org_id, _ = _usuario("g1-comercial@example.test")
    CuentasRepository().follow(
        organization_id=org_id, organo_nombre="Ayuntamiento de Pruebas", user_id=user_id
    )
    return user_id, org_id


def test_publicacion_nueva_de_una_cuenta_seguida(cuenta):
    user_id, org_id = cuenta
    ahora = datetime.now(UTC)
    ayer = (ahora - timedelta(days=1)).isoformat()
    set_cursor(
        avisos_outbox.CURSOR_CUENTAS, last_seen_updated=(ahora - timedelta(days=5)).isoformat()
    )
    # Otra grafía del mismo órgano: el plegado de los dos lados es el mismo.
    _lic("G1-CTA-1", organo="  AYUNTAMIENTO DE PRUEBAS ", primera_extraccion=ayer)
    _lic(
        "G1-CTA-VIEJA",
        organo="Ayuntamiento de Pruebas",
        primera_extraccion=(ahora - timedelta(days=10)).isoformat(),
    )
    _lic("G1-OTRO", organo="Diputación Ajena", primera_extraccion=ayer)

    assert avisos_outbox.emitir_avisos_de_cuentas() == 1

    evento = _eventos("cuenta.publicacion_nueva")[0]
    assert evento["payload"]["id_externo"] == "G1-CTA-1"
    assert [s["user_id"] for s in evento["payload"]["seguidores"]] == [user_id]
    assert evento["payload"]["organization_id"] == org_id


def test_vencimiento_a_seis_meses_de_una_cuenta_una_sola_vez(cuenta):
    fin = (date.today() + timedelta(days=180)).isoformat()
    _lic("G1-CTA-FIN", organo="Ayuntamiento de Pruebas", fecha_fin=fin)
    _lic("G1-CTA-LEJOS", organo="Ayuntamiento de Pruebas", fecha_fin="2030-01-01")
    with connect() as c:
        for id_externo in ("G1-CTA-FIN", "G1-CTA-LEJOS"):
            c.execute(
                "INSERT INTO adjudicaciones (licitacion_id, nombre, fecha_extraccion) "
                "VALUES (%s, 'Incumbente SA', '2026-09-01')",
                (id_externo,),
            )

    assert avisos_outbox.emitir_vencimientos_de_cuentas() == 1
    assert avisos_outbox.emitir_vencimientos_de_cuentas() == 0

    evento = _eventos("cuenta.vencimiento_proximo")[0]
    assert evento["payload"]["id_externo"] == "G1-CTA-FIN"
    assert evento["payload"]["fecha_fin"] == fin
