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


#: Columnas del export del pipeline (C6.7). El orden es el de lectura: qué
#: expediente, en qué estado, de quién, por cuánto y con qué próximo paso.
PURSUIT_COLUMNS = [
    "organizacion",
    "exportado_en",
    "id_externo",
    "titulo",
    "estado",
    "decision",
    "responsable",
    "importe_ofertado_eur",
    "resultado",
    "importe_adjudicado_eur",
    "proxima_accion",
    "proxima_accion_vence",
    "fecha_limite",
    "identificado_en",
    "actualizado_en",
]


def pursuit_rows(
    pursuits: list[dict[str, object]],
    *,
    organizacion: str,
    exportado_en: str,
) -> list[dict[str, object]]:
    """Filas del export del pipeline, con su procedencia en cada fila.

    ``organizacion`` y ``exportado_en`` van como **columnas** y no como una
    línea de comentario antes de la cabecera: un `# …` inicial rompe
    `pd.read_csv` por defecto y la importación de Excel, y el fichero acabaría
    siendo menos utilizable justo para quien lo abre en una hoja de cálculo. Van
    en cada fila porque un CSV se corta, se pega y se filtra: la procedencia
    tiene que sobrevivir a eso.
    """
    return [
        {
            "organizacion": organizacion,
            "exportado_en": exportado_en,
            "id_externo": p.get("licitacion_id"),
            "titulo": p.get("tender_title"),
            "estado": p.get("status"),
            "decision": p.get("decision"),
            "responsable": p.get("responsible_name"),
            "importe_ofertado_eur": p.get("offer_price_eur"),
            "resultado": p.get("outcome"),
            "importe_adjudicado_eur": p.get("awarded_amount_eur"),
            "proxima_accion": p.get("next_action"),
            "proxima_accion_vence": p.get("next_action_due"),
            "fecha_limite": p.get("tender_deadline"),
            "identificado_en": p.get("identified_at"),
            "actualizado_en": p.get("updated_at"),
        }
        for p in pursuits
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
