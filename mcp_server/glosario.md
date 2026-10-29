# Glosario de TenderFlow (léelo antes de escribir SQL)

Base: Postgres, solo lectura, 500 filas por consulta y 15 s por sentencia. `licitaciones` tiene cientos de miles de filas: filtra siempre (fecha, `estado`, `fuente`, órgano) y agrega en SQL en vez de traer filas. Cada ejemplo de abajo es válido contra el esquema visible.

## 1. Duplicados entre fuentes: cuenta solo la canónica

Un mismo contrato puede estar varias veces en `licitaciones`: lo publican PLACSP, TED (DOUE), la PSCP catalana y los RSS regionales, y cada corrigendo o aviso de adjudicación puede traer otra fila. `fuente` dice de dónde viene la fila (`placsp`, `bulk_YYYYMM` para la carga masiva de PLACSP, `ted`, `pscp_cat`…); `id_externo` lleva siempre el prefijo de la fuente (`ted:…`, `pscp:…`). En PLACSP va acotado por el órgano, porque el número de expediente lo teclea cada órgano y se repite: `placsp:<órgano>:<expediente>` (`placsp:11778670221627:2026/LIC/0049`), igual para `bulk_YYYYMM` (es la misma fila que el feed vivo), `placsp_watched_company_awards:<órgano>:<expediente>` y `placsp_agregadas:<órgano>:<expediente>`; el órgano es `licitaciones.organo_ref_fuente` (el `ID_PLATAFORMA` de la Plataforma). Todo lo que sigue al segundo `:` es el expediente tal cual, con sus `:` si los lleva.

`licitaciones_duplicados` marca las filas que NO son la canónica:
- `licitacion_id`: la fila duplicada (clave primaria). `canonical_id`: la fila canónica que se queda.
- `status`: `confirmed` (duplicado seguro), `pending` (lo detectó el job por órgano + CPV4 + año-mes + título y nadie lo ha revisado), `rejected` (una persona dijo que NO es duplicado: cuéntala).
- Canónica = PLACSP primero (`fuente = 'placsp'` o `bulk_YYYYMM`), TED (`fuente = 'ted'`) la última y el resto en medio; empatadas ahí, la de `fecha_publicacion` más antigua; si no, la de `primera_extraccion` (o `fecha_extraccion`) más antigua; al final `id_externo`. Con TED confirmada, la canónica es siempre la otra fuente.

Reglas, según la pregunta (ADR-026):
- Métricas (cuota de mercado, importes, bajas, conteos): excluye solo `confirmed`.
- Listados que se van a enseñar: excluye `confirmed` y `pending`.
- La fila duplicada sigue existiendo y su ficha responde; solo se deja fuera del conteo.

```sql
SELECT count(*) AS contratos
FROM licitaciones l
WHERE l.fecha_publicacion >= '2026-01-01'
  AND l.id_externo NOT IN (SELECT licitacion_id FROM licitaciones_duplicados WHERE status = 'confirmed')
```

Para saber con qué fila se quedó un duplicado:

```sql
SELECT d.licitacion_id AS duplicada, d.canonical_id AS canonica, d.status, d.confianza
FROM licitaciones_duplicados d
WHERE d.status <> 'rejected'
ORDER BY d.detectado_en DESC
LIMIT 20
```

La web pública además colapsa por clave (órgano plegado + CPV4 + año-mes + título) con una vista que aquí no es visible: sin marca en `licitaciones_duplicados`, su conteo puede ser algo menor que el tuyo.

## 2. Importe: qué base lleva cada columna (ADR-032)

`licitaciones.importe` es histórico y mezcla bases: el parser tomaba el importe sin IVA y, si faltaba, el total con IVA, sin guardar cuál. Por eso:
- `importe_tipo` dice qué es el `importe` de la fila: `sin_iva`, `con_iva` o `desconocido` (casi todo lo anterior a la re-ingesta; `NULL` se trata como `desconocido`).
- `importe_base_sin_iva`: presupuesto base de licitación SIN IVA. `importe_con_iva`: el mismo CON IVA. `valor_estimado`: valor estimado del contrato (incluye prórrogas y modificaciones; es lo que decide el procedimiento). Pueden ser `NULL`: se pueblan al re-ingerir.
- `importe_num` (numeric) e `importe` (`double precision`) son el mismo dato; `importe_num` es exacto pero puede faltar en filas antiguas: `COALESCE(importe_num, importe)`.
- Precisión: `licitaciones.importe` y los importes de `adjudicaciones` (`importe_adjudicado`, `importe_pagable`, `oferta_minima`, `oferta_maxima`) son `double precision` desde la revisión `v156`; antes eran `real` (unas 7 cifras significativas) y lo que se escribió entonces conserva ese redondeo hasta que el expediente se reingiere: 11 782 154,55 € puede leerse como 11 782 155. Para cifras exactas usa `importe_base_sin_iva`/`importe_con_iva`/`importe_num`.
- Nunca mezcles bases al promediar o sumar. Mínimo: `COALESCE(importe_tipo, 'desconocido') <> 'con_iva'`. Para declarar «sin IVA»: `importe_tipo = 'sin_iva' AND importe_base_sin_iva IS NOT NULL`. Di en la respuesta qué base usaste.
- `lotes.importe`: base sin IVA del lote.

`adjudicaciones` es lo que se adjudicó realmente, una fila por empresa ganadora (y por lote):
- `importe_adjudicado`: importe de adjudicación SIN IVA. `importe_pagable`: importe a pagar según el aviso (PayableAmount). `oferta_minima`/`oferta_maxima`/`n_ofertas_recibidas`: las ofertas del concurso.
- Una UTE produce una fila por miembro con el MISMO importe: sumar `importe_adjudicado` entre empresas cuenta ese contrato varias veces. Para totales de mercado agrupa por `licitacion_id` (y `lote_id`) o usa `max()` por contrato; para el ranking de una empresa, cada miembro suma el importe completo.
- Baja = `(base - adjudicado) / base * 100`. Compara solo base sin IVA contra adjudicado, con ambos positivos y `adjudicado <= 1.5 * base` (fuera de eso es error de fuente).

```sql
SELECT count(*) AS n,
       round(avg((l.importe_base_sin_iva - a.importe_adjudicado) / l.importe_base_sin_iva * 100)::numeric, 2) AS baja_media_pct
FROM adjudicaciones a
JOIN licitaciones l ON l.id_externo = a.licitacion_id
WHERE l.importe_tipo = 'sin_iva'
  AND l.importe_base_sin_iva > 0
  AND a.lote_id IS NULL
  AND a.importe_adjudicado > 0
  AND a.importe_adjudicado <= l.importe_base_sin_iva * 1.5
  AND l.id_externo NOT IN (SELECT licitacion_id FROM licitaciones_duplicados WHERE status = 'confirmed')
```

```sql
SELECT estado, count(*) AS n, round(avg(importe_base_sin_iva)::numeric, 0) AS base_media_sin_iva
FROM licitaciones
WHERE importe_tipo = 'sin_iva' AND importe_base_sin_iva > 0
GROUP BY estado
ORDER BY n DESC
```

## 3. `estado` de una licitación

Código de texto de la fuente, normalizado. `NULL` significa sin dato.
- Abiertos o por venir: `PUB` publicada, `EV` en evaluación, `PRE` anuncio previo y `CPM` consulta preliminar (estos dos sin pliego ni plazo todavía), `CREA` creada.
- Cerrados: `RES` resuelta, `ADJ` adjudicada, `ANUL` anulada, `EJEC` en ejecución (ya adjudicada).
- `AGR` es «publicación agregada» de la PSCP: avisos que agrupan contratos ya celebrados. Es la gran mayoría de las filas y NO es una oportunidad: sin filtrar `estado`, los conteos miden el tamaño del corpus.
- Puede aparecer un código nuevo o sin traducir (se conserva en crudo): enumera con `GROUP BY estado` antes de dar por completa una lista.
- «Abierta» = `estado IS NULL OR estado NOT IN ('RES','ADJ','ANUL','AGR','EJEC')`; para «aún admite ofertas» añade además `fecha_limite` futura.

```sql
SELECT estado, count(*) AS n FROM licitaciones GROUP BY estado ORDER BY n DESC
```

```sql
SELECT count(*) AS abiertas_con_plazo
FROM licitaciones
WHERE (estado IS NULL OR estado NOT IN ('RES','ADJ','ANUL','AGR','EJEC'))
  AND fecha_limite >= to_char(now(), 'YYYY-MM-DD')
```

## 4. Claves de unión

- `licitaciones.id_externo` (texto, PK) es la clave de cualquier tabla hija: `adjudicaciones.licitacion_id`, `lotes.licitacion_id`, `pursuits.licitacion_id`, `licitaciones_duplicados.licitacion_id`/`canonical_id`.
- Ids viejos: hasta la re-key de 2026-10 (`v164`) las filas de PLACSP llevaban el expediente sin prefijo (`2026/LIC/0049`). Ese id ya no existe en `licitaciones`; `licitaciones_id_anterior` dice a qué fila apunta (`id_anterior` → `id_externo`, `motivo = 'rekey_placsp_organo'`). Un id que alguien te dé y no esté en `licitaciones` puede ser uno viejo: búscalo ahí antes de decir que no existe. Para buscar por número de expediente, compara con lo que sigue al órgano, no con el id entero:

```sql
SELECT a.id_anterior, l.id_externo, l.titulo, l.organo_contratacion
FROM licitaciones_id_anterior a
JOIN licitaciones l ON l.id_externo = a.id_externo
WHERE a.id_anterior = '2026/LIC/0049'
```
- Empresas: `adjudicaciones.nif` es el NIF tal como lo publica la fuente (texto, puede faltar o venir con variantes). `adjudicaciones.empresa_id` apunta a `empresas.empresa_id` (empresa canónica con `nif_canonico`, `es_ute`, `es_pyme`); las variantes de nombre y NIF están en `empresa_aliases`. Une por `empresa_id` si existe; si no, por `nif`. Nunca por nombre.
- Órganos: `licitaciones.organo_contratacion` es texto libre («Ayuntamiento de Madrid» y «AYUNTAMIENTO DE MADRID» cuentan como dos). `licitaciones.organo_id` apunta al maestro `organos.organo_id`, que lleva el código oficial DIR3 en `dir3`; las grafías están en `organo_aliases`. `organo_id` puede ser `NULL` (aún sin resolver): para no perder esas filas, agrupa por `COALESCE(organo_id::text, organo_contratacion)`.
- Clientes: `organizations.id` es el `organization_id` del resto de tablas de cliente (`pursuits`, `organization_memberships`, `organization_nifs`…). `users.id` es `user_id`. `organization_nifs.nif` enlaza una organización cliente con su empresa (`empresas.nif_canonico`).

```sql
SELECT o.nombre_canonico AS organo, o.dir3, count(*) AS n
FROM licitaciones l
JOIN organos o ON o.organo_id = l.organo_id
WHERE l.estado IS DISTINCT FROM 'AGR'
GROUP BY o.nombre_canonico, o.dir3
ORDER BY n DESC
LIMIT 10
```

```sql
SELECT e.nombre_canonico AS empresa, count(DISTINCT a.licitacion_id) AS contratos, sum(a.importe_adjudicado) AS adjudicado_sin_iva
FROM adjudicaciones a
JOIN empresas e ON e.empresa_id = a.empresa_id
WHERE a.fecha_adjudicacion >= '2026-01-01'
  AND a.licitacion_id NOT IN (SELECT licitacion_id FROM licitaciones_duplicados WHERE status = 'confirmed')
GROUP BY e.nombre_canonico
ORDER BY adjudicado_sin_iva DESC
LIMIT 10
```

## 5. Pursuits (oportunidades en seguimiento)

Un pursuit es una licitación que una organización cliente ha decidido seguir: una fila por (`organization_id`, `licitacion_id`, `lote_numero`). Es dato de cliente; filtra por `organization_id` cuando preguntes por una cuenta.
- `status`, el embudo: `identified` → `qualifying` → `go_no_go` → `preparing` → `submitted` → `won` / `lost` / `withdrawn` (terminales).
- `decision`: `pending`, `go`, `no_go`. `outcome`: `pending`, `won`, `lost`, `cancelled` (`withdrawn` termina en `cancelled`).
- `offer_price_eur` es la oferta presentada y `awarded_amount_eur` lo adjudicado, en euros; `score_al_abrir` y `banda_al_abrir` son el score del radar al abrirlo.
- Fechas `identified_at`, `decision_at`, `submitted_at`, `closed_at`: texto ISO.
- Tablas hijas por `pursuit_id`: `pursuit_comments`, `pursuit_tasks` (con `estado`), `pursuit_events` (`event_type`, `payload_json` en texto), `pursuit_attachments`; `pursuit_comment_mentions` cuelga de `pursuit_comments.id`. Comentarios, tareas y adjuntos se borran con `deleted_at`: filtra `deleted_at IS NULL`.

```sql
SELECT outcome, count(*) AS n, sum(awarded_amount_eur) AS adjudicado_eur
FROM pursuits
WHERE outcome <> 'pending'
GROUP BY outcome
```

```sql
SELECT p.id, p.status, count(c.id) AS comentarios
FROM pursuits p
LEFT JOIN pursuit_comments c ON c.pursuit_id = p.id AND c.deleted_at IS NULL
GROUP BY p.id, p.status
ORDER BY comentarios DESC
LIMIT 10
```

## 6. `tecnologia` es un CSV de códigos

`licitaciones.tecnologia` guarda códigos separados por coma, a veces con espacios: `SAP,SALESFORCE`. Son claves en mayúsculas del diccionario de tecnologías (`SAP`, `SALESFORCE`, `ORACLE`, `MICROSOFT`, `ERP`, `CRM`, `CIBERSEGURIDAD`, `DATOS_IA`…). `tecnologia = 'SAP'` pierde los multi-tecnología y `LIKE '%SAP%'` casa con códigos que solo lo contienen: explota el CSV.
- `tecnologia` es la señal por palabras clave de la ingesta. `ml_tecnologias` (CSV por probabilidad), `ml_tech_principal` y `ml_proba_max` las derivan el clasificador, el etiquetado LLM y la señal de pliego (`licitacion_tecnologia_score`). Una fila con `tecnologia IS NULL` puede ser tecnología igualmente si `ml_tecnologias` trae algo. Para «es tecnología» usa ambas (ADR-026).
- `ml_proba` es otra cosa: la P(SAP) del clasificador binario `sap_classifier`. Sin una versión activa de ese modelo que haya pasado el gate (`model_versions`, `name = 'sap_classifier'`, `is_active = 1`) **no es señal** (D55): da ≥ 0,69 a la mayoría de su población. No la uses para decidir ni ordenar; la superficie del producto tampoco la usa.

```sql
SELECT t AS tecnologia, count(*) AS n
FROM licitaciones l, unnest(string_to_array(replace(l.tecnologia, ' ', ''), ',')) AS t
WHERE l.tecnologia IS NOT NULL AND l.tecnologia <> '' AND l.fecha_publicacion >= '2026-01-01'
GROUP BY t
ORDER BY n DESC
```

```sql
SELECT count(*) AS n
FROM licitaciones
WHERE 'SAP' = ANY (string_to_array(replace(COALESCE(tecnologia, ''), ' ', ''), ','))
  AND fecha_publicacion >= '2026-01-01'
```

## 7. Fechas como `text`

Casi todas las fechas son `text` ISO-8601 (`2026-09-01`, o `2026-09-01T10:00:00+00:00`): `fecha_publicacion`, `fecha_limite`, `fecha_extraccion`, `fecha_adjudicacion`, `created_at`, `identified_at`, etc. Orden y comparación por texto funcionan; no uses `now()` ni `interval` contra ellas sin convertir.
- Rangos: `fecha_publicacion >= '2026-01-01' AND fecha_publicacion < '2027-01-01'`. Mes: `substr(fecha_publicacion, 1, 7)`. Hoy: `to_char(now(), 'YYYY-MM-DD')`.
- Evita `::date` sobre columnas texto: una sola fila mal formada tumba la consulta. Existen columnas tipadas `fecha_pub_d` (date), `fecha_publicacion_ts` y `fecha_limite_ts` (timestamptz), pero pueden ser `NULL` en filas no rellenadas.
- `fecha_extraccion_ts`, `primera_extraccion_ts`, `fecha_inicio_ts`, `fecha_fin_ts`, `fecha_actualizacion_fuente_ts` y `fecha_adjudicacion_ts` (en `adjudicaciones`) son sombras timestamptz en migración: mientras no se rellenen, muchas filas las tienen `NULL`. Filtra y ordena por la columna de texto.
- `fecha_publicacion` es la del anuncio; `fecha_extraccion` es cuándo lo leyó el scraper y se reescribe en cada pasada; `primera_extraccion` es el primer avistamiento. Para «cuándo se publicó» usa la primera.
- Las columnas `timestamp with time zone` (`deleted_at`, `created_at` de algunas tablas) sí admiten `now() - interval '7 days'`.

```sql
SELECT substr(fecha_publicacion, 1, 7) AS mes, count(*) AS n
FROM licitaciones
WHERE fecha_publicacion >= '2026-01-01' AND fecha_publicacion < '2027-01-01'
  AND estado IS DISTINCT FROM 'AGR'
GROUP BY mes
ORDER BY mes
```

## 8. Otros consejos

- Texto libre: `search_vector @@ websearch_to_tsquery('spanish', 'mantenimiento sap')` usa índice; `titulo ILIKE '%…%'` recorre la tabla entera. La búsqueda por `search_vector` casa palabras enteras (con raíz): «automatización» no encuentra «hiperautomatización». Si no da nada, prueba `titulo ILIKE '%raíz%'` acotado por fecha u órgano.
- `buscar_licitaciones` solo ve licitaciones con `tecnologia` asignada. Un contrato de tecnología con `tecnologia` vacía (p. ej. clasificado solo por CPV) no sale ahí: búscalo en `licitaciones` con `consultar_sql`.
- Criterios de adjudicación (`licitacion_criterios_adjudicacion`): `es_precio` y `licitaciones.peso_precio_pct` se deducen del texto del criterio y fallan con las etiquetas genéricas de PLACSP. «…mera aplicación de fórmulas, diferentes al precio» sale como `es_precio = true` y el criterio de precio real, no. El criterio de precio es el de `subtipo_codigo = '1'`; el nombre concreto del criterio suele estar en `nota`, no en `descripcion`. Ante la duda, lee los tres campos antes de dar el peso del precio.
- Antes de unir tablas desconocidas, llama a `describir_tabla`: muestra columnas, claves foráneas y 3 filas de ejemplo.
- Las tablas de credenciales, sesiones y tokens no son visibles; `users` y `webhooks` solo muestran sus columnas no sensibles, y `SELECT *` sobre ellas falla: pide columnas concretas.

```sql
SELECT id_externo, titulo, fecha_publicacion
FROM licitaciones
WHERE search_vector @@ websearch_to_tsquery('spanish', 'mantenimiento sap')
  AND fecha_publicacion >= '2026-01-01'
ORDER BY fecha_publicacion DESC
LIMIT 20
```
