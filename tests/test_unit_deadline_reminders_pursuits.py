"""Recordatorios de plazo de los pursuits, sin base de datos.

La consulta se sustituye por filas ya cargadas y el outbox por un registro en
memoria: lo que se comprueba es la lógica de ventanas y de destinatario.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest

import services.deadline_reminders as mod
from shared.dto import CondicionesOficiales, IndicioPliego, PlazoRecursoEspecial


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
        "fecha_publicacion": _en(-10),
        "next_action": None,
        "next_action_due": None,
    }
    base.update(extra)
    return base


def _condiciones(*, vence: str | None, indicios: bool = True) -> CondicionesOficiales:
    return CondicionesOficiales(
        licitacion_id="LIC-1",
        indicios=[
            IndicioPliego(
                codigo="juicio_de_valor_mayoritario",
                titulo="Más de la mitad de los puntos, por juicio de valor",
                detalle="60 % juicio de valor.",
                base_legal="Art. 146.2.a) LCSP",
            )
        ]
        if indicios
        else [],
        plazo_recurso=PlazoRecursoEspecial(vence=vence, desde="2026-01-01", base_legal="Art. 50")
        if vence
        else None,
    )


def _correr(
    filas: list[dict[str, Any]],
    *,
    ya_emitidos: bool = False,
    condiciones: CondicionesOficiales | None = None,
) -> list[dict[str, Any]]:
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
        patch.object(
            mod,
            "condiciones_oficiales_de",
            side_effect=lambda ids: dict.fromkeys(ids, condiciones) if condiciones else {},
        ),
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


def test_plazo_de_recurso_con_indicios_avisa_a_cinco_y_a_un_dia() -> None:
    escritas = _correr([_fila(fecha_limite=_en(20))], condiciones=_condiciones(vence=_en(1)))
    recurso = sorted(e["aviso"] for e in escritas if e["aviso"].startswith("recurso_"))
    assert recurso == ["recurso_1", "recurso_5"]
    assert all(_en(1) in e["detalle"] for e in escritas if e["aviso"].startswith("recurso_"))


@pytest.mark.parametrize(
    "condiciones",
    [
        pytest.param(_condiciones(vence=_en(1), indicios=False), id="sin-indicios"),
        pytest.param(_condiciones(vence=_en(-1)), id="vencido"),
        pytest.param(_condiciones(vence=_en(9)), id="fuera-de-ventana"),
        pytest.param(_condiciones(vence=None), id="sin-plazo"),
    ],
)
def test_plazo_de_recurso_sin_indicios_vencido_o_lejano_no_avisa(
    condiciones: CondicionesOficiales,
) -> None:
    escritas = _correr([_fila(fecha_limite=_en(20))], condiciones=condiciones)
    assert [e["aviso"] for e in escritas] == ["deadline_30"]


def test_plazo_de_recurso_avisa_aunque_la_presentacion_ya_haya_cerrado() -> None:
    escritas = _correr([_fila(fecha_limite=_en(-3))], condiciones=_condiciones(vence=_en(1)))
    assert sorted(e["aviso"] for e in escritas) == ["recurso_1", "recurso_5"]


def test_lo_publicado_antes_del_horizonte_no_lee_las_condiciones() -> None:
    viejo = _fila(fecha_limite=_en(1), fecha_publicacion=_en(-41))
    with (
        patch.object(mod.PursuitRepository, "deadline_rows", return_value=[viejo]),
        patch.object(mod, "agregados_con_evento", return_value=set()),
        patch.object(mod, "append_domain_event"),
        patch.object(mod, "condiciones_oficiales_de") as condiciones,
    ):
        mod.check_pursuit_deadlines()
    condiciones.assert_not_called()


def test_la_consulta_pide_lo_publicado_dentro_del_horizonte_del_recurso() -> None:
    with (
        patch.object(mod.PursuitRepository, "deadline_rows", return_value=[]) as consulta,
        patch.object(mod, "append_domain_event"),
    ):
        mod.check_pursuit_deadlines()
    assert consulta.call_args.kwargs["publicadas_desde"] == _en(-40)


def test_un_fallo_al_leer_las_condiciones_no_tapa_el_plazo_de_presentacion() -> None:
    escritos: list[dict[str, Any]] = []
    filas = [_fila(fecha_limite=_en(1))]
    with (
        patch.object(mod.PursuitRepository, "deadline_rows", return_value=filas),
        patch.object(mod, "agregados_con_evento", return_value=set()),
        patch.object(mod, "append_domain_event", side_effect=lambda *a, **_: escritos.append(a[3])),
        patch.object(mod, "condiciones_oficiales_de", side_effect=RuntimeError("sin base")),
    ):
        mod.check_pursuit_deadlines()
    assert sorted(e["aviso"] for e in escritos) == ["deadline_1", "deadline_30", "deadline_7"]


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
        patch.object(mod, "_notificar_favoritos", return_value=2) as notificar,
        patch.object(mod, "check_pursuit_deadlines", side_effect=RuntimeError("sin tabla")),
    ):
        assert mod.check_all_users_deadlines() == 2

    # Todos los usuarios en una sola llamada: las lecturas son por lote.
    assert [c.args[0] for c in notificar.call_args_list] == [[7, 8]]
    assert "user_id IS NOT NULL" in sentencias[0]


def test_check_all_users_sigue_con_pursuits_si_fallan_los_favoritos() -> None:
    with (
        patch.object(mod._repo_watchlist, "usuarios_con_favoritos", return_value=[7]),
        patch.object(mod, "_notificar_favoritos", side_effect=RuntimeError("boom")),
        patch.object(mod, "check_pursuit_deadlines", return_value=3),
        patch.object(mod, "check_radar_postponements", return_value=1),
    ):
        assert mod.check_all_users_deadlines() == 4


def test_un_fallo_en_los_avisos_de_un_usuario_no_tapa_los_de_otro() -> None:
    """La lectura es por lote, pero cada usuario se prepara por separado."""
    favoritos = [(7, "LIC-1", 70), (8, "LIC-2", 80)]
    lics = [
        {"id_externo": "LIC-1", "titulo": "Uno", "fecha_limite": _en(5)},
        {"id_externo": "LIC-2", "titulo": "Dos", "fecha_limite": _en(5)},
    ]
    escritos: list[dict[str, Any]] = []
    original = mod._candidatos_favoritos

    def _falla_para_7(user_id: int, *args: Any) -> list[Any]:
        if user_id == 7:
            raise RuntimeError("boom")
        return original(user_id, *args)

    with (
        patch.object(mod._repo_watchlist, "favoritos_con_organizacion", return_value=favoritos),
        patch.object(mod._repo_watchlist, "plazos_de_licitaciones", return_value=lics),
        patch.object(mod, "_candidatos_favoritos", side_effect=_falla_para_7),
        patch.object(mod, "agregados_con_evento", return_value=set()),
        patch.object(mod, "append_domain_event", side_effect=lambda *a, **_: escritos.append(a[3])),
        patch.object(mod, "condiciones_oficiales_de", return_value={}),
    ):
        assert mod._notificar_favoritos([7, 8], {}) == 2

    assert {e["organization_id"] for e in escritos} == {80}


def test_un_evento_que_la_base_rechaza_no_corta_el_lote() -> None:
    """Los avisos de todos van en una llamada a `_emitir`: cada escritura falla sola."""
    candidatos = [
        ("plazo.recordatorio", "a:LIC-1:7:70", {"n": 1}, 70),
        ("plazo.recordatorio", "a:LIC-2:8:80", {"n": 2}, 80),
    ]
    escritos: list[str] = []

    def _append(_tipo: str, clave: str, *_a: Any, **_k: Any) -> None:
        if clave.endswith(":70"):
            raise RuntimeError("rechazado")
        escritos.append(clave)

    with (
        patch.object(mod, "agregados_con_evento", return_value=set()),
        patch.object(mod, "append_domain_event", side_effect=_append),
    ):
        assert mod._emitir(candidatos) == 1

    assert escritos == ["a:LIC-2:8:80"]
