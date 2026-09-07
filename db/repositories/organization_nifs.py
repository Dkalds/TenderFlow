"""Persistencia de la identidad fiscal de una organización (``organization_nifs``).

Existe desde S2.1 del plan 2026-09 v2 (decisión D11) para que el producto pueda
contestar dos preguntas que hasta ahora no sabía contestar:

1. **¿Esta adjudicación es mía?** — la cruza ``services/pursuit_awards.py`` para
   proponer ``won``/``lost`` sin cerrar la oportunidad por su cuenta.
2. **¿Quién de esta lista de competidores soy yo?** — la resuelve
   :meth:`OrganizationNifRepository.empresa_ids` enlazando el NIF con el
   ``empresa_id`` canónico del maestro, para que «contra quién» no cuente a la
   propia organización como competidora suya.

Los NIFs entran ya normalizados (``services.normalization.normalize_nif``); el
``CHECK`` de la tabla lo impone y este módulo no vuelve a normalizar: si algo
llegara sin normalizar, es mejor que falle la escritura a que se guarde una
fila que ningún cruce va a encontrar.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts

# El maestro de empresas guarda su NIF en ``empresas.nif_canonico`` con la
# misma forma (mayúsculas, sin separadores), así que el enlace es una igualdad
# y no una normalización en tiempo de consulta. ``LEFT JOIN`` porque una
# organización que aún no ha ganado nada en el corpus no está en el maestro, y
# eso no es un error: es una organización nueva.
#
# Las columnas son **exactamente** las de ``OrganizationNifOut``. En particular
# no se selecciona ``n.organization_id`` —la consulta ya filtra por él, así que
# devolverlo solo serviría para repetir el dato que el llamador acaba de pasar—
# ni la contabilidad interna de la fila (``created_by_user_id``,
# ``updated_at``): el DTO declara ``extra="forbid"`` para no publicar de más, y
# la forma de respetarlo es enumerar lo que sale, no ampliar el DTO.
_SELECT = (
    "SELECT n.id, n.nif, n.razon_social, n.principal, n.created_at, "
    "       e.empresa_id "
    "FROM organization_nifs n "
    "LEFT JOIN empresas e ON e.nif_canonico = n.nif "
    "WHERE n.organization_id = %s "
    "ORDER BY n.principal DESC, n.nif"
)


class OrganizationNifRepository:
    """Consultas de ``organization_nifs``, siempre acotadas por organización."""

    def list_for_organization(self, organization_id: int) -> list[dict[str, Any]]:
        """Los NIFs de la organización, con su ``empresa_id`` canónico si existe."""
        with connect_read() as conn:
            return rows_to_dicts(conn.execute(_SELECT, (organization_id,)))

    def nifs(self, organization_id: int) -> list[str]:
        """Solo los NIFs, para el cruce con adjudicatarios."""
        with connect_read() as conn:
            rows = conn.execute(
                "SELECT nif FROM organization_nifs WHERE organization_id = %s",
                (organization_id,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def empresa_ids(self, organization_id: int) -> list[int]:
        """``empresa_id`` canónicos de la organización en el maestro de empresas.

        Es lo que permite excluirla de su propia lista de competidores: la
        analítica competitiva agrupa por identidad canónica, no por NIF suelto.
        """
        with connect_read() as conn:
            rows = conn.execute(
                "SELECT DISTINCT e.empresa_id "
                "FROM organization_nifs n "
                "JOIN empresas e ON e.nif_canonico = n.nif "
                "WHERE n.organization_id = %s",
                (organization_id,),
            ).fetchall()
        return sorted(int(row[0]) for row in rows)

    def replace_all(
        self,
        organization_id: int,
        *,
        nifs: list[dict[str, Any]],
        actor_user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Reemplaza el conjunto completo de NIFs en una sola transacción.

        Reemplazo y no ``upsert`` fila a fila: la pantalla manda siempre la
        lista entera, y borrar lo que ya no está es justo lo que el usuario
        acaba de pedir. Todo dentro de la misma transacción para que nadie lea
        una organización sin ningún NIF a mitad de la escritura —ese estado
        intermedio haría que el cierre por NIF contestara ``lost`` a algo que
        sí es suyo.
        """
        now = now_utc_iso()
        with connect() as conn:
            conn.execute(
                "DELETE FROM organization_nifs WHERE organization_id = %s",
                (organization_id,),
            )
            for fila in nifs:
                conn.execute(
                    "INSERT INTO organization_nifs "
                    "(organization_id, nif, razon_social, principal, "
                    " created_by_user_id, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        organization_id,
                        fila["nif"],
                        fila.get("razon_social"),
                        bool(fila.get("principal")),
                        actor_user_id,
                        now,
                        now,
                    ),
                )
            return rows_to_dicts(conn.execute(_SELECT, (organization_id,)))
