# Corpus golden del parser CODICE

Expedientes PLACSP congelados como casos de regresión del parser. Los consume
[`tests/test_codice_parser_golden.py`](../../test_codice_parser_golden.py), que
compara el árbol parseado completo (licitación + lotes + adjudicaciones +
documentos) contra `golden.jsonl`.

## Disciplina

**Cada incidente de datos en producción añade su expediente aquí ANTES del fix.**
El caso entra en rojo, el fix lo pone en verde, y desde ese momento queda
protegido. El corpus solo crece: `_MIN_CASOS` en el test lo verifica.

Para capturar un expediente real, de los ZIP mensuales cacheados o de páginas
del ATOM y ZIP ya descargados:

```
ENV=dev python scripts/capture_placsp_fixtures.py --listar --atom muestra/*.atom
ENV=dev python scripts/capture_placsp_fixtures.py --atom muestra/*.atom --caso solvencia_umbral --id 20767645
ENV=dev python -m tests.test_codice_parser_golden --update   # regenera el golden
```

`--id` es el número final del `<id>` ATOM de la entry (la columna «Entry» de
abajo): con él cada caso real se vuelve a recortar igual. `--sustituir`
escribe sobre el fixture sintético del caso en vez de añadir uno nuevo, y solo
existe para los casos en los que el real conserva lo que el sintético congela
(`SINTETICO_POR_CASO` en el script).

## De dónde sale cada caso

Desde el 2026-10-24 el corpus mezcla expedientes **reales**, recortados sin
tocar del feed de PLACSP, con los **sintéticos** que escribieron a mano las
sesiones cuya red bloqueaba la Plataforma. Un sintético se sustituyó solo
cuando un expediente real reproducía lo que congelaba; si además fija una
construcción que el feed no publica (o que otro test lee por su id), se quedó
y el real entró como caso nuevo. Los reales son la entry tal cual: lo único
que cambia el script al escribirlos es la declaración XML delante, el salto de
línea final y los espacios de final de línea escritos como `&#32;`. No se ha
anonimizado nada: los contactos son buzones institucionales y los
adjudicatarios, sociedades (se descartaron candidatos con un buzón personal).

Muestras de las que salen, descargadas el 2026-10-24:

- **ATOM vivo**: `https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3.atom`
  y siete páginas más siguiendo `rel="next"`; 3.903 entradas con `updated`
  del 2026-10-22 al 2026-10-24.
- **ZIP de 2026-09**: `https://contrataciondelestado.es/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3_202609.zip`,
  95.910 entradas.

| Fixture | Origen | Entry | Expediente | `updated` |
|---|---|---|---|---|
| `03_sin_fecha_limite` | ATOM vivo | 20757521 | CONT94/2026 | 2026-10-22T13:24:26 |
| `08_fuera_universo_tecnologico` | ATOM vivo | 20767399 | 110/26 RTPA | 2026-10-23T14:19:38 |
| `09_deadline_hora_local` | ATOM vivo | 20706009 | 26710082900 | 2026-10-23T14:05:36 |
| `13_criterios_sin_escala_deducible` | ATOM vivo | 19791404 | 2026/LIC/0027 | 2026-10-22T14:51:08 |
| `15_anuncio_previo_notice_type_code` | ATOM vivo | 20093302 | ICO_2026_44 | 2026-10-22T17:04:47 |
| `16_condiciones_expediente` | ATOM vivo | 20573000 | 090/2026 | 2026-10-23T13:06:25 |
| `17_condiciones_por_lote` | ATOM vivo | 20767496 | SUM/2026/0000195073 | 2026-10-23T13:29:56 |
| `19_multilote_adjudicado_real` | ZIP 2026-09 | 19512506 | 1611/2026 | 2026-09-07T13:36:45 |
| `20_lotes_repiten_presupuesto_real` | ZIP 2026-09 | 20363232 | CESDA 1750/2026 | 2026-09-01T14:04:38 |
| `21_solvencia_umbral_real` | ATOM vivo | 20767645 | 17429/2026 | 2026-10-23T12:24:30 |
| `22_pyme_real` | ATOM vivo | 20768063 | CBA4573/2026 | 2026-10-23T07:45:31 |
| `23_ambos_periodos_real` | ATOM vivo | 20767663 | TCV20SDA/26 | 2026-10-23T12:11:13 |
| `24_documentos_real` | ATOM vivo | 20767306 | CS/99/1126067408/26/PNSP | 2026-10-23T17:06:21 |

La URL de cada entry es su `<id>`,
`https://contrataciondelestado.es/sindicacion/licitacionesPerfilContratante/<Entry>`;
el `<link>` del propio XML lleva a la ficha pública. Un ZIP mensual puede traer
varias versiones de la misma entry: el script se queda con la primera.

Siguen **sintéticos** 01, 02, 04, 05, 06, 07, 10, 11, 12, 14 y 18. Para el 02
(dos `WinningParty` en un `TenderResult`), el 05 (presupuesto solo en
`TotalAmount`) y el 10 (lotes con plazo propio y sin él) no apareció ningún
ejemplar en las 99.813 entradas de las dos muestras, ni dentro ni fuera del
universo tecnológico; para el 04 (solo `ParticipationRequestReceptionPeriod`)
hay 55 (51 en el ZIP y 4 en el ATOM), ninguno tecnológico. El resto fija una construcción concreta
que el real no trae, y la forma real de lo mismo está en los casos 19-24.

El 25, del ítem de las adjudicaciones multilote, también es **real**: la entry de `B070005/2022-0071` (Diputación de
Huesca) del ZIP mensual de 2026-06, recortada a mano con un script que solo
quita, sin reordenar ni reescribir: condiciones (`TenderingTerms`), adjuntos,
`GeneralDocument`, contactos y el detalle de cada anuncio salvo su
`IssueDate`. Conserva lo que el feed trae y ningún fixture sintético tenía: los
prefijos `cac-place-ext`/`cbc-place-ext`, `schemeName="ID_LOTE"` en el lote,
un NIF con `schemeName="OTROS"`, un `&#13;` dentro de un texto y dos
`ContractModification`.

| Fixture | Qué congela |
|---|---|
| `01_multilote_adjudicado_por_lote` | Sintético. 3 lotes con adjudicación referenciando cada lote por `ProcurementProjectLotReference`, una forma que el feed no usa (la real es la del 18 y el 19) y que el parser sigue leyendo |
| `02_ute_dos_ganadores_un_resultado` | Sintético. UTE: dos `WinningParty` en un `TenderResult` (el importe se repite entero en cada fila — comportamiento actual, no deseado) |
| `03_sin_fecha_limite` | Real. Anuncio previo (`PRE`, solo `DOC_PIN`) con `TenderingProcess` pero sin ningún periodo de plazo: `fecha_limite` queda `None`; su `TenderingTerms` no trae ninguno de los tres bloques |
| `04_deadline_participation_request` | Sintético. Plazo vía `ParticipationRequestReceptionPeriod` (restringido) |
| `05_importe_solo_total_amount` | Sintético. Presupuesto solo en `TotalAmount`, sin `TaxExclusiveAmount` |
| `06_documentos_tres_tipos` | Sintético. Pliego legal + técnico + anexo, y un adjunto sin URI que se descarta |
| `07_adjudicacion_pyme` | Sintético. `SMEAwardedIndicator`, horquilla de ofertas y `ResultCode` |
| `08_fuera_universo_tecnologico` | Real. Expediente no-TI (radiotelevisión autonómica): el parser lo descarta (resultado `null`) |
| `09_deadline_hora_local` | Real. Plazo a las 10:00 peninsulares de noviembre convertido a 09:00 UTC; el NUTS `ES` da `provincia` «España» (comportamiento actual) |
| `10_lotes_heredan_fecha_limite` | Sintético. Lote sin plazo propio hereda el del expediente; lote con plazo propio lo conserva. El lote 1 usa `TotalAmount` |
| `11_ambos_periodos_de_plazo` | Sintético. Los dos periodos presentes con fechas distintas: congela **cuál gana** |
| `12_procedimiento_tramitacion_criterios` | Sintético. `ProcedureCode` + `UrgencyCode` y criterios en escala porcentual, con subcriterios anidados que **no** deben contarse dos veces (en el feed no aparecen subcriterios) |
| `13_criterios_sin_escala_deducible` | Real. Solo se publica el criterio del precio (75) sin el resto: `peso_precio_pct` queda NULL aunque procedimiento y tramitación sí se extraigan. El órgano publicó la «oferta técnica» como solvencia técnica (`ZZZ`), y se guarda tal cual |
| `14_documentos_token_rotativo_y_hash` | Calcado del feed. Adjuntos con la forma real de PLACSP: URI de `GetDocumentByIdServlet` con token rotativo, sin `cbc:FileName`, con `cbc:ID` (nombre) y `cbc:DocumentHash` (identidad estable). Dos PCAP del mismo expediente con hash distinto: congela que `(licitacion_id, tipo)` **no** identifica un documento |
| `15_anuncio_previo_notice_type_code` | Real. Seis `ValidNoticeInfo` de cuatro tipos (`DOC_PIN`, `DOC_CN`, `DOC_CD`, `DOC_CAN_ADJ`): `tipos_anuncio` los guarda crudos, distintos y ordenados (v138, spike T5); la `fecha_publicacion` sale la mínima de todos los bloques, o sea la del PIN — comportamiento actual de `_issue_date`, congelado, no decidido. La adjudicación publica importe 0 y se guarda 0 |
| `16_condiciones_expediente` | Real. v148: `TenderingTerms` del expediente con los tres bloques — cuatro criterios en escala porcentual, garantía definitiva por `AmountRate` (5 = 5 %), solvencia técnica, económica y clasificación empresarial con solo `CodeValue` (`M5-1`, sin nombre). Los códigos viajan crudos |
| `17_condiciones_por_lote` | Real. v148: dos lotes con su propio `TenderingTerms` (cuatro y cinco criterios; en el lote 2 el precio no es el primero) y la garantía y la solvencia solo en el expediente, que es donde las publica el feed; el expediente no publica criterios propios y `peso_precio_pct` queda NULL |
| `18_lote_en_proyecto_adjudicado` | Sintético. El lote del resultado dentro del proyecto adjudicado (`AwardedTenderedProject/cbc:ProcurementProjectLotID`), que es como lo publica CODICE; el tercer `TenderResult` no dice lote y queda `NULL`. Incidente del 2026-10-17: el parser solo leía la forma del caso 01 y ninguna adjudicación de producción resolvía su lote |
| `19_multilote_adjudicado_real` | Real. Dos lotes adjudicados a dos sociedades distintas, cada resultado con su lote en `AwardedTenderedProject`; `valor_estimado` distinto del presupuesto |
| `20_lotes_repiten_presupuesto_real` | Real. Cada lote publica como presupuesto propio el del expediente entero (la suma de los lotes no es el total); `ValidNoticeInfo` solo trae el anuncio de adjudicación, así que `fecha_publicacion` es posterior al plazo |
| `21_solvencia_umbral_real` | Real. Solvencia económica con el umbral en `ThresholdQuantity`, sin moneda: sale en `umbral_importe` (101.700). Dos garantías al 5 % (tipos 2 y 3) |
| `22_pyme_real` | Real. Un único lote, numerado «4», adjudicado con `SMEAwardedIndicator` falso; sin plazo y sin documentos |
| `23_ambos_periodos_real` | Real. Los dos periodos de plazo presentes con la misma fecha y hora, que es como los publica el feed; adjudicado |
| `24_documentos_real` | Real. Pliego legal, técnico y un anexo `.xlsx`; un solo lote; la solvencia económica (`ZZZ`) publica «PRECIO» como descripción |
| `25_multilote_real_por_lote` | **Real** (ZIP 2026-06). Cuatro lotes, cuatro `TenderResult` con su `ProcurementProjectLotID`; la misma empresa gana el 2 y el 3 por importes distintos. Incidente del 2026-10-24: en producción las adjudicaciones de los lotes 1 y 3 seguían sin `lote_id` aunque el XML lo publica, porque 188.800,9 y 24.545,6 no caben exactos en `real` y el reproceso comparaba el importe por igualdad |

El caso 11 existe porque sin él invertir la prioridad en `_tender_deadline` no
rompía ningún test del corpus (el 23, real, no basta: sus dos fechas
coinciden): se detectó mutando el parser a propósito para comprobar que el
golden tenía dientes.

El caso 14 es el que codifica el incidente de los enlaces caducados (v88): hasta
entonces el parser leía `cbc:FileName` —que en los adjuntos de PLACSP no aparece
nunca— e ignoraba `cbc:ID` y `cbc:DocumentHash`, así que `filename` estaba a NULL
en las 37.953 filas de producción y cada rotación de token insertaba un duplicado
en vez de refrescar la fila. A diferencia del resto de sintéticos, su XML se
calcó de la forma verificada sobre el feed vivo el 2026-08-18, no se imaginó.

Los casos 12 y 13 son la pareja que congela el criterio de v85: el peso del
precio solo se persiste cuando la suma de los pesos publicados declara su
escala. El 13 es el que impide que una futura "mejora" devuelva 75 sobre un
denominador que nadie publicó.
