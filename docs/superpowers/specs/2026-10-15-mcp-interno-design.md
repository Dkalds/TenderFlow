# MCP interno de TenderFlow — diseño

- **Fecha:** 2026-10-15
- **Estado:** propuesto (pendiente de revisión)
- **Rama:** `claude/laughing-newton-dbht10`
- **Relacionado:** ADR-016 (Supabase), ADR-022 (SQL en `db/`), ADR-025 (pools),
  ADR-030 (identidad), ADR-034 (RLS por tenant), RFC 242 (`access_grants`)

## 1. Objetivo y alcance

**Lo pedido:** que el equipo interno pueda hacer preguntas en lenguaje natural
sobre la base de datos de TenderFlow desde Claude u otro LLM, desde varios
dispositivos —móvil y ordenador—, no solo en local.

**Decisiones tomadas en el brainstorming:**

| Pregunta | Decisión |
|---|---|
| Audiencia | Equipo interno. Remoto, multi-dispositivo. |
| Quién entra | Solo usuarios de TenderFlow con `is_admin = 1`, sin `deactivated_at`. |
| Datos | Mercado **y** datos de clientes, cruzando organizaciones. Todo visible salvo credenciales y secretos. |
| Enfoque | MCP propio: SQL de solo lectura con rol dedicado + tools de dominio. |

**Criterios de éxito:**

1. Una persona admin añade el conector una vez en claude.ai y lo usa desde
   web, escritorio y app móvil sin manejar claves.
2. Una pregunta analítica libre («¿qué empresas ganaron más importe en
   Andalucía en 2025?») se responde con datos reales vía `consultar_sql`.
3. Es imposible escribir en la BD o leer credenciales desde el MCP, y la
   garantía la da Postgres (rol y grants), no el código del servidor.
4. Retirar `is_admin` o desactivar al usuario corta el acceso en ≤ 60 s
   (re-comprobación por petición, §3.6), sin esperar a que caduque el token.
5. Cada llamada queda auditada con autor y SQL.

**Fuera de alcance:** acceso para clientes (multi-tenant acotado), escrituras,
tools de exportación o gráficos, fichas de empresa/órgano dedicadas.

## 2. Arquitectura

```
claude.ai / app móvil / ChatGPT
        │  Streamable HTTP + OAuth 2.1 (Bearer)
        ▼
tenderflow-mcp (Render, servicio aparte)  ──OAuth──▶ Google (login existente)
  mcp_server/  ── tools ──▶ db/consulta_libre.py ──▶ Postgres (rol tenderflow_mcp, RO)
               ── tools ──▶ db/ y services/ existentes (búsqueda, RAG, ficha)
               ── auth  ──▶ db/mcp_oauth.py ──▶ mcp_oauth_clients / mcp_oauth_tokens
```

- **Paquete nuevo `mcp_server/`**, capa más alta junto a `api/`. Se añade a
  `CAPAS` en `scripts/check_layers.py` después de `api` y con la arista
  prohibida `("mcp_server", "api")` y `("mcp_server", "scraper")`: lo que
  ambos necesiten baja a `services/` o `shared/`.
- **SDK oficial `mcp`** (FastMCP + `mcp.server.auth`), transporte Streamable
  HTTP sin estado (`stateless_http=True`, respuestas JSON), endpoint `/mcp`.
- **Servicio Render `tenderflow-mcp`**, misma imagen base, arranque
  `python -m mcp_server`, healthcheck `/healthz`, `autoDeploy: false`,
  desplegado por `.github/workflows/deploy.yml` como la API.
- **Dependencias** en `requirements-mcp.in` + lockfile propio: el SDK no entra
  en la imagen de la API.
- No toca `api/` ni la superficie congelada (`check_api_surface` no cambia).

## 3. Autenticación (OAuth 2.1 según la especificación MCP)

El servidor MCP es **su propio Authorization Server** y delega la identidad en
Google mediante el cliente OAuth que ya usa el producto.

1. Metadatos: `/.well-known/oauth-protected-resource` y
   `/.well-known/oauth-authorization-server`. Sin token, `/mcp` responde `401`
   con `WWW-Authenticate: Bearer resource_metadata=…`.
2. **Registro dinámico de clientes (DCR)** en `/register`: lo usan claude.ai y
   ChatGPT. Solo se aceptan `redirect_uris` https (y `http://localhost` para
   pruebas con MCP Inspector).
3. `/authorize` (PKCE S256 obligatorio) guarda la petición y redirige a
   Google con `state` firmado con `SIGNING_KEY`.
4. Callback de Google (`/oauth/google/callback`, un redirect URI más en
   Google Cloud Console): se verifica el email y se exige, contra `users`:
   `is_admin = 1`, `deactivated_at IS NULL` y la misma regla que
   `_oauth_access_allowed` (allowlist estática + `access_grants`). Si no
   cumple, error `access_denied` al cliente, sin emitir código.
5. El servidor emite un código de autorización de un solo uso (60 s) y, en
   `/token`, **sus propios tokens opacos**: access token 1 h, refresh token
   30 días con rotación (el refresh usado se invalida; reutilizarlo revoca la
   familia entera).
6. Cada petición a `/mcp` valida el access token y **re-comprueba
   `is_admin` y `deactivated_at`** contra `users` (lectura barata y cacheada
   60 s), de modo que retirar el permiso corta el acceso sin esperar a que
   caduque el token.

**Persistencia** (migración nueva, append-only):

- `mcp_oauth_clients(client_id, client_name, redirect_uris, created_at)`
- `mcp_oauth_tokens(token_hash, kind ∈ {code, access, refresh}, client_id,
  user_id, family_id, scopes, expires_at, revoked_at, created_at)`. Solo se
  guarda `sha256(token)`; el valor en claro nunca toca la BD ni los logs.

El SQL vive en `db/mcp_oauth.py` (invariante §3.10). Estas dos tablas se
clasifican como **ocultas** en el catálogo de §4.

## 4. Acceso a datos

### 4.1 Rol `tenderflow_mcp`

Se añade a `scripts/setup_pg_roles.sql` (idempotente, contraseña fuera del
repo), con el mismo patrón que `tenderflow_app`:

```sql
ALTER ROLE tenderflow_mcp NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
  NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 5;
ALTER ROLE tenderflow_mcp SET default_transaction_read_only = on;
ALTER ROLE tenderflow_mcp SET statement_timeout = '15s';
ALTER ROLE tenderflow_mcp SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE tenderflow_mcp SET work_mem = '32MB';
ALTER ROLE tenderflow_mcp SET search_path = pg_catalog, public;
```

- Solo `SELECT`, y solo lo que el catálogo marque visible (4.2). Ningún
  `INSERT/UPDATE/DELETE`, ningún privilegio sobre secuencias, sin `CREATE`.
- **RLS:** las políticas `tenant_scope_*` de v128 son `FOR ALL` a `PUBLIC` y
  dejan paso franco sin `app.organization_id`; el MCP no fija esa variable, así
  que ve todas las organizaciones, como se decidió. Las tablas sin
  `organization_id` (mercado) están en deny-all para roles sin política
  (v52), así que cada tabla visible recibe
  `CREATE POLICY tenderflow_mcp_read ON <t> FOR SELECT TO tenderflow_mcp USING (true)`.
- Conexión por `MCP_DATABASE_URL` (Supavisor, session mode, como el resto).
  El MCP sigue necesitando `DATABASE_URL` con el rol de la app **solo** para
  `db/mcp_oauth.py`, la lectura de `users` y la escritura en `audit_log`.

### 4.2 Catálogo de visibilidad

`mcp_server/catalogo.py` declara cada tabla de `public` en una de tres clases:

| Clase | Ejemplos | Grant |
|---|---|---|
| `VISIBLE` | `licitaciones`, `adjudicaciones`, `lotes`, `empresas`, `documentos`, `documento_chunks`, `resoluciones_recurso`, `pursuits`, `pursuit_comments`, `pursuit_attachments`, `watchlist_*`, `organization_*`, `organizations`, ML | `GRANT SELECT ON t` |
| `COLUMNAS_EXCLUIDAS` | `users` (sin `password_hash`), `webhooks` (sin secreto) | `GRANT SELECT (cols permitidas) ON t` |
| `OCULTA` | `api_keys`, `sessions`, `totp_secrets`, `totp_recovery_codes`, `password_reset_tokens`, `idempotency_keys`, `rate_limits`, `audit_chain_state`, `mcp_oauth_*`, `alembic_version` | nada |

- `scripts/gen_mcp_grants.py` genera el bloque SQL de grants y políticas a
  partir del catálogo; `--check` verifica que el SQL commiteado está al día.
- **Ratchet:** `tests/test_mcp_catalogo_integration.py` enumera
  `information_schema.tables` y `.columns` tras migrar y falla si hay una
  tabla sin clasificar o una columna nueva en una tabla `COLUMNAS_EXCLUIDAS`
  que no esté ni permitida ni excluida explícitamente. Una tabla nueva no
  queda expuesta sin decisión.

### 4.3 Ejecución de SQL libre (`db/consulta_libre.py`)

```
ejecutar_select(sql: str, *, max_filas: int = 500) -> ResultadoConsulta
```

1. Normaliza: quita espacios y `;` finales; rechaza vacío o > 20 000 chars.
2. Envuelve: `SELECT * FROM (<sql>) AS q LIMIT <max_filas + 1>`. Fuerza que
   sea una expresión de consulta (admite `WITH`), y el protocolo extendido de
   psycopg rechaza varias sentencias.
3. Ejecuta en el pool de `MCP_DATABASE_URL` (tamaño máximo 5).
4. Serializa: `Decimal` → `float`, fechas → ISO 8601, `bytes` → omitido,
   textos > 1 000 chars recortados con marca `…[+N]`.
5. Devuelve `columnas`, `filas`, `n_filas`, `truncado`, `duracion_ms`.
6. Errores de Postgres → `ErrorConsulta(codigo_sqlstate, mensaje, pista)`.
   Pistas para `42P01`/`42703` («usa describir_tabla»), `57014` (timeout:
   «acota por fecha o agrega»), `42501` (tabla no visible), `25006` (escritura
   en transacción read-only).

**La seguridad es del rol, no del envoltorio:** el envoltorio da errores
claros; aunque fallara, el rol no puede escribir ni leer lo oculto.

## 5. Tools

Todas con `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint:
true`, nombres en español con prefijo coherente, entradas Pydantic con
límites y descripciones con ejemplo, salida JSON compacta y `structuredContent`.

| Tool | Entrada | Qué hace |
|---|---|---|
| `describir_esquema` | — | Tablas visibles por dominio, una línea de descripción y filas aproximadas (`pg_class.reltuples`), más el glosario. |
| `describir_tabla` | `tabla` | Columnas (tipo, nulo, FK), descripción de `docs/database-schema.md` y 3 filas de ejemplo. Solo tablas visibles. |
| `consultar_sql` | `sql` | §4.3. |
| `buscar_licitaciones` | `texto`, `estado?`, `ccaa?`, `tecnologia?`, `importe_min?`, `importe_max?`, `desde?`, `hasta?`, `limite≤50` | Reutiliza `LicitacionesRepository.search_advanced` (el que sirve `POST /licitaciones/search`). Hereda su universo: solo filas con `tecnologia`. La descripción de la tool lo dice y remite a `consultar_sql` para el universo completo. |
| `buscar_en_pliegos` | `pregunta`, `id_externo?`, `limite≤20` | Devuelve fragmentos (texto, expediente, documento, página) reutilizando la selección de chunks de `services/rag/context.py`. **No** llama a un LLM: la síntesis la hace el cliente. |
| `ficha_licitacion` | `id_externo` | Metadatos, lotes, criterios, solvencia, garantías, adjudicaciones y ficha de pliego en un objeto, con las mismas funciones de `db/`/`services/` que usa `GET /licitaciones/{id}`. Lo que hoy esté compuesto dentro de la ruta baja a `services/` para compartirlo. |

**Glosario** (`mcp_server/glosario.md`, a mano): duplicados entre fuentes y
qué fila contar (vista canónica); semántica de `importe` (ADR-032); valores de
`estado`; claves de unión (`id_externo`, NIF, DIR3, `organization_id`);
qué es un pursuit; trampas conocidas. Se sirve en `describir_esquema` y en las
`instructions` de inicialización del servidor.

## 6. Operación

- **Auditoría:** cada llamada a una tool → `db.audit.log_action` con
  `user_id`, `action = "mcp.<tool>"` y en `detail` los argumentos (SQL
  completo), `n_filas`, `duracion_ms` y `error`. Login, emisión, rotación y
  revocación de tokens también se auditan.
- **Rate limit por usuario:** 60 llamadas/min y 1 000/día con
  `services/rate_limiting.get_rate_limiter()`. Superarlo → error de tool con
  el tiempo de espera.
- **Observabilidad:** logs estructurados con `observability.logging`
  (sin tokens ni filas); contador y latencia por tool.
- **Revocación manual:** `scripts/mcp_revocar.py --email x` revoca todos los
  tokens del usuario.
- **Configuración nueva** (`config/settings.py`): `MCP_DATABASE_URL`,
  `MCP_PUBLIC_URL`, `MCP_GOOGLE_REDIRECT_URI`. Reutiliza `SIGNING_KEY` y las
  credenciales OAuth de Google. En `prod` faltar cualquiera aborta el arranque.

**Pasos manuales (dueño del proyecto), en el runbook
`docs/runbooks/mcp-interno.md`:**

1. Crear el rol y aplicar los grants en Supabase (`setup_pg_roles.sql`).
2. Añadir el redirect URI en Google Cloud Console.
3. Crear el servicio en Render y sus variables.
4. Cada persona: claude.ai → Configuración → Conectores → Añadir conector
   personalizado → `https://<host>/mcp`. Aparece en todos sus dispositivos.
   ChatGPT: conector personalizado con la misma URL donde el plan lo permita.

## 7. Pruebas

TDD; categorías por auto-marking de `tests/conftest.py` (sin markers manuales).

- **Unit:** normalización y envoltura del SQL; serialización y recorte;
  clasificación del catálogo y generación de grants; proveedor OAuth con
  repositorio falso (rechazo de no-admin y desactivado, PKCE, código de un
  uso, rotación y detección de reutilización de refresh); rate limit.
- **Integration (Postgres)** con un **rol sonda** sin `BYPASSRLS` que recibe
  los mismos grants que `tenderflow_mcp` (la suite es superusuario, ADR-034
  §E): `INSERT`/`UPDATE`/`CREATE` fallan; `api_keys` y `users.password_hash`
  dan `42501`; se ven filas de dos organizaciones; una consulta larga corta
  por timeout; `db/mcp_oauth.py` de punta a punta.
- **Ratchet de catálogo** (§4.2).
- **E2E en proceso:** cliente del SDK `mcp` contra la app ASGI: sin token
  `401` + `WWW-Authenticate`; con token de prueba lista las seis tools y
  `consultar_sql` devuelve filas; un token de no-admin es rechazado.
- **Evaluación (tras desplegar):** 10 preguntas reales con respuesta
  verificada en `mcp_server/evaluacion.xml`, para ajustar glosario y
  descripciones.
- Controles: `make check`, `make check-layers`, `make check-agent-docs`.

## 8. Documentación

- **ADR-036** «Acceso interno por MCP con rol de solo lectura»: un camino de
  lectura nuevo a la BD, fuera de `api/`, con su propio rol.
- Runbook `docs/runbooks/mcp-interno.md`: alta, revocación, rotación de la
  contraseña del rol, diagnóstico.
- `docs/AGENT_PLAYBOOK.md`: `mcp_server/` en el mapa de áreas.
- `AGENTS.md` §2: el orden de capas incluye `mcp_server`.

## 9. Riesgos

| Riesgo | Mitigación |
|---|---|
| Consulta pesada degrada la BD compartida | `statement_timeout`, `work_mem`, `CONNECTION LIMIT 5`, rate limit. |
| Filtración de datos de clientes por el LLM del proveedor | Acceso solo admin y auditado; es una decisión aceptada («mercado + clientes»). Anotado en el ADR. |
| Tabla nueva con secretos queda expuesta | Ratchet de catálogo; por defecto nada tiene grant. |
| El LLM cuenta duplicados o malinterpreta importes | Glosario en las `instructions`; evaluación de 10 preguntas. |
| Cambios en la especificación MCP o en los clientes | SDK oficial; transporte sin estado; pruebas E2E con el cliente del SDK. |
