"""``FiltrosLicitacion`` y las dependencias del listado no pueden separarse.

Los filtros del listado viajaban como parámetros sueltos por cinco firmas que
había que mantener sincronizadas a mano. Ahora el repositorio recibe el objeto
entero, pero la query HTTP sigue declarándose parámetro a parámetro en las dos
dependencias de ``api/routes/licitaciones/listado.py`` (sus descripciones son
contrato OpenAPI). Este test es lo que impide que un campo nuevo del modelo se
quede sin su ``Query`` en una de las dos rutas —el filtro existiría en el
repositorio y ningún cliente podría pedirlo—.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from api.routes.licitaciones.listado import _filtros_cursor, _filtros_offset
from shared.dto import FiltrosLicitacion

#: Campos cuyo parámetro de query conserva otro nombre público.
_QUERY_DE_CAMPO = {"etiqueta_id": "etiqueta"}
#: Campos que no llegan de la query tal cual: la ruta los resuelve
#: (``organization_id`` → la organización validada de la etiqueta).
_RESUELTOS = {"etiqueta_organization_id"}
#: Lo que el cursor no ofrece, y nunca ofreció: la tecnología predicha.
_SOLO_OFFSET = {"tecnologia_predicha", "min_proba_tech"}
#: Parámetros de las dependencias que no son un campo del modelo.
_NO_CAMPOS = {"ctx", "organization_id"}


def _parametros(dependencia: Callable[..., Any]) -> set[str]:
    return set(inspect.signature(dependencia).parameters) - _NO_CAMPOS


def _campos_de_query() -> set[str]:
    return {
        _QUERY_DE_CAMPO.get(campo, campo)
        for campo in FiltrosLicitacion.model_fields
        if campo not in _RESUELTOS
    }


def test_el_listado_por_offset_declara_todos_los_filtros() -> None:
    assert _parametros(_filtros_offset) == _campos_de_query()


def test_el_cursor_declara_los_mismos_salvo_la_tecnologia_predicha() -> None:
    assert _parametros(_filtros_cursor) == _campos_de_query() - _SOLO_OFFSET


def test_un_filtro_mal_escrito_falla_en_vez_de_ignorarse() -> None:
    with pytest.raises(ValidationError):
        FiltrosLicitacion(ccca="Madrid")  # type: ignore[call-arg]  # es justo lo que se prueba


def test_sin_filtros_es_el_listado_entero() -> None:
    from db.repositories.licitaciones import LicitacionRepository

    assert len(LicitacionRepository._base_filters()) == len(
        LicitacionRepository._base_filters(FiltrosLicitacion())
    )
