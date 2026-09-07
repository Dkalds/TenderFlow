"""Menciones `@nombre` en los comentarios de una oportunidad (C6.2).

El comentario guarda su texto; una mención necesita saber **a quién** se refiere
para poder notificar y para que la UI la enlace.

**No se guarda el nombre resuelto dentro del texto.** Congelarlo significa que
cuando la persona cambia su `display_name`, el comentario queda mencionando a
alguien que ya no se llama así y sin forma de saber a quién apuntaba. Se guardan
los `user_id` en `pursuit_comment_mentions` (v123) y el texto conserva lo que
escribió el autor.

Aquí vive el criterio de resolución. El SQL está en
`db/repositories/pursuit_comments.py`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

#: `@` seguido de letras, dígitos, punto, guion o guion bajo, o de un nombre
#: entre llaves para los que llevan espacio: `@{Ana María Ruiz}`.
#:
#: Sin la forma con llaves, «@Ana María» resolvería solo «Ana» y mencionaría a
#: la persona equivocada cuando hay dos Anas — que es peor que no mencionar a
#: nadie, porque parece que funcionó.
_MENCION = re.compile(r"@(?:\{([^}\n]{1,80})\}|([A-Za-zÀ-ÿ0-9._-]{2,60}))")


def _plegar(texto: str) -> str:
    """Minúsculas sin tildes ni signos: la forma en que se comparan los nombres.

    «Ana Ruiz», «ana ruiz» y «Ana Rúiz» son la misma persona escribiendo con
    prisa. Lo que **no** se pliega son los espacios internos: «AnaRuiz» no es
    «Ana Ruiz», y tratarlas como iguales abriría la puerta a resolver una
    mención por un parecido que el autor no escribió.
    """
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return " ".join(sin_tildes.casefold().split())


@dataclass(frozen=True)
class Resolucion:
    """Qué se pudo resolver de las menciones de un comentario."""

    #: `user_id` de los mencionados, sin repetir y en orden de aparición.
    user_ids: list[int]
    #: Textos que parecían mención y no resolvieron a nadie.
    sin_resolver: list[str]
    #: Textos que resolvieron a más de una persona.
    ambiguos: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_ids": self.user_ids,
            "sin_resolver": self.sin_resolver,
            "ambiguos": self.ambiguos,
        }


def extraer(texto: str) -> list[str]:
    """Textos mencionados, en orden y sin repetir."""
    vistos: list[str] = []
    for entre_llaves, suelto in _MENCION.findall(texto or ""):
        crudo = (entre_llaves or suelto).strip()
        if crudo and crudo not in vistos:
            vistos.append(crudo)
    return vistos


def resolver(texto: str, miembros: list[dict[str, Any]]) -> Resolucion:
    """Resuelve las menciones contra los **miembros activos** de la organización.

    Args:
        texto: Cuerpo del comentario.
        miembros: `[{id, display_name}]` de la organización del comentario.
            Que la lista venga acotada es lo que garantiza que no se pueda
            mencionar —ni notificar— a alguien de fuera: el filtro no es una
            comprobación posterior que se pueda olvidar, es la entrada.

    Una mención ambigua **no se resuelve a nadie**. Elegir la primera
    coincidencia notificaría a la persona equivocada, y quien escribió creería
    que avisó a quien quería: un falso positivo aquí es peor que un fallo
    visible.
    """
    por_nombre: dict[str, list[int]] = {}
    for miembro in miembros:
        nombre = str(miembro.get("display_name") or "").strip()
        if not nombre:
            continue
        por_nombre.setdefault(_plegar(nombre), []).append(int(miembro["id"]))
        # Alias por el primer token («@ana» para «Ana Ruiz»), que es como se
        # escribe de verdad. Si dos miembros lo comparten, cae en ambiguo.
        primero = _plegar(nombre.split()[0])
        if primero and primero != _plegar(nombre):
            por_nombre.setdefault(primero, []).append(int(miembro["id"]))

    user_ids: list[int] = []
    sin_resolver: list[str] = []
    ambiguos: list[str] = []
    for crudo in extraer(texto):
        candidatos = por_nombre.get(_plegar(crudo), [])
        unicos = sorted(set(candidatos))
        if not unicos:
            sin_resolver.append(crudo)
        elif len(unicos) > 1:
            ambiguos.append(crudo)
        elif unicos[0] not in user_ids:
            user_ids.append(unicos[0])
    return Resolucion(user_ids=user_ids, sin_resolver=sin_resolver, ambiguos=ambiguos)
