"""Identidad de las licitaciones de la familia PLACSP: el expediente acotado por el órgano.

El defecto que resuelve (RFC ``2026-10-24-rfc-identidad-placsp-organo-expediente``)
-------------------------------------------------------------------------------------
El ``id_externo`` de las filas ``placsp``/``bulk_*`` es hoy el ``ContractFolderID``
a secas, y ese número lo teclea cada órgano: «2026/LIC/0049» lo usan a la vez una
mutua y un hospital. Como es la clave primaria de ``licitaciones``, la segunda
licitación **sustituye** a la primera por ``ON CONFLICT(id_externo)``. La clave
que lo arregla acota el expediente por el identificador del órgano en la
Plataforma::

    placsp:<órgano>:<ContractFolderID>

Este módulo es la **única** definición de esa clave: cómo se construye, cómo se
descompone y qué parte de ella es el expediente natural con el que el dedupe
casa con TED, PSCP y agregadas. Vive en ``shared/`` porque lo necesitan dos capas
que no pueden importarse entre sí (``services/dedupe.py`` y su gemelo SQL en
``db/repositories/dedupe.py``), además del parser de ``scraper/`` y la API.

Reglas de la clave
------------------
- **El prefijo es de la familia, no del carril.** El feed vivo (``fuente =
  placsp``) y el ZIP mensual (``fuente = bulk_YYYYMM``) escriben la misma fila,
  y los dos llevan ``placsp:``.
- **El ``:`` delimita.** El órgano se escribe con ``%`` → ``%25`` y ``:`` →
  ``%3A`` (:func:`codificar_organo`), así que nunca contiene ``:``. El
  expediente va tal cual —puede llevar ``:`` («RSC: 2019-00078»)— y por eso
  «todo lo que sigue al segundo ``:``» es siempre el expediente.
- **Contratos menores no cambia**: ``placsp_menores:<órgano>:<expediente>`` ya
  nació acotado y su expediente natural es ``<órgano>:<expediente>`` a propósito
  (no debe casar con nada; ver el docstring de
  ``scraper/connectors/placsp_menores.py``). Por eso **no** está en
  :data:`PREFIJOS_ACOTADOS_POR_ORGANO`.

Fase A (esta implementación)
----------------------------
Los escritores de PLACSP **siguen escribiendo la clave vieja**: cambiar la
clave de las filas nuevas sin re-escribir las existentes partiría cada
expediente republicado en dos filas. Lo que entra en la fase A es que todo el
código **lee** las dos formas (:func:`expediente_natural`,
:func:`expediente_natural_sql`, la resolución de ids viejos por
``licitaciones_id_anterior``), que el parser guarda el órgano en
``licitaciones.organo_ref_fuente``, y que el upsert cuenta la colisión en vez
de pisar en silencio. La re-key de las filas ya escritas es la fase B del RFC.
"""

from __future__ import annotations

import re
from typing import Final, NamedTuple

__all__ = [
    "PREFIJOS_ACOTADOS_POR_ORGANO",
    "ClavePlacsp",
    "clave_placsp",
    "codificar_organo",
    "decodificar_organo",
    "descomponer_clave_placsp",
    "es_fuente_placsp",
    "expediente_natural",
    "expediente_natural_sql",
]

#: Prefijos cuyo ``id_externo`` es ``<prefijo>:<órgano>:<expediente>`` y cuyo
#: expediente natural es lo que sigue al segundo ``:``. El orden no importa;
#: la tupla se vuelca en la alternancia de la regex de abajo.
PREFIJOS_ACOTADOS_POR_ORGANO: Final[tuple[str, ...]] = (
    "placsp",
    "placsp_agregadas",
    "placsp_watched_company_awards",
)

#: ``^(placsp|placsp_agregadas|...):[^:]*:`` — el prefijo y el órgano, que no
#: puede llevar ``:`` porque :func:`codificar_organo` lo escapa.
_PREFIJO_Y_ORGANO: Final[str] = (
    "^(" + "|".join(re.escape(p) for p in PREFIJOS_ACOTADOS_POR_ORGANO) + "):[^:]*:"
)
_RE_PREFIJO_Y_ORGANO: Final[re.Pattern[str]] = re.compile(_PREFIJO_Y_ORGANO)

#: PSCP acota su código con el UUID de la ficha: ``pscp:{uuid}:{codi}``. El
#: expediente es el código, no la ficha. Misma expresión en Python y en SQL.
_UUID_FICHA_PSCP_RE: Final[str] = "^[0-9a-f-]{36}:"
_RE_UUID_FICHA_PSCP: Final[re.Pattern[str]] = re.compile(_UUID_FICHA_PSCP_RE)


def es_fuente_placsp(fuente: str | None) -> bool:
    """``True`` para los dos carriles del feed principal: ``placsp`` y ``bulk_YYYYMM``."""
    valor = fuente or ""
    return valor == "placsp" or valor.startswith("bulk_")


#: ``%`` → ``%25`` y ``:`` → ``%3A``, en una sola pasada: un ``%3A`` literal en
#: la entrada queda ``%253A`` y no se confunde con un ``:`` escapado al
#: decodificar. No es el escapado de ``LIKE`` (``db.sql_fragments.escape_like``):
#: aquí se protege el delimitador de la clave, no un comodín de SQL.
_ESCAPE_ORGANO: Final[dict[int, str]] = str.maketrans({"%": "%25", ":": "%3A"})


def codificar_organo(organo: str) -> str:
    """El identificador del órgano tal como entra en la clave: sin ``:`` posible.

    Ningún valor medido lleva ``%`` ni ``:`` (``ID_PLATAFORMA`` son 14 o 15
    dígitos), pero ``ID_OC_PLAT`` de agregadas es texto libre y la regla tiene
    que valer para él.
    """
    return organo.translate(_ESCAPE_ORGANO)


def decodificar_organo(organo_codificado: str) -> str:
    """Inversa de :func:`codificar_organo`."""
    return organo_codificado.replace("%3A", ":").replace("%3a", ":").replace("%25", "%")


def clave_placsp(prefijo: str, organo: str, expediente: str) -> str:
    """``<prefijo>:<órgano codificado>:<expediente>``.

    Args:
        prefijo: uno de :data:`PREFIJOS_ACOTADOS_POR_ORGANO`.
        organo: identificador del órgano en la fuente (``ID_PLATAFORMA``,
            ``ID_OC_PLAT`` o su respaldo), sin codificar.
        expediente: ``ContractFolderID`` tal cual, con los ``:`` que tenga.

    Raises:
        ValueError: si el prefijo no es de la familia, o si órgano o
            expediente están vacíos — una clave sin órgano es justo la que
            pisa, y sin expediente no identifica nada.
    """
    if prefijo not in PREFIJOS_ACOTADOS_POR_ORGANO:
        raise ValueError(f"prefijo fuera de la familia PLACSP: {prefijo!r}")
    if not organo or not expediente:
        raise ValueError("la clave PLACSP exige órgano y expediente")
    return f"{prefijo}:{codificar_organo(organo)}:{expediente}"


class ClavePlacsp(NamedTuple):
    """Las tres partes de una clave acotada por órgano."""

    prefijo: str
    organo: str
    expediente: str


def descomponer_clave_placsp(id_externo: str) -> ClavePlacsp | None:
    """Las partes de ``<prefijo>:<órgano>:<expediente>``, o ``None`` si no tiene esa forma.

    ``None`` cubre la clave vieja de PLACSP (sin ``:`` de prefijo), el resto de
    fuentes y ``placsp_menores`` (fuera de la familia a propósito). El órgano se
    devuelve **decodificado**.
    """
    m = _RE_PREFIJO_Y_ORGANO.match(id_externo)
    if m is None:
        return None
    prefijo = m.group(1)
    organo_codificado = id_externo[len(prefijo) + 1 : m.end() - 1]
    return ClavePlacsp(prefijo, decodificar_organo(organo_codificado), id_externo[m.end() :])


def expediente_natural(id_externo: str) -> str:
    """Expediente nacional: lo que casa con el expediente de otra fuente (ADR-009).

    ======================================================  =======================
    ``id_externo``                                          expediente natural
    ======================================================  =======================
    ``placsp:<órgano>:<exp>`` (y los otros dos prefijos)    ``<exp>`` (tras el 2.º ``:``)
    ``placsp_menores:<órgano>:<exp>``                       ``<órgano>:<exp>`` (sin cambios)
    ``pscp:<uuid>:<codi>``                                  ``<codi>`` (sin cambios)
    sin ``:`` (PLACSP con la clave vieja)                   el id entero (sin cambios)
    ``<prefijo>:<resto>`` (el resto de fuentes)             ``<resto>`` (sin cambios)
    ======================================================  =======================

    Efecto lateral bueno de la clave nueva: un expediente que lleve ``:``
    («RSC: 2019-00078») ya no se corta por su propio ``:``, porque el prefijo y
    el órgano se quitan de una vez. Con la clave vieja sigue cortándose mal,
    como hasta ahora; la fase B lo arregla al re-escribirla.

    Gemelo SQL: :func:`expediente_natural_sql`. Los dos tienen que dar lo mismo
    o el prefiltro del repositorio escondería pares que el matching de Python
    sí considera; ``tests/test_identidad_placsp.py`` lo fija.
    """
    acotada = _RE_PREFIJO_Y_ORGANO.match(id_externo)
    if acotada is not None:
        return id_externo[acotada.end() :]
    _, sep, rest = id_externo.partition(":")
    return _RE_UUID_FICHA_PSCP.sub("", rest, count=1) if sep else id_externo


def expediente_natural_sql(columna: str) -> str:
    """La expresión SQL (Postgres) equivalente a :func:`expediente_natural`.

    Args:
        columna: la expresión de la columna, con alias si lo lleva
            (``"l.id_externo"``). Se interpola tal cual: solo nombres de
            columna escritos en el código, nunca entrada del usuario.

    Primero quita el prefijo y el órgano de una clave acotada; lo que queda
    de una clave así ya no tiene prefijo que cortar, salvo que el propio
    expediente lleve ``:``, y para no cortarlo el ``CASE`` solo aplica el corte
    por el primer ``:`` cuando la clave **no** era acotada.
    """
    sin_organo = f"regexp_replace({columna}, '{_PREFIJO_Y_ORGANO}', '')"
    sin_prefijo = f"substr({columna}, position(':' in {columna}) + 1)"
    sin_ficha_pscp = f"regexp_replace({sin_prefijo}, '{_UUID_FICHA_PSCP_RE}', '')"
    return (
        f"CASE WHEN {columna} ~ '{_PREFIJO_Y_ORGANO}' THEN {sin_organo} "
        f"WHEN position(':' in {columna}) > 0 THEN {sin_ficha_pscp} "
        f"ELSE {columna} END"
    )
