"""Repository para ``documentos``/``documento_chunks`` (plan Pliegos+RAG, F6).

Metadatos + texto extraído de los adjuntos (pliegos) de una licitación —
v56 (``db/alembic/versions/v56_pg_documentos_pgvector.py`` / equivalente
SQLite en ``db/schema.py``). Ciclo de vida por fila: ``pending`` (metadatos
insertados por el parser) → ``downloaded``/``error`` (F7, descarga) →
``extracted`` (F7, texto extraído) → chunks + embeddings (F8).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from db.database import DocumentoReferencia, connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

_MAX_ERROR_DETAIL_LEN = 2000


def _to_pg_vector_literal(vec: Sequence[float]) -> str:
    """Formato de texto que pgvector castea con ``::vector`` (``[0.1,0.2,...]``)."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


class DocumentosRepository:
    """Acceso a la tabla ``documentos`` (TID251: SQL nuevo solo aquí)."""

    def upsert_meta(self, licitacion_id: str, refs: list[DocumentoReferencia]) -> int:
        """Inserta o refresca los metadatos de los adjuntos de una licitación.

        Idempotente, pero **por identidad de documento y no por URI** (v88). La
        distinción importa porque los enlaces de PLACSP llevan un token que la
        plataforma re-emite: hasta v88 el conflicto se resolvía sobre
        ``UNIQUE(licitacion_id, uri)``, así que el mismo pliego con token nuevo
        no era "el mismo" y cada rotación insertaba una fila más (262 grupos
        duplicados en producción). Ahora la identidad es
        ``(licitacion_id, tipo, source_hash)`` —el ``cbc:DocumentHash`` del
        CODICE, que depende del contenido y no del token—.

        Se resuelve leyendo primero las filas de la licitación y repartiendo las
        referencias en Python, en lugar de encadenar ``UPDATE``s a ciegas: hace
        falta ver el conjunto entero para no violar ``UNIQUE(licitacion_id,
        uri)`` al mover una URI y para decidir las adopciones. Son ~4 viajes por
        licitación (el ``SELECT`` más los buckets no vacíos, que psycopg
        canaliza), frente a 1 antes.

        Cuatro destinos posibles para cada referencia:

        1. **Refresco por hash** — ya existe una fila con ese
           ``(tipo, source_hash)``: se le actualiza la URI (token nuevo) y el
           nombre. El ``status`` no se toca salvo por la regla de revive de
           abajo; en particular un documento ya ``extracted`` conserva su texto,
           porque el mismo hash significa el mismo contenido.
        2. **Adopción por URI** — la fila existe con esa URI exacta pero sin
           ``source_hash`` (fila anterior a v88): se le rellena la identidad.
        3. **Adopción por tipo único** — la referencia trae hash, no casa por
           hash ni por URI, y hay **exactamente una** fila legacy de ese tipo y
           **exactamente una** referencia huérfana de ese tipo. El mapeo es
           inequívoco, así que se adopta y de paso se repara su enlace muerto.
           Sin este caso, cada re-scrape de una fila legacy con token rotado
           insertaría un duplicado — y un backfill histórico completo los
           insertaría a decenas de miles de golpe.
        4. **Inserción** — todo lo demás.

        **Revive**: si el enlace cambió y la fila estaba en ``error`` por un
        fallo de *descarga* (``error_detail`` con el prefijo
        ``descarga fallida:`` que pone ``fetch_and_extract``), vuelve a
        ``pending``. Un token nuevo es exactamente lo que arregla un 500 del
        servlet. No reviven los fallos de *extracción* —content-type no
        soportado, PDF cifrado, escaneado sin OCR—, que no llevan ese prefijo:
        con esos, un enlace nuevo da el mismo resultado y el documento entraría
        en un ciclo perpetuo de reintento consumiendo el lote diario.

        Devuelve el número de referencias procesadas (no distingue insertadas de
        refrescadas; el detalle va al log ``documentos_upsert``).
        """
        if not refs:
            return 0

        ahora = now_utc_iso()
        with connect() as c:
            cur = c.execute(
                "SELECT id, tipo, uri, filename, source_hash, status, error_detail "
                "FROM documentos WHERE licitacion_id = %s",
                (licitacion_id,),
            )
            existentes = rows_to_dicts(cur)

            por_hash = {(f["tipo"], f["source_hash"]): f for f in existentes if f["source_hash"]}
            por_uri = {f["uri"]: f for f in existentes}
            legacy_por_tipo: dict[str, list[dict[str, Any]]] = {}
            for existente in existentes:
                if not existente["source_hash"]:
                    legacy_por_tipo.setdefault(existente["tipo"], []).append(existente)
            # ``uri -> id`` de las filas vivas; se mantiene al día según se
            # planifican movimientos, para que dos referencias del mismo lote no
            # se peleen por la misma URI.
            duenio_de_uri = {f["uri"]: f["id"] for f in existentes}

            updates: list[tuple[Any, ...]] = []
            updates_revive: list[tuple[Any, ...]] = []
            inserts: list[tuple[Any, ...]] = []
            huerfanas: list[DocumentoReferencia] = []
            vistas_hash: set[tuple[str, str]] = set()
            vistas_uri: set[str] = set()
            # Filas ya reclamadas por una referencia de este lote: no pueden
            # volver a serlo como candidatas de la adopción por tipo único.
            filas_tocadas: set[int] = set()
            duplicadas_en_lote = 0

            def _planificar(fila: dict[str, Any], ref: DocumentoReferencia) -> None:
                """Encola el UPDATE de ``fila`` con los datos de ``ref``."""
                nueva_uri = ref.uri
                ocupante = duenio_de_uri.get(nueva_uri)
                if ocupante is not None and ocupante != fila["id"]:
                    # Otra fila de esta licitación ya usa esa URI (el mismo
                    # fichero referenciado desde dos bloques del CODICE).
                    # Moverla violaría UNIQUE(licitacion_id, uri): conservamos
                    # la que tiene y solo actualizamos el resto.
                    log.info(
                        "documentos_upsert_uri_ocupada",
                        licitacion_id=licitacion_id,
                        documento_id=fila["id"],
                        uri=nueva_uri,
                    )
                    nueva_uri = fila["uri"]

                cambio_uri = nueva_uri != fila["uri"]
                if cambio_uri:
                    duenio_de_uri.pop(fila["uri"], None)
                    duenio_de_uri[nueva_uri] = fila["id"]
                filas_tocadas.add(fila["id"])

                revive = (
                    cambio_uri
                    and fila["status"] == "error"
                    and (fila["error_detail"] or "").startswith("descarga fallida:")
                )
                destino = updates_revive if revive else updates
                # ``tipo`` se refresca junto al resto: la adopción por URI casa
                # solo por ``uri``, así que sin esto una fila clasificada como
                # 'legal' podría quedarse con el hash de un 'technical'. Es
                # seguro frente a ``uq_documentos_lic_tipo_hash`` porque solo se
                # llega aquí cuando ``(ref.tipo, ref.source_hash)`` no existía
                # entre las filas de la licitación.
                destino.append(
                    (ref.tipo, nueva_uri, ref.filename, ref.source_hash, ahora, fila["id"]),
                )

            # ── Pasada 1: refresco por hash y adopción por URI ──────────────
            for ref in refs:
                clave_hash = (ref.tipo, ref.source_hash) if ref.source_hash else None
                if clave_hash is not None and clave_hash in vistas_hash:
                    duplicadas_en_lote += 1  # el CODICE repitió la referencia
                    continue
                if ref.uri in vistas_uri:
                    duplicadas_en_lote += 1
                    continue
                if clave_hash is not None:
                    vistas_hash.add(clave_hash)
                vistas_uri.add(ref.uri)

                fila = por_hash.get(clave_hash) if clave_hash is not None else None
                if fila is None:
                    candidata = por_uri.get(ref.uri)
                    # Solo adoptamos si la fila no tenía identidad. Si ya tiene
                    # otra distinta, el contenido cambió bajo la misma URI
                    # estable: eso es un documento nuevo, no un refresco.
                    if candidata is not None and not candidata["source_hash"]:
                        fila = candidata
                    elif candidata is not None:
                        # Misma URI estable, hash distinto: el contenido cambió
                        # sin cambiar el enlace. No se toca (pisar el hash
                        # ataría la identidad nueva al texto ya extraído del
                        # contenido viejo) ni se inserta (violaría el UNIQUE).
                        log.info(
                            "documentos_upsert_hash_divergente",
                            licitacion_id=licitacion_id,
                            documento_id=candidata["id"],
                        )
                        continue

                if fila is not None:
                    _planificar(fila, ref)
                else:
                    huerfanas.append(ref)

            # ── Pasada 2: adopción por tipo único, o inserción ──────────────
            huerfanas_por_tipo: dict[str, list[DocumentoReferencia]] = {}
            for ref in huerfanas:
                huerfanas_por_tipo.setdefault(ref.tipo, []).append(ref)

            for tipo, refs_tipo in huerfanas_por_tipo.items():
                # Solo se adoptan filas sin contenido descargado. La adopción
                # por tipo único es una inferencia, no una prueba de identidad
                # como el hash: si la fila ya está ``extracted``, atarle una
                # identidad nueva dejaría el texto (y los chunks) del documento
                # ANTERIOR asociados al documento NUEVO, y de forma permanente
                # —la fila no volvería ni a ``list_pendientes`` (no está
                # 'pending') ni a ``list_extracted_without_chunks`` (ya tiene
                # chunks)—, así que el asistente citaría el pliego viejo
                # mientras la UI enlaza al nuevo. Excluyéndolas, la referencia
                # nueva cae a INSERT y se descarga como lo que es.
                candidatas = [
                    f
                    for f in legacy_por_tipo.get(tipo, [])
                    if f["id"] not in filas_tocadas and f["status"] in ("pending", "error")
                ]
                # Solo cuando el mapeo es 1↔1 e inequívoco. Con dos filas legacy
                # del mismo tipo (los 637 sobrantes que dejó la rotación antes
                # de v88) no hay forma de saber cuál corresponde: se insertan y
                # las viejas quedan relegadas por el orden de list_by_licitacion.
                if len(refs_tipo) == 1 and len(candidatas) == 1 and refs_tipo[0].source_hash:
                    _planificar(candidatas[0], refs_tipo[0])
                    continue
                inserts.extend(
                    (licitacion_id, r.tipo, r.uri, r.filename, r.source_hash) for r in refs_tipo
                )

            if updates:
                c.executemany(
                    "UPDATE documentos SET tipo = %s, uri = %s, "
                    "filename = COALESCE(%s, filename), "
                    "source_hash = COALESCE(%s, source_hash), updated_at = %s WHERE id = %s",
                    updates,
                )
            if updates_revive:
                c.executemany(
                    "UPDATE documentos SET tipo = %s, uri = %s, "
                    "filename = COALESCE(%s, filename), "
                    "source_hash = COALESCE(%s, source_hash), updated_at = %s, "
                    "status = 'pending', error_detail = NULL WHERE id = %s",
                    updates_revive,
                )
            if inserts:
                # ``ON CONFLICT DO NOTHING`` sin árbitro: así lo absorben tanto
                # el UNIQUE de la URI como el índice de identidad de v88 si dos
                # procesos ingieren la misma licitación a la vez.
                c.executemany(
                    "INSERT INTO documentos (licitacion_id, tipo, uri, filename, source_hash) "
                    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    inserts,
                )

        log.info(
            "documentos_upsert",
            licitacion_id=licitacion_id,
            referencias=len(refs),
            insertados=len(inserts),
            refrescados=len(updates),
            revividos=len(updates_revive),
            duplicadas_en_lote=duplicadas_en_lote,
        )
        return len(refs)

    def list_pendientes(self, limit: int = 100) -> list[dict[str, Any]]:
        """Documentos con ``status='pending'``, priorizados por relevancia.

        El backlog (~44k documentos referenciados, ~1k licitaciones
        tech-relevantes) se drena por lotes diarios pequeños frente al feed
        PLACSP diario, así que el orden decide qué se procesa primero:
        1. Licitaciones con ``tecnologia`` (keyword match en título) o
           ``ml_tecnologias`` (clasificador) no vacíos van primero -- son las
           que la categorización necesita antes de nada.
        2. Dentro de cada grupo, más recientes primero: los enlaces de PLACSP
           usan tokens rotativos que caducan (~82% de los antiguos), así que
           el backlog viejo tiene tasa de error de descarga alta y queda al
           final -- newest-first evita gastar el lote diario en URIs muertas.
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT d.id, d.licitacion_id, d.tipo, d.uri, d.filename, "
                "d.content_type, d.size_bytes "
                "FROM documentos d "
                "JOIN licitaciones l ON l.id_externo = d.licitacion_id "
                "WHERE d.status = 'pending' "
                "ORDER BY "
                "(l.tecnologia IS NOT NULL AND l.tecnologia != '') DESC, "
                "(l.ml_tecnologias IS NOT NULL AND l.ml_tecnologias != '') DESC, "
                "d.created_at DESC "
                "LIMIT %s",
                (max(1, min(int(limit), 1000)),),
            )
            return rows_to_dicts(cur)

    def list_by_licitacion(self, licitacion_id: str) -> list[dict[str, Any]]:
        """Metadatos de los documentos de una licitación, para mostrarlos en el
        detalle de la UI (bloque "Documentos") y para el contexto del asistente
        IA. Excluye ``texto`` (puede ser muy pesado y solo lo usa el pipeline
        RAG internamente).

        Orden: pliego administrativo → técnico → adicional (el mismo criterio
        documental que ya usan ``list_chunks_by_licitacion`` y
        ``list_textos_by_licitacion``) y, dentro de cada tipo, **el más reciente
        primero**. Ese ``DESC`` no es cosmético: los enlaces de PLACSP llevan
        token rotativo y hasta que ``upsert_meta`` supo refrescar por
        ``source_hash`` cada rotación insertaba una fila nueva, así que un
        ``created_at`` ascendente enseñaba primero la copia más vieja, que es
        justo la que ya ha caducado. ``id`` desempata las filas de un mismo
        lote, cuyo ``created_at`` es idéntico.
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT id, tipo, uri, filename, content_type, size_bytes, "
                "status, created_at FROM documentos WHERE licitacion_id = %s "
                "ORDER BY CASE tipo WHEN 'legal' THEN 0 WHEN 'technical' THEN 1 ELSE 2 END, "
                "created_at DESC, id",
                (licitacion_id,),
            )
            return rows_to_dicts(cur)

    def mark_downloaded(
        self,
        documento_id: int,
        *,
        filename: str | None,
        content_type: str | None,
        size_bytes: int | None,
        sha256: str | None,
    ) -> None:
        """Descarga completada — metadatos del binario, texto aún pendiente."""
        with connect() as c:
            c.execute(
                "UPDATE documentos SET status = 'downloaded', filename = %s, "
                "content_type = %s, size_bytes = %s, sha256 = %s, fetched_at = %s, "
                "updated_at = %s WHERE id = %s",
                (
                    filename,
                    content_type,
                    size_bytes,
                    sha256,
                    now_utc_iso(),
                    now_utc_iso(),
                    documento_id,
                ),
            )

    def mark_extracted(
        self,
        documento_id: int,
        *,
        texto: str,
        sha256: str,
        pages: list[str] | None = None,
    ) -> None:
        """Texto extraído con éxito. ``sha256`` es del binario descargado —
        usado por el job de embeddings (F8) para saber si el contenido cambió
        entre corridas (skip si el hash no varió, delete+reinsert si sí).

        Cuando ``pages`` está presente, persiste texto por página y offsets
        absolutos sobre ``texto`` en la misma transacción. Reintentar reemplaza
        el conjunto completo y no duplica evidencia.
        """
        with connect() as c:
            c.execute(
                "UPDATE documentos SET status = 'extracted', texto = %s, sha256 = %s, "
                "fetched_at = %s, updated_at = %s WHERE id = %s",
                (texto, sha256, now_utc_iso(), now_utc_iso(), documento_id),
            )
            if pages is not None:
                c.execute(
                    "DELETE FROM documento_pages WHERE documento_id = %s",
                    (documento_id,),
                )
                page_rows: list[tuple[int, int, str, int, int]] = []
                offset = 0
                for page_number, page_text in enumerate(pages, start=1):
                    start_offset = offset
                    end_offset = start_offset + len(page_text)
                    page_rows.append(
                        (
                            documento_id,
                            page_number,
                            page_text,
                            start_offset,
                            end_offset,
                        )
                    )
                    offset = end_offset + 1  # separador ``\n`` del texto agregado
                if page_rows:
                    c.executemany(
                        "INSERT INTO documento_pages "
                        "(documento_id, page_number, texto, start_offset, end_offset) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        page_rows,
                    )

    def list_pages(self, documento_id: int) -> list[dict[str, Any]]:
        """Páginas extraídas y offsets, en orden documental."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT documento_id, page_number, texto, start_offset, end_offset "
                "FROM documento_pages WHERE documento_id = %s ORDER BY page_number",
                (documento_id,),
            )
            return rows_to_dicts(cur)

    def list_pages_by_licitacion(self, licitacion_id: str) -> list[dict[str, Any]]:
        """Páginas de todos los pliegos de una licitación, con metadatos de cita."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT dp.documento_id, dp.page_number, dp.texto, "
                "dp.start_offset, dp.end_offset, d.tipo, d.filename, d.uri "
                "FROM documento_pages dp "
                "JOIN documentos d ON d.id = dp.documento_id "
                "WHERE d.licitacion_id = %s "
                "ORDER BY d.id, dp.page_number",
                (licitacion_id,),
            )
            return rows_to_dicts(cur)

    def mark_error(self, documento_id: int, *, error_detail: str) -> None:
        """Descarga o extracción fallida — no rompe el resto del batch."""
        with connect() as c:
            c.execute(
                "UPDATE documentos SET status = 'error', error_detail = %s, "
                "updated_at = %s WHERE id = %s",
                (error_detail[:_MAX_ERROR_DETAIL_LEN], now_utc_iso(), documento_id),
            )

    def get(self, documento_id: int) -> dict[str, Any] | None:
        """Fila completa por id (incluye ``texto``) — usado por el job de embeddings."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT id, licitacion_id, tipo, uri, filename, content_type, "
                "size_bytes, sha256, source_hash, texto, status, error_detail, storage_key, "
                "fetched_at, created_at, updated_at FROM documentos WHERE id = %s",
                (documento_id,),
            )
            rows = rows_to_dicts(cur)
            return rows[0] if rows else None

    # ── documento_chunks (F8: chunking + embeddings) ────────────────────

    def list_extracted_without_chunks(self, limit: int = 50) -> list[dict[str, Any]]:
        """Documentos con texto extraído que aún no tienen chunks generados.

        Selección deliberadamente simple ("sin chunks" = candidato): en el
        pipeline actual (F6/F7) un documento pasa por ``extracted`` una sola
        vez — no hay camino de re-extracción que cambie ``texto`` después.
        Por eso la idempotencia entre corridas la da esta misma condición
        (`NOT EXISTS`): un documento ya chunkeado nunca vuelve a aparecer
        aquí, así que el job nunca reprocesa trabajo ya hecho.
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT id, licitacion_id, texto FROM documentos "
                "WHERE status = 'extracted' "
                "AND id NOT IN (SELECT DISTINCT documento_id FROM documento_chunks) "
                "ORDER BY updated_at LIMIT %s",
                (max(1, min(int(limit), 1000)),),
            )
            return rows_to_dicts(cur)

    def replace_chunks(self, documento_id: int, chunks: list[str], embeddings: Any) -> int:
        """Reemplaza (delete+insert) los chunks+embeddings de un documento.

        ``embeddings`` es indexable fila a fila (``np.ndarray`` de shape
        (n, dim) o lista de vectores), alineado 1:1 con ``chunks``.

        Transaccional dentro de una sola conexión: el DELETE corre primero,
        así que un fallo a mitad de los INSERTs no deja un estado "medio
        chunkeado" que pase el filtro `NOT EXISTS` de
        ``list_extracted_without_chunks`` — la siguiente corrida reintenta el
        documento completo desde cero (delete+reinsert es idempotente frente
        a reintentos, cumple el mismo contrato que pedía comparar por sha256
        sin necesitar una columna nueva en el schema).
        """
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks ({len(chunks)}) y embeddings ({len(embeddings)}) "
                "deben tener la misma longitud"
            )

        with connect() as c:
            c.execute("DELETE FROM documento_chunks WHERE documento_id = %s", (documento_id,))
            if not chunks:
                return 0
            rows = [
                (documento_id, i, texto, _to_pg_vector_literal(emb))
                for i, (texto, emb) in enumerate(zip(chunks, embeddings, strict=True))
            ]
            c.executemany(
                "INSERT INTO documento_chunks (documento_id, chunk_index, texto, embedding) "
                "VALUES (%s, %s, %s, %s::vector)",
                rows,
            )
        return len(chunks)

    # ── Lectura para el contexto LLM (resumen IA + chat contextualizado) ─
    # ``list_by_licitacion`` (más arriba) sirve tanto al bloque Documentos de
    # la UI como al contexto del asistente IA.

    def list_chunks_by_licitacion(
        self, licitacion_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Chunks de pliego de una licitación en orden documental.

        Orden: legal → technical → additional, y dentro de cada documento por
        ``chunk_index``. El ranking semántico frente a una pregunta se hace en
        Python (``services/rag/context.py``) — aquí no se consulta el embedding
        persistido, así que el mismo SQL sirve en Postgres y SQLite.
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT dc.documento_id, d.tipo, d.filename, dc.chunk_index, dc.texto "
                "FROM documento_chunks dc JOIN documentos d ON d.id = dc.documento_id "
                "WHERE d.licitacion_id = %s "
                "ORDER BY CASE d.tipo WHEN 'legal' THEN 0 WHEN 'technical' THEN 1 ELSE 2 END, "
                "dc.documento_id, dc.chunk_index LIMIT %s",
                (licitacion_id, max(1, min(int(limit), 1000))),
            )
            return rows_to_dicts(cur)

    def list_textos_by_licitacion(
        self, licitacion_id: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Texto completo de los documentos ya extraídos de una licitación.

        Fallback para licitaciones cuyo texto está extraído pero el job de
        chunking aún no corrió (``documento_chunks`` vacío).
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT id, tipo, filename, texto FROM documentos "
                "WHERE licitacion_id = %s AND status = 'extracted' AND texto IS NOT NULL "
                "ORDER BY CASE tipo WHEN 'legal' THEN 0 WHEN 'technical' THEN 1 ELSE 2 END, id "
                "LIMIT %s",
                (licitacion_id, max(1, min(int(limit), 100))),
            )
            return rows_to_dicts(cur)

    def count_chunks(self, documento_id: int) -> int:
        with connect_read() as c:
            row = c.execute(
                "SELECT COUNT(*) FROM documento_chunks WHERE documento_id = %s",
                (documento_id,),
            ).fetchone()
            return int(row[0] if row else 0)

    def count_all(self) -> int:
        """Total de filas en ``documentos`` -- usado por scripts de backfill para
        reportar progreso (antes/después)."""
        with connect_read() as c:
            row = c.execute("SELECT COUNT(*) FROM documentos").fetchone()
            return int(row[0] if row else 0)

    def status_counts(self) -> dict[str, int]:
        """Recuento de ``documentos`` por ``status`` + total de chunks.

        Usado por el reporting del job de embeddings (antes vivía como SQL
        inline en un heredoc de ``pliegos.yml``). Devuelve siempre las claves
        conocidas del ciclo de vida, con 0 cuando no hay filas, para que el
        formato del informe no dependa de los datos.
        """
        counts = {"total": 0, "pending": 0, "downloaded": 0, "extracted": 0, "error": 0}
        with connect_read() as c:
            cur = c.execute("SELECT status, COUNT(*) FROM documentos GROUP BY status")
            for status, n in cur.fetchall():
                counts[str(status)] = int(n)
                counts["total"] += int(n)
            row = c.execute("SELECT COUNT(*) FROM documento_chunks").fetchone()
            counts["chunks"] = int(row[0] if row else 0)
        return counts
