"""Resolución de entidades: adjudicaciones → maestro de empresas.

Cadena de resolución por adjudicación sin ``empresa_id``:

1. UTE detectada (``parse_ute_members``) → empresa UTE propia (``es_ute=1``)
   con sus miembros resueltos/creados y registrados en ``ute_miembros``.
2. Match exacto por NIF normalizado → enlace automático.
3. Match exacto por nombre normalizado (alias) → enlace automático, salvo
   conflicto de NIF (ambos no nulos y distintos) → cola de revisión.
4. Match fuzzy (difflib, umbral ``FUZZY_THRESHOLD``) → cola de revisión
   humana; la adjudicación queda sin enlazar hasta que se resuelva.
5. Sin match → alta de empresa nueva + enlace.

Idempotente y reanudable: opera solo sobre filas con ``empresa_id IS NULL``
y salta las que tienen revisión pendiente. Sirve igual para el backfill
histórico (scripts/backfill_empresas.py) y para el hook post-ingesta.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Any

from db.database import connect
from db.empresas import (
    EmpresaCaches,
    add_alias,
    add_ute_member,
    create_empresa,
    enqueue_review,
    fetch_unlinked,
    link_adjudicacion,
    load_caches,
    pending_review_keys,
    set_nif_canonico_if_null,
)
from observability.logging import get_logger
from services.normalization import normalize_company, normalize_nif, parse_ute_members

log = get_logger(__name__)

# Umbral de similitud (ratio difflib 0-1) a partir del cual un casi-match va
# a revisión humana. Por debajo se considera empresa distinta y se crea nueva.
FUZZY_THRESHOLD = 0.92


@dataclass
class ResolutionStats:
    linked_nif: int = 0
    linked_alias: int = 0
    created: int = 0
    queued_review: int = 0
    utes: int = 0
    skipped: int = 0
    fetched: int = 0
    last_id: int = 0  # cursor: máximo id de adjudicación visto en el lote

    @property
    def processed(self) -> int:
        return self.linked_nif + self.linked_alias + self.created + self.utes

    def as_dict(self) -> dict[str, int]:
        return {
            "linked_nif": self.linked_nif,
            "linked_alias": self.linked_alias,
            "created": self.created,
            "queued_review": self.queued_review,
            "utes": self.utes,
            "skipped": self.skipped,
        }


def _fuzzy_candidate(alias: str, caches: EmpresaCaches) -> tuple[int, float] | None:
    """Mejor alias existente por similitud, o None si no llega al umbral."""
    matches = difflib.get_close_matches(alias, caches.alias.keys(), n=1, cutoff=FUZZY_THRESHOLD)
    if not matches:
        return None
    best = matches[0]
    score = difflib.SequenceMatcher(None, alias, best).ratio()
    return caches.alias[best], score


def _resolve_simple(
    conn: Any,
    caches: EmpresaCaches,
    pending: set[tuple[str, str]],
    stats: ResolutionStats,
    *,
    nombre: str,
    nif_norm: str | None,
    alias: str,
    es_pyme: int | None,
    fuente: str,
    fuzzy: bool,
) -> int | None:
    """Resuelve una empresa individual (no-UTE). Devuelve empresa_id o None (en revisión)."""
    # 2. NIF exacto
    if nif_norm and nif_norm in caches.nif:
        empresa_id = caches.nif[nif_norm]
        add_alias(conn, empresa_id, alias, nif_variante=nif_norm, fuente=fuente)
        caches.alias.setdefault(alias, empresa_id)
        stats.linked_nif += 1
        return empresa_id

    # 3. Alias exacto
    if alias in caches.alias:
        empresa_id = caches.alias[alias]
        nif_canon = caches.nif_canonico.get(empresa_id)
        if nif_norm and nif_canon and nif_norm != nif_canon:
            # Mismo nombre normalizado, NIF distinto: posible filial u homónimo.
            key = (alias, nif_norm)
            if key not in pending:
                enqueue_review(
                    conn,
                    nombre_original=nombre,
                    alias_normalizado=alias,
                    nif=nif_norm,
                    candidato_empresa_id=empresa_id,
                    score=1.0,
                )
                pending.add(key)
                stats.queued_review += 1
            return None
        add_alias(conn, empresa_id, alias, nif_variante=nif_norm, fuente=fuente)
        if nif_norm and not nif_canon and set_nif_canonico_if_null(conn, empresa_id, nif_norm):
            caches.nif_canonico[empresa_id] = nif_norm
            caches.nif[nif_norm] = empresa_id
        stats.linked_alias += 1
        return empresa_id

    # 4. Fuzzy → revisión humana (nunca enlace automático)
    if fuzzy:
        candidate = _fuzzy_candidate(alias, caches)
        if candidate is not None:
            empresa_id, score = candidate
            key = (alias, nif_norm or "")
            if key not in pending:
                enqueue_review(
                    conn,
                    nombre_original=nombre,
                    alias_normalizado=alias,
                    nif=nif_norm,
                    candidato_empresa_id=empresa_id,
                    score=score,
                )
                pending.add(key)
                stats.queued_review += 1
            return None

    # 5. Empresa nueva
    empresa_id = create_empresa(
        conn, nombre_canonico=nombre.strip(), nif_canonico=nif_norm, es_pyme=es_pyme
    )
    add_alias(conn, empresa_id, alias, nif_variante=nif_norm, fuente=fuente)
    caches.alias[alias] = empresa_id
    caches.nif_canonico[empresa_id] = nif_norm
    if nif_norm:
        caches.nif[nif_norm] = empresa_id
    stats.created += 1
    return empresa_id


def _resolve_ute(
    conn: Any,
    caches: EmpresaCaches,
    stats: ResolutionStats,
    *,
    nombre: str,
    nif_norm: str | None,
    alias: str,
    members: list[str],
    fuente: str,
) -> int:
    """Resuelve una UTE: entidad propia + miembros en ute_miembros."""
    if alias in caches.alias:
        ute_id = caches.alias[alias]
    elif nif_norm and nif_norm in caches.nif:
        ute_id = caches.nif[nif_norm]
    else:
        ute_id = create_empresa(
            conn, nombre_canonico=nombre.strip(), nif_canonico=nif_norm, es_ute=True
        )
        caches.alias[alias] = ute_id
        caches.nif_canonico[ute_id] = nif_norm
        if nif_norm:
            caches.nif[nif_norm] = ute_id
    add_alias(conn, ute_id, alias, nif_variante=nif_norm, fuente=fuente)

    for member_alias in members:
        # Los miembros llegan ya normalizados desde parse_ute_members y sin
        # NIF propio; alta directa sin fuzzy para no inflar la cola de revisión.
        if member_alias in caches.alias:
            member_id = caches.alias[member_alias]
        else:
            member_id = create_empresa(conn, nombre_canonico=member_alias)
            add_alias(conn, member_id, member_alias, fuente=f"{fuente}:ute_member")
            caches.alias[member_alias] = member_id
            caches.nif_canonico[member_id] = None
        add_ute_member(conn, ute_id, member_id)
    stats.utes += 1
    return ute_id


def resolve_unlinked_adjudicaciones(
    batch_size: int = 5000,
    *,
    fuente: str = "placsp",
    fuzzy: bool = True,
    after_id: int = 0,
) -> ResolutionStats:
    """Procesa un lote de adjudicaciones sin empresa_id. Devuelve estadísticas.

    Llamar en bucle (backfill) o una vez tras la ingesta (hook). Cada lote
    corre en una única transacción.
    """
    stats = ResolutionStats(last_id=after_id)
    with connect() as conn:
        caches = load_caches(conn)
        pending = pending_review_keys(conn)
        rows = fetch_unlinked(conn, batch_size, after_id)
        stats.fetched = len(rows)
        for row in rows:
            stats.last_id = max(stats.last_id, int(row["id"]))
            nombre = (row.get("nombre") or "").strip()
            alias = normalize_company(nombre)
            if not alias:
                stats.skipped += 1
                continue
            nif_norm = normalize_nif(row.get("nif"))
            if (alias, nif_norm or "") in pending:
                stats.skipped += 1
                continue

            members = parse_ute_members(nombre)
            empresa_id: int | None
            if members:
                empresa_id = _resolve_ute(
                    conn,
                    caches,
                    stats,
                    nombre=nombre,
                    nif_norm=nif_norm,
                    alias=alias,
                    members=members,
                    fuente=fuente,
                )
            else:
                empresa_id = _resolve_simple(
                    conn,
                    caches,
                    pending,
                    stats,
                    nombre=nombre,
                    nif_norm=nif_norm,
                    alias=alias,
                    es_pyme=row.get("es_pyme"),
                    fuente=fuente,
                    fuzzy=fuzzy,
                )
            if empresa_id is not None:
                link_adjudicacion(conn, int(row["id"]), empresa_id)

    if stats.processed or stats.queued_review:
        log.info("entity_resolution_batch", **stats.as_dict())
    return stats


def resolve_all_unlinked(
    batch_size: int = 5000, *, fuente: str = "placsp", fuzzy: bool = True
) -> ResolutionStats:
    """Itera lotes hasta agotar las adjudicaciones resolubles (backfill)."""
    total = ResolutionStats()
    cursor = 0
    while True:
        batch = resolve_unlinked_adjudicaciones(
            batch_size, fuente=fuente, fuzzy=fuzzy, after_id=cursor
        )
        total.linked_nif += batch.linked_nif
        total.linked_alias += batch.linked_alias
        total.created += batch.created
        total.queued_review += batch.queued_review
        total.utes += batch.utes
        total.skipped += batch.skipped
        total.fetched += batch.fetched
        if batch.fetched == 0:
            break
        cursor = batch.last_id
    return total
