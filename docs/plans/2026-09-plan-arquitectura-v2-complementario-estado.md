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

**Última actualización: 2026-09-08 (tercera pasada: fusión sobre `master`).**

## Resumen

«Parcial» significa que el ítem entrega valor pero **no** cumple todavía todos
sus criterios de aceptación, y la tabla de su stream dice cuál falta. Contarlo
como hecho sería la clase de optimismo que obligó a escribir este documento.

| Stream | Hecho | Parcial | No hecho | Total |
|---|---|---|---|---|
| C1 Datos maestros y semántica | 3 | 1 (C1.3, falta el golden) | 0 | 4 |
| C2 Cuentas y seguridad | 7 | 2 (C2.5 descarte, C2.8 medido y no aplicado) | 0 | 9 |
| C3 Plataforma y coste | 5 | 1 (C3.2 ratchet) | 1 (C3.5) | 7 |
| C4 Ingesta y calidad | 6 | 0 | 1 (C4.3) | 7 |
| C5 Conocimiento | 5 | 0 | 3 (C5.1, C5.2, C5.8) | 8 |
| C6 Colaboración y captura | **7** | 0 | **0** | 7 |
| C7 Frontend y accesibilidad | **4** | **1** (C7.4) | 3 (C7.1, C7.3, C7.7) | 8 |
| C8 API y contrato | 5 | 0 | 0 | 5 |
| C9 Documentación y proceso | 6 | 0 | 0 | 6 |
| **Total** | **48** | **5** | **8** | **61** |

## Tercera pasada (2026-09-08): la fusión sobre `master`

Las dos pasadas anteriores trabajaron sobre `17169ce9`. Mientras tanto `master`
mergeó #272 (plan de funcionalidades) y #274 (Ola 0 de v2 y seis streams de la
Ola 1), y ocupó `v103`–`v112`. Las catorce migraciones de este plan colgaban de
`v102`, así que el árbol fusionado tenía **dos cabezas Alembic** y dos ficheros
distintos llamados `v112_*`. Se renumeran a `v113`–`v126` y la cadena se engancha
a `v112_organization_capabilities`, que es lo que prescribe la nota de O0.5: el
número de un plan es indicativo y el real es el siguiente libre **en el momento
del merge**.

**Lo que la fusión desbloqueó.** C6.3 llevaba «no hecho» porque necesitaba el
almacén de objetos de v2 S8.1, y ese llegó con #274. Se implementa aquí, así que
C6 queda completo.

**Lo que la fusión rompió, y por qué ninguno era un test defectuoso.** Los 19
fallos que dejó eran sitios donde las dos ramas describían el mismo hecho de
forma distinta: `log_extraccion` retirada por C4.6 y todavía parcheada por tres
tests de `master`; un job nuevo (`webhook_reintentos`) que cambia el recuento del
registro; cinco `log_event` sobre el event loop; dos rutas resolviendo la
organización a mano contra una allowlist que está vacía a propósito; `/me/keys`
devolviendo un sobre donde el contrato esperaba un array; tres estilos inline y
cinco `title=` nuevos contra ratchets que solo bajan; una fixture `[{}]` que
dejó de cuadrar al volverse obligatorios los campos de `WebhookOut`; y el fake
del RAG sin el `embedding_version` de C5.7. Todos corregidos: la suite unitaria
queda en **3983 pasando, 0 fallando**.

**Lo que no se pudo verificar aquí**, y por qué —AGENTS.md §4: se reporta, no se
da por verde—: no hay Docker ni Postgres local en esta máquina, y la única
`DATABASE_URL` del entorno apunta a **producción**, que no se toca. Las
migraciones `v113`–`v127` y la suite de integración las verifica el job
`schema-migrations-postgres` de CI, que las **aplicó en verde**.

### Dos ítems que figuraban como hechos y devolvían 500

Y es la razón por la que este documento no dice «hecho» a la ligera. El fuzzing
de la API en CI encontró dos 5xx, y los dos eran bugs del propio plan:

1. **C2.2 apuntaba a una tabla que no existe.** La tabla se llama
   `organization_memberships` desde `v61`; seis sentencias del ciclo de vida de
   la organización escribían `organization_members`. `transfer-ownership` y
   `leave` devolvían **500** —solo cuando quien llamaba era realmente el owner,
   porque los demás recibían 403 antes de llegar al SQL— y el recuento de
   miembros del preview de borrado devolvía **-1 en silencio**, tapado por el
   `try/except` que está ahí para otra cosa.
2. **C2.1 pasaba una factoría de dependencia sin llamar.**
   `Depends(require_recent_session)` en vez de `require_recent_session()`:
   FastAPI inyectaba la función interna como contexto y
   `DELETE /me/sessions/{id}` daba 500 en **todas** sus llamadas.

Ninguno lo veían mypy ni ruff —uno vive dentro de una cadena SQL y el otro es
una función que se pasa donde cabe una función—, y los tests de esas rutas
mockean el repositorio. Los dos tienen ahora guardarraíl estructural
(`tests/test_tablas_citadas_existen.py` y
`tests/test_depends_factories_llamadas.py`), y el primero se verificó
reintroduciendo el typo para comprobar que lo detecta.

«El código existe» y «la ruta funciona» no son lo mismo, y este documento había
contado lo primero como lo segundo.

## Correcciones al plan, registradas

Un plan que no registra sus errores los repite (§0 del propio plan). Cuatro
afirmaciones suyas no sobrevivieron a la medición:

1. **«152 apariciones de `title=`» (hecho 24, C7.4).** El grep mezcla `title`
   como prop de componente —`<KpiCard title="…">`, que no genera atributo HTML y
   es la mayoría—, `title=` en tests, y `title=` sobre elemento nativo, que es el
   único caso del problema. Las «olas de ≥ 50» que pide el ítem no existen.

   **Y la corrección estaba mal (2026-09-08).** Decía «33 en 18 ficheros», y esa
   cifra también era corta: la regex del contador era `<tag[^>]*?title=`, y
   `[^>]` no puede cruzar el `>` de una flecha, así que un
   `<button onClick={() => …} title="…">` —la forma normal de un botón en este
   repo— no se contaba. ESLint sí los veía, porque mira el AST: el ratchet decía
   «verde» mientras `npm run lint` señalaba ficheros que el contador ni
   nombraba. Con el escaneo corregido —retroceder hasta el `<` saltando los
   bloques `{…}`— salían **39**; migrados los tres que escondía, quedan **36**.
   Una cifra que se mide con una herramienta distinta a la que la hace cumplir
   acaba divergiendo, y aquí divergió.
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
| C1.1 Importe con semántica (D21) | **Hecho** (`6b1490d`, v113). Tres columnas + `importe_tipo`; el histórico queda en `desconocido` y **no** se copia a `importe_base_sin_iva`. `bajas`/`pricing`/`escenarios-precio` declaran `base`. |
| C1.2 Maestro de órganos (D22) | **Hecho** (`048a0ea`, v114+v115). Patrón de `empresas`; DIR3 único parcial; lectura dual `clave_organo_sql`. **La migración no rellena**: el backfill de 706 k filas es una operación con ventana, no un `UPDATE` en migración. |
| C1.3 Predecesor y similares | **Hecho** (`efbb709`). `GET /licitaciones/{id}/similares`, `metodo ∈ {embedding, fts}` y `n`. **Pendiente**: el golden de 30 pares con precisión ≥ 0,8 exige etiquetado humano — generarlo con la misma regla que se quiere medir sería circular. |
| C1.4 Lotes de primera clase | **Hecho** (`6b1490d`). `LoteOut`, `exports/download?por_lote=true`. |

## C2 — Cuentas y seguridad

Todo en `70b3c37` (v116–v119) salvo lo indicado.

| Ítem | Estado |
|---|---|
| C2.1 Sesiones visibles | **Hecho.** `list_active_sessions` existía y no la llamaba nadie. |
| C2.2 Ciclo de vida de la organización | **Hecho** (ADR-030 §D). La salida anonimiza la autoría y **no** borra el trabajo compartido. |
| C2.3 Claves con autoservicio y tiers (D25) | **Hecho.** `api_key_tiers` existía desde `v28` sin que ninguna ruta leyera la columna. |
| C2.4 Webhooks con reintento | **Hecho.** El criterio, el SQL y la ruta de re-entrega ya estaban escritos; **faltaba la puerta**: `trigger_event` no dejaba nada `pending` y ningún job leía la cola. |
| C2.5 Vulnerabilidades con plazo | **Política escrita y triaje hecho** (2026-09-08). `scripts/check_security_alerts.py` convierte la medición en un comando. Los tres avisos abiertos —dos altos, uno moderado— son **los tres fantasmas**: apuntan a `uv.lock`, que no está en el árbol, y el manifiesto vivo fija `cryptography==50.0.0` (el aviso se parchea en `49.0.0`) o no declara el paquete (`transformers`, solo transitiva del extra `[ml]`). **Falta**: descartarlos con motivo en la pestaña de seguridad — esta sesión no cierra avisos de seguridad por su cuenta. |
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
| C3.5 Preview por PR (D27) | **No hecho**, y el motivo es más concreto de lo que decía antes: el plan lo condiciona a «v2 O0.2 cerrado», y **O0.2 no está cerrado**. Su checklist humano vive en la cabecera de `render.yaml` con **seis casillas sin marcar**: el servicio se creó a mano por el dashboard y todavía no está vinculado al Blueprint, así que ese fichero describe el estado *deseado* y editarlo no cambia nada en Render. Escribir el workflow de preview contra un Blueprint sin vincular produciría configuración que nadie puede ejecutar y que puede chocar con el servicio manual. |
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
| C4.6 Cuatro tablas de salud a dos | **Hecho** (v125). Medido: `extracciones` era una tabla **sin lector** —`load_extracciones` no la llamaba ninguna ruta, job, script ni test— y `healthcheck.py` nunca la consultaba. Se retiran los cuatro escritores (`db/upsert.py`, dos en `pipeline_runs`, uno en el pipeline legacy) y v125 la renombra dejando una **vista** con el nombre antiguo: el histórico no se destruye y una consulta manual sigue funcionando, pero la vista no acepta `INSERT`, así que un escritor olvidado falla en voz alta. Queda el par `source_ingestion_health` + `ops_events`, con `extraction_runs` como detalle por pasada. |
| C4.7 Completitud por fuente | **Hecho.** PLACSP 100 % de `n_ofertas_recibidas`, PSCP 37 %, TED 0 %. |

## C5 — Conocimiento

Lo hecho, en `ccb6166` (v120, v121).

| Ítem | Estado |
|---|---|
| C5.1 Golden set de fichas | **No hecho.** Cuarenta pliegos con hechos esperados: etiquetado humano. |
| C5.2 Un solo selector de páginas | **No hecho.** Depende de C5.1: sin golden no hay forma de saber si la unificación empeora la ficha. |
| C5.3 Citas estructuradas (D29) | **Hecho.** Marcador `[doc:N p.M]` validado contra el contexto enviado; `sin_fuentes` se emite siempre; la respuesta **no** se reescribe. `page_number` se persiste al crear el chunk (v120). |
| C5.4 Feedback persistido | **Hecho** (v121). Hash con sal de servidor; texto solo con opt-in. |
| C5.5 Caché de respuestas | **Hecho.** Versión del prompt **derivada del prompt**, no un número a mano. |
| C5.6 Diccionario como dato (D28) | **Hecho** (v126). `tecnologias_keywords` manda y `config/keywords.py` queda como semilla y respaldo. `filter_version` sigue siendo el hash del **contenido vigente**, así que editar desde `/ops` cambia el linaje de las filas nuevas sin desplegar. Los patrones compilados dejan de congelarse al importar y se memoizan **por versión**, no por tiempo. Cada cambio se audita con su preview de impacto —expedientes que la keyword *añadiría*, no los que la mencionan— y con el `filter_version` de antes y de después. |
| C5.7 Versión de embeddings | **Hecho** (v120). Retrieval por versión vigente **con caída** a la anterior; nunca mezcla dos en la misma consulta. |
| C5.8 Clusters y proyectos | **No hecho.** Pide sesenta días de telemetría que aún no existen. |

## C6 — Colaboración y captura

El stream se dio por bloqueado «hasta v2 S3/S4» y **no lo estaba**: `pursuits`,
`pursuit_events` y `pursuit_comments` existen en este árbol desde v61/v83/v97.
Seis de siete, en v122–v124.

| Ítem | Estado |
|---|---|
| C6.1 Tareas de la oportunidad | **Hecho** (v122). `next_action` no se retira: se **deriva** de la tarea abierta más urgente, con un camino de escritura propio que no sube `version` ni escribe en el ledger — si lo hiciera, cerrar una tarea daría conflicto de concurrencia a quien editara la oportunidad en otra pestaña. |
| C6.2 Menciones en comentarios | **Hecho** (v124). Se guardan los `user_id`, no el nombre resuelto. Un nombre ambiguo no resuelve a nadie: notificar a la persona equivocada es peor que un fallo visible. **La entrega** de la notificación espera al outbox de v2 S4.1; `menciones_de_usuario` es la consulta que ese despachador usará. |
| C6.3 Adjuntos propios | **Hecho** (2026-09-08, `v127`). Estuvo bloqueado hasta que la fusión trajo el almacén de objetos de v2 S8.1. Lista blanca de tipos —no lista negra, que es una carrera que se pierde— con concordancia obligatoria entre tipo y extensión; tope de 25 MiB por fichero, duplicado como `CHECK` para que una ruta nueva que olvide validar choque contra la base; enlace de descarga firmado con la caducidad **dentro** de lo firmado, que devuelve **403 y no 410** —el fichero sigue ahí, lo que caducó es el permiso— y que **no** sustituye a la sesión. La subida va por **cuerpo crudo** con `X-Filename` y no por `multipart`: esa vía exigiría `python-multipart`, que D31 no pre-autoriza, para parsear un formato que aquí transportaría un campo. El binario se escribe **antes** que la fila (al revés, un fallo del bucket deja una descarga rota; así lo peor es un objeto huérfano) y el borrado va al revés por el mismo motivo. El opt-in del RAG es **por adjunto** y nace apagado; hoy la garantía es estructural —ningún camino de indexación alcanza la tabla, y hay test— y la columna es lo que permitirá levantarlo por fichero sin volver a migrar. Borrar la organización purga sus objetos **antes** de borrar las filas, y la advertencia previa los cuenta. |
| C6.4 Plantilla go/no-go (D30) | **Hecho** (v123). Cinco criterios fijos, pesos por organización, `riesgo` invertido. Solo se promedian los criterios puntuados —contar los ausentes como cero haría que media ficha dijera siempre «no go»— y la plantilla **señala, no bloquea**. |
| C6.5 Mi baja frente al mercado | **Hecho.** Solo `importe_base_sin_iva` con `importe_tipo = 'sin_iva'` (C1.1): mezclar bases daría una baja del 21 % que es el IVA. Los segmentos con menos de cinco ofertas salen con `suficiente: false` **y su `n`**. |
| C6.6 Notas en seguimientos | **Hecho** (v124). La nota es personal aunque el favorito sea de la organización: el filtro es solo `user_key`. |
| C6.7 Exportar el pipeline | **Hecho.** `exports/download?recurso=pursuits`; organización y fecha como **columnas**, no como preámbulo que rompería el CSV. |

## C7 — Frontend y accesibilidad

| Ítem | Estado |
|---|---|
| C7.1 Remediación axe | **No hecho.** Las cuatro reglas y los cuatro `test.fixme` exigen ver la aplicación corriendo. |
| C7.2 S5.8 | **Hecho** (2026-09-08). La ficha pública entra en el barrido axe, y el piso de `src/app/**` queda fijado **al valor medido**: 35.06 lines / 30.15 functions / 30.74 branches, con el buffer de ~3 puntos de siempre. El número no salió de esta máquina —el séptimo intento local murió como los seis anteriores— sino del `lcov` que publica el job `frontend` de CI, agregado por subárbol. La agregación se validó antes de fiarse de ella: el mismo método sobre `src/hooks/**` reproduce los 69.32 / 61.21 que vitest había reportado en ese run. `statements` se deja sin fijar a propósito: el `lcov` no lo lleva y derivarlo de `lines` sería inventarlo — en ese mismo run `hooks` lo tiene por encima de `lines` y el global por debajo. |
| C7.3 Primer uso | **No hecho.** Los estados vacíos se verifican mirando la pantalla. |
| C7.4 `title=` a `Tooltip` | **Regla, ratchet corregido y ocho migrados; el resto no.** Ver corrección 1, que a su vez estaba mal: el contador subcontaba (2026-09-08). De 39 reales quedan **36**. Migrados: `space-shell` a `<abbr>` —que es donde `title` sí es semántico, y además va dentro de un `<button>`, así que un tooltip ahí sería `nested-interactive`—; `estado-global-row`, `mercado-strip`, `eventos-feed` y `pursuit-comments` a `<Tooltip>`; y los tres `<button title=>` de `empresa-perfil` y `review-queue`, que son el caso limpio porque un botón ya es focusable. **Sin `tabIndex`**: ESLint (`jsx-a11y/no-noninteractive-tabindex`) tiene razón en que un `<span>` focusable que no hace nada al pulsarlo es otra violación, no una mejora — cambiar `title` por eso sería mover el problema. Lo que sí entregan los tooltips es el **táctil**, que es la mitad del reproche del ratchet. Los 36 que quedan están casi todos en celdas de tabla y heatmaps: hacerlos focusables cambia el orden de tabulación de la rejilla entera y eso se decide mirando la pantalla. |
| C7.5 Ajustes en un sitio | **Hecho.** El espacio nace con contenido real —por eso el plan lo puso detrás de C2—: sesiones, claves con su tier y preferencias no tenían pantalla ninguna. `/mi-cuenta` se absorbe como `?vista=cuenta` y **su `page.tsx` se retira**: el propio repo prohíbe dejar una página bajo un 308 (`titulos-de-pagina.test.ts`), porque se compila y no se ejecuta jamás. Su test cambia de sujeto al componente que sí se monta. Los tests de espacios pasan a **derivar** los recuentos en vez de fijarlos, que es lo que el ítem pedía. |
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

## Métricas de cierre, medidas el 2026-09-08

La §4 del plan pide que estas cifras las reproduzca un comando y que **no** se
anoten a mano en aquel fichero. Aquí sí, con el comando al lado, porque un
documento de estado sin números es una opinión.

| Métrica | Objetivo | Hoy | Comando |
|---|---|---|---|
| `title=` nativo en `.tsx` | 0, por olas | **36** (eran 39 al corregir el escaneo) | `python scripts/check_title_attrs.py` |
| Estilos inline en JSX | ratchet que solo baja | **94** (97 tras la fusión) | `python scripts/check_inline_styles.py` |
| Ortografía de la UI | 0 | **0** | `python scripts/check_ortografia_ui.py` |
| Operaciones de API opacas | 0 | **0** | `python scripts/check_openapi_contract.py` |
| Cobertura de fixtures de contrato | ≥ 80 % | **82 %** (31/38) | `python scripts/check_contract_fixtures.py` |
| Escaneos analíticos sin cota | 0 fuera de la allowlist | **0**, con 8 excepciones declaradas | `python scripts/check_analytics_unbounded.py` |
| Avisos de seguridad abiertos fuera de plazo | 0 | **0** — los 3 abiertos son fantasmas | `python scripts/check_security_alerts.py` |
| Cabezas Alembic | 1 | **1** (`v127_pursuit_attachments`) | `alembic heads` |
| Suite unitaria de Python | verde | **3983 pasan, 0 fallan** (más los guardarraíles nuevos) | `pytest -m "unit and not slow"` |
| Typecheck de Python | limpio | **limpio** (929 ficheros) | `mypy .` |
| 5xx en el fuzzing de la API | 0 | **2 encontrados y corregidos** | job `API contract fuzzing` |
| Lint del frontend | 0 errores | **0** (7 avisos preexistentes) | `npm run lint` |
| Typecheck del frontend | limpio | **limpio** | `npm run typecheck` |
| Cobertura de `src/app/**` | piso medido | **35.06 / 30.15 / 30.74** (lines/funcs/branches), piso en 32/27/27 | `lcov` del job `frontend` |

Las que siguen sin poder medirse aquí —cobertura de `organo_id`, tamaño de la
imagen, duración de `test-integration`, `importe_tipo` nulo— necesitan Postgres o
el runner de CI, y están en la lista de bloqueos.

## Lo que bloquea al resto

Cinco cosas, y ninguna es de código. Actualizado el 2026-09-08.

1. **Postgres.** Las migraciones v113–v127 no se han aplicado en ninguna sesión
   local; las aplicó en verde el job `schema-migrations-postgres` de CI. Todo lo
   que dependa de probar una migración o la suite de integración está bloqueado
   aquí: en esta máquina no hay Docker ni cluster local, y la única
   `DATABASE_URL` del entorno apunta a **producción**, que no se toca para correr
   tests que crean y borran schemas.

   Consecuencia menor pero anotable: **`docs/database-schema.md` se queda en
   `v112`**. Lo genera `scripts/gen_schema_doc.py` leyendo el catálogo de una
   base ya migrada, así que regenerarlo exige la base que aquí no hay. Editarlo
   a mano sería peor —su cabecera dice «no editar a mano» y el fichero es el
   volcado de un catálogo, no una descripción—; se regenera en la primera sesión
   con Postgres delante.
2. **La aplicación corriendo.** C7.1, C7.3 y C7.7 se verifican mirando la
   pantalla. Sin API ni datos sembrados no hay pantalla.
3. **Etiquetado humano.** C1.3 (30 pares), C5.1 (40 pliegos) y C5.8 (60 días de
   telemetría) piden dato que nadie ha producido todavía. C5.2 cuelga de C5.1:
   sin golden no hay forma de saber si unificar el selector empeora la ficha.
4. ~~**La cobertura del frontend, en esta máquina.**~~ **Resuelto por otra vía
   (2026-09-08).** El séptimo intento local murió como los seis anteriores, pero
   el número no tenía por qué salir de aquí: el job `frontend` de CI corre la
   cobertura entera y publica su `lcov` como artefacto. Descargado y agregado
   por subárbol da `src/app/**` en lines 35.06 / functions 30.15 / branches
   30.74, y la agregación se validó reproduciendo con el mismo método los
   69.32 / 61.21 de `src/hooks/**` que vitest había reportado en ese run.
   C7.2 queda cerrado. El `statements` de `src/app/**` sigue sin fijarse porque
   el `lcov` no lo lleva y derivarlo sería inventarlo — lo publicará vitest la
   primera vez que el umbral corra.
5. **O0.2 sin cerrar.** El Blueprint de Render no está vinculado al servicio: seis
   casillas sin marcar en la cabecera de `render.yaml`. C3.5 lo tiene como
   prerrequisito explícito.

Y una acción de un minuto que no es de código pero tampoco es un bloqueo:
**descartar los tres avisos fantasma** de la pestaña de seguridad (C2.5). El
triaje ya está hecho y publicado en `docs/SECURITY.md`.
