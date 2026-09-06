"""F4.2 (cuadro de mando) y F4.5 (actividad del equipo).

El Embudo son tres barras y cuatro cifras en 128 líneas. Con eso, un owner no
puede responder ninguna de las preguntas que se hace: dónde ganamos, dónde
perdemos y por qué, cuánto tarda el ciclo, y si el equipo está trabajando lo
que dijimos que íbamos a trabajar.

Cada tarjeta declara de qué está hecha
--------------------------------------
Universo, ventana y ``n``, siempre (ADR-014). Y **ninguna se pinta por debajo
del mínimo de su métrica**: la regla no es «avisar de que hay pocos casos»,
es no publicar el número. Un win rate del 100 % sobre dos cierres, en la
pantalla que mira dirección, es peor que un hueco — el hueco se pregunta, el
número se cree.

Permisos
--------
Solo owner y admin, y el control está **en el servicio**, no en el rail: un
`member` que teclee la URL recibe 403, no una pantalla sin enlace. Un rail sin
enlace es una sugerencia; esto es un permiso.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from observability.logging import get_logger
from services.organizations import OrganizationPermissionError, resolve_organization

log = get_logger(__name__)

__all__ = [
    "MINIMO_POR_CORTE",
    "ROLES_DIRECCION",
    "CuadroDireccion",
    "TarjetaMetrica",
    "corte_con_minimo",
]

#: Roles que pueden abrir Dirección.
ROLES_DIRECCION: frozenset[str] = frozenset({"owner", "admin"})

#: Cierres mínimos por celda de un corte (win rate por tecnología, por órgano).
#: Cinco, el mismo que F3.1 usa para los motivos de pérdida: es la misma
#: pregunta —«¿cuántos casos hacen falta para que esto signifique algo?»— y
#: dos umbrales distintos en la misma pantalla serían dos productos.
MINIMO_POR_CORTE = 5


class TarjetaMetrica(BaseModel):
    """Una cifra con todo lo que hace falta para creerla."""

    model_config = ConfigDict(extra="forbid")

    clave: str
    etiqueta: str
    #: `None` = no se publica por debajo del mínimo. La UI enseña el hueco y
    #: `nota` dice por qué; nunca un 0 ni un «—» sin explicación.
    valor: float | None = None
    #: Cifras sobre las que se calculó.
    n: int = Field(default=0, ge=0)
    #: Universo y ventana, en una frase.
    universo: str
    #: Por qué no hay valor, cuando no lo hay.
    nota: str | None = None


class CorteMetrica(BaseModel):
    """Una fila de un corte (por tecnología, por órgano)."""

    model_config = ConfigDict(extra="forbid")

    clave: str
    valor: float | None = None
    n: int = Field(ge=0)


class CuadroDireccion(BaseModel):
    """Lo que ve owner o admin en Dirección."""

    model_config = ConfigDict(extra="forbid")

    organization_id: int = Field(ge=1)
    tarjetas: list[TarjetaMetrica] = Field(default_factory=list)
    win_rate_por_tecnologia: list[CorteMetrica] = Field(default_factory=list)
    win_rate_por_organo: list[CorteMetrica] = Field(default_factory=list)
    #: Mínimo aplicado, declarado en vez de repetido en la UI.
    n_minimo: int = MINIMO_POR_CORTE


def exigir_direccion(user_id: int, organization_id: int | None) -> int:
    """Resuelve la organización y comprueba que el rol puede ver Dirección.

    Devuelve el ``organization_id`` resuelto. Lanza
    :class:`OrganizationPermissionError`, que la ruta convierte en 403 — el
    mismo error que el resto de operaciones restringidas, para que no haya dos
    formas de negar un permiso.
    """
    resuelta, rol = resolve_organization(user_id, organization_id)
    if str(rol) not in ROLES_DIRECCION:
        raise OrganizationPermissionError(
            "Dirección es para owner y admin: tu rol en esta organización no lo permite."
        )
    return resuelta


def corte_con_minimo(
    filas: list[dict[str, Any]],
    *,
    clave: str,
    ganadas: str = "won",
    perdidas: str = "lost",
    minimo: int = MINIMO_POR_CORTE,
) -> list[CorteMetrica]:
    """Win rate por ``clave``, con el mínimo aplicado **dentro**.

    El corte se devuelve con ``valor=None`` en las celdas por debajo del
    mínimo, en vez de omitirlas. Omitirlas escondería que existe un órgano con
    tres cierres, que es información: dice dónde el equipo está empezando.

    Se aplica aquí y no en la pantalla porque el mismo corte lo consumen el
    cuadro de mando, el informe semanal y el PDF, y un mínimo repartido entre
    tres consumidores es un mínimo que uno de los tres se salta.
    """
    agregados: dict[str, dict[str, int]] = {}
    for fila in filas:
        etiqueta = str(fila.get(clave) or "").strip() or "sin clasificar"
        resultado = str(fila.get("outcome") or "")
        if resultado not in (ganadas, perdidas):
            continue
        celda = agregados.setdefault(etiqueta, {"won": 0, "total": 0})
        celda["total"] += 1
        if resultado == ganadas:
            celda["won"] += 1

    cortes = [
        CorteMetrica(
            clave=etiqueta,
            n=datos["total"],
            valor=(datos["won"] / datos["total"]) if datos["total"] >= minimo else None,
        )
        for etiqueta, datos in agregados.items()
    ]
    # Por volumen y, a igualdad, alfabético: dos lecturas seguidas no pueden
    # devolver el corte en distinto orden.
    cortes.sort(key=lambda c: (-c.n, c.clave))
    return cortes


# ── F4.5: actividad de la organización ──────────────────────────────────────


class ItemActividad(BaseModel):
    """Una línea del feed del equipo."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    pursuit_id: int = Field(ge=1)
    licitacion_id: str
    titulo: str | None = None
    evento: str
    #: Nombre de quien lo hizo. `None` si el usuario se dio de baja: el ledger
    #: es inmutable pero `pursuits.responsible_user_id` se desvincula, así que
    #: un evento puede quedarse sin actor con nombre. Se dice «alguien del
    #: equipo» en vez de inventar uno.
    actor: str | None = None
    cuando: str


class FeedActividad(BaseModel):
    """Página del feed, con su cursor."""

    model_config = ConfigDict(extra="forbid")

    organization_id: int = Field(ge=1)
    items: list[ItemActividad] = Field(default_factory=list)
    #: `id` desde el que pedir la página siguiente. `None` = no hay más.
    siguiente_cursor: int | None = None
    #: `True` cuando se ocultaron los eventos de administración por rol.
    filtrado_por_rol: bool = False


def actividad_de_organizacion(
    user_id: int,
    *,
    organization_id: int | None = None,
    antes_de_id: int | None = None,
    solo_usuario: int | None = None,
    limit: int = 50,
) -> FeedActividad:
    """F4.5 — qué hizo el equipo, paginado por cursor.

    Un `member` ve el feed **sin los eventos de administración** (invitaciones,
    cambios de rol): el feed de actividad no es el sitio donde enterarse de a
    quién han cambiado de rol. Owner y admin lo ven entero.

    Sin PII de terceros: sólo el nombre de quien actuó, que es miembro de la
    misma organización y por tanto ya visible en Equipo.
    """
    from db.repositories.cuentas import ActividadRepository
    from services.organizations import resolve_organization

    resuelta, rol = resolve_organization(user_id, organization_id)
    incluir_admin = str(rol) in ROLES_DIRECCION

    filas = ActividadRepository().feed(
        resuelta,
        antes_de_id=antes_de_id,
        actor_user_id=solo_usuario,
        incluir_admin=incluir_admin,
        limit=limit,
    )
    items = [
        ItemActividad(
            id=int(f["id"]),
            pursuit_id=int(f["pursuit_id"]),
            licitacion_id=str(f["licitacion_id"]),
            titulo=f.get("titulo"),
            evento=str(f["event_type"]),
            actor=f.get("actor"),
            cuando=str(f.get("created_at") or ""),
        )
        for f in filas
    ]
    return FeedActividad(
        organization_id=resuelta,
        items=items,
        # El cursor sale de la última fila devuelta, no de `len(items)`: con
        # una página incompleta por el filtro de rol, un cursor calculado por
        # posición se saltaría eventos.
        siguiente_cursor=items[-1].id if len(items) == limit else None,
        filtrado_por_rol=not incluir_admin,
    )
