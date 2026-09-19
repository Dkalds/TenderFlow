"""Repository de lectura (y purga) para las tablas de predicciones ML.

``predicciones_retencion`` la **escribe** ``services/ml/scoring.py``
(whitelist TID251); ``predicciones_baja`` la escribe el mismo servicio a
través de :meth:`PrediccionesRepository.guardar_baja` desde que v140 cambió su
unicidad (agregada o por lote). Este repository cubre también las
lecturas de verificación/reporting que antes vivían como SQL inline en los
heredocs de ``.github/workflows/ml-scoring.yml``, la lectura que alimenta la
señal de margen del scoring (antes inline en
``services/analytics/scoring_signals.py``), las lecturas por lote que sirve
``GET /licitaciones/{id}/prediccion-baja?lote_id=…`` (S3.1) y la purga por
antigüedad.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read
from db.repositories.base import rows_to_dicts
from db.sql_fragments import exclude_duplicados_sql
from shared.estados import ESTADOS_CERRADOS

# Tablas de predicciones cuyo estado se puede consultar. Whitelist explícita:
# el nombre se interpola en el SQL, así que nunca puede venir de fuera.
_TABLAS = frozenset({"predicciones_baja", "predicciones_retencion"})


class PrediccionesRepository:
    """Lecturas de verificación, señal de margen y purga de predicciones."""

    def estado(self, tabla: str = "predicciones_baja") -> dict[str, Any]:
        """Número de filas y ``computed_at`` más reciente de una tabla.

        Args:
            tabla: Una de ``predicciones_baja`` / ``predicciones_retencion``.

        Returns:
            Dict con ``filas`` (int) y ``ultimo_computed_at`` (str | None).

        Raises:
            ValueError: Si ``tabla`` no está en la whitelist.
        """
        if tabla not in _TABLAS:
            raise ValueError(f"Tabla no permitida: {tabla!r}")
        with connect_read() as c:
            # Tabla interpolada pero validada contra _TABLAS: nunca input de
            # usuario. S608 ya está ignorado para db/** en pyproject.toml.
            row = c.execute(f"SELECT COUNT(*), MAX(computed_at) FROM {tabla}").fetchone()
        if not row:
            return {"filas": 0, "ultimo_computed_at": None}
        return {"filas": int(row[0] or 0), "ultimo_computed_at": row[1]}

    def baja_p50_con_origen(self) -> list[dict[str, Any]]:
        """``(licitacion_id, p50, model_version)`` de todas las predicciones de baja.

        ``model_version`` es la pieza que faltaba aguas abajo: ``services/ml/
        scoring.py`` escribe en esta misma tabla las filas del **modelo**
        (``model_version = int``) y las del **baseline histórico**
        (``model_version = NULL``), distinción que preserva con cuidado en el
        resumen del job (``degradado``) y que el consumidor de la señal de
        margen perdía al leer solo ``licitacion_id, p50``. Un p50 de la media
        del segmento y un p50 de un GBM entrenado no valen lo mismo y hasta
        ahora se servían indistinguibles.

        Sin ``WHERE``, igual que antes: el modo page-aligned del Detalle puntúa
        filas que ya no están en el universo vivo, y filtrarlas aquí les
        quitaría el margen en silencio. Lo que evita que la tabla crezca sin
        control es :meth:`purgar_cerradas`, no un filtro de lectura.

        El único filtro es la granularidad: solo la fila **agregada**
        (``lote_numero IS NULL``). La señal es por expediente y el consumidor
        indexa por ``licitacion_id``; con las filas por lote de v140 dentro, el
        p50 de un lote cualquiera pisaría al del expediente según el orden en
        que llegasen.
        """
        with connect_read() as c:
            return rows_to_dicts(
                c.execute(
                    "SELECT licitacion_id, p50, model_version FROM predicciones_baja "
                    "WHERE lote_numero IS NULL"
                )
            )

    def guardar_baja(
        self,
        filas: list[tuple[str, str | None, float, float, float, int | None, str]],
    ) -> int:
        """Upsert idempotente de predicciones de baja, agregadas o por lote.

        Cada fila es ``(licitacion_id, lote_numero, p10, p50, p90,
        model_version, computed_at)``; ``lote_numero`` ``None`` es la predicción
        del expediente entero.

        Dos sentencias y no una porque desde v140 la unicidad son **dos únicos
        parciales** (``uq_pred_baja_expediente`` / ``uq_pred_baja_lote``), y el
        árbitro de ``ON CONFLICT`` tiene que nombrar el predicado del índice
        que lo respalda: Postgres infiere un índice parcial solo si el
        ``WHERE`` del árbitro implica el del índice. Un único ``INSERT`` con
        filas de los dos tipos no tiene árbitro válido.

        Vive aquí y no en ``services.ml.scoring`` —donde estaba el upsert
        agregado— porque cambiar el árbitro era escribir SQL nuevo, y el SQL
        nuevo solo nace en ``db/`` (ADR-022).

        Returns:
            Filas enviadas (no cuántas cambiaron).
        """
        agregadas = [f for f in filas if f[1] is None]
        por_lote = [f for f in filas if f[1] is not None]
        actualizar = (
            "p10=excluded.p10, p50=excluded.p50, p90=excluded.p90, "
            "model_version=excluded.model_version, computed_at=excluded.computed_at"
        )
        columnas = (
            "INSERT INTO predicciones_baja "
            "(licitacion_id, lote_numero, p10, p50, p90, model_version, computed_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
        )
        with connect() as c:
            if agregadas:
                c.executemany(
                    columnas + "ON CONFLICT (licitacion_id) WHERE lote_numero IS NULL "
                    f"DO UPDATE SET {actualizar}",
                    agregadas,
                )
            if por_lote:
                c.executemany(
                    columnas + "ON CONFLICT (licitacion_id, lote_numero) "
                    f"WHERE lote_numero IS NOT NULL DO UPDATE SET {actualizar}",
                    por_lote,
                )
        return len(filas)

    # ── Lecturas por lote (S3.1) ─────────────────────────────────────────────
    # El expediente no es la unidad sobre la que se puja: el lote lo es
    # (``v86``). Estas tres lecturas son las que necesita
    # ``services.ml.scoring.prediccion_baja`` para servir un lote, y viven aquí
    # —y no como SQL inline en el servicio— porque son SQL nuevo (ADR-022: la
    # whitelist TID251 de ``services/`` solo puede encoger).

    def lote_de(self, licitacion_id: str, lote_id: int) -> dict[str, Any] | None:
        """El lote ``lote_id`` **si pertenece** a ``licitacion_id``, o ``None``.

        La pertenencia va en el mismo WHERE que la búsqueda (mismo criterio que
        ``PursuitRepository.lote_by_id``): sin ella se serviría la predicción
        del lote de otro expediente a quien pidiera el id equivocado.
        """
        with connect_read() as c:
            rows = rows_to_dicts(
                c.execute(
                    "SELECT id, numero, importe FROM lotes WHERE id = %s AND licitacion_id = %s",
                    (lote_id, licitacion_id),
                )
            )
        return rows[0] if rows else None

    def prediccion_materializada(
        self, licitacion_id: str, lote_numero: str | None = None
    ) -> dict[str, Any] | None:
        """La fila de ``predicciones_baja`` de ese lote, o la agregada.

        ``lote_numero=None`` pide **explícitamente** la fila del expediente
        entero (``lote_numero IS NULL``). La del lote solo existe si el batch
        por lote la materializó (``ML_BAJA_POR_LOTE``, v140); servir la del
        expediente para un lote es una aproximación declarada, no un dato del
        lote — quien la use tiene que decirlo (``prediccion_ambito`` en el DTO
        de la ruta).

        Por ``lote_numero`` y no por ``lotes.id``: el id se renumera en cada
        re-ingesta (cabecera de v140).
        """
        clausula = "lote_numero IS NULL" if lote_numero is None else "lote_numero = %s"
        parametros: tuple[Any, ...] = (
            (licitacion_id,) if lote_numero is None else (licitacion_id, lote_numero)
        )
        with connect_read() as c:
            rows = rows_to_dicts(
                c.execute(
                    "SELECT p10, p50, p90, model_version, computed_at "
                    f"FROM predicciones_baja WHERE licitacion_id = %s AND {clausula}",
                    parametros,
                )
            )
        return rows[0] if rows else None

    def predicciones_por_lote(self, licitacion_id: str) -> list[dict[str, Any]]:
        """Las predicciones **propias** de cada lote publicado del expediente.

        Es el desglose que sirve ``GET /licitaciones/{id}/prediccion-baja``
        junto a la cifra agregada. Solo filas que el batch materializó para un
        lote (``lote_numero`` no nulo): un lote sin fila propia no aparece, en
        vez de aparecer con la cifra del expediente — el desglose afirma «esto
        es lo que el modelo por lote dice de este lote», y rellenarlo con el
        agregado convertiría 30 copias de la misma cifra en un desglose.

        El ``JOIN`` con ``lotes`` por la clave de negocio re-resuelve el
        ``lote_id`` vigente (se renumera en cada re-ingesta, ver v140) y deja
        fuera las predicciones de lotes que ya no figuran publicados.
        """
        with connect_read() as c:
            return rows_to_dicts(
                c.execute(
                    "SELECT lo.id AS lote_id, p.lote_numero, p.p10, p.p50, p.p90, "
                    "       p.model_version, p.computed_at "
                    "FROM predicciones_baja p "
                    "JOIN lotes lo ON lo.licitacion_id = p.licitacion_id "
                    "             AND lo.numero = p.lote_numero "
                    "WHERE p.licitacion_id = %s AND p.lote_numero IS NOT NULL "
                    "ORDER BY lo.id",
                    (licitacion_id,),
                )
            )

    def baja_real_de_lote(self, licitacion_id: str, lote_id: int) -> dict[str, Any] | None:
        """``{presupuesto, total_adjudicado}`` del lote, o ``None`` si no existe.

        A diferencia del agregado por expediente
        (``services.ml.scoring._baja_real``), aquí el denominador no admite
        discusión: es el importe **de ese lote**. Puede venir NULL —hay pliegos
        que no publican el importe lote a lote—, y entonces no hay baja que
        calcular: quien llama devuelve la predicción sin la realidad en vez de
        dividir por el presupuesto del expediente, que daría una baja diez
        veces menor de la real (ADR-014).

        ``total_adjudicado`` suma las adjudicaciones **de ese lote**: un lote
        puede repartirse entre varias empresas y cada una es una fila.
        """
        # S608 no aplica: el único fragmento interpolado es una constante de
        # este mismo paquete; los valores viajan como parámetros.
        sql = f"""
            SELECT lo.importe AS presupuesto,
                   (
                       SELECT SUM(a.importe_adjudicado)
                       FROM adjudicaciones a
                       WHERE a.lote_id = lo.id
                         AND a.licitacion_id = lo.licitacion_id
                         AND a.importe_adjudicado > 0
                         AND {exclude_duplicados_sql("a.licitacion_id")}
                   ) AS total_adjudicado
            FROM lotes lo
            WHERE lo.id = %s AND lo.licitacion_id = %s
        """
        with connect_read() as c:
            rows = rows_to_dicts(c.execute(sql, (lote_id, licitacion_id)))
        return rows[0] if rows else None

    def purgar_cerradas(self, *, antes_de: str, tabla: str = "predicciones_baja") -> int:
        """Borra predicciones de expedientes cerrados antes de ``antes_de``.

        El upsert del batch nocturno nunca purga, así que la tabla crece de
        forma monótona: una vez que un expediente se cierra, su fila deja de
        actualizarse pero se queda para siempre — y el loader de la señal de
        margen la carga **entera** a un dict en cada refresco de caché.

        Criterio de "cerrado hace más de N días": estado terminal
        (``shared.estados.ESTADOS_CERRADOS``) y fecha de cierre anterior al
        corte. Como fecha de cierre se usa la última adjudicación del
        expediente y, si no tiene ninguna (anulados, agregados), la fecha
        límite o la de publicación. Los tres campos son TEXT en formato ISO, y
        la comparación lexicográfica sobre ``YYYY-MM-DD`` es la misma que usa
        el resto del esquema.

        Args:
            antes_de: Corte ``YYYY-MM-DD``; se borra lo cerrado **antes**.
            tabla: Una de las de :data:`_TABLAS`.

        Returns:
            Número de filas borradas.

        Raises:
            ValueError: Si ``tabla`` no está en la whitelist.
        """
        if tabla not in _TABLAS:
            raise ValueError(f"Tabla no permitida: {tabla!r}")
        marcadores = ", ".join(["%s"] * len(ESTADOS_CERRADOS))
        # Tabla y marcadores se generan aquí (whitelist + longitud de una
        # constante del módulo); los valores viajan como parámetros.
        sql = f"""
            DELETE FROM {tabla}
            WHERE licitacion_id IN (
                SELECT p.licitacion_id
                FROM {tabla} p
                JOIN licitaciones l ON l.id_externo = p.licitacion_id
                LEFT JOIN (
                    SELECT licitacion_id, MAX(fecha_adjudicacion) AS fecha_cierre
                    FROM adjudicaciones
                    GROUP BY licitacion_id
                ) a ON a.licitacion_id = p.licitacion_id
                WHERE l.estado IN ({marcadores})
                  AND COALESCE(
                          substr(a.fecha_cierre, 1, 10),
                          substr(l.fecha_limite, 1, 10),
                          substr(l.fecha_publicacion, 1, 10)
                      ) < %s
            )
        """
        with connect() as c:
            cur = c.execute(sql, (*ESTADOS_CERRADOS, antes_de))
            borradas = int(getattr(cur, "rowcount", 0) or 0)
            c.commit()
        return borradas
