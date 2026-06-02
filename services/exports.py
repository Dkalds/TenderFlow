"""Export service — CSV, Excel, PDF generation from licitaciones data."""

from __future__ import annotations

import io
from datetime import datetime
from typing import Literal

import pandas as pd

from observability.logging import get_logger

logger = get_logger(__name__)

ExportFormat = Literal["csv", "excel"]

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


def generate_csv(
    records: list[dict[str, object]],
    columns: list[str] | None = None,
) -> bytes:
    """Generate CSV bytes with UTF-8 BOM and semicolon delimiter for Excel compat."""
    cols = columns or _DEFAULT_COLUMNS
    df = pd.DataFrame(records)
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
    df = pd.DataFrame(records)
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


def get_export_filename(format: ExportFormat, prefix: str = "licitaciones") -> str:
    """Return a filename like ``licitaciones_20260529.csv``."""
    date_str = datetime.now().strftime("%Y%m%d")
    ext = "csv" if format == "csv" else "xlsx"
    return f"{prefix}_{date_str}.{ext}"
