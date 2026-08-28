"""Repository de conteo de matches de reglas de watchlist.

Existe por una razón muy concreta: el listado de reglas (``GET
/api/v1/watchlist/rules``) necesita un número por regla para el badge de la
tarjeta, y el conteo exacto no es pagable. Un ``SELECT COUNT(*) FROM
licitaciones WHERE titulo ILIKE '%kw%' OR descripcion ILIKE '%kw%'`` recorre
~1,6M filas de forma secuencial —``descripcion`` no tiene índice trigram— y el
listado lo hacía **una vez por regla**, cada una con su propia conexión del
pool. Con N reglas: N escaneos completos y N conexiones dentro de una sola
petición HTTP, contra un ``statement_timeout`` de 30 s.

La respuesta es acotar: se cuenta sobre un subselect con ``LIMIT``
(:data:`MATCH_COUNT_CAP`), de modo que el planner puede parar en cuanto reúne
esas filas en vez de agotar la tabla, y todas las reglas comparten **una** sola
conexión. El precio es que el número deja de ser exacto por encima del tope; la
UI lo muestra como «999+», que es toda la precisión que una tarjeta puede
aprovechar (el conteo exacto sigue disponible en el detalle de la regla).

ADR-022: el SQL vive en ``db/``. Las cláusulas del filtro las construye
``services.watchlist_rules._rule_clauses`` sobre la misma tabla de
``db.models``; aquí solo se envuelven en la forma acotada y se ejecutan.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, and_, func, literal, select

from db.database import connect_read
from db.models import compile_query, licitaciones

# Techo del conteo. 1.000 es suficiente para que el badge distinga «pocas»,
# «bastantes» y «demasiadas»; por encima, el usuario necesita afinar la regla,
# no un dígito más.
MATCH_COUNT_CAP = 1000


def _bounded_count_stmt(clauses: Sequence[Any]) -> Select[tuple[int]]:
    """``SELECT count(*) FROM (SELECT 1 FROM licitaciones WHERE … LIMIT cap)``.

    El ``LIMIT`` va dentro del subselect a propósito: puesto fuera limitaría la
    fila del resultado (siempre una) y no ahorraría ni un tuple del escaneo.
    """
    inner = select(literal(1)).select_from(licitaciones)
    if clauses:
        inner = inner.where(and_(*clauses))
    return select(func.count()).select_from(inner.limit(MATCH_COUNT_CAP).subquery())


def bounded_match_counts(clauses_per_rule: Sequence[Sequence[Any]]) -> list[int]:
    """Conteo acotado de cada regla, todas sobre la MISMA conexión.

    Devuelve una lista alineada con ``clauses_per_rule``. Cada valor está
    saturado en :data:`MATCH_COUNT_CAP`: alcanzarlo significa «al menos tantas»,
    no «exactamente tantas».
    """
    if not clauses_per_rule:
        # Un usuario sin reglas no debe llegar a pedir conexión al pool.
        return []
    counts: list[int] = []
    with connect_read() as c:
        for clauses in clauses_per_rule:
            sql, params = compile_query(_bounded_count_stmt(clauses))
            row = c.execute(sql, params).fetchone()
            counts.append(int(row[0]) if row else 0)
    return counts
