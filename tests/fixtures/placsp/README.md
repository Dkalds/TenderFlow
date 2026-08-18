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

Los catorce casos son **sintéticos**: estructuralmente fieles al CODICE
que publica PLACSP, pero escritos a mano porque ni la sesión que creó el corpus
ni las que lo ampliaron tenían ZIP cacheados a mano. Sustituirlos por
expedientes reales (`capture_placsp_fixtures.py`) es trabajo pendiente anotado
en el backlog — el valor del corpus crece cuando codifica variabilidad que
nadie imaginó.

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
