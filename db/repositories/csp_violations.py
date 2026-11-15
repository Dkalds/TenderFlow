"""Repository para csp_violations."""

from __future__ import annotations

from typing import TypedDict

from db.database import connect, connect_read, get_table_columns, now_utc_iso
from db.repositories.base import rows_to_dicts, typed_rows
from observability.logging import get_logger

log = get_logger(__name__)


class CspAgrupadaRow(TypedDict):
    """Una fila de :func:`agrupadas`: las claves son los alias de su SELECT."""

    directiva: str
    origen: str
    veces: int
    primera_vez: str
    ultima_vez: str
    documento_ejemplo: str | None


def agrupadas(*, desde: str, limit: int = 50) -> list[CspAgrupadaRow]:
    """Violaciones desde *desde* (ISO 8601, como `created_at`), por directiva y origen.

    El origen es esquema y host de `blocked_uri`: la ruta y la query de cada
    recurso bloqueado separarían en cien filas lo que es un solo dominio que
    falta en la política. Los valores sin URL (`inline`, `eval`, `data`) salen
    tal cual. La directiva es su primera palabra: hay navegadores que mandan la
    directiva entera, con sus fuentes, y otros solo el nombre.

    El documento de ejemplo va sin query ni fragmento: es una página de la
    propia app y basta la ruta para reproducirlo, mientras que la query puede
    llevar el token de un enlace de un solo uso.
    """
    with connect_read() as c:
        return typed_rows(
            CspAgrupadaRow,
            rows_to_dicts(
                c.execute(
                    "SELECT directiva, origen, COUNT(*) AS veces, "
                    "       MIN(created_at) AS primera_vez, MAX(created_at) AS ultima_vez, "
                    "       NULLIF(MAX(split_part(split_part(document_uri, '?', 1), '#', 1)), '') "
                    "         AS documento_ejemplo "
                    "FROM ("
                    "  SELECT COALESCE(NULLIF(split_part(violated_directive, ' ', 1), ''), '(vacío)') "
                    "           AS directiva, "
                    "         CASE WHEN COALESCE(blocked_uri, '') = '' THEN '(vacío)' "
                    "              ELSE COALESCE("
                    "                substring(blocked_uri from '^[A-Za-z][A-Za-z0-9+.-]*://[^/?#]+'), "
                    "                substring(blocked_uri from '^[A-Za-z][A-Za-z0-9+.-]*:'), "
                    "                blocked_uri) "
                    "         END AS origen, "
                    "         document_uri, created_at "
                    "  FROM csp_violations WHERE created_at >= %s"
                    ") v "
                    "GROUP BY directiva, origen "
                    "ORDER BY veces DESC, ultima_vez DESC LIMIT %s",
                    (desde, limit),
                )
            ),
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
