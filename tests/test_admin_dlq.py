"""Admin de la DLQ: reencolar desde la consola (RFC ux-calidad-datos #4).

- Sin BD: la ruta traduce cada estado de :func:`db.dlq.requeue` a su respuesta,
  audita sólo lo que de verdad reencola y responde 404 a lo que no existe.
- Con BD (``tmp_db``): ``requeue`` deja la entrada vencida para
  ``scheduler.dlq_retry`` y no rompe el índice único de abiertas.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException

import api.routes.admin_dlq as ruta_mod

# ---------------------------------------------------------------------------
# Ruta (sin BD)
# ---------------------------------------------------------------------------


@pytest.fixture()
def auditoria(monkeypatch) -> list[dict[str, Any]]:
    eventos: list[dict[str, Any]] = []
    monkeypatch.setattr(ruta_mod, "log_event", lambda **kw: eventos.append(kw))
    return eventos


def _reintentar(monkeypatch, estado: str) -> Any:
    monkeypatch.setattr(ruta_mod, "requeue", lambda _id: estado)
    return asyncio.run(ruta_mod.reintentar_dlq(failure_id=7, admin={"user_id": 3}))


@pytest.mark.parametrize("estado", ["abierta", "agotada"])
def test_reencolar_audita_con_actor_y_recurso(monkeypatch, auditoria, estado):
    res = _reintentar(monkeypatch, estado)
    assert res.reencolada is True
    assert res.estado_previo == estado
    assert auditoria == [
        {
            "event_type": "dlq.requeued",
            "actor": "3",
            "user_id": 3,
            "resource": "failed_extraction:7",
            "detail": f"estado_previo={estado}",
        }
    ]


@pytest.mark.parametrize("estado", ["resuelta", "duplicada"])
def test_lo_que_no_se_reencola_no_se_audita(monkeypatch, auditoria, estado):
    res = _reintentar(monkeypatch, estado)
    assert res.reencolada is False
    assert res.detalle
    assert auditoria == []


def test_entrada_inexistente_es_404(monkeypatch, auditoria):
    with pytest.raises(HTTPException) as exc:
        _reintentar(monkeypatch, "inexistente")
    assert exc.value.status_code == 404
    assert auditoria == []


def test_listado_mapea_filas_y_resumen(monkeypatch):
    fila = {
        "id": 1,
        "fuente": "placsp",
        "scope": None,
        "error_type": "TimeoutError",
        "error_message": "timeout",
        "retry_count": 2,
        "created_at": "2026-09-18T10:00:00+00:00",
        "last_attempt_at": None,
    }
    monkeypatch.setattr(ruta_mod, "list_unresolved", lambda limit: [fila])
    monkeypatch.setattr(ruta_mod, "list_exhausted", lambda limit: [])
    monkeypatch.setattr(
        ruta_mod,
        "unresolved_summary",
        lambda: [{"fuente": "placsp", "scope": "", "n": 1, "retries": 2}],
    )
    monkeypatch.setattr(
        ruta_mod,
        "unresolved_error_summary",
        lambda: [{"error_type": "UndefinedColumn", "n": 36, "abiertas": 2, "agotadas": 34}],
    )
    res = asyncio.run(ruta_mod.listar_dlq(estado="abiertas", limit=50, _admin={}))
    assert res.items[0].fuente == "placsp" and res.items[0].retry_count == 2
    assert res.resumen[0].n == 1
    # El resumen por error cuenta abiertas Y agotadas: es lo que dice si
    # reencolar puede servir de algo (un error de esquema no se arregla solo).
    error = res.resumen_errores[0]
    assert (error.error_type, error.n, error.abiertas, error.agotadas) == (
        "UndefinedColumn",
        36,
        2,
        34,
    )

    vacio = asyncio.run(ruta_mod.listar_dlq(estado="agotadas", limit=50, _admin={}))
    assert vacio.items == [] and vacio.estado == "agotadas"


def test_las_rutas_exigen_admin():
    """Las tres rutas dependen de `require_admin`, no de la auth genérica."""
    from api.routes.dual_auth import require_admin

    rutas: list[Any] = list(ruta_mod.router.routes)
    assert len(rutas) == 3
    for route in rutas:
        dependencias = {d.call for d in route.dependant.dependencies}
        assert require_admin in dependencias, route.path


def _descartar(monkeypatch, estado: str) -> Any:
    monkeypatch.setattr(ruta_mod, "discard", lambda _id: estado)
    return asyncio.run(ruta_mod.descartar_dlq(failure_id=7, admin={"user_id": 3}))


@pytest.mark.parametrize("estado", ["abierta", "agotada"])
def test_descartar_audita_con_actor_y_recurso(monkeypatch, auditoria, estado):
    """Cerrar una entrada sin reintentarla es una decisión: deja rastro."""
    res = _descartar(monkeypatch, estado)
    assert res.descartada is True
    assert res.estado_previo == estado
    assert auditoria == [
        {
            "event_type": "dlq.discarded",
            "actor": "3",
            "user_id": 3,
            "resource": "failed_extraction:7",
            "detail": f"estado_previo={estado}",
        }
    ]


def test_descartar_lo_ya_resuelto_no_hace_ni_audita_nada(monkeypatch, auditoria):
    res = _descartar(monkeypatch, "resuelta")
    assert res.descartada is False
    assert res.detalle
    assert auditoria == []


def test_descartar_una_entrada_inexistente_es_404(monkeypatch, auditoria):
    with pytest.raises(HTTPException) as exc:
        _descartar(monkeypatch, "inexistente")
    assert exc.value.status_code == 404
    assert auditoria == []


def test_el_evento_de_descarte_esta_en_el_registro_de_auditoria():
    """`log_event` valida contra `EVENTOS`: un tipo sin registrar no se escribe."""
    from shared.audit_events import DLQ_DISCARDED, EVENTOS, FAMILIAS

    assert DLQ_DISCARDED == "dlq.discarded"
    assert DLQ_DISCARDED in EVENTOS
    assert DLQ_DISCARDED in FAMILIAS["operacion"]


# ---------------------------------------------------------------------------
# requeue (con BD)
# ---------------------------------------------------------------------------


def _id_de(fuente: str) -> int:
    from db.connection import connect

    with connect() as c:
        row = c.execute(
            "SELECT id FROM failed_extractions WHERE fuente = %s ORDER BY id DESC LIMIT 1",
            (fuente,),
        ).fetchone()
    return int(row[0])


def test_requeue_deja_la_entrada_vencida(tmp_db):
    from db import dlq
    from scheduler.dlq_retry import _is_due

    dlq.record_failure("run-1", "placsp", RuntimeError("x"))
    fid = _id_de("placsp")
    dlq.increment_retry(fid)
    dlq.increment_retry(fid)

    assert dlq.requeue(fid) == "abierta"
    fila = dlq.get_failure(fid)
    assert fila is not None
    assert fila["retry_count"] == 0 and fila["last_attempt_at"] is None
    # Backoff desde created_at con el tramo base: vencido para una fila vieja.
    fila["created_at"] = "2020-01-01T00:00:00+00:00"
    assert _is_due(fila)


def test_requeue_reabre_agotadas_y_respeta_la_unicidad(tmp_db):
    from db import dlq

    dlq.record_failure("run-1", "pscp", RuntimeError("x"), scope="s")
    vieja = _id_de("pscp")
    dlq.mark_exhausted(vieja)

    assert dlq.requeue(vieja) == "agotada"
    fila = dlq.get_failure(vieja)
    assert fila is not None and fila["exhausted_at"] is None

    # Se agota otra vez y aparece una gemela abierta: reabrir violaría el índice.
    dlq.mark_exhausted(vieja)
    dlq.record_failure("run-2", "pscp", RuntimeError("y"), scope="s")
    assert dlq.requeue(vieja) == "duplicada"
    fila = dlq.get_failure(vieja)
    assert fila is not None and fila["exhausted_at"] is not None


def test_requeue_no_toca_resueltas_ni_inexistentes(tmp_db):
    from db import dlq

    dlq.record_failure("run-1", "ted", RuntimeError("x"))
    fid = _id_de("ted")
    dlq.mark_resolved(fid)
    assert dlq.requeue(fid) == "resuelta"
    assert dlq.requeue(999_999) == "inexistente"


# ---------------------------------------------------------------------------
# discard y resumen por error (con BD)
# ---------------------------------------------------------------------------


def test_discard_cierra_abiertas_y_agotadas_y_salen_del_recuento(tmp_db):
    from db import dlq

    dlq.record_failure("run-1", "placsp", RuntimeError("x"))
    abierta = _id_de("placsp")
    dlq.record_failure("run-1", "pscp", RuntimeError("y"), scope="s")
    agotada = _id_de("pscp")
    dlq.mark_exhausted(agotada)

    assert dlq.discard(abierta) == "abierta"
    assert dlq.discard(agotada) == "agotada"

    assert dlq.count_unresolved() == 0
    assert dlq.list_exhausted() == []
    fila = dlq.get_failure(agotada)
    assert fila is not None and fila["resolved_at"] is not None


def test_discard_no_toca_resueltas_ni_inexistentes(tmp_db):
    from db import dlq

    dlq.record_failure("run-1", "ted", RuntimeError("x"))
    fid = _id_de("ted")
    dlq.mark_resolved(fid)
    antes = dlq.get_failure(fid)

    assert dlq.discard(fid) == "resuelta"
    assert dlq.discard(999_999) == "inexistente"
    despues = dlq.get_failure(fid)
    assert antes is not None and despues is not None
    assert despues["resolved_at"] == antes["resolved_at"]


def test_el_resumen_por_error_cuenta_abiertas_y_agotadas(tmp_db):
    from db import dlq

    dlq.record_failure("run-1", "placsp", KeyError("a"))
    dlq.record_failure("run-1", "pscp", KeyError("b"))
    dlq.mark_exhausted(_id_de("pscp"))
    dlq.record_failure("run-1", "ted", TimeoutError("c"))
    dlq.record_failure("run-1", "tacrc", ValueError("d"))
    dlq.mark_resolved(_id_de("tacrc"))

    resumen = {r["error_type"]: r for r in dlq.unresolved_error_summary()}

    assert set(resumen) == {"KeyError", "TimeoutError"}
    assert (resumen["KeyError"]["n"], resumen["KeyError"]["abiertas"]) == (2, 1)
    assert resumen["KeyError"]["agotadas"] == 1
    assert resumen["TimeoutError"]["n"] == 1
    # El más frecuente primero: es por donde se empieza a mirar.
    assert next(iter(dlq.unresolved_error_summary()))["error_type"] == "KeyError"
