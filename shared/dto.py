"""DTOs Pydantic v2 para la frontera FastAPI ↔ aplicación.

Define los modelos de datos para serialización/deserialización en la API.
Estos modelos son el contrato público del sistema.

Uso:
    from shared.dto import LicitacionSummary, AdjudicacionDetail
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, EmailStr, Field

# Postgres serializa timestamptz a texto sin los minutos del offset cuando son
# cero (p.ej. "2026-08-01 00:45:48.33444+00"), formato que el parser RFC3339
# estricto de pydantic rechaza con `datetime_from_date_parsing`. Todas las
# columnas de fecha llegan como TEXT desde repositories/*.py (ADR-016/021), así
# que cualquier `datetime` de este módulo puede recibir ese formato.
_PG_SHORT_TZ_OFFSET_RE = re.compile(
    r"^(?P<body>.*\d{2}:\d{2}:\d{2}(?:\.\d+)?)(?P<offset>[+-]\d{2})$"
)


def _normalize_pg_datetime(value: Any) -> Any:
    """Completa el offset corto de Postgres (``+00`` → ``+00:00``) antes de parsear."""
    if isinstance(value, str):
        match = _PG_SHORT_TZ_OFFSET_RE.match(value)
        if match:
            return f"{match.group('body')}{match.group('offset')}:00"
    return value


PgDateTime = Annotated[datetime, BeforeValidator(_normalize_pg_datetime)]


def _reject_nul_bytes(value: Any) -> Any:
    """Rechaza el byte NUL en cadenas antes de que llegue a Postgres.

    Postgres no admite ``\\x00`` en columnas de texto: el ``DataError`` que
    lanza escapaba como 500 desde cualquier ruta que persistiera la cadena
    (``POST /licitaciones/bulk-get`` y ``PUT /feature-flags``, congelados en
    ``KNOWN_5XX`` de ``scripts/fuzz_api_contract.py``). Basta un carácter
    enviado por cualquier cliente, así que el saneo va en el contrato, no en
    cada endpoint: como validador de Pydantic, el fallo sale como 422 con la
    ruta del campo, que es lo que un cliente puede corregir.
    """
    if isinstance(value, str) and "\x00" in value:
        raise ValueError("El texto no puede contener el byte NUL (\\x00).")
    return value


#: ``str`` que no admite el byte NUL. Úsalo en todo campo de texto que acabe
#: persistido o comparado contra Postgres.
SafeStr = Annotated[str, BeforeValidator(_reject_nul_bytes)]


class LicitacionSummary(BaseModel):
    """Resumen de una licitación (listados, búsquedas)."""

    model_config = ConfigDict(from_attributes=True)

    id_externo: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    importe: float | None = Field(default=None, ge=0)
    estado: str | None = None
    fecha_publicacion: PgDateTime | None = None
    ccaa: str | None = None
    cpv: str | None = None
    url: str | None = None
    tecnologia: str | None = None


class LicitacionDetail(LicitacionSummary):
    """Detalle completo de una licitación."""

    descripcion: str | None = None
    tipo_contrato: str | None = None
    moneda: str | None = None
    provincia: str | None = None
    duracion_valor: float | None = None
    duracion_unidad: str | None = None
    fecha_limite: PgDateTime | None = None
    fecha_inicio: PgDateTime | None = None
    fecha_fin: PgDateTime | None = None
    fecha_extraccion: PgDateTime | None = None
    nuts_code: str | None = None


# ── Superficie pública indexable ──────────────────────────────────────────
#
# Estos modelos son deliberadamente **nuevos** y no heredan de
# `LicitacionSummary`/`LicitacionDetail`. Dos motivos, los dos aprendidos por
# las malas:
#
# 1. **Fuga por herencia.** Los DTO privados llevan `tecnologia` y el de
#    `api/routes/licitaciones.py` añade `ml_tecnologias`, `ml_proba_max` y
#    `ml_tech_principal`. Heredar de cualquiera de ellos publicaría la analítica
#    propia el primer día, con la petición devolviendo 200 y sin que nada
#    fallara. La proyección pública se construye por allowlist explícita: un
#    campo nuevo aguas arriba no aparece aquí solo por añadirse.
# 2. **Colisión de nombres en el OpenAPI.** `shared.dto.LicitacionSummary` y el
#    `LicitacionSummary` local de `api/routes/licitaciones.py` son modelos
#    distintos con el mismo nombre. Si dos schemas homónimos llegan al esquema,
#    FastAPI los renombra con prefijo de módulo y eso reescribe
#    `components["schemas"]` en `web/src/generated/api.d.ts`, rompiendo en
#    cascada el frontend que lo referencia. De ahí el sufijo `Publica`.
#
# Lo que NO está aquí y no debe añadirse: `ml_proba`, `ml_proba_max`,
# `ml_tecnologias`, `ml_tech_principal`, `tecnologia`, `raw_keywords`,
# `filter_version`, `classifier_model_version`, `inclusion_reason`,
# `analysis_universe` y `peso_precio_pct`. Todo eso es pipeline propio.
# Tampoco nada de `adjudicaciones`: el adjudicatario puede ser una persona
# física y no hay lógica en el repositorio que lo distinga.
# `scripts/check_public_surface.py` lo verifica en CI.


class LotePublico(BaseModel):
    """Lote de una licitación. La tabla `lotes` no tiene campos de persona."""

    model_config = ConfigDict(from_attributes=True)

    numero: str
    titulo: str | None = None
    cpv: str | None = None
    importe: float | None = Field(default=None, ge=0)
    fecha_limite: PgDateTime | None = None


class LicitacionPublica(BaseModel):
    """Anuncio de licitación tal y como lo publica la fuente oficial.

    Todos los campos provienen del anuncio de PLACSP o TED, que ya es open data
    reutilizable. `url` y `actualizado` no son decorativos: la Ley 37/2007
    condiciona la reutilización a citar la fuente e indicar la fecha de la
    última actualización, así que ambos tienen que llegar a la página.
    """

    model_config = ConfigDict(from_attributes=True)

    #: Referencia opaca apta para URL. Ver `shared/public_ref.py`: los
    #: `id_externo` reales llevan espacios y barras y no caben en un segmento
    #: de ruta.
    ref: str
    #: Número de expediente tal cual lo publica el órgano.
    expediente: str
    titulo: str
    descripcion: str | None = None
    organo_contratacion: str | None = None
    importe: float | None = Field(default=None, ge=0)
    moneda: str | None = None
    cpv: str | None = None
    tipo_contrato: str | None = None
    estado: str | None = None
    procedimiento: str | None = None
    tramitacion: str | None = None
    fecha_publicacion: PgDateTime | None = None
    fecha_limite: PgDateTime | None = None
    fecha_inicio: PgDateTime | None = None
    fecha_fin: PgDateTime | None = None
    duracion_valor: float | None = None
    duracion_unidad: str | None = None
    provincia: str | None = None
    ccaa: str | None = None
    nuts_code: str | None = None
    #: Enlace al anuncio original: el vehículo de atribución a la fuente.
    url: str | None = None
    #: `placsp` | `ted` | ...
    fuente: str
    #: Fecha de la última actualización del dato, exigida por la Ley 37/2007.
    actualizado: PgDateTime | None = None
    lotes: list[LotePublico] = Field(default_factory=list)


class AdjudicacionSummary(BaseModel):
    """Resumen de una adjudicación."""

    model_config = ConfigDict(from_attributes=True)

    licitacion_id: str
    nombre: str | None = None
    nif: str | None = None
    importe_adjudicado: float | None = Field(default=None, ge=0)
    fecha_adjudicacion: PgDateTime | None = None
    ccaa: str | None = None


class KpiSnapshotDTO(BaseModel):
    """Snapshot de KPIs pre-computados."""

    model_config = ConfigDict(from_attributes=True)

    total_licitaciones: int = 0
    total_adjudicadas: int = 0
    importe_medio: float | None = None
    importe_total: float | None = None
    computed_at: PgDateTime | None = None


# ── Contrato de paginación común ───────────────────────────────────────────
#
# Los dos envelopes de abajo nacieron dentro de `api/routes/licitaciones.py` y
# vivían allí, en 1 de los 30 módulos de rutas: cada consumidor del cliente TS
# aprendía una forma distinta de paginar. Se mueven aquí —el módulo que ya es
# el contrato API↔web— para que las siguientes olas de rutas los reutilicen en
# vez de reinventar la forma.
#
# Conservan **el nombre exacto** que tenían en la ruta a propósito: FastAPI
# deriva de él el componente OpenAPI (`PaginatedResponse_LicitacionSummary_`,
# `CursorPaginatedResponse_LicitacionSummary_`) que `web/src/generated/api.d.ts`
# ya referencia. Rebautizarlos a `Paginated[T]` habría roto el cliente generado
# sin ganar nada: el idioma ya existía, solo estaba en el sitio equivocado.

_ItemT = TypeVar("_ItemT")

#: Tope de `limit` en los listados que adoptan este contrato de paginación. Es
#: parte del contrato (por encima el API responde 422), así que vive con los
#: DTOs y no en una ruta.
#:
#: **No es universal todavía, y decir lo contrario sería falso**: la adopción va
#: por olas y hay rutas con su propio tope heredado. La conocida es
#: ``GET /competitive/renovaciones`` (``le=1000``). Bajarla a este valor no es
#: una limpieza: es un estrechamiento del contrato público —un cliente que hoy
#: pide 800 empezaría a recibir 422—, y por eso no se hizo de paso. Lo que sí
#: dejó de tener sentido es el motivo por el que pedía 1000: desde que
#: ``order_by=score`` ordena en servidor, el front pide 200 y recibe el top-N
#: real. Unificar el tope es un cambio deliberado, con su nota de contrato.
MAX_PAGE_LIMIT = 500

#: Página por defecto cuando el endpoint no tiene un motivo para otra cosa.
DEFAULT_PAGE_LIMIT = 50


class PaginatedResponse(BaseModel, Generic[_ItemT]):
    """Página de un listado con paginación por offset.

    ``total`` vale ``-1`` cuando el endpoint se invocó con ``with_total=false``:
    la página es válida pero el conteo no se calculó (evita el ``COUNT(*)``).
    """

    total: int
    limit: int
    offset: int
    items: list[_ItemT]
    deprecation_notice: str | None = None


class CursorPaginatedResponse(BaseModel, Generic[_ItemT]):
    """Página con paginación por cursor (recomendada para datasets grandes).

    No necesita ``COUNT(*)`` ni se descuadra con inserciones concurrentes, así
    que es la forma preferida para listados que crecen.
    """

    items: list[_ItemT]
    next_cursor: str | None = None
    has_more: bool = False
    limit: int


class SearchRequest(BaseModel):
    """Request de búsqueda del investigador."""

    question: str = Field(min_length=3, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)
    only_filtered: bool = True
    allowed_ids: list[str] | None = None


# ── Envelopes genéricos del contrato (tipado de operaciones opacas) ─────────
#
# Nota de modelado (backlog «Tipar el contrato API↔web»): los campos van SIN
# default cuando la query siempre devuelve la clave (valor posiblemente None).
# Un default los marcaría opcionales en OpenAPI y obligaría al cliente a
# tratar `undefined` donde nunca ocurre.


class StatusOk(BaseModel):
    """Respuesta mínima de una mutación sin payload propio."""

    status: str


class CreatedId(BaseModel):
    """Respuesta de creación con el id asignado."""

    id: int


class TotalCount(BaseModel):
    """Conteo agregado sin items (previews, badges)."""

    total: int


class DetailMessage(BaseModel):
    """Mensaje informativo de una operación (misma clave que los errores HTTP)."""

    detail: str


class SessionsRevoked(BaseModel):
    """Resultado de revocar sesiones (logout-all, borrado de cuenta)."""

    status: str
    sessions_revoked: int


class StatusMessage(BaseModel):
    """Mutación con mensaje legible además del status."""

    status: str
    message: str


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


# ── Clustering (F1) ─────────────────────────────────────────────────────────


class ClusterSummary(BaseModel):
    """Resumen de un cluster generado por `services/clusters.py`."""

    model_config = ConfigDict(from_attributes=True)

    cluster_id: int
    label: str | None = None
    size: int = Field(ge=0)
    centroid_terms: list[str] = Field(default_factory=list)
    representative_ids: list[str] = Field(default_factory=list)
    silhouette: float | None = None
    inertia: float | None = None
    computed_at: PgDateTime | None = None


# ── Cobertura de métricas agregadas ─────────────────────────────────────────


class CoberturaMetricaDTO(BaseModel):
    """Cuántas filas sostienen realmente un porcentaje agregado.

    Un porcentaje sin denominador no es un hecho del mercado: es un hecho sobre
    qué filas traen el campo. El caso que motiva este DTO es «oferta única
    93,1 %» en la tira de salud competitiva del Resumen — el numerador cuenta
    ``n_ofertas_recibidas = 1`` y el denominador solo las filas con el campo
    informado, y la republicación masiva de PSCP no trae ese campo. Con ese
    sesgo de selección el número mide la fuente, no la competencia.

    Por eso cada porcentaje viaja con su base. Todos los campos son opcionales
    con default: añadirlos no rompe a ningún cliente del contrato, y el default
    (`base`/`cobertura_pct` desconocidas, ``suficiente=False``) es el
    conservador — quien no sabe su cobertura no puede afirmar su porcentaje.

    ``cobertura_pct`` se sirve **sin redondear a un número cómodo**: un 3,4 %
    tiene que llegar al cliente como 3,4 %, no como «bajo» ni como 0.
    """

    #: Filas con el campo informado — el denominador honesto del porcentaje.
    base: int | None = Field(default=None, ge=0)
    #: Filas del corpus consideradas (informadas o no).
    universo: int | None = Field(default=None, ge=0)
    #: ``base / universo * 100``. ``None`` = cobertura no medida, que **no** es
    #: lo mismo que cobertura cero: no autoriza a afirmar el porcentaje, pero
    #: tampoco a negarlo.
    cobertura_pct: float | None = Field(default=None, ge=0, le=100)
    #: Umbral por debajo del cual el consumidor no debe presentar la métrica
    #: como un hecho. Viaja con el dato para que el cliente no lo reinvente.
    umbral_pct: float = Field(default=50.0, ge=0, le=100)
    #: ``cobertura_pct is not None and cobertura_pct >= umbral_pct``. Lo decide
    #: el backend (ADR-014): el frontend presenta, no deriva analítica.
    suficiente: bool = False


# Competitive company dossier


class CompetitiveCompanyIdentityDTO(BaseModel):
    """Canonical identity displayed in a competitor dossier."""

    empresa_id: int = Field(ge=1)
    nombre: str
    nif: str | None = None
    es_ute: bool = False
    grupo: str | None = None


class CompetitiveCompanyTotalsDTO(BaseModel):
    """Headline activity and data-coverage metrics for the selected scope."""

    contratos: int = Field(default=0, ge=0)
    importe_total: float = Field(default=0, ge=0)
    importe_mediano: float | None = Field(default=None, ge=0)
    ofertas_medias: float | None = Field(default=None, ge=0)
    baja_media_pct: float | None = None
    pct_oferta_unica: float | None = Field(default=None, ge=0, le=100)
    cobertura_ofertas_pct: float = Field(default=0, ge=0, le=100)
    primera_adjudicacion: str | None = None
    ultima_adjudicacion: str | None = None
    organos: int = Field(default=0, ge=0)
    territorios: int = Field(default=0, ge=0)
    familias_cpv: int = Field(default=0, ge=0)


class CompetitiveCompanyBreakdownDTO(BaseModel):
    """Reusable amount/count distribution row (CPV, territory or buyer)."""

    codigo: str | None = None
    label: str
    cpv2: str | None = None
    ccaa: str | None = None
    organo: str | None = None
    contratos: int = Field(ge=0)
    importe: float = Field(ge=0)
    cuota_empresa_pct: float = Field(default=0, ge=0, le=100)
    ultima_adjudicacion: str | None = None


class CompetitiveCompanyYearDTO(BaseModel):
    """Annual activity point."""

    anio: int = Field(ge=1900, le=2200)
    contratos: int = Field(ge=0)
    importe: float = Field(ge=0)


class CompetitiveCompanyPositionDTO(BaseModel):
    """Market position inside the currently selected segment."""

    rank: int | None = Field(default=None, ge=1)
    empresas: int = Field(default=0, ge=0)
    cuota_pct: float | None = Field(default=None, ge=0, le=100)
    importe_segmento: float = Field(default=0, ge=0)


class CompetitiveCompanyComparisonDTO(BaseModel):
    """Current period compared with the immediately preceding equal period."""

    desde: str
    hasta: str
    anterior_desde: str
    anterior_hasta: str
    contratos: int = Field(default=0, ge=0)
    contratos_anterior: int = Field(default=0, ge=0)
    variacion_contratos_pct: float | None = None
    importe: float = Field(default=0, ge=0)
    importe_anterior: float = Field(default=0, ge=0)
    variacion_importe_pct: float | None = None
    importe_mediano: float | None = Field(default=None, ge=0)
    importe_mediano_anterior: float | None = Field(default=None, ge=0)


class CompetitiveCompanyConcentrationDTO(BaseModel):
    """Dependence on the most relevant public buyers."""

    organo_principal: str | None = None
    top1_contratos_pct: float = Field(default=0, ge=0, le=100)
    top1_importe_pct: float = Field(default=0, ge=0, le=100)
    top3_importe_pct: float = Field(default=0, ge=0, le=100)


class CompetitiveCompanySignalDTO(BaseModel):
    """Explainable movement or risk derived from observed awards."""

    kind: str
    tone: str = Field(pattern="^(positive|neutral|warning|negative)$")
    title: str
    detail: str


class CompetitiveCompanyScopeDTO(BaseModel):
    """Effective filters used to calculate a company dossier."""

    fecha_desde: str | None = None
    fecha_hasta: str | None = None
    cpv: str | None = None
    ccaas: list[str] = Field(default_factory=list)
    tecnologias: list[str] = Field(default_factory=list)
    importe_min: float | None = Field(default=None, ge=0)


class CompetitiveCompanyHistoryDTO(BaseModel):
    """Unfiltered company history, separate from the active analysis scope."""

    contratos: int = Field(default=0, ge=0)
    importe_total: float = Field(default=0, ge=0)
    primera_adjudicacion: str | None = None
    ultima_adjudicacion: str | None = None


class CompetitiveCompanyAwardDTO(BaseModel):
    """Award row in the paginated company history."""

    licitacion_id: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    fecha_adjudicacion: str | None = None
    cpv: str | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    presupuesto_licitacion: float | None = Field(default=None, ge=0)
    importe_adjudicado: float | None = Field(default=None, ge=0)
    baja_pct: float | None = None
    n_ofertas_recibidas: int | None = Field(default=None, ge=0)
    expediente_url: str | None = None


class CompetitiveCompanyUteParticipationDTO(BaseModel):
    """UTE en la que la empresa participa como miembro, con su actividad propia.

    Deliberadamente separado de ``totales``/``posicion_mercado``, que solo
    cuentan lo adjudicado directamente a ``empresa_id`` -- sumarlo ahí
    duplicaría el importe ya atribuido a la UTE como entidad propia en
    cuota_mercado()/concentracion_hhi(). Esto es visibilidad adicional, no
    una redefinición de la cuota de mercado.
    """

    ute_empresa_id: int = Field(ge=1)
    ute_nombre: str
    otros_miembros: list[str] = Field(default_factory=list)
    contratos: int = Field(default=0, ge=0)
    importe_total: float = Field(default=0, ge=0)


class CompetitiveCompanyProfileDTO(BaseModel):
    """Full competitor dossier used by quick and deep company views."""

    empresa: CompetitiveCompanyIdentityDTO
    scope: CompetitiveCompanyScopeDTO
    actividad_historica: CompetitiveCompanyHistoryDTO
    totales: CompetitiveCompanyTotalsDTO
    posicion_mercado: CompetitiveCompanyPositionDTO
    comparacion: CompetitiveCompanyComparisonDTO
    concentracion_clientes: CompetitiveCompanyConcentrationDTO
    por_cpv: list[CompetitiveCompanyBreakdownDTO] = Field(default_factory=list)
    por_ccaa: list[CompetitiveCompanyBreakdownDTO] = Field(default_factory=list)
    organos_principales: list[CompetitiveCompanyBreakdownDTO] = Field(default_factory=list)
    por_anio: list[CompetitiveCompanyYearDTO] = Field(default_factory=list)
    movimientos: list[CompetitiveCompanySignalDTO] = Field(default_factory=list)
    contratos_recientes: list[CompetitiveCompanyAwardDTO] = Field(default_factory=list)
    participaciones_ute: list[CompetitiveCompanyUteParticipationDTO] = Field(default_factory=list)


class CompetitiveCompanyAwardsDTO(BaseModel):
    """Paginated award history for a canonical company."""

    items: list[CompetitiveCompanyAwardDTO] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(default=0, ge=0)


# ── Organizaciones y pursuits (Fase 1 TenderFlow) ──────────────────────────

OrganizationRole = Literal["owner", "admin", "member", "viewer"]
OrganizationMembershipStatus = Literal["active", "invited", "suspended", "revoked"]
PursuitStatus = Literal[
    "identified",
    "qualifying",
    "go_no_go",
    "preparing",
    "submitted",
    "won",
    "lost",
    "withdrawn",
]
PursuitDecision = Literal["pending", "go", "no_go"]
PursuitOutcome = Literal["pending", "won", "lost", "cancelled"]


class OrganizationSummary(BaseModel):
    """Organización de trabajo visible para el usuario autenticado."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    is_personal: bool
    role: OrganizationRole
    created_at: PgDateTime


class OrganizationMembershipOut(BaseModel):
    """Membresía sin datos de autenticación ni credenciales."""

    model_config = ConfigDict(extra="forbid")

    organization_id: int = Field(ge=1)
    user_id: int = Field(ge=1)
    role: OrganizationRole
    status: OrganizationMembershipStatus
    created_at: PgDateTime
    updated_at: PgDateTime
    display_name: str | None = None
    email: str | None = None


class OrganizationCreate(BaseModel):
    """Alta de un espacio compartido."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)


class OrganizationMembershipUpsert(BaseModel):
    """Alta o cambio de rol/estado de un miembro existente."""

    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(ge=1)
    role: OrganizationRole = "member"
    status: OrganizationMembershipStatus = "active"


class OrganizationMemberInvite(BaseModel):
    """Alta de un miembro por correo; requiere una cuenta activa existente."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr
    role: Literal["admin", "member", "viewer"] = "member"


class PursuitCreate(BaseModel):
    """Convierte una licitación existente en oportunidad colaborativa."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    licitacion_id: str = Field(min_length=1, max_length=500)
    organization_id: int | None = Field(default=None, ge=1)
    responsible_user_id: int | None = Field(default=None, ge=1)


class PursuitUpdate(BaseModel):
    """Patch parcial de una oportunidad con control optimista opcional."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: PursuitStatus | None = None
    decision: PursuitDecision | None = None
    decision_reason: str | None = Field(default=None, max_length=4000)
    responsible_user_id: int | None = Field(default=None, ge=1)
    offer_price_eur: float | None = Field(default=None, ge=0)
    outcome: PursuitOutcome | None = None
    awarded_amount_eur: float | None = Field(default=None, ge=0)
    outcome_reason: str | None = Field(default=None, max_length=4000)
    next_action: str | None = Field(default=None, max_length=300)
    next_action_due: date | None = None
    expected_version: int | None = Field(default=None, ge=1)


class PursuitEventOut(BaseModel):
    """Entrada inmutable del historial de una oportunidad."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    pursuit_id: int = Field(ge=1)
    event_type: str
    actor_user_id: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: PgDateTime


class PursuitSummary(BaseModel):
    """Oportunidad enriquecida con los datos básicos de su licitación."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    organization_id: int = Field(ge=1)
    licitacion_id: str
    tender_title: str | None = None
    tender_deadline: PgDateTime | None = None
    responsible_user_id: int | None = None
    responsible_name: str | None = None
    status: PursuitStatus
    decision: PursuitDecision
    decision_reason: str | None = None
    offer_price_eur: float | None = Field(default=None, ge=0)
    outcome: PursuitOutcome
    awarded_amount_eur: float | None = Field(default=None, ge=0)
    outcome_reason: str | None = None
    next_action: str | None = None
    next_action_due: date | None = None
    identified_at: PgDateTime
    decision_at: PgDateTime | None = None
    submitted_at: PgDateTime | None = None
    closed_at: PgDateTime | None = None
    created_at: PgDateTime
    updated_at: PgDateTime
    version: int = Field(ge=1)


class PursuitDetail(PursuitSummary):
    """Detalle de una oportunidad con su ledger append-only."""

    events: list[PursuitEventOut] = Field(default_factory=list)


class PursuitListResponse(BaseModel):
    """Listado paginado dentro de una única organización."""

    organization_id: int = Field(ge=1)
    items: list[PursuitSummary] = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)


class PursuitMetrics(BaseModel):
    """Métricas reproducibles de funnel y resultado por organización/periodo."""

    organization_id: int = Field(ge=1)
    period_from: PgDateTime | None = None
    period_to: PgDateTime | None = None
    pursuits_identified: int = Field(ge=0)
    pursuits_submitted: int = Field(ge=0)
    pursuits_won: int = Field(ge=0)
    pursuits_lost: int = Field(ge=0)
    win_rate: float | None = Field(default=None, ge=0, le=1)
    awarded_amount_eur: float = Field(default=0, ge=0)
    median_decision_time_hours: float | None = Field(default=None, ge=0)


# ── Agenda de Mi Pipeline ───────────────────────────────────────────────────
#
# La agenda fusiona tres clases de compromiso en una sola cronología por
# usuario/organización. La fusión, el orden y la banda de urgencia se calculan
# en backend (ADR-014: el frontend no fabrica orden ni agregados).

AgendaItemKind = Literal["pursuit", "senal", "renovacion"]
AgendaUrgencia = Literal["vencida", "hoy", "semana", "mes", "despues", "sin_fecha"]


class PipelineAgendaItem(BaseModel):
    """Una fila de la agenda, ya clasificada por urgencia.

    Los campos específicos de cada ``kind`` son NULL en los otros dos:
    ``pursuit_*``/``status``/``next_action`` solo en pursuits, ``rule_*`` solo
    en señales, ``adjudicatario``/``riesgo_cambio`` solo en renovaciones.
    ``importe_eur`` es presupuesto de licitación (pursuit/señal) o importe
    adjudicado del contrato que vence (renovación).
    """

    model_config = ConfigDict(extra="forbid")

    kind: AgendaItemKind
    urgencia: AgendaUrgencia
    due_date: date | None
    dias_restantes: int | None
    licitacion_id: str
    titulo: str | None
    organo: str | None
    importe_eur: float | None
    ccaa: str | None
    tecnologia: str | None
    url: str | None
    pursuit_id: int | None
    status: PursuitStatus | None
    decision: PursuitDecision | None
    responsible_user_id: int | None
    responsible_name: str | None
    next_action: str | None
    next_action_due: date | None
    version: int | None
    rule_id: int | None
    rule_nombre: str | None
    adjudicatario: str | None
    riesgo_cambio: float | None


class PipelineAgendaKpis(BaseModel):
    """Franja de compromisos de la agenda, calculada sobre el scope completo."""

    vence_semana: int = Field(ge=0)
    vence_semana_importe_eur: float = Field(ge=0)
    go_no_go_pendientes: int = Field(ge=0)
    sin_proxima_accion: int = Field(ge=0)
    senales_nuevas: int = Field(ge=0)


class PipelineAgendaResponse(BaseModel):
    """Respuesta de ``GET /api/v1/pursuits/agenda``."""

    organization_id: int = Field(ge=1)
    solo_mios: bool
    items: list[PipelineAgendaItem] = Field(default_factory=list)
    kpis: PipelineAgendaKpis
    #: Nº de pursuits abiertos considerados; si se alcanzó el tope interno la
    #: agenda lo declara en vez de presentar KPIs silenciosamente bajos.
    pursuits_total: int = Field(ge=0)
    pursuits_truncados: bool
    senales_truncadas: bool
    renovaciones_horizonte_meses: int = Field(ge=1, le=60)
