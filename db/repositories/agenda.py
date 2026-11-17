"""Señales de la agenda de Mi Pipeline: matches de reglas sin triar.

Una señal es una licitación **abierta y con plazo por delante** que coincide
con una regla de watchlist del usuario y que nadie ha triado todavía: no tiene
pursuit en la organización (seguida) ni descarte en ``radar_dismissals``
(descartada). El triaje reutiliza los mismos gestos y persistencia que el
Radar — no se inventa un segundo mecanismo de descarte.

El matching **no** se replica aquí: llega como las cláusulas SA Core de
``services.watchlist_rules.predicado_de_regla``, el mismo predicado de la vista
previa y del job de alertas, y aquí se compone con lo propio de la agenda.
La copia que vivía aquí solo sabía de keyword, CPV, importe y CCAA, y con
``LIKE`` sensible a mayúsculas: una regla de solo tecnología —la alerta por
defecto— señalaba las abiertas más próximas del corpus entero.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, select

from db.database import connect_read
from db.models import compile_query, licitaciones
from db.radar_dismissals import VIGENTE_SQL
from db.repositories.base import ambito_agenda_sql, rows_to_dicts
from db.sql_fragments import ISO_MAX
from shared.estados import abierta_sql

# Techo de fecha bien formada. Sale de la misma constante que usa
# ``db.sql_fragments.iso_guard`` —aquí era un ``'3000'`` re-tecleado— y no del
# fragmento entero: el suelo de esta consulta no es ``'1900'`` sino la fecha de
# hoy, que es un filtro de negocio ("todavía se puede presentar") y no una
# guarda de formato. El CHECK de v59 valida el formato en escrituras nuevas;
# esto solo excluye legado malformado sin recurrir a un regex, que no podría
# usar el btree de la columna.
_FECHA_LIMITE_VIVA_SQL = (
    "l.fecha_limite IS NOT NULL "
    "AND l.fecha_limite >= to_char(CURRENT_DATE, 'YYYY-MM-DD') "
    f"AND l.fecha_limite < '{ISO_MAX}'"
)

_SIGNAL_COLS = (
    "l.id_externo, l.titulo, l.organo_contratacion AS organo, "
    "l.importe AS importe_eur, l.ccaa, l.tecnologia, l.fecha_limite, l.url"
)


def signal_rows(
    match_clauses: Sequence[Any],
    *,
    user_id: int,
    organization_id: int,
    tecnologias: Sequence[str] | None = None,
    ccaas: Sequence[str] | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Matches vivos y sin triar de una regla, más urgentes primero.

    Los descartes se leen por ``user_id``, la PK de ``radar_dismissals`` desde
    v135: los hechos bajo la clave de un correo anterior siguen fuera.

    ``match_clauses`` es el predicado de la regla sobre ``licitaciones``
    (``services.watchlist_rules.predicado_de_regla``); entra como subconsulta
    por ``id_externo`` porque aquí la tabla va con alias.

    ``tecnologias``/``ccaas`` son el ámbito de la agenda (OR dentro de cada
    lista, mismo criterio que los pursuits: ``ambito_agenda_sql``). La CCAA de
    la **regla** es otra cosa —forma parte del match— y se aplica aparte.
    """
    clauses = [
        abierta_sql("l.estado"),
        _FECHA_LIMITE_VIVA_SQL,
        "NOT EXISTS (SELECT 1 FROM pursuits p "
        "WHERE p.organization_id = %s AND p.licitacion_id = l.id_externo)",
        # `VIGENTE_SQL` y no la mera existencia de la fila: desde v103 un
        # descarte puede caducar (`posponer`, `silenciar`). Sin el predicado,
        # posponer siete días escondía el expediente de la Agenda para
        # siempre, y el recordatorio de vencimiento avisaba de que «ya está
        # otra vez en la bandeja» señalando a algo que la Agenda no volvía a
        # enseñar. Es el tercer lector del mismo juicio, y por eso comparte
        # la grafía con los otros dos.
        "NOT EXISTS (SELECT 1 FROM radar_dismissals rd "
        f"WHERE rd.user_id = %s AND rd.id_externo = l.id_externo AND {VIGENTE_SQL})",
    ]
    params: list[object] = [organization_id, user_id]
    if match_clauses:
        sub_sql, sub_params = compile_query(
            select(licitaciones.c.id_externo).where(and_(*match_clauses))
        )
        clauses.append(f"l.id_externo IN ({sub_sql})")
        params.extend(sub_params)
    ambito, valores = ambito_agenda_sql("l", tecnologias=tecnologias, ccaas=ccaas)
    clauses.extend(ambito)
    params.extend(valores)

    sql = (
        "SELECT "
        + _SIGNAL_COLS
        + " FROM licitaciones l WHERE "
        + " AND ".join(clauses)
        + " ORDER BY l.fecha_limite ASC, l.id_externo LIMIT %s"
    )
    with connect_read() as conn:
        return rows_to_dicts(conn.execute(sql, tuple([*params, limit])))
