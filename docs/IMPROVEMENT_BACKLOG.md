# Improvement Backlog

Lista viva de mejoras conocidas, priorizadas. **Diseñada para que un agente pueda elegir un ítem y trabajarlo sin pedir contexto extra al usuario.**

## Convenciones

- **Prioridad**: P0 (urgente / bloquea) · P1 (alta) · P2 (media) · P3 (nice-to-have).
- **Riesgo**: bajo (cambio aislado) · medio (afecta varios módulos) · alto (toca core / migra schema / cambia contrato).
- Si añadís un ítem nuevo, copiá la plantilla del final.
- Al cerrarlo, no lo dejes tachado aquí: **movélo entero a la sección _Cerrados_** del final con la fecha y el commit/PR que lo resolvió. Las secciones P1/P2/P3 contienen **solo ítems abiertos**.

## Plan 2026-10 — foco de piloto (PROPUESTO el 2026-10-26)

[plans/2026-10-plan-foco-piloto.md](plans/2026-10-plan-foco-piloto.md) fija
**el orden** de lo que queda abierto aquí y **qué se aplaza**. No redefine
criterios: cada ítem conserva los suyos, y el estado se anota en el §8 del plan.
Hasta que el propietario tome sus decisiones D50–D58, el orden de abajo es una
propuesta.

| Ola | Ítems de este backlog |
|---|---|
| 0 — que funcione lo prometido | P1 «Recuperación de contraseña» (1) y (2); P1 «[Ola 1 · S5]» (suspender `TenderFlow-1`); P2 «[Ola 1 · S8]» (reencolado); P2 «Sentry»; P2 «latido del healthcheck»; P2 «claves de API sin dueño» |
| 1 — verdad del dato | P1 «La identidad de PLACSP no incluye el órgano» (fase B), con P2 «condiciones oficiales de CODICE» en la misma reingesta; P1 «sap_classifier»; P1 «Ampliar el golden set»; P2 «El corpus de PSCP ahoga…» |
| 2 — ciclo central | Ítems nuevos B1–B6 del plan (alerta por defecto, ficha para lo que casa, resumen con ficha, checklist asistido, primeros pasos, cierre por NIF) |
| 3 — medir y recortar | P2 «La telemetría de producto» |
| 4 — plataforma y proceso | P1 «[Ola 1 · S1]» (fase 3 de `user_key`); P3 «fechas a `timestamptz`»; P2 «[Ola 1 · S4]»; P2 «Desbloquear los pines»; P3 «gates stdlib»; P3 «ratchets congelados»; P3 «El coste de leer el repo» |
| Aplazados (§4 del plan) | P2 «Encender las fuentes nuevas»; P2 «Antes de activar Microsoft»; P2 «Modelo de baja por lote»; P2 «`baja_model` v2 y `retencion_model` v1»; P2 «[Investigador] búsqueda por significado»; P3 «Entorno de staging» |

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
[plans/2026-09-plan-funcionalidades.md](plans/2026-09-plan-funcionalidades.md).
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
| F2.1 Hitos del procedimiento | **Descartado por D32** | El spike midió 735 entradas del ATOM en vivo: `OpenTenderEvent` aparece en el **0 %**, muy por debajo del umbral del 30 % que D32 fijaba. Ver [el documento del spike](archive/plans/2026-09-spike-d32-hitos-procedimiento.md). La consecuencia prevista —que la fecha prevista de adjudicación se estime sola— está implementada (F4.4), y `ExpectedAward.metodo` ya admite `hito` para el día que la Plataforma los publique. |
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
[plans/2026-09-plan-arquitectura.md](archive/plans/2026-09-plan-arquitectura.md), con el
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
[plans/2026-09-plan-arquitectura-v2.md](plans/2026-09-plan-arquitectura-v2.md)
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

Este fichero y [UX_AUDIT.md](UX_AUDIT.md) iban por detrás del código que citaban. Lo que cambió:

- **Cerrado y archivado:** el P1 de los enlaces caducados de PLACSP — entregado entero en `c230e63` (PR #191), no en los tres SHAs que el ítem citaba, que nunca llegaron a `master`. Ficha completa en [el archivo](archive/IMPROVEMENT_BACKLOG_CERRADOS.md).
- **Altas:** dos P1 (allowlist de acceso, `plan: free` frente al SLO) y dos P2 (onboarding de primer uso, experiencia móvil). El de la allowlist nace como **RFC**, no como PR: toca auth y necesita migración. *(2026-09-19: los cuatro están resueltos; el del `plan: free` nunca llegó a tener entrada — ver la nota del P3 de staging.)*
- **Cifras corregidas** en el P1 de cobertura del frontend: las páginas de 1.000+ líneas que citaba ya no existen.
- *(2026-09-28: el P0 de los backups sin copia remota se descartó al delegar las
  copias en Supabase; ver el archivo.)* El índice del scoring en frío ya existe en
  `v84_lic_universo_cpv_index`; queda medir su efecto tras aplicar la revisión, no
  volver a implementarlo.

---

## P0 — Urgente

_Sin ítems abiertos._

---

## P1 — Alta

### [P1] La identidad de PLACSP no incluye el órgano: dos licitaciones con el mismo número de expediente se pisan
- **Área:** scraper/connectors/placsp.py y el parser CODICE, carga bulk, `licitaciones.id_externo` y todo lo que lo referencia, services/dedupe.py (`natural_expediente`) y su gemelo en db/repositories/dedupe.py
- **Problema:** el `id_externo` de las filas `placsp`/`bulk_*` es el `ContractFolderID` sin prefijo ni órgano, y es la PK de `licitaciones`. Cuando dos órganos usan el mismo número de expediente, la segunda licitación sobrescribe a la primera por `ON CONFLICT(id_externo)`. Medido el 2026-10-24 en `licitaciones_history` (fuentes `placsp` y `bulk_%`): **339 de 10.007** `id_externo` con historia tienen dos o más `organo_contratacion` distintos (3,4 %). En una muestra aleatoria de 8, siete eran licitaciones distintas —`2026/LIC/0049`: un servicio web de la Mutua Intercomarcal y un hosting de EGARSAT; `1681/2026`: el Ayuntamiento de Carlet y el de Sanlúcar de Barrameda— y una era un renombre del mismo órgano. En el feed vivo (8 páginas) salieron 67 de 3.646 expedientes compartidos (93 filas, 2,5 %), y en el de agregadas 74 de 7.956 (0,9 %). Las licitaciones pisadas desaparecen del producto sin error: el Radar, la ficha, las adjudicaciones y la analítica ven solo la última que llegó. Y lo que queda mezcla las dos: las adjudicaciones y los documentos no se reemplazan cuando la entrada nueva no trae los suyos, así que una licitación puede heredar el adjudicatario de otro órgano. El RFC cuenta, con órgano **y** título distintos, 379 `id_externo` y 570 pares perdidos (cota inferior: el histórico empieza el 2026-05-22).
- **Hallazgo aparte, del mismo RFC (§«Riesgos y preguntas abiertas»):** la re-key de PSCP (`v153`) no repuntó `domain_events.aggregate_id`, y hoy hay 1.117 eventos de PSCP huérfanos. **Resuelto el 2026-10-24:** `v158_domain_events_pscp_rekey` (#540) repunta los 1.095 con una sola licitación `pscp:{uuid}:{codi}` candidata (0 ambiguos) y conserva los 22 que apuntan a 11 licitaciones que ya no existen —probablemente purgadas—. Aplicada en producción con `migrate.yml`: `plan` (run 40133575553, solo `v158` pendiente) y `apply` (run 40133688669). La consulta de verificación de su docstring dio 1.095 / 0 / 22 antes y 0 / 0 / 22 después. La fase B de este RFC debe llevar `domain_events.aggregate_id` en su lista de referencias.
- **Más evidencia (2026-10-24, ítem de las adjudicaciones multilote):** 8 adjudicaciones sin lote son de otro órgano con el mismo `ContractFolderID` (`04/2026` CERSA/Pinto, `101/2026` ICEX/Collado Mediano, `36/2026`, `47/2026`, `48/2026`, `49/2026`, `51/2026`, `SUM005/2026` Univ. León/Fund. Univ. La Laguna).
- **Cómo se arregló en los conectores nuevos:** contratos menores usa `placsp_menores:<ID_PLATAFORMA>:<ContractFolderID>` (rama `claude/mejoras-2026-10-24`; `ID_PLATAFORMA` viene en el 100 % de las entradas y es 1:1 con el órgano), y PSCP ya usaba `pscp:<uuid>:<expediente>`.
- **Por qué no se cerró en el mismo cambio:** exige cambiar la clave de filas ya escritas y de todo lo que las referencia, URLs públicas incluidas. Es un cambio de persistencia irreversible: RFC y OK del dueño (AGENTS.md §5 y §6). RFC: [2026-10-24-rfc-identidad-placsp-organo-expediente](rfc/2026-10-24-rfc-identidad-placsp-organo-expediente.md) (`draft`).
- **Acceptance criteria:** los del RFC una vez aprobado; como mínimo, que dos licitaciones de órganos distintos con el mismo expediente convivan (test de integración), que el dedupe con TED siga casando por expediente, que las URLs viejas redirijan, y una consulta que cuente cuántas filas pisadas se recuperan de `licitaciones_history` o de la reingesta.
- **Progreso 2026-10-25 — fase A hecha (RFC `approved`, rama `agente/identidad-placsp-fase-a`):** `v163_identidad_placsp_fase_a` añade `licitaciones.organo_ref_fuente` y la tabla `licitaciones_id_anterior` (vacía hasta la fase B); `shared/identidad_placsp.py` es la única definición de `placsp:<órgano>:<expediente>` y del expediente natural, con el gemelo SQL generado desde ella; el parser CODICE guarda el `ID_PLATAFORMA` y el upsert lo conserva con COALESCE y **cuenta la colisión** (`placsp_colision_expediente_total`, log con los dos órganos) en vez de pisar en silencio; `resolver_id_licitacion` + dependencia `resolver_id_externo` (detalle, documentos, similares, competencia esperada; `Deprecation`/`Sunset` 2027-04-30), ficha pública con 308 y MCP resolviendo alias; `LicitacionSummary.expediente` en la consola; `scripts/inventario_pisadas_placsp.py` (detección en `licitaciones_history`, puerta 1 y expedientes que conviven). Tests: `tests/test_identidad_placsp.py` (dos órganos conviven con la clave nueva, TED casa por expediente con las dos claves, gemelos iguales, alias en la API, inventario). **Los escritores siguen con la clave vieja**: nada visible cambia hasta la fase B.
- **Queda (fase B, RFC §fases 2-5):** rellenar `organo_ref_fuente` del histórico por `idEvl` desde los ZIP (puerta: 0 filas sin órgano, `scripts/inventario_pisadas_placsp.py` lo mide), la migración de re-key con sus guardas (lista de §4 **más** `domain_events.aggregate_id` y `licitaciones_id_anterior`), `clave_placsp` en todos los escritores en el mismo PR y con la ingesta parada, reingesta de los 22 ZIP y limpieza de hijas, el ADR que revisa ADR-009, el runbook, `mcp_server/glosario.md`, extender `resolver_id_externo` al resto de rutas `/licitaciones/{id}/…` y a los cuerpos que traen `licitacion_id`.
- **Riesgo:** alto — cambia la PK de la tabla central y sus referencias.

### [P1] Cerrar el incidente de la v2 de `sap_classifier`: ver la pasada en verde y unificar los dos caminos de entrenamiento
- **Área:** scheduler/concept_drift.py, scheduler/jobs/ml_training_run.py, services/ml/promotion.py, services/ml/model_artifacts.py, .github/workflows/train-model.yml, `model_versions` (producción)
- **Progreso (2026-10-26, D55):** mientras no haya versión validada, la probabilidad del clasificador no es señal (`services/ml/senal_clasificador.py`); el Radar ya no la leía. Ver [plan 2026-10](plans/2026-10-plan-foco-piloto.md) §8.
- **Problema:** `scrape-daily` está en rojo desde el 2026-09-29T18:08Z (15
  runs hasta el 2026-10-03T23:09Z). En el primero el paso semanal
  `sap_active_learning` contó 59
  feedbacks humanos (umbral 50), reentrenó **dentro del runner**, pasó el gate y
  dejó activa la v2 en `model_versions` (sha256 `c45898ee…`, nota
  `active_learning_auto_retrain`). El `.pkl` se escribió en `data/models/` de
  ese runner y nadie lo subió a ninguna Release ni al bucket: ya no existe. El
  `precompute_ml_proba(force=True)` posterior agotó los 20 minutos del step
  (primer rojo). Desde la pasada siguiente, `resolve_active_artifact` bajaba el
  `sap_classifier.pkl` de `v1.0.0-models` —el del 2026-05-22, sha256
  `5ddcc0ee…`—, no coincidía con el registrado y `ml_scoring` (bloqueante)
  lanzaba `ModelArtifactMismatch`. Hasta entonces no había versión activa y la
  pasada servía ese mismo asset de mayo por `ensure_downloaded`, sin cotejar.
  La semana anterior (2026-09-22) el mismo paso había fallado al entrenar por
  desbalance (1,2 % de positivos con las 709k filas de PSCP), y por eso no
  ocurrió antes.
- **Hecho:**
  - 2026-10-04T00:19Z, producción: la v2 quedó desactivada (una fila). El
    modelo no tiene versión activa y la pasada sirve el asset de mayo.
  - PR #404 (`ea76b40a`): con `SCHEDULER_PLANE` declarado,
    `maybe_retrain_classifier` no entrena ni activa; paso canónico
    `model_artifacts_canary` (advisory, diario), que coteja el sha256 de cada
    versión activa con el `digest` del asset de la Release sin descargarlo;
    `db.model_registry.list_active`/`deactivate`; sección
    «`ModelArtifactMismatch`» del runbook.
  - PR #403 (`2e341907`): `promote_if_better` numera desde el máximo
    registrado, como `register_version`.
  - PR #405 (`ec970a77`): `train-model.yml` activa **después** de subir
    (entrenar → subir → cotejar el `digest` → activar → `precompute`); el paso
    semanal lanza `train-model.yml` por `workflow_dispatch` (`actions: write`
    en `scrape-daily.yml`) y, si no puede, avisa; el disparador cuenta el
    feedback posterior a la última versión **registrada**, no a la activa, para
    no relanzar cada semana un entrenamiento que el gate ya rechazó;
    `rescore-ml-proba.yml`, manual, para recalcular `ml_proba` con el modelo
    servido.
  - 2026-10-04T01:12Z, producción: `rescore-ml-proba.yml` (run 37167276246,
    3 min). Cargó el asset de mayo (`trained_at` 2026-05-20, umbral 0,466),
    reescribió 24.593 filas y borró 978 scores fuera de la población: la
    población quedó con 0 filas sin `ml_proba`, incluidas las 481 que la
    pasada no había podido puntuar desde el 29/09. **La distribución cambió**:
    `ml_proba ≥ 0,69` pasó de 5.859 de 25.090 filas puntuadas (23 %, medido el
    2026-10-03) a 14.819 de 24.593 (60 %), y `≥ 0,30` de 32 % a 81 %. Dos
    lecturas: la reescritura de la v2 del 29/09, que se cortó a los 68 s, había
    cubierto casi toda la población; y el modelo de mayo da por SAP a la
    mayoría, que es el problema de «El corpus de PSCP ahoga el dataset del
    clasificador SAP». No es reversible: el artefacto de la v2 no existe.
  - 2026-10-09, producción (tabla `jobs`): `ml_scoring` volvió a `ok` en la
    pasada del 2026-10-04T06:09Z y no ha fallado desde entonces — 14 fallos
    entre el 2026-09-29T23:58Z y el 2026-10-03T23:13Z, 17 pasadas `ok` después
    (la última medida, 2026-10-09T06:25Z). `model_artifacts_canary` da `ok` a
    diario y `sap_classifier` sigue sin versión activa. Ops › Ejecuciones
    seguía enseñando ese día el texto del error —6 de los fallos quedaban
    dentro de su ventana de siete días— sin decir de cuándo era, y se leyó como
    un fallo vivo; la fila de un paso recuperado lleva ahora la fecha de su
    último fallo.
- **Acceptance criteria:**
  - Ver correr por primera vez el flujo nuevo de `train-model.yml` (subir →
    cotejar → activar) y el `workflow_dispatch` desde el cierre. El orden de
    pasos, los permisos y el `env` están fijados por tests sobre el YAML; ni la
    activación ni el dispatch contra la API real se han ejecutado todavía: el
    paso semanal corrió el 2026-10-06T18:47Z sin lanzar nada (`train-model.yml`
    no tiene runs desde el 2026-09-27).
  - Decidir qué entrena cada camino: el candidato de `train-model.yml` del
    2026-09-27 (v1, 17.641 filas) fue rechazado con `recall_no_keyword` 0 y el
    del reentrenamiento automático (v2, 57.913 filas, `_fetch_training_dataframe`
    sobre la tabla entera) pasó con 0,33 — uno de tres ejemplos del golden. Con
    el dispatch, el automático entrena ya por el camino de `train-model.yml`;
    queda retirar o alinear el dataset del otro, que solo corre sin plano
    declarado. Ver «Ampliar el golden set del clasificador SAP».
    **Hecho en código el 2026-10-25 (un solo camino):** se retiró el
    reentrenamiento en proceso de `maybe_retrain_classifier` y su dataset
    (`_fetch_training_dataframe`); el paso semanal lanza `train-model.yml` o
    avisa con el comando en **cualquier** plano, también sin
    `SCHEDULER_PLANE`. `promote_if_better` ya no tiene parámetro `activar` ni
    campo `activada`: registra siempre inactivo y deja el candidato que pasa
    en `pendiente_de_activar`; `train_from_db()` tampoco activa, y
    `scripts/ml_clasificadores.py train` lo dice («registrada SIN activar»).
    La única activación es `ml_training_run activar --version N`, que coteja
    el sha256 con la Release antes. Tests: `test_active_learning_publicacion.py`
    (sin plano no entrena; el módulo ya no importa gate ni clasificador),
    `test_ml_promotion_gate.py::test_no_hay_forma_de_pedirle_al_gate_que_active`.
    Runbook: «Verificar la primera pasada de `train-model.yml`» en
    [model-rollback.md](runbooks/model-rollback.md). Queda el primer criterio
    (acción del dueño): `gh workflow run train-model.yml` y comprobar lo que
    lista esa sección —resumen con `Asset: sap_classifier-<sha12>.pkl` y
    «Versión activada», asset en `ml-models` con `digest` igual al `sha256`
    de `get_active("sap_classifier")`, y `model_artifacts_canary`/`ml_scoring`
    en `ok` en la pasada siguiente—.
  - Nombrar el asset de `sap_classifier` por contenido, como los predictivos
    (`rename_to_content_address`). Con nombre fijo, la subida sustituye el
    asset de la versión activa, y por eso «Train model» la retira antes: entre
    ese paso y la activación el modelo se sirve sin cotejar contra el registro,
    y un fallo de la subida después de borrar el asset deja a los runners sin
    modelo. Es el mismo cambio que el punto «Pasar a `locate_release_asset` y
    a una Release fija» de «ml-scoring: verificar en producción el arreglo del
    2026-09-24», y exige que la ingesta resuelva el modelo por
    `resolve_artifact` y no por `ensure_downloaded` + `load()`.
    **Hecho en código el 2026-10-24:** `promote_if_better` publica y registra
    `sap_classifier-<sha12>.pkl` (`services.ml.model_artifacts.content_addressed_path`,
    la misma regla que `rename_to_content_address`); `train-model.yml` lo sube
    a la Release `ml-models` sin `delete-asset` ni retirar la versión activa
    (entrenar → verificar artefactos → subir → activar → medir); la ingesta
    carga por `SAPClassifier.resolve_artifact()` + `load(ruta)` y la cola de
    feedback por `api.model_cache.get_classifier()`. Sin versión activa se
    sigue sirviendo el `sap_classifier.pkl` de mayo de `v1.0.0-models`, que
    `ensure_downloaded` busca ahora con `locate_release_asset`. Queda verlo en
    la primera ejecución de `train-model.yml` (forma parte del primer
    criterio): el resumen debe decir `Asset: sap_classifier-<sha12>.pkl` en
    `ml-models`, el canary dar `ok` y la ingesta registrar
    `pipeline.ml_clf_loaded` con esa ruta. `drift_report`, `ml_eval` y
    `sample_golden_candidates` siguen con `SAPClassifier.load()`.
- *Nota (2026-10-24):* el camino de F3 del plan de tres niveles (`scripts/entrenar_nivel1.py`, `services/ml/nivel1.py`) no registra ni activa nada. Al unificar los dos caminos, el que sobreviva debería ser ese y no `train_from_db`, cuya etiqueta es circular. *(2026-10-25: se unificaron quedándose `train_from_db`, que es el que publica y activa por `train-model.yml`; cambiar su etiqueta por la de nivel 1 sigue abierto y no exige otro camino.)* Registrar en `model_versions` y la semana en sombra siguen pendientes de OK.
- **Files de partida:** [scheduler/jobs/ml_training_run.py](../scheduler/jobs/ml_training_run.py), [scheduler/concept_drift.py](../scheduler/concept_drift.py), [services/ml/promotion.py](../services/ml/promotion.py), [.github/workflows/train-model.yml](../.github/workflows/train-model.yml), [docs/runbooks/model-rollback.md](runbooks/model-rollback.md)
- **Riesgo:** bajo para las verificaciones; medio para el nombre por
  contenido, que toca el camino por el que la ingesta y la API cargan el
  modelo.

### [P1] Ejecutar en producción la purga de PSCP sin tecnología
- **Área:** scripts/purgar_pscp_sin_tecnologia.py, db/repositories/purga_licitaciones.py (acción del usuario: borrado irreversible)
- **Problema:** de ~685.500 filas de PSCP solo 3.268 llevan `tecnologia` (medido el
  2026-09-26). Las otras son el censo catalán entero —limpieza, obras, reactivos—
  y 100.421 tienen `analysis_universe` NULL, que cuenta como `technology_observed`:
  salen en el Radar, en las cifras de cuentas y en los avisos (hay notificaciones
  enviadas sobre «Missatges WhatsApp Business»). Son además el 97 % del heap de
  `licitaciones`, que es lo que hace lentas las vistas de Mercado sin filtros.
  El código de la purga y la puerta endurecida del conector están hechos
  (RFC [2026-09-26](rfc/2026-09-26-rfc-purga-pscp-sin-tecnologia.md)); falta
  ejecutarla, y eso lo decide el propietario.
- **Acceptance criteria:**
  - ~~Dry-run revisado y pregunta abierta decidida~~ (2026-09-26): primer dry-run en
    producción hecho; lo que es TI solo por CPV 48/72 **se conserva** (RFC). Falta
    repetir el dry-run con la regla ampliada.
  - `--apply` ejecutado y PSCP reingerida entera (`--desde 2000-01-01`) para
    refrescar las etiquetas desactualizadas; balance y delta de
    `make audit-truth-check` anotados en el RFC, que pasa a `implemented`.
    - **Estado al 2026-10-09** (issue #408; logs de Actions): la reingesta del
      run 36287345654 (2026-09-27, con `apply`) murió a los 55 min y 812.591
      avisos por un «Read timed out» de Socrata en una página, que no tenía
      reintento. Lo escrito no se perdió: el cursor avanza con cada lote y quedó
      en `2026-07-13T13:26:08.273Z` (la marca de la republicación completa del
      dataset). La pasada diaria de `scrape-daily.yml`, que no lleva `--desde`,
      siguió desde ahí —cayendo tres veces más por el mismo timeout— y alcanzó
      la cabeza del dataset el 2026-09-28 17:09 UTC: el recorrido completo está
      hecho, aunque el último run de `purga-pscp.yml` siga en rojo.
    - Medido en producción el 2026-10-09 (solo lectura): 60.107 filas de PSCP.
      59.910 llevan `fecha_actualizacion_fuente`, es decir, las ha escrito el
      conector actual. Las otras 197 no la llevan, ni `analysis_universe` ni
      `inclusion_reason`: su última extracción es de entre el 2026-06-12 y el
      2026-07-29 (182 con CPV 48/72, 33 con `tecnologia`). Una muestra de 6 ya
      no está en el dataset (2.007.085 filas hoy, ninguna con marca anterior a
      la republicación), así que relanzar la reingesta no las tocaría. Con el
      universo a NULL cuentan como `technology_observed`; qué hacer con ellas
      está sin decidir.
    - Arreglado el 2026-10-09: la petición de página reintenta con el
      `http_retry` compartido (`_pedir_pagina` en el conector).
    - Sin tocar, por si se relanza: `--desde` no reanuda. Ignora el cursor,
      vuelve a recorrer los ~2 M de filas (más de 2 h) y mientras dura rebobina el
      cursor de la pasada diaria al punto por el que va; y el step de reingesta
      solo corre con `apply`, así que relanzarlo repite antes la purga.
    - Falta lo demás: balance, delta de `make audit-truth-check` y el RFC.
  - Tras el `VACUUM (ANALYZE)`, `pg_relation_size('licitaciones')` anotado aquí.
    - **Medido el 2026-10-25 (MCP, solo lectura):** `pg_relation_size('licitaciones')` = **89 MB** (era ~870 MB); 88.925 filas en total, de las que 60.737 son `pscp` y **16.798 llevan `tecnologia`** (el ítem citaba 3.268 sobre 685.500: la cifra es anterior a la purga y a la reingesta). Siguen 195 filas `pscp` sin `fecha_actualizacion_fuente` (la decisión sobre ellas sigue abierta). La purga y la reingesta están hechas; lo único que falta para cerrar es el balance en el RFC y el delta de `make audit-truth-check`, que exige la BD real.
- **Files de partida:** [.github/workflows/purga-pscp.yml](../.github/workflows/purga-pscp.yml) (dry-run por defecto; `apply` + `reingerir_desde`), [scripts/purgar_pscp_sin_tecnologia.py](../scripts/purgar_pscp_sin_tecnologia.py), [db/repositories/purga_licitaciones.py](../db/repositories/purga_licitaciones.py), [scraper/connectors/pscp.py](../scraper/connectors/pscp.py) (`senal_tecnologica`)
- **Riesgo:** alto — borra ~680.000 filas y sus dependientes. Mitigado: reevalúa con la
  misma puerta que el conector, conserva las filas con trabajo de usuario, es
  reanudable, y el dato es público y reingestable (`--desde`).

### [P2] Medir en producción los documentos de TED y PSCP tras el despliegue
- **Área:** scraper/documentos_plataforma.py, scraper/connectors/{ted,pscp,placsp}.py, config/settings.py
- **Problema:** hasta el 2026-10-02 ninguna fila TED ni PSCP tenía documentos
  (de ~248 convocatorias TED abiertas, solo las 87 emparejadas con PLACSP veían
  pliegos, los de su canónica). Desde entonces: el PDF del anuncio TED para las
  convocatorias sin pareja, los pliegos de PLACSP rescatados de las entries que
  el ATOM descarta, la ficha JSON de la PSCP y el emparejamiento TED↔PSCP por el
  anuncio que la ficha cita. Nada de eso está medido en producción, y una cosa
  puede dejarlo mudo sin error: que Render fije `DOCUMENT_ALLOWED_HOSTS` con el
  valor viejo (solo PLACSP; la descarga bajo demanda de la API rechazaría TED y
  la PSCP con «Host no incluido»). `.env.example` ya lleva el valor nuevo.
- **Acceptance criteria:**
  - Logs `ted_documentos_completados`, `pscp_documentos_completados` y
    `placsp_rescate_ted` en un run de `scrape-daily.yml`, con sus recuentos aquí.
  - `SELECT l.fuente, count(DISTINCT d.licitacion_id) FROM documentos d JOIN licitaciones l ON l.id_externo = d.licitacion_id WHERE l.fuente IN ('ted','pscp') GROUP BY 1`
    y cuántos llegan a `extracted` tras el lote nocturno de `pliegos.yml`.
  - Marcas `clave_match LIKE 'publicacion_oficial:%'` contadas.
  - `DOCUMENT_ALLOWED_HOSTS` en Render comprobado (sin definir, o con
    `ted.europa.eu` y `contractaciopublica.cat`).
  - PSCP guarda sin etiqueta de tecnología lo que entra solo por CPV 48/72
    (`cpv_ti_universe`: 48 de 122 convocatorias vigentes ese día) y por eso no se
    publica, mientras su anuncio TED sí. Decidir con el diagnóstico de la
    clasificación si esa asimetría se mantiene.
- **Progreso (2026-10-03, #395 en producción desde las 08:39 UTC):**
  - **TED, medido.** El backfill de ese día dejó 193 convocatorias con su
    anuncio (`ted_documentos_completados candidatas=193 con_documentos=193`), y
    la pasada programada de las 13:29 ya no encontró ninguna (`candidatas=0`).
    De las 239 convocatorias TED abiertas: 119 emparejadas (116 con pliegos en
    la canónica, 91 extraídos) y 120 con su anuncio; ninguna sin documentos. Los
    193 anuncios seguían `pending` a las 14:00 UTC, con el lote de `pliegos.yml`
    en curso: falta anotar cuántos llegan a `extracted`.
  - **Rescate del ATOM, sin ocasión todavía.** `ted_reemparejo_id_evl
    evaluadas=147 confirmados=0`: son los avisos que esperan una entry
    descartada. El ATOM no trajo entradas nuevas en esa pasada (sábado), así que
    no hay `placsp_rescate_ted` que contar.
  - **PSCP, sin ejecutar**: ver el ítem P1 de arriba. 0 filas con documentos y
    0 marcas `publicacion_oficial:%`.
  - **Render, sin comprobar.** El MCP de Render no lista variables de entorno
    (solo las escribe): hay que mirarlo en el panel. Fuera de Render no la pisa
    nadie: ni `render.yaml`, ni los workflows, ni las variables del repositorio.
- **Progreso (2026-10-24, MCP de solo lectura):** PSCP, 217 licitaciones con
  documentos (1.589 documentos, 1.416 `extracted`); TED, 409 (960 documentos,
  283 `extracted`); 32 marcas `publicacion_oficial:%`, todas `confirmed`. El P1
  de los pliegos de la PSCP está en _Cerrados_. Siguen abiertos el recuento de
  `placsp_rescate_ted`, `DOCUMENT_ALLOWED_HOSTS` en Render y la asimetría de CPV.
- **Files de partida:** [scraper/documentos_plataforma.py](../scraper/documentos_plataforma.py), [db/repositories/documentos.py](../db/repositories/documentos.py), [config/settings.py](../config/settings.py)
- **Riesgo:** bajo — solo observación y una variable de entorno.

### [P1] Ampliar el golden set del clasificador SAP a 300-500 ejemplos etiquetados a mano
- **Área:** tests/fixtures/golden_set.jsonl, tests/fixtures/golden_set_tech.jsonl, scripts/sample_golden_candidates.py (acción del usuario: etiquetar)
- **Problema:** el golden set es el único sitio del repo con etiquetas humanas independientes del filtro de keywords, y de él salen dos cosas que gobiernan producción: el umbral servido y `recall_no_keyword`, la métrica que decide si el ML aporta algo sobre `matches_sap()` (desde el 2026-08-24 es criterio **bloqueante** del gate de promoción, `services/ml/promotion.py`). Con 27 ejemplos no sostiene ninguna de las dos: solo 6 son positivos humanos sin keyword, así que `recall_no_keyword` se mueve a saltos de 16,7 puntos y solo puede tomar 7 valores; un bootstrap sobre esos 27 da un umbral con sigma=0,084 y rango p5-p95 de [0,30, 0,56] sobre un rango útil de 0,65, y el F-beta reportado sobre el mismo conjunto donde se elegía el umbral sobreestimaba el real en +0,08 de media (+0,25 en el p90). El reparto tune/holdout ya está implementado; partir 27 en dos no arregla el tamaño. El golden multi-etiqueta (`golden_set_tech.jsonl`) tiene 23 ejemplos semilla y el mismo problema.
- **Por qué no se cerró en el mismo cambio:** etiquetar requiere criterio humano sobre licitaciones reales. Fabricar cientos de ejemplos sintéticos mediría el texto que escribió quien los fabricó, no la realidad — un golden set inventado es peor que uno pequeño, porque el pequeño al menos se sabe pequeño.
- **Acceptance criteria:**
  - >= 60 ejemplos por mitad (`services.ml_eval.MIN_TUNE_EXAMPLES` / `MIN_HOLDOUT_EXAMPLES`); objetivo 300-500 en total.
  - >= 30 positivos humanos **sin keyword** en el holdout, para que `recall_no_keyword` tenga resolución útil.
  - `load_golden_set()` deja de emitir `golden_tune_split_too_small` / `golden_holdout_too_small`.
- **Cómo empezar:** `python -m scripts.sample_golden_candidates --n 400 --out /tmp/candidatos.jsonl` — muestrea estratificando por la zona de desacuerdo entre keywords y modelo, que es donde una etiqueta humana aporta información. Escribe `label: null` para rellenar a mano.
- **Files de partida:** [scripts/sample_golden_candidates.py](../scripts/sample_golden_candidates.py), [tests/fixtures/golden_set.jsonl](../tests/fixtures/golden_set.jsonl), [services/ml_eval.py](../services/ml_eval.py)
- **Riesgo:** bajo en código, alto en oportunidad — mientras el set sea pequeño, el gate de promoción bloquea con poca evidencia y el umbral servido tiene una varianza que ninguna mejora del modelo puede compensar.
- *Estado (2026-09-27):* el plan [2026-09-27-clasificacion-tres-niveles](plans/2026-09-27-clasificacion-tres-niveles.md) propone sustituir este golden por `golden_ti.jsonl` (fase F2): la etiqueta pasa de «es SAP» a «es TI», que es lo que el binario aprende de verdad, y los ~500 ejemplos se revisan partiendo de la propuesta del LLM en vez de etiquetarse desde cero. Ese día el reentrenamiento del binario (primero que completa desde julio) quedó rechazado con `recall_no_keyword` 0/3 sobre los 17 ejemplos del holdout.
- *Estado (2026-10-24):* la muestra y el import existen desde el 2026-10-23 (`scripts/muestra_etiquetado_ti.py`, [runbook](runbooks/etiquetado-ti.md)), y ya hay consumidor: `scripts/entrenar_nivel1.py` (F3 del plan de tres niveles) usa `golden_ti.jsonl`, con `tune` para fijar umbrales y `holdout` para el gate; para decidir exige ≥ 60 ejemplos en el holdout y ≥ 10 de cada clase en «CPV 48/72 sin keyword». Medido en producción ese día: 2 revisiones humanas `revision_ti` frente a 3.451 licitaciones con marcador del LLM (`__es_ti__`/`__no_es_ti__`), con las dos clases en todas las fuentes (en CPV 48/72 sin keyword: 1.585 sí / 452 no). Solo falta etiquetar (D4) y exportar; sin golden no se puede medir si las etiquetas del LLM son aptas.
- *Progreso (2026-10-25, herramientas):* `scripts/sample_golden_candidates.py --desde` muestrea desde un export CSV/JSONL (usa su `ml_proba` si viene en todas las filas) y escribe el órgano; `scripts/revisar_golden_candidates.py`, que ya etiquetaba, guarda `source`/`fecha` en cada etiqueta, saca los dudosos de la cola (`--dudosos` los recupera), deja de enseñar `keyword_match` y `ml_proba` antes de decidir, y con `--estado` da además el intervalo bootstrap del umbral (`services.ml_eval.umbral_bootstrap`, misma rejilla que el tuning servido, ahora extraída a `elegir_umbral`). Estado medido hoy: 27 etiquetados, tune 10 / holdout 17, 3 positivos sin keyword en holdout: **no cumple**. No se generaron candidatos: ni Postgres local ni distro WSL en la máquina del agente. Detalle en [model-rollback.md](runbooks/model-rollback.md#ampliar-el-golden-del-clasificador-sap).
- **Paso humano pendiente (dueño), en 3 líneas:**
  1. `ENV=prod PYTHONPATH="$PWD" python -m scripts.sample_golden_candidates --n 400 --out data/etiquetado/candidatos_golden_sap.jsonl` (o `--desde export.csv`, con el `\copy` del runbook).
  2. `python -m scripts.revisar_golden_candidates data/etiquetado/candidatos_golden_sap.jsonl` — `1`/`0`/`d`/`s`/`q`; se puede parar y retomar.
  3. `python -m scripts.revisar_golden_candidates data/etiquetado/candidatos_golden_sap.jsonl --anexar`, y commitear `tests/fixtures/golden_set.jsonl` cuando `--estado` diga que cumple.

### [P2] Verificar que el fix de PSCP progresa en producción tras el próximo deploy
- **Área:** scraper/connectors/pscp.py, observability
- **Problema:** El fix del cursor PSCP (ver Cerrados) es correcto y verificado con tests, pero corre contra un cursor YA atascado en producción desde hace semanas (`last_seen_updated='2026-06-19'`, sin `last_entry_id`). El primer run post-deploy re-consultará desde ese mismo punto (comportamiento esperado y correcto), pero hay que confirmar en los logs de Actions que el cursor **avanza** en el run siguiente (antes se quedaba pegado indefinidamente). Además, dado el volumen de filas que comparten el `:updated_at` de la republicación masiva (~1.86M filas), el conector tardará muchos ciclos en ponerse al día — el throughput por-registro (~240ms, probablemente dominado por round-trips US↔EU a Supabase) es una preocupación separada, no resuelta por este fix. **Actualización 2026-07-27:** el throughput sí está resuelto — la ruta de escritura pasó de un round trip por fila a `executemany` (ver _Cerrados_: 2201 → 6 viajes por lote de 800 filas). Queda solo la verificación en logs de que el cursor avanza.
- **Acceptance criteria:**
  - `gh run view <run> --log | grep pscp_fetch_start` muestra un `since` que avanza run a run (no repite el mismo timestamp).
  - ~~Si el throughput sigue siendo insuficiente, batchear los upserts para reducir round-trips por registro.~~ **Hecho 2026-07-27.** Si aun así no se pone al día, el siguiente eje es la co-locación del plano de ingesta con la BD (runners US vs Supabase EU), que contradice ADR-012 y requiere ADR nueva.
- **Files de partida:** [scraper/connectors/pscp.py](../scraper/connectors/pscp.py), [.github/workflows/scrape-daily.yml](../.github/workflows/scrape-daily.yml)
- **Riesgo:** bajo — solo observación; la acción de subir el timeout del step si hiciera falta requeriría gate humano.

### [P1] Verificar checklist F3d post-cutover (hardening Supabase) — solo acciones manuales pendientes
- **Área:** docs/runbooks, GitHub Settings, Supabase Dashboard
- **Problema:** El cutover F3c a Supabase Postgres ya se ejecutó. Todo el trabajo de **código y tooling** del hardening post-cutover está cerrado (ver progreso abajo); lo que queda es estrictamente **ejecución manual contra infraestructura real** con credenciales que un agente no tiene (gate secrets+ops, AGENTS.md §6).
- **Acceptance criteria (todas acciones del usuario — checklist ejecutable en el runbook):**
  - Password del rol dueño rotada; `DATABASE_URL` reconstruida con `sslmode=verify-full`.
  - `DATABASE_ADMIN_URL` (rol dueño, solo para alembic) guardada como secret aparte.
  - `scripts/setup_pg_roles.sql` ejecutado contra Supabase; `DATABASE_URL` de runtime apuntando al rol `tenderflow_app`; verificado que puede DML pero no DDL.
  - Confirmado (`psql`) que `v52_rls_lockdown` está aplicada y `has_table_privilege('anon',…)` es false.
  - ~~Turso retirado una vez pasada la ventana de rollback ≥14 días.~~ **Hecho 2026-07-26 (ADR-020)** — pendiente solo la acción manual de revocar el token en el dashboard de Turso y borrar los GH Secrets `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN` (código y workflows ya no los usan).
- **Files de partida:** [docs/runbooks/migracion-persistencia.md](archive/runbooks/migracion-persistencia.md) (Paso 9, checklist ejecutable), [scripts/setup_pg_roles.sql](../scripts/setup_pg_roles.sql)
- **Progreso 2026-07-13 (plan Pliegos+RAG, fases D1/D2 — CERRADAS del lado de código):**
  - ~~`docs/runbooks/backup-restore.md`: sección "Backups Postgres cifrados"~~ (retirado el 2026-09-28 con los backups propios).
  - `scripts/setup_pg_roles.sql`: rol `tenderflow_app` (solo DML + timeouts) + políticas RLS explícitas por tabla (`tenderflow_app_full_access`) que resuelven la dependencia con `v52_rls_lockdown` (rol no-dueño + RLS sin políticas = deny-all).
  - `config/settings.py::_validate_prod_database_ssl`: ahora exige `sslmode` seguro para **cualquier host remoto, independientemente de `ENV`** (antes solo en prod/staging) — cierra el gap real donde `scrape-daily.yml` corre con `ENV=dev` contra Supabase sin que el validator actuara. Host local (`localhost`/`127.0.0.1`/`::1`) sigue exento (sin red externa que interceptar). 4 tests nuevos en `test_config_settings.py` cubren la matriz ENV×host×sslmode.
  - `docs/archive/runbooks/migracion-persistencia.md` Paso 9 reescrito como checklist `- [ ]` ejecutable con comandos psql concretos.
  - 2026-07-26: `setup_pg_roles.sql` endurece el rol de runtime con `NOINHERIT`/`NOBYPASSRLS` y sin `CREATE` en `public`; Alembic v59 revoca `EXECUTE` público sobre la función `SECURITY DEFINER` de RLS. Sigue pendiente ejecutar el checklist contra Supabase.
- **Riesgo:** bajo — todo el código/tooling es aditivo y ya está testeado; el riesgo real pendiente es que el usuario no ejecute el checklist (credencial sin rotar, rol de privilegios mínimos sin crear).

### [P1] [Ola 1 · S1] Identidad y equipo: invitar sin cuenta previa, OIDC y el ratchet de `user_key`
- **Área:** api/routes/auth.py, services/organizations.py, db/repositories/organizations.py, db/users.py, shared/identity.py, scripts/check_user_key_ratchet.py
- **Progreso fase 3, tercera tanda (2026-10-26, `v165_user_id_fase3_tanda3`):** `notification_reads`, `user_event_prefs` y `saved_filters` por `user_id`; `follows` y `pending_digests` van con `watchlist_*`. Ratchet 53 → 53. Aplicar v165 **antes** del despliegue. El borrado RGPD se lleva ya `notification_reads`. Ver [plan 2026-10](plans/2026-10-plan-foco-piloto.md) §8.
- **Problema:** una organización no puede incorporar a nadie que no tenga ya cuenta —`add_member_by_email` rechaza el email aunque `organization_memberships.status` admita `invited` desde `v61`—, el único OAuth es Google (un partner con Microsoft 365 no entra con su identidad), y la identidad interna sigue derivándose del email: `user_key` aparece en 60 ficheros (grep 2026-09-05), así que un cambio de email es un cambio de clave primaria de facto.
- **Decisiones ya tomadas (2026-09-06):** D17 → Entra ID multi-tenant reutilizando `OAUTH_ALLOWED_DOMAINS` y `access_grants` (revisada el 2026-10-23 por [ADR-037](adr/ADR-037-correo-acreditado-y-vinculacion-por-proveedor.md): solo con `xms_edov`); D18 → ratchet ahora y migración aditiva por olas después (esa segunda fase es T4 del plan, no este ítem).
- **Progreso T4 (2026-09-14, v129 · ADR-030 fase 2):** `user_id` junto a `user_key` en las doce tablas de usuario (nueve nuevas + FK e índice en las tres que ya la tenían), backfill por email en SQL y lectura dual + escritura doble en `db/`, `services/notifications.py`, `services/watchlist_rules.py` y los productores de alertas; GDPR exporta y borra por id o por clave (y cubre por fin `saved_filters`). Test de aceptación del ADR: `tests/test_user_id_cambio_email_integration.py`. **Queda la fase 3** (dejar de escribir `user_key`, recrear las PK de `user_profiles`/`radar_dismissals`, retirar `user_key` del payload de `watchlist_rule.matched` con RFC, y llevar el ratchet a cero).
- **Progreso fase 3 (2026-09-18, v135, rama `worktree-agent-a8484f81d7c8a27e2`):** PK de `user_profiles` → `(user_id)` y de `radar_dismissals` → `(user_id, id_externo)`, con backfill y fallo ruidoso si queda alguna fila sin id o duplicada; `user_profiles` ya no escribe `user_key`; `log_event(actor=…)` saca seis ficheros del ratchet (69 → 63); RFC `draft` [2026-09-18](rfc/2026-09-18-rfc-retirar-user-key-payload-watchlist-rule-matched.md) para el payload del webhook, con el campo intacto hasta la ventana y la sustitución pendiente de decisión humana. **Queda:** `user_notifications`/`follows`/`watchlist_*` siguen tecleadas por `user_key` (y con ellas `radar_dismissals` la sigue escribiendo); aplicar v135 en producción (antes del deploy del código) y regenerar `docs/database-schema.md`. *Estado (2026-09-19):* `docs/database-schema.md` ya está regenerado con v135 y v140 (`98f34bee`; su cabecera dice `v138_notice_type_code`).
- *Nota (2026-10-17):* este ítem se lleva también la mayoría de las 64 `# noqa: S608` del repo (34 en producción; 18 entre `services/notifications.py` y `services/watchlist_rules.py`). No son inyección: interpolan `_IDENT`, el predicado constante de identidad dual `user_id`/`user_key`, y duplican cada consulta en una rama con y otra sin `organization_id`. Quitarlas antes obligaría a copiar el predicado en cada sentencia; cuando la lectura sea solo por `user_id` el fragmento desaparece y con él la supresión. Sacarlas en el mismo PR que retire la columna. *Actualización (2026-10-23):* las 18 de esos dos servicios ya no existen: su SQL bajó a `db/`, donde `S608` está desactivado por fichero y `_IDENT` lleva escrito por qué no es inyección. El predicado dual sigue y se va con la columna.
- **Progreso fase 3, segunda tanda (2026-10-25, v162, rama `agente/user-id-columna-doble`):** `user_notifications` pasa a teclearse por `(user_id, licitacion_id, type)` —índice único parcial `uq_user_notifications_user_id`; el `UNIQUE` por `user_key` de v48 se conserva como árbitro de las filas sin id y del código anterior durante el despliegue— y `db.notifications.insert_user_notification` deja de escribir `user_key` cuando conoce el id (producción medida ese día: 0 filas sin `user_id` en las once tablas). Con eso ningún productor de alertas deriva ya la clave del correo (`services/pursuit_awards.py`, `services/pursuits.py`, `services/deadline_reminders.py`; `scheduler/watchlist_rules_alerts.py` deja de tener su propio `INSERT`) y `shared.identity.actor_del_principal` sustituye las tres copias del actor de auditoría (`webhooks`, `feedback`, `me`, esta última recortaba el correo). Ratchet **59 → 53** (salen `pursuit_awards`, `webhooks`, `feedback`, `db/repositories/pursuits`, `scheduler/jobs/watchlist_rules`, `services/analytics/quality`). Tests: `tests/test_v161_user_notifications_user_id_fase3.py`. **Queda:** aplicar v161 en producción *antes* del deploy del código y regenerar `docs/database-schema.md` (`make schema-doc`); `user_id NOT NULL` en `user_notifications` cuando `watchlist_items` deje de admitir favoritos sin id (hoy `check_deadlines_and_notify(user_key)` y una veintena de tests escriben sólo con clave); `notification_reads` y `user_event_prefs` con el mismo patrón (índice parcial por id, clave opcional); después `watchlist_*`, `saved_filters`, `follows` y `pending_digests`, que son las que retienen a los 53 restantes (ver `python scripts/check_user_key_ratchet.py --list`).
- **Acceptance criteria:** los de S1.1–S1.4 del plan v2, sin redefinirlos aquí. Los cuatro subítems son independientes y se pueden entregar por separado; S1.3 (dominio propio) es acción humana.
- **Files de partida:** [docs/plans/2026-09-plan-arquitectura-v2.md](plans/2026-09-plan-arquitectura-v2.md) (§5, S1), [services/organizations.py](../services/organizations.py), [api/routes/auth.py](../api/routes/auth.py)
- **Estado (2026-10-17):** el **Problema** ya no describe el código en su primera frase: invitar a quien no tiene cuenta existe (`services/organizations.py::invite_member_by_email`, tabla `organization_invitations`, aceptación por token y al iniciar sesión con `accept_invitations_for_email`). `add_member_by_email` sigue rechazando un correo sin cuenta porque es el alta directa, no la invitación. Lo abierto es lo de la fase 3 de `user_key` descrito arriba.
- **Riesgo:** medio — S1.2 toca el login, que es el camino por el que entra todo el mundo; el resto es aditivo.

### [P1] [Ola 1 · S2] La organización no sabe quién es: NIF, capacidad y go/no-go asistido
- **Área:** services/go_no_go.py, db/repositories/organization_capabilities.py, services/pursuit_awards.py, services/analytics/affinity.py, web/src/app/(dashboard)/equipo
- **Problema:** `OrganizationSettings` solo guarda `tecnologias`. Sin NIF, `PursuitAdjudicacionDetectada` tiene que pedir confirmación humana para cerrar una oportunidad —lo dice su propio docstring: «el sistema no conoce el NIF de la organización»— y «contra quién» no puede excluir a la propia organización de la lista de competidores. Sin perfil de capacidad, la ficha del pliego (certificaciones, solvencias, equipo) no tiene contra qué contrastarse: el producto extrae el requisito y deja al usuario comprobándolo a mano.
- **Decisión ya tomada (2026-09-06):** D11 → tablas propias (`organization_nifs`, `organization_capabilities`), no un JSON en `settings_json`, porque el cierre por NIF y el contraste de solvencia se resuelven en SQL.
- **Acceptance criteria:** los de S2.1–S2.4 del plan v2. El veredicto del checklist nunca decide por el usuario: `cumple | no_cumple | desconocido`, ningún `cumple` sin `EvidenceRef`, y `desconocido` cuando falta el dato — es la misma regla de ADR-014 aplicada a una decisión en vez de a una cifra.
- **Estado:** lo dice el §5 del plan, no este ítem — ver la nota de cabecera. Dos precisiones sobre el **Problema** de arriba, que ya no describe el código: el docstring que citaba («el sistema no conoce el NIF de la organización») se corrigió el 2026-09-08 porque el código lo desmentía, y la exclusión de la propia organización de «contra quién» ya está viva. Lo que S2 tuvo que arreglar en esa tanda no fue escribir el motor —estaba escrito desde #274— sino enchufarlo: cuatro piezas probadas y sin ningún llamador de producción.
- **Files de partida:** [docs/plans/2026-09-plan-arquitectura-v2.md](plans/2026-09-plan-arquitectura-v2.md) (§5, S2), [shared/dto/](../shared/dto/__init__.py)
- **Riesgo:** medio — dos migraciones y una regla de producto nueva; el golden `golden_go_no_go.jsonl` es la red.

### [P1] [Ola 1 · S5] Cola de trabajo y worker: un despliegue mata lo que un usuario pidió
- **Área:** services/jobs.py, db/repositories/jobs.py, scheduler/worker.py, api/routes/jobs.py, scheduler/pipeline_runs.py, render.yaml
- **Problema:** la extracción asíncrona de la ficha corre en `BackgroundTasks` de la API con 30 s de drenado al apagar (`api/app.py`), y `autoDeploy` está activo en el servicio real: un push a `master` en mitad de una extracción la pierde, y el usuario ve un estado que nunca avanza. El cierre post-ingesta son quince pasos secuenciales dentro de un job de Actions cada cuatro horas, donde un paso caído arrastra a los que no dependen de él.
- **Decisión ya tomada (2026-09-06):** D14 → worker en Render para lo que pide un usuario y Actions para lo programado, sobre la misma tabla de cola. El servicio nuevo exige O0.2 cerrado primero (un solo camino de despliegue).
- **Acceptance criteria:** los de S5.1–S5.4 del plan v2, incluidos los dos que son medibles sin producción: dos consumidores concurrentes procesan cien jobs exactamente una vez, y `grep -rc "BackgroundTasks" api/routes/licitaciones/` = 0 (el fichero es un paquete desde 2026-09).
- **Files de partida:** [docs/plans/2026-09-plan-arquitectura-v2.md](plans/2026-09-plan-arquitectura-v2.md) (§5, S5), [scheduler/pipeline_runs.py](../scheduler/pipeline_runs.py), [api/app.py](../api/app.py)
- **Estado (2026-10-01):** el código de la cola está, pero **`tenderflow-worker` no existe en Render** (su API lista un único servicio, la API). Nadie consumía los jobs `ficha_pliego`: siete `pending` desde el 14-sep y la pestaña Pliego en «Extrayendo…» para siempre (oportunidad 14). Mientras tanto los consume la API ([ADR-028 §G](adr/ADR-028-cola-de-trabajo-y-worker.md)), que además ganó `pybreaker`/`tenacity` en su imagen y encola la ficha al abrir una oportunidad en vez de usar `BackgroundTasks`. Lo que queda de este ítem: crear el servicio (checklist de `render.yaml`) y poner `JOBS_CONSUMIDOR_EN_API=0` en la API.
- **Actualización (2026-10-10):** la creación del servicio está escrita paso a paso, con todas sus variables, en el paso 1 del [runbook del cutover del cron](runbooks/cutover-cron-al-worker.md), y su plan declarado pasa a `standard`: con el plano de cron de ADR-033 corre la ingesta y el scoring en el mismo proceso que la cola. `deploy.yml` despliega también el worker, del mismo commit y tras verificar la API, si su deploy hook está en `RENDER_WORKER_DEPLOY_HOOK_URL` (en los de Actions); sin él no despliega ninguno de los dos.
- **Actualización (2026-10-19):** el servicio se creó el 2026-10-10, pero en el plan `free` de Render, que lo hibernaba a los ~15 min: su consumidor y su plano de cron solo corrían tras cada deploy. Como `JOBS_CONSUMIDOR_EN_API` nunca se puso a `0`, la cola la siguió vaciando la API, y la ingesta y el scoring siguieron en Actions. Se retiró en vez de pagar `standard`: `render.yaml` ya no lo declara, `deploy.yml` no lo despliega y `scripts/check_job_parity.py` acepta a la API como consumidor ([ADR-028 §G](adr/ADR-028-cola-de-trabajo-y-worker.md), revisión del 2026-10-19). Lo que quedaba de este ítem —crear el servicio y apagar el consumidor de la API— deja de aplicar; el de §A (que la extracción no comparta proceso con la API) sigue abierto y es lo que justificaría recrearlo.
- *Nota (2026-10-24):* el servicio sigue existiendo en Render: `TenderFlow-1` (`srv-db58n80473hc73a94rsg`), plan `free`, sin suspender y sin ningún log desde el 2026-10-19. No consume nada, pero si alguien lo despierta corre contra la misma base. Suspenderlo o borrarlo es acción del dueño.
- *Nota (2026-10-25):* confirmado por la API de Render: `TenderFlow-1` (`srv-db58n80473hc73a94rsg`) está `suspended` por el usuario desde el 2026-10-24, plan `free`. Quedan dos servicios activos: `TenderFlow` (la API, `standard`) y `tenderflow-mcp` (`starter`). Retomar el worker exige un plan de pago y devolver a `deploy.yml` su paso: decisión del dueño, no de un agente.
- **Riesgo:** medio — servicio nuevo en producción y cambio del camino por el que se sirve la ficha.

---

### [P1] Recuperación de contraseña: comprobar la entrega en producción y decidir lo que la auditoría dejó fuera
- **Área:** services/password_reset.py, api/routes/auth.py, api/middleware.py, observability/, config/settings.py, variables de Render (acción del usuario)
- **Progreso (2026-10-26):** el (2) está hecho en código con la opción B del RFC (ya `approved`): `API_ORIGIN_SECRET` en Vercel y Render, [runbook](runbooks/ip-del-cliente.md). Falta poner el secreto y verificar con dos redes. El (1) sigue siendo acción del propietario. Ver [plan 2026-10](plans/2026-10-plan-foco-piloto.md) §8.
- **Problema:** la auditoría del issue #243 (2026-10-09) cerró los huecos del flujo en el código —ver [el RFC](rfc/243-recuperacion-contrasena-local.md)—, pero dejó ocho cosas que no se arreglan con un commit: dos hay que mirarlas en producción y el resto son decisiones del dueño. Cada una lleva su prioridad. **2026-10-23:** el dueño aprobó 3, 4, 5, 6 y 8 y están hechos (ver _Cerrados_ en el [archivo](archive/IMPROVEMENT_BACKLOG_CERRADOS.md)); el 7 se hizo el 2026-10-24 (ídem); quedan 1 y 2.
  1. **[P1] La entrega del correo en producción no está comprobada.** `render.yaml` no declara `EMAIL_*` ni `ALERT_SMTP_*` para `tenderflow-api` (solo para `tenderflow-alertmanager`), y ese fichero tampoco gobierna el servicio real (ítem P2 de más abajo), así que desde el repo no se sabe si la API tiene con qué enviar. Sin credenciales el transporte devuelve «no configurado» sin lanzar: quien pide el enlace lee «te llegará un enlace» y no llega nada. Desde este cambio queda `password_reset_email sent=false` a nivel `warning`; antes, solo un `info`. Lo mismo si falta la URL del frontend (`CORS_ALLOWED_ORIGINS` vacío y sin `OAUTH_REDIRECT_URI`): `password_reset_frontend_url_unavailable`.
     **Progreso 2026-10-21:** comprobado en el log de Render que **no sale ningún correo**: la aprobación de la solicitud 3 dejó `solicitud_acceso_aviso_persona enviado=false` sin `mailer_failed` alrededor, firma de `not_configured`. `render.yaml` declara ya las variables de correo en la API, el arranque avisa con `email_backend_not_configured` y `mailer_not_configured` pasó a `warning` ([RFC del alta](rfc/2026-10-21-rfc-alta-con-contrasena-tras-concesion.md) §7). Falta lo que solo hace el dueño: poner las credenciales en el panel de Render y el reset real de extremo a extremo del criterio (1). El alta con contraseña depende de lo mismo, y comparte con este ítem el riesgo del punto 2: sus cuotas por IP (`register`, `verify-email`) se repartirían entre todos los usuarios si la IP que ve la API es la de Vercel.
  2. **[P1] Hipótesis sin verificar: el límite por IP puede no distinguir clientes en producción.** El navegador llama a `/api/*` en Vercel y Vercel lo reenvía a Render (`rewrites()` de `web/next.config.ts`), así que quien abre la conexión con Render es Vercel. `_trusted_client_ip` recorre `X-Forwarded-For` desde el final y devuelve el primer salto que no esté en `FORWARDED_ALLOW_IPS` —el rango del proxy de Render—: ese salto sería la IP de salida de Vercel, no la del usuario. Si es así, las cuotas por IP de la recuperación (5 cada 15 minutos), el bloqueo de login (`_login_client_key`) y el tope global del middleware se reparten entre todos los usuarios, y cualquiera puede agotárselos a los demás. `web/src/lib/server-prefetch.ts` ya lo reconoce para las peticiones del SSR; nadie lo ha mirado para las del navegador. Depende de qué cabeceras pone Vercel y de qué hay en `FORWARDED_ALLOW_IPS` en el panel de Render, que desde aquí no se lee.
     **Medido 2026-10-24 (log de Render, servicio `TenderFlow`):** es peor que la hipótesis. El `client_ip` de las líneas `http_request` es siempre una IP interna `10.19x.x.x` (seis distintas en dos minutos, también en el `INFO: 10.192.214.29:42670` de uvicorn), y cambia **dentro de la misma sesión**: la carga de una pantalla reparte sus peticiones entre `10.192.214.29`, `10.197.182.120`, `10.194.137.88`… No es la IP de salida de Vercel ni la del usuario, sino el salto interno del proxy de Render: las cuotas por IP son por nodo del proxy, compartidas por todos los usuarios y troceadas para cada uno. Hace falta decidir de dónde sale la IP del cliente (qué hay en `FORWARDED_ALLOW_IPS` y en `X-Forwarded-For`, o una cabecera de Vercel verificable).
     **Diagnóstico y opciones (2026-10-24):** RFC [2026-10-24-rfc-ip-del-cliente-tras-vercel-y-render](rfc/2026-10-24-rfc-ip-del-cliente-tras-vercel-y-render.md) (`draft`). El peer que ve uvicorn es el nodo interno de Render y no se reescribe (puertos efímeros reales en el log), así que `FORWARDED_ALLOW_IPS` no cubre `10.x`; pero ampliarla tampoco basta: el salto siguiente es el borde de Cloudflare y, tras él, la salida de Vercel, común a todos. Efecto medido: la cuota de recuperación queda en ~30 peticiones cada 15 min para toda la plataforma (y `request` responde 202 igual), y ~30 fallos bloquean una cuenta para todo el mundo. Opción recomendada: **B**, una cabecera secreta que Vercel añade en el rewrite y la API verifica en tiempo constante antes de confiar en `x-real-ip`. Preguntas para el dueño en el RFC (rango de `FORWARDED_ALLOW_IPS`, secreto compartido y su rotación, plan de Vercel, clientes directos a `*.onrender.com`). Mientras se decide, `api/diagnostico_proxy.py` registra `proxy_cabeceras_diag` en `/api/v1/auth/*` con la forma de las cabeceras de reenvío —solo clase, red truncada y huella HMAC de cada IP, nunca la IP entera—; se retira al aplicar la opción.
     **Y el (1) sigue igual el 2026-10-24:** a las 01:17 UTC una petición de recuperación para una cuenta del dominio `deloitte.es` dejó `password_reset_email sent=false`. Hay usuarios reales pidiendo el enlace y no les llega.
- **Acceptance criteria:**
  - (1) Un reset real de extremo a extremo en producción: pedir el enlace para una cuenta local, recibir el correo, cambiar la contraseña y entrar. Anotado con fecha, y con el backend de correo que usa la API.
  - (2) El `client_ip` de las líneas `http_request` del log de la API, comparado para dos usuarios en redes distintas: si coincide, la hipótesis es cierta y hace falta decidir de dónde sale la IP del cliente (una cabecera de Vercel verificable, o que el navegador llame a la API sin pasar por el rewrite).
- **Files de partida:** [services/password_reset.py](../services/password_reset.py), [api/middleware.py](../api/middleware.py), [web/next.config.ts](../web/next.config.ts), [observability/logging.py](../observability/logging.py), [config/settings.py](../config/settings.py), [docs/runbooks/correo-transaccional.md](runbooks/correo-transaccional.md)
- **Riesgo:** medio — (1) y (2) son comprobaciones; lo que salga de (2) toca la base del rate limiting.

### [P1] Poner en producción la rama `claude/funcionalidades-2026-10` (acción del propietario)
- **Área:** db/alembic/versions (v147–v149), `.github/workflows/scrape-daily.yml`, variables de repo
- **Problema:** la rama trae funciones que no se ven hasta que alguien las enciende fuera del código: tres migraciones, un cambio de workflow aprobado el 2026-10-12, y la ficha nocturna del pliego, que sigue apagada por coste.
- **Acceptance criteria:**
  - v147 (tipo de documento acreditativo), v148 (condiciones oficiales de CODICE) y v149 (el ledger de oportunidades deja borrar la organización) aplicadas con `plan` antes de `apply` ([runbooks/disaster-recovery.md §5](runbooks/disaster-recovery.md)); `/health/ready → schema: ok`. v149 toca el trigger de un registro inmutable: revisar su test antes.
  - Decidida la variable de repo `PLIEGO_FACTS_ENABLED`: con ella a `true`, `pliegos.yml` extrae la ficha de los expedientes abiertos cada noche (gasto acotado por el presupuesto LLM y `PLIEGO_FACTS_BATCH`); sin ella, lotes, criterios y solvencia del pliego solo aparecen al abrir una oportunidad. La publicación oficial de CODICE (v148) no depende de esto.
  - Comprobado que `domain_events_pending` baja tras el primer cierre con el despachador (ver el cerrado del 2026-10-12).
  - Tras el primer deploy: el P0 del ATOM y el P1 de los pliegos de PSCP verificados con datos.
- **Estado (2026-10-15):** fusionada como `e8889a0` (#471) y en producción. El
  primer criterio está hecho: v147–v149 aplicadas con `plan` (run 38765966684)
  y `apply` (run 38766204885), de v146 a `v149_ledger_borrado_org` a las 16:07
  UTC; `deploy.yml` (run 38766484577) en verde con `schema_revision = ok
  (v149_ledger_borrado_org)` y el smoke en verde (pero sondeó la instancia que
  ya servía, que era del mismo commit; ese gate se arregló el 2026-10-17).
  API, worker y Vercel sirven `e8889a0`. No se comprobó que hubiera una copia
  reciente de Supabase antes del `apply`: ninguna herramienta de la sesión
  lista los backups.
  El autodeploy de Render (P2 de `render.yaml`) llevó `e8889a0` a la API a las
  14:52 y al worker a las 15:17, antes de las migraciones. La API no dio 5xx en
  esa ventana. La pasada del worker de las 15:17 sí corrió contra v146: el paso
  `documentacion_avisos` falló con `UndefinedColumn: column c.tipo does not
  exist` (la columna es de v147) y saltó la alerta «[pipeline] paso
  documentacion_avisos falló»; el resto de la pasada terminó. `_run_periodic`
  libera el lock al fallar, así que la pasada de las 16:17, ya sobre v149, lo
  reintentó con éxito (`avisos: 0`).
  Siguen abiertos los otros tres criterios. El despachador corrió a las 16:17
  (`procesados: 0, ignorados: 1, fallidos: 0`), pero eso todavía no dice si la
  cola de `domain_events_pending` baja.
- **Riesgo:** bajo-medio — las migraciones ya están; queda el primer reparto real de avisos de caducidad y de la campana nueva.

## P2 — Media

### [P2] Medir y recalcular las etiquetas de tecnología tras las reglas de precisión (2026-10-30)
- **Área:** services/tech_signal.py, config/keywords.py, api/routes/licitaciones/analitica.py, scripts/medir_etiquetas_tecnologia.py (acción del propietario: medir en producción, revisar la muestra y recalcular)
- **Problema:** el detalle enseñaba demasiadas etiquetas de tecnología. El código ya está cambiado (ver «Cuántas etiquetas lleva una licitación» en [taxonomia-tecnologica.md](taxonomia-tecnologica.md)): el bloque del detalle solo lista lo que cada fuente predice, las keywords ambiguas no añaden etiqueta a una fila con señal firme y la señal de pliegos ignora lo que solo dice el pliego administrativo, topa las repeticiones y pide dos términos a las categorías.
- *Medido el 2026-10-30 (`etiquetas-tecnologia.yml`, modo `medir`, 30.563 licitaciones con alguna etiqueta):* el bloque del detalle enseñaba **13,8 etiquetas de media** (17.014 licitaciones con 16); con el filtro de #599, **1,36**. `ml_tecnologias` (lo que filtran el Radar y la analítica) tiene media 0,81 pero una cola de hasta 13 etiquetas, fundidas desde pliegos. Los términos que más etiquetas de pliego sostenían eran de tramitación («firma electrónica» 2.405, «licitación electrónica» 2.302, «factura electrónica» 2.237, «esquema nacional de seguridad» 1.653), y en la muestra ponían ADMIN_ELECTRONICA a licencias de Salesforce o a NetBackup: el 2026-10-31 pasaron a `KEYWORDS_DE_TRAMITACION`, ambiguas solo en los pliegos (en el título siguen contando: «Certificación de conformidad con el ENS» es ciberseguridad).
- **Acceptance criteria:**
  - `resumen` repetido tras el recálculo, con la media de cada vista anotada aquí.
  - Una muestra de 100 revisada a mano (`muestra` → rellenar `correcta` → `precision`), con la precisión por fuente anotada; si «solo_pliego» sigue baja, los términos de `terminos_solo_pliego` con un ejemplo real entran en `KEYWORDS_AMBIGUAS`.
  - `etiquetas-tecnologia.yml` en modo `recalcular` completo (`rehacer` con `"completo": true`), para que `ml_tecnologias` pierda lo fundido desde señales que ya no pasan.
- **Files de partida:** [scripts/medir_etiquetas_tecnologia.py](../scripts/medir_etiquetas_tecnologia.py), [services/tech_signal.py](../services/tech_signal.py), [config/keywords.py](../config/keywords.py)
- **Riesgo:** medio — las reglas cambian lo que se guarda: menos etiquetas por fila y algún verdadero positivo perdido (el golden de PLACSP pierde `DATOS_IA` en «Consultoría SAP BW … cuadro de mando»).

### [P2] [Rendimiento 2026-10] Lo que quedó de la revisión de rendimiento y código
- **Área:** db/upsert.py, services/entity_resolution.py, scheduler/{watchlist_rules_alerts,competitor_alerts}.py, services/deadline_reminders.py, db/repositories/aggregates.py, observability/alerts.py, varios helpers duplicados
- **Problema:** la revisión del 2026-10-26 (lo hecho está en _Cerrados_ con esa fecha) dejó abierto lo que necesita una decisión, una medición en producción o el OK del propietario:
  - **Adjudicaciones re-ingeridas en cada pasada.** `replace_adjudicaciones_batch` borra y reinserta las de cada expediente que el ATOM reenvía (cada ~4 h), con ids nuevos y `empresa_id` a NULL, que la resolución de empresas vuelve a calcular. Conservar `empresa_id` o saltarse los expedientes cuyas adjudicaciones no cambian es más rápido, pero una re-resolución hoy recoge alias y revisiones nuevas: decisión de producto.
  - **`entity_resolution`** recarga todos los alias y NIF cada 5.000 filas, y el fuzzy compara cada nombre con todos los alias de longitud parecida (~0,3 s por búsqueda con 200k alias, medido en memoria). Llevar las cachés entre lotes puede enlazar a una empresa que otro proceso fusionó entre medias; acotar candidatos puede perder casamientos.
  - **Jobs de avisos fila a fila:** `watchlist_rules_alerts` (una conexión por coincidencia), `competitor_alerts` (hasta ~52 consultas por entrada, repetidas por cada usuario que sigue a la misma empresa), `deadline_reminders` (2-3 viajes por usuario × favorito × ventana, casi todos `ON CONFLICT DO NOTHING`) y la derivación de eventos (`derive_new_events`: una consulta de estado y de seguidores por fila de historial; el recorrido cuadrático ya está corregido). SQL nuevo, con su sitio en `db/`.
  - **Overview de analítica:** `overview_funnel` y `overview_por_estado` recorren el mismo conjunto; `overview_ccaa_cubiertas` filtrado es `len(por_ccaa)`; `overview_concentracion_organos` trae todos los órganos a Python para sumar diez.
  - **`NOT IN (subconsulta)` de duplicados** (`db/sql_fragments.py`) en casi todo listado y agregado: comprobar con `EXPLAIN` que sigue siendo *hashed SubPlan*; si no, `NOT EXISTS` (ojo con la semántica ante NULL y los tests que fijan el SQL).
  - **Código muerto que exige borrar tests (§6):** `check_daily_lag`, `check_daily_consecutive_failures` y `check_ml_model_staleness` en `observability/alerts.py` no los llama nadie y el runbook de alertas los da por activos; borrarlos quita además dos importaciones congeladas del ratchet de capas.
  - **Helpers duplicados que ya divergen:** plegado de tildes (~9 copias, `services/pursuit_menciones.py` con NFD), `cpv4` (7), «ISO a instante UTC» (~15), parseo de importes en texto (`regional_rss` acepta «1.5 €» como 15), verificación OIDC de Google frente a la genérica.
  - **NIF de relleno** (`N/A`, `000000000`…): `services/entity_resolution.py` crea una empresa con ese NIF y le enlaza todas las adjudicaciones que lo traen; tres normalizaciones SQL distintas del NIF en `db/`. Contar en producción antes de tocar.
- **Acceptance criteria:** cada viñeta cerrada o convertida en su propio ítem, con la medición o la decisión que la justifica.
- **Files de partida:** [db/upsert.py](../db/upsert.py), [services/entity_resolution.py](../services/entity_resolution.py), [scheduler/watchlist_rules_alerts.py](../scheduler/watchlist_rules_alerts.py), [db/repositories/aggregates.py](../db/repositories/aggregates.py), [observability/alerts.py](../observability/alerts.py)
- **Riesgo:** medio — casi todo toca la ingesta o el dato publicado.

### [P2] Antes de activar Microsoft en producción: dos comprobaciones del propietario
- **Área:** variables de Render (`tenderflow-api`), registro de la aplicación en Entra ID
- **Problema:** el código ya no deja entrar con un correo que Entra no acredita ([ADR-037](adr/ADR-037-correo-acreditado-y-vinculacion-por-proveedor.md); el ítem P1 está en _Cerrados_). Quedan dos cosas que desde el repo no se ven: qué valor tiene hoy `OAUTH_MICROSOFT_CLIENT_ID` en Render (no se comprobó el 2026-10-09 ni el 2026-10-23), y que la aplicación de Entra emita el claim opcional `xms_edov`, sin el que nadie entra con Microsoft.
- **Acceptance criteria:**
  - Anotado con fecha el valor de `OAUTH_MICROSOFT_CLIENT_ID` en Render (vacío = Microsoft apagado).
  - Antes de ponerlo: `email` y `xms_edov` añadidos como claims opcionales del ID token (ADR-037 §3), y un login real con una cuenta de trabajo sin `oidc_id_token_email_not_verified` en el log.
- **Riesgo:** bajo — sin el claim el fallo es cerrado: nadie entra con Microsoft.

### [P2] Instalar la app de Renovate y ver su primer PR de Python (acción del propietario)
- **Área:** GitHub (app), renovate.json, .github/dependabot.yml
- **Problema:** desde el 2026-10-11 las actualizaciones de versión las abre Renovate y las de Dependabot están apagadas (`open-pull-requests-limit: 0`), pero la app de Renovate no está instalada en el repositorio. Mientras no lo esté, `renovate.json` es configuración muerta y el repo **no recibe actualizaciones de versión**.
- **Acceptance criteria:**
  - La app instalada y el primer *Dependency Dashboard* abierto.
  - Su primer PR de Python recompila los cuatro lockfiles con CI en verde. En local solo se validó la configuración y la lectura de dependencias (Renovate 44, `--platform=local`), no la recompilación.
  - Decidido si se apagan las *security updates* de Dependabot para no duplicar las de Renovate.
- **Files de partida:** [renovate.json](../renovate.json), [.github/dependabot.yml](../.github/dependabot.yml), [tests/test_unit_lock_cabeceras.py](../tests/test_unit_lock_cabeceras.py)
- **Riesgo:** bajo.

### [P2] [Rendimiento 2026-09] Medir la analítica en producción y encender su techo de sentencia
- **Área:** config/settings.py (`API_ANALYTICS_STATEMENT_TIMEOUT_MS`), variables de Render
- **Problema:** el mecanismo existe (`api/techo_analitica.py`, `db.connection.techo_de_sentencia`) pero nace apagado: sin `pg_stat_statements` de producción no se sabe cuántas agregaciones filtradas tardan hoy entre 15 y 30 s y pasarían a fallar. Una consulta cancelada ya no se reintenta (503 `query-timeout`), así que encenderlo no multiplica la carga.
- **Acceptance criteria:**
  - Distribución de duraciones de las consultas de `/analytics` y `/competitive` medida (`pg_stat_statements` o `http_request_duration_seconds` por ruta), anotada con fecha.
  - El valor elegido fijado en Render (o el default del setting cambiado) con el motivo; preferiblemente después del P1 de índices.
- **Riesgo:** medio — un techo corto convierte consultas lentas en errores.

### [P2] La portada cita el tamaño del censo bajo un titular que promete lo contrario
- **Área:** producción (acción del usuario) + web/src/app/(publico)/_components/franja-datos.tsx
- **Problema:** la franja de la portada publica el total del corpus público —medido el 2026-09-03 en producción: 417.182 expedientes— justo encima de una sección titulada «Un radar tecnológico, no un censo de toda la contratación pública». Las dos cosas son honestas por separado: el número sale tal cual de `/publico/sitemap/resumen` (ADR-014) y el titular describe la regla de entrada. Lo que las hace incompatibles es que la migración **v98**, que acota la superficie pública al universo tecnológico, está mergeada y **sin aplicar**: `migrate.yml` es `workflow_dispatch` y el `autoDeploy` de Render no migra. Ver el ítem cerrado del 2026-09-02 en [el archivo](archive/IMPROVEMENT_BACKLOG_CERRADOS.md).
- **Por qué importa más que un número feo:** es la única cifra que la portada aporta como prueba, en un producto que vende confianza en el dato. Un visitante que compruebe los CPV más frecuentes en `/cpv` encuentra reactivos de laboratorio.
- **Estado (2026-10):** v158 está aplicada en producción, así que v98 también; el código ya cuenta sobre el universo tecnológico. Queda solo verificar la cifra publicada y los CPV de `/cpv`.
- **Acceptance criteria:**
  - `migrate.yml` ejecutado y `alembic current` en v98 (se lee en el log del step "Estado actual del schema").
  - `/publico/hubs` deja de listar CPV ajenos a tecnología.
  - La franja de la portada baja a la cifra del universo tecnológico tras la siguiente revalidación.
  - Search Console verá una caída grande de URLs indexadas: es el objetivo, no un incidente.
- **Riesgo:** medio — el cambio es de datos publicados, no de código.

### [P2] La portada sirve una captura oscura a quien tiene el sistema en claro
- **Área:** web/src/app/(publico)/page.tsx, web/e2e/capturas-landing.spec.ts
- **Problema:** la superficie pública usa `defaultTheme="system"` y no tiene selector de tema, así que un visitante con el sistema en claro ve una página clara con una captura del producto en oscuro incrustada. Las dos imágenes de `_assets/` son las únicas que hay.
- **Cómo empezar:** el spec ya genera las variantes `-claro` (`npm run capturas:landing`, con el stack sembrado). Falta ejecutarlo, commitear `radar-hero-claro.webp` y `radar-hero-movil-claro.webp` y dar a `CapturaProducto` los `<source media="(prefers-color-scheme: dark)">` con los oscuros en el mismo cambio.
- **Acceptance criteria:** las dos variantes existen, se sirve una sola por visita (no dos descargas), y el spec de capturas las genera juntas.
- **Files de partida:** [web/e2e/capturas-landing.spec.ts](../web/e2e/capturas-landing.spec.ts), [web/src/app/(publico)/page.tsx](../web/src/app/%28publico%29/page.tsx)
- **Riesgo:** bajo.

### [P2] Dar de alta el check externo del latido del healthcheck (acción del propietario)
- **Área:** healthchecks.io (o equivalente), GitHub (variables cifradas de Actions), Render
- **Problema:** `scheduler/latido.py` hace una petición a `HEALTHCHECK_HEARTBEAT_URL` tras cada healthcheck con alertas, pero la variable está vacía en todas partes: no hay check externo esperándola. Mientras tanto, si el cron deja de ejecutar el healthcheck o el correo deja de entregarse, nadie lo nota.
- **Acceptance criteria:**
  - El check creado (periodo de 6 h, gracia de 2 h) y su URL guardada en el repositorio de GitHub con el nombre `HEALTHCHECK_HEARTBEAT_URL`; pasos en [observability-alerts.md §3.1](runbooks/observability-alerts.md).
  - `healthcheck.yml` lanzado a mano: el panel del servicio muestra el ping y el log del job dice `latido_enviado`.
  - Al pasar el cron al worker, la misma URL como variable de `tenderflow-worker`.
- **Files de partida:** [scheduler/latido.py](../scheduler/latido.py), [docs/runbooks/observability-alerts.md](runbooks/observability-alerts.md)
- **Riesgo:** bajo.

### [P2] `render.yaml` no gobierna el servicio que corre en producción
- **Área:** render.yaml, Render Dashboard (acción del usuario)
- **Problema:** el Blueprint está en el repo, pero el servicio de producción se creó a mano por el dashboard y nunca se vinculó a él, así que el fichero documenta una intención que nadie aplica: editarlo no cambia nada y leerlo puede inducir a error sobre cómo está configurado el servicio real. Lo que sí está activo es `autoDeploy`, y **sin healthcheck configurado** — es decir, un deploy que arranca mal reemplaza igualmente al que funcionaba, sin rollback automático. (Estado observado en la sesión del 2026-08-04; **reconfirmar en el dashboard antes de actuar**, que es barato.)
- **Progreso 2026-09-06 (O0.2 del plan v2, cierra D4):** la decisión ya está tomada y escrita — **se vincula el Blueprint y manda `render.yaml`**, con `autoDeploy: false` y `deploy.yml` como único disparador, porque es la única de las dos ramas que conserva CI como gate en vez de dejarlo en advisory. Lo que queda de este ítem es **exactamente lo que un agente no puede hacer**: vincular el Blueprint y apagar `autoDeploy` en el dashboard, y comprobar que un push a `master` produce un solo deploy.
- **Reconfirmado (2026-10-15), y ya con un fallo:** la API es el servicio
  `TenderFlow` (`srv-d8dq7df40ujc73cur9q0`, plan `standard`), con `autoDeploy:
  yes`, disparador `commit` y `healthCheckPath` vacío. El worker `TenderFlow-1`
  (`srv-db58n80473hc73a94rsg`) tiene healthcheck (`/api/v1/health/ready`) y
  autodeploy con disparador `checksPass`. Cada push a `master` produce dos
  deploys por servicio: el automático y el de `deploy.yml` (`deploy_hook`). Con
  `e8889a0`, la API se desplegó a las 14:52 (`dep-db8egkh42hec73c9a7sg`) y a
  las 16:09 (`dep-db8fl4t9fdbs739gc3bg`); el worker, a las 15:17 y a las 16:10.
  Los dos automáticos llegaron antes de que se aplicaran v147–v149 (16:07), y
  la pasada del worker de las 15:17 falló un paso contra el esquema viejo
  (detalle en el P1 de la rama `claude/funcionalidades-2026-10`). El gate de
  schema de `deploy.yml` presupone migrar antes de desplegar, y el autodeploy
  se adelanta a los dos: cada PR que trae una migración que el código ya lee
  repetirá el fallo.
- **Estado (2026-10-18, 01:22 UTC):** el autodeploy **sigue activo** según la API de Render,
  aunque se dio por apagado en el dashboard: `TenderFlow` con `autoDeploy: yes` y disparador
  `commit`, y `TenderFlow-1` con `yes` y `checksPass`. La prueba: `aec5c4b` (#496), fusionado
  a las 01:16:56, se desplegó solo en la API a las 01:16:59 (`dep-dba1s2oae00c739beh30`,
  `trigger: new_commit`). `tenderflow-mcp`, creado el 2026-10-17, ya tiene `autoDeploy: no`.
  Comprobar con `get_service` tras cambiarlo: el campo `updatedAt` del servicio cambia
  cuando se guarda el ajuste.
- **Acceptance criteria (lo que queda, todo acción del usuario):**
  - Blueprint vinculado y `autoDeploy` apagado en el servicio real; la cabecera de `render.yaml` anota la fecha de verificación.
  - `healthCheckPath` efectivo, verificado con un deploy deliberadamente fallido.
  - Un push a `master` produce exactamente un deploy, observado siete días.
- **Files de partida:** [render.yaml](../render.yaml), [.github/workflows/deploy.yml](../.github/workflows/deploy.yml)
- **Relación:** comparte superficie con el P3 de staging y plan de la API (más abajo); si se toca el servicio, conviene decidir ambos a la vez.
- **Riesgo:** bajo-medio — vincular un Blueprint a un servicio existente puede recrearlo; hacerlo en ventana y con el healthcheck decidido de antemano.
- **Al apagar `autoDeploy`:** los hooks de `deploy.yml` pueden pasar `?ref=<sha>` para desplegar exactamente `github.sha` en vez de la punta de `master` del momento. Render lo admite y responde 404 si el SHA no existe, pero **desplegar un commit concreto apaga el autodeploy del servicio**: por eso no se hizo en el arreglo del gate del 2026-10-17 (ver _Cerrados_). Una vez apagado a propósito, ya no hay efecto lateral.

### [P2] Migrar `licitaciones.importe` de `real` a `double precision`
- **Área:** db/alembic, db/upsert.py, shared/numeric.py
- **Problema:** la columna es `real` (float4, 4 bytes ≈ 7 cifras significativas) en producción mientras que los conectores escriben `float` de Python (float8): el valor que vuelve del SELECT nunca coincide con el que se escribió. El detector de diffs de `db/upsert.py::_upsert_chunk` comparaba con `!=` exacto y marcaba "importe cambió" en **cada** re-ingesta de un expediente intacto. Medido el 2026-08-16: un backfill de TED generó 635 filas de `licitaciones_history` con `changed_fields='importe'` y en los 7 días previos hubo 1.150 más —una tanda por run del cron—; ningún importe había cambiado (desvío relativo máximo snapshot↔actual: 4,96e-6, el límite de precisión de float4). También afectaba a `placsp` y `pscp`. **Mitigado el 2026-08-16** comparando con tolerancia relativa (`shared/numeric.py::values_equal`, `FLOAT_REL_TOL = 1e-5`) en el detector de diffs y en `services/contract_events.py::_classify` — este último protege además de las filas basura ya escritas, que siguen en la tabla y el cursor de eventos acabará procesando. Queda abierto el arreglo de raíz: mientras la columna sea float4, la tolerancia es obligatoria y ciega a cambios reales por debajo del 0,001 % (10 € en 1 M€).
- **Acceptance criteria:**
  - `licitaciones.importe` en `double precision` en producción, y `duracion_valor` con el mismo criterio (mismo tipo, mismo ruido).
  - `FLOAT_REL_TOL` baja al ruido residual de float8 (o la tolerancia se retira del campo) **sólo después** de verificar el tipo en producción, no en el mismo commit que la migración.
  - Limpieza de las filas de `licitaciones_history` con `changed_fields='importe'` cuyo snapshot no difiere del valor actual más allá de la tolerancia, y de los `contrato_eventos` de tipo `modificacion` derivados de ellas.
- **Ojo con la ventana:** requiere **OK humano explícito** (AGENTS.md §6, `db/alembic/`) y no se lanza a ciegas. `ALTER TABLE licitaciones ALTER COLUMN importe TYPE double precision` **reescribe la tabla entera** (~1,3 M filas) con lock `ACCESS EXCLUSIVE`, además de reconstruir `idx_lic_importe`. Hay precedente directo: la columna generada de `v68_fecha_pub_date_generated` tardó >30 min con lock exclusivo y no cupo en la ventana de mantenimiento. El plan que sí cabe es el de columna sombra: añadir `importe_f8`, backfillear por lotes, cambiar lecturas/escrituras y renombrar en una ventana corta.
- **Nota de deriva de schema:** `alembic upgrade head` crea la columna como `double precision` (`sa.Float` en `baseline002_pg_core_genesis`), así que **CI y cualquier bootstrap nuevo no reproducen el bug**: el `real` de producción viene del schema SQLite pre-ADR-021. Los tests de regresión (`tests/test_db_upsert.py::test_reingesta_identica_no_genera_historial_con_importe_float4`) alinean la columna con producción vía `ALTER` en una fixture para poder medir algo.
- **Files de partida:** [db/upsert.py](../db/upsert.py), [shared/numeric.py](../shared/numeric.py), [services/contract_events.py](../services/contract_events.py), [db/alembic/versions/baseline002_pg_core_genesis.py](../db/alembic/versions/baseline002_pg_core_genesis.py)
- **Riesgo:** alto — migra schema de la tabla núcleo con lock exclusivo sobre 1,3 M filas; la mitigación aplicada (tolerancia) es de riesgo bajo y ya cubre el síntoma.
- **Progreso (2026-09-18, PARCIAL, rama `worktree-agent-ae7fea40cc310a705`):** unificado con T2 del plan de arquitectura v2. El plan de columna sombra está escrito con el nombre que fijó el plan, **`importe_num numeric(14,2)`** (no `importe_f8`: céntimos exactos en vez de otro float), más `duracion_valor_num numeric` (`v133_nucleo_tipado_sombra`, sólo catálogo, sin reescritura), escritura dual en `db/upsert.py` que traduce el `float` del conector **antes** de que pase por `real`, backfill por lotes (`scripts/backfill_nucleo_tipado.py`) y runbook de la ventana ([runbooks/nucleo-tipado-ventana.md](runbooks/nucleo-tipado-ventana.md)). `FLOAT_REL_TOL` **no se ha tocado**. Pendiente, todo en producción: aplicar la ventana, verificar cero divergencias, mover las lecturas de `importe` a la sombra, y sólo entonces bajar la tolerancia y limpiar `licitaciones_history`/`contrato_eventos`. El test de round-trip exacto contra Postgres (`tests/test_nucleo_tipado_pg.py`) está escrito y **no se ha ejecutado**.
- **Progreso (2026-10-23, rama de la tanda paralela, OK del propietario a la migración):** escrita `v156_importes_double_precision`, que pasa a `double precision` `licitaciones.importe` y `duracion_valor` y los cuatro importes de `adjudicaciones` (`importe_adjudicado`, `importe_pagable`, `oferta_minima`, `oferta_maxima`). Inventario de dependencias con `pg_depend` en producción y en una base recién migrada: solo índices (los reconstruye el `ALTER`) y la vista `licitaciones_canonicas`, que la revisión tira y rehace con el cuerpo de `v102`; ningún trigger, función, `CHECK` ni `DEFAULT`. Un `ALTER TABLE` por tabla, para reescribir cada una una sola vez; `lock_timeout` 30 s y downgrade simétrico a `real` (con pérdida de precisión, documentada). El plan de columna sombra deja de ser el camino para `importe`: la tabla tiene hoy ~89 k filas vivas, no 1,3 M. `importe_num` **se conserva** (las filas antiguas conservan el redondeo de float4 hasta su reingesta; retirarla es decisión aparte). Ciclo `upgrade head` → `downgrade -1` ×3 → `upgrade head` verde en Postgres local. **Pendiente, propietario:** aplicarla con `migrate.yml` en ventana y con la ingesta parada (lock `ACCESS EXCLUSIVE` sobre `licitaciones` y `adjudicaciones` mientras se reescriben: 873 MB + 1,15 GB de índices y 280 MB; estimación sin medir, de uno a pocos minutos). **Después**, en otro cambio: bajar `FLOAT_REL_TOL` (o retirarla del campo) y limpiar `licitaciones_history`/`contrato_eventos`, como dicen los criterios.

### [P2] Modelo de baja por lote
- **Área:** services/ml, db/alembic, api/routes/predicciones.py, web/
- **Problema:** el modelo predice la baja **agregada por expediente** porque es la granularidad que puede servir `predicciones_baja` (PK `licitacion_id`) y la que mide `services/ml/calibration.py`. Pero el lote es la unidad sobre la que realmente se puja: en un expediente de 30 lotes, una sola cifra agregada es menos accionable que 30.
- **Acceptance criteria:**
  - Migración de `predicciones_baja` a PK `(licitacion_id, lote_id)` con `lote_id` nullable para expedientes de lote único.
  - `db/repositories/ml_dataset.py` expone la variante por lote (el denominador por fila ya existe: `EFFECTIVE_BUDGET_SQL`), `calibration.py` compara a la misma granularidad, y el DTO/endpoint/frontend exponen el desglose.
  - Se compara `mae_p50` por lote contra el agregado actual antes de sustituirlo; si no mejora, se documenta y se queda el agregado.
- **Files de partida:** [db/repositories/ml_dataset.py](../db/repositories/ml_dataset.py), [services/ml/calibration.py](../services/ml/calibration.py), [api/routes/predicciones.py](../api/routes/predicciones.py)
- **Progreso (2026-09-18, rama `worktree-agent-a0a81e5a659bd1de7`) — parte de código hecha, falta la medida:** `v140_predicciones_baja_por_lote` retira la PK y deja dos únicos parciales (patrón v65/v110): uno por expediente (`lote_numero IS NULL`) y otro por `(licitacion_id, lote_numero)`. La identidad del lote es **`lote_numero`, no `lote_id`**: `replace_lotes` renumera `lotes.id` en cada re-ingesta y la FK CASCADE de v86 habría borrado la predicción justo en la re-ingesta que trae la adjudicación, así que la calibración por lote no habría visto nunca un par (la columna `lote_id`, siempre NULL, se elimina). Hay dataset y features por lote (`construir_dataset_baja(por_lote=True)`, importe del lote), modelo propio `baja_model_lote` (`score_predicciones.py --model baja --por-lote --train`), batch por lote tras `ML_BAJA_POR_LOTE` (apagado por defecto), lecturas agregadas filtradas por `lote_numero IS NULL`, desglose aditivo `lotes` en `GET /licitaciones/{id}/prediccion-baja` y en el bloque de baja del detalle. **Pendiente, humano y con BD real:** correr `ENV=dev python scripts/comparar_baja_por_lote.py` (backtest sobre los mismos lotes + la comparación servida) y decidir si se enciende `ML_BAJA_POR_LOTE`; hasta entonces el agregado es lo servido. De paso: `PrediccionBajaResult.model_version` (contrato `string`) daba 500 con un modelo activo (int); se convierte en el validador sin cambiar el contrato.
- **Riesgo:** medio — migración de una tabla materializada + cambio de contrato API.

### [P2] Sustituir los fixtures sintéticos del corpus CODICE por expedientes reales
- **Área:** tests/fixtures/placsp/
- **Problema:** los once casos del corpus golden son estructuralmente fieles al CODICE pero escritos a mano: la sesión que los creó no tenía ZIP mensuales cacheados ni acceso al feed. El valor del corpus está en codificar variabilidad que nadie imaginó, y eso solo lo dan los datos reales.
- **Acceptance criteria:**
  - `ENV=dev python scripts/capture_placsp_fixtures.py --caso <caso>` sustituye cada fixture sintético por uno real, y `python -m tests.test_codice_parser_golden --update` regenera el golden con el diff revisado.
- **Estado (2026-10-15):** el corpus crece con dos casos más, también
  sintéticos (16 y 17, condiciones oficiales; el README lo dice), porque el
  proxy de la sesión que los escribió denegaba PLACSP.
  `capture_placsp_fixtures.py --caso condiciones|condiciones_por_lote` ya sabe
  recortarlos de una muestra real.
- **Estado (2026-10-24):** catorce casos reales en el corpus, del ATOM vivo, del ZIP de 2026-09 y del de 2026-06, recortados con `capture_placsp_fixtures.py --id` (acepta ya páginas ATOM y ZIP sueltos, y `--sustituir`). Siete sustituyen a su sintético (03, 08, 09, 13, 15, 16, 17) y siete son nuevos (19–24 y el 25 del ítem de las multilote). El README da la procedencia de cada uno (URL, entry, expediente, `updated`). Siguen sintéticos 01, 02, 04, 05, 06, 07, 10, 11, 12, 14 y 18: congelan construcciones que el feed no publica (el lote por `ProcurementProjectLotReference` del 01, los subcriterios anidados del 12, dos plazos con fechas distintas del 11…) o los leen otros tests por su id; de 02, 05 y 10 no hay ningún ejemplar en 99.813 entradas. **Queda decidir** si el ítem se cierra así o se borran los sintéticos de forma ficticia (01, 12).
- **Files de partida:** [scripts/capture_placsp_fixtures.py](../scripts/capture_placsp_fixtures.py), [tests/fixtures/placsp/README.md](../tests/fixtures/placsp/README.md)
- **Riesgo:** bajo — solo tests.


### [P2] Golden set de extracción de fichas: la calidad de la ficha no se mide
- **Área:** tests/eval, services/rag/fact_sheet.py
- **Problema:** el retrieval tiene eval con ratchet (`tests/eval/test_eval_rag.py`, MRR ≥ 0.65); la extracción de fichas y el resumen IA no tienen ninguno. La ficha ya tiene mecánica de validación dura (citas contra texto persistido), pero nadie mide precisión/recall por familia: un cambio de prompt, de modelo o del selector de páginas puede degradar la extracción sin que nada salte. El feedback de usuario (evento `asistente_feedback`, 2026-09-01) da señal débil; el eval da la red fuerte. Esto además **bloquea** la unificación del selector de páginas de la ficha con el retrieval pgvector (ítem siguiente): refactorizar ese selector sin eval es volar a ciegas.
- **Acceptance criteria:**
  - ~10 pliegos reales etiquetados a mano (lotes, criterios con pesos, solvencias, ANS, certificaciones) como fixture versionado.
  - Eval que mida precisión/recall por familia contra ese set, con umbral mínimo ratcheado al valor medido, mismo patrón que `MRR_MIN`.
- **Files de partida:** [tests/eval/test_eval_rag.py](../tests/eval/test_eval_rag.py), [services/rag/fact_sheet.py](../services/rag/fact_sheet.py)
- **Riesgo:** bajo en código; el coste real es el etiquetado manual (decisión/tiempo del mantenedor).
- *Estado (2026-10-11):* **código escrito, sin casos todavía.** Diseño y cambios al implementarlo en [plans/2026-10-eval-ficha-pliego.md](plans/2026-10-eval-ficha-pliego.md); queda el trabajo del propietario (su §8): capturar diez pliegos con `scripts/capturar_ficha_golden.py`, revisarlos con `scripts/revisar_ficha_golden.py` y fijar la base con `python scripts/eval_ficha.py --fijar-minimos`. Cambia un criterio de arriba: diez pliegos revisados, de los que tres se etiquetan además a fondo, en vez de diez desde cero. El ítem no se cierra hasta que existan los casos y `minimos.json`.
- **Nota 2026-09-28 (`tender-facts-v6`):** el selector de páginas **se cambió sin este eval**, a sabiendas, porque la ficha v5 no tenía nada que proteger: de 886 filas en producción, 17 `extracted` y 70 `needs_review`, casi todas con 0 hechos; el resto `failed`. Medición manual (Nemotron super, mismos pliegos, antes → después): `2025/191` 0 → 7 hechos, `20/026` fallo → 20, `2025/000423-PEA` 0 → 14, `1934/2026` 0 → 22; la fórmula de precio aparece en tres de los cuatro. Es una comparación de cuatro pliegos sin etiquetas, no un baseline: sigue haciendo falta el golden set para medir **precisión**, que esta nota no mide.
- **Nota 2026-10-29 (`tender-facts-v7`):** también sin este eval, una segunda llamada solo para `required_documents` con sus propias páginas (`_select_document_pages`). No cambia lo que ve la pasada general, así que no puede empeorar las demás familias; lo único medido es que en el PCAP de la oportunidad 17 entran las dos páginas del Sobre nº 1 que antes quedaban fuera. `cobertura_selector` cuenta ya esas páginas para `required_documents`, para que la base del eval no la infravalore.
- **Nota 2026-10-30 (`tender-facts-v8`):** solo la pregunta: `price_formula` acotada a la fórmula del precio. En la oportunidad 18 el modelo guardó ahí la de experiencia de perfiles (`otra`, 100 puntos) y el simulador decía «fórmula no calculable» con la proporcionalidad inversa de 40 puntos citada en `award_criteria`. Sin este eval no se sabe en cuántas fichas pasaba; el caso de la 18 es lo único comprobado.

### [P2] Unificar la selección de páginas de la ficha con el retrieval pgvector
- **Área:** services/rag/fact_sheet.py, services/rag/context.py
- **Problema:** conviven dos nociones de "texto relevante del pliego": la ficha puntúa páginas con términos hardcodeados (`_TOPIC_TERMS`/`_TECH_TERMS`, con footguns documentados en el propio fichero) y el chat/resumen rankea chunks (desde 2026-09-01, vía pgvector con fallback Python). Dos selectores, dos presupuestos, dos mantenimientos. La convergencia natural: seleccionar páginas de la ficha con queries fijas por familia ("criterios de adjudicación", "solvencia económica"…) contra los embeddings persistidos, y retirar las listas de términos.
- **Por qué NO se hizo en el cambio del 2026-09-01:** el selector actual está batallado y la extracción no tiene eval (ítem anterior). Cambiar qué páginas ve el LLM sin poder medir el efecto sobre la ficha es exactamente el tipo de regresión silenciosa que este backlog existe para evitar. Orden correcto: primero el golden set, después este refactor medido contra él.
- **Acceptance criteria:** un único camino de selección de contexto de pliegos parametrizado por caso de uso; `_TOPIC_TERMS`/`_TECH_TERMS` retirados; el eval de extracción igual o mejor que el baseline medido.
- **Files de partida:** [services/rag/fact_sheet.py](../services/rag/fact_sheet.py), [services/rag/context.py](../services/rag/context.py), [db/repositories/documentos.py](../db/repositories/documentos.py)
- **Riesgo:** medio — toca el camino que produce el dato más confiable del producto; por eso va detrás del eval.

### [P2] Hay PDFs cuyo texto sale con las tildes cambiadas («Nœmero», «ClÆusula») y nada lo detecta
- **Área:** scraper/document_fetcher.py (`page.extract_text()` de pypdf), services/rag/fact_sheet.py
- **Problema:** en el PCAP de `placsp:10000400045061:IPA 1/27` (documento 235069, oportunidad 17), visto el 2026-10-29 desde la API de páginas, el texto persistido trae `á→Æ`, `é→Ø`, `ú→œ` y la `ó` intacta: «Sobre Nœmero», «ClÆusula», «tambiØn». Es el patrón de una fuente con codificación propia que pypdf decodifica con la tabla equivocada. El texto entra así en `documento_pages` y de ahí a todo lo que lo lee: cualquier término con á, é o ú del selector de la ficha (`_TOPIC_TERMS`, `_DOC_TERMS`) no puntúa esa página, la búsqueda por texto y los embeddings ven otra palabra, y la cita literal que enseña la UI sale rota. Nadie sabe cuántos documentos están así.
- **Acceptance criteria:**
  - Medido en producción cuántos documentos `extracted` tienen el patrón (p. ej. páginas con `Æ`, `Ø` o `œ` dentro de una palabra en minúscula), con fecha.
  - Si son una fracción relevante: la extracción repara o evita el patrón (otro extractor para ese PDF, o reparar la tabla conocida) con un test sobre un PDF que lo reproduzca, y un comando que re-extraiga los afectados. Las citas ya guardadas en `tender_fact_sheets` dejan de casar con el texto nuevo, así que esas fichas se reprocesan también.
  - Si son residuales: el porqué, escrito aquí, y el ítem se cierra.
- **Files de partida:** [scraper/document_fetcher.py](../scraper/document_fetcher.py), [services/rag/fact_sheet.py](../services/rag/fact_sheet.py)
- **Riesgo:** medio — cambiar el texto persistido invalida las citas verificadas de las fichas que lo usan; por eso el reproceso va en el mismo cambio.

### [P2] El corpus de PSCP ahoga el dataset del clasificador SAP: no se puede reentrenar, y el modelo servido no discrimina
- **Área:** services/ml/classifier_training.py (`train_from_db`), scraper/connectors/pscp.py, services/ml/classifier_pipeline.py (`validate_training_data`)
- **Problema:** `train_from_db` construye el dataset con un `SELECT … FROM licitaciones` **sin filtro de fuente**, y la etiqueta es «`raw_keywords` no vacío OR `tecnologia` no vacía». Medido contra producción el 2026-09-04:

  | fuente | filas | positivos | % |
  |---|---|---|---|
  | **pscp** | 683.076 | 3.113 | **0,46%** |
  | placsp | 6.853 | 4.412 | 64% |
  | bulk_* | 13.095 | 376 | 2,9% |
  | ted | 2.015 | 140 | 6,9% |
  | **total** | **705.094** | **8.041** | **1,14%** |

  Dos consecuencias, las dos verificadas:
  1. **No se puede reentrenar.** `validate_training_data` exige ≥5% de clase minoritaria y aborta con `Minority class is only 1.1% of data`. El run [33855421538](https://github.com/Dkalds/TenderFlow/actions/runs/33855421538) (2026-09-04) murió ahí. El gate hizo su trabajo: no se publicó nada.
  2. **El modelo servido no discrimina sobre esa población.** El de mayo se entrenó cuando el corpus eran ~4k filas de PLACSP con 64% de positivos. Hoy puntúa 683k registros de PSCP que nunca vio y da **90,64% del corpus por encima del umbral** (0,4657), con 42% de las filas en la banda 0,9-1,0. Un binario que dice «SAP» a 9 de cada 10 es una constante, no un clasificador.

  Esto salió a la luz al arreglar la descarga de modelos (#263): hasta entonces el 96% de las filas tenía `ml_proba` a NULL y no había con qué verlo.
- **La bifurcación (hay que elegir, no es solo trabajo):**
  1. **Acotar la población de entrenamiento** por fuente. PLACSP + bulk + TED son 21.963 filas con 4.928 positivos = **22,4%**, muy por encima del suelo: el entrenamiento saldría hoy. Contrapartida: el modelo aprendería de una población distinta de la que puntúa, que es una forma nueva del mismo problema.
  2. **Arreglar el etiquetado de PSCP**, si esas 683k filas deberían llevar `tecnologia`/`raw_keywords` y no las llevan. Sería un bug de conector, y haría innecesaria la opción 1.
  3. **Aceptar** y dejar el modelo de mayo, asumiendo que su score no informa sobre PSCP.
- **Orden sugerido:** mirar primero por qué las filas de PSCP no llevan `tecnologia`. Si es un bug de conector, la opción 2 resuelve las dos consecuencias a la vez; si es correcto (el corpus de PSCP realmente es 99,5% no-TI), entonces la pregunta de verdad es por qué se ingiere entero, y eso conecta con la «contaminación PSCP» de la auditoría de 2026-08.
- **Files de partida:** [services/ml/classifier_training.py](../services/ml/classifier_training.py) (`train_from_db`, la query y la etiqueta), [services/ml/classifier_pipeline.py](../services/ml/classifier_pipeline.py) (`validate_training_data`), [scraper/connectors/pscp.py](../scraper/connectors/pscp.py)
- **Relación:** bloquea el P1 del golden set (ampliarlo no sirve de nada si el dataset de entrenamiento está ahogado) y explica por qué `model_versions` no tiene ninguna fila de `sap_classifier`.
- **Riesgo:** medio — cambiar la población de entrenamiento cambia qué aprende el clasificador que decide el rescate ML en ingesta.
- **Progreso parcial (2026-09-14, Ola 1 · Taxonomía):** parte del 0,46 % era vocabulario, no población: el diccionario solo tenía castellano y la PSCP publica en catalán. `config/keywords.py` añade nueve categorías de TI con formas en catalán, euskera y gallego ([docs/taxonomia-tecnologica.md](taxonomia-tecnologica.md)); tras resembrar, la tasa de positivos de PSCP hay que volver a medirla antes de decidir la bifurcación. No toca la población de entrenamiento ni `validate_training_data`.
- *Estado (2026-10-24):* el código de F3 ([plan](plans/2026-09-27-clasificacion-tres-niveles.md) §6) sustituye la etiqueta «alguna keyword» por la humana o la del LLM cuando su acuerdo es apto, sin submuestrear negativos y con calibración isotónica temporal (`services/ml/nivel1.py`). El gate (`services/ml/nivel1_eval.py`) exige batir a los baselines «solo keywords» y «solo CPV 48/72» con la cota inferior del IC95 de la diferencia por encima de cero. No se ha entrenado: falta el golden (ver «Ampliar el golden set…»).
- *Estado (2026-10-25):* revisado al trabajar el golden: **no queda filtro ni estratificación que añadir al dataset**. La opción 1 está en código y con tests (`poblacion_clasificador_sql` excluye `pscp_observed` y los duplicados confirmados, `tests/test_ml_poblacion_entrenamiento.py`), la purga se ejecutó y el reentreno del 2026-09-27 ya pasó `validate_training_data` (21,7 % de positivos), y `precompute_ml_proba` puntúa la misma población. Lo que mantiene abierto el ítem es la consecuencia 2 —el modelo servido sigue siendo el de mayo— y su causa es la etiqueta, no el corpus: se cierra cuando se promocione un binario entrenado con el golden humano. Candidato a archivar en cuanto eso pase.
- *Estado (2026-09-27):* la purga se ejecutó (PSCP quedó en 35.542 filas) y ese mismo día el binario reentrenado sobre la población acotada (32.641 filas, 21,7 % de positivos) completó y el gate lo rechazó: `recall_no_keyword` 0/3, F1 temporal 0,52 frente a 0,94 en validación cruzada. La causa ya no es la población sino la etiqueta, que sigue siendo «alguna keyword»: el plan [2026-09-27-clasificacion-tres-niveles](plans/2026-09-27-clasificacion-tres-niveles.md) la sustituye por etiquetas del LLM revisadas por humanos.
- *Estado (2026-09-26):* medido contra producción, las 683k filas de PSCP **no** eran un bug de etiquetado: son el censo catalán entero (0 filas se llegaron a marcar `pscp_censo`). El RFC [2026-09-26](rfc/2026-09-26-rfc-purga-pscp-sin-tecnologia.md) las purga reevaluando cada fila con la puerta del conector —conserva las que el diccionario de hoy sí reconoce, y la reingesta posterior las reetiqueta—; queda pendiente de ejecutar (P1 «Ejecutar en producción la purga de PSCP»). Tras ella, la población de entrenamiento deja de depender del acotado.
- *Estado (2026-09-19):* **la bifurcación ya se tomó en código, por la opción 1**, y el ítem no lo decía. Desde S6.1 del plan v2 (`#274`, 2026-09-08) `train_from_db` (`services/ml/classifier_training.py:374-418`) no lee `licitaciones` entera: entrena sobre `db.repositories.ml_dataset.filas_entrenamiento_sap`, acotada por `poblacion_clasificador_sql` (universo tecnológico observado, no un filtro por nombre de fuente, y sin duplicados confirmados), pasa `validate_training_data` en ese mismo camino y registra la población como `train_population`. Lo que sigue abierto es la consecuencia que la propia opción 1 anunciaba —el modelo puntúa una población distinta de la que aprende— y la medida: `domain-truth.yml` seguía dando `ml_proba > 0,7` en el 72,9 % de lo puntuado del 12 al 18/09 (ver el P2 de `importe_tipo`). No se comprobó aquí si hay ya una versión de `sap_classifier` entrenada con esa población.

### [P2] `baja_model` v2 y `retencion_model` v1 están entrenados y publicados, pero nadie puede decidir si activarlos
- **Área:** db/model_registry.py, services/ml/baja_model.py, services/ml/calibration.py (acción del usuario)
- **Problema:** desde el 2026-09-03 el reentrenamiento vuelve a completar y sus artefactos están en la Release, pero las tres filas de `model_versions` siguen con `is_active = 0`, así que `ml-scoring.yml` sirve baseline **en verde**. La activación es decisión humana por diseño (`train-predictivos.yml`: *"salvo `ML_PRED_AUTO_ACTIVATE`"*), y el problema es que **las métricas registradas no permiten tomarla**:
  - `baja_model` v2 mejora al baseline un **3,3%** (`mae_p50` 0.12494 vs `mae_baseline` 0.12999, o sea 0.005), pero su propia dispersión entre folds es **`mae_p50_std_folds` = 0.01287**, dos veces y media esa mejora. Es indistinguible de ruido con la evidencia que hay.
  - `retencion_model` v1 no registra **ninguna** métrica de baseline (`pr_auc` 0.2453 sobre prevalencia 0.1099, `ece` 0.054): no hay contra qué compararlo.
  - `baja_model` v1 (2026-08-05) sí registra una mejora del 17,8%, pero su ventana de validación dice `valid_hasta: "2032-06-23"` —una fecha futura, o sea basura— y se entrenó antes del arreglo del rolling origin y del filtro de fechas. No es comparable, y su artefacto ya no está en la Release.
- **Por qué no se activó al arreglar la descarga (2026-09-03):** activar cambia lo que ve producción, no hay gate automático como el de `services/ml/promotion.py` del SAP, y no hay medición posterior que detecte una regresión. Activar sobre una mejora menor que la varianza es activar sobre ruido.
- **Acceptance criteria:**
  - Un criterio de promoción escrito para los predictivos, del mismo tipo que el del clasificador SAP: qué margen sobre el baseline y con qué dispersión se considera suficiente.
  - `retencion_model` registra una métrica de baseline comparable (el ranking trivial por prevalencia o por antigüedad del contrato).
  - Decidido y ejecutado: activar o descartar, con el número que lo justifica anotado en `notes` de `model_versions`.
- **Files de partida:** [db/model_registry.py](../db/model_registry.py), [services/ml/baja_model.py](../services/ml/baja_model.py), [services/ml/promotion.py](../services/ml/promotion.py) (el gate del SAP, como referencia), [.github/workflows/train-predictivos.yml](../.github/workflows/train-predictivos.yml)
- **Riesgo:** medio — activar cambia lo que sirve `predicciones_baja` sin red que lo detecte.
- **Progreso parcial (2026-09-18, rama worktree-agent-a3fd0bc81b8a949c2) — los dos primeros criterios ya estaban en código; queda solo la decisión humana.** Comprobado contra el código: el criterio escrito existe desde #274 (v2 S6.4) — `services.ml.promotion.evaluar_promocion_predictiva`: una versión solo es promocionable si su mejora sobre el baseline mide al menos `MIN_IMPROVEMENT_OVER_FOLD_DISPERSION` (1.0) veces la dispersión de la métrica entre folds, sin dispersión medida no se promociona, y los criterios del RFC entran como motivos extra. `baja_model.entrenar` y `retencion_model.entrenar` lo aplican y dejan el veredicto en `notes` (`promotion_reason`); retención registra `pr_auc_baseline` (prevalencia) y `pr_auc_std_folds` (bloques contiguos de validación). Tests en `tests/test_ml_promocion_predictiva.py`; el runbook `model-rollback.md` lo cita. Esta rama añade a retención el rival de antigüedad que pedía el criterio: `pr_auc_baseline_antiguedad` (ordenar por `antiguedad_relacion_meses`), **informativo, no gatea**. Aplicado a los números de arriba, baja v2 sale «indistinguible de ruido» (0.005 < 0.0129). **Falta (humano):** relanzar `train-predictivos.yml` para que retención tenga dispersión y rival registrados —v1 es anterior al gate—, y decidir activar o descartar con el `promotion_reason` delante.
- **Progreso (2026-09-24, rama `claude/ml-scoring-improvements-da84e5`) — activar ya no rompe el scoring al mes siguiente.** Hasta hoy todas las versiones se publicaban como `baja_model.pkl`/`retencion_model.pkl` con `--clobber`: activar vN y dejar que el reentrenamiento mensual registrara vN+1 sin activar pisaba el asset de vN, y `ml-scoring.yml` caía cada día por `ModelArtifactMismatch` hasta activar vN+1. Ahora cada versión nueva lleva un nombre derivado de su contenido (`baja_model-<sha12>.pkl`) en la Release fija `ml-models`. La resolución busca por nombre en `ml-models` → *latest* → las 30 Releases más recientes, así que las filas actuales (v2 y v1, de nombre fijo) se siguen encontrando. La decisión pendiente es solo la de arriba.
- **Progreso (2026-10-23):** el criterio aplicado a estas dos versiones, condición por condición y con sus constantes, está en `docs/runbooks/model-rollback.md` § «`baja_model` v2 y `retencion_model` v1: qué hace falta para decidir». Resultado con lo registrado: baja v2 **no promocionable** (falla la dispersión y el 10 % relativo); retención v1 **no decidible** (sin `pr_auc_std_folds`; su margen sobre la prevalencia, 0,135, tampoco llega al 0,15 del RFC). Sigue faltando relanzar `train-predictivos.yml` y decidir sobre la versión nueva. No se activó ni se descartó nada.

### [P2] ml-scoring: verificar en producción el arreglo del 2026-09-24 y cerrar sus flecos
- **Área:** services/ml/, scheduler/jobs/ml_predicciones.py, .github/workflows/ml-scoring.yml, shared/release_assets.py
- **Problema:** El job estaba al borde de su `timeout-minutes: 20`: el 2026-09-20 consumió 1.190 de los 1.200 s. Unos 11 minutos se iban en features de retención que la rama baseline calculaba y tiraba, y otro minuto en hilos del pool que no se cerraban. La rama `claude/ml-scoring-improvements-da84e5` corrige eso y nueve puntos más:
  - disparo tras la ingesta, con un guard de una corrida al día;
  - preflight de schema;
  - verify por `computed_at`;
  - artefactos con nombre por contenido;
  - drift que solo alerta según el régimen servido;
  - dedup de alertas;
  - población sin zombis;
  - baseline de retención con shrinkage jerárquico;
  - purga de filas viejas.

  Falta medirlo en producción y cerrar lo que no entró.
- **Acceptance criteria:**
  - En los primeros runs tras el merge:
    - el step de scoring tarda menos de 6 min (`duraciones_s` en el resumen del job);
    - hay una sola corrida por día UTC (las demás salen con `ya_puntuado_hoy`);
    - el preflight sale verde;
    - el verify corre en modo `corrida`.
  - Medir cuántas filas borra `purgar_sin_adjudicar` en su primera pasada y cómo cambia el PSI del drift con la población viva. Antes, la mediana de `n_obs_organo` era 3 en scoring y 1.293 en la referencia.
  - Decidir `ML_RETENCION_EXCLUIR_RESUELTOS` tras auditar una muestra de `resueltos_detectados`. Hoy está apagado: la heurística órgano + CPV-4 da falsos positivos en segmentos con mucha actividad, y excluir un contrato lo esconde del orden «score». `scripts/audit_retencion.py` solo audita pares de entrenamiento; hay que añadirle un modo `--resueltos`.
  - Que el entrenamiento de retención deje de ser cuadrático. `construir_pares` llama a `_features_historicas` por cada par (~5,5K pares × ~698K adjudicaciones × 2), y `_emparejar` es O(Σ n²) por segmento. Solución: índices por clave más bisect, con paridad contra la referencia como en `tests/test_ml_retencion_serving.py`.
  - Resolver la clave de `predicciones_retencion` **antes de activar `retencion_model`**; exige migración. La tabla guarda un riesgo por expediente (`licitacion_id` es la PK), pero Renovaciones pinta una fila por empresa adjudicataria. Con el modelo, que sí depende de la empresa, un expediente con varios adjudicatarios mostraría a todos el riesgo del primero.
  - Pasar a `locate_release_asset` y a una Release fija lo que aún publica y busca solo en *latest*: `ensure_downloaded` de `services/ml/sap_classifier.py` y de `services/ml/tech_classifier.py`, más `train-model.yml` y `train-tech.yml`. *SAP hecho el 2026-10-24* (`ensure_downloaded` busca con `locate_release_asset` y `train-model.yml` publica en `ml-models`); quedan `tech_classifier` y `train-tech.yml`.
  - ~~Arreglar `observability/logging.py::redact_dsn`, que no redacta la contraseña de los DSN con driver (`postgresql+psycopg://…`).~~ **Hecho el 2026-10-25:** la regex admite `+driver` y la propia de `db/schema_revision.py` se retira (test parametrizado en `tests/test_observability_logging.py`).
- **Files de partida:** [scheduler/jobs/ml_predicciones.py](../scheduler/jobs/ml_predicciones.py), [services/ml/retencion_labels.py](../services/ml/retencion_labels.py), [shared/release_assets.py](../shared/release_assets.py), [.github/workflows/ml-scoring.yml](../.github/workflows/ml-scoring.yml)
- **Riesgo:** bajo para las verificaciones; medio para la clave de `predicciones_retencion`, que exige migración.

### [P3] Las 47 adjudicaciones con fecha imposible siguen anclando filas de entrenamiento
- **Área:** services/ml/features.py, db/repositories/ml_dataset.py, scraper/connectors/pscp.py
- **Problema:** el #262 filtra en `_fecha_opt` los años de menos de cuatro cifras (`0019-12-10` del expediente `19/002/5-2`, `0202-02-27` de PSCP), que es lo que rompía el round-trip de `%Y`. Pero de las **47 filas** de `adjudicaciones` con `fecha_adjudicacion` imposible —medidas contra producción el 2026-09-03— la mayoría son `1899-12-30`: el cero de la epoch de Excel, o sea como PSCP exporta una celda vacía. Esas pasan el filtro, porque tienen cuatro cifras y parsean bien. Y el ancla del dataset es `LEAST(fecha_publicacion, fecha_adjudicacion)`, así que ganan: la fila entra en el train de **todos** los folds con los acumuladores históricos vacíos, y su adjudicación los alimenta como si precediera a todo el histórico.
- **Por qué no se subió el umbral con el #262:** el `_ANIO_MINIMO = 1000` está justificado por la asimetría de `%Y` entre `strptime` y `strftime`, que es un hecho del parser y no admite discusión. Un umbral de *plausibilidad* (1990, 2008…) es una afirmación distinta —sobre los datos, no sobre el formato— y merece decidirse aparte en vez de colarse dentro de una constante que hoy significa otra cosa.
- **Acceptance criteria:**
  - Decidido dónde se corta: el conector de PSCP (que es quien genera el `1899-12-30`), el parser, o el SQL del dataset.
  - Las 47 filas dejan de anclar filas de entrenamiento, verificado con la misma query que las midió.
- **Files de partida:** [services/ml/features.py](../services/ml/features.py) (`_fecha_opt`), [db/repositories/ml_dataset.py](../db/repositories/ml_dataset.py) (`fecha_anchor`), [scraper/connectors/pscp.py](../scraper/connectors/pscp.py)
- **Riesgo:** bajo — son 47 filas de ~691k adjudicaciones; el impacto es de calidad de dataset, no de disponibilidad.
- **Progreso parcial (2026-09-18, rama worktree-agent-a3fd0bc81b8a949c2) — decidido: se corta en los dos extremos, y en ninguno con `_ANIO_MINIMO`.** El conector de PSCP ya descartaba en origen desde C4.4 las fechas anteriores a `shared.dates.ANIO_MINIMO_PLAUSIBLE` (1990; cubre `1899-12-30` y `1900-01-00`), pero no puede ver las filas ya escritas. Para esas, `db/repositories/ml_dataset.py` añade `fecha_adjudicacion >= '1990-01-01'` (como parámetro, `_filtro_fecha_adj`) en las dos CTE de `_sql_agregado` y de `_sql_por_lote` y en `adjudicaciones_por_empresa` (HHI): la fila se trata como adjudicación sin fecha —lo que es—, que ya quedaba fuera por el `IS NOT NULL`. `_ANIO_MINIMO = 1000` del parser no cambia de significado (lo fija un test). Efecto colateral buscado: las subconsultas de lotes dejan de contar adjudicaciones sin fecha que la CTE principal nunca vio. Tests: `tests/test_ml_dataset_fecha_plausible.py` (SQL y parámetros sin BD; uno contra Postgres **no ejecutado** en local) y el de año corto de `tests/test_ml_features.py` adaptado. **Falta:** verificar contra producción, con la query de `db.domain_truth_audit.adjudicaciones_con_fecha_imposible`, que ninguna de esas filas aparece en `pares_baja_agregada()` — sin acceso a la BD desde esta rama.

### [P2] [Ola 1 · S3] Oportunidad por lote, y saber si el Radar prioriza bien
- **Área:** db/repositories/pursuits.py, services/pursuits.py, services/product_metrics.py, web/src/app/(dashboard)/oportunidades
- **Problema:** `pursuits` es única por `(organization_id, licitacion_id)`, así que no se puede abrir una oportunidad por lote — que es la unidad sobre la que de verdad se puja, y que los lotes existen desde `v65`. Y el bucle del Radar no se cierra: `score_al_abrir` y `banda_al_abrir` se persisten desde `v93` y **ningún módulo de producción los lee**, o sea que el producto no puede responder si la banda «Caliente» acierta.
- **Decisión ya tomada (2026-09-06):** D12 → `pursuits.lote_id` nullable con dos únicos parciales (patrón `v65`); `NULL` significa expediente completo y las filas existentes no cambian.
- **Acceptance criteria:** los de S3.1–S3.3 del plan v2. La precisión por banda solo se pinta con N ≥ 10 y, por debajo, dice «sin datos suficientes» (ADR-014); la propuesta de pesos nunca se aplica sola.
- **Files de partida:** [docs/plans/2026-09-plan-arquitectura-v2.md](plans/2026-09-plan-arquitectura-v2.md) (§5, S3), [db/repositories/pursuits.py](../db/repositories/pursuits.py)
- **Relación:** desbloquea el P2 «Modelo de baja por lote» de este backlog (S6.5 del plan sirve las filas por lote que `predicciones_baja` ya guarda desde `v86`).
- **Estado:** lo dice el §5 del plan, no este ítem. **Corrección de un hecho de la línea anterior**, comprobada el 2026-09-08: `predicciones_baja` **no guarda filas por lote**. `v86` dejó la columna `lote_id` preparada, pero el único escritor (`score_predicciones_baja`) nunca la rellena y su `ON CONFLICT(licitacion_id)` ni siquiera dejaría convivir dos filas del mismo expediente. S6.5 sirve la estimación agregada declarándolo en `prediccion_ambito`; la `baja_real` sí es del lote. El «Modelo de baja por lote» sigue, pues, siendo trabajo de ML, no de fontanería. (2026-09-18: `v140` ya permite y escribe filas por lote, identificadas por `lote_numero`; ver el progreso de ese ítem.)
- **Estado (2026-10-17):** las dos mitades del **Problema** están resueltas en código: la oportunidad por lote existe (`pursuits.lote_numero`, `v110`, con el lote resuelto por número en `_PURSUIT_SELECT`) y `score_al_abrir`/`banda_al_abrir` se leen en `services/pursuits.py::calcular_radar_quality`, que pinta precisión y tasa de cierre por banda con mínimo de N (`components/pursuits/radar-quality.tsx`, Dirección). Lo que faltaba para cerrar una oportunidad de lote —saber de qué lote es cada adjudicación— quedó resuelto el 2026-10-18 (ver _Cerrados_ del archivo); el resto es el P3 «247 adjudicaciones de expedientes multilote siguen sin lote».
- **Riesgo:** medio — cambia la clave única de una tabla viva; `plan` antes de `apply`.

### [P2] [Ola 1 · S4] Eventos y salida: siete almacenes con forma de evento y ningún backbone
- **Área:** db/events.py, shared/events.py, scheduler/jobs/event_dispatch.py, api/routes/webhooks.py, services/notifications.py, api/routes/watchlist_rules.py
- **Progreso (2026-10-26):** el ratchet de productores (`tests/test_s4_outbox_ratchet.py`) ya existía; ahora lee el AST y recorre también `config/`, `mcp_server/` y `observability/`. Siguen 4 productores directos. Ver [plan 2026-10](plans/2026-10-plan-foco-piloto.md) §8.
- **Problema:** conviven `pursuit_events`, `contrato_eventos`, `licitaciones_history`, `user_notifications`, `pending_digests`, `webhook_deliveries` y `domain_events`, y la tabla de event sourcing solo la escriben dos sitios. El equipo se entera por email o abriendo la consola: los webhooks exigen `require_admin` en todas sus rutas y `_VALID_EVENTS` tiene cuatro tipos. Y un cambio en un expediente seguido —`licitaciones_history` guarda `changed_fields`— no genera ninguna alerta.
- **Decisión ya tomada (2026-09-06):** D13 → plantillas de payload (`json`, `slack_blocks`, `teams_adaptive_card`) sobre el webhook genérico, no integraciones nativas con OAuth de cada plataforma, y webhooks que pueda crear un miembro dentro de su organización.
- **Acceptance criteria:** los de S4.1–S4.6 del plan v2. El que sostiene lo demás es el ratchet de productores: toda inserción directa en `user_notifications`/`pending_digests` fuera del despachador entra en una lista que solo puede encoger.
- **Files de partida:** [docs/plans/2026-09-plan-arquitectura-v2.md](plans/2026-09-plan-arquitectura-v2.md) (§5, S4), [db/events.py](../db/events.py), [api/routes/webhooks.py](../api/routes/webhooks.py)
- **Estado (2026-10-17):** dos frases del **Problema** ya no son ciertas: los webhooks los crea un miembro con escritura en su organización (`require_organization(write=True)`, `v108`) con formatos `json`/`slack_blocks`/`teams_adaptive_card`, y un cambio en un expediente seguido sí genera aviso (`services/avisos.py::clasificar_cambio`, llamado desde `services/contract_events.py` y `services/novedades.py`). Lo abierto es el ratchet de productores fuera del despachador.
- **Progreso (2026-10-25, rama `agente/outbox-domain-events`):** dos consumidores más leen del backbone. (1) **Campana/correo de asignación**: `PursuitRepository.create/update` escribe `pursuit.assigned` en la misma transacción que la asignación (texto de `shared.events.payload_asignacion`, idéntico al de antes salvo que el actor nunca viaja por email) y `services/pursuits.py` sale de `PRODUCTORES_DIRECTOS`. Efecto añadido: la asignación llega también por correo según la preferencia S4.6 (`immediate` por defecto) y a los webhooks `pursuit.*`, como pedía el catálogo. (2) **Webhooks**: `solicitud_acceso.creada` se escribe en el outbox desde `db/solicitudes_acceso.crear_solicitud` en vez de `trigger_event` síncrono, y el canal `webhook` del despachador entrega con `db/webhooks.py::entregar_firmado`, la misma salida que `trigger_event` —con fila en `webhook_deliveries`, `X-Webhook-Delivery` y reintento C2.4, que el outbox no tenía—. El despachador corre además **a demanda** (job `despacho_eventos` de la cola de ADR-028, `services.jobs.solicitar_despacho_de_eventos`) y está en el registry (`event_dispatch`, plano `pipeline`); `release_channel` reabre el evento para que dos pasadas concurrentes no pierdan un canal fallido. **Quedan con el patrón** (escribir el evento del catálogo con `append_domain_event(conn=…)` en la transacción del cambio y borrar la escritura directa): `scheduler/watchlist_rules_alerts.py` (campana y digest de reglas; el webhook ya sale por `watchlist_rule.matched`), `scheduler/watchlist_alerts.py` (digests de la watchlist legada y el último `trigger_event`, `watchlist_match`, fuera del catálogo), `services/deadline_reminders.py` (→ `renovacion.en_ventana` y un tipo nuevo para vencimientos) y `services/pursuit_awards.py` (→ `adjudicacion.detectada`). Y sin emitir todavía: `pursuit.created`/`state_changed`/`decided`, que el catálogo manda también al canal `cache` —una invalidación **global** por cada cambio de una oportunidad privada—; quitar ese canal antes de emitirlos.
- **Riesgo:** medio — toca el camino de escritura de pursuits y de reglas.

### [P2] [Ola 1 · S7] Frontend: las tres deudas que dejó a medias el plan de septiembre, más formularios, flags e inspectores
- **Área:** web/src/app, web/eslint.config.mjs
- **Problema:** S5.1 (prefetch en servidor con hidratación), S5.2 (partir las páginas monolito) y S5.9 (grupo de rutas `(privado)`) quedaron sin entregar cuando tres agentes murieron por límite de sesión, y dos de ellas se revirtieron a conciencia (§8 del plan anterior). A eso sumaba el §1 del plan v2, medido el 2026-09-05: doce ficheros de `web/src/app` por encima de 300 líneas, ninguna librería de formularios en las seis pantallas con validación, feature flags que se administran en `/ops` y **ninguna vista lee**, e inspectores de Radar y Detalle que solo existen desde `xl`.
- **Acceptance criteria:** los de S7.1–S7.4 del plan v2, y los de S5.1/S5.2/S5.9 del plan de septiembre tal cual para el primero. La allowlist inicial de `max-lines` son esos doce ficheros y solo puede encoger.
- **Estado:** lo dice el §5 del plan cuando el stream se cierra, no este ítem — ver la nota de cabecera. S7 se está entregando en esta misma ola.
- **Files de partida:** [docs/plans/2026-09-plan-arquitectura-v2.md](plans/2026-09-plan-arquitectura-v2.md) (§5, S7 y la tabla de los doce ficheros en §1)
- **Relación:** S7.1 es la vía por la que avanza el P1 de cobertura de las páginas del frontend: la lógica sale a `_hooks/` testeables en vez de testear el árbol entero.
- **Riesgo:** medio en S7.1 (routing y datos iniciales), como ya dijo el plan anterior.

### [P2] [Ola 1 · S8] Documentos: solo se leen PDF con texto y texto plano
- **Área:** scraper/document_fetcher.py, shared/object_store.py, .github/workflows/pliegos.yml, services/ml/model_artifacts.py
- **Problema (diagnóstico del §1 del plan v2, medido el 2026-09-05):** `_SUPPORTED_CONTENT_TYPES` admitía dos content-types, así que un pliego en DOCX, ODT o dentro de un ZIP no se procesaba y un PDF escaneado terminaba en error por no haber OCR; y el binario se descartaba tras extraer, de modo que reprocesar exigía volver a PLACSP, cuyas URIs llevan un token que caduca. Es el techo real de la ficha del pliego: lo que no se puede leer no existe para el producto.
- **Acceptance criteria:** los de S8.1–S8.4 del plan v2, sin redefinirlos aquí. Los cuatro son independientes y se entregan por separado; S8.1 y S8.2 llevan migración y dependencias nuevas, ambas pre-autorizadas por D20.
- **Estado:** lo dice el §5 del plan cuando el stream se cierra, no este ítem — ver la nota de cabecera. S8 se está entregando en esta misma ola.
- **Files de partida:** [docs/plans/2026-09-plan-arquitectura-v2.md](plans/2026-09-plan-arquitectura-v2.md) (§5, S8), [scraper/document_fetcher.py](../scraper/document_fetcher.py)
- **Relación:** S8.4 roza el P3 «Un solo transporte para bajar assets de la Release» (cerrado el 2026-09-18): los dos tocan cómo se resuelve un artefacto de modelo, y conviene decidirlos juntos.
- **Riesgo:** medio — el coste del OCR por página se mide en el primer run nocturno y lo acota el tope de páginas.
- **Progreso 2026-09-28:** el soporte de DOCX existía pero no se usaba en la mayoría de casos: PLACSP manda el tipo mal escrito (`…openxmlformatsofficedocument…`, sin guion) y 1.964 documentos acabaron en `unsupported`, el mayor agujero de cobertura medido. El formato lo decide ahora la firma del contenido (`_resolver_content_type`). Las filas ya marcadas no se recuperan solas: `unsupported` no vuelve a `list_pendientes`, así que hace falta reencolarlas (dato de producción, OK del mantenedor).
- **Progreso 2026-10-23 (tanda paralela, agente H):**
  - **OpenDocument sin `odfpy`.** ODT, ODS y ODP se leen de `content.xml` con `zipfile` + `expat` (`_extract_odf_paginas`), con encabezados (`text:h`, que `odfpy` perdía), filas de tabla como una línea y sin el texto borrado del control de cambios. Un `content.xml` con `DOCTYPE` se rechaza antes de expandir entidades (`defusedxml` no es dependencia de producción). Al no depender de ningún extra, el ODT ya se lee también en la imagen de la API. `odfpy` queda sin uso en el extra `[pliegos]` de `pyproject.toml`: retirarlo es un cambio de dependencias (§6) y se deja para quien lo apruebe.
  - **ZIP endurecido.** Tope por entrada (`_ZIP_MAX_BYTES_POR_ENTRADA`) además del total, ratio de compresión (`_ZIP_RATIO_MAX`, comprobado por bloques), rutas con `..`/absolutas/de unidad y restos de macOS ignorados, nombres UTF-8 sin bandera recuperados, ODT/ODS/ODP dentro del ZIP, y cada entrada abre su primera página con `── nombre ──`. Sigue sin recursión. Tests en `tests/test_unit_document_fetcher_odf_zip.py` (zip bomb y path traversal construidos en memoria).
  - **Reencolado.** `make reencolar-documentos` (sin `APLICAR=1` solo cuenta) devuelve a `pending` las filas `unsupported` —y las `error` con «content-type no soportado:» de cuando aún no existía ese estado— cuyo tipo ya se lee, comparando sin guiones para recoger el DOCX mal escrito de PLACSP. Medido el 2026-10-23 por el MCP de solo lectura: ~2.140 DOCX (1.007 `unsupported` + 1.131 `error`), 48 ODT, 2 ODS y 215 ZIP. **Pendiente, propietario:** ejecutarlo contra producción ([runbooks/documentos-reencolar.md](runbooks/documentos-reencolar.md)). XLSX (337), XML (349), HTML (237), RTF, `.doc` y RAR siguen sin leerse y no se tocan.
  - **OCR de escaneados: fuera de esta tanda.** S8.3 dejó `ocrmypdf` en el runner de `pliegos.yml`, pero el coste por página sigue sin medir (su propia aceptación), y sin ese número no se amplía: los 54 PDF «sin texto extraíble» en `error` no entran en el reencolado.
- **Progreso 2026-10-25 (escaneados con estado propio y backend Supabase Storage):**
  - **`sin_texto`** (`v161`, aditiva sobre el `CHECK` de `documentos.status`): un PDF sin capa de texto que el OCR no lee lanza `PdfSinTextoError` y la fila queda `sin_texto` (con `content_type` y huella de la descarga), no `error`. La migración pasa a `sin_texto` las filas `error` con «PDF sin texto extraíble» (~54 en producción). La detección exige letras, no solo una cadena no vacía: la paginación estampada o la puntuación de un escaneo no cuentan como texto. Un ZIP cuyos únicos legibles son escaneados también es `sin_texto`. La ficha bajo demanda lo dice («PDF escaneado sin capa de texto, este servidor no pudo aplicarle OCR») en vez de «descargas fallidas, los enlaces caducan»; `status_counts`, `formato_counts`, `/analytics/quality` (`documentos_por_formato[].sin_texto`) y el informe nocturno lo cuentan aparte; la UI lo rotula en Documentos y en el asistente.
  - **Almacén:** `shared/object_store.py` gana `SupabaseStorageObjectStore` (API REST de Supabase Storage sobre `shared/outbound_http`, sin SDK nuevo, host del proyecto como única entrada de la allowlist). La configuración pasa a `config/settings_object_store.py` (recoge el `.env`; el entorno del proceso sigue ganando). Tests sin red de los dos backends HTTP en `tests/test_unit_object_store_supabase.py`.
  - **Pendiente:** OCR real fuera del runner de `pliegos.yml` (la imagen de la API no trae `ocrmypdf`/tesseract; añadirlo es decisión de despliegue y dependencia de sistema, no de `requirements`). Con OCR disponible, las filas `sin_texto` con `blob_key` se re-extraen con `reextract_from_blob` sin volver a PLACSP; falta un comando que las recorra (gemelo de `make reencolar-documentos`). Aplicar `v161` en producción.

---

### [P2] Inventariar las claves de API sin dueño: 89 activas, sin usuario y sin caducidad
- **Área:** api/routes, db/repositories, web/src/app/(dashboard)/ops
- **Problema:** medido en producción el 2026-10-09: `api_keys` tiene 101 filas, 89 activas, **todas con `user_id` nulo y sin `expires_at`**, y ninguna creada en los últimos 30 días. No hay pantalla que las liste: Ajustes › Claves de API enseña las de quien mira, y la tarjeta que había en Ops › Administración (retirada ese día) también listaba solo las propias, rotuladas como «de la instancia». Una clave sin dueño no se revoca al desactivar a nadie, así que no hay ningún camino por el que estas dejen de valer.
- **Acceptance criteria:**
  - Se sabe qué son (restos de pruebas, integraciones vivas o claves de antes de que tuvieran dueño) y se revocan las que no tengan uso.
  - Ruta de administración tipada que lista las claves de la instancia (nombre, tier, permisos, dueño, creada, caduca) sin exponer hash ni token, y una tarjeta en Ops › Administración que la lee y permite revocar con confirmación.
  - Una clave nueva no puede nacer sin dueño ni sin caducidad.
- **Files de partida:** [api/routes/me.py](../api/routes/me.py), [services/auth.py](../services/auth.py), [web/src/app/(dashboard)/ops/_components/administracion-view.tsx](../web/src/app/(dashboard)/ops/_components/administracion-view.tsx)
- **Riesgo:** medio — revocar una clave que sí usa una integración la rompe; primero el inventario.
- **Progreso (2026-10-25, código):** `create_api_key` exige `user_id` en cualquier entorno y siempre fija `expires_at` (90 días por defecto, 365 como máximo). `ApiKeyRepository.create()`, que insertaba sin dueño ni caducidad, se eliminó; `insert()` exige los dos. `seed_dev.py` y el fuzzer dejaron de emitir claves sin dueño, y los tests usan `tests/claves.py`. Nuevas `GET /admin/api-keys` (todas las claves de la instancia sin hash ni token, con recuento de activas, sin dueño y sin caducidad) y `DELETE /admin/api-keys/{id}` (auditada con el `user_id` del actor), y una tarjeta en Ops › Administración que las lee y revoca con confirmación (CU-20). El inventario por el MCP no fue posible porque `api_keys` está excluida, pero desde el 2026-07-27 la validación ya rechaza en producción las claves sin dueño (`unbound_api_key_rejected`), así que las 89 no deberían autenticar (deducido del código, no medido). **Pendiente del propietario:** revisar el último uso en la tarjeta y revocarlas, y aprobar la migración `CHECK (is_active = 0 OR (user_id IS NOT NULL AND expires_at IS NOT NULL)) NOT VALID`, con `VALIDATE` tras la revocación. Los tests de integración nuevos (`tests/test_admin_api_keys_route.py`) y los 27 adaptados a una clave con dueño están sin ejecutar: falta correrlos contra Postgres.

### [P2] Confirmar que Sentry captura en el backend de producción (acción del propietario)
- **Área:** Render (variables de `tenderflow-api` y `tenderflow-worker`), observability/sentry.py
- **Problema:** `sentry-sdk` entró en los lockfiles el 2026-10-11; hasta entonces el módulo existía pero no enviaba nada. Que capture depende de una variable que el repo no ve: `SENTRY_DSN` en el panel de Render.
- **Acceptance criteria:**
  - `SENTRY_DSN` definida en `tenderflow-api` (y en `tenderflow-worker`) con el DSN de un proyecto de backend, no el del frontend.
  - Tras el siguiente despliegue el log dice `sentry_configured` y no `sentry_sdk_missing`, y un error provocado aparece en Sentry sin query string, cookies ni cabeceras fuera de `host`, `user-agent` y `referer`.
- **Files de partida:** [observability/sentry.py](../observability/sentry.py), [render.yaml](../render.yaml)
- **Riesgo:** bajo.

### [P2] La auditoría de conceder y revocar acceso puede no escribirse, y la revocación no guarda quién la hizo
- **Área:** db/audit.py, db/access_grants.py, api/routes/admin_solicitudes.py
- **Problema:** `access_grant.granted` y `access_grant.revoked` se escriben con `db.audit.log_event` **después** de confirmar la transacción de la concesión, y `log_event`/`log_action` son best-effort por diseño en todo el producto: un fallo se queda en el log (`audit_log_persist_failed`) y no llega a quien llama. Puede existir, por tanto, una concesión —o una revocación— sin su fila de auditoría. De la concesión queda al menos `access_grants.granted_by`; de la revocación no queda nada más: la tabla guarda `revoked_at` pero no quién, así que el audit log es el único sitio donde consta. No se arregló al cerrar los huecos del RFC 242 (2026-10-09) porque hacerlo solo aquí deja dos semánticas de auditoría en el producto, y hacerlo para todo es un cambio de `db/audit.py` con alcance propio.
- **Relacionado:** ese día las tres llamadas de `api/routes/admin_solicitudes.py` empezaron a pasar `user_id`. `api/routes/admin_users.py` y `api/routes/feature_flags.py` siguen llamando a `log_event` sin él, así que sus filas quedan con `audit_log.user_id` NULL pese a lo que dice `docs/SECURITY.md` («el actor se guarda como `users.id`»).
- **Acceptance criteria:**
  - Decidido y escrito (ADR) para qué eventos la auditoría es condición de la operación —candidatos: control de acceso y administración de usuarios— y para cuáles sigue siendo best-effort.
  - Para los primeros, la fila de `audit_log` va en la misma transacción que la escritura que audita, o la operación falla si no se puede auditar. La cadena de hashes sigue verificando (`scripts/verify_audit_chain.py`).
  - `access_grants` guarda quién revocó (columna nueva: migración, AGENTS.md §6).
  - Test: con la escritura de auditoría fallando, conceder no deja una concesión activa sin rastro.
  - Las rutas de administración que auditan pasan `user_id`.
- **Files de partida:** [db/audit.py](../db/audit.py), [db/access_grants.py](../db/access_grants.py), [api/routes/admin_solicitudes.py](../api/routes/admin_solicitudes.py), [docs/rfc/242-acceso-oauth-dinamico.md](rfc/242-acceso-oauth-dinamico.md)
- **Riesgo:** medio — `log_action` serializa la cadena con un advisory lock global: meterlo en transacciones ajenas cambia quién espera a quién.

### [P3] Las violaciones de CSP se guardan y nadie las lee
- **Área:** api/routes/security.py, web/src/app/(dashboard)/ops
- **Problema:** `csp_violations` recibió 14 informes en siete días (todos `frame-src`, a 2026-10-09) y no tiene ruta de lectura. Los errores de JavaScript del navegador, que se guardan al lado, sí la tienen y desde ese día se ven en Ops › Estado.
- **Acceptance criteria:**
  - Ruta de administración tipada con las violaciones agrupadas por directiva y origen.
  - Panel en Ops › Estado junto a «Errores en el navegador».
- **Files de partida:** [api/routes/security.py](../api/routes/security.py), [web/src/app/(dashboard)/ops/_components/observabilidad/errores-navegador-card.tsx](../web/src/app/(dashboard)/ops/_components/observabilidad/errores-navegador-card.tsx)
- **Riesgo:** bajo.

### [P2] Encender las fuentes nuevas: contratos menores, plataformas agregadas y TACRC completo
- **Área:** scraper/connectors/placsp_menores.py, scraper/connectors/placsp_agregadas.py, scraper/connectors/tacrc.py, [runbooks/fuentes-opcionales.md](runbooks/fuentes-opcionales.md)
- **Problema:** los tres conectores están escritos y apagados (decisión del 2026-10-12, que revisa D16), pero ninguna URL se pudo verificar: el proxy de la sesión que los escribió denegaba PLACSP y Hacienda. Las fixtures de las sindicaciones 1143 y 1044 son sintéticas, y la URL de la biblioteca del TACRC (API REST de SharePoint) es una candidata.
- **Acceptance criteria:**
  - `--check --dump` de cada conector contra la URL real, y fixtures sustituidas por un recorte real.
  - **Antes de encender menores:** decidir su identidad. `placsp_menores:<ContractFolderID>` sigue la convención de PLACSP, pero en menores es más probable que dos órganos repitan número de expediente y se pisen.
  - Decidido si la analítica de competidores sin filtro de tecnología debe contar los menores.
  - Variables en `vars.` según el runbook; las tres fuentes en `ok` en el healthcheck.
- **Riesgo:** medio — volumen nuevo en `adjudicaciones` y `empresas`.
- **Nota 2026-10-24 (verificación contra las fuentes reales):** las URL de 1143 y 1044 responden GET 200 con ATOM CODICE (`--check` da 13 de 498 y 25 de 283 admitidas) y las fixtures son ya recortes reales. **Menores:** identidad decidida: `placsp_menores:<ID_PLATAFORMA>:<ContractFolderID>`. En 9.977 entradas, 327 de 9.563 expedientes los compartían órganos distintos (390 filas pisadas con la clave vieja, 3,9 %); no había filas que migrar porque nunca se encendió. Las adjudicaciones con NIF enmascarado no se guardan. **Agregadas:** ninguno de sus 1.057 pliegos apunta a PLACSP (544 `contractaciopublica.cat`, 346 `contratacion.euskadi.eus`, 167 `contratos-publicos.comunidad.madrid`); el filtro sigue ahora la allowlist de descargas. **TACRC:** la API REST candidata no existe (302 a `pagenotfound`, que `fetch_index` ahora rechaza) y el buscador exige Cloudflare Turnstile: no hay índice completo anónimo; queda el Pleno (19 resoluciones) o pedir a Hacienda un listado abierto. El mismo defecto de identidad está en el feed principal: ver el P1 «La identidad de PLACSP no incluye el órgano». Quedan:
  - Del dueño: si se guardan los 12 adjudicatarios persona física con NIF y nombre visibles (de 241 admitidos; registro de tratamientos), si `DOCUMENT_ALLOWED_HOSTS` se amplía a `contratacion.euskadi.eus` y `contratos-publicos.comunidad.madrid`, y `make medir-solape` contra producción.
  - Los `test_integration_*` de `tests/test_connectors_placsp_sindicaciones.py`, con Postgres.
  - Analítica de competidores: excluir los menores por defecto (mediana 4.950 € en la muestra) en `AdjudicacionRepository.load_for_competitors` y las consultas de UTE, y ofrecerlos como vista aparte.
- **Nota 2026-10-23 (tanda paralela):** no se encienden en esta tanda: dependen de `make medir-solape` contra producción (D16, D42 del plan de salida al mercado). El comando existe y funciona: se ejecutó en local contra una base migrada a head (vacía, así que solo prueba el camino). Contra producción lo ejecuta el propietario con un `DATABASE_URL` de lectura (`make medir-solape`, o `python scripts/medir_solape_agregados.py --json`); el script solo usa el pool de lectura (`default_transaction_read_only=on`). El número se anota aquí antes de decidir.

### [P2] Medir la cobertura de las condiciones oficiales de CODICE y verificar sus nombres
- **Área:** scraper/codice_parser.py (`parse_condiciones`), scripts/medir_terminos_codice.py
- **Progreso (2026-10-26, V2):** la reingesta del histórico se hace junto con la fase B de identidad: [runbook](runbooks/reingesta-unica-placsp.md) y `scripts/verificar_reingesta.py`. No por `scrape-bulk.yml`. Ver [plan 2026-10](plans/2026-10-plan-foco-piloto.md) §8.
- **Problema:** criterios, garantías y solvencia se leen de `cac:TenderingTerms` desde v148, pero no se pudo medir sobre el feed real (proxy denegado). Los nombres de criterio coinciden con un parser público independiente; los de garantía y solvencia salen del esquema CODICE/UBL sin verificar, y se asume que `AmountRate` viene en porcentaje. Un nombre que no case da dato ausente, no falso.
- **Acceptance criteria:**
  - `scripts/medir_terminos_codice.py --vivo --paginas 2 --guardar muestra/` ejecutado; porcentaje por bloque y nivel anotado aquí con fecha.
  - Nombres y escala corregidos si la muestra los desmiente; `parser_field_null_total` de las tres familias revisado en producción.
  - Decidido si se rellena el histórico (solo con los ZIP mensuales: la fase de adjudicación deja de publicar el bloque).
- **Medido el 2026-10-24** (`scripts/medir_terminos_codice.py`, que ahora lee también ZIP mensuales y desglosa por estado): ocho páginas del ATOM vivo (3.903 entradas) y el ZIP de 2026-09 (95.910). Bloque presente en cualquier nivel, ATOM / ZIP: criterios 94,2 / 88,4 %, garantías 53,4 / 54,0 %, solvencia técnica 67,2 / 64,5 %, económica 66,5 / 64,1 %, clasificación 6,0 / 6,5 %. Garantías y clasificación solo vienen en el expediente; en el lote, criterios en el 6,9 % y solvencia en un 3 %. Producción, filas extraídas desde el 2026-10-15: 93,3 % criterios, 47,1 % garantías y 67,0 % solvencia sobre 5.565 licitaciones de PLACSP, coherente con el feed.
  - **Nombres:** existen todos los que asume el parser salvo uno. PLACSP no publica `ThresholdAmount`: el umbral va en `cbc:ThresholdQuantity`, sin moneda, y producción tenía **0 de 4.069** requisitos económicos con `umbral_importe`. Arreglado solo para la solvencia económica (`_umbral_de_solvencia`; un 0 queda NULL); en la técnica esa cantidad mezcla importes y número de trabajos y no se lee (guardarla pediría una columna nueva). `AmountRate` va en porcentaje (mediana 5; 14 de 59.114 valores < 1). `SpecificTendererRequirement` son declaraciones responsables y se dejan fuera a propósito.
  - **El supuesto del tercer criterio es falso:** las fases ADJ y RES siguen publicando el bloque (criterios en el 79 % y el 82,5 % del ZIP). Rellenar el histórico —y con él los 4.069 umbrales a NULL— es viable re-ingiriendo los ZIP mensuales; **queda la decisión del dueño**, por el coste (más de 2 h por mes con `scrape-bulk.yml`).
  - Sin revisar `parser_field_null_total` (métrica de Prometheus sin acceso desde la sesión); se contaron las filas en BD en su lugar.
  - Vistos y sin arreglar: `fecha_publicacion` es el `updated` completo cuando no hay `ValidNoticeInfo` (caso golden 24); adjudicaciones y garantías a 0 se guardan como 0; el NUTS `ES` da `provincia` «España»; lotes que repiten el presupuesto del expediente entero (caso 20), que afecta a la baja por lote.
  - **Arreglados el 2026-10-25** tres de los «vistos y sin arreglar»: sin `ValidNoticeInfo`, `fecha_publicacion` es el día del `updated` (`to_iso_date`, el mismo formato que el `IssueDate`) y no el timestamp entero (caso golden 24); un 0 en importe adjudicado, pagable, oferta mínima y máxima, y en el porcentaje y el importe de una garantía, queda NULL (`_importe_informado`, el criterio de `_umbral_de_solvencia`; presupuesto y valor estimado no se tocan; caso 15); con NUTS de nivel país (`ES`) `provincia` queda NULL en vez de «España» (`shared.geo.es_nuts_de_pais`; caso 09). El golden solo cambia en esos campos; tests en `tests/test_unit_codice_parser_no_informado.py`. Las filas de producción se corrigen al reingerir cada expediente (la reingesta pisa `provincia`, reescribe adjudicaciones y garantías y se queda con la fecha más temprana); ningún consumidor dependía del 0. Dos cosas vistas al hacerlo: los NUTS de nivel 1 y 2 siguen dando una región o una CCAA como provincia (el caso 17 publica `ES70` con «Canarias»), y `db/repositories/reproceso_lotes.py::asignar_lotes` compara el importe con `IS NOT DISTINCT FROM`, así que un reproceso futuro sobre filas que en BD aún tienen 0 no las casaría con el `None` que parsea ahora. Sigue abierto el caso 20, que es decisión de modelado.
- **Riesgo:** bajo — solo lectura y parser.

### [P2] Fijar la convención de la API pública antes de más consumidores: idioma, errores y una sola paginación
- **Área:** api/routes/*, api/errors.py, shared/dto.py, docs/api-design.md, .github/workflows/release-sdk.yml
- **Problema:** la API tiene claves para terceros (CU-14) y un SDK Python que `release-sdk.yml` genera del OpenAPI, así que la superficie es contrato. Medido el 2026-10-17 sobre `docs/STATUS.md`: 297 operaciones con la nomenclatura mezclada en la misma versión —`/pursuits`, `/organizations`, `/follows`, `/saved-filters`, `/feature-flags` junto a `/cuentas`, `/etiquetas`, `/licitaciones`, `/publico`, `/resoluciones`—; dos paginaciones para el mismo recurso (`GET /licitaciones` por offset y `GET /licitaciones/cursor`, cuyo RFC del 2026-09-06 lo llama «sucesor»); y 307 `HTTPException(...)` con cadenas sueltas en `api/routes/` frente a 16 handlers en `api/errors.py`, de modo que el cliente generado no tiene una forma de error estable que parsear. Cada consumidor externo nuevo hace más caro arreglarlo.
- **Acceptance criteria:**
  - RFC en `docs/rfc/` (es contrato público: política de §5 de AGENTS.md) que decida (a) el idioma de los paths para `/api/v1` y si los renombres se hacen con alias y `Deprecation`/`Sunset` o esperan a `/api/v2`; (b) un único envelope de error (propuesta: RFC 9457 `application/problem+json`, con `type` estable por condición) emitido por `api/errors.py` para todo `HTTPException`; (c) la fecha de retirada de la paginación por offset de `/licitaciones`.
  - Un ratchet (conteo de `HTTPException(` en `api/routes/` con cadena literal) que solo baja, y la tabla de códigos de error en `docs/api-design.md` generada desde `api/errors.py`.
  - El SDK publicado tras la RFC tipa el error una sola vez.
- **Files de partida:** [api/errors.py](../api/errors.py), [api/routes/licitaciones/listado.py](../api/routes/licitaciones/listado.py), [docs/api-design.md](api-design.md), [docs/STATUS.md](STATUS.md)
- **Riesgo:** alto — breaking para los consumidores de la API; por eso nace como RFC y con periodo de alias, no como PR directo.
- **Progreso (2026-10-25, rama `agente/convencion-api-publica`) — la parte compatible, hecha:** convención escrita en `docs/api-design.md` («Convención de la API»): español en paths y campos nuevos sin renombrar lo existente en `/api/v1`; un solo error, `ProblemDetail` (RFC 9457, `application/problem+json`), y una sola paginación, `limit`/`offset` con `Pagina[T]` (11 de las 13 operaciones que paginaban ya eran offset). `shared/dto/errores.py` trae `ProblemDetail`/`Error`/`ErrorDeValidacion` y `shared/dto/paginacion.py` el alias `Pagina` (mismo componente OpenAPI, nada se rompe). `api/errors.py::documentar_errores`, enganchado a `app.openapi()`, declara el error en todas las operaciones (422, 4xx declarados y `default`) en vez del `HTTPValidationError` de FastAPI que la API nunca emitía: el cliente generado ya tipa el error una vez. Ratchet nuevo `scripts/check_api_convencion.py` (`make check-api-convencion`, test `tests/test_unit_ratchet_api_convencion.py`): paginación fuera de `Pagina[T]`, errores con otro esquema y `JSONResponse` de error a mano en `api/` fallan; 11 salidas heredadas congeladas con motivo. Migradas a `Pagina[T]` en código: `GET /publico/licitaciones`, `GET /adjudicaciones`, `GET /licitaciones`, `POST /licitaciones/search`. El MCP no consume la API por HTTP (llama a `services/` y `db/`), así que no había rutas suyas que migrar.
  - **Queda (pide RFC, es incompatible):** las 10 paginaciones congeladas (`/empresas`, `/pursuits`, `/pursuits/{id}/comments`, `/radar/proximas`, `/notifications/alerts`, `/competitive/empresas/{id}/adjudicaciones`, `/competitive/renovaciones`, `/publico/sitemap/entradas` y los dos cursores) y el `503` de `/health/ready`; los renombres de idioma y la convivencia offset/cursor de `/licitaciones`; un `type` estable por condición (hoy uno por código HTTP salvo `query-timeout` y `reauthentication-required`) y la tabla de códigos generada desde `api/errors.py`. No se añadió el ratchet de `HTTPException(` con cadena literal: con la convención escrita, `HTTPException` es la forma sancionada de lanzar un error (el manejador único lo formatea), y contarlo solo tiene sentido cuando exista el catálogo de `type`.

### [P2] Desbloquear los pines que acumulan deuda: FastAPI, suelo de Python y las dos fuentes de dependencias
- **Área:** requirements.in, requirements-api.in, pyproject.toml, renovate.json, scripts/gen_status.py, scripts/check_api_surface.py, tests que recorren `app.routes`
- **Progreso (2026-10-26, rama `agente/plan-arquitectura-2026-10`):** hecho en código — fastapi 0.146 / starlette 1.9 / uvicorn 0.54 sin tope, `api/rutas.py` lee la superficie anclada en `app.openapi()`, Python ≥ 3.13 y `pyproject.toml` lee `requirements.in`; sin `faiss`. Falta que CI confirme E2E, fuzz y Docker. Detalle en [plan 2026-10](plans/2026-10-plan-foco-piloto.md) §8.
- **Problema:** tres topes de versión llevan meses y cada semana que pasa su salto es más grande. (1) `fastapi<0.137` (y con él `starlette<1.4`, `uvicorn<0.47`) desde el 2026-08-17 porque desde 0.141 los routers montados aparecen en `app.routes` como `_IncludedRouter` opacos; lo que depende de esa introspección es acotado —`scripts/gen_status.py`, `scripts/check_api_surface.py` y 10 ficheros de tests— y todo ello puede leerse de `app.openapi()`, que es estable. (2) `requires-python >=3.11`, `ruff target-version py311` y `mypy python_version 3.11`, mientras producción corre `python:3.13` (`.python-version`, `Dockerfile.api`, CI): ningún módulo puede usar sintaxis de 3.12+ y mypy comprueba contra un intérprete que no se despliega. (3) `pyproject.toml` declara `dependencies` a mano y no coincide con `requirements.in` (no lista httpx, email-validator, statsmodels, uvicorn, starlette, pypdf en el mismo rango, mcp…): dos fuentes de verdad que `check_requirements_sync.py` no compara. Además `faiss`, retirado en julio, sigue en los `overrides` de mypy, en los `skips` de bandit y en el README.
- **Acceptance criteria:**
  - `gen_status.py`, `check_api_surface.py` y los tests que recorren `app.routes` leen de `app.openapi()`; `superficie_congelada.txt` sigue dando 297; el tope de fastapi/starlette/uvicorn sube en `requirements*.in` y en `renovate.json`, con el job E2E en verde contra la versión nueva.
  - `requires-python >=3.13` (o >=3.12 con el motivo escrito), `target-version`/`python_version` alineados, y la matriz de CI deja de probar 3.12 en el `schedule` si el suelo sube.
  - `pyproject.dependencies` se genera o se verifica contra `requirements.in` (ampliar `check_requirements_sync.py`), y los restos de `faiss` desaparecen de `pyproject.toml` y del README.
- **Files de partida:** [requirements.in](../requirements.in), [pyproject.toml](../pyproject.toml), [renovate.json](../renovate.json), [scripts/gen_status.py](../scripts/gen_status.py), [scripts/check_requirements_sync.py](../scripts/check_requirements_sync.py)
- **Riesgo:** medio — el salto de FastAPI toca todas las rutas; mitigado por el gate de arranque del job E2E y el fuzz de Schemathesis, que es justo lo que detectó la rotura en agosto.

### [P2] La telemetría de producto: medir el uso por espacio antes de la siguiente ola
- **Área:** web/src/lib/analytics.ts, web/src/components/layout/*, web/src/hooks/*, docs/UX_AUDIT.md
- **Problema:** `web/src/lib/analytics.ts` nació en agosto para responder «qué se usa, qué se abandona y qué se puede retirar» con un catálogo de eventos categóricos y reglas de privacidad; medido el 2026-10-17 solo hay dos llamadas a `track()` fuera del propio módulo y las dos están en la superficie pública (solicitar acceso y su resultado). Dentro del producto —15 espacios, 297 operaciones, 30 casos de uso— sigue sin medirse nada, así que las decisiones de retirar o fusionar superficies (como la del 2026-10-12, que absorbió Empresas y unificó el asistente) se toman sin dato de uso. El punto 0 de AGENTS.md pide comprobar que una superficie nueva hace falta; sin esta medida no se puede comprobar que una existente sobra.
- **Corrección (2026-10-23):** la medición del 2026-10-17 contó `track()`, que solo se llama dentro de `web/src/lib/analytics.ts`; los emisores del producto pasan por `registrarEvento()`. Auditado ese día: los **23** eventos del catálogo `EventosProducto` tienen al menos un emisor, en unos 30 ficheros (`espacio_abierto` sale del rail, del conmutador de `space-shell.tsx` y de cuatro piezas de pantalla). `web/src/lib/__tests__/analytics-emisores.test.ts` falla si un evento del catálogo se queda sin `registrarEvento("<evento>"` (con una lista de excepciones justificadas, hoy vacía) o si se emite uno fuera del catálogo. Queda abierto lo que necesita datos: la tabla de 30 días y el inventario de la API.
- **Progreso (2026-10-25) — la herramienta está; los datos, pendientes de exportar.** `scripts/inventario_uso.py` (`make inventario-uso`, solo stdlib, `tests/test_unit_inventario_uso.py`) produce las dos tablas: espacios y vistas desde un CSV exportado de Vercel Analytics (catálogo leído de `console-spaces.ts` y `space-views.ts`, % y marca bajo el 2 %, claves fuera de catálogo señaladas) y operaciones sin llamadas desde `increase(http_requests_total[30d])` (consulta en vivo, respuesta guardada de Prometheus o volcado de `/metrics`), contra la línea base más las `NUEVAS`. Ninguna fuente se puede leer sin credenciales: Vercel Analytics no tiene lectura desde el repo, `tenderflow-prometheus` es un `pserv` privado y el `/metrics` de producción exige `metrics:read`. Por eso `docs/UX_AUDIT.md` («Uso por espacio y por vista») tiene la tabla con «pendiente de exportar» y los pasos exactos para el propietario (incluido comprobar antes que el plan de Vercel conserva los eventos personalizados), y `api/superficie_congelada.txt` dice dónde irán las candidatas. **Falta (propietario):** exportar los dos conjuntos, pegar las tablas y escribir la decisión de cada fila bajo el umbral.
- **Acceptance criteria:**
  - ~~Un evento por espacio al entrar (dimensión `espacio`, y `vista` cuando la haya) y los eventos de acción que el catálogo ya define, emitidos desde el marco de la consola, no desde cada pantalla; ninguna propiedad fuera de `PROPIEDADES_PERMITIDAS` (test).~~ Hecho (ver la corrección de arriba).
  - Tras 30 días, una tabla en `docs/UX_AUDIT.md` con sesiones por espacio y por vista, y una decisión escrita por cada espacio o vista con menos del 2 % de uso: se queda, se fusiona o se retira.
  - La misma pregunta para la API: `pursuits/metrics` o `admin/ejecuciones` ya existen; falta el inventario de operaciones sin ninguna llamada en 30 días (`http_requests_total` por handler ya está en Prometheus), y la lista va a `superficie_congelada.txt` como candidatas a encoger.
- **Files de partida:** [web/src/lib/analytics.ts](../web/src/lib/analytics.ts), [web/src/components/layout/console-rail.tsx](../web/src/components/layout/console-rail.tsx), [web/src/lib/console-spaces.ts](../web/src/lib/console-spaces.ts), [api/superficie_congelada.txt](../api/superficie_congelada.txt)
- **Hallazgo (2026-10-25):** los eventos personalizados de Vercel Web Analytics exigen plan Pro y el proyecto `tenderflow` está en Hobby: la API de eventos responde `402 payment_required`. **Los 23 eventos del catálogo se emiten pero no se guardan en ningún sitio.** Lo que sí hay son pageviews por ruta, y con eso está hecha la primera tabla real (30 días) en [UX_AUDIT.md](UX_AUDIT.md#uso-real-por-ruta-pageviews-de-vercel-2026-09-25-a-2026-10-25). Decisión pendiente del dueño: pagar Pro, mandar los eventos a otro destino (la propia API ya tiene `http_requests_total` por handler) o conformarse con pageviews.
- **Riesgo:** bajo — telemetría categórica sin identificadores; el filtro del módulo ya la acota.

## P3 — Nice to have

### [P3] Referencias a documentos desde Galicia, Euskadi y TACRC
- **Área:** scraper/connectors/{tacrc,regional_rss,galicia,euskadi}.py, db/resoluciones.py, config/settings.py
- **Problema:** solo PLACSP, TED y PSCP emitían referencias a documentos; las otras tres fuentes registradas no aportaban ningún adjunto.
- **Progreso 2026-10-23 (tanda paralela, agente H):**
  - **TACRC — hecho en código.** El PDF de cada resolución **vinculada** a una licitación entra en `documentos` como adjunto `additional` de esa licitación (`scraper.connectors.tacrc.registrar_documentos`, tras `link_unlinked`), con `source_hash = tacrc-<número>` y upsert idempotente; `www.hacienda.gob.es` pasa a `dominios_documentos` y a `DOCUMENT_ALLOWED_HOSTS`, con su propio circuito en `scraper/resilience.py`. Efecto hoy: **cero**, porque en producción hay 19 resoluciones y ninguna vinculada (MCP, 2026-10-23); crece cuando se encienda el índice completo (ítem «Encender las fuentes nuevas») y la vinculación encuentre expedientes.
  - **Galicia y Euskadi — no se emiten, a propósito.** Lo que su conector descarga es solo el RSS, y sus `item` traen título, enlace a la ficha, `pubDate` y una descripción en prosa (estado, órgano, tipo, importe, fechas) sin ningún enlace a pliegos ni anexos: no hay nada que emitir sin inventarlo. Los documentos están en la ficha HTML de cada licitación, que el conector no pide. Para traerlos haría falta una petición por ficha, revisar antes su `robots.txt` (el de PLACSP es `Disallow: /`, y por eso no se lee la suya) y una fixture real: la sesión del 2026-10-23 no tenía salida a `contratosdegalicia.gal` ni a `euskadi.eus`.
- **Pendiente:** (1) si Render fija `DOCUMENT_ALLOWED_HOSTS` a mano, añadir `www.hacienda.gob.es` (acción del propietario; `.env.example` no se tocó, §6); (2) Galicia/Euskadi: `--dump` del RSS real para confirmar que no hay enlaces y decidir si merece la pena pedir la ficha.
- **Riesgo:** bajo — volumen mínimo y fail-open por licitación.

### [P3] Pasar las fechas de `text` a `timestamptz`
- **Área:** db/ (esquema), todo lector de fechas
- **Problema:** 132 columnas de fecha son `text` (frente a 35 `timestamptz` y 2 `date`), así que cada comparación y cada orden en SQL o en Python depende de que todos los escritores usen exactamente `now_utc_iso()`. Cuando uno no lo hizo (los `DEFAULT now()` y los `NOW()::text` escritos a mano), el fallo fue silencioso: «desde tu última visita» perdía los pliegos del mismo día. La migración de 2026-10-17 arregla el formato y un test impide nuevos `text DEFAULT now()`, pero el tipo sigue sin proteger nada.
- **Acceptance criteria:**
  - Inventario de las columnas por tabla y de quién las lee como cadena (slicing `[:10]`, comparaciones de texto, serialización a JSON).
  - Migración por tabla, empezando por las que entran en diffs y órdenes (`documentos`, `licitaciones_history`, `pursuit_events`, `user_notifications`), con la suite verde entre cada una.
- **Files de partida:** [docs/database-schema.md](database-schema.md), [db/connection.py](../db/connection.py) (`now_utc_iso`), [tests/test_v151_fechas_texto_iso_migration.py](../tests/test_v151_fechas_texto_iso_migration.py)
- **Riesgo:** alto — cambia el tipo que devuelve psycopg (de `str` a `datetime`) en cientos de lecturas; requiere RFC por ser cambio de persistencia.
- **Progreso 2026-10-25 — fase 1 en código (rama `agente/fechas-timestamptz`), sin aplicar en producción.** Inventario medido con el MCP de solo lectura: 132 columnas de fecha `text` en 74 tablas; las calientes ya no admiten un formato único —`licitaciones.fecha_extraccion` y `primera_extraccion` mezclan `…T…+00:00` (86 964 filas) con `… …+00` y `… …` sin zona (~2 000), y `fecha_inicio`/`fecha_adjudicacion` traen años `0021`/`0019`—. Hecho, **aditivo y reversible**:
  - `v161_fechas_ts_sombra`: `<columna>_ts timestamptz` junto a 14 fechas — `licitaciones` (`fecha_extraccion`, `primera_extraccion`, `fecha_inicio`, `fecha_fin`, `fecha_actualizacion_fuente`; las otras dos ya tenían sombra desde `v133`), `adjudicaciones.fecha_adjudicacion`, `licitaciones_history.captured_at`, `documentos` (`created_at`, `fetched_at`, `updated_at`), `pursuit_events.created_at` y `user_notifications` (`created_at`, `read_at`). Solo catálogo con `lock_timeout`. Conversión única: `nucleo_iso_a_timestamptz` y su gemela `db.nucleo_tipado.a_timestamptz`.
  - Escritura: dual en `db/upsert.py` para `licitaciones` (pregunta al catálogo por chunk, como `v133`); trigger `BEFORE INSERT OR UPDATE OF <texto>` en las otras cinco tablas, cuyos escritores están repartidos (y así cubre los `DEFAULT`). `pursuit_events` y `user_notifications` se rellenan en la migración; el resto, `scripts/backfill_fechas_ts.py` (por lotes de PK, idempotente, reanudable con `--tabla/--desde`, `--verificar` cuenta divergencias y «no ISO» por columna). Registro único en `db/fechas_ts.py`.
  - `v160_fechas_ts_indices`: `idx_lic_fecha_extraccion_ts` `CONCURRENTLY`, tras el backfill. Es el único índice que una lectura necesita (`MAX(fecha_extraccion_ts)`); los demás se replican cuando una lectura los pida.
  - Lectura dual detrás de `FECHAS_TS_LECTURA` (apagado; con él apagado el SQL es el de siempre): `db.sql_fragments.instante_sql` → `COALESCE(<col>_ts, nucleo_iso_a_timestamptz(<col>))` en «desde tu última visita» (historial, documentos, oportunidades), el orden del historial, el de las alertas y `get_last_extraction_date`. Lo proyectado sigue siendo texto: ningún DTO cambia en esta fase.
  - Tests: `tests/test_unit_fechas_ts.py` (formatos de producción, corpus golden CODICE, forma de migraciones, upsert, backfill, script, lectura dual) y `tests/test_fechas_ts_pg.py` (paridad SQL/Python, triggers, escritura dual, backfill idempotente, orden por instante) — este último **no ejecutado** en la sesión que lo escribió (sin Postgres).
  - Runbook: [runbooks/fechas-ts-ventana.md](runbooks/fechas-ts-ventana.md).
- **Pendiente (fase 1, producción):** `v159` por `migrate.yml` → despliegue → backfill → `--verificar` en cero → `v160` → `FECHAS_TS_LECTURA=true`. Luego, mover más lectores a `instante_sql` (p. ej. `fetch_recent` del SSE, agregados por `fecha_adjudicacion`) y repetir la receta con las tablas restantes del inventario.
- **Fase 2 (corte, NO hecho):** con todos los lectores de una tabla ya en la sombra y su verificación en cero (incluidos los `*_no_iso` revisados a mano), en una revisión nueva por tabla: (1) los escritores dejan de escribir el texto y la API proyecta la sombra serializada en ISO (cambio de tipo en psycopg: `str` → `datetime`, revisar slicing `[:10]` y comparaciones de texto en Python); (2) `DROP` de triggers y columna de texto y `RENAME <col>_ts TO <col>` (solo catálogo, con `lock_timeout`), reconstruyendo antes con `CONCURRENTLY` los índices que hoy viven sobre el texto (`idx_lic_fecha_extraccion`, `idx_adj_fecha`, `idx_hist_externo`, `idx_documentos_status_created`); (3) RFC previo por ser cambio de persistencia irreversible (§5). La clave canónica (`periodo_publicacion_sql`, `v92/v101/v102`) sigue leyendo `fecha_publicacion`/`fecha_extraccion` en texto hasta que esa fase la mueva explícitamente.

### [P2] [Investigador] La búsqueda por significado no corre en producción: decidir si se sirve
- **Área:** services/investigador/search_engine.py, services/embeddings.py, requirements-api.in, docker/Dockerfile.api
- **Problema:** `hybrid_search` exige `sentence-transformers` para codificar la consulta y la imagen de la API no lo instala a propósito (C3.1: PyTorch pesa ~2 GB). Medido el 2026-10-09: `POST /search/semantic` responde siempre `fts` o `like`, y los 345.422 fragmentos embebidos de `documento_chunks` (2,2 GB de los 6,9 GB de la base; el HNSW, 637 MB) no los consulta ninguna ruta por vector. Desde esa fecha la pantalla ya no lo promete —«Tipo de coincidencia» solo aparece si una respuesta llega por `rrf`— y la búsqueda por texto mira dentro de los pliegos, pero la decisión sigue pendiente.
- **Acceptance criteria:**
  - Decisión tomada entre codificar la consulta en la API sin PyTorch (el mismo `paraphrase-multilingual-MiniLM-L12-v2` en ONNX; es una dependencia nueva, §6), o dejar de embeber los pliegos y soltar el índice.
  - Si se sirve: `source=rrf` en el log `semantic_search.ok` de producción, y el MRR del golden set (`tests/eval/test_eval_rag.py`) medido antes y después.
- **Files de partida:** [services/investigador/search_engine.py](../services/investigador/search_engine.py), [services/embeddings.py](../services/embeddings.py), [requirements-api.in](../requirements-api.in)
- **Riesgo:** medio — dependencia nueva y memoria del proceso de la API.
- **Progreso (2026-10-17, rama `claude/quirky-wozniak-xp20q0`):** lo que la fusión haría al encenderse ya no empeora la pantalla. Hasta esa fecha, con embeddings la ruta respondía **solo** con la fusión: sin `coincide_en`, pasaje, resaltados ni `fecha_limite`, ignorando «las más recientes» y, en la lista vectorial, las comillas y la `-exclusión`. Ahora completa la lista del texto (`services/investigador/busqueda.py::combinar`): primero lo que casa con todos los términos, después lo que solo se parece por significado (`coincide_en=["significado"]`, con su fragmento), y al final lo parcial. No corre con operadores, con «recientes» ni con `alpha=0`. La decisión de servirla sigue pendiente.
- **Progreso (2026-10-23) — decidido servirla con ONNX; código listo, falta el modelo en la imagen.** El propietario autorizó `onnxruntime` + `tokenizers` en `requirements-api.in` (~100 MB instalados frente a ~2 GB de PyTorch; `click` sube a 8.5.0 por `huggingface_hub`). `services/embeddings_onnx.py` reproduce la cuenta de sentence-transformers (truncado a 128 con los especiales dentro, mean pooling por máscara, L2) y `services/embeddings.py` elige motor: sentence-transformers si está, si no ONNX cuando `EMBEDDINGS_ONNX_DIR` (`config/settings_embeddings.py`) apunta a un modelo cuyo `origen.json` coincide con `EMBEDDING_MODEL`; un fallo de carga lo apaga hasta reiniciar. `hybrid_search` ya consultaba los fragmentos de `documento_chunks` por vector: con el motor ONNX, `/search/semantic` fusiona (`rrf`) y `/ask` con `RAG_HYBRID_ENABLED` también. `docker/Dockerfile.api` descarga el modelo con `scripts/descargar_modelo_embeddings.py` (commit fijo, sha256 obligatorio por fichero) y solo define `EMBEDDINGS_ONNX_DIR` si lo descargó. Tests: `tests/test_unit_embeddings_onnx.py` (sesión falsa + tokenizador real en memoria), `tests/test_unit_descargar_modelo_embeddings.py` y `tests/test_embeddings_onnx_paridad.py` (coseno ≥ 0,999 frente a sentence-transformers). Corpus al vuelo **no**: la afinidad del Radar (~1.600 candidatas por carga), el ranking de fragmentos del RAG (≤ 120) y el embebido de pliegos del worker de la API siguen gateados por sentence-transformers (`embeddings_masivos_disponibles`): con ONNX en un vCPU serían decenas de segundos por petición, estimado por FLOPs, sin medir. Similares y predecesor (≤ 100 títulos) sí lo usan. **Falta:**
  - **Propietario:** el commit del repo de Hugging Face y los tres sha256 (`EMBEDDINGS_ONNX_REVISION`, `EMBEDDINGS_ONNX_SHA256_{MODELO,TOKENIZADOR,CONFIG}`) como variables de `tenderflow-api` en Render — desde la sesión que lo implementó Hugging Face no era accesible (proxy 403) y no se inventaron; pasos en `docs/runbooks/model-rollback.md` § «Modelo ONNX de embeddings».
  - El test de paridad no se ha ejecutado nunca (sin modelo ni red a Hugging Face): correrlo con el modelo descargado antes de desplegar.
  - Tras el deploy: `source=rrf` en `semantic_search.ok`, MRR de `tests/eval/test_eval_rag.py` antes/después, RSS de la API tras la primera búsqueda (~470 MB esperados) y latencia de la primera búsqueda (carga perezosa del modelo) y de los similares de la ficha.
  - Para que el Radar puntúe por significado en la API hace falta **persistir** el embedding de cada licitación (columna o tabla `vector(384)` + backfill en el pipeline; migración, §6) y leerlo en `score_affinity_batch`, no calcularlo al vuelo.
- **Progreso (2026-10-25, rama `agente/busqueda-semantica-servida`) — se sirve detrás de una flag, con los valores del modelo verificados.** Por qué seguía sin correr: la imagen de la API se construía sin modelo, porque `tenderflow-api` no declara en Render `EMBEDDINGS_ONNX_REVISION` ni los tres sha256; sin revisión el build no descarga nada, `EMBEDDINGS_ONNX_DIR` queda vacía y `hybrid_search` devuelve `[]`. Hecho:
  - Valores verificados desde la API de Hugging Face (commit `e8f8c211…`, sha256 de `model.onnx`, `tokenizer.json` y `sentence_bert_config.json`), aceptados por `scripts/descargar_modelo_embeddings.py`, y **paridad medida contra producción**: los vectores ONNX de tres fragmentos de `documento_chunks` coinciden con los guardados por sentence-transformers (coseno 1,00000, `md5` del texto cotejado). Tabla y pasos en `docs/runbooks/model-rollback.md` § «Modelo ONNX de embeddings». El test de paridad local (`tests/test_embeddings_onnx_paridad.py`) sigue sin ejecutarse: no hay PyTorch en esa máquina.
  - Flag `busqueda_semantica` (`db/feature_flags.py`), **apagada por defecto**: `services/investigador/busqueda.py::semantica_activa` la lee por usuario (fail-closed) y `buscar(..., semantica=)` solo intenta la fusión con ella. `FLAGS_DECLARADAS` hace que `GET /feature-flags` la liste aunque no tenga fila, para encenderla desde Administración sin SQL.
  - Degradación limpia: sin motor de embeddings, sin pgvector o fragmentos, o si la fusión lanza, la respuesta es la del texto (antes, un fallo al completar la lista con lo que trajo la fusión —abrir la conexión, `anuncios_por_id`— salía como 503). El log `semantic_search.ok` lleva `semantica` (`apagada`, `no_aplica`, `sin_motor`, `sin_aporte`, `error`, `servida`) y `fusion_ms`. Tests: `tests/test_search_semantic_ruta.py` (`TestFlagYDegradacion`, `TestSemanticaActiva`), `tests/test_search_semantic_hybrid.py` y `tests/test_feature_flags_route.py`.
  - Presupuesto de latencia en `docs/sli-slo.md` § 8 (`fusion_ms` P95 ≤ 1,5 s; respuesta P95 ≤ 2,5 s; `error` < 1 %), con lo medido: codificar P95 21 ms en local, consulta HNSW 0,9–1,6 s por el MCP.
  - La pantalla ya decía qué modo respondió: la insignia de `source` (`rrf` = «Por significado y texto», `fts` = «Por texto»), así que el DTO no cambia.
  - **Falta (propietario):** las cuatro variables en `tenderflow-api` (Render) y un deploy con caché limpia; encender la flag; después, `source=rrf` en `semantic_search.ok`, MRR antes/después, RSS y `fusion_ms` real contra el presupuesto. Con eso se cierra.

### [P3] [Investigador] El historial de consultas sigue en `localStorage`
- **Área:** web/src/app/(dashboard)/investigador/_hooks/use-ajustes.ts
- **Problema:** las consultas recientes viven en el navegador (`docs/frontend-data-invariants.md`, anti-patrón 3): no viajan a otro dispositivo. `saved_filters` no sirve tal cual —guarda instantáneas del ámbito que las demás pantallas restauran—, así que hace falta una tabla propia, es decir, una migración (§6).
- **Acceptance criteria:**
  - Las consultas recientes se guardan por usuario en servidor y `localStorage` queda como caché.
  - El término no llega a la telemetría de producto (sigue siendo «la estrategia comercial de quien lo escribe»).
- **Files de partida:** [web/src/app/(dashboard)/investigador/_hooks/use-ajustes.ts](<../web/src/app/(dashboard)/investigador/_hooks/use-ajustes.ts>)
- **Riesgo:** bajo.
- **Nota (2026-10-25):** no se hizo junto con la búsqueda por significado: la tabla nueva es una migración en `db/alembic/`, que pide OK del propietario (AGENTS.md §6).

### [P3] [Rendimiento 2026-09] Flecos de la rama de rendimiento
- **Área:** web/bundle-budget.json, .env.example (OK humano), varios
- **Problema:** lo que la rama no pudo cerrar por falta de build, de permiso o de alcance:
  - Los techos de `web/bundle-budget.json` no se han bajado: sin `next build` no se midió. Estimado: −200 a −570 KB sin comprimir según la ruta (/resumen la que más). **Parcial (2026-10-09, issue #428):** las tres rutas de `hub-paginado/` y `/cuentas/[id]` ya tienen techo y el de `/login` se bajó a lo medido; los de las demás rutas siguen sin bajar (holgura medida ese día: 13–36 % en el dashboard salvo `/investigador`, 3,7 %; ~8 % en la superficie pública; 9 % en `/restablecer-contrasena`).
  - El paso «Bundle analyzer report» de `ci.yml` no genera nada (comprobado el 2026-10-09): `@next/bundle-analyzer` no es compatible con las builds de Turbopack, `ANALYZE=true next build` lo avisa y no escribe `.next/analyze/`, y el artefacto se sube vacío sin fallar. El desglose por módulo sale de `next experimental-analyze -o` (`.next/diagnostics/analyze/`). Cambiar el paso pide OK (workflow); el docstring de `scripts/check_bundle_budget.py` y el comentario de `web/next.config.ts` siguen recomendando el plugin, y este último dice que el control lee `app-build-manifest.json` cuando lee `diagnostics/route-bundle-stats.json`.
  - `.env.example` no declara `RATE_LIMIT_BACKEND=auto` (sigue diciendo `sqlite`), `DB_POOL_MIN_SIZE`, `DB_READ_POOL_MIN_SIZE`, `API_ANALYTICS_STATEMENT_TIMEOUT_MS` ni `UVICORN_LIMIT_CONCURRENCY` (tocar `.env*` pide OK; por eso `render.yaml` tampoco declara la última: `check_env_parity` exige que todo lo de `render.yaml` esté en `.env.example`).
  - Siguen con E/S síncrona en handlers `async`: `_check_budget` de `api/routes/ask.py` (presupuesto LLM en Redis).
  - La imagen Open Graph de la ficha pública (`opengraph-image.tsx`) sigue dinámica.
  - El scoring de /detalle no manda `organization_id` y puntúa con los pesos de la organización personal; las renovaciones filtran tecnología por igualdad (`IN`) y `tecnologia_detalle_*` sigue con `unnest`.
  - Si se activa `NUCLEO_TIPADO_LECTURA`, el listado por cursor pierde `idx_lic_cursor` (v134 solo crea índices simples).
- **Acceptance criteria:** cada viñeta cerrada o convertida en su propio ítem; `python scripts/check_bundle_budget.py --update` tras el primer build de la rama mergeada.
- **Riesgo:** bajo.

### [P3] Descartar los avisos fantasma de Dependabot (manifest `uv.lock` inexistente)
- **Área:** GitHub Security (acción del usuario), .github/dependabot.yml
- **Problema:** 37 de los 38 avisos abiertos apuntan a un `uv.lock` que se borró de `master` en `cc096fb` (2026-05-31). El grafo de dependencias de GitHub conservó una instantánea de ese fichero y **sigue emitiendo avisos nuevos contra ella** — los abiertos van del 2026-07-13 al 2026-08-07, todos posteriores al borrado. La prueba está en el SBOM, que lista a la vez los pines vivos y sus fantasmas (`pillow@12.3.0` ×2 junto a `pillow@12.2.0`; `cryptography@50.0.0` ×2 junto a `46.0.7`), y en el trío del 2026-08-03 sobre `GHSA-g6cj-pr64-35w5`: #82 y #83 (manifiestos vivos) se cerraron el mismo día; #87 (`uv.lock`) sigue abierto y no puede cerrarse nunca.
- **Cómo triar (corregido 2026-08-30):** **no** basta con filtrar por `manifest_path`, y sobre todo no debe convertirse en una regla de auto-descarte. GitHub atribuye mal ese campo: los tres avisos de `cryptography` (#87–#89) salen etiquetados como `uv.lock` pese a que ese paquete **nunca** estuvo en ese fichero. Una regla que descarte por `manifest_path: uv.lock` acabaría tapando en silencio un aviso real de `requirements.txt`. El criterio que sí decide es el pin vivo: comparar `first_patched_version` contra `requirements.txt` / `requirements-dev.txt` / `web/package-lock.json`, aviso por aviso.
- **Acceptance criteria:** los 37 descartados con motivo (`not_used` los 18 de GitPython, que no está en ningún manifiesto; `inaccurate` el resto, cuyo pin vivo ya está parcheado); el listado refleja solo manifiestos reales. La cura de fondo —que el grafo deje de ver `uv.lock`— exige forzar un re-parse del path o abrir ticket a GitHub Support; el toggle del dependency graph no existe en repos públicos.
- **Progreso (2026-09-24):** el 2026-08-30 se descartaron 33 con el criterio de arriba (17 `inaccurate`, 16 `not_used`). El fantasma **sigue emitiendo**: desde entonces han llegado 8 más, todos contra `uv.lock` y ninguno con pin vivo vulnerable — #113 y #114 (`anyio` < 4.14.2: los cuatro `requirements*.txt` fijan 4.14.2), #108–#112 (`GitPython` ≤ 3.1.58: no está en ningún manifiesto) y #105 (`transformers` < 5.10.0: sin pin, entra por los extras `ml`/`ml-embeddings`; la última ejecución de `pliegos.yml` resolvió 5.17.0 y el código no llama a `save_pretrained`). Descartar a mano es un goteo sin fin: el ítem no se cierra hasta aplicar la cura de fondo.
- **Files de partida:** [.github/dependabot.yml](../.github/dependabot.yml)
- **Riesgo:** bajo — no toca código; el cuidado está en verificar cada aviso contra el pin vivo en vez de contra el nombre del manifiesto.

### [P3] Los dos módulos-dios: `aggregates.py` y `settings.py`
- **Nota:** este ítem estaba **duplicado**. Había una segunda entrada, "Partir los dos módulos-dios: `aggregates.py` y `settings.py`", sobre los mismos dos ficheros y con criterios que se contradecían: una decía "no big-bang, solo dejar de crecer" y la otra "partir por dominio". Fusionados el 2026-08-18 (mismo patrón que la fusión de los `title=` el 2026-08-10). El criterio que sobrevive es el gradual, que es el que el repo ha demostrado que sí ejecuta.
- **Área:** db/repositories/aggregates.py, config/settings.py
- **Problema:** `db/repositories/aggregates.py` son 1.327 líneas y 55 funciones en una sola clase que concentra toda la analítica; `config/settings.py` son 946 líneas con 26 validadores en una clase plana que mezcla ejes ortogonales (BD, ML, LLM, auth, scraper, observabilidad) que ya están conceptualmente separados por `APP_PROFILE`. Son los dos ficheros que todo el mundo tiene que tocar, y donde se concentran los conflictos de merge. (`shared/dto.py`, en contraste, está sano: 620 líneas / 45 clases.)
- **Acceptance criteria:**
  - Una agregación o setting **nuevo** va a un módulo hermano (`aggregates_<área>.py` / settings por dominio) en vez de sumar al monolito.
  - Al tocar un bloque cohesivo existente **por otro motivo**, se evalúa extraerlo en el mismo cambio. El destino de `AggregateRepository` es partido por dominio (overview / geografía / competidores) y el de `Settings` submodelos anidados por eje preservando los nombres de variables de entorno — pero **llegando por partes, con la suite verde entre cada una**, no en un big-bang.
- **Progreso 2026-09-18 (rama worktree-agent-acad4a43a2c0f0bae):** primer módulo hermano de settings, `config/settings_resumen.py` (`ResumenPregenSettings`, de la que hereda `Settings`: mismos nombres de variable de entorno y mismo acceso `settings.X`). Es el patrón para los siguientes settings nuevos. En `aggregates.py` no hubo agregación nueva que mover.
- *Estado (2026-09-19) — las cifras del problema están caducadas y la regla «no crecer» no se ha cumplido:* `db/repositories/aggregates.py` tiene hoy **1.980 líneas** (eran 1.327) y `AggregateRepository` **60 métodos** (eran 55); `config/settings.py`, **1.422 líneas** (eran 946) y **27 validadores**. `shared/dto.py` ya no es el contraejemplo sano: **1.904 líneas y 83 clases** (eran 620 / 45). Medido con `wc -l` y `grep` sobre el árbol.
- *Progreso 2026-10-17 (rama `claude/nifty-turing-axm5xg`):* la misma regla aplicada a los dos módulos de oportunidades, que ya eran los más grandes después de `shared/dto.py` y `aggregates.py`. `services/pursuits.py` (2.308 → 1.758 líneas): las piezas de la agenda salen a `services/pursuits_agenda.py`; `get_agenda` y las señales de reglas se quedan porque reciben `user_key` y el ratchet no deja que un fichero nuevo herede esa deuda. `api/routes/pursuits.py` (2.112 → 1.646): las rutas de organizaciones salen a `api/routes/organizations.py`, con el OpenAPI idéntico (comparado antes y después). Siguen pendientes los dos de este ítem, `aggregates.py` (2.457) y `shared/dto.py` (2.482).
- *Progreso 2026-10-25:* `shared/dto.py` es ya el paquete `shared/dto/` (14 submódulos; ver el cerrado «Partir `shared/dto.py`…» en el archivo). Queda `aggregates.py`.
- *Plan de partición (2026-10-25, sin ejecutar — no cabía con calidad en el PR que bajó los ratchets):* medido hoy, `aggregates.py` 2.489 líneas y `config/settings.py` 1.711.
  - **`db/repositories/aggregates.py` → paquete `db/repositories/aggregates/`** con `__init__.py` que reexporta `AggregateRepository`, `LicitacionesFilters`, `build_licitaciones_where`, `ParaHoy` y los privados que importa la suite, para no tocar importadores. Submódulos por familia de métodos (cada uno una clase mixin; `AggregateRepository` hereda de todas): `filtros.py` (`LicitacionesFilters`, `build_licitaciones_where`, `_in_clause`, `_lectura`), `overview.py` (`overview_*`, `importe_p75`, `count_total_activas`, `_para_hoy*`), `resumen.py` (`resumen_*`), `tecnologias.py` (`tecnologias_*`, `tecnologia_detalle_*`), `geografia_tendencias.py` (`geography_*`, `trends_*`, `vencimientos_*`), `organos.py` (`_organos_where`, `organos_*`), `proyectos.py` (`proyectos_*`, `_where_modulos`, `tipos_contrato_breakdown`, `tipo_estado_crosstab`, `cpv_top_por_count`, `codigos_codelist`), `calidad_forecast.py` (`quality_*`, `forecast_monthly`, `publicaciones_mensuales`, `retendering_universe`, `adjudicaciones_para_forecast`, `clustering_universe`) y `scoring.py` (`_scoring_cols`, `importe_percentiles*`, `competencia_ofertas_por_cpv4`, `scoring_candidates`, `licitaciones_by_ids`, `tech_signal_by_ids`, `pipeline_window`, `licitaciones_por_organo`). Riesgos a vigilar: `tests/test_dedup_guardrail.py` escanea por ruta (añadir los submódulos a `_SCANNED_FILES` en el mismo cambio) y los `patch("db.repositories.aggregates.connect_read")` de la suite, que hay que redirigir al submódulo que ejecuta.
  - **`config/settings.py`**: seguir el patrón de `config/settings_resumen.py` — un `BaseSettings` mixin por eje (`settings_bd.py`, `settings_ml.py`, `settings_llm.py`, `settings_auth.py`, `settings_scraper.py`, `settings_observabilidad.py`) del que hereda `Settings`, con los validadores de cada eje dentro de su mixin. Mismos nombres de variable y mismo `settings.X`; el gate es `tests/test_config_settings.py` y `scripts/check_env_parity.py`.
- **Files de partida:** [db/repositories/aggregates.py](../db/repositories/aggregates.py), [config/settings.py](../config/settings.py)
- **Riesgo:** bajo si se hace oportunista; medio si alguien intenta el big-bang.

### [P3] Migrar la resolución de identidad de `competitors.py` a SQL (union-find + unaccent)
- **Área:** services/analytics/competitors.py, db/repositories/adjudicaciones.py
- **Problema:** Tras mover `overview.py`/`tecnologias.py` a agregación SQL (commit `ab520da`), `competitors.py` quedó híbrido a propósito: sus filtros (fecha/tecnologia/estado/importe_min) ya se empujan a SQL, pero la resolución de identidad de empresa (`_prepare_company_identity`/`_connected_identity_keys`, un connected-components/union-find sobre 5 tokens de identidad por fila) sigue en pandas. Migrarla a SQL necesita `normalize_company`/`normalize_nif` en el motor (NFKD accent-fold + 12+ alternativas regex de sufijo legal), lo que requiere la extensión `unaccent` de Postgres — no habilitada hoy (solo `pg_trgm`/`vector` lo están), y habilitarla exige una migración Alembic (fuera de alcance sin OK humano, AGENTS.md §6).
- **Acceptance criteria:**
  - Extensión `unaccent` habilitada (migración Alembic, requiere confirmación humana).
  - Connected-components de identidad expresado como CTE recursiva en `db/repositories/adjudicaciones.py` (o módulo hermano), con paridad de resultado verificada contra los 17 tests existentes de `tests/test_analytics_competitors.py` (casos: grupo Deloitte curado, joins solo-por-NIF, exclusión de NIF placeholder).
  - `_apply_filters` (red de seguridad redundante añadida en la migración parcial) puede retirarse si el filtrado SQL cubre todos los casos que cubría.
- **Files de partida:** [services/analytics/competitors.py](../services/analytics/competitors.py), [services/normalization.py](../services/normalization.py), [db/repositories/adjudicaciones.py](../db/repositories/adjudicaciones.py), [tests/test_analytics_competitors.py](../tests/test_analytics_competitors.py)
- **Riesgo:** medio — toca una migración de schema (gate humano) y una query recursiva no trivial; mitigado por los 17 tests de caracterización ya existentes.
- **Progreso 2026-09-18 (rama `worktree-agent-af7ab85116eea30b4`) — parcial, el interruptor sigue apagado.** El «Problema» de arriba está desfasado en dos cosas que el código ya desmentía: `unaccent` **sí** está habilitada (`v87_unaccent_extension`, no hace falta otra revisión y no se creó ninguna) y el SQL de la CTE recursiva ya existía sin cablear en `db/repositories/competitor_identity.py`, con su test de paridad por capas. Los tests de `tests/test_analytics_competitors.py` son **15**, no 17. Lo hecho ahora: `resolve_identity_for_rows` reparte **las mismas filas** que ya cargó `load_for_competitors` (con su `LIMIT`), y `services/analytics/competitors.py` la usa cuando `settings.COMPETITORS_IDENTITY_SQL` está activo — **por defecto `False`**, así que el camino de pandas sigue siendo el de producción. La paridad contra los 15 tests se mide reejecutando cada uno con el interruptor encendido (`tests/test_analytics_competitors_identity_sql.py`, capa 5), **no ejecutada**: no hay Postgres en la máquina que la escribió. Falta para cerrar: (1) esa capa en verde en CI; (2) `identity_graph_stats` medido en producción (el cierre de la CTE es cuadrático en el tamaño del componente); (3) encender el interruptor y, tras un ciclo, retirar el union-find de pandas y `_apply_filters`. Aviso para (3): la etiqueta del grupo pasa de raíz del union-find a `MIN(token)`, y es lo que `services/competitive/socios.py` expone como `empresa_key`.

### [P3] F5: Refactor de repositories por olas (TID251 whitelist decreciente)
- **Área:** services/, scheduler/, api/routes/, scraper/, scripts/
- **Problema:** El ratchet TID251 tiene una whitelist que solo puede decrecer (conteo vigente: [STATUS.md](STATUS.md), generado por `make status`). **Destino fijado por [ADR-022](adr/ADR-022-frontera-de-persistencia.md)**: el SQL se mueve a `db/`, y `db/repositories/*` (clases) y `db/*.py` (funciones de módulo) son el mismo estrato — o sea que **no hay renombrado de por medio**, cada archivo va al módulo `db/` de su tabla en la forma que ya tenga. Antes de ADR-022 este ítem no tenía estado final declarado, que era el motivo real de que llevara meses parado: refactorizar hacia un destino indefinido produce un idioma más, no menos.
- **Baseline (medido 2026-07-30 sobre `pyproject.toml`):** services/ 18 · scheduler/ 9 · scripts/ 5 · api/ 4 · scraper/ 2 = **38 archivos** en whitelist, más los dos globs estructurales que no son deuda (`db/**` y `tests/*`, exentos por diseño). El "= 44 entradas" del baseline anterior no cuadraba con el desglose (que ya sumaba 40 contando los globs); la cifra de referencia es la de STATUS.md, que cuenta archivos.
- **Progreso 2026-08-10 — primera ola, 38 → 36:** `services/job_locks.py` entero pasa a `db/job_locks.py` (aprovechando que había que corregir su `release()`, que borraba locks ajenos) y el `SELECT 1` de `services/health.py` pasa a `db.connection.ping()`. El ratchet llevaba meses sin moverse; la lección de esta ola es que sale barato cuando se hace **al pasar por el módulo por otro motivo**, no como pasada dedicada.
- **Progreso 2026-08-18 — 34 → 32:** `services/licitaciones.py` y `services/ml/retencion_labels.py` salen de la whitelist; su SQL pasa a `db/repositories/licitaciones.py` y `db/repositories/adjudicaciones.py`, con tests de caracterización escritos **antes** de mover. El listado de renovaciones también se movió a `db/repositories/renovaciones.py` (ítem de `/renovaciones`, ver Cerrados), pero su entrada del ratchet **no se puede quitar todavía** porque los agregados hermanos (`resumen_renovaciones`/`totales_renovaciones`) siguen en `services/`.
- **Corrección de conteo:** la cifra "38 → 36" de la ola anterior nunca cuadró con [STATUS.md](STATUS.md), que el 2026-08-13 ya contaba **34**. La cifra buena es siempre la de STATUS.md, que se genera con `make status`; anotar el conteo a mano en este fichero solo produce dos números que se contradicen.
- **Dos efectos colaterales que esta migración tiene y nadie había registrado** (descubiertos el 2026-08-18 al ejecutar la ola):
  1. **Erosiona el guardrail de dedupe.** `tests/test_dedup_guardrail.py` escaneaba solo `services/`; mover SQL analítico a `db/` lo sacaba de su radio en silencio. Ya está corregido (el escáner tiene ahora una lista explícita de módulos de `db/`), pero **cada ola futura debe añadir a `_SCANNED_FILES` el módulo de `db/` que crea**, en el mismo cambio. Lo que destapó al ampliarlo es un ítem P1 propio.
  2. **Tienta a invertir las capas.** Al mover una query se mueven con ella los fragmentos SQL que interpola, y el reflejo es importarlos de `services/` — que ADR-024 prohíbe (`db/` no depende de `services/`). El destino correcto es `db/sql_fragments.py`, creado el 2026-08-18 con `FECHA_FIN_SQL`, `TECHNOLOGY_OBSERVED_SQL` y `exclude_duplicados_sql`; `services/` los reexporta.
- **Progreso 2026-09-24 — 26 → 25:** `services/ml/scoring.py` sale. El upsert de retención, duplicado en las ramas de modelo y de baseline, y la baja real por expediente (`_baja_real`) pasan a `db/repositories/predicciones.py` (`guardar_retencion`, `baja_real_de_expediente`); la división sigue en services. `db/repositories/predicciones.py` entra en `_SCANNED_FILES` del guardrail de dedupe en el mismo cambio, con sus dos purgas como exentas por diseño.
- **Progreso 2026-09-16 — 28 → 26:** `scheduler/kpi_precompute.py` pasa a `db/kpi_precompute.py` (no a `db/repositories/kpi_snapshots.py`, que es de las métricas `ov_*` y advierte que no se mezclen) y `services/competitive/mercado.py` pasa a `db/repositories/mercado.py`, con el `WHERE` construido por `alcance_sql` en vez de interpolación suelta — el candidato «aparte» de más abajo queda cerrado. Equivalencia verificada con un arnés que compara SQL y parámetros contra `HEAD`; `db/repositories/mercado.py` entra en `_SCANNED_FILES` del guardrail de dedupe en el mismo cambio.
- **Progreso 2026-10-25 — 18 → 12** (rama `agente/ratchets-y-modulos-dios`; `MAX_ENTRADAS_WHITELIST = 12`). Salen seis, todos con su SQL en `db/`: `services/resoluciones.py` (vinculación en `db/resoluciones.py::vincular_pendientes`, con el emparejamiento por expediente + órgano como función pura en el servicio, y el listado en `listar_resoluciones`), `services/deadline_reminders.py` (tres métodos nuevos de `WatchlistRepository`; el barrido de usuarios entra en `_LEGITIMATE_SWEEPS` de `tests/test_user_key_sql_isolation.py` porque es la misma consulta que ya corría inline), `services/competitive/renovaciones.py` (los dos agregados a `db/repositories/renovaciones.py`, que ya estaba en `_SCANNED_FILES` del guardrail de dedupe y los dos llevan `exclude_duplicados_sql`; los umbrales de «caliente» se quedan en el servicio y entran como parámetros), `scheduler/competitor_alerts.py` (→ `db/watchlist_empresas.py::nuevas_adjudicaciones_de_empresa`), `scheduler/retention.py` (la purga con sus savepoints → `db/retention.py::purgar_por_fecha`; la política publicada se queda) y `scripts/rotate_api_keys.py` (→ `ApiKeyRepository.expirar_por_nombre`).
- Siguientes candidatos por coste: `services/entity_resolution.py` (1 `connect`, pero solo abre la transacción del lote y el SQL ya está en `db/empresas.py`: hay que mover el bucle entero o pasar la transacción por un callback), `services/analytics/scoring_signals.py` (1; sus dos agregados de baja no llevan `exclude_duplicados_sql` y al bajar a un módulo escaneado necesitarían decisión sobre el guardrail), `services/competitive/bajas.py` (2), `scheduler/aggregates_precompute.py` (2).
- **~~Candidato aparte~~ — hecho el 2026-09-16 (ver progreso arriba).** `services/competitive/mercado.py` concentraba ~12 de los ~30 `# noqa: S608` del repo (conteo del 2026-08-18). Cada supresión está justificada una por una y el idioma de fragmentos constantes está documentado en `services/sql_fragments.py`, así que no es un bug — pero es la mayor densidad de SQL interpolado del proyecto en un solo fichero, y cada filtro nuevo que se añade ahí es otra oportunidad de que un valor entre por concatenación sin que nadie lo note. Al moverlo a `db/`, hacerlo con un builder de `WHERE` testeado en lugar de arrastrar la interpolación tal cual (patrón de `tests/test_adjudicaciones_dedupe_sql.py`, que verifica que los `%s` siguen cuadrando con los parámetros).
- **Orden de olas:** services/ → api/ → scheduler/ → scripts/ (por densidad; `services/` es además el único que viola la capa de dominio de ADR-007)
- **Excepción declarada:** `services/sql_fragments.py` se queda — expone fragmentos SQL constantes pero no ejecuta nada (ADR-022 §3).
- **Acceptance criteria por ola:**
  - `make check` verde tras cada ola.
  - `ruff check --select TID251 --statistics .` monotónamente decreciente (anotar conteo en cada PR).
  - Tests de caracterización donde falten.
  - Estado final: whitelist vacía (`db/**` no la necesita: importar `connect` desde dentro de `db/` está permitido).
- **Files de partida:** `pyproject.toml` (whitelist TID251), `db/repositories/`
- **Riesgo:** medio — toca caminos de datos; mitigado por ratchet como gate y tests de caracterización previos a cada movimiento.


### [P2] Aislamiento de la suite: una base por sesión en vez de un schema por test

- **Área:** tests/conftest.py
- **Problema:** Cada uno de los 157 ficheros de test con BD crea un schema completo (~50 tablas + índices), cierra el pool y abre uno nuevo (TCP + handshake TLS) y luego hace `DROP SCHEMA CASCADE`. El cacheo del DDL entre workers ya está hecho y bien; el coste residual es lineal en número de tests y es el techo estructural de la velocidad de la suite.
- **Acceptance criteria:**
  - `CREATE DATABASE … TEMPLATE` una vez por sesión, o aislamiento por transacción con rollback para los tests que no hacen DDL.
  - Tiempo del job `test` de CI medido antes/después en el PR.
- **Files de partida:** [tests/conftest.py](../tests/conftest.py)
- **Riesgo:** medio — toca el aislamiento de toda la suite; un fallo aquí se manifiesta como tests que se contaminan entre sí.

### [P3] Decidir el techo de memoria de WSL en la máquina de desarrollo (acción del propietario)
- **Área:** `%UserProfile%\.wslconfig`, scripts/dev/
- **Problema:** los controles corren en WSL desde el 2026-10-11 ([entorno-wsl.md](runbooks/entorno-wsl.md)). WSL reserva hasta la mitad de la RAM del host y no devuelve enseguida la caché de disco: con el equipo cargado, la VM dejó de aceptar conexiones unos diez minutos ese mismo día.
- **Acceptance criteria:**
  - Decidido el techo (`memory=` y `autoMemoryReclaim`) y aplicado con `wsl --shutdown`, que corta Docker Desktop y las shells abiertas en la distro.
  - Medida de nuevo la suite completa con la máquina desahogada y anotada en el runbook: los 34 min 33 s del 2026-10-11 se midieron con la VM tirando de swap.
- **Files de partida:** [docs/runbooks/entorno-wsl.md](runbooks/entorno-wsl.md), [scripts/dev/wsl_run.sh](../scripts/dev/wsl_run.sh)
- **Riesgo:** bajo.

### [P3] Entorno de staging

- **Área:** render.yaml, infraestructura (acción del usuario)
- **Problema:** `render.yaml` define tres servicios, todos en `frankfurt`, ninguno de staging: el primer entorno donde un cambio se ejecuta contra infraestructura real es producción. `deploy.yml` verifica el deploy, pero verificar no sustituye a tener dónde probar.
- **Acceptance criteria (decisión del usuario, con coste asociado):**
  - Decidir si se añade un servicio de staging apuntando a una BD de staging, y si `deploy.yml` despliega allí primero.
- **Files de partida:** [render.yaml](../render.yaml), [.github/workflows/deploy.yml](../.github/workflows/deploy.yml)
- **Relación:** la otra mitad de este ítem —el `plan: free` de la API— se separó el 2026-08-27 y subió a P1, porque contradice un SLO escrito y eso no es un nice-to-have. Se decide con coste, igual que ésta.
- *Estado (2026-09-19):* ese P1 **no existe** en este backlog ni en el archivo, y ya no hace falta: `render.yaml:105` declara `plan: standard` para `tenderflow-api`, con el comentario de que el 2026-08-28 se verificó por la API de Render que el servicio real corre en `standard`. Lo que queda de aquella mitad es reconfirmarlo tras vincular el Blueprint (P2 de `render.yaml`). De paso: `render.yaml` ya no define tres servicios sino cinco (`tenderflow-api`, `tenderflow-worker`, `tenderflow-prometheus`, `tenderflow-alertmanager`, `tenderflow-grafana`), todos en `frankfurt` y ninguno de staging.
- **Riesgo:** bajo técnico, con coste económico — por eso es decisión del usuario.

### [P3] Medir la cobertura de `procedimiento`, `tramitacion` y `peso_precio_pct` y decidir si entran como features
- **Área:** db/repositories/ml_dataset.py, services/ml/features.py
- **Problema:** las tres columnas se persisten desde `v85` y el upsert ya las protege del clobber (ver el ítem cerrado del 2026-09-06), pero siguen fuera de `FEATURE_COLUMNS`: el criterio de aceptación las admitía solo con cobertura real por encima del 50 % y **esa cobertura no se ha medido**. Mientras tanto son datos que se escriben y nadie usa. Una feature NULL en el 90 % de las filas no es neutra: gasta un split del GBM en aprender el patrón de ausencia.
- **Acceptance criteria:**
  - Medida y anotada la cobertura por campo sobre una BD real (o sobre el reprocesado de los ZIP cacheados), con fecha.
  - Si supera el 50 %: los cuatro pasos que enumera `FEATURES_PENDIENTES_COBERTURA` en `services/ml/features.py`, incluido reentrenar y reportar el delta de `mae_p50` contra la versión previa. Si no lo supera, queda escrito el número que lo desaconseja.
- **Files de partida:** [services/ml/features.py](../services/ml/features.py) (`FEATURES_PENDIENTES_COBERTURA`), [db/repositories/ml_dataset.py](../db/repositories/ml_dataset.py)
- **Riesgo:** bajo — el guard de `feature_columns` de `BajaModel` degrada a baseline si se despliega el código sin reentrenar.
- **Progreso parcial (2026-09-18, rama worktree-agent-a3fd0bc81b8a949c2) — la medición existe; el número no.** `ENV=dev python scripts/medir_cobertura_features.py` (o `--json` para archivarlo) imprime, contra la BD de `DATABASE_URL` y solo leyendo, la cobertura de los tres campos sobre dos poblaciones: `dataset_baja` (las filas exactas de entrenamiento, `_sql_agregado`) y `universo_abierto` (lo que puntúa el batch), cada una con total, por `fuente` y por año de publicación, y un veredicto contra el 50 % **solo sobre el total del dataset**. El SQL vive en `MlDatasetRepository.cobertura_features_pendientes`. Tests en `tests/test_medir_cobertura_features.py` (uno contra Postgres, no ejecutado en local). **Falta:** correrlo contra producción, anotar aquí el número con fecha y, según salga, seguir los cuatro pasos o dejar escrito el número que lo desaconseja.

### [P3] Partir los componentes con cinco o más booleanos de modo en variantes explícitas
- **Área:** web/src (composición de componentes)
- **Problema:** la auditoría del 2026-10 contra la skill `vercel-composition-patterns` encontró componentes cuyo modo se elige con varios booleanos que se solapan. Medido ese día, la cuenta de props `boolean` era de 7 en `detalle-fila.tsx`, 7 en `detalle-tabla.tsx` y 7 en `chat-thread.tsx`, y de 4-5 en `detalle-pie`, `radar-fila`, `barra-guardado` y `vista-previa-card`. Cada combinación nueva es un camino que nadie prueba, y quien llama tiene que saber qué pares son incompatibles. No hay ningún bug abierto por esto: es coste de cambio.
- **Acceptance criteria:**
  - `chat-thread` y la pareja `detalle-fila`/`detalle-tabla` exponen variantes con nombre (componentes explícitos o una prop `variante` con unión de literales) en vez de booleanos combinables.
  - Los tests existentes siguen verdes sin tocar su intención.
- **Files de partida:** [web/src/components/chat-thread.tsx](../web/src/components/chat-thread.tsx), [web/src/app/(dashboard)/detalle/_components/detalle-fila.tsx](../web/src/app/%28dashboard%29/detalle/_components/detalle-fila.tsx), [web/src/app/(dashboard)/detalle/_components/detalle-tabla.tsx](../web/src/app/%28dashboard%29/detalle/_components/detalle-tabla.tsx)
- **Riesgo:** medio — refactor sin cambio visible, pero toca componentes con muchos consumidores.

### [P3] Decidir el copy de la portada frente a las señales de plantilla (acción del propietario)
- **Área:** web/src/app/(publico)/_content/landing.ts
- **Problema:** la auditoría del 2026-10 contra la skill `design-taste-frontend` (`tells.md`) marca en la portada patrones de copy que esa skill considera señal de plantilla:
  - Rótulos en versalitas en cada sección y uno («FAQ») que repite su titular.
  - Cadenas con punto medio.
  - Un titular con la corrección «X, no Y» («Un radar tecnológico, no un censo…»).
  - Unas 8 rayas de inciso y un `familiasTitulo` de unas 45 palabras.
  - Un `ctaIntermedioTexto` que habla de la propia página.

  El rótulo único `KICKER` es decisión registrada (UX_AUDIT F46) y **no** entra aquí; lo que hay que decidir es si cada sección necesita además el suyo y si el texto se reescribe.
- **Acceptance criteria:**
  - Decisión escrita del propietario: qué se reescribe y qué se mantiene a propósito.
  - Si se reescribe: `faqKicker` desaparece, el h2 de «Qué entra» afirma en positivo y `familiasTitulo` se parte en un título corto y una enumeración.
- **Files de partida:** [web/src/app/(publico)/_content/landing.ts](../web/src/app/%28publico%29/_content/landing.ts), [web/src/app/(publico)/_components/piel-publica.ts](../web/src/app/%28publico%29/_components/piel-publica.ts)
- **Riesgo:** bajo — solo copy, pero es la cara pública y la voz la decide el propietario.

---

### [P3] Flecos de la rama `claude/funcionalidades-2026-10`
- **Área:** varios
- **Problema:** lo que las seis líneas dejaron escrito como pendiente, para que no se pierda.
- **Acceptance criteria:**
  - ~~RFC para retirar de `GET /notifications` los campos que la campana ya no usa (`items`, `unread_count`, `hoy`), y `POST /notifications/read` y `GET /licitaciones/stream`: quitarlos rompe el contrato.~~ Escrito el 2026-10-23: [2026-10-23-rfc-retirada-campana-antigua-y-stream](rfc/2026-10-23-rfc-retirada-campana-antigua-y-stream.md) (`review`), que propone el 2027-02-01 y añade `forecast/retendering`. La fase 1 ya está en el código: `deprecated`, `Deprecation`/`Sunset`/`Link`. El borrado (fase 2) espera a que el propietario apruebe la RFC.
  - Decidir si la cuota de adjuntos (2 GiB por organización) debe descontar los retirados; hoy borrar no libera espacio.
  - Regenerar los códigos de recuperación sin desactivar el segundo factor. (El QR en el alta del 2FA quedó **decidido no** el 2026-10-23: exige una dependencia nueva y D39 del [plan de funcionalidades](plans/2026-09-plan-funcionalidades.md) no la autoriza; el alta sigue ofreciendo la clave para teclearla y el enlace `otpauth://`.)
  - Renovar la captura de `/competencia` en `visual.spec.ts` (tiene dos pestañas más). `/empresas` ya salió de `web/bundle-budget.json`.
  - Validar con el dueño el reparto fabricante → familia de «Proyectos y módulos» (`FAMILIA_DE_FABRICANTE`; Oracle, Microsoft, IBM, ServiceNow y Sopra no cuentan en ninguna).
  - El digest dice «expedientes que sigues» también en los avisos de documentación.
  - `use-renovaciones` sigue leyendo `usePursuits()` con la página de 50.
- **Riesgo:** bajo.

### [P3] Decidir qué hacer con los ratchets que llevan meses congelados sin bajar
- **Área:** scripts/check_layers.py, pyproject.toml (TID251), scripts/check_user_key_ratchet.py, docs/STATUS.md
- **Problema:** tres ratchets congelan deuda con nombre y ninguno tiene plan de bajada: 22 imports contra el orden de capas (los peores van de la capa inferior a la superior: `db/repositories/go_no_go.py -> services.go_no_go_template`, `db/repositories/licitaciones.py -> services.investigador.search_engine`, `db/access_grants.py -> services.access_grants`, `config/settings.py -> shared.*`), 22 ficheros con SQL fuera de `db/` (TID251: de 32 entradas en agosto a 22 hoy, según los comentarios de `pyproject.toml`; 19 desde el 2026-10-23, y `tests/test_s4b_ratchet_tid251.py` falla ahora también ante una entrada que ya no abre conexiones) y 59 ficheros con `user_key` (el P1 de S1 lo lleva a cero con T4, pero el resto no tiene dueño). Un ratchet que solo impide crecer protege el futuro y deja el presente igual; medido el 2026-10-17 contra `docs/STATUS.md`.
- **Acceptance criteria:**
  - Decisión escrita del dueño por ratchet: (a) cuota de bajada —por ejemplo, cada PR que toque un módulo de la lista saca ese módulo o explica por qué no—, (b) fecha objetivo para llegar a cero, o (c) aceptar la violación como diseño y borrarla de la lista (y, en el caso de capas, actualizar AGENTS.md §2).
  - Para capas: las cuatro violaciones `db/* -> services.*` tienen prioridad, porque son las únicas en que la persistencia conoce el dominio; la pieza compartida baja a `shared/` o a `db/`.
  - `docs/STATUS.md` muestra la tendencia (valor y fecha del último descenso), no solo el valor.
- *Progreso 2026-10-25 (rama `agente/ratchets-y-modulos-dios`) — dos de los tres bajan más de un tercio:*
  - **Capas: 21 → 12** (`python scripts/check_layers.py --count`). Las cuatro `db/* -> services.*` están a cero, que era la prioridad del criterio. Bajan a la capa inferior las piezas compartidas: `password_policy` y `scoring_weights` a `config/`; `webhook_retry`, `go_no_go_template`, el criterio de concesiones OAuth (`shared/concesiones_acceso.py`) y `extract_keywords`/`FTS5_STOPWORDS` (`shared/palabras_clave.py`, reexportados desde `services.investigador.search_engine`) a `shared/`. Suben a su capa los módulos de `shared/` que abrían la BD: `jobs` → `services/jobs.py`, `model_artifacts` → `services/ml/model_artifacts.py`, `cache_signal` → `db/cache_signal.py`. Quedan 12: seis de `observability/` contra `db`/`services`, tres de `services/` contra `scraper/`, `api/routes/publico.py -> scraper.connectors`, `config/secrets.py -> observability.logging` y `observability/mailer.py -> shared.outbound_http`.
  - **TID251: 18 → 12** (ver el ítem F5).
  - `user_key`: sin cambios (lo lleva T4).
  - Comentarios de `.github/workflows/{ml-scoring,train-model,train-predictivos}.yml` siguen citando `shared/model_artifacts.py` (solo prosa; editar workflows pide OK humano, AGENTS.md §6).
  - **Falta para cerrar:** la decisión del dueño de los criterios de aceptación (no la puede tomar un agente). Propuesta que este PR deja en marcha: (a) cuota —un PR que toque un módulo de una lista lo saca o dice por qué no—, con objetivo de capas ≤ 6 (las de `observability/` se resuelven pasando el colaborador por argumento) y TID251 ≤ 6 antes de 2027-01; y la tendencia en `docs/STATUS.md`, que todavía muestra solo el valor.
- **Files de partida:** [scripts/check_layers.py](../scripts/check_layers.py), [pyproject.toml](../pyproject.toml), [docs/STATUS.md](STATUS.md)
- **Riesgo:** bajo — es una decisión de política; cada bajada concreta tiene su propio riesgo.

### [P3] `strict` con 2.113 `Any`: tipar las filas de los repositorios calientes
- **Área:** db/repositories/licitaciones.py, db/repositories/pursuits.py, db/repositories/aggregates.py, api/routes/*
- **Problema:** mypy strict pasa en los 1.269 ficheros, pero medido el 2026-10-17 hay 2.113 usos de `Any` en código de producción y 383 `dict[str, Any]` solo en `api/routes/` y `shared/dto.py`: los repositorios devuelven filas como `dict[str, Any]` (`rows_to_dicts`) y la ruta vuelve a tipar a mano al construir el DTO, así que un cambio de columna no lo detecta mypy sino el test de integración, si lo hay. El contrato hacia fuera ya está tipado (0 operaciones opacas); el hueco es hacia dentro.
- **Acceptance criteria:**
  - Un `TypedDict` (o dataclass) por forma de fila en los tres repositorios más usados, devuelto por sus métodos públicos; la ruta construye el DTO desde él sin `cast` ni `# type: ignore`.
  - El conteo de `dict[str, Any]` en `api/routes/` baja al menos un tercio y se añade como ratchet stdlib (solo baja).
- **Files de partida:** [db/repositories/base.py](../db/repositories/base.py), [db/repositories/licitaciones.py](../db/repositories/licitaciones.py), [db/repositories/pursuits.py](../db/repositories/pursuits.py)
- **Riesgo:** bajo — cambios de tipos sin cambio de comportamiento; mypy es el gate.
- **Progreso (2026-10-25, rama `agente/tipar-filas-repositorios`):** `TypedDict` por forma de fila en los cinco repositorios calientes —`aggregates` (overview, Radar, Resumen, Mercado), `licitaciones` (listado y ficha), `adjudicaciones`, `pursuits` y `publico`—, devueltos por sus métodos públicos vía `typed_rows(Fila, rows_to_dicts(cur))` (`db/repositories/base.py`: el único `cast`, comentado; `rows_to_dicts` sigue en el módulo para los tests que lo doblan y para `check_analytics_unbounded`). Los servicios y rutas consumidores se tipan con esas filas sin `cast` ni `# type: ignore`. Cifras: líneas con `Any` en `db/` + `services/` + `api/` **2.035 → 1.891**; usos de `Any` en el AST de producción (las diez capas) **2.351 → 2.192**, congelados en el ratchet nuevo `scripts/check_any_count.py` (`make check-any-count`, `tests/test_unit_ratchet_any.py`, solo baja). Por fichero: `aggregates` 58 → 12, `licitaciones` 46 → 28, `pursuits` 33 → 5, `adjudicaciones` 20 → 8, `publico` 28 → 25. **Queda:** `dict[str, Any]` en `api/routes/` solo bajó 406 → 398 (el criterio pide un tercio); la proyección de scoring (`scoring_candidates`, `licitaciones_by_ids`, `pipeline_window`) sigue como `dict[str, Any]` porque entra en un `DataFrame` que muta columnas; `conn: Any` no se toca hasta tipar `db/connection.py`.

### [P3] Documentar o fundir las dos caras de la persistencia, y retirar `services/sql_fragments.py` y `drift_monitor.py`
- **Área:** db/*.py, db/repositories/*.py, services/sql_fragments.py, scheduler/drift_monitor.py, docs/adr/ADR-022-frontera-de-persistencia.md
- **Problema:** para `watchlist`, `webhooks` y `audit` conviven un módulo de funciones en `db/` y un repositorio en `db/repositories/` sobre las mismas tablas; en `empresas` la pareja está documentada (escritura en el módulo, lectura en el repositorio), en las otras tres no, y quien busca «dónde está el SQL de webhooks» tiene dos respuestas (357 y 635 líneas). ADR-022 admite los dos estilos pero no dice cuándo una entidad lleva ambos. Aparte: `services/sql_fragments.py` (69 líneas, dos constantes) sobrevive como excepción nominal de AGENTS.md §3.10 cuando su contenido ya bajó a `db/sql_fragments.py`; y `scheduler/drift_monitor.py` es la capa para APScheduler, que no es el plano activo (ADR-012/033), así que es código para un plano que no corre.
- **Acceptance criteria:**
  - ADR-022 (o una nota en AGENTS.md §3.10) fija la regla: escritura en módulo / lectura en repositorio, o un solo sitio por entidad; `watchlist`, `webhooks` y `audit` quedan con la cabecera que lo diga, como `db/repositories/empresas.py` ya hace.
  - `services/sql_fragments.py` desaparece (sus dos constantes van a `db/sql_fragments.py`) y la excepción se borra de AGENTS.md §3.10.
  - `drift_monitor.py` se retira o se registra en el plano del worker (ADR-033) con su job en `docs/STATUS.md`; no hay módulo del scheduler que solo exista para APScheduler.
  - **Progreso 2026-10-25:** hecho el reparto de las dos caras (ADR-022, «Entidades con las dos caras», con cabecera en `db/repositories/{audit,webhooks,watchlist}.py` y nota en el playbook) y retirado `services/sql_fragments.py` (los importadores van a `db/sql_fragments.py`; la excepción sale de AGENTS.md §3.10). Queda `scheduler/drift_monitor.py`.
- **Files de partida:** [db/webhooks.py](../db/webhooks.py), [db/repositories/webhooks.py](../db/repositories/webhooks.py), [services/sql_fragments.py](../services/sql_fragments.py), [scheduler/drift_monitor.py](../scheduler/drift_monitor.py), [docs/adr/ADR-022-frontera-de-persistencia.md](adr/ADR-022-frontera-de-persistencia.md)
- **Riesgo:** bajo — reorganización sin cambio de SQL; TID251 y los tests de repositorio lo fijan.

### [P3] El coste de leer el repo: deriva documental y un backlog que su propia regla llama ilegible
- **Área:** docs/AGENT_PLAYBOOK.md, README.md, docs/IMPROVEMENT_BACKLOG.md, AGENTS.md
- **Problema:** medido el 2026-10-17: 202 ficheros y 39.489 líneas en `docs/`; AGENTS.md, CLAUDE.md, el playbook, este backlog y `web/AGENTS.md` suman 259 KB que cada sesión de agente carga antes de la primera línea de código; este fichero tiene 1.696 líneas con 62 ítems abiertos y `check_backlog_freshness.py` emite 15 avisos de frescura, mientras AGENTS.md §0 dice que «un backlog que nadie puede leer entero no prioriza nada». Deriva concreta, que la regla de §5 pide arreglar en el mismo cambio en que se detecta: el playbook cita `services/analytics_engine.py` (DuckDB) y `shared/i18n`, que no existen; el README dice «umbral: 70 %» de cobertura y `pyproject.toml` exige 78; `api/routes/licitaciones.py` figura en `per-file-ignores` de ruff y es un paquete desde septiembre.
- **Acceptance criteria:**
  - Las cuatro derivas de arriba corregidas.
  - Los ítems de este backlog con avisos de frescura revisados uno a uno (cerrar, actualizar o anotar por qué siguen abiertos aunque la revisión citada exista), y `check_backlog_freshness.py --strict` en CI en vez del modo informe.
  - Una regla de tamaño para el backlog (por ejemplo, 40 ítems abiertos o 1.000 líneas) que `check_backlog_freshness.py` avise al superar, y un apartado «Trabajo del propietario» que agrupe los 13 ítems que hoy son acciones manuales fuera del código, para que no se mezclen con lo que un agente puede coger.
- **Files de partida:** [docs/AGENT_PLAYBOOK.md](AGENT_PLAYBOOK.md), [README.md](../README.md), [scripts/check_backlog_freshness.py](../scripts/check_backlog_freshness.py), [pyproject.toml](../pyproject.toml)
- **Riesgo:** bajo — solo documentación; `check-agent-docs` valida las rutas citadas.

### [P3] Agrupar la veintena de gates stdlib en un solo target y un solo job
- **Área:** Makefile, .github/workflows/ci.yml, scripts/check_*.py
- **Progreso (2026-10-26):** `make gates` / `make gates-deps` (`scripts/run_gates.py`) y `ci.yml` los usa. Queda decidir una sola vía por gate (paso de CI o `tests/test_unit_ratchet_*`). Ver [plan 2026-10](plans/2026-10-plan-foco-piloto.md) §8.
- **Problema:** medido el 2026-10-17: 22 workflows y 4.213 líneas de YAML, `ci.yml` con 957 líneas y 11 jobs, y unos veinte gates y ratchets (`check_layers`, `check_api_surface`, `check_user_key_ratchet`, `check_analytics_unbounded`, `check_frontend_invariants`, `check_inline_styles`, `check_title_attrs`, `check_ortografia_ui`, `check_public_surface`, `check_env_parity`, `check_backlog_freshness`, `check_casos_uso`, `check_job_parity`, `check_coverage_per_module`, `check_bundle_budget`…) repartidos entre pasos de `static-analysis`, targets del Makefile y tests `tests/test_unit_ratchet_*.py`. Funcionan, pero cada gate nuevo es un paso más que mantener en tres sitios y la lista de qué corre dónde no está escrita en ninguno.
- **Acceptance criteria:**
  - Un `make gates` que ejecute todos los checks que solo necesitan la stdlib (y `make gates-deps` para los que necesitan la API importable), con salida agregada; `ci.yml` los invoca con un paso cada uno en vez de uno por script.
  - `docs/AGENT_PLAYBOOK.md` §2 lista los gates desde ese target (o se genera), y `tests/test_unit_ratchet_*.py` deja de duplicar los que ya corren como paso, o al revés: una sola vía por gate.
- **Files de partida:** [Makefile](../Makefile), [.github/workflows/ci.yml](../.github/workflows/ci.yml), [docs/AGENT_PLAYBOOK.md](AGENT_PLAYBOOK.md)
- **Riesgo:** bajo — reordena controles existentes; el riesgo es dejar uno fuera, y la lista explícita es justo lo que lo evita.

### [P3] Los 41 `SELECT *` de `db/` y el SQL propio de `services/notifications.py` y `services/watchlist_rules.py`
- **Área:** db/*.py, db/repositories/*.py, services/notifications.py, services/watchlist_rules.py, db/notifications.py, db/repositories/watchlist_rules.py
- **Problema:** medido el 2026-10-17 hay 41 `SELECT *` en `db/`: cada columna nueva viaja en todas esas lecturas y el orden de las columnas pasa a ser contrato implícito (es lo que hace frágil `rows_to_dicts` ante un `ALTER TABLE`). Aparte, `services/notifications.py` (10 sentencias con `# noqa: S608`) y `services/watchlist_rules.py` (8) —18 en total; el recuento anterior, «18 y 10», sumaba de más— construían y ejecutaban SQL propio pese a existir `db/notifications.py`, `db/repositories/notification_preferences.py` y `db/repositories/watchlist_rules.py`: son dos de las 22 entradas del ratchet TID251 y las dos tienen ya un destino en `db/`.
- **Acceptance criteria:**
  - Las lecturas con `SELECT *` que sirven a la API nombran sus columnas (las de `pg_dump`/herramientas internas pueden quedarse con el motivo en la línea); el conteo baja y se fija.
  - ~~El SQL de `services/notifications.py` y `services/watchlist_rules.py` vive en sus módulos de `db/`; los dos ficheros salen de la whitelist TID251 de `pyproject.toml` (22 → 20) y `docs/STATUS.md` lo refleja.~~ **Hecho el 2026-10-23:** el SQL bajó a `db/notifications.py` y `db/repositories/watchlist_rules.py` (incluida la ejecución del matching), los 18 `noqa: S608` desaparecieron y la whitelist queda en 19 (sale también el fósil `services/ml/tech_classifier.py`). Queda solo la mitad de los `SELECT *`.
  - **Progreso 2026-10-25:** `db/mcp_oauth.py` nombra sus columnas (`SELECT *` y `RETURNING *` fuera) y las lecturas que devuelven la fila entera por contrato (exportaciones RGPD de `audit`, `feedback`, `pursuits` y `watchlist`; `users`; `licitaciones.get_by_id`; `organos`; la búsqueda FTS de `db/upsert.py`) llevan `# SELECT *: <motivo>` en la línea. Quedan sin tocar los `SELECT *` que no leen una tabla (envoltorios `FROM (...)`, `unnest`, `LIMIT 0` de `db/connection.py`). Pendiente: sustituir los de `users`, `organos` y `get_by_id` por columnas nombradas, lo que exige inventariar quién consume cada clave del dict.
- **Files de partida:** [services/notifications.py](../services/notifications.py), [services/watchlist_rules.py](../services/watchlist_rules.py), [db/notifications.py](../db/notifications.py), [db/repositories/watchlist_rules.py](../db/repositories/watchlist_rules.py)
- **Riesgo:** bajo — movimiento de SQL con tests de integración existentes para ambos módulos.

### [P3] Frontend: navegación con `window.location.href` y acceso a la API desde componentes
- **Área:** web/src/lib/api-client.ts, web/src/app/login/_hooks/use-login-form.ts, web/src/components/layout/console-rail.tsx, web/src/components/**
- **Problema:** `npm run lint` da seis avisos `@next/next/no-location-assign-relative-destination` (medido el 2026-10-17: `api-client.ts:60`, `use-login-form.ts:195/215/257`, `console-rail.tsx:143`, `ajustes/_components/cuenta-view.tsx:88`): una navegación interna con recarga completa pierde el estado de React Query y el prefetch. Y 18 componentes fuera de `web/src/hooks/` llaman a `fetchWithAuth`/`apiGet`/`apiMutate` directamente, con lo que la clave de caché, el manejo de error y el toast se deciden en cada componente en vez de en un hook; es la misma dispersión que D6 del UX_AUDIT (doble toast en mutaciones) ve desde el otro lado.
- **Acceptance criteria:**
  - Cero avisos de lint en `web/`: `useRouter().push()`/`redirect()` donde la navegación es interna; donde la recarga es intencionada (cambio de organización, cierre de sesión) un comentario `eslint-disable-next-line` con el motivo.
  - Las 18 llamadas directas pasan por un hook de `web/src/hooks/` (o un `_hooks/` de su ruta) con clave en `query-keys.ts`; una regla de ESLint (`no-restricted-imports` de `api-client` fuera de `hooks/` y `lib/`) lo fija.
- **Files de partida:** [web/src/lib/api-client.ts](../web/src/lib/api-client.ts), [web/src/app/login/_hooks/use-login-form.ts](../web/src/app/login/_hooks/use-login-form.ts), [web/eslint.config.mjs](../web/eslint.config.mjs), [web/src/lib/query-keys.ts](../web/src/lib/query-keys.ts)
- **Riesgo:** bajo — refactor mecánico con tests de hooks existentes; el E2E de login cubre las recargas.

### [P3] SQLAlchemy se usa en producción y no está declarada como dependencia directa
- **Área:** requirements.in, pyproject.toml (`[project] dependencies`)
- **Problema:** `db/models.py`, `db/repositories/watchlist_rules.py`, `services/watchlist_rules.py` y otros construyen consultas con SQLAlchemy Core (`compile_query`), pero `sqlalchemy` no está en `requirements.in` ni en las dependencias de `pyproject.toml`: llega a `requirements.txt` solo como dependencia transitiva (`sqlalchemy==2.0.49`, «via» otra librería). El día que esa librería la suelte, o la fije a una major incompatible, la API deja de arrancar sin que ningún diff de dependencias lo haya avisado. Visto el 2026-10-23.
- **Acceptance criteria:**
  - `sqlalchemy` declarada en `requirements.in` y en `pyproject.toml` con el mismo rango, y `requirements.txt` regenerado con `pip-compile`; `scripts/check_requirements_sync.py` en verde.
- **Pendiente de OK del propietario** (AGENTS.md §6: cambiar dependencias requiere confirmación explícita). No se toca hasta tenerlo.
- **Files de partida:** [requirements.in](../requirements.in), [pyproject.toml](../pyproject.toml)
- **Riesgo:** bajo — declara lo que ya está instalado; el riesgo es no hacerlo.

### [P3] El marco común del dashboard pesa ~850 KB y el paso de CI del analizador de bundle no produce nada
- **Área:** web/src/components/layout/*, web/src/components/ui/*, .github/workflows/ci.yml (con OK del propietario)
- **Problema:** tras el cierre del 2026-10-25 de «Un objetivo de bajada para el First Load JS», las cuatro rutas grandes rondan 0,9-1 MB y casi todo es el marco común (~850 KB, 453 de Next y React). Las palancas que quedan, medidas: sonner (34,5 KB; `toast()` se importa en 68 módulos), los menús y popovers de Radix del marco (~25 KB; cargar sus disparadores al usarlos), el editor del ámbito de la barra (~8 KB) y, en la ficha, el Select del kit de presentación. Además, el paso «Bundle analyzer report» de `ci.yml` usa `@next/bundle-analyzer`, que con Turbopack no escribe informe.
- **Acceptance criteria:** las cuatro rutas en su `objetivo` de `web/bundle-budget.json`; el paso de CI cambiado a `next analyze --output` (editar `ci.yml` pide OK, AGENTS.md §6).
- **Files de partida:** [web/bundle-budget.json](../web/bundle-budget.json), [web/src/__tests__/first-load-diferido.test.ts](../web/src/__tests__/first-load-diferido.test.ts), [scripts/check_bundle_budget.py](../scripts/check_bundle_budget.py)
- **Riesgo:** bajo.

## Cerrados

- [2026-10-25] **Índices `v142`/`v143` (búsqueda `q`, tecnología) y `v144` (analítica) ya estaban aplicados en producción** — verificado con `migrate.yml` en `plan` (BD en `v158`) y `pg_stat_user_indexes`; los dos ítems P1 que pedían aplicarlos eran deuda documental y van al archivo con los `idx_scan` medidos.
- [2026-10-26] **Revisión de rendimiento y código (rama `agente/optimizacion-rendimiento-2026-10`)** —
  API: la validación de API keys hacía tres lecturas de BD en el event loop
  (`api/auth.py`, fuera del barrido de `test_async_handlers_no_blocking_io.py`, que ahora
  mira también los módulos de primer nivel de `api/`); el dueño viaja en el contexto y
  `dual_auth` ya no lo relee; las columnas de `api_keys` se leen una vez por proceso;
  `last_used` se escribe como mucho una vez por minuto y clave. Las descargas (CSV, Excel,
  PDF, CRM, RGPD) salen en un cuerpo con `Content-Length` en vez de un salto al threadpool
  por línea. `/metrics` serializa en un hilo; la validación del listado por cursor y de
  `/search` va en el hilo de la consulta; `/tecnologias` hace un salto en vez de tres;
  `fts_available` recuerda el `True`; `/source-freshness` cachea 60 s; el health check
  cierra su cliente Redis; la invalidación de caché barre Redis de 1.000 en 1.000 y borra
  en tanda; `get_tracer` no reintenta el import fallido de OpenTelemetry en cada `run_db`.
  Logging: `filter_by_level` primero (un `log.debug` suprimido pasa de ~18 µs a ~1,4 µs).
  Ingesta: XPath compiladas una vez por hilo (`parse_entry_unfiltered` 0,55 → 0,31 ms por
  entry, fixtures); PSCP extrae importes y estado después de la puerta tecnológica; el
  rescate de pliegos pregunta si alguien espera la entry antes de leer sus referencias;
  `replace_lotes_batch` es una transacción con dos `DELETE` y un upsert multi-fila (antes,
  una transacción y 3+N viajes por licitación); `upsert_meta_batch` escribe los documentos
  del flush con un `SELECT` y tres `executemany`, con fail-open por licitación vía
  `SAVEPOINT`. BD: la asignación de órganos para tras un lote incompleto (un recorrido
  menos por grafía); `list_extracted_without_chunks` con `NOT EXISTS`; `scope_coverage` en
  una consulta; preferencias de notificación en una transacción y todas o ninguna.
  Servicios: `derive_new_events` sin el recorrido cuadrático; clustering sin el ajuste
  repetido de KMeans ni la concatenación cuadrática; `normalize_company` memoizada; fecha
  ISO por `fromisoformat` en ML. Bugs: `int("²")` en la normalización de códigos (y una
  copia duplicada menos), `_rfc3339` del feed Atom sellaba como UTC horas con zona,
  temporal fijo en `LocalObjectStore.put`, cuatro `except` del healthcheck sin `ROLLBACK`
  (el de `pg_database_size` dejaba la transacción abortada y tumbaba el healthcheck entero),
  carrera de versión en `tech_signal.score_documents`. Frontend: recharts fuera del First
  Load de Competidores y Órganos, panel de opciones del Investigador bajo demanda,
  `staleTime` del overview sin rebajar, tablero sin re-render en cada `dragleave`,
  `useFilters` estable, cola de cierre cancelable. Verificado contra Postgres 16 + pgvector
  local: suite `integration and not slow` (3.123 verdes; los 5 rojos de esa pasada, arreglados
  y re-ejecutados) y 495 tests de BD de lotes, documentos y conectores tras el lote. Lo que
  quedó abierto: el P2 «[Rendimiento 2026-10] Lo que quedó de la revisión».
- [2026-10-23] **Excepción de `braces` en `npm audit` retirada** — el job «Security audit»
  de la PR #529 falló porque `npm audit` ya no reporta GHSA-vfj7-8cjw-p6xm (el lockfile sigue en
  `braces` 3.0.3 y `npm view braces version` también) y `scripts/check_npm_audit.py` exige quitar
  una excepción que no tapa nada. `EXCEPCIONES` queda vacía; si el aviso vuelve, la puerta falla
  y se re-evalúa con la plantilla del 2026-10-03.
- [2026-10-23] **Higiene de la sección 6: SQL de servicios a `db/`, ratchet TID251 sin fósiles, deprecaciones con fecha y auditoría de telemetría** —
  el SQL de `services/notifications.py` (alertas in-app y preferencias de correo) baja a
  `db/notifications.py`, y el de `services/watchlist_rules.py` (CRUD de reglas y ejecución del
  matching) a `db/repositories/watchlist_rules.py`; los servicios conservan la regla (modo de
  correo por defecto, validación contra el catálogo, fail-safe de la lectura, normalización del
  órgano, cláusulas del filtro). Desaparecen los 18 `noqa: S608` (eran 18, no 26). Salen de la
  whitelist TID251 esos dos ficheros y el fósil `services/ml/tech_classifier.py`, que solo
  nombraba `connect()` en un docstring: **22 → 19**. `test_sin_entradas_fosiles` falla ahora
  también ante una entrada sin ningún uso real (`ast`, no texto) de `connect`/`connect_read`.
  Las tres rutas de analítica de D19 y `forecast/retendering` envían `Deprecation`/`Sunset`/`Link`
  (desde una dependencia, para que sobrevivan al acierto de `cache_response`); la fecha de D19
  pasa del 2026-12-04 —89 días, fuera de la ventana de C8.1— al 2027-01-15 del listado por
  offset, cuyo `summary` también decía 2026-12-04 (addendum en la RFC). RFC nueva
  [2026-10-23-rfc-retirada-campana-antigua-y-stream](rfc/2026-10-23-rfc-retirada-campana-antigua-y-stream.md)
  para `GET /notifications` (campos), `POST /notifications/read`, `GET /licitaciones/stream` y
  `forecast/retendering`, con su fase 1 aplicada. `tests/test_deprecacion_cabeceras.py` exige
  fecha a toda operación `deprecated`. Telemetría: los 23 eventos del catálogo tienen emisor y
  `analytics-emisores.test.ts` lo fija. Pendiente aparte: SQLAlchemy como dependencia directa
  (ítem P3, espera OK del propietario).
- [2026-10-23] **P2: Las colas de revisión del dato se llenaban y nadie podía vaciarlas;
  la auditoría de verdad del dato solo llegaba por correo** (tanda paralela, tramo A) —
  `licitaciones_duplicados` en `pending` (ADR-026) solo se resolvía desde un test, con el SQL
  en `services/dedupe.py` (contra ADR-022), y `organo_review_queue` (ADR-032 §C) no tenía
  ninguna función que la resolviera. El SQL de la cola de duplicados baja a
  `db/repositories/dedupe.py` (`pendientes_de_revision`, `pendientes_count`,
  `resolver_pendiente`; `review_pending`/`resolve_pending` desaparecen del servicio). Los
  órganos se resuelven con `db.repositories.organos.resolver_revision` (reclama la fila) y la
  regla `services.organos.decidir_revision`, calcada de `db.empresas.apply_review`: aceptar
  registra la grafía como alias del candidato, rechazar crea un órgano propio, y en los dos
  casos las licitaciones con esa grafía reciben su `organo_id`. Rutas de admin en
  `api/routes/admin_revision.py` (`GET/POST /admin/revision/duplicados`, `…/organos` y
  `GET /admin/revision/verdad`, cacheada una hora), auditadas como `dedupe.review_resolved` y
  `organo.review_resolved`. Los umbrales, la medición de BD y `evaluar` de
  `scripts/audit_domain_truth.py` bajan a `services/verdad_dominio.py` para que la API los
  sirva sin importar el script; el script los re-exporta y añade la sección (b), que lee ZIP
  con `scraper/`. `QualityResult` publica `duplicados_pendientes`. En la consola, Ops › Datos
  monta tres tarjetas (`revision-duplicados-card`, `revision-organos-card`,
  `verdad-dominio-card`). Lo fijan `tests/test_revision_datos.py`,
  `tests/test_unit_admin_revision.py`, `tests/test_unit_verdad_dominio.py`, el escenario
  CU-20 `tests/test_escenario_revision_datos.py` y
  `web/src/app/(dashboard)/ops/__tests__/revision-datos-cards.test.tsx`. Sigue fuera: la
  auditoría no persiste su serie en la BD (el histórico está en los artefactos de
  `domain-truth.yml`), así que el panel enseña la medición de la última hora, no la tendencia.

- [2026-10-23] **Backend sin pantalla en Competencia y Equipo: cuota, HHI y
  bajas; pesos del go/no-go; rastro de auditoría de la organización** (tanda
  paralela, agente D) — Competencia → Competidores gana «Concentración por
  segmento» (`GET /competitive/hhi` por familia CPV, comunidad, órgano o
  tecnología; al elegir un segmento, `/competitive/cuota` y
  `/competitive/bajas/referencia` solo cuando el endpoint sabe filtrar ese
  corte) y «Bajas medias» (`/competitive/bajas` por órgano, CPV o comunidad,
  con la parte de la barra que el endpoint entiende y nombrando la que no).
  Los umbrales del HHI salen de un solo sitio (`competencia/_hooks/mercado-segmentos.ts`)
  para la cifra del ámbito y la lista de segmentos; la cifra ya era dato real
  de `/analytics/competitors`. Equipo → Organización gana la tarjeta de pesos
  del go/no-go (`GET/PUT /organizations/go-no-go/weights`; todos a cero se para
  antes de la API) y Equipo → Actividad, para owner/admin, el rastro de
  auditoría con filtro de fechas, paginación por cursor y CSV generado por la
  API. **Bug arreglado de paso:** los pesos del go/no-go y la propuesta de
  pesos aplicada se auditaban con `resource=organization:<id>` y el rastro solo
  leía `org:<id>`, así que nunca aparecían; `AuditRepository.list_for_organization`
  lee las dos formas (también lo ya persistido). Recorridos:
  `tests/test_escenario_gobierno_organizacion.py` (CU-06 y CU-32 nuevo) y el
  segundo test de `tests/test_escenario_competencia.py` (CU-18). Queda abierta
  la pantalla de la matriz por criterio (ver P2 «La matriz go/no-go por
  criterio no tiene pantalla»).
- [2026-10-23] **P1: La vista canónica todavía puede preferir TED, y el bulk no cuenta como
  PLACSP** (rama de la tanda paralela; OK del propietario a la migración) — el primer criterio de
  canónica pasa a `db.sql_fragments.rango_de_fuente_sql`: PLACSP (`placsp` o `bulk_*`, prefijo
  exacto con `left(..., 5)`, sin `LIKE` ni `%`) → resto → TED. Su gemelo
  `services.dedupe._rango_canonico` cambia con él y `tests/test_canonica_orden_pg.py` ordena las mismas
  filas en Postgres y en Python. `v157_mv_canonicas_fuente` reconstruye la vista por permuta (calcada
  de `v102`); `tests/test_mv_canonicas_definicion.py` apunta a ella. Delta medido en producción el
  mismo día con el MCP, sin aplicar nada: **32 de 40.545** contratos publicables cambian de fila
  canónica (29 de TED a PLACSP-bulk, 3 de `placsp` a `bulk_*` del mismo expediente). Glosario del
  MCP y ADR-026 actualizados. **Pendiente, propietario:** revisar el delta con
  `ENV=dev python scripts/medir_delta_canonicas.py` (lista cada URL que cambia) y aplicar `v157` con
  `migrate.yml`; va detrás de `v156`, así que se puede subir hasta `v156` sin mover URLs.

- [2026-10-23] **P2: Filas nuevas con importe y sin `importe_tipo`** — las 4 filas de `galicia_rss`
  (escritas entre el 10 y el 17/09, las únicas de toda la tabla, medido ese día) pasan a
  `desconocido` con `v155_importe_tipo_galicia_desconocido`, acotada a esa fuente para que otro camino
  roto siga saltando en la auditoría. Idempotente; downgrade no-op documentado. El conector de hoy ya
  escribe la base (`regional_rss._tipo_de_importe`, test `test_rss_la_fila_de_galicia_lleva_tipo`).
  **Pendiente, propietario:** aplicar `v155` con `migrate.yml`; tras ello `importe/filas_nuevas_sin_tipo`
  vuelve a cero.

- [2026-10-17] **P2: Decidir si el listado `/licitaciones` esconde duplicados (ADR-026 D23
  dice que sí)** (rama `claude/listado-esconde-duplicados`) — manda D23: el listado es
  presentación y esconde `pending` y `confirmed`, como el Radar. La exclusión entra siempre
  en `_base_filters` (paginado y cursor), en la rama FTS, en el export (`fetch_for_pdf`) y en
  el feed SSE del dashboard (`fetch_recent`); `build_licitaciones_where` la emite solo con
  `presentacion=True`, que es como la piden el overview y sus tarjetas, el Resumen, el
  calendario de vencimientos y el Radar (`scoring_candidates`, `pipeline_window`; la aplicaba
  a mano). `count_total_activas` y el universo del snapshot (`db/kpi_precompute.py`) siguen la
  misma regla, de modo que lista, KPIs, Radar y snapshot cuentan lo mismo; la ficha por id no
  cambia. Siguen contando, sin el flag: las agregaciones de Mercado (tendencias, geografía,
  órganos, tecnologías, CPV, forecast, tipos, clusters, proyectos) y sus drill-downs —son la
  fila «métrica» de D23 y leen de `idx_lic_analitica` (v144), que no incluye `id_externo`—,
  el feed de eventos del Resumen (lista eventos, no expedientes) y las métricas competitivas,
  que siguen con `exclude_duplicados_sql`. Fuera a propósito: `POST /licitaciones/search`
  (`search_advanced`), que monta su propio SQL por rango de `ml_proba`, `search_vector` y
  ventanas de fecha y no tiene consumidor en la web; si algún cliente de la API lo usa como
  listado, es un cambio aparte. La decisión queda escrita en ADR-026 (nota del 2026-10-17) y
  en el docstring del guardrail de dedupe. Lo fijan `tests/test_listado_esconde_duplicados.py`
  (Postgres: cuatro superficies, KPIs, snapshot, calendario, Radar, Mercado y ficha) y los
  tests de SQL emitido y de «quién pide qué» de `tests/test_republicaciones_regla.py`.
- [2026-10-17] **P2: El tipo de contrato de una regla no casa con lo que guarda
  la columna** — la regla traduce lo que guarda (código o la palabra del
  selector antiguo) a código CODICE con `shared.procedimientos.codigo_tipo_contrato`
  y casa con el código sin ceros y con los textos de cada fuente que lo
  significan («Serveis», «services», «Servizos»…). Las opciones del selector
  salen de `/meta/filters`. No había reglas con tipo de contrato en producción.
  El filtro `tipo_contrato` del listado, el cursor, el export y la rama FTS
  casa igual (`_tipos_de_contrato` en `db/repositories/licitaciones.py`):
  filtrar por servicios pasa de 13.652 filas a 57.339, de 200 a 373 ms sobre la
  tabla entera (medido en producción el 2026-10-18).

- [2026-10-17] **P2: `deploy.yml` verificaba la instancia que ya servía, no la que acababa de
  desplegar** (rama `claude/funcionalidades-2026-10`) — Render despliega sin corte, y la
  espera aceptaba el primer 200 de `/health/ready`, que daba la instancia vieja: en el run
  38766484577 schema y smoke terminaron a las 16:09:05 y el deploy encolado no quedó vivo
  hasta las 16:09:32. Ahora `/health/ready` publica `commit` (`RENDER_GIT_COMMIT`, o
  `GIT_SHA` fuera de Render; `unknown` sin ninguno), y la espera es
  `scripts/esperar_deploy.py`: sondea hasta un 200 que traiga `github.sha`. Una respuesta
  sin el campo es de la versión anterior a este gate, y otro commit es la instancia vieja
  o un push posterior; si vence el plazo, el job dice qué commit respondía. Con `commit:
  unknown` falla al primer intento, porque reintentar no lo arregla. El gate de schema
  lee el payload verificado en vez de volver a preguntar. El hook sigue desplegando la
  punta de `master`: `?ref=<sha>` apagaría el autodeploy del servicio, y eso va con el P2
  de `render.yaml`. Tests en `tests/test_deploy_gate_commit.py`. **Verificado en
  producción el 2026-10-18** (#495, `da64d45`; `deploy.yml` run 39085288930): el intento 1
  vio «sin campo `commit`», la instancia de `54385dd` anterior al gate, y siguió esperando;
  el intento 2, 15 s después, vio `da64d45` (el contenedor recibe `RENDER_GIT_COMMIT`).
  Schema `ok (v153_rekey_pscp_id_externo)` y smoke en verde. La instancia aprobada fue la
  del autodeploy (`dep-dba1n37lk1mc73ceiog0`, viva a las 01:07:08), no la del hook (viva a
  las 01:07:49). Es el mismo commit, así que el veredicto vale, pero mientras siga el
  autodeploy el gate no prueba el arranque de la instancia del hook.
- [2026-10-17] **Segundo repaso del Investigador** (rama
  `claude/quirky-wozniak-xp20q0`):
  - **Duplicados:** los cinco caminos del motor (términos, expresión,
    subcadena, solo filtros y pliegos) esconden las copias `confirmed` y
    `pending` de `licitaciones_duplicados`, la regla de listados de ADR-026.
    Medido ese día: 6 de 11 resultados de una búsqueda corriente eran copias
    TED.
  - **Órgano en la frase:** «del Ayuntamiento de Valencia» filtra por órgano.
    Casa por palabras plegadas (`db.sql_fragments.palabras_de_organo`), con la
    clase en otras lenguas («Ajuntament de Barcelona», 589 filas frente a 4 de
    «Ayuntamiento de Barcelona») y sin exigir «Provincial» o «Insular».
  - **Tildes:** sin migración, la consulta añade la forma con la tilde
    probable (-cion, -ería, -logía…) y busca las dos. «instalacion» pasa de 18
    anuncios a 2.790; «depuracion», de 0 a 46.
  - **Crear alerta:** lleva el órgano y el procedimiento entendidos, y el alta
    rápida los enseña («Además filtra por», con «Quitar»). De paso, la regla
    comparaba el procedimiento con palabras («abierto») contra una columna de
    códigos CODICE y no casaba nunca; ahora compara códigos sin ceros y las
    opciones salen de `/meta/filters`. En producción no había reglas con
    procedimiento.
  - **E2E:** `web/e2e/recorrido-investigador.spec.ts` recorre CU-23.
  - **Medido y descartado:** buscar el procedimiento en el texto de las filas
    con `procedimiento` nulo (93 % del corpus). «contrato menor» solo traía 7
    filas más, y «acuerdo marco» acertaba en 10 de 103.

- [2026-10-17] **P2: Aplicar `v151_fechas_texto_iso` en producción** — aplicada con
  `migrate.yml` (`mode=apply`, run 39066215215, 82 s) fuera de la ventana de la ingesta:
  `alembic current` en `v151_fechas_texto_iso`, 0 de 54.300 filas de `documentos` con el
  formato de `now()::text` y `trg_lts_derivar_ml` habilitado (`tgenabled = 'O'`). El
  criterio que pedía 0 también en `licitacion_tecnologia_score.computed_at` estaba mal
  planteado: quedaban 53.903 filas, más 134 en `contrato_eventos.created_at`, con otro
  formato, el de SQLite sin zona (`2026-05-21 15:02:22`, de mayo a julio de 2026), que
  v151 dejaba fuera a propósito para no adivinar la zona. `v152_fechas_sin_zona_utc`
  las reescribe en ISO leyéndolas como UTC (la zona de `datetime('now')` en SQLite), en
  las mismas 34 columnas; se aplica con `migrate.yml` tras el merge.
- [2026-10-17] **Bug sin ítem: «desde tu última visita» perdía los pliegos del mismo día**
  (rama `claude/nifty-turing-axm5xg`, `4a7d04e` y `f383d88`) — lo documentaban tres
  `xfail(strict=True)` en `tests/test_novedades_desde_ultima_visita.py`. Las fechas se
  comparaban y ordenaban como texto: el corte con otro offset no se pasaba a UTC, y
  `documentos.created_at` (`DEFAULT now()`) se guardaba con espacio. Ahora el corte va en
  UTC, la consulta de pliegos compara instantes, el diff ordena por instante y `cuando`
  sale en ISO con `T`. `v151` corrige el DEFAULT de las 33 columnas afectadas y normaliza
  sus filas (aplicarla en producción es el P2 nuevo). Se quitan los tres `xfail` y se
  añade un test con filas en el formato antiguo, más un ratchet contra nuevos
  `text DEFAULT now()`. En el mismo cambio, `/organizations/{id}/settings` gana test HTTP
  (`332c0d4`): solo tenía tests de servicio con dobles.
- [2026-10-17] **P2: Mejorar el ranking de retrieval de producción (MRR 0.689)**
  y **P3: Flecos de la reescritura de la búsqueda del Investigador** — el
  golden set de `tests/eval/test_eval_rag.py`, medido en Postgres 16 con tres
  corridas idénticas, da para el camino de producción de `/ask`
  (`search_for_ask`, que desde 2026-10-09 responde con el motor del
  Investigador) `hit_rate@5 = 1.000` y **MRR = 1.000**, frente al 0.689 del
  2026-07. No hizo falta tocar pesos: lo cambió el motor nuevo (basta casar
  algún término y el orden pesa los raros). `MRR_MIN` sube de 0.65 a **0.95**,
  el valor medido menos una pregunta que baje al segundo puesto. Con esto se
  cierran los tres flecos del P3: el texto de la consulta fuera del log, el
  código sin llamantes retirado y el `MRR_MIN` ratcheado.
- [2026-10-17] **P2: Medir en producción la muestra ordenada de pasajes de pliego**
  — medido con «mantenimiento» (40.690 fragmentos) por el MCP de solo lectura:
  la muestra ordenada por `documento_id` tardaba 2,6–6,5 s frente a 175–509 ms
  la que no se ordena, y no era más reciente (46 expedientes de 2026 frente a
  54), porque `documento_id` no sigue a la fecha de publicación. Con menos
  coincidencias que el tope («baja temeraria», 480) las dos devolvían lo mismo
  en ~0,4–0,5 s. Se revierte a la muestra sin orden; el porqué queda en el
  docstring de `licitaciones_con_pasaje`.
- [2026-10-17] **Repaso del Investigador** (rama `claude/quirky-wozniak-xp20q0`)
  — lo que quedaba tras la reescritura del 2026-10-09:
  - **Fusión:** completa la lista del texto en vez de sustituirla (ver el P2 de
    la búsqueda por significado).
  - **Frase:** entiende el fin del plazo («que cierran esta semana», «con plazo
    hasta el 30 de noviembre»), los meses con nombre («en marzo») y el
    procedimiento («contratos menores», «procedimiento abierto»). Los tres van
    en el `WHERE` de todos los caminos (`ambito_busqueda_sql`) y vuelven en
    `interpretacion`.
  - **Resultados y `/ask`:** `hay_mas` y «Mostrar más» (hasta 100). `/ask`
    declara en `ask_meta.recuperacion_fallida` que buscar falló —antes se leía
    como «el corpus no cubre la pregunta»— y no cachea esa respuesta.
  - **Pantalla:** los deslizadores aplican al soltar (antes, una petición por
    paso del arrastre). Las preguntas de seguimiento llevan los ajustes vigentes.
    La selección se suelta al cambiar la consulta de la URL, no al repetir la
    misma. «Buscar» dice que busca también con lista en pantalla. Se enseña con
    qué palabras se buscó.
  - **Exportación y accesibilidad:** CSV con BOM y sin fórmulas, un solo
    `csvCell` en `@/lib/export`. «Recientes» solo guarda lo que se pudo buscar.
    `maxLength` en la caja. Recuento con `aria-live`. «Preguntar por este» sin
    hueco sigue enfocable y explica por qué. Los ajustes guardados se validan.

- [2026-10-15] **P3: La campana nunca lista novedades de licitaciones** (rama
  `claude/funcionalidades-2026-10`) — decidido «solo lo tuyo»: la campana lee la
  bandeja `in_app` de la organización activa (`GET /notifications/alerts`,
  paginada y con filtro), no marca nada al abrirse, tiene «Ver todas» y deja
  pausar la regla de una alerta. Las novedades de mercado se quedan en el
  Resumen; `get_resumen_novedades(user_id)` está retirada y un test vigila que
  nada lea `users.last_login`. Los campos deprecados de `GET /notifications`
  siguen hasta su RFC (ítem P3 nuevo; la RFC es
  [2026-10-23-rfc-retirada-campana-antigua-y-stream](rfc/2026-10-23-rfc-retirada-campana-antigua-y-stream.md)).
- [2026-10-12] **P1: El despachador del outbox no lo invoca ningún plano** — el ítem
  estaba desfasado: el cierre de la pasada ya llama a `event_dispatch` entre
  `cartera_avisos` y `digests` (`scheduler/pipeline_runs.py`, `_run_event_dispatch`,
  tier `advisory`), encendido por defecto y con `EVENT_DISPATCH_ENABLED=0` como
  salida de escape (`config/settings.py`, `event_dispatch_enabled`). La cola
  histórica se resolvió por antigüedad: `event_dispatch.caducar_viejos` caduca sin
  repartir lo que supera la antigüedad máxima. Lo único que queda es mirar que
  `domain_events_pending` baja en producción, y eso va con las demás comprobaciones
  del propietario.
- [2026-10-09] **P1: El Investigador no encontraba lo que se le escribía** (rama
  `claude/investigador-improvements-1e5d9c`) — medido contra producción: una
  pregunta normal caía a un `ILIKE` del primer token de la consulta cruda
  (5,4 s; 0 y 9 resultados en las dos únicas búsquedas del registro), el ámbito
  se aplicaba después contra 5.000 ids sin orden (Cataluña tiene 60.840 filas) y
  la fusión semántica no corría nunca (la imagen de la API no trae el modelo).
  Ahora la frase se interpreta (`services/investigador/consulta.py`), basta con
  casar algún término y el orden pesa los raros
  (`db/repositories/investigador.py`), se busca también en los pasajes de
  pliego, y `/ask` usa el mismo motor (`services/investigador/busqueda.py`). En
  la pantalla: una sola caja, la consulta en la URL, tarjeta con estado, plazo y
  pasaje, asistente con su propia entrada y alcance de hasta tres resultados, y
  «Crear alerta» hacia Mi Watchlist. Mismas consultas, 20-600 ms. Quedan
  abiertos los tres ítems «[Investigador]» de P2/P3.
- [2026-10-03] **P2: El auto-marcado de tests excluye del gate los módulos con «download» en el nombre** (#402) — el token de carga casa como palabra de la ruta; entran en `make check` 47 tests de tres módulos (los dos de «download» y `test_ola2_performance.py`, que probaba la caché y se renombra a `test_ola2_cache_y_bulk.py`), y un test fija con nombres qué módulos quedan `load`. Ficha en [el archivo](archive/IMPROVEMENT_BACKLOG_CERRADOS.md).
- [2026-10-03] **P2: Impedir que un test unitario salga a la red** (#402) — fixture autouse en `tests/conftest.py` que hace fallar con `pytest.fail` toda resolución o conexión no local desde un test `unit`, también si el código se traga el corte; los tests SSRF resuelven contra un `getaddrinfo` de pega. Ficha en [el archivo](archive/IMPROVEMENT_BACKLOG_CERRADOS.md).
- [2026-10-03] **P1: Tras desplegar el dedupe por referencia de TED, re-leer TED y medir cuánto se marcó** — backfill ejecutado desde el 2026-06-01 (no desde 2025-01-01: la fila TED más antigua era del 2026-06-10): 2.978 filas TED, 1.417 `confirmed` (522 por `idEvl`, 895 por expediente; eran 291) y ningún título con el prefijo «España – ». Ficha en [el archivo](archive/IMPROVEMENT_BACKLOG_CERRADOS.md).
- [2026-09-19] **P2: Remediación axe — reactivar las reglas desactivadas del E2E de accesibilidad** — sin `disableRules` ni `fixme`; últimos rojos en `8a424967` y `0fd5082c`. Ficha en [el archivo](archive/IMPROVEMENT_BACKLOG_CERRADOS.md).
- [2026-09-19] **P2: La experiencia móvil existe pero nadie la diseñó** — los cuatro criterios cumplidos; los rojos móviles del E2E, en `8a424967`. Ficha en [el archivo](archive/IMPROVEMENT_BACKLOG_CERRADOS.md).
- [2026-09-18] **P2: La consola no tiene primer uso** (rama worktree-agent-a37b58d577faad267) — la barra de
  ámbito explica qué es la primera vez (`components/layout/ambito-intro.tsx`,
  se cierra y se recuerda por navegador como `descarte.ts`; cada frase describe
  algo que la barra hace), y cuatro vacíos dicen qué hacer: Radar (quitar la
  tecnología del ámbito o crear una regla), Favoritos (dónde está la estrella,
  con enlace), Reglas (qué hace una regla) y Resultados combinados (aflojar
  criterios). El score ya se explicaba desde el 2026-08-30.
- [2026-09-18] **P3: Migrar los `title=` nativos restantes a `Tooltip`** (rama worktree-agent-a37b58d577faad267)
  — los 36 migrados: controles a `<Tooltip>`, texto truncado y casillas de
  heatmap a `<Pista>` (`components/ui/pista.tsx`), cuyo disparador no es
  focusable para no sumar una parada de tabulación por celda; lo que solo
  vivía en el `title` pasa a texto, `sr-only` o `aria-label`.
  `deudaTitleNativo` vacía y `MAX_TITLE_NATIVO = 0`.
- [2026-09-18] **P3: Scroll edge effects en vez de divisores duros** (rama worktree-agent-a37b58d577faad267) —
  además de la barra de ámbito y la barra móvil, las cabeceras de
  `SpaceShell` y de Resumen pierden el `border-b` fijo: montan su propio
  `ScrollEdgeProvider` (el que scrollea es su cuerpo, no `#main-content`) y el
  borde solo aparece con contenido debajo. Con `bleed` se conserva el borde.

**Cerrados el 2026-09-06 por la reconciliación O0.5** — ficha completa de cada
uno en [el archivo](archive/IMPROVEMENT_BACKLOG_CERRADOS.md), que es donde
AGENTS.md §0 manda que vivan los cerrados. Ninguno se cerró por lo que decía la
cabecera de este fichero: los seis se comprobaron contra el código.

- [P1] Aprobar un acceso es editar variables de entorno a mano — RFC 242, `v95_access_grants`, `db/access_grants.py` y las rutas `/admin/solicitudes-acceso/grants` con auditoría.
- [P2] Persistir procedimiento, tramitación y peso del precio — `v85` + `db/upsert.py`; entrar en `FEATURE_COLUMNS` sigue abierto como P3 propio, y se explica por qué.
- [P2] `HistGradientBoosting` revienta con una feature todo-NaN — `_columnas_observadas` + `tests/test_s3_feature_todo_nan.py`.
- [P2] Migrar las llamadas del frontend al cliente OpenAPI tipado — sin `fetch("/api/…")` crudo fuera de `lib/`, con regla ESLint que lo impide.
- [P3] Vigilar el crecimiento de `predicciones_baja` — purga por antigüedad en el job de ML.
- Modelos NIM de razonamiento sin `chat_template_kwargs` — arreglado en `9a6014b`; nunca llegó a ser ítem abierto, y se anota para que el backlog refleje el código.
- [2026-09-18, rama `worktree-agent-acc2389c11c7f60d4`] **[P1] Cobertura de tests de las
  páginas del frontend** — los tres criterios, medidos. (1) De los tres flujos «sin cubrir»,
  dos ya lo estaban cuando se revisó: `use-watchlist-items` (100 % de sentencias) y
  `ask-stream.ts` (96,9 %); el que faltaba de verdad, los filtros nuqs usados desde una
  página, lo cubren ahora los tests de `mercado/_hooks/use-tecnologias-view`,
  `use-organos-view` y `radar/_hooks/use-radar-consola` con el ámbito **real** (adaptador de
  pruebas de nuqs, sin doblar `useFilterParams`) y el test de paridad
  `lib/__tests__/filter-params.test.tsx`. (2) La lógica de `tecnologias`, `organos` y `radar`
  ya estaba en `_hooks/`; le faltaban tests, y los tres hooks quedan en 97–100 % de
  sentencias. (3) `npx vitest run --coverage` **terminó en local por primera vez desde
  2026-08-10** (199 ficheros, 2.198 tests): global 56,45/48,45/51,45/57,15 y `src/app/**`
  39,27/34,54/34,44/39,47. `web/vitest.config.ts` sube los globales de 38/28/35/39 a
  54/46/49/55, `src/app/**` gana su piso de sentencias (37/32/32/37) y los pisos por carpeta
  suben donde había margen, sin bajar ninguno. Hallazgo sin arreglar: en la vista
  Tecnologías, con `?tecnologia=` en el ámbito, el detalle de la tecnología elegida viaja con
  la del ámbito (`useFilteredQuery` hace ganar al filtro global sobre `extraParams`).
- [2026-09-07] **Barrido de ortografía castellana en las cadenas visibles**
  — cerrado al medirlo (C7.8): **cero** cadenas de UI sin tilde y **cero** `...`
  donde corresponde `…`. La ola anterior lo había cerrado y el backlog no se
  actualizó. `scripts/check_ortografia_ui.py` lo mantiene cerrado en CI, mirando
  solo texto JSX visible y props de copy — un grep sobre el fichero entero
  marcaría `"tecnologia"` y `"organo"`, que aquí son **nombres de campo de la
  API** y acentuarlos rompería las peticiones.
  El primer borrador de ese script daba 38 hallazgos y **los 38 eran correctos**:
  llevaba en la lista los plurales en `-ciones`, que no llevan tilde
  («licitación» → «licitaciones»). La lista quedó con los singulares agudos y
  con los plurales que sí la conservan («órganos», «tecnologías»).
- [2026-09-18] **Cerrados en la rama `worktree-agent-ac2127b7dcd3fc315`:**
  - P3 «Documentar `FRONTEND_URL` y `SENTRY_DSN` en `.env.example`» — documentadas, junto con las `DOCUMENT_BLOB_*` de S8.1; `_DOCUMENTACION_PENDIENTE` queda vacía y `scripts/check_env_parity.py` pasa.
  - P3 «Cuatro módulos citan un RFC de retirada de exports que no existe» — `docs/rfc/2026-09-03-rfc-retirada-exports-asincronos.md` reconstruido desde D7, `9207bde9` y #265; índice regenerado.
  - P3 «Decidir el destino de los tests tautológicos» — los dos de argon2 se reescriben en `tests/test_auth_core.py` contra la librería real y la rama sin argon2; el de `hasattr` sobre un `Protocol` se borra; `tests/test_TODO_review_tautologico.py` desaparece.
  - P3 «Suites propias para `services/investigador/` y `extraction_runs`» — `tests/test_investigador_search_engine.py` y `tests/test_extraction_runs.py` (el test `_bd` necesita Postgres).

- [2026-09-18] **P2: Contrato de paginación común para la API** (rama
  worktree-agent-acad4a43a2c0f0bae) — `PaginatedResponse`/`CursorPaginatedResponse`
  ya vivían en `shared/dto.py`; faltaba la otra mitad: `api/pagination.py`
  (`PageParams` + `pagina(default)`) declara `limit`/`offset` una sola vez con
  `MAX_PAGE_LIMIT` como tope único. Primera ola: las siete rutas que ya paginaban
  por offset (licitaciones, adjudicaciones, adjudicaciones de empresa, pursuits,
  comentarios, Próximas, empresas); mismos parámetros y misma respuesta, con el tope
  ensanchado de 200 a 500 donde era 200. `trends` ya exponía el roll-up `group_by`
  (day/week/month) y `serie_truncada` documentados en el DTO. Siguientes olas: las
  rutas con solo `limit` que devuelven listas.
- [2026-09-18] **P3: El embudo del Resumen mide sus porcentajes contra todo el
  corpus** (misma rama) — decidido: los cinco escalones (PUB, EV, RES, ADJ, ANUL)
  se miden contra su propia suma y suman 100; lo demás (PRE, AGR, EJEC, CPM, OTROS)
  sigue listado con `en_embudo=false` y `pct` sobre el ámbito. `OverviewResult`
  gana `funnel_denominador` y `fuera_del_embudo`. Cambio de semántica de
  `FunnelStep.pct` documentado en el DTO (AGENTS §3.5). El frontend no pinta
  `funnel_estados`, así que no hubo rótulo que cambiar.
- [2026-09-18] **P3: Unificar la definición de «Calientes»** (misma rama) —
  decidido: el Resumen mantiene su heurística (importe ≥ P75, abierta y en plazo)
  con el nombre que ya enseña la UI, «Grandes en plazo»; la banda `Caliente` del
  score queda para el Radar. Los campos `ResumenHoyResult.calientes`,
  `HoyCounters.calientes` y `OverviewResult.calientes_hoy` no se renombran y llevan
  la definición en su descripción OpenAPI (`shared.dto.DESCRIPCION_GRANDES_EN_PLAZO`).
- [2026-09-18] **P3: Pre-generar el resumen IA nocturno para licitaciones
  calientes** (misma rama) — fase 5 de `scheduler/jobs/documentos_embeddings.py`,
  gated por `RESUMEN_PREGEN_ENABLED` (off; `config/settings_resumen.py`): hasta
  `RESUMEN_PREGEN_BATCH` licitaciones abiertas —seguidas, banda `Caliente`, publicadas
  hoy— sin entrada vigente en el caché del resumen. BudgetGuard antes de cada una,
  corte por credencial rechazada, y salto entero sin caché compartida (Redis).
  Clave, prompt y contexto compartidos con la ruta en `services/rag/resumen.py`.
  **Pendiente de decisión humana para que sirva en Actions:** `pliegos.yml` no
  propaga `REDIS_URL` (a propósito, por el gate de presupuesto de fichas), así que
  en ese plano la fase se salta; activarla allí exige propagar `REDIS_URL` y la
  variable `RESUMEN_PREGEN_ENABLED`.
- [2026-09-14] **P2: cada re-ingesta nuleaba las cuatro columnas ML, y `tech_signal_merge`
  lo curaba a ciegas cada 4 h** — decidido: el clobber se corta en origen. `ml_proba`,
  `ml_tecnologias`, `ml_proba_max` y `ml_tech_principal` entran en
  `_LIC_COALESCE_UPDATE_FIELDS` (`db/upsert.py`): el `None` de un conector es «sin opinión», y
  los pasos ML siguen escribiendo por UPDATE explícito. `merge_doc_signals()` sin ids deja de
  barrer la tabla: `list_signals_for_merge` acota a licitaciones con señal sin `merged_at` o con
  resumen ML a NULL o sin la tecnología detectada, y devuelve
  `licitaciones_candidatas`/`licitaciones_reparadas`, que el paso loguea — «cero reparaciones en
  siete días» se lee ahí. Ficha completa en
  [el archivo](archive/IMPROVEMENT_BACKLOG_CERRADOS.md).
- [2026-09-18] **P2: Separar los requirements de la API de los del pipeline/ML**
  — rama `worktree-agent-aa37c7b64b746caaa` (sin PR). `requirements-api.txt`
  (63 pines) y `requirements-pipeline.txt` (79) compilados con hashes por
  `make lock`, con `--constraint requirements.txt` para que los pines coincidan
  con los que prueba el CI (`scripts/check_requirements_sync.py` lo verifica y
  además que el lock de la API no traiga nada solo-pipeline).
  `docker/Dockerfile.api` instala por defecto el de la API; `ARG
  REQUIREMENTS_FILE` da la variante del pipeline, que es la que usa
  `tenderflow-worker` en render.yaml y la vuelta atrás sin tocar código. Salen
  de la imagen de la API scikit-learn, scipy, joblib, statsmodels, networkx y
  lxml. Smoke por entrypoint en `tests/test_unit_api_imagen_slim.py` (la API
  arranca en un proceso que solo puede importar su lockfile; el worker, el del
  pipeline) y `ci.yml::docker-build` construye y prueba las dos variantes y
  publica su tamaño. La medición destapó un import implícito: `/publico/cobertura`
  arrastraba lxml vía `scraper.connectors` (arreglado con re-export diferido).
  `/explain` y `/analytics/clusters` responden 503 sin sklearn; su destino es la
  RFC [2026-09-18-rfc-explain-fuera-del-proceso-api](rfc/2026-09-18-rfc-explain-fuera-del-proceso-api.md)
  (`review`), que deja la decisión de desplegar la imagen reducida al mantenedor.
  **No verificado:** el build Docker real (el daemon no estaba levantado en la
  máquina que lo hizo; lo cubre el job de CI) y que Render pase
  `REQUIREMENTS_FILE` como build arg.
- [2026-09-18, rama worktree-agent-a3fd0bc81b8a949c2] **P3: un solo transporte para bajar
  assets de la Release** — `services/ml/model_artifacts.py::_download_release_asset` delega en
  `shared.release_assets` (`fetch_latest_release` → `find_asset_id` → `download_asset`): HTTPS
  pinned, allowlist por salto y sin reenviar el token al CDN. `requests` sale del módulo. La
  verificación del sha256 contra `model_versions` no se tocó: sigue en `resolve_active_artifact`,
  después de materializar, igual para bucket y Release. Tests nuevos en
  `tests/test_model_artifacts.py` (delegación, asset ausente, Release inaccesible, y un guard AST
  de que `requests` no vuelve).
- [2026-09-18, rama worktree-agent-a3fd0bc81b8a949c2] **P2: calibrar los umbrales de la
  auditoría de verdad del dato** — con los `domain-truth.json` de siete ejecuciones
  programadas (12→18/09, descargados con `gh run download`, artefacto
  `domain-truth-measurements`). `fecha_limite` por fuente ya se había calibrado en C4.5
  (2026-09-06); ahora `placsp` baja a 81,9 % (su límite estaba topado en 100 y no podía
  saltar), `ted` a 65,9 %, la UTE de 8 % a 0,02 % (medido las siete veces) y el delta de
  baja de 5 a 1,12 puntos. Histórico por día en el docstring de
  `scripts/audit_domain_truth.py`. De la serie sale un P2 nuevo: `importe_tipo` sin base
  declarada viola su umbral a diario y crece.


- [2026-09-01] **Revisión integral de la IA del detalle de licitación (10 mejoras en un
  cambio)** — salida de la auditoría de arquitecto del asistente IA. Lo que cambió:
  (1) el extracto de `descripcion` es ahora por modo (`llm/prompts.py::_EXCERPT_CHARS_BY_MODE`):
  el resumen ejecutivo veía **300 chars** del anuncio con 16k de presupuesto sin usar;
  (2) la neutralización anti-inyección cubre el bloque de contexto entero — `titulo` y
  `descripcion` también son texto scrapeado y podían cerrar `</fuentes_no_confiables>`;
  (3) los prompts internos (extraction/clasificacion/resumen) dejan de viajar por el límite
  de usuario de 2000 chars (`MAX_INTERNAL_QUESTION_LEN=12k`) — la causa raíz del incidente
  v3 de la ficha; (4) cadena de fallback de proveedor (`FALLBACK_MODELS`): un modelo que
  falla o devuelve vacío ANTES del primer token pasa al siguiente con API key, con métrica
  `llm_fallback_total` — mitiga el patrón deepseek-v4-pro (6 días caído en silencio);
  (5) canary diario del catálogo NIM (`scheduler/jobs/llm_models_canary.py`, paso canónico
  `llm_models_canary`) que convierte el próximo EOL en un email en vez de en un 410 mudo;
  (6) el serving del chat/resumen usa los embeddings pgvector persistidos
  (`DocumentosRepository.search_chunks_by_embedding`, `ORDER BY embedding <=>`) cuando el
  motor está disponible, con el camino Python previo como fallback — hasta ahora el job
  nocturno pagaba embeddings que ninguna request consultaba, y sin el extra instalado el
  "ranking semántico" real de producción era overlap de substrings; (7) el resumen se
  cachea por firma de estado (documentos + ficha + metadatos, `shared/cache`, TTL 7d) con
  `force` para regenerar y `cached` en `resumen_meta` — sin migración a propósito (gate §6);
  (8) la ficha verificada entra como contexto priorizado del resumen (chunk «ficha
  estructurada verificada» + instrucción en el system prompt); (9) `/ask` emite el evento
  aditivo `ask_meta` con el ámbito EFECTIVO y la UI avisa cuando la respuesta degradó al
  corpus — antes ese fallback era silencioso en el detalle; (10) «Extraer ficha» pasa a
  background (`extract-async` + polling de `/estado`, flag `running` en cache y no en el
  CHECK de la tabla), las citas de la ficha resuelven a `filename · página` con deeplink
  `#page=N` al PDF, la confianza autoinformada se presenta como ordinal, y nace el evento
  `asistente_feedback` (👍/👎 en chat, resumen y ficha). Diferido con criterio: golden set
  de extracción y unificación del selector de páginas (ítems P2 nuevos), pre-generación
  nocturna del resumen (P3). **Verificación:** ruff y mypy strict en verde; suite unit
  completa en verde salvo dos fallos preexistentes de trabajo sin commitear ajeno a este
  cambio (`auth.py::confirm_password_reset` en el checker de blocking-IO y el test de
  notificación de solicitudes); contrato OpenAPI e invariantes frontend OK; tsc/eslint/
  vitest del frontend en verde. Los tests de integración (Postgres) NO se ejecutaron en
  esta sesión — sin BD local — y quedan para CI.

- [2026-08-30] **P2: extraer las vistas de `/ops` a componentes compartidos** — ya estaba
  hecho y el ítem seguía abierto describiendo el estado anterior. `ops/page.tsx` importa hoy
  seis `_components/<x>-view.tsx` y ninguna `page.tsx`; su propio docstring documenta el
  cambio. Se cierra al detectarlo en la auditoría del 2026-08-29: un ítem cuya premisa el
  código desmiente hace que quien lo coja empiece por un callejón sin salida, que es
  exactamente lo que AGENTS.md §5 prohíbe.

- [2026-08-30] **P0: las alertas de reglas de vigilancia no podían dispararse** — el job
  guardaba su cursor como marca de tiempo y lo comparaba como **fecha**, con `>` estricto,
  contra `fecha_publicacion`, que solo tiene día; y adelantaba la ventana en cada evaluación
  hubiera o no coincidencias. Efecto compuesto: en cuanto una regla se evaluaba el día D, todo
  lo publicado ese día quedaba fuera de su ventana **para siempre**. Con el carril diario
  corriendo a las 00:0x UTC —cuando no se ha publicado nada del día todavía— la regla no
  volvía a disparar nunca después de su primera evaluación. Sin excepción, sin log y con sus
  tests en verde, porque todos sembraban el cursor y la publicación en días distintos, que es
  el único caso que funcionaba.
  El corte pasa a inclusivo con dos días de gracia y **quien decide qué es nuevo deja de ser
  la fecha**: es el anti-join contra `user_notifications`
  (`db/repositories/watchlist_rules.py::matches_pendientes`), o sea la misma verdad que ya
  imponía el `UNIQUE(user_key, licitacion_id, type)` de v48 — solo que antes actuaba en el
  INSERT, demasiado tarde para impedir que las filas ya notificadas gastaran el `LIMIT`.
  De paso, una regla que satura el tope deja aviso en vez de perder las coincidencias por
  encima de él. Tres tests nuevos, incluido el del mismo día que faltaba.
  **No verificado:** los tests exigen Postgres y esta sesión no lo tiene.

- [2026-08-30] **P1: el refresco de la vista pública corría antes que cinco de las siete
  fuentes** — `scrape-daily.yml` ejecutaba `run_update --daily`, que ingiere PLACSP *y* corre
  la secuencia canónica entera (KPIs, refresco de `licitaciones_canonicas`, evaluación de
  reglas, digests), y solo entonces lanzaba TED, Galicia, Euskadi, adjudicaciones vigiladas,
  PSCP y TACRC. Su corpus del ciclo no entraba en la superficie pública, ni en los agregados,
  ni en las alertas hasta cuatro horas después. El contrato escrito en
  `db/repositories/publico.py` decía «al final de la pasada de ingesta»; era a mitad.
  La pasada se parte en `--fase ingesta` y `--fase cierre` (`run_post_ingestion_only`), y el
  cierre es ahora el último step del workflow. Sin `continue-on-error`: un cierre roto sí debe
  poner el job en rojo, porque es donde viven el refresco y las alertas.

- [2026-08-30] **P1: un fallo del clustering congelaba la superficie pública en silencio** —
  `run_aggregates_precompute` declaraba en su docstring que el refresco iba aparte «por si el
  clustering fallara» y metía las dos cosas en el mismo `try`, con los dos caminos que de
  verdad pueden caer —una lectura de 50.000 filas y un DELETE con inserciones por lotes— por
  delante del refresco. El resultado era el sitio público servido sobre el último corpus
  bueno: cifras coherentes entre sí, viejas, y sin nada que lo delatara. Ahora son dos `try`
  independientes con estado `partial`, y el healthcheck vigila la vista (`canonicas_frescas`,
  `canonicas_tamano`) leyendo el evento `mv_canonicas_refresh` de `ops_events` — la única
  señal que cruza del plano efímero de Actions. NO se añadió regla de Prometheus, y está
  escrito por qué en `alert_rules.yml`: el scheduler no es scrapeable, sería una alerta muerta.

- [2026-08-30] **P1: métricas de cobertura desconocida pintadas como 0 %** — `/resumen` se
  abstenía de publicar `pct_oferta_unica` sin cobertura suficiente y `/competidores`, un clic
  más allá, publicaba la misma magnitud sin acotar; el gráfico de posicionamiento convertía
  los nulos en `0 %`, presentando a una empresa sin dato de ofertantes como la más disputada
  del mercado. El helper sale a `lib/cobertura.ts` y se aplica en las dos superficies. El
  guard `check_frontend_invariants.py` gana la categoría `nulo-a-cero`, que encontró **18**
  ocurrencias: se corrigieron las que se pintan y se justificaron en su línea las que son
  denominador o clave de orden.

- [2026-08-30] **P1: la superficie pública perdía su telemetría en el proxy de borde** —
  `PUBLIC_PREFIXES` de `web/src/proxy.ts` no eximía `/_vercel`, así que las peticiones a
  `/_vercel/insights/*` y `/_vercel/speed-insights/*` sin cookie de sesión —o sea todas las de
  la superficie anónima— recibían un 307 a `/login`. Se perdían las páginas vistas de las URLs
  indexables y los dos eventos que miden la conversión del embudo. Dentro del dashboard no se
  notaba porque allí siempre hay sesión, que es lo que lo hacía invisible desde dentro del
  producto. Con él se añade la primera suite de `proxy.ts` (31 casos): rutas públicas y
  privadas, la trampa del prefijo `/` que el propio fichero documentaba sin red debajo, y las
  dos ramas de CSP. **Pendiente de verificar contra producción:** si además el plan de Vercel
  descarta los eventos personalizados (son función de Pro), este arreglo no basta por sí solo.

- [2026-08-30] **P1: el aviso legal declaraba sus propias lagunas en producción** — el sitio
  es indexable y recoge una dirección de correo por consentimiento explícito, y la página
  terminaba con «Pendiente de completar: identificación del responsable del tratamiento y
  domicilio social». Honesto, y no es cumplir: el RGPD (art. 13) y la LSSI-CE (art. 10) exigen
  identificar al responsable en el momento de la recogida. La identidad pasa a `lib/legal.ts`
  y la ausencia **rompe el build de producción** (`next.config.ts`), en vez de hacer
  desaparecer el bloque en silencio. El plazo de conservación deja de ser «no hay ninguno»: se
  publican 24 meses y `scheduler/retention.py` los aplica, con un test que compara el número
  publicado con el que borra el job — si se separan, el aviso pasa a ser una promesa falsa sin
  que falle nada. **Requiere acción del responsable:** cargar las tres variables en Vercel.

- [2026-08-30] **P2: nueve rutas del dashboard sin título de documento** — WCAG 2.2 §2.4.2,
  nivel A. Faltaba en Radar y Oportunidades, las dos pantallas insignia, que heredaban el
  `default` del layout raíz: pestaña, marcador, historial y lector de pantalla decían
  «TenderFlow» en todas. Nueve `layout.tsx`, `generateMetadata` en las dos rutas dinámicas, y
  un test que recorre el árbol para que la décima falle el día que se cree.

- [2026-08-30] **P2: cambiar de espacio no se anunciaba ni movía el foco** — la consola navega
  en cliente entre catorce espacios y el foco se quedaba en el enlace del rail. Las dos piezas
  necesarias ya existían sin usarse: la región `aria-live` única y el `#main-content` con
  `tabIndex={-1}`. Seis líneas en `DashboardShell` y tres tests.

- [2026-08-30] **P2: el guard de superficie pública no alcanzaba al código que la alimenta** —
  `check_public_surface.py` escaneaba `api/routes`, `db/repositories/publico.py` y
  `web/src/app/(publico)`, y dejaba fuera los módulos de `lib/` que componen lo que se publica
  (`jsonld.ts` serializa datos estructurados con `dangerouslySetInnerHTML`). No había fuga:
  había una red con un agujero que se abriría en cuanto alguien extrajera una pieza a `lib/`,
  que es el refactor que el repo promueve — el mismo mecanismo por el que el escáner de
  deduplicación se desactivó solo en 2026-08. Radio ampliado de 23 a 36 ficheros y verificado
  inyectando una fuga temporal en `lib/jsonld.ts`, que el guard detectó.


- [2026-08-18] **P1: seis queries analíticas de `db/` contaban dos veces los contratos
  duplicados entre fuentes** — `tests/test_dedup_guardrail.py` existe para impedir exactamente
  eso, pero **solo escaneaba `services/competitive` y `services/ml`**. Las olas del ratchet
  TID251 llevan meses moviendo SQL analítico a `db/` (ADR-022) y, al moverlo, lo sacaban del
  radio del escáner: sin fallo, sin aviso, y con el commit de la migración saliendo verde. Es
  un guardrail que se desactivaba solo, por el mecanismo mismo del refactor que el backlog
  promueve. Al ampliar el escáner aparecieron 9 funciones sin la cláusula. Dos son exentas por
  diseño (`list_paginated` es CRUD, y `find_publicacion_posterior_a_adjudicacion` busca
  anomalías: deduplicar escondería lo que va a buscar). Una era **falso positivo del propio
  escáner** (`ml_dataset.licitaciones_abiertas` sí deduplica, con la subconsulta escrita
  inline). Las seis restantes eran deuda real, y las dos peores estaban en el camino de las
  métricas que se publican: `load_for_competitors`, que alimenta la cuota de mercado y el HHI
  de `services/analytics/competitors.py` —y se verificó que ese módulo **tampoco** deduplica en
  pandas—, y `load_licitadores`, el ranking de licitadores. Las otras cuatro son los KPIs de
  UTE. En esas cuatro la cláusula se sembró en `_adj_filter_conditions`, el helper que las
  cuatro comparten, para que no se pueda olvidar en la quinta.
  El escáner ahora lleva una lista explícita de módulos de `db/` (`_SCANNED_FILES`) que **cada
  ola futura del ratchet debe ampliar en el mismo cambio que crea el módulo**, y reconoce las
  tres formas legítimas de aportar el dedupe: la llamada al helper, la constante de módulo (el
  idioma de `db/`, que evita importar hacia arriba) y la subconsulta inline. `_PENDIENTES_MAX`
  queda en 0.
  `tests/test_adjudicaciones_dedupe_sql.py` (19 tests, sin BD) fija la composición del SQL en
  la frontera: que la cláusula aparece con filtros y sin ellos, que el `WHERE` queda bien
  formado en ambos caminos, que apunta a `a.licitacion_id` y no a `l.id_externo` —con el LEFT
  JOIN, la columna de la derecha habría descartado filas válidas por `NULL NOT IN`— y, sobre
  todo, **que los `%s` siguen cuadrando con los parámetros**: sembrar una condición en un
  constructor de `WHERE` desalinea los valores en silencio si la condición lleva placeholder, y
  eso no da error, da resultados incorrectos.
  **Lo que no se pudo hacer aquí:** medir el delta. La sesión no tenía Postgres, así que no hay
  número de cuánto bajan la cuota y el ranking al dejar de contar duplicados. Conviene mirarlo
  en el primer deploy: es la magnitud de lo que llevaban inflado.

- [2026-08-08] **P1: el trabajo bloqueante sale del event loop, y un ratchet impide que vuelva** —
  La API es async pero toda la persistencia es síncrona, así que un `async def` que llamaba directo
  a `db.*`/`services.*` ejecutaba ese trabajo **sobre el event loop**: mientras duraba, ningún
  endpoint del proceso respondía. Ninguna herramienta del repo veía la clase (ruff y mypy no
  modelan qué bloquea, y los tests funcionales pasan igual — un handler bloqueante da la respuesta
  correcta, solo que parando el proceso). Los peores casos eran `dual_auth.require_any_auth` y
  `auth._session_principal` (dependencias de casi toda la superficie autenticada, 1 y 3 viajes a BD
  por request), `auth.login`/`register` (seis viajes más argon2, caro por diseño),
  `exports.download_export` (50k filas + reportlab) y `security.verify_audit_integrity` (HMAC fila
  a fila sobre una tabla que solo crece). Los 22 handlers migran al idioma que ya usaba
  `watchlist_rules.post_rule`: el trabajo síncrono en una función anidada y un solo
  `await run_db(...)`, conservando el span OTEL `db.query`.
  `tests/test_async_handlers_no_blocking_io.py` lo congela con allowlist **vacía** (el barrido no
  dejó deuda) y se verificó que detecta una regresión inyectada. De paso, `download_export` empuja
  `tecnologia`/`fecha_desde`/`fecha_hasta` a la query: antes el LIMIT se gastaba en filas que luego
  se descartaban en Python, así que una exportación filtrada podía salir corta. Commits `8f3e7b9`,
  `fa383e5`.

- [2026-08-08] **P1: `/health` responde aunque una dependencia esté colgada** — Los tres sondeos no
  tenían techo de tiempo: con la BD colgada el endpoint esperaba al `connect_timeout` (10 s) o al
  `statement_timeout` (30 s), más de lo que aguanta el probe de la plataforma, que daba el proceso
  por muerto y lo reiniciaba justo cuando `/health` existía para publicar "degraded". Ahora van
  concurrentes en un task group, cada uno bajo `anyio.fail_after` con
  `HEALTH_CHECK_TIMEOUT_SECONDS` (default 5 s). Commit `377b844`.

- [2026-08-08] **P1: `POST /licitaciones/{id}/resumen` alcanzable para ids con `/`** — Usaba el
  conversor por defecto (`[^/]+`) mientras sus ocho rutas hermanas usan `{...:path}`. Los
  expedientes PLACSP con barra en el id (`PA-S 2026/000058`) recibían 404 antes de entrar al
  handler: el resumen ejecutivo era inalcanzable para ellos, en silencio. Commit `fa383e5`.

- [2026-08-08] **P1: `INSERT … RETURNING id` en vez del `lastrowid` emulado** — El adaptador
  emulaba el id con `SELECT lastval()` en sentencia aparte, que devuelve el último valor de
  **cualquier** secuencia de la sesión: con triggers ya en el schema (v61), un trigger que
  insertara en otra tabla con identity hacía que el caller recibiera un id ajeno **sin ningún
  error**. Los dos call-sites de webhooks eran los más expuestos (de ese id se deriva el secret
  HMAC). Los 5 sitios migran y la propiedad se elimina del adaptador. Commit `187ff9d`.

- [2026-08-08] **P2: un solo poller del centinela SSE por proceso** — Cada cliente conectado
  consultaba `db.cache_signal` cada 5 s por su cuenta: N clientes = N consultas por intervalo
  compitiendo por el threadpool con el resto de la API. Ahora un `_SignalWatcher` por proceso
  publica el timestamp en memoria y cada cliente lo compara con su checkpoint — exactamente lo que
  evaluaba `check_cache_signal`, pero O(1) en conexiones. Arranca con el primer suscriptor y se
  cancela con el último; el bucle por cliente baja a 1 s (comprobación en memoria), mejorando
  latencia y detección de desconexión sin coste de BD. Commit `b07fd6b`.

- [2026-08-08] **P2: `API_THREADPOOL_TOKENS` parametriza el límite de hilos** — `api/app.py` fijaba
  `total_tokens = 4` sin leer settings; ese pool sirve a los endpoints `def` y a todo `run_db`, así
  que el valor correcto para Render Free era un cuello de botella en cualquier instancia mayor.
  Default 4 (comportamiento idéntico) y warning si supera `DB_POOL_SIZE`. Commit `978b373`.

- [2026-08-08] **P2: primer test para los 3 módulos que ninguno mencionaba** —
  `services/deadline_reminders.py` (las tres ventanas, la distinción deadline/renovación, la
  idempotencia que hace seguro correrlo a diario), `services/rate_limiting.py` (selección de
  backend y los dos caminos de degradación, que deben acabar en BD y nunca en "sin rate limiting")
  y `db/repositories/csp_violations.py` (su contrato defensivo: ni tabla ausente ni BD caída
  propagan al endpoint público). Commit `2ca9174`.

El histórico de ítems cerrados vive en
[docs/archive/IMPROVEMENT_BACKLOG_CERRADOS.md](archive/IMPROVEMENT_BACKLOG_CERRADOS.md).
Al cerrar un ítem, movelo entero allí con su fecha y el commit que lo resolvió.

## Plantilla nueva entrada

```markdown
### [P0|P1|P2|P3] Título corto en imperativo
- **Área:** paquete/subárea
- **Problema:** 1-2 frases describiendo qué está mal y por qué importa.
- **Acceptance criteria:**
  - Bullet verificable 1
  - Bullet verificable 2
- **Files de partida:** [path1](../path1), [path2](../path2)
- **Riesgo:** bajo | medio | alto — razón breve.
```
