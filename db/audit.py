"""Registro de auditoría para acciones de usuario.

Las acciones se persisten en ``audit_log`` y permiten trazabilidad de
quién hizo qué sin almacenar PII directa (se usa ``user_key`` opaco y
``session_hash`` truncado).

Acciones estándar:
    ``login``              — autenticación exitosa
    ``login_failed``       — intento fallido de autenticación
    ``logout``             — cierre de sesión explícito
    ``watchlist_add``      — entrada añadida a la watchlist
    ``watchlist_delete``   — entrada eliminada de la watchlist
    ``export_excel``       — exportación a Excel
    ``export_pdf``         — exportación a PDF
"""

from __future__ import annotations

import hmac
from typing import Any

from db.database import connect, now_utc_iso
from db.database import get_table_columns as _get_cols
from observability.logging import get_logger

log = get_logger(__name__)

_CHAIN_NAME = "audit_log"


def _audit_hmac(value: str) -> str:
    """Firma la cadena con una clave fuera de la base de datos."""
    import hashlib
    import hmac

    from config import settings

    key = settings.AUDIT_HMAC_KEY.get_secret_value()
    if not key and settings.ENV == "dev":
        key = "development-only-audit-key"
    if not key:
        raise RuntimeError("AUDIT_HMAC_KEY is not configured")
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def _state_hmac(head_hash: str, entry_count: int) -> str:
    """Sign the independently persisted chain head and cardinality."""
    return _audit_hmac(f"audit-chain-state-v1:{head_hash}:{entry_count}")


def _serialize_audit_chain_write(connection: Any) -> None:
    """Serialize appends on Postgres so concurrent writers cannot fork a chain."""
    from db.connection import is_postgres_backend

    if is_postgres_backend():
        connection.execute("SELECT pg_advisory_xact_lock(hashtext('tenderflow.audit_log.chain.v1'))")


def _assert_or_bootstrap_chain_state(connection: Any) -> tuple[str, int, bool]:
    """Return a verified ``(head_hash, count, state_exists)`` tuple."""
    state_row = connection.execute(
        "SELECT head_hash, entry_count, state_hmac FROM audit_chain_state WHERE chain_name = ?",
        (_CHAIN_NAME,),
    ).fetchone()
    tail_row = connection.execute(
        "SELECT this_hash FROM audit_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    count_row = connection.execute("SELECT COUNT(*) FROM audit_log").fetchone()
    current_head = str(tail_row[0]) if tail_row and tail_row[0] else "genesis"
    current_count = int(count_row[0]) if count_row else 0
    if state_row is None:
        return current_head, current_count, False

    stored_head, stored_count, stored_signature = (
        str(state_row[0]),
        int(state_row[1]),
        str(state_row[2]),
    )
    if not hmac.compare_digest(stored_signature, _state_hmac(stored_head, stored_count)):
        raise RuntimeError("audit chain state signature mismatch")
    if stored_head != current_head or stored_count != current_count:
        raise RuntimeError("audit chain head/state does not match audit_log")
    return stored_head, stored_count, True


def log_action(
    user_key: str,
    session_hash: str,
    action: str,
    detail: str = "",
) -> None:
    """Persiste una acción de usuario en ``audit_log``. No lanza excepciones.

    Calcula un hash chain (SHA-256 del prev_hash + contenido de la fila)
    para permitir verificación de integridad post-hoc si la columna existe.

    Args:
        user_key: Clave opaca del usuario (hash).
        session_hash: Hash truncado de la sesión de usuario.
        action: Nombre de la acción (ver módulo docstring).
        detail: Información adicional en texto libre (sin PII).
    """
    import json

    try:
        now = now_utc_iso()
        with connect() as c:
            # Detectar si la tabla tiene columnas de hash chain (migración 26)
            cols_info = _get_cols(c, "audit_log")
            has_hash_chain = "prev_hash" in cols_info and "this_hash" in cols_info
            has_hash_version = "hash_version" in cols_info
            has_chain_state = bool(_get_cols(c, "audit_chain_state"))

            if has_hash_chain:
                _serialize_audit_chain_write(c)
                if has_chain_state:
                    prev_hash, entry_count, state_exists = _assert_or_bootstrap_chain_state(c)
                else:
                    prev_row = c.execute(
                        "SELECT this_hash FROM audit_log ORDER BY id DESC LIMIT 1"
                    ).fetchone()
                    prev_hash = str(prev_row[0]) if prev_row and prev_row[0] else "genesis"
                    entry_count = 0
                    state_exists = False

                # Calcular this_hash
                row_json = json.dumps(
                    {
                        "user_key": user_key,
                        "session_hash": session_hash,
                        "action": action,
                        "detail": detail,
                        "created_at": now,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                this_hash = _audit_hmac(f"{prev_hash}{row_json}")
                if has_hash_version:
                    c.execute(
                        "INSERT INTO audit_log "
                        "(user_key, session_hash, action, detail, created_at, prev_hash, this_hash, hash_version) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, 'hmac-sha256-v1')",
                        (user_key, session_hash, action, detail, now, prev_hash, this_hash),
                    )
                else:
                    c.execute(
                        "INSERT INTO audit_log "
                        "(user_key, session_hash, action, detail, created_at, prev_hash, this_hash) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (user_key, session_hash, action, detail, now, prev_hash, this_hash),
                    )
                if has_chain_state:
                    next_count = entry_count + 1
                    next_signature = _state_hmac(this_hash, next_count)
                    if state_exists:
                        c.execute(
                            "UPDATE audit_chain_state SET head_hash = ?, entry_count = ?, "
                            "state_hmac = ?, updated_at = ? WHERE chain_name = ?",
                            (this_hash, next_count, next_signature, now, _CHAIN_NAME),
                        )
                    else:
                        c.execute(
                            "INSERT INTO audit_chain_state "
                            "(chain_name, head_hash, entry_count, state_hmac, updated_at) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (_CHAIN_NAME, this_hash, next_count, next_signature, now),
                        )
            else:
                c.execute(
                    "INSERT INTO audit_log (user_key, session_hash, action, detail, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user_key, session_hash, action, detail, now),
                )
    except Exception as exc:
        log.warning("audit_log_persist_failed", action=action, error=str(exc))


# ───────────────── E8: Audit trail expansion ─────────────────────────────


def log_event(
    *,
    event_type: str,
    user_key: str = "",
    session_hash: str = "",
    outcome: str = "success",
    ip: str | None = None,
    resource: str | None = None,
    detail: str | dict[str, Any] = "",
) -> None:
    """Variante extendida de :func:`log_action` con outcome + ip + resource (E8).

    Args:
        event_type: Categoría del evento (e.g. ``api_key.created``,
            ``webhook.delivery``, ``model.activated``).
        user_key: Clave opaca del usuario (hash) o ``"system"``.
        session_hash: Hash de sesión, opcional para eventos de sistema.
        outcome: ``success`` | ``failure`` | ``denied``.
        ip: IP del cliente, ya redactada/truncada si aplica.
        resource: Identificador del recurso afectado (e.g. ``webhook:42``).
        detail: Texto libre o dict serializable. Se persiste como JSON si dict.

    Diseñado para no lanzar excepciones — auditoría no debe romper la app.
    También incrementa el counter Prometheus ``audit_events_total``.
    """
    import json

    if isinstance(detail, dict):
        try:
            detail_str = json.dumps(detail, ensure_ascii=False, default=str)[:2000]
        except Exception:
            detail_str = str(detail)[:2000]
    else:
        detail_str = str(detail)[:2000]

    parts: list[str] = [f"event={event_type}", f"outcome={outcome}"]
    if ip:
        parts.append(f"ip={ip}")
    if resource:
        parts.append(f"resource={resource}")
    if detail_str:
        parts.append(detail_str)
    structured_detail = " | ".join(parts)

    log_action(
        user_key=user_key or "system",
        session_hash=session_hash or "-",
        action=event_type,
        detail=structured_detail,
    )

    # Métrica Prometheus (no rompe si runtime_metrics no está disponible)
    try:
        from observability.runtime_metrics import audit_events_total

        audit_events_total.labels(event_type=event_type, outcome=outcome).inc()
    except Exception:
        pass


def list_recent(
    limit: int = 200,
    *,
    user_key: str | None = None,
    action: str | None = None,
) -> list[dict[str, Any]]:
    """Devuelve entradas recientes del audit log (para el panel de Observabilidad).

    Args:
        limit: Máximo de entradas a devolver.
        user_key: Filtra por usuario si se proporciona.
        action: Filtra por tipo de acción si se proporciona.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if user_key:
        clauses.append("user_key = ?")
        params.append(user_key)
    if action:
        clauses.append("action = ?")
        params.append(action)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with connect() as c:
        cur = c.execute(
            "SELECT id, user_key, session_hash, action, detail, created_at "
            "FROM audit_log " + where + " ORDER BY created_at DESC, id DESC LIMIT ?",
            params,
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def verify_hash_chain() -> dict[str, object]:
    """Verifica la integridad del audit log recalculando el hash chain.

    Returns:
        dict con ``valid`` (bool), ``checked`` (int filas), ``first_tampered_id``
        (int o None) y ``error`` (str o None).
    """
    import json

    from db.database import connect_read

    try:
        with connect_read() as c:
            cols_info = _get_cols(c, "audit_log")
            if "prev_hash" not in cols_info or "this_hash" not in cols_info:
                return {
                    "valid": None,
                    "checked": 0,
                    "first_tampered_id": None,
                    "error": "Hash chain no disponible (migración 26 pendiente)",
                }

            has_hash_version = "hash_version" in cols_info
            has_chain_state = bool(_get_cols(c, "audit_chain_state"))
            version_column = ", hash_version" if has_hash_version else ""
            rows = c.execute(
                "SELECT id, user_key, session_hash, action, detail, created_at, prev_hash, this_hash"
                + version_column
                + " FROM audit_log ORDER BY id ASC"
            ).fetchall()
            total_row = c.execute("SELECT COUNT(*) FROM audit_log").fetchone()
            state_row = None
            if has_chain_state:
                state_row = c.execute(
                    "SELECT head_hash, entry_count, state_hmac FROM audit_chain_state "
                    "WHERE chain_name = ?",
                    (_CHAIN_NAME,),
                ).fetchone()

        if not rows:
            if state_row is not None:
                state_head, state_count, state_signature = (
                    str(state_row[0]),
                    int(state_row[1]),
                    str(state_row[2]),
                )
                if (
                    not hmac.compare_digest(state_signature, _state_hmac(state_head, state_count))
                    or state_head != "genesis"
                    or state_count != 0
                ):
                    return {
                        "valid": False,
                        "checked": 0,
                        "first_tampered_id": None,
                        "error": "La cabecera anclada no coincide con audit_log",
                    }
            return {"valid": True, "checked": 0, "first_tampered_id": None, "error": None}

        expected_prev = "genesis"
        checked = 0
        for row in rows:
            row_id, u_key, s_hash, action, detail, created_at, prev_hash, stored_hash = row[:8]
            hash_version = row[8] if has_hash_version else None
            if stored_hash is None:
                continue  # Filas anteriores a migración 26 — skip

            actual_prev = str(prev_hash or "genesis")
            if actual_prev != expected_prev:
                return {
                    "valid": False,
                    "checked": checked,
                    "first_tampered_id": row_id,
                    "error": f"Cadena interrumpida en fila id={row_id}",
                }

            row_json = json.dumps(
                {
                    "user_key": u_key or "",
                    "session_hash": s_hash or "",
                    "action": action or "",
                    "detail": detail or "",
                    "created_at": created_at or "",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            chain_data = f"{actual_prev}{row_json}"
            if hash_version == "hmac-sha256-v1":
                expected = _audit_hmac(chain_data)
            else:
                import hashlib

                expected = hashlib.sha256(chain_data.encode()).hexdigest()

            if expected != stored_hash:
                return {
                    "valid": False,
                    "checked": row_id,
                    "first_tampered_id": row_id,
                    "error": f"Hash no coincide en fila id={row_id}",
                }
            expected_prev = str(stored_hash)
            checked += 1

        if state_row is not None:
            state_head, state_count, state_signature = (
                str(state_row[0]),
                int(state_row[1]),
                str(state_row[2]),
            )
            if not hmac.compare_digest(state_signature, _state_hmac(state_head, state_count)):
                return {
                    "valid": False,
                    "checked": checked,
                    "first_tampered_id": None,
                    "error": "Firma del estado de la cadena de auditoría no coincide",
                }
            total_count = int(total_row[0]) if total_row else 0
            if state_head != expected_prev or state_count != total_count:
                return {
                    "valid": False,
                    "checked": checked,
                    "first_tampered_id": None,
                    "error": "La cabecera anclada no coincide con audit_log",
                }

        return {"valid": True, "checked": checked, "first_tampered_id": None, "error": None}

    except Exception as exc:
        return {"valid": None, "checked": 0, "first_tampered_id": None, "error": str(exc)}
