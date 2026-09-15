"""Maquetado de un PDF tabular con reportlab.

Por qué vive aquí y no en la ruta
---------------------------------
Este maquetador nació dentro de ``api/routes/exports.py`` como ``_build_pdf``,
que es donde tenía su único consumidor: ``GET /exports/download?format=pdf``.
El plan de la Ola 2 marcó su extracción como prerrequisito de T6 —los informes
programados adjuntan un PDF que **no** se pide por HTTP— y señaló por qué no se
había hecho antes: sin ese segundo consumidor habría sido «infraestructura sin
consumidor», que es justo el defecto que aquella tanda vino a corregir. Ahora
el consumidor existe.

Lo que la extracción arregla, además de desbloquear T6: el PDF deja de estar
atrapado detrás de una ruta HTTP. Un job del scheduler no puede —ni debe—
importar `api/routes/` para maquetar una tabla.

Qué hace y qué no
-----------------
Hace **una tabla**: cabecera, filas, cebra y rejilla. No sabe de dominio, no
sabe de organizaciones y no decide qué columnas van; eso lo trae quien llama.
Los informes que necesitan varias secciones montan varios bloques y los
concatenan con :func:`construir_pdf_secciones`.

Límites deliberados
-------------------
- **500 filas por tabla.** Un PDF de veinte mil filas no lo lee nadie y sí
  tumba la memoria del proceso que lo genera. Quien quiera el volcado completo
  tiene el CSV.
- **Anchos de columna entre 40 y 180 puntos**, estimados por el contenido: sin
  el mínimo una columna de una letra se vuelve ilegible, y sin el máximo una
  descripción larga empuja el resto fuera de la página.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any
from xml.sax.saxutils import escape as _escape_xml

#: Tope de filas por tabla. Ver «Límites deliberados».
MAX_FILAS = 500

_ANCHO_MIN = 40.0
_ANCHO_MAX = 180.0
#: Puntos por carácter, estimados para Helvetica 8. No es medición real de
#: fuente: reportlab la haría, pero exige cargar la métrica y el error de esta
#: aproximación cabe dentro del recorte de `_ANCHO_MAX`.
_PUNTOS_POR_CARACTER = 5.5


def _texto(valor: Any) -> str:
    """Escapa para `Paragraph`, que **no** recibe texto plano sino mini-XML.

    reportlab interpreta `<b>`, `<i>` y, lo que importa aquí, `<img src=...>`,
    que **abre el recurso**: un fichero local o una URL. Y el título del
    informe semanal lleva dentro el nombre de la organización, que es texto
    libre del cliente (`SafeStr` sólo rechaza el byte NUL).

    O sea que sin esto una organización llamada `Acme <b>x` hacía reventar la
    generación del PDF —y el adjunto desaparecía en silencio, porque el job lo
    captura—, y una llamada `Acme <img src="http://169.254.169.254/..."/>`
    convertía al scheduler en un lector de recursos internos cuyo resultado
    acababa incrustado en un PDF y enviado por correo.

    `render_html` de `services/informes.py` ya escapaba; era el camino del PDF
    el que no.
    """
    return _escape_xml(str(valor))


def _estilo_tabla() -> Any:
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle

    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a5276")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eaf0fb")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#aab7c4")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
    )


def _tabla(rows: list[dict[str, Any]]) -> Any:
    """Una ``Table`` de reportlab a partir de las filas, o ``None`` si no hay."""
    from reportlab.platypus import Table

    if not rows:
        return None
    keys = list(rows[0].keys())
    datos = [[str(k) for k in keys]] + [[str(r.get(k, "")) for k in keys] for r in rows[:MAX_FILAS]]
    anchos = [
        max(_ANCHO_MIN, min(max(len(f[i]) for f in datos) * _PUNTOS_POR_CARACTER, _ANCHO_MAX))
        for i in range(len(keys))
    ]
    tabla = Table(datos, colWidths=anchos, repeatRows=1)
    tabla.setStyle(_estilo_tabla())
    return tabla


def construir_pdf_tabular(rows: list[dict[str, Any]], title: str) -> bytes:
    """Genera un PDF tabular simple con reportlab.

    Es el cuerpo que servía ``GET /exports/download?format=pdf`` desde F5, con
    el mismo aspecto: mover un maquetador no es el momento de rediseñarlo.
    """
    return construir_pdf_secciones(title, [(None, rows)])


def construir_pdf_secciones(
    title: str,
    secciones: list[tuple[str | None, list[dict[str, Any]]]],
    *,
    subtitulo: str | None = None,
    pie: str | None = None,
) -> bytes:
    """Un PDF con varias tablas tituladas, una detrás de otra.

    ``subtitulo`` es donde va la declaración de universo y ventana que exige
    ADR-014: un PDF con cifras y sin decir sobre qué se calcularon es un PDF
    que alguien llevará a un comité creyendo que dice otra cosa. No es
    opcional por descuido — lo es porque la exportación de un listado ya
    declara su universo en los propios filtros.
    """
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), rightMargin=20, leftMargin=20)
    estilos = getSampleStyleSheet()
    story: list[Any] = [
        Paragraph(_texto(title), estilos["Title"]),
        Paragraph(datetime.now(UTC).strftime("Generado: %Y-%m-%d %H:%M UTC"), estilos["Normal"]),
    ]
    if subtitulo:
        story.append(Paragraph(_texto(subtitulo), estilos["Normal"]))
    story.append(Spacer(1, 12))

    for encabezado, filas in secciones:
        if encabezado:
            story.append(Paragraph(_texto(encabezado), estilos["Heading2"]))
        tabla = _tabla(filas)
        story.append(
            tabla if tabla is not None else Paragraph("Sin resultados.", estilos["Normal"])
        )
        story.append(Spacer(1, 16))

    if pie:
        story.append(Paragraph(_texto(pie), estilos["Normal"]))

    doc.build(story)
    return buf.getvalue()
