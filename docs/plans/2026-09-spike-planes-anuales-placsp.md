---
tags: [spike, decision, placsp, codice, pre-radar]
---

# Spike T5 — ¿publica PLACSP los planes anuales de contratación?

**Resultado: NO-GO. No hay ningún objeto «plan anual» en el canal que el
producto puede leer. Su equivalente legal —el anuncio de información previa—
aparece en el 4,35 % del flujo y en el 42 % de esos casos no anticipa nada.**

T5 del [plan de arquitectura 2026-09](2026-09-plan-arquitectura-v2.md)
condicionaba una tercera pata del pre-radar («calendario de compra a partir de
los planes anuales de contratación de PLACSP») a un spike con muestra, formato
y decisión. Este documento es ese spike.

---

## Qué es un «plan anual de contratación» y por dónde debería salir

Verificado contra el texto consolidado de la **Ley 9/2017 (LCSP)** en el BOE
(`BOE-A-2017-12902`, consultado el 2026-09-08):

- **Art. 28.4** obliga a programar: las entidades «darán a conocer su plan de
  contratación anticipadamente **mediante un anuncio de información previa
  previsto en el artículo 134**», al menos para los contratos SARA.
- **Art. 134.1** define ese anuncio en potestativo: los órganos «**podrán**
  publicar un anuncio de información previa» para los contratos SARA que
  proyecten adjudicar.
- **Art. 134.2** lo publica en el DOUE **o** en el perfil de contratante alojado
  en la Plataforma, a elección del órgano.
- **Art. 134.6** acota su horizonte a **12 meses** desde el envío.

Es decir: en la ley española **el plan anual no es un documento con formato
propio publicado en la Plataforma**, es un conjunto de anuncios de información
previa (PIN). Cualquier ingesta de «planes» pasa, en la práctica, por los PIN.
El obligado del 28.4 y el potestativo del 134.1 conviven en la misma norma, y la
medición de abajo dice cuál gana.

---

## Lo que sí se pudo comprobar contra la fuente real

**Medido el 2026-09-08** desde esta máquina, con el `User-Agent` del proyecto
(`TenderflowBot/1.0`, `config/constants.py:22`), sobre el mismo feed que ya
consume el scraper (`PLACE_LIVE_ATOM_URL`, sindicación 643,
`config/constants.py:25-27`).

| Página | Entradas |
|---|---|
| `licitacionesPerfilesContratanteCompleto3.atom` (cabecera) | 405 |
| `..._20260907_201809.atom` | 500 |
| `..._20260907_201809_1.atom` | 498 |
| **Total** | **1 403** |

La detección es **por `local-name` con lxml**, no por expresión regular: los
prefijos de la Plataforma llevan guion (`cbc-place-ext:`, `cac-place-ext:`) y un
patrón `<\w+:Nombre>` no los casa. Es un error real: la primera pasada de este
spike, hecha con regex, dio 0 % de `ContractFolderStatusCode` sobre entradas que
lo llevan todas.

### 1. No existe ningún elemento de plan

| Elemento buscado | Entradas | Cobertura |
|---|---|---|
| `PlannedProcurement` | 0 | **0,00 %** |
| `ContractingPlan` | 0 | **0,00 %** |
| `AnnualProcurementPlan` | 0 | **0,00 %** |
| `PriorInformationNotice` (como elemento) | 0 | **0,00 %** |
| `cac:PlannedPeriod` | 1 402 | 99,93 %¹ |

¹ `PlannedPeriod` es el **periodo de ejecución previsto del contrato**
(`StartDate` + `DurationMeasure`), no un plan de compra. Es el único de los 164
nombres de elemento distintos del feed que contiene la palabra «plan».

### 2. El estado `PRE` es residual en el flujo

`ContractFolderStatusCode` sobre las 1 403 entradas. Las etiquetas son las de la
lista de códigos oficial, descargada para este spike
(`.../codice/cl/2.04/SyndicationContractFolderStatusCode-2.04.gc`, seis códigos):

| Estado | Etiqueta oficial | Entradas | % |
|---|---|---|---|
| `EV` | Pendiente de adjudicación | 556 | 39,63 % |
| `RES` | Resuelta | 427 | 30,43 % |
| `ADJ` | Adjudicada | 286 | 20,38 % |
| `PUB` | En plazo | 132 | 9,41 % |
| **`PRE`** | **Anuncio previo** | **2** | **0,14 %** |
| `ANUL` | Anulada | 0 | 0,00 % |

Dato con consecuencias para la bandeja «Próximas»: **esa lista no contiene
`CPM`**. La consulta preliminar de mercado no es un estado de sindicación de
PLACSP; el `CPM` de TenderFlow viene de la normalización de las plataformas
autonómicas que hizo `v91` (`CONSULTA PRELIMINAR` →`CPM`,
`db/alembic/versions/v91_normaliza_estado_licitaciones.py:121`). En PLACSP la
consulta preliminar viaja como **tipo de anuncio**, `DOC_CON`, y en esta
muestra aparece **cero veces** (ver tabla siguiente).

El feed es de *actualizaciones*, no de stock: una entrada aparece cuando el
expediente se mueve. Un expediente en `PRE` publica una vez y se queda quieto
hasta que sale a licitación, así que este 0,14 % mide **cuánto anuncio previo
entra por el canal de ingesta**, que es justo el denominador que importa para
decidir si construir sobre él.

### 3. El PIN sí está etiquetado, y no se extrae hoy

`cbc-place-ext:NoticeTypeCode` distingue el tipo de anuncio dentro de cada
`cac-place-ext:ValidNoticeInfo`. Las etiquetas de abajo **no son
interpretaciones**: son las de la lista de códigos oficial, descargada también
para este spike (`.../codice/cl/2.11/TenderingNoticeTypeCode-2.11.gc`, treinta
códigos):

| `NoticeTypeCode` | Etiqueta oficial | Entradas | % |
|---|---|---|---|
| `DOC_CD` | Anuncio de Pliegos | 1 287 | 91,73 % |
| `DOC_CN` | Anuncio de Licitación | 1 286 | 91,66 % |
| `DOC_CAN_ADJ` | Anuncio de Adjudicación | 708 | 50,46 % |
| `DOC_FORM` | Anuncio de Formalización | 376 | 26,80 % |
| `DOC_MOD` | Anuncio modificación de contrato | 55 | 3,92 % |
| **`DOC_PIN`** | **Anuncio Previo** | **45** | **3,21 %** |
| **`DOC_PIN_RTL`** | **Anuncio Previo con Reducción de Plazos** | **18** | **1,28 %** |
| `DOC_CCN` | Anuncio de Finalización de Contrato | 12 | 0,86 % |
| `DESISTIMIENTO` | Anuncio de Desistimiento | 5 | 0,36 % |
| **`DOC_CON`** | **Anuncio de Consulta Preliminar de Mercado** | **0** | **0,00 %** |

Los otros veinte códigos de la lista (anulaciones, encargos, adjudicación
provisional/definitiva) tampoco aparecen. **`DOC_CON` en cero** es el dato que
conviene retener: la consulta preliminar de mercado —la otra mitad del pre-radar
junto con el anuncio previo— no entró ni una vez por este canal en 1 403
expedientes.

**61 de 1 403 entradas (4,35 %) llevan algún PIN.** El parser del repo lee
`ContractFolderStatusCode` (`scraper/codice_parser.py:477,638`) y la `IssueDate`
mínima de `ValidNoticeInfo` (`scraper/codice_parser.py:224-230`), pero **no lee
`NoticeTypeCode`**: hoy no se puede saber desde la BD si un expediente pasó por
un anuncio previo. El dato está en la fuente y no se extrae.

### 4. Cuánto anticipa realmente un PIN — el número que decide

Para cada expediente con PIN se comparó la `IssueDate` más temprana de su
`ValidNoticeInfo` de tipo PIN contra la del anuncio de licitación (`DOC_CN`).
De los 61 con PIN, **59 tienen ya `DOC_CN`** y forman par medible:

| Métrica | Días entre PIN y anuncio de licitación |
|---|---|
| Mínimo | 0 |
| p25 | 0 |
| **Mediana** | **1** |
| p75 | 56 |
| Máximo | 214 |
| Pares con **0 días o menos** | **25 / 59 (42 %)** |
| Pares con **≥ 30 días** | 18 / 59 (30,5 %) |

Traducido: en cuatro de cada diez PIN, el anuncio previo se emite **el mismo
día** que el anuncio de licitación — es un asiento administrativo, no un aviso.
La señal con anticipación útil (≥ 30 días) son **18 expedientes sobre 1 403**:
**1,28 % del flujo**.

Estados de los expedientes que llevan PIN: `EV` 24, `RES` 16, `PUB` 13, `ADJ` 6,
`PRE` 2 — o sea, el rastro del PIN sobrevive al cambio de estado y se puede leer
a posteriori; simplemente casi nunca llegó antes.

---

## La muestra

Una de las dos entradas en estado `PRE` del feed, íntegra en el ATOM del
2026-09-07 (recortada aquí a lo que decide):

```xml
<summary type="text">Id licitación: 300/2026/01575; Órgano de Contratación:
  Distrito de Chamberí; Importe: 351641.8 EUR; Estado: PRE</summary>
<title>Organización, gestión y ejecución del programa de actividades de la
  Navidad, en el Distrito de Chamberí.</title>

<cac-place-ext:ContractFolderStatus>
  <cbc:ContractFolderID>300/2026/01575</cbc:ContractFolderID>
  <cbc-place-ext:ContractFolderStatusCode
      listURI=".../SyndicationContractFolderStatusCode-2.04.gc">PRE</cbc-place-ext:ContractFolderStatusCode>
  <cac:ProcurementProject>
    <cbc:TypeCode listURI=".../ContractCode-2.08.gc">2</cbc:TypeCode>
    <cac:BudgetAmount>
      <cbc:EstimatedOverallContractAmount currencyID="EUR">1406567.2</cbc:EstimatedOverallContractAmount>
      <cbc:TaxExclusiveAmount currencyID="EUR">351641.8</cbc:TaxExclusiveAmount>
    </cac:BudgetAmount>
    <cac:RequiredCommodityClassification>
      <cbc:ItemClassificationCode listURI=".../CPV2008-2.04.gc">92000000</cbc:ItemClassificationCode>
    </cac:RequiredCommodityClassification>
    <cac:PlannedPeriod>
      <cbc:StartDate>2026-11-01</cbc:StartDate>
      <cbc:DurationMeasure unitCode="ANN">1</cbc:DurationMeasure>
    </cac:PlannedPeriod>
  </cac:ProcurementProject>
  <cac-place-ext:ValidNoticeInfo>
    <cbc-place-ext:NoticeTypeCode
        listURI=".../TenderingNoticeTypeCode-2.11.gc">DOC_PIN_RTL</cbc-place-ext:NoticeTypeCode>
    <cac-place-ext:AdditionalPublicationStatus>
      <cbc:IssueDate>2026-05-22</cbc:IssueDate>
    </cac-place-ext:AdditionalPublicationStatus>
  </cac-place-ext:ValidNoticeInfo>
</cac-place-ext:ContractFolderStatus>
```

**Formato encontrado:** un expediente CODICE normal y corriente, idéntico en
estructura a cualquier otro del feed. Lo único que lo hace «previo» son dos
campos: el estado `PRE` y el `NoticeTypeCode` `DOC_PIN_RTL`. **No hay un
documento de plan, ni una lista de contratos previstos, ni un esquema propio.**
La fecha prevista, cuando existe, sale de `PlannedPeriod/StartDate` — y de las
dos entradas `PRE` de la muestra, **una la trae y la otra no**, que es
exactamente el caso que la bandeja «Próximas» tiene que saber pintar como «sin
fecha».

---

## Lo que NO se pudo comprobar

Sin esto, la decisión sigue en pie, pero conviene que quede escrito quién tendría
que ir a mirar y dónde:

1. **No pude enumerar el catálogo de sindicaciones de PLACSP.** El índice
   `https://contrataciondelsectorpublico.gob.es/sindicacion/` devuelve **403**
   con el UA del proyecto y con un UA de navegador. Peor: cualquier ruta
   inventada bajo `/sindicacion/` responde **200 con `text/html`** (una página
   del portal), no 404 — así que **sondear URLs adivinadas no puede demostrar
   que un feed no exista**. Lo comprobado es que el feed 643 no trae planes, no
   que la Plataforma no publique ninguno por otro canal. (Las listas de códigos
   bajo `/codice/cl/...` sí se sirven sin problema: de ahí salen las etiquetas
   oficiales de las tablas de arriba.)
2. **No pude leer la guía oficial de servicios de sindicación**, que vive bajo
   `wps/portal` y no es accesible por HTTP plano desde aquí.
3. **No abrí ningún perfil de contratante** para ver si los órganos cuelgan ahí
   su plan anual como documento (PDF/XLSX/HTML). El art. 134.2 permite
   publicarlo en el perfil, y esa es la vía por la que un plan podría existir
   en formato humano y no en CODICE. **Queda por comprobar contra la fuente
   real**: es una página web por órgano, no un feed, y su forma es la incógnita
   que decidiría si un scraper de perfiles es siquiera viable.
4. **No descargué los ZIP mensuales** (`bulk_downloader.py:34-35`). Podrían
   contener más entradas `PRE` que el feed en vivo por el efecto de stock frente
   a flujo. Los porcentajes de arriba son del feed de actualizaciones y no se
   deben extrapolar al histórico completo.
5. **No consulté la BD de producción** para contar cuántas filas `PRE`/`CPM` hay
   ya guardadas: en esta máquina no hay Postgres y no se abrió la de producción.
   El «cuánto pre-radar tenemos ya» sigue sin medir.

---

## Decisión

**NO-GO: no se construye ingesta de planes anuales de contratación.**

Los tres motivos, en orden de peso:

1. **No hay nada que parsear.** Cero elementos de plan en 1 403 expedientes. Un
   parser de planes no tendría entrada. Lo que la ley llama «plan» se materializa
   como PIN sueltos, no como documento.
2. **El PIN no da la anticipación que justificaría el trabajo.** 4,35 % de
   cobertura y mediana de **un día** de adelanto. Un «calendario de compra»
   construido sobre eso avisaría de 18 expedientes sobre 1 403 y llegaría tarde
   en los otros 43. Es exactamente el patrón que ADR-014 prohíbe: una pantalla
   que promete anticipación y entrega un asiento administrativo.
3. **La vía alternativa es de otro orden de esfuerzo.** Raspar el plan anual del
   perfil de contratante de cada órgano es N scrapers de HTML más N formatos de
   documento heterogéneos, y ni siquiera pude establecer cuál es ese formato
   (punto 3 de la sección anterior). No es una tarea de talla M.

**Lo que sí sostiene el pre-radar es lo que ya está en casa:** los estados `PRE`
y `CPM` normalizados por `v91` (`db/alembic/versions/v91_normaliza_estado_licitaciones.py:121-129`,
catálogo en `services/classification.py:226,230`) y los avisos `pin-*` de TED
(`scraper/connectors/ted.py:109`). La bandeja «Próximas» de T5 se apoya en eso y
no necesita nada de este spike.

Con una advertencia que sale de esta medición y que conviene tener delante al
dimensionar esa bandeja: **por PLACSP entra muy poco**. `PRE` es el 0,14 % del
flujo y `DOC_CON` (consulta preliminar) el 0 %. El grueso del `CPM` de la base
viene de las plataformas autonómicas —que sí publican ese estado, y por eso
`v91` tuvo que normalizarlo desde cadenas en catalán— y el `PRE` tiene además la
vía de TED. Cuánto hay realmente guardado hoy **no se midió** (ver punto 5).

### Cuándo se reabre

- Si alguien establece que PLACSP publica un feed o dataset de planes
  (el catálogo de sindicaciones no se pudo enumerar: es una comprobación
  pendiente, no una negación).
- Si `DOC_PIN` sube de forma sostenida por encima del **15 %** del flujo **y** la
  mediana de anticipación PIN→`DOC_CN` supera los **30 días**. Con la medida de
  hoy (4,35 % y 1 día) no está ni cerca.

### Lo barato que sí sale de aquí (no implementado en esta tanda)

Extraer `cbc-place-ext:NoticeTypeCode` en `scraper/codice_parser.py` cuesta poco
y es el único dato de este spike que hoy se pierde: permitiría marcar «este
expediente tuvo anuncio previo» y medir la anticipación **sobre nuestro propio
histórico** en vez de sobre tres páginas del feed. Queda anotado, no hecho: T5 no
lo pedía y toca un fichero fuera del alcance de este trabajo.

---

## Hallazgo lateral: D32 queda corroborado

El [spike D32](2026-09-spike-d32-hitos-procedimiento.md) midió la cobertura de
los hitos del procedimiento con expresiones regulares del tipo `<\w+:Nombre[ >]`,
que —como se explica arriba— **no casan prefijos con guion**. Sus ceros podrían
haber sido un artefacto de medición, así que se recontaron por `local-name` sobre
esta muestra nueva e independiente de 1 403 entradas:

| Elemento | D32 (735 entradas) | Aquí (1 403 entradas, sin regex) |
|---|---|---|
| `OpenTenderEvent` | 0,00 % | **0,00 %** |
| `OpenTenderEventTypeCode` | 0,00 % | **0,00 %** |
| `AdditionalInformationRequestPeriod` | 0,00 % | **0,00 %** |
| `InvitationSubmissionPeriod` | 0,00 % | **0,00 %** |
| `TenderResultEvent` | 0,00 % | **0,00 %** |
| `PlannedDate` / `OccurenceDate` | 0,00 % | **0,00 %** |
| `TenderSubmissionDeadlinePeriod` | 98,4 % | 99,00 % |
| `ParticipationRequestReceptionPeriod` | 3,8 % | 4,06 % |
| `AwardDate` | 45,2 % | 50,82 % |

**La conclusión de D32 se sostiene**: los hitos no se publican, y no era un fallo
del método. Los tres elementos que sí se publican salen con cifras del mismo
orden, lo que además valida que las dos muestras miden lo mismo.

---

## Cómo repetir la medida

Una página del feed y `lxml`, sin nada más:

1. `GET https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3.atom`
   con `User-Agent: TenderflowBot/1.0`; se pagina por `<link rel="next">`.
2. Por cada `<entry>`, recorrer el árbol y clasificar por `local-name` —
   **nunca por prefijo**: `ContractFolderStatusCode` y `NoticeTypeCode` viven en
   `cbc-place-ext`.
3. Para la anticipación: por cada `ValidNoticeInfo`, quedarse con
   `(NoticeTypeCode, min(IssueDate))` y restar la del PIN a la de `DOC_CN`.
4. Las etiquetas de los códigos salen de los `.gc` que el propio XML referencia
   en `listURI` — se descargan sin autenticación y son la fuente para no tener
   que adivinar qué significa un código.

No se commitea el script: no es código de producción y el valor está en los
números, no en el programa. Las tres páginas medidas fueron las vigentes el
2026-09-08; el feed rota, así que una repetición dará entradas distintas —
lo que no debería cambiar es el orden de magnitud.
