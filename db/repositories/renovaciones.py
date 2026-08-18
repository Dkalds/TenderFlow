"""Repository de renovaciones: contratos adjudicados que vencen próximamente.

La fecha de fin efectiva se calcula en SQL con esta prioridad:

1. ``licitaciones.fecha_fin`` explícita (solo ~6% de las filas).
2. ``fecha_inicio + duracion`` (unidades CODICE: ANN/MON/DAY).
3. ``fecha_adjudicacion + duracion`` como último recurso.

Este módulo nace moviendo aquí el SQL del listado, que vivía en
``services/competitive/renovaciones.py`` — una de las entradas del ratchet
TID251 de ``pyproject.toml``. ADR-022: todo el SQL vive en ``db/``. Los
agregados de ese servicio (``resumen_renovaciones`` / ``totales_renovaciones``)
siguen allí de momento y por eso la entrada del ratchet no se puede quitar
todavía; los dos fragmentos compartidos con ellos
(:func:`rango_vencimiento_sql` y :func:`dias_restantes_sql`) se exponen desde
aquí para que exista un único sitio donde cambiarlos.

**Orden por oportunidad.** El listado se puede pedir ordenado por proximidad
del vencimiento (``order_by="fecha"``, el histórico) o por *score de
oportunidad* (``order_by="score"``). El score es ``riesgo x importe x
urgencia`` y se calcula **en SQL** para que un ``LIMIT N`` devuelva el top-N
real del dataset y no el top-N de la primera página por fecha de fin, que es
lo que veía el usuario cuando la tabla se reordenaba en cliente sobre las
1000 filas más próximas a vencer.
"""

from __future__ import annotations

from typing import Any, Literal

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from db.sql_fragments import (
    TECHNOLOGY_OBSERVED_SQL,
    exclude_duplicados_sql,
    fecha_fin_sql,
)

OrderBy = Literal["fecha", "score"]

# Días por mes con los que se convierte el horizonte de la consulta en la
# escala de urgencia del score. Es el mismo 30 que usa la vista
# (`web/src/app/(dashboard)/renovaciones/page.tsx`: `Number(meses) * 30`) al
# pintar el badge de oportunidad: si los dos números se separan, el orden que
# sirve el backend y el número que enseña la tabla dejan de contar la misma
# historia. La constante no pretende ser un calendario, solo una escala
# estable.
DIAS_POR_MES = 30

# Ventana máxima admitida (5 años). Acota el parámetro antes de que llegue al
# SQL; el valor viaja siempre como placeholder, este clamp es de dominio.
MAX_MESES = 60
MAX_LIMIT = 1000


def rango_vencimiento_sql() -> str:
    """``BETWEEN`` de vencimiento: hoy y hoy + N meses (parámetro ``%s``).

    Produce TEXT 'YYYY-MM-DD' para comparar contra ``fecha_fin_sql()``, que
    usa el mismo formato.
    """
    return (
        "BETWEEN to_char(CURRENT_DATE, 'YYYY-MM-DD') "
        "AND to_char(CURRENT_DATE + (%s * INTERVAL '1 month'), 'YYYY-MM-DD')"
    )


def dias_restantes_sql(fecha_fin_expr: str) -> str:
    """Días restantes hasta el vencimiento, como entero."""
    return f"(({fecha_fin_expr})::date - CURRENT_DATE)"


# ── Score de oportunidad ──────────────────────────────────────────────────
# La fórmula tiene dos encarnaciones que DEBEN coincidir: esta (SQL, la que
# ordena) y la de `web/src/lib/opportunity-score.ts` (TS, la que pinta el
# badge relativo). `score_oportunidad()`, justo debajo, es el port Python de
# ambas: existe para poder fijar la equivalencia en un test unitario sin
# Postgres delante (tests/test_renovaciones_score.py).


def urgencia_oportunidad(dias_restantes: float | None, horizonte_dias: float) -> float:
    """Urgencia normalizada 0..1.

    Vale 1 cuando el contrato vence ya (o venció) y decae linealmente hasta 0
    al final del horizonte. Port de ``urgency()`` en
    ``web/src/lib/opportunity-score.ts``.
    """
    if dias_restantes is None:
        return 0.0
    if horizonte_dias <= 0:
        return 1.0 if dias_restantes <= 0 else 0.0
    return min(1.0, max(0.0, 1.0 - dias_restantes / horizonte_dias))


def score_oportunidad(
    *,
    riesgo_cambio: float | None,
    importe: float | None,
    dias_restantes: float | None,
    horizonte_dias: float,
) -> float:
    """``riesgo_cambio x importe x urgencia``.

    Devuelve 0 cuando falta el riesgo o el importe: sin esos dos números no
    se puede priorizar, y un contrato sin score se va al fondo del orden en
    vez de colarse arriba por defecto. Port de ``opportunityScore()`` en
    ``web/src/lib/opportunity-score.ts``.
    """
    if riesgo_cambio is None or importe is None or importe <= 0:
        return 0.0
    return riesgo_cambio * importe * urgencia_oportunidad(dias_restantes, horizonte_dias)


def score_oportunidad_sql(dias_restantes_expr: str) -> str:
    """Expresión SQL del score; lleva **un** placeholder: el horizonte en días.

    Traducción literal de :func:`score_oportunidad`. Los tres ``NULL`` que
    allí devuelven 0.0 se comprueban aquí explícitamente porque en SQL
    cualquier operando NULL propagaría NULL al producto y el orden pasaría a
    depender de ``NULLS FIRST/LAST`` en vez de la fórmula.

    La rama ``horizonte <= 0`` del port no se traduce: el único llamador
    calcula el horizonte como ``months_ahead * DIAS_POR_MES`` con
    ``months_ahead >= 1``, así que el divisor nunca es 0 ni negativo.
    """
    return (
        "CASE WHEN pr.riesgo_cambio IS NULL "
        "       OR a.importe_adjudicado IS NULL "
        "       OR a.importe_adjudicado <= 0 "
        f"      OR ({dias_restantes_expr}) IS NULL "
        "     THEN 0.0 "
        "     ELSE pr.riesgo_cambio * a.importe_adjudicado "
        "          * LEAST(1.0, GREATEST(0.0, "
        f"                 1.0 - ({dias_restantes_expr})::float / %s::float)) "
        "END"
    )


def proximas_renovaciones(
    *,
    months_ahead: int = 6,
    empresa_id: int | None = None,
    ccaa: str | None = None,
    tecnologias: list[str] | None = None,
    min_importe: float | None = None,
    order_by: OrderBy = "fecha",
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Contratos cuya fecha de fin efectiva cae en los próximos N meses.

    Cada fila es un par contrato-adjudicatario con la empresa canónica del
    maestro.

    ``order_by``:

    - ``"fecha"`` (por defecto): proximidad del vencimiento, ascendente. Es
      el orden que asume ``services/pursuits.py`` para quedarse con la fila
      más próxima a vencer de una UTE.
    - ``"score"``: score de oportunidad descendente, con el vencimiento como
      desempate. Con este orden ``limit`` recorta el **top-N real**.

    Coste: los dos órdenes son expresiones calculadas, así que ninguno se
    resuelve por índice y ambos ordenan la ventana filtrada entera antes del
    ``LIMIT``. El score no empeora eso —``fecha_fin_efectiva`` ya era una
    expresión— y a cambio el llamador puede pedir 200 filas en vez de 1000.
    """
    months_ahead = max(1, min(int(months_ahead), MAX_MESES))
    fecha_fin = fecha_fin_sql()
    sql = f"""
        SELECT a.licitacion_id,
               l.titulo,
               l.organo_contratacion,
               l.cpv,
               l.ccaa,
               l.url,
               a.empresa_id,
               COALESCE(e.nombre_canonico, a.nombre) AS empresa,
               e.es_ute,
               a.importe_adjudicado,
               a.fecha_adjudicacion,
               l.duracion_valor,
               l.duracion_unidad,
               {fecha_fin} AS fecha_fin_efectiva,
               {dias_restantes_sql(fecha_fin)} AS dias_restantes,
               pr.riesgo_cambio,
               pr.model_version AS retencion_model_version
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        LEFT JOIN empresas e ON e.empresa_id = a.empresa_id
        LEFT JOIN predicciones_retencion pr ON pr.licitacion_id = a.licitacion_id
        WHERE {fecha_fin} {rango_vencimiento_sql()}
          AND {TECHNOLOGY_OBSERVED_SQL}
          AND {exclude_duplicados_sql()}
    """
    params: list[Any] = [months_ahead]
    if empresa_id is not None:
        sql += " AND a.empresa_id = %s"
        params.append(empresa_id)
    if ccaa:
        sql += " AND l.ccaa = %s"
        params.append(ccaa)
    tecnologias = [t for t in (tecnologias or []) if t]
    if tecnologias:
        placeholders = ",".join("%s" for _ in tecnologias)
        sql += f" AND l.tecnologia IN ({placeholders})"
        params.extend(tecnologias)
    if min_importe is not None:
        sql += " AND a.importe_adjudicado >= %s"
        params.append(min_importe)
    if order_by == "score":
        # `a.id` cierra el desempate: sin él dos filas con el mismo score y el
        # mismo vencimiento pueden alternar de página en página bajo LIMIT/OFFSET.
        sql += (
            f" ORDER BY ({score_oportunidad_sql(dias_restantes_sql(fecha_fin))}) DESC,"
            " fecha_fin_efectiva ASC, a.id ASC"
        )
        # float y no int: el horizonte es el divisor de la urgencia, y mandarlo
        # ya tipado evita depender de que Postgres resuelva el cast int→float8
        # del placeholder.
        params.append(float(months_ahead * DIAS_POR_MES))
    else:
        sql += " ORDER BY fecha_fin_efectiva ASC"
    sql += " LIMIT %s OFFSET %s"
    params.extend([max(1, min(int(limit), MAX_LIMIT)), max(0, int(offset))])

    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))
