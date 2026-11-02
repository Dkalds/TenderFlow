"""Lectura de las puntuaciones del acta para la ficha (``services/puntuaciones_acta``).

Sin BD: los repositorios están sustituidos. Las cifras son las del acta real del
expediente 1611/2026 del Ayuntamiento de Astillero (lote 1: ASAP GLOBAL SOLUTION
100 puntos, ADELANTE SERVICIOS INFORMÁTICOS 77,54), repartidas aquí en dos lotes
cuando el caso lo pide.

La segunda mitad cubre lo que ``services/pursuits.py`` hace con esa lectura: la
ficha la lleva en la adjudicación (fail-open) y el PATCH de ``fila_acta`` la
valida y la anota en el ledger sin tocar la oportunidad.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import services.pursuits as pursuits_mod
from db.repositories.pursuits import PursuitConcurrencyError
from services.normalization import normalize_company
from services.puntuaciones_acta import puntuaciones_de_pursuit, validar_fila_acta
from shared.dto import FilaActaRef, PuntuacionesActa, PursuitUpdate
from tests.dobles_tenencia import alcance_fijo

_LIC = "EXP-1611"
_ORG = 7
_PURSUIT = 11

_ADELANTE = "ADELANTE SERVICIOS INFORMÁTICOS S.L."
_ASAP = "ASAP GLOBAL SOLUTION S.L."
_ADELANTE_N = "ADELANTE SERVICIOS INFORMATICOS"
_ASAP_N = "ASAP GLOBAL SOLUTION"

# (criterio, puntos, máximo, es_precio)
_TECNICO = "Informe técnico"
_TIEMPO = "Tiempo de respuesta"
_PRECIO = "Oferta económica"

_ids = iter(range(1, 10_000))


def _filas(
    lote: str | None,
    licitador: str,
    criterios: list[tuple[str, float | None, float | None, bool | None]],
    total: float | None,
    *,
    excluida: bool = False,
    documento_id: int = 1,
    pagina: int = 2,
) -> list[dict[str, Any]]:
    """Las filas de BD de un licitador: una por criterio y la del total (``criterio`` ``None``)."""
    normalizado = normalize_company(licitador)
    comunes = {
        "lote_numero": lote,
        "licitador_nombre": licitador,
        "licitador_normalizado": normalizado,
        "excluida": excluida,
        "documento_id": documento_id,
        "pagina": pagina,
    }
    por_criterio = [
        {
            **comunes,
            "id": next(_ids),
            "criterio": nombre,
            "puntos": puntos,
            "puntos_max": maximo,
            "es_precio": es_precio,
            "cita": f"{licitador} {nombre}",
        }
        for nombre, puntos, maximo, es_precio in criterios
    ]
    total_fila = {
        **comunes,
        "id": next(_ids),
        "criterio": None,
        "puntos": total,
        "puntos_max": None,
        "es_precio": None,
        "cita": f"{licitador} total",
    }
    return [*por_criterio, total_fila]


def _adelante(lote: str | None = "1") -> list[dict[str, Any]]:
    return _filas(
        lote,
        _ADELANTE,
        [(_TECNICO, 28, 30, False), (_TIEMPO, 5, 5, False), (_PRECIO, 44.54, 65, True)],
        77.54,
    )


def _asap(lote: str | None = "1", *, pagina: int = 2) -> list[dict[str, Any]]:
    return _filas(
        lote,
        _ASAP,
        [(_TECNICO, 30, 30, False), (_TIEMPO, 5, 5, False), (_PRECIO, 65, 65, True)],
        100,
        pagina=pagina,
    )


def _evento(lote: str | None, licitador_normalizado: str) -> dict[str, Any]:
    return {
        "actor_user_id": 1,
        "payload_json": json.dumps(
            {"lote_numero": lote, "licitador_normalizado": licitador_normalizado}
        ),
        "created_at": "2026-11-02T10:00:00+00:00",
    }


@dataclass
class _Mundo:
    """Lo que devuelven los repositorios; cada test rellena lo que necesita."""

    extraccion: dict[str, Any] | None = field(default_factory=lambda: {"status": "ok"})
    tiene_actas: bool = True
    puntuaciones: list[dict[str, Any]] = field(default_factory=list)
    adjudicatarios: list[dict[str, Any]] = field(default_factory=list)
    nombres_org: list[str] = field(default_factory=list)
    eventos: list[dict[str, Any]] = field(default_factory=list)


@pytest.fixture
def mundo() -> Iterator[_Mundo]:
    m = _Mundo()
    with (
        patch("services.puntuaciones_acta.PuntuacionesActaRepository") as acta_cls,
        patch("services.puntuaciones_acta.PursuitRepository") as pursuit_cls,
    ):
        repo = acta_cls.return_value
        repo.get_extraccion.side_effect = lambda _lic: m.extraccion
        repo.tiene_actas.side_effect = lambda _lic: m.tiene_actas
        repo.list_puntuaciones.side_effect = lambda _lic: list(m.puntuaciones)
        repo.adjudicatarios_por_lote.side_effect = lambda _lic: list(m.adjudicatarios)
        repo.nombres_de_organizacion.side_effect = lambda _org: list(m.nombres_org)
        pursuit_cls.return_value.fila_acta_events.side_effect = lambda _org, _p: list(m.eventos)
        yield m


def _leer(lote_pursuit: str | None = None) -> PuntuacionesActa | None:
    return puntuaciones_de_pursuit(
        licitacion_id=_LIC, organization_id=_ORG, pursuit_id=_PURSUIT, lote_pursuit=lote_pursuit
    )


def _lote_unico(mundo: _Mundo) -> Any:
    resultado = _leer()
    assert resultado is not None and resultado.estado == "ok"
    assert len(resultado.lotes) == 1
    return resultado.lotes[0]


# --- Estado -------------------------------------------------------------------


def test_sin_actas_ni_extraccion_es_none(mundo: _Mundo) -> None:
    mundo.extraccion = None
    mundo.tiene_actas = False

    assert _leer() is None


def test_con_actas_sin_extraccion_es_pendiente(mundo: _Mundo) -> None:
    mundo.extraccion = None
    mundo.tiene_actas = True

    assert _leer() == PuntuacionesActa(estado="pendiente", lotes=[])


@pytest.mark.parametrize("status", ["sin_acta", "sin_tabla", "error"])
def test_estados_sin_filas(mundo: _Mundo, status: str) -> None:
    mundo.extraccion = {"status": status}
    # Aunque quedaran filas de una lectura anterior, solo ``ok`` trae lotes.
    mundo.puntuaciones = [*_asap(), *_adelante()]

    resultado = _leer()

    assert resultado is not None
    assert (resultado.estado, resultado.lotes) == (status, [])


# --- Agrupación y orden -------------------------------------------------------


def test_ok_agrupa_por_lote_ordena_excluidas_al_final(mundo: _Mundo) -> None:
    excluida = _filas("1", "CONSTRUCCIONES EXCLUIDAS S.A.", [], None, excluida=True)
    sin_total = _filas("1", "OFERTA SIN TOTAL S.L.", [(_TECNICO, 10, 30, False)], None)
    mundo.puntuaciones = [
        *excluida,  # primera en el acta, pero excluida: va al final
        *_adelante(),
        *sin_total,
        *_asap(),
        *_asap("2", pagina=3),
    ]

    resultado = _leer()

    assert resultado is not None and resultado.estado == "ok"
    assert [lote.lote_numero for lote in resultado.lotes] == ["1", "2"]
    lote1, lote2 = resultado.lotes
    assert [f.licitador_normalizado for f in lote1.filas] == [
        _ASAP_N,
        _ADELANTE_N,
        "OFERTA SIN TOTAL",
        "CONSTRUCCIONES EXCLUIDAS",
    ]
    assert [f.total for f in lote1.filas] == [100, 77.54, None, None]
    assert [f.excluida for f in lote1.filas] == [False, False, False, True]
    assert [f.licitador for f in lote2.filas] == [_ASAP]
    assert lote2.filas[0].criterios[0].pagina == 3

    asap = lote1.filas[0]
    assert [c.nombre for c in asap.criterios] == [_TECNICO, _TIEMPO, _PRECIO]
    precio = asap.criterios[2]
    assert (precio.puntos, precio.maximo, precio.es_precio) == (65, 65, True)
    assert (precio.documento_id, precio.pagina) == (1, 2)
    assert precio.cita == f"{_ASAP} {_PRECIO}"


# --- Fila ganadora ------------------------------------------------------------


def test_ganadora_es_el_adjudicatario_publicado(mundo: _Mundo) -> None:
    # El adjudicatario publicado no es el de más puntos: manda el publicado.
    mundo.puntuaciones = [*_asap(), *_adelante()]
    mundo.adjudicatarios = [
        {"lote_numero": None, "nombre": "Adelante Servicios Informáticos SL", "nif": None}
    ]

    lote = _lote_unico(mundo)

    assert lote.filas[lote.fila_ganadora].licitador_normalizado == _ADELANTE_N
    assert lote.ganadora_es_mayor_puntuacion is False


def test_sin_adjudicatario_que_case_la_ganadora_es_la_de_mayor_puntuacion(mundo: _Mundo) -> None:
    mundo.puntuaciones = [*_adelante(), *_asap()]
    mundo.adjudicatarios = [{"lote_numero": None, "nombre": "OTRA EMPRESA SL", "nif": None}]

    lote = _lote_unico(mundo)

    assert lote.filas[lote.fila_ganadora].licitador_normalizado == _ASAP_N
    assert lote.ganadora_es_mayor_puntuacion is True


def test_ganadora_casa_por_lote(mundo: _Mundo) -> None:
    """El adjudicatario del lote 1 no es la ganadora del lote 2."""
    mundo.puntuaciones = [
        *_asap("1"),
        *_adelante("1"),
        *_asap("2"),
        *_adelante("2"),
    ]
    mundo.adjudicatarios = [
        {"lote_numero": "Lote 1", "nombre": _ADELANTE, "nif": None},
        {"lote_numero": "2", "nombre": _ASAP, "nif": None},
    ]

    resultado = _leer()

    assert resultado is not None
    lote1, lote2 = resultado.lotes
    assert lote1.filas[lote1.fila_ganadora].licitador_normalizado == _ADELANTE_N
    assert lote1.ganadora_es_mayor_puntuacion is False
    assert lote2.filas[lote2.fila_ganadora].licitador_normalizado == _ASAP_N
    assert lote2.ganadora_es_mayor_puntuacion is False


def test_adjudicatario_del_lote_1_no_casa_en_el_lote_2(mundo: _Mundo) -> None:
    mundo.puntuaciones = [*_asap("1"), *_adelante("1"), *_asap("2"), *_adelante("2")]
    # Solo se adjudicó el lote 1, a la de menos puntos. En el lote 2 nadie casa.
    mundo.adjudicatarios = [{"lote_numero": "1", "nombre": _ADELANTE, "nif": None}]

    lote1, lote2 = _dos_lotes(mundo)

    assert lote1.ganadora_es_mayor_puntuacion is False
    assert lote2.ganadora_es_mayor_puntuacion is True
    assert lote2.filas[lote2.fila_ganadora].licitador_normalizado == _ASAP_N


def test_adjudicatario_sin_lote_vale_para_todos_los_lotes(mundo: _Mundo) -> None:
    mundo.puntuaciones = [*_asap("1"), *_adelante("1"), *_asap("2"), *_adelante("2")]
    mundo.adjudicatarios = [{"lote_numero": None, "nombre": _ADELANTE, "nif": None}]

    lote1, lote2 = _dos_lotes(mundo)

    for lote in (lote1, lote2):
        assert lote.filas[lote.fila_ganadora].licitador_normalizado == _ADELANTE_N
        assert lote.ganadora_es_mayor_puntuacion is False


def _dos_lotes(mundo: _Mundo) -> tuple[Any, Any]:
    resultado = _leer()
    assert resultado is not None and len(resultado.lotes) == 2
    return resultado.lotes[0], resultado.lotes[1]


# --- Fila propia, diferencia y motivo -----------------------------------------


def test_propuesta_sin_confirmar(mundo: _Mundo) -> None:
    mundo.puntuaciones = [*_adelante(), *_asap()]
    mundo.adjudicatarios = [{"lote_numero": None, "nombre": _ASAP, "nif": None}]
    mundo.nombres_org = ["Adelante Servicios Informáticos, S.L.", "Otro Nombre"]

    lote = _lote_unico(mundo)

    assert lote.fila_propia is not None
    assert lote.filas[lote.fila_propia].licitador_normalizado == _ADELANTE_N
    assert lote.fila_propia_confirmada is False
    assert lote.filas[lote.fila_ganadora].licitador_normalizado == _ASAP_N
    # Se perdió sobre todo en la oferta económica (-20,46 de 65) y poco en lo técnico (-2).
    assert lote.motivo_sugerido == "precio"
    por_criterio = {d.criterio: d for d in lote.diferencia}
    assert set(por_criterio) == {_TECNICO, _TIEMPO, _PRECIO, None}
    assert por_criterio[_TECNICO].diferencia == -2
    assert por_criterio[_TECNICO].maximo == 30
    assert por_criterio[_TECNICO].es_precio is False
    assert por_criterio[_PRECIO].diferencia == -20.46
    assert por_criterio[_PRECIO].es_precio is True
    assert por_criterio[None].diferencia == -22.46
    assert por_criterio[None].maximo is None


def test_motivo_tecnica_cuando_se_pierde_mas_en_lo_tecnico(mundo: _Mundo) -> None:
    propia = _filas("1", _ADELANTE, [(_TECNICO, 10, 30, False), (_PRECIO, 64, 65, True)], 74)
    mundo.puntuaciones = [*propia, *_asap()]
    mundo.nombres_org = [_ADELANTE]

    assert _lote_unico(mundo).motivo_sugerido == "tecnica"


def test_la_diferencia_enlaza_a_la_pagina_de_la_ganadora(mundo: _Mundo) -> None:
    mundo.puntuaciones = [*_adelante(), *_asap(pagina=5)]
    mundo.adjudicatarios = [{"lote_numero": None, "nombre": _ASAP, "nif": None}]
    mundo.nombres_org = [_ADELANTE]

    lote = _lote_unico(mundo)

    assert lote.diferencia
    assert all((d.documento_id, d.pagina) == (1, 5) for d in lote.diferencia)


def test_confirmacion_gana_a_la_propuesta(mundo: _Mundo) -> None:
    """El último evento del lote manda sobre la propuesta y sobre los anteriores."""
    mundo.puntuaciones = [*_adelante(), *_asap()]
    mundo.nombres_org = [_ADELANTE]  # la propuesta sería ADELANTE
    mundo.eventos = [
        _evento("1", _ADELANTE_N),
        _evento("1", _ASAP_N),  # el último del lote manda
        _evento("2", _ADELANTE_N),  # otro lote: no cuenta
    ]

    lote = _lote_unico(mundo)

    assert lote.filas[lote.fila_propia].licitador_normalizado == _ASAP_N
    assert lote.fila_propia_confirmada is True


def test_confirmacion_huerfana_vuelve_a_la_propuesta(mundo: _Mundo) -> None:
    """Una fila que la nueva lectura del acta ya no trae no deja la ficha sin fila propia."""
    mundo.puntuaciones = [*_adelante(), *_asap()]
    mundo.nombres_org = [_ADELANTE]
    mundo.eventos = [_evento("1", "EMPRESA QUE YA NO ESTA")]

    lote = _lote_unico(mundo)

    assert lote.filas[lote.fila_propia].licitador_normalizado == _ADELANTE_N
    assert lote.fila_propia_confirmada is False


def test_confirmacion_sin_propuesta(mundo: _Mundo) -> None:
    mundo.puntuaciones = [*_adelante(), *_asap()]
    mundo.eventos = [_evento("1", _ADELANTE_N)]

    lote = _lote_unico(mundo)

    assert lote.filas[lote.fila_propia].licitador_normalizado == _ADELANTE_N
    assert lote.fila_propia_confirmada is True


def test_evento_ilegible_no_rompe_la_lectura(mundo: _Mundo) -> None:
    mundo.puntuaciones = [*_adelante(), *_asap()]
    mundo.eventos = [
        {"actor_user_id": 1, "payload_json": "no es json", "created_at": "x"},
        {"actor_user_id": 1, "payload_json": '{"otra": "cosa"}', "created_at": "x"},
        _evento("1", _ASAP_N),
    ]

    lote = _lote_unico(mundo)

    assert lote.filas[lote.fila_propia].licitador_normalizado == _ASAP_N
    assert lote.fila_propia_confirmada is True


def test_sin_propia_no_hay_diferencia_ni_motivo(mundo: _Mundo) -> None:
    mundo.puntuaciones = [*_adelante(), *_asap()]
    mundo.adjudicatarios = [{"lote_numero": None, "nombre": _ASAP, "nif": None}]
    mundo.nombres_org = ["Una Empresa Distinta"]

    lote = _lote_unico(mundo)

    assert lote.fila_propia is None
    assert lote.fila_propia_confirmada is False
    assert lote.diferencia == []
    assert lote.motivo_sugerido is None


def test_si_la_propia_es_la_ganadora_no_hay_diferencia_ni_motivo(mundo: _Mundo) -> None:
    mundo.puntuaciones = [*_adelante(), *_asap()]
    mundo.adjudicatarios = [{"lote_numero": None, "nombre": _ASAP, "nif": None}]
    mundo.nombres_org = [_ASAP]

    lote = _lote_unico(mundo)

    assert lote.fila_propia == lote.fila_ganadora
    assert lote.diferencia == []
    assert lote.motivo_sugerido is None


def test_nombres_de_la_organizacion_vacios_o_none_no_rompen(mundo: _Mundo) -> None:
    mundo.puntuaciones = [*_adelante(), *_asap()]
    mundo.nombres_org = ["", ".,-"]  # no normalizan a nada

    assert _lote_unico(mundo).fila_propia is None


# --- Lote de la oportunidad ---------------------------------------------------


def test_puntuaciones_filtra_el_lote_de_la_oportunidad(mundo: _Mundo) -> None:
    mundo.puntuaciones = [*_asap("1"), *_adelante("1"), *_asap("2"), *_adelante("3")]

    solo_el_2 = _leer("2")
    ausente = _leer("9")
    sin_lote = _leer(None)
    con_texto = _leer("Lote nº 2: Servicio de limpieza")

    assert solo_el_2 is not None and [lote.lote_numero for lote in solo_el_2.lotes] == ["2"]
    # El lote de la oportunidad no está en el acta: se enseña todo, no nada.
    assert ausente is not None and [lote.lote_numero for lote in ausente.lotes] == ["1", "2", "3"]
    assert sin_lote is not None and [lote.lote_numero for lote in sin_lote.lotes] == ["1", "2", "3"]
    assert con_texto is not None and [lote.lote_numero for lote in con_texto.lotes] == ["2"]


def test_acta_sin_lotes_se_enseña_aunque_la_oportunidad_tenga_lote(mundo: _Mundo) -> None:
    mundo.puntuaciones = [*_asap(None), *_adelante(None)]
    mundo.adjudicatarios = [{"lote_numero": "2", "nombre": _ADELANTE, "nif": None}]

    resultado = _leer("2")

    assert resultado is not None and [lote.lote_numero for lote in resultado.lotes] == [None]
    # El acta no distingue lotes: el adjudicatario de cualquiera de ellos puede ser la ganadora.
    lote = resultado.lotes[0]
    assert lote.filas[lote.fila_ganadora].licitador_normalizado == _ADELANTE_N
    assert lote.ganadora_es_mayor_puntuacion is False


# --- validar_fila_acta --------------------------------------------------------


def test_validar_fila_acta_acepta_una_fila_del_acta(mundo: _Mundo) -> None:
    mundo.puntuaciones = [*_adelante("1"), *_asap("2")]

    assert validar_fila_acta(_LIC, FilaActaRef(lote_numero="1", licitador_normalizado=_ADELANTE_N))
    assert validar_fila_acta(_LIC, FilaActaRef(lote_numero="2", licitador_normalizado=_ASAP_N))


def test_validar_fila_acta_rechaza_lote_o_licitador_que_no_estan(mundo: _Mundo) -> None:
    mundo.puntuaciones = [*_adelante("1"), *_asap("2")]

    # Existe el licitador, pero en otro lote.
    assert not validar_fila_acta(
        _LIC, FilaActaRef(lote_numero="2", licitador_normalizado=_ADELANTE_N)
    )
    assert not validar_fila_acta(_LIC, FilaActaRef(lote_numero="1", licitador_normalizado="NADIE"))
    # ``None`` solo vale si el acta no distingue lotes.
    assert not validar_fila_acta(_LIC, FilaActaRef(licitador_normalizado=_ADELANTE_N))


def test_validar_fila_acta_sin_filas_leidas(mundo: _Mundo) -> None:
    mundo.puntuaciones = []

    assert not validar_fila_acta(_LIC, FilaActaRef(licitador_normalizado=_ADELANTE_N))


# --- La ficha y el PATCH (services/pursuits.py) --------------------------------

_ACTUAL: dict[str, Any] = {
    "id": _PURSUIT,
    "organization_id": _ORG,
    "licitacion_id": _LIC,
    "lote_numero": None,
    "version": 3,
    "status": "identified",
    "decision": "pending",
    "outcome": "pending",
    "next_action": None,
    "submitted_at": None,
    "closed_at": None,
}
_FILA = FilaActaRef(lote_numero="1", licitador_normalizado=_ADELANTE_N)
_USUARIO = 5


@dataclass
class _Patch:
    repo: MagicMock
    validar: MagicMock
    detalle: MagicMock


@pytest.fixture
def patch_env() -> Iterator[_Patch]:
    with (
        patch.object(pursuits_mod, "alcance_resuelto", alcance_fijo(_ORG)),
        patch.object(pursuits_mod, "_repo") as repo,
        patch.object(pursuits_mod, "_detalle", return_value="DETALLE") as detalle,
        patch.object(pursuits_mod, "validar_fila_acta", return_value=True) as validar,
    ):
        repo.get.return_value = dict(_ACTUAL)
        repo.update.return_value = {**_ACTUAL, "version": 4, "next_action": "Llamar"}
        yield _Patch(repo=repo, validar=validar, detalle=detalle)


def test_patch_solo_fila_acta_anota_el_ledger_y_no_actualiza(patch_env: _Patch) -> None:
    resultado = pursuits_mod.update_pursuit(
        _USUARIO, _PURSUIT, PursuitUpdate(fila_acta=_FILA), organization_id=_ORG
    )

    assert resultado == "DETALLE"
    patch_env.validar.assert_called_once_with(_LIC, _FILA)
    # Nada que actualizar: ni UPDATE ni versión nueva.
    patch_env.repo.update.assert_not_called()
    patch_env.repo.append_fila_acta_event.assert_called_once_with(
        organization_id=_ORG,
        pursuit_id=_PURSUIT,
        actor_user_id=_USUARIO,
        payload={"lote_numero": "1", "licitador_normalizado": _ADELANTE_N},
    )
    patch_env.detalle.assert_called_once_with(_ACTUAL, _ORG, _PURSUIT)


def test_patch_con_fila_que_no_esta_en_el_acta_es_422_y_no_escribe(patch_env: _Patch) -> None:
    patch_env.validar.return_value = False

    with pytest.raises(
        pursuits_mod.PursuitValidationError,
        match=re.escape("Esa fila no está en el acta leída de este expediente."),
    ):
        pursuits_mod.update_pursuit(
            _USUARIO,
            _PURSUIT,
            PursuitUpdate(fila_acta=_FILA, next_action="Llamar"),
            organization_id=_ORG,
        )

    patch_env.repo.update.assert_not_called()
    patch_env.repo.append_fila_acta_event.assert_not_called()


def test_patch_con_fila_y_otro_cambio_actualiza_sin_fila_en_las_columnas_y_anota(
    patch_env: _Patch,
) -> None:
    resultado = pursuits_mod.update_pursuit(
        _USUARIO,
        _PURSUIT,
        PursuitUpdate(fila_acta=_FILA, next_action="Llamar", expected_version=3),
        organization_id=_ORG,
    )

    assert resultado == "DETALLE"
    patch_env.repo.update.assert_called_once()
    kwargs = patch_env.repo.update.call_args.kwargs
    assert kwargs["changes"] == {"next_action": "Llamar"}
    assert "fila_acta" not in json.dumps(kwargs["event_payload"])
    patch_env.repo.append_fila_acta_event.assert_called_once()
    # Primero se actualiza: si la versión chocara, la fila no quedaría confirmada.
    nombres = [
        c[0] for c in patch_env.repo.mock_calls if c[0] in {"update", "append_fila_acta_event"}
    ]
    assert nombres == ["update", "append_fila_acta_event"]
    patch_env.detalle.assert_called_once_with(patch_env.repo.update.return_value, _ORG, _PURSUIT)


def test_patch_con_conflicto_de_version_no_confirma_la_fila(patch_env: _Patch) -> None:
    patch_env.repo.update.side_effect = PursuitConcurrencyError("la versión cambió")

    with pytest.raises(pursuits_mod.PursuitConflictError):
        pursuits_mod.update_pursuit(
            _USUARIO,
            _PURSUIT,
            PursuitUpdate(fila_acta=_FILA, next_action="Llamar", expected_version=2),
            organization_id=_ORG,
        )

    patch_env.repo.append_fila_acta_event.assert_not_called()


def test_patch_sin_fila_acta_ni_la_valida_ni_la_anota(patch_env: _Patch) -> None:
    pursuits_mod.update_pursuit(
        _USUARIO,
        _PURSUIT,
        PursuitUpdate(fila_acta=None, next_action="Llamar"),
        organization_id=_ORG,
    )

    patch_env.validar.assert_not_called()
    patch_env.repo.append_fila_acta_event.assert_not_called()
    patch_env.repo.update.assert_called_once()


def test_la_ficha_lleva_las_puntuaciones_en_la_adjudicacion() -> None:
    esperado = PuntuacionesActa(estado="pendiente", lotes=[])
    with (
        patch.object(pursuits_mod, "_adj_repo") as adj_repo,
        patch.object(pursuits_mod, "_lic_repo") as lic_repo,
        patch.object(pursuits_mod, "_resultado_sugerido", return_value=None),
        patch.object(
            pursuits_mod, "puntuaciones_de_pursuit", return_value=esperado
        ) as puntuaciones,
    ):
        adj_repo.list_for_licitacion.return_value = [{"nombre": _ASAP, "nif": None}]
        lic_repo.get_by_id.return_value = {"estado": "ADJ"}
        fila: Any = {**_ACTUAL, "lote_numero": "2"}
        adjudicacion = pursuits_mod._adjudicacion_detectada(fila, organization_id=_ORG)

    assert adjudicacion is not None
    assert adjudicacion.puntuaciones == esperado
    puntuaciones.assert_called_once_with(
        licitacion_id=_LIC, organization_id=_ORG, pursuit_id=_PURSUIT, lote_pursuit="2"
    )


def test_puntuaciones_de_la_ficha_son_fail_open() -> None:
    fila: Any = dict(_ACTUAL)
    with patch.object(
        pursuits_mod, "puntuaciones_de_pursuit", side_effect=RuntimeError("BD caída")
    ) as puntuaciones:
        assert pursuits_mod._puntuaciones(fila, _ORG) is None
        puntuaciones.assert_called_once()
        # Sin organización resuelta ni se intenta.
        puntuaciones.reset_mock()
        assert pursuits_mod._puntuaciones(fila, None) is None
        puntuaciones.assert_not_called()


# --- Importaciones ------------------------------------------------------------


def test_importar_services_pursuits_no_arrastra_rag_ni_llm() -> None:
    """La API no carga el cliente del modelo al arrancar por leer las puntuaciones."""
    codigo = (
        "import sys, services.pursuits;"
        "assert 'services.rag.fact_sheet' not in sys.modules;"
        "assert 'services.puntuaciones_acta_reglas' not in sys.modules;"
        "assert 'llm.client' not in sys.modules"
    )
    raiz = Path(__file__).resolve().parent.parent
    resultado = subprocess.run(  # intérprete propio y código constante
        [sys.executable, "-c", codigo],
        cwd=raiz,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stderr[-500:]
