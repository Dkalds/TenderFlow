"""Campos opcionales de ``WebhookRepository.update`` y el fallback de entregas.

Sólo se ejercitaba la rama ``name``: las de ``url``, ``event_types`` y
``active`` construían su ``SET ... = %s`` sin que ningún test las recorriera,
y son líneas que reescribió la migración de paramstyle.

``active`` importa aparte: la columna guarda 0/1 y la API expone un booleano
(``WebhookOut.active`` pasó de ``int | None`` a ``bool | None`` en esta misma
rama), así que la conversión de ida tiene que quedar fijada.
"""

from __future__ import annotations

from db import webhooks as wh_mod
from db.repositories.webhooks import WebhookRepository


def _crear(nombre: str = "hook") -> int:
    webhook_id, _ = wh_mod.create_webhook(
        name=nombre,
        url="https://example.com/hook",
        event_types=["watchlist_match"],
    )
    return webhook_id


def _leer(webhook_id: int) -> dict:
    return next(w for w in WebhookRepository().list_all() if w["id"] == webhook_id)


def test_update_sin_campos_no_toca_nada(tmp_db):
    """Sin `SET` no hay UPDATE que emitir; devuelve True igual (nada que fallar)."""
    webhook_id = _crear()

    assert (
        WebhookRepository().update(webhook_id, name=None, url=None, event_types=None, active=None)
        is True
    )
    assert _leer(webhook_id)["name"] == "hook"


def test_update_cambia_url(tmp_db):
    webhook_id = _crear()

    assert WebhookRepository().update(
        webhook_id, name=None, url="https://otro.example/h", event_types=None, active=None
    )
    assert _leer(webhook_id)["url"] == "https://otro.example/h"


def test_update_cambia_event_types(tmp_db):
    """Se guardan como CSV (el `update` hace el `join`) y se leen como lista."""
    webhook_id = _crear()

    assert WebhookRepository().update(
        webhook_id,
        name=None,
        url=None,
        event_types=["watchlist_match", "tender_closing"],
        active=None,
    )
    assert _leer(webhook_id)["event_types"] == ["watchlist_match", "tender_closing"]


def test_update_desactiva_con_booleano(tmp_db):
    webhook_id = _crear()

    assert WebhookRepository().update(
        webhook_id, name=None, url=None, event_types=None, active=False
    )
    assert not _leer(webhook_id)["active"]


def test_update_de_un_id_inexistente_devuelve_false(tmp_db):
    assert (
        WebhookRepository().update(999_999, name="x", url=None, event_types=None, active=None)
        is False
    )


def test_list_deliveries_degrada_a_vacio_si_la_consulta_falla(tmp_db):
    """El `except` se instrumentó en esta rama; nadie lo recorría.

    Se tira la tabla en el schema aislado del test para provocar el fallo real
    en vez de simularlo: lo que se fija es que un error de lectura del historial
    no tumbe la respuesta, y que deje rastro en el log.
    """
    db_mod, _ = tmp_db
    webhook_id = _crear()
    with db_mod.connect() as conn:
        conn.execute("DROP TABLE webhook_deliveries")

    assert WebhookRepository().list_deliveries(webhook_id) == []
