# Runbook: MCP interno de TenderFlow

Servidor MCP de **solo lectura** para que el equipo (admins) pregunte a la base
de datos desde Claude u otro cliente MCP, en cualquier dispositivo. Decisión y
alternativas: [ADR-036](../adr/ADR-036-acceso-interno-por-mcp.md). Diseño:
[`docs/superpowers/specs/2026-10-15-mcp-interno-design.md`](../superpowers/specs/2026-10-15-mcp-interno-design.md).

| Qué | Valor |
|---|---|
| Servicio | Render, `tenderflow-mcp` (`render.yaml`), `python -m mcp_server` |
| Host | `https://tenderflow-mcp.onrender.com` (`srv-db9cr1om7kps73ctg25g`) |
| Endpoint MCP | `https://tenderflow-mcp.onrender.com/mcp` |
| Health | `GET /healthz` → `{"ok": true}` |
| Callback de Google | `https://tenderflow-mcp.onrender.com/oauth/google/callback` |
| Rol de BD de lectura | `tenderflow_mcp` (`scripts/setup_pg_role_mcp.sql`, generado) |
| Quién entra | `users.is_admin = 1`, sin `deactivated_at`, y la allowlist de login (`services.access_grants.acceso_oauth_permitido`: `OAUTH_ALLOWED_EMAILS`/`OAUTH_ALLOWED_DOMAINS` **del servicio MCP** o una concesión en `access_grants`) |
| Despliegue | `.github/workflows/deploy.yml`, secret opcional `RENDER_MCP_DEPLOY_HOOK_URL` |

> **Estado a 2026-10-17: en producción.** Pasos 1 a 3 hechos; el primer admin
> conectó desde claude.ai y `consultar_sql` y `buscar_licitaciones` responden
> (el SQL libre corre como `tenderflow_mcp`, en solo lectura). Lo que queda de la
> primera prueba manual está en la sección 6.

---

## 1. Alta (cuatro pasos manuales, del dueño del proyecto)

Orden: el paso 1 exige las migraciones aplicadas; el host de Render solo se
conoce al crear el servicio, así que el paso 3 se hace en dos tiempos (crear con
valores provisionales, y fijar los reales y dar de alta el redirect URI en
Google tras el primer deploy: paso 2); el 4 es por persona y va al final.

### Paso 1 — Crear el rol de solo lectura en Supabase

> **Estado (2026-10-17):** aplicado en producción el 2026-10-16 con el
> placeholder sustituido por `PASSWORD NULL`, para que la contraseña no pasara
> por ningún registro, y la contraseña fijada después desde el SQL Editor de
> Supabase (`ALTER ROLE tenderflow_mcp PASSWORD '…';`).
>
> `extra_float_digits`: Supabase fija `0` en su configuración y, con ese
> valor, las columnas `real` (`adjudicaciones.importe_adjudicado`,
> `licitaciones.importe`…) llegan con 6 cifras significativas (11 782 155 como
> 11 782 200). Lo corrigen los propios pools: `db/connection.py` (API, worker y
> tools de dominio) y `db/consulta_libre.py` (SQL libre) fijan `3` en cada
> conexión y tras cada `RESET ALL`. La línea
> `ALTER ROLE tenderflow_mcp SET extra_float_digits = 3` del script es una
> segunda red; a 2026-10-18 aún no estaba aplicada en producción.
> Re-ejecutar el script (p. ej. tras cambiar el catálogo) no la toca: el
> `CREATE ROLE` solo corre si el rol no existe.

1. Migraciones al día (el script aborta si falta alguna tabla visible del
   catálogo): Actions → *Apply DB migrations (alembic)* con `mode=apply`, o en
   local `alembic upgrade head` con el rol admin.
2. Generar una contraseña fuerte y sustituir el placeholder del fichero
   (**no lo subas al repo con la contraseña puesta**; hazlo en una copia temporal):

   ```bash
   PASS=$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-32)
   sed "s/<GENERAR_PASSWORD_FUERTE>/$PASS/" scripts/setup_pg_role_mcp.sql > /tmp/setup_mcp.sql
   ```

3. Aplicarlo con el rol admin (dueño del schema), de forma atómica; sin
   `--single-transaction` un error a medias deja el rol sin permisos:

   ```bash
   psql -v ON_ERROR_STOP=1 --single-transaction "$DATABASE_ADMIN_URL" -f /tmp/setup_mcp.sql
   shred -u /tmp/setup_mcp.sql   # o rm: contiene la contraseña
   ```

   Es idempotente, pero la contraseña solo se fija al **crear** el rol; para
   cambiarla después, ver la sección 3.
4. Construir `MCP_DATABASE_URL` con el **session pooler de Supavisor**, donde
   el usuario lleva el ref del proyecto (`tenderflow_mcp.<project-ref>`):

   ```
   postgresql://tenderflow_mcp.<project-ref>:<PASS>@<host-del-pooler>:5432/postgres?sslmode=verify-full
   ```

   Con `verify-full` hace falta `DATABASE_SSL_ROOT_CERT` en el servicio (la CA
   de Supabase, `db/certs/README.md`), como en la API.
5. Comprobar con ese DSN (desde tu máquina) que el rol hace lo que debe:

   ```bash
   psql "$MCP_DATABASE_URL" -c "SELECT count(*) FROM licitaciones"      # OK
   psql "$MCP_DATABASE_URL" -c "SELECT * FROM api_keys LIMIT 1"         # ERROR 42501
   psql "$MCP_DATABASE_URL" -c "CREATE TABLE x(a int)"                  # ERROR (permiso / read-only)
   ```

### Paso 2 — Redirect URI en Google Cloud

Google Cloud Console → APIs y servicios → Credenciales → el **mismo** cliente
OAuth que usa la API (`GOOGLE_CLIENT_ID`) → *URI de redireccionamiento
autorizados* → añadir exactamente:

```
https://<host>/oauth/google/callback
```

Sin barra final. Si no coincide al carácter con `MCP_GOOGLE_REDIRECT_URI`,
Google responde `redirect_uri_mismatch` en el login.

### Paso 3 — Crear el servicio en Render

1. **A mano, no con *New → Blueprint*.** Los servicios de producción se crearon
   por el dashboard y el Blueprint **no está vinculado** (checklist de la
   cabecera de `render.yaml`). Una *New Blueprint Instance* sobre este repo
   crearía **todos** los servicios del fichero, incluida una segunda API
   contra la base de producción. Hasta
   que ese checklist esté completo, el alta es: Dashboard → *New → Web
   Service* → este repo, con lo mismo que declara `render.yaml` para
   `tenderflow-mcp`:

   | Campo del dashboard | Valor |
   |---|---|
   | Name | `tenderflow-mcp` |
   | Runtime / Language | **Docker** |
   | Region | Frankfurt (la de los demás servicios) |
   | Branch | `master` |
   | Dockerfile Path | `docker/Dockerfile.api` |
   | Docker Build Context Directory | `.` |
   | Docker Command | `python -m mcp_server` |
   | Instance Type (plan) | Starter |
   | Health Check Path | `/healthz` |
   | Auto-Deploy | **Off** (Settings → Build & Deploy): solo despliega `deploy.yml` |

   Variables de entorno fijas (además de las de la tabla siguiente):
   `ENV=prod`, `APP_PROFILE=mcp`, `REQUIREMENTS_FILE=requirements-mcp.txt`
   (Render la pasa como **build arg** de Docker: es la que mete el SDK `mcp` en
   la imagen; sin ella el arranque falla con `ModuleNotFoundError: mcp`),
   `HEALTHCHECK_PATH=/healthz`, `DB_POOL_SIZE=2` y `DB_READ_POOL_SIZE=2`.
   Cuando el Blueprint se vincule, comprobar que su definición de
   `tenderflow-mcp` coincide con lo creado aquí (si no, el *Sync* lo recrearía).
2. Variables (todas en el servicio `tenderflow-mcp`):

   | Variable | Valor |
   |---|---|
   | `DATABASE_URL` | La misma que `tenderflow-api` (rol de la app: tablas OAuth, `users`, auditoría y las tres tools de dominio, con el SQL fijo de los repositorios) |
   | `DATABASE_SSL_ROOT_CERT` | La misma que la API |
   | `MCP_DATABASE_URL` | El DSN del paso 1 |
   | `APP_PROFILE` | `mcp` (ya en `render.yaml`; perfil propio, ni API ni worker) |
   | `MCP_PUBLIC_URL` | `https://<host>`, **sin barra final y sin `:443`** (al crear: provisional, ver abajo) |
   | `MCP_GOOGLE_REDIRECT_URI` | `https://<host>/oauth/google/callback` (exactamente `MCP_PUBLIC_URL` + `/oauth/google/callback`; al crear: provisional) |
   | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Los mismos que la API |
   | `SIGNING_KEY` | La misma que la API (32+ caracteres) |
   | `REDIS_URL`, `REDIS_PASSWORD` | Los mismos que la API (cuota por usuario y nonce de `state`) |
| `OAUTH_ALLOWED_EMAILS` | **Obligatoria en la práctica.** Los correos de Google de los admins que usan el MCP, separados por comas (o `OAUTH_ALLOWED_DOMAINS` para dominios enteros). El MCP aplica la misma allowlist que el login de la API, pero lee **sus propias** variables: no hereda las de `tenderflow-api`. Sin ninguna, solo entra quien tenga concesión en `access_grants`, y el resto ve «Tenderflow wasn't connected» |
   | `AUDIT_HMAC_KEY` | **La misma que la API.** Otra clave rompe la verificación de la cadena de auditoría; vacía o de menos de 32 caracteres, el MCP no arranca en prod |
   | `MCP_REDIRECT_URIS_EXTRA` | Opcional, ver paso 4 (ChatGPT) |

   En producción ya está hecho: el servicio se creó por la API de Render y,
   como el host salió `tenderflow-mcp.onrender.com` (el nombre del servicio), se
   fijaron los valores reales justo después de crearlo. Si se recrea con otro
   nombre, el host cambia:

   El host `*.onrender.com` solo existe tras crear el servicio. **Crea el
   servicio con valores provisionales** que pasen la validación (por ejemplo
   `MCP_PUBLIC_URL=https://provisional.invalid` y
   `MCP_GOOGLE_REDIRECT_URI=https://provisional.invalid/oauth/google/callback`;
   vacías, el arranque aborta a propósito). Tras el primer deploy, copia el host
   real de la pestaña del servicio, **sustituye esas dos variables por los
   valores reales**, da de alta el redirect URI en Google (paso 2) y relanza el
   deploy. Hasta ese segundo deploy el login no funciona.
3. Comprobar: `curl -sS https://<host>/healthz` → `{"ok":true}`;
   `curl -sS -i https://<host>/mcp` → `401` con `WWW-Authenticate: Bearer
   resource_metadata=…`.
4. **Deploy hook para CI:** Render → `tenderflow-mcp` → Settings → Deploy Hook;
   copiar la URL a un secret del repo con nombre `RENDER_MCP_DEPLOY_HOOK_URL`.
   Mientras no exista, `deploy.yml` omite el MCP con un aviso y no falla.

### Paso 4 — Cada persona añade el conector

- **claude.ai** (web, escritorio y móvil, una vez): Configuración → Conectores
  → *Añadir conector personalizado* → `https://tenderflow-mcp.onrender.com/mcp`.
  Pide el login de Google; solo pasa un admin activo cuyo correo esté en
  `OAUTH_ALLOWED_EMAILS` del servicio MCP (o con concesión en `access_grants`):
  **antes de dar el alta a una persona, añade su correo ahí** (Render →
  `tenderflow-mcp` → *Environment*, guardar redespliega). Aparece en todos sus
  dispositivos.
- **ChatGPT** (donde el plan permita conectores personalizados): la misma URL.
  ChatGPT registra un callback propio **por app**,
  `https://chatgpt.com/connector/oauth/<callback_id>`, que el servidor no admite
  por defecto. Al primer intento el registro falla; copia el `callback_id` que
  muestra ChatGPT, añade esa URI exacta a `MCP_REDIRECT_URIS_EXTRA` en Render
  (varias, separadas por comas), redespliega y reintenta. Los callbacks de
  Claude (`claude.ai`, `claude.com`) y el loopback (`localhost`, `127.0.0.1`,
  para Claude Code y el Inspector) ya están incorporados.

---

## 2. Revocar el acceso a una persona

**Cortar sesiones ya abiertas** (pierde el portátil, cierra todo ahora):

La vía recomendada es la **shell del servicio `tenderflow-mcp`** (Render →
`tenderflow-mcp` → *Shell*): ya tiene todo el entorno de producción
(`ENV=prod`, `APP_PROFILE=mcp`, `DATABASE_URL` con su CA, `AUDIT_HMAC_KEY`) y el
SDK instalado, porque el script importa `mcp_server`:

```bash
python -m scripts.mcp_revocar --email alguien@empresa.es
# → Revocados N tokens de alguien@empresa.es   (una línea por cuenta; exit 0)
#   correo desconocido: exit 1 con «ERROR: no existe ninguna cuenta…»
```

Con `ENV=prod` y `APP_PROFILE=mcp`, si falta `AUDIT_HMAC_KEY` o `SIGNING_KEY`
(o tiene menos de 32 caracteres) el script **ni llega a arrancar**:
`config.settings` aborta al importarse con un `ValidationError` de pydantic
(traza, exit 1) y no se revoca nada. Distínguelo del correo desconocido por la
traza. El `exit 2` del propio script («falta AUDIT_HMAC_KEY») es una segunda red
para un perfil que no compruebe las claves; con el perfil `mcp` no se alcanza.

El correo se compara **sin distinguir mayúsculas** (como el login) y alcanza
también cuentas desactivadas; si varias cuentas casan (`Ana@x.es` y `ana@x.es`),
se revocan todas y se imprime cada una.

Desde otra máquina funciona, pero el venv necesita `requirements-mcp.txt`
(`pip install -r requirements-mcp.txt`), `DATABASE_SSL_ROOT_CERT` si el DSN es
`verify-full`, y lanzarlo desde la raíz del repo con
`ENV=prod APP_PROFILE=mcp DATABASE_URL=… AUDIT_HMAC_KEY=… SIGNING_KEY=…`
(las de producción; el perfil `mcp` exige las dos claves con 32+ caracteres).

Cierra todos sus tokens vivos (access, refresh y códigos sin canjear). Deja
`mcp.revocacion_manual` en `audit_log` (con el número de tokens, sin correo). En
producción no hay revocación sin rastro: sin `AUDIT_HMAC_KEY` no arranca (ver
arriba). Nunca con `ENV=dev` contra la BD de producción: firmaría la auditoría
con la clave de desarrollo.

**Esto no impide que vuelva a entrar**: si sigue siendo admin y activo, puede
repetir el login de Google y obtener tokens nuevos. Para quitarle el acceso del
todo, además:

- quítale `is_admin` (o desactiva la cuenta, `deactivated_at`); el MCP lo
  re-comprueba en cada petición con una caché de 60 s, así que en ≤ 1 min sus
  tokens dejan de valer aunque no se hubieran revocado; y/o
- retira su acceso en la allowlist / `access_grants`.

Orden recomendado si hay urgencia: primero `is_admin`/desactivar, luego
`mcp_revocar.py`.

---

## 3. Rotar la contraseña del rol `tenderflow_mcp`

Re-ejecutar `setup_pg_role_mcp.sql` **no** cambia la contraseña (el
`CREATE ROLE` solo corre si el rol no existe). Se cambia a mano:

```bash
PASS=$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-32)
psql "$DATABASE_ADMIN_URL" -c "ALTER ROLE tenderflow_mcp PASSWORD '$PASS'"
```

Luego, **de inmediato** (entre ambos pasos el MCP no consulta datos):
actualizar `MCP_DATABASE_URL` en Render con la contraseña nueva (si la
contiene caracteres especiales, codificarla en la URL) y guardar para que
redespliegue. Verificar con `consultar_sql` desde un cliente y con
`/healthz`. Las conexiones abiertas del pool con la contraseña vieja siguen
vivas hasta que el reinicio las cierre; no hace falta cortarlas.

---

## 4. Diagnóstico

Logs: Render → `tenderflow-mcp` → *Logs*. Los propios del MCP salen en JSON
(`mcp_server`); el log de acceso de uvicorn está apagado (sección 7).

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| El servicio no arranca: `Configuración del MCP incompleta o inválida: …` | Falta (o está mal formada) una variable. El mensaje lista cuáles | Corregir en Render. Incluye `AUDIT_HMAC_KEY` y que `MCP_GOOGLE_REDIRECT_URI` sea exactamente `MCP_PUBLIC_URL` + `/oauth/google/callback` |
| claude.ai: «Tenderflow wasn't connected. If you didn't cancel the sign-in, ask your Tenderflow admin for access.» En los logs, `GET /oauth/google/callback` → `302` y **ningún** `POST /token` después | El callback denegó el login y devolvió `access_denied`. `audit_log` tiene `mcp.login_denegado` con `motivo`: `fuera_de_allowlist` (el correo no está en `OAUTH_ALLOWED_EMAILS`/`OAUTH_ALLOWED_DOMAINS` **del servicio MCP** ni en `access_grants`; fue el caso del primer alta), `no_admin` o `sin_usuario_activo` (no hay cuenta activa con ese correo de Google) | `SELECT detail, created_at FROM audit_log WHERE action = 'mcp.login_denegado' ORDER BY id DESC LIMIT 3`. Para `fuera_de_allowlist`, añadir el correo a `OAUTH_ALLOWED_EMAILS` en `tenderflow-mcp` y reintentar tras el redeploy |
| El cliente da vueltas pidiendo login (**401 en bucle**) | (a) la persona ya no es admin/activa o no pasa la allowlist (`mcp.login_denegado` en auditoría con `motivo`); (b) el cliente tiene un token de otro `MCP_PUBLIC_URL`/servicio; (c) `SIGNING_KEY` cambió: las peticiones pendientes (10 min) ya no verifican y el `client_secret` de los clientes registrados (derivado de esa clave) deja de valer en `/token` | Mirar `mcp.login_denegado`. Quitar y volver a añadir el conector. Si cambió `SIGNING_KEY`, cada persona tiene que quitar y volver a añadir el conector (se registra un cliente nuevo) |
| `redirect_uri_mismatch` en Google | El paso 2 no coincide al carácter con `MCP_GOOGLE_REDIRECT_URI` | Corregir en Google Cloud o en la variable |
| El registro del cliente falla (`invalid_redirect_uri` en `/register`) | Un cliente con callback propio (ChatGPT) | Añadirlo a `MCP_REDIRECT_URIS_EXTRA` (paso 4) |
| `/register` responde `invalid_client_metadata` «Demasiados registros…» o «Registro desmedido…»; `/authorize` vuelve con `error=temporarily_unavailable` | Topes y rate limit del DCR abierto: 30 registros/h y 600 autorizaciones/h **globales**, 60/h por cliente; campos de más de 500 caracteres, registro de más de 8 KB. No hay límite por IP | Si es un abuso, esperar a que pase la hora (o vaciar las claves `mcp:oauth:*` de `rate_limits`/Redis, ver `rate-limit-reset.md`); si es un cliente legítimo con metadatos enormes, es un cambio de código en `mcp_server/auth/proveedor.py` |
| Un conector que funcionaba da `invalid_client` / «Client ID … not found» | El cliente se purgó (más de 30 días sin tokens) o uno de sus `redirect_uris` ya no está en la allowlist (`MCP_REDIRECT_URIS_EXTRA` se cambió) | Quitar y volver a añadir el conector: se registra de nuevo |
| `consultar_sql`: «La función X no está permitida en el MCP» | Llamada vetada (cerrojos `pg_advisory_*`, `pg_notify`, `set_config`, señales a otros procesos, las que escriben WAL —`pg_logical_*`, `txid_current`, ranuras de replicación—, funciones que ejecutan SQL en texto); ADR-036 | Reescribir la consulta sin esa función. Si el LLM la escribió sin que nadie se lo pidiera, mirar si venía de un pliego (inyección de instrucciones) |
| **421 Misdirected Request** en `/mcp` | El `Host` de la petición no coincide con `MCP_PUBLIC_URL`. Típico: `MCP_PUBLIC_URL` escrito con `:443` explícito (`https://host:443`), o llamar por otro dominio | Poner `MCP_PUBLIC_URL=https://host` sin puerto y sin barra final; usar el mismo host en el conector |
| **403** con `Origin` en `/mcp` | Petición de navegador desde un origen que no es el del propio servicio, claude.ai/claude.com, chatgpt.com o localhost | Si es un cliente legítimo nuevo, requiere un cambio de código en `mcp_server/servidor.py::_ORIGENES_CLIENTES` |
| `consultar_sql` devuelve **`42501`** inesperado | La tabla/columna no está concedida al rol: o es oculta a propósito (`api_keys`, `sessions`, `users.password_hash`…), o es nueva y falta clasificarla en `mcp_server/catalogo.py` y regenerar | Si es nueva: clasificar, `python scripts/gen_mcp_grants.py` y reaplicar el SQL (paso 1.3; la contraseña ya existe, el script no la toca) |
| **`57014`** (timeout) | Consulta > `statement_timeout = 15s` del rol | Acotar por fecha o agregar antes; no se sube el límite desde el cliente |
| Una tool de dominio responde «La consulta tardó más de 15 s y se cortó» | Sus lecturas por el pool de la app llevan el mismo techo de 15 s (`TECHO_SENTENCIA_MS` en `mcp_server/envoltura.py`): con 2 conexiones en el pool, dos llamadas lentas lo dejarían sin servicio | Acotar con filtros o con el `id_externo`; si una consulta concreta lo necesita a menudo, es un índice o un cambio en su repositorio |
| `25006` (read-only) | Se intentó escribir; está bloqueado a propósito | — |
| Error de conexión / agotado el pool | El rol tiene `CONNECTION LIMIT 5` y el pool llega a 5 | Esperar; si es continuo, mirar `pg_stat_activity` por `usename = 'tenderflow_mcp'` y consultas colgadas |
| Llamadas con error de cuota | Rate limit por usuario: 60/min, 1 000/día | El mensaje dice cuánto esperar |
| Una tool responde «Error interno» y `audit_log` trae `error = "interno: SalidaFueraDeEsquema"` | Lo que devolvió no casa con su `outputSchema` (el `TypedDict` `Salida*` de `mcp_server/tools/`); el log `mcp_tool_error_interno` lista los campos | Ajustar el `TypedDict` a la forma real; `tests/test_mcp_servidor_integration.py` llama a las seis con datos sembrados |
| Las llamadas funcionan pero **no hay filas `mcp.*` en `audit_log`** | `AUDIT_HMAC_KEY` ausente o distinta (`log_action` no lanza: `audit_log_persist_failed` en logs) | Poner la clave de la API |
| Render marca el deploy como fallido tras un health check | `/healthz` responde 421/404, o el arranque abortó por configuración | Ver los logs del arranque; ver sección 6 sobre el `Host` del health check |

---

## 5. Auditoría

Cada llamada a una tool y cada evento de OAuth escribe en `audit_log`
(`session_hash = 'mcp'`, `action` empieza por `mcp.`). `created_at` es texto
ISO; `detail` es JSON en texto. Acciones: `mcp.<tool>` (por llamada),
`mcp.login_ok`, `mcp.login_denegado`, `mcp.token_emitido`, `mcp.token_rotado`,
`mcp.token_revocado`, `mcp.refresh_reutilizado`, `mcp.codigo_reutilizado`,
`mcp.revocacion_manual`. Las llamadas cortadas por el rate limit se auditan una
vez por usuario, ventana (`min`/`dia`) y minuto; el resto solo va al log (debug).

```sql
-- Qué se ha preguntado, por quién y cuándo (últimas 50)
SELECT a.created_at, u.email, a.action,
       a.detail::json->'args'->>'sql' AS sql,
       a.detail::json->>'n_filas'     AS n_filas,
       a.detail::json->>'duracion_ms' AS ms,
       a.detail::json->>'error'       AS error
FROM audit_log a
LEFT JOIN users u ON u.id = a.user_id
WHERE a.action LIKE 'mcp.%'
ORDER BY a.id DESC
LIMIT 50;

-- Actividad por persona y por tool en los últimos 7 días
SELECT u.email, a.action, count(*) AS llamadas
FROM audit_log a LEFT JOIN users u ON u.id = a.user_id
WHERE a.action LIKE 'mcp.%' AND a.created_at >= to_char(now() - interval '7 days', 'YYYY-MM-DD')
GROUP BY 1, 2 ORDER BY 3 DESC;

-- Logins denegados y reutilización de tokens (señales de alarma)
SELECT a.created_at, a.action, a.detail
FROM audit_log a
WHERE a.action IN ('mcp.login_denegado', 'mcp.refresh_reutilizado', 'mcp.codigo_reutilizado')
ORDER BY a.id DESC LIMIT 50;

-- Errores de consultar_sql por SQLSTATE en 30 días: los frecuentes piden
-- corregir el glosario o la pista, no la consulta de quien preguntó
SELECT COALESCE(substring(a.detail::json->>'error' FROM 'SQLSTATE ([0-9A-Z]{5})'),
                'sin SQLSTATE') AS sqlstate,
       count(*) AS n,
       min(left(a.detail::json->>'error', 160)) AS ejemplo
FROM audit_log a
WHERE a.action = 'mcp.consultar_sql' AND a.detail::json->>'error' IS NOT NULL
  AND a.created_at >= to_char(now() - interval '30 days', 'YYYY-MM-DD')
GROUP BY 1 ORDER BY 2 DESC;
```

**`audit_log` es visible para el MCP.** Por decisión (todo visible salvo
credenciales y secretos), `tenderflow_mcp` tiene `SELECT` sobre `audit_log`
(la tabla entera: el catálogo la marca `VISIBLE` y revisó como no secretas `user_key`, `session_hash` y los hashes de la cadena). Eso significa que
cualquier admin puede, vía `consultar_sql`, leer las filas de auditoría de todos:
incluido el SQL que otras personas han ejecutado por el MCP (`mcp.consultar_sql`
con su `detail`) y los correos de los logins denegados. Está aceptado para este
equipo de tres admins; si el ámbito crece, hay que ocultar la tabla en
`mcp_server/catalogo.py` y regenerar los grants. Estas mismas consultas pueden
lanzarse con el rol de la app o el admin, o desde el propio MCP.

---

## 6. Primera prueba manual (checklist)

Se hace una vez, tras el alta (pasos 1–3). Lo marcado se comprobó el
2026-10-17 con el conector de claude.ai y los logs de Render:

- [x] `curl https://<host>/healthz` → 200 `{"ok":true}`, y el health check de
      Render lo da por bueno (200 cada 5 s en los logs). Si Render devuelve 421, el validador de `Host`
      está alcanzando la ruta: anotarlo y abrir un cambio de código.
- [x] `curl -i https://<host>/mcp` → 401 con `WWW-Authenticate` que apunta a
      `/.well-known/oauth-protected-resource` (claude.ai lo siguió: 401 en
      `POST /mcp` y a continuación `GET /.well-known/oauth-protected-resource/mcp`).
- [ ] **MCP Inspector** contra la URL desplegada:
      `npx @modelcontextprotocol/inspector` → transporte *Streamable HTTP* →
      `https://<host>/mcp` → *OAuth*. El loopback del Inspector ya está
      admitido.
- [x] **Login completo con Google** con un admin real (desde claude.ai, no
      desde el Inspector): `/register` → `/authorize` → Google →
      `/oauth/google/callback` → conectado. El primer intento falló por
      `fuera_de_allowlist` (faltaba `OAUTH_ALLOWED_EMAILS` en el servicio MCP).
- [ ] Con un usuario **no admin** el login termina en error y deja
      `mcp.login_denegado` con motivo `no_admin`.
- [x] `tools/list` devuelve las seis: `describir_esquema`, `describir_tabla`,
      `consultar_sql`, `buscar_licitaciones`, `buscar_en_pliegos`,
      `ficha_licitacion`.
- [x] Un `consultar_sql` real devuelve filas: corre como `tenderflow_mcp` con
      `transaction_read_only = on` (~370 ms un `count(*)` de 2026). Un filtro
      con regex sobre todo `licitaciones` cortó en 15 s con `57014` y su pista.
- [ ] Su fila `mcp.consultar_sql` aparece en `audit_log` con el SQL.
- [ ] Un `consultar_sql` contra `api_keys` devuelve el error `42501` con su
      pista, sin tumbar el servidor.
- [x] Esquemas a los que llega el rol (en Supabase hay `extensions`, `net`
      —`pg_net` hace peticiones HTTP—, `graphql`, `vault`…):
      `SELECT nspname FROM pg_namespace WHERE has_schema_privilege('tenderflow_mcp', oid, 'USAGE')`
      debe dar solo `pg_catalog`, `information_schema` y `public`. Si sale otro,
      revisar sus funciones contra la lista de vetadas de `db/consulta_libre.py`
      (ADR-036) antes de abrir el servicio.
      *Visto en producción el 2026-10-16:* el rol llega a `net` porque Supabase
      da `USAGE` y `EXECUTE` a `PUBLIC` sobre `pg_net` (`net.http_get`,
      `net.http_post`…). El modo de solo lectura lo frena (`net.http_get` encola
      con un INSERT y falla con 25006) y el ejecutor veta `net` y `http*`; en
      `public` solo hay funciones de pgvector y pg_trgm.
- [x] **El conector real de claude.ai funciona** (el canje de `/token` pasó
      con el cliente que registra claude.ai). Esto es lo único que el
      Inspector no prueba: los metadatos OAuth del SDK anuncian
      `token_endpoint_auth_methods_supported = ["client_secret_post",
      "client_secret_basic"]` y **no** `none`, aunque `/register` acepta clientes
      públicos. Si claude.ai registra un cliente público y el canje de `/token`
      falla, es esto; hay que decidirlo con el conector delante (ver
      seguimientos).
- [ ] Probar `mcp_revocar.py` con la cuenta de prueba: el siguiente refresh del
      cliente falla y vuelve a pedir login.
- [ ] Anotar aquí la fecha y lo que difiera del runbook.

### Pasar la evaluación (`mcp_server/evaluacion.xml`)

Diez preguntas con respuesta verificada sobre datos de producción. Se pasan
tras cambiar el glosario, la descripción de una tool o lo que devuelve, y el
resultado se compara con la pasada anterior. Es un informe, no un gate, y cuesta
llamadas al modelo.

1. Sacar un access token: MCP Inspector (`npx @modelcontextprotocol/inspector`)
   → *Streamable HTTP* → `https://<host>/mcp` → *OAuth* con un admin. El token
   aparece en el panel de autenticación; vale una hora.
2. Ejecutar el script de evaluación del skill `mcp-builder` (no está en el
   repo: `scripts/evaluation.py` dentro de la carpeta del skill), con
   `pip install anthropic mcp` y `ANTHROPIC_API_KEY`, desde la raíz del repo:

   ```bash
   python <carpeta-del-skill>/scripts/evaluation.py -t http -u https://<host>/mcp \
     -H "Authorization: Bearer <token>" -o informe.md mcp_server/evaluacion.xml
   ```

3. Una pregunta que falla se arregla en el glosario o en la descripción de la
   tool, nunca en la pregunta. El token caduca solo en una hora; `mcp_revocar.py`
   no sirve para cerrarlo antes, porque revoca **todos** los de la persona,
   también los de su conector.

### Medir el uso antes de cambiar el glosario o una tool

Cada llamada queda en `audit_log` (`action = 'mcp.<tool>'`, `detail` en JSON con
`args`, `n_filas`, `duracion_ms` y `error`), y la tabla es visible para el propio
MCP: estas consultas se lanzan con `consultar_sql`. Las filas OAuth
(`mcp.login_denegado`…) no llevan `duracion_ms` y quedan fuera.

Llamadas, errores y P95 por tool:

```sql
SELECT action,
       count(*) AS llamadas,
       count(*) FILTER (WHERE detail::jsonb->>'error' IS NOT NULL) AS errores,
       percentile_disc(0.95) WITHIN GROUP (ORDER BY (detail::jsonb->>'duracion_ms')::int) AS p95_ms
FROM audit_log
WHERE action LIKE 'mcp.%' AND detail::jsonb ? 'duracion_ms'
  AND created_at >= '2026-10-01'
GROUP BY action
ORDER BY llamadas DESC
```

Errores de `consultar_sql` por SQLSTATE (`57014` = cortada a los 15 s, `42P01`/`42703`
= tabla o columna mal nombrada, `22007`/`22008` = fecha en texto mal convertida):

```sql
SELECT substring(detail::jsonb->>'error' FROM 'SQLSTATE ([0-9A-Z]{5})') AS sqlstate,
       count(*) AS n,
       min(left(detail::jsonb->>'error', 120)) AS ejemplo
FROM audit_log
WHERE action = 'mcp.consultar_sql' AND detail::jsonb->>'error' IS NOT NULL
GROUP BY 1
ORDER BY n DESC
```

Un SQLSTATE que se repite señala la sección del glosario que falta o no se
entiende; una tool sin llamadas, una descripción que el modelo no reconoce.

**Medido el 2026-10-31** (del 17-10 al 31-10, un usuario): 652 llamadas;
`consultar_sql` 527 (40 errores, 7,6 %; P95 6,0 s), `describir_tabla` 44,
`ficha_licitacion` 39, `buscar_en_pliegos` 21, `describir_esquema` 12,
`buscar_licitaciones` 9 (P95 3,3 s). Errores de `consultar_sql`: 22 `42703`
(columnas inventadas, dispersas; la que más, `lote_numero` en `lotes` o
`adjudicaciones`, 5), 8 `42501` (`licitaciones_canonicas`, `api_keys` y
`licitaciones_id_anterior` antes de reaplicar los grants), 6 `42883`
(`round(double precision, int)`, `date_trunc` sobre texto, `cardinality(text)`)
y 3 `57014`. El glosario se ajustó a los tres primeros ese mismo día.

---

## 7. Seguimientos conocidos

Entradas equivalentes en [`docs/IMPROVEMENT_BACKLOG.md`](../IMPROVEMENT_BACKLOG.md):

- **Purga de las tablas OAuth** (`db.mcp_oauth.purgar`): el servidor la corre
  al arrancar y cada hora (log `mcp_oauth_purga` con lo borrado por clase):
  peticiones pendientes y códigos caducados hace más de un día, access y
  refresh revocados o caducados hace más de 30 días, y clientes registrados hace
  más de 30 días sin ningún token (plazo confirmado el 2026-10-19; antes, 7).
  Consecuencias: un refresh rotado hace más de 30 días —lo que vive un
  refresh— ya no se reconoce como reutilizado (se rechaza como desconocido, sin
  revocar la familia), y un conector sin tokens durante un mes pierde su
  registro y tiene que volver a añadirse.
- **Celdas enormes de `consultar_sql`** (resuelto el 2026-10-29): las
  columnas `text`, `varchar` y `xml` llegan ya recortadas desde Postgres
  (`db.consulta_libre.envolver_con_recorte`), así que un `string_agg` de
  `documentos.texto` o un `database_to_xml` ya no entra entero en memoria. Los
  `json`/`jsonb` y los arrays de tipos nativos llegan como `jsonb` y, si pasan
  de 100 000 caracteres (no cabrían ni solos en la respuesta), como texto
  recortado con la marca `…[+N]`. Quedan fuera los arrays de tipos propios
  (enums): si hay OOM en `starter`, son los sospechosos.
- **El `client_secret` del DCR ya no se guarda** (2026-10-29): es
  `HMAC-SHA256(SIGNING_KEY, client_id)` y se recalcula en cada `/token`
  (`mcp_server.auth.proveedor.secreto_de_cliente`). Los clientes registrados
  antes conservan su secreto aleatorio en `mcp_oauth_clients.datos` hasta que se
  vuelvan a registrar (quitar y volver a añadir el conector) o los purgue la
  limpieza. Contrapartida: rotar `SIGNING_KEY` obliga a volver a añadir todos
  los conectores (sección 4).
- **Log de acceso de uvicorn apagado** (`access_log=False`, 2026-10-29): llevaba
  la query string del callback de OAuth (`code` y `state`). Las peticiones a las
  tools siguen en el log `mcp_tool` y en `audit_log`.
- El SDK repetía a INFO el texto de cada error de tool (puede traer literales
  SQL) en `mcp.server.mcpserver.server`; desde el 2026-10-29 `python -m
  mcp_server` sube ese logger a WARNING. Los fallos siguen en `mcp_tool`
  (`ok=false`) y en `audit_log`, y los inesperados del SDK, a ERROR.
- El CI construye la variante `requirements-mcp.txt` de la imagen y comprueba
  que importa el servidor (`ci.yml::docker-build`, desde el 2026-10-29).
