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

from dataclasses import dataclass, field

from services.pdf_accesible import compilar, sello

__all__ = ["BloqueFicha", "FichaOportunidad", "construir_pdf"]

#: Ancho máximo de una celda de texto antes de recortarla. Un valor de 400
#: caracteres —un título de expediente— se lee peor envuelto en seis líneas que
#: recortado, y empuja el bloque entero a la página siguiente.
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


def _texto(valor: object) -> str:
    """Valor listo para una celda: nunca ``None``, nunca sin recortar."""
    if valor is None:
        return "—"
    texto = str(valor).strip()
    if not texto:
        return "—"
    return texto if len(texto) <= _MAX_CELDA else texto[: _MAX_CELDA - 1] + "…"


def construir_pdf(ficha: FichaOportunidad) -> bytes:
    """Renderiza el one-pager (``plantillas_pdf/ficha.typ``), PDF/UA-1.

    El texto viaja como dato, no como marcado: un título de licitación con
    ``<b>`` o ``<img src=...>`` sale literal (ver ``services/pdf_accesible``).
    Un bloque vacío imprime su nota en lugar de la tabla: la nota es el
    contenido, lo que impide que el lector interprete el hueco como un cero.
    """
    return compilar(
        "ficha",
        {
            "titulo": _texto(ficha.titulo),
            "subtitulo": _texto(ficha.subtitulo),
            "generado": sello("Generado el %Y-%m-%d a las %H:%M UTC"),
            "bloques": [
                {
                    "titulo": _texto(bloque.titulo),
                    "filas": [[_texto(e), _texto(v)] for e, v in bloque.filas],
                    "procedencia": (bloque.procedencia or "").strip(),
                    "nota": _texto(bloque.nota_vacio or "Sin datos suficientes para este bloque."),
                }
                for bloque in ficha.bloques
            ],
        },
    )
