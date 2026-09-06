"""F1.2 — la paleta ⌘K busca lo que el usuario tiene en la cabeza.

Hoy la paleta navega entre espacios, salta a un expediente por id y manda
texto libre a Detalle. Eso convierte «Indra» en una búsqueda de expedientes
cuyo título contiene «Indra», que casi nunca es lo que alguien quiere al
escribir el nombre de una empresa: quiere el perfil de esa empresa.

Cuatro tipos, un único endpoint
-------------------------------
Expedientes, empresas, órganos y oportunidades de la organización. Uno solo
porque la paleta abre con una tecla y no puede encadenar cuatro peticiones ni
decidir el tipo por adelantado: el usuario escribe y la respuesta dice qué
encontró de cada clase.

El NIF es un caso aparte
------------------------
Un NIF exacto **no es una búsqueda**, es una identificación: quien lo teclea
sabe exactamente a quién busca. La respuesta lo marca (``exacto``) para que la
paleta abra el perfil directamente en vez de enseñar una lista de un elemento
que hay que pulsar.

Ámbito
------
Expedientes, empresas y órganos son públicos dentro del producto. Las
oportunidades son de la organización, y por eso el servicio exige
``organization_id`` para buscarlas: sin él no las busca, no las busca «todas».
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from observability.logging import get_logger

log = get_logger(__name__)

__all__ = ["TIPOS_RESULTADO", "ResultadoBusqueda", "TipoResultado", "buscar_global"]

TipoResultado = Literal["expediente", "empresa", "organo", "oportunidad"]

TIPOS_RESULTADO: tuple[str, ...] = ("expediente", "empresa", "organo", "oportunidad")

#: NIF/CIF español: letra o dígito, siete dígitos, letra o dígito de control.
#: Se usa para **detectar la intención**, no para validar: un NIF con letra de
#: control equivocada sigue siendo alguien tecleando un NIF, y devolverle una
#: búsqueda por texto sería peor que buscarlo y no encontrarlo.
_NIF_RE = re.compile(r"^[A-Za-z0-9]\d{7}[A-Za-z0-9]$")

#: Mínimo para buscar. Con menos de tres caracteres cualquier término casa con
#: media tabla y la paleta se convierte en una lista aleatoria.
MIN_LONGITUD = 3


class ResultadoBusqueda(BaseModel):
    """Un resultado, con lo justo para pintar una fila de la paleta."""

    model_config = ConfigDict(extra="forbid")

    tipo: TipoResultado
    #: Identificador con el que navegar. Su forma depende del tipo: el
    #: `id_externo` del expediente, el id numérico de la empresa como texto,
    #: el nombre normalizado del órgano (hasta que exista el maestro, C1.2).
    id: str
    titulo: str
    #: Segunda línea: el órgano de un expediente, el NIF de una empresa. Puede
    #: faltar, y entonces la fila va a una línea en vez de con un hueco.
    subtitulo: str | None = None
    #: `True` sólo para la identificación por NIF exacto: la paleta abre el
    #: perfil sin pasar por la lista.
    exacto: bool = False


class BusquedaGlobal(BaseModel):
    """La respuesta de la paleta."""

    model_config = ConfigDict(extra="forbid")

    q: str
    resultados: list[ResultadoBusqueda] = Field(default_factory=list)
    #: Conteo por tipo, para que la paleta pueda agrupar sin recontar y para
    #: que «no hay empresas que se llamen así» sea distinguible de «no busqué
    #: empresas».
    por_tipo: dict[str, int] = Field(default_factory=dict)
    #: Qué se buscó. Sin organización no se buscan oportunidades, y decirlo
    #: evita que el usuario crea que su equipo no tiene ninguna.
    tipos_buscados: list[str] = Field(default_factory=list)
    #: Motivo de no haber buscado, si no se buscó.
    sin_busqueda: str | None = None


def es_nif(termino: str) -> bool:
    """``True`` si el término tiene forma de NIF/CIF."""
    return bool(_NIF_RE.match(termino.strip()))


def _fila(
    tipo: TipoResultado, id_: Any, titulo: Any, subtitulo: Any = None, *, exacto: bool = False
) -> ResultadoBusqueda:
    return ResultadoBusqueda(
        tipo=tipo,
        id=str(id_),
        titulo=str(titulo or id_),
        subtitulo=str(subtitulo) if subtitulo else None,
        exacto=exacto,
    )


def buscar_global(
    q: str,
    *,
    organization_id: int | None = None,
    limite_por_tipo: int = 5,
) -> BusquedaGlobal:
    """Busca en los cuatro tipos y devuelve lo que encuentre de cada uno.

    Cada tipo se busca en su propio ``try``: una tabla caída no puede dejar la
    paleta sin resultados de las otras tres. Es la misma decisión que toma el
    Radar con sus señales, y por el mismo motivo — la alternativa es que un
    fallo parcial se vea como «no hay nada».
    """
    termino = q.strip()
    if len(termino) < MIN_LONGITUD:
        return BusquedaGlobal(
            q=termino,
            sin_busqueda=f"Escribe al menos {MIN_LONGITUD} caracteres.",
        )

    from db.repositories.busqueda import BusquedaRepository

    repo = BusquedaRepository()
    resultados: list[ResultadoBusqueda] = []
    buscados: list[str] = []

    # 1. NIF exacto: identificación, no búsqueda. Va primero y, si acierta, la
    #    empresa encontrada encabeza la lista.
    if es_nif(termino):
        try:
            empresa = repo.empresa_por_nif(termino.upper())
            if empresa is not None:
                resultados.append(
                    _fila(
                        "empresa",
                        empresa["id"],
                        empresa.get("nombre_canonico"),
                        empresa.get("nif"),
                        exacto=True,
                    )
                )
        except Exception:
            log.warning("busqueda_global_nif_error", exc_info=True)

    publicos: tuple[tuple[TipoResultado, Callable[[], list[dict[str, Any]]]], ...] = (
        ("expediente", lambda: repo.expedientes(termino, limite_por_tipo)),
        ("empresa", lambda: repo.empresas(termino, limite_por_tipo)),
        ("organo", lambda: repo.organos(termino, limite_por_tipo)),
    )
    for tipo, cargar in publicos:
        buscados.append(tipo)
        try:
            for fila in cargar():
                resultados.append(
                    _fila(tipo, fila["id"], fila.get("titulo"), fila.get("subtitulo"))
                )
        except Exception:
            log.warning("busqueda_global_error", tipo=tipo, exc_info=True)

    # 4. Oportunidades: sólo con organización. Sin ella **no se buscan**, que
    #    no es lo mismo que buscarlas y no encontrar ninguna — la respuesta lo
    #    declara en `tipos_buscados`.
    if organization_id is not None:
        buscados.append("oportunidad")
        try:
            for fila in repo.oportunidades(termino, organization_id, limite_por_tipo):
                resultados.append(
                    _fila("oportunidad", fila["id"], fila.get("titulo"), fila.get("subtitulo"))
                )
        except Exception:
            log.warning("busqueda_global_error", tipo="oportunidad", exc_info=True)

    por_tipo: dict[str, int] = {}
    for resultado in resultados:
        por_tipo[resultado.tipo] = por_tipo.get(resultado.tipo, 0) + 1

    return BusquedaGlobal(
        q=termino,
        resultados=resultados,
        por_tipo=por_tipo,
        tipos_buscados=buscados,
    )
