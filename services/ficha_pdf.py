"""F2.7 — la ficha de una oportunidad en un PDF que se lleva a dirección.

Quien tiene que defender un go/no-go delante de un comité no puede llevar una
URL con sesión: lleva un papel. Hoy no existe ninguno, así que ese papel se
rehace a mano en un slide, y en el trayecto se pierde justo lo que el producto
aporta — de cuándo es el dato y sobre cuántos casos se calculó.

Las dos reglas del documento
----------------------------
1. **Un bloque sin datos se omite con nota, no se rellena.** Un one-pager con
   «Competencia esperada: —» junto a «Escenarios de precio: —» se lee como que
   el producto no sabe nada; una nota que dice qué falta y por qué se lee como
   trazabilidad. Es ADR-014 llevado al papel.
2. **Cada bloque declara su universo y su fecha.** Es lo primero que pregunta
   quien recibe el papel («¿esto de cuándo es?») y lo primero que se pierde al
   copiar cifras a mano.

Aislamiento
-----------
La función recibe una ficha **ya leída con ámbito de organización** por la
ruta. No consulta nada por su cuenta: así no puede haber una consulta aquí que
se olvide del `organization_id`, que es la forma en que una exportación acaba
enseñando datos de otra organización.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

__all__ = ["BloqueFicha", "FichaOportunidad", "construir_pdf"]

#: Ancho máximo de una celda de texto antes de recortarla. Un valor largo
#: —un título de expediente de 400 caracteres— rompe la tabla de reportlab en
#: vez de envolverse, y el recorte es preferible a una página ilegible.
_MAX_CELDA = 220


@dataclass(frozen=True, slots=True)
class BloqueFicha:
    """Una sección del one-pager.

    ``filas`` son pares etiqueta/valor. ``procedencia`` es la línea pequeña con
    el universo, la ventana y la ``n``: no es opcional por diseño —un bloque
    que no puede decir de dónde sale su cifra no debería estar en el papel—,
    pero se admite vacía para los bloques que sólo repiten dato publicado por
    la fuente (título, órgano, importe), donde la procedencia es evidente.
    """

    titulo: str
    filas: list[tuple[str, str]] = field(default_factory=list)
    procedencia: str = ""
    #: Por qué está vacío, cuando lo está. Se imprime en lugar de las filas.
    nota_vacio: str = ""

    @property
    def vacio(self) -> bool:
        return not self.filas


@dataclass(frozen=True, slots=True)
class FichaOportunidad:
    """Todo lo que va al papel, ya resuelto y sin acceso a BD."""

    titulo: str
    subtitulo: str
    bloques: list[BloqueFicha]


def _texto(valor: Any) -> str:
    """Valor listo para una celda: nunca ``None``, nunca sin recortar."""
    if valor is None:
        return "—"
    texto = str(valor).strip()
    if not texto:
        return "—"
    return texto if len(texto) <= _MAX_CELDA else texto[: _MAX_CELDA - 1] + "…"


def construir_pdf(ficha: FichaOportunidad) -> bytes:
    """Renderiza el one-pager. ``reportlab`` ya es dependencia del proyecto.

    Los imports van dentro de la función, como en ``api/routes/exports.py``:
    ``reportlab`` tarda ~200 ms en importarse y este módulo lo carga cualquier
    proceso que toque `services/`, incluidos los jobs que no exportan nada.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        title=ficha.titulo,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    base = getSampleStyleSheet()
    estilo_procedencia = ParagraphStyle(
        "procedencia",
        parent=base["Normal"],
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#5b6b7c"),
    )
    estilo_seccion = ParagraphStyle(
        "seccion",
        parent=base["Heading2"],
        fontSize=11,
        spaceAfter=2,
        textColor=colors.HexColor("#1a5276"),
    )

    story: list[Any] = [
        Paragraph(_texto(ficha.titulo), base["Title"]),
        Paragraph(_texto(ficha.subtitulo), base["Normal"]),
        Paragraph(
            datetime.now(UTC).strftime("Generado el %Y-%m-%d a las %H:%M UTC"),
            estilo_procedencia,
        ),
        Spacer(1, 10),
    ]

    for bloque in ficha.bloques:
        partes: list[Any] = [Paragraph(_texto(bloque.titulo), estilo_seccion)]
        if bloque.vacio:
            # La nota es el contenido del bloque, no un pie: es lo que impide
            # que el lector interprete el hueco como un cero.
            partes.append(
                Paragraph(
                    _texto(bloque.nota_vacio or "Sin datos suficientes para este bloque."),
                    estilo_procedencia,
                )
            )
        else:
            tabla = Table(
                [[_texto(etiqueta), _texto(valor)] for etiqueta, valor in bloque.filas],
                colWidths=[52 * mm, 112 * mm],
            )
            tabla.setStyle(
                TableStyle(
                    [
                        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#42526b")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#e2e8f0")),
                    ]
                )
            )
            partes.append(tabla)
            if bloque.procedencia:
                partes.append(Paragraph(_texto(bloque.procedencia), estilo_procedencia))
        partes.append(Spacer(1, 9))
        # `KeepTogether`: un bloque partido entre páginas deja su procedencia
        # huérfana en la siguiente, que es justo la línea que no puede
        # separarse de la cifra que califica.
        story.append(KeepTogether(partes))

    doc.build(story)
    return buf.getvalue()
