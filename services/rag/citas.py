"""Citas estructuradas de las respuestas del asistente (C5.3, D29).

El defecto que corrige
----------------------
Los fragmentos de pliego entran al prompt con su documento y su página
(``llm/prompts.py``), y la respuesta sale como **texto libre**: quien la lee no
puede comprobar de dónde viene cada afirmación sin abrir los pliegos y buscarla
a mano. El único modo que exigía referencias era el de extracción de ficha
(``evidence`` con ``documento_id``, ``page_number`` y cita literal); el modo
conversacional no exigía ninguna.

La diferencia importa más aquí que en la ficha: la ficha la revisa alguien antes
de usarla, y la respuesta del asistente se lee y se cree.

Cómo funciona
-------------
El prompt de ``licitacion`` pide marcar cada afirmación con ``[doc:N p.M]``
(``p.M`` opcional). Este módulo:

1. **Extrae** los marcadores del texto ya generado.
2. **Valida** cada uno contra los chunks que se le mandaron al modelo: un
   ``documento_id`` que no estaba en el contexto es una cita inventada y se
   descarta. Es el mismo criterio que ``_validated_evidence`` aplica en la ficha
   —la validación va contra lo que se envió, no contra lo que el modelo dice—
   porque un modelo que alucina una fuente alucina también su contenido.
3. **Declara la ausencia**: cuando no queda ninguna cita válida, el evento lo
   dice (``sin_fuentes``) en vez de omitir el campo. Omitirlo haría
   indistinguible «el pliego no lo dice» de «el evento no llegó», y la UI
   pintaría igual una respuesta fundada y una que no lo está.

Qué NO hace
-----------
No reescribe la respuesta ni borra marcadores inválidos del texto: el usuario ve
lo que el modelo escribió, y el evento dice qué parte de eso se sostiene. Borrar
en silencio una cita inventada dejaría una afirmación con aspecto de fundada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: `[doc:12 p.3]`, `[doc:12, p.3]`, `[doc:12]`. Tolerante con el espaciado
#: porque el modelo lo varía; estricta con la forma, porque un marcador laxo
#: capturaría cualquier corchete de la respuesta.
_MARCADOR = re.compile(r"\[doc:\s*(\d+)(?:\s*[,;]?\s*p\.?\s*(\d+))?\s*\]", re.IGNORECASE)

#: Longitud de la cita que viaja en el evento.
#:
#: El marcador apunta a un fragmento, no a una frase, así que la «cita» es el
#: arranque de ese fragmento: suficiente para reconocerlo en la página y corto
#: para no reenviar el pliego por el stream.
MAX_CITA_CHARS = 240


@dataclass(frozen=True)
class Cita:
    """Una referencia validada contra el contexto que se envió al modelo."""

    documento_id: int
    page_number: int | None
    cita: str
    tipo: str | None = None
    filename: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "documento_id": self.documento_id,
            "page_number": self.page_number,
            "cita": self.cita,
            "tipo": self.tipo,
            "filename": self.filename,
        }


def extraer_marcadores(texto: str) -> list[tuple[int, int | None]]:
    """`(documento_id, page_number)` de cada marcador, en orden y sin repetir."""
    vistos: list[tuple[int, int | None]] = []
    for doc, pagina in _MARCADOR.findall(texto or ""):
        clave = (int(doc), int(pagina) if pagina else None)
        if clave not in vistos:
            vistos.append(clave)
    return vistos


def _extracto(chunk: dict[str, Any]) -> str:
    texto = " ".join(str(chunk.get("texto") or "").split())
    if len(texto) <= MAX_CITA_CHARS:
        return texto
    return texto[:MAX_CITA_CHARS].rsplit(" ", 1)[0] + "…"


def validar(
    texto: str, chunks: list[dict[str, Any]] | None
) -> tuple[list[Cita], list[tuple[int, int | None]]]:
    """Separa los marcadores del texto en válidos e inventados.

    Un marcador es válido cuando el contexto enviado traía un chunk de ese
    documento. Si el marcador declara página, se prefiere el chunk de esa
    página; si ninguno la tiene, la cita se conserva **sin página** en vez de
    descartarse: el documento sí estaba, y perder la cita entera por una página
    equivocada castiga al lector más que al modelo.

    Returns:
        `(validas, invalidas)`. `invalidas` son los marcadores cuyo documento no
        estaba en el contexto — citas inventadas.
    """
    por_documento: dict[int, list[dict[str, Any]]] = {}
    for chunk in chunks or []:
        doc_id = chunk.get("documento_id")
        if doc_id is None:
            continue
        por_documento.setdefault(int(doc_id), []).append(chunk)

    validas: list[Cita] = []
    invalidas: list[tuple[int, int | None]] = []
    for documento_id, page_number in extraer_marcadores(texto):
        candidatos = por_documento.get(documento_id)
        if not candidatos:
            invalidas.append((documento_id, page_number))
            continue
        elegido = candidatos[0]
        pagina_final: int | None = None
        if page_number is not None:
            en_pagina = [
                c
                for c in candidatos
                if c.get("page_number") is not None and int(c["page_number"]) == page_number
            ]
            if en_pagina:
                elegido = en_pagina[0]
                pagina_final = page_number
        if pagina_final is None and elegido.get("page_number") is not None:
            pagina_final = int(elegido["page_number"])
        validas.append(
            Cita(
                documento_id=documento_id,
                page_number=pagina_final,
                cita=_extracto(elegido),
                tipo=(str(elegido["tipo"]) if elegido.get("tipo") else None),
                filename=(str(elegido["filename"]) if elegido.get("filename") else None),
            )
        )
    return validas, invalidas


def evento_sources(texto: str, chunks: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Evento SSE ``sources``, aditivo al stream (nunca al DTO).

    Se emite **siempre** en modo licitación, incluso vacío: `sin_fuentes` es la
    señal que la UI necesita para pintar distinto una respuesta que el pliego no
    sostiene. `descartadas` cuenta las citas inventadas — es la métrica que dice
    si el prompt está funcionando, y no se puede reconstruir después.
    """
    validas, invalidas = validar(texto, chunks)
    return {
        "sources": [c.as_dict() for c in validas],
        "sin_fuentes": not validas,
        "descartadas": len(invalidas),
    }
