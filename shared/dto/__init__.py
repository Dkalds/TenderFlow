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

**Un submódulo por dominio** (2026-10-25). Hasta entonces esto era un único
``shared/dto.py`` de 2.482 líneas, y cada agente que añadía un DTO tocaba el
mismo fichero: con varios en paralelo era el conflicto de merge más probable
del repo. Las «anclas por stream» del plan de arquitectura 2026-09 v2 eran el
parche para eso; el paquete las sustituye:

- ``primitivas``: ``PgDateTime`` y ``SafeStr``.
- ``publico``: la proyección pública indexable (``LicitacionPublica``).
- ``paginacion``: ``Pagina`` (``PaginatedResponse``), ``CursorPaginatedResponse`` y topes.
- ``errores``: ``Error`` (``ProblemDetail``), la forma única del error (RFC 9457).
- ``genericos``: ``StatusOk``, ``CreatedId``, ``TotalCount``…
- ``watchlist``: favoritos, reglas y seguimientos.
- ``analitica``: cobertura de métricas y dosier competitivo.
- ``organizaciones``: miembros, configuración, invitaciones y auditoría.
- ``capacidad``: NIF, documentación y solvencia de la organización.
- ``cuentas``: cuentas objetivo, etiquetas y calendario.
- ``pursuits``: oportunidades, comentarios, métricas y calidad del Radar.
- ``agenda``: la agenda de Mi Pipeline.
- ``jobs``: estado de la cola de trabajo.
- ``condiciones``: condiciones oficiales de PLACSP.
- ``filtros``: los filtros del listado de licitaciones (``FiltrosLicitacion``).

Este ``__init__`` re-exporta todo lo público, así que **se importa siempre del
paquete** (``from shared.dto import X``) y nunca del submódulo: dónde vive un
modelo es un detalle que puede volver a moverse. Un DTO nuevo va al submódulo de
su dominio (o a uno nuevo) y se añade aquí y a ``__all__``. El nombre del
componente OpenAPI sale de la clase, no del módulo, así que mover un modelo de
submódulo no cambia el contrato.

Uso::

    from shared.dto import PaginatedResponse, SafeStr, StatusOk
"""

from __future__ import annotations

from shared.dto.agenda import (
    AgendaBanda,
    AgendaContador,
    AgendaDueKind,
    AgendaItemKind,
    AgendaUrgencia,
    PipelineAgendaContadores,
    PipelineAgendaItem,
    PipelineAgendaKpis,
    PipelineAgendaResponse,
)
from shared.dto.analitica import (
    DESCRIPCION_GRANDES_EN_PLAZO,
    CoberturaMetricaDTO,
    CompetitiveCompanyAwardDTO,
    CompetitiveCompanyAwardsDTO,
    CompetitiveCompanyBreakdownDTO,
    CompetitiveCompanyComparisonDTO,
    CompetitiveCompanyConcentrationDTO,
    CompetitiveCompanyCorteDTO,
    CompetitiveCompanyHistoryDTO,
    CompetitiveCompanyIdentityDTO,
    CompetitiveCompanyPositionDTO,
    CompetitiveCompanyProfileDTO,
    CompetitiveCompanyScopeDTO,
    CompetitiveCompanySignalDTO,
    CompetitiveCompanyTotalsDTO,
    CompetitiveCompanyUteParticipationDTO,
    CompetitiveCompanyYearDTO,
)
from shared.dto.capacidad import (
    EstadoVigencia,
    OrganizationCapabilities,
    OrganizationCapabilitiesOut,
    OrganizationCapabilityField,
    OrganizationCapabilityScope,
    OrganizationCertification,
    OrganizationDocumentCategory,
    OrganizationDocumentType,
    OrganizationFacturacion,
    OrganizationNif,
    OrganizationNifOut,
    OrganizationNifsIn,
    OrganizationNifsOut,
    OrganizationReferencia,
    OrganizationTeamProfile,
    VigenciaDocumento,
)
from shared.dto.condiciones import (
    ClaseSolvenciaOficial,
    CondicionesAmbito,
    CondicionesOficiales,
    CriterioOficial,
    GarantiaOficial,
    RequisitoSolvenciaOficial,
)
from shared.dto.cuentas import (
    MAX_ORGANOS_POR_ALTA,
    AmbitoCifra,
    BloqueOportunidadesCuenta,
    BloquePublicacionesCuenta,
    BloqueVencimientosCuenta,
    CalendarioEnlace,
    CuentaObjetivo,
    CuentaObjetivoCreate,
    CuentaObjetivoUpdate,
    CuentaOrgano,
    CuentaOrganosAdd,
    CuentaResumen,
    CuentasResumen,
    Etiqueta,
    EtiquetaAplicacion,
    EtiquetaAplicada,
    EtiquetaCreate,
    FichaCuenta,
    ObjetoEtiquetable,
    OportunidadCuenta,
    OrganoCandidato,
    OrganoDeCuenta,
    PublicacionCuenta,
    VencimientoCuenta,
)
from shared.dto.errores import Error, ErrorDeValidacion, ProblemDetail
from shared.dto.filtros import FiltrosLicitacion
from shared.dto.genericos import (
    CreatedId,
    DetailMessage,
    SessionsRevoked,
    StatusMessage,
    StatusOk,
    TotalCount,
)
from shared.dto.jobs import (
    JobEstadoDTO,
    JobResultado,
)
from shared.dto.organizaciones import (
    PROBABILIDADES_ETAPA_DEFAULT,
    AuditEntryOut,
    OrganizationCreate,
    OrganizationInvitationAccept,
    OrganizationInvitationOut,
    OrganizationInvitationStatus,
    OrganizationMemberInvite,
    OrganizationMembershipOut,
    OrganizationMembershipStatus,
    OrganizationMembershipUpsert,
    OrganizationRole,
    OrganizationSettings,
    OrganizationSettingsOut,
    OrganizationSummary,
    ReportSchedule,
    ReportScheduleOut,
)
from shared.dto.paginacion import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    CursorPaginatedResponse,
    CursorPaginatedResponseWithTotal,
    Pagina,
    PaginatedResponse,
)
from shared.dto.primitivas import (
    PgDateTime,
    SafeStr,
)
from shared.dto.publico import (
    LicitacionPublica,
    LotePublico,
)
from shared.dto.pursuits import (
    PURSUIT_COMMENT_MAX_CHARS,
    ExpectedAward,
    PerdidaPorMotivo,
    PursuitAdjudicacionDetectada,
    PursuitAdjudicatario,
    PursuitCommentCreate,
    PursuitCommentListResponse,
    PursuitCommentOut,
    PursuitCreate,
    PursuitDecision,
    PursuitDetail,
    PursuitEventOut,
    PursuitListResponse,
    PursuitMetrics,
    PursuitOutcome,
    PursuitOutcomeReasonCode,
    PursuitPlazo,
    PursuitStatus,
    PursuitSummary,
    PursuitUpdate,
    RadarBanda,
    RadarBandaCalidad,
    RadarQuality,
)
from shared.dto.watchlist import (
    FollowItem,
    FollowsResult,
    WatchlistEntry,
    WatchlistFavoriteCreated,
    WatchlistFavoriteItem,
    WatchlistFavoritesResult,
    WatchlistRuleMatch,
    WatchlistRuleMatchesResult,
)

# ── ANCLA S8 — documentos: formatos, OCR y almacén de objetos ──────────────
#
# S8 no aterriza ningún modelo aquí, y es deliberado: el criterio de este
# módulo es la COMPARTICIÓN entre rutas (ver el docstring), y ninguno de los
# tipos que S8 introduce la tiene.
#
# - ``DocumentoFormatoCobertura`` (desglose de adjuntos por content-type) lo
#   sirve una sola ruta, ``GET /analytics/quality``, y vive junto a su función
#   de dominio en ``services/analytics/quality.py``, como el resto de los
#   modelos de esa familia.
# - ``EvidenceRef.ocr`` es un campo aditivo sobre un modelo que ya existía en
#   ``shared/tender_facts.py``, que es donde vive el contrato de la ficha del
#   pliego.
# - ``DocumentoPagina`` (texto de una página + si vino de OCR) es el tipo de
#   entrada del repositorio, no del contrato HTTP: vive en
#   ``db/repositories/documentos.py``.
#
# Traerlos aquí no los haría más públicos, sólo los alejaría de lo que
# describen — y añadiría nombres al esquema OpenAPI que ninguna ruta alcanza,
# que es justo lo que se limpió el 2026-09-03.

__all__ = [
    "DEFAULT_PAGE_LIMIT",
    "DESCRIPCION_GRANDES_EN_PLAZO",
    "MAX_ORGANOS_POR_ALTA",
    "MAX_PAGE_LIMIT",
    "PROBABILIDADES_ETAPA_DEFAULT",
    "PURSUIT_COMMENT_MAX_CHARS",
    "AgendaBanda",
    "AgendaContador",
    "AgendaDueKind",
    "AgendaItemKind",
    "AgendaUrgencia",
    "AmbitoCifra",
    "AuditEntryOut",
    "BloqueOportunidadesCuenta",
    "BloquePublicacionesCuenta",
    "BloqueVencimientosCuenta",
    "CalendarioEnlace",
    "ClaseSolvenciaOficial",
    "CoberturaMetricaDTO",
    "CompetitiveCompanyAwardDTO",
    "CompetitiveCompanyAwardsDTO",
    "CompetitiveCompanyBreakdownDTO",
    "CompetitiveCompanyComparisonDTO",
    "CompetitiveCompanyConcentrationDTO",
    "CompetitiveCompanyCorteDTO",
    "CompetitiveCompanyHistoryDTO",
    "CompetitiveCompanyIdentityDTO",
    "CompetitiveCompanyPositionDTO",
    "CompetitiveCompanyProfileDTO",
    "CompetitiveCompanyScopeDTO",
    "CompetitiveCompanySignalDTO",
    "CompetitiveCompanyTotalsDTO",
    "CompetitiveCompanyUteParticipationDTO",
    "CompetitiveCompanyYearDTO",
    "CondicionesAmbito",
    "CondicionesOficiales",
    "CreatedId",
    "CriterioOficial",
    "CuentaObjetivo",
    "CuentaObjetivoCreate",
    "CuentaObjetivoUpdate",
    "CuentaOrgano",
    "CuentaOrganosAdd",
    "CuentaResumen",
    "CuentasResumen",
    "CursorPaginatedResponse",
    "CursorPaginatedResponseWithTotal",
    "DetailMessage",
    "Error",
    "ErrorDeValidacion",
    "EstadoVigencia",
    "Etiqueta",
    "EtiquetaAplicacion",
    "EtiquetaAplicada",
    "EtiquetaCreate",
    "ExpectedAward",
    "FichaCuenta",
    "FiltrosLicitacion",
    "FollowItem",
    "FollowsResult",
    "GarantiaOficial",
    "JobEstadoDTO",
    "JobResultado",
    "LicitacionPublica",
    "LotePublico",
    "ObjetoEtiquetable",
    "OportunidadCuenta",
    "OrganizationCapabilities",
    "OrganizationCapabilitiesOut",
    "OrganizationCapabilityField",
    "OrganizationCapabilityScope",
    "OrganizationCertification",
    "OrganizationCreate",
    "OrganizationDocumentCategory",
    "OrganizationDocumentType",
    "OrganizationFacturacion",
    "OrganizationInvitationAccept",
    "OrganizationInvitationOut",
    "OrganizationInvitationStatus",
    "OrganizationMemberInvite",
    "OrganizationMembershipOut",
    "OrganizationMembershipStatus",
    "OrganizationMembershipUpsert",
    "OrganizationNif",
    "OrganizationNifOut",
    "OrganizationNifsIn",
    "OrganizationNifsOut",
    "OrganizationReferencia",
    "OrganizationRole",
    "OrganizationSettings",
    "OrganizationSettingsOut",
    "OrganizationSummary",
    "OrganizationTeamProfile",
    "OrganoCandidato",
    "OrganoDeCuenta",
    "Pagina",
    "PaginatedResponse",
    "PerdidaPorMotivo",
    "PgDateTime",
    "PipelineAgendaContadores",
    "PipelineAgendaItem",
    "PipelineAgendaKpis",
    "PipelineAgendaResponse",
    "ProblemDetail",
    "PublicacionCuenta",
    "PursuitAdjudicacionDetectada",
    "PursuitAdjudicatario",
    "PursuitCommentCreate",
    "PursuitCommentListResponse",
    "PursuitCommentOut",
    "PursuitCreate",
    "PursuitDecision",
    "PursuitDetail",
    "PursuitEventOut",
    "PursuitListResponse",
    "PursuitMetrics",
    "PursuitOutcome",
    "PursuitOutcomeReasonCode",
    "PursuitPlazo",
    "PursuitStatus",
    "PursuitSummary",
    "PursuitUpdate",
    "RadarBanda",
    "RadarBandaCalidad",
    "RadarQuality",
    "ReportSchedule",
    "ReportScheduleOut",
    "RequisitoSolvenciaOficial",
    "SafeStr",
    "SessionsRevoked",
    "StatusMessage",
    "StatusOk",
    "TotalCount",
    "VencimientoCuenta",
    "VigenciaDocumento",
    "WatchlistEntry",
    "WatchlistFavoriteCreated",
    "WatchlistFavoriteItem",
    "WatchlistFavoritesResult",
    "WatchlistRuleMatch",
    "WatchlistRuleMatchesResult",
]
