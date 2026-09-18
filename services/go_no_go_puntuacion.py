"""Go/no-go de una oportunidad: pesos y puntuación (C6.4, D30).

Se llama `go_no_go_puntuacion` y no `go_no_go` porque ese nombre ya lo ocupa el
contraste entre la ficha del pliego y la capacidad declarada (S2.3): son dos
cosas distintas que se leen en la misma pestaña, y compartir módulo haría que
un cambio en una arrastrase a la otra.

El criterio de cálculo vive en `services/go_no_go_template.py` y el SQL en
`db/repositories/go_no_go.py`. Aquí, quién puede qué.
"""

from __future__ import annotations

from typing import Any

from db.repositories.go_no_go import GoNoGoRepository
from db.repositories.pursuits import PursuitRepository
from services import go_no_go_template as plantilla
from services.organizations import (
    OrganizationPermissionError,
    alcance_resuelto,
)
from services.pursuits import PursuitNotFoundError
from shared.audit_events import GO_NO_GO_WEIGHTS_UPDATED

_repo = GoNoGoRepository()
_pursuits = PursuitRepository()

#: Los pesos son configuración de la organización, no de una oportunidad: los
#: mueve quien responde de cómo decide el equipo.
_ROLES_PESOS = frozenset({"owner", "admin"})


def get_weights(user_id: int, *, organization_id: int | None = None) -> dict[str, Any]:
    with alcance_resuelto(user_id, organization_id) as (resolved_id, _role):
        guardados = _repo.pesos(resolved_id)
        return {
            "organization_id": resolved_id,
            "umbral": plantilla.UMBRAL_DEFECTO,
            "criterios": [
                {
                    "criterio": c,
                    "etiqueta": plantilla.ETIQUETAS[c],
                    "peso": plantilla.normalizar_pesos(guardados)[c],
                    "invertido": c == plantilla.CRITERIO_INVERTIDO,
                }
                for c in plantilla.CRITERIOS
            ],
        }


def set_weights(
    user_id: int, pesos: dict[str, float], *, organization_id: int | None = None
) -> dict[str, Any]:
    """Guarda los pesos. Solo owner/admin, y queda auditado."""
    with alcance_resuelto(user_id, organization_id, write=True) as (resolved_id, role):
        if role not in _ROLES_PESOS:
            raise OrganizationPermissionError(
                "Solo un owner o admin puede cambiar los pesos de la plantilla."
            )
        _repo.guardar_pesos(resolved_id, pesos)
        _auditar(resolved_id, user_id, pesos)
        return get_weights(user_id, organization_id=resolved_id)


def get_score(
    user_id: int, pursuit_id: int, *, organization_id: int | None = None
) -> dict[str, Any]:
    """Puntuaciones de la oportunidad más el total ponderado y su recomendación."""
    with alcance_resuelto(user_id, organization_id) as (resolved_id, _role):
        pursuit = _pursuits.get(resolved_id, pursuit_id)
        if pursuit is None:
            raise PursuitNotFoundError("Oportunidad no encontrada.")

        filas = _repo.puntuaciones(resolved_id, pursuit_id)
        puntuaciones = {str(f["criterio"]): int(f["puntuacion"]) for f in filas}
        resultado = plantilla.calcular(puntuaciones, _repo.pesos(resolved_id))
        return {
            "pursuit_id": pursuit_id,
            "organization_id": resolved_id,
            "criterios": [
                {
                    "criterio": c,
                    "etiqueta": plantilla.ETIQUETAS[c],
                    "invertido": c == plantilla.CRITERIO_INVERTIDO,
                    **next(
                        (
                            {
                                "puntuacion": int(f["puntuacion"]),
                                "motivo": f.get("motivo"),
                                "author_name": f.get("author_name"),
                            }
                            for f in filas
                            if str(f["criterio"]) == c
                        ),
                        {"puntuacion": None, "motivo": None, "author_name": None},
                    ),
                }
                for c in plantilla.CRITERIOS
            ],
            **resultado.as_dict(),
            # La decisión ya tomada, para que la UI pueda señalar la discrepancia sin
            # una segunda petición.
            "decision": pursuit.get("decision"),
            "discrepa": plantilla.discrepa(pursuit.get("decision"), resultado),
        }


def set_score(
    user_id: int,
    pursuit_id: int,
    *,
    criterio: str,
    puntuacion: int,
    motivo: str | None = None,
    organization_id: int | None = None,
) -> dict[str, Any]:
    """Puntúa un criterio. Cualquier miembro con permiso de escritura puede.

    Puntuar **no** es decidir: la plantilla informa y la decisión sigue siendo
    de quien la toma. Reservarla a owner/admin convertiría un instrumento de
    deliberación en un trámite de aprobación.
    """
    with alcance_resuelto(user_id, organization_id, write=True) as (resolved_id, _role):
        if not _repo.puntuar(
            organization_id=resolved_id,
            pursuit_id=pursuit_id,
            criterio=criterio,
            puntuacion=puntuacion,
            motivo=motivo,
            author_user_id=user_id,
        ):
            raise PursuitNotFoundError("Oportunidad no encontrada.")
        return get_score(user_id, pursuit_id, organization_id=resolved_id)


def _auditar(organization_id: int, user_id: int, pesos: dict[str, float]) -> None:
    from db.audit import log_event

    log_event(
        event_type=GO_NO_GO_WEIGHTS_UPDATED,
        actor=f"user:{user_id}",
        resource=f"organization:{organization_id}",
        detail={"pesos": {k: float(v) for k, v in pesos.items() if k in plantilla.CRITERIOS}},
    )
