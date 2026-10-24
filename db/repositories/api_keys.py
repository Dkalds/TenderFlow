"""Repository para api_keys."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from db.database import connect, connect_read, get_table_columns, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)


class ApiKeyRepository:
    def _hash(self, raw: str) -> str:
        from config import settings

        secret = settings.API_HMAC_SECRET.get_secret_value()
        if secret:
            return hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
        return hashlib.sha256(raw.encode()).hexdigest()

    # ── Lookups ──────────────────────────────────────────────

    def get_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        with connect_read() as c:
            cols_info = get_table_columns(c, "api_keys")
            select_parts = [
                "id",
                "expires_at" if "expires_at" in cols_info else "NULL AS expires_at",
                "user_id" if "user_id" in cols_info else "NULL AS user_id",
            ]
            if "scopes" in cols_info:
                select_parts.append("scopes")
            else:
                select_parts.append("'*' AS scopes")
            row = c.execute(
                "SELECT " + ", ".join(select_parts) + " FROM api_keys "
                "WHERE key_hash = %s AND is_active = 1",
                (key_hash,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "expires_at": row[1],
            "user_id": row[2],
            "scopes": row[3] if len(row) > 3 else "*",
        }

    def get_stored_hash(self, key_id: int) -> str | None:
        """Devuelve el ``key_hash`` almacenado para validación en tiempo constante."""
        with connect_read() as c:
            row = c.execute("SELECT key_hash FROM api_keys WHERE id = %s", (key_id,)).fetchone()
        return str(row[0]) if row else None

    def get_active_scopes(self, key_hash: str) -> str | None:
        """Devuelve scopes de una key activa, o ``None`` si no existe."""
        try:
            with connect_read() as c:
                row = c.execute(
                    "SELECT scopes FROM api_keys WHERE key_hash = %s AND is_active = 1",
                    (key_hash,),
                ).fetchone()
        except Exception:
            # Un fallo de BD aquí se presenta como "clave inválida": sin log no
            # hay forma de distinguir un ataque de una caída de infraestructura.
            log.warning("api_key_scopes_lookup_failed", exc_info=True)
            return None
        if not row:
            return None
        return str(row[0]) if row[0] is not None else "*"

    def get_user_id(self, key_id: int) -> int | None:
        """Obtiene ``user_id`` vinculado a la API key, si la columna existe."""
        with connect_read() as c:
            try:
                cols = get_table_columns(c, "api_keys")
                if "user_id" not in cols:
                    return None
                row = c.execute(
                    "SELECT user_id FROM api_keys WHERE id = %s LIMIT 1", (key_id,)
                ).fetchone()
                if row and row[0]:
                    return int(row[0])
                return None
            except Exception:
                log.warning("api_key_user_id_lookup_failed", key_id=key_id, exc_info=True)
                return None

    def get_name_and_scopes(self, key_id: int) -> tuple[str, str] | None:
        """Obtiene nombre y scopes de una API key por ID."""
        with connect_read() as c:
            row = c.execute("SELECT name, scopes FROM api_keys WHERE id = %s", (key_id,)).fetchone()
        if not row:
            return None
        return row[0], str(row[1] or "*")

    def get_rotatable(self, key_id: int) -> dict[str, Any] | None:
        """Devuelve ``{user_id, name, scopes}`` de una key rotable, o ``None``.

        Rotable = existe, sigue activa y no ha caducado. El filtro no es
        cosmético: mientras la rotación se autenticaba con la propia key
        (``require_api_key`` → ``lookup_active_key``) solo se podía rotar una
        credencial viva. Al mover el endpoint a step-up por sesión, esa
        garantía se perdía — bastaba con conocer el id de una key revocada
        para acuñar otra activa con sus mismos scopes, anulando tanto la
        revocación manual como la automática del webhook de secret scanning de
        GitHub (``api/routes/security.py``) y la del alta de baja de un usuario.
        """
        with connect_read() as c:
            row = c.execute(
                "SELECT user_id, name, scopes FROM api_keys "
                "WHERE id = %s AND is_active = 1 "
                "AND (expires_at IS NULL OR expires_at > %s)",
                (key_id, now_utc_iso()),
            ).fetchone()
        if not row:
            return None
        return {
            "user_id": int(row[0]) if row[0] is not None else None,
            "name": str(row[1]),
            "scopes": str(row[2] or "*"),
        }

    def get_name(self, key_hash: str) -> str | None:
        with connect_read() as c:
            row = c.execute(
                "SELECT name FROM api_keys WHERE key_hash = %s LIMIT 1", (key_hash,)
            ).fetchone()
        return str(row[0]) if row else None

    def get_all_for_user(self, user_id: int) -> list[dict[str, Any]]:
        """Lista las keys del usuario. Nunca incluye el hash ni el token.

        Devuelve ``id`` porque es el único identificador con el que el dueño
        puede señalar qué key rotar: ``POST /me/keys/rotate`` lo exige desde
        que pasó a step-up por sesión, y sin este campo no había forma de
        obtenerlo — el endpoint quedaba inalcanzable desde la UI.
        """
        with connect_read() as c:
            try:
                cur = c.execute(
                    # `tier` desde C2.3: sin él, la pantalla de Ajustes no
                    # puede decir qué límite tiene cada clave, y el usuario
                    # descubre su tier por un 429. `last_used` para decidir
                    # cuál revocar: una clave que nadie usa desde hace meses
                    # es la primera candidata. La más reciente primero: tras
                    # rotar, la nueva queda arriba.
                    "SELECT id, name, created_at, expires_at, last_used, is_active, "
                    "COALESCE(tier, 'standard') AS tier "
                    "FROM api_keys WHERE user_id = %s "
                    "ORDER BY created_at DESC, id DESC",
                    (user_id,),
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]
            except Exception:
                # Una lista vacía por fallo de BD es indistinguible de "este
                # usuario no tiene keys", y el dueño no puede rotar lo que no ve.
                log.warning("api_keys_list_for_user_failed", user_id=user_id, exc_info=True)
                return []

    # ── Listings ─────────────────────────────────────────────

    def list_all(self, *, limit: int = 500) -> list[dict[str, Any]]:
        """Lista las API keys de la instancia con su dueño. Nunca el hash ni el token.

        Es lo que lee Ops > Administración: hasta 2026-10 no había ninguna
        pantalla desde la que ver las claves de otros, y en producción había 89
        activas sin dueño ni caducidad que nadie podía revocar. ``prefix`` son
        los ocho primeros caracteres del token —los que el integrador reconoce
        en su configuración— y no bastan para autenticar.

        ``estado`` se calcula aquí, con el mismo reloj que usa la validación
        (``expires_at`` contra ``now_utc_iso()``): una clave con ``is_active = 1``
        pero caducada no abre nada, y pintarla como «activa» engañaría a quien
        decide qué revocar. Las vivas primero; dentro, la más reciente arriba.
        """
        ahora = now_utc_iso()
        with connect_read() as c:
            cur = c.execute(
                "SELECT k.id, k.name, k.prefix, k.tier, k.scopes, k.user_id, "
                "u.email AS owner_email, u.display_name AS owner_name, "
                "(u.deactivated_at IS NOT NULL) AS owner_deactivated, "
                "k.organization_id, k.created_at, k.expires_at, k.last_used, k.is_active, "
                "CASE WHEN k.is_active = 0 THEN 'revocada' "
                "     WHEN k.expires_at IS NOT NULL AND k.expires_at <= %s THEN 'caducada' "
                "     ELSE 'activa' END AS estado "
                "FROM api_keys k LEFT JOIN users u ON u.id = k.user_id "
                "ORDER BY (k.is_active = 1 AND (k.expires_at IS NULL OR k.expires_at > %s)) DESC, "
                "k.created_at DESC, k.id DESC "
                "LIMIT %s",
                (ahora, ahora, limit),
            )
            return rows_to_dicts(cur)

    def resumen_instancia(self) -> dict[str, int]:
        """Cuántas claves hay y cuántas vivas carecen de dueño o de caducidad.

        Se cuenta sobre la tabla entera, no sobre la página que devuelve
        :meth:`list_all`: con el listado recortado, contar en el cliente daría
        una cifra que no es la de la instancia.
        """
        ahora = now_utc_iso()
        with connect_read() as c:
            fila = c.execute(
                "SELECT count(*), "
                "count(*) FILTER (WHERE vivas), "
                "count(*) FILTER (WHERE vivas AND user_id IS NULL), "
                "count(*) FILTER (WHERE vivas AND expires_at IS NULL) "
                "FROM (SELECT user_id, expires_at, "
                "      (is_active = 1 AND (expires_at IS NULL OR expires_at > %s)) AS vivas "
                "      FROM api_keys) k",
                (ahora,),
            ).fetchone()
        total, activas, sin_dueno, sin_caducidad = (int(v or 0) for v in fila)
        return {
            "total": total,
            "activas": activas,
            "activas_sin_dueno": sin_dueno,
            "activas_sin_caducidad": sin_caducidad,
        }

    def list_for_export(self, key_hash: str) -> list[dict[str, Any]]:
        """Exporta las API keys vinculadas al ``key_hash`` (GDPR)."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT name, created_at, expires_at FROM api_keys WHERE key_hash = %s",
                (key_hash,),
            )
            return rows_to_dicts(cur)

    def get_by_key_id(self, key_id: int) -> list[dict[str, Any]]:
        """Devuelve datos de la API key por ID con columnas dinámicas."""
        with connect_read() as c:
            try:
                cols_info = get_table_columns(c, "api_keys")
                select_cols = "id, name, created_at, is_active, scopes"
                if "prefix" in cols_info:
                    select_cols += ", prefix"
                if "expires_at" in cols_info:
                    select_cols += ", expires_at"
                cur = c.execute(
                    "SELECT " + select_cols + " FROM api_keys WHERE id = %s",
                    (key_id,),
                )
                return rows_to_dicts(cur)
            except Exception:
                log.warning("api_key_lookup_by_id_failed", key_id=key_id, exc_info=True)
                return []

    # ── Mutations ────────────────────────────────────────────

    def update_last_used(self, key_id: int) -> None:
        try:
            with connect() as c:
                c.execute(
                    "UPDATE api_keys SET last_used = %s WHERE id = %s",
                    (now_utc_iso(), key_id),
                )
        except Exception:
            log.debug("api_key_update_last_used_failed", key_id=key_id, exc_info=True)

    def insert(
        self,
        *,
        key_hash: str,
        name: str,
        scopes: str,
        prefix: str,
        user_id: int,
        expires_at: str,
    ) -> None:
        """Inserta una API key pre-hasheada respetando columnas presentes.

        Es el único ``INSERT INTO api_keys`` del código de producción, y exige
        dueño y caducidad. Hasta 2026-10 los dos eran opcionales —y había un
        ``create()`` al lado que no aceptaba ninguno de los dos—: en producción
        se acumularon 89 claves activas sin usuario ni ``expires_at``, que no se
        revocan al dar de baja a nadie y no caducan nunca. El tipo ya lo pide;
        la comprobación cubre a quien llegue con un ``0`` o una cadena vacía.
        La restricción en la propia tabla (``NOT NULL``) necesita una migración.
        """
        if not user_id or user_id < 1:
            raise ValueError("Una clave de API necesita dueño (user_id).")
        if not expires_at:
            raise ValueError("Una clave de API necesita caducidad (expires_at).")
        now = now_utc_iso()
        with connect() as c:
            cols = get_table_columns(c, "api_keys")
            fields = ["key_hash", "name", "created_at", "is_active"]
            values: list[Any] = [key_hash, name, now, 1]

            if "scopes" in cols:
                fields.append("scopes")
                values.append(scopes)
            if "user_id" in cols:
                fields.append("user_id")
                values.append(user_id)
            if "prefix" in cols:
                fields.append("prefix")
                values.append(prefix)
            if "expires_at" in cols:
                fields.append("expires_at")
                values.append(expires_at)

            placeholders = ",".join(["%s"] * len(fields))
            c.execute(
                "INSERT INTO api_keys (" + ", ".join(fields) + ") VALUES (" + placeholders + ")",
                values,
            )

    def revoke(self, key_hash: str) -> bool:
        with connect() as c:
            cur = c.execute("UPDATE api_keys SET is_active = 0 WHERE key_hash = %s", (key_hash,))
            return bool(cur.rowcount)

    def revoke_for_user(self, key_id: int, user_id: int) -> bool:
        """Revoca una key **del usuario**. ``False`` si no existe o es de otro.

        El dueño va en el ``WHERE`` y no en una lectura previa: comprobar y
        luego actualizar deja una ventana, y además así un id ajeno y uno
        inexistente responden igual. Revocar una ya revocada cuenta como
        hecho (la fila casa aunque el valor no cambie).
        """
        with connect() as c:
            cur = c.execute(
                "UPDATE api_keys SET is_active = 0 WHERE id = %s AND user_id = %s",
                (key_id, user_id),
            )
            return bool(cur.rowcount)

    def revoke_by_id(self, key_id: int) -> dict[str, Any] | None:
        """Revoca una API key por su ID interno, sea de quien sea.

        Es la revocación de administración: no filtra por dueño, al contrario
        que :meth:`revoke_for_user`. Devuelve ``{id, name, user_id}`` de la fila
        para que quien audita sepa de quién era, o ``None`` si el id no existe.
        Revocar una ya revocada devuelve la fila: el estado pedido es el que hay.
        """
        with connect() as c:
            fila = c.execute(
                "UPDATE api_keys SET is_active = 0 WHERE id = %s RETURNING id, name, user_id",
                (key_id,),
            ).fetchone()
        if fila is None:
            return None
        return {
            "id": int(fila[0]),
            "name": str(fila[1]),
            "user_id": int(fila[2]) if fila[2] is not None else None,
        }

    def deactivate_by_id(self, key_id: int) -> None:
        """Desactiva una key por ID y actualiza ``last_used`` (GDPR)."""
        with connect() as c:
            c.execute(
                "UPDATE api_keys SET is_active = 0, last_used = %s WHERE id = %s",
                (now_utc_iso(), key_id),
            )

    def deactivate_all_for_user(self, user_id: int) -> int:
        """Desactiva todas las keys del usuario (GDPR, borrado de cuenta por sesión)."""
        with connect() as c:
            try:
                cur = c.execute(
                    "UPDATE api_keys SET is_active = 0, last_used = %s WHERE user_id = %s",
                    (now_utc_iso(), user_id),
                )
                return int(cur.rowcount)
            except Exception:
                # Camino GDPR de borrado de cuenta: devolver 0 en silencio deja
                # keys vivas de una cuenta que el usuario cree eliminada.
                log.warning("api_keys_deactivate_all_failed", user_id=user_id, exc_info=True)
                return 0

    def set_expiry(self, key_id: int, expires_at: str) -> None:
        """Establece ``expires_at`` en una API key (rotación con grace period)."""
        with connect() as c:
            cols_info = get_table_columns(c, "api_keys")
            if "expires_at" in cols_info:
                c.execute(
                    "UPDATE api_keys SET expires_at = %s WHERE id = %s",
                    (expires_at, key_id),
                )


def tier_limit_por_hash(key_hash: str) -> int | None:
    """Requests/minuto que el tier de esta API key permite (C2.3, D25).

    ``api_key_tiers`` existe desde ``v28`` con tres tiers sembrados y una
    columna ``tier`` en ``api_keys``, y **ninguna ruta ni middleware la leía**:
    una clave `free` y una `enterprise` recibían exactamente el mismo rate
    limit. Esta función es lo que faltaba para que el tier signifique algo.

    Devuelve:
        - El límite por minuto del tier.
        - ``None`` si la clave no existe, está inactiva, o su tier declara
          ``per_minute_limit = 0`` — que es como ``enterprise`` dice «sin
          límite». ``None`` significa «usa el default del middleware», no «cero
          requests»: confundir esas dos cosas dejaría fuera al tier que más
          paga.
    """
    with connect_read() as c:
        fila = c.execute(
            "SELECT t.per_minute_limit FROM api_keys k "
            "JOIN api_key_tiers t ON t.tier = k.tier "
            "WHERE k.key_hash = %s AND k.is_active = 1 "
            "LIMIT 1",
            (key_hash,),
        ).fetchone()
    if not fila or not fila[0]:
        return None
    limite = int(fila[0])
    return limite if limite > 0 else None
