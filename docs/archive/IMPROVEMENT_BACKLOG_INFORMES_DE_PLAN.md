---
tags: [backlog, archivo]
---

# Backlog — informes de plan (archivo histórico)

Movidos desde [IMPROVEMENT_BACKLOG.md](../IMPROVEMENT_BACKLOG.md) el 2026-11-06. Son fotos del estado de
los planes de 2026-09 (rendimiento, funcionalidades, arquitectura v1 y v2) y del repaso del 2026-08-27,
escritas en su momento: **no describen el árbol de hoy** y no sustituyen a los ítems abiertos del backlog.
La única parte aún viva, las verificaciones pendientes del despliegue de rendimiento, se quedó en el backlog.

## Rendimiento 2026-09 — rama `claude/app-performance-optimization-222a43`

Revisión de rendimiento del 2026-09-24 y su implementación (2026-09-25). Punto
de partida medido: las funciones de Vercel corrían en `iad1` (`X-Vercel-Id:
cdg1::iad1::…` en `/login`) con la API en Frankfurt y la BD en París; el
dashboard es `force-dynamic` sin caché de router; la API es un proceso con un
event loop y `--limit-concurrency 20`.

**Hecho en la rama** (detalle en los commits):
- **Red y navegación:** `regions: ["fra1"]`; `staleTimes.dynamic = 30`; cambiar
  de pestaña, carril, periodo o búsqueda de Renovaciones ya no navega
  (`lib/url-superficial.ts`); prefetch de servidor con 600 ms de presupuesto y
  el del Radar movido a su página; esqueletos propios en Radar, Mercado y
  Oportunidades.
- **Frontend:** búsqueda del ámbito con debounce y cancelación de peticiones
  (`signal` hasta `fetch`); `gcTime` 30 min y `refetchOnWindowFocus` solo donde
  aporta; `keepPreviousData` en Radar y agenda; total de /detalle solo en la
  primera página; organización por defecto adelantada; overlays del dashboard,
  recharts de /resumen y pestañas de la ficha de oportunidad bajo demanda;
  streaming del copiloto agrupado por frame; SSE de la campana cerrado con la
  pestaña oculta y montado una sola vez; fichas y hubs públicos en ISR sin
  cambiar URLs (`lib/paginacion-hubs.ts`), con precarga solo ante intención.
- **API:** cuota fuera del event loop y en Redis por defecto; middlewares ASGI
  puros; caché de respuestas sin E/S en el loop, con clave canónica (cerraba
  una colisión entre parámetros) y ETag calculado al guardar (ADR-035); sesión y
  organización personal con menos viajes; `/notifications` en una conexión;
  SSE con una consulta por señal; pools con conexiones mínimas verificadas;
  consulta cancelada como 503 que el navegador no reintenta; el
  `--limit-concurrency` de uvicorn pasa de 20 a 200 (cada pestaña ocupaba una
  plaza con su SSE).
- **Analítica:** `adj_indicadores` del snapshot aunque haya filtro; consultas
  del overview en paralelo acotado; variantes precalculadas para las cinco
  tecnologías más frecuentes; scoring del Radar por columnas (×15-20);
  `/competitive/*` cacheado; migraciones `v142` (GIN de tecnología) y `v143`
  (trigram de la búsqueda `q` plegada), escritas y sin aplicar.
- **Tests:** `tests/conftest.py` clasificaba por ruta absoluta y en un checkout
  con «performance» en el nombre `make test-unit` no seleccionaba ningún test.

**Pendiente:** los cuatro ítems marcados «Rendimiento 2026-09» más abajo —el
primero, aplicar `v142`/`v143` justo después de mergear: hasta entonces el smoke
falla y `ml-scoring` no corre—, y comprobar tras el primer despliegue que
`X-Vercel-Id` de `/login` dice `fra1`, que `?p=2` de un hub da
`X-Vercel-Cache: HIT` a la segunda petición, que el log de la API muestra
`ratelimit_redis_connected` y ningún `Exceeded concurrency limit`, y que el
panel de Render no fija `UVICORN_LIMIT_CONCURRENCY` a mano.

## Plan de funcionalidades 2026-09 — ejecutado casi entero

El plan y sus criterios de aceptación están en
[plans/2026-09-plan-funcionalidades.md](../plans/2026-09-plan-funcionalidades.md).
Treinta y ocho funcionalidades en seis recorridos; **treinta y seis con
backend** (F4.6 se desbloqueó el 2026-09-18) y dos descartadas por su propia
decisión (F2.1 y F6.6). Tener backend no es tener pantalla: ver la nota de
abajo.

*Estado (2026-09-19):* el «treinta y seis con backend» era optimista en dos
ítems, comprobado en el código: **F1.4 no tiene backend real** — el scoring
nunca emite `organo_anula_frecuente` (solo existen su texto en
`services/analytics/scoring_explicacion.py` y su rótulo en
`web/src/lib/riesgos.ts`) y no hay tasas precalculadas —, y **F2.8 tiene
backend solo para la tabla** (`POST /licitaciones/comparar`): `/ask` sigue
aceptando un único `id_externo`, así que la pregunta cruzada falta también en
el backend, no solo en la UI.

*Estado (2026-10-12):* las dos salvedades de arriba ya no describen el código.
F1.4 tiene backend: `tasas_anulacion_organo` (v141) alimenta el flag
`FLAG_ANULACION` de `services/analytics/scoring.py`. Y `/ask` acepta
`ids_externos` con hasta tres expedientes (`api/routes/ask.py`), que el
Investigador usa (`web/src/lib/ask-stream.ts`).

Lo que **no** se hizo, y por qué:

| Ítem | Estado | Motivo |
|---|---|---|
| F2.1 Hitos del procedimiento | **Descartado por D32** | El spike midió 735 entradas del ATOM en vivo: `OpenTenderEvent` aparece en el **0 %**, muy por debajo del umbral del 30 % que D32 fijaba. Ver [el documento del spike](plans/2026-09-spike-d32-hitos-procedimiento.md). La consecuencia prevista —que la fecha prevista de adjudicación se estime sola— está implementada (F4.4), y `ExpectedAward.metodo` ya admite `hito` para el día que la Plataforma los publique. |
| F4.6 Plantillas de tareas por etapa | **Hecho el 2026-09-18** (rama `worktree-agent-a46c6c93b69b8f96c`) | Se desbloqueó al llegar las tareas C6.1 (v122). Sin migración: plantilla en `plantillas_organizacion` (`tipo='tareas'`), instanciación idempotente por `pursuit_events`, editor en Equipo → Organización. |
| F6.6 Boletín público | **Descartado por D36** | La propuesta de D36 es «no hasta que exista dominio propio (v2 S1.3) y política de privacidad para suscriptores». Ninguna de las dos existe. |

Lo que se hizo **con fallback**, porque su dependencia no está en este árbol
(no hay outbox de eventos, ni maestro de órganos, ni invitaciones de v2):

- **F1.5** guarda la cuenta objetivo en tabla propia y, desde v145, sus
  órganos en `cuenta_organos`, cada uno con su nombre plegado, que es lo que el
  plan prevé hasta que llegue C1.2. La columna `organo_id` existe, nullable,
  para que ese maestro la rellene sin migración; en 2026-09 el maestro tenía
  248 órganos y no cubría ni los del Ayuntamiento de Madrid. Estado completo
  en el plan.
- **F5.1–F5.4, F3.4 y F4.3** entregan por los jobs y la campana que ya existen,
  no por el outbox. El catálogo de subtipos de aviso está escrito una sola vez
  (`services/avisos.py`), así que enchufarlo al outbox cuando exista es cambiar
  el productor, no el vocabulario.
- **F3.2** distingue «nosotros perdimos» de «ellos ganaron»: sin el NIF propio
  (v2 S2.1) sólo se puede afirmar lo primero, y la respuesta lo declara. La
  pestaña «Contra mí» lo pinta así desde el 2026-09-18 (UI de F1.2, F3.2,
  F3.3, F5.4 y F5.6 en la rama `worktree-agent-aa4eeee01ef3fbb62`; ver el estado de cada ítem en el plan).
- **F2.3** se entregó sin responsable; desde el 2026-09-18 el responsable es
  el de la tarea C6.1 del documento (rama `worktree-agent-a46c6c93b69b8f96c`).

**«Implementadas» significaba backend.** Varias de las treinta y cinco no
tenían pantalla. En el lado de oportunidades, la UI llegó el 2026-09-18 (rama
`worktree-agent-a46c6c93b69b8f96c`) para F1.6 (aplicar/quitar etiquetas; falta
el filtro en Radar y Detalle), F2.3, F3.1, F4.1 (sin pantalla para editar las
probabilidades), F4.3 (sin «preparar renovación», que no tiene endpoint), F4.4
y F4.6. El estado de cada una está anotado en el plan.

*Estado (2026-10-23):* las salvedades de ese párrafo y del siguiente ya no
describen el código, y el plan lo anota ítem por ítem: F1.6 filtra por
etiqueta en Detalle (en servidor) y en Radar; F4.1 edita las probabilidades en
Equipo → Organización; F4.3 tiene «Preparar renovación»
(`POST /pursuits/cartera/{id}/renovacion`); y F2.6 descarga el PDF del guion
(`GET /licitaciones/{id}/guion.pdf`).

Pantallas que faltaban de lado ficha y superficie pública (2026-09-18, rama
`worktree-agent-ac5d5218d7d3b1f8b`): F2.2, F2.5, F2.6, F2.8, F6.2 y F6.5 ya
tienen UI; el estado por ítem está anotado en el plan. Quedan sin hacer: el
PDF del guion (F2.6, sin ruta en el backend), `/ask` multi-expediente (F2.8;
hecho después, ver el estado del 2026-10-12 de arriba) y la emisión de `evidencia_abierta` (F2.5). Los E2E nuevos
(`pagina-cita.spec.ts`, bloque de órganos de `seo.spec.ts`) no se ejecutaron
en local.

Ítems de **este** backlog que el plan toca:

| Ítem | Estado tras el plan |
|---|---|
| [P3] Unificar la definición de «Calientes» | **Sin tocar** — sigue abierto |
| [P2] Remediación axe: 4 reglas desactivadas | **Cerrado** el 2026-09-19 — las cuatro reactivadas; ver _Cerrados_ |

Hallazgos nuevos que el plan destapó y ya están corregidos: el
`TIPO_CONTRATO_LABELS` con dos etiquetas desplazadas y cuatro códigos sin
traducir; `list_cursor` comparando `tecnologia` por igualdad sobre una columna
que guarda un CSV; la rama FTS ignorando los filtros; y la consulta de
lead-time contando dos veces los expedientes duplicados.

## Plan de arquitectura 2026-09 — ejecutado parcialmente

El diagnóstico de arquitecto del 2026-09-02 y su plan por streams están en
[plans/2026-09-plan-arquitectura.md](plans/2026-09-plan-arquitectura.md), con el
estado real de cada ítem en su §8. Excluía a propósito `backup.yml` y
`restore-drill.yml` (decisión del usuario del 2026-09-02); ambos se retiraron
el 2026-09-28 al delegar los backups en Supabase.

Ítems de ESTE backlog que el plan toca, para que nadie los trabaje dos veces:

| Ítem | Estado tras el plan |
|---|---|
| [P2] `HistGradientBoosting` revienta con una feature todo-NaN | **Cerrado y movido** el 2026-09-06 a _Cerrados_ — el entrenamiento descarta antes del ajuste las columnas sin ningún valor observado, con log y test |
| [P2] `render.yaml` no gobierna el servicio de producción | **Parcial** — la decisión se tomó el 2026-09-06 (O0.2 del plan v2: se vincula el Blueprint y `autoDeploy` se apaga); vincular y verificar en el dashboard sigue siendo acción del usuario |
| [P2] Migrar las llamadas del frontend al cliente tipado | **Cerrado y movido** el 2026-09-06 a _Cerrados_ — no queda ningún `fetch("/api/…")` crudo fuera de `lib/`, y una regla ESLint impide que vuelva |
| [P3] Vigilar el crecimiento de `predicciones_baja` | **Cerrado y movido** el 2026-09-06 a _Cerrados_ — el job de ML purga por antigüedad, y el consumidor distingue el p50 del modelo del del baseline histórico |
| [P3] F5: refactor de repositories (ratchet TID251) | **Progresa** — la whitelist baja de 32 a 28 archivos, y a 26 el 2026-09-16 (`kpi_precompute`, `mercado`); 12 el 2026-10-25; el destino sigue siendo vaciarla |
| [P1] Cobertura de tests de las páginas del frontend | **Cerrado y movido** el 2026-09-18 a _Cerrados_ — primera medición local completa; pisos globales y de `src/app/**` subidos a lo medido |
| [P2] Contrato de paginación común | **Cerrado y movido** el 2026-09-18 a _Cerrados_ — dependencia `limit`/`offset` compartida en `api/pagination.py`, primera ola de siete rutas; `trends` ya exponía `group_by` |
| [P2] Remediación axe: 4 reglas desactivadas | **Cerrado y movido** el 2026-09-19 a _Cerrados_ — `nested-interactive` (C7.1), las tres restantes el 2026-09-18 y los rojos que destapó el E2E en `8a424967` y `0fd5082c`; sin `disableRules` ni `fixme` |
| [P3] Los dos módulos-dios (`aggregates.py`, `settings.py`) | **Abierto** — sigue vigente la regla oportunista; plan de partición escrito en el ítem (2026-10-25) |
| [P3] Unificar la definición de «Calientes» | **Cerrado y movido** el 2026-09-18 a _Cerrados_ — se mantiene la heurística de importe como «Grandes en plazo», documentada en los DTOs |
| [P3] Descartar los avisos fantasma de Dependabot | **Abierto** — acción del usuario en GitHub; 33 descartados el 2026-08-30 y 8 nuevos desde entonces (2026-09-24) |

Ítems **nuevos** que salen del plan y no estaban aquí: partir las páginas
monolito del dashboard (S5.2), el prefetch en servidor con hidratación (S5.1) y
el grupo de rutas `(privado)` que unifica `Providers`/`Toaster` (S5.9). Los tres
los recoge hoy el ítem de S7 del plan v2, más abajo.

## Plan de arquitectura 2026-09 **v2** — Ola 0 en curso

El sucesor está en
[plans/2026-09-plan-arquitectura-v2.md](../plans/2026-09-plan-arquitectura-v2.md)
y es la **fuente única de alcance y criterios** de sus ocho streams: los ítems
`[Ola 1]` de este backlog existen para que la priorización no exija leerlo
entero, y remiten al plan en vez de copiarlo (dos copias del mismo criterio
divergen).

O0.5 se ejecutó el **2026-09-06**: las decisiones D1–D9 y D11–D20 quedan
cerradas con fecha y evidencia en las tablas §3 de los dos planes, y los ítems
que el código ya había resuelto bajan a _Cerrados_. Lo que las tablas cierran es
la **decisión**, no siempre su ejecución: las dos que dependen del dashboard de
Render siguen abiertas como trabajo —D4 la ejecuta O0.2 (y el P2 de `render.yaml`
de más abajo es su mitad de infraestructura) y D5 la ejecuta O0.3—, y los
streams de Ola 1 arrancan con su decisión ya tomada.

**Qué de la Ola 1 entra aquí y qué no.** Hay un ítem `[Ola 1 · Sx]` por cada uno
de los siete streams que no tienen ya sitio en este backlog: S1, S2, S3, S4, S5,
S7 y S8.

**S6 no lleva ítem propio**, y no por olvido: tres de sus cinco subítems ya
tienen entrada aquí y se siguen desde ella —S6.1 desde el P2 «El corpus de PSCP
ahoga el dataset del clasificador SAP», que es el diagnóstico que el propio
subítem del plan cita; S6.3 desde el P1 del golden set; S6.5 desde el P2 del
modelo de baja por lote—, y abrirle un ítem paralelo dejaría dos sitios donde
mirar lo mismo. Los dos que no tienen entrada (S6.2, etiquetas no circulares;
S6.4, criterio de promoción escrito) están en el §5 del plan y son de esfuerzo S.

**Lo que esta sección NO dice es cuánto de la Ola 1 está ya escrito.** Los
streams los están entregando agentes distintos en paralelo mientras se redacta
esto, así que cualquier foto del estado que tomara este fichero nacería
caducada — y un backlog que lista como abierto algo ya cerrado es exactamente la
avería que O0.5 existe para arreglar. Quien manda sobre el estado es el §5 del
plan, donde cada stream anota lo entregado al cerrarse — la misma convención que
la Ola 0 ya usa en su §4. Estos ítems los da de baja la consolidación de la ola,
no una comprobación hecha a mitad de ella.

## Repaso del 2026-08-27 (auditoría de producto/UX)

Este fichero y [UX_AUDIT.md](../UX_AUDIT.md) iban por detrás del código que citaban. Lo que cambió:

- **Cerrado y archivado:** el P1 de los enlaces caducados de PLACSP — entregado entero en `c230e63` (PR #191), no en los tres SHAs que el ítem citaba, que nunca llegaron a `master`. Ficha completa en [el archivo](IMPROVEMENT_BACKLOG_CERRADOS.md).
- **Altas:** dos P1 (allowlist de acceso, `plan: free` frente al SLO) y dos P2 (onboarding de primer uso, experiencia móvil). El de la allowlist nace como **RFC**, no como PR: toca auth y necesita migración. *(2026-09-19: los cuatro están resueltos; el del `plan: free` nunca llegó a tener entrada — ver la nota del P3 de staging.)*
- **Cifras corregidas** en el P1 de cobertura del frontend: las páginas de 1.000+ líneas que citaba ya no existen.
- *(2026-09-28: el P0 de los backups sin copia remota se descartó al delegar las
  copias en Supabase; ver el archivo.)* El índice del scoring en frío ya existe en
  `v84_lic_universo_cpv_index`; queda medir su efecto tras aplicar la revisión, no
  volver a implementarlo.
