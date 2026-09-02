"""Repository para ``licitacion_tecnologia_pliego`` y la escritura del merge
hacia ``licitaciones``/``licitacion_tecnologia_score`` (TID251: todo el SQL
nuevo de la señal de tecnología por pliego vive aquí, aunque el merge toque
tablas que otros repos también leen -- ``licitacion_tecnologia_pliego`` es la
tabla que esta feature posee).

Plan "categorización alimentada por los pliegos" (2026-08-04): la señal
(keywords o LLM) vive en tabla propia para sobrevivir al clobber que
``db/upsert.py`` hace en cada re-scrape sobre ``licitaciones.ml_*`` -- el
merge se re-aplica después de cada ``precompute_ml_tecnologias``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, NamedTuple

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts

# Sentinel persistido cuando una licitación se puntuó y no dio ninguna
# tecnología por encima del mínimo de hits: sin esta fila, la consulta de
# "pendientes de señal" volvería a seleccionarla en cada corrida para
# siempre (a diferencia de tender_fact_sheets, esta tabla no tiene una fila
# por licitación -- es multi-fila por tecnología). score=0 la deja fuera de
# cualquier merge (PLIEGO_TECH_MIN_SCORE nunca es <= 0) y de las lecturas
# para el endpoint, que la filtran explícitamente.
#
# Público: cualquier lectura de la tabla tiene que excluirlo, y duplicar el
# literal en otro repo es la forma de que un día uno de los dos se olvide.
NO_SIGNAL_SENTINEL = "__no_signal__"
_NO_SIGNAL_SENTINEL = NO_SIGNAL_SENTINEL


class TechSignal(NamedTuple):
    """Señal detectada para una tecnología: score + evidencia (una de las dos)."""

    score: float
    matched_terms: list[str] | None = None
    evidence: list[dict[str, Any]] | None = None


class MergeOutcome(NamedTuple):
    """Salida de ``merge_many_with_lock``: lo escrito y lo que falló.

    Ambos van por ``licitacion_id`` para que el llamador pueda emitir los
    eventos de auditoría solo de lo que realmente se persistió y contar los
    fallos sin volver a la BD.
    """

    results: dict[str, dict[str, Any]]
    errors: dict[str, str]


# Licitaciones por transacción del merge por lotes. Acota el tamaño de los
# ``executemany`` y el tiempo que el lote nocturno retiene el lock frente al
# camino incremental de ``pliegos.yml``; el ahorro de viajes ya está hecho a
# partir de unas pocas decenas. Ver ``merge_many_with_lock``.
_MERGE_CHUNK_SIZE = 200

# Clave del advisory lock que serializa el merge consigo mismo. Antes era una
# por licitación (``tenderflow.tech_signal_merge.<id>``); ver el docstring de
# ``merge_many_with_lock`` para por qué ahora es una sola.
_MERGE_LOCK_KEY = "tenderflow.tech_signal_merge"


class TecnologiaPliegoRepository:
    def upsert_signals(
        self,
        licitacion_id: str,
        *,
        method: str,
        signal_version: str,
        scores: dict[str, TechSignal],
    ) -> int:
        """Upsert de las señales ``method`` vigentes de una licitación.

        ``ON CONFLICT ... DO UPDATE`` preserva ``merged_at`` de una fila ya
        fusionada (no está en el SET), así que una re-puntuación que
        redetecta la misma tecnología a un score distinto NO reabre su
        ventana de "pendiente de fusionar" ni duplica el evento de auditoría
        en ``domain_events`` -- un DELETE+INSERT ciego rompía esto porque el
        INSERT siempre deja ``merged_at`` en NULL. Solo se borran las
        tecnologías que esta corrida YA NO detecta, para no acumular
        obsoletas.

        ``scores`` vacío persiste el sentinel ``_NO_SIGNAL_SENTINEL`` para que
        ``list_licitaciones_pending_signal`` no vuelva a seleccionar esta
        licitación en cada corrida mientras ``signal_version`` no cambie.
        """
        now = now_utc_iso()
        techs = list(scores.keys()) or [_NO_SIGNAL_SENTINEL]
        rows: list[tuple[str, str, str, float, str | None, str | None, str, str]] = [
            (
                licitacion_id,
                tech,
                method,
                signal.score,
                json.dumps(signal.matched_terms, ensure_ascii=False)
                if signal.matched_terms is not None
                else None,
                json.dumps(signal.evidence, ensure_ascii=False)
                if signal.evidence is not None
                else None,
                signal_version,
                now,
            )
            for tech, signal in scores.items()
        ] or [(licitacion_id, _NO_SIGNAL_SENTINEL, method, 0.0, None, None, signal_version, now)]

        with connect() as c:
            placeholders = ",".join("%s" for _ in techs)
            c.execute(
                "DELETE FROM licitacion_tecnologia_pliego "
                f"WHERE licitacion_id = %s AND method = %s AND tecnologia NOT IN ({placeholders})",
                (licitacion_id, method, *techs),
            )
            c.executemany(
                "INSERT INTO licitacion_tecnologia_pliego "
                "(licitacion_id, tecnologia, method, score, matched_terms, "
                "evidence_json, signal_version, computed_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT(licitacion_id, tecnologia, method) DO UPDATE SET "
                "score=excluded.score, matched_terms=excluded.matched_terms, "
                "evidence_json=excluded.evidence_json, signal_version=excluded.signal_version, "
                "computed_at=excluded.computed_at",
                rows,
            )
        return len(scores)

    def list_licitaciones_pending_signal(
        self, *, signal_version: str, method: str = "keywords", limit: int = 500
    ) -> list[str]:
        """Licitaciones con al menos un documento ``extracted`` y sin señal
        ``method`` vigente (inexistente o de una ``signal_version`` distinta
        -- un bump del filtro de keywords reprocesa el universo)."""
        with connect_read() as c:
            rows = c.execute(
                "SELECT DISTINCT d.licitacion_id FROM documentos d "
                "WHERE d.status = 'extracted' "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM licitacion_tecnologia_pliego p "
                "  WHERE p.licitacion_id = d.licitacion_id AND p.method = %s "
                "  AND p.signal_version = %s"
                ") "
                "ORDER BY d.licitacion_id LIMIT %s",
                (method, signal_version, max(1, min(int(limit), 2000))),
            ).fetchall()
            return [str(row[0]) for row in rows]

    def list_metadata_pending_llm_signal(
        self, *, signal_version: str, method: str = "llm_metadata", limit: int = 200
    ) -> list[dict[str, Any]]:
        """Licitaciones sin señal ``method`` vigente, con la metadata que basta
        para clasificarlas.

        A diferencia de ``list_licitaciones_pending_signal``, no exige
        documentos: el etiquetado por LLM sobre metadata solo lee el anuncio,
        así que el universo es toda la tabla ``licitaciones``. Devuelve las
        filas completas (no solo los ids) para que el job no haga un N+1
        contra el repo de licitaciones.

        Las más recientes primero: el valor de negocio está en el flujo
        entrante, y el backlog histórico se drena por detrás lote a lote.

        Pendiente = sin fila de esta ``(method, signal_version)``, incluido el
        sentinel ``NO_SIGNAL_SENTINEL`` -- una licitación que el LLM ya declaró
        "sin tecnología" cuenta como procesada y no se reintenta hasta que se
        bumpee la versión (modelo o prompt nuevo).
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT l.id_externo, l.titulo, l.descripcion, l.cpv, l.importe, "
                "l.organo_contratacion, l.estado, l.fecha_publicacion "
                "FROM licitaciones l "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM licitacion_tecnologia_pliego p "
                "  WHERE p.licitacion_id = l.id_externo AND p.method = %s "
                "  AND p.signal_version = %s"
                ") "
                "ORDER BY l.fecha_publicacion DESC NULLS LAST, l.id_externo "
                "LIMIT %s",
                (method, signal_version, max(1, min(int(limit), 5000))),
            )
            return rows_to_dicts(cur)

    def list_signals_for_merge(
        self, *, min_score: float, licitacion_ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Filas de señal candidatas al merge (``score >= min_score``),
        opcionalmente acotadas a un subconjunto de licitaciones (tras
        puntuar un lote nuevo). Sin acotar, cubre todas -- usado por el
        re-merge nightly completo tras ``precompute_ml_tecnologias``."""
        params: list[Any] = [min_score]
        extra = ""
        if licitacion_ids:
            placeholders = ",".join("%s" for _ in licitacion_ids)
            extra = f" AND licitacion_id IN ({placeholders})"
            params.extend(licitacion_ids)
        with connect_read() as c:
            cur = c.execute(
                "SELECT licitacion_id, tecnologia, method, score, matched_terms, "
                "evidence_json, signal_version, merged_at "
                f"FROM licitacion_tecnologia_pliego WHERE score >= %s{extra} "
                "ORDER BY licitacion_id",
                params,
            )
            return rows_to_dicts(cur)

    def stamp_merged(self, rows: list[tuple[str, str, str]], *, merged_at: str) -> None:
        """Marca ``merged_at`` la primera vez -- solo dedupe del evento de
        auditoría, nunca condición de si el merge se aplica (el merge se
        re-aplica entero en cada corrida nightly para sanar el clobber de
        ``db/upsert.py``)."""
        if not rows:
            return
        with connect() as c:
            c.executemany(
                "UPDATE licitacion_tecnologia_pliego SET merged_at = %s "
                "WHERE licitacion_id = %s AND tecnologia = %s AND method = %s "
                "AND merged_at IS NULL",
                [(merged_at, lic, tech, method) for (lic, tech, method) in rows],
            )

    def list_for_licitacion(self, licitacion_id: str) -> list[dict[str, Any]]:
        """Señales (todas, cualquier score) de una licitación para el
        endpoint de detalle -- excluye el sentinel de "sin señal"."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT tecnologia, method, score, matched_terms, evidence_json, "
                "signal_version, computed_at, merged_at "
                "FROM licitacion_tecnologia_pliego "
                "WHERE licitacion_id = %s AND tecnologia != %s "
                "ORDER BY score DESC",
                (licitacion_id, _NO_SIGNAL_SENTINEL),
            )
            return rows_to_dicts(cur)

    def merge_many_with_lock(
        self,
        licitacion_ids: list[str],
        compute: Callable[[str, dict[str, Any]], dict[str, Any] | None],
        *,
        chunk_size: int = _MERGE_CHUNK_SIZE,
    ) -> MergeOutcome:
        """Read-modify-write atómico del merge para un lote de licitaciones,
        serializado por un advisory lock transaccional (mismo patrón que
        ``db/audit.py::_serialize_audit_chain_write``).

        Sin el lock, leer el estado actual y escribir el resultado en dos
        transacciones separadas es una carrera de lost-update real: el paso
        ``tech_signal_merge`` corre cada 4h vía ``scrape-daily.yml``
        (``concurrency.group: scrape``) y también, para lotes recién
        puntuados, vía ``pliegos.yml`` (``concurrency.group: pliegos``,
        cron nocturno) -- grupos de concurrencia distintos, así que GitHub
        Actions no serializa ambos workflows entre sí, y si se solapan sobre
        la misma licitación uno puede pisar la escritura del otro con datos
        ya obsoletos.

        **Por lotes, no de una en una.** Hasta 2026-09 esto era
        ``merge_with_lock`` y abría una transacción por licitación: lock, dos
        SELECT, UPDATE, INSERT y COMMIT, o sea ~6 viajes secuenciales a
        Postgres por fila. Con las 1.085 licitaciones con señal vigente eso
        son ~6.500 idas y vueltas contra Supabase a ~127 ms cada una: 14 de
        los 20 minutos del step "Cierre de la pasada" de ``scrape-daily.yml``,
        que expiraba dejando sin correr todo lo que va detrás (``dlq_retry``,
        ``anomaly_checks``, ``retention_cleanup``, ``drift_checks``...). No
        era coste de BD -- ambas búsquedas van por índice (``licitaciones_pkey``
        e ``idx_lts_lic``)-- sino latencia pura, el mismo defecto que ya se
        corrigió en ``db/connection.py::connect_read``. Ahora son ~6 viajes
        por CHUNK.

        El lock pasa a ser **uno para toda la feature** en vez de uno por
        licitación: tomar N locks en una sola sentencia no garantiza el orden
        de adquisición (dos lotes con conjuntos distintos podrían
        interbloquearse) y además cuentan contra ``max_locks_per_transaction``.
        Con la sección crítica reducida a milisegundos por chunk, serializar
        merge contra merge no cuesta nada, y los dos únicos caminos que lo
        toman son jobs por lotes.

        ``compute`` es lógica de dominio pura (sin I/O) que recibe
        ``(licitacion_id, {"predicted": set[str], "scores": dict[str, float]})``
        -- el estado actual de ``licitaciones.ml_tecnologias`` +
        ``licitacion_tecnologia_score`` -- y devuelve el resultado a escribir,
        o ``None`` para no escribir nada de esa licitación.

        Fail-open por licitación: una excepción de ``compute`` (dato
        inconsistente) descarta solo esa licitación y el resto del chunk se
        escribe igual. Un fallo de BD revierte su chunk entero y se reporta
        como error de cada licitación del chunk; los siguientes se intentan
        igualmente.
        """
        results: dict[str, dict[str, Any]] = {}
        errors: dict[str, str] = {}
        # Orden estable y sin duplicados: el mismo lote produce los mismos
        # chunks en cada corrida, así que un fallo de BD siempre se lleva el
        # mismo grupo y no rota entre pasadas.
        ordenados = sorted(set(licitacion_ids))
        for start in range(0, len(ordenados), chunk_size):
            chunk = ordenados[start : start + chunk_size]
            try:
                chunk_results, chunk_errors = self._merge_chunk(chunk, compute)
            except Exception as exc:
                errors.update(dict.fromkeys(chunk, f"{type(exc).__name__}: {exc}"))
                continue
            results.update(chunk_results)
            errors.update(chunk_errors)
        return MergeOutcome(results=results, errors=errors)

    def _merge_chunk(
        self,
        chunk: list[str],
        compute: Callable[[str, dict[str, Any]], dict[str, Any] | None],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        """Una transacción del merge por lotes: lock, lectura del estado de
        todo el chunk, cálculo en memoria y escritura agrupada. Ver
        ``merge_many_with_lock`` para el porqué del lote y del lock."""
        results: dict[str, dict[str, Any]] = {}
        errors: dict[str, str] = {}
        with connect() as c:
            c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (_MERGE_LOCK_KEY,))
            lic_rows = c.execute(
                "SELECT id_externo, ml_tecnologias FROM licitaciones WHERE id_externo = ANY(%s)",
                (chunk,),
            ).fetchall()
            score_rows = c.execute(
                "SELECT licitacion_id, tecnologia, probabilidad "
                "FROM licitacion_tecnologia_score WHERE licitacion_id = ANY(%s)",
                (chunk,),
            ).fetchall()

            predicted: dict[str, set[str]] = {}
            for row in lic_rows:
                raw = str(row[1]) if row[1] else ""
                predicted[str(row[0])] = {t for t in raw.split(",") if t}
            scores: dict[str, dict[str, float]] = {}
            for row in score_rows:
                scores.setdefault(str(row[0]), {})[str(row[1])] = float(row[2])

            now = now_utc_iso()
            update_params: list[tuple[Any, ...]] = []
            score_params: list[tuple[Any, ...]] = []
            for licitacion_id in chunk:
                # Una licitación inexistente se descarta aquí y no en la BD:
                # ``licitacion_tecnologia_score`` tiene FK contra
                # ``licitaciones.id_externo``, así que su INSERT reventaría la
                # transacción y se llevaría por delante al chunk ENTERO. La
                # comprobación es gratis (``lic_rows`` ya está leído) y el
                # resultado es el mismo que daba la versión de una en una: esa
                # licitación cuenta como error y las demás se escriben.
                if licitacion_id not in predicted:
                    errors[licitacion_id] = "licitacion_id sin fila en licitaciones"
                    continue
                state: dict[str, Any] = {
                    "predicted": predicted[licitacion_id],
                    "scores": scores.get(licitacion_id, {}),
                }
                try:
                    result = compute(licitacion_id, state)
                except Exception as exc:
                    errors[licitacion_id] = f"{type(exc).__name__}: {exc}"
                    continue
                if result is None:
                    continue
                results[licitacion_id] = result
                update_params.append(
                    (
                        result["ml_tecnologias"],
                        result["ml_proba_max"],
                        result["ml_tech_principal"],
                        licitacion_id,
                    )
                )
                score_params.extend(
                    (licitacion_id, tech, proba, result["threshold_aplicado"], now)
                    for tech, proba in result["pliego_scores"]
                )

            if update_params:
                c.executemany(
                    "UPDATE licitaciones SET ml_tecnologias = %s, ml_proba_max = %s, "
                    "ml_tech_principal = %s WHERE id_externo = %s",
                    update_params,
                )
            if score_params:
                c.executemany(
                    "INSERT INTO licitacion_tecnologia_score "
                    "(licitacion_id, tecnologia, probabilidad, threshold_aplicado, computed_at) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT(licitacion_id, tecnologia) DO UPDATE SET "
                    "probabilidad=excluded.probabilidad, "
                    "threshold_aplicado=excluded.threshold_aplicado, "
                    "computed_at=excluded.computed_at",
                    score_params,
                )
        return results, errors
