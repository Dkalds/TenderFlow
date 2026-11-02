"""Reglas puras de las puntuaciones del acta de la mesa (sin BD ni red).

Lo comparten el job que lee el acta (``services/puntuaciones_acta.py``) y la
lectura que arma la ficha de adjudicación: aquí viven el contrato del JSON que
devuelve el modelo, la validación de cada fila contra su cita, y las reglas que
dicen cuál es la fila ganadora, cuál es la nuestra, en qué se perdió y qué
motivo proponer. Spec: ``docs/superpowers/specs/2026-11-01-puntuaciones-acta-design.md``
§5 (``es_precio``) y §6.2-§6.4.

Sin cita verificable no hay dato (ADR-014): una fila cuya cita no está
literalmente en el texto del acta se tira, no se corrige. Esa validación es la
de la ficha del pliego (``_validated_evidence``); aquí no se copia.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from db.repositories.puntuaciones_acta import PuntuacionNueva
from services.normalization import fold_text, normalize_company
from services.rag.fact_sheet import _validated_evidence
from shared.dto.pursuits import PursuitOutcomeReasonCode
from shared.tender_facts import EvidenceRef

# --- El JSON del modelo --------------------------------------------------------


def _a_numero(valor: object) -> float | None:
    """«18,50» -> 18.5. Lo ilegible («n/d», «excluida», «—») es ``None``, no un error."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, int | float):
        numero = float(valor)
    elif isinstance(valor, str):
        try:
            numero = float(valor.strip().replace(",", "."))
        except ValueError:
            return None
    else:
        return None
    return numero if math.isfinite(numero) else None


def _a_texto(valor: object) -> object:
    """El modelo a veces devuelve el número del lote como entero."""
    if isinstance(valor, int) and not isinstance(valor, bool):
        return str(valor)
    return valor


Puntos = Annotated[float | None, BeforeValidator(_a_numero)]


class CriterioActa(BaseModel):
    """Lo que el acta puntúa en un criterio a un licitador."""

    model_config = ConfigDict(extra="ignore")

    nombre: str
    puntos: Puntos = None
    maximo: Puntos = None


class FilaActa(BaseModel):
    """Una fila de la tabla de puntuaciones, con la cita de la que sale."""

    model_config = ConfigDict(extra="ignore")

    licitador: str
    criterios: list[CriterioActa] = Field(default_factory=list)
    total: Puntos = None
    excluida: bool = False
    cita: str
    pagina: int
    documento_id: int


class LoteActa(BaseModel):
    """Las filas de un lote (``lote`` ``None``: el acta no distingue lotes)."""

    model_config = ConfigDict(extra="ignore")

    lote: Annotated[str | None, BeforeValidator(_a_texto)] = None
    filas: list[FilaActa] = Field(default_factory=list)


class RespuestaActa(BaseModel):
    """Lo que el modelo devuelve al leer las páginas del acta."""

    model_config = ConfigDict(extra="ignore")

    lotes: list[LoteActa] = Field(default_factory=list)


# --- Lote y precio -------------------------------------------------------------

#: «lote 1», «lote nº 1», «lote n.º 2», «1», sobre texto ya plegado (``fold_text``:
#: «º» llega como «o»). Solo un número entero, solo o tras «lote»: «lote 1 y 2» no
#: es el lote 1.
_LOTE_RE = re.compile(r"(?:lote\s*)?(?:(?:num(?:ero)?|n)\.?[º°o]?\.?\s*)?(\d+)")


def normalizar_lote(raw: str | None) -> str | None:
    """«Lote Nº 1» -> ``"1"``. Sin número que reconocer (o sin lote) -> ``None``."""
    if not raw:
        return None
    casado = _LOTE_RE.fullmatch(fold_text(raw).strip())
    return casado.group(1) if casado else None


#: Nombre de criterio que delata el precio cuando el pliego no lo dice (spec §5).
_PRECIO_EN_NOMBRE_RE = re.compile(r"oferta econ|precio|baja")


def es_precio_de(
    nombre: str,
    criterios_pliego: Sequence[Mapping[str, object]],
    lote_numero: str | None,
) -> bool | None:
    """¿Es de precio el criterio ``nombre`` del acta? ``None`` si no se sabe.

    Primero se casa con los criterios del pliego del mismo lote y, después, con
    los del expediente (``lote_numero`` ``None``): la descripción de uno
    contiene a la del otro, sin tildes ni mayúsculas, y manda su ``es_precio``.
    Si no casa, por el nombre (``oferta económica``, ``precio``, ``baja``). Si
    tampoco, ``None``: no se adivina que lo demás sea técnico.
    """
    buscado = fold_text(nombre).strip()
    candidatos = [c for c in criterios_pliego if c.get("lote_numero") == lote_numero]
    if lote_numero is not None:
        candidatos += [c for c in criterios_pliego if c.get("lote_numero") is None]
    for criterio in candidatos:
        descripcion = criterio.get("descripcion")
        es_precio = criterio.get("es_precio")
        if not isinstance(descripcion, str) or not isinstance(es_precio, bool):
            continue
        propuesto = fold_text(descripcion).strip()
        # Con alguno vacío «'' in x» sería cierto para todo.
        if buscado and propuesto and (buscado in propuesto or propuesto in buscado):
            return es_precio
    return True if _PRECIO_EN_NOMBRE_RE.search(buscado) else None


# --- Qué páginas se le dan al modelo -------------------------------------------

_MAX_PAGINAS = 12
_MAX_CHARS = 40_000
#: Un nombre de criterio más corto casa en cualquier página.
_MIN_NOMBRE_CRITERIO = 6
#: «(sobre 30 puntos)», la cabecera de las columnas de una tabla de puntuaciones.
_SOBRE_PUNTOS_RE = re.compile(r"sobre \d+(?:[.,]\d+)? puntos")


def _clave_de_pagina(pagina: Mapping[str, object]) -> tuple[int, int]:
    """Orden de documento: ``(documento_id, page_number)``."""
    documento, numero = pagina.get("documento_id"), pagina.get("page_number")
    return (
        documento if isinstance(documento, int) else 0,
        numero if isinstance(numero, int) else 0,
    )


def _texto_plegado(pagina: Mapping[str, object]) -> str:
    """Texto sin tildes ni mayúsculas y con los blancos colapsados.

    Colapsar los blancos importa: el PDF parte «(sobre 30 puntos)» en dos líneas
    dentro de la celda de la cabecera.
    """
    return " ".join(fold_text(str(pagina.get("texto") or "")).split())


def seleccionar_paginas(
    paginas: Sequence[Mapping[str, object]],
    nombres_criterio: Sequence[str],
) -> list[dict[str, object]]:
    """Las páginas del acta que parecen traer una tabla de puntuaciones.

    Puntúa cada página: +2 por «puntuaci», +1 por «total», +2 por una cabecera
    «sobre N puntos» y +1 por cada nombre de criterio (≥ 6 caracteres) que
    aparezca. Se queda con las de más de 1 punto, las mejores primero hasta
    ``_MAX_PAGINAS`` páginas y ``_MAX_CHARS`` caracteres, y las devuelve en
    orden de documento y página.
    """
    nombres = {
        plegado
        for plegado in (" ".join(fold_text(n).split()) for n in nombres_criterio)
        if len(plegado) >= _MIN_NOMBRE_CRITERIO
    }
    puntuadas: list[tuple[int, Mapping[str, object]]] = []
    for pagina in paginas:
        texto = _texto_plegado(pagina)
        puntuacion = (
            (2 if "puntuaci" in texto else 0)
            + (1 if "total" in texto else 0)
            + (2 if _SOBRE_PUNTOS_RE.search(texto) else 0)
            + sum(1 for n in nombres if n in texto)
        )
        if puntuacion > 1:
            puntuadas.append((puntuacion, pagina))

    elegidas: list[Mapping[str, object]] = []
    caracteres = 0
    for _, pagina in sorted(puntuadas, key=lambda p: (-p[0], _clave_de_pagina(p[1]))):
        if len(elegidas) == _MAX_PAGINAS:
            break
        largo = len(str(pagina.get("texto") or ""))
        if caracteres + largo > _MAX_CHARS:
            continue
        elegidas.append(pagina)
        caracteres += largo
    return [dict(p) for p in sorted(elegidas, key=_clave_de_pagina)]


# --- De la respuesta del modelo a las filas que se guardan ---------------------


def _filas_de(
    fila: FilaActa,
    lote_numero: str | None,
    indice: dict[tuple[int, int], dict[str, object]],
    criterios_pliego: Sequence[Mapping[str, object]],
) -> list[PuntuacionNueva]:
    """Las filas que salen de una fila del acta; ninguna si su cita no se sostiene."""
    licitador = " ".join(fila.licitador.split())
    normalizado = normalize_company(licitador)
    if not normalizado:
        return []
    try:
        ref = EvidenceRef(
            documento_id=fila.documento_id, page_number=fila.pagina, quote=fila.cita[:600]
        )
    except ValidationError:
        return []  # documento o página no positivos, o cita vacía
    cita = _validated_evidence(ref, indice)
    if cita is None:
        return []

    def nueva(
        criterio: str | None, puntos: float | None, maximo: float | None, es_precio: bool | None
    ) -> PuntuacionNueva:
        return {
            "lote_numero": lote_numero,
            "licitador_nombre": licitador,
            "licitador_normalizado": normalizado,
            "criterio": criterio,
            "puntos": puntos,
            "puntos_max": maximo,
            "es_precio": es_precio,
            "excluida": fila.excluida,
            "documento_id": cita.documento_id,
            "pagina": cita.page_number,
            "cita": cita.quote,
        }

    por_criterio = [
        nueva(nombre, c.puntos, c.maximo, es_precio_de(nombre, criterios_pliego, lote_numero))
        for c in fila.criterios
        if (nombre := " ".join(c.nombre.split()))
    ]
    return [*por_criterio, nueva(None, fila.total, None, None)]


def filas_validadas(
    respuesta: RespuestaActa,
    paginas: Sequence[Mapping[str, object]],
    criterios_pliego: Sequence[Mapping[str, object]],
) -> list[PuntuacionNueva]:
    """Las filas de la respuesta cuya cita está literalmente en el acta.

    Por licitador sale una fila por criterio y una de total (``criterio`` y
    ``puntos_max`` ``None``). Se tira el licitador entero si su cita no está en
    la página citada ni en otra del mismo documento (``_validated_evidence``,
    que corrige la página si hace falta) o si su nombre no se puede normalizar.

    Sin duplicados por ``(lote, licitador normalizado, criterio)``: la
    escritura es una transacción contra un índice único y un solo duplicado la
    deshace entera. Se queda la primera aparición.
    """
    indice = {_clave_de_pagina(p): dict(p) for p in paginas}
    filas: list[PuntuacionNueva] = []
    vistas: set[tuple[str, str, str]] = set()
    for lote in respuesta.lotes:
        lote_numero = normalizar_lote(lote.lote)
        for fila in lote.filas:
            for nueva in _filas_de(fila, lote_numero, indice, criterios_pliego):
                clave = (lote_numero or "", nueva["licitador_normalizado"], nueva["criterio"] or "")
                if clave not in vistas:
                    vistas.add(clave)
                    filas.append(nueva)
    return filas


# --- Fila ganadora, fila propia, diferencia y motivo ---------------------------


@dataclass(frozen=True)
class CriterioCalculo:
    """Un criterio de una fila, tal como se lee de la BD."""

    nombre: str
    puntos: float | None
    maximo: float | None
    es_precio: bool | None
    documento_id: int
    pagina: int
    cita: str


@dataclass(frozen=True)
class FilaCalculo:
    """Un licitador de un lote con sus criterios y su total."""

    licitador: str
    licitador_normalizado: str
    total: float | None
    excluida: bool
    criterios: tuple[CriterioCalculo, ...]


@dataclass(frozen=True)
class DiferenciaCalculo:
    """Puntos de la propia menos puntos de la ganadora; ``criterio`` ``None`` es el total."""

    criterio: str | None
    diferencia: float
    maximo: float | None
    es_precio: bool | None


def fila_ganadora(
    filas: Sequence[FilaCalculo], adjudicatarios_normalizados: set[str]
) -> tuple[int | None, bool]:
    """``(índice, es_mayor_puntuacion)`` de la fila ganadora del lote (spec §6.2).

    La que casa con el adjudicatario publicado. Si ninguna casa, la de mayor
    total entre las no excluidas, y la interfaz la rotula «mayor puntuación» y
    no «ganadora» (``True``). Sin totales que comparar, ``(None, False)``.
    """
    for i, fila in enumerate(filas):
        if fila.licitador_normalizado in adjudicatarios_normalizados:
            return i, False
    mejor: tuple[int, float] | None = None
    for i, fila in enumerate(filas):
        if fila.excluida or fila.total is None:
            continue
        if mejor is None or fila.total > mejor[1]:
            mejor = (i, fila.total)
    return (mejor[0], True) if mejor else (None, False)


def fila_propia(filas: Sequence[FilaCalculo], nombres_org_normalizados: set[str]) -> int | None:
    """La fila que es de la organización, o ``None`` (spec §6.3).

    Casamiento exacto tras normalizar. Con dos filas candidatas o con ninguna no
    se propone nada: proponer la de otra empresa es peor que no proponer, porque
    la persona siempre puede marcarla. Una UTE que la contiene no casa.
    """
    casan = [i for i, f in enumerate(filas) if f.licitador_normalizado in nombres_org_normalizados]
    return casan[0] if len(casan) == 1 else None


def _redondeado(valor: float) -> float:
    """Sin el ruido de la coma flotante (``43,13 - 50,91`` no es ``-7,779999…``)."""
    return round(valor, 4)


def diferencia(propia: FilaCalculo, ganadora: FilaCalculo) -> list[DiferenciaCalculo]:
    """Por criterio y en total, ``puntos_propios - puntos_ganadora`` (spec §6.4).

    Solo los criterios que están, con puntos, en las dos filas (se casan por el
    nombre sin tildes ni mayúsculas); el total, si las dos lo tienen.
    """
    de_la_ganadora = {fold_text(c.nombre): c for c in ganadora.criterios}
    resultado: list[DiferenciaCalculo] = []
    for propio in propia.criterios:
        ajeno = de_la_ganadora.get(fold_text(propio.nombre))
        if ajeno is None or propio.puntos is None or ajeno.puntos is None:
            continue
        resultado.append(
            DiferenciaCalculo(
                criterio=propio.nombre,
                diferencia=_redondeado(propio.puntos - ajeno.puntos),
                maximo=propio.maximo if propio.maximo is not None else ajeno.maximo,
                es_precio=propio.es_precio if propio.es_precio is not None else ajeno.es_precio,
            )
        )
    if propia.total is not None and ganadora.total is not None:
        resultado.append(
            DiferenciaCalculo(
                criterio=None,
                diferencia=_redondeado(propia.total - ganadora.total),
                maximo=None,
                es_precio=None,
            )
        )
    return resultado


def motivo_sugerido(
    propia: FilaCalculo, ganadora: FilaCalculo, *, propia_es_ganadora: bool
) -> PursuitOutcomeReasonCode | None:
    """El motivo de pérdida que proponen los puntos, o ``None`` (spec §6.4).

    Se suman las pérdidas (solo las diferencias negativas) en criterios de
    precio y en el resto. Si la de precio es mayor, ``precio``; si la del resto
    es mayor o igual y no es cero, ``tecnica``. Con la propia ganadora o
    excluida, sin pérdidas o sin ningún ``es_precio`` conocido, ``None``.
    """
    if propia_es_ganadora or propia.excluida:
        return None
    criterios = [d for d in diferencia(propia, ganadora) if d.criterio is not None]
    if all(d.es_precio is None for d in criterios):
        return None
    perdida_precio = _redondeado(
        sum(-d.diferencia for d in criterios if d.es_precio is True and d.diferencia < 0)
    )
    perdida_resto = _redondeado(
        sum(-d.diferencia for d in criterios if d.es_precio is not True and d.diferencia < 0)
    )
    if perdida_precio > perdida_resto:
        return "precio"
    if perdida_resto > 0:
        return "tecnica"
    return None
