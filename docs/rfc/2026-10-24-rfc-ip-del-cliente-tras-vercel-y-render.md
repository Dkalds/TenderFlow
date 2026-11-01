---
rfc: 2026-10-24-ip-del-cliente-tras-vercel-y-render
title: De dónde sale la IP del cliente cuando la API está detrás de Vercel y del proxy de Render
issue: "(sin issue: punto 2 del P1 «Recuperación de contraseña: comprobar la entrega en producción…» de docs/IMPROVEMENT_BACKLOG.md, 2026-10-24)"
author: agent:claude-code
date: 2026-10-24
status: partially-implemented
evidence: "Código en el árbol (comprobado el 2026-11-01): cabecera x-tf-origin-secret en api/middleware.py, API_ORIGIN_SECRET en config/settings.py, web/src/lib/server-prefetch.ts, api/diagnostico_proxy.py, tests/test_unit_ip_cliente_origen.py y docs/runbooks/ip-del-cliente.md. Falta lo que solo puede hacer el propietario (el secreto en Vercel y en Render) y la verificación en producción de §7."
related:
  - "[[ADR-006-etag-pdf-export-ratelimit-redis]]"
---

## Decisión (2026-10-26)

**Opción B**, aceptada por el propietario como D58 del
[plan 2026-10](../plans/2026-10-plan-foco-piloto.md). La parte de código está en
el árbol; falta la del propietario (secreto en Vercel y Render) y la
verificación en producción de §7, sin las cuales el comportamiento es el de
antes. Pasos en [el runbook](../runbooks/ip-del-cliente.md).

Cómo quedó, frente al plan de §6:

- **Cabecera** `x-tf-origin-secret`; **variable** `API_ORIGIN_SECRET` con el
  mismo nombre en los dos paneles (en Vercel, variable de servidor sensible de
  *Production*, nunca `NEXT_PUBLIC_*`), y `API_ORIGIN_SECRET_PREVIOUS` solo en
  Render durante una rotación. Mínimo 32 caracteres: `config/settings.py` no
  arranca con uno más corto, y así el texto literal `$API_ORIGIN_SECRET` que
  manda el transform de Vercel en un entorno sin la variable nunca puede casar.
- **Vercel** (`web/vercel.json`): una ruta `^/api/(.*)$` **sin `dest` y con
  `continue: true`**, cuyo transform primero borra la cabecera que traiga el
  visitante y luego pone el secreto. El rewrite sigue en `next.config.ts`. La
  documentación de Vercel dice que `routes` convive con las propiedades de alto
  nivel; que conviva también con el rewrite que genera Next **se verifica en un
  preview** (paso 3 del runbook). Si no, el rewrite se muda a esa misma ruta
  con `dest: "${API_BASE_URL}/api/$1"` y `env`.
- **API** (`api/middleware.py::_trusted_client_ip`): si la cabecera casa con
  alguno de los dos valores —`hmac.compare_digest` contra todos, sin cortar al
  primer acierto—, la IP es `x-real-ip` validada con `ipaddress`, o el primer
  salto de `X-Forwarded-For` si falta. Sin cabecera, con una que no casa o sin
  IP válida, lo de siempre. La variante A2 (`CF-Connecting-IP`) **no** se
  implementó: espera a lo que diga el diagnóstico.
- **SSR** (`web/src/lib/server-prefetch.ts`): manda el secreto y el `x-real-ip`
  de la request entrante; sin la variable no manda ninguno de los dos. Las
  lecturas de la superficie pública (`lib/publico-api.ts`, sitemap, cobertura)
  no lo mandan: se generan en build o ISR, sin un visitante detrás.
- `api/routes/auth.py::_set_session_cookie` guarda la IP de
  `_trusted_client_ip`, no `request.client.host`.
- `observability/sentry.py` no necesitó cambio: envía solo `host`,
  `user-agent` y `referer`; un test fija que la cabecera no sale.
- El secreto no se registra en ningún sitio. El arranque en `ENV=prod` sin él
  emite `api_origin_secret_not_configured` (solo el nombre de la variable).
- **`api/diagnostico_proxy.py` se queda** hasta que el propietario haga la
  verificación de §7 en producción; ahora añade `origen_acreditado` (booleano)
  para ver si el secreto casó. Se retira en el cambio que anote esa verificación.

## Por qué hace falta un RFC

Es una decisión de seguridad (`AGENTS.md` §5): elegir en qué cabecera confía la
API para saber quién llama decide si el rate limiting, el bloqueo de login y la
IP del rastro de auditoría significan algo, y quién puede falsificarlos. Este
documento no cambia ese comportamiento: describe la causa, propone opciones y
recomienda una. El único código que acompaña al RFC es un **log de diagnóstico
temporal** para confirmar en producción lo que aquí se infiere (§4).

## 1. Qué se midió

El 2026-10-24, en el log de Render del servicio `TenderFlow`
(`srv-d8dq7df40ujc73cur9q0`, instancia `-9q8rf`):

- El `client_ip` de **todas** las líneas `http_request` es una IP interna
  `10.19x.x.x`. Entre las 18:00 y las 19:25 UTC salen seis:
  `10.192.214.29`, `10.193.127.39`, `10.194.123.132`, `10.194.137.88`,
  `10.195.187.132` y `10.197.182.120`. Son direcciones de la infraestructura de
  Render, no de personas.
- Una misma carga de pantalla reparte sus peticiones entre varias de ellas
  (`/publico/sitemap/entradas` a las 18:34:24–25 pasa por cuatro distintas en
  medio segundo).
- La línea de acceso de uvicorn de esas mismas peticiones lleva **puerto
  efímero real**: `INFO: 10.195.187.132:47742 - "GET /api/v1/publico/licitaciones…"`
  y la siguiente petición reutiliza `:47742` (keep-alive). Esto importa en §2.

No hay logs de tipo `request` de Render para el servicio en esa ventana; solo
los de aplicación.

## 2. Por qué sale `10.19x`

### El camino de una petición del navegador

```
navegador ──► Vercel (tenderflow.app, rewrite /api/*) ──► Cloudflare (borde de Render)
          ──► proxy interno de Render (10.19x.x.x) ──► contenedor: uvicorn ──► FastAPI
```

- `web/next.config.ts::rewrites()` reenvía `/api/:path*` a `API_BASE_URL`
  (el host `*.onrender.com` de la API). Es una reescritura a origen externo:
  la ejecuta la red de Vercel, no la función de Next.
- `web/src/lib/server-prefetch.ts` pide además a la API **desde la función de
  Next** (SSR), con la cookie del usuario y sin ninguna cabecera de IP: esas
  peticiones salen de la IP de egreso de Vercel.
- Vercel, según su documentación, **sobrescribe** `x-forwarded-for` y
  `x-real-ip` con la IP pública del visitante y los reenvía al origen externo
  ([Rewrites → Identifying the visitor at your origin](https://vercel.com/docs/routing/rewrites#identifying-the-visitor-at-your-origin);
  [Request headers → x-forwarded-for](https://vercel.com/docs/headers/request-headers#x-forwarded-for)).
- Render no documenta las cabeceras de IP en su referencia de servicios web
  ([Web services](https://render.com/docs/web-services) solo dice que su
  balanceador termina TLS y reenvía al puerto). Lo que hay es indirecto:
  - Su CEO, en el hilo de feedback: «we set the first IP in the list to the
    real client IP»; y otro usuario: Render «does not clear or reset any
    passed-in X-Forwarded-For header (it only appends to it)», con
    `CF-Connecting-IP`/`True-Client-IP` puestos por Cloudflare
    ([feedback.render.com](https://feedback.render.com/features/p/send-the-correct-xforwardedfor)).
  - Un servicio de prueba desplegado en Render (no es documentación oficial)
    muestra la cadena `X-Forwarded-For: <falsa>, <cliente>, 172.71.x.x, 10.x.x.x`
    —el salto `172.71` es Cloudflare—, que `CF-Connecting-IP` falsificada se
    rechaza con un 403 de Cloudflare y que `True-Client-IP` falsificada se
    sobrescribe ([johnbeynon/header-test](https://github.com/johnbeynon/header-test)).
  - Cloudflare: `CF-Connecting-IP` es la IP que conecta con Cloudflare, y si ya
    viene un `X-Forwarded-For`, «Cloudflare will append the IP address of the
    HTTP proxy connecting to Cloudflare»
    ([Cloudflare HTTP headers](https://developers.cloudflare.com/fundamentals/reference/http-headers/)).

Con todo eso, lo **esperable** al llegar al contenedor es:

```
peer TCP          = 10.19x.x.x                       (nodo del proxy de Render, uno por conexión)
X-Forwarded-For   = <visitante>, <egreso de Vercel>, <borde de Cloudflare>, <10.x de Render>
X-Real-IP         = <visitante>                      (lo pone Vercel; falta ver si alguien lo toca)
CF-Connecting-IP  = <egreso de Vercel>               (quien conectó con Cloudflare)
```

Esa cadena **no está observada**: es lo que confirma el diagnóstico de §4.

### Qué hace el código con ella

1. **uvicorn** arranca con `--proxy-headers --forwarded-allow-ips
   "${FORWARDED_ALLOW_IPS:-127.0.0.1}"` (`docker/docker-entrypoint-api.sh`; el
   `Dockerfile.api` fija además `ENV FORWARDED_ALLOW_IPS=127.0.0.1`). Su
   `ProxyHeadersMiddleware` (uvicorn 0.46) solo reescribe `scope["client"]` si
   el peer está en esa lista, y cuando lo hace le pone el puerto del salto
   elegido —0 si el salto es una IP sin puerto—. El puerto efímero real del log
   (`:47742`) dice que **uvicorn no reescribió el peer**: o `FORWARDED_ALLOW_IPS`
   no cubre `10.19x`, o no llegó `X-Forwarded-For`. Lo segundo contradice todo
   lo que se sabe de Render, así que lo probable es lo primero —que la variable
   del panel no exista y valga el `127.0.0.1` de la imagen, o que tenga otro
   rango—. `render.yaml` la declara `sync: false` y el validador
   `config/settings.py::_validate_prod_forwarded_allow_ips` solo rechaza vacío o
   comodín, así que `127.0.0.1` arranca sin queja.
2. **`api/middleware.py::_trusted_client_ip`** toma `request.client.host` (el
   peer que dejó uvicorn, `10.19x`), comprueba si es un proxy de confianza contra
   la misma `FORWARDED_ALLOW_IPS`, ve que no, y **devuelve el peer**. No llega a
   mirar `X-Forwarded-For`.

Resultado: la «IP del cliente» es el nodo del proxy de Render que abrió esa
conexión. Ni la del visitante ni la de Vercel.

**Y con `FORWARDED_ALLOW_IPS=10.0.0.0/8` tampoco se arreglaría.** Recorriendo la
cadena de §2 desde la derecha, el primer salto no confiable sería el borde de
Cloudflare; confiando además en los rangos de Cloudflare, sería el egreso de
Vercel —compartido por todos los visitantes—. Para llegar al visitante habría
que confiar en las IP de Vercel, que no publica un rango estable (solo vende IP
estáticas de salida como producto aparte,
[Static IPs](https://vercel.com/docs/networking/static-ips/getting-started)).
Recorrer `X-Forwarded-For` no alcanza al visitante en ningún caso: la cabecera
tiene que venir firmada o acreditada de algún modo por Vercel.

### Quién usa esa IP

| Uso | Dónde | Efecto hoy |
|---|---|---|
| Tope global 120/min (y los pesados, `publico:`, `solicitudes:`) | `RateLimitMiddleware` vía `_client_key` | Unos seis cubos para **todo** el tráfico del navegador. Con carga, usuarios ajenos se reparten los 429; y a un solo usuario su carga se le trocea entre nodos. |
| Recuperación de contraseña 5/15 min, y `confirm`, `register`, `verify-email` | `api/routes/auth.py::_password_reset_rate_allowed` | ~30 peticiones cada 15 min **para toda la plataforma** (5 × nodos). Cualquiera las agota y nadie más recibe el enlace, **en silencio**: `request` responde 202 igual con la cuota agotada. El cubo por sujeto (3/h por correo) sí funciona. |
| Bloqueo de login (5 fallos / 5 min) | `_login_client_key` = hash(`ip:correo`) | El bloqueo es por (nodo, cuenta): quien falla 5 veces contra una cuenta la bloquea **para todos** en ese nodo; ~30 intentos la bloquean entera. Y un atacante tiene 5 × nodos intentos por ventana. |
| Informes CSP y errores de cliente | `api/routes/security.py` | Cuotas compartidas: un navegador ruidoso silencia los informes de los demás. |
| `client_ip` del access log | `_registrar_acceso` | No sirve como evidencia. |
| IP de la sesión (`/me/sesiones`) | `_set_session_cookie` usa `request.client.host`, **no** `_trusted_client_ip` | Enseña `10.19x`. Al arreglar lo demás, unificarlo. |
| Allowlist de `/metrics` | `api/routes/metrics.py` | No aplica en prod (allí exige credencial). |

`mcp_server/` no usa IP (sus límites son globales por diseño).

## 3. Opciones

Las cuatro no se excluyen del todo: D complementa a cualquiera.

### A. Confiar en el proxy de Render (y en Cloudflare) y recorrer la cadena

`FORWARDED_ALLOW_IPS = 10.0.0.0/8` más los rangos de Cloudflare
([cloudflare.com/ips](https://www.cloudflare.com/ips/)), o, en su variante A2,
leer `CF-Connecting-IP` cuando el peer está en `10.0.0.0/8`.

- **Gana:** la IP real de quien conecta **directamente** con Render (clientes de
  API con clave, `curl`, bots contra `*.onrender.com`). Para el navegador da la
  IP de egreso de Vercel: sigue compartida por todos (es exactamente la hipótesis
  original del backlog), aunque deja de trocearse por nodo.
- **Suplantación:** con la variante de rangos, un Worker de Cloudflare puede
  escribir `X-Forwarded-For` a su gusto y el salto que añade Cloudflare cae en
  un rango «de confianza», así que el recorrido acaba en el valor falso. La
  variante A2 no tiene ese agujero (Cloudflare fija `CF-Connecting-IP` y fuerza
  `2a06:98c0:3600::103` para subpeticiones de Workers entre zonas, según su
  documentación), pero depende de que Render siga detrás de Cloudflare, cosa que
  Render no documenta ni garantiza: si lo dejara y la cabecera pasara tal cual,
  sería falsificable.
- **Cambia:** A, solo la variable en Render (lista de ~22 CIDR que hay que
  mantener). A2, `_trusted_client_ip` y tests.
- **Coste:** bajo (A: 30 min; A2: medio día). **No resuelve el problema del
  navegador.**

### B. Cabecera secreta que Vercel añade en el rewrite y la API verifica *(recomendada)*

Vercel documenta este patrón para restringir el origen a su tráfico
([Restricting your origin to Vercel traffic](https://vercel.com/docs/routing/rewrites#restricting-your-origin-to-vercel-traffic)):
un `routes` de `vercel.json` con un *transform* `request.headers` / `set` cuyo
valor sale de una variable de entorno
([vercel.json → transforms](https://vercel.com/docs/project-configuration/vercel-json#in-transforms)).
Como `set` reemplaza, el visitante no puede colar el suyo. Con la cabecera
válida, la API sabe que la petición pasó por Vercel y que `x-real-ip` (o el
primer salto de `X-Forwarded-For`, que Vercel sobrescribe) es la del visitante.

- **Gana:** la IP del visitante para todo el tráfico del navegador, que es el
  que importa para recuperación, alta, login y el tope global.
- **Suplantación:** solo con el secreto. Si se filtra (variables de Vercel o de
  Render), el atacante vuelve a elegir su IP: se pierde la eficacia de las
  cuotas por IP, no la autenticación. Se mitiga con un secreto largo, rotación
  con dos valores aceptados a la vez y comparación en tiempo constante. Sin el
  secreto (tráfico directo a `*.onrender.com`), la API cae al comportamiento de
  A2 o al actual.
- **Cambia en Vercel:** variable sensible solo en *Production* (p. ej.
  `TF_ORIGIN_SECRET`) y la regla en `web/vercel.json`. **A verificar en un
  preview** que un `routes` con solo `transforms` convive con el `rewrites()` de
  `next.config.ts`; si no, el rewrite se muda a ese mismo `routes`
  (`dest: "${API_BASE_URL}/api/$1"` con `env`), que también lo admite.
- **Cambia en Render:** la misma variable (o dos, para rotar) en la API.
- **Cambia en el código:** `config/settings.py` (campo `SecretStr` con lista de
  secretos aceptados y aviso al arrancar en prod si falta);
  `_trusted_client_ip` (cabecera válida → `x-real-ip` validada con `ipaddress`;
  si no, lo de hoy o A2); `server-prefetch.ts` manda el secreto (variable de
  servidor, nunca `NEXT_PUBLIC_*`) y el `x-real-ip` que recibió, para que el SSR
  también cuente por visitante; la cabecera secreta al filtro de
  `observability/sentry.py`; `_set_session_cookie` pasa a `_trusted_client_ip`;
  tests de las tres ramas (sin cabecera, cabecera falsa, cabecera buena).
- **Coste:** medio. Un día de código y tests; media hora de configuración del
  propietario en los dos paneles; un preview para validar la regla.

### C. Que el navegador llame a la API sin pasar por el rewrite

Dominio propio en Render (`api.…`) y el cliente web apuntando a él.

- **Gana:** quita un salto (latencia) y la dependencia de Vercel para la IP.
- **Suplantación:** la de A o A2, que sigue haciendo falta para leer la IP tras
  Cloudflare y el proxy de Render.
- **Cambia:** dominio y DNS; CORS con credenciales; cookies de sesión y de CSRF
  con `Domain` compartido; CSP `connect-src`; `web/src/lib/api-client.ts`;
  SSE; las URI de retorno de OAuth registradas en Google; y un *preflight* en
  cada `POST` JSON. Es un cambio de autenticación en sí mismo.
- **Coste:** alto (varios días y riesgo de regresión en login/OAuth). Solo
  compensa si se quiere quitar Vercel del camino de la API por otros motivos.

### D. Claves de cuota por cuenta o por sesión donde aplique

No sustituye a la IP en los endpoints anónimos, pero reduce cuánto depende de
ella el resto:

- Tope global: una petición con cookie de sesión cuenta en
  `sesion:{sha256(cookie)[:16]}` (como ya hace la API key en `_tier_bucket`),
  sin ir a BD. Crear sesiones exige login, que sigue limitado.
- Recuperación: el cubo por correo (3/h) ya existe; el de IP pasa a ser un tope
  de abuso más alto.
- Login: un bloqueo **solo** por cuenta permitiría a cualquiera bloquear a una
  víctima; por eso la clave sigue llevando la IP. Lo más que aporta D aquí es
  sustituir el bloqueo duro por cuenta por un retardo progresivo.
- **Suplantación:** ninguna nueva. **Coste:** medio día a un día.

## 4. Diagnóstico añadido con este RFC

`api/diagnostico_proxy.py` emite `proxy_cabeceras_diag` en cada petición a
`/api/v1/auth/*` (basta con abrir la app: `GET /auth/me`). Lleva los **nombres**
de las cabeceras, el peer y si uvicorn lo reescribió, cada salto de
`X-Forwarded-For` y cada cabecera de IP conocida (`x-real-ip`,
`true-client-ip`, `cf-connecting-ip`, `x-vercel-forwarded-for`…) y la IP que
eligió `_trusted_client_ip`. **Ninguna IP sale entera**: de cada una, su clase
(`publica`, `privada`…), su red truncada (`/16` en IPv4, `/32` en IPv6) y una
huella HMAC de 8 caracteres con una clave aleatoria por proceso que no se
guarda. Dentro de un proceso la misma IP da la misma huella; tras un reinicio,
no se puede recalcular ni enlazar. Es menos que lo que ya registra
`http_request` (`client_ip` en claro), así que no añade categoría de datos al
[registro de tratamientos](../legal/registro-tratamientos.md).

Cómo leerlo, tras desplegar:

1. Dos personas en redes distintas (wifi de casa y datos del móvil) abren la
   app. En el log, filtrar `proxy_cabeceras_diag`.
2. Confirmar la cadena de §2: `xff_saltos` y la clase de cada salto, la red del
   tercero (`172.64.0.0/13` o `104.16.0.0/13` serían Cloudflare).
3. **Decisivo para B:** `x_real_ip.h` coincide con `xff[0].h` y **difiere entre
   las dos personas**; y `peer_reescrito` es `false`.
4. Para A2: `cf_connecting_ip` presente y con la huella del segundo salto
   (egreso de Vercel).
5. Nombres de cabecera nuevos que no estén en este RFC (alguna firma de Vercel,
   `rndr-id`, `cf-ray`…): anotarlos aquí.

Se retira en el mismo cambio que aplique la opción elegida.

## 5. Recomendación

**B**, con la variante A2 como respaldo para el tráfico que no pasa por Vercel
una vez el diagnóstico confirme que `CF-Connecting-IP` llega, y D para el tope
global de peticiones con sesión como siguiente paso.

- B es la única opción que devuelve la IP del visitante sin rehacer la
  autenticación, y es el mecanismo que la propia Vercel documenta para esto.
- Su riesgo residual (filtración del secreto) degrada al estado de hoy, no a
  algo peor.
- **No** tocar `FORWARDED_ALLOW_IPS` por separado mientras tanto: confiar solo
  en `10.0.0.0/8` cambia el nodo de Render por el borde de Cloudflare o el
  egreso de Vercel, igual de compartidos, y además hace que uvicorn reescriba el
  peer que usan la sesión y el log.

## 6. Plan de implementación (opción B)

1. Desplegar el diagnóstico y leerlo (§4). Si `x-real-ip` no es el visitante,
   usar el primer salto de `X-Forwarded-For` (Vercel lo sobrescribe) o parar y
   revisar este RFC.
2. Propietario: generar el secreto (`openssl rand -hex 32`), crearlo como
   variable sensible de *Production* en Vercel y en el servicio de la API en
   Render.
3. `web/vercel.json`: la regla `routes` con el transform; validarla en un
   preview contra una API de staging o con el diagnóstico.
4. `config/settings.py`, `api/middleware.py::_trusted_client_ip`,
   `web/src/lib/server-prefetch.ts`, `observability/sentry.py`,
   `api/routes/auth.py::_set_session_cookie`, y tests en
   `tests/test_unit_ip_spoofing.py`.
5. Retirar `api/diagnostico_proxy.py` y su test.
6. Actualizar los comentarios de `render.yaml` y `docker-entrypoint-api.sh`
   sobre `FORWARDED_ALLOW_IPS`, que hoy presentan la variable como la solución.

**Archivos de partida:** `api/middleware.py`, `api/routes/auth.py`,
`config/settings.py`, `web/next.config.ts`, `web/vercel.json`,
`web/src/lib/server-prefetch.ts`, `observability/sentry.py`.
**Riesgo:** medio — toca la base del rate limiting; el fallo de configuración
(secreto ausente o distinto) degrada al comportamiento actual, no bloquea a
nadie.

## 7. Cómo verificarlo en producción tras aplicarlo

- Dos personas en redes distintas abren la app: en `http_request` de
  `/api/v1/auth/me`, cada una con su `client_ip`, **estable** durante su sesión,
  pública y distinta de la otra. Ninguna `10.x`.
- Las peticiones del SSR (`/publico/sitemap/*`, prefetch del dashboard) dejan de
  salir con `10.x`.
- Petición directa al host de Render con `X-Real-IP` inventada y la cabecera
  secreta errónea o ausente: el `client_ip` no es la inventada. (La hace el
  propietario: es una petición contra producción.)
- Cuota por IP: seis `POST /auth/password-reset/confirm` con un token inválido
  desde una red → el sexto, 429; desde la otra red, el primero no da 429.
  (Con `password-reset/request` no se ve: responde 202 igual con la cuota
  agotada, para no revelar nada.) O cinco logins fallidos contra una cuenta de
  prueba desde una red → 429 ahí, y la misma cuenta entra desde la otra.
- `/me/sesiones` enseña la IP del visitante, no la del proxy.

## 8. Preguntas para el propietario

1. ¿Qué rango hay hoy en `FORWARDED_ALLOW_IPS` en el panel de Render: ¿incluye
   `10.0.0.0/8` o algo `10.19x`, o la variable no existe? El log dice que no
   cubre `10.19x`; basta con decir el rango, no hace falta pegar el valor.
2. ¿Aceptás un secreto compartido entre Vercel y Render, con su rotación (dos
   valores aceptados durante el cambio)?
3. ¿Qué plan tiene el proyecto de Vercel? Hay que confirmar que los
   `transforms` de `routes` están disponibles en él.
4. ¿Hay clientes que llamen al host de Render directamente y necesiten cuota por
   IP (integraciones con clave, scripts)? Con clave ya cuentan por clave.
5. ¿Hasta cuándo puede quedarse el log de diagnóstico? La propuesta es
   retirarlo con la opción elegida.
6. ¿Hay o habrá un dominio propio para la API (afecta a C)?

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | El diagnóstico y lo que venga, en `api/` y `config/` | Strict sin `Any` ni `ignore` |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno | — |
| §3.4 Auto-marking tests | Tests `test_unit_*` sin BD | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | No cambia el mecanismo; cambia la entrada de las cuotas que lo protegen | Comparación en tiempo constante, rotación |
| §3.8 Frontend vía API | Ninguno (B sigue por el rewrite) | — |

## Acceptance criteria

- [ ] Diagnóstico leído en producción y la cadena real anotada en §2.
- [x] Opción elegida por el propietario y anotada aquí (B, 2026-10-26).
- [ ] Verificación de §7 hecha y anotada con fecha.
- [ ] Secreto puesto en Vercel y Render, y la regla de `web/vercel.json`
  validada en un preview.
- [ ] `api/diagnostico_proxy.py` retirado (tras la verificación de §7).
- [ ] `make lint && make typecheck && make test-unit` en verde.
