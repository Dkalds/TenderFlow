"""El healthcheck avisa del aviso TED que sigue sin su expediente de PLACSP.

Un aviso TED que enlaza PLACSP por ``idEvl`` espera a que el ATOM re-emita el
expediente. Pasado el plazo hay dos casos con remedio distinto: el expediente no
está en la BD (lo trae ``scraper.reproceso_ted``) o está y no se emparejó (el
reproceso se lo saltaría). La consulta se prueba contra Postgres en
``tests/test_documentos_plataforma.py``; aquí, sin BD, qué hace el informe con
ella.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch


def _fila(id_externo: str, fecha: str | None, *, en_bd: bool = False) -> dict[str, Any]:
    return {"id_externo": id_externo, "fecha_publicacion": fecha, "en_bd": en_bd}


def _incorporar(
    resultado: list[dict[str, Any]] | Exception,
) -> tuple[list[dict[str, object]], list[str], dict[str, object], str]:
    from scheduler.healthcheck import _incorporar_ted_esperando_placsp

    checks: list[dict[str, object]] = []
    warnings: list[str] = []
    info: dict[str, object] = {}
    efecto = (
        {"side_effect": resultado}
        if isinstance(resultado, Exception)
        else {"return_value": resultado}
    )
    with patch("db.repositories.dedupe.ted_esperando_placsp", **efecto) as consulta:
        _incorporar_ted_esperando_placsp(checks, warnings, info)
    return checks, warnings, info, consulta.call_args.args[0]


def test_sin_avisos_esperando_el_check_pasa_y_no_avisa() -> None:
    checks, warnings, info, _ = _incorporar([])

    assert warnings == []
    assert checks == [{"name": "ted_con_expediente_placsp", "ok": True}]
    assert info == {}


def test_sin_el_expediente_en_bd_degrada_y_da_el_reproceso_a_lanzar() -> None:
    hasta = datetime.now(UTC).strftime("%Y-%m")
    checks, warnings, info, _ = _incorporar(
        [_fila("ted:760321-2026", "2026-11-02"), _fila("ted:759105-2026", "2026-10-30")]
    )

    assert warnings == ["ted_esperando_placsp:2"]
    assert checks == [{"name": "ted_con_expediente_placsp", "ok": False}]
    # Plano: el correo de alerta descarta los valores que no lo son.
    assert info["ted_esperando_placsp"] == "ted:760321-2026, ted:759105-2026"
    # Desde el mes anterior al aviso más antiguo: PLACSP publica antes que TED.
    assert info["ted_esperando_placsp_reproceso"] == (
        f"python -m scraper.reproceso_ted --desde 2026-09 --hasta {hasta} --aplicar"
    )


def test_un_aviso_de_enero_pide_desde_diciembre_del_ano_anterior() -> None:
    _, _, info, _ = _incorporar([_fila("ted:1-2027", "2027-01-15")])

    assert "--desde 2026-12 " in str(info["ted_esperando_placsp_reproceso"])


def test_con_el_expediente_en_bd_sin_emparejar_no_manda_al_reproceso() -> None:
    checks, warnings, info, _ = _incorporar([_fila("ted:1-2026", "2026-11-02", en_bd=True)])

    assert warnings == ["ted_placsp_sin_emparejar:1"]
    assert checks == [{"name": "ted_con_expediente_placsp", "ok": False}]
    assert info == {"ted_placsp_sin_emparejar": "ted:1-2026"}


def test_no_poder_medirlo_no_tumba_el_informe() -> None:
    checks, warnings, info, _ = _incorporar(RuntimeError("BD caída"))

    assert warnings == ["ted_esperando_placsp_no_medido"]
    assert checks == [{"name": "ted_con_expediente_placsp", "ok": True}]
    assert "BD caída" in str(info["ted_esperando_placsp_error"])


def test_solo_cuentan_los_que_llevan_mas_de_tres_dias() -> None:
    from scheduler.healthcheck import TED_ESPERA_PLACSP_HORAS

    *_, antes_de = _incorporar([])

    corte = datetime.fromisoformat(antes_de)
    esperado = datetime.now(UTC) - timedelta(hours=TED_ESPERA_PLACSP_HORAS)
    assert TED_ESPERA_PLACSP_HORAS == 72
    assert abs((corte - esperado).total_seconds()) < 60
    # El mismo formato que `primera_extraccion`, que se compara como texto.
    assert antes_de.endswith("+00:00")
