---
rfc: 2026-09-26-purga-pscp-sin-tecnologia
title: Purga de las licitaciones de PSCP sin señal tecnológica y puerta de ingesta endurecida
issue: (sin issue: petición directa del propietario, 2026-09-26)
author: agent:claude-code
date: 2026-09-26
status: review
---

## Por qué hace falta un RFC

`AGENTS.md` §5 lo exige para el **borrado irreversible de datos de
producción**. Esto borra del orden de 680.000 filas de `licitaciones` y, en
cascada, sus adjudicaciones, historial, eventos de contrato y scores. Este RFC
fija qué se borra, qué no y cómo se deshace si hiciera falta, **antes** de
ejecutarlo.

## Contexto

La PSCP (Plataforma de Serveis de Contractació Pública de Catalunya) publica
toda la contratación catalana: obras, limpieza, reactivos de laboratorio,
viajes. Hasta el 2026-09-09 el conector la guardaba entera y solo etiquetaba
`tecnologia` cuando el título casaba con el diccionario.

C4.1 (D24) decidió acotar el conector al universo tecnológico y **marcar** el
histórico como `analysis_universe = 'pscp_censo'` en vez de purgarlo. El filtro
del conector está en producción desde el 2026-09-09; el marcado **no se aplicó
nunca** (0 filas con `pscp_censo` el 2026-09-26).

Medido contra producción el 2026-09-26, solo lecturas:

| Filas de PSCP | Nº |
|---|---:|
| Total | ~685.500 |
| Con `tecnologia` | 3.268 |
| Sin `tecnologia`, `analysis_universe = 'pscp_observed'` | 581.748 |
| Sin `tecnologia`, `analysis_universe` **NULL** | 100.421 |

Las 100.421 con universo NULL son el síntoma visible: `technology_observed_sql`
trata NULL como `technology_observed`, así que **entran en el Radar, en las
cifras de cuentas y en los avisos** como si fueran tecnología. Hay
notificaciones de usuario enviadas sobre «Missatges WhatsApp Business», «Llavor
Sorgo Saphir» o «Treballs de pintura».

Y el filtro del conector, además, deja pasar falsos positivos: de las 3.268 con
`tecnologia`, 1.318 no traen ningún CPV 48/72, y muchas son keywords que en
Cataluña significan otra cosa (detalle en `scraper/connectors/pscp.py`,
`KEYWORDS_AMBIGUAS`): «SAP» son códigos de material del ICS y el Servei
d'Atenció Primària (609 filas), «Lightning» son cables de Apple,
«manteniment correctiu» son ascensores y alumbrado, «tallafocs» son telones
ignífugos, «PACS» es un reactivo de potabilización.

El propietario pide dos cosas: **depurar la base de datos** y que PSCP **deje de
traer** lo que no es tecnología.

## Decisión

### 1. Una sola puerta, en el conector y en la purga

`scraper.connectors.pscp.senal_tecnologica(titulo, cpv)` decide si un aviso de
PSCP es tecnología:

1. El título, con los apóstrofos tipográficos normalizados, casa con el
   diccionario vigente. («desenvolupament d’aplicacions», con U+2019, es como
   escribe la PSCP; el diccionario usa el apóstrofo recto y no casaba nunca).
2. Si **todo** lo que casó son keywords ambiguas y el CPV existe sin ningún
   código 48/72, se descarta. Sin CPV, o con una sola keyword no ambigua, entra
   como antes: los contratos menores traen CPV absurdos (licencias de Office 365
   codificadas como obra de puentes) y una keyword de fabricante es mejor señal.

El conector la aplica en `parse` y cuenta el descarte nuevo
(`pscp_keyword_ambigua_sin_cpv_ti`) junto a `pscp_sin_senal_tecnologica` en el
resumen del run.

### 2. La purga reevalúa, no filtra por columna

`scripts/purgar_pscp_sin_tecnologia.py` recorre PSCP entera y aplica **la misma
función** a cada fila. No borra por `tecnologia IS NULL` porque esa columna se
escribió con el diccionario de su día: hasta el 2026-09-14 no había términos en
catalán, y una muestra de producción da ~0,4 % de las filas sin etiqueta que
hoy **sí** son TI («Plataforma d'administració electrònica», «serveis de
desenvolupament de programari»). Esas **se quedan**.

| Caso | Acción |
|---|---|
| Admitida, etiquetas iguales | Nada |
| Admitida, etiquetas distintas o sin `analysis_universe` | Conservar y contar como *desactualizada* |
| No admitida | Borrar, con cascada y referencias blandas |
| No admitida con trabajo de usuario | Conservar y contar |

Las desactualizadas **no se reetiquetan desde la purga**: `tecnologia` tiene un
solo escritor, el upsert de ingesta, y `tests/test_dedup_guardrail.py` prohíbe
un `UPDATE licitaciones SET tecnologia` en producción (es el clobber que T3
cerró). Las corrige la reingesta del paso 5 del procedimiento, que además rellena
el `analysis_universe` que les falte (`COALESCE` del upsert).

«Trabajo de usuario» es una referencia desde `pursuits`, `contratos_cartera`,
`watchlist_items`, `follows` (seguir), `etiquetas_aplicadas` u
`organization_references`; también `resoluciones_recurso`, cuya FK no tiene
`ON DELETE`. Se recalcula dentro de la transacción de cada lote.

Se van con la fila: por `ON DELETE CASCADE`, `adjudicaciones`,
`licitaciones_history`, `contrato_eventos`, `licitacion_tecnologia_score`,
`licitaciones_duplicados`, `lotes`, `documentos` (0 de PSCP),
`tender_fact_sheets`, `predicciones_*` y `licitacion_tecnologia_pliego`; a mano,
`user_notifications`, `pending_digests` y los descartes (`follows` con
`kind='descartar'` y `radar_dismissals`, los dos para no romper la paridad).

### 3. El marcado `pscp_censo` se retira

`scripts/backfill_pscp_censo.py` y su SQL salen del árbol: nunca se ejecutaron y
contradecirían esto.

## Alternativas descartadas

- **Marcar en vez de borrar (C4.1).** Deja la basura dentro: la base de datos
  sigue midiendo 700.000 filas para servir 3.000, y cualquier lectura que olvide
  el predicado de universo la vuelve a enseñar — que es exactamente lo que pasa
  hoy con las 100.000 de universo NULL.
- **Borrar por `tecnologia IS NULL`.** Rápido y en SQL, pero tira TI real
  etiquetada con un diccionario viejo.
- **Corroborar siempre con CPV (también las keywords no ambiguas).** Tiraría
  licencias de Oracle, Azure u Office 365 con CPV equivocados, que en contratos
  menores de PSCP son frecuentes.

## Reversibilidad

El dato es público. `python -m scraper.connectors.pscp --desde AAAA-MM-DD`
reingiere desde cualquier fecha, y la reingesta pasa por la misma puerta. Lo que
no vuelve igual es lo derivado (historial de cambios, eventos de contrato,
enlaces de dedupe), que se recalcula al reingerir.

## Pregunta abierta para el propietario

Unas **30.500 filas** de PSCP sin keyword tienen CPV 48/72 (software y servicios
TI): licencias de STATA o Autodesk, renovaciones de dominio, pero también «Servei
consultoria implantació CRM» o «Manteniment aplicacions informàtiques». Con D24
tal cual, **se borran** (salvo las que el diccionario de hoy reconoce). PLACSP
las conserva como `cpv_ti_universe`. El dry-run las cuenta aparte
(«de ellas con CPV 48/72») con ejemplos; si se prefiere conservarlas, es añadir
esa regla a `senal_tecnologica` antes del `--apply`, o reingerirlas después.

## Procedimiento

Todo se ejecuta desde el workflow manual `.github/workflows/purga-pscp.yml`
(`DATABASE_URL` de producción, `concurrency.group: scrape` para no solaparse
con la ingesta): sin marcar `apply` es el dry-run del paso 1, y con `apply` y
`reingerir_desde` hace los pasos 4 y 5 en el mismo job. Desde una máquina con
acceso a la BD valen los mismos comandos:

1. `python scripts/purgar_pscp_sin_tecnologia.py` (dry-run): balance por acción
   y motivo, protegidas y ejemplos por clase. No escribe nada.
2. Revisar el balance y los ejemplos; decidir la pregunta abierta.
3. `make audit-truth-check` (línea base).
4. `python scripts/purgar_pscp_sin_tecnologia.py --apply`. Lotes de 500
   borrados por transacción; reanudable si se corta. Al terminar refresca la
   vista de canónicas y avisa a las cachés.
5. Reingerir PSCP entera para refrescar las etiquetas desactualizadas:
   `python -m scraper.connectors.pscp --desde 2000-01-01` (recorre el dataset
   completo, ~1,9 M filas en páginas de 1.000; lo que no pasa la puerta se
   descarta sin escribir). Mejor fuera de la ventana del `scrape-daily`.
6. `VACUUM (ANALYZE) licitaciones, adjudicaciones` (o esperar al autovacuum) y
   `make audit-truth-check` otra vez; anotar el delta aquí y pasar el estado a
   `implemented`.
