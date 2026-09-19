"""Repository para watchlist y pending_digests."""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

_WATCHLIST_LIC_COLS = (
    "id_externo, titulo, descripcion, organo_contratacion, "
    "cpv, importe, ccaa, estado, fecha_publicacion, url"
)

# ── Identidad dual (ADR-030 fase 2, v129) ────────────────────────────────────
#
# Cada tabla de usuario lleva ``user_id`` (la identidad interna) junto a
# ``user_key`` (la clave derivada del correo, en retirada). El predicado se
# escribe UNA vez y recibe siempre la misma terna ``(user_id, user_key,
# user_id)``:
#
# * con ``user_id`` conocido: la fila es del usuario si lleva su id, o si
#   —sin id todavía, porque el backfill de v129 no pudo resolverla— lleva su
#   clave. Una fila con OTRO id y la misma clave no es suya: es lo que impide
#   que quien registre después el correo antiguo herede los datos del anterior;
# * con ``user_id = None`` (API keys sin dueño, jobs, llamadores legacy) se
#   reduce a ``user_key = %s``, exactamente lo que había antes.
_IDENT = "(user_id = %s OR (user_key = %s AND (user_id IS NULL OR %s::int IS NULL)))"


class WatchlistRepository:
    """Acceso a las tablas ``watchlist_cpv``, ``watchlist_items`` y ``pending_digests``."""

    def query_licitaciones_since(self, cpv_prefix: str, since_date: str) -> list[dict[str, Any]]:
        """Licitaciones con CPV que empiece por ``cpv_prefix`` desde ``since_date``."""
        pattern = cpv_prefix + "%"
        with connect_read() as c:
            cur = c.execute(
                "SELECT " + _WATCHLIST_LIC_COLS + " FROM licitaciones "
                "WHERE fecha_publicacion >= %s AND cpv LIKE %s "
                "ORDER BY fecha_publicacion DESC",
                (since_date, pattern),
            )
            return rows_to_dicts(cur)

    def query_licitaciones_batch(
        self, entries: list[dict[str, Any]], default_since: str
    ) -> dict[str, list[dict[str, Any]]]:
        """Consulta licitaciones para múltiples entradas watchlist agrupadas por fecha."""
        from collections import defaultdict

        by_since: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entry in entries:
            raw_since = entry.get("last_notified_at") or default_since
            by_since[str(raw_since)].append(entry)

        result: dict[str, list[dict[str, Any]]] = {}

        with connect_read() as c:
            for since_date, grp_entries in by_since.items():
                cpv_prefixes = [e["cpv_prefix"] for e in grp_entries]
                placeholders = " OR ".join("cpv LIKE %s" for _ in cpv_prefixes)
                params: list[Any] = [since_date] + [p + "%" for p in cpv_prefixes]
                cur = c.execute(
                    "SELECT " + _WATCHLIST_LIC_COLS + " FROM licitaciones "
                    "WHERE fecha_publicacion >= %s AND (" + placeholders + ") "
                    "ORDER BY fecha_publicacion DESC",
                    params,
                )
                rows = rows_to_dicts(cur)

                for prefix in cpv_prefixes:
                    result[prefix] = [r for r in rows if (r.get("cpv") or "").startswith(prefix)]

        return result

    def store_pending_digest(
        self,
        *,
        user_key: str,
        recipient: str,
        entry_id: int,
        licitacion_id: str,
        frequency: str,
        matched_at: str,
        user_id: int | None = None,
    ) -> bool:
        """Persiste una coincidencia en ``pending_digests``.

        ``user_id`` se escribe junto a ``user_key`` cuando el productor lo
        conoce (escritura doble de ADR-030 fase 2).
        """
        try:
            with connect() as c:
                c.execute(
                    "INSERT INTO pending_digests "
                    "(user_key, user_id, recipient_email, entry_id, licitacion_id, "
                    " frequency, matched_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT(entry_id, licitacion_id) DO NOTHING",
                    (user_key, user_id, recipient, entry_id, licitacion_id, frequency, matched_at),
                )
            return True
        except Exception as exc:
            log.warning(
                "pending_digest_store_failed",
                entry_id=entry_id,
                licitacion_id=licitacion_id,
                error=str(exc),
            )
            return False

    def load_pending_digests(self, frequency: str) -> list[dict[str, Any]]:
        """Carga los digests pendientes (no enviados) para una frecuencia dada.

        ``entry_id`` apunta a dos tablas según quién encoló la fila: el job de
        reglas (``watchlist_rules``, el producto vivo) o el legado de
        ``watchlist_cpv``. La tabla no lleva discriminador, así que se resuelve
        por ``(id, user_key)``: una regla del mismo usuario con ese id gana, y
        sólo si no la hay se cae al legado. Antes se unía sólo a ``watchlist_cpv``
        por ``id``, y un digest de reglas salía con los criterios de una entrada
        ajena que casualmente compartía número.

        Desde v129 la correlación admite también ``user_id``: una regla creada
        tras un cambio de correo lleva otra ``user_key`` que el digest que la
        cita, y sin el id el correo saldría sin sus criterios.
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT pd.id, pd.recipient_email, pd.entry_id, pd.licitacion_id, pd.user_key, "
                "       l.titulo, l.descripcion, l.organo_contratacion, "
                "       l.cpv, l.importe, l.ccaa, l.estado, l.fecha_publicacion, "
                "       l.fecha_limite, l.tecnologia, l.url, "
                "       COALESCE(r.cpv, w.cpv_prefix) AS cpv_prefix, "
                "       COALESCE(r.keyword, w.keyword) AS keyword, "
                "       COALESCE(r.min_importe, w.min_importe) AS min_importe, "
                "       COALESCE(r.ccaa, w.ccaa) AS entry_ccaa, "
                "       r.nombre AS rule_nombre "
                "FROM pending_digests pd "
                "LEFT JOIN licitaciones l ON l.id_externo = pd.licitacion_id "
                "LEFT JOIN watchlist_rules r ON r.id = pd.entry_id "
                "  AND (r.user_key = pd.user_key "
                "       OR (pd.user_id IS NOT NULL AND r.user_id = pd.user_id)) "
                "LEFT JOIN watchlist_cpv w ON w.id = pd.entry_id AND r.id IS NULL "
                "WHERE pd.sent = 0 AND pd.frequency = %s "
                "ORDER BY pd.recipient_email, pd.entry_id",
                (frequency,),
            )
            return rows_to_dicts(cur)

    def mark_digests_sent(self, digest_ids: list[int]) -> None:
        """Marca los digests como enviados."""
        if not digest_ids:
            return
        with connect() as c:
            placeholders = ",".join("%s" for _ in digest_ids)
            c.execute(
                "UPDATE pending_digests SET sent = 1 WHERE id IN (" + placeholders + ")",
                digest_ids,
            )

    def export_by_user_key(self, user_key: str, user_id: int | None = None) -> list[dict[str, Any]]:
        """Exporta entradas de watchlist CPV del usuario (GDPR Art. 15/20).

        Histórico: hasta 2026-08 consultaba una tabla ``watchlist`` inexistente
        con el error tragado por un ``except``, así que el export devolvía
        siempre ``[]``. Sin ``except``: si la query falla, el export debe
        fallar, no fingir que el usuario no tiene datos.

        Con ``user_id`` la lectura es dual (v129): un export que sólo mirase la
        clave del correo actual dejaría fuera lo guardado con el anterior.
        """
        with connect_read() as c:
            cur = c.execute(
                f"SELECT * FROM watchlist_cpv WHERE {_IDENT} LIMIT 5000",
                (user_id, user_key, user_id),
            )
            return rows_to_dicts(cur)

    def anonymize_by_user_key(self, user_key: str, user_id: int | None = None) -> None:
        """Anonimiza la watchlist CPV del usuario (GDPR Art. 17).

        ``watchlist_cpv`` no tiene columna ``name``; la PII real es
        ``email``/``user_id`` (v53) además del propio ``user_key``. Un fallo
        aquí debe propagarse: un borrado GDPR que falla en silencio es
        incumplimiento, no robustez.
        """
        with connect() as c:
            c.execute(
                "UPDATE watchlist_cpv SET user_key = 'DELETED', email = NULL, "
                f"user_id = NULL WHERE {_IDENT}",
                (user_id, user_key, user_id),
            )

    # ------------------------------------------------------------------
    # watchlist_items — favoritos de licitaciones individuales (v45)
    # ------------------------------------------------------------------

    # ``organization_id`` es obligatoria en los métodos de watchlist_items y no
    # tiene rama ``None``. La tuvo: quien omitía el argumento caía en una query
    # sin filtro de organización (lectura) o escribía una fila con organización
    # nula (``add_item``), invisible para siempre a la rama con ámbito. Un
    # llamador que hoy la omita falla al tipar, que es cuando toca enterarse.
    # Los llamadores reciben el valor ya resuelto por ``api.tenancy``
    # (``ctx["organization_id"]``, que nunca es ``None``).

    # El predicado de identidad es el dual de v129 (``_IDENT``, con alias): el
    # anterior, ``wi.user_id = %s OR wi.user_key = %s``, dejaba ver una fila
    # con OTRO ``user_id`` a quien compartiera su clave. Va escrito como
    # literal y no compuesto desde ``_IDENT`` porque el escáner de
    # ``tests/test_user_key_sql_isolation.py`` sólo pliega literales.
    _ITEMS_SCOPE_WHERE = (
        "WHERE wi.organization_id = %s AND (wi.visibility = 'organization' OR "
        "(wi.user_id = %s OR (wi.user_key = %s AND (wi.user_id IS NULL OR %s::int IS NULL)))) "
    )

    def list_items(
        self,
        user_key: str,
        organization_id: int,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Favoritos del usuario, enriquecidos con datos de la licitación.

        El backend es la fuente de la analítica/join (ADR-014): el frontend
        nunca debe fabricar este enriquecimiento por su cuenta.

        Con ``FOLLOWS_LECTURA`` encendido la pertenencia sale de ``follows``
        (ADR-031 §B, fase 2) y de aquí sólo la nota personal: ver
        :func:`db.repositories.follows.favoritos_desde_follows`.
        """
        from db.repositories import follows as _follows

        if _follows.lectura_desde_follows():
            return _follows.favoritos_desde_follows(user_key, organization_id, user_id)
        with connect_read() as c:
            cur = c.execute(
                "SELECT wi.id, wi.id_externo, wi.created_at, "
                "       wi.organization_id, wi.visibility, wi.nota, "
                "       l.titulo, l.importe, l.estado, l.fecha_publicacion "
                "FROM watchlist_items wi "
                "LEFT JOIN licitaciones l ON l.id_externo = wi.id_externo "
                + self._ITEMS_SCOPE_WHERE
                + "ORDER BY wi.created_at DESC, wi.id DESC",
                (organization_id, user_id, user_key, user_id),
            )
            return rows_to_dicts(cur)

    def calendar_items(
        self,
        user_key: str,
        organization_id: int,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Favoritos con fecha de compromiso, para el calendario ICS.

        Comparte el predicado de visibilidad de :meth:`list_items` a propósito:
        son la misma colección vista por dos superficies. Hasta 2026-09 esta
        query vivía en ``api/routes/exports.py`` (violando ADR-022) y filtraba
        sólo por ``wi.user_key``, sin ``organization_id`` ni ``visibility`` --
        y quien la sirve es un enlace firmado de larga vida, sin sesión.
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT l.id_externo, l.titulo, l.fecha_limite, l.fecha_fin, l.url "
                "FROM watchlist_items wi "
                "JOIN licitaciones l ON l.id_externo = wi.id_externo "
                + self._ITEMS_SCOPE_WHERE
                + "AND (l.fecha_limite IS NOT NULL OR l.fecha_fin IS NOT NULL)",
                (organization_id, user_id, user_key, user_id),
            )
            return rows_to_dicts(cur)

    def add_item(
        self,
        user_key: str,
        user_id: int | None,
        id_externo: str,
        organization_id: int,
        visibility: str = "private",
    ) -> dict[str, Any]:
        """Añade un favorito de forma idempotente.

        Si el usuario ya tiene ese ``id_externo`` no duplica ni falla: devuelve
        el registro existente sin tocarlo. «Ya lo tiene» se decide con la
        identidad dual y no sólo con ``UNIQUE(user_key, id_externo)``: tras un
        cambio de correo la clave nueva no choca con la fila antigua, y el
        ``ON CONFLICT`` habría dejado el mismo expediente dos veces en la lista.
        """
        with connect() as c:
            existente = c.execute(
                "SELECT id, user_key, user_id, id_externo, organization_id, "
                "visibility, nota, created_at "
                f"FROM watchlist_items WHERE {_IDENT} AND id_externo = %s "
                "ORDER BY CASE WHEN user_key = %s THEN 0 ELSE 1 END, id LIMIT 1",
                (user_id, user_key, user_id, id_externo, user_key),
            )
            rows = rows_to_dicts(existente)
            if rows:
                return rows[0]
            c.execute(
                "INSERT INTO watchlist_items "
                "(user_key, user_id, id_externo, organization_id, visibility) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT(user_key, id_externo) DO NOTHING",
                (user_key, user_id, id_externo, organization_id, visibility),
            )
            cur = c.execute(
                "SELECT id, user_key, user_id, id_externo, organization_id, "
                "visibility, nota, created_at "
                "FROM watchlist_items WHERE user_key = %s AND id_externo = %s",
                (user_key, id_externo),
            )
            rows = rows_to_dicts(cur)

        # Escritura doble hacia `follows` (ADR-031 §B, fase aditiva): el
        # favorito sigue viviendo aquí y se lee de aquí; `follows` es la copia
        # que la unificación va a necesitar, y mantenerla al día desde el
        # primer día es lo que hace medible la paridad. No lanza nunca (ver
        # `db/repositories/follows.py::registrar`).
        from db.repositories import follows as _follows

        _follows.registrar(
            user_key=user_key,
            user_id=user_id,
            organization_id=organization_id,
            target_type="licitacion",
            target_id=id_externo,
            visibility=visibility,
        )
        return rows[0] if rows else {}

    #: Tope de la nota, igual que el CHECK de v124.
    MAX_NOTA = 2000

    def set_nota(
        self,
        user_key: str,
        id_externo: str,
        nota: str | None,
        user_id: int | None = None,
    ) -> bool:
        """Escribe (o borra, con `None`) la nota **personal** de un favorito (C6.6).

        El filtro es solo `user_key`, deliberadamente, y no la organización: la
        nota es de quien la escribe. Un favorito con `visibility='organization'`
        lo ven todos los miembros, pero la nota no —dos personas que siguen el
        mismo expediente tienen cada una la suya, en su propia fila—. Acotar por
        organización aquí permitiría que un compañero sobrescribiera la nota de
        otro sin que nada fallara.

        `False` si esa persona no tiene ese favorito.
        """
        limpia = (nota or "").strip()
        with connect() as c:
            cur = c.execute(
                f"UPDATE watchlist_items SET nota = %s WHERE {_IDENT} AND id_externo = %s",
                ((limpia[: self.MAX_NOTA] or None), user_id, user_key, user_id, id_externo),
            )
            return bool(getattr(cur, "rowcount", 0))

    def remove_item(
        self,
        user_key: str,
        id_externo: str,
        organization_id: int,
        user_id: int | None = None,
    ) -> bool:
        """Elimina un favorito propio. ``True`` si borró algo."""
        from db.repositories import follows as _follows

        with connect() as c:
            cur = c.execute(
                "DELETE FROM watchlist_items WHERE organization_id = %s "
                f"AND id_externo = %s AND (visibility = 'organization' OR {_IDENT})",
                (organization_id, id_externo, user_id, user_key, user_id),
            )
            borrado = bool(cur.rowcount > 0)

        # Se limpia `follows` aunque aquí no hubiera nada: si las dos tablas
        # divergieron, esta es la ocasión de cuadrarlas.
        _follows.olvidar(
            user_key=user_key,
            user_id=user_id,
            target_type="licitacion",
            target_id=id_externo,
        )
        return borrado

    def export_items_by_user_key(
        self, user_key: str, user_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Exporta los favoritos (watchlist_items) del usuario (GDPR)."""
        with connect_read() as c:
            try:
                cur = c.execute(
                    f"SELECT * FROM watchlist_items WHERE {_IDENT} LIMIT 5000",
                    (user_id, user_key, user_id),
                )
                return rows_to_dicts(cur)
            except Exception:
                # Export GDPR: un [] por fallo de BD entrega un export
                # incompleto que el usuario lee como completo.
                log.warning("watchlist_export_items_failed", exc_info=True)
                return []

    def anonymize_items_by_user_key(self, user_key: str, user_id: int | None = None) -> None:
        """Anonimiza (borra) los favoritos del usuario (GDPR).

        A diferencia de ``watchlist`` (que tiene columna ``name`` a anonimizar
        in-place), ``watchlist_items`` no guarda datos personales adicionales
        más allá de ``user_key``/``user_id``; se eliminan las filas para
        cumplir con el derecho al olvido sin dejar remanentes.
        """
        with connect() as c:
            try:
                c.execute(
                    f"DELETE FROM watchlist_items WHERE {_IDENT}",
                    (user_id, user_key, user_id),
                )
            except Exception:
                log.debug("watchlist_items_anonymize_failed", exc_info=True)
