"""C6.1 y C6.2 por el outbox: tareas que vencen y menciones en comentarios.

Las dos piezas existían a medias: la consulta de tareas que vencen
(`PursuitTasksRepository.vencen_en`) y la de menciones
(`menciones_de_usuario`) estaban escritas «para cuando exista el outbox», y la
preferencia de Ajustes (`pursuit.task_due`, `pursuit.mention`) se podía guardar
sin que nada la leyera. Estos tests fijan el cableado:

- el productor escribe un evento del catálogo, **no** una notificación (el
  ratchet de `tests/test_s4_outbox_ratchet.py` lo prohíbe fuera del
  despachador);
- el despachador respeta lo que el usuario apagó en Ajustes.

Sin BD: los repositorios y la cola se sustituyen por dobles. Lo que se prueba es
la decisión (a quién, cuándo, cuántas veces), no el SQL.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

from shared.events import CATALOGO, especificacion, validar_payload

# ── Catálogo ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tipo", ["pursuit.task_due", "pursuit.mentioned"])
def test_los_eventos_de_c6_estan_en_el_catalogo_y_son_personales(tipo: str) -> None:
    spec = especificacion(tipo)
    assert {"in_app", "digest"} <= set(spec.canales)
    assert spec.tipo_notificacion, "sin tipo de notificación no hay clave de deduplicación"


def test_la_clave_de_ajustes_existe_en_la_pantalla_de_ajustes() -> None:
    """Una `clave_ajustes` que Ajustes no pinta es un interruptor que nadie puede tocar."""
    from db.repositories.notification_preferences import TIPOS

    en_ajustes = {clave for clave, _ in TIPOS}
    for spec in CATALOGO.values():
        if spec.clave_ajustes is not None:
            assert spec.clave_ajustes in en_ajustes, spec.tipo
            assert "digest" in spec.canales, spec.tipo


# ── C6.1: productor de tareas que vencen ─────────────────────────────────────


def _tarea(task_id: int, *, responsable: int | None = 5, org: int = 7) -> dict[str, Any]:
    return {
        "id": task_id,
        "pursuit_id": 40 + task_id,
        "organization_id": org,
        "titulo": f"Tarea {task_id}",
        "responsable_user_id": responsable,
        "vence": "2026-09-18",
        "licitacion_id": f"LIC-{task_id}",
    }


@pytest.fixture
def cola(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Outbox en memoria: `append_domain_event` valida como el real y apunta."""
    import db.events as events

    estado: dict[str, Any] = {"escritos": [], "previos": {}}

    def _append(
        event_type: str,
        aggregate_id: Any,
        aggregate_type: str,
        payload: dict[str, Any],
        **kwargs: Any,
    ) -> int:
        validar_payload(event_type, payload)
        estado["escritos"].append(
            {
                "event_type": event_type,
                "aggregate_id": aggregate_id,
                "aggregate_type": aggregate_type,
                "payload": payload,
                **kwargs,
            }
        )
        return len(estado["escritos"])

    def _get_events(aggregate_type: str, aggregate_id: Any, **_: Any) -> list[dict[str, Any]]:
        return list(estado["previos"].get((aggregate_type, int(aggregate_id)), []))

    monkeypatch.setattr(events, "append_domain_event", _append)
    monkeypatch.setattr(events, "get_events", _get_events)
    return estado


def _con_tareas(monkeypatch: pytest.MonkeyPatch, tareas: list[dict[str, Any]]) -> Any:
    import services.pursuit_tasks as mod

    class _Repo:
        def vencen_en(self, *, fecha: str) -> list[dict[str, Any]]:
            return [t for t in tareas if t["vence"] == fecha]

    monkeypatch.setattr(mod, "_repo", _Repo())
    return mod


def test_una_tarea_que_vence_hoy_escribe_un_evento_para_su_responsable(
    monkeypatch: pytest.MonkeyPatch, cola: dict[str, Any]
) -> None:
    mod = _con_tareas(monkeypatch, [_tarea(1)])

    assert mod.emitir_tareas_que_vencen("2026-09-18") == 1

    (evento,) = cola["escritos"]
    assert evento["event_type"] == "pursuit.task_due"
    assert evento["aggregate_type"] == "pursuit_task"
    assert evento["organization_id"] == 7
    assert evento["payload"]["destinatarios"] == [5]
    assert evento["payload"]["licitacion_id"] == "LIC-1"
    assert evento["payload"]["vence"] == "2026-09-18"


def test_la_segunda_pasada_del_dia_no_repite_el_aviso(
    monkeypatch: pytest.MonkeyPatch, cola: dict[str, Any]
) -> None:
    """El despachador corre varias veces al día; el correo, una."""
    mod = _con_tareas(monkeypatch, [_tarea(1)])
    cola["previos"][("pursuit_task", 1)] = [{"payload": {"vence": "2026-09-18"}}]

    assert mod.emitir_tareas_que_vencen("2026-09-18") == 0
    assert cola["escritos"] == []


def test_una_tarea_re_fechada_vuelve_a_avisar_el_dia_nuevo(
    monkeypatch: pytest.MonkeyPatch, cola: dict[str, Any]
) -> None:
    mod = _con_tareas(monkeypatch, [_tarea(1)])
    cola["previos"][("pursuit_task", 1)] = [{"payload": {"vence": "2026-09-10"}}]

    assert mod.emitir_tareas_que_vencen("2026-09-18") == 1


def test_una_tarea_sin_responsable_sale_sin_destinatario_personal(
    monkeypatch: pytest.MonkeyPatch, cola: dict[str, Any]
) -> None:
    """Adivinar a quién le toca sería peor que no avisar; el webhook sí la recibe."""
    mod = _con_tareas(monkeypatch, [_tarea(1, responsable=None)])

    assert mod.emitir_tareas_que_vencen("2026-09-18") == 1
    assert cola["escritos"][0]["payload"]["destinatarios"] == []


def test_sin_fecha_usa_hoy_en_espana(monkeypatch: pytest.MonkeyPatch, cola: dict[str, Any]) -> None:
    mod = _con_tareas(monkeypatch, [_tarea(1)])
    monkeypatch.setattr(mod, "_hoy_madrid", lambda: "2026-09-18")

    assert mod.emitir_tareas_que_vencen() == 1


# ── C6.2: productor de menciones ─────────────────────────────────────────────


def _montar_comentarios(
    monkeypatch: pytest.MonkeyPatch, *, creado: bool = True
) -> tuple[Any, list[tuple[int, list[int]]]]:
    import services.pursuit_comments as mod

    guardadas: list[tuple[int, list[int]]] = []

    @contextmanager
    def _alcance(user_id: int, organization_id: int | None, *, write: bool = False) -> Any:
        yield 7, "member"

    class _Pursuits:
        def get(self, organization_id: int, pursuit_id: int) -> dict[str, Any]:
            return {"id": pursuit_id, "licitacion_id": "LIC-9", "organization_id": organization_id}

    class _Orgs:
        def list_members(self, organization_id: int) -> list[dict[str, Any]]:
            return [
                {"user_id": 1, "display_name": "Ana Ruiz", "status": "active"},
                {"user_id": 3, "display_name": "Luis Gomez", "status": "active"},
            ]

    class _Repo:
        def create(self, **kwargs: Any) -> tuple[dict[str, Any], bool]:
            fila = {
                "id": 55,
                "pursuit_id": kwargs["pursuit_id"],
                "organization_id": kwargs["organization_id"],
                "author_user_id": kwargs["author_user_id"],
                "author_name": "Luis Gomez",
                "body": kwargs["body"],
                "created_at": "2026-09-18T08:00:00+00:00",
            }
            return fila, creado

        def guardar_menciones(self, comment_id: int, user_ids: list[int]) -> int:
            guardadas.append((comment_id, user_ids))
            return len(user_ids)

    monkeypatch.setattr(mod, "alcance_resuelto", _alcance)
    monkeypatch.setattr(mod, "_pursuits", _Pursuits())
    monkeypatch.setattr(mod, "_organizations", _Orgs())
    monkeypatch.setattr(mod, "_repo", _Repo())
    return mod, guardadas


def _comentar(mod: Any, texto: str, *, autor: int = 3) -> Any:
    from shared.dto import PursuitCommentCreate

    return mod.add_comment(autor, 12, PursuitCommentCreate(body=texto))


def test_mencionar_a_un_companero_escribe_pursuit_mentioned(
    monkeypatch: pytest.MonkeyPatch, cola: dict[str, Any]
) -> None:
    mod, guardadas = _montar_comentarios(monkeypatch)

    _comentar(mod, "@{Ana Ruiz} ¿revisas la garantía?")

    assert guardadas == [(55, [1])]
    (evento,) = cola["escritos"]
    assert evento["event_type"] == "pursuit.mentioned"
    assert evento["organization_id"] == 7
    assert evento["actor_id"] == 3
    payload = evento["payload"]
    assert payload["destinatarios"] == [1]
    assert payload["comment_id"] == 55
    assert payload["pursuit_id"] == 12
    assert payload["licitacion_id"] == "LIC-9"


def test_mencionarse_a_uno_mismo_no_escribe_evento(
    monkeypatch: pytest.MonkeyPatch, cola: dict[str, Any]
) -> None:
    mod, _ = _montar_comentarios(monkeypatch)

    _comentar(mod, "nota para mí, @{Luis Gomez}", autor=3)

    assert cola["escritos"] == []


def test_un_comentario_sin_menciones_no_escribe_evento(
    monkeypatch: pytest.MonkeyPatch, cola: dict[str, Any]
) -> None:
    mod, _ = _montar_comentarios(monkeypatch)

    _comentar(mod, "sin nadie a quien avisar")

    assert cola["escritos"] == []


def test_el_reintento_idempotente_no_vuelve_a_avisar(
    monkeypatch: pytest.MonkeyPatch, cola: dict[str, Any]
) -> None:
    """Un cliente que reenvía tras un corte no manda dos avisos."""
    mod, _ = _montar_comentarios(monkeypatch, creado=False)

    _comentar(mod, "@{Ana Ruiz} ¿revisas la garantía?")

    assert cola["escritos"] == []


def test_un_fallo_de_la_cola_no_pierde_el_comentario(monkeypatch: pytest.MonkeyPatch) -> None:
    import db.events as events

    mod, _ = _montar_comentarios(monkeypatch)

    def _roto(*_: Any, **__: Any) -> int:
        raise RuntimeError("outbox caído")

    monkeypatch.setattr(events, "append_domain_event", _roto)

    salida = _comentar(mod, "@{Ana Ruiz} ¿revisas la garantía?")
    assert salida.id == 55


# ── Despachador: clave de deduplicación y preferencias de Ajustes ─────────────


def test_cada_vencimiento_y_cada_mencion_son_avisos_distintos() -> None:
    from scheduler.jobs.event_dispatch import _tipo_notificacion

    tarea = especificacion("pursuit.task_due")
    mencion = especificacion("pursuit.mentioned")

    a = _tipo_notificacion({"payload": {"task_id": 1, "vence": "2026-09-18"}}, tarea)
    b = _tipo_notificacion({"payload": {"task_id": 1, "vence": "2026-09-25"}}, tarea)
    assert a != b
    c = _tipo_notificacion({"payload": {"comment_id": 5}}, mencion)
    d = _tipo_notificacion({"payload": {"comment_id": 6}}, mencion)
    assert c != d


@pytest.fixture
def despacho(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Despachador con destinatario fijo y puertas de salida grabadas."""
    import db.notifications as notifications
    import db.repositories.notification_preferences as prefs
    import scheduler.jobs.event_dispatch as mod
    import services.notifications as svc_notifications
    import services.watchlist as watchlist

    estado: dict[str, Any] = {
        "frecuencias": {},
        "notificaciones": [],
        "digests": [],
        "modo_email_de": 0,
    }

    monkeypatch.setattr(
        mod,
        "_destinatarios",
        lambda evento: [
            mod.Destinatario(user_key="uk-1", organization_id=7, user_id=1, email="a@b.es")
        ],
    )

    def _resolver(user_id: int, *, tipo: str, canal: str, organization_id: int | None) -> str:
        valor = estado["frecuencias"].get((tipo, canal))
        if isinstance(valor, Exception):
            raise valor
        return str(valor or prefs.frecuencia_por_defecto(canal))

    def _modo_email_de(*_: Any, **__: Any) -> str:
        estado["modo_email_de"] += 1
        return "immediate"

    monkeypatch.setattr(prefs, "resolver", _resolver)
    monkeypatch.setattr(svc_notifications, "modo_email_de", _modo_email_de)
    monkeypatch.setattr(
        notifications,
        "insert_user_notification",
        lambda **kw: estado["notificaciones"].append(kw) or True,
    )
    monkeypatch.setattr(
        watchlist, "store_pending_digest", lambda *a, **kw: estado["digests"].append(a)
    )
    estado["mod"] = mod
    return estado


def _evento_tarea() -> dict[str, Any]:
    return {
        "id": 900,
        "event_type": "pursuit.task_due",
        "organization_id": 7,
        "payload": {
            "pursuit_id": 41,
            "licitacion_id": "LIC-1",
            "task_id": 1,
            "vence": "2026-09-18",
            "destinatarios": [1],
            "titulo": "Tarea 1",
        },
    }


def test_in_app_apagado_en_ajustes_no_escribe_notificacion(despacho: dict[str, Any]) -> None:
    mod = despacho["mod"]
    despacho["frecuencias"][("pursuit.task_due", "in_app")] = "off"

    assert mod._canal_in_app(_evento_tarea(), especificacion("pursuit.task_due")) == 0
    assert despacho["notificaciones"] == []


def test_in_app_por_defecto_si_notifica(despacho: dict[str, Any]) -> None:
    mod = despacho["mod"]

    assert mod._canal_in_app(_evento_tarea(), especificacion("pursuit.task_due")) == 1
    (fila,) = despacho["notificaciones"]
    assert fila["type_"] == "pursuit_tarea_vence:1:2026-09-18"
    assert fila["licitacion_id"] == "LIC-1"


def test_el_correo_por_defecto_de_ajustes_va_al_digest_diario(despacho: dict[str, Any]) -> None:
    """El defecto del canal email en Ajustes es `daily`; el despachador lo obedece
    y no consulta `user_event_prefs`, que es de otros eventos."""
    mod = despacho["mod"]

    encoladas, enviados = mod._canal_digest(_evento_tarea(), especificacion("pursuit.task_due"))

    assert (encoladas, enviados) == (1, 0)
    assert despacho["modo_email_de"] == 0


def test_correo_apagado_en_ajustes_no_encola_nada(despacho: dict[str, Any]) -> None:
    mod = despacho["mod"]
    despacho["frecuencias"][("pursuit.mention", "email")] = "off"
    evento = {
        "id": 901,
        "event_type": "pursuit.mentioned",
        "organization_id": 7,
        "payload": {
            "pursuit_id": 12,
            "licitacion_id": "LIC-9",
            "comment_id": 55,
            "actor_user_id": 3,
            "destinatarios": [1],
        },
    }

    assert mod._canal_digest(evento, especificacion("pursuit.mentioned")) == (0, 0)
    assert despacho["digests"] == []


def test_preferencias_ilegibles_caen_al_defecto_y_no_a_silencio(despacho: dict[str, Any]) -> None:
    mod = despacho["mod"]
    despacho["frecuencias"][("pursuit.task_due", "email")] = RuntimeError("tabla a medio migrar")

    encoladas, _ = mod._canal_digest(_evento_tarea(), especificacion("pursuit.task_due"))

    assert encoladas == 1


def test_los_eventos_de_s46_siguen_leyendo_user_event_prefs(
    despacho: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """La clave de Ajustes es opt-in por evento: `pursuit.assigned` no cambia."""
    import observability.alerts as alerts
    import services.email_digest as email_digest

    mod = despacho["mod"]
    enviados: list[Any] = []
    monkeypatch.setattr(email_digest, "render_evento", lambda **_: ("texto", "<p>html</p>"))
    monkeypatch.setattr(
        alerts, "enviar_email_transaccional", lambda **kw: enviados.append(kw) or True
    )
    evento = {
        "id": 902,
        "event_type": "pursuit.assigned",
        "organization_id": 7,
        "payload": {"pursuit_id": 1, "licitacion_id": "L", "responsible_user_id": 1},
    }

    mod._canal_digest(evento, especificacion("pursuit.assigned"))

    assert despacho["modo_email_de"] == 1
    assert len(enviados) == 1


# ── run(): el productor de vencimientos va antes del despacho ────────────────


def test_run_emite_los_vencimientos_antes_de_despachar(monkeypatch: pytest.MonkeyPatch) -> None:
    import scheduler.jobs.event_dispatch as mod
    import services.pursuit_tasks as tareas

    orden: list[str] = []
    monkeypatch.setattr(tareas, "emitir_tareas_que_vencen", lambda: orden.append("emitir") or 2)
    monkeypatch.setattr(
        mod, "dispatch_pending", lambda: orden.append("despachar") or mod.ResultadoDespacho()
    )

    mod.run()

    assert orden == ["emitir", "despachar"]


def test_un_fallo_del_productor_no_para_el_despacho(monkeypatch: pytest.MonkeyPatch) -> None:
    import scheduler.jobs.event_dispatch as mod
    import services.pursuit_tasks as tareas

    def _roto() -> int:
        raise RuntimeError("BD caída")

    despachado: list[bool] = []
    monkeypatch.setattr(tareas, "emitir_tareas_que_vencen", _roto)
    monkeypatch.setattr(
        mod, "dispatch_pending", lambda: despachado.append(True) or mod.ResultadoDespacho()
    )

    mod.run()

    assert despachado == [True]
