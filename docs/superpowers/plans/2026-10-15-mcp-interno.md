# MCP interno de TenderFlow — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un servidor MCP remoto, de solo lectura, con el que los admins de TenderFlow preguntan en lenguaje natural sobre mercado y clientes desde claude.ai (web, escritorio y móvil) u otro LLM.

**Architecture:** Paquete `mcp_server/` (capa más alta, sin importar `api/` ni `scraper/`) servido como servicio Render aparte por Streamable HTTP sin estado. Es su propio Authorization Server OAuth 2.1 y delega la identidad en Google; solo entran usuarios con `is_admin`. El SQL libre corre con un rol Postgres `tenderflow_mcp` cuyos grants se generan desde un catálogo de visibilidad que un ratchet mantiene completo.

**Tech Stack:** Python 3.13, SDK `mcp==2.3.0` (`mcp.server.mcpserver.MCPServer`, `mcp.server.auth`), Starlette/uvicorn, psycopg 3 + psycopg_pool, Postgres (Supabase), pytest.

**Spec:** [docs/superpowers/specs/2026-10-15-mcp-interno-design.md](../specs/2026-10-15-mcp-interno-design.md)

## Global Constraints

- SDK: `mcp==2.3.0`. En la v2 `FastMCP` ya no existe: se usa `from mcp.server.mcpserver import MCPServer`; auth en `mcp.server.auth.provider` (`OAuthAuthorizationServerProvider`, `AuthorizationParams`, `AuthorizationCode`, `RefreshToken`, `AccessToken`, `AuthorizeError`, `TokenError`, `RegistrationError`), `mcp.server.auth.settings` (`AuthSettings`, `ClientRegistrationOptions`, `RevocationOptions`), `mcp.shared.auth` (`OAuthClientInformationFull`, `OAuthToken`), `mcp.server.auth.middleware.auth_context.get_access_token`.
- Transporte: `streamable_http_app(streamable_http_path="/mcp", json_response=True, stateless_http=True)`.
- Límites: 500 filas por consulta (`LIMIT 501` para detectar truncado); textos recortados a 1 000 caracteres con marca `…[+N]`; SQL de más de 20 000 caracteres rechazado.
- Rol `tenderflow_mcp`: `NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 5`, `default_transaction_read_only = on`, `statement_timeout = '15s'`, `idle_in_transaction_session_timeout = '30s'`, `work_mem = '32MB'`, `search_path = pg_catalog, public`. Política por tabla visible: `tenderflow_mcp_read FOR SELECT TO tenderflow_mcp USING (true)`.
- Pool MCP: tamaño máximo 5, por `MCP_DATABASE_URL`.
- Tokens: código de autorización 60 s y de un solo uso; access token 1 h; refresh token 30 días con rotación; reutilizar un refresh revoca la familia. Petición pendiente (entre `/authorize` y el callback de Google): 10 min. Solo se guarda `sha256(token)`.
- Acceso: `users.is_admin = 1`, `deactivated_at IS NULL` y `services.auth.acceso_oauth_permitido(email)`. Re-comprobación por petición con caché de 60 s.
- DCR: `redirect_uris` solo `https://…` o `http://localhost[:puerto]/…` / `http://127.0.0.1[:puerto]/…`. PKCE S256 obligatorio (lo impone el SDK).
- Rate limit por usuario: 60 llamadas/min y 1 000/día (`services.rate_limiting.get_rate_limiter().check(key, max_calls=…, window_seconds=…)`).
- Tools: nombres en español, `ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)`.
- Invariantes del repo (AGENTS.md §3): mypy strict sin `Any`/`# type: ignore` sin comentario; **todo SQL en `db/`**; migraciones append-only; nada de markers manuales de categoría en tests; pre-commit sin `--no-verify`.
- Capas: `mcp_server` va después de `api` en `scripts/check_layers.py::CAPAS`, con `("mcp_server", "api")` y `("mcp_server", "scraper")` en `PROHIBIDAS`.
- Prefijo de comandos: `ENV=dev` en tests y scripts. Prerrequisito de los tests de integración: Postgres con `pgvector` (sin él falla la migración v56 y con ella toda la suite).
- **Ajustes al spec** (decididos aquí, sin cambiar su intención): (a) la configuración del MCP son funciones `mcp_*()` en `config/settings.py` siguiendo el patrón `oauth_microsoft_*()`, no campos de `Settings`, para que su ausencia no aborte la API en `prod`; la validación la hace el arranque del MCP. (b) Los grants y el rol se generan en un fichero propio, `scripts/setup_pg_role_mcp.sql`, en vez de editar a mano `setup_pg_roles.sql`, que solo lo referencia. (c) Las descripciones de tabla viven en el catálogo, no en `docs/database-schema.md`, que no las tiene y no viaja en la imagen. (d) Las tablas OAuth llevan una columna `datos jsonb` para los campos propios de cada tipo (PKCE, redirect, resource, petición pendiente). (e) La ruta `GET /licitaciones/{id}` no se refactoriza: la composición nueva vive en `services/` y la ruta queda igual.

## Review Focus

1. **SQL que acaba en un comentario `-- …` o con `;` y espacios/comentarios detrás.** El envoltorio debe seguir funcionando: se envuelve con saltos de línea (`SELECT * FROM (\n<sql>\n) AS q LIMIT n`). Test en la Task 3.
2. **Resultados con tipos no triviales** (`jsonb`, arrays, `uuid`, `bytea`, `timestamptz`, `interval`, `Decimal('NaN')`, `vector` de pgvector, `NULL`). Deben serializarse y no tumbar la tool. Test en la Task 3.
3. **Respuesta enorme** (500 filas × columnas de texto largo). La respuesta serializada no debe superar 100 000 caracteres: se quitan filas del final y se marca `truncado`. Test en la Task 3.
4. **El mismo refresh token presentado dos veces a la vez** (reintento del cliente). Solo un intercambio gana, el otro recibe `invalid_grant` y la familia queda revocada; el consumo es atómico en la BD. Test en la Task 6.
5. **Nombres de tabla hostiles o fuera de catálogo** en `describir_tabla` (`users"; --`, `api_keys`, `pg_shadow`, mayúsculas). Se rechazan contra el catálogo antes de tocar SQL, con un error que lista las tablas válidas. Test en la Task 4.

---

## Mapa de ficheros

| Fichero | Responsabilidad |
|---|---|
| `requirements-mcp.in` / `.txt` | Dependencias de la imagen MCP (`-r requirements-api.in` + `mcp`). |
| `config/settings.py` | `mcp_database_url()`, `mcp_public_url()`, `mcp_google_redirect_uri()`. |
| `mcp_server/catalogo.py` | Visibilidad de cada tabla; genera el SQL de rol, grants y políticas. |
| `scripts/gen_mcp_grants.py` → `scripts/setup_pg_role_mcp.sql` | SQL generado (`--check` en tests). |
| `db/consulta_libre.py` | Pool MCP; ejecuta SELECT libre y la introspección de esquema. |
| `mcp_server/glosario.md` | Reglas de negocio para el LLM (a mano). |
| `mcp_server/tools/esquema.py` | `describir_esquema`, `describir_tabla`. |
| `mcp_server/tools/consulta.py` | `consultar_sql`. |
| `mcp_server/tools/dominio.py` | `buscar_licitaciones`, `buscar_en_pliegos`, `ficha_licitacion`. |
| `services/rag/fragmentos.py` | Fragmentos de pliego relevantes sin LLM. |
| `services/expediente.py` | Expediente completo en un dict. |
| `services/auth.py` | `acceso_oauth_permitido(email)` (bajado de `api/routes/auth.py`). |
| `db/alembic/versions/v150_mcp_oauth.py` | Tablas `mcp_oauth_clients`, `mcp_oauth_tokens`. |
| `db/mcp_oauth.py` | SQL de clientes y tokens. |
| `mcp_server/auth/proveedor.py` | `OAuthAuthorizationServerProvider` de TenderFlow. |
| `mcp_server/auth/google.py` | Redirección a Google, intercambio de código, verificación del id_token. |
| `mcp_server/envoltura.py` | Auditoría + rate limit + errores alrededor de cada tool. |
| `mcp_server/servidor.py`, `mcp_server/__main__.py` | Construye `MCPServer`, rutas extra y arranque. |
| `scripts/mcp_revocar.py` | Revocación manual por email. |
| `docker/Dockerfile.api`, `render.yaml`, `.github/workflows/deploy.yml` | Despliegue. |
| `docs/adr/ADR-036-…`, `docs/runbooks/mcp-interno.md`, `AGENTS.md`, `docs/AGENT_PLAYBOOK.md` | Documentación. |

---

### Task 1: Dependencias, paquete y capa

**Files:**
- Create: `requirements-mcp.in`, `requirements-mcp.txt` (generado), `mcp_server/__init__.py`
- Modify: `requirements.in` (añadir `mcp>=2.3,<3`), `requirements.txt` (generado), `Makefile` (target `lock`), `scripts/check_layers.py:59-74`, `scripts/check_requirements_sync.py` (si enumera los lockfiles hijos), `config/settings.py` (junto a `oauth_microsoft_*`), `AGENTS.md` §2 (orden de capas)
- Test: `tests/test_mcp_config.py`

**Interfaces:**
- Produces: `config.settings.mcp_database_url() -> str`, `mcp_public_url() -> str` (sin barra final), `mcp_google_redirect_uri() -> str`. Las tres leen `os.environ` y devuelven `""` si no hay valor.

- [ ] **Step 1: Write the failing test**

```python
def test_mcp_config_vacia_por_defecto(monkeypatch):
    for v in ("MCP_DATABASE_URL", "MCP_PUBLIC_URL", "MCP_GOOGLE_REDIRECT_URI"):
        monkeypatch.delenv(v, raising=False)
    assert settings.mcp_database_url() == ""
    assert settings.mcp_public_url() == ""

def test_mcp_public_url_sin_barra_final(monkeypatch):
    monkeypatch.setenv("MCP_PUBLIC_URL", "https://mcp.example.com/ ")
    assert settings.mcp_public_url() == "https://mcp.example.com"

def test_mcp_server_capa_por_encima_de_api():
    from scripts.check_layers import CAPAS, PROHIBIDAS
    assert CAPAS[-1] == "mcp_server" and CAPAS[-2] == "api"
    assert ("mcp_server", "api") in PROHIBIDAS and ("mcp_server", "scraper") in PROHIBIDAS
```

- [ ] **Step 2: Run to verify it fails** — `ENV=dev pytest tests/test_mcp_config.py -v` → FAIL (`AttributeError: mcp_database_url`).
- [ ] **Step 3: Implement.** Las tres funciones; `CAPAS` + `PROHIBIDAS`; `requirements-mcp.in` con cabecera explicativa al estilo de `requirements-api.in`, `-r requirements-api.in` y `mcp>=2.3,<3`; línea en `make lock`: `$(call compilar_lock,requirements-mcp.in,requirements-mcp.txt,--constraint=requirements.txt)`; `make lock`; `pip install -r requirements.txt -r requirements-dev.txt`; `mcp_server/__init__.py` con docstring del paquete; AGENTS.md §2: `… < api < mcp_server`, y «ni `api/` ni `mcp_server/` importan de `scraper/`; `mcp_server/` no importa de `api/`».
- [ ] **Step 4: Verify** — `ENV=dev pytest tests/test_mcp_config.py -v` PASS; `make check-layers` y `python scripts/check_requirements_sync.py` sin errores; `python -c "from mcp.server.mcpserver import MCPServer"` sin error.
- [ ] **Step 5: Commit** — `build(mcp): dependencias, paquete mcp_server y su capa`

---

### Task 2: Catálogo de visibilidad, SQL del rol y ratchet

**Files:**
- Create: `mcp_server/catalogo.py`, `scripts/gen_mcp_grants.py`, `scripts/setup_pg_role_mcp.sql` (generado)
- Modify: `scripts/setup_pg_roles.sql` (cabecera: «el rol del MCP vive en `setup_pg_role_mcp.sql`, generado»)
- Test: `tests/test_mcp_catalogo.py` (unit), `tests/test_mcp_catalogo_integration.py` (integration, `tmp_db`)

**Interfaces:**
- Produces:
  - `class Visibilidad(StrEnum): VISIBLE = "visible"; COLUMNAS_EXCLUIDAS = "columnas_excluidas"; OCULTA = "oculta"`
  - `@dataclass(frozen=True) class EntradaCatalogo: tabla: str; visibilidad: Visibilidad; dominio: str; descripcion: str; columnas_permitidas: tuple[str, ...] = (); columnas_excluidas: tuple[str, ...] = ()`
  - `CATALOGO: Mapping[str, EntradaCatalogo]`, una entrada por tabla de `public` salvo `alembic_version` (que se trata como oculta implícita).
  - `DOMINIOS: tuple[str, ...]`: los encabezados `##` de `docs/database-schema.md` (Licitaciones y fuente, Documentos y pliegos, Empresas y mercado, Organizaciones y oportunidades, Identidad, acceso y auditoría, Seguimiento y notificaciones, ML y predicciones).
  - `COLUMNAS_REVISADAS: frozenset[tuple[str, str]]`: pares `(tabla, columna)` cuyo nombre parece secreto pero se revisaron y no lo son.
  - `tablas_visibles() -> list[EntradaCatalogo]` (VISIBLE y COLUMNAS_EXCLUIDAS, ordenadas por dominio y nombre)
  - `entrada_visible(tabla: str) -> EntradaCatalogo | None` (comparación exacta; `None` si oculta o desconocida)
  - `sentencias_rol(rol: str = "tenderflow_mcp") -> list[str]` (`ALTER ROLE … SET …` con los valores de Global Constraints)
  - `sentencias_grants(rol: str = "tenderflow_mcp", schema: str = "public") -> list[str]` (`GRANT USAGE ON SCHEMA`, `GRANT SELECT ON` o `GRANT SELECT (cols) ON` por tabla, y `CREATE POLICY tenderflow_mcp_read` protegido con `DO $$ … IF NOT EXISTS … $$`)
- `scripts/gen_mcp_grants.py [--check]`: escribe `setup_pg_role_mcp.sql` (bloque `CREATE ROLE` idempotente con contraseña placeholder `<GENERAR_PASSWORD_FUERTE>` y `pragma: allowlist secret` como en `setup_pg_roles.sql`, más `sentencias_rol()` y `sentencias_grants()`); con `--check` sale con 1 si difiere.

- [ ] **Step 1: Write the failing unit tests**

```python
def test_rol_lleva_los_limites_del_spec():
    sql = "\n".join(sentencias_rol("tenderflow_mcp"))
    for fragmento in ("default_transaction_read_only = on", "statement_timeout = '15s'",
                      "idle_in_transaction_session_timeout = '30s'", "work_mem = '32MB'"):
        assert fragmento in sql

def test_tablas_de_credenciales_ocultas():
    for t in ("api_keys", "sessions", "totp_secrets", "totp_recovery_codes",
              "password_reset_tokens", "idempotency_keys", "rate_limits",
              "audit_chain_state", "mcp_oauth_clients", "mcp_oauth_tokens"):
        assert CATALOGO[t].visibilidad is Visibilidad.OCULTA

def test_users_sin_password_hash():
    e = CATALOGO["users"]
    assert e.visibilidad is Visibilidad.COLUMNAS_EXCLUIDAS
    assert "password_hash" in e.columnas_excluidas and "password_hash" not in e.columnas_permitidas

def test_grants_no_mencionan_tablas_ocultas():
    sql = "\n".join(sentencias_grants())
    assert "api_keys" not in sql and "GRANT SELECT ON public.licitaciones" in sql.replace('"', "")
    assert "INSERT" not in sql and "UPDATE" not in sql and "DELETE" not in sql

def test_sql_generado_al_dia():
    assert subprocess.run([sys.executable, "scripts/gen_mcp_grants.py", "--check"]).returncode == 0
```

- [ ] **Step 2: Write the failing integration (ratchet) tests**

```python
_PARECE_SECRETO = re.compile(r"(hash|secret|token|password|passwd|clave|key|totp|salt)", re.I)

def test_toda_tabla_clasificada(tmp_db):
    # information_schema.tables del schema del test, BASE TABLE, sin alembic_version
    assert sin_clasificar == set(), f"Clasifica en mcp_server/catalogo.py: {sorted(sin_clasificar)}"

def test_columnas_de_tablas_con_exclusiones_cubiertas(tmp_db):
    # para cada COLUMNAS_EXCLUIDAS: set(columnas reales) == permitidas ∪ excluidas
    ...

def test_ninguna_columna_visible_parece_secreta_sin_revisar(tmp_db):
    # columnas de tablas VISIBLE (y permitidas de COLUMNAS_EXCLUIDAS) cuyo nombre casa
    # _PARECE_SECRETO y no están en COLUMNAS_REVISADAS
    assert sospechosas == set()

def test_grants_aplican_en_postgres(tmp_db):
    # crea un rol NOLOGIN efímero (patrón rol_runtime de test_rls_tenant_scope_integration),
    # ejecuta sentencias_rol + sentencias_grants(rol, schema) sin error y lo borra
```

- [ ] **Step 3: Run to verify they fail** — `ENV=dev pytest tests/test_mcp_catalogo.py tests/test_mcp_catalogo_integration.py -v` → FAIL (`ModuleNotFoundError: mcp_server.catalogo`).
- [ ] **Step 4: Implement** `mcp_server/catalogo.py` (las tablas reales salen del test de integración: correrlo, clasificar todo lo que liste, con dominio y una línea de descripción por tabla) y `scripts/gen_mcp_grants.py`; generar el SQL. Los identificadores van entre comillas dobles y pasan por `db.connection._validate_identifier` o por una validación equivalente `^[a-z_][a-z0-9_]*$` dentro de `catalogo.py`. Las tablas OAuth de la Task 6 se clasifican ya como OCULTA (el ratchet las verá cuando exista la migración).
- [ ] **Step 5: Verify** — los dos ficheros de test en PASS.
- [ ] **Step 6: Commit** — `feat(mcp): catálogo de visibilidad y SQL del rol de solo lectura`

---

### Task 3: Ejecutor de SQL libre con el rol MCP

**Files:**
- Create: `db/consulta_libre.py`
- Modify: `tests/conftest.py` (fixture `rol_mcp`), whitelist del TID251 en `pyproject.toml` solo si el ratchet exige declarar el pool nuevo dentro de `db/` (no debería: `db/` puede abrir conexiones)
- Test: `tests/test_consulta_libre.py` (unit), `tests/test_consulta_libre_integration.py`

**Interfaces:**
- Consumes: `sentencias_rol`, `sentencias_grants` (Task 2); `config.settings.mcp_database_url()` (Task 1); `db.connection._pg_connect_kwargs(url, read_only=True)`.
- Produces:
  - `JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]` (alias `type`; lo importan las Tasks 4, 5 y 8)
  - `MAX_FILAS = 500`, `MAX_CHARS_CELDA = 1_000`, `MAX_CHARS_SQL = 20_000`, `MAX_CHARS_RESPUESTA = 100_000`
  - `@dataclass(frozen=True) class ResultadoConsulta: columnas: list[str]; filas: list[list[JSONValue]]; n_filas: int; truncado: bool; duracion_ms: int` con `def como_dict(self) -> dict[str, JSONValue]`
  - `class ErrorConsulta(Exception): sqlstate: str | None; mensaje: str; pista: str | None`
  - `normalizar_sql(sql: str) -> str`: `strip()`, quita `;` finales repetidos; `ErrorConsulta(None, …)` si queda vacío o supera `MAX_CHARS_SQL`
  - `envolver(sql: str, max_filas: int) -> str`: devuelve `f"SELECT * FROM (\n{sql}\n) AS q LIMIT {max_filas + 1}"`
  - `serializar_valor(v: object) -> JSONValue`
  - `ejecutar_select(sql: str, *, max_filas: int = MAX_FILAS) -> ResultadoConsulta`
  - `cerrar_pool_mcp() -> None`
  - `PISTAS: Mapping[str, str]` para `42P01`, `42703`, `57014`, `42501`, `25006`, `42601`
- Fixture `rol_mcp(tmp_db, monkeypatch) -> Iterator[str]`: crea un rol efímero `tf_mcp_probe_<pid>_<hex>` con `LOGIN PASSWORD '<aleatoria>' NOBYPASSRLS`, aplica `sentencias_rol(rol)` + `sentencias_grants(rol, schema)`, después `ALTER ROLE … SET statement_timeout = '1s'` (velocidad del test; el 15 s lo fija el unit test de la Task 2), apunta `MCP_DATABASE_URL` a un DSN con ese usuario y `options=-csearch_path%3D<schema>%2Cpublic`, llama a `cerrar_pool_mcp()` antes y después, y al salir hace `DROP OWNED BY` + `DROP ROLE`.

- [ ] **Step 1: Write the failing unit tests**

```python
@pytest.mark.parametrize("entrada,esperado", [
    ("SELECT 1;", "SELECT 1"), ("  SELECT 1 ;; \n", "SELECT 1"),
])
def test_normalizar_quita_puntos_y_coma(entrada, esperado): ...

def test_normalizar_rechaza_vacio_y_largo():
    with pytest.raises(ErrorConsulta): normalizar_sql(" ; ")
    with pytest.raises(ErrorConsulta): normalizar_sql("SELECT " + "1," * 10_001 + "1")

def test_envolver_sobrevive_a_comentario_final():
    assert envolver("SELECT 1 -- fin", 500) == "SELECT * FROM (\nSELECT 1 -- fin\n) AS q LIMIT 501"

@pytest.mark.parametrize("valor,esperado", [
    (Decimal("1.50"), 1.5), (Decimal("NaN"), None), (date(2025, 1, 2), "2025-01-02"),
    (datetime(2025, 1, 2, 3, 4, tzinfo=UTC), "2025-01-02T03:04:00+00:00"),
    (UUID(int=1), "00000000-0000-0000-0000-000000000001"), (b"\x00", None),
    (timedelta(seconds=90), "PT1M30S"), ({"a": [1]}, {"a": [1]}), (None, None),
])
def test_serializar_valor(valor, esperado): ...

def test_serializar_recorta_texto_largo():
    assert serializar_valor("x" * 1_500) == "x" * 1_000 + "…[+500]"
```

- [ ] **Step 2: Write the failing integration tests** (todos con `rol_mcp`)

```python
def test_select_devuelve_filas(rol_mcp): r = ejecutar_select("SELECT 1 AS a"); assert r.columnas == ["a"] and r.filas == [[1]]
def test_tope_de_filas(rol_mcp): r = ejecutar_select("SELECT g FROM generate_series(1, 600) g"); assert r.n_filas == 500 and r.truncado
def test_comentario_final(rol_mcp): assert ejecutar_select("SELECT 1 AS a -- fin").filas == [[1]]
def test_cte(rol_mcp): assert ejecutar_select("WITH x AS (SELECT 2 AS b) SELECT b FROM x").filas == [[2]]
def test_varias_sentencias_rechazadas(rol_mcp): err = _err("SELECT 1; DROP TABLE licitaciones"); assert err.sqlstate == "42601"
def test_insert_falla(rol_mcp): assert _err("INSERT INTO licitaciones (id_externo) VALUES ('x') RETURNING 1").sqlstate in {"25006", "42501", "42601"}
def test_tabla_oculta_denegada(rol_mcp): assert _err("SELECT * FROM api_keys").sqlstate == "42501"
def test_columna_excluida_denegada(rol_mcp): assert _err("SELECT password_hash FROM users").sqlstate == "42501"
def test_columnas_permitidas_de_users(rol_mcp): ejecutar_select("SELECT id, email, is_admin FROM users")
def test_ve_dos_organizaciones(rol_mcp, dos_organizaciones_con_pursuits): assert ejecutar_select("SELECT DISTINCT organization_id FROM pursuits").n_filas == 2
def test_timeout(rol_mcp): err = _err("SELECT pg_sleep(5)"); assert err.sqlstate == "57014" and err.pista
def test_tipos_reales(rol_mcp): ejecutar_select("SELECT '{\"a\":1}'::jsonb, ARRAY[1,2], gen_random_uuid(), '\\x00'::bytea, now(), interval '1 day'")
def test_respuesta_acotada(rol_mcp):
    r = ejecutar_select("SELECT repeat('x', 1000) AS t FROM generate_series(1, 500)")
    assert len(json.dumps(r.como_dict())) <= MAX_CHARS_RESPUESTA and r.truncado
```

`_err(sql)` es un helper local que ejecuta y devuelve el `ErrorConsulta`; `dos_organizaciones_con_pursuits` es una fixture local que siembra dos organizaciones con un pursuit cada una, con los helpers que ya usa `tests/test_rls_tenant_scope_integration.py`.

- [ ] **Step 3: Run to verify they fail** — `ENV=dev pytest tests/test_consulta_libre.py tests/test_consulta_libre_integration.py -v` → FAIL (módulo inexistente).
- [ ] **Step 4: Implement** `db/consulta_libre.py`. El pool es un `psycopg_pool.ConnectionPool` perezoso con `max_size=5`, `kwargs=_pg_connect_kwargs(url, read_only=True)` y autocommit, protegido por un `threading.Lock` como `_get_pg_read_pool`. Si `mcp_database_url()` está vacía: `ErrorConsulta(None, "MCP_DATABASE_URL no configurada", None)`. Los `psycopg.Error` se traducen a `ErrorConsulta(e.sqlstate, primera línea de e.diag.message_primary, PISTAS.get(sqlstate))`. El recorte a `MAX_CHARS_RESPUESTA` quita filas del final (búsqueda por tamaño acumulado de `json.dumps` de cada fila) y marca `truncado`.
- [ ] **Step 5: Verify** — los dos ficheros en PASS; `make lint typecheck`.
- [ ] **Step 6: Commit** — `feat(db): ejecutor de SELECT libre con el rol tenderflow_mcp`

---

### Task 4: Glosario y tools de esquema

**Files:**
- Create: `mcp_server/glosario.md`, `mcp_server/tools/__init__.py`, `mcp_server/tools/esquema.py`
- Modify: `db/consulta_libre.py` (introspección)
- Test: `tests/test_mcp_tools_esquema.py` (unit), `tests/test_mcp_tools_esquema_integration.py`

**Interfaces:**
- Consumes: `CATALOGO`, `tablas_visibles`, `entrada_visible` (Task 2); `ejecutar_select`, `ErrorConsulta` (Task 3).
- Produces:
  - En `db/consulta_libre.py` (pool MCP): `columnas_de(tabla: str) -> list[dict[str, str | bool]]` (`nombre`, `tipo`, `nulo`), `claves_foraneas_de(tabla: str) -> list[dict[str, str]]` (`columna`, `tabla_destino`, `columna_destino`), `filas_aproximadas(tablas: Sequence[str]) -> dict[str, int]` (`pg_class.reltuples`, `-1` → `0`). Las tres con parámetros enlazados, nunca interpolando.
  - `class ErrorHerramienta(Exception): mensaje: str; pista: str | None` en `mcp_server/tools/__init__.py`.
  - `glosario() -> str` (lee `glosario.md` una vez, con `functools.cache`)
  - `describir_esquema() -> dict[str, JSONValue]`: `{"dominios": [{"dominio", "tablas": [{"tabla", "descripcion", "filas_aprox"}]}], "glosario": str}`
  - `describir_tabla(tabla: str) -> dict[str, JSONValue]`: `{"tabla", "dominio", "descripcion", "columnas", "claves_foraneas", "ejemplo": ResultadoConsulta.como_dict()}`. Solo columnas permitidas, y el ejemplo es `SELECT <cols permitidas entre comillas> FROM "<tabla>" LIMIT 3`.
- `glosario.md` cubre, con un ejemplo SQL corto cada uno: duplicados entre fuentes y cómo contar solo la canónica (leer `services/sql_fragments.py::_criterios_canonicos_sql`, `licitaciones_duplicados` y ADR-026); semántica de `importe` frente a `importe_adjudicado` y la base con o sin IVA (ADR-032); valores de `estado`; claves de unión (`id_externo`, NIF, DIR3, `organization_id`); qué es un pursuit y sus tablas hijas; que `tecnologia` es un CSV de códigos; las fechas guardadas como `text`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("tabla", ['users"; --', "api_keys", "pg_shadow", "LICITACIONES", "", "mcp_oauth_tokens"])
def test_describir_tabla_rechaza_fuera_de_catalogo(tabla):
    with pytest.raises(ErrorHerramienta) as e: describir_tabla(tabla)
    assert "describir_esquema" in (e.value.pista or "")

def test_glosario_no_vacio_y_cubre_canonica_e_importe():
    g = glosario(); assert "canónica" in g and "importe" in g

# integration (rol_mcp)
def test_describir_esquema_lista_solo_visibles(rol_mcp):
    nombres = {t["tabla"] for d in describir_esquema()["dominios"] for t in d["tablas"]}
    assert "licitaciones" in nombres and "api_keys" not in nombres

def test_describir_tabla_users_sin_password_hash(rol_mcp):
    d = describir_tabla("users")
    assert "password_hash" not in {c["nombre"] for c in d["columnas"]}
    assert "password_hash" not in d["ejemplo"]["columnas"]
```

- [ ] **Step 2: Run to verify they fail** — `ENV=dev pytest tests/test_mcp_tools_esquema*.py -v` → FAIL.
- [ ] **Step 3: Implement** las tres funciones de introspección, `esquema.py` y `glosario.md`.
- [ ] **Step 4: Verify** — PASS.
- [ ] **Step 5: Commit** — `feat(mcp): glosario y tools describir_esquema / describir_tabla`

---

### Task 5: Tools de dominio

**Files:**
- Create: `services/rag/fragmentos.py`, `services/expediente.py`, `mcp_server/tools/dominio.py`
- Modify: `services/rag/context.py` (exponer un ranking público si hace falta; ver Step 3)
- Test: `tests/test_rag_fragmentos.py` (unit, repos falsos), `tests/test_expediente_integration.py`, `tests/test_mcp_tools_dominio_integration.py`

**Interfaces:**
- Consumes: `LicitacionesRepository.search_advanced(...)` y `.search_fts_docs(query, limit=…)` (`db/repositories/licitaciones.py:1564,1823`); `DocumentosRepository.list_chunks_by_licitacion(licitacion_id, limit=200)`; `services.rag.context._rank_by_question`; `services.licitaciones.get_licitacion_detail`; `db.repositories.licitaciones.lotes_de`; `db.repositories.dedupe.canonical_for`; `AdjudicacionesRepository.list_for_licitacion`; `CondicionesOficialesRepository.get`; `TenderFactSheetsRepository.get` (comprobar el nombre de la clase en `db/repositories/tender_fact_sheets.py`).
- Produces:
  - `@dataclass(frozen=True) class Fragmento: id_externo: str; documento: str | None; tipo: str | None; pagina: int | None; texto: str` (texto recortado a 1 500 caracteres)
  - `fragmentos_de_pliego(pregunta: str, *, id_externo: str | None = None, limite: int = 10) -> list[Fragmento]`. Con `id_externo`: los chunks de ese expediente ordenados por `_rank_by_question`. Sin él: los 5 primeros expedientes de `search_fts_docs(pregunta, limit=5)` y sus chunks, mezclados por rango y cortados en `limite`.
  - `expediente_completo(id_externo: str) -> dict[str, Any] | None` con las claves `licitacion`, `canonica`, `lotes`, `adjudicaciones`, `criterios`, `solvencia`, `garantias`, `ficha_pliego`.
  - En `mcp_server/tools/dominio.py` (cada una devuelve `dict[str, JSONValue]` y valida su entrada con un modelo Pydantic):
    - `buscar_licitaciones(texto: str, estado: list[str] | None = None, ccaa: list[str] | None = None, tecnologia: list[str] | None = None, importe_min: float | None = None, importe_max: float | None = None, desde: str | None = None, hasta: str | None = None, limite: int = 20) -> dict`, con `limite` entre 1 y 50 y fechas `YYYY-MM-DD`. Devuelve `{"total", "resultados": [...]}`. Su docstring (que es la descripción de la tool) dice que solo cubre licitaciones con tecnología asignada y remite a `consultar_sql`.
    - `buscar_en_pliegos(pregunta: str, id_externo: str | None = None, limite: int = 10) -> dict`, con `limite` entre 1 y 20.
    - `ficha_licitacion(id_externo: str) -> dict`; un expediente inexistente → `ErrorHerramienta("No existe la licitación …", pista="búscala con buscar_licitaciones")`.
  - Todos los valores pasan por `db.consulta_libre.serializar_valor` (recursivo sobre dicts y listas).

- [ ] **Step 1: Write the failing tests**

```python
# unit — repos falsos inyectados por monkeypatch
def test_fragmentos_con_expediente_ordena_por_pregunta(): ...  # el chunk que menciona «solvencia» sale primero
def test_fragmentos_sin_expediente_mezcla_y_respeta_limite(): ...  # 3 expedientes × 6 chunks, limite=10 → 10
def test_fragmentos_sin_chunks_devuelve_lista_vacia(): ...

# integration
def test_expediente_completo_inexistente_es_none(tmp_db): assert expediente_completo("NO-EXISTE") is None
def test_expediente_completo_trae_lotes_y_adjudicaciones(tmp_db, licitacion_con_lote_y_adjudicacion): ...
def test_tool_buscar_licitaciones_limite_maximo(tmp_db):
    with pytest.raises(ValidationError): buscar_licitaciones("x", limite=51)
def test_tool_ficha_inexistente(tmp_db):
    with pytest.raises(ErrorHerramienta): ficha_licitacion("NO-EXISTE")
def test_tool_ficha_serializa_a_json(tmp_db, licitacion_con_lote_y_adjudicacion):
    json.dumps(ficha_licitacion(ID))
```

Las fixtures de siembra reutilizan los helpers de `tests/` que ya insertan licitaciones, lotes y adjudicaciones (buscarlos con `python scripts/code_map.py simbolo` sobre `upsert_licitaciones` o similares).

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.** Si usar `_rank_by_question` desde otro módulo choca con ruff (acceso a privado), renombrarlo a `rank_by_question` en `services/rag/context.py`, actualizar sus usos y dejar `_rank_by_question = rank_by_question` solo si hay tests que lo importen.
- [ ] **Step 4: Verify** — PASS; `make check-layers` (`services/` no importa de `mcp_server/`).
- [ ] **Step 5: Commit** — `feat(mcp): tools buscar_licitaciones, buscar_en_pliegos y ficha_licitacion`

---

### Task 6: Persistencia OAuth (migración v150 y `db/mcp_oauth.py`)

**Files:**
- Create: `db/alembic/versions/v150_mcp_oauth.py`, `db/mcp_oauth.py`
- Modify: `docs/database-schema.md` (`make schema-doc`), `mcp_server/catalogo.py` (ya OCULTA desde la Task 2; comprobarlo)
- Test: `tests/test_mcp_oauth_integration.py`

**Interfaces:**
- Migración `v150_mcp_oauth` (Revises `v149_ledger_borrado_org`; DIALECT-GUARDED y `ENABLE ROW LEVEL SECURITY` como `v145_cuenta_organos`):
  - `mcp_oauth_clients(client_id text PK, client_name text, redirect_uris jsonb NOT NULL, datos jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now())`
  - `mcp_oauth_tokens(token_hash text PK, kind text NOT NULL CHECK (kind IN ('pendiente','code','access','refresh')), client_id text NOT NULL REFERENCES mcp_oauth_clients ON DELETE CASCADE, user_id integer REFERENCES users ON DELETE CASCADE, family_id text, scopes jsonb NOT NULL DEFAULT '[]', datos jsonb, expires_at timestamptz NOT NULL, revoked_at timestamptz, created_at timestamptz NOT NULL DEFAULT now())`, con índices en `(user_id)`, `(family_id)` y `(expires_at)`. `user_id` es nulo solo en `pendiente`.
- Produces (todas síncronas; las llama `run_db`/`anyio.to_thread` desde el proveedor):
  - `hash_token(token: str) -> str` (sha256 hex)
  - `guardar_cliente(client_id: str, client_name: str | None, redirect_uris: list[str], datos: Mapping[str, object]) -> None` (upsert idempotente)
  - `obtener_cliente(client_id: str) -> dict[str, Any] | None`
  - `guardar_token(token: str, *, kind: TipoToken, client_id: str, user_id: int | None, family_id: str | None, scopes: list[str], datos: Mapping[str, object] | None, expires_at: datetime) -> None`
  - `obtener_token(token: str, kind: TipoToken) -> dict[str, Any] | None` (vigente: sin revocar y sin caducar)
  - `consumir_token(token: str, kind: TipoToken) -> tuple[dict[str, Any] | None, bool]` → `(fila, reutilizado)`. Un único `UPDATE … SET revoked_at = now() WHERE token_hash = %s AND kind = %s AND revoked_at IS NULL AND expires_at > now() RETURNING *`; si no devuelve fila, `reutilizado = True` cuando existe con `revoked_at` no nulo.
  - `revocar_familia(family_id: str) -> int`, `revocar_de_usuario(user_id: int) -> int`, `revocar_token(token: str) -> None`
  - `TipoToken = Literal["pendiente", "code", "access", "refresh"]`

- [ ] **Step 1: Write the failing tests**

```python
def test_token_se_guarda_hasheado(tmp_db, cliente):
    guardar_token("secreto", kind="access", ...)
    assert "secreto" not in json.dumps(_todas_las_filas("mcp_oauth_tokens"), default=str)

def test_consumir_codigo_una_sola_vez(tmp_db, cliente, usuario):
    guardar_token("c1", kind="code", ...)
    assert consumir_token("c1", "code")[0] is not None
    fila, reutilizado = consumir_token("c1", "code"); assert fila is None and reutilizado

def test_consumo_concurrente_solo_gana_uno(tmp_db, cliente, usuario):
    guardar_token("r1", kind="refresh", ...)
    with ThreadPoolExecutor(2) as ex:
        res = list(ex.map(lambda _: consumir_token("r1", "refresh")[0], range(2)))
    assert sum(r is not None for r in res) == 1

def test_token_caducado_no_se_obtiene(tmp_db, cliente, usuario): ...  # expires_at en el pasado → None
def test_revocar_familia_y_usuario(tmp_db, cliente, usuario): ...  # cuentas devueltas y obtener_token → None
def test_borrar_usuario_borra_sus_tokens(tmp_db, cliente, usuario): ...
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** la migración y `db/mcp_oauth.py`; `make schema-doc`.
- [ ] **Step 4: Verify** — PASS; `tests/test_mcp_catalogo_integration.py` y `tests/test_rls_tenant_scope_integration.py` siguen en PASS (las tablas no tienen `organization_id`).
- [ ] **Step 5: Commit** — `feat(db): tablas y repositorio OAuth del MCP (v150)`

---

### Task 7: Proveedor OAuth y login con Google

**Files:**
- Create: `mcp_server/auth/__init__.py`, `mcp_server/auth/proveedor.py`, `mcp_server/auth/google.py`
- Modify: `services/auth.py` (añadir `acceso_oauth_permitido`), `api/routes/auth.py:103-118` (`_oauth_access_allowed` delega en la función nueva vía `run_db`)
- Test: `tests/test_mcp_proveedor_oauth.py` (unit, almacén y Google falsos), `tests/test_acceso_oauth_permitido.py`

**Interfaces:**
- Consumes: Task 6 entera; `shared.auth_core.generate_oauth_state()`, `verify_oauth_state(state)`, `oauth_state_nonce(state)`, `verify_google_id_token(jwt, audience=…, expected_nonce=None)`, `validate_google_id_token(...)`, `oauth_email_allowed(email)`; `db.users.get_active_user_by_email_ci(email)`, `db.users.get_user_by_id(user_id)`; `db.access_grants.is_access_granted(email)`; `settings.GOOGLE_CLIENT_ID`, `settings.GOOGLE_CLIENT_SECRET`; `mcp_google_redirect_uri()`.
- Produces:
  - `services.auth.acceso_oauth_permitido(email: str) -> bool`: `oauth_email_allowed(email) or is_access_granted(email)`; cualquier excepción del lado dinámico → `log.exception("oauth_dynamic_allowlist_unavailable")` y `False`.
  - `class AlmacenOAuth(Protocol)` con los métodos de la Task 6 (los mismos nombres y firmas) y `class AlmacenOAuthPostgres` que delega en `db.mcp_oauth`.
  - `@dataclass(frozen=True) class IdentidadGoogle: email: str; sub: str`
  - `class ClienteGoogle(Protocol)`: `def url_autorizacion(self, state: str) -> str` y `async def identidad(self, code: str) -> IdentidadGoogle | None` (intercambia el código en `https://oauth2.googleapis.com/token` con `httpx`, verifica el `id_token` con `verify_google_id_token` y exige `email_verified`). Implementación: `ClienteGoogleReal` en `google.py`, con scope `openid email`, `prompt=select_account` y `redirect_uri = mcp_google_redirect_uri()`.
  - `class ProveedorTenderFlow(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken])`, con `__init__(self, almacen: AlmacenOAuth, google: ClienteGoogle, *, usuarios: Callable[[str], dict[str, Any] | None] = get_active_user_by_email_ci, usuario_por_id: Callable[[int], dict[str, Any] | None] = get_user_by_id, acceso_permitido: Callable[[str], bool] = acceso_oauth_permitido, reloj: Callable[[], float] = time.time, auditar: Callable[[str, int | None, Mapping[str, object]], None] = auditar_oauth)`:
    - `auditar_oauth(accion, user_id, detalle)` llama a `db.audit.log_action(user_key=f"user:{user_id}" o "anon", session_hash="mcp", action=accion, detail=json.dumps(detalle), user_id=user_id)`. Acciones: `mcp.login_ok`, `mcp.login_denegado` (con `motivo` y el email), `mcp.token_emitido`, `mcp.token_rotado`, `mcp.refresh_reutilizado`, `mcp.token_revocado`. Nunca se audita el valor de un token.
    - Las llamadas al almacén y a `usuarios`/`usuario_por_id` son síncronas: el proveedor las ejecuta con `anyio.to_thread.run_sync`.
    - `register_client`: valida los `redirect_uris` (ver Global Constraints) → `RegistrationError("invalid_redirect_uri", …)` y guarda `client_info.model_dump(mode="json")`.
    - `get_client`: `OAuthClientInformationFull.model_validate(fila["datos"])`.
    - `authorize`: genera `state = generate_oauth_state()`, guarda un `pendiente` (token = `oauth_state_nonce(state)`, TTL 10 min, `datos` = `params.model_dump(mode="json")`) y devuelve `google.url_autorizacion(state)`.
    - `async def completar_login(self, state: str, code: str | None, error: str | None) -> str`: devuelve la URL a la que redirigir. Verifica el state y consume el `pendiente`; obtiene la identidad de Google; exige `usuario_activo_admin(email)`. Si falla tras recuperar el pendiente: `construct_redirect_uri(redirect_uri, error="access_denied", state=state_original)`. Si falla antes (state inválido): lanza `AuthorizeError("invalid_request", …)`. En éxito: código aleatorio (`secrets.token_urlsafe(32)`), guardado 60 s con `subject=str(user_id)` y `datos` (`code_challenge`, `redirect_uri`, `redirect_uri_provided_explicitly`, `resource`), y `construct_redirect_uri(redirect_uri, code=…, state=state_original)`.
    - `load_authorization_code` / `exchange_authorization_code`: el exchange usa `consumir_token`; si no hay fila, `TokenError("invalid_grant")`. Emite access (1 h) y refresh (30 d) con un `family_id` nuevo y devuelve `OAuthToken(access_token, token_type="Bearer", expires_in=3600, refresh_token, scope)`.
    - `load_refresh_token` / `exchange_refresh_token`: `consumir_token("refresh")`; si `reutilizado`, `revocar_familia` + `TokenError("invalid_grant")`. Si no, emite un par nuevo en la misma familia.
    - `load_access_token(token)`: `obtener_token(…, "access")` y además `usuario_sigue_admin(user_id)` con caché de 60 s por `user_id` (que use `reloj`). Devuelve `AccessToken(..., subject=str(user_id))` o `None`.
    - `revoke_token`: revoca la familia del token.
    - `exchange_identity_assertion`: no soportado (`TokenError("unsupported_grant_type")`).
  - `usuario_activo_admin(email) -> int | None` y `usuario_sigue_admin(user_id) -> bool`: métodos privados que aplican la regla de acceso de Global Constraints.

- [ ] **Step 1: Write the failing tests** (`AlmacenEnMemoria` y `GoogleFalso` en el propio fichero de test; `pytest.mark.anyio` o el plugin async que ya use la suite)

```python
async def test_registro_rechaza_redirect_http_no_local(proveedor): ...       # http://evil.com/cb → RegistrationError
async def test_registro_acepta_https_y_localhost(proveedor): ...
async def test_authorize_redirige_a_google_con_state(proveedor, cliente): ...
async def test_login_no_admin_vuelve_con_access_denied(proveedor, cliente): ...  # error=access_denied y state original
async def test_login_desactivado_vuelve_con_access_denied(proveedor, cliente): ...
async def test_login_fuera_de_allowlist_vuelve_con_access_denied(proveedor, cliente): ...
async def test_login_email_con_mayusculas_casa(proveedor, cliente): ...       # «Ana@Empresa.ES» → usuario ana@empresa.es
async def test_state_falsificado_lanza_authorize_error(proveedor): ...
async def test_codigo_de_un_solo_uso(proveedor, cliente_con_codigo): ...      # segundo exchange → TokenError invalid_grant
async def test_codigo_caduca_a_los_60s(proveedor, cliente_con_codigo, reloj): ...
async def test_refresh_rota_y_el_viejo_no_vale(proveedor, tokens): ...
async def test_refresh_reutilizado_revoca_familia(proveedor, tokens): ...     # el access de la familia también deja de valer
async def test_access_token_cae_al_perder_admin(proveedor, tokens, reloj): ...  # vale; quitar is_admin; +61 s → None
async def test_access_token_caduca_en_1h(proveedor, tokens, reloj): ...
async def test_audita_login_denegado_y_reutilizacion(proveedor, cliente, tokens): ...  # acciones mcp.login_denegado y mcp.refresh_reutilizado, sin valores de token en detail

def test_acceso_oauth_permitido_fail_closed(monkeypatch): ...  # is_access_granted lanza → False
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** `services/auth.acceso_oauth_permitido`, el cambio en `api/routes/auth.py` (el comportamiento no cambia y sus tests siguen verdes), `google.py` y `proveedor.py`.
- [ ] **Step 4: Verify** — `ENV=dev pytest tests/test_mcp_proveedor_oauth.py tests/test_acceso_oauth_permitido.py tests/test_access_grants_integration.py -v` PASS; `make typecheck`.
- [ ] **Step 5: Commit** — `feat(mcp): proveedor OAuth 2.1 con login de Google solo para admins`

---

### Task 8: Servidor, envoltura de tools y E2E

**Files:**
- Create: `mcp_server/envoltura.py`, `mcp_server/tools/consulta.py`, `mcp_server/servidor.py`, `mcp_server/__main__.py`
- Test: `tests/test_mcp_envoltura.py` (unit), `tests/test_mcp_servidor_integration.py` (E2E en proceso)

**Interfaces:**
- Consumes: las tools de las Tasks 4–5; `ejecutar_select`/`ErrorConsulta` (Task 3); `ProveedorTenderFlow`, `AlmacenOAuthPostgres`, `ClienteGoogleReal` (Task 7); `db.audit.log_action(user_key, session_hash, action, detail="", *, user_id=None)`; `get_rate_limiter()`; `get_access_token()`.
- Produces:
  - `consultar_sql(sql: str) -> dict[str, JSONValue]` en `tools/consulta.py`: `ejecutar_select(sql).como_dict()`; un `ErrorConsulta` se traduce a `ErrorHerramienta`.
  - `herramienta(nombre: str, fn: Callable[P, R]) -> Callable[P, R]` en `envoltura.py`, que envuelve cada tool así:
    1. `user_id = int(get_access_token().subject)` (si no hay token: `ErrorHerramienta`, porque en producción no llega aquí).
    2. Rate limit con las claves `mcp:min:<user_id>` (60/60 s) y `mcp:dia:<user_id>` (1 000/86 400 s). Si se excede, `ErrorHerramienta("Límite de uso alcanzado", pista="espera N s")`.
    3. Ejecuta la función en el threadpool (`anyio.to_thread.run_sync`).
    4. Audita **siempre**, también en error: `log_action(user_key=f"user:{user_id}", session_hash="mcp", action=f"mcp.{nombre}", detail=json.dumps({"args": …, "n_filas": …, "duracion_ms": …, "error": …}), user_id=user_id)`.
    5. Emite `log.info("mcp_tool", tool=nombre, user_id=…, duracion_ms=…, ok=…)` (sin argumentos ni filas: eso va a la auditoría).
    6. Un `ErrorHerramienta` se relanza como `mcp.server.mcpserver.exceptions.ToolError`, con el texto `"{mensaje}\nPista: {pista}"`. Cualquier otra excepción se registra con `log.exception` y sale como `ToolError("Error interno; revisa los logs del servidor")`, sin traza.
  - `crear_servidor(proveedor: OAuthAuthorizationServerProvider[Any, Any, Any] | None = None) -> MCPServer`: nombre `tenderflow`; `instructions` = 3 líneas de uso + `glosario()`; `AuthSettings(issuer_url=mcp_public_url(), resource_server_url=f"{mcp_public_url()}/mcp", client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=["tenderflow:leer"], default_scopes=["tenderflow:leer"]), revocation_options=RevocationOptions(enabled=True), required_scopes=["tenderflow:leer"], validate_token_resource=False)`; registra las seis tools con `server.tool(name=…, annotations=ToolAnnotations(...))`.
  - Rutas extra con `@server.custom_route`: `GET /healthz` → `{"ok": true}`; `GET /oauth/google/callback` → `RedirectResponse(await proveedor.completar_login(state, code, error))`, y un `AuthorizeError` → página HTML 400 mínima.
  - `crear_app() -> Starlette`: `crear_servidor().streamable_http_app(streamable_http_path="/mcp", json_response=True, stateless_http=True, host="0.0.0.0")` (comprobar si `transport_security` necesita el host público en `allowed_hosts` para no rechazar el `Host` de Render).
  - `validar_configuracion() -> list[str]`: las variables que faltan entre `MCP_DATABASE_URL`, `MCP_PUBLIC_URL`, `MCP_GOOGLE_REDIRECT_URI`, `DATABASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` y `SIGNING_KEY`. `__main__` aborta con `SystemExit` si `ENV=prod` y la lista no está vacía; después `uvicorn.run(crear_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))`.

- [ ] **Step 1: Write the failing unit tests** (envoltura, con `get_access_token`, el limiter y `log_action` parcheados)

```python
async def test_audita_exito_con_sql_y_filas(): ...      # action == "mcp.consultar_sql", detail contiene el SQL y n_filas
async def test_audita_tambien_el_error(): ...
async def test_rate_limit_por_minuto(): ...             # check() → False → ToolError con «Límite de uso»
async def test_excepcion_inesperada_no_filtra_traza(): ...  # el mensaje no contiene «Traceback» ni el texto de la excepción
async def test_falta_config_en_prod(monkeypatch): ...   # validar_configuracion() enumera las ausentes
```

- [ ] **Step 2: Write the failing E2E tests** (`rol_mcp` + `tmp_db`; `starlette.testclient.TestClient(crear_app())` como context manager para que corra el lifespan; JSON-RPC a mano: `initialize`, `notifications/initialized`, `tools/list`, `tools/call`; un token de acceso sembrado con `AlmacenOAuthPostgres` para un usuario admin)

```python
def test_sin_token_401_con_resource_metadata(app_cliente):
    r = app_cliente.post("/mcp", json=_initialize())
    assert r.status_code == 401 and "resource_metadata" in r.headers["www-authenticate"]

def test_metadatos_oauth_publicados(app_cliente):
    assert app_cliente.get("/.well-known/oauth-authorization-server").json()["registration_endpoint"]
    assert app_cliente.get("/.well-known/oauth-protected-resource/mcp").status_code == 200

def test_lista_las_seis_tools_de_solo_lectura(app_cliente, token_admin):
    tools = _tools_list(app_cliente, token_admin)
    assert {t["name"] for t in tools} == {"describir_esquema", "describir_tabla", "consultar_sql",
                                          "buscar_licitaciones", "buscar_en_pliegos", "ficha_licitacion"}
    assert all(t["annotations"]["readOnlyHint"] for t in tools)

def test_consultar_sql_devuelve_filas_y_audita(app_cliente, token_admin): ...
def test_token_de_no_admin_rechazado(app_cliente, token_ex_admin): ...  # 401
def test_healthz(app_cliente): assert app_cliente.get("/healthz").json() == {"ok": True}
```

Ajusta la ruta exacta de `oauth-protected-resource` a lo que publique el SDK.

- [ ] **Step 3: Run to verify they fail.**
- [ ] **Step 4: Implement** los cuatro ficheros.
- [ ] **Step 5: Verify** — los dos ficheros en PASS. Prueba manual: `ENV=dev MCP_PUBLIC_URL=http://localhost:8080 … python -m mcp_server` y `npx @modelcontextprotocol/inspector` contra `http://localhost:8080/mcp`; el flujo OAuth abre Google (requiere el redirect URI `http://localhost:8080/oauth/google/callback` en el cliente de dev). Si no hay credenciales de dev, anotarlo como control no ejecutado.
- [ ] **Step 6: Commit** — `feat(mcp): servidor Streamable HTTP con auditoría, rate limit y E2E`

---

### Task 9: Revocación manual, despliegue y documentación

**Files:**
- Create: `scripts/mcp_revocar.py`, `docs/adr/ADR-036-acceso-interno-por-mcp.md`, `docs/runbooks/mcp-interno.md`
- Modify: `docker/Dockerfile.api` (`COPY` de `requirements-mcp.txt` junto a los otros lockfiles; el `ARG REQUIREMENTS_FILE` ya permite elegirlo), `render.yaml` (servicio `tenderflow-mcp`), `.github/workflows/deploy.yml` (deploy hook `RENDER_MCP_DEPLOY_HOOK_URL` tras verificar la API, con el mismo patrón que el worker), `docs/AGENT_PLAYBOOK.md` (área `mcp_server/`), `docs/IMPROVEMENT_BACKLOG.md` (solo si algún ítem lo cubre), `docs/STATUS.md` (`make status`)
- Test: `tests/test_mcp_revocar.py`

**Interfaces:**
- Consumes: `db.users.get_user_by_email`, `db.mcp_oauth.revocar_de_usuario`, `db.audit.log_action`.
- Produces: `scripts/mcp_revocar.py --email <email>` → imprime `Revocados N tokens de <email>` y sale con 0; un email inexistente sale con 1. Registra `mcp.revocacion_manual` en la auditoría.
- `render.yaml`, servicio `tenderflow-mcp`: `type: web`, `runtime: docker`, `dockerfilePath: docker/Dockerfile.api`, `dockerContext: .`, `buildArgs`/`envVars` con `REQUIREMENTS_FILE=requirements-mcp.txt`, `dockerCommand: python -m mcp_server`, `plan: starter`, `autoDeploy: false`, `healthCheckPath: /healthz`, `envVars` (`sync: false` para secretos): `ENV=prod`, `DATABASE_URL`, `MCP_DATABASE_URL`, `MCP_PUBLIC_URL`, `MCP_GOOGLE_REDIRECT_URI`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SIGNING_KEY`, `REDIS_URL`. Comentario de cabecera al estilo del fichero, con la fecha y lo que está sin verificar en Render.
- ADR-036: contexto (equipo interno, remoto, multi-dispositivo), decisión (las secciones 2–4 del spec, resumidas), alternativas descartadas (solo tools curadas, MCP de terceros, montado dentro de `tenderflow-api`), consecuencias (riesgo aceptado: datos de clientes viajan al proveedor del LLM del admin; segundo camino de lectura a la BD; un servicio más) y relación con ADR-022/025/034.
- Runbook: los 4 pasos manuales del spec §6 con comandos exactos (`psql "$DATABASE_URL" -f scripts/setup_pg_role_mcp.sql` tras sustituir la contraseña; el DSN de Supavisor `tenderflow_mcp.<project-ref>`; el redirect URI en Google Cloud; el alta en Render; el alta en claude.ai: Configuración → Conectores → Añadir conector personalizado → `https://<host>/mcp`), la revocación con `mcp_revocar.py`, la rotación de la contraseña del rol, el diagnóstico (401 en bucle, `42501` inesperado, timeouts) y la consulta de auditoría (`SELECT … FROM audit_log WHERE action LIKE 'mcp.%'`).

- [ ] **Step 1: Write the failing test**

```python
def test_revocar_usuario_inexistente_sale_con_1(tmp_db): assert main(["--email", "nadie@x.es"]) == 1
def test_revocar_cuenta_y_audita(tmp_db, usuario_con_dos_tokens, capsys):
    assert main(["--email", usuario_con_dos_tokens.email]) == 0
    assert "Revocados 2 tokens" in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify it fails** — FAIL (script inexistente).
- [ ] **Step 3: Implement** el script, `Dockerfile.api`, `render.yaml`, `deploy.yml`, ADR, runbook y el playbook.
- [ ] **Step 4: Verify** — test en PASS; `docker build -f docker/Dockerfile.api --build-arg REQUIREMENTS_FILE=requirements-mcp.txt .` si hay Docker (si no, anotarlo como control no ejecutado); `make check`, `make check-layers`, `make check-agent-docs`, `make status`; `python scripts/check_api_surface.py` sin cambios.
- [ ] **Step 5: Commit** — `feat(mcp): revocación manual, despliegue en Render y documentación`

---

### Task 10 (tras desplegar, con datos de producción): evaluación

**Precondición:** el servicio desplegado, el conector dado de alta y al menos un admin con acceso. No se ejecuta en CI.

- [ ] **Step 1:** Escribir `mcp_server/evaluacion.xml` con 10 preguntas siguiendo el formato del skill `mcp-builder` (`reference/evaluation.md`): independientes, de solo lectura, que exijan varias llamadas y con una respuesta estable y verificable. Por ejemplo: ganador por importe adjudicado de un CPV y un año ya cerrados; número de expedientes canónicos de un órgano en un trimestre cerrado; un dato de solvencia de un pliego concreto.
- [ ] **Step 2:** Verificar cada respuesta a mano con `consultar_sql`.
- [ ] **Step 3:** Pasarla con Claude conectado al MCP; por cada fallo, corregir el glosario o la descripción de la tool (no la pregunta) y repetir.
- [ ] **Step 4: Commit** — `test(mcp): evaluación de 10 preguntas y ajustes de glosario`
