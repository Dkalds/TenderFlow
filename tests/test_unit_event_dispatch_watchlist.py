"""El despachador reparte las alertas de watchlist leyendo el destinatario del origen.

``watchlist_rule.matched`` (reglas) y ``watchlist_match`` (watchlist de
instancia) no traen correo ni frecuencia: los lee el despachador de la regla o
de la entrada al despachar. Lo que se fija aquí es esa lectura y que el correo
no acaba en el cuerpo del webhook de la organización.

Sin BD: la persistencia y la salida HTTP son dobles.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from scheduler.jobs import event_dispatch
from shared.events import Canal, especificacion

_REGLA = {
    "id": 5,
    "user_key": "clave-regla",
    "user_id": 9,
    "nombre": "SAP",
    "keyword": "SAP",
    "cpv": None,
    "email": "privado@example.test",
    "frequency": "weekly",
    "organization_id": 7,
}


def _evento_regla() -> dict[str, Any]:
    return {
        "id": 41,
        "event_type": "watchlist_rule.matched",
        "organization_id": 7,
        "created_at": "2026-11-10T08:00:00+00:00",
        "payload": {
            "rule_id": 5,
            "user_key": "clave-regla",
            "nombre": "SAP",
            "keyword": "SAP",
            "cpv": None,
            "total_matches": 2,
            "licitaciones": ["L1", "L2"],
        },
    }


@pytest.fixture()
def regla(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    fila = dict(_REGLA)
    monkeypatch.setattr("db.repositories.watchlist_rules.fila_de_regla", lambda _id: fila)
    monkeypatch.setattr(
        event_dispatch,
        "_licitaciones",
        lambda ids: {i: {"titulo": f"T {i}", "organo_contratacion": "Órgano"} for i in ids},
    )
    return fila


def _despachar(canal: Canal, evento: dict[str, Any]) -> event_dispatch.ResultadoDespacho:
    resultado = event_dispatch.ResultadoDespacho()
    spec = especificacion(evento["event_type"])
    event_dispatch._despachar_canal(canal, evento, spec, resultado)
    return resultado


def test_la_campana_de_la_regla_lleva_una_fila_por_licitacion_y_su_rule_id(
    monkeypatch: pytest.MonkeyPatch, regla: dict[str, Any]
) -> None:
    llamadas: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "db.notifications.insert_user_notifications",
        lambda **kw: llamadas.append(kw) or len(kw["filas"]),
    )

    resultado = _despachar("in_app", _evento_regla())

    assert resultado.in_app == 2
    (kw,) = llamadas
    assert kw["type_"] == "rule_match"
    assert kw["rule_id"] == 5
    assert kw["user_id"] == 9
    assert kw["organization_id"] == 7
    assert kw["title"] == "2 licitacion(es) nueva(s) para «SAP»"
    assert kw["filas"] == [("L1", "T L1 | Órgano"), ("L2", "T L2 | Órgano")]


def test_el_digest_de_la_regla_usa_su_correo_y_su_frecuencia(
    monkeypatch: pytest.MonkeyPatch, regla: dict[str, Any]
) -> None:
    llamadas: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        "services.watchlist.store_pending_digests",
        lambda *a, **kw: llamadas.append((*a, kw)) or True,
    )

    resultado = _despachar("digest", _evento_regla())

    assert resultado.digest == 2
    ((user_key, email, entry_id, lics, frecuencia, _ts, kw),) = llamadas
    assert (user_key, email, entry_id, lics, frecuencia) == (
        "clave-regla",
        "privado@example.test",
        5,
        ["L1", "L2"],
        "weekly",
    )
    assert kw == {"user_id": 9}


def test_un_digest_que_no_se_encola_libera_el_canal(
    monkeypatch: pytest.MonkeyPatch, regla: dict[str, Any]
) -> None:
    """La puerta no lanza: sin esto el canal quedaría reclamado y el correo perdido."""
    monkeypatch.setattr("services.watchlist.store_pending_digests", lambda *_a, **_k: False)

    with pytest.raises(RuntimeError):
        _despachar("digest", _evento_regla())


def test_una_regla_sin_correo_no_encola_digest(
    monkeypatch: pytest.MonkeyPatch, regla: dict[str, Any]
) -> None:
    regla["email"] = None
    monkeypatch.setattr(
        "services.watchlist.store_pending_digests",
        lambda *_a, **_k: pytest.fail("no debía encolar"),
    )

    assert _despachar("digest", _evento_regla()).digest == 0


def test_una_regla_borrada_no_escribe_campana(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("db.repositories.watchlist_rules.fila_de_regla", lambda _id: None)
    monkeypatch.setattr(
        "db.notifications.insert_user_notifications",
        lambda **_: pytest.fail("no debía escribir"),
    )

    assert _despachar("in_app", _evento_regla()).in_app == 0


def _cuerpos_de_webhook(monkeypatch: pytest.MonkeyPatch, evento: dict[str, Any]) -> list[Any]:
    from db.repositories.webhooks import WebhookRepository

    cuerpos: list[Any] = []
    monkeypatch.setattr(
        WebhookRepository,
        "list_active_subscribers",
        lambda self, **_: [
            {
                "id": 1,
                "url": "https://hooks.example.test/x",
                "secret": "s",  # pragma: allowlist secret -- literal de test
                "event_types": ["*"],
                "formato": "json",
            }
        ],
    )
    monkeypatch.setattr(
        "db.webhooks.entregar_firmado",
        lambda **kw: cuerpos.append(json.loads(kw["body"])) or True,
    )
    assert _despachar("webhook", evento).webhooks == 1
    return cuerpos


def test_el_webhook_de_la_regla_no_recibe_su_correo(
    monkeypatch: pytest.MonkeyPatch, regla: dict[str, Any]
) -> None:
    (cuerpo,) = _cuerpos_de_webhook(monkeypatch, _evento_regla())

    assert cuerpo["event"] == "watchlist_rule.matched"
    assert cuerpo["data"]["licitaciones"] == ["L1", "L2"]
    assert "privado@example.test" not in json.dumps(cuerpo)


# ── watchlist_match: la watchlist de instancia ───────────────────────────────


def _evento_watchlist() -> dict[str, Any]:
    return {
        "id": 42,
        "event_type": "watchlist_match",
        "organization_id": None,
        "created_at": "2026-11-10T08:00:00+00:00",
        "payload": {
            "total_matches": 3,
            "entries": [
                {"entry_id": 1, "cpv_prefix": "48", "keyword": "SAP", "matches": ["L1"]},
                {"entry_id": 2, "cpv_prefix": "72", "keyword": None, "matches": ["L2", "L3"]},
            ],
        },
    }


@pytest.fixture()
def entradas(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    filas = [
        {
            "id": 1,
            "user_key": "instancia",
            "user_id": None,
            "email": "operador@example.test",
            "cpv_prefix": "48",
            "keyword": "SAP",
            "min_importe": None,
            "ccaa": None,
            "frequency": "immediate",
        },
        {
            "id": 2,
            "user_key": "instancia",
            "user_id": None,
            "email": "operador@example.test",
            "cpv_prefix": "72",
            "keyword": None,
            "min_importe": None,
            "ccaa": None,
            "frequency": "daily",
        },
    ]
    monkeypatch.setattr(
        "db.watchlist.entradas_por_id", lambda ids: [f for f in filas if f["id"] in ids]
    )
    monkeypatch.setattr(
        event_dispatch,
        "_licitaciones",
        lambda ids: {i: {"id_externo": i, "titulo": f"T {i}"} for i in ids},
    )
    return filas


def test_la_watchlist_encola_lo_diario_y_avisa_al_momento_lo_inmediato(
    monkeypatch: pytest.MonkeyPatch, entradas: list[dict[str, Any]]
) -> None:
    encoladas: list[tuple[Any, ...]] = []
    avisos: list[tuple[str, list[Any]]] = []
    monkeypatch.setattr(
        "services.watchlist.store_pending_digests",
        lambda *a, **_k: encoladas.append(a) or True,
    )
    monkeypatch.setattr(
        "scheduler.watchlist_alerts.avisar_al_momento",
        lambda recipient, grupos: avisos.append((recipient, grupos)),
    )

    resultado = _despachar("digest", _evento_watchlist())

    assert [(a[1], a[2], a[3], a[4]) for a in encoladas] == [
        ("operador@example.test", 2, ["L2", "L3"], "daily")
    ]
    ((destinatario, grupos),) = avisos
    assert destinatario == "operador@example.test"
    assert [(e["id"], [lic["id_externo"] for lic in lics]) for e, lics in grupos] == [(1, ["L1"])]
    assert (resultado.digest, resultado.correos) == (2, 1)


def test_el_webhook_de_la_watchlist_conserva_el_recipient_del_contrato(
    monkeypatch: pytest.MonkeyPatch, entradas: list[dict[str, Any]]
) -> None:
    """El cuerpo publicado desde v15 trae ``recipient``; el evento guardado, no."""
    evento = _evento_watchlist()

    (cuerpo,) = _cuerpos_de_webhook(monkeypatch, evento)

    assert cuerpo["event"] == "watchlist_match"
    assert cuerpo["data"]["recipient"] == "operador@example.test"
    assert cuerpo["data"]["total_matches"] == 3
    assert "recipient" not in evento["payload"]
