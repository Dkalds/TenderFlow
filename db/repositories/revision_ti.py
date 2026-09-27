"""Candidatos de la revisión humana por desacuerdo (plan de tres niveles, F1).

Una etiqueta humana informa donde las fuentes no coinciden. Las reglas son
`licitaciones.tecnologia` y el CPV; el LLM, el marcador de es_ti y las
familias de `llm_metadata`; el modelo, `ml_proba`. Lo que ya revisó una
persona con `revision_ti` no vuelve.
"""

from __future__ import annotations

import json
from typing import Any  # filas psycopg heterogéneas, como el resto de db/repositories

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from db.repositories.feedback import FUENTE_REVISION_TI
from db.repositories.tecnologia_pliego import ES_TI_SENTINEL, NO_ES_TI_SENTINEL, SENTINELS

MOTIVOS: tuple[str, ...] = (
    "llm_no_reglas_si",
    "llm_si_reglas_no",
    "llm_no_cpv_si",
    "familias_distintas",
    "modelo_dudoso",
)

#: Algún código CPV 48/72 en el campo, con cualquier separador (PSCP une con `||`).
_CPV_TI_SQL = "coalesce(l.cpv, '') ~ '(^|[^0-9])(48|72)[0-9]{6}'"

_SQL = f"""
WITH es_ti AS (
    SELECT DISTINCT ON (licitacion_id) licitacion_id, tecnologia AS marcador, evidence_json
    FROM licitacion_tecnologia_pliego
    WHERE method = 'llm_metadata' AND tecnologia IN (%(es_ti)s, %(no_es_ti)s)
    ORDER BY licitacion_id, computed_at DESC
), familias AS (
    SELECT licitacion_id, array_agg(tecnologia ORDER BY tecnologia) AS llm_familias
    FROM licitacion_tecnologia_pliego
    WHERE method = 'llm_metadata' AND tecnologia <> ALL(%(sentinels)s) AND score >= %(min_score)s
    GROUP BY licitacion_id
), candidatos AS (
    SELECT l.id_externo, l.titulo, l.descripcion, l.cpv, l.importe, l.organo_contratacion,
           l.ccaa, l.fecha_publicacion, l.url, l.tecnologia, l.ml_tecnologias,
           l.ml_proba_max, l.ml_tech_principal, l.ml_proba,
           e.marcador, e.evidence_json AS llm_evidencia, f.llm_familias,
           CASE
             WHEN e.marcador = %(no_es_ti)s AND coalesce(l.tecnologia, '') <> ''
               THEN 'llm_no_reglas_si'
             WHEN e.marcador = %(es_ti)s AND coalesce(l.tecnologia, '') = '' AND NOT ({_CPV_TI_SQL})
               THEN 'llm_si_reglas_no'
             WHEN e.marcador = %(no_es_ti)s AND {_CPV_TI_SQL}
               THEN 'llm_no_cpv_si'
             WHEN f.llm_familias IS NOT NULL AND coalesce(l.tecnologia, '') <> ''
                  AND NOT (f.llm_familias && string_to_array(replace(l.tecnologia, ' ', ''), ','))
               THEN 'familias_distintas'
             WHEN l.ml_proba BETWEEN 0.3 AND 0.7
               THEN 'modelo_dudoso'
           END AS motivo
    FROM licitaciones l
    LEFT JOIN es_ti e ON e.licitacion_id = l.id_externo
    LEFT JOIN familias f ON f.licitacion_id = l.id_externo
    WHERE NOT EXISTS (
        SELECT 1 FROM ml_feedback r
        WHERE r.expediente = l.id_externo AND r.source = %(revision)s
    )
)
SELECT * FROM candidatos
WHERE motivo IS NOT NULL
ORDER BY array_position(%(motivos)s::text[], motivo), fecha_publicacion DESC NULLS LAST
LIMIT %(limit)s
"""  # Interpola solo el predicado constante del módulo.


def candidatos_desacuerdo(limit: int) -> list[dict[str, Any]]:
    """Hasta ``limit`` licitaciones sin revisar, primero las de desacuerdo más grave."""
    from config import settings

    with connect_read() as c:
        filas = rows_to_dicts(
            c.execute(
                _SQL,
                {
                    "sentinels": list(SENTINELS),
                    "min_score": settings.PLIEGO_TECH_MIN_SCORE,
                    "es_ti": ES_TI_SENTINEL,
                    "no_es_ti": NO_ES_TI_SENTINEL,
                    "revision": FUENTE_REVISION_TI,
                    "motivos": list(MOTIVOS),
                    "limit": max(1, min(int(limit), 200)),
                },
            )
        )
    for fila in filas:
        marcador = fila.pop("marcador", None)
        if marcador == ES_TI_SENTINEL:
            fila["llm_es_ti"] = True
        elif marcador == NO_ES_TI_SENTINEL:
            fila["llm_es_ti"] = False
        else:
            fila["llm_es_ti"] = None
        fila["llm_confianza_es_ti"] = _confianza(fila.pop("llm_evidencia", None))
        fila["llm_familias"] = list(fila.get("llm_familias") or [])
    return filas


def _confianza(evidence_json: str | None) -> float | None:
    """La confianza del marcador de es_ti, leída de su ``evidence_json``.

    El job la guarda como ``[{"es_ti": ..., "confianza": ..., "otros_fabricantes":
    [...]}]``. Cualquier otra forma (sin evidencia, JSON roto, confianza ausente
    o no numérica) es «no se sabe» y no un error: la cola se sirve igual.
    """
    if not evidence_json:
        return None
    try:
        evidencia = json.loads(evidence_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(evidencia, list) or not evidencia:
        return None
    primera = evidencia[0]
    if not isinstance(primera, dict):
        return None
    valor = primera.get("confianza")
    # `bool` es subclase de `int`: un `true` en la confianza no es un número.
    if isinstance(valor, bool) or not isinstance(valor, int | float):
        return None
    return float(valor)
