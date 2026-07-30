"""Lecturas de empresas vigiladas para procesos de ingesta."""

from __future__ import annotations

from db.database import connect_read


class WatchedCompanyRepository:
    """Acceso de solo lectura a los NIF canónicos de la watchlist de empresas."""

    def list_canonical_nifs(self) -> set[str]:
        """Devuelve los NIF canónicos únicos que están vigilados por algún usuario.

        Las empresas sin NIF canónico no son seleccionables por el conector:
        la fuente PLACSP solo permite una coincidencia fiable por ese
        identificador, no por nombre.
        """
        with connect_read() as c:
            rows = c.execute(
                "SELECT DISTINCT e.nif_canonico "
                "FROM watchlist_empresas w "
                "JOIN empresas e ON e.empresa_id = w.empresa_id "
                "WHERE e.nif_canonico IS NOT NULL AND TRIM(e.nif_canonico) != ''"
            ).fetchall()
        return {str(row[0]) for row in rows}
