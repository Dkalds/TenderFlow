"""Modificaciones de contrato publicadas (art. 207.3 LCSP): enlazado y lectura en la ficha.

Las escriben los conectores (``db.repositories.modificaciones``). Aquí vive lo
que es regla de dominio:

- **Enlazar un aviso de TED con su expediente.** Primero por el aviso que
  modifica (BT-1501): si ese aviso está en ``licitaciones``, su expediente (o la
  canónica de la que es republicación confirmada). Si no, por ``idEvl`` o por
  BT-22 dentro del mismo órgano (``services.dedupe.expedientes_por_referencia``).
  Nunca por título: lo que no casa se queda sin enlazar y se reintenta en la
  siguiente pasada, por si su expediente llega después.
- **Lo que un contrato acaba costando.** Lo adjudicado frente al importe final
  de su última modificación, solo con las dos cifras publicadas y sin IVA.
- **Cuánto amplía un órgano sus contratos.** La mediana de esa variación entre
  sus contratos modificados, solo por encima de una muestra mínima.
"""

from __future__ import annotations

import re
import statistics
from typing import TYPE_CHECKING

from db.repositories import modificaciones as repo
from observability import get_logger
from services.dedupe import ReferenciaCruzada, expedientes_por_referencia, id_evl_de_url
from shared.dto import (
    AmpliacionDelOrgano,
    CosteDeContrato,
    ModificacionesDeLicitacion,
    ModificacionPublicada,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from db.repositories.modificaciones import FilaAdjudicado, FilaModificacion

log = get_logger(__name__)

#: Contratos con adjudicación e importe final publicados que necesita un órgano
#: para que la ficha dé su cifra. La misma vara que la tasa de anulación
#: (``services.analytics.scoring.ANULACION_MINIMO_EXPEDIENTES``): con cinco, un
#: solo contrato que dobla su importe mueve la mediana, y lo que se lee es un
#: contrato, no un hábito del órgano.
MUESTRA_MINIMA_ORGANO = 10

#: Avisos sin enlazar que se reintentan por pasada. Medido el 2026-11-10: 1.489
#: avisos ``can-modif`` de TI en 24 meses; el tope cubre todo el histórico.
_MAX_SIN_ENLAZAR = 5_000


#: BT-1501 en su forma de número de publicación (``871071-2025``): la de
#: ``id_externo`` de un aviso. La otra, el UUID del aviso con su versión
#: (``cb2be52c-…-01``), solo lleva a otro aviso de modificación.
_NUMERO_PUBLICACION = re.compile(r"\d{1,8}-\d{4}")
_VERSION_DE_UUID = re.compile(
    r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})-\d+$"
)


def _uuid_del_aviso(aviso: str) -> str:
    """El UUID de un BT-1501 sin su sufijo de versión, o el valor tal cual."""
    encontrado = _VERSION_DE_UUID.match(aviso.strip().lower())
    return encontrado.group(1) if encontrado else aviso.strip().lower()


def enlazar_pendientes(*, fuente: str) -> int:
    """Enlaza con su expediente las modificaciones de ``fuente`` que siguen sin él.

    Por este orden: el aviso original (BT-1501) si es una fila de
    ``licitaciones``; si es otro aviso de modificación ya enlazado, su
    expediente; y si no, ``idEvl`` o BT-22 dentro del mismo órgano. Devuelve
    cuántas se enlazaron. Idempotente: solo toca filas sin expediente.
    """
    filas = repo.sin_enlazar(fuente=fuente, limite=_MAX_SIN_ENLAZAR)
    if not filas:
        return 0
    numeros = {
        f["clave"]: f"ted:{f['aviso_original']}"
        for f in filas
        if f["aviso_original"] and _NUMERO_PUBLICACION.fullmatch(f["aviso_original"])
    }
    uuids = {
        f["clave"]: _uuid_del_aviso(f["aviso_original"])
        for f in filas
        if f["aviso_original"] and f["clave"] not in numeros
    }
    originales = repo.expedientes_de_avisos(sorted(set(numeros.values())))
    previos = repo.expedientes_de_avisos_previos(sorted(set(uuids.values())))

    enlaces: list[tuple[str, str, str]] = []
    restantes: dict[str, tuple[str | None, ReferenciaCruzada]] = {}
    for fila in filas:
        clave = fila["clave"]
        expediente = originales.get(numeros.get(clave, "")) or previos.get(uuids.get(clave, ""))
        if expediente is not None:
            enlaces.append((clave, expediente, "aviso_original"))
            continue
        referencia = ReferenciaCruzada(
            expediente=fila["expediente_ref"], id_evl=id_evl_de_url(fila["url"])
        )
        restantes[clave] = (fila["organo"], referencia)
    enlaces.extend(
        (clave, expediente, "referencia")
        for clave, expediente in expedientes_por_referencia(restantes).items()
    )
    enlazadas = repo.enlazar(enlaces)
    log.info(
        "modificaciones_enlazadas",
        fuente=fuente,
        pendientes=len(filas),
        enlazadas=enlazadas,
    )
    return enlazadas


def _publicada(fila: FilaModificacion) -> ModificacionPublicada:
    campos = ModificacionPublicada.model_fields
    return ModificacionPublicada.model_validate({k: v for k, v in fila.items() if k in campos})


def _adjudicado_por_lote(filas: Iterable[FilaAdjudicado]) -> dict[tuple[str, str | None], float]:
    """El importe adjudicado de cada ``(expediente, lote)``, si es uno solo.

    Varios importes distintos en el mismo lote (un marco con varios
    adjudicatarios, cada uno por su parte) no dicen cuánto se adjudicó al
    contrato modificado: ese lote no entra.
    """
    importes: dict[tuple[str, str | None], set[float]] = {}
    for fila in filas:
        importes.setdefault((fila["licitacion_id"], fila["lote_numero"]), set()).add(
            fila["importe_adjudicado"] or 0.0
        )
    return {
        clave: valores.pop()
        for clave, valores in importes.items()
        if len(valores) == 1 and next(iter(valores)) > 0
    }


def _costes(
    modificaciones: Sequence[tuple[str, FilaModificacion]],
    adjudicado: dict[tuple[str, str | None], float],
) -> list[tuple[str, CosteDeContrato]]:
    """``(expediente, coste)`` de cada contrato con adjudicado e importe final sin IVA.

    El final es el de la última modificación del contrato que lo publica
    (``modificaciones`` llega ordenada de la más antigua a la más reciente). Un
    lote con modificaciones de varios contratos distintos, o con un número de
    modificación repetido, no entra: no hay un adjudicado que sea de uno de
    ellos.
    """
    final: dict[tuple[str, str | None], float] = {}
    contratos: dict[tuple[str, str | None], set[str | None]] = {}
    numeros: dict[tuple[str, str | None], list[str | None]] = {}
    for licitacion_id, fila in modificaciones:
        clave = (licitacion_id, fila["lote_numero"])
        contratos.setdefault(clave, set()).add(fila["contrato_ref"])
        numeros.setdefault(clave, []).append(fila["numero"])
        if fila["importe_final"] is not None and fila["importe_final_base"] == "sin_iva":
            final[clave] = fila["importe_final"]
    out: list[tuple[str, CosteDeContrato]] = []
    for clave, importe_final in final.items():
        base = adjudicado.get(clave)
        # Dos modificaciones con el mismo número en el mismo contrato son de
        # lotes que comparten `ContractID` sin decir cuál: no hay un final.
        repetidos = len(numeros[clave]) != len(set(numeros[clave]))
        if base is None or len(contratos[clave]) > 1 or repetidos:
            continue
        out.append(
            (
                clave[0],
                CosteDeContrato(
                    lote_numero=clave[1],
                    adjudicado=base,
                    final=importe_final,
                    variacion_pct=round((importe_final / base - 1) * 100, 1),
                ),
            )
        )
    return out


def modificaciones_de_licitacion(licitacion_id: str) -> ModificacionesDeLicitacion:
    """Lo que la ficha enseña de las modificaciones del expediente y de su órgano."""
    propias = repo.de_licitacion(licitacion_id)
    del_organo = repo.del_organo_de(licitacion_id)
    ids = sorted({licitacion_id} | {f["licitacion_id"] for f in del_organo})
    adjudicado = _adjudicado_por_lote(repo.adjudicado_por_lote(ids))

    costes = [c for _, c in _costes([(licitacion_id, f) for f in propias], adjudicado)]
    del_organo_costes = _costes([(f["licitacion_id"], f) for f in del_organo], adjudicado)
    variaciones = [c.variacion_pct for _, c in del_organo_costes]
    n = len(variaciones)
    return ModificacionesDeLicitacion(
        items=[_publicada(f) for f in propias],
        costes=sorted(costes, key=lambda c: (c.lote_numero is not None, c.lote_numero or "")),
        organo=AmpliacionDelOrgano(
            n=n,
            muestra_minima=MUESTRA_MINIMA_ORGANO,
            mediana_pct=(
                round(statistics.median(variaciones), 1) if n >= MUESTRA_MINIMA_ORGANO else None
            ),
        ),
    )
