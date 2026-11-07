"""Settings de la analítica de producto: pesos del scoring y resolución de competidores.

Módulo hermano de ``config/settings.py`` (P3 «Los dos módulos-dios»): ``Settings``
hereda de esta clase, así que los nombres de las variables de entorno y el
acceso (``settings.SCORING_WEIGHTS``) son los de siempre.

Sin ``model_config`` propio, por lo mismo que ``config/settings_resumen.py``.
"""

from __future__ import annotations

from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings

from config.scoring_weights import validate_scoring_weights


class AnaliticaSettings(BaseSettings):
    """Scoring de oportunidades y analítica de competidores."""

    # ── Scoring de oportunidades ─────────────────────────────────────────
    # Pesos por dimensión (enteros, deben sumar 100). Validados al arrancar por
    # config/scoring_weights.py, el mismo validador que aplica el perfil de
    # usuario.
    #
    # `senal_tecnica` (2026-08) mide cuán confirmada está la tecnología en el
    # pliego real y en el clasificador. Los 10 puntos salen de `importe` y
    # `competencia`, que son las dos señales más ruidosas del reparto: una
    # normaliza contra los percentiles de ~1,6 k importes y la otra contra
    # medias por CPV-4 con muestras de tres expedientes. `margen` se deja
    # intacta porque es la única que viene de una predicción por licitación.
    #
    # `organo_anula_frecuente` (F1.4) **no es una dimensión**: no cuenta en la
    # suma de 100. Son los puntos que se restan cuando el órgano anula o deja
    # desiertos al menos el 25 % de sus expedientes resueltos (mínimo diez, 24
    # meses). 0 la apaga; el perfil de usuario puede sobreescribirla.
    #
    # Overridable via ENV como JSON:
    #   SCORING_WEIGHTS='{"importe":20,"plazo":15,"competencia":20,"margen":20,"afinidad":15,"senal_tecnica":10,"organo_anula_frecuente":8}'
    SCORING_WEIGHTS: dict[str, int] = {
        "importe": 20,
        "plazo": 15,
        "competencia": 20,
        "margen": 20,
        "afinidad": 15,
        "senal_tecnica": 10,
        "organo_anula_frecuente": 8,
    }
    # Keywords de afinidad configurables por el usuario (casefold-substring sobre título).
    # Si está vacía, la dimensión afinidad se omite del desglose y su peso se
    # redistribuye proporcionalmente entre las demás dimensiones.
    # Overridable via ENV como JSON:
    #   SCORING_AFINIDAD_KEYWORDS='["consultoría","mantenimiento"]'
    SCORING_AFINIDAD_KEYWORDS: list[str] = []

    # ── Analítica de competidores ─────────────────────────────────────────
    # Resolución de identidad de empresa (quién es el mismo competidor) en
    # Postgres (`db/repositories/competitor_identity.py`: unaccent + CTE
    # recursiva) en vez del union-find de pandas. APAGADO hasta que la paridad
    # de `tests/test_analytics_competitors_identity_sql.py` pase en CI contra
    # Postgres real y `identity_graph_stats` se haya medido en producción: el
    # cierre de la CTE es cuadrático en el tamaño del componente.
    COMPETITORS_IDENTITY_SQL: bool = False

    @model_validator(mode="after")
    def _validate_scoring_weights(self) -> Self:
        # Misma regla que aplica el perfil de usuario en `PUT /me/profile`: los
        # dos caminos por los que entran pesos comparten validador para que no
        # puedan divergir (config/scoring_weights.py).
        validate_scoring_weights(self.SCORING_WEIGHTS, source="SCORING_WEIGHTS")
        return self
