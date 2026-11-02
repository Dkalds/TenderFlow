"""Aislamiento entre organizaciones en los eventos y los webhooks (auditoría 2026-11).

`licitacion.cambiada` se escribía sin organización y con los seguidores de todas
las organizaciones; el despachador, para un evento sin organización, leía los
webhooks de **todas** y les entregaba el payload íntegro. Un miembro con un
webhook hacia un host permitido recibía quién seguía qué en las demás.

Sin BD: el productor y el despachador se prueban con dobles. El SQL del
repositorio se comprueba por su texto, porque sin Postgres no hay otra forma
de fijar el predicado; la versión con BD está en
`tests/test_aislamiento_webhooks_integracion.py`.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from shared.events import especificacion, renderizar

# ── Productor: un evento por organización ────────────────────────────────────


def _seguidor(org: int, user_key: str, user_id: int | None = None) -> dict[str, Any]:
    return {"user_key": user_key, "organization_id": org, "user_id": user_id}


def _emitir(
    monkeypatch: pytest.MonkeyPatch, seguidores: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    import services.contract_events as mod

    escritos: list[dict[str, Any]] = []

    def _append(
        event_type: str, aggregate_id: str, aggregate_type: str, payload: dict[str, Any], **kw: Any
    ) -> int:
        escritos.append({"event_type": event_type, "payload": payload, **kw})
        return len(escritos)

    monkeypatch.setattr(mod, "seguidores_de_licitacion", lambda _id: seguidores)
    monkeypatch.setattr(mod, "append_domain_event", _append)
    emitido = mod._emitir_cambio_seguido(
        object(),
        id_externo="LIC-1",
        history_id=9,
        antes={"fecha_limite": "2026-11-01"},
        despues={"fecha_limite": "2026-12-01"},
        changed=["fecha_limite"],
    )
    assert emitido is True
    return escritos


def test_un_cambio_seguido_por_dos_organizaciones_escribe_un_evento_por_cada_una(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    escritos = _emitir(
        monkeypatch,
        [_seguidor(7, "uk-a"), _seguidor(8, "uk-b"), _seguidor(7, "uk-c")],
    )

    por_org = {e["organization_id"]: e for e in escritos}
    assert sorted(por_org) == [7, 8]
    assert all(e["event_type"] == "licitacion.cambiada" for e in escritos)
    for organization_id, evento in por_org.items():
        assert evento["payload"]["organization_id"] == organization_id
        assert {s["organization_id"] for s in evento["payload"]["seguidores"]} == {organization_id}
    assert [s["user_key"] for s in por_org[7]["payload"]["seguidores"]] == ["uk-a", "uk-c"]
    assert [s["user_key"] for s in por_org[8]["payload"]["seguidores"]] == ["uk-b"]


def test_un_seguidor_sin_organizacion_no_genera_evento(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.contract_events as mod

    monkeypatch.setattr(mod, "seguidores_de_licitacion", lambda _id: [_seguidor(0, "uk-x")])
    monkeypatch.setattr(mod, "append_domain_event", lambda *a, **k: pytest.fail("no debe escribir"))

    assert (
        mod._emitir_cambio_seguido(
            object(),
            id_externo="LIC-1",
            history_id=9,
            antes={"fecha_limite": "2026-11-01"},
            despues={"fecha_limite": "2026-12-01"},
            changed=["fecha_limite"],
        )
        is False
    )


# ── Despachador: cada webhook recibe solo lo suyo ────────────────────────────

_WEBHOOKS = [
    {"id": 1, "organization_id": 7, "url": "https://hooks.example.test/a"},
    {"id": 2, "organization_id": 8, "url": "https://hooks.example.test/b"},
    {"id": 3, "organization_id": None, "url": "https://hooks.example.test/global"},
]


@pytest.fixture
def entregas(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Webhooks de dos organizaciones y uno global; la salida HTTP se graba.

    El repositorio falso aplica la **misma regla** que el SQL de
    `list_active_subscribers`: con organización, la suya más las globales; sin
    ella, solo las globales.
    """
    import db.repositories.webhooks as repos
    import db.webhooks as salida
    from config.settings import settings

    enviadas: list[dict[str, Any]] = []

    class _Repo:
        def list_active_subscribers(
            self, *, organization_id: int | None = None
        ) -> list[dict[str, Any]]:
            return [
                {
                    **w,
                    "secret": "s",  # pragma: allowlist secret
                    "event_types": ["*"],
                    "formato": "json",
                }
                for w in _WEBHOOKS
                if w["organization_id"] is None or w["organization_id"] == organization_id
            ]

    def _intento(*, url: str, headers: dict[str, str], body: bytes, **_: Any) -> tuple[int, None]:
        enviadas.append({"url": url, "body": json.loads(body)})
        return 200, None

    monkeypatch.setattr(repos, "WebhookRepository", _Repo)
    monkeypatch.setattr(salida, "_resolve_secret", lambda webhook_id, stored: stored)
    monkeypatch.setattr(salida, "validate_outbound_url", lambda url, **_: url)
    monkeypatch.setattr(salida, "_intentar_entrega", _intento)
    monkeypatch.setattr(salida, "crear_entrega", lambda **_: 1)
    monkeypatch.setattr(salida, "_aplicar_decision", lambda **_: None)
    monkeypatch.setattr(settings, "WEBHOOK_ALLOWED_HOSTS", "hooks.example.test")
    return enviadas


def _cambio(organization_id: int | None, seguidores: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": 501,
        "event_type": "licitacion.cambiada",
        "organization_id": organization_id,
        "created_at": "2026-11-01T10:00:00+00:00",
        "payload": {
            "id_externo": "LIC-1",
            "changed_fields": ["fecha_limite"],
            "seguidores": seguidores,
        },
    }


def _canal(evento: dict[str, Any]) -> int:
    from scheduler.jobs import event_dispatch

    return event_dispatch._canal_webhook(evento, especificacion(evento["event_type"]))


def test_el_evento_de_una_organizacion_solo_llega_a_su_webhook_y_al_global(
    entregas: list[dict[str, Any]],
) -> None:
    assert _canal(_cambio(7, [_seguidor(7, "uk-a")])) == 2

    assert sorted(e["url"] for e in entregas) == [
        "https://hooks.example.test/a",
        "https://hooks.example.test/global",
    ]


def test_el_cuerpo_del_webhook_no_lleva_seguidores(entregas: list[dict[str, Any]]) -> None:
    _canal(_cambio(7, [_seguidor(7, "uk-a", 3)]))

    assert entregas, "el webhook tenía que recibir el evento"
    for entrega in entregas:
        assert "seguidores" not in entrega["body"]["data"]
        assert "uk-a" not in json.dumps(entrega["body"])
        assert entrega["body"]["data"]["id_externo"] == "LIC-1"


def test_un_evento_de_instancia_sin_organizacion_solo_llega_a_los_globales(
    entregas: list[dict[str, Any]],
) -> None:
    evento = {
        "id": 502,
        "event_type": "solicitud_acceso.creada",
        "organization_id": None,
        "created_at": "2026-11-01T10:00:00+00:00",
        "payload": {"id": 5, "empresa": "ACME", "pendientes": 2},
    }

    assert _canal(evento) == 1
    assert [e["url"] for e in entregas] == ["https://hooks.example.test/global"]


def test_un_cambio_anterior_a_la_correccion_se_reparte_solo_por_sus_organizaciones(
    entregas: list[dict[str, Any]],
) -> None:
    """Los `licitacion.cambiada` que ya estaban en cola: sin organización y con
    los seguidores de todas. No se pierden para las organizaciones que sí
    siguen el expediente, ni salen por las que no."""
    legado = _cambio(None, [_seguidor(7, "uk-a")])

    assert _canal(legado) == 2
    assert sorted(e["url"] for e in entregas) == [
        "https://hooks.example.test/a",
        "https://hooks.example.test/global",
    ]
    assert all("seguidores" not in e["body"]["data"] for e in entregas)


def test_un_cambio_legado_con_seguidores_de_dos_organizaciones_llega_a_las_dos_una_vez(
    entregas: list[dict[str, Any]],
) -> None:
    assert _canal(_cambio(None, [_seguidor(7, "uk-a"), _seguidor(8, "uk-b")])) == 3

    assert sorted(e["url"] for e in entregas) == [
        "https://hooks.example.test/a",
        "https://hooks.example.test/b",
        "https://hooks.example.test/global",
    ]


# ── Repositorio: el predicado SQL ────────────────────────────────────────────


class _Conexion:
    def __init__(self, vistas: list[tuple[str, list[object]]]) -> None:
        self._vistas = vistas

    def __enter__(self) -> _Conexion:
        return self

    def __exit__(self, *_a: object) -> bool:
        return False

    def execute(self, sql: str, params: list[object]) -> list[Any]:
        self._vistas.append((sql, list(params)))
        return []


def test_sin_organizacion_el_repositorio_solo_pide_los_globales(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import db.repositories.webhooks as repos

    vistas: list[tuple[str, list[object]]] = []
    monkeypatch.setattr(repos, "connect_read", lambda: _Conexion(vistas))
    monkeypatch.setattr(repos, "rows_to_dicts", lambda cur: cur)

    repos.WebhookRepository().list_active_subscribers()
    repos.WebhookRepository().list_active_subscribers(organization_id=7)

    (sql_global, params_global), (sql_org, params_org) = vistas
    assert sql_global.endswith("AND organization_id IS NULL")
    assert params_global == []
    assert "(organization_id = %s OR organization_id IS NULL)" in sql_org
    assert params_org == [7]


def test_trigger_event_legado_solo_lee_los_webhooks_globales(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`watchlist_match` lleva el correo y los criterios del operador."""
    import db.webhooks as salida

    sqls: list[str] = []

    class _Cursor:
        def __enter__(self) -> _Cursor:
            return self

        def __exit__(self, *_a: object) -> bool:
            return False

        def execute(self, sql: str, *_a: object) -> _Cursor:
            sqls.append(sql)
            return self

        def fetchall(self) -> list[Any]:
            return []

    monkeypatch.setattr(salida, "connect", lambda: _Cursor())
    monkeypatch.setattr(salida, "_allowed_webhook_hosts", frozenset)

    assert salida.trigger_event("watchlist_match", {"recipient": "op@example.test"}) == 0
    assert len(sqls) == 1
    assert "organization_id IS NULL" in sqls[0]


# ── Plantillas: lo que escribe un visitante no es marcado ────────────────────

_HOSTIL = "<https://phish.example/login|Caducó tu sesión> <!channel> & [x](https://evil.example)"


def test_slack_escapa_los_valores_de_usuario_en_los_campos_y_en_el_texto() -> None:
    cuerpo = renderizar(
        "solicitud_acceso.creada",
        {"id": 5, "empresa": _HOSTIL, "titulo": _HOSTIL},
        formato="slack_blocks",
        timestamp="2026-11-01T10:00:00+00:00",
    )

    campos = [campo["text"] for bloque in cuerpo["blocks"] for campo in bloque.get("fields", [])]
    texto = "\n".join([cuerpo["text"], *campos])
    assert "<https://" not in texto
    assert "<!channel>" not in texto
    assert "&lt;https://phish.example/login|Caducó tu sesión&gt;" in texto
    assert "&lt;!channel&gt;" in texto
    assert "&amp;" in texto


def test_teams_escapa_los_corchetes_del_markdown() -> None:
    cuerpo = renderizar(
        "solicitud_acceso.creada",
        {"id": 5, "empresa": _HOSTIL, "titulo": _HOSTIL},
        formato="teams_adaptive_card",
        timestamp="2026-11-01T10:00:00+00:00",
    )

    tarjeta = cuerpo["attachments"][0]["content"]
    textos = [tarjeta["body"][0]["text"], *(h["value"] for h in tarjeta["body"][1]["facts"])]
    hostiles = [t for t in textos if "phish" in t]
    assert len(hostiles) == 3, "resumen, empresa y titulo"
    for texto in hostiles:
        assert "[x]" not in texto
        assert "\\[x\\]" in texto


def test_el_formato_json_no_cambia() -> None:
    cuerpo = renderizar(
        "solicitud_acceso.creada",
        {"id": 5, "empresa": _HOSTIL},
        formato="json",
        timestamp="2026-11-01T10:00:00+00:00",
    )

    assert cuerpo["data"]["empresa"] == _HOSTIL
