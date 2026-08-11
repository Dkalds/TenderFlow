"""Lecturas del dataset de los modelos predictivos de baja.

Todo el SQL del dataset de ``services/ml/`` vive aquí (ADR-022: el SQL solo
existe en ``db/``). Antes estaba inline en ``services/ml/features.py`` y
``services/ml/calibration.py``, ambos en la whitelist congelada del ratchet
TID251 -- moverlo la encoge, que es la única dirección permitida.

**La unidad es el expediente, no el lote.** Una licitación multi-lote tiene
varias filas en ``adjudicaciones``; aquí se agregan a una sola observación
antes de dividir. El motivo es que las tres superficies que consumen esto
hablaban de granularidades distintas:

- entrenamiento: una fila por adjudicación (baja del lote contra su lote),
- ``predicciones_baja``: PK ``licitacion_id``, una predicción por expediente,
- ``calibration.py``: baja realizada agregada por expediente.

Con el agregado, las tres miden lo mismo y la cobertura empírica del intervalo
pasa a ser comparable con la nominal. La granularidad por lote es un modelo
distinto (requiere PK nueva en ``predicciones_baja``) y queda fuera.

Denominador del target -- la regla está en :func:`_sql_agregado`:

- si **todas** las adjudicaciones del expediente tienen ``lote_id`` resuelto
  (v65_lotes), el presupuesto es la suma de los lotes **distintos**
  adjudicados: un lote adjudicado a dos empresas no debe contar su
  presupuesto dos veces;
- si alguna no lo tiene (datos anteriores a v65), cae a ``l.importe``, que es
  el denominador correcto de la comparación agregada.

Un expediente parcialmente adjudicado da así la baja de la porción adjudicada,
no una baja inflada contra el presupuesto total.
"""

from __future__ import annotations

from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts

# Exclusión de duplicados cross-fuente. Duplicado de
# ``services.dedupe.exclude_duplicados_sql`` porque ``db/`` no debe depender de
# ``services/`` (capa superior, ADR-024) -- mismo motivo por el que
# ``db/repositories/pricing.py`` duplica ``EFFECTIVE_BUDGET_SQL``. Solo excluye
# duplicados ``confirmed``; los ``pending`` cuentan hasta que un humano los
# confirme.
_NO_DUPLICADOS = (
    "a.licitacion_id NOT IN "
    "(SELECT licitacion_id FROM licitaciones_duplicados WHERE status = 'confirmed')"
)

_UNIVERSO = "COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed'"

# Tolerancia de validez del par agregado: descarta expedientes donde lo
# adjudicado supera el presupuesto en más de un 50% (errores de fuente o
# modificados mal atribuidos). Mismo criterio que ``VALID_PAIR``, aplicado al
# agregado.
_TOLERANCIA_SOBRECOSTE = 1.5


def _sql_agregado(hasta: str | None) -> tuple[str, list[Any]]:
    """SQL de una fila por expediente adjudicado, con su presupuesto efectivo.

    ``hasta`` filtra por fecha de adjudicación **dentro de las agregaciones**:
    si se filtrase por fuera, un expediente con un lote adjudicado después del
    corte incluiría ese importe en la suma y el target vería el futuro.

    Devuelve ``(sql, params)``; el SELECT resultante expone ``fecha_anchor``,
    el instante desde el que se miran las features históricas: la fecha de
    publicación, **acotada** a no superar la de adjudicación. ``LEAST`` ignora
    NULLs, así que resuelve de una vez el respaldo (publicación ausente) y el
    tope: si una fila trae publicación posterior a su adjudicación --error de
    fuente-- el ancla cae en la adjudicación y el acumulador nunca puede
    incorporar el resultado de la propia fila antes de leerla, que es la
    garantía anti-fuga de ``services.ml.features``.
    """
    filtro_adj = " AND a.fecha_adjudicacion <= %s" if hasta else ""
    filtro_lote = " AND fecha_adjudicacion <= %s" if hasta else ""
    params: list[Any] = []
    if hasta:
        params.extend([hasta, hasta])

    sql = f"""
        WITH adj AS (
            SELECT a.licitacion_id AS lic_id,
                   SUM(a.importe_adjudicado) AS total_adjudicado,
                   COUNT(*) AS n_adjudicaciones,
                   COUNT(a.lote_id) AS n_con_lote,
                   MAX(a.fecha_adjudicacion) AS fecha_adjudicacion,
                   AVG(a.n_ofertas_recibidas::float) AS n_ofertas_media
            FROM adjudicaciones a
            WHERE a.importe_adjudicado > 0
              AND a.fecha_adjudicacion IS NOT NULL
              AND {_NO_DUPLICADOS}{filtro_adj}
            GROUP BY a.licitacion_id
        ),
        lotes_adjudicados AS (
            SELECT d.licitacion_id AS lic_id, SUM(lo.importe) AS presupuesto_lotes
            FROM (
                SELECT DISTINCT licitacion_id, lote_id
                FROM adjudicaciones
                WHERE lote_id IS NOT NULL AND importe_adjudicado > 0{filtro_lote}
            ) d
            JOIN lotes lo ON lo.id = d.lote_id
            WHERE lo.importe > 0
            GROUP BY d.licitacion_id
        ),
        lotes_publicados AS (
            SELECT licitacion_id AS lic_id, COUNT(*) AS n_lotes
            FROM lotes GROUP BY licitacion_id
        )
        SELECT * FROM (
            SELECT l.id_externo,
                   adj.fecha_adjudicacion,
                   LEAST(substr(l.fecha_publicacion, 1, 10),
                         substr(adj.fecha_adjudicacion, 1, 10)) AS fecha_anchor,
                   l.fecha_publicacion, l.fecha_limite,
                   l.organo_contratacion AS organo,
                   l.cpv, l.ccaa, l.provincia, l.tipo_contrato, l.fuente,
                   l.importe, l.duracion_valor, l.duracion_unidad,
                   COALESCE(lp.n_lotes, 0) AS n_lotes,
                   adj.total_adjudicado, adj.n_ofertas_media,
                   CASE
                       WHEN adj.n_adjudicaciones = adj.n_con_lote
                            AND la.presupuesto_lotes > 0
                       THEN la.presupuesto_lotes
                       ELSE l.importe
                   END AS presupuesto_efectivo
            FROM adj
            JOIN licitaciones l ON l.id_externo = adj.lic_id
            LEFT JOIN lotes_adjudicados la ON la.lic_id = adj.lic_id
            LEFT JOIN lotes_publicados lp ON lp.lic_id = adj.lic_id
            WHERE l.importe > 0 AND {_UNIVERSO}
        ) t
        WHERE t.presupuesto_efectivo > 0
          AND t.total_adjudicado <= t.presupuesto_efectivo * {_TOLERANCIA_SOBRECOSTE}
    """  # Interpola solo fragmentos constantes del módulo; los valores van con %s.
    return sql, params


class MlDatasetRepository:
    """Repositorio read-only del dataset de baja. No escribe nada."""

    def pares_baja_agregada(self, hasta: str | None = None) -> list[dict[str, Any]]:
        """Un expediente adjudicado por fila, en orden de fecha ancla.

        El orden (``fecha_anchor`` asc) es el que consume
        ``services.ml.features``: procesa las filas en orden de publicación y
        alimenta los acumuladores con los eventos de adjudicación anteriores,
        de modo que ninguna fila ve información posterior a su publicación.
        """
        sql, params = _sql_agregado(hasta)
        sql += " ORDER BY t.fecha_anchor ASC, t.id_externo ASC"
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, params))

    def adjudicaciones_por_empresa(self, hasta: str | None = None) -> list[dict[str, Any]]:
        """Importe adjudicado por (expediente, empresa), en orden de adjudicación.

        Alimenta el HHI del segmento, que necesita la cuota de cada empresa y
        no sobreviviría a la agregación por expediente de
        :meth:`pares_baja_agregada`: atribuir todo el expediente a su
        adjudicatario principal distorsionaría la concentración medida.
        """
        filtro = " AND a.fecha_adjudicacion <= %s" if hasta else ""
        params: list[Any] = [hasta] if hasta else []
        sql = f"""
            SELECT a.licitacion_id,
                   MAX(a.fecha_adjudicacion) AS fecha,
                   l.cpv, l.ccaa,
                   COALESCE(a.empresa_id::text, a.nombre) AS empresa,
                   SUM(a.importe_adjudicado) AS importe
            FROM adjudicaciones a
            JOIN licitaciones l ON l.id_externo = a.licitacion_id
            WHERE a.importe_adjudicado > 0
              AND a.fecha_adjudicacion IS NOT NULL
              AND {_UNIVERSO}
              AND {_NO_DUPLICADOS}{filtro}
            GROUP BY a.licitacion_id, l.cpv, l.ccaa, COALESCE(a.empresa_id::text, a.nombre)
            ORDER BY MAX(a.fecha_adjudicacion) ASC, a.licitacion_id ASC
        """  # Interpola solo fragmentos constantes del módulo; los valores van con %s.
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, params))

    def licitaciones_abiertas(
        self, *, estados_cerrados: tuple[str, ...], limit: int = 5000
    ) -> list[dict[str, Any]]:
        """Licitaciones sin adjudicación, para el batch de scoring.

        Expone las mismas columnas que :meth:`pares_baja_agregada` puede
        conocer antes de adjudicar (fechas, duración, lotes publicados,
        provincia): el camino de scoring tiene que poder construir exactamente
        las mismas features que el de entrenamiento.
        """
        marcadores = ", ".join(["%s"] * len(estados_cerrados))
        sql = f"""
            SELECT l.id_externo, l.organo_contratacion AS organo,
                   l.cpv, l.ccaa, l.provincia, l.tipo_contrato, l.fuente, l.importe,
                   l.fecha_publicacion, l.fecha_limite,
                   l.duracion_valor, l.duracion_unidad,
                   -- Subquery correlada, no un GROUP BY de toda `lotes`: esta
                   -- query devuelve como mucho `limit` filas y hay índice
                   -- (idx_lotes_licitacion, v66), así que cuesta N búsquedas
                   -- indexadas en vez de agregar la tabla entera.
                   (SELECT COUNT(*) FROM lotes lo WHERE lo.licitacion_id = l.id_externo)
                       AS n_lotes
            FROM licitaciones l
            WHERE l.importe > 0
              AND {_UNIVERSO}
              AND COALESCE(l.estado, '') NOT IN ({marcadores})
              AND NOT EXISTS (
                  SELECT 1 FROM adjudicaciones a WHERE a.licitacion_id = l.id_externo
              )
              AND l.id_externo NOT IN (
                  SELECT licitacion_id FROM licitaciones_duplicados WHERE status = 'confirmed'
              )
            ORDER BY l.fecha_publicacion DESC
            LIMIT %s
        """  # Los marcadores se generan aquí; los valores van con %s.
        with connect_read() as c:
            return rows_to_dicts(
                c.execute(sql, (*estados_cerrados, max(1, min(int(limit), 50_000))))
            )

    def media_global_baja(self, defecto: float = 0.12) -> float:
        """Baja media agregada del histórico, baseline sin modelo activo.

        Comparte la regla de denominador con el target de entrenamiento: el
        baseline y el modelo predicen la misma magnitud.
        """
        sql, params = _sql_agregado(None)
        envuelto = (
            "SELECT AVG((t2.presupuesto_efectivo - t2.total_adjudicado) "
            f"/ t2.presupuesto_efectivo) FROM ({sql}) t2"
        )
        with connect_read() as c:
            row = c.execute(envuelto, params).fetchone()
        return float(row[0]) if row and row[0] is not None else defecto

    def calibracion_baja(self) -> dict[str, Any]:
        """Cobertura empírica, MAE y sesgo de ``predicciones_baja`` vs la realidad.

        La baja realizada se calcula con la **misma** regla que el target de
        entrenamiento, que es lo que hace comparable la cobertura empírica con
        la nominal. Antes esta query dividía siempre entre ``l.importe``
        mientras el entrenamiento usaba el presupuesto del lote: se medía una
        magnitud distinta de la que se entrenaba.
        """
        sql, params = _sql_agregado(None)
        envuelto = f"""
            WITH evaluadas AS (
                SELECT pb.p10 AS p10, pb.p50 AS p50, pb.p90 AS p90,
                       (t2.presupuesto_efectivo - t2.total_adjudicado)
                           / t2.presupuesto_efectivo AS realizada
                FROM predicciones_baja pb
                JOIN ({sql}) t2 ON t2.id_externo = pb.licitacion_id
            )
            SELECT COUNT(*) AS n,
                   AVG(CASE WHEN realizada BETWEEN p10 AND p90 THEN 1.0 ELSE 0.0 END) AS cobertura,
                   AVG(ABS(realizada - p50)) AS mae,
                   AVG(realizada - p50) AS sesgo
            FROM evaluadas
        """  # SQL propio del módulo; los valores van con %s.
        with connect_read() as c:
            row = c.execute(envuelto, params).fetchone()
        if not row or row[0] is None:
            return {"n": 0, "cobertura": None, "mae": None, "sesgo": None}
        return {
            "n": int(row[0]),
            "cobertura": float(row[1]) if row[1] is not None else None,
            "mae": float(row[2]) if row[2] is not None else None,
            "sesgo": float(row[3]) if row[3] is not None else None,
        }
