"""Menciones ``@nombre`` en los comentarios de una oportunidad (C6.2).

Qué resuelve
------------
Un hilo de comentarios sin menciones obliga a leerlo entero para saber si algo
te toca. «@ana ¿tenemos la clasificación?» es una pregunta dirigida; sin
mención, es una frase que Ana verá cuando entre, si entra.

Las tres reglas
---------------
1. **Sólo miembros activos de la organización.** Un `invited` todavía no ha
   entrado y un `revoked` ya no está; mencionarlos no notifica a nadie y
   además diría, a quien escribe, que esa persona sigue en el equipo.
2. **Lo ambiguo no se resuelve.** Con dos «Ana» en el equipo, `@ana` no
   notifica a ninguna. Elegir una es peor que no elegir: la mención llega a
   quien no era y la persona a la que iba dirigida no se entera, que son los
   dos fallos a la vez. La interfaz debe ofrecer el nombre completo.
3. **Se guardan los ``user_id``, no el texto resuelto.** Si mañana alguien
   cambia su nombre visible, la mención sigue apuntando a la misma persona. Al
   revés —guardar «@Ana Pérez» resuelto— convierte el hilo en un registro de
   nombres viejos.

Cómo se escribe una mención
---------------------------
``@`` seguido de letras, dígitos, puntos, guiones y espacios simples, hasta un
máximo de tres palabras: el nombre visible de una persona rara vez pasa de eso y
un límite alto haría que «@ana y el resto del equipo» intentara resolver la
frase entera. La coincidencia es por prefijo sobre el nombre visible plegado
(sin acentos, en minúsculas) y también sobre la parte local del email, que es
como la gente escribe las menciones cuando el nombre visible está vacío.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

#: Hasta tres palabras tras la arroba. Se prueban de la más larga a la más
#: corta: «@ana maria lopez» debe ganar a «@ana» cuando las dos existen.
_MENCION_RE = re.compile(r"@([A-Za-zÀ-ÿ0-9._-]+(?:[ ][A-Za-zÀ-ÿ0-9._-]+){0,2})")

#: Estados de membresía que reciben menciones.
ESTADO_ACTIVO = "active"


def _plegar(texto: str) -> str:
    """Minúsculas sin acentos: «Ana Pérez» y «ana perez» son la misma persona."""
    sin_acentos = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sin_acentos if not unicodedata.combining(c)).strip().lower()


def extraer(texto: str) -> list[str]:
    """Texto que sigue a cada ``@``, tal y como se escribió y en orden.

    Una arroba, un candidato. Resolverlo es cosa de :func:`resolver`, que
    necesita la lista de miembros.
    """
    return list(_MENCION_RE.findall(texto or ""))


def _prefijos(candidato: str) -> list[str]:
    """Prefijos por palabras, del más largo al más corto.

    «@ana maria lopez» se prueba como «ana maria lopez», «ana maria» y «ana»:
    el más largo primero, que es el que menos ambigüedad tiene. Como el regex
    se lleva hasta tres palabras, el candidato arrastra las que siguen a la
    mención («@Ana María revisa») y hay que poder descartarlas.
    """
    palabras = candidato.split(" ")
    return [" ".join(palabras[:n]) for n in range(len(palabras), 0, -1)]


def _indice(miembros: list[dict[str, Any]]) -> dict[str, set[int]]:
    """``clave plegada -> {user_id}``. Un conjunto por clave: así la ambigüedad se ve."""
    indice: dict[str, set[int]] = {}
    for miembro in miembros:
        if str(miembro.get("status") or "") != ESTADO_ACTIVO:
            continue
        user_id = miembro.get("user_id")
        if user_id is None:
            continue
        claves = {_plegar(str(miembro.get("display_name") or ""))}
        email = str(miembro.get("email") or "")
        if "@" in email:
            claves.add(_plegar(email.split("@", 1)[0]))
        for clave in claves:
            if clave:
                indice.setdefault(clave, set()).add(int(user_id))
    return indice


def resolver(texto: str, miembros: list[dict[str, Any]]) -> list[int]:
    """``user_id`` mencionados en el texto, sin repetir y en orden de aparición.

    Una mención que case con más de una persona **no** resuelve: ver la regla 2
    del módulo. Una que no case con nadie tampoco — escribir «@mañana» no
    notifica a quien tenga ese nombre por casualidad, porque no lo tiene.
    """
    indice = _indice(miembros)
    if not indice:
        return []
    salida: list[int] = []
    consumidos: set[int] = set()
    for candidato in extraer(texto):
        # Una arroba menciona como mucho a UNA persona: en cuanto un prefijo
        # resuelve, los más cortos ya no se prueban. Sin este corte,
        # «@Ana María» notificaría a Ana María **y** a Ana.
        for prefijo in _prefijos(candidato):
            posibles = indice.get(_plegar(prefijo))
            if posibles is None:
                continue
            if len(posibles) == 1:
                user_id = next(iter(posibles))
                if user_id not in consumidos:
                    consumidos.add(user_id)
                    salida.append(user_id)
            # Resuelva o quede ambiguo, esta arroba está decidida: un prefijo
            # ambiguo tampoco debe caer al siguiente, más corto y más ambiguo.
            break
    return salida


def notificar(
    *,
    mencionados: list[int],
    autor_user_id: int,
    organization_id: int,
    pursuit_id: int,
    comment_id: int,
) -> int:
    """Emite un evento ``pursuit.mentioned`` por persona mencionada (ADR-027).

    Va al outbox (``domain_events``) y no a un envío directo: el despachador de
    v2 S4.6 es quien decide el canal según las preferencias de cada persona
    (C2.7). Escribir aquí un correo saltaría esa decisión.

    **No se notifica al autor**: mencionarse a uno mismo es una forma de
    escribir, no una petición de atención.

    Best-effort: un fallo del outbox no puede tumbar la publicación del
    comentario, que es lo que la persona vino a hacer.
    """
    from db.events import append_event
    from observability.logging import get_logger

    log = get_logger(__name__)
    enviados = 0
    for user_id in mencionados:
        if user_id == autor_user_id:
            continue
        try:
            append_event(
                "pursuit.mentioned",
                pursuit_id,
                "pursuit",
                {
                    "organization_id": organization_id,
                    "comment_id": comment_id,
                    "mencionado_user_id": user_id,
                },
                actor_id=autor_user_id,
            )
            enviados += 1
        except Exception:
            log.warning(
                "mencion_evento_fallido",
                pursuit_id=pursuit_id,
                comment_id=comment_id,
                exc_info=True,
            )
    return enviados
