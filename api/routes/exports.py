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
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response

from api.auth import AuthContext, require_api_key
from observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/exports", tags=["exports"])

# ── Almacén en memoria (proceso) ─────────────────────────────────────────────
# Suficiente para un servicio de instancia única. Para multi-instancia,
# usar Redis/DB. TTL = 15 min para evitar fugas de memoria.

_TTL_SECONDS = 900
_store: dict[str, dict[str, Any]] = {}


def _gc_store() -> None:
    """Elimina jobs expirados (>TTL)."""
    now = time.monotonic()
    expired = [k for k, v in _store.items() if now - v["created_at"] > _TTL_SECONDS]
    for k in expired:
        del _store[k]


# ── Generador PDF ─────────────────────────────────────────────────────────────


def _build_pdf(rows: list[dict[str, Any]], title: str) -> bytes:
    """Genera un PDF tabular simple con reportlab."""
    from reportlab.lib import colors  # type: ignore[import-untyped]
    from reportlab.lib.pagesizes import A4, landscape  # type: ignore[import-untyped]
    from reportlab.lib.styles import getSampleStyleSheet  # type: ignore[import-untyped]
    from reportlab.platypus import (  # type: ignore[import-untyped]
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
        from db.database import connect

        sql = (
            "SELECT id, titulo, organo_contratacion, importe, estado, fecha_publicacion "
            "FROM licitaciones WHERE 1=1"
        )
        params: list[Any] = []
        if filters.get("ccaa"):
            sql += " AND ccaa = ?"
            params.append(filters["ccaa"])
        if filters.get("estado"):
            sql += " AND estado = ?"
            params.append(filters["estado"])
        if filters.get("q"):
            sql += " AND (titulo LIKE ? OR descripcion LIKE ?)"
            term = f"%{filters['q']}%"
            params.extend([term, term])
        sql += " ORDER BY fecha_publicacion DESC LIMIT 500"

        with connect() as conn:
            rows_raw = conn.execute(sql, params).fetchall()

        cols = ["id", "titulo", "organo_contratacion", "importe", "estado", "fecha_publicacion"]
        rows = [dict(zip(cols, r, strict=False)) for r in rows_raw]
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


@router.post("", status_code=202)
def create_export(
    background_tasks: BackgroundTasks,
    ccaa: str | None = None,
    estado: str | None = None,
    q: str | None = None,
    ctx: AuthContext = Depends(require_api_key),
) -> dict[str, str]:
    """Crea un job de exportación PDF asíncrono.

    Devuelve ``{id, status}`` inmediatamente (202 Accepted).
    Sondea ``GET /exports/{id}`` para obtener el PDF cuando ``status=done``.
    """
    _gc_store()
    job_id = str(uuid.uuid4())
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
    return {"id": job_id, "status": "pending"}


@router.get("/{job_id}")
def get_export(
    job_id: str,
    ctx: AuthContext = Depends(require_api_key),
) -> Response:
    """Sondea el estado del job. Devuelve el PDF cuando ``status=done``."""
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


@router.delete("/{job_id}", status_code=204)
def delete_export(
    job_id: str,
    ctx: AuthContext = Depends(require_api_key),
) -> None:
    """Elimina un job de exportación de la memoria."""
    job = _store.get(job_id)
    if job is None:
        return
    if job.get("owner") != ctx.key_hash:
        raise HTTPException(status_code=403, detail="Forbidden.")
    del _store[job_id]


__all__ = ["router"]
