"""Recordatorios de plazo de los pursuits, sin base de datos.

La consulta se sustituye por filas ya cargadas y la escritura por un registro
en memoria: lo que se comprueba es la lógica de ventanas y de destinatario.
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


def _correr(filas: list[dict[str, Any]], *, inserta: bool = True) -> list[dict[str, Any]]:
    escritas: list[dict[str, Any]] = []

    def _insert(**kwargs: Any) -> bool:
        escritas.append(kwargs)
        return inserta

    with (
        patch.object(mod.PursuitRepository, "deadline_rows", return_value=filas),
        patch.object(mod, "insert_user_notification", side_effect=_insert),
    ):
        total = mod.check_pursuit_deadlines()
    assert total == (len(escritas) if inserta else 0)
    return escritas


def test_plazo_a_cinco_dias_cae_en_las_ventanas_de_30_y_7_pero_no_en_la_de_1() -> None:
    escritas = _correr([_fila(fecha_limite=_en(5))])
    tipos = sorted(e["type_"] for e in escritas)
    assert tipos == ["deadline_30", "deadline_7"]
    assert all(e["licitacion_id"] == "LIC-1" and e["organization_id"] == 7 for e in escritas)
    assert "5 dia(s)" in escritas[0]["title"]


def test_accion_para_hoy_dispara_las_tres_ventanas_con_el_texto_hoy() -> None:
    escritas = _correr([_fila(next_action="Llamar al órgano", next_action_due=_en(0))])
    tipos = sorted(e["type_"] for e in escritas)
    assert tipos == ["accion_0", "accion_1", "accion_7"]
    assert all("hoy" in e["title"] and "Llamar al órgano" in e["title"] for e in escritas)


def test_sin_responsable_o_sin_email_no_hay_a_quien_avisar() -> None:
    assert _correr([_fila(responsible_email=None, fecha_limite=_en(1))]) == []
    assert _correr([_fila(responsible_user_id=None, fecha_limite=_en(1))]) == []


def test_fechas_pasadas_o_ilegibles_no_generan_avisos() -> None:
    assert _correr([_fila(fecha_limite=_en(-2), next_action_due="no-es-fecha")]) == []


def test_las_inserciones_deduplicadas_no_cuentan() -> None:
    escritas = _correr([_fila(fecha_limite=_en(1))], inserta=False)
    assert len(escritas) == 3  # se intentó en las tres ventanas


def test_check_all_users_suma_favoritos_y_pursuits_y_sobrevive_a_un_fallo() -> None:
    class _Cursor:
        def fetchall(self) -> list[tuple[str]]:
            return [("clave-a",), ("clave-b",)]

    class _Conn:
        def execute(self, *_: Any) -> _Cursor:
            return _Cursor()

        def __enter__(self) -> _Conn:
            return self

        def __exit__(self, *_: Any) -> bool:
            return False

    with (
        patch.object(mod, "connect_read", return_value=_Conn()),
        patch.object(mod, "check_deadlines_and_notify", side_effect=[2, RuntimeError("boom")]),
        patch.object(mod, "check_pursuit_deadlines", side_effect=RuntimeError("sin tabla")),
    ):
        assert mod.check_all_users_deadlines() == 2
