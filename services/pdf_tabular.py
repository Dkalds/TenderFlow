"""Maquetado de un PDF tabular (Typst, PDF/UA-1: ``services/pdf_accesible``).

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

from collections.abc import Mapping, Sequence

from services.pdf_accesible import compilar, sello

#: Tope de filas por tabla. Ver «Límites deliberados».
MAX_FILAS = 500

_ANCHO_MIN = 40.0
_ANCHO_MAX = 180.0
#: Puntos por carácter a 8 pt. No es medición de fuente: solo reparte el ancho
#: de la página entre columnas, y el error cabe en el recorte de `_ANCHO_MAX`.
_PUNTOS_POR_CARACTER = 5.5


def _seccion(encabezado: str | None, rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Una tabla como dato para la plantilla: columnas, filas y pesos de ancho.

    El texto (el título del informe lleva el nombre de la organización, texto
    libre del cliente) viaja como dato y Typst lo pinta literal: con reportlab
    había que escaparlo porque ``Paragraph`` abría el recurso de un
    ``<img src=...>`` (ver ``services/pdf_accesible``).
    """
    if not rows:
        return {"encabezado": encabezado or "", "columnas": [], "filas": [], "anchos": []}
    keys = list(rows[0].keys())
    columnas = [str(k) for k in keys]
    filas = [[str(r.get(k, "")) for k in keys] for r in rows[:MAX_FILAS]]
    anchos = [
        max(
            _ANCHO_MIN,
            min(max(len(f[i]) for f in [columnas, *filas]) * _PUNTOS_POR_CARACTER, _ANCHO_MAX),
        )
        for i in range(len(keys))
    ]
    return {"encabezado": encabezado or "", "columnas": columnas, "filas": filas, "anchos": anchos}


def construir_pdf_tabular(rows: Sequence[Mapping[str, object]], title: str) -> bytes:
    """Genera un PDF tabular simple: una sola tabla bajo el título.

    Es el cuerpo que servía ``GET /exports/download?format=pdf`` desde F5.
    """
    return construir_pdf_secciones(title, [(None, rows)])


def construir_pdf_secciones(
    title: str,
    secciones: Sequence[tuple[str | None, Sequence[Mapping[str, object]]]],
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
    return compilar(
        "tabular",
        {
            "titulo": str(title),
            "subtitulo": subtitulo or "",
            "generado": sello("Generado: %Y-%m-%d %H:%M UTC"),
            "secciones": [_seccion(encabezado, filas) for encabezado, filas in secciones],
            "pie": pie or "",
        },
    )
