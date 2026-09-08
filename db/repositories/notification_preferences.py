"""Preferencias de notificación por usuario, tipo y canal (C2.7).

Ninguna tabla ni servicio las modelaba (hecho 13 del plan complementario), y el
despachador de eventos de v2 S4.6 las necesita. Sin un sitio único, cada canal
acabaría inventando el suyo — que es como se llega a tener el mismo ajuste en
tres pantallas con tres valores distintos.

El esquema lo crea ``v118``.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

#: Vocabulario cerrado, espejo del `CHECK` de `v118`.
FRECUENCIAS = ("immediate", "daily", "off")
CANALES = ("email", "in_app", "webhook")

#: Qué se hace cuando el usuario no ha dicho nada.
#:
#: **`immediate` para in-app y `daily` para email**, y no `off`: apagar por
#: omisión es la clase de decisión que hace que nadie se entere de nada y nadie
#: sepa por qué. Un usuario que no quiere correos lo dice; uno que nunca entró
#: en Ajustes no está pidiendo silencio.
#:
#: `webhook` sí nace apagado, pero por otro motivo: mandar un evento a un
#: endpoint que el usuario no ha configurado no es una notificación, es tráfico
#: contra un sitio que no lo espera.
DEFECTOS: dict[str, str] = {
    "in_app": "immediate",
    "email": "daily",
    "webhook": "off",
}

#: Tipos de aviso sobre los que se puede expresar una preferencia.
#:
#: Es el catálogo que la pantalla de Ajustes necesita para pintar los
#: interruptores. Vive aquí, junto a los canales y los defectos, y **no** en el
#: frontend: una lista de tipos hardcodeada en la UI se queda atrás en cuanto
#: nace un aviso nuevo, y el usuario deja de poder configurarlo sin que nada
#: falle (ADR-014: nada de hardcode que el backend debe proveer).
#:
#: Cuando exista el catálogo de eventos de dominio de ADR-027
#: (`shared/events.py`, v2), esta tupla pasa a derivarse de él. Mientras tanto
#: son los avisos que el producto emite de verdad.
TIPOS: tuple[tuple[str, str], ...] = (
    ("watchlist_match", "Una licitación encaja con mi watchlist"),
    ("watchlist_rule.matched", "Una regla guardada encuentra algo"),
    ("daily_summary", "Resumen diario"),
    ("pursuit.task_due", "Vence una tarea de una oportunidad"),
    ("pursuit.mention", "Me mencionan en un comentario"),
)


def frecuencia_por_defecto(canal: str) -> str:
    """Frecuencia cuando no hay fila. Ver :data:`DEFECTOS`."""
    return DEFECTOS.get(canal, "off")


def listar(user_id: int, *, organization_id: int | None = None) -> list[dict[str, Any]]:
    """Preferencias explícitas del usuario.

    Devuelve **solo las que existen**: las que faltan valen su defecto, y
    materializarlas aquí obligaría a conocer el catálogo de tipos —que vive en
    `shared/events.py` (ADR-027)— desde la capa de persistencia.
    """
    condiciones = ["user_id = %s"]
    params: list[Any] = [user_id]
    if organization_id is not None:
        # Las globales (organization_id NULL) también aplican en esa
        # organización: son el ajuste "en todas partes" del usuario.
        condiciones.append("(organization_id = %s OR organization_id IS NULL)")
        params.append(organization_id)
    with connect_read() as c:
        return rows_to_dicts(
            c.execute(
                "SELECT user_id, organization_id, tipo, canal, frecuencia, updated_at "
                "FROM notification_preferences WHERE " + " AND ".join(condiciones) + " "
                "ORDER BY tipo, canal",
                params,
            )
        )


def resolver(user_id: int, *, tipo: str, canal: str, organization_id: int | None = None) -> str:
    """Frecuencia efectiva para un `(usuario, tipo, canal)`.

    Precedencia: la preferencia **de esa organización** gana sobre la global, y
    la global sobre el defecto. Alguien que quiere el digest diario de su
    consultora y nada de su cooperativa necesita justamente eso.
    """
    with connect_read() as c:
        fila = c.execute(
            "SELECT frecuencia FROM notification_preferences "
            "WHERE user_id = %s AND tipo = %s AND canal = %s "
            "  AND (organization_id = %s OR organization_id IS NULL) "
            # `NULLS LAST`: la fila con organización concreta gana.
            "ORDER BY organization_id NULLS LAST LIMIT 1",
            (user_id, tipo, canal, organization_id),
        ).fetchone()
    if fila and fila[0]:
        return str(fila[0])
    return frecuencia_por_defecto(canal)


def guardar(
    user_id: int,
    *,
    tipo: str,
    canal: str,
    frecuencia: str,
    organization_id: int | None = None,
) -> None:
    """Fija una preferencia. Idempotente por `(usuario, org, tipo, canal)`."""
    if frecuencia not in FRECUENCIAS:
        raise ValueError(f"frecuencia inválida: {frecuencia!r} (válidas: {FRECUENCIAS})")
    if canal not in CANALES:
        raise ValueError(f"canal inválido: {canal!r} (válidos: {CANALES})")
    ahora = now_utc_iso()
    with connect() as c:
        c.execute(
            "INSERT INTO notification_preferences "
            "(user_id, organization_id, tipo, canal, frecuencia, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (user_id, COALESCE(organization_id, 0), tipo, canal) DO UPDATE SET "
            "  frecuencia = excluded.frecuencia, updated_at = excluded.updated_at",
            (user_id, organization_id, tipo, canal, frecuencia, ahora, ahora),
        )


def borrar_de_usuario(user_id: int) -> int:
    """Borra las preferencias del usuario. Lo llama el borrado GDPR."""
    with connect() as c:
        cur = c.execute("DELETE FROM notification_preferences WHERE user_id = %s", (user_id,))
        return int(getattr(cur, "rowcount", 0) or 0)
