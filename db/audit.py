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
from shared.audit_events import es_evento_conocido

log = get_logger(__name__)

_CHAIN_NAME = "audit_log"

#: Fila de ``audit_chain_state`` (misma tabla, otro ``chain_name``: sin migración)
#: que ancla el extremo antiguo de la cadena tras una purga de retención: el
#: ``this_hash`` de la última fila borrada y cuántas filas se han purgado en total.
_PURGE_CHAIN_NAME = "audit_log.purge"

#: Cuánto espera un escritor al candado que serializa la cadena antes de rendirse.
#: Sin techo, cada espera retiene un hilo y una conexión de escritura hasta el
#: ``statement_timeout`` (30 s), y unos pocos eventos concurrentes agotaban el
#: pool para todo lo demás. Al rendirse se pierde un evento de auditoría (que
#: ``log_action`` ya trata como best-effort y deja en el log), no la API.
_AUDIT_LOCK_TIMEOUT_MS = 2000

#: Filas por lote al verificar la cadena (paginación por clave dentro de un snapshot).
_VERIFY_BATCH = 2000


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
    """Serialize appends so concurrent writers cannot fork a chain.

    ``lock_timeout`` y el candado viajan en un solo viaje (protocolo simple, sin
    parámetros) y el ``SET LOCAL`` muere con la transacción.
    """
    connection.execute(
        f"SET LOCAL lock_timeout = {int(_AUDIT_LOCK_TIMEOUT_MS)}; "
        "SELECT pg_advisory_xact_lock(hashtext('tenderflow.audit_log.chain.v1'))"
    )


def _purge_hmac(anchor_hash: str, purged_count: int) -> str:
    """Firma el ancla de purga (dominio propio, distinto del de la cabecera)."""
    return _audit_hmac(f"audit-chain-purge-v1:{anchor_hash}:{purged_count}")


def _read_purge_anchor(connection: Any, *, for_update: bool = False) -> tuple[str, int]:
    """``(hash, filas purgadas)`` del ancla de purga; ``("genesis", 0)`` si nunca se purgó.

    Raises:
        RuntimeError: si la firma no coincide (ancla alterada).
    """
    row = connection.execute(
        "SELECT head_hash, entry_count, state_hmac FROM audit_chain_state WHERE chain_name = %s"
        + (" FOR UPDATE" if for_update else ""),
        (_PURGE_CHAIN_NAME,),
    ).fetchone()
    if row is None:
        return "genesis", 0
    anchor_hash, purged, signature = str(row[0]), int(row[1]), str(row[2])
    if not hmac.compare_digest(signature, _purge_hmac(anchor_hash, purged)):
        raise RuntimeError("audit purge anchor signature mismatch")
    return anchor_hash, purged


def _assert_or_bootstrap_chain_state(connection: Any) -> tuple[str, int, bool]:
    """Return a verified ``(head_hash, count, state_exists)`` tuple.

    Camino caliente (estado ya presente): **no** recuenta ``audit_log``. La
    cardinalidad vive firmada con HMAC en ``audit_chain_state.entry_count``, así
    que se confía en ella tras verificar la firma; el ancla de integridad del
    append es que el ``head_hash`` firmado coincida con el ``this_hash`` de la
    cola (``ORDER BY id DESC LIMIT 1``, índice por PK → O(log n)). El
    ``COUNT(*)`` que se hacía por evento era un seq-scan O(n) de una tabla
    append-only que crece sin límite, ejecutado además bajo el advisory lock
    global que serializa toda la auditoría: cada login/export lo pagaba, y el
    día que cruzara ``statement_timeout`` la auditoría entera empezaría a
    cancelarse. La verificación completa de la cadena (recorrido total) sigue
    disponible en :func:`verify_hash_chain`.
    """
    state_row = connection.execute(
        "SELECT head_hash, entry_count, state_hmac FROM audit_chain_state WHERE chain_name = %s",
        (_CHAIN_NAME,),
    ).fetchone()
    tail_row = connection.execute(
        "SELECT this_hash FROM audit_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    current_head = str(tail_row[0]) if tail_row and tail_row[0] else "genesis"

    if state_row is None:
        # Bootstrap único (aún no hay fila de estado): aquí sí recontamos, una
        # sola vez, para sembrar el ``entry_count`` firmado inicial.
        count_row = connection.execute("SELECT COUNT(*) FROM audit_log").fetchone()
        # Las filas ya purgadas siguen contando en la cardinalidad de la cadena.
        current_count = (int(count_row[0]) if count_row else 0) + _read_purge_anchor(connection)[1]
        return current_head, current_count, False

    stored_head, stored_count, stored_signature = (
        str(state_row[0]),
        int(state_row[1]),
        str(state_row[2]),
    )
    if not hmac.compare_digest(stored_signature, _state_hmac(stored_head, stored_count)):
        raise RuntimeError("audit chain state signature mismatch")
    if stored_head != current_head:
        raise RuntimeError("audit chain head/state does not match audit_log")
    return stored_head, stored_count, True


def log_action(
    user_key: str,
    session_hash: str,
    action: str,
    detail: str = "",
    *,
    user_id: int | None = None,
) -> None:
    """Persiste una acción de usuario en ``audit_log``. No lanza excepciones.

    Calcula un hash chain (SHA-256 del prev_hash + contenido de la fila)
    para permitir verificación de integridad post-hoc si la columna existe.

    Args:
        user_key: Clave opaca del usuario (hash).
        session_hash: Hash truncado de la sesión de usuario.
        action: Nombre de la acción (ver módulo docstring).
        detail: Información adicional en texto libre (sin PII).
        user_id: Identidad interna del actor (v129, ADR-030 §D: la auditoría
            guarda ids). Va en su columna y **fuera del hash**: la cadena
            firma exactamente lo que firmaba antes, así que las filas
            anteriores siguen verificando.
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
            # v129: columna opcional para bases a medio migrar.
            col_uid = ", user_id" if "user_id" in cols_info else ""
            val_uid = ", %s" if col_uid else ""
            params_uid: tuple[int | None, ...] = (user_id,) if col_uid else ()

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
                        "(user_key, session_hash, action, detail, created_at, prev_hash, "
                        f" this_hash, hash_version{col_uid}) "
                        f"VALUES (%s, %s, %s, %s, %s, %s, %s, 'hmac-sha256-v1'{val_uid})",
                        (
                            user_key,
                            session_hash,
                            action,
                            detail,
                            now,
                            prev_hash,
                            this_hash,
                            *params_uid,
                        ),
                    )
                else:
                    c.execute(
                        "INSERT INTO audit_log "
                        "(user_key, session_hash, action, detail, created_at, prev_hash, "
                        f" this_hash{col_uid}) "
                        f"VALUES (%s, %s, %s, %s, %s, %s, %s{val_uid})",
                        (
                            user_key,
                            session_hash,
                            action,
                            detail,
                            now,
                            prev_hash,
                            this_hash,
                            *params_uid,
                        ),
                    )
                if has_chain_state:
                    next_count = entry_count + 1
                    next_signature = _state_hmac(this_hash, next_count)
                    if state_exists:
                        c.execute(
                            "UPDATE audit_chain_state SET head_hash = %s, entry_count = %s, "
                            "state_hmac = %s, updated_at = %s WHERE chain_name = %s",
                            (this_hash, next_count, next_signature, now, _CHAIN_NAME),
                        )
                    else:
                        c.execute(
                            "INSERT INTO audit_chain_state "
                            "(chain_name, head_hash, entry_count, state_hmac, updated_at) "
                            "VALUES (%s, %s, %s, %s, %s)",
                            (_CHAIN_NAME, this_hash, next_count, next_signature, now),
                        )
            else:
                c.execute(
                    "INSERT INTO audit_log "
                    f"(user_key, session_hash, action, detail, created_at{col_uid}) "
                    f"VALUES (%s, %s, %s, %s, %s{val_uid})",
                    (user_key, session_hash, action, detail, now, *params_uid),
                )
    except Exception as exc:
        log.warning("audit_log_persist_failed", action=action, error=str(exc))


# ───────────────── E8: Audit trail expansion ─────────────────────────────

#: Claves de cabecera de ``detail`` (el lector, ``db.repositories.audit``, las
#: reconoce por el mismo nombre). Un payload que empezara por una de ellas se
#: leería como cabecera.
_CLAVES_CABECERA = ("event=", "outcome=", "ip=", "resource=")


def _sin_separador(valor: str) -> str:
    """Quita el separador de campos (``|``) de un valor de cabecera.

    El nombre de una API key o de un webhook, o el expediente de un feedback,
    acaban en ``resource``/``detail``; con un `` | resource=org:7 | `` dentro
    plantaban un evento en el rastro de otra organización. ``¦`` (U+00A6) se
    lee igual y no separa nada.
    """
    return valor.replace("|", "¦")


def componer_detalle(
    event_type: str, outcome: str, ip: str | None, resource: str | None, detail_str: str
) -> str:
    """``detail`` persistido: cabecera ``event | outcome | [ip |] [resource |]`` y payload.

    Los valores de cabecera salen sin ``|`` y un payload que empiece como una
    cabecera se marca con ``detail=``, de modo que la cabecera es inequívoca:
    el filtro por organización (``db.repositories.audit``) solo mira ahí.
    """
    parts: list[str] = [f"event={_sin_separador(event_type)}", f"outcome={_sin_separador(outcome)}"]
    if ip:
        parts.append(f"ip={_sin_separador(ip)}")
    if resource:
        parts.append(f"resource={_sin_separador(resource)}")
    if detail_str:
        parts.append(
            f"detail={detail_str}" if detail_str.startswith(_CLAVES_CABECERA) else detail_str
        )
    return " | ".join(parts)


def log_event(
    *,
    event_type: str,
    actor: str = "",
    user_key: str = "",
    session_hash: str = "",
    outcome: str = "success",
    ip: str | None = None,
    resource: str | None = None,
    detail: str | dict[str, Any] = "",
    user_id: int | None = None,
) -> None:
    """Variante extendida de :func:`log_action` con outcome + ip + resource (E8).

    Args:
        event_type: Categoría del evento (e.g. ``api_key.created``,
            ``webhook.delivery``, ``model.activated``).
        actor: Quién actúa, tal y como se guarda en la columna ``user_key``
            de ``audit_log``: el id del principal en texto, un prefijo de hash
            o ``"system"``. Es el nombre nuevo del parámetro (ADR-030 fase 3):
            lo que se pasa aquí no tiene por qué ser una clave derivada del
            correo, y el nombre viejo obligaba a congelar en el ratchet a
            llamadores que ya pasaban el ``user_id``.
        user_key: Alias **deprecado** de ``actor``, vivo mientras queden
            llamadores sin migrar. Si llegan los dos, manda ``actor``.
        session_hash: Hash de sesión, opcional para eventos de sistema.
        outcome: ``success`` | ``failure`` | ``denied``.
        ip: IP del cliente, ya redactada/truncada si aplica.
        resource: Identificador del recurso afectado (e.g. ``webhook:42``).
        detail: Texto libre o dict serializable. Se persiste como JSON si dict.
        user_id: Identidad interna del actor, si hay principal (v129).

    Diseñado para no lanzar excepciones — auditoría no debe romper la app.
    También incrementa el counter Prometheus ``audit_events_total``.

    El tipo se contrasta con ``shared.audit_events`` de forma **blanda**: un
    tipo fuera del catálogo se registra igual y deja un aviso en el log. Es
    un bug del llamante, no un motivo para perder el rastro.
    """
    import json

    if not es_evento_conocido(event_type):
        log.warning("audit_event_type_unknown", event_type=event_type)

    user_key = actor or user_key
    # Quien ya tiene ``user_id`` no tiene por qué repetirlo como clave: la
    # columna ``user_key`` queda con el id en texto, que es la forma que el
    # backfill de v129 resuelve y la que llevan los llamadores más recientes.
    if not user_key and user_id is not None:
        user_key = str(user_id)

    if isinstance(detail, dict):
        try:
            detail_str = json.dumps(detail, ensure_ascii=False, default=str)[:2000]
        except Exception:
            # El detalle degradado a repr() sigue siendo mejor que perder el
            # evento, pero un detalle no serializable es un bug del llamante.
            log.warning("audit_detail_not_serializable", event_type=event_type, exc_info=True)
            detail_str = str(detail)[:2000]
    else:
        detail_str = str(detail)[:2000]

    log_action(
        user_key=user_key or "system",
        session_hash=session_hash or "-",
        action=event_type,
        detail=componer_detalle(event_type, outcome, ip, resource, detail_str),
        user_id=user_id,
    )

    # Métrica Prometheus (no rompe si runtime_metrics no está disponible)
    try:
        from observability.runtime_metrics import audit_events_total

        audit_events_total.labels(event_type=event_type, outcome=outcome).inc()
    except Exception:
        # La métrica es accesoria (el evento ya está persistido), pero perderla
        # en silencio deja los paneles de auditoría mintiendo por omisión.
        log.debug("audit_metric_unavailable", event_type=event_type, exc_info=True)


def list_recent(
    limit: int = 200,
    *,
    user_key: str | None = None,
    action: str | None = None,
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    """Devuelve entradas recientes del audit log (para el panel de Observabilidad).

    Args:
        limit: Máximo de entradas a devolver.
        user_key: Filtra por usuario si se proporciona.
        action: Filtra por tipo de acción si se proporciona.
        user_id: Filtra por identidad interna (v129); combinado con
            ``user_key`` es la lectura dual, solo o sin clave es ``user_id = %s``.
    """
    clauses: list[str] = []
    params: list[object] = []
    if user_key and user_id is not None:
        clauses.append("(user_id = %s OR (user_key = %s AND user_id IS NULL))")
        params.extend([user_id, user_key])
    elif user_key:
        clauses.append("user_key = %s")
        params.append(user_key)
    elif user_id is not None:
        clauses.append("user_id = %s")
        params.append(user_id)
    if action:
        clauses.append("action = %s")
        params.append(action)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with connect() as c:
        cur = c.execute(
            "SELECT id, user_key, session_hash, action, detail, created_at "
            "FROM audit_log " + where + " ORDER BY created_at DESC, id DESC LIMIT %s",
            params,
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def verify_hash_chain() -> dict[str, object]:
    """Verifica la integridad del audit log recalculando el hash chain.

    Todo se lee dentro de **una** transacción ``REPEATABLE READ``: las filas, el
    recuento, la cabecera firmada y el ancla de purga salen de un mismo
    snapshot, así que una escritura intercalada ya no da un falso
    «manipulación». Las filas se paginan por ``id`` (``_VERIFY_BATCH``) en vez
    de traer la tabla entera a memoria.

    Tras una purga de retención la cadena no arranca en ``genesis`` sino en el
    ancla firmada (``_PURGE_CHAIN_NAME``), y la cardinalidad firmada es
    ``filas vivas + filas purgadas``.

    Returns:
        dict con ``valid`` (bool), ``checked`` (int filas), ``first_tampered_id``
        (int o None) y ``error`` (str o None).
    """
    import json

    from db.database import connect_read

    try:
        with connect_read() as c:
            c.execute("BEGIN ISOLATION LEVEL REPEATABLE READ")
            try:
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
                state_row = None
                expected_prev, purged_count = "genesis", 0
                if has_chain_state:
                    state_row = c.execute(
                        "SELECT head_hash, entry_count, state_hmac FROM audit_chain_state "
                        "WHERE chain_name = %s",
                        (_CHAIN_NAME,),
                    ).fetchone()
                    try:
                        expected_prev, purged_count = _read_purge_anchor(c)
                    except RuntimeError:
                        return {
                            "valid": False,
                            "checked": 0,
                            "first_tampered_id": None,
                            "error": "Firma del ancla de purga de la cadena no coincide",
                        }
                total_row = c.execute("SELECT COUNT(*) FROM audit_log").fetchone()
                total_count = int(total_row[0]) if total_row else 0

                checked = 0
                last_id = 0
                while True:
                    rows = c.execute(
                        "SELECT id, user_key, session_hash, action, detail, created_at, "
                        "prev_hash, this_hash" + version_column + " FROM audit_log "
                        "WHERE id > %s ORDER BY id ASC LIMIT %s",
                        (last_id, _VERIFY_BATCH),
                    ).fetchall()
                    if not rows:
                        break
                    last_id = int(rows[-1][0])
                    for row in rows:
                        row_id, u_key, s_hash, action, detail, created_at, prev_hash, stored = row[
                            :8
                        ]
                        hash_version = row[8] if has_hash_version else None
                        if stored is None:
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

                        if expected != stored:
                            return {
                                "valid": False,
                                "checked": row_id,
                                "first_tampered_id": row_id,
                                "error": f"Hash no coincide en fila id={row_id}",
                            }
                        expected_prev = str(stored)
                        checked += 1
            finally:
                try:
                    c.rollback()
                except Exception:
                    # Sin ROLLBACK la conexión vuelve al pool con la transacción
                    # abierta; el pool la revierte (y avisa) o la descarta.
                    log.debug("audit_verify_rollback_failed", exc_info=True)

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
            # Sin filas ``expected_prev`` es la raíz («genesis» o el ancla de purga),
            # que la cabecera solo iguala si la tabla estaba vacía de verdad.
            if state_head != expected_prev or state_count != total_count + purged_count:
                return {
                    "valid": False,
                    "checked": checked,
                    "first_tampered_id": None,
                    "error": "La cabecera anclada no coincide con audit_log",
                }

        return {"valid": True, "checked": checked, "first_tampered_id": None, "error": None}

    except Exception as exc:
        # `valid: None` viaja hasta /security/audit/verify como "no se pudo
        # comprobar". Sin log no se distingue una cadena rota de un fallo al
        # leerla, que es justo la diferencia que importa en una auditoría.
        log.warning("audit_hash_chain_verify_failed", exc_info=True)
        return {"valid": None, "checked": 0, "first_tampered_id": None, "error": str(exc)}


def purgar_extremo_antiguo(cutoff: str, *, apply: bool) -> int:
    """Purga las filas de ``audit_log`` anteriores a ``cutoff`` sin romper la cadena.

    Un ``DELETE ... WHERE created_at < cutoff`` a secas dejaba la verificación en
    ``valid=false`` para siempre: la cadena ya no arrancaba en ``genesis`` y la
    cardinalidad firmada ya no cuadraba con ``COUNT(*)``. Aquí se borra solo el
    **prefijo** por ``id`` (nunca el medio, y siempre se conserva la última fila,
    de la que cuelga la cabecera firmada) y, en la misma transacción, se firma un
    ancla (``_PURGE_CHAIN_NAME``): el ``this_hash`` de la última fila borrada y
    cuántas filas se han purgado. ``verify_hash_chain`` arranca desde ella.

    Se niega (``RuntimeError``) a purgar si la cadena no es continua en la
    frontera o si la cabecera firmada no cuadra con la cola: reanclar encima de
    una rotura la blanquearía. El total purgado se calcula contra la cabecera
    firmada (``total histórico - filas vivas``), así que también cura una BD
    cuyas filas viejas ya se borraron con el ``DELETE`` anterior.

    Con la cadena sin migrar (sin ``prev_hash``/``this_hash`` o sin
    ``audit_chain_state``) es el borrado por fecha de siempre.

    Returns:
        Filas que se borran (``apply=True``) o se borrarían (dry-run).
    """
    with connect() as c:
        cols_info = _get_cols(c, "audit_log")
        if not ({"prev_hash", "this_hash"} <= cols_info and _get_cols(c, "audit_chain_state")):
            plain = c.execute(
                "SELECT COUNT(*) FROM audit_log WHERE created_at < %s", (cutoff,)
            ).fetchone()
            if apply and plain and plain[0]:
                c.execute("DELETE FROM audit_log WHERE created_at < %s", (cutoff,))
            return int(plain[0]) if plain else 0

        anchor_hash, already_purged = _read_purge_anchor(c, for_update=apply)
        newer = c.execute(
            "SELECT MIN(id) FROM audit_log WHERE created_at >= %s", (cutoff,)
        ).fetchone()
        if newer and newer[0] is not None:
            cut_id = int(newer[0])
        else:  # todo es anterior al plazo: se conserva la cola
            tail = c.execute("SELECT MAX(id) FROM audit_log").fetchone()
            cut_id = int(tail[0]) if tail and tail[0] is not None else 0
        count_row = c.execute("SELECT COUNT(*) FROM audit_log WHERE id < %s", (cut_id,)).fetchone()
        count = int(count_row[0]) if count_row else 0
        if not apply or count == 0:
            return count

        last_deleted = c.execute(
            "SELECT this_hash FROM audit_log WHERE id < %s AND this_hash IS NOT NULL "
            "ORDER BY id DESC LIMIT 1",
            (cut_id,),
        ).fetchone()
        new_anchor = str(last_deleted[0]) if last_deleted else anchor_hash
        survivor = c.execute(
            "SELECT prev_hash FROM audit_log WHERE id >= %s AND this_hash IS NOT NULL "
            "ORDER BY id ASC LIMIT 1",
            (cut_id,),
        ).fetchone()
        if survivor is None or str(survivor[0] or "genesis") != new_anchor:
            raise RuntimeError("audit chain is not continuous at the purge boundary")

        c.execute("DELETE FROM audit_log WHERE id < %s", (cut_id,))
        # Bajo el mismo candado que los escritores: la cabecera y el recuento
        # tienen que ser del mismo instante. El candado cae con el commit, justo
        # después (esta conexión es solo de la purga del audit_log).
        _serialize_audit_chain_write(c)
        _head, total_ever, state_exists = _assert_or_bootstrap_chain_state(c)
        live_row = c.execute("SELECT COUNT(*) FROM audit_log").fetchone()
        # Sin cabecera firmada no hay total histórico contra el que calcular.
        purged_total = (
            total_ever - (int(live_row[0]) if live_row else 0)
            if state_exists
            else already_purged + count
        )
        c.execute(
            "INSERT INTO audit_chain_state (chain_name, head_hash, entry_count, state_hmac, "
            "updated_at) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (chain_name) DO UPDATE SET "
            "head_hash = EXCLUDED.head_hash, entry_count = EXCLUDED.entry_count, "
            "state_hmac = EXCLUDED.state_hmac, updated_at = EXCLUDED.updated_at",
            (
                _PURGE_CHAIN_NAME,
                new_anchor,
                purged_total,
                _purge_hmac(new_anchor, purged_total),
                now_utc_iso(),
            ),
        )
        return count
