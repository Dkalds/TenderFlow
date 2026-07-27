"""Repository de lectura para las tablas de predicciones ML.

``predicciones_baja`` y ``predicciones_retencion`` las **escribe**
``services/ml/scoring.py`` (whitelist TID251). Este repository cubre solo las
lecturas de verificación/reporting que antes vivían como SQL inline en los
heredocs de ``.github/workflows/ml-scoring.yml``.
"""

from __future__ import annotations

from typing import Any

from db.database import connect_read

# Tablas de predicciones cuyo estado se puede consultar. Whitelist explícita:
# el nombre se interpola en el SQL, así que nunca puede venir de fuera.
_TABLAS = frozenset({"predicciones_baja", "predicciones_retencion"})


class PrediccionesRepository:
    """Lecturas de verificación sobre las tablas de predicciones."""

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
