# ADR-036 — Acceso interno por MCP con rol de solo lectura: un servicio aparte, OAuth propio y el SQL lo limita Postgres

- **Estado:** aceptado
- **Fecha:** 2026-10-15
- **Relacionado:** [ADR-016](ADR-016-destino-persistencia-supabase.md)
  (Supabase y sus pools), [ADR-022](ADR-022-frontera-de-persistencia.md) (todo
  el SQL vive en `db/`), [ADR-025](ADR-025-construccion-de-sql-y-pools.md)
  (pools y construcción del SQL), [ADR-030](ADR-030-identidad-user-id-y-oidc.md)
  (identidad por `user_id`), [ADR-034](ADR-034-rls-por-tenant.md) (RLS por
  tenant, que este acceso atraviesa a propósito).
- **Diseño completo:** [`docs/superpowers/specs/2026-10-15-mcp-interno-design.md`](../superpowers/specs/2026-10-15-mcp-interno-design.md).
  Operación: [`docs/runbooks/mcp-interno.md`](../runbooks/mcp-interno.md).

---

## Contexto

El equipo interno (tres personas, todas con `users.is_admin = 1`) quiere
hacerle preguntas en lenguaje natural a la base de datos de TenderFlow desde
Claude u otro LLM, **de forma remota y desde varios dispositivos** —web,
escritorio y móvil—, no solo desde un checkout local con credenciales. Las
preguntas son analíticas y abiertas («¿qué empresas ganaron más importe en
Andalucía en 2025?»), y cruzan mercado **y** datos de clientes, de varias
organizaciones.

Lo que hay hoy no sirve para eso:

- La API REST (`api/`) está pensada para el frontend: rutas cerradas, una
  organización por petición (ADR-034), autenticación por sesión o API key. No
  hay una ruta para «cualquier consulta agregada».
- Una conexión local a Supabase obliga a repartir el DSN con permisos de
  escritura y solo funciona en el ordenador que lo tiene.

El protocolo MCP (Model Context Protocol) es lo que los clientes de LLM
entienden para conectarse a una herramienta remota, con OAuth 2.1 para la
identidad. claude.ai lo admite como «conector personalizado», que la persona
añade una vez y le aparece en todos sus dispositivos.

## Decisión

Se añade el paquete `mcp_server/` y un servicio Render, `tenderflow-mcp`, que lo
ejecuta con `python -m mcp_server`. Resumen de las secciones 2–4 del diseño:

1. **Un proceso aparte, capa más alta.** `mcp_server` va después de `api` en
   `scripts/check_layers.py::CAPAS`, con las aristas prohibidas
   `("mcp_server", "api")` y `("mcp_server", "scraper")`: lo que ambos necesiten
   baja a `services/` o `shared/`. No toca `api/` ni la superficie congelada
   (`scripts/check_api_surface.py` no cambia). Transporte Streamable HTTP sin
   estado, respuestas JSON, endpoint `/mcp`; SDK oficial `mcp==2.3.0`, con su
   propio lockfile (`requirements-mcp.in`) para que no entre en la imagen de la
   API. La imagen es la misma (`docker/Dockerfile.api` con
   `REQUIREMENTS_FILE=requirements-mcp.txt`).

2. **El servidor es su propio Authorization Server y delega la identidad en
   Google.** Registro dinámico de clientes (DCR) con una allowlist cerrada de
   `redirect_uris` (callbacks de Claude, loopback para pruebas y las URIs
   exactas de `MCP_REDIRECT_URIS_EXTRA`); PKCE S256; `/authorize` guarda la
   petición y manda a Google con un `state` de un solo uso; el callback exige
   `is_admin = 1`, sin `deactivated_at` y la misma regla de allowlist que el
   login web (`services.access_grants.acceso_oauth_permitido`). Tokens **opacos y
   propios**: código de 60 s de un solo uso, access token de 1 h, refresh de 30
   días con rotación y revocación de la familia si se reutiliza. En la base solo
   se guarda `sha256(token)` (`mcp_oauth_clients`, `mcp_oauth_tokens`, SQL en
   `db/mcp_oauth.py`). Cada petición vuelve a comprobar `is_admin` y
   `deactivated_at` (caché de 60 s): retirar el permiso corta el acceso sin
   esperar a que caduque el token.

3. **La barrera de lectura la pone Postgres, no el código.** Un rol dedicado,
   `tenderflow_mcp` (`NOSUPERUSER … NOBYPASSRLS CONNECTION LIMIT 5`,
   `default_transaction_read_only = on`, `statement_timeout = 15s`,
   `idle_in_transaction_session_timeout = 30s`), con `SELECT` solo sobre lo que
   el catálogo `mcp_server/catalogo.py` marca como visible y una política
   `tenderflow_mcp_read … USING (true)` por tabla (ve todas las organizaciones,
   como se decidió; las tablas con credenciales quedan sin grant). El SQL de
   los grants se **genera** (`scripts/gen_mcp_grants.py` →
   `scripts/setup_pg_role_mcp.sql`) y un ratchet falla si aparece una tabla sin
   clasificar: por defecto, una tabla nueva no se expone. `db/consulta_libre.py`
   envuelve la consulta y da errores útiles, pero **aunque fallara, el rol no
   puede escribir ni leer lo oculto**.

4. **Seis tools de lectura** (`describir_esquema`, `describir_tabla`,
   `consultar_sql`, `buscar_licitaciones`, `buscar_en_pliegos`,
   `ficha_licitacion`), con 500 filas, 100 000 caracteres de respuesta y 20 000
   de SQL como techos, un rate limit de 60 llamadas por minuto y 1 000 al día
   por usuario, y **cada llamada auditada** (`audit_log`, `action = "mcp.<tool>"`,
   con el SQL completo; ver abajo quién puede leerla) por un único helper
   (`mcp_server.auth.proveedor.auditar_oauth`).

El MCP conserva `DATABASE_URL` (rol de la app) **solo** para las tablas OAuth,
la lectura de `users` y la escritura en `audit_log`; los datos de negocio solo se
leen con `MCP_DATABASE_URL`.

## Alternativas descartadas

- **Solo tools curadas, sin SQL libre.** Más seguro por construcción, pero cada
  pregunta nueva exige una tool nueva y el equipo quería preguntar sin
  intermediarios. Con el rol de solo lectura el SQL libre no añade capacidad de
  escritura ni de lectura de secretos, que es lo que se quería evitar. Las tools
  de dominio (`buscar_licitaciones`, `ficha_licitacion`…) se conservan para lo
  que ya existe y se pide a menudo.
- **Un servidor MCP de terceros contra la base de datos** (un MCP genérico de
  Postgres/Supabase). Habría que darle el DSN y quedaría fuera del catálogo de
  visibilidad, del rate limit y de la auditoría propios; los de terceros
  tampoco resuelven la autenticación del equipo (suelen ir por stdio, en local).
- **Montarlo dentro de `tenderflow-api`.** Una ruta `/mcp` en la API compartiría
  proceso, event loop (ADR-035) y credenciales con lo que sirve a los clientes,
  y metería el SDK y su OAuth en la imagen de la API. Un servicio aparte cuesta
  un `starter` de Render, pero separa superficie pública, rol de BD y ritmo de
  despliegue.

## Consecuencias

**Riesgo aceptado: los datos de clientes viajan al proveedor del LLM.** Una
consulta que devuelve filas de clientes envía esas filas al proveedor del
cliente MCP que use cada persona (Anthropic en claude.ai, OpenAI en ChatGPT). Se
decidió con los ojos abiertos («mercado y datos de clientes»): el acceso es solo
de administradores, queda auditado con autor y SQL, y las credenciales y los
secretos no son legibles ni por el rol. Si algún día el ámbito crece más allá de
estas tres personas, esta decisión se revisa antes.

- **`audit_log` es legible por el propio MCP.** Siguiendo «todo visible salvo
  credenciales y secretos», el catálogo marca `audit_log` como visible (la tabla
  entera, incluidas `user_key` y los hashes de la cadena, revisados como no
  secretos). Cualquier admin puede, con
  `consultar_sql`, leer el historial de auditoría de los demás: el SQL que han
  ejecutado por el MCP, los correos de logins denegados y las acciones del resto
  de la aplicación. Se acepta para este equipo; si el ámbito crece, se oculta la
  tabla (una línea en el catálogo y regenerar los grants).
- **Un segundo camino de lectura a la base de datos**, fuera de `api/` y de
  `db/repositories/`, con su propio rol, su propio pool (máximo 5) y sus propias
  garantías. El perímetro de seguridad pasa a ser el catálogo y el SQL generado:
  hay que mantenerlos al día cuando se crean tablas (lo vigila el ratchet).
- **Un servicio más que operar**: variables propias (`MCP_*`), un redirect URI
  más en Google, un deploy hook más en `deploy.yml`, y un runbook. Una caída del
  MCP no afecta a la API, ni al revés: comparten la base de datos, no el
  proceso.
- **La auditoría escribe en la misma cadena firmada que la API**
  (`AUDIT_HMAC_KEY` compartida): el MCP se niega a arrancar en prod sin ella.
- **Deuda conocida**, anotada en el runbook y en el backlog: no hay purga de
  tokens caducados o revocados; el `client_secret` del DCR queda legible en
  `mcp_oauth_clients.datos` (oculto para el rol MCP); los logs de acceso de
  uvicorn son texto plano e incluyen la query string del callback de OAuth.
