---
id: ADR-036
title: "Acceso interno por MCP con rol de solo lectura: un servicio aparte, OAuth propio y el SQL lo limita Postgres"
status: accepted
date: 2026-10-15
deciders: "Daniel Kalitovics"
related:
  - "[[ADR-016-destino-persistencia-supabase]]"
  - "[[ADR-022-frontera-de-persistencia]]"
  - "[[ADR-025-construccion-de-sql-y-pools]]"
  - "[[ADR-030-identidad-user-id-y-oidc]]"
  - "[[ADR-034-rls-por-tenant]]"
tags: [adr]
---

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
   `tenderflow_mcp` (`NOCREATEDB … NOBYPASSRLS CONNECTION LIMIT 5`; nace
   `NOSUPERUSER` y el script lo comprueba, porque desde Postgres 16 tocar ese
   atributo exige ser superusuario y el `postgres` de Supabase no lo es,
   `default_transaction_read_only = on`, `statement_timeout = 15s`,
   `idle_in_transaction_session_timeout = 30s`), con `SELECT` solo sobre lo que
   el catálogo `mcp_server/catalogo.py` marca como visible y una política
   `tenderflow_mcp_read … USING (true)` por tabla (ve todas las organizaciones,
   como se decidió; las tablas con credenciales quedan sin grant). El SQL de
   los grants se **genera** (`scripts/gen_mcp_grants.py` →
   `scripts/setup_pg_role_mcp.sql`) y un ratchet falla si aparece una tabla sin
   clasificar: por defecto, una tabla nueva no se expone. `db/consulta_libre.py`
   envuelve la consulta, la lee por lotes con un cursor de servidor, veta unas
   pocas funciones (ver Consecuencias) y da errores útiles, pero **aunque
   fallara, el rol no puede escribir ni leer lo oculto**. Esta garantía cubre
   `consultar_sql` y las tools de esquema, que son las que corren con el rol
   (ver el párrafo tras la lista).

4. **Seis tools de lectura** (`describir_esquema`, `describir_tabla`,
   `consultar_sql`, `buscar_licitaciones`, `buscar_en_pliegos`,
   `ficha_licitacion`), con 500 filas, 100 000 caracteres de respuesta y 20 000
   de SQL como techos, un rate limit de 60 llamadas por minuto y 1 000 al día
   por usuario, y **cada llamada auditada** (`audit_log`, `action = "mcp.<tool>"`,
   con el SQL completo; ver abajo quién puede leerla) por un único helper
   (`mcp_server.auth.proveedor.auditar_oauth`).

**Dos roles, dos garantías.** `consultar_sql`, `describir_esquema` y
`describir_tabla` corren con `MCP_DATABASE_URL` (rol `tenderflow_mcp`): para
ellas vale el criterio 3 del diseño, «la garantía la da Postgres». El MCP
conserva además `DATABASE_URL` (rol de la app) para las tablas OAuth, la lectura
de `users` y la escritura en `audit_log`, **y para las tres tools de dominio**:
`buscar_licitaciones`, `buscar_en_pliegos` y `ficha_licitacion` leen datos de
negocio con los servicios y repositorios de la aplicación
(`services.licitaciones.search_advanced`, `services.rag.fragmentos`,
`services.expediente`), es decir, con el rol de la app. Ahí lo que impide
escribir o leer secretos no es el rol sino que el SQL es **fijo**, del
repositorio: el LLM solo aporta valores de parámetros enlazados y validados por
los modelos de entrada, nunca texto SQL, y las columnas que salen las elige el
código.

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
- **Funciones vetadas en `consultar_sql`: denylist, riesgo residual
  aceptado.** Algunas funciones de `pg_catalog` que `PUBLIC` puede ejecutar
  tocan estado compartido con la aplicación, y en Supabase un rol no
  superusuario no puede retirarles `EXECUTE` sin afectar a otros roles y a los
  internals de la plataforma. Los cerrojos de aviso son comunes a todos los
  roles: `SELECT pg_advisory_lock(hashtext('tenderflow.audit_log.chain.v1'))`
  bloquearía cada `log_action` de la API (y sus filas se perderían por
  timeout); igual con los cerrojos de `tecnologia_pliego` o de las familias
  OAuth. `pg_notify` y las señales (`pg_cancel_backend`,
  `pg_terminate_backend`) llegan a otros procesos; `pg_logical_emit_message`
  **escribe WAL aun en una transacción de solo lectura** (gigabytes en los 15 s
  de una consulta llenarían el disco y Supabase pasaría la base a solo
  lectura), y `pg_current_xact_id`/`txid_current` asignan un xid cuyo commit
  también escribe; las ranuras de replicación retendrían WAL (hoy las frena
  `NOREPLICATION`). `query_to_xml`, `cursor_to_xml`, `ts_stat`, `ts_rewrite` o
  `dblink` ejecutan SQL escrito en texto, que esquivaría el veto.
  `db/consulta_libre.py` rechaza antes de ejecutar cualquier identificador en
  posición de código con esos nombres (`pg_advisory_*`, `pg_try_advisory_*`,
  `pg_logical_*`, `pg_create_*`, `pg_copy_*`, `pg_replication_*`, `dblink*`,
  `set_config`…), con un
  recorrido léxico que sigue el de Postgres 16 (`scan.l`: `E'…'`, continuación
  de literales, comentarios, cadenas entre dólares; `U&"…"` se rechaza) y que
  los tests contrastan con Postgres real. Es **defensa en profundidad, no
  frontera**: el rol sigue siendo el límite principal (no escribe ni lee lo
  oculto). La lista sale de revisar las funciones de `pg_catalog` que `PUBLIC`
  puede ejecutar en PG16 (2026-10-15, informe de la revisión final); una
  función dañina que falte, una de una extensión instalada después o un cambio
  léxico de una versión futura de Postgres quedaría abierta. No daría lectura de
  lo oculto ni escritura de datos (lo impiden los grants y la solo lectura),
  pero sí podría afectar al servidor compartido: bloquear o señalar a otros
  procesos, o consumir recursos como WAL o disco. Por eso cada extensión nueva
  obliga a repasar la lista. El motor del
  riesgo es la **inyección de instrucciones**: el LLM lee el texto de los
  pliegos (`buscar_en_pliegos`, `documentos.texto`), escrito por terceros, y un
  pliego hostil podría pedirle que ejecute una de esas llamadas.
- **El DCR y `/authorize` no piden autenticación y escriben en la base**:
  topes por campo (registro ≤ 8 KB, petición pendiente ≤ 4 KB), rate limit
  **global** (30 registros/h, 600 autorizaciones/h y 60/h por cliente; no por
  IP, porque la IP de confianza la resuelve `api.middleware`, fuera del alcance
  de las capas del MCP) y una purga horaria (`db.mcp_oauth.purgar`) de lo
  caducado, lo revocado y los clientes huérfanos.
- **La auditoría escribe en la misma cadena firmada que la API**
  (`AUDIT_HMAC_KEY` compartida): el MCP se niega a arrancar en prod sin ella.
- **Deuda conocida**, anotada en el runbook y en el backlog: el
  `client_secret` del DCR queda legible en `mcp_oauth_clients.datos` (oculto
  para el rol MCP); los logs de acceso de uvicorn son texto plano e incluyen la
  query string del callback de OAuth; una única celda enorme del resultado de
  `consultar_sql` se carga entera en memoria antes de recortarse.
  *Actualización 2026-10-29:* el `client_secret` ya no se guarda (se deriva de
  `SIGNING_KEY` y el `client_id`), el log de acceso de uvicorn está apagado y
  las celdas `text`/`varchar`/`xml` se recortan en Postgres; quedan los
  `json`/`jsonb` y los arrays enormes (runbook `mcp-interno.md` §7). Después,
  ese mismo día, también los `json`/`jsonb` y los arrays de tipos nativos.
  *Actualización 2026-11-02 (auditoría de seguridad):* los tipos sin tope que
  no son texto (`bit`, `varbit`, `tsvector`, `tsquery`, `jsonpath`, `record`)
  también se recortan en Postgres y los `bytea` ni se transfieren; el DCR y
  `/authorize` tienen además cuota **por IP** (10 registros/h y 30
  autorizaciones/h; el middleware del propio MCP lee la IP del último salto
  global de `X-Forwarded-For`, así que ya no depende de `api.middleware`); el
  login rechaza las cuentas con TOTP confirmado y las ligadas a otro proveedor
  o a otro `sub` de Google, y el callback de Google exige la cookie `mcp_login`
  (HMAC del nonce, `Path` del callback, `SameSite=Lax`) que `/authorize` fijó en
  el navegador que inició el flujo — sin pantalla de consentimiento por cliente,
  que sigue pendiente; las tools que pueden devolver texto de terceros
  declaran `open_world_hint` y marcan su salida con `contenido_no_confiable:
  true`; y `consultar_sql` impone el techo de 15 s si el rol llega sin
  `statement_timeout`.
