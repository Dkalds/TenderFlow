"""Catálogo de visibilidad del MCP interno: qué ve el rol ``tenderflow_mcp``.

El equipo interno consulta **datos de mercado y datos de cliente** (oportunidades,
comentarios, favoritos, organizaciones, auditoría, usuarios…). Lo único que el
rol nunca puede leer son credenciales y secretos: claves de API, sesiones,
secretos y códigos TOTP, tokens de restablecimiento, tokens OAuth del propio
MCP, la cadena de integridad de la auditoría y las columnas con hashes de
contraseña o secretos de webhook.

Fuente única de la política. De este módulo salen tres cosas, y solo estas:

* el SQL del rol (``scripts/setup_pg_role_mcp.sql``, generado por
  ``scripts/gen_mcp_grants.py``);
* la lista de tablas que ``describir_esquema``/``describir_tabla`` pueden mostrar;
* el ratchet de ``tests/test_mcp_catalogo_integration.py``: toda tabla nueva
  de una migración obliga a clasificarla aquí, y toda columna con nombre de
  secreto obliga a excluirla o a dejar escrito por qué no lo es.

Sobre la regla «todo el SQL vive en ``db/``» (AGENTS.md §3): este módulo solo
**genera cadenas** SQL para un script de administración y para un test; nunca
las ejecuta, igual que ``services/sql_fragments.py`` solo compone fragmentos.
Quien las ejecuta es un humano con el rol dueño (el script) o el test, contra
un rol efímero. Por eso los identificadores se validan aquí con una lista
blanca estricta (``^[a-z_][a-z0-9_]*$``) antes de quedar entre comillas dobles.

Fallo cerrado: una tabla que no figura aquí no recibe ``GRANT`` ni política, y
el rol no hereda privilegios por defecto (no hay ``ALTER DEFAULT PRIVILEGES``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

__all__ = [
    "CATALOGO",
    "COLUMNAS_REVISADAS",
    "DOMINIOS",
    "ROL_MCP",
    "EntradaCatalogo",
    "Visibilidad",
    "entrada_visible",
    "sentencias_grants",
    "sentencias_rol",
    "tablas_visibles",
]

ROL_MCP = "tenderflow_mcp"
POLITICA_LECTURA = "tenderflow_mcp_read"

_IDENTIFICADOR = re.compile(r"^[a-z_][a-z0-9_]*$")


class Visibilidad(StrEnum):
    VISIBLE = "visible"
    COLUMNAS_EXCLUIDAS = "columnas_excluidas"
    OCULTA = "oculta"


@dataclass(frozen=True)
class EntradaCatalogo:
    tabla: str
    visibilidad: Visibilidad
    dominio: str
    descripcion: str
    columnas_permitidas: tuple[str, ...] = ()
    columnas_excluidas: tuple[str, ...] = ()


#: Encabezados ``##`` de ``docs/database-schema.md`` que agrupan tablas, en el
#: orden del documento. Se añade «Operación y observabilidad» a los ocho de la
#: especificación porque el documento le reserva sección propia (jobs, eventos
#: de dominio, KPIs…). La sección «Otras» no es un dominio: sus tablas están
#: repartidas por afinidad.
DOMINIOS: tuple[str, ...] = (
    "Licitaciones y fuente",
    "Documentos y pliegos",
    "Empresas y mercado",
    "Organizaciones y oportunidades",
    "Identidad, acceso y auditoría",
    "Seguimiento y notificaciones",
    "ML y predicciones",
    "Operación y observabilidad",
)

_LIC, _DOC, _EMP, _ORG, _IDE, _SEG, _ML, _OPS = DOMINIOS

_V = Visibilidad.VISIBLE
_C = Visibilidad.COLUMNAS_EXCLUIDAS
_O = Visibilidad.OCULTA

# (tabla, visibilidad, dominio, descripción). Las tablas con columnas excluidas
# se completan más abajo en ``_COLUMNAS``.
_TABLAS: tuple[tuple[str, Visibilidad, str, str], ...] = (
    # ── Licitaciones y fuente ──────────────────────────────────────────────
    (
        "licitaciones",
        _V,
        _LIC,
        "Licitaciones públicas ingeridas (PLACSP y otras fuentes), una fila por expediente.",
    ),
    (
        "adjudicaciones",
        _V,
        _LIC,
        "Adjudicaciones de cada licitación: empresa, importe, ofertas recibidas y fecha.",
    ),
    (
        "contrato_eventos",
        _V,
        _LIC,
        "Cambios detectados en un contrato (importe, plazos, estado) entre capturas.",
    ),
    (
        "extraction_runs",
        _V,
        _LIC,
        "Ejecuciones del extractor de PLACSP con sus contadores y errores.",
    ),
    ("failed_extractions", _V, _LIC, "Extracciones fallidas pendientes de reintento o agotadas."),
    (
        "ingestion_cursors",
        _V,
        _LIC,
        "Cursor de ingesta incremental por fuente (última entrada vista, etag).",
    ),
    (
        "licitacion_criterios_adjudicacion",
        _V,
        _LIC,
        "Criterios de adjudicación de la licitación con su peso.",
    ),
    (
        "licitacion_garantias",
        _V,
        _LIC,
        "Garantías exigidas por la licitación (provisional, definitiva…).",
    ),
    (
        "licitacion_solvencia",
        _V,
        _LIC,
        "Requisitos de solvencia económica y técnica de la licitación.",
    ),
    (
        "licitaciones_duplicados",
        _V,
        _LIC,
        "Pares licitación-canónica detectados como duplicados entre fuentes.",
    ),
    (
        "licitaciones_history",
        _V,
        _LIC,
        "Histórico de capturas de cada licitación, con los campos que cambiaron.",
    ),
    ("lotes", _V, _LIC, "Lotes de cada licitación con su CPV, importe y plazo."),
    ("resoluciones_recurso", _V, _LIC, "Resoluciones de tribunales de recursos contractuales."),
    (
        "source_ingestion_health",
        _V,
        _LIC,
        "Salud de la ingesta por fuente: última ejecución, éxitos y errores.",
    ),
    (
        "extracciones_retirada",
        _V,
        _LIC,
        "Registro de extracciones históricas retiradas, por fecha y fuente.",
    ),
    # ── Documentos y pliegos ───────────────────────────────────────────────
    (
        "documentos",
        _V,
        _DOC,
        "Documentos de pliegos asociados a una licitación (metadatos y texto extraído).",
    ),
    (
        "documento_chunks",
        _V,
        _DOC,
        "Fragmentos de texto de los documentos con su embedding para búsqueda.",
    ),
    ("documento_pages", _V, _DOC, "Texto de cada página de un documento, con marca de OCR."),
    ("tender_fact_sheets", _V, _DOC, "Ficha estructurada extraída del pliego de cada licitación."),
    # ── Empresas y mercado ─────────────────────────────────────────────────
    ("empresas", _V, _EMP, "Empresas canónicas (NIF y nombre normalizado), con marca UTE y pyme."),
    ("empresa_aliases", _V, _EMP, "Alias y variantes de NIF que resuelven a una empresa canónica."),
    ("empresa_review_queue", _V, _EMP, "Cola de revisión de coincidencias dudosas de empresas."),
    ("grupos_empresariales", _V, _EMP, "Grupos empresariales a los que pertenecen las empresas."),
    ("mat_clusters", _V, _EMP, "Clúster de mercado asignado a cada licitación."),
    ("ute_miembros", _V, _EMP, "Empresas miembro de cada UTE."),
    ("organos", _V, _EMP, "Órganos de contratación canónicos (DIR3, CCAA, tipo, perfil)."),
    (
        "organo_aliases",
        _V,
        _EMP,
        "Alias de nombre que resuelven a un órgano de contratación canónico.",
    ),
    ("organo_review_queue", _V, _EMP, "Cola de revisión de coincidencias dudosas de órganos."),
    # ── Organizaciones y oportunidades ─────────────────────────────────────
    ("organizations", _V, _ORG, "Organizaciones cliente (cuentas multiusuario) y sus ajustes."),
    (
        "organization_memberships",
        _V,
        _ORG,
        "Pertenencia de usuarios a organizaciones, con rol y estado.",
    ),
    (
        "organization_invitations",
        _C,
        _ORG,
        "Invitaciones pendientes a una organización (sin el hash del token).",
    ),
    ("organization_nifs", _V, _ORG, "NIF y razón social de las entidades de una organización."),
    (
        "organization_certifications",
        _V,
        _ORG,
        "Certificaciones de la organización con su vigencia.",
    ),
    (
        "organization_references",
        _V,
        _ORG,
        "Referencias de contratos ejecutados por la organización.",
    ),
    ("organization_revenues", _V, _ORG, "Facturación anual declarada por la organización."),
    (
        "organization_team_profiles",
        _V,
        _ORG,
        "Perfiles de equipo declarados por la organización (rol, años, cantidad).",
    ),
    (
        "organization_report_schedules",
        _V,
        _ORG,
        "Informes programados de la organización: tipo, frecuencia, destinatarios.",
    ),
    (
        "pursuits",
        _V,
        _ORG,
        "Oportunidades en seguimiento por organización: decisión, oferta y resultado.",
    ),
    (
        "pursuit_attachments",
        _V,
        _ORG,
        "Adjuntos de una oportunidad (metadatos y clave del binario).",
    ),
    ("pursuit_comments", _V, _ORG, "Comentarios del equipo sobre una oportunidad."),
    (
        "pursuit_comment_mentions",
        _V,
        _ORG,
        "Menciones de usuarios en los comentarios de oportunidades.",
    ),
    ("pursuit_events", _V, _ORG, "Línea temporal de eventos de una oportunidad."),
    ("pursuit_tasks", _V, _ORG, "Tareas asignadas dentro de una oportunidad."),
    (
        "contratos_cartera",
        _V,
        _ORG,
        "Contratos en cartera de la organización con fechas de fin y prórrogas.",
    ),
    ("cuentas_objetivo", _V, _ORG, "Órganos objetivo que la organización quiere trabajar."),
    ("cuenta_organos", _V, _ORG, "Órganos de contratación asociados a cada cuenta objetivo."),
    ("etiquetas", _V, _ORG, "Etiquetas definidas por la organización."),
    (
        "etiquetas_aplicadas",
        _V,
        _ORG,
        "Aplicación de etiquetas a objetos (licitaciones, oportunidades).",
    ),
    ("go_no_go_scores", _V, _ORG, "Puntuaciones go/no-go de una oportunidad por criterio."),
    ("go_no_go_weights", _V, _ORG, "Pesos de los criterios go/no-go de la organización."),
    (
        "plantillas_organizacion",
        _V,
        _ORG,
        "Plantillas reutilizables definidas por la organización.",
    ),
    ("plantillas_aplicadas", _V, _ORG, "Registro de plantillas aplicadas a una organización."),
    # ── Identidad, acceso y auditoría ──────────────────────────────────────
    ("users", _C, _IDE, "Usuarios de la plataforma (sin el hash de contraseña)."),
    ("access_grants", _V, _IDE, "Concesiones de acceso por correo o dominio."),
    ("access_log", _V, _IDE, "Registro de inicios de sesión por usuario y método."),
    ("api_key_tiers", _V, _IDE, "Niveles de cuota de las claves de API."),
    ("audit_log", _V, _IDE, "Registro de auditoría encadenado: quién hizo qué y cuándo."),
    ("csp_violations", _V, _IDE, "Violaciones de la política CSP notificadas por los navegadores."),
    (
        "solicitudes_acceso",
        _V,
        _IDE,
        "Solicitudes de acceso recibidas desde el formulario público.",
    ),
    ("api_keys", _O, _IDE, "Claves de API (hash de la clave): credencial."),
    (
        "audit_chain_state",
        _O,
        _IDE,
        "Cabeza y HMAC de la cadena de auditoría: material de integridad.",
    ),
    ("idempotency_keys", _O, _IDE, "Claves de idempotencia con respuestas cacheadas de la API."),
    ("password_reset_tokens", _O, _IDE, "Tokens de restablecimiento de contraseña: credencial."),
    ("rate_limits", _O, _IDE, "Contadores del limitador de tasa (claves de cliente)."),
    ("sessions", _O, _IDE, "Sesiones de usuario (hash del token): credencial."),
    ("totp_recovery_codes", _O, _IDE, "Códigos de recuperación TOTP: credencial."),
    ("totp_secrets", _O, _IDE, "Secretos TOTP: credencial."),
    (
        "mcp_oauth_clients",
        _O,
        _IDE,
        "Clientes OAuth registrados del MCP (v150).",
    ),
    (
        "mcp_oauth_tokens",
        _O,
        _IDE,
        "Códigos y tokens OAuth del MCP, solo sha256 (v150).",
    ),
    # ── Seguimiento y notificaciones ───────────────────────────────────────
    ("watchlist_items", _V, _SEG, "Licitaciones favoritas de cada usuario u organización."),
    ("watchlist_cpv", _V, _SEG, "Alertas por prefijo CPV."),
    ("watchlist_empresas", _V, _SEG, "Alertas por empresa seguida."),
    (
        "watchlist_rules",
        _V,
        _SEG,
        "Reglas de alerta compuestas (palabra clave, CPV, importe, órgano…).",
    ),
    ("saved_filters", _V, _SEG, "Filtros de búsqueda guardados."),
    ("user_profiles", _V, _SEG, "Perfil de relevancia del usuario (pesos, CPV y CCAA preferidos)."),
    ("user_notifications", _V, _SEG, "Notificaciones generadas para cada usuario."),
    ("notification_reads", _V, _SEG, "Marca de lectura de las notificaciones."),
    (
        "notification_preferences",
        _V,
        _SEG,
        "Preferencias de canal y frecuencia por tipo de notificación.",
    ),
    (
        "pending_digests",
        _V,
        _SEG,
        "Entradas pendientes de enviar en el próximo resumen por correo.",
    ),
    ("radar_dismissals", _V, _SEG, "Licitaciones descartadas del radar por cada usuario."),
    (
        "follows",
        _V,
        _SEG,
        "Seguimientos de objetos (órganos, empresas, CPV) con canales y visibilidad.",
    ),
    ("user_event_prefs", _V, _SEG, "Preferencias de eventos de usuario."),
    ("webhooks", _C, _SEG, "Webhooks de salida configurados (sin URL ni secreto de firma)."),
    ("webhook_deliveries", _V, _SEG, "Entregas de webhooks con estado, reintentos y carga."),
    # ── ML y predicciones ──────────────────────────────────────────────────
    ("feature_store", _V, _ML, "Features calculadas por entidad para los modelos."),
    (
        "licitacion_tecnologia_pliego",
        _V,
        _ML,
        "Señales de tecnología detectadas en el pliego de cada licitación.",
    ),
    (
        "licitacion_tecnologia_score",
        _V,
        _ML,
        "Probabilidad de tecnología por licitación según el modelo.",
    ),
    ("ml_feedback", _V, _ML, "Feedback humano sobre la relevancia y tecnología de licitaciones."),
    ("model_versions", _V, _ML, "Versiones de modelos entrenados con sus métricas."),
    (
        "predicciones_baja",
        _V,
        _ML,
        "Predicción de baja de adjudicación (p10/p50/p90) por licitación.",
    ),
    (
        "predicciones_retencion",
        _V,
        _ML,
        "Probabilidad de retención del adjudicatario por licitación.",
    ),
    ("asistente_feedback", _V, _ML, "Votos de utilidad sobre las respuestas del asistente."),
    ("tasas_anulacion_organo", _V, _ML, "Tasa de anulación de expedientes por órgano y CPV."),
    ("tecnologias_keywords", _V, _ML, "Palabras clave que definen cada tecnología."),
    # ── Operación y observabilidad ─────────────────────────────────────────
    ("domain_events", _V, _OPS, "Outbox de eventos de dominio."),
    ("domain_event_dispatches", _V, _OPS, "Despacho de cada evento de dominio por canal."),
    ("feature_flags", _V, _OPS, "Feature flags con porcentaje de despliegue."),
    ("job_locks", _V, _OPS, "Cerraduras de ejecución de tareas programadas."),
    ("jobs", _V, _OPS, "Cola de trabajos en segundo plano."),
    ("kpi_snapshots", _V, _OPS, "Instantáneas de KPIs del producto."),
    ("ops_events", _V, _OPS, "Eventos operativos de la plataforma."),
    ("client_errors", _V, _OPS, "Errores del cliente web agrupados por huella."),
)

#: Columnas de las tablas ``COLUMNAS_EXCLUIDAS``: ``(permitidas, excluidas)``.
#: La unión debe ser exactamente el conjunto de columnas reales (lo comprueba el
#: ratchet), así una columna añadida por una migración obliga a decidir.
_COLUMNAS: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "users": (
        (
            "id",
            "email",
            "oauth_provider",
            "oauth_sub",
            "display_name",
            "created_at",
            "is_admin",
            "deactivated_at",
            "admin_granted_by",
        ),
        ("password_hash",),
    ),
    "webhooks": (
        (
            "id",
            "name",
            "event_types",
            "active",
            "created_at",
            "last_triggered_at",
            "last_status",
            "failure_count",
            "organization_id",
            "created_by",
            "formato",
        ),
        # La URL de Slack/Teams lleva el token incrustado: es una credencial.
        ("secret", "url"),
    ),
    "organization_invitations": (
        (
            "id",
            "organization_id",
            "email",
            "role",
            "invited_by_user_id",
            "created_at",
            "expires_at",
            "accepted_at",
            "accepted_user_id",
            "revoked_at",
            "revoked_by_user_id",
        ),
        ("token_hash",),
    ),
}

#: Pares ``(tabla, columna)`` cuyo nombre parece secreto (hash, key, token…) y
#: que se revisaron: no son credenciales. El motivo va en el comentario; añadir
#: una entrada sin motivo no pasa la revisión.
COLUMNAS_REVISADAS: frozenset[tuple[str, str]] = frozenset(
    {
        # Palabras clave de negocio, no claves criptográficas.
        ("licitaciones", "raw_keywords"),
        ("user_profiles", "afinidad_keywords_json"),
        ("watchlist_cpv", "keyword"),
        ("watchlist_rules", "keyword"),
        ("tecnologias_keywords", "keyword"),
        # Clave de deduplicación entre fuentes (texto normalizado del expediente).
        ("licitaciones_duplicados", "clave_match"),
        # Clave del objeto en el almacén de binarios y hash del contenido público
        # del pliego; sin las credenciales del almacén no abren nada.
        ("documentos", "storage_key"),
        ("documentos", "blob_key"),
        ("documentos", "source_hash"),
        ("pursuit_attachments", "blob_key"),
        # Clave de idempotencia de un comentario/evento: un UUID del cliente que
        # evita duplicados; no autentica nada.
        ("pursuit_comments", "idempotency_key"),
        ("pursuit_events", "idempotency_key"),
        # Identidad opaca heredada del usuario (D18), derivada del correo o del
        # id; es un identificador, no una credencial.
        ("audit_log", "user_key"),
        ("notification_reads", "user_key"),
        ("pending_digests", "user_key"),
        ("radar_dismissals", "user_key"),
        ("saved_filters", "user_key"),
        ("user_notifications", "user_key"),
        ("user_profiles", "user_key"),
        ("watchlist_cpv", "user_key"),
        ("watchlist_empresas", "user_key"),
        ("watchlist_items", "user_key"),
        ("watchlist_rules", "user_key"),
        ("follows", "user_key"),
        ("user_event_prefs", "user_key"),
        # Clave de agrupación órgano+CPV de una estadística, no una clave secreta.
        ("tasas_anulacion_organo", "organo_key"),
        # Eslabones de la cadena de auditoría (SHA-256 de filas ya visibles) y su
        # versión: permiten verificar integridad, no autenticarse. El material
        # que la protege (``audit_chain_state.state_hmac``) está en una tabla OCULTA.
        ("audit_log", "prev_hash"),
        ("audit_log", "this_hash"),
        ("audit_log", "hash_version"),
        # Hash truncado de 16 hex de la sesión, solo para correlacionar eventos;
        # con ``"-"`` cuando no hay sesión. No sirve para suplantarla.
        ("audit_log", "session_hash"),
        # Hash de la pregunta del asistente para agrupar votos repetidos.
        ("asistente_feedback", "pregunta_hash"),
        # FK al webhook configurado (``webhooks.id``): un entero, no su secreto de
        # firma (``webhooks.secret`` y la URL están excluidas).
        ("webhook_deliveries", "webhook_id"),
    }
)

_CATALOGO: dict[str, EntradaCatalogo] = {}
for _tabla, _vis, _dominio, _descripcion in _TABLAS:
    _permitidas, _excluidas = _COLUMNAS.get(_tabla, ((), ()))
    if _tabla in _CATALOGO:  # pragma: no cover - error de edición del catálogo
        raise ValueError(f"Tabla duplicada en el catálogo: {_tabla}")
    _CATALOGO[_tabla] = EntradaCatalogo(
        tabla=_tabla,
        visibilidad=_vis,
        dominio=_dominio,
        descripcion=_descripcion,
        columnas_permitidas=_permitidas,
        columnas_excluidas=_excluidas,
    )

#: Una entrada por tabla de ``public``, salvo ``alembic_version`` (oculta implícita).
CATALOGO: Mapping[str, EntradaCatalogo] = MappingProxyType(_CATALOGO)


def tablas_visibles() -> list[EntradaCatalogo]:
    """Tablas ``VISIBLE`` y ``COLUMNAS_EXCLUIDAS``, ordenadas por dominio y nombre."""
    return sorted(
        (e for e in CATALOGO.values() if e.visibilidad is not Visibilidad.OCULTA),
        key=lambda e: (DOMINIOS.index(e.dominio), e.tabla),
    )


def entrada_visible(tabla: str) -> EntradaCatalogo | None:
    """Entrada de ``tabla`` si el MCP puede mostrarla; ``None`` si oculta o desconocida.

    Comparación exacta: ``Users`` o ``users"; --`` no coinciden con nada.
    """
    entrada = CATALOGO.get(tabla)
    if entrada is None or entrada.visibilidad is Visibilidad.OCULTA:
        return None
    return entrada


def _ident(nombre: str) -> str:
    """Identificador SQL entre comillas dobles tras validarlo contra la lista blanca."""
    if not _IDENTIFICADOR.match(nombre):
        raise ValueError(f"Identificador SQL no válido: {nombre!r}")
    return f'"{nombre}"'


def sentencias_rol(rol: str = ROL_MCP) -> list[str]:
    """``ALTER ROLE`` con los límites del rol de solo lectura (sin ``;`` final)."""
    r = _ident(rol)
    return [
        f"ALTER ROLE {r} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION "
        "NOBYPASSRLS CONNECTION LIMIT 5",
        f"ALTER ROLE {r} SET default_transaction_read_only = on",
        f"ALTER ROLE {r} SET statement_timeout = '15s'",
        f"ALTER ROLE {r} SET idle_in_transaction_session_timeout = '30s'",
        f"ALTER ROLE {r} SET work_mem = '32MB'",
        f"ALTER ROLE {r} SET search_path = pg_catalog, public",
    ]


def sentencias_grants(rol: str = ROL_MCP, schema: str = "public") -> list[str]:
    """``GRANT`` de solo lectura por tabla visible y la política RLS, sin ``;`` final.

    Idempotente: parte de un ``REVOKE`` completo, de modo que volver a ejecutarlo
    tras ocultar una tabla o una columna retira lo que ya no corresponde.

    La primera sentencia aborta con un error claro si falta alguna tabla visible
    (típico: ejecutar el script antes de ``alembic upgrade head``), antes de
    revocar nada: sin ella, un ``GRANT`` fallido deja pasar el resto y el único
    ``DO`` de políticas se desharía entero, dejando al rol sin filas y sin error.
    """
    r = _ident(rol)
    s = _ident(schema)
    visibles = tablas_visibles()
    nombres = ", ".join(f"'{e.tabla}'" for e in visibles)
    sentencias = [
        "DO $$\n"  # noqa: S608 - identificadores validados por _ident; nunca se ejecuta aquí
        "DECLARE faltan text;\n"
        "BEGIN\n"
        "    SELECT string_agg(t, ', ' ORDER BY t) INTO faltan\n"
        f"    FROM unnest(ARRAY[{nombres}]) AS t\n"
        f"    WHERE to_regclass(format('%I.%I', '{schema}', t)) IS NULL;\n"
        "    IF faltan IS NOT NULL THEN\n"
        "        RAISE EXCEPTION\n"
        f"            'tenderflow_mcp: faltan tablas visibles en {schema}: %. '\n"
        "            'Aplica antes `alembic upgrade head`.', faltan;\n"
        "    END IF;\n"
        "END $$",
        f"REVOKE ALL ON ALL TABLES IN SCHEMA {s} FROM {r}",
        f"REVOKE CREATE ON SCHEMA {s} FROM {r}",
        f"GRANT USAGE ON SCHEMA {s} TO {r}",
    ]
    for e in visibles:
        t = _ident(e.tabla)
        if e.visibilidad is Visibilidad.COLUMNAS_EXCLUIDAS:
            columnas = ", ".join(_ident(c) for c in e.columnas_permitidas)
            sentencias.append(f"GRANT SELECT ({columnas}) ON {s}.{t} TO {r}")
        else:
            sentencias.append(f"GRANT SELECT ON {s}.{t} TO {r}")
    # Las tablas tienen RLS activo (v52): sin política el rol vería cero filas.
    # ``IF NOT EXISTS`` porque ``CREATE POLICY`` no admite ``OR REPLACE``.
    sentencias.append(
        "DO $$\n"  # noqa: S608 - identificadores validados por _ident; nunca se ejecuta aquí
        "DECLARE t text;\n"
        "BEGIN\n"
        f"    FOREACH t IN ARRAY ARRAY[{nombres}] LOOP\n"
        "        IF NOT EXISTS (\n"
        "            SELECT 1 FROM pg_policies\n"
        f"            WHERE schemaname = '{schema}' AND tablename = t\n"
        f"              AND policyname = '{POLITICA_LECTURA}' AND '{rol}' = ANY (roles)\n"
        "        ) THEN\n"
        "            EXECUTE format(\n"
        f"                'CREATE POLICY {POLITICA_LECTURA} ON %I.%I FOR SELECT TO %I USING (true)',\n"
        f"                '{schema}', t, '{rol}'\n"
        "            );\n"
        "        END IF;\n"
        "    END LOOP;\n"
        "END $$"
    )
    return sentencias
