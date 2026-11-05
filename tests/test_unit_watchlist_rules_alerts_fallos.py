"""Un fallo al escribir una alerta no se traga, no avanza la ventana ni bloquea a otras reglas.

``_write_user_notifications`` tenía un ``except Exception`` pensado para una base
sin la tabla (v48): un corte de conexión o un timeout se registraba a nivel
``debug`` y el job seguía con la ventana de la regla ya avanzada, así que la
alerta se perdía sin que nadie lo viera. Y el bucle marcaba la regla como
notificada *antes* de escribir.

Sin BD: la capa de persistencia es un doble.
"""

from __future__ import annotations

from typing import Any

import pytest
from psycopg import errors as pg_errors

from scheduler import watchlist_rules_alerts as alertas
from services.watchlist_rules import WatchlistRule


def _escribir_alerta() -> int:
    regla = WatchlistRule(keyword="SAP", frequency="daily", organization_id=7)
    coincidencias = [{"id_externo": "L1", "titulo": "t", "organo_contratacion": "o"}]
    return alertas._write_user_notifications(
        "k", 1, coincidencias, regla, "2026-11-05T00:00:00+00:00", user_id=3
    )


def test_un_fallo_al_escribir_la_alerta_no_se_traga(monkeypatch: pytest.MonkeyPatch) -> None:
    def insertar(**_: object) -> int:
        raise pg_errors.OperationalError("connection reset by peer")

    monkeypatch.setattr(alertas, "insert_user_notifications", insertar)

    with pytest.raises(pg_errors.OperationalError):
        _escribir_alerta()


def test_sin_tabla_de_notificaciones_no_escribe_y_no_falla(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def insertar(**_: object) -> int:
        raise pg_errors.UndefinedTable('relation "user_notifications" does not exist')

    monkeypatch.setattr(alertas, "insert_user_notifications", insertar)

    assert _escribir_alerta() == 0


# ── El bucle: la ventana de una regla avanza solo si su alerta quedó escrita ──


def _fila(rule_id: int) -> dict[str, Any]:
    return {
        "id": rule_id,
        "user_key": f"k{rule_id}",
        "keyword": "SAP",
        "frequency": "daily",
        "last_notified_at": None,
        "email": None,
        "organization_id": 7,
        "user_id": None,
    }


def _pasada(
    monkeypatch: pytest.MonkeyPatch,
    filas: list[dict[str, Any]],
    *,
    coincidencias: list[dict[str, Any]] | None = None,
    falla: frozenset[int] = frozenset(),
) -> list[tuple[str, int]]:
    """Cablea el bucle sin BD y devuelve, en orden, lo que hizo con cada regla."""
    eventos: list[tuple[str, int]] = []
    nuevas = [{"id_externo": "L1"}] if coincidencias is None else coincidencias

    def escribir(user_key: str, rule_id: int, *_: object, **__: object) -> int:
        eventos.append(("escribir", rule_id))
        if rule_id in falla:
            raise pg_errors.OperationalError("connection reset by peer")
        return 1

    monkeypatch.setattr(alertas, "filas_de_reglas_a_evaluar", lambda: filas)
    monkeypatch.setattr(alertas, "matches_since", lambda *_, **__: nuevas)
    monkeypatch.setattr(alertas, "_write_user_notifications", escribir)
    monkeypatch.setattr(
        alertas,
        "marcar_regla_notificada",
        lambda rule_id, _ts: eventos.append(("ventana", rule_id)),
    )
    monkeypatch.setattr("db.events.append_domain_event", lambda *_, **__: None)
    return eventos


def test_la_ventana_avanza_despues_de_escribir_la_alerta(monkeypatch: pytest.MonkeyPatch) -> None:
    eventos = _pasada(monkeypatch, [_fila(1)])

    assert alertas.check_rules_and_notify() == 1

    assert eventos == [("escribir", 1), ("ventana", 1)]


def test_una_regla_que_falla_no_bloquea_a_las_demas_ni_avanza_su_ventana(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    eventos = _pasada(monkeypatch, [_fila(1), _fila(2)], falla=frozenset({1}))

    assert alertas.check_rules_and_notify() == 1

    # La 1 se intentó y su ventana quedó donde estaba (la siguiente pasada la
    # reintenta); la 2 se evaluó entera.
    assert eventos == [("escribir", 1), ("escribir", 2), ("ventana", 2)]


def test_sin_coincidencias_la_ventana_avanza_igual(monkeypatch: pytest.MonkeyPatch) -> None:
    eventos = _pasada(monkeypatch, [_fila(1)], coincidencias=[])

    assert alertas.check_rules_and_notify() == 0

    assert eventos == [("ventana", 1)]
