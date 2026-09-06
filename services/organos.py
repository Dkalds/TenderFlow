"""Resolución de identidad de órganos de contratación (C1.2, ADR-032, D22).

La persistencia está en ``db/repositories/organos.py`` (ADR-022); aquí vive lo
que es criterio: cuándo dos grafías son el mismo órgano, cuándo la decisión la
tiene que tomar una persona, y cuál de las grafías es la canónica.

**La regla, en una línea:** DIR3 manda; si no lo hay, nombre normalizado; si el
nombre normalizado casi coincide, lo decide un humano.

Por qué «casi coincide» no se decide solo
------------------------------------------
Dos organismos distintos pueden tener nombres casi idénticos. «Servicio de
Salud» existe en varias comunidades; «Ayuntamiento de Villanueva» hay siete.
Fusionarlos junta dos historiales de contratación que no son el mismo, y el
error no se ve mirando la ficha: se ve meses después, cuando alguien nota que un
ayuntamiento pequeño licita cien millones al año.

El error contrario —crear dos órganos para el mismo— se ve enseguida y se
arregla con un alias. Por eso la asimetría: fusionar exige evidencia, separar no.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from db.repositories import organos as repo
from observability.logging import get_logger
from services.dedupe import normalize_organo

log = get_logger(__name__)

#: Umbral de similitud a partir del cual dos nombres normalizados se consideran
#: **candidatos** a ser el mismo órgano y van a la cola de revisión.
#:
#: 0,88 sale de la asimetría de arriba: por debajo hay demasiados falsos
#: positivos («Ayuntamiento de Alcalá de Henares» y «Ayuntamiento de Alcalá de
#: Guadaíra» comparten casi todo), y por encima de 0,95 la cola se queda vacía y
#: las variantes de verdad —una coma, un «Excmo.»— se pierden como órganos
#: nuevos. **No es un umbral de fusión: es un umbral de sospecha.**
UMBRAL_SOSPECHA = 0.88

#: Formas de tratamiento y ruido que no distinguen a un órgano de otro.
_RUIDO = re.compile(
    r"\b(excmo|excma|ilmo|ilma|sr|sra|d|dna|m\.i\.|junta de gobierno)\b\.?",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Resolucion:
    """Resultado de resolver una grafía contra el maestro."""

    #: Id del órgano cuando la resolución es firme. `None` si quedó en revisión.
    organo_id: int | None
    #: `dir3` | `nombre` | `alias` | `nuevo` | `revision`.
    via: str
    #: Solo cuando `via == "revision"`: el candidato que se propuso.
    candidato_id: int | None = None
    score: float = 0.0


def normalizar(nombre: str | None) -> str | None:
    """Nombre plegado para comparar. Extiende `services.dedupe.normalize_organo`.

    `normalize_organo` retira formas societarias, que es lo correcto para
    empresas. Un órgano no tiene forma societaria pero sí tratamiento
    («Excmo. Ayuntamiento de…»), y esa palabra no distingue a un órgano de otro.
    """
    base = normalize_organo(nombre)
    if not base:
        return None
    limpio = _RUIDO.sub(" ", base)
    limpio = unicodedata.normalize("NFKD", limpio)
    limpio = "".join(c for c in limpio if not unicodedata.combining(c))
    limpio = re.sub(r"[^a-z0-9 ]+", " ", limpio.lower())
    return " ".join(limpio.split()) or None


def similitud(a: str, b: str) -> float:
    """Similitud de dos nombres normalizados, en [0, 1].

    Jaccard sobre palabras y no distancia de edición: lo que distingue a dos
    órganos suele ser **una palabra entera** (el topónimo), no unos caracteres.
    Una distancia de edición da 0,93 a «Alcalá de Henares» y «Alcalá de
    Guadaíra», que son dos ayuntamientos distintos; Jaccard da 0,60.
    """
    pa = set(a.split())
    pb = set(b.split())
    if not pa or not pb:
        return 0.0
    return len(pa & pb) / len(pa | pb)


def resolver(
    nombre: str | None,
    *,
    dir3: str | None = None,
    ccaa: str | None = None,
    crear_si_falta: bool = True,
) -> Resolucion | None:
    """Resuelve una grafía a un órgano del maestro.

    Devuelve ``None`` si el nombre no da para nada (vacío tras normalizar).

    El orden es el de ADR-032 §C y no es negociable: DIR3 primero porque es el
    único identificador con garantía; el nombre después; y la sospecha, a la
    cola.
    """
    normalizado = normalizar(nombre)
    if not normalizado:
        return None

    # 1. DIR3: identidad sin ambigüedad.
    if dir3:
        existente = repo.get_by_dir3(dir3)
        if existente:
            organo_id = int(existente["organo_id"])
            # La grafía nueva se registra como alias aunque el órgano ya
            # existiera: es lo que hace que la próxima vez resuelva por nombre
            # sin volver a depender de que la fuente publique el DIR3.
            if normalizado != existente.get("nombre_normalizado"):
                repo.anadir_alias(
                    organo_id,
                    alias_normalizado=normalizado,
                    alias_original=nombre,
                    dir3_variante=dir3,
                    fuente="dir3",
                )
            return Resolucion(organo_id, "dir3")

    # 2. Nombre normalizado exacto (incluye alias ya registrados).
    existente = repo.get_by_nombre_normalizado(normalizado)
    if existente:
        return Resolucion(int(existente["organo_id"]), "nombre")

    # 3. Sospecha: se parece a uno que ya existe, pero no lo suficiente.
    candidato, score = _candidato_mas_parecido(normalizado)
    if candidato is not None and score >= UMBRAL_SOSPECHA:
        repo.encolar_revision(
            nombre_original=nombre or "",
            alias_normalizado=normalizado,
            dir3=dir3,
            candidato_organo_id=candidato,
            score=score,
        )
        log.info(
            "organo_a_revision",
            nombre=normalizado,
            candidato=candidato,
            score=round(score, 3),
        )
        return Resolucion(None, "revision", candidato_id=candidato, score=score)

    # 4. Órgano nuevo.
    if not crear_si_falta:
        return Resolucion(None, "nuevo")
    organo_id = repo.crear(
        nombre_canonico=(nombre or "").strip(),
        nombre_normalizado=normalizado,
        dir3=dir3,
        ccaa=ccaa,
    )
    return Resolucion(organo_id, "nuevo")


def _candidato_mas_parecido(normalizado: str) -> tuple[int | None, float]:
    """Órgano existente más parecido a *normalizado*, con su score.

    Se acota a los que comparten al menos una palabra larga: comparar contra el
    maestro entero en cada resolución sería O(n) por grafía, y con miles de
    órganos el backfill no terminaría. Perder un candidato que no comparte
    ninguna palabra es aceptable — si no comparten ninguna, el score sería 0.
    """
    palabras = [p for p in normalizado.split() if len(p) > 4]
    if not palabras:
        return None, 0.0
    mejor_id: int | None = None
    mejor_score = 0.0
    for fila in _candidatos_por_palabras(palabras):
        score = similitud(normalizado, str(fila["nombre_normalizado"]))
        if score > mejor_score:
            mejor_id, mejor_score = int(fila["organo_id"]), score
    return mejor_id, mejor_score


def _candidatos_por_palabras(palabras: list[str]) -> list[dict[str, Any]]:
    """Órganos que comparten alguna de *palabras*. Delegado a `db/` (ADR-022)."""
    from db.repositories.organos import candidatos_por_palabras

    return candidatos_por_palabras(palabras)
