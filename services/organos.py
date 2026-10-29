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


@dataclass(slots=True)
class ResumenResolucion:
    """Qué hizo una pasada de :func:`resolver_pendientes`.

    ``agotado_por_tiempo`` distingue «no quedaba nada» de «me quedé sin
    presupuesto»: la primera es el estado normal de la pipeline cada 4 h, la
    segunda es la señal de que hay backlog histórico que la pasada
    incremental no debe hacer.
    """

    grafias_vistas: int = 0
    por_dir3: int = 0
    por_nombre: int = 0
    creadas: int = 0
    encoladas_revision: int = 0
    sin_nombre: int = 0
    filas_actualizadas: int = 0
    agotado_por_tiempo: bool = False

    @property
    def asignadas(self) -> int:
        """Grafías que acabaron con un ``organo_id`` firme."""
        return self.por_dir3 + self.por_nombre + self.creadas

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "grafias_vistas": self.grafias_vistas,
            "por_dir3": self.por_dir3,
            "por_nombre": self.por_nombre,
            "creadas": self.creadas,
            "encoladas_revision": self.encoladas_revision,
            "sin_nombre": self.sin_nombre,
            "asignadas": self.asignadas,
            "filas_actualizadas": self.filas_actualizadas,
            "agotado_por_tiempo": self.agotado_por_tiempo,
        }


#: Presupuesto por defecto de una pasada incremental, en segundos. Mismo
#: criterio que ``services.entity_resolution.HOOK_TIME_BUDGET_S``: el paso
#: corre dentro del cierre de la pipeline y no puede quedarse con el step.
PRESUPUESTO_PASADA_S = 120.0


def resolver_pendientes(
    *,
    max_grafias: int = 500,
    presupuesto_s: float = PRESUPUESTO_PASADA_S,
    batch: int = 2_000,
    aplicar: bool = True,
) -> ResumenResolucion:
    """Resuelve, por volumen descendente, las grafías sin ``organo_id``.

    Es **la misma** decisión que ejecutó el backfill histórico de órganos —el
    script delega aquí desde 2026-09-14— y también lo que corre el paso
    canónico ``organos_resolve`` en cada cierre de la pipeline: hasta esa
    fecha nada resolvía las filas ingeridas *después* del backfill, así que el
    maestro se degradaba con cada pasada del ATOM y la analítica volvía a
    agrupar por texto para todo lo nuevo.

    Idempotente y reanudable: solo mira filas con ``organo_id IS NULL`` y se
    detiene por cuenta (``max_grafias``) o por reloj (``presupuesto_s``), lo
    que llegue antes. Con ``aplicar=False`` cuenta lo que haría sin escribir
    (el *dry-run* del script).
    """
    import time

    from db.repositories import organos as repo_organos

    inicio = time.monotonic()
    resumen = ResumenResolucion()
    for fila in repo_organos.grafias_sin_resolver(limit=max_grafias):
        if time.monotonic() - inicio > presupuesto_s:
            resumen.agotado_por_tiempo = True
            break
        resumen.grafias_vistas += 1
        nombre = str(fila.get("nombre") or "")
        resolucion = resolver(nombre, ccaa=fila.get("ccaa"), crear_si_falta=aplicar)
        if resolucion is None:
            resumen.sin_nombre += 1
            continue
        if resolucion.via == "dir3":
            resumen.por_dir3 += 1
        elif resolucion.via == "nombre":
            resumen.por_nombre += 1
        elif resolucion.via == "revision":
            resumen.encoladas_revision += 1
        elif resolucion.via == "nuevo":
            resumen.creadas += 1
        if not aplicar or resolucion.organo_id is None:
            continue
        # La asignación va por lotes sobre la grafía cruda, que es como está en
        # la tabla: `lower(btrim(...))` es el mismo predicado que la descubrió.
        plano = str(fila.get("nombre_plano") or "")
        while True:
            n = repo_organos.asignar_a_licitaciones(
                resolucion.organo_id, nombre_normalizado=plano, limit=batch
            )
            if n <= 0:
                break
            resumen.filas_actualizadas += n
            # Un lote incompleto es el último: sin índice sobre
            # `lower(btrim(...))` cada llamada recorre la tabla entera, y la
            # que confirmaba el cero era un recorrido más por grafía.
            if n < batch:
                break
    if resumen.grafias_vistas:
        log.info("organos_resolver_pendientes", **resumen.as_dict())
    return resumen


@dataclass(frozen=True, slots=True)
class DecisionRevision:
    """Qué hizo :func:`decidir_revision` con un ítem de la cola."""

    #: Órgano al que quedó asignada la grafía.
    organo_id: int
    #: ``True`` si la decisión creó (o recuperó por nombre) un órgano propio
    #: para la grafía; ``False`` si se fusionó con el candidato como alias.
    organo_nuevo: bool
    #: Licitaciones que recibieron ``organo_id`` por esta decisión.
    filas_asignadas: int


#: Lote de :func:`decidir_revision` al asignar licitaciones. El mismo que la
#: pasada incremental de :func:`resolver_pendientes`.
LOTE_ASIGNACION = 2_000


def decidir_revision(
    revision_id: int,
    *,
    aceptar: bool,
    resolved_by: str = "",
    batch: int = LOTE_ASIGNACION,
) -> DecisionRevision | None:
    """Aplica la decisión humana sobre una fusión dudosa de la cola.

    Calcada de ``db.empresas.apply_review``, que hace lo mismo con empresas:

    - **Aceptar**: la grafía es el candidato. Se registra como alias suyo
      (``fuente="review"``), y la próxima pasada del resolver la encuentra por
      nombre sin volver a la cola.
    - **Rechazar**: es otro órgano. Se crea uno propio con esa grafía como
      canónica. Es la asimetría del módulo: separar no exige evidencia.

    En los dos casos, las licitaciones que esperaban la decisión con esa
    grafía (``organo_id IS NULL``) reciben el órgano, por lotes hasta agotar.

    Devuelve ``None`` si el ítem no existe o ya no estaba pendiente.

    La fila se reclama **antes** de aplicar los efectos
    (:func:`db.repositories.organos.resolver_revision`): así dos decisiones
    simultáneas no pueden aplicar las dos. Si un efecto falla a medias, la
    grafía sigue sin ``organo_id`` y la siguiente pasada de
    :func:`resolver_pendientes` la vuelve a encolar: se pierde la decisión, no
    el dato.
    """
    fila = repo.resolver_revision(
        revision_id,
        status="accepted" if aceptar else "rejected",
        resolved_by=resolved_by,
    )
    if fila is None:
        return None

    nombre_original = str(fila.get("nombre_original") or "")
    alias = str(fila["alias_normalizado"])
    dir3 = fila.get("dir3") or None
    candidato = fila.get("candidato_organo_id")

    if aceptar and candidato is not None:
        organo_id = int(candidato)
        organo_nuevo = False
        repo.anadir_alias(
            organo_id,
            alias_normalizado=alias,
            alias_original=nombre_original,
            dir3_variante=dir3,
            fuente="review",
        )
    else:
        # Sin candidato no hay con quién fusionar: aceptar equivale a separar,
        # como en `apply_review`. El DIR3 solo se reclama si nadie lo tiene ya:
        # el índice único de `v114` haría que `crear` no encontrara su fila.
        organo_id = repo.crear(
            nombre_canonico=nombre_original.strip() or alias,
            nombre_normalizado=alias,
            dir3=dir3 if dir3 and repo.get_by_dir3(dir3) is None else None,
        )
        organo_nuevo = True

    plano = str(fila.get("nombre_plano") or "")
    filas_asignadas = 0
    while plano:
        n = repo.asignar_a_licitaciones(organo_id, nombre_normalizado=plano, limit=batch)
        if n <= 0:
            break
        filas_asignadas += n
        if n < batch:  # lote incompleto: no queda nada que asignar
            break

    log.info(
        "organo_revision_resuelta",
        revision_id=revision_id,
        aceptada=aceptar,
        organo_id=organo_id,
        organo_nuevo=organo_nuevo,
        filas_asignadas=filas_asignadas,
    )
    return DecisionRevision(
        organo_id=organo_id, organo_nuevo=organo_nuevo, filas_asignadas=filas_asignadas
    )


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
