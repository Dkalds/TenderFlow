"""El linaje de inclusión no se borra en una re-ingesta (S2.2).

Sin BD: se afirma sobre el SQL generado (``db.upsert._LIC_UPDATES``), que es
donde vive la decisión. El linaje no lo publica la fuente — lo decide el camino
de ingesta —, así que cualquier camino que construya la ``Licitacion`` con los
defaults ``None`` borraba con ``excluded.*`` lo que otro camino había escrito.
"""

from __future__ import annotations

import re
from dataclasses import fields

import pytest

from db.upsert import (
    _LIC_COALESCE_UPDATE_FIELDS,
    _LIC_INSERT_ONLY_FIELDS,
    _LIC_KEYS,
    _LIC_UPDATES,
    Licitacion,
)

#: Columnas que responden a «por qué está esta fila aquí y con qué versión se
#: decidió». Perderlas no degrada un dato accesorio: ``analysis_universe`` es
#: el denominador de las métricas.
COLUMNAS_DE_LINAJE = (
    "inclusion_reason",
    "filter_version",
    "analysis_universe",
    "classifier_model_version",
)


#: ``_LIC_UPDATES`` es una lista separada por ", " cuyos elementos pueden
#: contener comas propias (``COALESCE(a, b)``), así que el corte va por el
#: inicio de la siguiente asignación, no por cualquier coma.
_SEPARADOR_ASIGNACIONES = re.compile(r",\s(?=\w+=)")


def _asignaciones() -> list[str]:
    return _SEPARADOR_ASIGNACIONES.split(_LIC_UPDATES)


def _asignacion(columna: str) -> str:
    """El fragmento ``col=...`` que ``_LIC_UPDATES`` genera para esa columna."""
    for fragmento in _asignaciones():
        if fragmento.startswith(f"{columna}="):
            return fragmento
    raise AssertionError(f"{columna} no aparece en _LIC_UPDATES")


@pytest.mark.parametrize("columna", COLUMNAS_DE_LINAJE)
def test_las_columnas_de_linaje_existen_en_el_modelo(columna: str) -> None:
    """Si alguna se renombra, este test lo dice antes que el SQL en producción."""
    assert columna in {f.name for f in fields(Licitacion)}


@pytest.mark.parametrize("columna", COLUMNAS_DE_LINAJE)
def test_el_linaje_se_actualiza_con_coalesce_y_no_con_excluded_a_secas(columna: str) -> None:
    assert _asignacion(columna) == f"{columna}=COALESCE(excluded.{columna}, licitaciones.{columna})"


@pytest.mark.parametrize("columna", COLUMNAS_DE_LINAJE)
def test_el_linaje_esta_declarado_en_el_conjunto_de_coalesce(columna: str) -> None:
    assert columna in _LIC_COALESCE_UPDATE_FIELDS


def test_los_campos_originales_de_coalesce_siguen_protegidos() -> None:
    """Regresión: añadir linaje no puede desproteger `fecha_limite` y compañía."""
    for columna in ("fecha_limite", "procedimiento", "tramitacion", "peso_precio_pct"):
        assert _asignacion(columna) == (
            f"{columna}=COALESCE(excluded.{columna}, licitaciones.{columna})"
        )


def test_una_columna_normal_sigue_sobreescribiendose() -> None:
    """COALESCE es la excepción, no la regla: el estado debe pisarse."""
    assert _asignacion("estado") == "estado=excluded.estado"
    assert _asignacion("titulo") == "titulo=excluded.titulo"


def test_la_clave_de_conflicto_no_se_actualiza() -> None:
    assert "id_externo=" not in _LIC_UPDATES


def test_el_update_cubre_todas_las_columnas_menos_la_clave_y_las_de_solo_insert() -> None:
    columnas = {fragmento.split("=", 1)[0] for fragmento in _asignaciones()}
    esperadas = set(_LIC_KEYS) - {"id_externo"} - set(_LIC_INSERT_ONLY_FIELDS)
    assert columnas == esperadas


def test_el_mecanismo_de_solo_insert_existe_y_esta_vacio() -> None:
    """Preparado para ``primera_extraccion``, que aún no existe en el modelo.

    Cuando el agente que la añada la declare en ``db/models.py`` y en el
    dataclass ``Licitacion``, basta con listarla en ``_LIC_INSERT_ONLY_FIELDS``:
    ``_LIC_UPDATES`` ya la excluye del ``DO UPDATE SET`` sin más cambios. Este
    test falla si alguien la añade al dataclass sin declararla ahí.
    """
    assert frozenset() == _LIC_INSERT_ONLY_FIELDS
    assert "primera_extraccion" not in {f.name for f in fields(Licitacion)}, (
        "primera_extraccion ya existe en el modelo: añadila a "
        "_LIC_INSERT_ONLY_FIELDS y actualizá este test"
    )
