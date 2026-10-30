"""Lectura para medir las etiquetas de tecnología por licitación.

Solo lectura. La consume ``scripts/medir_etiquetas_tecnologia.py``, que cuenta
cuántas etiquetas lleva cada licitación y de qué fuente sale cada una (título,
clasificador, pliego) y saca una muestra para revisarla a mano. El SQL vive
aquí por ADR-022; el recuento, en el script.
"""

from __future__ import annotations

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from db.repositories.tecnologia_pliego import SENTINELS
from db.sql_fragments import exclude_duplicados_sql


def filas_etiquetas_tecnologia() -> list[dict[str, object]]:
    """Licitaciones con alguna etiqueta, con lo que dice cada fuente.

    Una fila por licitación con ``tecnologia`` o ``ml_tecnologias`` no vacía
    (sin duplicados confirmados). ``ml_scores`` y ``pliego`` traen **todas**
    las filas de ``licitacion_tecnologia_score`` y de
    ``licitacion_tecnologia_pliego`` (sin sentinels), también las que no pasan
    su umbral: contarlas es parte de lo que se mide.
    """
    sql = (
        "SELECT l.id_externo, l.titulo, l.cpv, l.tecnologia, l.ml_tecnologias, "
        "  COALESCE(("
        "    SELECT json_agg(json_build_object("
        "      'tecnologia', s.tecnologia, 'probabilidad', s.probabilidad, "
        "      'threshold_aplicado', s.threshold_aplicado))"
        "    FROM licitacion_tecnologia_score s WHERE s.licitacion_id = l.id_externo"
        "  ), '[]'::json) AS ml_scores, "
        "  COALESCE(("
        "    SELECT json_agg(json_build_object("
        "      'tecnologia', p.tecnologia, 'method', p.method, 'score', p.score, "
        "      'matched_terms', p.matched_terms))"
        "    FROM licitacion_tecnologia_pliego p "
        "    WHERE p.licitacion_id = l.id_externo AND p.tecnologia <> ALL(%s)"
        "  ), '[]'::json) AS pliego "
        "FROM licitaciones l "
        "WHERE (COALESCE(l.tecnologia, '') <> '' OR COALESCE(l.ml_tecnologias, '') <> '') "
        f"AND {exclude_duplicados_sql('l.id_externo')} "
        "ORDER BY l.id_externo"
    )
    with connect_read() as c:
        cur = c.execute(sql, (list(SENTINELS),))
        return rows_to_dicts(cur)
