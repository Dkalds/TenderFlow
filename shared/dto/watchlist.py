"""Watchlist, favoritos y seguimientos (``follows``, ADR-031)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shared.dto.primitivas import PgDateTime

# ── Watchlist (F1) ──────────────────────────────────────────────────────────


class WatchlistRuleMatch(BaseModel):
    """Licitación que coincide con una regla (proyección de matches)."""

    id_externo: str
    titulo: str | None
    organo_contratacion: str | None
    importe: float | None
    cpv: str | None
    ccaa: str | None
    estado: str | None
    fecha_publicacion: str | None
    url: str | None


class WatchlistRuleMatchesResult(BaseModel):
    """Matches de una regla + conteo total sin recortar por ``limit``."""

    items: list[WatchlistRuleMatch]
    total: int


class WatchlistFavoriteItem(BaseModel):
    """Favorito del usuario enriquecido con la licitación (LEFT JOIN)."""

    id: int
    id_externo: str
    created_at: PgDateTime | None
    organization_id: int | None
    visibility: str | None
    # Nota **personal** del favorito (C6.6). Aunque el favorito sea visible para
    # toda la organización, la nota no: cada persona tiene su propia fila, así
    # que aquí solo llega la de quien pregunta.
    nota: str | None = None
    titulo: str | None
    importe: float | None
    estado: str | None
    fecha_publicacion: str | None


class WatchlistFavoritesResult(BaseModel):
    """Listado de favoritos del usuario."""

    items: list[WatchlistFavoriteItem]


class WatchlistFavoriteCreated(BaseModel):
    """Registro devuelto al crear (idempotente) un favorito."""

    id: int
    user_key: str
    user_id: int | None
    id_externo: str
    organization_id: int | None
    visibility: str | None
    created_at: PgDateTime | None


class FollowItem(BaseModel):
    """Un seguimiento de la tabla unificada (`follows`, ADR-031).

    `target_id` es texto aunque el objetivo sea un entero (una empresa, un
    órgano): el tipo es polimórfico y por eso ni lleva clave foránea ni puede
    tener un tipo más estrecho (ADR-031 §Riesgo).
    """

    id: int
    user_key: str
    user_id: int | None = None
    organization_id: int | None = None
    target_type: str
    target_id: str
    kind: str
    visibility: str
    # Caducidad de un descarte pospuesto («recuérdamelo en una semana»). `None`
    # es para siempre, que es lo que vale para todo lo que no sea un descarte.
    hasta: PgDateTime | None = None
    # Vocabulario pendiente de C2.7 (ver v130): hoy siempre `None`. Viaja en el
    # contrato desde el principio para que añadirlo no sea un cambio de forma.
    channels: dict[str, Any] | None = None
    created_at: PgDateTime | None = None


class FollowsResult(BaseModel):
    """Listado de seguimientos, con el total por si la interfaz pagina."""

    items: list[FollowItem]
    total: int


class WatchlistEntry(BaseModel):
    """Entrada de la watchlist de un usuario.

    Contrato compartido entre `services/watchlist.py`, `api/routes/watchlist_feed.py`
    y las vistas de watchlist de la aplicación.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    user_id: str
    licitacion_id: str
    note: str | None = Field(default=None, max_length=2000)
    pinned: bool = False
    created_at: PgDateTime | None = None
    updated_at: PgDateTime | None = None


# ── ANCLA S4 — eventos, webhooks y reglas de watchlist ─────────────────────
#
# S4 no aterriza ningún modelo aquí, y es deliberado: el criterio de este
# módulo es la COMPARTICIÓN entre rutas (ver el docstring), y ninguno de los
# tipos que S4 introduce la tiene.
#
# - ``WebhookOut``, ``WebhookCreate``, ``WebhookUpdate``, ``WebhookDelivery``,
#   ``WebhookPingResult``, ``WebhookEventTypes`` y ``WebhookSecretRotated`` los
#   sirve una sola ruta (``api/routes/webhooks.py``) y ya vivían junto a ella.
# - Los seis criterios nuevos de la regla (`tecnologia`, `organo`,
#   `procedimiento`, `tipo_contrato`, `banda_min`, `plazo_min_dias`) son campos
#   aditivos de ``WatchlistRuleBody``, que es de ``api/routes/watchlist_rules.py``.
#   ``WatchlistRuleMatch``/``WatchlistRuleMatchesResult`` ya estaban aquí porque
#   los comparten dos rutas, y no cambian de forma.
# - El catálogo de eventos y sus plantillas NO son DTOs de HTTP: son el
#   vocabulario del backbone y viven en ``shared/events.py``, que además tiene
#   que poder importarse desde el scheduler sin arrastrar FastAPI.
#
# Traerlos aquí no los haría más públicos, sólo los alejaría de lo que
# describen — y añadiría nombres al esquema OpenAPI que ninguna ruta alcanza.
