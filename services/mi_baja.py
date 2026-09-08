"""«Mi baja frente al mercado»: orquestación (C6.5).

El criterio de agrupación está en `services/pursuit_bajas.py`, el de la
referencia de mercado en `services/competitive/bajas.py` y el SQL de las ofertas
propias en `db/repositories/pursuits.py`. Aquí solo se juntan.
"""

from __future__ import annotations

from typing import Any

from db.repositories.pursuits import PursuitRepository
from observability.logging import get_logger
from services.organizations import resolve_organization
from services.pursuit_bajas import agrupar

log = get_logger(__name__)

_pursuits = PursuitRepository()

#: Tope de segmentos que se cruzan con el mercado en una petición.
#:
#: Cada uno es una consulta agregada sobre `adjudicaciones`. Sin tope, una
#: organización con doscientos expedientes dispararía doscientas consultas por
#: carga del Embudo. Los segmentos vienen ordenados por número de ofertas
#: propias, así que el corte se lleva los que menos población tienen — que son
#: justo los que menos se pueden interpretar.
MAX_SEGMENTOS = 20


def mi_baja(user_id: int, *, organization_id: int | None = None) -> dict[str, Any]:
    """Mi baja media por CPV4 y por órgano, junto a la del mercado.

    `base` viaja en la respuesta y siempre vale `sin_iva`: las ofertas propias
    se cruzan solo con expedientes cuyo `importe_tipo` es `sin_iva` (C1.1), así
    que aquí no hay población mixta que declarar. Hoy eso devuelve poco y crece
    con la re-ingesta; devolver más filas a costa de mezclar bases haría que el
    número mintiera justo donde se usa para fijar un precio.
    """
    from services.competitive.bajas import baja_de_referencia

    resolved_id, _role = resolve_organization(user_id, organization_id)
    ofertas = _pursuits.ofertas_presentadas(resolved_id)

    # Primero se agrupa sin mercado para saber **qué** segmentos existen, y solo
    # después se piden sus referencias: pedirlas antes obligaría a adivinarlas.
    preliminar = agrupar(ofertas, {})
    referencias: dict[tuple[str, str], dict[str, Any]] = {}
    for segmento in preliminar[:MAX_SEGMENTOS]:
        try:
            referencias[(segmento.segmento, segmento.clave)] = baja_de_referencia(
                organo=(segmento.clave if segmento.segmento == "organo" else None),
                cpv_prefix=(segmento.clave if segmento.segmento == "cpv4" else None),
                solo_base_declarada=True,
            )
        except Exception:
            # Un segmento sin referencia sale igual, con `baja_mercado_pct` a
            # null: perder mi propia cifra porque la del mercado falló sería
            # esconder el dato que sí tengo.
            log.warning(
                "mi_baja_referencia_failed",
                segmento=segmento.segmento,
                clave=segmento.clave,
                exc_info=True,
            )

    segmentos = agrupar(ofertas, referencias)[:MAX_SEGMENTOS]
    return {
        "organization_id": resolved_id,
        "base": "sin_iva",
        "ofertas_consideradas": len(ofertas),
        "segmentos": [s.as_dict() for s in segmentos],
    }
