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

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Path,
    Query,
    Security,
    status,
)
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.security import APIKeyHeader

from api.auth import validate_api_key_credential
from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from api.tenancy import require_organization, resolve_organization_ctx
from config.settings import jobs_export_umbral_filas
from db.repositories.watchlist import WatchlistRepository
from observability.logging import get_logger
from shared.dto import CalendarioEnlace, JobEstadoDTO

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


def build_pdf_export(payload: dict[str, Any]) -> tuple[bytes, int]:
    """Consulta + maquetado del PDF de exportación. Devuelve ``(bytes, filas)``.

    Extraída del handler para que el worker de la cola pueda ejecutar
    exactamente lo mismo que el camino síncrono (``scheduler/worker.py``): si
    fueran dos implementaciones, el PDF que llega por la cola dejaría de
    parecerse al que llega por la request en cuanto una de las dos cambiara.
    """
    from services.licitaciones import fetch_for_pdf

    ccaa = payload.get("ccaa")
    rows = fetch_for_pdf(
        ccaa=ccaa,
        estado=payload.get("estado"),
        q=payload.get("q"),
        tecnologia=payload.get("tecnologia"),
        fecha_desde=payload.get("fecha_desde"),
        fecha_hasta=payload.get("fecha_hasta"),
        limit=int(payload.get("limit") or 10000),
    )
    title = "Licitaciones SAP — Exportación"
    if ccaa:
        title += f" ({ccaa})"
    return _build_pdf(rows, title), len(rows)


# response_class=StreamingResponse: la respuesta normal es el fichero
# (CSV/XLSX/PDF), no hay 200 application/json que documentar. El 202 sí lleva
# modelo: es el mismo cuerpo que sirve `GET /jobs/{id}`.
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
        },
        202: {
            "model": JobEstadoDTO,
            "description": (
                "PDF grande: se encoló; se recoge en el `descarga` de su resultado "
                "(`/api/v1/exports/descargas/{job_id}`)"
            ),
        },
    },
)
async def download_export(
    format: Literal["csv", "excel", "pdf"] = Query("csv"),
    recurso: Literal["licitaciones", "pursuits"] = Query(
        "licitaciones",
        description=(
            "Qué se exporta. `pursuits` baja el tablero de oportunidades de tu "
            "organización con los filtros del tablero (C6.7); `licitaciones`, el "
            "corpus con los filtros de búsqueda. No se mezclan: son dos "
            "colecciones con columnas distintas."
        ),
    ),
    pursuit_status: str | None = Query(
        None,
        alias="pursuit_status",
        description="Filtro de estado del tablero. Solo con `recurso=pursuits`.",
    ),
    responsible_user_id: int | None = Query(
        None, ge=1, description="Filtro de responsable. Solo con `recurso=pursuits`."
    ),
    q: str | None = Query(None),
    estado: str | None = Query(None),
    ccaa: str | None = Query(None),
    tecnologia: str | None = Query(None),
    fecha_desde: str | None = Query(None),
    fecha_hasta: str | None = Query(None),
    limit: int = Query(10000, ge=1, le=50000),
    organization_id: int | None = Query(
        None,
        ge=1,
        description="Organización a la que se atribuye la exportación encolada.",
    ),
    por_lote: bool = Query(
        False,
        description=(
            "Una fila por LOTE en vez de por expediente (C1.4). Los expedientes "
            "sin lotes salen igual, con los campos de lote vacíos: un export que "
            "solo trajera los multi-lote perdería la mayoría del corpus sin "
            "decirlo. Solo aplica a `csv` y `excel`."
        ),
    ),
    _user: dict[str, Any] = Depends(require_any_auth),
) -> Response:
    """Descarga (CSV, Excel o PDF) con los filtros actuales.

    ``format=pdf`` es **el** camino para exportar a PDF desde 2026-09-03. Por
    encima de un umbral de filas la maquetación no cabe en una request: la
    respuesta pasa a ser **202 con el trabajo encolado** y el fichero se recoge
    en ``GET /exports/descargas/{job_id}``. Por debajo del umbral, y para CSV y
    Excel, la respuesta sigue siendo el fichero.

    Esta operación **nunca** se parametriza por identificador de trabajo: sus
    parámetros son los filtros de quien la pide, así que no hay nada de otro
    usuario que pedir aquí (issue #50, ``tests/test_unit_export_idor.py``). La
    recogida del encolado, que sí lleva id, es otra ruta con su propia
    comprobación de dueño.
    """
    from services.exports import generate_csv, generate_excel, get_export_filename

    filtros: dict[str, Any] = {
        "q": q,
        "estado": estado,
        "ccaa": ccaa,
        "tecnologia": tecnologia,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "limit": limit,
    }

    if format == "pdf" and limit > jobs_export_umbral_filas():
        return await _encolar_export_pdf(
            filtros, await resolve_organization_ctx(_user, organization_id)
        )

    if recurso == "pursuits":
        return await _download_pursuits(
            format=format,
            status_filtro=pursuit_status,
            responsible_user_id=responsible_user_id,
            limit=limit,
            user=_user,
        )

    def _render() -> tuple[bytes, str, int]:
        """Consulta + serialización, fuera del event loop.

        Hasta 50 000 filas y, con ``format=pdf``, la maquetación de reportlab:
        segundos de CPU que, ejecutados aquí, congelaban la API entera.
        """
        if format == "pdf":
            contenido, filas = build_pdf_export(filtros)
            return contenido, "application/pdf", filas

        from services.licitaciones import fetch_for_pdf

        rows = fetch_for_pdf(
            ccaa=ccaa,
            estado=estado,
            q=q,
            tecnologia=tecnologia,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            limit=limit,
        )
        if por_lote:
            # Aquí `format` ya solo puede ser `csv` o `excel`: el PDF salió por
            # el retorno de arriba. Queda fuera a propósito —su maquetación es
            # una tabla por expediente y expandir a lotes le rompería el layout
            # sin que nadie lo haya pedido—, y comprobarlo otra vez sería una
            # condición que nunca es falsa, que es lo que mypy señaló.
            from db.repositories.licitaciones import licitaciones_por_lote

            ids = [str(r["id_externo"]) for r in rows if r.get("id_externo")]
            rows = licitaciones_por_lote(ids)
        if format == "excel":
            return (
                generate_excel(rows),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                len(rows),
            )
        return generate_csv(rows), "text/csv; charset=utf-8", len(rows)

    filename = get_export_filename(format)
    content, media_type, n_rows = await run_db(_render)

    log.info("export_download", format=format, n_rows=n_rows)
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _encolar_export_pdf(payload: dict[str, Any], ctx: dict[str, Any]) -> JSONResponse:
    """Encola el maquetado y responde 202 con el estado del trabajo."""
    from api.routes.jobs import a_dto
    from shared.jobs import TIPO_EXPORT_PDF, enqueue, obtener

    job_id = await run_db(
        enqueue,
        TIPO_EXPORT_PDF,
        payload,
        organization_id=int(ctx["organization_id"]),
        # Sin deduplicar: dos peticiones con los mismos filtros son dos
        # descargas que alguien espera por separado, y el binario se guarda
        # bajo la clave del job. Compartir uno haría que la segunda descarga
        # dependiera de que la primera no hubiera caducado todavía.
        deduplicar=False,
    )
    job = await run_db(obtener, job_id)
    if job is None:  # defensa: acabamos de insertarlo
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="El trabajo se encoló pero no pudo releerse.",
        )
    log.info("export_pdf_encolado", job_id=job_id, filas_pedidas=payload.get("limit"))
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=a_dto(job).model_dump(mode="json"),
    )


@router.get(
    "/descargas/{job_id}",
    response_class=StreamingResponse,
    summary="Recoger el PDF de una exportación encolada",
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "El PDF que maquetó el worker",
        },
        401: {"description": "Autenticación inválida"},
        404: {"description": "El trabajo no existe o no es de esta organización"},
        409: {"description": "El trabajo todavía no ha terminado"},
        410: {"description": "El fichero caducó; hay que volver a pedir la exportación"},
    },
)
async def descargar_export_encolado(
    job_id: int = Path(ge=1, description="Identificador que devolvió el 202 de /download"),
    ctx: dict[str, Any] = Depends(require_organization()),
) -> StreamingResponse:
    """Sirve el PDF que dejó maquetado el worker, mientras siga en caché.

    Es una ruta separada de ``/download`` a propósito. El issue #50 fue un IDOR
    sobre exports asíncronos: un id global adivinable apuntando al resultado de
    otro usuario, y su RFC de retirada (2026-09-03) dijo que la máquina 202+poll
    solo podía volver «con backend compartido». Vuelve ahora con las dos cosas
    que le faltaban — el estado vive en la tabla ``jobs`` y el binario en la
    caché compartida, no en un ``dict`` de proceso; y cada lectura comprueba que
    el trabajo es de la organización de quien lo pide—. Manteniéndola aparte,
    ``/download`` sigue sin aceptar identificadores ajenos: la ruta que se
    parametriza por un id es esta, y es la que carga con la comprobación.

    404 —y no 403— cuando el trabajo es de otra organización, por el mismo
    motivo que en ``GET /jobs/{id}``: un 403 confirmaría que ese id existe.
    """
    from services.exports import get_export_filename
    from shared.cache import get_cache
    from shared.jobs import CACHE_EXPORTS, TIPO_EXPORT_PDF, clave_cache_export, obtener

    job = await run_db(obtener, job_id)
    if (
        job is None
        or job.tipo != TIPO_EXPORT_PDF
        or job.organization_id != int(ctx["organization_id"])
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Trabajo {job_id} no encontrado."
        )
    if job.estado != "done":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El trabajo {job_id} está en estado '{job.estado}'; todavía no hay fichero.",
        )

    contenido = get_cache(CACHE_EXPORTS).get(clave_cache_export(job_id))
    if not isinstance(contenido, bytes):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="El fichero exportado caducó; vuelve a pedir la exportación.",
        )
    return StreamingResponse(
        io.BytesIO(contenido),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{get_export_filename("pdf")}"',
        },
    )


async def _download_pursuits(
    *,
    format: Literal["csv", "excel", "pdf"],
    status_filtro: str | None,
    responsible_user_id: int | None,
    limit: int,
    user: dict[str, Any],
) -> StreamingResponse:
    """Export del tablero de oportunidades (C6.7).

    **PDF queda fuera**: su maquetación es una tabla por expediente del corpus
    público, y el tablero es otra colección con otras columnas. Reutilizarla
    daría un documento con las cabeceras de una cosa y los datos de otra.

    La sanitización de fórmulas es la misma de siempre
    (`shared.export_safety.sanitize_spreadsheet_record`, dentro de
    `generate_csv`/`generate_excel`): un `decision_reason` que empiece por `=`
    es una fórmula en Excel, y aquí el texto lo escribe el propio equipo — que
    es exactamente el caso en que nadie sospecha del fichero.
    """
    from services.exports import get_export_filename, render_pursuits_export
    from services.organizations import OrganizationAccessError

    if format == "pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El tablero de oportunidades se exporta en CSV o Excel, no en PDF.",
        )

    try:
        content, media_type, n_rows = await run_db(
            render_pursuits_export,
            int(user["user_id"]),
            formato=format,
            status=status_filtro,
            responsible_user_id=responsible_user_id,
            limit=limit,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    filename = get_export_filename(format, prefix="oportunidades")
    log.info("export_download", format=format, recurso="pursuits", n_rows=n_rows)
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
