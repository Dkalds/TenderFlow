"""F5.1 a F5.4 — avisos con nombre, en vez de «algo cambió».

La campana tenía dos tipos de aviso —vencimiento y coincidencia de regla— y
un genérico «este expediente ha cambiado». Ese genérico es el problema: un
plazo ampliado nueve días, una anulación y una corrección de importe llegan
con el mismo texto, así que quien recibe tres al día deja de abrirlos, y el
que importaba se pierde con los otros dos.

Este módulo pone nombre a lo que pasó. Es **puro**: recibe el estado anterior
y el nuevo y devuelve el subtipo y su texto. Ni consulta ni escribe, así que
se prueba entero sin BD y el mismo juicio vale para la campana, el digest y
«qué cambió desde tu última visita».

La regla que evita el peor fallo
--------------------------------
Un cambio que no encaja en ningún subtipo **cae al genérico**, no se descarta.
Perder un aviso por no saber nombrarlo sería peor que el problema que este
módulo resuelve.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

__all__ = [
    "CATALOGO_AVISOS",
    "SUBTIPOS",
    "Aviso",
    "SubtipoAviso",
    "clasificar_cambio",
    "etiqueta_de",
]

#: Vocabulario cerrado de avisos. Los cuatro primeros son los que F5.3 nombra;
#: `documento_nuevo` es F5.1, `recurso` F5.2, y `cambio` es el cajón.
SubtipoAviso = Literal[
    "anulado",
    "desierto",
    "plazo_ampliado",
    "plazo_acortado",
    "importe_corregido",
    "adjudicado",
    "documento_nuevo",
    "recurso",
    "cambio",
]

SUBTIPOS: Final[tuple[str, ...]] = (
    "anulado",
    "desierto",
    "plazo_ampliado",
    "plazo_acortado",
    "importe_corregido",
    "adjudicado",
    "documento_nuevo",
    "recurso",
    "cambio",
)

#: Etiqueta corta por subtipo, para agrupar el digest y para el icono. El texto
#: **con los datos concretos** lo compone `clasificar_cambio`; esto es sólo el
#: nombre de la clase de aviso.
CATALOGO_AVISOS: Final[dict[str, str]] = {
    "anulado": "Expediente anulado",
    "desierto": "Declarado desierto",
    "plazo_ampliado": "Plazo ampliado",
    "plazo_acortado": "Plazo acortado",
    "importe_corregido": "Importe corregido",
    "adjudicado": "Expediente adjudicado",
    "documento_nuevo": "Documento nuevo",
    "recurso": "Recurso resuelto",
    "cambio": "Cambio en el expediente",
}

#: Estados que la fuente usa para «no se adjudicó a nadie». `ANUL` es la
#: anulación por el órgano; el desierto no tiene código propio en PLACSP y se
#: detecta por el resultado, así que se acepta también por el campo de
#: resultado cuando llega.
_ESTADO_ANULADO = "ANUL"
_ESTADO_ADJUDICADO = "ADJ"


@dataclass(frozen=True, slots=True)
class Aviso:
    """Un cambio ya clasificado, listo para la campana."""

    subtipo: SubtipoAviso
    #: Titular con el dato concreto: «Plazo ampliado al 12/10».
    titulo: str
    #: Segunda línea, cuando aporta. `None` si el titular ya lo dice todo.
    detalle: str | None = None


def etiqueta_de(subtipo: str) -> str:
    """Nombre de la clase de aviso. Un subtipo desconocido se degrada al
    genérico en vez de mostrarse en crudo."""
    return CATALOGO_AVISOS.get(subtipo, CATALOGO_AVISOS["cambio"])


def _fecha_corta(iso: Any) -> str:
    """`12/10/2026` a partir de un ISO. El texto lo lee una persona."""
    texto = str(iso or "")[:10]
    partes = texto.split("-")
    return f"{partes[2]}/{partes[1]}/{partes[0]}" if len(partes) == 3 else texto


def _euros(valor: Any) -> str:
    try:
        return f"{float(valor):,.0f} €".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def clasificar_cambio(
    anterior: dict[str, Any],
    actual: dict[str, Any],
    changed_fields: list[str] | None = None,
) -> Aviso:
    """Pone nombre a lo que cambió entre dos versiones del expediente.

    ``changed_fields`` es lo que ya guarda ``licitaciones_history``; se usa
    como pista, pero la decisión se toma comparando los valores, porque un
    campo puede estar listado como cambiado y haber vuelto a su valor anterior.

    El orden importa: **primero lo terminal** (anulado, desierto, adjudicado),
    porque un expediente que se anula normalmente cambia también de fecha y de
    importe, y avisar de «importe corregido» cuando lo que ha pasado es que se
    ha anulado sería exacto y completamente inútil.
    """
    campos = set(changed_fields or [])
    estado_nuevo = str(actual.get("estado") or "").strip().upper()
    estado_viejo = str(anterior.get("estado") or "").strip().upper()

    if estado_nuevo != estado_viejo:
        if estado_nuevo == _ESTADO_ANULADO:
            return Aviso("anulado", "Expediente anulado", "Ya no se puede presentar oferta.")
        if estado_nuevo == _ESTADO_ADJUDICADO:
            return Aviso("adjudicado", "Expediente adjudicado")

    # Desierto: no tiene código de estado propio en PLACSP. Llega por el
    # resultado, y sólo se afirma cuando la fuente lo dice — nunca se deduce
    # de «adjudicado sin adjudicatario», que también es un hueco de ingesta.
    resultado = str(actual.get("resultado") or "").strip().lower()
    if "desiert" in resultado and "desiert" not in str(anterior.get("resultado") or "").lower():
        return Aviso("desierto", "Declarado desierto", "El órgano no adjudicó a nadie.")

    limite_viejo = str(anterior.get("fecha_limite") or "")[:10]
    limite_nuevo = str(actual.get("fecha_limite") or "")[:10]
    if limite_nuevo and limite_viejo and limite_nuevo != limite_viejo:
        # Comparación lexicográfica: son ISO, así que ordena como la fecha.
        if limite_nuevo > limite_viejo:
            return Aviso(
                "plazo_ampliado",
                f"Plazo ampliado al {_fecha_corta(limite_nuevo)}",
                f"Antes cerraba el {_fecha_corta(limite_viejo)}.",
            )
        return Aviso(
            "plazo_acortado",
            f"Plazo acortado al {_fecha_corta(limite_nuevo)}",
            f"Antes cerraba el {_fecha_corta(limite_viejo)}.",
        )

    importe_viejo = anterior.get("importe")
    importe_nuevo = actual.get("importe")
    if importe_nuevo is not None and importe_viejo is not None:
        try:
            distinto = abs(float(importe_nuevo) - float(importe_viejo)) > 0.005
        except (TypeError, ValueError):
            distinto = False
        if distinto:
            return Aviso(
                "importe_corregido",
                f"Importe corregido a {_euros(importe_nuevo)}",
                f"Antes era {_euros(importe_viejo)}.",
            )

    # Cajón. Lleva los campos para que el aviso genérico diga al menos qué
    # tocaron, en vez de «algo cambió».
    detalle = ", ".join(sorted(campos)[:5]) if campos else None
    return Aviso("cambio", "Cambio en el expediente", detalle)


def aviso_documento_nuevo(tipo_documento: str | None) -> Aviso:
    """F5.1 — un adjunto nuevo en un expediente seguido.

    El tipo va en el titular porque decide si hay que dejarlo todo: un pliego
    publicado después del anuncio, una rectificación o las respuestas a
    consultas no piden lo mismo.
    """
    tipo = (tipo_documento or "").strip()
    return Aviso(
        "documento_nuevo",
        f"Documento nuevo: {tipo}" if tipo else "Documento nuevo en el expediente",
        "Publicado después del anuncio.",
    )


def aviso_recurso(sentido: str | None) -> Aviso:
    """F5.2 — una resolución de recurso sobre un expediente seguido.

    El sentido va en el titular por el mismo motivo: un recurso estimado puede
    reabrir el plazo, y uno inadmitido no cambia nada.
    """
    normalizado = (sentido or "").strip().lower()
    legible = {
        "estimado": "estimado",
        "desestimado": "desestimado",
        "inadmitido": "inadmitido",
    }.get(normalizado)
    if legible is None:
        return Aviso("recurso", "Resolución de recurso publicada")
    return Aviso("recurso", f"Recurso {legible}")
