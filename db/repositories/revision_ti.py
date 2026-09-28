"""Candidatos de la revisión humana por desacuerdo (plan de tres niveles, F1).

Una etiqueta humana informa donde las fuentes no coinciden. Las reglas son
`licitaciones.tecnologia` y el CPV; el LLM, el marcador de es_ti y las
familias de `llm_metadata`; el modelo, `ml_proba`. Lo que ya revisó una
persona con `revision_ti` no vuelve.

Las filas humanas anteriores al plan (`source='human'`, su `relevante` era
«es SAP») vuelven a la cola con el motivo `legado` hasta que alguien las
revise con `revision_ti` (spec §3.3), tengan o no señal del LLM.

Dos consultas, porque una sola pasada recorría `licitaciones` entera (5,98 s
medidos en producción el 2026-09-27) y esta es la vista por defecto:

- **Fase A**, los cuatro motivos del LLM y `legado`: parte de las filas
  `llm_metadata` de `licitacion_tecnologia_pliego` (~9k) y de las filas
  `human` de `ml_feedback` (59), y llega a `licitaciones` por su clave
  primaria.
- **Fase B**, `modelo_dudoso`: solo si A no llena el cupo, sin repetir lo que A
  ya trajo y solo lo publicado en los últimos `VENTANA_DUDOSO_DIAS` días, que
  baja por `idx_fecha_pub`.

La propuesta del LLM avisa con `llm_sin_evidencia` si sus filas vigentes
traen `__sin_evidencia__`: afirmó familias sin una cita verificable, y esa
respuesta no entrena. El motivo no cambia.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any  # filas psycopg heterogéneas, como el resto de db/repositories

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from db.repositories.feedback import FUENTE_LEGADO, FUENTE_REVISION_TI
from db.repositories.tecnologia_pliego import (
    ES_TI_SENTINEL,
    NO_ES_TI_SENTINEL,
    SENTINELS,
    SIN_EVIDENCIA_SENTINEL,
)

#: En orden de gravedad: el de una licitación que casa con varios es el primero.
MOTIVOS: tuple[str, ...] = (
    "llm_no_reglas_si",
    "llm_si_reglas_no",
    "llm_no_cpv_si",
    "familias_distintas",
    "legado",
    "modelo_dudoso",
)

#: Heap de 872 MB: recorrer `licitaciones` entera cuesta ~6 s; la fase B se queda en lo reciente.
VENTANA_DUDOSO_DIAS = 90

#: Algún código CPV 48/72 en el campo, con cualquier separador (PSCP une con `||`).
_CPV_TI_SQL = "coalesce(l.cpv, '') ~ '(^|[^0-9])(48|72)[0-9]{6}'"

#: Fase A: los cuatro motivos del LLM y `legado`, desde las licitaciones con
#: señal del LLM o con una fila humana heredada.
_SQL_DESACUERDO_LLM = f"""
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
), sin_evidencia AS (
    SELECT DISTINCT licitacion_id
    FROM licitacion_tecnologia_pliego
    WHERE method = 'llm_metadata' AND tecnologia = %(sin_evidencia)s
), senal AS (
    SELECT coalesce(e.licitacion_id, f.licitacion_id) AS licitacion_id,
           e.marcador, e.evidence_json, f.llm_familias
    FROM es_ti e
    FULL JOIN familias f ON f.licitacion_id = e.licitacion_id
), legado AS (
    -- Las ~59 filas `human` de antes del plan: su `relevante` era «es SAP».
    SELECT DISTINCT expediente AS licitacion_id
    FROM ml_feedback
    WHERE source = %(legado)s
), universo AS (
    SELECT coalesce(s.licitacion_id, g.licitacion_id) AS licitacion_id,
           s.marcador, s.evidence_json, s.llm_familias,
           g.licitacion_id IS NOT NULL AS es_legado
    FROM senal s
    FULL JOIN legado g ON g.licitacion_id = s.licitacion_id
), candidatos AS (
    SELECT l.id_externo, l.titulo, l.descripcion, l.cpv, l.importe, l.organo_contratacion,
           l.ccaa, l.fecha_publicacion, l.url, l.tecnologia, l.ml_tecnologias,
           l.ml_proba_max, l.ml_tech_principal, l.ml_proba,
           u.marcador, u.evidence_json AS llm_evidencia, u.llm_familias,
           se.licitacion_id IS NOT NULL AS llm_sin_evidencia,
           CASE
             WHEN u.marcador = %(no_es_ti)s AND coalesce(l.tecnologia, '') <> ''
               THEN 'llm_no_reglas_si'
             WHEN u.marcador = %(es_ti)s AND coalesce(l.tecnologia, '') = '' AND NOT ({_CPV_TI_SQL})
               THEN 'llm_si_reglas_no'
             WHEN u.marcador = %(no_es_ti)s AND {_CPV_TI_SQL}
               THEN 'llm_no_cpv_si'
             WHEN u.llm_familias IS NOT NULL AND coalesce(l.tecnologia, '') <> ''
                  AND NOT (u.llm_familias && string_to_array(replace(l.tecnologia, ' ', ''), ','))
               THEN 'familias_distintas'
             WHEN u.es_legado
               THEN 'legado'
           END AS motivo
    FROM universo u
    -- Una sonda por clave primaria por licitación con señal o heredada. El
    -- OFFSET 0 impide que el planificador aplane la subconsulta y cambie las
    -- sondas por un recorrido entero de licitaciones, cuyo heap ocupa 872 MB.
    CROSS JOIN LATERAL (
        SELECT * FROM licitaciones x WHERE x.id_externo = u.licitacion_id OFFSET 0
    ) l
    LEFT JOIN sin_evidencia se ON se.licitacion_id = u.licitacion_id
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

#: Fase B: `modelo_dudoso` en lo reciente, con la propuesta del LLM si la hay.
_SQL_MODELO_DUDOSO = """
WITH dudosas AS (
    SELECT l.id_externo, l.titulo, l.descripcion, l.cpv, l.importe, l.organo_contratacion,
           l.ccaa, l.fecha_publicacion, l.url, l.tecnologia, l.ml_tecnologias,
           l.ml_proba_max, l.ml_tech_principal, l.ml_proba
    FROM licitaciones l
    WHERE l.fecha_publicacion >= %(desde)s
      AND l.ml_proba BETWEEN 0.3 AND 0.7
      AND l.id_externo <> ALL(%(excluir)s::text[])
      AND NOT EXISTS (
          SELECT 1 FROM ml_feedback r
          WHERE r.expediente = l.id_externo AND r.source = %(revision)s
      )
    ORDER BY l.fecha_publicacion DESC
    LIMIT %(faltan)s
)
SELECT d.*, e.marcador, e.evidence_json AS llm_evidencia, f.llm_familias,
       EXISTS (
           SELECT 1 FROM licitacion_tecnologia_pliego p
           WHERE p.licitacion_id = d.id_externo AND p.method = 'llm_metadata'
             AND p.tecnologia = %(sin_evidencia)s
       ) AS llm_sin_evidencia,
       'modelo_dudoso' AS motivo
FROM dudosas d
LEFT JOIN LATERAL (
    SELECT p.tecnologia AS marcador, p.evidence_json
    FROM licitacion_tecnologia_pliego p
    WHERE p.licitacion_id = d.id_externo AND p.method = 'llm_metadata'
      AND p.tecnologia IN (%(es_ti)s, %(no_es_ti)s)
    ORDER BY p.computed_at DESC
    LIMIT 1
) e ON true
LEFT JOIN LATERAL (
    SELECT array_agg(p.tecnologia ORDER BY p.tecnologia) AS llm_familias
    FROM licitacion_tecnologia_pliego p
    WHERE p.licitacion_id = d.id_externo AND p.method = 'llm_metadata'
      AND p.tecnologia <> ALL(%(sentinels)s) AND p.score >= %(min_score)s
) f ON true
ORDER BY d.fecha_publicacion DESC
"""


def candidatos_desacuerdo(limit: int) -> list[dict[str, Any]]:
    """Hasta ``limit`` licitaciones sin revisar, primero las de desacuerdo más grave."""
    from config import settings

    tope = max(1, min(int(limit), 200))
    comunes: dict[str, Any] = {
        "sentinels": list(SENTINELS),
        "min_score": settings.PLIEGO_TECH_MIN_SCORE,
        "es_ti": ES_TI_SENTINEL,
        "no_es_ti": NO_ES_TI_SENTINEL,
        "sin_evidencia": SIN_EVIDENCIA_SENTINEL,
        "revision": FUENTE_REVISION_TI,
    }
    with connect_read() as c:
        filas = rows_to_dicts(
            c.execute(
                _SQL_DESACUERDO_LLM,
                {**comunes, "legado": FUENTE_LEGADO, "motivos": list(MOTIVOS), "limit": tope},
            )
        )
        faltan = tope - len(filas)
        if faltan > 0:
            hace = datetime.now(UTC) - timedelta(days=VENTANA_DUDOSO_DIAS)
            filas += rows_to_dicts(
                c.execute(
                    _SQL_MODELO_DUDOSO,
                    {
                        **comunes,
                        "desde": hace.date().isoformat(),
                        "excluir": [str(f["id_externo"]) for f in filas],
                        "faltan": faltan,
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
        fila["llm_sin_evidencia"] = bool(fila.get("llm_sin_evidencia"))
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
