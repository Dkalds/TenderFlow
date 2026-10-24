# Corpus golden del parser CODICE

Expedientes PLACSP congelados como casos de regresión del parser. Los consume
[`tests/test_codice_parser_golden.py`](../../test_codice_parser_golden.py), que
compara el árbol parseado completo (licitación + lotes + adjudicaciones +
documentos) contra `golden.jsonl`.

## Disciplina

**Cada incidente de datos en producción añade su expediente aquí ANTES del fix.**
El caso entra en rojo, el fix lo pone en verde, y desde ese momento queda
protegido. El corpus solo crece: `_MIN_CASOS` en el test lo verifica.

Para capturar un expediente real de los ZIP mensuales ya cacheados:

```
ENV=dev python scripts/capture_placsp_fixtures.py --listar
ENV=dev python scripts/capture_placsp_fixtures.py --caso ute
ENV=dev python -m tests.test_codice_parser_golden --update   # regenera el golden
```

## Estado de los fixtures

Los dieciocho primeros casos son **sintéticos**: estructuralmente fieles al CODICE
que publica PLACSP, pero escritos a mano porque ni la sesión que creó el corpus
ni las que lo ampliaron tenían ZIP cacheados a mano. La que añadió el 16 y el
17 (v148, 2026-10-12) intentó leer el ATOM en vivo para recortar entradas
reales y la política de red de su entorno bloqueaba
`contrataciondelsectorpublico.gob.es`: sus dos casos son tan inventados como
el resto, y `capture_placsp_fixtures.py` trae ya los casos `condiciones` y
`condiciones_por_lote` para sustituirlos. Sustituirlos por
expedientes reales (`capture_placsp_fixtures.py`) es trabajo pendiente anotado
en el backlog — el valor del corpus crece cuando codifica variabilidad que
nadie imaginó.

El 19 es el primero **real**: la entry de `B070005/2022-0071` (Diputación de
Huesca) del ZIP mensual de 2026-06, recortada a mano con un script que solo
quita, sin reordenar ni reescribir: condiciones (`TenderingTerms`), adjuntos,
`GeneralDocument`, contactos y el detalle de cada anuncio salvo su
`IssueDate`. Conserva lo que el feed trae y ningún fixture sintético tenía: los
prefijos `cac-place-ext`/`cbc-place-ext`, `schemeName="ID_LOTE"` en el lote,
un NIF con `schemeName="OTROS"`, un `&#13;` dentro de un texto y dos
`ContractModification`.

| Fixture | Qué congela |
|---|---|
| `01_multilote_adjudicado_por_lote` | 3 lotes con adjudicación referenciando cada lote |
| `02_ute_dos_ganadores_un_resultado` | UTE: dos `WinningParty` en un `TenderResult` (el importe se repite entero en cada fila — comportamiento actual, no deseado) |
| `03_sin_fecha_limite` | Expediente sin `TenderingProcess`: `fecha_limite` queda `None` |
| `04_deadline_participation_request` | Plazo vía `ParticipationRequestReceptionPeriod` (restringido) |
| `05_importe_solo_total_amount` | Presupuesto solo en `TotalAmount`, sin `TaxExclusiveAmount` |
| `06_documentos_tres_tipos` | Pliego legal + técnico + anexo, y un adjunto sin URI que se descarta |
| `07_adjudicacion_pyme` | `SMEAwardedIndicator`, horquilla de ofertas y `ResultCode` |
| `08_fuera_universo_tecnologico` | Expediente no-TI: el parser lo descarta (resultado `null`) |
| `09_deadline_hora_local` | Plazo en hora peninsular convertido a UTC |
| `10_lotes_heredan_fecha_limite` | Lote sin plazo propio hereda el del expediente; lote con plazo propio lo conserva. El lote 1 usa `TotalAmount` |
| `11_ambos_periodos_de_plazo` | Los dos periodos presentes: congela **cuál gana** |
| `12_procedimiento_tramitacion_criterios` | `ProcedureCode` + `UrgencyCode` y criterios de adjudicación en escala porcentual, con subcriterios que **no** deben contarse dos veces |
| `13_criterios_sin_escala_deducible` | Solo se publica un criterio (60) sin el resto: `peso_precio_pct` queda NULL aunque procedimiento y tramitación sí se extraigan |
| `14_documentos_token_rotativo_y_hash` | Adjuntos con la forma real de PLACSP: URI de `GetDocumentByIdServlet` con token rotativo, sin `cbc:FileName`, con `cbc:ID` (nombre) y `cbc:DocumentHash` (identidad estable). Dos PCAP del mismo expediente con hash distinto: congela que `(licitacion_id, tipo)` **no** identifica un documento |
| `15_anuncio_previo_notice_type_code` | Cuatro `ValidNoticeInfo` con `NoticeTypeCode` (`DOC_PIN_RTL`, `DOC_CN` dos veces, `DOC_CD`): `tipos_anuncio` los guarda crudos, distintos y ordenados (v138, spike T5); la `fecha_publicacion` sale la mínima de todos los bloques, o sea la del PIN — comportamiento actual de `_issue_date`, congelado, no decidido |
| `16_condiciones_expediente` | v148: `cac:TenderingTerms` del expediente con los tres bloques — tres criterios con tipo, subtipo y nota (escala porcentual), una garantía por porcentaje (`AmountRate`) y solvencia técnica, económica con `ThresholdAmount` y clasificación empresarial. Los códigos viajan crudos |
| `17_condiciones_por_lote` | v148: cada lote con su `TenderingTerms` — el 1 con criterios en fracciones (0,8/0,2 → 80/20), el 2 con garantía por importe (`LiabilityAmount`), solvencia técnica y criterios en porcentaje — y una garantía a nivel de expediente declarada **después** de los lotes |
| `18_lote_en_proyecto_adjudicado` | El lote del resultado dentro del proyecto adjudicado (`AwardedTenderedProject/cbc:ProcurementProjectLotID`), que es como lo publica CODICE; el tercer `TenderResult` no dice lote y queda `NULL`. Incidente del 2026-10-17: el parser solo leía la forma del caso 01 y ninguna adjudicación de producción resolvía su lote |
| `19_multilote_real_por_lote` | **Real** (ZIP 2026-06). Cuatro lotes, cuatro `TenderResult` con su `ProcurementProjectLotID`; la misma empresa gana el 2 y el 3 por importes distintos. Incidente del 2026-10-24: en producción las adjudicaciones de los lotes 1 y 3 seguían sin `lote_id` aunque el XML lo publica, porque 188.800,9 y 24.545,6 no caben exactos en `real` y el reproceso comparaba el importe por igualdad |

El caso 11 existe porque sin él invertir la prioridad en `_tender_deadline` no
rompía ningún test del corpus: se detectó mutando el parser a propósito para
comprobar que el golden tenía dientes.

El caso 14 es el que codifica el incidente de los enlaces caducados (v88): hasta
entonces el parser leía `cbc:FileName` —que en los adjuntos de PLACSP no aparece
nunca— e ignoraba `cbc:ID` y `cbc:DocumentHash`, así que `filename` estaba a NULL
en las 37.953 filas de producción y cada rotación de token insertaba un duplicado
en vez de refrescar la fila. A diferencia del resto, su XML se calcó de la forma
verificada sobre el feed vivo el 2026-08-18, no se imaginó.

Los casos 12 y 13 son la pareja que congela el criterio de v85: el peso del
precio solo se persiste cuando la suma de los pesos publicados declara su
escala. El 13 es el que impide que una futura "mejora" devuelva 60 sobre un
denominador que nadie publicó.
