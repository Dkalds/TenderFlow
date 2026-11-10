"""Recordatorios de plazo de los pursuits, sin base de datos.

La consulta se sustituye por filas ya cargadas y el outbox por un registro en
memoria: lo que se comprueba es la lógica de ventanas y de destinatario.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import services.deadline_reminders as mod


def _en(dias: int) -> str:
    return (datetime.now(UTC) + timedelta(days=dias)).date().isoformat()


def _fila(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "pursuit_id": 1,
        "organization_id": 7,
        "licitacion_id": "LIC-1",
        "responsible_user_id": 3,
        "responsible_email": "ana@example.com",
        "titulo": "Servicio TI",
        "fecha_limite": None,
        "next_action": None,
        "next_action_due": None,
    }
    base.update(extra)
    return base


def _correr(filas: list[dict[str, Any]], *, ya_emitidos: bool = False) -> list[dict[str, Any]]:
    """Payloads que la pasada escribe en el outbox."""
    escritos: list[dict[str, Any]] = []

    def _ya(_tipo: str, _agregado: str, claves: set[str]) -> set[str]:
        return set(claves) if ya_emitidos else set()

    def _append(_tipo: str, _clave: str, _agregado: str, payload: dict[str, Any], **_: Any) -> int:
        escritos.append(payload)
        return len(escritos)

    with (
        patch.object(mod.PursuitRepository, "deadline_rows", return_value=filas),
        patch.object(mod, "agregados_con_evento", side_effect=_ya),
        patch.object(mod, "append_domain_event", side_effect=_append),
    ):
        total = mod.check_pursuit_deadlines()
    assert total == len(escritos)
    return escritos


def test_plazo_a_cinco_dias_cae_en_las_ventanas_de_30_y_7_pero_no_en_la_de_1() -> None:
    escritas = _correr([_fila(fecha_limite=_en(5))])
    tipos = sorted(e["aviso"] for e in escritas)
    assert tipos == ["deadline_30", "deadline_7"]
    assert all(e["licitacion_id"] == "LIC-1" and e["organization_id"] == 7 for e in escritas)
    assert all(e["seguidores"] == [{"user_id": 3, "organization_id": 7}] for e in escritas)
    assert "5 dia(s)" in escritas[0]["aviso_titulo"]


def test_accion_para_hoy_dispara_las_tres_ventanas_con_el_texto_hoy() -> None:
    escritas = _correr([_fila(next_action="Llamar al órgano", next_action_due=_en(0))])
    tipos = sorted(e["aviso"] for e in escritas)
    assert tipos == ["accion_0", "accion_1", "accion_7"]
    assert all("hoy" in e["aviso_titulo"] and e["titulo"] == "Llamar al órgano" for e in escritas)


def test_sin_responsable_o_sin_email_no_hay_a_quien_avisar() -> None:
    assert _correr([_fila(responsible_email=None, fecha_limite=_en(1))]) == []
    assert _correr([_fila(responsible_user_id=None, fecha_limite=_en(1))]) == []


def test_fechas_pasadas_o_ilegibles_no_generan_avisos() -> None:
    assert _correr([_fila(fecha_limite=_en(-2), next_action_due="no-es-fecha")]) == []


def test_lo_ya_emitido_no_se_vuelve_a_emitir() -> None:
    assert _correr([_fila(fecha_limite=_en(1))], ya_emitidos=True) == []


def test_check_all_users_suma_favoritos_y_pursuits_y_sobrevive_a_un_fallo() -> None:
    sentencias: list[str] = []

    class _Cursor:
        # Una columna desde v181: la consulta es
        # `SELECT DISTINCT user_id ... WHERE user_id IS NOT NULL`. Las filas sin
        # id (claves que ningún usuario reclamó) no tienen a quién avisar y la
        # propia consulta las deja fuera.
        def fetchall(self) -> list[tuple[int]]:
            return [(7,), (8,)]

    class _Conn:
        def execute(self, sql: str, *_: Any) -> _Cursor:
            sentencias.append(sql)
            return _Cursor()

        def __enter__(self) -> _Conn:
            return self

        def __exit__(self, *_: Any) -> bool:
            return False

    with (
        patch("db.repositories.watchlist.connect_read", return_value=_Conn()),
        patch.object(
            mod, "check_deadlines_and_notify", side_effect=[2, RuntimeError("boom")]
        ) as comprobar,
        patch.object(mod, "check_pursuit_deadlines", side_effect=RuntimeError("sin tabla")),
    ):
        assert mod.check_all_users_deadlines() == 2

    assert [c.args for c in comprobar.call_args_list] == [(7,), (8,)]
    assert "user_id IS NOT NULL" in sentencias[0]
