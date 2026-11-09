"""Export service — CSV, Excel, PDF generation from licitaciones data."""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel

from observability.logging import get_logger
from services.analytics.competitors import CompetitorFilters, get_competitors
from services.analytics.geography import GeoFilters, get_geography
from services.analytics.organos import OrganosFilters, get_organos
from services.analytics.tecnologias import TecnologiasFilters, get_tecnologias
from services.analytics.utes import UTEFilters, get_utes
from shared.export_safety import sanitize_spreadsheet_record

logger = get_logger(__name__)

ExportFormat = Literal["csv", "excel", "pdf"]

_DEFAULT_COLUMNS = [
    "id_externo",
    "titulo",
    "organo_contratacion",
    "importe",
    "estado",
    "fecha_publicacion",
    "ccaa",
    "cpv",
    "tecnologia",
]


#: Columnas del export del tablero de oportunidades (C6.7).
#:
#: `organizacion_id` y `exportado_en` van **como columnas** y no como preámbulo
#: del fichero: una línea de cabecera antes de los nombres de columna rompe a
#: pandas, a Excel y a cualquier consumidor que espere un CSV, mientras que una
#: columna la lee todo el mundo y sobrevive a que alguien filtre y reenvíe media
#: hoja — que es justo cuando importa saber de qué organización y de qué día es
#: el dato.
PURSUIT_COLUMNS = [
    "id",
    "licitacion_id",
    "tender_title",
    "organo_contratacion",
    "cpv",
    "tender_deadline",
    "responsable",
    "status",
    "decision",
    "decision_reason",
    "offer_price_eur",
    "outcome",
    "awarded_amount_eur",
    "outcome_reason",
    "next_action",
    "next_action_due",
    "identified_at",
    "decision_at",
    "submitted_at",
    "closed_at",
    "updated_at",
    "organizacion_id",
    "exportado_en",
]


def generate_csv(
    records: Sequence[Mapping[str, object]],
    columns: list[str] | None = None,
) -> bytes:
    """Generate CSV bytes with UTF-8 BOM and semicolon delimiter for Excel compat."""
    cols = columns or _DEFAULT_COLUMNS
    df = pd.DataFrame([sanitize_spreadsheet_record(record) for record in records])
    # Keep only requested columns that exist
    available = [c for c in cols if c in df.columns]
    if available:
        df = df[available]

    buf = io.StringIO()
    df.to_csv(buf, index=False, sep=";")
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def generate_excel(
    records: Sequence[Mapping[str, object]],
    columns: list[str] | None = None,
    sheet_name: str = "Licitaciones",
) -> bytes:
    """Generate .xlsx bytes using openpyxl engine via pandas."""
    cols = columns or _DEFAULT_COLUMNS
    df = pd.DataFrame([sanitize_spreadsheet_record(record) for record in records])
    available = [c for c in cols if c in df.columns]
    if available:
        df = df[available]

    # Strip timezone-aware datetimes (openpyxl doesn't support them)
    for c in df.select_dtypes(include=["datetimetz"]).columns:
        df[c] = df[c].dt.tz_localize(None)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
        # Auto-size columns
        ws = writer.sheets[sheet_name]
        for col_idx, col_name in enumerate(df.columns, 1):
            max_len = max(
                len(str(col_name)),
                df[col_name].astype(str).str.len().max() if len(df) else 0,
            )
            ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(
                max_len + 2, 50
            )
    return buf.getvalue()


_EXTENSIONS: dict[str, str] = {"csv": "csv", "excel": "xlsx", "pdf": "pdf"}


#: Las tablas de Competencia y Mercado que tienen botón de exportar.
SeccionExport = Literal["competidores", "utes", "geografia", "organos", "tecnologias"]


#: Cabeceras del fichero: los nombres de campo (`count`, `cuota`…) son del
#: contrato de la API, no castellano para quien abre el Excel.
_CABECERAS: dict[str, str] = {
    "nombre": "Nombre",
    "organo_contratacion": "Órgano de contratación",
    "organo": "Órgano",
    "tecnologia": "Tecnología",
    "ccaa": "Comunidad autónoma",
    "count": "Licitaciones",
    "contratos": "Contratos",
    "importe": "Importe (€)",
    "importe_medio": "Importe medio (€)",
    "pct": "% del total",
    "pct_adjudicado": "% adjudicado",
    "cuota": "Cuota (%)",
    "empresa_id": "Id. de empresa",
    "nif": "NIF",
    "es_agrupacion": "Agrupación",
    "contratos_por_anio": "Contratos por año",
    "baja_media": "Baja media (%)",
    "n_organos": "Órganos",
    "ofertas_medias": "Ofertas medias",
    "pct_monopolio": "% con oferta única",
    "pct_top_organo": "% en su primer órgano",
    "ultima": "Última adjudicación",
}


def _filtros_de(modelo: type[BaseModel], filtros: Mapping[str, object]) -> dict[str, object]:
    """Solo los filtros que ese servicio entiende: los demás no los aplica su pantalla."""
    return {k: v for k, v in filtros.items() if k in modelo.model_fields and v not in (None, "")}


def filas_de_seccion(
    seccion: SeccionExport, filtros: Mapping[str, object]
) -> list[dict[str, object]]:
    """Las filas de la tabla de una sección, con los filtros que esa sección aplica.

    Sale del mismo servicio que su endpoint de analítica, así que el fichero
    dice lo mismo que la pantalla. Antes el botón «Exportar competidores» (y
    los de UTE, geografía, órganos y tecnologías) mandaba un ``section`` que
    nadie leía y bajaba el listado de licitaciones. Los campos que son listas
    (series, desgloses) se quedan fuera: no caben en una celda.
    """
    entradas: Sequence[BaseModel]
    if seccion == "competidores":
        # El tope del endpoint (100), no los 20 de la pantalla: quien exporta
        # quiere la cola también.
        competidores = CompetitorFilters.model_validate(
            {**_filtros_de(CompetitorFilters, filtros), "limit": 100}
        )
        entradas = get_competitors(competidores).competitors
    elif seccion == "utes":
        entradas = get_utes(
            UTEFilters.model_validate(_filtros_de(UTEFilters, filtros))
        ).top_miembros
    elif seccion == "geografia":
        entradas = get_geography(
            GeoFilters.model_validate(_filtros_de(GeoFilters, filtros))
        ).by_ccaa
    elif seccion == "organos":
        organos = OrganosFilters.model_validate(
            {**_filtros_de(OrganosFilters, filtros), "limit": 500}
        )
        entradas = get_organos(organos).organos
    else:
        tecnologias = TecnologiasFilters.model_validate(_filtros_de(TecnologiasFilters, filtros))
        entradas = get_tecnologias(tecnologias).tecnologias
    return [
        {
            _CABECERAS.get(k, k): v
            for k, v in entrada.model_dump().items()
            if not isinstance(v, (list, dict))
        }
        for entrada in entradas
    ]


def get_export_filename(format: ExportFormat, prefix: str = "licitaciones") -> str:
    """Return a filename like ``licitaciones_20260529.csv``."""
    date_str = datetime.now().strftime("%Y%m%d")
    return f"{prefix}_{date_str}.{_EXTENSIONS.get(format, 'csv')}"


def render_pursuits_export(
    user_id: int,
    *,
    formato: str,
    status: str | None = None,
    responsible_user_id: int | None = None,
    limit: int = 10000,
    organization_id: int | None = None,
) -> tuple[bytes, str, int]:
    """``(bytes, media_type, n_filas)`` del tablero de oportunidades (C6.7).

    Vive aquí y no en la ruta porque la ruta no puede resolver la organización
    por su cuenta: el repo lo prohíbe para que exista **un** sitio donde se
    decide con qué organización se lee (`tests/test_organization_sql_isolation.py`).

    La sanitización de fórmulas es la de siempre —`generate_csv`/`generate_excel`
    la aplican—: un `decision_reason` que empiece por `=` es una fórmula en
    Excel, y aquí el texto lo escribe el propio equipo, que es justo el caso en
    que nadie sospecha del fichero.
    """
    from db.repositories.pursuits import PursuitRepository
    from services.organizations import alcance_resuelto

    with alcance_resuelto(user_id, organization_id) as (organizacion, _role):
        rows = PursuitRepository().export_rows(
            organizacion,
            status=status,
            responsible_user_id=responsible_user_id,
            limit=limit,
        )
        if formato == "excel":
            return (
                generate_excel(rows, PURSUIT_COLUMNS),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                len(rows),
            )
        return generate_csv(rows, PURSUIT_COLUMNS), "text/csv; charset=utf-8", len(rows)


def build_pdf_export(payload: dict[str, Any]) -> tuple[bytes, int]:
    """Consulta + maquetado del PDF de exportación. Devuelve ``(bytes, filas)``.

    Una sola implementación para los dos caminos: la descarga síncrona
    (``api/routes/exports.py``) y el job de la cola (``scheduler/worker.py``).
    Si fueran dos, el PDF que llega por la cola dejaría de parecerse al que
    llega por la request en cuanto una de las dos cambiara. Vive en
    ``services/`` y no en la ruta porque el worker no puede importar
    ``api/routes/`` para ejecutar lo que un usuario encoló.
    """
    from services.licitaciones import fetch_for_pdf
    from services.pdf_tabular import construir_pdf_tabular

    ccaa = payload.get("ccaa")
    rows = fetch_for_pdf(
        ccaa=ccaa,
        estado=payload.get("estado"),
        q=payload.get("q"),
        tecnologia=payload.get("tecnologia"),
        fecha_desde=payload.get("fecha_desde"),
        fecha_hasta=payload.get("fecha_hasta"),
        importe_min=payload.get("importe_min"),
        importe_max=payload.get("importe_max"),
        provincia=payload.get("provincia"),
        procedimiento=payload.get("procedimiento"),
        solo_abiertas=bool(payload.get("solo_abiertas")),
        cierre_desde=payload.get("cierre_desde"),
        cierre_hasta=payload.get("cierre_hasta"),
        limit=int(payload.get("limit") or 10000),
    )
    title = "Licitaciones SAP — Exportación"
    if ccaa:
        title += f" ({ccaa})"
    return construir_pdf_tabular(rows, title), len(rows)
