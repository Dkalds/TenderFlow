# ADR-032 — Semántica del importe y maestro de órganos

- **Estado:** aceptado
- **Fecha:** 2026-09-06
- **Relacionado:** [ADR-022](ADR-022-frontera-de-persistencia.md),
  [ADR-026](ADR-026-caminos-de-lectura-y-precedencia-tecnologica.md)
  (la analítica de órganos es uno de sus seis caminos de lectura),
  [ADR-009](ADR-009-framework-conectores-multifuente.md)
- **Cierra:** D21 y D22 del
  [plan complementario](../plans/2026-09-plan-arquitectura-v2-complementario.md)
- **Implementa:** C1.1 y C1.2 de ese plan

---

## Contexto

### El importe mezcla dos bases y no lo dice

`scraper/codice_parser.py` toma `cbc:TaxExclusiveAmount` y, si falta, cae a
`cbc:TotalAmount` (líneas 448-450 para lotes, 491-499 y 651-653 para el
expediente). El primero es la base **sin** IVA; el segundo lo **incluye**. La
fila resultante guarda un número en `licitaciones.importe` y **no guarda cuál
de los dos fue**.

Consecuencia medible: `services/competitive/bajas.py` calcula bajas —
`(importe - adjudicado) / importe` — sobre una población en la que unas filas
llevan IVA y otras no. Una baja del 21 % puede ser exactamente el IVA. Los
escenarios de precio y el scoring por banda heredan el mismo defecto.

Además, `cbc:EstimatedOverallContractAmount` —el valor estimado del contrato,
que incluye prórrogas y modificaciones y es lo que la Ley 9/2017 usa para
determinar el procedimiento— no se extrae en absoluto.

### El órgano de contratación es una cadena de texto

`licitaciones.organo_contratacion` es texto libre. La analítica agrupa y cuenta
por ese texto (`db/repositories/aggregates.py:245`,
`services/analytics/organos.py:113`), así que «Ayuntamiento de Madrid» y
«AYUNTAMIENTO DE MADRID» son dos órganos con dos historiales. El parser no
extrae el código DIR3 aunque CODICE lo transporte.

El maestro de **empresas** ya resolvió este problema en `v35`, con canónico,
alias y cola de revisión. El de órganos no existe.

---

## Decisión

### A. Tres importes aditivos y una etiqueta (D21)

El parser extrae los tres por separado y el upsert los persiste en columnas
propias:

| Columna | Origen CODICE | Qué es |
|---|---|---|
| `importe_base_sin_iva` | `cbc:TaxExclusiveAmount` | Presupuesto base de licitación sin IVA |
| `importe_con_iva` | `cbc:TotalAmount` | El mismo presupuesto con IVA |
| `valor_estimado` | `cbc:EstimatedOverallContractAmount` | Valor estimado del contrato (prórrogas y modificaciones incluidas) |
| `importe_tipo` | derivada | Qué representa el `importe` histórico de esa fila |

**`importe` se conserva** como alias de la base sin IVA. No se renombra ni se
borra: lo consumen el frontend, los exports, el scoring y varias vistas
materializadas, y romperlo a cambio de un nombre mejor no compra nada.

`importe_tipo ∈ {sin_iva, con_iva, desconocido}` etiqueta **lo ya ingerido**:
las filas históricas no se pueden reinterpretar sin volver a parsear el CODICE
original, así que se marcan `desconocido` y el backfill las corrige cuando la
re-ingesta pasa por ellas. Las filas nuevas nunca son `desconocido` — ese es el
umbral 0 que `audit_domain_truth` vigila.

### B. Todo cálculo comparativo usa la base sin IVA, y lo declara

`bajas`, `pricing` y `scoring` leen **solo** `importe_base_sin_iva`, excluyen
las filas que no la tienen, y su respuesta lleva `base: "sin_iva"`. Un cálculo
que no puede declarar su base no se publica.

Motivo: mezclar bases no es un error de precisión, es un error de significado.
Una media entre importes con y sin IVA no es una media de nada.

### C. El maestro de órganos copia el patrón de `empresas` (D22)

```
organos(id, nombre_canonico, dir3, ccaa, tipo, url_perfil, ...)
organo_aliases(organo_id, alias, origen, ...)
```

más cola de revisión, exactamente como `empresas` desde `v35`. No se inventa un
patrón nuevo para el mismo problema.

**La clave es DIR3 cuando existe; el nombre normalizado es el respaldo.** DIR3
es el identificador oficial del inventario de unidades administrativas: si
CODICE lo trae, dos grafías con el mismo DIR3 son el mismo órgano sin
ambigüedad. Cuando no lo trae —fuentes regionales, expedientes antiguos— se
resuelve por `services/dedupe.normalize_organo`, que ya existe, y la fusión
dudosa va a la cola de revisión humana en vez de decidirse sola.

`licitaciones.organo_id` es **nullable**. Un expediente cuyo órgano no resuelve
sigue siendo un expediente válido; lo que no puede es desaparecer de la
analítica. Durante el backfill, la analítica agrupa por `organo_id` cuando lo
hay y por texto normalizado cuando no.

### D. Las cifras cambian, y el cambio se anota

Agrupar por `organo_id` **fusiona** grafías que hoy cuentan como órganos
distintos: `/analytics/organos` devolverá menos órganos y más expedientes por
órgano. Eso es la corrección, no una regresión. El delta de
`make audit-truth-check` antes y después queda anotado en la PR.

---

## Consecuencias

**A favor.** Una baja deja de poder ser el IVA. El valor estimado —el número
que determina el procedimiento— entra en el dato. Un órgano tiene historial,
perfil del contratante y página propia en vez de tantos como grafías.

**En contra.** Cuatro columnas más en la tabla núcleo y un backfill masivo
sobre ella. `importe_tipo = desconocido` será mayoría durante meses: el dato
histórico no mejora solo, y decir «desconocido» es preferible a fingir que se
sabe.

**Riesgo.** Alto en la columna `organo_id`: es la tabla núcleo y el backfill
toca todas las filas. Mitigación: `plan` antes de `apply`, en ventana, y la
analítica con lectura dual (§C) mientras el backfill no llegue al 95 %.

**Lo que este ADR no decide.** El predecesor y los similares (C1.3), que usan
el órgano pero no lo definen, ni la exposición de lotes en el contrato (C1.4).
