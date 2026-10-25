"""El publicador del outbox (ADR-027 §C), sin base de datos.

Lo que se fija aquí es el contrato del despachador, con la tabla de progreso
(``domain_event_dispatches``) y la cola (``domain_events.dispatched_at``)
sustituidas por un doble en memoria que reproduce su semántica:

- **exactamente una vez por consumidor**: cada canal (``in_app``, ``digest``,
  ``webhook``, ``cache``) recibe el evento una sola vez aunque el despachador
  pase N veces o haya dos pasadas a la vez (cierre y worker a demanda);
- **reintento tras fallo**: un canal que lanza libera su reclamo y la pasada
  siguiente repite *solo* ese canal; los que ya salieron no se repiten;
- **dos pasadas concurrentes**: si una da el evento por despachado mientras la
  otra sigue entregando y a esta le falla un canal, el evento vuelve a la cola
  (``release_channel`` lo reabre) y el canal no se pierde.

Lo mismo contra Postgres está en ``test_s4_outbox.py``.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

import pytest

from scheduler.jobs import event_dispatch

_EVENTO_ASIGNACION: dict[str, Any] = {
    "id": 41,
    "event_type": "pursuit.assigned",
    "organization_id": 7,
    "created_at": "2026-10-25T10:00:00+00:00",
    "payload": {
        "pursuit_id": 5,
        "licitacion_id": "LIC-1",
        "responsible_user_id": 3,
        "actor_user_id": 9,
    },
}


class _Outbox:
    """Doble en memoria de ``domain_events`` + ``domain_event_dispatches``."""

    def __init__(self, eventos: list[dict[str, Any]]) -> None:
        self.eventos = {int(e["id"]): dict(e) for e in eventos}
        self.despachados: set[int] = set()
        self.reclamos: set[tuple[int, str]] = set()

    def pending_events(self, limit: int) -> list[dict[str, Any]]:
        return [dict(self.eventos[i]) for i in sorted(self.eventos) if i not in self.despachados][
            :limit
        ]

    def claim_channel(self, event_id: int, canal: str) -> bool:
        if (event_id, canal) in self.reclamos:
            return False
        self.reclamos.add((event_id, canal))
        return True

    def release_channel(self, event_id: int, canal: str) -> None:
        self.reclamos.discard((event_id, canal))
        self.despachados.discard(event_id)

    def mark_dispatched(self, event_id: int) -> None:
        self.despachados.add(event_id)


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> _Outbox:
    doble = _Outbox([_EVENTO_ASIGNACION])
    monkeypatch.setattr(event_dispatch, "pending_events", doble.pending_events)
    monkeypatch.setattr(event_dispatch, "claim_channel", doble.claim_channel)
    monkeypatch.setattr(event_dispatch, "release_channel", doble.release_channel)
    monkeypatch.setattr(event_dispatch, "mark_dispatched", doble.mark_dispatched)
    monkeypatch.setattr(event_dispatch, "caducar_viejos", lambda _horas=None: 0)
    return doble


def _grabar_entregas(
    monkeypatch: pytest.MonkeyPatch, *, fallan: dict[str, int] | None = None
) -> Counter[str]:
    """Sustituye los canales por un contador; ``fallan`` dice cuántas veces lanza cada uno."""
    entregas: Counter[str] = Counter()
    pendientes_de_fallo = dict(fallan or {})

    def _despachar(canal: str, evento: dict[str, Any], spec: Any, resultado: Any) -> None:
        if pendientes_de_fallo.get(canal, 0) > 0:
            pendientes_de_fallo[canal] -= 1
            raise RuntimeError(f"{canal} caído")
        entregas[canal] += 1

    monkeypatch.setattr(event_dispatch, "_despachar_canal", _despachar)
    return entregas


def test_cada_consumidor_recibe_el_evento_exactamente_una_vez(
    outbox: _Outbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    entregas = _grabar_entregas(monkeypatch)

    primera = event_dispatch.dispatch_pending()
    for _ in range(3):
        event_dispatch.dispatch_pending()

    assert primera.procesados == 1
    assert entregas == Counter({"in_app": 1, "digest": 1, "webhook": 1})
    assert 41 in outbox.despachados


def test_un_canal_que_falla_se_reintenta_solo_el(
    outbox: _Outbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    entregas = _grabar_entregas(monkeypatch, fallan={"webhook": 1})

    primera = event_dispatch.dispatch_pending()
    assert primera.fallidos == 1 and primera.procesados == 0
    assert 41 not in outbox.despachados, "con un canal pendiente el evento sigue en la cola"
    assert entregas == Counter({"in_app": 1, "digest": 1})

    segunda = event_dispatch.dispatch_pending()
    assert segunda.procesados == 1
    assert entregas == Counter({"in_app": 1, "digest": 1, "webhook": 1})

    event_dispatch.dispatch_pending()
    assert entregas == Counter({"in_app": 1, "digest": 1, "webhook": 1})


def test_un_fallo_persistente_no_duplica_lo_que_ya_salio(
    outbox: _Outbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    entregas = _grabar_entregas(monkeypatch, fallan={"digest": 3})

    for _ in range(3):
        assert event_dispatch.dispatch_pending().fallidos == 1
    assert entregas == Counter({"in_app": 1, "webhook": 1})

    assert event_dispatch.dispatch_pending().procesados == 1
    assert entregas == Counter({"in_app": 1, "digest": 1, "webhook": 1})


def test_dos_pasadas_a_la_vez_no_pierden_el_canal_que_falla(
    outbox: _Outbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La pasada B (worker a demanda) encuentra todos los canales reclamados por
    la A (cierre), que sigue entregando, y da el evento por despachado. Si a la A
    le falla después el webhook, liberar el reclamo reabre el evento."""
    for canal in ("in_app", "digest", "webhook"):
        assert outbox.claim_channel(41, canal)  # la pasada A, en vuelo

    entregas = _grabar_entregas(monkeypatch)
    pasada_b = event_dispatch.dispatch_pending()
    assert pasada_b.procesados == 1 and entregas == Counter()
    assert 41 in outbox.despachados

    outbox.release_channel(41, "webhook")  # a la pasada A le falló el webhook
    assert 41 not in outbox.despachados

    event_dispatch.dispatch_pending()
    assert entregas == Counter({"webhook": 1})
    assert 41 in outbox.despachados


def test_un_evento_fuera_del_catalogo_sale_de_la_cola_sin_canales(
    outbox: _Outbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    outbox.eventos[42] = {"id": 42, "event_type": "cache.invalidated", "payload": {}}
    entregas = _grabar_entregas(monkeypatch)

    resultado = event_dispatch.dispatch_pending()

    assert resultado.ignorados == 1
    assert 42 in outbox.despachados
    assert entregas == Counter({"in_app": 1, "digest": 1, "webhook": 1})


def test_el_worker_a_demanda_solo_reparte(monkeypatch: pytest.MonkeyPatch) -> None:
    """El handler de la cola no corre los productores del cierre (vencimientos,
    documentos nuevos): esos tienen su cadencia y su cursor en el paso
    ``event_dispatch``."""
    from scheduler import worker
    from services.jobs import TIPO_DESPACHO_EVENTOS, TIPOS_A_DEMANDA, Job

    llamadas: list[str] = []

    def _dispatch() -> event_dispatch.ResultadoDespacho:
        llamadas.append("dispatch")
        return event_dispatch.ResultadoDespacho(procesados=2, in_app=1, webhooks=1)

    monkeypatch.setattr(event_dispatch, "dispatch_pending", _dispatch)
    monkeypatch.setattr(
        event_dispatch, "run", lambda: pytest.fail("el worker no corre los productores")
    )
    ahora = datetime(2026, 10, 25, tzinfo=UTC)
    job = Job(
        id=1,
        tipo=TIPO_DESPACHO_EVENTOS,
        payload={"motivo": "pursuit.assigned"},
        organization_id=None,
        estado="running",
        intentos=1,
        run_after=ahora,
        locked_by="test",
        locked_at=ahora,
        resultado=None,
        error_detail=None,
        created_at=ahora,
        updated_at=ahora,
    )

    resultado = worker.ejecutar_despacho_eventos(job)

    assert llamadas == ["dispatch"]
    assert resultado["procesados"] == 2 and resultado["motivo"] == "pursuit.assigned"
    assert TIPOS_A_DEMANDA[TIPO_DESPACHO_EVENTOS].clave_dedupe is None
