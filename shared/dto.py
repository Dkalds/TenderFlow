"""Tipos Pydantic v2 compartidos por MÁS DE UNA ruta de la API.

Eso es lo que este módulo es. **No** es «el contrato público del sistema»: el
contrato lo define el esquema OpenAPI que genera FastAPI a partir de todos los
modelos de respuesta, y la mayoría de ellos vive junto a su ruta en
``api/routes/*`` (unos 116 de los ~304 ``BaseModel`` del repo) o junto a su
función de dominio en ``services/analytics/*``. Decir aquí que este fichero era
el contrato invitaba a dos errores opuestos: creer que basta con leerlo para
conocer la API, y creer que cualquier DTO nuevo tiene que aterrizar aquí.

**El criterio para que un modelo viva en este módulo es la compartición**: lo
usan dos o más rutas (``PaginatedResponse``, ``StatusOk``, ``CreatedId``…), o
es una primitiva del contrato que no pertenece a ningún recurso concreto
(``SafeStr``, ``PgDateTime``, ``MAX_PAGE_LIMIT``). Un modelo de una sola ruta
se queda en su ruta: traerlo aquí no lo hace más público, solo lo aleja de lo
que describe.

**Y no puede haber dos modelos con el mismo nombre en el esquema.** Si los hay,
FastAPI los desambigua con un prefijo de módulo y eso reescribe en bloque
``components["schemas"]`` de ``web/src/generated/api.d.ts``, rompiendo el
frontend que lo referencia. Este módulo llegó a tener tres colisiones vivas
—``LicitacionSummary``, ``LicitacionDetail`` y ``AdjudicacionSummary``
existían aquí *y* en ``api/routes/licitaciones.py``, con tipos distintos— que
no explotaron por un pelo: las de aquí no las alcanzaba ninguna ruta, así que
nunca llegaron al esquema. Se borraron el 2026-09-03, junto con
``ClusterSummary`` y ``KpiSnapshotDTO``, que tampoco tenían llamadores.

Uso::

    from shared.dto import PaginatedResponse, SafeStr, StatusOk
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

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


# ── Superficie pública indexable ──────────────────────────────────────────
#
# Estos modelos son deliberadamente **nuevos** y no heredan de
# `LicitacionSummary`/`LicitacionDetail`. Dos motivos, los dos aprendidos por
# las malas:
#
# 1. **Fuga por herencia.** El `LicitacionSummary` de
#    `api/routes/licitaciones.py` lleva `tecnologia`, `ml_tecnologias`,
#    `ml_proba_max` y `ml_tech_principal`. Heredar de él publicaría la
#    analítica propia el primer día, con la petición devolviendo 200 y sin que
#    nada fallara. La proyección pública se construye por allowlist explícita:
#    un campo nuevo aguas arriba no aparece aquí solo por añadirse.
# 2. **Colisión de nombres en el OpenAPI.** Dos modelos distintos con el mismo
#    nombre hacen que FastAPI los renombre con prefijo de módulo, y eso
#    reescribe `components["schemas"]` en `web/src/generated/api.d.ts`,
#    rompiendo en cascada el frontend que lo referencia. De ahí el sufijo
#    `Publica`. (Este módulo tuvo tres homónimos de `api/routes/licitaciones.py`
#    hasta 2026-09-03; se borraron porque además estaban muertos.)
#
# Lo que NO está aquí y no debe añadirse: `ml_proba`, `ml_proba_max`,
# `ml_tecnologias`, `ml_tech_principal`, `tecnologia`, `raw_keywords`,
# `filter_version`, `classifier_model_version`, `inclusion_reason`,
# `analysis_universe` y `peso_precio_pct`. Todo eso es pipeline propio.
# Tampoco nada de `adjudicaciones`: el adjudicatario puede ser una persona
# física y no hay lógica en el repositorio que lo distinga.
# `scripts/check_public_surface.py` (que CI corre con `--strict`) NO escanea
# este fichero: vigila `api/routes/publico*.py` y la proyección por allowlist de
# `db/repositories/publico.py`, que son las dos puertas por las que un campo
# llegaría hasta aquí. Esta lista, por tanto, se sostiene por revisión; el guard
# cubre el camino, no el DTO.


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


# ── Contrato de paginación común ───────────────────────────────────────────
#
# Los dos envelopes de abajo nacieron dentro de `api/routes/licitaciones.py` y
# vivían allí, en 1 de los 30 módulos de rutas: cada consumidor del cliente TS
# aprendía una forma distinta de paginar. Se mueven aquí —el módulo que ya es
# el contrato API↔web— para que las siguientes olas de rutas los reutilicen en
# vez de reinventar la forma.
#
# Conservan **el nombre exacto** que tenían en la ruta a propósito: FastAPI
# deriva de él el componente OpenAPI
# (`PaginatedResponse_LicitacionSummary_`, con el `LicitacionSummary` de la
# ruta,
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

#: Motivos de pérdida (D37). **Lista cerrada**, y ésa es la decisión: una lista
#: abierta no se puede agregar, y la pregunta que abre esta función —«¿por qué
#: perdemos en el CPV 72?»— sólo tiene respuesta si los motivos se pueden
#: contar. El matiz sigue viajando en `outcome_reason`, que es texto libre y no
#: se toca.
#:
#: `sin_codificar` **no** está aquí: no es un motivo que alguien elija, es la
#: ausencia de código de los cierres anteriores a v104. Se representa con la
#: columna a NULL para que no se confunda con un `otro` deliberado, que es una
#: respuesta distinta y mucho más informativa.
PursuitOutcomeReasonCode = Literal[
    "precio",
    "tecnica",
    "solvencia",
    "plazo",
    "desierto_o_anulado",
    "no_presentada",
    "otro",
]


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


#: Probabilidad por defecto de cada etapa del embudo, en porcentaje (D34).
#:
#: **Son supuestos, no medidas**, y así se declaran en la respuesta: hasta que
#: F3.1 acumule cierres no hay histórico con el que calibrarlos. Owner y admin
#: los editan. Se eligen crecientes y sin llegar al 100 % porque una
#: oportunidad presentada sigue pudiendo perderse; poner `submitted` al 100 %
#: convertiría el valor ponderado en la suma del pipeline, que es el número
#: que este campo existe para dejar de publicar.
PROBABILIDADES_ETAPA_DEFAULT: dict[str, int] = {
    "identified": 10,
    "qualifying": 20,
    "go_no_go": 30,
    "preparing": 50,
    "submitted": 60,
}


class OrganizationSettings(BaseModel):
    """Configuración de producto de una organización (``organizations.settings_json``).

    ``tecnologias`` son las familias del diccionario (``SAP``, ``MICROSOFT``…)
    que vende la organización. Vacío significa «todas»: el Radar puntúa el
    universo entero, como hasta 2026-09. Con familias declaradas, el Radar
    acota su universo a ellas cuando el usuario no filtra por tecnología a
    mano, y la ingesta no cambia —el filtro es una vista sobre el corpus, no
    una pérdida de datos.

    **Ámbito de mercado (F6.1).** El resto de campos de ámbito —CPVs, CCAAs,
    rango de importe, tipos de órgano y procedimientos excluidos— vivían sólo
    en el perfil **personal** (``api/routes/me.py``), así que cada miembro
    tenía que reconfigurar a mano lo que la organización entera comparte, y
    quien no lo hacía veía el mercado sin acotar. Aquí son de la organización,
    y la precedencia es explícita: **perfil personal → organización → global**.
    En todos, la lista vacía significa «sin restricción», nunca «ninguno»: un
    ámbito que se interpretara al revés vaciaría el Radar en silencio el día
    que alguien guardara la configuración sin tocar un campo.

    No hay migración: ``organizations.settings_json`` es JSON y admite claves
    nuevas. La que D39 pre-autorizaba no hace falta.
    """

    model_config = ConfigDict(extra="forbid")

    tecnologias: list[str] = Field(default_factory=list, max_length=30)
    #: CPVs por **prefijo**, como en el filtro del listado (F1.1): `72` es
    #: «servicios de TI» entero.
    cpvs: list[str] = Field(default_factory=list, max_length=50)
    ccaas: list[str] = Field(default_factory=list, max_length=25)
    importe_min: float | None = Field(default=None, ge=0)
    importe_max: float | None = Field(default=None, ge=0)
    #: Tipos de contrato CODICE que interesan (`shared/procedimientos.py`).
    tipos_organo: list[str] = Field(default_factory=list, max_length=20)
    #: Procedimientos que la organización **no** quiere ver. Es una lista de
    #: exclusión y no de inclusión porque así es como se usa: casi nadie
    #: enumera los diez procedimientos que le valen, pero mucha gente quiere
    #: quitar los contratos menores del Radar.
    procedimientos_excluidos: list[str] = Field(default_factory=list, max_length=20)
    #: F4.1 — probabilidad por etapa para el valor ponderado del pipeline.
    #: Vacío = se usan los `PROBABILIDADES_ETAPA_DEFAULT`.
    probabilidades_etapa: dict[str, int] = Field(default_factory=dict)

    @field_validator("tecnologias")
    @classmethod
    def _normaliza_tecnologias(cls, value: list[str]) -> list[str]:
        vistas: list[str] = []
        for raw in value:
            code = str(raw).strip().upper()
            if code and code not in vistas:
                vistas.append(code)
        return vistas

    @field_validator("cpvs", "ccaas", "tipos_organo", "procedimientos_excluidos")
    @classmethod
    def _limpia_lista(cls, value: list[str]) -> list[str]:
        """Sin vacíos ni duplicados, conservando el orden en que se guardaron."""
        vistas: list[str] = []
        for raw in value:
            item = str(raw).strip()
            if item and item not in vistas:
                vistas.append(item)
        return vistas

    @field_validator("probabilidades_etapa")
    @classmethod
    def _valida_probabilidades(cls, value: dict[str, int]) -> dict[str, int]:
        """Sólo etapas conocidas y sólo porcentajes 0-100.

        Una etapa inventada se rechaza en vez de ignorarse: guardarla en
        silencio dejaría a un admin creyendo que configuró algo que no existe,
        y el valor ponderado seguiría usando el default sin decirlo.
        """
        limpio: dict[str, int] = {}
        for etapa, pct in value.items():
            if etapa not in PROBABILIDADES_ETAPA_DEFAULT:
                raise ValueError(
                    f"Etapa desconocida: {etapa}. "
                    f"Válidas: {', '.join(sorted(PROBABILIDADES_ETAPA_DEFAULT))}."
                )
            entero = int(pct)
            if not 0 <= entero <= 100:
                raise ValueError(f"La probabilidad de {etapa} debe estar entre 0 y 100.")
            limpio[etapa] = entero
        return limpio

    @model_validator(mode="after")
    def _rango_de_importe_coherente(self) -> OrganizationSettings:
        if (
            self.importe_min is not None
            and self.importe_max is not None
            and self.importe_max < self.importe_min
        ):
            raise ValueError("importe_max no puede ser menor que importe_min.")
        return self

    def probabilidad_de(self, etapa: str) -> int:
        """Probabilidad efectiva de una etapa: la configurada o el default.

        Una etapa terminal (`won`, `lost`, `withdrawn`) devuelve 0: ya no está
        en el pipeline, y contarla en el valor ponderado sería sumar dos veces
        lo ganado (que ya tiene su propio `awarded_amount_eur`).
        """
        if etapa not in PROBABILIDADES_ETAPA_DEFAULT:
            return 0
        return self.probabilidades_etapa.get(etapa, PROBABILIDADES_ETAPA_DEFAULT[etapa])


class OrganizationSettingsOut(OrganizationSettings):
    """Configuración leída, con la organización a la que pertenece."""

    organization_id: int = Field(ge=1)
    #: Familias válidas del diccionario, para que el cliente pinte el selector
    #: sin copiarse la lista a mano (invariante 3 de ``web/AGENTS.md``).
    tecnologias_disponibles: list[str] = Field(default_factory=list)
    #: F4.1 — los defaults vigentes, para que el formulario pueda enseñar «10 %
    #: (por defecto)» en vez de un hueco, y para que el cliente no lleve su
    #: propia copia de los supuestos de D34.
    probabilidades_etapa_default: dict[str, int] = Field(
        default_factory=lambda: dict(PROBABILIDADES_ETAPA_DEFAULT)
    )


# ── Cuentas objetivo y etiquetas (F1.5, F1.6) ───────────────────────────────


class CuentaObjetivo(BaseModel):
    """Un órgano que la organización sigue como cuenta.

    ``organo_id`` nace vacío: el maestro de órganos (C1.2) todavía no existe y
    la identidad va por el nombre normalizado. El campo está en el contrato
    desde ahora para que ese maestro no obligue a cambiarlo.
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    organization_id: int = Field(ge=1)
    organo_nombre: str = Field(min_length=1, max_length=500)
    organo_norm: str
    organo_id: int | None = None
    created_by_user_id: int | None = None
    created_at: str
    nota: str | None = Field(default=None, max_length=2000)


#: Qué se puede etiquetar (D38). Cerrado: cada tipo tiene su tabla y su forma
#: de clave, y añadir uno exige decidir cómo se limpia al borrar el objeto.
ObjetoEtiquetable = Literal["favorito", "oportunidad", "cuenta"]

#: Color hex de una etiqueta. Se valida la forma —no la legibilidad— porque el
#: contraste lo garantiza el componente, que pinta el texto en blanco o negro
#: según la luminancia del fondo.
_COLOR_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class Etiqueta(BaseModel):
    """Una etiqueta de la organización."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    organization_id: int = Field(ge=1)
    nombre: str = Field(min_length=1, max_length=40)
    nombre_norm: str
    color: str
    created_by_user_id: int | None = None
    created_at: str

    @field_validator("color")
    @classmethod
    def _color_hex(cls, value: str) -> str:
        if not _COLOR_HEX_RE.match(value):
            raise ValueError("El color debe ser hexadecimal de seis dígitos (#rrggbb).")
        return value.lower()


class EtiquetaAplicada(BaseModel):
    """La etiqueta tal como se pinta junto al objeto: sólo lo que se ve."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    nombre: str
    color: str


class EtiquetaCreate(BaseModel):
    """Alta de etiqueta."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nombre: str = Field(min_length=1, max_length=40)
    color: str = Field(default="#64748b")

    @field_validator("color")
    @classmethod
    def _color_hex(cls, value: str) -> str:
        if not _COLOR_HEX_RE.match(value):
            raise ValueError("El color debe ser hexadecimal de seis dígitos (#rrggbb).")
        return value.lower()


class EtiquetaAplicacion(BaseModel):
    """Aplicar o quitar una etiqueta de un objeto."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    etiqueta_id: int = Field(ge=1)
    objeto_tipo: ObjetoEtiquetable
    objeto_id: str = Field(min_length=1, max_length=120)


class CuentaObjetivoCreate(BaseModel):
    """Seguir un órgano como cuenta objetivo."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    organo: str = Field(min_length=1, max_length=500)
    nota: str | None = Field(default=None, max_length=2000)


class CalendarioEnlace(BaseModel):
    """Enlace de suscripción al calendario ICS del usuario."""

    model_config = ConfigDict(extra="forbid")

    #: Ruta relativa al origen del sitio; el cliente antepone su origen. Un
    #: cliente de calendario externo la consume tal cual.
    path: str
    #: Cuántos eventos devolvería hoy, para que la UI no ofrezca un calendario
    #: vacío sin decirlo.
    eventos: int = Field(ge=0)


class PursuitCreate(BaseModel):
    """Convierte una licitación existente en oportunidad colaborativa.

    ``score_al_abrir`` y ``banda_al_abrir`` son la puntuación que el usuario
    tenía en pantalla al comprometerse, y los manda el cliente porque el score
    no se persiste en ninguna parte: se calcula en vivo sobre el universo del día
    y los pesos del perfil, así que recalcularlo aquí daría un número distinto
    del que motivó la decisión. Sin ellos no hay forma de responder si el Radar
    prioriza bien —la promesa central del producto—, y el dato es irrecuperable
    a posteriori (revisión ``v93``).

    Opcionales: abrir la oportunidad es la acción y medir es el efecto
    secundario. Una llamada por API o un cliente antiguo siguen funcionando, y
    la fila queda con ``NULL``, que significa «no se supo».
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    licitacion_id: str = Field(min_length=1, max_length=500)
    organization_id: int | None = Field(default=None, ge=1)
    responsible_user_id: int | None = Field(default=None, ge=1)
    score_al_abrir: int | None = Field(default=None, ge=0, le=100)
    banda_al_abrir: Literal["Caliente", "Atractiva", "Tibia", "Descarte"] | None = None


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
    #: F3.1 — obligatorio al cerrar en `lost` (la ruta responde 422 sin él).
    #: Aquí es opcional porque este mismo patch sirve para editar otras cosas
    #: de una oportunidad ya cerrada sin tener que reenviar el motivo.
    outcome_reason_code: PursuitOutcomeReasonCode | None = None
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


class ExpectedAward(BaseModel):
    """F4.4 — cuándo se espera la adjudicación, y de dónde sale esa fecha.

    Viaja con su dispersión y su ``n`` a propósito: una fecha sola se lee como
    un compromiso, y esto es una estimación. La regla que decide si se publica
    —y el mínimo de expedientes por debajo del cual **no** hay estimación—
    vive en :mod:`services.analytics.lead_time`.
    """

    model_config = ConfigDict(extra="forbid")

    #: La central, no la optimista.
    fecha: date
    #: Extremos del intervalo intercuartílico. Iguales a ``fecha`` cuando el
    #: método es ``hito``: una fecha publicada no tiene dispersión.
    p25: date
    p75: date
    #: Expedientes del órgano que sostienen la estimación. Con ``metodo="hito"``
    #: es 0: el dato no viene de una muestra.
    n: int = Field(default=0, ge=0)
    #: ``estimacion`` hoy; ``hito`` cuando F2.1 traiga la fecha publicada por
    #: el procedimiento y sustituya a la estimada.
    metodo: Literal["hito", "estimacion"] = "estimacion"


class PursuitSummary(BaseModel):
    """Oportunidad enriquecida con los datos básicos de su licitación."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    organization_id: int = Field(ge=1)
    licitacion_id: str
    tender_title: str | None = None
    tender_deadline: PgDateTime | None = None
    #: Campo ADITIVO (F4.4). El órgano de la licitación, que es de donde sale
    #: `expected_award`: sin él la consola no puede explicar por qué la fecha
    #: prevista es esa ni enlazar a la cuenta.
    tender_organo: str | None = None
    #: Campo ADITIVO (F4.4). `None` = sin estimación, y la UI lo dice; nunca se
    #: rellena con una fecha de menor calidad. Ver `services/analytics/
    #: lead_time.py` para por qué el mínimo de expedientes no es negociable.
    expected_award: ExpectedAward | None = None
    responsible_user_id: int | None = None
    responsible_name: str | None = None
    status: PursuitStatus
    decision: PursuitDecision
    decision_reason: str | None = None
    offer_price_eur: float | None = Field(default=None, ge=0)
    outcome: PursuitOutcome
    awarded_amount_eur: float | None = Field(default=None, ge=0)
    outcome_reason: str | None = None
    #: `None` = cierre anterior a F3.1, sin codificar. La UI lo ofrece para
    #: completar; la analítica lo cuenta aparte y no lo reparte entre motivos.
    outcome_reason_code: PursuitOutcomeReasonCode | None = None
    next_action: str | None = None
    next_action_due: date | None = None
    identified_at: PgDateTime
    decision_at: PgDateTime | None = None
    submitted_at: PgDateTime | None = None
    closed_at: PgDateTime | None = None
    created_at: PgDateTime
    updated_at: PgDateTime
    version: int = Field(ge=1)
    # Tamaño del hilo de comentarios. Lo calcula el repositorio en la misma
    # consulta (subconsulta correlacionada, v97): el tablero pinta el contador
    # en cada tarjeta sin una llamada por oportunidad.
    comments_count: int = Field(default=0, ge=0)


class PursuitAdjudicatario(BaseModel):
    """Un adjudicatario del expediente, tal como lo publicó la fuente."""

    model_config = ConfigDict(extra="forbid")

    nombre: str
    nif: str | None = None
    importe_adjudicado: float | None = Field(default=None, ge=0)
    fecha_adjudicacion: str | None = None
    n_ofertas_recibidas: int | None = Field(default=None, ge=0)
    lote_id: int | None = None


class PursuitAdjudicacionDetectada(BaseModel):
    """La adjudicación que el sistema ya conoce de una oportunidad abierta.

    Existe para cerrar el ciclo sin teclear: hasta 2026-09 ganada, perdida e
    importe adjudicado se escribían a mano aunque la ingesta ya traía
    adjudicatario, importe y número de ofertas del mismo expediente. La ficha
    la muestra como propuesta —«este expediente se adjudicó a X por Y €»— y la
    persona confirma el resultado; el sistema no decide por ella quién ganó
    porque no conoce el NIF de la organización.
    """

    model_config = ConfigDict(extra="forbid")

    estado_licitacion: str | None = None
    adjudicatarios: list[PursuitAdjudicatario] = Field(default_factory=list)
    importe_total: float | None = Field(default=None, ge=0)
    n_ofertas: int | None = Field(default=None, ge=0)
    #: ``True`` cuando el pursuit sigue abierto: es entonces cuando la ficha
    #: debe proponer el cierre. En un pursuit ya cerrado la adjudicación es
    #: contexto, no una acción pendiente.
    cierre_pendiente: bool


class PursuitDetail(PursuitSummary):
    """Detalle de una oportunidad con su ledger append-only."""

    events: list[PursuitEventOut] = Field(default_factory=list)
    #: Sólo viaja cuando la ingesta conoce una adjudicación del expediente.
    adjudicacion: PursuitAdjudicacionDetectada | None = None


class PursuitListResponse(BaseModel):
    """Listado paginado dentro de una única organización."""

    organization_id: int = Field(ge=1)
    items: list[PursuitSummary] = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)


# ── Comentarios de una oportunidad ──────────────────────────────────────────
#
# El hilo de conversación del equipo sobre un expediente. Tabla propia
# (``pursuit_comments``, v97) y no entradas del ledger ``pursuit_events``: el
# ledger es append-only por trigger (v61) y un comentario tiene que poder
# borrarse; además, mezclar conversación con auditoría convierte el historial
# de decisiones en ruido.

#: Longitud máxima de un comentario. La migración v97 lo fija también como
#: CHECK en la tabla, así que cambiarlo aquí exige una revisión nueva.
PURSUIT_COMMENT_MAX_CHARS = 4000


class PursuitCommentCreate(BaseModel):
    """Nuevo comentario en el hilo de una oportunidad."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    body: SafeStr = Field(min_length=1, max_length=PURSUIT_COMMENT_MAX_CHARS)


class PursuitCommentOut(BaseModel):
    """Comentario con el autor resuelto y el permiso de borrado de quien lo pide.

    ``can_delete`` se calcula en backend (autor, o owner/admin del espacio):
    así el frontend no duplica la regla de moderación ni necesita conocer el
    rol del solicitante. ``author_user_id`` queda ``NULL`` cuando la cuenta se
    anonimiza (RGPD); el texto sigue siendo parte del trabajo del equipo.
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    pursuit_id: int = Field(ge=1)
    organization_id: int = Field(ge=1)
    author_user_id: int | None = None
    author_name: str | None = None
    body: str
    created_at: PgDateTime
    can_delete: bool = False


class PursuitCommentListResponse(BaseModel):
    """Página del hilo, en orden cronológico y paginada desde el más reciente.

    ``offset=0`` son los últimos ``limit`` comentarios —lo que un chat abre—,
    devueltos del más antiguo al más nuevo. ``total`` declara el tamaño real
    del hilo para que el cliente diga cuánto no está mostrando (ADR-014).
    """

    pursuit_id: int = Field(ge=1)
    organization_id: int = Field(ge=1)
    items: list[PursuitCommentOut] = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


class PerdidaPorMotivo(BaseModel):
    """Cuántas veces se perdió por un motivo, y qué parte del total es."""

    model_config = ConfigDict(extra="forbid")

    #: Uno de `PursuitOutcomeReasonCode`, o `sin_codificar` para los cierres
    #: anteriores a F3.1.
    motivo: str
    n: int = Field(ge=0)
    #: Sobre el total de pérdidas del periodo, 0-1.
    pct: float = Field(ge=0, le=1)


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
    #: Campo ADITIVO (F3.1). Vacío cuando no hay cierres suficientes: la UI
    #: sólo lo pinta con al menos cinco pérdidas en el corte, porque un
    #: «60 % por precio» sobre tres casos es ruido con aspecto de conclusión.
    perdidas_por_motivo: list[PerdidaPorMotivo] = Field(default_factory=list)
    #: Mínimo aplicado, declarado en vez de repetido en la UI.
    perdidas_n_minimo: int = Field(default=5, ge=1)
    #: Campo ADITIVO (F4.1). Suma de importes por la probabilidad de su etapa.
    #: Sólo cuenta oportunidades **abiertas**: una ganada ya está en
    #: `awarded_amount_eur` y sumarla aquí la contaría dos veces.
    pipeline_value_eur: float = Field(default=0, ge=0)
    #: Los supuestos con los que se calculó, declarados con el número (ADR-014).
    #: Sin esto, «1,2 M€ de pipeline» es una cifra que nadie puede reproducir.
    probabilidades_etapa_usadas: dict[str, int] = Field(default_factory=dict)
    #: Previsión por trimestre, `{"2026-Q4": 340000.0}`, repartiendo el valor
    #: ponderado por la fecha prevista de adjudicación o, si no la hay, por la
    #: fecha límite. Vacío cuando ninguna oportunidad abierta tiene fecha.
    prevision_trimestral: dict[str, float] = Field(default_factory=dict)
    #: Oportunidades abiertas sin importe publicado, que por tanto **no**
    #: entran en el valor ponderado. Se publica el hueco en vez de tratar el
    #: importe ausente como cero: un pipeline que ignora en silencio la mitad
    #: de su cartera es peor que uno que dice cuánta no pudo valorar.
    pipeline_sin_importe: int = Field(default=0, ge=0)


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
    #: Sólo en renovaciones: ``real`` si la fuente publicó la fecha de fin,
    #: ``estimada_*`` si se calculó con la duración. Opcional para no romper a
    #: los clientes que construyen items sin este dato.
    fecha_fin_origen: str | None = None


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
