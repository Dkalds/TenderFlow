---
tags: [plan, arquitectura, producto, estado]
---

# Plan 2026-10 — del piloto al uso: que llegue, que sea verdad, y menos superficie

Redactado el 2026-10-26 sobre `master` = `a365e773`. Sucede como marco de
prioridades a [2026-09-plan-arquitectura-v2.md](2026-09-plan-arquitectura-v2.md)
y a [2026-09-plan-salida-al-mercado.md](2026-09-plan-salida-al-mercado.md): no
redefine sus criterios, decide **en qué orden** se ejecuta lo que queda y **qué
se deja de hacer**.

**Estado: EN EJECUCIÓN desde el 2026-10-26.** El propietario aceptó ese día las
recomendaciones de D50–D58 y autorizó escribir las migraciones de V1 y de la
fase 3 de `user_id`, los cambios de CI y la subida de pines. Lo entregado está
en §8; lo que queda es, sobre todo, acción del propietario (§7).

Convención de los planes anteriores: «hecho» es código en el árbol con pruebas
verdes; «parcial» entrega valor sin cumplir todos sus criterios; **«acción del
propietario»** es algo que un agente no puede o no debe ejecutar (paneles de
Render, Vercel, Supabase o GitHub; migraciones; secretos; etiquetado — AGENTS.md
§6). Las cifras llevan fecha y fuente.

---

## 1. Diagnóstico

### 1.1 Lo que dice producción (2026-10-26)

Fuente: MCP interno de solo lectura ([ADR-036](../adr/ADR-036-acceso-interno-por-mcp.md))
y Vercel Web Analytics por ruta.

| Indicador | Valor |
|---|---|
| Usuarios / organizaciones / membresías | 12 / 14 / 15 |
| Usuarios distintos con inicio de sesión al mes (`access_log`, jul–oct) | 4, 1, 3, 3 |
| Visitantes de la consola en 30 días (Vercel; cuenta dispositivos, equipo incluido) | ~61 |
| Operaciones de la API ([STATUS.md](../STATUS.md)) | 306 |
| Oportunidades / con resultado | 16 / 9 |
| Reglas de vigilancia (`watchlist_rules`) | **0** |
| Webhooks · puntuaciones GO/NO-GO · votos al asistente | **0 · 0 · 0** |
| Cuentas objetivo · contratos en cartera | 1 · 1 |
| Organizaciones con NIF · con certificaciones | 4 · 5 filas |
| Licitaciones abiertas con plazo vigente | 768 |
| … con documentos descargados · con ficha del pliego | 689 · **82 (11 %)** |
| `licitaciones` con `importe_tipo` desconocido o nulo | 37.813 de 88.943 (42 %) |

El uso por ruta está en [UX_AUDIT.md](../UX_AUDIT.md#uso-real-por-ruta-pageviews-de-vercel-2026-09-25-a-2026-10-25):
`/resumen` y `/detalle` concentran el uso; la web pública indexable
(`/licitaciones/[ccaa]/[slug]/[ref]`, `/cpv/[codigo]`) recibió 2 y 1 visitas en
30 días.

### 1.2 Lectura

1. **La promesa central no llega.** El producto vende alertas, pero (a) la API
   no envía ningún correo —ítem P1 «Recuperación de contraseña», punto 1— y (b)
   el resumen diario sale de las reglas de vigilancia
   ([services/email_digest.py](../../services/email_digest.py)), y hay cero.
   Aunque el correo funcionara mañana, nadie recibiría nada.
2. **El diferenciador casi no se ve.** La ficha del pliego cubre el 11 % de lo
   abierto porque `PLIEGO_FACTS_ENABLED` está apagada y solo se extrae al abrir
   una oportunidad.
3. **El dato tiene defectos que un cliente detectaría.** Expedientes de órganos
   distintos que se pisan (P1 de identidad PLACSP, fase A hecha), el 42 % de los
   importes sin base conocida, y un clasificador servido que da probabilidad
   ≥ 0,69 al 60 % de la población.
4. **La superficie va muy por delante del uso.** Hay 306 operaciones y unos 15
   espacios para un piloto de tres usuarios activos al mes; las funciones de
   equipo y de integración (webhooks, matriz GO/NO-GO, cuentas, cartera) tienen
   uso cero o uno.
5. **El coste de proceso es alto para un mantenedor.** Unos veinte controles
   automáticos, ratchets que llevan meses congelados y un backlog de casi 2.000
   líneas que su propia regla llama ilegible.

La conclusión es que **el cuello de botella no es la arquitectura**. Es que el
valor no llega al usuario y que el dato no siempre es fiable. El plan ordena el
trabajo en ese sentido.

---

## 2. Decisiones previas (D50–D58)

| Id | Decisión | Recomendación | Estado |
|---|---|---|---|
| D50 | **Foco de piloto.** Hasta cumplir el criterio de salida de §5, no se añade superficie nueva (endpoint, espacio, pantalla) que no sirva al bucle de §3, Ola 2. | Sí. La lista `NUEVAS` de `scripts/check_api_surface.py` cita este plan en cada alta. | pendiente |
| D51 | **Destino de la telemetría.** Los 23 eventos de `web/src/lib/analytics.ts` se pierden (Vercel Hobby responde `402`). | Treinta días con pageviews por ruta + `http_requests_total` por handler, sin coste ni superficie nueva; revisar después si hace falta medir acciones. | pendiente |
| D52 | **Ficha nocturna.** Priorizar lo abierto que casa con alguna regla (B2) y fijar un tope de gasto mensual en [COSTES.md](../COSTES.md) §5.1. *Corrección del 2026-10-26:* `PLIEGO_FACTS_ENABLED` ya era `true` desde el 2026-08-14 (25 fichas por noche); el 11 % venía de un selector que no filtraba por «abierta», no de la variable. | Sí, con tope. | aceptada; falta el tope |
| D53 | **Alerta por defecto.** Al completar el perfil de una organización se crea una regla de vigilancia a partir de sus tecnologías, CPV y CCAA, editable y con baja en un clic. | Sí. | pendiente |
| D54 | **GO/NO-GO.** El checklist asistido (`cumple | no_cumple | desconocido`, ya en [services/go_no_go.py](../../services/go_no_go.py)) pasa a ser la vista principal de la oportunidad; la matriz ponderada queda secundaria y se retira si sigue sin uso a los 30 días de R4. | Sí. | pendiente |
| D55 | **Señal del clasificador.** Mientras el golden set no cumpla su gate (27 etiquetados frente a ≥ 60 en el holdout, 2026-10-25), `ml_proba` del `sap_classifier` no se muestra como señal ni ordena el Radar; quedan palabras clave + etiquetado LLM + señal del pliego. | Sí. | pendiente |
| D56 | **Identidad PLACSP fase B.** Ventana con la ingesta parada para la re-key y la reingesta de los 22 ZIP ([RFC](../rfc/2026-10-24-rfc-identidad-placsp-organo-expediente.md), `approved`). | Fecha acordada; ver V1. | pendiente |
| D57 | **Web pública.** Tres visitas en 30 días: o se mide su indexación (Search Console) y se decide invertir en ella, o se congela sin crecer. | Medir antes de tocar. | pendiente |
| D58 | **IP del cliente.** Opción del [RFC](../rfc/2026-10-24-rfc-ip-del-cliente-tras-vercel-y-render.md) (`draft`). | Opción B: cabecera secreta que añade Vercel y verifica la API en tiempo constante. | pendiente |

---

## 3. Olas

Cada ítem dice quién lo ejecuta. **Agente** = código en rama propia con PR;
**propietario** = acción fuera del repo o que exige OK según AGENTS.md §6. Donde
un ítem ya existe en el backlog, el criterio de aceptación es el suyo y aquí
solo se cita.

### Ola 0 — Que funcione lo que ya está prometido (días)

| Id | Qué | Quién | Criterio | Backlog |
|---|---|---|---|---|
| O0.1 | Credenciales de correo en la API de Render y un reset de contraseña de extremo a extremo | propietario | El criterio (1) del ítem; en el log, `email_backend_not_configured` deja de aparecer | P1 «Recuperación de contraseña» (1) |
| O0.2 | IP del cliente según D58 | propietario (secreto compartido en Vercel y Render) + agente (verificación en `api/middleware.py`, retirar `api/diagnostico_proxy.py`) | Dos usuarios en redes distintas dan `client_ip` distintos en `http_request`; cuotas de login y recuperación por persona | P1 «Recuperación de contraseña» (2) |
| O0.3 | Suspender o borrar el servicio `TenderFlow-1` de Render | propietario | No aparece activo en el panel | P1 «[Ola 1 · S5]», nota del 2026-10-24 |
| O0.4 | Reencolar los ~2.400 documentos DOCX/ODT/ZIP que ya se leen | propietario | `make reencolar-documentos APLICAR=1` según [el runbook](../runbooks/documentos-reencolar.md); la cobertura de documentos de lo abierto sube y se anota | P2 «[Ola 1 · S8]» |
| O0.5 | `SENTRY_DSN` en la API y check externo del latido | propietario | Los criterios de sus ítems | P2 «Sentry», P2 «latido» |
| O0.6 | Revisar y revocar las claves de API sin dueño; aprobar el `CHECK … NOT VALID` | propietario | Las del ítem | P2 «claves de API sin dueño» |

**Salida de la Ola 0:** el correo sale, el rate limiting distingue personas y
no queda ningún servicio fantasma contra la base de producción.

### Ola 1 — Verdad del dato (semanas 1–4)

| Id | Qué | Quién | Criterio | Backlog |
|---|---|---|---|---|
| V1 | Fase B de la identidad PLACSP: rellenar `organo_ref_fuente`, re-key con sus guardas (incluidos `domain_events.aggregate_id` y `licitaciones_id_anterior`), escritores con `clave_placsp` y reingesta | agente (código y migración) + propietario (OK de la migración, ventana de D56, `migrate.yml`) | Los del RFC; `scripts/inventario_pisadas_placsp.py` da 0 filas sin órgano antes y 0 pisadas después | P1 «La identidad de PLACSP no incluye el órgano» |
| V2 | **Una sola reingesta, cuatro arreglos.** La reingesta de V1 se planifica para recoger también la base del importe (`importe_tipo`, `importe_base_sin_iva`, `importe_con_iva`), las condiciones CODICE del histórico (umbrales de solvencia) y los arreglos del parser del 2026-10-25 (`provincia`, ceros a NULL, `fecha_publicacion`) | agente (orden de pasos y verificación) + propietario (`scrape-bulk.yml`) | Tras la reingesta: `importe_tipo` desconocido o nulo por debajo del 10 % en filas de PLACSP; umbrales de solvencia económica no nulos donde la fuente los publica; consultas de verificación anotadas aquí con fecha | P2 «condiciones oficiales de CODICE», [ADR-032](../adr/ADR-032-semantica-del-importe-y-maestro-de-organos.md) |
| V3 | Aplicar D55: la UI y el Radar no usan `ml_proba` del `sap_classifier` hasta que el golden cumpla | agente | Ninguna pantalla ni orden del Radar lee esa columna mientras no haya versión activa que haya pasado el gate; test que lo fija | P1 «sap_classifier», P2 «El corpus de PSCP ahoga…» |
| V4 | Etiquetar el golden set hasta su gate | propietario ([runbook](../runbooks/etiquetado-ti.md)) | ≥ 60 en el holdout y ≥ 10 por clase en «CPV 48/72 sin keyword» | P1 «Ampliar el golden set» |

**Salida de la Ola 1:** ninguna licitación pisa a otra, la mayoría de los
importes declaran su base y ninguna pantalla enseña una probabilidad que no se
puede defender.

### Ola 2 — El ciclo central: me entero → decido → preparo (semanas 3–8)

Puede empezar en paralelo a la Ola 1: no toca la clave de `licitaciones`.

| Id | Qué | Quién | Criterio |
|---|---|---|---|
| B1 | **Alerta por defecto (D53).** Al guardar las tecnologías de la organización (`OrganizationSettings`, [shared/dto/organizaciones.py](../../shared/dto/organizaciones.py)) se crea con `services/watchlist_rules.py::create_rule` una regla diaria por organización si no tiene ninguna. Sin endpoint nuevo: lo hace el servicio al guardar ajustes. | agente | Toda organización con tecnologías tiene ≥ 1 regla; test de integración; la regla se ve y se edita en `/mi-watchlist` |
| B2 | **Ficha para lo que importa (D52).** `TenderFactSheetsRepository.list_pending_licitaciones` ([db/repositories/tender_fact_sheets.py](../../db/repositories/tender_fact_sheets.py)) prioriza, después de las oportunidades abiertas, las licitaciones abiertas con plazo que casan con alguna regla de vigilancia; el propietario enciende `PLIEGO_FACTS_ENABLED` | agente + propietario (variable y tope de gasto) | ≥ 80 % de las abiertas que casan con alguna regla tienen ficha en menos de 48 h desde que se descargó su pliego; gasto mensual medido y anotado en COSTES.md |
| B3 | **El resumen como producto.** El correo diario de [services/email_digest.py](../../services/email_digest.py) incluye por licitación plazo, importe base sin IVA (o «base desconocida»), los requisitos de solvencia de la ficha y el veredicto del checklist frente a la capacidad de la organización, con enlace a la ficha | agente | Golden de plantilla con y sin ficha; un envío real a una cuenta de prueba tras O0.1 |
| B4 | **Checklist asistido como primera vista (D54).** La oportunidad abre en el checklist, rellenado con la ficha y [db/repositories/organization_capabilities.py](../../db/repositories/organization_capabilities.py); `desconocido` cuando falta el dato, nunca `cumple` sin evidencia (ADR-014) | agente | Las reglas de S2 del plan v2; E2E del recorrido |
| B5 | **Primeros pasos que llevan al valor.** Los tres pasos de [web/src/components/onboarding/pasos.ts](../../web/src/components/onboarding/pasos.ts) pasan de «perfil de scoring / regla / pursuit» a «capacidad de la organización (NIF, certificaciones, facturación) / revisa tu alerta / abre tu primera oportunidad desde el resumen» | agente | Tests de `primeros-pasos`; caso de uso actualizado en [casos-de-uso.md](../casos-de-uso.md) |
| B6 | **Cerrar el resultado sin trabajo manual.** Verificar con datos que la adjudicación detectada por NIF cierra la oportunidad ([services/pursuit_awards.py](../../services/pursuit_awards.py)) en las organizaciones con NIF, y que la calidad del Radar por banda llega a N suficiente | agente (consulta y, si falla, arreglo) | Las 9 oportunidades con resultado y las que lleguen se explican por NIF o por cierre manual, contado |

**Salida de la Ola 2:** cada organización piloto recibe cada mañana un correo
con lo que encaja con ella, con qué pide el pliego y si cumple, y llega a la
oportunidad en un clic.

### Ola 3 — Medir y recortar (desde el día 30 de la Ola 0)

| Id | Qué | Quién | Criterio | Backlog |
|---|---|---|---|---|
| R1 | Treinta días de uso según D51: pageviews por ruta y `make inventario-uso` con `http_requests_total` | propietario (exportar o dar lectura) + agente (tabla) | Tabla de espacios y de operaciones sin llamadas en UX_AUDIT.md | P2 «La telemetría de producto» |
| R2 | Una decisión escrita por cada espacio o vista por debajo del 2 % y por cada operación sin llamadas: se queda, se fusiona o se retira. Candidatos ya visibles: webhooks, cuentas objetivo, cartera, Dirección, previsiones y clústeres de analítica, la matriz GO/NO-GO (D54) | agente + propietario (decisión) | `api/superficie_congelada.txt` encoge; cada retirada con su caso de uso actualizado |
| R3 | Web pública según D57 | propietario | Decisión anotada con el dato de indexación |

### Ola 4 — Plataforma y proceso (continuo y oportunista)

No abre frentes nuevos: **termina lo empezado** y reduce el coste de mantener.

- **Terminar migraciones a medias:** fase 3 de `user_key` → `user_id` hasta
  ratchet 0 ([ADR-030](../adr/ADR-030-identidad-user-id-y-oidc.md)); fase 2 de
  las fechas `timestamptz` (P3 «Pasar las fechas de `text` a `timestamptz`»);
  ratchet de productores fuera del despachador del outbox (P2 «[Ola 1 · S4]»).
- **Pines:** P2 «Desbloquear los pines» (FastAPI, suelo de Python, una fuente de
  dependencias). Exige OK de dependencias (§6).
- **Proceso:** P3 «Agrupar la veintena de gates stdlib», P3 «Decidir qué hacer
  con los ratchets que llevan meses congelados» y P3 «El coste de leer el
  repo». Regla nueva propuesta: el backlog abierto no pasa de ~40 ítems; lo
  demás se archiva o se descarta con una línea de motivo.

---

## 4. Lo que este plan para o aplaza, y por qué

| Qué | Por qué | Cuándo se revisa |
|---|---|---|
| Encender contratos menores, plataformas agregadas y TACRC | Más volumen y ruido en la analítica antes de que el dato existente sea fiable | Tras la salida de la Ola 1 |
| Activar Microsoft (Entra ID) en producción | Ningún piloto lo ha pedido | Cuando lo pida una organización |
| Recrear el worker de Render | La API consume la cola ([ADR-028](../adr/ADR-028-cola-de-trabajo-y-worker.md) §G) y el volumen no lo justifica | Si B2 hace que la extracción compita con las peticiones (latencia p95 de la API) |
| Ampliar la API pública y el SDK | No hay consumidores externos: las claves sin dueño ya se rechazan | Cuando haya un integrador |
| Modelo de baja por lote, activar `baja_model` v2 y `retencion_model` v1 | Sin uso que lo pida y con el dato de importe a medio arreglar | Tras V2 |
| Búsqueda por significado más allá de su flag | `/investigador` tiene uso bajo | Con el dato de R1 |
| Entorno de staging | Coste frente a un piloto de tres usuarios | Al salir del piloto |
| Espacios o pantallas nuevos | D50 | Al salir del piloto |

---

## 5. Métricas y criterio de salida del piloto

**Métrica norte:** organizaciones con al menos una acción de valor a la semana
(abrir una ficha desde el resumen, mover una oportunidad o marcar el checklist).
Hasta D51 se aproxima con pageviews de `/oportunidades/[id]` y `/detalle` y con
`pursuit_events`.

| Métrica | Hoy (2026-10-26) | Objetivo al cerrar la Ola 2 |
|---|---|---|
| Correos de resumen enviados por semana | 0 | Uno diario por organización con regla |
| Organizaciones con ≥ 1 regla de vigilancia | 0 | Todas las que tengan tecnologías |
| Abiertas que casan con una regla y tienen ficha | 11 % de todas las abiertas | ≥ 80 % de las que casan |
| `importe_tipo` desconocido en PLACSP | 42 % de todo el corpus | < 10 % |
| Pisadas de PLACSP nuevas | se cuentan (`placsp_colision_expediente_total`) | 0 tras V1 |
| Operaciones de la API | 306 | Encoge tras R2 |

**Se sale del piloto** cuando al menos cinco organizaciones cumplen la métrica
norte durante cuatro semanas seguidas. Entonces se revisan D50 y la tabla de
§4.

---

## 6. Riesgos

- **V1 es la operación más arriesgada del plan:** cambia la PK de la tabla
  central. Mitigación: la del RFC (fase A ya en producción, alias y redirecciones
  308, ingesta parada, `plan` antes de `apply`) y una copia reciente de Supabase
  comprobada antes de la ventana.
- **B2 abre gasto LLM recurrente.** Mitigación: tope en COSTES.md, presupuesto y
  circuit breaker existentes, y medida en el primer mes antes de ampliar la
  selección.
- **B1 puede generar correos que nadie pidió.** Mitigación: regla visible y
  editable, `List-Unsubscribe` ya existente y frecuencia diaria (no inmediata)
  por defecto.
- **Recortar superficie con poco dato.** Treinta días de tres usuarios es una
  muestra pequeña: R2 decide **fusionar o congelar** antes que borrar cuando la
  evidencia sea débil, y nada se retira sin su caso de uso actualizado.

---

## 7. Acciones del propietario, juntas

- [ ] Tomar D50–D58 (§2).
- [ ] O0.1 credenciales de correo en Render y reset de extremo a extremo.
- [ ] O0.2 secreto compartido Vercel ↔ Render (tras D58).
- [ ] O0.3 suspender `TenderFlow-1`.
- [ ] O0.4 `make reencolar-documentos APLICAR=1`.
- [ ] O0.5 `SENTRY_DSN` y check externo del latido.
- [ ] O0.6 revocar las claves sin dueño y aprobar el `CHECK`.
- [ ] V1/V2 aprobar la migración de re-key, fijar la ventana y lanzar la reingesta.
- [ ] V4 etiquetar el golden set.
- [ ] B2 tope de gasto en COSTES.md §5.1 (la variable ya está a `true`).
- [ ] R1 exportar pageviews o dar lectura a `http_requests_total`.

Añadidas al ejecutar (2026-10-26):

- [ ] O0.2 generar `API_ORIGIN_SECRET`, ponerlo en Render y en Vercel, probar la regla de `web/vercel.json` en un preview y verificar con dos redes ([runbook](../runbooks/ip-del-cliente.md)).
- [ ] Antes del despliegue de esta rama: aplicar `v164` (con la ingesta parada, según su runbook) y `v165` con `plan` → `apply`. El código nuevo necesita los índices de `v165`.
- [ ] B1 `python scripts/crear_alertas_por_defecto.py` contra producción; si el recuento cuadra, `--aplicar`.
- [x] V2 la reingesta ascendente, un mes por job: `gh workflow run scrape-bulk.yml -f backfill_desde=2025-01`, y así sucesivamente ([runbook](../runbooks/reingesta-unica-placsp.md)).
- [ ] Tras el despliegue: confirmar en Prometheus que `http_requests_total` y `api_cost_estimate_total` siguen con el prefijo `/api/v1` (FastAPI 0.146 cambió `scope["route"].path`).

---

## 8. Estado de ejecución

Cada ítem anota aquí lo entregado al cerrarse (fecha, PR, evidencia). El
backlog remite a esta tabla en vez de copiar su estado.

Todo lo de abajo está en la rama `agente/plan-arquitectura-2026-10`. Los
controles sin base de datos pasan en esa rama (ruff, mypy strict, 9.262 tests
`unit`, gates, `gen_status --check`, lint, typecheck y vitest del frontend); los
tests de integración, los E2E y el fuzz quedan para CI.

| Id | Estado | Evidencia |
|---|---|---|
| D50 | **hecho** | Párrafo en AGENTS.md §0; `scripts/check_api_surface.py` exige `plan 2026-10, <ítem>` en cada entrada nueva de `NUEVAS` (`ANTERIORES_A_D50` solo encoge) |
| O0.1, O0.3–O0.6 | propietario | Sin cambios de código: ver §7 |
| O0.2 | **hecho en código**, falta producción | `API_ORIGIN_SECRET` (+ `_PREVIOUS`), `hmac.compare_digest` en `api/middleware.py`, cabecera desde `web/vercel.json` y del SSR; RFC `approved`; [runbook](../runbooks/ip-del-cliente.md). `api/diagnostico_proxy.py` sigue hasta verificar con dos redes |
| V1 | **hecho en código**, falta producción | `v164_identidad_placsp_rekey` (guardas antes de escribir, 31 columnas repuntadas, alias por fila; validada en sintaxis contra producción: 24.763 claves nuevas, todas distintas); `clave_placsp` en todos los escritores vía `scraper.codice_parser.acotar_por_organo`; `scripts/rellenar_organo_ref_placsp.py`; `resolver_id_externo` en todas las rutas y cuerpos; [ADR-038](../adr/ADR-038-clave-de-placsp-acotada-por-organo.md) y [runbook](../runbooks/rekey-placsp-organo.md). En producción está `v163` y no `v164` (`migrate.yml`, chequeo de solo lectura, 2026-10-30) |
| V2 | **hecho** (2026-11-01) | Reingesta ascendente de 2025-01 a 2026-10 del 2026-10-31 15:37 al 2026-11-01 02:19 UTC (~10 h 40 min): siete meses de uno en uno y cinco tramos de tres (`backfill_desde`/`backfill_hasta`, unos 50 min por tramo), todos en verde. Medido con el MCP sobre las 31.826 filas PLACSP reescritas: `importe_tipo` desconocido 0 (puerta < 10 %: cumple; todas `sin_iva` con base), `provincia = 'España'` 122 → 0, `fecha_publicacion` con hora 307 → 0, ceros en adjudicaciones 1.408 → 4 de 32.664 y en garantías 161 → 5 de 15.272. Solvencia económica con umbral: 1.501 de 17.072 licitaciones (la fuente no lo publica en todas). Quedan 5.550 filas PLACSP sin reescribir (5.364 con importe desconocido): las que el filtro TI ya no admite o no están en los ZIP. RFC de identidad: consulta 4 (clave vieja) 0; consulta 9 (expedientes que conviven) 0 → 872; consulta 10 (dedupe con canónica PLACSP) 2.134 `confirmed`; inventario 765 pares, 569 pisada segura. Limpieza de hijas de las 379 pisadas seguras (`rekey-placsp.yml` modo `limpiar-hijas`, run 41338467634): borradas 62 adjudicaciones, 28 lotes, 5 criterios, 15 garantías, 17 solvencias y 1.408 documentos (en ninguno la fila hermana tiene título parecido). Canónicas refrescadas después: 105.838; 1 pursuit a mover a mano: se creó el 2026-09-02 viendo el de la Junta de Gobierno del Ayuntamiento de Andorra (alojamiento web), que hoy es `placsp:31312320174992:1019/2024`, y cuelga de la fila de la Autoridad Portuaria de Avilés. La consulta 8 no cabe en los 15 s del MCP |
| V3 | **hecho** | `services/ml/senal_clasificador.py`. El Radar ya no leía `ml_proba` (el orden cambia 0); la cola de etiquetado y `/explain` declaran `senal_clasificador.validada=false` |
| V4 | propietario | Golden set: 27 etiquetados de ≥ 60 |
| B1 | **hecho en código** | `asegurar_alerta_por_defecto` al guardar los ajustes; una regla diaria por tecnología (≤ 5), idempotente y con baja definitiva; `scripts/crear_alertas_por_defecto.py` (dry-run, `--aplicar`). CU-04 |
| B2 | **hecho en código** | Nivel «abierta con plazo que casa con una regla» en `list_pending_licitaciones`; COSTES.md §5.1 con la fórmula y la cota (≤ 0,05 USD por ficha). Vacío hasta que existan reglas (B1) |
| B3 | **hecho en código** | `services/email_digest.py` + `services/digest_pliego.py`: plazo, base (ADR-032), hasta tres requisitos de solvencia y veredicto del checklist; golden `tests/fixtures/golden_resumen_diario.txt`. El envío real depende de O0.1 |
| B4 | **hecho** | La oportunidad abre en el checklist; la matriz pasa a `matriz-plegada.tsx` y solo se descarga al abrirla. CU-06 |
| B5 | **hecho** | Pasos `capacidad` / `alerta` / `pursuit` en `components/onboarding/pasos.ts`. CU-34 |
| B6 | **medido** | Datos de producción del 2026-10-26: 15 de las 16 oportunidades son de una sola organización (la 21). El cierre asistido avisó una vez (oportunidad 4, 2026-09-02) y nadie la cerró en 54 días; la «ganada» (7) y la «perdida» (10) se cerraron a mano sobre expedientes sin adjudicación (EV y PUB): la tasa de acierto no es un dato fiable todavía. Hubo 34 avisos `rule_match` hasta el 2026-09-23 y hoy 0 reglas: `watchlist_rules` no se audita, así que no consta quién las borró. Lo más usado es el MCP interno: 458 `mcp.consultar_sql` frente a 15 inicios de sesión en `audit_log` |
| R1 | parcial | Pageviews por ruta en UX_AUDIT.md; `http_requests_total` sigue sin lectura |
| R2, R3 | pendiente | Tras los 30 días de R1 |
| Ola 4 · `user_id` | **hecho en código** | `v165_user_id_fase3_tanda3`: `notification_reads`, `user_event_prefs` y `saved_filters` por `user_id`. `follows` y `pending_digests` van con `watchlist_*`. Ratchet 53 → 53. Aplicar **antes** del despliegue del código |
| Ola 4 · RGPD | **hecho** | El borrado del art. 17 se lleva también `notification_reads` (no lo hacía) |
| Ola 4 · S4 | **hecho** | El ratchet de productores del outbox lee el AST (antes se escapaba por un docstring); 4 productores |
| Ola 4 · gates | **hecho** | `make gates` / `make gates-deps` (`scripts/run_gates.py`) y CI los usa en vez de once pasos sueltos |
| Ola 4 · pines | **hecho en código** | fastapi 0.136.3 → 0.146.0, starlette 1.3.1 → 1.9.0, uvicorn 0.46 → 0.54; `api/rutas.py` lee la superficie anclada en `app.openapi()`; Python ≥ 3.13; `pyproject.toml` lee sus dependencias de `requirements.in`; sin `faiss`. OpenAPI idéntico byte a byte |
| Ola 4 · ratchets | medido | Propuesta de bajada barata por ratchet en el informe del 2026-10-26: capas −2, TID251 −4, `user_key` −1 y `_GRANDFATHERED_NON_DB_FILES` −3 |
