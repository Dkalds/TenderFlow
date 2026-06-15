"""Calibración del modelo de baja en producción (closed-loop).

``drift.py`` cubre el drift de *features* (PSI entrada). Falta cerrar el loop
sobre el *resultado*: ¿el intervalo p10-p90 que servimos cubre de verdad las
bajas que luego se observan? Un intervalo "80%" bien calibrado debe contener
~80% de las bajas reales; una cobertura muy por debajo significa que el modelo
es sobreconfiado y los intervalos engañan al usuario.

Las predicciones se materializan mientras la licitación está *abierta*
(``score_predicciones_baja`` solo puntúa abiertas) y la fila persiste en
``predicciones_baja``. Cuando esa licitación se adjudica, ya tenemos par
predicción↔realidad sin guardar nada nuevo: este monitor lo explota.

Mismo contrato que el monitor de drift: computa, loguea structured y alerta
por el canal existente; fail-open (nunca bloquea el scoring).
"""

from __future__ import annotations

from typing import Any

from db.database import connect_read
from observability.logging import get_logger
from services.competitive.bajas import _VALID_PAIR
from services.dedupe import exclude_duplicados_sql

log = get_logger(__name__)

# Cobertura nominal del intervalo servido (p10..p90 = 80%).
_COBERTURA_NOMINAL = 0.80
# Mínimo de pares resueltos para que la cobertura sea informativa.
_MIN_EVALUADAS = 30
# La cobertura empírica puede degradarse hasta estos puntos antes de alertar.
_COBERTURA_WARN = 0.65  # < nominal - 0.15
_COBERTURA_CRIT = 0.50  # < nominal - 0.30


def comprobar_calibracion_baja() -> dict[str, Any]:
    """Cobertura empírica del intervalo p10-p90 vs bajas realizadas.

    Devuelve cobertura (fracción dentro de [p10, p90]), MAE de p50 y sesgo
    (error medio firmado: positivo => el modelo infraestima la baja real).
    Fail-open: cualquier error se loguea y no propaga.
    """
    try:
        # S608: _VALID_PAIR y exclude_duplicados_sql son fragmentos constantes;
        # no hay input de usuario en esta query.
        sql = f"""
            WITH evaluadas AS (
                SELECT pb.p10 AS p10, pb.p50 AS p50, pb.p90 AS p90,
                       (l.importe - a.importe_adjudicado) / l.importe AS realizada
                FROM predicciones_baja pb
                JOIN licitaciones l ON l.id_externo = pb.licitacion_id
                JOIN adjudicaciones a ON a.licitacion_id = l.id_externo
                WHERE {_VALID_PAIR} AND {exclude_duplicados_sql()}
            )
            SELECT
                COUNT(*) AS n,
                AVG(CASE WHEN realizada BETWEEN p10 AND p90 THEN 1.0 ELSE 0.0 END) AS cobertura,
                AVG(ABS(realizada - p50)) AS mae,
                AVG(realizada - p50) AS sesgo
            FROM evaluadas
        """  # noqa: S608
        with connect_read() as c:
            row = c.execute(sql).fetchone()

        n = int(row[0]) if row and row[0] is not None else 0
        if n < _MIN_EVALUADAS:
            log.info("ml_calibracion_skip", reason="pocas_evaluadas", n=n)
            return {"status": "sin_datos", "n": n}

        cobertura = round(float(row[1]), 4)
        mae = round(float(row[2]), 4)
        sesgo = round(float(row[3]), 4)

        if cobertura < _COBERTURA_CRIT:
            severity = "crit"
        elif cobertura < _COBERTURA_WARN:
            severity = "warn"
        else:
            severity = "ok"

        resultado = {
            "status": severity,
            "n": n,
            "cobertura": cobertura,
            "cobertura_nominal": _COBERTURA_NOMINAL,
            "mae_p50": mae,
            "sesgo_p50": sesgo,
        }

        if severity != "ok":
            log.warning("ml_calibracion_degradada", **resultado)
            try:
                from observability.alerts import notify

                notify(
                    "warn" if severity == "warn" else "error",
                    f"Calibración del modelo de baja degradada "
                    f"(cobertura {cobertura:.0%} vs {_COBERTURA_NOMINAL:.0%} nominal)",
                    f"n={n} mae_p50={mae} sesgo_p50={sesgo}",
                )
            except Exception:  # canal de alertas opcional
                log.debug("ml_calibracion_alert_channel_unavailable")
        else:
            log.info("ml_calibracion_ok", **resultado)

        return resultado
    except Exception as e:  # fail-open como el monitor de drift
        log.warning("ml_calibracion_check_failed", error=str(e))
        return {"status": "error", "error": str(e)}
