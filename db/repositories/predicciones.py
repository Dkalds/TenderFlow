"""Repository de lectura (y purga) para las tablas de predicciones ML.

``predicciones_baja`` y ``predicciones_retencion`` las **escribe**
``services/ml/scoring.py`` (whitelist TID251). Este repository cubre las
lecturas de verificación/reporting que antes vivían como SQL inline en los
heredocs de ``.github/workflows/ml-scoring.yml``, la lectura que alimenta la
señal de margen del scoring (antes inline en
``services/analytics/scoring_signals.py``) y la purga por antigüedad.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read
from db.repositories.base import rows_to_dicts
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
        """
        with connect_read() as c:
            return rows_to_dicts(
                c.execute("SELECT licitacion_id, p50, model_version FROM predicciones_baja")
            )

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
