---
id: ADR-024
title: "services/ es biblioteca de dominio, no frontera obligatoria de persistencia"
status: accepted
date: 2026-07-28
deciders: "Daniel Kalitovics"
related:
  - "[[ADR-007-services-domain-layer]]"
  - "[[ADR-022-frontera-de-persistencia]]"
tags: [adr, architecture, boundaries, api]
---

# ADR-024 — services/ es biblioteca de dominio, no frontera obligatoria de persistencia

* **Estado:** Aceptado
* **Fecha:** 2026-07-28

## Contexto

`AGENTS.md` describe `services/` como "Lógica de dominio ... Core; usa
`db.repositories.*`" y cita ADR-007 como su origen. Medido hoy:

```
$ grep -rln '^from db\.\|^    from db\.' api/routes/*.py | wc -l
18
```

18 de 27 archivos en `api/routes/` importan `db.*` directamente, saltándose
`services/`. El ratchet TID251 ([[ADR-022-frontera-de-persistencia|ADR-022]])
vigila **dónde vive el SQL** (dentro de `db/`) — no **qué capa puede llamar a
`db/`**. Desde la perspectiva del propio ratchet, los 18 archivos cumplen: el
SQL está en `db/`. Eso deja sin responder la pregunta real: ¿debería
`api/routes/` poder llamar a `db.*` en absoluto, o debería pasar siempre por
`services/`?

### Por qué ni ADR-007 ni ADR-022 la zanjan

- **ADR-007** nació para sacar lógica de dominio pura (normalización,
  clasificación) de `dashboard/` (Streamlit) — su alcance histórico era
  "UI ↔ dominio", no "`api/routes/` ↔ `services/` ↔ `db/`". Su propia
  sección de consecuencias lista como positivo que "la API puede importar de
  `services/`" — permite, no exige. Y su lista de alternativas descartadas
  rechaza explícitamente la sobre-ingeniería (inyección de dependencias vía
  Protocol "para funciones puras" — descartado).
- **ADR-022** dice explícitamente en su §4 que `api/`, `scheduler/`,
  `scraper/`, `scripts/` "tampoco" escriben SQL — pero esa frase es sobre
  **dónde vive el texto SQL**, no sobre si esos paquetes pueden invocar una
  función/repository de `db/` directamente sin pasar por `services/`.
  ADR-022 es explícito en que `db/repositories/*` (clases) y `db/*.py`
  (funciones) son "el mismo estrato" de persistencia — pero no dice quién
  puede llamarlo.

### Lo que muestra el código real

Se leyó una muestra representativa de los 18 archivos
(`api/routes/watchlist_items.py`, `api/routes/me.py`, `api/routes/auth.py`,
más `admin_users.py`, `competitive.py`, `empresas.py`, `eventos.py`,
`exports.py`, `feature_flags.py`, `feedback.py`, `licitaciones.py`, `meta.py`,
`models.py`, `saved_filters.py`, `search.py`, `security.py`,
`watchlist_rules.py`, `webhooks.py`). Hay dos grupos distintos, no uno:

1. **4 archivos ya llevan SQL crudo dentro de la ruta** (`connect`/
   `connect_read` importados directamente): `empresas.py`, `eventos.py`,
   `exports.py`, `watchlist_rules.py`. Ya están en la whitelist TID251 y
   destinados a vaciarse por ADR-022 §4 — es una violación **más grave** que
   la pregunta de este ADR y ya tiene mecanismo de seguimiento. No es el
   sujeto de esta decisión.
2. **Los ~14 restantes** importan repositorios/funciones ya encapsulados de
   `db/` (`db.repositories.licitaciones.LicitacionRepository`,
   `db.repositories.watchlist.WatchlistRepository`, `db.audit.log_event`,
   `db.sessions.*`, `db.users.*`, `db.saved_filters.*`,
   `db.model_registry.*`) para operaciones CRUD directas: leer por id,
   listar paginado, escribir un registro de auditoría, crear/revocar una
   sesión, marcar/desmarcar un favorito. Ninguna de estas llamadas hace una
   transformación de dominio — son passthroughs parametrizados.

Y — dato clave — **cuando sí hay lógica de dominio real, el código ya pasa
por `services/`, sin que nadie se lo exigiera formalmente**:
`competitive.py` importa `db.watchlist_empresas.*` para lecturas simples
**y** `services.competitive.{bajas,mercado,renovaciones}` para la agregación
competitiva real; `eventos.py` usa `services.contract_events` para construir
el feed; `feature_flags.py` usa `services.feature_flags` para la regla de
negocio de flags; `watchlist_rules.py` usa `services.watchlist_rules` para
el matching; `licitaciones.py` usa `services.licitaciones.search_advanced`
para el ranking de búsqueda; `exports.py` usa `services.exports`/
`services.licitaciones.fetch_for_pdf` para generar el documento. El patrón
de facto ya es: **CRUD simple → `db.*` directo; regla de negocio →
`services/`**. Nadie lo impuso con una herramienta — es lo que emergió.

### Dónde se garantizan hoy tenencia/auth/validación (sin depender de `services/`)

Antes de decidir, se verificó explícitamente dónde viven estas tres
invariantes, porque si la respuesta fuera "solo si pasa por `services/`",
elegir la opción (b) sería negligente:

- **Auth**: en dependencias de FastAPI inyectadas por ruta —
  `Depends(require_any_auth)` / `Depends(require_scope(...))` /
  `Depends(require_recent_session())`, definidas en `api/auth.py` y
  `api/routes/dual_auth.py`. Es un mecanismo transversal completamente
  ortogonal a si la ruta llama a `services/` o a `db/`.
- **Scoping de tenencia**: vive en el **predicado SQL del repository**, no
  en una capa intermedia. `db/repositories/watchlist.py::list_items/
  add_item/remove_item/export_by_user_key/anonymize_by_user_key` reciben
  `user_key` como parámetro obligatorio y lo usan en el `WHERE`. Ese
  `user_key` canónico se calcula **una vez**, en la dependencia de auth
  (`shared/identity.py::user_key_from_email`, invocado desde
  `api/routes/dual_auth.py::require_any_auth`), y se adjunta al contexto de
  la request. Una capa `services/` intermedia no añadiría una segunda
  comprobación de scoping — solo reenviaría el mismo parámetro que ya
  recibe la ruta.
- **Validación**: modelos Pydantic (`WatchlistItemBody`,
  `DeleteMyDataRequest.confirmation: Literal["DELETE"]`,
  `UserProfileBody.validate_weights()`) validados por FastAPI en el borde de
  la ruta — de nuevo, ortogonal a `services/`.

Ninguna de las tres depende de "siempre pasa por `services/`" hoy. Elegir
(a) no cerraría ninguna brecha real de seguridad — solo movería código.

## Decisión

**Se elige la opción (b): `services/` es biblioteca de dominio, no frontera
obligatoria.**

1. **`services/` sigue siendo la capa de dominio** (ADR-007 no se
   revierte): agregación multi-tabla, clasificación, scoring, matching de
   reglas, orquestación con lógica condicional — todo eso **debe** vivir en
   `services/`, y la ruta debe llamar a `services/`, no reimplementar la
   lógica ni llamar a `db/` para ensamblarla a mano.
2. **`api/routes/` puede importar `db.*` directamente para operaciones CRUD
   parametrizadas sin transformación de dominio**: leer por id, listar
   paginado con filtros simples, escribir/leer una fila de auditoría,
   gestionar sesiones/usuarios/API keys, alternar un favorito. Esto es
   legítimo y no se marca como deuda.
3. **Criterio operativo para revisión de código** (no hay herramienta que lo
   automatice, ver Consecuencias): "¿esta llamada a `db.*` ejecuta algo que
   una persona describiría como una regla de negocio (agregación, matching,
   scoring, orquestación condicional multi-tabla), o es CRUD parametrizado
   (leer/escribir una fila o lista por clave)?" Regla de negocio →
   `services/`. CRUD → directo desde la ruta está bien.
4. **No se crea un ratchet nuevo análogo a TID251 para esto.** Un ratchet
   necesita una línea nítida y automatizable; "¿es lógica de negocio?" no lo
   es. Un check de "cero imports de `db.*` en `api/routes/`" sería
   trivialmente burlable envolviendo cada CRUD en una función passthrough de
   `services/` que no agrega nada — exactamente la sobre-ingeniería que
   ADR-007 ya rechazó para un problema análogo (su alternativa 3
   descartada). Se prefiere dejar la pregunta a revisión humana antes que
   automatizar una respuesta falsa.
5. **Los 4 archivos con SQL crudo en la ruta** (`empresas.py`, `eventos.py`,
   `exports.py`, `watchlist_rules.py`) no cambian de estado con este ADR:
   siguen siendo la violación real, ya trackeada por TID251/ADR-022 §4, y
   deben vaciarse ahí — moviendo el SQL a `db/`, no necesariamente a través
   de `services/` si la operación resultante es CRUD simple.

## Consecuencias

**Positivas:**
- La decisión coincide con lo que el código ya hace en su mayoría — no
  exige un refactor masivo de 14 archivos cuyas llamadas a `db.*` son CRUD
  legítimo.
- Evita el coste de servicios-passthrough ceremoniales que ADR-007 ya había
  descartado como patrón para código similar.
- Da a quien revisa una pregunta concreta ("¿regla de negocio o CRUD?") en
  vez de un lint binario que no puede distinguir los dos casos.
- Dice explícitamente dónde se garantizan tenencia/auth/validación
  (dependencias de FastAPI + predicado SQL parametrizado en el repository),
  así que la arquitectura no depende silenciosamente de una capa que en la
  práctica el 67% de las rutas (18/27) ya se saltan.

**Negativas:**
- Sin ratchet automatizado, la línea CRUD/regla-de-negocio depende del
  juicio de quien revisa el PR y puede desdibujarse con el tiempo (un CRUD
  "simple" que gana un `if` de negocio y nadie lo mueve a `services/`).
  Mitigación: la pregunta del §3 de la Decisión debe citarse explícitamente
  en revisiones de `api/routes/*`; no hay mecanismo automático, es
  disciplina de review.
- Se encontró, durante esta revisión, que `watchlist_items.py` y `me.py`
  reimplementan localmente la derivación de `user_key` (fallback hash de
  email/key_hash) en vez de llamar siempre a
  `shared.identity.user_key_from_email` — funciona hoy porque ambas
  implementaciones se mantienen consistentes por convención/comentario
  cruzado ("misma convención que watchlist_rules/watchlist_items/
  competitive"), pero es una duplicación de una pieza de scoping que
  debería vivir en un solo sitio. No se corrige en este ADR (no es su
  alcance tocar código), se deja anotado como hallazgo.
- Los 4 archivos con SQL crudo en rutas siguen siendo deuda activa; este ADR
  no acelera ni retrasa su cierre, solo aclara que no son el mismo problema
  que los otros 14.

## Alternativa descartada

**(a) `services/` como frontera obligatoria + ratchet análogo a TID251** que
detecte imports de `db.*` en `api/routes/*.py` y solo permita que la
whitelist encoja. Se descarta porque: (i) exigiría envolver ~14 operaciones
CRUD triviales en funciones `services/` que no añaden lógica, solo
indirección; (ii) el propio ADR-007 rechazó ese patrón de sobre-ingeniería
para un problema estructuralmente idéntico; (iii) no cierra ninguna brecha
real de tenencia/auth/validación, que ya viven fuera de `services/` (ver
Contexto); (iv) un ratchet de "cero imports" sería indistinguible de éxito
si todo el mundo simplemente envuelve cada CRUD en un passthrough — mediría
cumplimiento de la letra, no del objetivo real de mantener las reglas de
negocio en un solo sitio.
