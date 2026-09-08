"""Export service — CSV, Excel, PDF generation from licitaciones data."""

from __future__ import annotations

import io
from datetime import datetime
from typing import Literal

import pandas as pd

from observability.logging import get_logger
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
    records: list[dict[str, object]],
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
    records: list[dict[str, object]],
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
    from services.organizations import resolve_organization

    organizacion, _role = resolve_organization(user_id, organization_id)
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
