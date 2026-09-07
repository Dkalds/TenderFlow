---
tags: [plan, arquitectura, estado, generado-a-mano]
---

# Estado de ejecución del plan complementario 2026-09

Estado por ítem del [plan complementario](2026-09-plan-arquitectura-v2-complementario.md),
que se redactó como **PROPUESTO** y no lleva sección de seguimiento. Este
documento la aporta.

Existe porque su ausencia costó una sesión entera: el trabajo se repartió en dos
ramas —una con cinco streams commiteados, otra con un stream a medias y **sin
commitear**— y para saber qué faltaba hubo que leer los mensajes de commit uno a
uno y comprobar el árbol ítem por ítem. Lo que sigue es esa reconstrucción, ya
hecha.

**Última actualización: 2026-09-07.**

## Resumen

«Parcial» significa que el ítem entrega valor pero **no** cumple todavía todos
sus criterios de aceptación, y la tabla de su stream dice cuál falta. Contarlo
como hecho sería la clase de optimismo que obligó a escribir este documento.

| Stream | Hecho | Parcial | No hecho | Total |
|---|---|---|---|---|
| C1 Datos maestros y semántica | 3 | 1 (C1.3, falta el golden) | 0 | 4 |
| C2 Cuentas y seguridad | 7 | 2 (C2.5 triaje, C2.8 medido y no aplicado) | 0 | 9 |
| C3 Plataforma y coste | 5 | 1 (C3.2 ratchet) | 1 (C3.5) | 7 |
| C4 Ingesta y calidad | 5 | 0 | 2 (C4.3, C4.6) | 7 |
| C5 Conocimiento | 4 | 0 | 4 (C5.1, C5.2, C5.6, C5.8) | 8 |
| C6 Colaboración y captura | 0 | 0 | 7 | 7 |
| C7 Frontend y accesibilidad | 2 | 2 (C7.2, C7.4) | 4 | 8 |
| C8 API y contrato | 5 | 0 | 0 | 5 |
| C9 Documentación y proceso | 6 | 0 | 0 | 6 |
| **Total** | **37** | **6** | **18** | **61** |

## Correcciones al plan, registradas

Un plan que no registra sus errores los repite (§0 del propio plan). Cuatro
afirmaciones suyas no sobrevivieron a la medición:

1. **«152 apariciones de `title=`» (hecho 24, C7.4).** El grep mezcla `title`
   como prop de componente —`<KpiCard title="…">`, que no genera atributo HTML y
   es la mayoría—, `title=` en tests, y `title=` sobre elemento nativo, que es el
   único caso del problema. Reales: **33 en 18 ficheros**
   (`scripts/check_title_attrs.py`). Las «olas de ≥ 50» que pide el ítem no
   existen.
2. **C7.8 ya estaba hecho.** Medido: cero cadenas de UI sin tilde y cero `...`
   donde corresponde `…`. El backlog no se había actualizado tras la ola
   anterior. Lo que faltaba era el gate (`scripts/check_ortografia_ui.py`).
3. **C3.1: «≤ 60 % del tamaño actual» no es alcanzable** separando requirements.
   `scikit-learn` (+ scipy) lo necesita la API de verdad: `/licitaciones/{id}/explain`
   y la cola de `/feedback` cargan el clasificador en proceso. La palanca real es
   mover ese trabajo al worker de ADR-028.
4. **C4.5: el umbral anterior de `fecha_limite` (60 %) lo superaban todas las
   fuentes con volumen.** Un gate que no puede estar rojo no mide nada.

Y una del propio plan sobre v2, que él mismo registró: el README **sí** listaba
TED entre las fuentes activas.

## C1 — Datos maestros y semántica

| Ítem | Estado |
|---|---|
| C1.1 Importe con semántica (D21) | **Hecho** (`6b1490d`, v112). Tres columnas + `importe_tipo`; el histórico queda en `desconocido` y **no** se copia a `importe_base_sin_iva`. `bajas`/`pricing`/`escenarios-precio` declaran `base`. |
| C1.2 Maestro de órganos (D22) | **Hecho** (`048a0ea`, v113+v114). Patrón de `empresas`; DIR3 único parcial; lectura dual `clave_organo_sql`. **La migración no rellena**: el backfill de 706 k filas es una operación con ventana, no un `UPDATE` en migración. |
| C1.3 Predecesor y similares | **Hecho** (`efbb709`). `GET /licitaciones/{id}/similares`, `metodo ∈ {embedding, fts}` y `n`. **Pendiente**: el golden de 30 pares con precisión ≥ 0,8 exige etiquetado humano — generarlo con la misma regla que se quiere medir sería circular. |
| C1.4 Lotes de primera clase | **Hecho** (`6b1490d`). `LoteOut`, `exports/download?por_lote=true`. |

## C2 — Cuentas y seguridad

Todo en `70b3c37` (v115–v118) salvo lo indicado.

| Ítem | Estado |
|---|---|
| C2.1 Sesiones visibles | **Hecho.** `list_active_sessions` existía y no la llamaba nadie. |
| C2.2 Ciclo de vida de la organización | **Hecho** (ADR-030 §D). La salida anonimiza la autoría y **no** borra el trabajo compartido. |
| C2.3 Claves con autoservicio y tiers (D25) | **Hecho.** `api_key_tiers` existía desde `v28` sin que ninguna ruta leyera la columna. |
| C2.4 Webhooks con reintento | **Hecho.** El criterio, el SQL y la ruta de re-entrega ya estaban escritos; **faltaba la puerta**: `trigger_event` no dejaba nada `pending` y ningún job leía la cola. |
| C2.5 Vulnerabilidades con plazo | **Política escrita** en `docs/SECURITY.md`. El **triaje** de los avisos abiertos es acción del mantenedor. |
| C2.6 Errores de cliente con vista (D26) | **Hecho.** Tabla propia, sin SDK; retención de 30 días publicada. |
| C2.7 Preferencias de notificación | **Hecho.** |
| C2.8 CSP sin `unsafe-inline` | **Medido y NO aplicado, a propósito.** Un nonce cubre los `<style>` de Tailwind pero no los 94 atributos `style={{…}}`, y 12 llevan valores calculados. En CSP nivel 3, un nonce en `style-src` hace que el navegador **ignore** `'unsafe-inline'`: la corrección parcial rompe la página. Queda un ratchet que solo baja. |
| C2.9 Presupuesto por organización | **Hecho.** |

## C3 — Plataforma, coste y rendimiento

| Ítem | Estado |
|---|---|
| C3.1 Imagen de la API sin ML | **Hecho con el objetivo corregido** (`928d227`). Ver corrección 3. |
| C3.2 Agregados sin pandas | **Parcial + ratchet.** 9 escaneos sin cota encontrados, 1 corregido, 8 en allowlist decreciente con su motivo. |
| C3.3 Alertas de latencia | **Hecho.** `ApiLatencyP99High` y `PublicSurfaceSlow`, `for: 10m`. La latencia de navegador (SLO 3) la mide Speed Insights: alerta = acción humana en Vercel. |
| C3.4 Suite más rápida | **Hecho, detrás de interruptor.** `TF_TEST_SCHEMA_STRATEGY=truncate`. El default sigue en `schema`: cambiarlo sin poder ejecutar un test de integración es lo que AGENTS.md §4 prohíbe. |
| C3.5 Preview por PR (D27) | **No hecho.** Exige v2 O0.2 y provisionar un servicio en Render: no es una acción de este árbol. |
| C3.6 Hoja de costes | **Hecho** (`docs/COSTES.md`, entró con C9). |
| C3.7 Peso de `graphify-out/` | **Decidido y anotado** en AGENTS.md §1: se conserva, con disparador de revisión a los 50 MB. |

## C4 — Ingesta y calidad

| Ítem | Estado |
|---|---|
| C4.1 PSCP acotado (D24) | **Hecho** (`8d2f0b7`). 684 374 filas, 0,46 % con tecnología, el 96,9 % del corpus. Se **marca** (`analysis_universe='pscp_censo'`), no se purga. |
| C4.2 Republicaciones (D23) | **Hecho.** Regla en ADR-026: presentación esconde, métrica cuenta, la ficha avisa. |
| C4.3 Euskadi y Galicia por API | **No hecho.** Exige integrar dos APIs vivas y validar cobertura contra una muestra manual de 50 expedientes por fuente. |
| C4.4 Fechas imposibles | **Hecho.** 50 adjudicaciones anteriores a 1990, la mayoría `1899-12-30` (cero de la epoch de Excel). |
| C4.5 Umbrales calibrados | **Hecho**, por fuente. Ver corrección 4. |
| C4.6 Cuatro tablas de salud a dos | **No hecho.** Lleva migración y toca `scheduler/healthcheck.py`; la vista de compatibilidad no se puede probar sin Postgres. **Medido para quien lo retome**: `extracciones` la escribe `log_extraccion` (2 llamadas en `pipeline_runs`) y la lee `load_extracciones`, que **no la llama nadie** — es una tabla sin lector, y `healthcheck.py` nunca la consulta. |
| C4.7 Completitud por fuente | **Hecho.** PLACSP 100 % de `n_ofertas_recibidas`, PSCP 37 %, TED 0 %. |

## C5 — Conocimiento

Lo hecho, en `ccb6166` (v119, v120).

| Ítem | Estado |
|---|---|
| C5.1 Golden set de fichas | **No hecho.** Cuarenta pliegos con hechos esperados: etiquetado humano. |
| C5.2 Un solo selector de páginas | **No hecho.** Depende de C5.1: sin golden no hay forma de saber si la unificación empeora la ficha. |
| C5.3 Citas estructuradas (D29) | **Hecho.** Marcador `[doc:N p.M]` validado contra el contexto enviado; `sin_fuentes` se emite siempre; la respuesta **no** se reescribe. `page_number` se persiste al crear el chunk (v119). |
| C5.4 Feedback persistido | **Hecho** (v120). Hash con sal de servidor; texto solo con opt-in. |
| C5.5 Caché de respuestas | **Hecho.** Versión del prompt **derivada del prompt**, no un número a mano. |
| C5.6 Diccionario como dato (D28) | **No hecho.** Esfuerzo L: migración, edición desde `/ops`, preview de impacto y `filter_version` por hash. |
| C5.7 Versión de embeddings | **Hecho** (v119). Retrieval por versión vigente **con caída** a la anterior; nunca mezcla dos en la misma consulta. |
| C5.8 Clusters y proyectos | **No hecho.** Pide sesenta días de telemetría que aún no existen. |

## C6 — Colaboración y captura

**Ningún ítem empezado.** El stream depende de v2 S3 y S4, que no están
implementados: C6.2 necesita el outbox de v2 S4.1 para notificar la mención y
C6.3 el almacén de objetos de v2 S8.1. Los cuatro que no dependen de v2 —C6.1
(tareas), C6.4 (plantilla go/no-go), C6.5 (mi baja frente al mercado), C6.6
(notas) y C6.7 (exportar el pipeline)— llevan tres migraciones y superficie de
UI cuya red son los E2E.

## C7 — Frontend y accesibilidad

| Ítem | Estado |
|---|---|
| C7.1 Remediación axe | **No hecho.** Las cuatro reglas y los cuatro `test.fixme` exigen ver la aplicación corriendo. |
| C7.2 S5.8 | **Mitad.** La ficha pública entra en el barrido axe. El piso de cobertura de `src/app/**` **no**: `vitest run --coverage` vuelve a morir (sexto intento documentado en `vitest.config.ts`). |
| C7.3 Primer uso | **No hecho.** Los estados vacíos se verifican mirando la pantalla. |
| C7.4 `title=` a `Tooltip` | **Regla y ratchet puestos; migración no.** Ver corrección 1. `TooltipTrigger asChild` cambia el foco y el orden de tabulación, y eso se comprueba mirando. |
| C7.5 Ajustes en un sitio | **No hecho.** Mueve superficie autenticada entera; depende además de C2.1, C2.3 y C2.7, que ya están. |
| C7.6 Presupuesto de bundle | **Hecho.** `@next/bundle-analyzer` + `scripts/check_bundle_budget.py` sobre `route-bundle-stats.json`, con `bundle-budget.json` sembrado con 31 rutas medidas. |
| C7.7 Captura clara en la portada | **No hecho.** Generar los `.webp` exige el stack levantado; el propio `capturas-landing.spec.ts` ya dejó escrito que el `<source>` y los ficheros van en el mismo cambio. |
| C7.8 Ortografía castellana | **Cerrado + gate.** Ver corrección 2. |

## C8 y C9

**Completos** (`f0a8752`, `31551da`, `a73deb4`). C8 dejó `deprecate_route()` con
`Sunset`, el detector de cambios incompatibles (`scripts/check_api_breaking.py`,
recursivo sobre `Paginated[T] → items[] → T`), 29 fixtures de contrato al 85 % de
cobertura, idempotencia en las cuatro escrituras que faltaban y `MAX_PAGE_LIMIT`
universal. C9 dejó los seis ADR (027–032), los docs que el código desmentía, la
retención publicada desde constantes, el registro de tratamientos y los dos
generadores con `--check` en CI.

## Lo que bloquea al resto

Tres cosas, y ninguna es de código:

1. **Postgres.** Las migraciones v112–v120 no se han aplicado en ninguna sesión;
   las verifica el job `schema-migrations` de CI. Todo lo que dependa de probar
   una migración o la suite de integración está bloqueado en local.
2. **La aplicación corriendo.** C7.1, C7.3, C7.5 y C7.7 se verifican mirando la
   pantalla. Sin API ni datos sembrados no hay pantalla.
3. **Etiquetado humano.** C1.3 (30 pares), C5.1 (40 pliegos) y C5.8 (60 días de
   telemetría) piden dato que nadie ha producido todavía.
