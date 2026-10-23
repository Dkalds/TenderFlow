"""Repository para csp_violations.

La escritura (``store``) es best-effort: la llama un endpoint público sin
autenticación y un fallo al guardar no puede convertirse en un 500 para el
navegador. La lectura (``listar_agrupadas``) es la de Ops > Estado: hasta
2026-10 la tabla se llenaba y ninguna ruta la leía.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, get_table_columns, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

#: Esquema y host de un ``blocked-uri`` que es una URL. Lo que no casa
#: (``inline``, ``eval``, ``data``, ``blob``) se agrupa por su valor literal.
_ORIGEN_DE_URL = "^[A-Za-z][A-Za-z0-9+.-]*://[^/?#]+"


def listar_agrupadas(*, desde: str, limit: int = 100) -> list[dict[str, Any]]:
    """Violaciones desde *desde* (ISO, inclusive), agrupadas por directiva y origen.

    El origen es el esquema y el host del ``blocked-uri`` (``https://cdn.x``),
    o el valor tal cual cuando no es una URL: agrupar por la URL entera daría
    una fila por fichero y escondería el patrón, que es «esta directiva bloquea
    este origen». ``documento`` es la página más frecuente del grupo, sin su
    query string — igual que los errores de cliente, aquí no viaja identidad.
    """
    with connect_read() as c:
        return rows_to_dicts(
            c.execute(
                "SELECT violated_directive AS directiva, "
                "       COALESCE(substring(blocked_uri FROM %s), NULLIF(blocked_uri, ''), "
                "                'sin origen') AS origen, "
                "       COUNT(*) AS ocurrencias, "
                "       MIN(created_at) AS primera_vez, MAX(created_at) AS ultima_vez, "
                # La moda sobre la página ya sin query string: con ella, dos
                # visitas a la misma página con parámetros distintos contarían
                # como dos páginas y ganaría cualquier otra con una sola.
                "       mode() WITHIN GROUP (ORDER BY split_part(document_uri, '?', 1)) "
                "         AS documento "
                "FROM csp_violations WHERE created_at >= %s "
                "GROUP BY 1, 2 ORDER BY ocurrencias DESC, ultima_vez DESC LIMIT %s",
                (_ORIGEN_DE_URL, desde, limit),
            )
        )


class CspViolationRepository:
    """Acceso a la tabla ``csp_violations``."""

    def store(
        self,
        *,
        blocked_uri: str,
        violated_directive: str,
        document_uri: str,
        source_file: str,
    ) -> None:
        """Persiste una violación CSP (si la tabla existe)."""
        try:
            now = now_utc_iso()
            with connect() as c:
                if get_table_columns(c, "csp_violations"):
                    c.execute(
                        "INSERT INTO csp_violations "
                        "(blocked_uri, violated_directive, document_uri, source_file, created_at) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (blocked_uri, violated_directive, document_uri, source_file, now),
                    )
        except Exception as exc:
            log.debug("csp_violation_persist_failed", error=str(exc))
