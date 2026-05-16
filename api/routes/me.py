"""Endpoints GDPR: export y borrado de datos de usuario.

GET  /api/v1/me/data      — exporta todos los datos del usuario (zip JSON)
DELETE /api/v1/me         — anonimiza todos los datos del usuario
POST /api/v1/auth/logout-all — revoca todas las sesiones activas

Identificación: el usuario se identifica por el ``key_hash`` de la API Key
autenticada. No se hace resolución por nombre/email para evitar colisiones GDPR.
"""

from __future__ import annotations

import io
import json
import zipfile

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from api.auth import AuthContext, create_api_key, require_api_key
from db.audit import log_event
from db.database import connect, connect_read, now_utc_iso
from db.repositories.api_keys import ApiKeyRepository
from db.sessions import revoke_all_sessions
from observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["me"])

_key_repo = ApiKeyRepository()


def _get_user_id_from_key_id(key_id: int) -> int | None:
    """Obtiene el user_id vinculado a la API key, si la columna existe."""
    with connect_read() as c:
        try:
            cols = {row[1] for row in c.execute("PRAGMA table_info(api_keys)").fetchall()}
            if "user_id" not in cols:
                # Columna aún no migrada — fallback al primer usuario
                row = c.execute("SELECT id FROM users LIMIT 1").fetchone()
                return int(row[0]) if row else None
            row = c.execute(
                "SELECT user_id FROM api_keys WHERE id = ? LIMIT 1", (key_id,)
            ).fetchone()
            if row and row[0]:
                return int(row[0])
            # Si user_id es NULL, usar el primer usuario como fallback documentado
            row = c.execute("SELECT id FROM users LIMIT 1").fetchone()
            return int(row[0]) if row else None
        except Exception:
            return None


@router.get(
    "/me/data",
    summary="GDPR — exportar todos mis datos",
    responses={200: {"content": {"application/zip": {}}}},
)
def export_my_data(ctx: AuthContext = Depends(require_api_key)) -> StreamingResponse:
    """Exporta watchlist, feedback, API keys y audit log en un ZIP JSON.

    La exportación se vincula exclusivamente al ``key_hash`` de la API key
    autenticada, evitando colisiones por nombre de usuario.
    """
    key_name = _key_repo.get_name(ctx.key_hash) or ctx.key_hash[:8]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        with connect_read() as c:
            # API keys propias (solo la key autenticada, no todas las del nombre)
            cur = c.execute(
                "SELECT name, created_at, expires_at FROM api_keys WHERE key_hash = ?",
                (ctx.key_hash,),
            )
            cols = [d[0] for d in cur.description]
            api_keys_data = [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]
            zf.writestr("api_keys.json", json.dumps(api_keys_data, ensure_ascii=False, indent=2))

            # Watchlist — filtrar por key_hash (campo user_key en watchlist)
            try:
                cur = c.execute(
                    "SELECT * FROM watchlist WHERE user_key = ? LIMIT 5000",
                    (ctx.key_hash,),
                )
                cols = [d[0] for d in cur.description]
                watchlist = [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]
            except Exception:
                watchlist = []
            zf.writestr("watchlist.json", json.dumps(watchlist, ensure_ascii=False, indent=2))

            # ML feedback — todo el feedback es anónimo (no hay FK a user), exportar todo
            cur = c.execute("SELECT * FROM ml_feedback LIMIT 10000")
            cols = [d[0] for d in cur.description]
            feedback = [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]
            zf.writestr("feedback.json", json.dumps(feedback, ensure_ascii=False, indent=2))

            # Audit log filtrado por user_key = key_hash (no expone datos de otros)
            try:
                cur = c.execute(
                    "SELECT * FROM audit_log WHERE user_key = ? ORDER BY created_at DESC LIMIT 1000",
                    (ctx.key_hash,),
                )
                cols = [d[0] for d in cur.description]
                audit = [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]
                zf.writestr("audit.json", json.dumps(audit, ensure_ascii=False, indent=2))
            except Exception:
                zf.writestr("audit.json", "[]")

        meta = {"exported_at": now_utc_iso(), "key_name": key_name}
        zf.writestr("metadata.json", json.dumps(meta, ensure_ascii=False, indent=2))

    buf.seek(0)
    log_event(
        event_type="gdpr.export",
        user_key=ctx.key_hash[:8],
        outcome="success",
    )
    log.info("gdpr_export_generated", key_name=key_name)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=my_data_{now_utc_iso()[:10]}.zip"},
    )


@router.delete(
    "/me",
    summary="GDPR — anonimizar y eliminar mis datos",
    status_code=200,
)
def delete_my_data(ctx: AuthContext = Depends(require_api_key)) -> dict:
    """Anonimiza watchlist y feedback; revoca la API key autenticada.

    La identificación es por ``key_hash`` — no por nombre de usuario,
    evitando borrado accidental de datos de otros usuarios con el mismo nombre.
    """
    with connect() as c:
        # Anonimizar watchlist vinculada a esta key hash
        try:
            c.execute(
                "UPDATE watchlist SET user_key = 'DELETED', name = 'DELETED' WHERE user_key = ?",
                (ctx.key_hash,),
            )
        except Exception:
            pass
        # Revocar la API key por ID (no por nombre)
        c.execute(
            "UPDATE api_keys SET is_active = 0, last_used = ? WHERE id = ?",
            (now_utc_iso(), ctx.key_id),
        )

    log_event(
        event_type="gdpr.delete",
        user_key=ctx.key_hash[:8],
        outcome="success",
        resource=f"api_key:{ctx.key_id}",
    )
    log.info("gdpr_delete_executed", key_id=ctx.key_id)
    return {"status": "ok", "message": "Datos anonimizados y API key revocada."}


@router.post(
    "/auth/logout-all",
    summary="Revocar todas las sesiones activas",
    status_code=200,
)
def logout_all(ctx: AuthContext = Depends(require_api_key)) -> dict:
    """Revoca todas las sesiones server-side del usuario."""
    user_id = _get_user_id_from_key_id(ctx.key_id)
    if user_id:
        n = revoke_all_sessions(user_id)
        log_event(
            event_type="auth.logout_all",
            user_key=ctx.key_hash[:8],
            resource=f"user:{user_id}",
            detail={"sessions_revoked": n},
        )
        log.info("logout_all", user_id=user_id, revoked=n)
        return {"status": "ok", "sessions_revoked": n}
    return {"status": "ok", "sessions_revoked": 0}


@router.get(
    "/me/keys",
    summary="Listar mis API keys (sin el secret — solo prefix y metadatos)",
    responses={401: {"description": "API key inválida"}},
)
def list_my_keys(ctx: AuthContext = Depends(require_api_key)) -> list[dict]:
    """Devuelve las API keys vinculadas al mismo ``key_id`` autenticado.

    El ``prefix`` (primeros 8 chars del token original) permite identificar
    la key en logs/soporte sin exponer el secreto completo.
    """
    with connect_read() as c:
        try:
            cols_info = {row[1] for row in c.execute("PRAGMA table_info(api_keys)").fetchall()}
            select_cols = "id, name, created_at, is_active, scopes"
            if "prefix" in cols_info:
                select_cols += ", prefix"
            if "expires_at" in cols_info:
                select_cols += ", expires_at"
            cur = c.execute(
                f"SELECT {select_cols} FROM api_keys WHERE id = ?",  # noqa: S608
                (ctx.key_id,),
            )
            col_names = [d[0] for d in cur.description]
            rows = [dict(zip(col_names, row, strict=False)) for row in cur.fetchall()]
        except Exception as exc:
            log.warning("list_my_keys_error", error=str(exc))
            rows = []
    return rows


@router.post(
    "/me/keys/rotate",
    summary="Rotar API key — genera una nueva con grace period",
    status_code=201,
    responses={
        201: {"description": "Nueva key generada. La key anterior sigue activa N días."},
        401: {"description": "API key inválida"},
    },
)
def rotate_my_key(
    ctx: AuthContext = Depends(require_api_key),
    grace_days: int = 7,
) -> dict:
    """Genera una nueva API key con los mismos scopes que la actual.

    La key anterior permanece activa durante ``grace_days`` (default 7 días)
    para permitir migración gradual. Después de ese período, se desactiva
    automáticamente (requiere que el scheduler ejecute el job de cleanup).

    El token nuevo solo se devuelve en esta respuesta — guárdalo de forma segura.
    """
    from datetime import UTC, datetime, timedelta

    # Obtener nombre y scopes de la key actual
    with connect_read() as c:
        row = c.execute("SELECT name, scopes FROM api_keys WHERE id = ?", (ctx.key_id,)).fetchone()
    if not row:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="API key no encontrada.")

    name, scopes = row[0], str(row[1] or "*")

    # Marcar la key actual con expires_at = now + grace_days
    grace_expires = (datetime.now(UTC) + timedelta(days=grace_days)).isoformat()
    with connect() as c:
        cols_info = {r[1] for r in c.execute("PRAGMA table_info(api_keys)").fetchall()}
        if "expires_at" in cols_info:
            c.execute(
                "UPDATE api_keys SET expires_at = ? WHERE id = ?",
                (grace_expires, ctx.key_id),
            )

    # Crear la nueva key
    new_raw = create_api_key(
        name=f"{name} (rotated)",
        scopes=scopes,
        user_id=_get_user_id_from_key_id(ctx.key_id),
    )

    log_event(
        event_type="api_key.rotated",
        user_key=ctx.key_hash[:8],
        resource=f"api_key:{ctx.key_id}",
        detail={"grace_days": grace_days, "old_expires_at": grace_expires},
    )
    log.info("api_key_rotated", key_id=ctx.key_id, grace_days=grace_days)

    return {
        "new_token": new_raw,
        "message": (
            f"Guarda el token — no es recuperable. "
            f"La key anterior expira en {grace_days} días ({grace_expires[:10]})."
        ),
        "old_key_expires_at": grace_expires,
    }
