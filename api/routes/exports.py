"""Endpoint de exportación asíncrona a PDF (F5).

Flujo:
  1. ``POST /exports`` — crea un job, lo encola como BackgroundTask,
     devuelve ``{"id": "...", "status": "pending"}``.
  2. ``GET /exports/{id}`` — sondea el estado. Devuelve PDF bytes cuando
     el job está ``done``, o ``{"status": "pending"|"error"}``.
  3. ``DELETE /exports/{id}`` — elimina el job de la memoria.

El PDF se genera con ``reportlab`` (ya en dependencies del proyecto).
"""

from __future__ import annotations

import io
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from api.auth import AuthContext, require_api_key
from api.routes.auth import get_current_session_user
from observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/exports", tags=["exports"])

# ── Almacén en memoria (proceso) ─────────────────────────────────────────────
# Sólo lo usan los endpoints de job asíncrono, ya deprecados en favor de
# `GET /exports/download?format=pdf` (ver la nota en `create_export`). La
# premisa "instancia única que no se reinicia" que lo hacía aceptable no se
# sostiene en el despliegue real, y por eso el camino síncrono es el
# recomendado. TTL = 15 min, max 100 jobs concurrentes.

_TTL_SECONDS = 900
_MAX_JOBS = 100
_store: dict[str, dict[str, Any]] = {}
_store_lock = threading.Lock()


def _gc_store() -> None:
    """Elimina jobs expirados (>TTL) y trunca si excede maxsize."""
    with _store_lock:
        now = time.monotonic()
        expired = [k for k, v in _store.items() if now - v["created_at"] > _TTL_SECONDS]
        for k in expired:
            del _store[k]
        # Si aún excede el máximo tras limpiar expirados, eliminar los más antiguos
        if len(_store) > _MAX_JOBS:
            sorted_jobs = sorted(_store.items(), key=lambda kv: kv[1]["created_at"])
            overflow = len(_store) - _MAX_JOBS
            for k, _ in sorted_jobs[:overflow]:
                del _store[k]
                log.warning("export_pdf.store_overflow_evicted", job_id=k)


# ── Generador PDF ─────────────────────────────────────────────────────────────


def _build_pdf(rows: list[dict[str, Any]], title: str) -> bytes:
    """Genera un PDF tabular simple con reportlab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), rightMargin=20, leftMargin=20)
    styles = getSampleStyleSheet()
    story: list[Any] = []

    story.append(Paragraph(title, styles["Title"]))
    story.append(
        Paragraph(datetime.now(UTC).strftime("Generado: %Y-%m-%d %H:%M UTC"), styles["Normal"])
    )
    story.append(Spacer(1, 12))

    if not rows:
        story.append(Paragraph("Sin resultados.", styles["Normal"]))
    else:
        keys = list(rows[0].keys())
        header = [str(k) for k in keys]
        table_data = [header] + [[str(r.get(k, "")) for k in keys] for r in rows[:500]]

        col_widths = [max(len(str(r[i])) for r in table_data) * 5.5 for i in range(len(keys))]
        col_widths = [max(40.0, min(w, 180.0)) for w in col_widths]

        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a5276")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#eaf0fb")],
                    ),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#aab7c4")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(t)

    doc.build(story)
    return buf.getvalue()


# ── Background worker ─────────────────────────────────────────────────────────


def _run_export(job_id: str, filters: dict[str, Any]) -> None:
    """Ejecutado en BackgroundTask: consulta la BD y genera el PDF."""
    _store[job_id]["status"] = "running"
    try:
        from services.licitaciones import fetch_for_pdf

        rows = fetch_for_pdf(
            ccaa=filters.get("ccaa"),
            estado=filters.get("estado"),
            q=filters.get("q"),
        )

        title = "Licitaciones SAP — Exportación"
        if filters.get("ccaa"):
            title += f" ({filters['ccaa']})"

        pdf_bytes = _build_pdf(rows, title)
        _store[job_id]["pdf"] = pdf_bytes
        _store[job_id]["status"] = "done"
        _store[job_id]["n_rows"] = len(rows)
        log.info("export_pdf.done", job_id=job_id, n_rows=len(rows), bytes=len(pdf_bytes))
    except Exception as exc:
        _store[job_id]["status"] = "error"
        _store[job_id]["error"] = str(exc)
        log.warning("export_pdf.error", job_id=job_id, error=str(exc))


# ── Endpoints ─────────────────────────────────────────────────────────────────


class ExportJobStatus(BaseModel):
    """Estado del job de exportación asíncrona (202 + sondeo)."""

    id: str
    status: str


@router.post("", status_code=202, deprecated=True)
def create_export(
    background_tasks: BackgroundTasks,
    ccaa: str | None = None,
    estado: str | None = None,
    q: str | None = None,
    ctx: AuthContext = Depends(require_api_key),
) -> ExportJobStatus:
    """Crea un job de exportación PDF asíncrono.

    .. deprecated::
       Usá ``GET /exports/download?format=pdf``, que devuelve el PDF en la
       propia respuesta.

       El job vive en un dict **de proceso** con los bytes del PDF en memoria.
       Eso sólo funciona con una única instancia que además no se reinicie:
       cualquier deploy o reinicio de la instancia (el plan de pago de Render
       ya no hiberna por inactividad, pero sí recicla en cada release) hace
       desaparecer un job aceptado con 202 y el sondeo devuelve 404 sin que
       nada lo registre como fallo; y al escalar a dos instancias el poll cae
       en la equivocada y responde 404 o 403 de forma no determinista.

       Se mantiene funcionando —retirarlo es un cambio breaking del contrato
       público y requiere RFC (AGENTS §5)— pero no debe usarse en clientes
       nuevos.

    Devuelve ``{id, status}`` inmediatamente (202 Accepted).
    Sondea ``GET /exports/{id}`` para obtener el PDF cuando ``status=done``.
    """
    _gc_store()
    job_id = str(uuid.uuid4())
    with _store_lock:
        _store[job_id] = {
            "status": "pending",
            "created_at": time.monotonic(),
            "pdf": None,
            "error": None,
            "owner": ctx.key_hash,
        }
    filters = {k: v for k, v in {"ccaa": ccaa, "estado": estado, "q": q}.items() if v}
    background_tasks.add_task(_run_export, job_id, filters)
    log.info("export_pdf.created", job_id=job_id, filters=filters)
    return ExportJobStatus(id=job_id, status="pending")


__all__ = ["router"]


# ── Synchronous CSV/Excel download ───────────────────────────────────────────


# response_class=StreamingResponse: la respuesta es el fichero (CSV/XLSX/PDF),
# no hay 200 application/json que documentar.
@router.get(
    "/download",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "text/csv": {},
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {},
                "application/pdf": {},
            },
            "description": "Fichero exportado con los filtros actuales",
        }
    },
)
async def download_export(
    format: Literal["csv", "excel", "pdf"] = Query("csv"),
    q: str | None = Query(None),
    estado: str | None = Query(None),
    ccaa: str | None = Query(None),
    tecnologia: str | None = Query(None),
    fecha_desde: str | None = Query(None),
    fecha_hasta: str | None = Query(None),
    limit: int = Query(10000, ge=1, le=50000),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> StreamingResponse:
    """Descarga síncrona (CSV, Excel o PDF) con los filtros actuales.

    ``format=pdf`` es el camino recomendado para exportar a PDF: devuelve el
    documento en la propia respuesta, sin la máquina de estados 202+poll de
    ``POST /exports`` (ver la nota de deprecación de ese endpoint).
    """
    from services.exports import generate_csv, generate_excel, get_export_filename
    from services.licitaciones import fetch_for_pdf

    rows = fetch_for_pdf(ccaa=ccaa, estado=estado, q=q, limit=limit)
    # Apply extra filters not supported by fetch_for_pdf
    if tecnologia:
        rows = [r for r in rows if r.get("tecnologia") == tecnologia]
    if fecha_desde:
        rows = [r for r in rows if (r.get("fecha_publicacion") or "") >= fecha_desde]
    if fecha_hasta:
        rows = [r for r in rows if (r.get("fecha_publicacion") or "") <= fecha_hasta]

    filename = get_export_filename(format)

    if format == "excel":
        content = generate_excel(rows)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif format == "pdf":
        title = "Licitaciones SAP — Exportación"
        if ccaa:
            title += f" ({ccaa})"
        content = _build_pdf(rows, title)
        media_type = "application/pdf"
    else:
        content = generate_csv(rows)
        media_type = "text/csv; charset=utf-8"

    log.info("export_download", format=format, n_rows=len(rows))
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Export calendario ICS (Feature D)
# ---------------------------------------------------------------------------


def _ics_escape(value: str) -> str:
    """Escapa caracteres especiales segun RFC 5545 para valores de texto."""
    value = value.replace("\\", "\\\\")
    value = value.replace(";", "\\;")
    value = value.replace(",", "\\,")
    value = value.replace("\n", "\\n")
    value = value.replace("\r", "")
    return value


def _ics_fold(line: str) -> str:
    """Aplica el folding de lineas RFC 5545 (max 75 octetos por linea)."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    result = []
    offset = 0
    while offset < len(encoded):
        chunk = encoded[offset : offset + 75]
        result.append(chunk.decode("utf-8", errors="replace"))
        offset += 75
    return "\r\n ".join(result)


def _safe_ics_url(value: object) -> str | None:
    """Return an HTTPS URI suitable for a URL property, never a new ICS line."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or any(ord(char) < 32 or ord(char) == 127 for char in candidate):
        return None
    parsed = urlsplit(candidate)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return candidate


def _generate_ics(items: list[dict[str, Any]], cal_name: str = "Tenderflow") -> str:
    """Genera contenido ICS (iCalendar) para una lista de eventos.

    Cada item debe tener: uid, dtstart (str ISO), summary, description, url.
    """
    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Tenderflow//ES",
        f"X-WR-CALNAME:{_ics_escape(cal_name)}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for item in items:
        uid = _ics_escape(str(item.get("uid", "")))
        dtstart = str(item.get("dtstart", "")).replace("-", "").replace(":", "")[:8]
        summary = _ics_escape(str(item.get("summary", "")))
        description = _ics_escape(str(item.get("description", "")))
        url = _safe_ics_url(item.get("url"))

        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now}",
            f"DTSTART;VALUE=DATE:{dtstart}" if dtstart else "DTSTART;VALUE=DATE:20000101",
            f"SUMMARY:{summary}",
        ]
        if description:
            lines.append(f"DESCRIPTION:{description}")
        if url is not None:
            lines.append(f"URL:{url}")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(_ics_fold(ln) for ln in lines) + "\r\n"


@router.get(
    "/calendario.ics",
    summary="Calendario ICS con deadlines y vencimientos de favoritos",
    # response_class=Response evita el content application/json {} por defecto
    # (es un .ics; su contrato lo declara `responses`).
    response_class=Response,
    responses={
        200: {"content": {"text/calendar": {}}, "description": "Archivo iCalendar (.ics)"},
        401: {"description": "Token invalido o ausente"},
    },
    include_in_schema=True,
)
async def calendario_ics(
    ctx: AuthContext = Depends(require_api_key),
) -> Response:
    """Exporta un archivo .ics con los deadlines (fecha_limite) y fines de
    contrato (fecha_fin) de las licitaciones favoritas del usuario.

    Autenticacion via API key en la cabecera ``X-API-Key`` y solo ahi: la
    dependencia usa ``APIKeyHeader``, que no mira la query string. Es
    deliberado — un token en la URL acaba en los access logs, en el historial
    del navegador y en la cabecera ``Referer`` de cualquier salto externo, y de
    ahi no se puede revocar. Si un cliente de calendario no admite cabeceras
    personalizadas, la solucion no es reabrir ``?token=``.

    Compatible con Google Calendar, Outlook, Apple Calendar, etc.:
      ``/api/v1/exports/calendario.ics`` con cabecera ``X-API-Key: <token>``.
    """
    from db.users import get_user_by_id
    from shared.identity import user_key_from_email

    owner = get_user_by_id(ctx.user_id) if ctx.user_id is not None else None
    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="API key owner unavailable"
        )
    user_key = user_key_from_email(owner.get("email"), int(owner["id"]))

    from db.database import connect_read

    with connect_read() as c:
        cur = c.execute(
            "SELECT l.id_externo, l.titulo, l.fecha_limite, l.fecha_fin, l.url "
            "FROM watchlist_items wi "
            "JOIN licitaciones l ON l.id_externo = wi.id_externo "
            "WHERE wi.user_key = ? AND (l.fecha_limite IS NOT NULL OR l.fecha_fin IS NOT NULL)",
            (user_key,),
        )
        rows = [
            dict(zip([d[0] for d in cur.description], row, strict=False)) for row in cur.fetchall()
        ]

    events: list[dict[str, Any]] = []
    for row in rows:
        id_ext = str(row.get("id_externo", ""))
        titulo = str(row.get("titulo") or id_ext)[:200]
        url = str(row.get("url") or "")

        for field, label in (("fecha_limite", "Plazo"), ("fecha_fin", "Fin contrato")):
            raw = row.get(field)
            if not raw:
                continue
            date_str = str(raw)[:10]
            events.append(
                {
                    "uid": f"{id_ext}-{field}@tenderflow",
                    "dtstart": date_str,
                    "summary": f"{label}: {titulo}",
                    "description": f"Licitacion: {id_ext}",
                    "url": url,
                }
            )

    ics_content = _generate_ics(events, cal_name="Tenderflow - Favoritos")
    log.info("calendario_ics_export", user_key=user_key[:8], events=len(events))
    return Response(
        content=ics_content.encode("utf-8"),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="tenderflow.ics"'},
    )


# ── Jobs asíncronos (deprecados) ─────────────────────────────────────────────
# Van al final del módulo A PROPÓSITO: ``/{job_id}`` es un comodín de un solo
# segmento y Starlette resuelve por orden de registro, así que declarado antes
# se tragaba ``/exports/download`` y ``/exports/calendario.ics`` (las atendía
# ``get_export`` con job_id="download", que exige X-API-Key y respondía 401 a
# toda sesión de navegador: todos los botones de exportación del dashboard
# estaban rotos). Es el mismo motivo por el que el catch-all de licitaciones se
# registra el último en ``api/app.py``. Cualquier sub-ruta estática nueva de
# ``/exports`` debe declararse por encima de este bloque.


# response_class=Response evita el content application/json {} por defecto:
# el 200 es el PDF; el estado intermedio viaja como 202 con ExportJobStatus.
@router.get(
    "/{job_id}",
    deprecated=True,
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {}}, "description": "PDF generado"},
        202: {"model": ExportJobStatus, "description": "Job pendiente o en curso"},
    },
)
def get_export(
    job_id: str,
    ctx: AuthContext = Depends(require_api_key),
) -> Response:
    """Sondea el estado del job. Devuelve el PDF cuando ``status=done``.

    .. deprecated:: Ver ``POST /exports``.
    """
    job = _store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado o expirado.")
    if job.get("owner") != ctx.key_hash:
        raise HTTPException(status_code=403, detail="Forbidden.")
    if job["status"] == "done" and job["pdf"]:
        return Response(
            content=job["pdf"],
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="licitaciones_{job_id[:8]}.pdf"',
                "X-Export-Rows": str(job.get("n_rows", 0)),
            },
        )
    if job["status"] == "error":
        log.error("export_pdf.client_poll_error", job_id=job_id, error=job["error"])
        raise HTTPException(
            status_code=500, detail="Error generando PDF. Consulte los logs del servidor."
        )
    # pending o running
    from fastapi.responses import JSONResponse

    return JSONResponse({"id": job_id, "status": job["status"]}, status_code=202)


@router.delete("/{job_id}", status_code=204, deprecated=True)
def delete_export(
    job_id: str,
    ctx: AuthContext = Depends(require_api_key),
) -> None:
    """Elimina un job de exportación de la memoria.

    .. deprecated:: Ver ``POST /exports``.
    """
    job = _store.get(job_id)
    if job is None:
        return
    if job.get("owner") != ctx.key_hash:
        raise HTTPException(status_code=403, detail="Forbidden.")
    del _store[job_id]
