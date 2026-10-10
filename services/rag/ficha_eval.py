"""Eval de la ficha del pliego: emparejar lo extraído con el golden y medirlo.

Puro: sin base de datos, sin LLM y sin red. Recibe hechos ya extraídos y un
caso del golden (``services/rag/ficha_golden.py``) y dice cuáles aciertan.

La comparación es determinista a propósito
(``docs/plans/2026-10-eval-ficha-pliego.md`` §5): un segundo modelo haciendo
de juez mediría una máquina contra otra y daría un número distinto en cada
ejecución. Un hecho extraído «es» uno del golden si comparte **ancla** —cita el
mismo texto, o la misma página cuando hay un dato que comparar— y **clave** —el
dato en sí: el peso, el importe, el tipo de fórmula—.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from typing import Literal

from services.rag.fact_sheet import _MIN_FRAGMENTO_CHARS, _normalize_quote
from services.rag.ficha_golden import CAMPOS_CLAVE
from shared.tender_facts import FactItem

Comparacion = Literal["igual", "distinta", "sin_comparar"]
Resultado = Literal[
    "acierto",
    # Encontró el sitio y leyó mal el dato: una cita real bajo un valor falso.
    # Es el error más caro, porque la validación de citas lo deja pasar.
    "valor_distinto",
    "error_confirmado",
    # Caso parcial: nadie revisó este hecho. No es un error; es un desconocido.
    "sin_juzgar",
    "falso_positivo",
]

#: Tolerancia relativa al comparar números (0,5 %): absorbe redondeos del
#: pliego («60 %» frente a «60,2 puntos sobre 100»), no un dato distinto.
TOLERANCIA_NUMERICA = 0.005
#: Páginas de distancia a las que una cita sigue contando como «el mismo
#: sitio»: el modelo confunde páginas contiguas de una misma tabla.
MAX_DISTANCIA_PAGINAS = 1
#: Solape mínimo de palabras (Jaccard) para dar dos nombres por el mismo.
MIN_JACCARD_NOMBRES = 0.5

#: Familias de dos campos donde el primero decide solo y el segundo es el
#: recurso cuando el primero falta («el peso si ambos lo traen; si no, el nombre»).
_CLAVE_ALTERNATIVA = frozenset({"award_criteria", "lots", "critical_deadlines"})

_CAMPOS_DE_NOMBRE = frozenset({"name", "role"})
_NO_ALFANUMERICO = re.compile(r"[^a-z0-9]+")
_PALABRAS_VACIAS = frozenset(
    {"a", "al", "con", "de", "del", "el", "en", "la", "las", "los", "o", "para", "por", "y"}
)


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in sin_tildes if not unicodedata.combining(c))


def _palabras(texto: str) -> frozenset[str]:
    todas = frozenset(p for p in _NO_ALFANUMERICO.split(_plano(texto)) if p)
    return (todas - _PALABRAS_VACIAS) or todas


def _mismo_nombre(a: str, b: str) -> bool:
    pa, pb = _palabras(a), _palabras(b)
    if not pa or not pb:
        return _plano(a).strip() == _plano(b).strip()
    if pa <= pb or pb <= pa:
        return True
    return len(pa & pb) / len(pa | pb) >= MIN_JACCARD_NOMBRES


def _mismo_lote(a: str, b: str) -> bool:
    return _palabras(a) - {"lote"} == _palabras(b) - {"lote"}


def _comparar_campo(campo: str, a: object, b: object) -> Comparacion:
    """Compara un campo de la clave. Solo cuenta si los dos lados lo traen."""
    if a is None or b is None:
        return "sin_comparar"
    if isinstance(a, bool) or isinstance(b, bool):
        iguales = a == b
    elif isinstance(a, int | float) and isinstance(b, int | float):
        iguales = math.isclose(a, b, rel_tol=TOLERANCIA_NUMERICA, abs_tol=1e-9)
    elif isinstance(a, date) and isinstance(b, date):
        iguales = a == b
    elif campo == "lot_number":
        iguales = _mismo_lote(str(a), str(b))
    elif campo in _CAMPOS_DE_NOMBRE:
        iguales = _mismo_nombre(str(a), str(b))
    else:
        iguales = a == b
    return "igual" if iguales else "distinta"


def comparar_clave(familia: str, a: FactItem, b: FactItem) -> Comparacion:
    """Compara el dato de dos hechos de la misma familia.

    ``sin_comparar`` no es un empate: significa que no hay dato con el que
    decidir (la familia no tiene clave, o a algún lado le falta), y entonces
    solo el texto de la cita puede emparejarlos.
    """
    campos = CAMPOS_CLAVE[familia]
    if not campos:
        return "sin_comparar"
    comparaciones: list[Comparacion] = [
        _comparar_campo(campo, getattr(a, campo, None), getattr(b, campo, None)) for campo in campos
    ]
    primera = comparaciones[0]
    if len(comparaciones) == 1:
        return primera
    segunda = comparaciones[1]
    if familia in _CLAVE_ALTERNATIVA:
        return primera if primera != "sin_comparar" else segunda
    # Conjunta: el primer campo identifica el hecho (el perfil, el tipo de
    # fórmula) y tiene que coincidir; el segundo afina si ambos lo traen.
    if primera != "igual":
        return primera
    return "distinta" if segunda == "distinta" else "igual"


@dataclass(frozen=True)
class Emparejado:
    """Un hecho extraído y lo que resultó ser."""

    extraido: FactItem
    #: El hecho del golden con el que casó: el positivo en ``acierto`` y
    #: ``valor_distinto``, el negativo en ``error_confirmado``, ``None`` si no casó.
    golden: FactItem | None
    resultado: Resultado


@dataclass(frozen=True)
class EmparejamientoFamilia:
    familia: str
    #: Uno por hecho extraído, en el orden en que se extrajeron.
    pares: list[Emparejado]
    #: Positivos del golden que ningún hecho extraído acertó.
    omitidos: list[FactItem]


@dataclass(frozen=True)
class _Vinculo:
    """Lo que une a un hecho extraído con uno del golden."""

    solape: int
    misma_pagina: bool
    clave: Comparacion

    @property
    def ancla_cita(self) -> bool:
        return self.solape >= _MIN_FRAGMENTO_CHARS

    @property
    def casa(self) -> bool:
        # La página sola nunca basta sin un dato que coincida: dos requisitos
        # distintos de la misma página no son el mismo hecho.
        return (self.ancla_cita and self.clave != "distinta") or (
            self.misma_pagina and self.clave == "igual"
        )

    @property
    def mismo_sitio_otro_dato(self) -> bool:
        return self.ancla_cita and self.clave == "distinta"


def _vinculo(familia: str, extraido: FactItem, golden: FactItem) -> _Vinculo:
    solape = 0
    misma_pagina = False
    for cita_e in extraido.evidence:
        texto_e = _normalize_quote(cita_e.quote)
        for cita_g in golden.evidence:
            if cita_e.documento_id != cita_g.documento_id:
                continue
            if abs(cita_e.page_number - cita_g.page_number) <= MAX_DISTANCIA_PAGINAS:
                misma_pagina = True
            texto_g = _normalize_quote(cita_g.quote)
            comun = SequenceMatcher(None, texto_e, texto_g, autojunk=False).find_longest_match(
                0, len(texto_e), 0, len(texto_g)
            )
            solape = max(solape, comun.size)
    return _Vinculo(
        solape=solape, misma_pagina=misma_pagina, clave=comparar_clave(familia, extraido, golden)
    )


def _asignar(
    candidatos: list[tuple[int, int, int]],
    libres_extraidos: set[int],
    libres_golden: set[int],
) -> list[tuple[int, int]]:
    """Asignación uno a uno: mayor solape primero; a igualdad, orden de aparición."""
    asignados: list[tuple[int, int]] = []
    for _solape, i, j in sorted(candidatos, key=lambda c: (-c[0], c[1], c[2])):
        if i in libres_extraidos and j in libres_golden:
            libres_extraidos.discard(i)
            libres_golden.discard(j)
            asignados.append((i, j))
    return asignados


def emparejar(
    familia: str,
    extraidos: Sequence[FactItem],
    positivos: Sequence[FactItem],
    negativos: Sequence[FactItem],
    *,
    completo: bool,
) -> EmparejamientoFamilia:
    """Decide qué es cada hecho extraído frente al golden de su familia.

    Tres pasadas uno a uno, cada una sobre lo que dejó libre la anterior:
    aciertos, errores ya conocidos y, por último, «mismo sitio, otro dato».
    El orden importa: repetir el valor que alguien ya corrigió es un error
    confirmado antes que un valor distinto sin más.
    """
    con_positivos = {
        (i, j): _vinculo(familia, e, g)
        for i, e in enumerate(extraidos)
        for j, g in enumerate(positivos)
    }
    con_negativos = {
        (i, j): _vinculo(familia, e, g)
        for i, e in enumerate(extraidos)
        for j, g in enumerate(negativos)
    }
    libres = set(range(len(extraidos)))
    positivos_libres = set(range(len(positivos)))
    negativos_libres = set(range(len(negativos)))
    resultado: dict[int, Emparejado] = {}

    aciertos = _asignar(
        [(v.solape, i, j) for (i, j), v in con_positivos.items() if v.casa],
        libres,
        positivos_libres,
    )
    for i, j in aciertos:
        resultado[i] = Emparejado(extraidos[i], positivos[j], "acierto")
    acertados = {j for _i, j in aciertos}

    for i, j in _asignar(
        [(v.solape, i, j) for (i, j), v in con_negativos.items() if v.casa],
        libres,
        negativos_libres,
    ):
        resultado[i] = Emparejado(extraidos[i], negativos[j], "error_confirmado")

    for i, j in _asignar(
        [(v.solape, i, j) for (i, j), v in con_positivos.items() if v.mismo_sitio_otro_dato],
        libres,
        positivos_libres,
    ):
        resultado[i] = Emparejado(extraidos[i], positivos[j], "valor_distinto")

    sin_casar: Resultado = "falso_positivo" if completo else "sin_juzgar"
    for i in libres:
        resultado[i] = Emparejado(extraidos[i], None, sin_casar)

    return EmparejamientoFamilia(
        familia=familia,
        pares=[resultado[i] for i in range(len(extraidos))],
        omitidos=[g for j, g in enumerate(positivos) if j not in acertados],
    )
