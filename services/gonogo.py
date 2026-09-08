"""Plantilla de go/no-go ponderada (C6.4, D30).

Qué resuelve
------------
Presentarse o no es la decisión más cara del proceso —preparar una oferta cuesta
semanas de gente— y se registraba como una etiqueta (`go` / `no_go`) más un
párrafo de texto libre. Con eso no se puede responder «¿en qué nos equivocamos al
decidir?», porque no consta contra qué se decidió.

Cinco criterios, de uno a cinco
-------------------------------
Encaje estratégico, capacidad, competencia, rentabilidad y riesgo. Cerrados a
propósito: un formulario que cada equipo amplía a su gusto deja de poder
compararse consigo mismo el trimestre siguiente, que es para lo único que sirve
puntuar.

``riesgo`` se puntúa **al derecho**, como los demás: 5 es «poco riesgo». Invertir
uno solo de los cinco es la forma más rápida de que alguien rellene el formulario
al revés sin darse cuenta.

Los pesos y el umbral
---------------------
Viven en `organizations.settings_json`, son de owner/admin y quedan auditados.
Los de fábrica reparten 100 puntos entre los cinco con dos acentos deliberados:
encaje estratégico y rentabilidad pesan más porque son los que más veces
explican una derrota conocida. Cualquier equipo puede cambiarlos; lo que no puede
es dejarlos sin sumar 100, porque entonces el total dejaría de ser comparable
entre organizaciones y consigo mismo.
"""

from __future__ import annotations

from typing import Any

#: Los cinco criterios de D30, en el orden en que se presentan.
CRITERIOS: tuple[str, ...] = (
    "encaje_estrategico",
    "capacidad",
    "competencia",
    "rentabilidad",
    "riesgo",
)

#: Pesos de fábrica. Suman 100.
PESOS_POR_DEFECTO: dict[str, int] = {
    "encaje_estrategico": 25,
    "capacidad": 20,
    "competencia": 15,
    "rentabilidad": 25,
    "riesgo": 15,
}

#: Umbral por defecto sobre 100. Un `go` por debajo no se bloquea —la decisión
#: es de las personas— pero **se cuenta**: es la métrica que C6.4 pide en
#: `make product-status`, y su valor está en verla, no en impedirla.
UMBRAL_POR_DEFECTO = 60.0

#: Clave dentro de `settings_json`.
CLAVE_AJUSTES = "gonogo"

PUNTUACION_MIN = 1
PUNTUACION_MAX = 5

#: Quién puede cambiar la plantilla. Decide contra qué se juzgan las
#: oportunidades del equipo entero.
ROLES_QUE_EDITAN = frozenset({"owner", "admin"})


class GoNoGoError(ValueError):
    """Pesos o puntuaciones fuera de contrato."""


def validar_pesos(pesos: dict[str, Any]) -> dict[str, int]:
    """Normaliza y valida los pesos de una organización.

    Exige los cinco criterios, enteros no negativos, y que sumen exactamente
    100. La suma no es una manía: sin ella el total deja de ser «sobre 100» y
    dos organizaciones —o la misma antes y después de un cambio— dejan de poder
    compararse, que es justo lo que este número existe para permitir.
    """
    faltan = [c for c in CRITERIOS if c not in pesos]
    if faltan:
        raise GoNoGoError(f"Faltan pesos para: {', '.join(faltan)}.")
    sobran = [c for c in pesos if c not in CRITERIOS]
    if sobran:
        raise GoNoGoError(f"Criterios desconocidos: {', '.join(sobran)}.")
    limpios: dict[str, int] = {}
    for criterio in CRITERIOS:
        valor = pesos[criterio]
        if not isinstance(valor, int) or isinstance(valor, bool) or valor < 0:
            raise GoNoGoError(f"El peso de '{criterio}' debe ser un entero >= 0.")
        limpios[criterio] = valor
    if sum(limpios.values()) != 100:
        raise GoNoGoError(f"Los pesos deben sumar 100 (suman {sum(limpios.values())}).")
    return limpios


def validar_puntuaciones(puntuaciones: dict[str, Any]) -> dict[str, int]:
    """Los cinco criterios, cada uno de 1 a 5.

    No se admite puntuar sólo tres: media plantilla rellenada produce un total
    que parece comparable y no lo es.
    """
    faltan = [c for c in CRITERIOS if c not in puntuaciones]
    if faltan:
        raise GoNoGoError(f"Faltan puntuaciones para: {', '.join(faltan)}.")
    sobran = [c for c in puntuaciones if c not in CRITERIOS]
    if sobran:
        raise GoNoGoError(f"Criterios desconocidos: {', '.join(sobran)}.")
    limpias: dict[str, int] = {}
    for criterio in CRITERIOS:
        valor = puntuaciones[criterio]
        if not isinstance(valor, int) or isinstance(valor, bool):
            raise GoNoGoError(f"La puntuación de '{criterio}' debe ser un entero.")
        if not PUNTUACION_MIN <= valor <= PUNTUACION_MAX:
            raise GoNoGoError(
                f"La puntuación de '{criterio}' debe estar entre "
                f"{PUNTUACION_MIN} y {PUNTUACION_MAX}."
            )
        limpias[criterio] = valor
    return limpias


def total_ponderado(puntuaciones: dict[str, int], pesos: dict[str, int]) -> float:
    """Total sobre 100, redondeado a dos decimales.

    Una puntuación de 5 en todo da 100; una de 1 en todo da 20, no 0 — el mínimo
    de la escala es 1, y presentar «0 sobre 100» a quien puso todo unos sería
    decirle que no puntuó.
    """
    return round(
        sum(pesos[c] * puntuaciones[c] for c in CRITERIOS) / PUNTUACION_MAX,
        2,
    )


def ajustes_de(settings: dict[str, Any]) -> tuple[dict[str, int], float]:
    """``(pesos, umbral)`` de la organización, con los de fábrica como respaldo.

    Un `settings_json` corrupto o a medias no puede dejar sin plantilla al
    equipo: se cae a los valores de fábrica, que son válidos por construcción.
    """
    crudo = settings.get(CLAVE_AJUSTES) if isinstance(settings, dict) else None
    if not isinstance(crudo, dict):
        return dict(PESOS_POR_DEFECTO), UMBRAL_POR_DEFECTO
    try:
        pesos = validar_pesos(dict(crudo.get("pesos") or {}))
    except GoNoGoError:
        pesos = dict(PESOS_POR_DEFECTO)
    umbral = crudo.get("umbral")
    if not isinstance(umbral, int | float) or isinstance(umbral, bool):
        return pesos, UMBRAL_POR_DEFECTO
    return pesos, float(max(0.0, min(float(umbral), 100.0)))


# ── Operaciones de servicio ─────────────────────────────────────────────────


def leer_ajustes(user_id: int, organization_id: int | None = None) -> tuple[dict[str, int], float]:
    """Pesos y umbral de la organización activa."""
    from db.repositories.organizations import OrganizationRepository
    from services.organizations import resolve_organization

    resolved_id, _role = resolve_organization(user_id, organization_id)
    return ajustes_de(OrganizationRepository().get_settings(resolved_id))


def guardar_ajustes(
    user_id: int,
    pesos: dict[str, Any],
    umbral: float,
    *,
    organization_id: int | None = None,
) -> tuple[dict[str, int], float]:
    """Cambia la plantilla de la organización. Sólo owner/admin, y queda auditado.

    La plantilla decide contra qué se juzgan las oportunidades del equipo
    entero: quien la toca está cambiando el criterio de todos, y por eso el
    cambio deja rastro con el valor anterior y el nuevo.
    """
    from db.audit import log_event
    from db.repositories.organizations import OrganizationRepository
    from services.organizations import OrganizationPermissionError, resolve_organization

    resolved_id, role = resolve_organization(user_id, organization_id, write=True)
    if role not in ROLES_QUE_EDITAN:
        raise OrganizationPermissionError(
            "Sólo owner o admin pueden cambiar la plantilla de go/no-go."
        )
    limpios = validar_pesos(dict(pesos))
    if not 0 <= umbral <= 100:
        raise GoNoGoError("El umbral debe estar entre 0 y 100.")

    repo = OrganizationRepository()
    anteriores = ajustes_de(repo.get_settings(resolved_id))
    repo.update_settings(resolved_id, {CLAVE_AJUSTES: {"pesos": limpios, "umbral": float(umbral)}})
    log_event(
        event_type="organization.gonogo_updated",
        user_key=f"user:{user_id}",
        resource=f"organization:{resolved_id}",
        detail={
            "antes": {"pesos": anteriores[0], "umbral": anteriores[1]},
            "despues": {"pesos": limpios, "umbral": float(umbral)},
        },
    )
    return limpios, float(umbral)


def puntuar(
    user_id: int,
    pursuit_id: int,
    puntuaciones: dict[str, Any],
    *,
    organization_id: int | None = None,
) -> dict[str, Any]:
    """Puntúa un expediente con la plantilla vigente de la organización.

    El total se calcula **ahora** y se guarda: los pesos cambian, y recalcularlo
    al leer haría que cambiar un peso reescribiera decisiones ya tomadas.
    """
    import json

    from db.database import now_utc_iso
    from db.repositories.organizations import OrganizationRepository
    from db.repositories.pursuits import PursuitRepository
    from services.organizations import resolve_organization
    from services.pursuits import PursuitNotFoundError

    resolved_id, _role = resolve_organization(user_id, organization_id, write=True)
    limpias = validar_puntuaciones(dict(puntuaciones))
    pesos, umbral = ajustes_de(OrganizationRepository().get_settings(resolved_id))
    total = total_ponderado(limpias, pesos)
    guardado = PursuitRepository().guardar_gonogo(
        resolved_id,
        pursuit_id,
        puntuaciones_json=json.dumps(limpias, ensure_ascii=False),
        total=total,
        ahora=now_utc_iso(),
    )
    if not guardado:
        raise PursuitNotFoundError(f"La oportunidad {pursuit_id} no existe en este espacio.")
    return {
        "pursuit_id": pursuit_id,
        "puntuaciones": limpias,
        "total": total,
        "umbral": umbral,
        "bajo_umbral": total < umbral,
    }
