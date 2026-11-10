"""Repository para watchlist y pending_digests: ítems de seguimiento y digests.

El CRUD por CPV y su matching viven en ``db/watchlist.py`` (ADR-022,
«Entidades con las dos caras»).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from db.database import connect, connect_read
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

_WATCHLIST_LIC_COLS = (
    "id_externo, titulo, descripcion, organo_contratacion, "
    "cpv, importe, ccaa, estado, fecha_publicacion, url"
)

# ── Identidad (ADR-030 fase 3, v181) ─────────────────────────────────────────
#
# Cada tabla de usuario lleva ``user_id`` (la identidad interna) junto a
# ``user_key`` (la clave derivada del correo, en retirada). El predicado se
# escribe UNA vez y recibe siempre el par ``(user_id, user_id)``: la fila es del
# usuario si lleva su id, o si —sin id todavía, porque el backfill no pudo
# resolverla— lleva la clave que ``clave_legada_de_usuario(user_id)`` calcula en
# la base con su correo actual. Una fila con OTRO id y la misma clave no es
# suya: es lo que impide que quien registre después el correo antiguo herede
# los datos del anterior. Las columnas ``user_key`` se siguen escribiendo con
# esa misma función.
_IDENT = "(user_id = %s OR (user_id IS NULL AND user_key = clave_legada_de_usuario(%s)))"


class WatchlistRepository:
    """Acceso a las tablas ``watchlist_cpv``, ``watchlist_items`` y ``pending_digests``."""

    # ── Recordatorios de plazos (``services/deadline_reminders.py``) ─────────
    # Bajaron aquí desde ese servicio el 2026-10-25 (ADR-022, ratchet TID251).
    # Devuelven tuplas y no dicts porque el servicio solo necesita dos columnas
    # y decide qué hacer con las filas sin organización (ver su docstring).

    def favoritos_con_organizacion(self, user_id: int) -> list[tuple[str, int | None]]:
        """``(id_externo, organization_id)`` de los favoritos del usuario.

        Incluye los guardados bajo la clave de un correo anterior que el
        backfill no resolvió: sin ellos no tendrían recordatorio. Las filas
        legacy con ``organization_id IS NULL`` se devuelven tal cual: el
        servicio las cuenta y las descarta.
        """
        with connect_read() as c:
            filas = c.execute(
                f"SELECT id_externo, organization_id FROM watchlist_items WHERE {_IDENT}",
                (user_id, user_id),
            ).fetchall()
        return [(str(fila[0]), None if fila[1] is None else int(fila[1])) for fila in filas]

    def plazos_de_licitaciones(self, ids: list[str]) -> list[dict[str, Any]]:
        """``titulo``, ``fecha_limite`` y ``fecha_fin`` de esas licitaciones."""
        if not ids:
            return []
        placeholders = ",".join(["%s"] * len(ids))
        with connect_read() as c:
            cur = c.execute(
                f"SELECT id_externo, titulo, fecha_limite, fecha_fin "
                f"FROM licitaciones WHERE id_externo IN ({placeholders})",
                ids,
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def usuarios_con_favoritos(self) -> list[int]:
        """``user_id`` de cada usuario con algún favorito.

        Barrido global por diseño: lo recorre el job de recordatorios, que no
        corre en nombre de nadie. Las filas sin ``user_id`` (claves que ningún
        usuario reclamó) no tienen a quién avisar y quedan fuera.
        """
        with connect_read() as c:
            filas = c.execute(
                "SELECT DISTINCT user_id FROM watchlist_items "
                "WHERE user_id IS NOT NULL ORDER BY user_id"
            ).fetchall()
        return [int(fila[0]) for fila in filas]

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
                params: list[object] = [since_date] + [p + "%" for p in cpv_prefixes]
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
        return self.store_pending_digests(
            user_key=user_key,
            recipient=recipient,
            entry_id=entry_id,
            licitacion_ids=[licitacion_id],
            frequency=frequency,
            matched_at=matched_at,
            user_id=user_id,
        )

    def store_pending_digests(
        self,
        *,
        user_key: str,
        recipient: str,
        entry_id: int,
        licitacion_ids: Sequence[str],
        frequency: str,
        matched_at: str,
        user_id: int | None = None,
    ) -> bool:
        """Varias coincidencias de una misma entrada en una sola conexión.

        Todas o ninguna: un fallo se registra y devuelve ``False`` sin dejar la
        mitad encolada. ``ON CONFLICT`` hace que repetir no duplique.
        """
        if not licitacion_ids:
            return True
        try:
            with connect() as c:
                c.executemany(
                    "INSERT INTO pending_digests "
                    "(user_key, user_id, recipient_email, entry_id, licitacion_id, "
                    " frequency, matched_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT(entry_id, licitacion_id) DO NOTHING",
                    [
                        (user_key, user_id, recipient, entry_id, lic, frequency, matched_at)
                        for lic in licitacion_ids
                    ],
                )
            return True
        except Exception as exc:
            log.warning(
                "pending_digest_store_failed",
                entry_id=entry_id,
                licitaciones=len(licitacion_ids),
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

        ``rule_organization_id`` es la organización de la regla: contra su
        capacidad se calcula el checklist que el correo enseña (B3).
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT pd.id, pd.recipient_email, pd.entry_id, pd.licitacion_id, pd.user_key, "
                "       l.titulo, l.descripcion, l.organo_contratacion, "
                "       l.cpv, l.importe, l.ccaa, l.estado, l.fecha_publicacion, "
                "       l.fecha_limite, l.tecnologia, l.url, "
                # Base del importe (ADR-032): el correo dice «sin IVA» o
                # «base desconocida», nunca un importe de base ignorada.
                "       l.importe_tipo, l.importe_base_sin_iva, l.importe_con_iva, "
                "       COALESCE(r.cpv, w.cpv_prefix) AS cpv_prefix, "
                "       COALESCE(r.keyword, w.keyword) AS keyword, "
                "       COALESCE(r.min_importe, w.min_importe) AS min_importe, "
                "       COALESCE(r.ccaa, w.ccaa) AS entry_ccaa, "
                "       r.nombre AS rule_nombre, r.organization_id AS rule_organization_id, "
                "       de.event_type AS evento_tipo, de.payload_json AS evento_payload "
                "FROM pending_digests pd "
                "LEFT JOIN licitaciones l ON l.id_externo = pd.licitacion_id "
                "LEFT JOIN watchlist_rules r ON pd.entry_id > 0 AND r.id = pd.entry_id "
                "  AND (r.user_key = pd.user_key "
                "       OR (pd.user_id IS NOT NULL AND r.user_id = pd.user_id)) "
                "LEFT JOIN watchlist_cpv w ON pd.entry_id > 0 AND w.id = pd.entry_id "
                "  AND r.id IS NULL "
                # Filas del despachador de eventos (S4.1): `entry_id` negativo
                # que codifica `-(event_id * 100 + posición)`. Ver
                # `scheduler/jobs/event_dispatch.entry_id_de_digest`.
                "LEFT JOIN domain_events de ON pd.entry_id < 0 "
                "  AND de.id = (-pd.entry_id) / 100 "
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

    def export_cpv(self, user_id: int) -> list[dict[str, Any]]:
        """Exporta entradas de watchlist CPV del usuario (GDPR Art. 15/20).

        Histórico: hasta 2026-08 consultaba una tabla ``watchlist`` inexistente
        con el error tragado por un ``except``, así que el export devolvía
        siempre ``[]``. Sin ``except``: si la query falla, el export debe
        fallar, no fingir que el usuario no tiene datos.

        La lectura incluye lo guardado con un correo anterior: un export que
        sólo mirase la clave del correo actual lo dejaría fuera.
        """
        with connect_read() as c:
            cur = c.execute(
                f"SELECT * FROM watchlist_cpv WHERE {_IDENT} LIMIT 5000",  # SELECT *: export RGPD: la fila entera es el contrato
                (user_id, user_id),
            )
            return rows_to_dicts(cur)

    def anonymize_cpv(self, user_id: int) -> None:
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
                (user_id, user_id),
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

    # El predicado de identidad es ``_IDENT`` con alias: el anterior,
    # ``wi.user_id = %s OR wi.user_key = %s``, dejaba ver una fila con OTRO
    # ``user_id`` a quien compartiera su clave. Va escrito como literal y no
    # compuesto desde ``_IDENT`` porque el escáner de
    # ``tests/test_user_key_sql_isolation.py`` sólo pliega literales.
    _ITEMS_SCOPE_WHERE = (
        "WHERE wi.organization_id = %s AND (wi.visibility = 'organization' OR "
        "(wi.user_id = %s OR (wi.user_id IS NULL "
        "AND wi.user_key = clave_legada_de_usuario(%s)))) "
    )

    def list_items(self, user_id: int, organization_id: int) -> list[dict[str, Any]]:
        """Favoritos del usuario, enriquecidos con datos de la licitación.

        El backend es la fuente de la analítica/join (ADR-014): el frontend
        nunca debe fabricar este enriquecimiento por su cuenta.

        Con ``FOLLOWS_LECTURA`` encendido la pertenencia sale de ``follows``
        (ADR-031 §B, fase 2) y de aquí sólo la nota personal: ver
        :func:`db.repositories.follows.favoritos_desde_follows`.
        """
        from db.repositories import follows as _follows

        if _follows.lectura_desde_follows():
            return _follows.favoritos_desde_follows(organization_id, user_id)
        with connect_read() as c:
            cur = c.execute(
                "SELECT wi.id, wi.id_externo, wi.created_at, "
                "       wi.organization_id, wi.visibility, wi.nota, "
                "       l.titulo, l.importe, l.estado, l.fecha_publicacion "
                "FROM watchlist_items wi "
                "LEFT JOIN licitaciones l ON l.id_externo = wi.id_externo "
                + self._ITEMS_SCOPE_WHERE
                + "ORDER BY wi.created_at DESC, wi.id DESC",
                (organization_id, user_id, user_id),
            )
            return rows_to_dicts(cur)

    def calendar_items(self, user_id: int, organization_id: int) -> list[dict[str, Any]]:
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
                (organization_id, user_id, user_id),
            )
            return rows_to_dicts(cur)

    def add_item(
        self,
        user_id: int,
        id_externo: str,
        organization_id: int,
        visibility: str = "private",
    ) -> dict[str, Any]:
        """Añade un favorito de forma idempotente.

        Si el usuario ya tiene ese ``id_externo`` no duplica ni falla: devuelve
        el registro existente sin tocarlo. «Ya lo tiene» se decide con ``_IDENT``
        (su id, o su clave legada en las filas sin id) y no sólo con el índice
        único por ``user_id``: tras un cambio de correo una fila antigua sin id
        sigue siendo suya, y el ``ON CONFLICT`` no la vería.
        """
        with connect() as c:
            existente = c.execute(
                "SELECT id, user_key, user_id, id_externo, organization_id, "
                "visibility, nota, created_at "
                f"FROM watchlist_items WHERE {_IDENT} AND id_externo = %s "
                "ORDER BY id LIMIT 1",
                (user_id, user_id, id_externo),
            )
            rows = rows_to_dicts(existente)
            if rows:
                return rows[0]
            c.execute(
                "INSERT INTO watchlist_items "
                "(user_key, user_id, id_externo, organization_id, visibility) "
                "VALUES (clave_legada_de_usuario(%s), %s, %s, %s, %s) "
                "ON CONFLICT (user_id, id_externo) WHERE user_id IS NOT NULL DO NOTHING",
                (user_id, user_id, id_externo, organization_id, visibility),
            )
            cur = c.execute(
                "SELECT id, user_key, user_id, id_externo, organization_id, "
                "visibility, nota, created_at "
                "FROM watchlist_items WHERE user_id = %s AND id_externo = %s",
                (user_id, id_externo),
            )
            rows = rows_to_dicts(cur)

        # Escritura doble hacia `follows` (ADR-031 §B, fase aditiva): el
        # favorito sigue viviendo aquí y se lee de aquí; `follows` es la copia
        # que la unificación va a necesitar, y mantenerla al día desde el
        # primer día es lo que hace medible la paridad. No lanza nunca (ver
        # `db/repositories/follows.py::registrar`).
        from db.repositories import follows as _follows

        _follows.registrar(
            user_id=user_id,
            organization_id=organization_id,
            target_type="licitacion",
            target_id=id_externo,
            visibility=visibility,
        )
        return rows[0] if rows else {}

    #: Tope de la nota, igual que el CHECK de v124.
    MAX_NOTA = 2000

    def set_nota(self, user_id: int, id_externo: str, nota: str | None) -> bool:
        """Escribe (o borra, con `None`) la nota **personal** de un favorito (C6.6).

        El filtro es solo la identidad, deliberadamente, y no la organización: la
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
                ((limpia[: self.MAX_NOTA] or None), user_id, user_id, id_externo),
            )
            return bool(getattr(cur, "rowcount", 0))

    def remove_item(self, user_id: int, id_externo: str, organization_id: int) -> bool:
        """Elimina un favorito propio. ``True`` si borró algo."""
        from db.repositories import follows as _follows

        with connect() as c:
            cur = c.execute(
                "DELETE FROM watchlist_items WHERE organization_id = %s "
                f"AND id_externo = %s AND (visibility = 'organization' OR {_IDENT})",
                (organization_id, id_externo, user_id, user_id),
            )
            borrado = bool(cur.rowcount > 0)

        # Se limpia `follows` aunque aquí no hubiera nada: si las dos tablas
        # divergieron, esta es la ocasión de cuadrarlas.
        _follows.olvidar(
            user_id=user_id,
            target_type="licitacion",
            target_id=id_externo,
        )
        return borrado

    def export_items(self, user_id: int) -> list[dict[str, Any]]:
        """Exporta los favoritos (watchlist_items) del usuario (GDPR)."""
        with connect_read() as c:
            try:
                cur = c.execute(
                    f"SELECT * FROM watchlist_items WHERE {_IDENT} LIMIT 5000",  # SELECT *: export RGPD: la fila entera es el contrato
                    (user_id, user_id),
                )
                return rows_to_dicts(cur)
            except Exception:
                # Export GDPR: un [] por fallo de BD entrega un export
                # incompleto que el usuario lee como completo.
                log.warning("watchlist_export_items_failed", exc_info=True)
                return []

    def anonymize_items(self, user_id: int) -> None:
        """Anonimiza (borra) los favoritos del usuario (GDPR).

        A diferencia de ``watchlist`` (que tiene columna ``name`` a anonimizar
        in-place), ``watchlist_items`` no guarda datos personales adicionales
        más allá de ``user_id``/``user_key``; se eliminan las filas para
        cumplir con el derecho al olvido sin dejar remanentes.
        """
        with connect() as c:
            try:
                c.execute(
                    f"DELETE FROM watchlist_items WHERE {_IDENT}",
                    (user_id, user_id),
                )
            except Exception:
                log.debug("watchlist_items_anonymize_failed", exc_info=True)
