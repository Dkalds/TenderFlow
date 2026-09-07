---
tags: [spike, decision, codice, hitos]
---

# Spike D32 — ¿publica CODICE los hitos del procedimiento?

**Resultado: NO. Cobertura medida 0 %. F2.1 no se construye.**

D32 del [plan de funcionalidades 2026-09](2026-09-plan-funcionalidades.md)
condicionaba F2.1 («hitos del procedimiento»: apertura de sobres, fin del
plazo de consultas, visita obligatoria, fecha prevista de adjudicación) a que
un spike midiera la cobertura real de esos eventos en el ATOM de la Plataforma
y a que superara el **30 %**. Este documento es ese spike.

## Método

Se descargaron páginas del feed de sindicación en vivo que ya consume el
scraper (`PLACE_LIVE_ATOM_URL`, sindicación 643, «licitaciones y perfiles de
contratante completo 3») y se contó, sobre cada `<entry>`, la presencia de los
elementos CODICE que darían cada hito. La detección es por nombre de elemento
con cualquier prefijo de espacio de nombres (`<\w+:Nombre[ >]`), así que no
depende de qué alias use la Plataforma en cada documento.

Medido el **2026-09-06**.

| Página | Entradas |
|---|---|
| `licitacionesPerfilesContratanteCompleto3.atom` (cabecera del feed) | 235 |
| `licitacionesPerfilesContratanteCompleto3_20260903_201337.atom` | 500 |
| **Total** | **735** |

Una tercera página fechada (`..._20260902_121216.atom`) devolvió 521 bytes sin
entradas y se descarta del cómputo en vez de contarla como 0 %: una página
vacía no es una muestra de que no se publiquen hitos, es una página que no
está.

## Lo medido

| Elemento | Qué daría | Entradas | Cobertura |
|---|---|---|---|
| `OpenTenderEvent` | Apertura de sobres | 0 | **0,00 %** |
| `OpenTenderEventTypeCode` | Tipo de acto de apertura | 0 | **0,00 %** |
| `AdditionalInformationRequestPeriod` | Fin del plazo de consultas | 0 | **0,00 %** |
| `InvitationSubmissionPeriod` | Plazo de invitación | 0 | 0,00 % |
| `TenderResultEvent` | Acto público de resultado | 0 | 0,00 % |
| `PlannedDate` / `OccurenceDate` | Fecha prevista de un acto | 0 | 0,00 % |
| `TenderSubmissionDeadlinePeriod` | Plazo de presentación *(ya se extrae)* | 723 | 98,4 % |
| `ParticipationRequestReceptionPeriod` | Plazo de solicitudes *(ya se extrae)* | 9 | 3,8 %¹ |
| `ProcedureCode` | Procedimiento *(F1.7)* | 235 | 100 %¹ |
| `AwardDate` | Fecha de adjudicación | 332 | 45,2 % |

¹ Medido sólo sobre la primera página (235 entradas); las dos últimas filas se
contaron en la primera pasada.

## Decisión

**No se construye el parser de hitos ni la tabla `licitacion_hitos`.** La
cobertura de apertura de sobres es cero, no baja: el elemento no aparece ni
una vez en 735 expedientes. No es un problema de umbral ni de muestra
pequeña — la Plataforma sencillamente no publica esos actos en este feed.

Consecuencias, todas ya resueltas en el plan:

1. **La fecha prevista de adjudicación (F4.4) se estima sola**, que es lo que
   D32 preveía para este caso. Ya está implementada: mediana del lead-time del
   órgano sobre la fecha límite, con rango p25–p75 y `n`, y sin estimación por
   debajo de cinco adjudicaciones
   (`services/analytics/lead_time.py`).
2. **`ExpectedAward.metodo` ya admite `hito`.** El contrato no cambia el día
   que la Plataforma empiece a publicar el acto de apertura: sólo cambiaría de
   dónde sale la fecha. Ese campo existe precisamente por esta posibilidad.
3. **La agenda no distingue «hito publicado» de «fecha estimada»** porque hoy
   sólo hay de las segundas, y `metodo` es lo que permitirá distinguirlas sin
   rehacer nada.

## Un hallazgo lateral que sí sirve

`AwardDate` aparece en el **45 %** de las entradas —las que están en fase de
adjudicación—, que es exactamente la mitad del par que necesita el cálculo del
lead-time (`fecha_adjudicacion` − `fecha_publicacion`). Confirma que la
estimación de F4.4 se apoya en un dato realmente publicado y no en una
reconstrucción, que era la duda razonable al sustituir el hito por la
estimación.

## Cómo repetir la medida

El spike es un script corto de una sola dependencia (`urllib`): descarga la
página, trocea por `<entry>` y cuenta elementos por expresión regular. No se
commitea porque no es código de producción y su valor está en el número, no en
el programa. Para rehacerlo basta con contar, sobre las entradas de una página
del feed, cuántas contienen `<\w+:OpenTenderEvent[ >]`.

Si algún día ese número sube del 30 %, D32 se reabre y F2.1 vuelve al plan con
lo que ya está preparado para recibirlo.
