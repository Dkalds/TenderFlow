"""Piezas comunes del HTML de los correos: colores de marca, cabecera y plurales.

Cada correo se escribe a mano en su módulo (no hay motor de plantillas), pero
la paleta, el ``<head>`` y la forma de contar no pueden divergir entre ellos:
viven aquí.

Los colores replican ``web/src/lib/marca.ts`` (``MARCA_HEX``), que es la copia
de la marca para lo que se pinta fuera del navegador. Si cambia allí, cambia
aquí. Todo color de texto sobre blanco cumple 4,5:1 (WCAG AA); lo comprueba
``tests/test_unit_email_html.py``. El naranja claro de la marca (``naranja``,
``#F39349``) no está a propósito: sobre blanco no llega a 2,5:1.
"""

from __future__ import annotations

#: ``MARCA_HEX.tinta``: texto principal.
TINTA = "#0E0D0C"
#: ``MARCA_HEX.oxido`` (el ``--primary`` del tema claro): enlaces y botones.
OXIDO = "#9A4513"
#: ``MARCA_HEX.papel``: fondo de cabeceras de tabla y bordes suaves.
PAPEL = "#EFEEEB"
#: Texto secundario. ``marca.ts`` no tiene un gris válido sobre blanco (``gris``
#: está pensado para ir sobre ``tinta`` y aquí daría 3:1), así que es el
#: ``--muted-foreground`` del tema claro de ``web/src/app/globals.css``.
SECUNDARIO = "#5E5850"
#: Fondo del correo y texto sobre ``OXIDO``.
BLANCO = "#FFFFFF"

#: Estilo base del ``<body>``: 14 px para el cuerpo y las tablas. Solo el pie
#: legal y de baja baja a 12 px (:data:`ESTILO_PIE`).
ESTILO_BODY = (
    f"font-family:Arial,sans-serif;font-size:14px;color:{TINTA};"
    f"background:{BLANCO};line-height:1.5;margin:0 auto"
)
ESTILO_PIE = f"font-size:12px;color:{SECUNDARIO}"
ESTILO_ENLACE = f"color:{OXIDO}"


def abrir_documento(*, max_ancho: int = 640) -> str:
    """``<!DOCTYPE>``, ``<html lang="es">``, ``<head>`` y la apertura del ``<body>``.

    ``color-scheme: light`` le dice al cliente que el correo está pensado para
    fondo claro: sin eso, algunos invierten los colores en modo oscuro y el
    óxido sobre negro deja de leerse.
    """
    return (
        '<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="color-scheme" content="light">'
        '<meta name="supported-color-schemes" content="light">'
        f'</head><body style="{ESTILO_BODY};max-width:{max_ancho}px">'
    )


CERRAR_DOCUMENTO = "</body></html>"


def contar(n: int, singular: str, plural: str) -> str:
    """``"1 solicitud"`` / ``"3 solicitudes"``: el número con su palabra concordada."""
    return f"{n} {singular if n == 1 else plural}"
