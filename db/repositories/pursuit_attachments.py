"""Adjuntos propios de una oportunidad (C6.3, v127) y su texto indexado (v179).

TID251: el SQL de `pursuit_attachments` y de `pursuit_attachment_chunks` vive
solo aquí. Los bytes no pasan por este módulo — los guarda
`shared/object_store.py` y aquí solo viaja la clave.

Toda consulta lleva `organization_id` en el `WHERE`, no como comodidad sino como
frontera: un adjunto es la propuesta que el equipo va a presentar, y es el dato
más sensible que guarda el producto.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

from db.audit import registrar_evento
from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts, typed_rows
from db.repositories.documentos import _texto_para_postgres, _to_pg_vector_literal
from observability.logging import get_logger
from shared.audit_events import PURSUIT_ATTACHMENT_INDEXING_CHANGED

if TYPE_CHECKING:
    from db.connection import _PgConnAdapter

log = get_logger(__name__)

_SELECT = (
    "SELECT a.id, a.pursuit_id, a.organization_id, a.blob_key, a.filename, "
    "a.content_type, a.size_bytes, a.sha256, a.uploaded_by_user_id, "
    "u.display_name AS uploaded_by_name, a.indexable, a.index_status, a.index_error, "
    "a.created_at "
    "FROM pursuit_attachments a "
    "LEFT JOIN users u ON u.id = a.uploaded_by_user_id "
)

#: De dónde sale un fragmento citable (v179, ADR-040). La organización se exige
#: **dos veces** —en el fragmento y en el adjunto— y el adjunto tiene que seguir
#: vivo y con el permiso puesto: aunque un borrado de fragmentos fallara a
#: medias, lo que ya no es indexable no se recupera. La oportunidad de origen
#: viaja con la fila porque la cita se rotula con ella.
_DESDE_FRAGMENTOS = (
    "FROM pursuit_attachment_chunks c "
    "JOIN pursuit_attachments a "
    "  ON a.id = c.attachment_id AND a.organization_id = c.organization_id "
    "JOIN pursuits p ON p.id = a.pursuit_id AND p.organization_id = a.organization_id "
    "LEFT JOIN licitaciones l ON l.id_externo = p.licitacion_id "
)
#: A esto cada consulta le añade, a la vista, ``a.deleted_at IS NULL``
#: (``tests/test_pursuit_borrado_logico.py`` lo busca en cada ``execute``).
_SOLO_INDEXABLES = "WHERE c.organization_id = %s AND a.organization_id = %s AND a.indexable "

_COLUMNAS_DE_CITA = (
    "c.attachment_id, c.chunk_index, c.page_number, c.texto, a.filename, a.pursuit_id, "
    "p.licitacion_id, l.titulo AS licitacion_titulo"
)


class FragmentoEncontrado(TypedDict):
    """Un fragmento citable de un adjunto, con de dónde sale."""

    attachment_id: int
    chunk_index: int
    page_number: int | None
    texto: str
    filename: str
    pursuit_id: int
    licitacion_id: str
    licitacion_titulo: str | None
    #: Similitud coseno (por significado) o ``ts_rank_cd`` (por palabras).
    score: float
    #: Solo en la búsqueda por palabras; ``0`` y ``None`` en la otra.
    n_terminos: int
    cobertura: int
    extracto: str | None


class _FilaDeFragmento(TypedDict):
    """La fila de las dos búsquedas tal como la devuelve psycopg.

    Las claves son los alias de ``_COLUMNAS_DE_CITA`` más ``score``; las tres
    últimas solo las trae la búsqueda por palabras.
    """

    attachment_id: int
    chunk_index: int
    page_number: int | None
    texto: str
    filename: str
    pursuit_id: int
    licitacion_id: str
    licitacion_titulo: str | None
    score: float | None
    n_terminos: NotRequired[int]
    cobertura: NotRequired[int]
    extracto: NotRequired[str | None]


def _a_fragmentos(filas: list[_FilaDeFragmento]) -> list[FragmentoEncontrado]:
    return [
        FragmentoEncontrado(
            attachment_id=int(f["attachment_id"]),
            chunk_index=int(f["chunk_index"]),
            page_number=None if f["page_number"] is None else int(f["page_number"]),
            texto=str(f["texto"]),
            filename=str(f["filename"]),
            pursuit_id=int(f["pursuit_id"]),
            licitacion_id=str(f["licitacion_id"]),
            licitacion_titulo=(
                None if f["licitacion_titulo"] is None else str(f["licitacion_titulo"])
            ),
            score=float(f["score"] or 0.0),
            n_terminos=int(f.get("n_terminos") or 0),
            cobertura=int(f.get("cobertura") or 0),
            extracto=None if f.get("extracto") is None else str(f["extracto"]),
        )
        for f in filas
    ]


#: Estados en los que un adjunto indexable se queda **sin** texto indexado.
ESTADOS_SIN_TEXTO: frozenset[str] = frozenset({"error", "unsupported", "sin_texto"})

#: Trozo literal del fragmento alrededor de lo que casa, sin marcas de resaltado.
_OPCIONES_EXTRACTO = 'MaxFragments=1, MaxWords=40, MinWords=15, StartSel="", StopSel=""'


class PursuitAttachmentExists(Exception):
    """Ese fichero ya está en esa oportunidad (misma huella)."""


class PursuitAttachmentsRepository:
    """Acceso a ``pursuit_attachments``."""

    def create(
        self,
        *,
        pursuit_id: int,
        organization_id: int,
        blob_key: str,
        filename: str,
        content_type: str,
        size_bytes: int,
        sha256: str,
        uploaded_by_user_id: int | None,
    ) -> dict[str, Any] | None:
        """Registra un adjunto en una oportunidad **de esa organización**.

        Devuelve ``None`` si el pursuit no es de la organización. Igual que en
        `pursuit_tasks`, la comprobación va dentro del `INSERT ... SELECT` para
        que no exista ventana entre comprobar y escribir.

        Lanza :class:`PursuitAttachmentExists` si la clave ya estaba: como la
        clave incorpora la huella del contenido, eso significa exactamente «ese
        mismo fichero ya está subido aquí».
        """
        ahora = now_utc_iso()
        with connect() as c:
            cur = c.execute(
                "INSERT INTO pursuit_attachments "
                "(pursuit_id, organization_id, blob_key, filename, content_type, "
                " size_bytes, sha256, uploaded_by_user_id, indexable, created_at) "
                "SELECT p.id, p.organization_id, %s, %s, %s, %s, %s, %s, false, %s "
                "FROM pursuits p WHERE p.id = %s AND p.organization_id = %s "
                # `DO UPDATE` y no `DO NOTHING` desde v131: `blob_key` lleva la
                # huella del contenido y es UNIQUE, así que tras un borrado
                # lógico la fila sigue ocupando la clave. Con `DO NOTHING`, ese
                # fichero no se podría volver a subir **nunca** — y el usuario
                # vería un 409 sin nada a la vista que lo explique. El `WHERE`
                # acota la resurrección a las filas borradas: si el adjunto está
                # vivo, sigue siendo el 409 de siempre.
                "ON CONFLICT (blob_key) DO UPDATE SET "
                " deleted_at = NULL, filename = EXCLUDED.filename, "
                " uploaded_by_user_id = EXCLUDED.uploaded_by_user_id, "
                " created_at = EXCLUDED.created_at "
                "WHERE pursuit_attachments.deleted_at IS NOT NULL "
                "RETURNING id",
                (
                    blob_key,
                    filename,
                    content_type,
                    size_bytes,
                    sha256,
                    uploaded_by_user_id,
                    ahora,
                    pursuit_id,
                    organization_id,
                ),
            )
            fila = cur.fetchone()
            if fila is None:
                # Dos causas posibles y hay que distinguirlas: el pursuit no es
                # de esta organización (404 para quien pregunta) o la clave ya
                # existía (409). Sin esta consulta, un reintento legítimo se
                # leería como «no existe».
                ya = c.execute(
                    "SELECT 1 FROM pursuit_attachments WHERE blob_key = %s AND deleted_at IS NULL",
                    (blob_key,),
                ).fetchone()
                if ya is not None:
                    raise PursuitAttachmentExists(blob_key)
                return None
            nuevo_id = int(fila[0] if not isinstance(fila, dict) else fila["id"])
        return self.get(nuevo_id, organization_id=organization_id)

    def get(self, attachment_id: int, *, organization_id: int) -> dict[str, Any] | None:
        """Un adjunto por id, acotado a su organización."""
        with connect_read() as c:
            filas = rows_to_dicts(
                c.execute(
                    _SELECT + "WHERE a.id = %s AND a.organization_id = %s AND a.deleted_at IS NULL",
                    (attachment_id, organization_id),
                )
            )
        return filas[0] if filas else None

    def list_for_pursuit(
        self, pursuit_id: int, *, organization_id: int, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Adjuntos de una oportunidad, recientes primero."""
        with connect_read() as c:
            return rows_to_dicts(
                c.execute(
                    _SELECT + "WHERE a.pursuit_id = %s AND a.organization_id = %s "
                    "AND a.deleted_at IS NULL ORDER BY a.id DESC LIMIT %s",
                    (pursuit_id, organization_id, limit),
                )
            )

    def delete(
        self, attachment_id: int, *, organization_id: int, actor_user_id: int | None = None
    ) -> str | None:
        """Marca el adjunto como borrado (v131). Devuelve su ``blob_key``, o ``None``.

        **El objeto del almacén no se toca, y eso es la mitad del cambio.** Antes
        esto borraba la fila y devolvía la clave para que el servicio borrara
        después el binario; con borrado lógico, borrar el binario haría
        irreversible justo lo que la revisión viene a hacer reversible — la fila
        seguiría ahí, apuntando a un objeto que ya no está, y restaurarla daría
        una descarga rota.

        La clave se sigue devolviendo porque es lo que distingue «se borró» de
        «no existía o no era tuyo», que es lo que el servicio necesita saber
        para devolver 204 o 404. Quien limpia el almacén es el barrido de
        huérfanos, cuando exista; hasta entonces el objeto se conserva, y eso es
        un coste de almacenamiento consciente.

        Lo que **no** se conserva es su texto indexado (v179): se borra aquí, y
        si el adjunto era indexable el rastro lo dice en la misma transacción.
        """
        with connect() as c:
            previo = _bloquear_vivo(c, attachment_id, organization_id)
            if previo is None:
                return None
            era_indexable, pursuit_id, blob_key = previo
            # Retirar el adjunto retira también el permiso y el estado: si el
            # mismo fichero vuelve a subirse, la fila resucita sin él.
            c.execute(
                "UPDATE pursuit_attachments SET deleted_at = now(), indexable = false, "
                "index_status = NULL, index_error = NULL, index_embedding_version = NULL "
                "WHERE id = %s AND organization_id = %s AND deleted_at IS NULL",
                (attachment_id, organization_id),
            )
            _borrar_fragmentos(c, attachment_id, organization_id)
            if era_indexable:
                _registrar_permiso(
                    c,
                    organization_id,
                    attachment_id,
                    pursuit_id,
                    actor_user_id=actor_user_id,
                    indexable=False,
                    motivo="adjunto_retirado",
                )
        return blob_key

    def set_indexable(
        self,
        attachment_id: int,
        *,
        organization_id: int,
        indexable: bool,
        actor_user_id: int | None = None,
        motivo: str = "permiso",
    ) -> dict[str, Any] | None:
        """Levanta o baja el opt-in de indexación del RAG para UN adjunto.

        Levantarlo deja el adjunto ``pending`` (lo indexa la cola); repetirlo
        sobre uno ya indexable no toca su estado, para que un doble clic no
        vuelva a encolar. Bajarlo borra **en la misma transacción** sus
        fragmentos y sus embeddings: no hay instante en que el permiso esté
        retirado y el texto siga ahí.

        Cuando el valor cambia, el evento de auditoría se escribe también en
        esa transacción (ADR-039 §3): no hay cambio de permiso sin rastro, y si
        el rastro no se puede escribir el permiso no cambia.
        """
        with connect() as c:
            previo = _bloquear_vivo(c, attachment_id, organization_id)
            if previo is None:
                return None
            era_indexable, pursuit_id, _blob_key = previo
            if indexable:
                c.execute(
                    "UPDATE pursuit_attachments SET "
                    "index_status = CASE WHEN indexable THEN index_status ELSE 'pending' END, "
                    "index_error = CASE WHEN indexable THEN index_error ELSE NULL END, "
                    "indexable = true "
                    "WHERE id = %s AND organization_id = %s AND deleted_at IS NULL",
                    (attachment_id, organization_id),
                )
            else:
                c.execute(
                    "UPDATE pursuit_attachments SET indexable = false, index_status = NULL, "
                    "index_error = NULL, index_embedding_version = NULL "
                    "WHERE id = %s AND organization_id = %s AND deleted_at IS NULL",
                    (attachment_id, organization_id),
                )
                _borrar_fragmentos(c, attachment_id, organization_id)
            if era_indexable != indexable:
                _registrar_permiso(
                    c,
                    organization_id,
                    attachment_id,
                    pursuit_id,
                    actor_user_id=actor_user_id,
                    indexable=indexable,
                    motivo=motivo,
                )
        return self.get(attachment_id, organization_id=organization_id)

    # ── Texto indexado (v179, ADR-040) ──────────────────────────────────────

    def contar_indexables(self, organization_id: int) -> int:
        """Adjuntos vivos con el permiso puesto: lo que cuenta contra el tope."""
        with connect_read() as c:
            fila = c.execute(
                "SELECT COUNT(*) AS n FROM pursuit_attachments "
                "WHERE organization_id = %s AND indexable AND deleted_at IS NULL",
                (organization_id,),
            ).fetchone()
        if fila is None:
            return 0
        return int(fila["n"] if isinstance(fila, dict) else fila[0])

    def reemplazar_fragmentos(
        self,
        attachment_id: int,
        *,
        organization_id: int,
        fragmentos: Sequence[str],
        paginas: Sequence[int | None],
        embeddings: Sequence[Sequence[float]] | None = None,
        embedding_model: str | None = None,
        embedding_version: str | None = None,
    ) -> int | None:
        """Sustituye los fragmentos del adjunto y lo deja ``indexed``.

        ``None`` si el adjunto ya no es indexable (o no es de la organización):
        la fila se bloquea con ``FOR UPDATE`` antes de escribir, así que retirar
        el permiso mientras el job trabaja no puede dejar texto detrás — o el
        job llega antes y ``set_indexable`` lo borra, o llega después y no
        escribe nada.

        Borrar e insertar en una transacción hace el job reintentable: un
        segundo intento no duplica ni deja el adjunto a medias. ``embeddings``
        va alineado con ``fragmentos``, o es ``None`` cuando el proceso no tiene
        motor para un documento entero; entonces los rellena
        :meth:`guardar_embeddings`.
        """
        if len(paginas) != len(fragmentos):
            raise ValueError("paginas y fragmentos deben tener la misma longitud")
        if embeddings is not None and len(embeddings) != len(fragmentos):
            raise ValueError("embeddings y fragmentos deben tener la misma longitud")
        filas = [
            (
                attachment_id,
                organization_id,
                i,
                paginas[i],
                _texto_para_postgres(texto),
                None if embeddings is None else _to_pg_vector_literal(embeddings[i]),
                None if embeddings is None else embedding_model,
                None if embeddings is None else embedding_version,
            )
            for i, texto in enumerate(fragmentos)
        ]
        with connect() as c:
            if not _bloquear_indexable(c, attachment_id, organization_id):
                return None
            _borrar_fragmentos(c, attachment_id, organization_id)
            if filas:
                c.executemany(
                    "INSERT INTO pursuit_attachment_chunks "
                    "(attachment_id, organization_id, chunk_index, page_number, texto, "
                    " embedding, embedding_model, embedding_version) "
                    "VALUES (%s, %s, %s, %s, %s, %s::vector, %s, %s)",
                    filas,
                )
            c.execute(
                "UPDATE pursuit_attachments SET index_status = 'indexed', index_error = NULL, "
                "index_embedding_version = %s "
                "WHERE id = %s AND organization_id = %s AND deleted_at IS NULL",
                (
                    None if embeddings is None else embedding_version,
                    attachment_id,
                    organization_id,
                ),
            )
        return len(filas)

    def marcar_sin_texto(
        self, attachment_id: int, *, organization_id: int, estado: str, error: str
    ) -> bool:
        """Deja el adjunto en ``estado`` (de :data:`ESTADOS_SIN_TEXTO`) y sin fragmentos.

        ``False`` si ya no es indexable. El motivo se guarda recortado: es lo
        que la pantalla enseña, no un volcado.
        """
        if estado not in ESTADOS_SIN_TEXTO:
            raise ValueError(f"estado de indexado no válido: {estado!r}")
        with connect() as c:
            if not _bloquear_indexable(c, attachment_id, organization_id):
                return False
            _borrar_fragmentos(c, attachment_id, organization_id)
            c.execute(
                "UPDATE pursuit_attachments SET index_status = %s, index_error = %s, "
                "index_embedding_version = NULL "
                "WHERE id = %s AND organization_id = %s AND deleted_at IS NULL",
                (estado, error[:500], attachment_id, organization_id),
            )
        return True

    def pendientes_de_embedding(
        self, embedding_version: str, *, limit: int
    ) -> list[dict[str, int]]:
        """``[{id, organization_id}]`` de adjuntos indexados sin vectores vigentes.

        Es la única lectura transversal de este módulo y por eso no devuelve
        más que identificadores: quien rellena los embeddings entra después
        organización a organización, con su ámbito puesto.
        """
        with connect_read() as c:
            filas = rows_to_dicts(
                c.execute(
                    "SELECT id, organization_id FROM pursuit_attachments "
                    "WHERE indexable AND deleted_at IS NULL AND index_status = 'indexed' "
                    "AND index_embedding_version IS DISTINCT FROM %s ORDER BY id LIMIT %s",
                    (embedding_version, limit),
                )
            )
        return [{"id": int(f["id"]), "organization_id": int(f["organization_id"])} for f in filas]

    def textos_de_fragmentos(
        self, attachment_id: int, *, organization_id: int
    ) -> list[tuple[int, str]]:
        """``[(chunk_index, texto)]`` de un adjunto, en orden."""
        with connect_read() as c:
            filas = rows_to_dicts(
                c.execute(
                    "SELECT chunk_index, texto FROM pursuit_attachment_chunks "
                    "WHERE attachment_id = %s AND organization_id = %s ORDER BY chunk_index",
                    (attachment_id, organization_id),
                )
            )
        return [(int(f["chunk_index"]), str(f["texto"])) for f in filas]

    def guardar_embeddings(
        self,
        attachment_id: int,
        *,
        organization_id: int,
        indices: Sequence[int],
        embeddings: Sequence[Sequence[float]],
        embedding_model: str,
        embedding_version: str,
    ) -> bool:
        """Rellena los vectores de fragmentos ya guardados. ``False`` sin permiso.

        ``embeddings`` va alineado con ``indices``.
        """
        if len(indices) != len(embeddings):
            raise ValueError("indices y embeddings deben tener la misma longitud")
        with connect() as c:
            if not _bloquear_indexable(c, attachment_id, organization_id):
                return False
            if indices:
                c.executemany(
                    "UPDATE pursuit_attachment_chunks SET embedding = %s::vector, "
                    "embedding_model = %s, embedding_version = %s "
                    "WHERE attachment_id = %s AND organization_id = %s AND chunk_index = %s",
                    [
                        (
                            _to_pg_vector_literal(embeddings[n]),
                            embedding_model,
                            embedding_version,
                            attachment_id,
                            organization_id,
                            indice,
                        )
                        for n, indice in enumerate(indices)
                    ],
                )
            c.execute(
                "UPDATE pursuit_attachments SET index_embedding_version = %s "
                "WHERE id = %s AND organization_id = %s AND deleted_at IS NULL",
                (embedding_version, attachment_id, organization_id),
            )
        return True

    def buscar_por_palabras(
        self, organization_id: int, terminos: Sequence[str], *, limit: int = 12
    ) -> list[FragmentoEncontrado]:
        """Fragmentos de la organización que casan con alguno de ``terminos``.

        Cada término pasa por el diccionario español en la consulta
        (``plainto_tsquery``, la misma construcción que
        ``db/repositories/investigador.py``): las palabras vacías desaparecen y
        ``n_terminos`` cuenta las que quedan. ``cobertura`` dice cuántas casan
        en el fragmento; quién es relevante lo decide el servicio.
        ``extracto`` es un trozo **literal** del fragmento alrededor de lo que
        casa (``ts_headline`` sin marcas), calculado solo para lo que se devuelve.
        """
        if not terminos:
            return []
        sql = (
            "WITH terminos AS MATERIALIZED ("
            "  SELECT DISTINCT plainto_tsquery('spanish', u.t)::text AS lex "
            "  FROM unnest(%s::text[]) AS u(t) "
            "  WHERE numnode(plainto_tsquery('spanish', u.t)) > 0"
            "), consulta AS MATERIALIZED ("
            "  SELECT string_agg('(' || lex || ')', ' | ')::tsquery AS q, count(*) AS n "
            "  FROM terminos"
            "), casan AS ("
            f"  SELECT {_COLUMNAS_DE_CITA}, k.q, k.n AS n_terminos, "
            "         (SELECT count(*) FROM terminos t "
            "          WHERE c.search_vector @@ t.lex::tsquery) AS cobertura, "
            "         ts_rank_cd(c.search_vector, k.q) AS score "
            f"  {_DESDE_FRAGMENTOS} CROSS JOIN consulta k {_SOLO_INDEXABLES}"
            "  AND a.deleted_at IS NULL AND c.search_vector @@ k.q "
            "  ORDER BY cobertura DESC, score DESC, c.attachment_id, c.chunk_index "
            "  LIMIT %s"
            ") "
            "SELECT attachment_id, chunk_index, page_number, texto, filename, pursuit_id, "
            "       licitacion_id, licitacion_titulo, n_terminos, cobertura, score, "
            "       ts_headline('spanish', texto, q, %s) AS extracto "
            "FROM casan ORDER BY cobertura DESC, score DESC, attachment_id, chunk_index"
        )
        with connect_read() as c:
            filas = rows_to_dicts(
                c.execute(
                    sql,
                    (list(terminos), organization_id, organization_id, limit, _OPCIONES_EXTRACTO),
                )
            )
        return _a_fragmentos(typed_rows(_FilaDeFragmento, filas))

    def buscar_por_significado(
        self,
        organization_id: int,
        embedding: Sequence[float],
        *,
        embedding_version: str,
        limit: int = 12,
    ) -> list[FragmentoEncontrado]:
        """Fragmentos de la organización por cercanía coseno a ``embedding``.

        Orden exacto, sin índice aproximado: la búsqueda va acotada a una
        organización y un HNSW global filtraría después de elegir vecinos entre
        todas (ver la cabecera de ``v179``). Solo compara vectores de
        ``embedding_version``: dos modelos no comparten geometría.
        """
        vec = _to_pg_vector_literal(embedding)
        with connect_read() as c:
            filas = rows_to_dicts(
                c.execute(
                    f"SELECT {_COLUMNAS_DE_CITA}, 1 - (c.embedding <=> %s::vector) AS score "
                    f"{_DESDE_FRAGMENTOS}{_SOLO_INDEXABLES}"
                    "AND a.deleted_at IS NULL "
                    "AND c.embedding IS NOT NULL AND c.embedding_version = %s "
                    "ORDER BY c.embedding <=> %s::vector LIMIT %s",
                    (vec, organization_id, organization_id, embedding_version, vec, limit),
                )
            )
        return _a_fragmentos(typed_rows(_FilaDeFragmento, filas))

    def keys_de_organizacion(self, organization_id: int) -> list[str]:
        """Todas las claves de una organización, para purgarlas al borrarla.

        ADR-030 §D: borrar una organización borra su dato corporativo, y un
        adjunto lo es. El `ON DELETE CASCADE` se lleva las filas; los objetos
        del almacén hay que enumerarlos **antes** para poder borrarlos después.
        """
        with connect_read() as c:
            filas = c.execute(
                "SELECT blob_key FROM pursuit_attachments WHERE organization_id = %s",
                (organization_id,),
            ).fetchall()
        return [str(f[0] if not isinstance(f, dict) else f["blob_key"]) for f in filas]

    def ocupacion(self, organization_id: int) -> dict[str, int]:
        """``{n, bytes}`` de lo que ocupa una organización.

        Es lo que permite poner un tope por cliente sin listar el bucket, que
        en S3 es una operación paginada y cara.
        """
        with connect_read() as c:
            fila = c.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS bytes "
                "FROM pursuit_attachments WHERE organization_id = %s",
                (organization_id,),
            ).fetchone()
        if fila is None:
            return {"n": 0, "bytes": 0}
        if isinstance(fila, dict):
            return {"n": int(fila["n"]), "bytes": int(fila["bytes"])}
        return {"n": int(fila[0]), "bytes": int(fila[1])}


def _borrar_fragmentos(c: _PgConnAdapter, attachment_id: int, organization_id: int) -> None:
    """Borra el texto indexado de un adjunto, en la transacción de quien llama."""
    c.execute(
        "DELETE FROM pursuit_attachment_chunks WHERE attachment_id = %s AND organization_id = %s",
        (attachment_id, organization_id),
    )


def _bloquear_vivo(
    c: _PgConnAdapter, attachment_id: int, organization_id: int
) -> tuple[bool, int, str] | None:
    """Bloquea la fila de un adjunto vivo: ``(indexable, pursuit_id, blob_key)``."""
    fila = c.execute(
        "SELECT indexable, pursuit_id, blob_key FROM pursuit_attachments "
        "WHERE id = %s AND organization_id = %s AND deleted_at IS NULL FOR UPDATE",
        (attachment_id, organization_id),
    ).fetchone()
    if fila is None:
        return None
    if isinstance(fila, dict):
        return bool(fila["indexable"]), int(fila["pursuit_id"]), str(fila["blob_key"])
    return bool(fila[0]), int(fila[1]), str(fila[2])


def _registrar_permiso(
    c: _PgConnAdapter,
    organization_id: int,
    attachment_id: int,
    pursuit_id: int,
    *,
    actor_user_id: int | None,
    indexable: bool,
    motivo: str,
) -> None:
    """El cambio de permiso, en el rastro de la organización (CU-32). Con ids, sin nombres."""
    registrar_evento(
        c,
        event_type=PURSUIT_ATTACHMENT_INDEXING_CHANGED,
        user_id=actor_user_id,
        resource=f"org:{organization_id}",
        detail={
            "attachment_id": attachment_id,
            "pursuit_id": pursuit_id,
            "indexable": indexable,
            "motivo": motivo,
        },
    )


def _bloquear_indexable(c: _PgConnAdapter, attachment_id: int, organization_id: int) -> bool:
    """Bloquea la fila del adjunto si sigue vivo, es de la organización e indexable."""
    fila = c.execute(
        "SELECT 1 FROM pursuit_attachments "
        "WHERE id = %s AND organization_id = %s AND indexable AND deleted_at IS NULL "
        "FOR UPDATE",
        (attachment_id, organization_id),
    ).fetchone()
    return fila is not None
