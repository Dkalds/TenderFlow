"""Pesos y puntuaciones de la plantilla go/no-go (C6.4, v123).

El criterio —qué se puntúa, cómo se pondera, cuándo recomienda ir— vive en
`services/go_no_go_template.py`. Aquí solo está el SQL.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger
from services.go_no_go_template import CRITERIOS, PUNTUACION_MAX, PUNTUACION_MIN

log = get_logger(__name__)

MAX_MOTIVO = 1000


class GoNoGoRepository:
    """Acceso a ``go_no_go_weights`` y ``go_no_go_scores``."""

    # ── Pesos (owner/admin) ──────────────────────────────────────────────

    def pesos(self, organization_id: int) -> dict[str, float]:
        """Pesos guardados. Los ausentes los rellena el servicio con el default."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT criterio, peso FROM go_no_go_weights WHERE organization_id = %s",
                (organization_id,),
            )
            return {str(f["criterio"]): float(f["peso"]) for f in rows_to_dicts(cur)}

    def guardar_pesos(self, organization_id: int, pesos: dict[str, float]) -> dict[str, float]:
        """Upsert de los pesos. Ignora criterios desconocidos.

        Se escriben uno a uno con `ON CONFLICT` en vez de borrar y reinsertar:
        un `DELETE` + `INSERT` deja una ventana en la que la organización no
        tiene pesos, y cualquier cálculo en ese instante usaría los defaults sin
        que nadie lo pidiera.
        """
        ahora = now_utc_iso()
        with connect() as c:
            for criterio, peso in pesos.items():
                if criterio not in CRITERIOS:
                    continue
                c.execute(
                    "INSERT INTO go_no_go_weights (organization_id, criterio, peso, updated_at) "
                    "VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (organization_id, criterio) DO UPDATE SET "
                    "peso = excluded.peso, updated_at = excluded.updated_at",
                    (organization_id, criterio, max(0.0, float(peso)), ahora),
                )
        return self.pesos(organization_id)

    # ── Puntuaciones (por oportunidad) ───────────────────────────────────

    def puntuaciones(self, organization_id: int, pursuit_id: int) -> list[dict[str, Any]]:
        with connect_read() as c:
            cur = c.execute(
                "SELECT s.criterio, s.puntuacion, s.motivo, s.author_user_id, "
                "u.display_name AS author_name, s.updated_at "
                "FROM go_no_go_scores s LEFT JOIN users u ON u.id = s.author_user_id "
                "WHERE s.pursuit_id = %s AND s.organization_id = %s "
                "ORDER BY s.criterio",
                (pursuit_id, organization_id),
            )
            return rows_to_dicts(cur)

    def puntuar(
        self,
        *,
        organization_id: int,
        pursuit_id: int,
        criterio: str,
        puntuacion: int,
        motivo: str | None = None,
        author_user_id: int | None = None,
    ) -> bool:
        """Puntúa un criterio. `False` si el pursuit no es de esa organización.

        Igual que en `pursuit_tasks.create`, la pertenencia se comprueba dentro
        del `INSERT ... SELECT` para no dejar ventana entre comprobar y escribir.
        """
        if criterio not in CRITERIOS:
            raise ValueError(f"criterio desconocido: {criterio}")
        if not PUNTUACION_MIN <= int(puntuacion) <= PUNTUACION_MAX:
            raise ValueError(f"puntuación fuera de rango: {puntuacion}")
        ahora = now_utc_iso()
        with connect() as c:
            cur = c.execute(
                "INSERT INTO go_no_go_scores "
                "(pursuit_id, organization_id, criterio, puntuacion, motivo, author_user_id, "
                " created_at, updated_at) "
                "SELECT p.id, p.organization_id, %s, %s, %s, %s, %s, %s "
                "FROM pursuits p WHERE p.id = %s AND p.organization_id = %s "
                "ON CONFLICT (pursuit_id, criterio) DO UPDATE SET "
                "puntuacion = excluded.puntuacion, motivo = excluded.motivo, "
                "author_user_id = excluded.author_user_id, updated_at = excluded.updated_at",
                (
                    criterio,
                    int(puntuacion),
                    (motivo or None) and motivo[:MAX_MOTIVO],
                    author_user_id,
                    ahora,
                    ahora,
                    pursuit_id,
                    organization_id,
                ),
            )
            return bool(getattr(cur, "rowcount", 0))

    def puntuaciones_por_organizacion(self, organization_id: int) -> dict[int, dict[str, int]]:
        """`{pursuit_id: {criterio: puntuacion}}` de toda la organización.

        Lo consume la métrica de producto, que necesita cruzar puntuación y
        decisión para todas las oportunidades: pedirlo oportunidad a oportunidad
        sería una consulta por fila del tablero.
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT pursuit_id, criterio, puntuacion FROM go_no_go_scores "
                "WHERE organization_id = %s",
                (organization_id,),
            )
            filas = rows_to_dicts(cur)
        salida: dict[int, dict[str, int]] = {}
        for f in filas:
            salida.setdefault(int(f["pursuit_id"]), {})[str(f["criterio"])] = int(f["puntuacion"])
        return salida
