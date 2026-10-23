"""Contrato del bloque de CRUD de ``db/repositories/watchlist_rules.py``.

El ``UPDATE`` de una regla se arma con dos piezas que tienen que ir en el mismo
orden: el texto ``SET`` sale de ``_CAMPOS_SET`` y los valores de
``_valores_set``. Si alguien añade un criterio a una y no a la otra, el
``UPDATE`` escribe cada valor en la columna de al lado sin error ninguno —el
tipo de casi todas es ``text`` y Postgres lo acepta—, y la regla del usuario
pasa a filtrar por otra cosa.
"""

from __future__ import annotations

from typing import get_type_hints

from db.repositories.watchlist_rules import (
    _CAMPOS_SET,
    _SETS_REGLA,
    ValoresRegla,
    _valores_set,
)


def test_los_valores_del_set_van_en_el_orden_de_sus_columnas() -> None:
    # Cada valor es el nombre de su propia clave: si el orden se cruza, la
    # tupla deja de coincidir con la lista de columnas.
    valores = ValoresRegla(**{campo: campo for campo in _CAMPOS_SET})  # type: ignore[typeddict-item]  # valores centinela de tipo str a propósito
    assert _valores_set(valores) == _CAMPOS_SET


def test_el_set_cubre_exactamente_las_columnas_editables() -> None:
    assert set(_CAMPOS_SET) == set(get_type_hints(ValoresRegla))
    assert len(_CAMPOS_SET) == len(set(_CAMPOS_SET))
    assert _SETS_REGLA.count("%s") == len(_CAMPOS_SET)
