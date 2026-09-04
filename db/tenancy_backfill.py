"""Inventario de filas sin organización (backfill de tenencia, S4.3).

Existe por el otro lado del cambio que hizo obligatoria ``organization_id`` en
los repositorios de datos de usuario: a partir de ahora nadie escribe una fila
sin ámbito, pero las que ya se escribieron siguen ahí y son **invisibles** para
la consulta con ámbito. El usuario ve desaparecer sus favoritos, sus filtros
guardados o su perfil de scoring sin que nada falle.

Este módulo solo **cuenta**. La asignación la hace
``OrganizationRepository.claim_legacy_rows``, que ya existía y adjudica las
filas huérfanas de un usuario a su organización personal (nunca a una
compartida). El consumidor de ambos es
``scripts/asignar_organizacion_huerfanos.py``.

ADR-022: el SQL vive en ``db/``. El script no abre conexiones ni escribe SQL.
"""

from __future__ import annotations

from db.database import connect_read
from observability.logging import get_logger

log = get_logger(__name__)

#: Tablas con ``organization_id`` anulable que guardan datos de usuario. Es la
#: misma lista que recorre ``OrganizationRepository.claim_legacy_rows``; si una
#: de las dos crece, la otra también.
TABLAS_CON_AMBITO: tuple[str, ...] = (
    "watchlist_items",
    "watchlist_rules",
    "watchlist_empresas",
    "watchlist_cpv",
    "saved_filters",
    "user_profiles",
    "user_notifications",
)


def contar_huerfanos() -> dict[str, int]:
    """Filas con ``organization_id IS NULL`` por tabla.

    Una tabla que todavía no existe en la base consultada cuenta como 0 en vez
    de reventar el inventario entero: el script debe poder correr contra un
    entorno a medio migrar y decir lo que sí sabe.

    Ese 0 de fallback **es indistinguible de "no hay huérfanos"**, que es
    justamente el modo de fallo que congela
    ``tests/test_swallowed_exceptions_guard.py``: el precedente es el export
    GDPR, que devolvió lista vacía durante meses porque consultaba una tabla
    inexistente detrás de un ``except Exception``. Aquí la consecuencia sería
    declarar el backfill de tenencia terminado con filas todavía huérfanas —o
    sea, con favoritos y filtros guardados invisibles para su dueño—, así que el
    handler deja constancia con el nombre de la tabla antes de rellenar el 0.
    """
    conteos: dict[str, int] = {}
    with connect_read() as c:
        for tabla in TABLAS_CON_AMBITO:
            try:
                # El nombre de tabla sale de la constante de arriba, nunca de
                # entrada de usuario: no hay forma de inyectar por aquí.
                row = c.execute(
                    f"SELECT COUNT(*) FROM {tabla} WHERE organization_id IS NULL"
                ).fetchone()
            except Exception:
                log.warning("tenancy_backfill_conteo_fallido", tabla=tabla, exc_info=True)
                conteos[tabla] = 0
                continue
            conteos[tabla] = int(row[0]) if row else 0
    return conteos


__all__ = ["TABLAS_CON_AMBITO", "contar_huerfanos"]
