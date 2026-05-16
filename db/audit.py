"""Registro de auditoría para acciones de usuario en el dashboard.

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

from typing import Any

from db.database import connect, now_utc_iso
from observability.logging import get_logger

log = get_logger(__name__)


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
        session_hash: Hash truncado de la sesión Streamlit.
        action: Nombre de la acción (ver módulo docstring).
        detail: Información adicional en texto libre (sin PII).
    """
    import hashlib
    import json

    try:
        now = now_utc_iso()
        with connect() as c:
            # Detectar si la tabla tiene columnas de hash chain (migración 26)
            cols_info = {r[1] for r in c.execute("PRAGMA table_info(audit_log)").fetchall()}
            has_hash_chain = "prev_hash" in cols_info and "this_hash" in cols_info

            if has_hash_chain:
                # Obtener el hash del último registro
                prev_row = c.execute(
                    "SELECT this_hash FROM audit_log ORDER BY id DESC LIMIT 1"
                ).fetchone()
                prev_hash = str(prev_row[0]) if prev_row and prev_row[0] else "genesis"

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
                this_hash = hashlib.sha256(
                    f"{prev_hash}{row_json}".encode()
                ).hexdigest()

                c.execute(
                    "INSERT INTO audit_log "
                    "(user_key, session_hash, action, detail, created_at, prev_hash, this_hash) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_key, session_hash, action, detail, now, prev_hash, this_hash),
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
            f"SELECT id, user_key, session_hash, action, detail, created_at "  # noqa: S608
            f"FROM audit_log {where} ORDER BY created_at DESC LIMIT ?",
            params,
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def verify_hash_chain() -> dict:
    """Verifica la integridad del audit log recalculando el hash chain.

    Returns:
        dict con ``valid`` (bool), ``checked`` (int filas), ``first_tampered_id``
        (int o None) y ``error`` (str o None).
    """
    import hashlib
    import json

    from db.database import connect_read

    try:
        with connect_read() as c:
            cols_info = {r[1] for r in c.execute("PRAGMA table_info(audit_log)").fetchall()}
            if "prev_hash" not in cols_info or "this_hash" not in cols_info:
                return {
                    "valid": None,
                    "checked": 0,
                    "first_tampered_id": None,
                    "error": "Hash chain no disponible (migración 26 pendiente)",
                }

            rows = c.execute(
                "SELECT id, user_key, session_hash, action, detail, created_at, prev_hash, this_hash "
                "FROM audit_log ORDER BY id ASC"
            ).fetchall()

        if not rows:
            return {"valid": True, "checked": 0, "first_tampered_id": None, "error": None}

        for row in rows:
            row_id, u_key, s_hash, action, detail, created_at, prev_hash, stored_hash = row
            if stored_hash is None:
                continue  # Filas anteriores a migración 26 — skip

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
            expected = hashlib.sha256(
                f"{prev_hash or 'genesis'}{row_json}".encode()
            ).hexdigest()

            if expected != stored_hash:
                return {
                    "valid": False,
                    "checked": row_id,
                    "first_tampered_id": row_id,
                    "error": f"Hash no coincide en fila id={row_id}",
                }

        return {"valid": True, "checked": len(rows), "first_tampered_id": None, "error": None}

    except Exception as exc:
        return {"valid": None, "checked": 0, "first_tampered_id": None, "error": str(exc)}
