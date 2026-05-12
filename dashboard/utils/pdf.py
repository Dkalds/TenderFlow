"""Generador de PDF «informe ejecutivo» de licitaciones SAP.

Usa reportlab para generar un PDF con:
- Portada con filtros aplicados y fecha de generación
- KPIs principales
- Tabla top-10 oportunidades
- Charts exportados como imágenes (pasados como bytes PNG)
"""

from __future__ import annotations

import html as _html
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_BRAND_COLOR = colors.HexColor("#1B4F72")
_LIGHT_BG = colors.HexColor("#EBF5FB")
_WHITE = colors.white


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "PDFTitle",
            parent=base["Title"],
            fontSize=22,
            textColor=_BRAND_COLOR,
            spaceAfter=6 * mm,
        ),
        "subtitle": ParagraphStyle(
            "PDFSubtitle",
            parent=base["Heading2"],
            fontSize=14,
            textColor=_BRAND_COLOR,
            spaceBefore=8 * mm,
            spaceAfter=4 * mm,
        ),
        "body": ParagraphStyle(
            "PDFBody",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
        ),
        "kpi_label": ParagraphStyle(
            "KPILabel",
            parent=base["Normal"],
            fontSize=9,
            textColor=colors.gray,
        ),
        "kpi_value": ParagraphStyle(
            "KPIValue",
            parent=base["Normal"],
            fontSize=14,
            textColor=_BRAND_COLOR,
            leading=18,
        ),
        "meta": ParagraphStyle(
            "PDFMeta",
            parent=base["Normal"],
            fontSize=8,
            textColor=colors.gray,
        ),
    }


def generate_pdf(
    *,
    kpis: dict[str, str],
    filtros: dict[str, str],
    top_oportunidades: list[dict[str, Any]],
    chart_images: list[tuple[str, bytes]] | None = None,
    titulo: str = "Informe Ejecutivo — Licitaciones SAP",
) -> bytes:
    """Genera un PDF en memoria y devuelve los bytes.

    Args:
        kpis: {label: valor_formateado} — los KPIs principales.
        filtros: {nombre_filtro: valor} — filtros activos al generar.
        top_oportunidades: lista de dicts con las top oportunidades.
        chart_images: lista de (titulo, png_bytes) con charts.
        titulo: título del informe.

    Returns:
        Bytes del PDF generado.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
    )
    s = _styles()
    story: list[Any] = []

    # ── Portada ──────────────────────────────────────────────────────
    story.append(Spacer(1, 3 * cm))
    story.append(Paragraph(titulo, s["title"]))

    import pandas as pd

    ts = pd.Timestamp.now("UTC").strftime("%d/%m/%Y %H:%M UTC")
    story.append(Paragraph(f"Generado: {ts}", s["meta"]))
    story.append(Spacer(1, 1 * cm))

    if filtros:
        filtros_text = " · ".join(
            f"<b>{_html.escape(str(k))}</b>: {_html.escape(str(v))}"
            for k, v in filtros.items()
        )
        story.append(Paragraph(f"Filtros: {filtros_text}", s["body"]))
        story.append(Spacer(1, 5 * mm))

    # ── KPIs ─────────────────────────────────────────────────────────
    story.append(Paragraph("KPIs principales", s["subtitle"]))

    kpi_data = []
    kpi_row_labels: list[Any] = []
    kpi_row_values: list[Any] = []
    for label, value in kpis.items():
        kpi_row_labels.append(Paragraph(label, s["kpi_label"]))
        kpi_row_values.append(Paragraph(str(value), s["kpi_value"]))
        if len(kpi_row_labels) == 4:
            kpi_data.append(kpi_row_labels)
            kpi_data.append(kpi_row_values)
            kpi_row_labels = []
            kpi_row_values = []
    if kpi_row_labels:
        # Pad remaining cells
        while len(kpi_row_labels) < 4:
            kpi_row_labels.append("")
            kpi_row_values.append("")
        kpi_data.append(kpi_row_labels)
        kpi_data.append(kpi_row_values)

    if kpi_data:
        col_width = (A4[0] - 4 * cm) / 4
        t = Table(kpi_data, colWidths=[col_width] * 4)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), _LIGHT_BG),
                    ("BOX", (0, 0), (-1, -1), 0.5, _BRAND_COLOR),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(t)

    # ── Top oportunidades ────────────────────────────────────────────
    if top_oportunidades:
        story.append(Paragraph("Top oportunidades por importe", s["subtitle"]))

        header = ["Título", "Órgano", "Importe", "Estado", "CPV"]
        rows = [header]
        for opp in top_oportunidades[:10]:
            titulo_cell = str(opp.get("titulo", ""))[:80]
            rows.append(
                [
                    Paragraph(titulo_cell, s["body"]),
                    Paragraph(str(opp.get("organo_contratacion", "—"))[:40], s["body"]),
                    str(opp.get("importe_fmt", "—")),
                    str(opp.get("estado_desc", "—")),
                    str(opp.get("cpv", "—"))[:10],
                ]
            )

        col_widths = [6.5 * cm, 4 * cm, 2.5 * cm, 2.5 * cm, 2 * cm]
        t = Table(rows, colWidths=col_widths, repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), _BRAND_COLOR),
                    ("TEXTCOLOR", (0, 0), (-1, 0), _WHITE),
                    ("FONTSIZE", (0, 0), (-1, 0), 9),
                    ("FONTSIZE", (0, 1), (-1, -1), 8),
                    ("BACKGROUND", (0, 1), (-1, -1), _LIGHT_BG),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_WHITE, _LIGHT_BG]),
                    ("BOX", (0, 0), (-1, -1), 0.5, _BRAND_COLOR),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(t)

    # ── Charts ───────────────────────────────────────────────────────
    if chart_images:
        story.append(PageBreak())
        for chart_title, png_bytes in chart_images:
            story.append(Paragraph(chart_title, s["subtitle"]))
            img_buf = BytesIO(png_bytes)
            img = Image(img_buf, width=16 * cm, height=9 * cm, kind="proportional")
            story.append(img)
            story.append(Spacer(1, 8 * mm))

    doc.build(story)
    return buf.getvalue()
