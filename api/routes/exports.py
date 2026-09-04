"""Exportación de datos: descarga síncrona (CSV/Excel/PDF) y calendario ICS.

* ``GET /exports/download`` — devuelve el fichero en la propia respuesta.
* ``GET /exports/calendario/enlace`` — ruta firmada de suscripción al calendario.
* ``GET /exports/calendario.ics`` — el calendario, por cabecera o enlace firmado.

**Los tres endpoints de job asíncrono (``POST /exports``, ``GET /exports/{id}``,
``DELETE /exports/{id}``) se retiraron el 2026-09-03**; el almacén en memoria que
los sostenía se fue con ellos. Motivo y plan en
``docs/rfc/2026-09-03-rfc-retirada-exports-asincronos.md``: el job vivía en un
``dict`` de proceso, así que con más de una instancia (o tras cualquier
reinicio) el 202 aceptaba un trabajo que el sondeo no volvía a encontrar. El
sustituto es ``GET /exports/download?format=pdf``, que ya existía y devuelve el
PDF en la misma respuesta.

El PDF se genera con ``reportlab`` (ya en dependencies del proyecto).
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Security, status
from fastapi.responses import Response, StreamingResponse
from fastapi.security import APIKeyHeader

from api.auth import validate_api_key_credential
from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from api.tenancy import resolve_organization_ctx
from db.repositories.watchlist import WatchlistRepository
from observability.logging import get_logger
from shared.dto import CalendarioEnlace

log = get_logger(__name__)

router = APIRouter(prefix="/exports", tags=["exports"])

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
    _user: dict[str, Any] = Depends(require_any_auth),
) -> StreamingResponse:
    """Descarga síncrona (CSV, Excel o PDF) con los filtros actuales.

    ``format=pdf`` es **el** camino para exportar a PDF desde 2026-09-03:
    devuelve el documento en la propia respuesta, sin la máquina de estados
    202+poll que sostenía el retirado ``POST /exports``.
    """
    from services.exports import generate_csv, generate_excel, get_export_filename
    from services.licitaciones import fetch_for_pdf

    def _render() -> tuple[bytes, str, int]:
        """Consulta + serialización, fuera del event loop.

        Hasta 50 000 filas y, con ``format=pdf``, la maquetación de reportlab:
        segundos de CPU que, ejecutados aquí, congelaban la API entera.
        """
        rows = fetch_for_pdf(
            ccaa=ccaa,
            estado=estado,
            q=q,
            tecnologia=tecnologia,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            limit=limit,
        )
        if format == "excel":
            return (
                generate_excel(rows),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                len(rows),
            )
        if format == "pdf":
            title = "Licitaciones SAP — Exportación"
            if ccaa:
                title += f" ({ccaa})"
            return _build_pdf(rows, title), "application/pdf", len(rows)
        return generate_csv(rows), "text/csv; charset=utf-8", len(rows)

    filename = get_export_filename(format)
    content, media_type, n_rows = await run_db(_render)

    log.info("export_download", format=format, n_rows=n_rows)
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


_repo_watchlist = WatchlistRepository()


_API_KEY_OPCIONAL = APIKeyHeader(name="X-API-Key", auto_error=False)
_PREFIJO_FIRMA_CALENDARIO = b"calendario-ics:"


def _firma_calendario(user_id: int) -> str:
    """Firma HMAC del usuario para el enlace de suscripción (``kid.sig``)."""
    from shared.signing import sign

    return sign(_PREFIJO_FIRMA_CALENDARIO + str(int(user_id)).encode("ascii"))


def _verificar_firma_calendario(user_id: int, token: str) -> bool:
    from shared.signing import verify

    return verify(_PREFIJO_FIRMA_CALENDARIO + str(int(user_id)).encode("ascii"), token)


def _eventos_calendario(user_key: str, user_id: int, organization_id: int) -> list[dict[str, Any]]:
    """Eventos ICS del usuario: pursuits abiertos primero, favoritos después.

    Un expediente que es a la vez pursuit y favorito sale una sola vez, como
    pursuit: es el que lleva responsable y próxima acción.

    ``organization_id`` no es decorativa: los favoritos se leen con el mismo
    predicado de visibilidad que ``GET /watchlist/items``. Hasta 2026-09 esta
    función ejecutaba su propio SQL en la ruta, filtrando sólo por
    ``wi.user_key`` — sin organización ni visibilidad— y lo hacía además desde
    un endpoint alcanzable con un enlace firmado de larga vida, sin sesión.
    """
    from db.repositories.pursuits import PursuitRepository

    events: list[dict[str, Any]] = []
    con_pursuit: set[str] = set()
    for row in PursuitRepository().calendar_rows(user_id):
        id_ext = str(row.get("licitacion_id", ""))
        con_pursuit.add(id_ext)
        titulo = str(row.get("titulo") or id_ext)[:200]
        url = str(row.get("url") or "")
        organizacion = str(row.get("organization_name") or "")
        pursuit_id = int(row["pursuit_id"])
        descripcion = f"Oportunidad #{pursuit_id}"
        if organizacion:
            descripcion += f" · {organizacion}"
        if row.get("fecha_limite"):
            events.append(
                {
                    "uid": f"pursuit-{pursuit_id}-plazo@tenderflow",
                    "dtstart": str(row["fecha_limite"])[:10],
                    "summary": f"Plazo: {titulo}",
                    "description": f"{descripcion} · Licitacion: {id_ext}",
                    "url": url,
                }
            )
        if row.get("next_action_due"):
            accion = str(row.get("next_action") or "Próxima acción")[:120]
            events.append(
                {
                    "uid": f"pursuit-{pursuit_id}-accion@tenderflow",
                    "dtstart": str(row["next_action_due"])[:10],
                    "summary": f"Acción: {accion} · {titulo}",
                    "description": f"{descripcion} · Licitacion: {id_ext}",
                    "url": url,
                }
            )
        if row.get("fecha_fin"):
            events.append(
                {
                    "uid": f"pursuit-{pursuit_id}-fin@tenderflow",
                    "dtstart": str(row["fecha_fin"])[:10],
                    "summary": f"Fin contrato: {titulo}",
                    "description": f"{descripcion} · Licitacion: {id_ext}",
                    "url": url,
                }
            )

    for row in _repo_watchlist.calendar_items(user_key, organization_id, user_id):
        id_ext = str(row.get("id_externo", ""))
        if id_ext in con_pursuit:
            continue
        titulo = str(row.get("titulo") or id_ext)[:200]
        url = str(row.get("url") or "")
        for field, label in (("fecha_limite", "Plazo"), ("fecha_fin", "Fin contrato")):
            raw = row.get(field)
            if not raw:
                continue
            events.append(
                {
                    "uid": f"{id_ext}-{field}@tenderflow",
                    "dtstart": str(raw)[:10],
                    "summary": f"{label}: {titulo}",
                    "description": f"Favorito · Licitacion: {id_ext}",
                    "url": url,
                }
            )
    return events


async def _organizacion_del_calendario(ctx: dict[str, Any]) -> int:
    """Organización con la que se leen los favoritos del calendario.

    Siempre la **personal** del usuario, y por una razón concreta: el enlace de
    suscripción es una URL firmada que no lleva —ni puede llevar sin invalidar
    los enlaces ya emitidos— un ``organization_id``. Si el contador de
    ``/calendario/enlace`` y el contenido de ``/calendario.ics`` resolvieran la
    organización de formas distintas, el usuario vería un número que no
    corresponde con su calendario. Los pursuits, que son el grueso del ICS, no
    dependen de esto: se leen por ``user_id``.
    """
    resuelto = await resolve_organization_ctx(ctx, None)
    return int(resuelto["organization_id"])


@router.get(
    "/calendario/enlace",
    response_model=CalendarioEnlace,
    summary="Enlace de suscripción al calendario de compromisos",
)
async def calendario_enlace(
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> CalendarioEnlace:
    """Ruta firmada para suscribirse desde Google/Apple/Outlook, y cuántos
    eventos devolvería hoy. El cliente antepone su propio origen: el mismo
    host que sirve la consola proxya ``/api`` a esta API."""
    from urllib.parse import urlencode

    user_id = int(ctx["user_id"])
    user_key = str(ctx.get("user_key") or "")
    organization_id = await _organizacion_del_calendario(ctx)
    eventos = await run_db(_eventos_calendario, user_key, user_id, organization_id)
    query = urlencode({"u": user_id, "t": _firma_calendario(user_id)})
    return CalendarioEnlace(path=f"/api/v1/exports/calendario.ics?{query}", eventos=len(eventos))


@router.get(
    "/calendario.ics",
    summary="Calendario ICS con los plazos de pursuits y favoritos",
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
    api_key_raw: str | None = Security(_API_KEY_OPCIONAL),
    u: int | None = Query(default=None, ge=1, description="Usuario del enlace firmado"),
    t: str | None = Query(default=None, max_length=200, description="Firma del enlace"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> Response:
    """Exporta un archivo .ics con los plazos que importan: los de los pursuits
    abiertos del usuario (fecha límite y próxima acción) y los de sus favoritos.

    Dos formas de autenticarse:

    - Cabecera ``X-API-Key`` (la de siempre; scripts y clientes que admiten
      cabeceras).
    - Enlace firmado ``?u=<user_id>&t=<firma>`` (ver :func:`_firma_calendario`).
      Google Calendar, Apple Calendar y Outlook **no** envían cabeceras
      personalizadas al suscribirse a una URL, así que hasta 2026-09 este
      endpoint era inservible para los tres y ningún componente lo enlazaba.
      La firma es una capacidad acotada a este endpoint: no abre sesión, no es
      una API key y sólo devuelve fechas de compromisos. Un enlace filtrado se
      revoca rotando ``SIGNING_KEY`` (``shared/signing``, con ``kid``).
    """
    from db.users import get_user_by_id
    from shared.identity import user_key_from_email

    user_id: int | None = None
    if api_key_raw:
        ctx = await validate_api_key_credential(
            api_key_raw,
            method="GET",
            path="/api/v1/exports/calendario.ics",
            background_tasks=background_tasks,
        )
        user_id = ctx.user_id
    elif u is not None and t and _verificar_firma_calendario(u, t):
        user_id = u
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido o ausente"
        )

    # Todo el trabajo de BD va al threadpool: este endpoint lo consumen clientes
    # de calendario que refrescan solos cada pocos minutos, y corría entero
    # sobre el event loop.
    owner = await run_db(get_user_by_id, user_id)
    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="API key owner unavailable"
        )
    user_key = user_key_from_email(owner.get("email"), int(owner["id"]))

    organization_id = await _organizacion_del_calendario(
        {"user_id": int(owner["id"]), "user_key": user_key}
    )
    events = await run_db(_eventos_calendario, user_key, int(owner["id"]), organization_id)

    ics_content = _generate_ics(events, cal_name="TenderFlow - Compromisos")
    log.info("calendario_ics_export", user_key=user_key[:8], events=len(events))
    return Response(
        content=ics_content.encode("utf-8"),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="tenderflow.ics"'},
    )


__all__ = ["router"]
