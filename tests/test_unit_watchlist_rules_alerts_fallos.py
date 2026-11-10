"""Un fallo al escribir una alerta no se traga, no avanza la ventana ni bloquea a otras reglas.

``_write_user_notifications`` tenía un ``except Exception`` pensado para una base
sin la tabla (v48): un corte de conexión o un timeout se registraba a nivel
``debug`` y el job seguía con la ventana de la regla ya avanzada, así que la
alerta se perdía sin que nadie lo viera. Y el bucle marcaba la regla como
notificada *antes* de escribir.

Desde 2026-11 la campana la escribe el despachador
(``event_dispatch._campana_de_regla``) y el job solo escribe el evento; las dos
garantías se conservan, cada una donde vive ahora.

Sin BD: la capa de persistencia es un doble.
"""

from __future__ import annotations

from typing import Any

import pytest
from psycopg import errors as pg_errors

from scheduler import watchlist_rules_alerts as alertas
from scheduler.jobs import event_dispatch


def _escribir_alerta(monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(event_dispatch, "_licitaciones", lambda ids: {})
    regla = {"id": 1, "user_key": "k", "user_id": 3, "keyword": "SAP", "organization_id": 7}
    return event_dispatch._campana_de_regla(regla, ["L1"], "2026-11-05T00:00:00+00:00")


def test_un_fallo_al_escribir_la_alerta_no_se_traga(monkeypatch: pytest.MonkeyPatch) -> None:
    def insertar(**_: object) -> int:
        raise pg_errors.OperationalError("connection reset by peer")

    monkeypatch.setattr("db.notifications.insert_user_notifications", insertar)

    with pytest.raises(pg_errors.OperationalError):
        _escribir_alerta(monkeypatch)


def test_sin_tabla_de_notificaciones_no_escribe_y_no_falla(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def insertar(**_: object) -> int:
        raise pg_errors.UndefinedTable('relation "user_notifications" does not exist')

    monkeypatch.setattr("db.notifications.insert_user_notifications", insertar)

    assert _escribir_alerta(monkeypatch) == 0


# ── El bucle: la ventana de una regla avanza solo si su evento quedó escrito ──


def _fila(rule_id: int) -> dict[str, Any]:
    return {
        "id": rule_id,
        "user_key": f"k{rule_id}",
        "keyword": "SAP",
        "frequency": "daily",
        "last_notified_at": None,
        "email": f"privado{rule_id}@example.test",
        "organization_id": 7,
        "user_id": None,
    }


def _pasada(
    monkeypatch: pytest.MonkeyPatch,
    filas: list[dict[str, Any]],
    *,
    coincidencias: list[dict[str, Any]] | None = None,
    falla: frozenset[int] = frozenset(),
    en_cola: frozenset[str] = frozenset(),
) -> tuple[list[tuple[str, int]], list[dict[str, Any]]]:
    """Cablea el bucle sin BD; devuelve lo que hizo con cada regla y los payloads."""
    eventos: list[tuple[str, int]] = []
    payloads: list[dict[str, Any]] = []
    nuevas = [{"id_externo": "L1"}] if coincidencias is None else coincidencias

    def emitir(_tipo: str, rule_id: int, _agregado: str, payload: dict[str, Any], **_: Any) -> int:
        eventos.append(("evento", rule_id))
        if rule_id in falla:
            raise pg_errors.OperationalError("connection reset by peer")
        payloads.append(payload)
        return 1

    monkeypatch.setattr(alertas, "filas_de_reglas_a_evaluar", lambda: filas)
    monkeypatch.setattr(alertas, "agregados_pendientes", lambda *_: set(en_cola))
    monkeypatch.setattr(alertas, "matches_since", lambda *_, **__: nuevas)
    monkeypatch.setattr(alertas, "append_domain_event", emitir)
    monkeypatch.setattr(
        alertas,
        "marcar_regla_notificada",
        lambda rule_id, _ts: eventos.append(("ventana", rule_id)),
    )
    return eventos, payloads


def test_la_ventana_avanza_despues_de_escribir_el_evento(monkeypatch: pytest.MonkeyPatch) -> None:
    eventos, _ = _pasada(monkeypatch, [_fila(1)])

    assert alertas.check_rules_and_notify() == 1

    assert eventos == [("evento", 1), ("ventana", 1)]


def test_una_regla_que_falla_no_bloquea_a_las_demas_ni_avanza_su_ventana(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    eventos, _ = _pasada(monkeypatch, [_fila(1), _fila(2)], falla=frozenset({1}))

    assert alertas.check_rules_and_notify() == 1

    # La 1 se intentó y su ventana quedó donde estaba (la siguiente pasada la
    # reintenta); la 2 se evaluó entera.
    assert eventos == [("evento", 1), ("evento", 2), ("ventana", 2)]


def test_sin_coincidencias_la_ventana_avanza_igual(monkeypatch: pytest.MonkeyPatch) -> None:
    eventos, _ = _pasada(monkeypatch, [_fila(1)], coincidencias=[])

    assert alertas.check_rules_and_notify() == 0

    assert eventos == [("ventana", 1)]


def test_una_regla_con_su_aviso_en_cola_ni_emite_ni_mueve_la_ventana(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    eventos, _ = _pasada(monkeypatch, [_fila(1), _fila(2)], en_cola=frozenset({"1"}))

    assert alertas.check_rules_and_notify() == 1

    assert eventos == [("evento", 2), ("ventana", 2)]


def test_el_evento_no_lleva_el_correo_ni_la_frecuencia_de_la_regla(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El payload es también el cuerpo del webhook de la organización."""
    _, payloads = _pasada(monkeypatch, [_fila(1)])

    alertas.check_rules_and_notify()

    (payload,) = payloads
    assert "email" not in payload and "frequency" not in payload
    assert "privado1@example.test" not in repr(payload)
    assert payload["licitaciones"] == ["L1"]
