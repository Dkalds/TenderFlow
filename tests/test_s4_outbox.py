"""Outbox de ``domain_events`` y despachador idempotente (S4.1).

Integración: exige Postgres (``tmp_db``). Lo que se prueba aquí es lo único que
un backbone de eventos tiene que garantizar: que el evento se escribe una vez,
que se reparte una vez por canal, y que interrumpir el reparto a mitad no
duplica lo ya entregado.
"""

from __future__ import annotations

import pytest

from db.events import (
    append_domain_event,
    append_event,
    claim_channel,
    count_pending_events,
    mark_dispatched,
    pending_events,
    release_channel,
)
from shared.events import PayloadIncompleto, TipoDeEventoDesconocido

_PAYLOAD_CREADA = {"pursuit_id": 1, "licitacion_id": "LIC-S4-1", "organization_id": 7}


def _crear_evento(**kwargs):
    return append_domain_event(
        "pursuit.created", 1, "pursuit", dict(_PAYLOAD_CREADA), organization_id=7, **kwargs
    )


def test_append_domain_event_persiste_organizacion_y_queda_pendiente(tmp_db):
    event_id = _crear_evento()
    assert event_id > 0

    pendientes = pending_events()
    assert [e["id"] for e in pendientes] == [event_id]
    assert pendientes[0]["organization_id"] == 7
    assert pendientes[0]["payload"]["licitacion_id"] == "LIC-S4-1"
    assert count_pending_events() == 1


def test_append_domain_event_rechaza_un_tipo_fuera_del_catalogo(tmp_db):
    """La validación ocurre ANTES de tocar la base: la tabla no puede acabar
    con un tipo que nadie sabe repartir."""
    with pytest.raises(TipoDeEventoDesconocido):
        append_domain_event("pursuit.inventado", 1, "pursuit", {})
    assert count_pending_events() == 0


def test_append_domain_event_rechaza_un_payload_incompleto(tmp_db):
    with pytest.raises(PayloadIncompleto):
        append_domain_event("pursuit.created", 1, "pursuit", {"pursuit_id": 1})
    assert count_pending_events() == 0


def test_append_event_legacy_no_valida_y_no_ensucia_la_cola_del_despachador(tmp_db):
    """``cache.invalidated`` y compañía se escriben con la puerta histórica y el
    despachador las saca de la cola por no tener canal (ver el test del job)."""
    event_id = append_event("cache.invalidated", "global", "cache", {})
    assert event_id > 0
    assert count_pending_events() == 1


def test_el_evento_se_escribe_en_la_transaccion_de_quien_muta(tmp_db):
    """Outbox de verdad: si la mutación se revierte, su evento se va con ella.

    Sin esto, un aviso podría entregarse por algo que la transacción deshizo —
    exactamente lo que hace irreproducible un sistema de notificaciones.
    """
    from db.database import connect

    with pytest.raises(RuntimeError):
        with connect() as c:
            append_domain_event(
                "pursuit.created",
                2,
                "pursuit",
                {"pursuit_id": 2, "licitacion_id": "LIC-ROLLBACK", "organization_id": 7},
                organization_id=7,
                conn=c,
            )
            raise RuntimeError("la mutación falla después de escribir el evento")

    assert count_pending_events() == 0


def test_claim_channel_es_idempotente_por_evento_y_canal(tmp_db):
    event_id = _crear_evento()
    assert claim_channel(event_id, "webhook") is True
    assert claim_channel(event_id, "webhook") is False
    # Otro canal del mismo evento es otra reserva.
    assert claim_channel(event_id, "cache") is True


def test_release_channel_devuelve_el_canal_a_la_cola(tmp_db):
    """Un canal que falló tiene que poder reintentarse: la idempotencia no se
    paga con mensajes perdidos."""
    event_id = _crear_evento()
    assert claim_channel(event_id, "webhook") is True
    release_channel(event_id, "webhook")
    assert claim_channel(event_id, "webhook") is True


def test_mark_dispatched_saca_el_evento_de_la_cola(tmp_db):
    event_id = _crear_evento()
    mark_dispatched(event_id)
    assert pending_events() == []
    assert count_pending_events() == 0


def test_una_interrupcion_a_mitad_no_duplica_entregas(tmp_db, monkeypatch):
    """El test que pide el criterio de aceptación de S4.1.

    Se hace fallar el canal ``cache`` la primera vez. El evento queda sin
    marcar y la pasada siguiente lo vuelve a coger entero: el canal ``webhook``
    NO se vuelve a entregar (su reserva sigue en pie) y el que falló sí.
    """
    from scheduler.jobs import event_dispatch

    entregas: list[str] = []

    def _webhook(evento, spec):
        entregas.append("webhook")
        return 1

    fallos = {"n": 0}

    def _cache():
        if fallos["n"] == 0:
            fallos["n"] += 1
            raise RuntimeError("proceso interrumpido a mitad del abanico")
        entregas.append("cache")

    monkeypatch.setattr(event_dispatch, "_canal_webhook", _webhook)
    monkeypatch.setattr(event_dispatch, "_canal_cache", _cache)

    _crear_evento()

    primera = event_dispatch.dispatch_pending()
    assert primera.fallidos == 1
    assert primera.procesados == 0
    assert entregas == ["webhook"]
    assert count_pending_events() == 1, "un evento con un canal fallido sigue pendiente"

    segunda = event_dispatch.dispatch_pending()
    assert segunda.procesados == 1
    assert entregas == ["webhook", "cache"], "el canal ya entregado no se repite"
    assert count_pending_events() == 0

    # Y una tercera pasada no encuentra nada.
    assert event_dispatch.dispatch_pending().procesados == 0
    assert entregas == ["webhook", "cache"]


def test_el_despachador_saca_de_la_cola_los_eventos_sin_canal(tmp_db):
    """``cache.invalidated`` y la señal de tecnología no tienen canal.

    Sin esta rama, ``domain_events_pending`` crecería para siempre por filas
    que nadie va a repartir jamás — y la alerta de la cola sería ruido.
    """
    from scheduler.jobs import event_dispatch

    append_event("cache.invalidated", "global", "cache", {})
    resultado = event_dispatch.dispatch_pending()
    assert resultado.ignorados == 1
    assert resultado.procesados == 0
    assert count_pending_events() == 0
