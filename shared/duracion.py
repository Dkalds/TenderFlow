"""Vocabulario de unidades de duración de CODICE.

``licitaciones.duracion_unidad`` guarda el ``@unitCode`` tal como lo publica la
Plataforma (``scraper/codice_parser.py`` lo copia sin traducir): son códigos
UN/CEFACT —``ANN``, ``MON``, ``DAY``, ``WEK``, ``HUR``—, nunca palabras en
castellano. Un conversor que espere «meses» o «años» devuelve cero para
**todas** las filas reales, y lo hace en silencio.

Vive en ``shared/`` porque lo necesitan capas que no pueden importarse entre
sí: ``services/analytics/forecast.py`` (que arrastra pandas) y
``services/cartera.py`` (que no debería arrastrarlo). ``db/sql_fragments.py``
expresa el mismo mapeo en SQL para ``FECHA_FIN_SQL``; los dos hablan de lo
mismo y por eso están enlazados desde aquí.

``services/ml/features.py`` mantiene su propia tabla a propósito: usa 30 días
por mes en vez de 30,4375, y alinearla cambiaría el valor de una feature ya
serializada en los artefactos del modelo.
"""

from __future__ import annotations

from typing import Final

#: Días medios por mes: 365,25 / 12. El año juliano y no 360, para que una
#: duración en días y la misma en meses no se separen a lo largo del contrato.
DIAS_POR_MES: Final = 30.4375

#: Factor por el que multiplicar ``duracion_valor`` para obtener meses.
UNIDAD_A_MESES: Final[dict[str, float]] = {
    "ANN": 12.0,
    "MON": 1.0,
    "DAY": 1.0 / DIAS_POR_MES,
    "WEK": 7.0 / DIAS_POR_MES,
    "HUR": 1.0 / 730.0,
}

#: Sinónimos en castellano que aparecen en filas cargadas a mano o por
#: conectores que no son CODICE. Se aceptan por prefijo y en minúsculas.
#: No sustituyen al código: lo complementan.
_PREFIJOS_ES: Final[tuple[tuple[tuple[str, ...], str], ...]] = (
    (("mes",), "MON"),
    (("ano", "año", "year"), "ANN"),
    (("sem",), "WEK"),
    (("dia", "día", "day"), "DAY"),
    (("hor",), "HUR"),
)


def codigo_de_unidad(unidad: str | None) -> str | None:
    """El código CODICE de una unidad escrita como sea, o ``None``.

    ``None`` significa «no se sabe», y quien llama debe declararlo en vez de
    adivinar: una duración mal convertida se propaga a la fecha de fin, y de
    ahí a la ventana de relicitación, sin que nadie pueda rastrearla.
    """
    if not unidad:
        return None
    limpio = str(unidad).strip()
    if not limpio:
        return None
    if (mayus := limpio.upper()) in UNIDAD_A_MESES:
        return mayus
    minus = limpio.lower()
    for prefijos, codigo in _PREFIJOS_ES:
        if minus.startswith(prefijos):
            return codigo
    return None


def meses_de(valor: object, unidad: str | None) -> float | None:
    """Duración en meses, o ``None`` si no se puede convertir sin adivinar.

    ``valor`` se acepta como ``object`` porque llega de una fila cruda: la
    columna es numérica pero los conectores han escrito cadenas, y forzar al
    llamante a convertir antes es pedirle que repita este mismo ``try``.
    """
    if valor is None or isinstance(valor, bool):
        return None
    try:
        cantidad = float(valor)  # type: ignore[arg-type]  # el try es la comprobación
    except (TypeError, ValueError):
        return None
    if cantidad <= 0:
        return None
    codigo = codigo_de_unidad(unidad)
    if codigo is None:
        return None
    return cantidad * UNIDAD_A_MESES[codigo]
