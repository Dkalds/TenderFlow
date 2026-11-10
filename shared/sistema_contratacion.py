"""Sistema de contratación de un expediente: marco, SDA, basado en uno de ellos o ninguno.

Un acuerdo marco (AM) o un sistema dinámico de adquisición (SDA) no es un
procedimiento: es un expediente que **admite empresas** y del que luego cuelgan
contratos basados en los que solo compiten las admitidas. ``procedimiento``
(``shared/procedimientos.py``) no lo recoge: medido el 2026-11-10, los basados
llegan con procedimiento abierto, restringido o sin él, y el código ``12``
(«basado en SDA») no aparece en ninguna fila.

``licitaciones.sistema_contratacion`` (v178) guarda uno de los valores de
:data:`SistemaContratacion`, **normalizado** y no el código crudo, al revés que
``procedimiento``: cada fuente lo publica con su propia lista (CODICE con un
código, eForms con dos campos) y lo que el producto pregunta —«¿es un marco?»,
«¿es un basado?»— tiene que poder responderse en SQL sin conocer la fuente.
``None`` significa que la fuente no lo dice; ``ninguno``, que dice que no
aplica.

De qué marco cuelga un basado va aparte, en ``licitaciones.marco_ref``, y solo
donde la fuente lo publica como dato.

Procedencia de :data:`_CODICE`: ``ContractingSystemTypeCode-2.08.gc``, la lista
que declara el ``listURI`` de ``cbc:ContractingSystemCode`` en el ATOM, leída
del servidor de la Plataforma el 2026-11-10.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final, Literal, get_args

SistemaContratacion = Literal["ninguno", "marco", "sda", "basado_marco", "basado_sda"]

SISTEMAS: Final[tuple[str, ...]] = get_args(SistemaContratacion)

#: Los que admiten empresas y de los que cuelgan contratos basados.
MARCOS: Final[frozenset[str]] = frozenset({"marco", "sda"})
#: Los que se adjudican dentro de un marco o un SDA.
BASADOS: Final[frozenset[str]] = frozenset({"basado_marco", "basado_sda"})

_CODICE: Final = MappingProxyType[str, SistemaContratacion](
    {
        "0": "ninguno",
        "1": "marco",
        "2": "sda",
        "3": "basado_marco",
        "4": "basado_sda",
    }
)


def desde_codice(codigo: str | None) -> SistemaContratacion | None:
    """``cbc:ContractingSystemCode`` de CODICE → sistema; ``None`` si falta o no se conoce.

    Un código que la lista no trae no se asimila al vecino: queda sin dato.
    """
    return _CODICE.get((codigo or "").strip())
