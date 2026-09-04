"""Lecturas del dataset de los modelos predictivos de baja.

Todo el SQL del dataset de ``services/ml/`` vive aquí (ADR-022: el SQL solo
existe en ``db/``). Antes estaba inline en ``services/ml/features.py`` y
``services/ml/calibration.py``, ambos en la whitelist congelada del ratchet
TID251 -- moverlo la encoge, que es la única dirección permitida.

**La unidad por defecto es el expediente, no el lote.** Una licitación
multi-lote tiene varias filas en ``adjudicaciones``; en el camino agregado se
juntan en una sola observación antes de dividir. El motivo es que las tres
superficies que consumen esto hablaban de granularidades distintas:

- entrenamiento: una fila por adjudicación (baja del lote contra su lote),
- ``predicciones_baja``: PK ``licitacion_id``, una predicción por expediente,
- ``calibration.py``: baja realizada agregada por expediente.

Con el agregado, las tres miden lo mismo y la cobertura empírica del intervalo
pasa a ser comparable con la nominal.

**La variante por lote existe desde v86 pero NO es el default.** El lote es la
unidad sobre la que se puja, así que una cifra por expediente de 30 lotes es
menos accionable que 30 cifras; pero sustituir el agregado está condicionado a
medir antes el ``mae_p50`` por lote contra el agregado actual, y esa medida
requiere Postgres con histórico. :meth:`~MlDatasetRepository.pares_baja_por_lote`
y :meth:`~MlDatasetRepository.calibracion_baja_por_lote` son la instrumentación
que hace posible esa comparación (ver ``services.ml.calibration``); hasta que
diga que el lote mejora, el agregado se queda.

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
from db.sql_fragments import TECHNOLOGY_OBSERVED_SQL, exclude_duplicados_sql

# Exclusión de duplicados cross-fuente. Era una copia literal de la subconsulta
# —``db/`` no podía depender de ``services/`` (ADR-024)—; desde que la
# definición canónica vive en ``db/sql_fragments.py`` se compone desde allí.
# Sigue siendo constante de módulo porque las cuatro consultas de este fichero
# la interpolan sobre el mismo alias. Solo excluye duplicados ``confirmed``;
# los ``pending`` cuentan hasta que un humano los confirme.
_NO_DUPLICADOS = exclude_duplicados_sql("a.licitacion_id")

_UNIVERSO = TECHNOLOGY_OBSERVED_SQL

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


def _sql_por_lote(hasta: str | None) -> tuple[str, list[Any]]:
    """SQL de una fila por **lote adjudicado**, con el presupuesto de ese lote.

    Misma estructura y mismos filtros que :func:`_sql_agregado` (duplicados
    confirmados fuera, universo tecnológico, tolerancia de sobrecoste, corte
    ``hasta`` aplicado *dentro* de las agregaciones para no ver el futuro), y
    la misma columna ``fecha_anchor`` con su garantía anti-fuga. Lo que cambia
    es la clave y el denominador:

    - ``lote_id IS NOT NULL`` -> una fila por ``(expediente, lote)``, con
      denominador ``lotes.importe``. Un lote adjudicado a dos empresas suma sus
      importes en una única fila: son dos adjudicatarios de la misma unidad de
      compra, no dos observaciones.
    - ``lote_id IS NULL`` -> una sola fila por expediente con denominador
      ``licitaciones.importe``. Es el caso de lote único (o de datos anteriores
      a v65_lotes, donde el parser no resolvía el lote): el expediente **es** la
      unidad de puja, y por eso la clave admite ``lote_id`` NULL, igual que el
      índice único ``(licitacion_id, COALESCE(lote_id, -1))`` de v86.

    El caso mixto —expediente con algunas adjudicaciones con lote resuelto y
    otras sin él— descarta las filas sin lote en vez de darles un denominador.
    ``licitaciones.importe`` ahí es el presupuesto del expediente **entero**,
    ya contado por las filas con lote: usarlo produciría una baja fantasma
    contra un presupuesto que no le corresponde. Es el mismo razonamiento que
    ``_sql_agregado`` aplica con ``n_adjudicaciones = n_con_lote``, resuelto
    aquí por fila en vez de por expediente.

    ``COALESCE(lo.importe, l.importe)`` es la regla de denominador por fila que
    ``db.repositories.pricing`` ya usa (gemela de
    ``services.sql_fragments.EFFECTIVE_BUDGET_SQL``); la diferencia es que aquí
    el ``COALESCE`` nunca cae al expediente para una fila **con** lote, porque
    esas se exigen con ``lo.importe > 0``: un lote sin presupuesto publicado no
    tiene denominador propio y no puede entrar en el dataset por lote.
    """
    filtro_adj = " AND a.fecha_adjudicacion <= %s" if hasta else ""
    filtro_mixto = " AND fecha_adjudicacion <= %s" if hasta else ""
    params: list[Any] = []
    if hasta:
        params.extend([hasta, hasta])

    sql = f"""
        WITH adj AS (
            SELECT a.licitacion_id AS lic_id,
                   a.lote_id AS lote_id,
                   SUM(a.importe_adjudicado) AS total_adjudicado,
                   MAX(a.fecha_adjudicacion) AS fecha_adjudicacion,
                   AVG(a.n_ofertas_recibidas::float) AS n_ofertas_media
            FROM adjudicaciones a
            WHERE a.importe_adjudicado > 0
              AND a.fecha_adjudicacion IS NOT NULL
              AND {_NO_DUPLICADOS}{filtro_adj}
            GROUP BY a.licitacion_id, a.lote_id
        ),
        con_algun_lote AS (
            SELECT DISTINCT licitacion_id AS lic_id
            FROM adjudicaciones
            WHERE lote_id IS NOT NULL AND importe_adjudicado > 0{filtro_mixto}
        ),
        lotes_publicados AS (
            SELECT licitacion_id AS lic_id, COUNT(*) AS n_lotes
            FROM lotes GROUP BY licitacion_id
        )
        SELECT * FROM (
            SELECT l.id_externo,
                   adj.lote_id,
                   lo.numero AS lote_numero,
                   adj.fecha_adjudicacion,
                   LEAST(substr(l.fecha_publicacion, 1, 10),
                         substr(adj.fecha_adjudicacion, 1, 10)) AS fecha_anchor,
                   l.fecha_publicacion, l.fecha_limite,
                   l.organo_contratacion AS organo,
                   -- El CPV del lote cuando existe: en un expediente mixto
                   -- (obra + mantenimiento) el CPV del expediente es el del
                   -- conjunto y no describe la unidad que se puja.
                   COALESCE(lo.cpv, l.cpv) AS cpv,
                   l.ccaa, l.provincia, l.tipo_contrato, l.fuente,
                   l.importe, l.duracion_valor, l.duracion_unidad,
                   COALESCE(lp.n_lotes, 0) AS n_lotes,
                   adj.total_adjudicado, adj.n_ofertas_media,
                   COALESCE(lo.importe, l.importe) AS presupuesto_efectivo
            FROM adj
            JOIN licitaciones l ON l.id_externo = adj.lic_id
            LEFT JOIN lotes lo ON lo.id = adj.lote_id
            LEFT JOIN lotes_publicados lp ON lp.lic_id = adj.lic_id
            WHERE l.importe > 0 AND {_UNIVERSO}
              AND (
                  (adj.lote_id IS NOT NULL AND lo.importe > 0)
                  OR (adj.lote_id IS NULL AND NOT EXISTS (
                          SELECT 1 FROM con_algun_lote cal WHERE cal.lic_id = adj.lic_id
                      ))
              )
        ) t
        WHERE t.presupuesto_efectivo > 0
          AND t.total_adjudicado <= t.presupuesto_efectivo * {_TOLERANCIA_SOBRECOSTE}
    """  # Interpola solo fragmentos constantes del módulo; los valores van con %s.
    return sql, params


# Predicción aplicable a una fila del dataset por lote: la del lote exacto si
# el batch la materializó, y si no la del expediente. El ``ORDER BY`` ordena
# false < true, así que la específica gana a la agregada; ``LIMIT 1`` garantiza
# que un expediente con predicción por lote Y agregada no cuente dos veces.
#
# Mientras el serving siga siendo agregado (v86 no cambia el default), TODAS
# las filas caen en la rama agregada: eso no es un apaño, es exactamente la
# medida que pide el gate — el modelo actual evaluado a granularidad de lote,
# que es el número contra el que hay que comparar un futuro modelo por lote.
_PREDICCION_APLICABLE = """
    SELECT p.p10, p.p50, p.p90, p.lote_id, p.model_version
    FROM predicciones_baja p
    WHERE p.licitacion_id = pl.id_externo
      AND (p.lote_id = pl.lote_id OR p.lote_id IS NULL)
    ORDER BY (p.lote_id IS NULL)
    LIMIT 1
"""

# Agregados de calibración, medidos a la vez sobre el total y sobre cada
# régimen de serving. ``GROUPING(es_baseline)`` marca la fila del total, que así
# sale exacto en el mismo viaje en vez de recomponerse ponderando en Python.
_AGREGADOS_CALIBRACION = """
    GROUPING(es_baseline) AS es_total,
    es_baseline,
    COUNT(*) AS n,
    AVG(CASE WHEN realizada BETWEEN p10 AND p90 THEN 1.0 ELSE 0.0 END) AS cobertura,
    AVG(ABS(realizada - p50)) AS mae,
    AVG(realizada - p50) AS sesgo
"""

_SIN_DATOS: dict[str, Any] = {"n": 0, "cobertura": None, "mae": None, "sesgo": None}


def _por_regimen(filas: list[Any], con_lote: bool = False) -> dict[str, Any]:
    """Descompone un GROUPING SET en total + un bloque por régimen de serving.

    Un solo número que promedie los intervalos que sirvió el modelo con los que
    sirvió el baseline no describe a ninguno de los dos: el modelo conformaliza
    su intervalo y el baseline el suyo, con anchuras distintas, así que la
    mezcla depende de en qué proporción se sirvió cada uno y no de si alguno
    está bien calibrado. El total se conserva —es lo que el usuario tiene
    servido, venga de donde venga— y el desglose es lo que permite **atribuir**
    una degradación en vez de solo detectarla.
    """
    total = dict(_SIN_DATOS)
    regimenes: dict[str, dict[str, Any]] = {
        "modelo": dict(_SIN_DATOS),
        "baseline": dict(_SIN_DATOS),
    }
    if con_lote:
        total["n_prediccion_por_lote"] = 0
        for bloque in regimenes.values():
            bloque["n_prediccion_por_lote"] = 0

    for fila in filas:
        medido: dict[str, Any] = {
            "n": int(fila[2] or 0),
            "cobertura": float(fila[3]) if fila[3] is not None else None,
            "mae": float(fila[4]) if fila[4] is not None else None,
            "sesgo": float(fila[5]) if fila[5] is not None else None,
        }
        if con_lote:
            medido["n_prediccion_por_lote"] = int(fila[6] or 0)
        if fila[0]:  # GROUPING(es_baseline) = 1 → la fila agregada
            total = medido
        else:
            regimenes["baseline" if fila[1] else "modelo"] = medido

    return {**total, "por_regimen": regimenes}


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

    def pares_baja_por_lote(self, hasta: str | None = None) -> list[dict[str, Any]]:
        """Un **lote adjudicado** por fila, en el mismo orden que el agregado.

        Gemela de :meth:`pares_baja_agregada` a la granularidad sobre la que se
        puja de verdad. Expone las mismas columnas más ``lote_id`` y
        ``lote_numero``, y con ``cpv`` resuelto al del lote cuando lo hay, para
        que un constructor de features pueda consumir cualquiera de las dos sin
        ramificar.

        El orden (``fecha_anchor`` asc) es el mismo contrato anti-fuga: los
        acumuladores históricos solo pueden haber visto adjudicaciones
        anteriores al ancla de la fila que están alimentando. Se desempata
        además por ``lote_id`` para que dos ejecuciones sobre los mismos datos
        devuelvan la misma secuencia -- sin ese desempate el orden de los lotes
        de un expediente lo decide el plan de ejecución, y un dataset de
        entrenamiento no reproducible es un modelo no reproducible.
        """
        sql, params = _sql_por_lote(hasta)
        sql += " ORDER BY t.fecha_anchor ASC, t.id_externo ASC, t.lote_id ASC NULLS FIRST"
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
              AND {exclude_duplicados_sql("l.id_externo")}
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

    def pares_baseline_resueltos(self) -> list[tuple[float, float]]:
        """``(p50_servido, baja_realizada)`` de los pares que sirvió el baseline.

        Solo filas con ``model_version IS NULL``: son exactamente las que
        produjo ``predecir_baseline``, y calibrar el baseline con intervalos que
        salieron del modelo mediría otra cosa.

        Devuelve el ``p50`` y **no** el intervalo almacenado, a propósito. El
        offset conformal tiene que medirse siempre contra el intervalo *crudo*
        de la regla (``services.ml.baja_model.intervalo_baseline``), que es
        reconstruible desde ``p50`` porque el offset nunca toca la mediana. Si
        se midiera contra el ``p10``/``p90`` ya guardados, cada noche se
        calcularía la corrección sobre un intervalo ya corregido: el score
        saldría ~0 y la anchura quedaría congelada en la de la primera pasada.

        Misma regla de denominador que el target de entrenamiento, por el mismo
        motivo que en :meth:`calibracion_baja`.
        """
        sql, params = _sql_agregado(None)
        envuelto = f"""
            SELECT pb.p50 AS p50,
                   (t2.presupuesto_efectivo - t2.total_adjudicado)
                       / t2.presupuesto_efectivo AS realizada
            FROM predicciones_baja pb
            JOIN ({sql}) t2 ON t2.id_externo = pb.licitacion_id
            WHERE pb.model_version IS NULL
        """  # SQL propio del módulo; los valores van con %s.
        with connect_read() as c:
            filas = c.execute(envuelto, params).fetchall()
        return [
            (float(p50), float(realizada))
            for p50, realizada in filas
            if p50 is not None and realizada is not None
        ]

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
                SELECT (pb.model_version IS NULL) AS es_baseline,
                       pb.p10 AS p10, pb.p50 AS p50, pb.p90 AS p90,
                       (t2.presupuesto_efectivo - t2.total_adjudicado)
                           / t2.presupuesto_efectivo AS realizada
                FROM predicciones_baja pb
                JOIN ({sql}) t2 ON t2.id_externo = pb.licitacion_id
            )
            SELECT {_AGREGADOS_CALIBRACION}
            FROM evaluadas
            GROUP BY GROUPING SETS ((es_baseline), ())
        """  # SQL propio del módulo; los valores van con %s.
        with connect_read() as c:
            filas = c.execute(envuelto, params).fetchall()
        return _por_regimen(list(filas))

    def calibracion_baja_por_lote(self) -> dict[str, Any]:
        """Lo mismo que :meth:`calibracion_baja`, pero un par por **lote**.

        Existe para poder responder a la única pregunta que decide si el modelo
        por lote sustituye al agregado: ¿cuánto vale ``mae_p50`` medido sobre la
        unidad que realmente se puja? Sin esta medida, cambiar la granularidad
        del serving sería una apuesta.

        Cada lote adjudicado se empareja con la predicción **más específica**
        disponible (la de su lote si existe; la del expediente si no). Devuelve
        además ``n_prediccion_por_lote``, el número de pares que usaron una
        predicción propia del lote: mientras el serving sea agregado ese contador
        vale 0 y la cifra que sale es "el modelo agregado evaluado por lote" --
        el baseline contra el que comparar. Leer el MAE sin mirar ese contador
        es confundir el baseline con el candidato.
        """
        sql, params = _sql_por_lote(None)
        envuelto = f"""
            WITH evaluadas AS (
                SELECT (pb.model_version IS NULL) AS es_baseline,
                       pb.p10 AS p10, pb.p50 AS p50, pb.p90 AS p90,
                       pb.lote_id IS NOT NULL AS prediccion_propia,
                       (pl.presupuesto_efectivo - pl.total_adjudicado)
                           / pl.presupuesto_efectivo AS realizada
                FROM ({sql}) pl
                JOIN LATERAL ({_PREDICCION_APLICABLE}) pb ON TRUE
            )
            SELECT {_AGREGADOS_CALIBRACION},
                   COUNT(*) FILTER (WHERE prediccion_propia) AS n_prediccion_por_lote
            FROM evaluadas
            GROUP BY GROUPING SETS ((es_baseline), ())
        """  # SQL propio del módulo; los valores van con %s.
        with connect_read() as c:
            filas = c.execute(envuelto, params).fetchall()
        return _por_regimen(list(filas), con_lote=True)

    def regimen_servido(self) -> str | None:
        """``"modelo"`` o ``"baseline"``, según la última pasada de scoring.

        No se deduce de ``model_versions``: el scoring degrada a baseline aun
        con una versión activa si el artefacto no se resuelve o el layout de
        features no cuadra (``services.ml.scoring``). La fuente de verdad de lo
        que se está sirviendo es la propia tabla de predicciones.

        Mira solo el lote más reciente de ``computed_at`` (indexado): las filas
        viejas describen lo que se servía entonces, que es justo lo que no hay
        que confundir con lo de ahora. ``None`` si no hay ninguna predicción.
        """
        sql = """
            SELECT (model_version IS NULL) AS es_baseline, COUNT(*) AS n
            FROM predicciones_baja
            WHERE computed_at = (SELECT MAX(computed_at) FROM predicciones_baja)
            GROUP BY 1
            ORDER BY n DESC
            LIMIT 1
        """
        with connect_read() as c:
            row = c.execute(sql).fetchone()
        if not row:
            return None
        return "baseline" if row[0] else "modelo"
