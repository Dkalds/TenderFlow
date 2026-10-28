---
rfc: 2026-10-24-identidad-placsp-organo-expediente
title: "Identidad de las licitaciones de PLACSP: el expediente acotado por el órgano (`placsp:<ID_PLATAFORMA>:<ContractFolderID>`)"
issue: "(sin issue: P1 de docs/IMPROVEMENT_BACKLOG.md, «La identidad de PLACSP no incluye el órgano», 2026-10-24)"
author: agent:claude-code
date: 2026-10-24
status: approved
related:
  - "[[ADR-009-framework-conectores-multifuente]]"
  - "[[ADR-026-caminos-de-lectura-y-precedencia-tecnologica]]"
  - "[[ADR-032-semantica-del-importe-y-maestro-de-organos]]"
---

## Estado

`approved` el 2026-10-25: el dueño autorizó la fase 1 (migración A) y abrir
el PR que la implementa. Las fases 2 a 5 siguen como están escritas abajo;
las decisiones que la implementación de la fase A tomó donde este texto
dejaba margen están en §«Decisiones de la fase A».

## Por qué hace falta un RFC

`AGENTS.md` §5 lo exige por dos motivos a la vez:

- **Cambio de persistencia irreversible.** Cambia la clave primaria de unas
  24.700 filas de `licitaciones` y la de todo lo que las referencia (17 FK, 7
  columnas sin FK, 3 tablas polimórficas y las que la re-key de PSCP se dejó,
  ver §4).
- **Cambio de semántica en el contrato API público.** `GET
  /api/v1/licitaciones/{id_externo}` está en `api/contrato_publico.py`, y el
  `id_externo` de esas filas deja de ser el que un cliente guardó.

Además contradice una decisión registrada: el *Rationale* de
[ADR-009](../adr/ADR-009-framework-conectores-multifuente.md) descartó
«migrar las PKs existentes a `placsp:...`» por «alto riesgo sin beneficio».
El beneficio ya está medido (abajo), así que antes de mergear la fase 3 hace
falta un ADR nuevo que lo revise (ver §«Qué cambia en la documentación»).

Este RFC **no escribe código ni migraciones**: fija la clave, la lista de lo
que se toca, el orden y cómo se verifica, para que el dueño lo apruebe antes.

## Contexto

### El defecto

`scraper/codice_parser.py` (`parse_entry` y `parse_entry_unfiltered`) toma
`cbc:ContractFolderID` como `id_externo`, y `PlacspAtomConnector` y
`PlacspBulkConnector` (`scraper/connectors/placsp.py`) lo escriben **sin
prefijo** y con `fuente = placsp` o `bulk_YYYYMM`. El upsert va por
`ON CONFLICT(id_externo)` (`db/upsert.py`). `ContractFolderID` es el número de
expediente que teclea cada órgano («1681/2026», «2026/LIC/0049») y se repite
entre órganos: la segunda licitación **sustituye** a la primera sin error.

Lo mismo, con menos peso, en otros dos escritores de la familia PLACSP:
`placsp_agregadas:<ContractFolderID>` (apagado, 0 filas en producción) y
`placsp_watched_company_awards:<ContractFolderID>` (199 filas). Contratos
menores ya se resolvió en esta rama con
`placsp_menores:<ID_PLATAFORMA>:<ContractFolderID>` (ver el docstring de
`scraper/connectors/placsp_menores.py`), y PSCP con
`pscp:<uuid>:<codi_expedient>` (`v153_rekey_pscp_id_externo`), que es el
precedente directo de este RFC.

La pisada no se queda en la fila. `scraper/connectors/base.py` solo reemplaza
adjudicaciones, documentos y lotes cuando la entrada nueva trae alguno («los
ids sin adj no entran al dict»): si la segunda licitación llega sin
adjudicatario, **hereda las adjudicaciones de la primera**. Una convocatoria
abierta puede aparecer así como adjudicada a la empresa que ganó el contrato de
otro órgano. Los documentos se acumulan del mismo modo, y cada pisada deja en
`licitaciones_history` un snapshot ajeno y, a veces, un `contrato_eventos` de
`modificacion` que no es tal.

### Lo medido (2026-10-24)

**En producción** (lecturas por el MCP de solo lectura):

| | Nº |
|---|---:|
| Filas `placsp` | 7.057 |
| Filas `bulk_*` (22 meses, `bulk_202501` a `bulk_202610`) | 17.484 |
| Filas `placsp_watched_company_awards` | 199 |
| Filas `placsp_agregadas` / `placsp_menores` | 0 / 0 |
| `id_externo` PLACSP que ya contienen `:` («RSC: 2019-00078», «S: 41/19-68») | 7 |
| Filas PLACSP con `idEvl` en `url` | 24.520 de 24.541 (21 sin él) |

Hijas de esas filas: `licitacion_tecnologia_score` 150.043, `documentos`
53.917, `licitaciones_history` 49.508, `adjudicaciones` 19.272,
`domain_events` (`aggregate_type = 'licitacion'`) 13.016, filas de
`licitaciones_duplicados` que las tocan 1.948, y datos de usuario: 7
`pursuits`, 2 `follows`, 14 `user_notifications`, 39 `ml_feedback`.

**Pisadas visibles en el historial.** El backlog midió 339 de 10.007
`id_externo` con historia que tienen dos o más `organo_contratacion` distintos
**entre sus snapshots** (3,39 %); en una muestra de 8, 7 eran licitaciones
distintas y 1 un renombre. Comparando además cada snapshot con la fila actual
(la consulta de §«Las filas ya pisadas»):

| | `id_externo` | pares (`id_externo`, órgano perdido) |
|---|---:|---:|
| Algún snapshot con otro órgano que la fila actual | 456 | 661 |
| … con órgano **y** título distintos (`similarity < 0,5` en los dos) | 379 | 570 |
| … dudosos o renombres (alguno de los dos parecido) | — | 93 |

Es una **cota inferior**: el historial empieza el 2026-05-22 y solo escribe
snapshot cuando cambia un campo de `HISTORY_TRACKED_FIELDS`
(`config/constants.py`, que **no** incluye `organo_contratacion`; en la
práctica cambia la `descripcion`, que en PLACSP lleva el órgano). Sobre los
`id_externo` afectados hay 1 `pursuit` y 0 `follows`.

**En el feed vivo** (sindicación 643, 10 páginas descargadas el 2026-10-24,
4.830 entradas, 4.653 `<id>` Atom distintos, ~2 días):

| | Nº |
|---|---:|
| Entradas con `ID_PLATAFORMA` / `NIF` / `DIR3` | 4.830 / 4.830 / 3.629 (75 %) |
| `ContractFolderID` usados por 2 o más `ID_PLATAFORMA` | 94 de 4.518 (236 entradas) |
| Pares (`ID_PLATAFORMA`, `ContractFolderID`) | 4.653 = nº de `<id>` Atom, 1:1 |
| `idEvl` distintos | 4.653, 1:1 con el `<id>` Atom |
| `ID_PLATAFORMA` con más de un DIR3 / más de un nombre | 0 / 0 |
| `NIF` compartidos por más de un `ID_PLATAFORMA` | 123 |
| Forma de `ID_PLATAFORMA` | solo dígitos, 14 (4.810) o 15 (20) caracteres |

El backlog midió 67 de 3.646 en 8 páginas (2,5 %); esta muestra da 94 de 4.518
(2,1 %). Lo mismo en las dos.

**En agregadas** (sindicación 1044, 15 páginas, 7.064 entradas, 6.328 `<id>`):
el órgano viene en `ID_OC_PLAT` (100 %), no en `ID_PLATAFORMA` (0 %); DIR3 en el
37 %. 34 de 6.290 `ContractFolderID` compartidos por órganos distintos (91
entradas). `ID_OC_PLAT` es heterogéneo —«935078», «207», «A31118441»,
«24446_24448_25089»— pero ninguno cuelga de dos plataformas raíz distintas. Y
un hallazgo que importa para la clave: **3 `<id>` cambian de
`ContractFolderID` entre versiones** (Fundación Rioja Salud,
`40-7-2.01-0032/2026` → `40-AP-0029/2026`; dos de la Mancomunidad de Pamplona,
de vacío a relleno), y 4 entradas llegan con `ContractFolderID` vacío.

## Decisión

### 1. La clave

| Fuente (`licitaciones.fuente`) | `id_externo` nuevo | Identificador del órgano, por preferencia |
|---|---|---|
| `placsp`, `bulk_YYYYMM` | `placsp:<órgano>:<ContractFolderID>` | `ID_PLATAFORMA`, `NIF`, `DIR3` |
| `placsp_agregadas` | `placsp_agregadas:<órgano>:<ContractFolderID>` | `ID_OC_PLAT`, `DIR3` |
| `placsp_watched_company_awards` | `placsp_watched_company_awards:<órgano>:<ContractFolderID>` | como `placsp` |
| `placsp_menores` | sin cambios (`placsp_menores:<órgano>:<ContractFolderID>`) | ya implementado |

Reglas:

- **El prefijo es de la familia, no del carril.** El feed vivo y el bulk
  escriben hoy la **misma** fila (cambia `fuente`, no la clave), y tienen que
  seguir haciéndolo: los dos llevan `placsp:`, nunca `bulk_202608:`.
- **De dónde sale el órgano.** Los tres carriles leen el mismo nodo CODICE,
  `cacext:ContractFolderStatus/cacext:LocatedContractingParty/cac:Party/cac:PartyIdentification/cbc:ID`
  con su `schemeName`. El ZIP mensual del bulk (`scraper/bulk_downloader.py`)
  contiene los mismos `.atom` que el feed, así que la extracción es una sola.
  `identificador_organo` sale de `placsp_menores.py` a `scraper/codice_parser.py`,
  parametrizado por la lista de esquemas, y `parse_entry` /
  `parse_entry_unfiltered` lo devuelven en un campo nuevo de `Licitacion`
  (`organo_ref_fuente`, §3).
- **Una sola función construye la clave** (`clave_placsp(prefijo, órgano,
  expediente)`, en `scraper/codice_parser.py`), y la usan **todos** los
  escritores: `scraper/connectors/placsp.py` (`_PlacspParseCore`),
  `placsp_agregadas.py`, `watched_company_awards.py`, `placsp_menores.py`,
  `scraper/pipeline.py::process_daily` (el carril legacy que aún usa el
  reintento de la DLQ), `scraper/seed_negatives.py` (inserta en
  `licitaciones` con `ON CONFLICT DO NOTHING`) y `scraper/reproceso_lotes.py`
  (hoy compara el `ContractFolderID` crudo con su conjunto objetivo).
- **El `:` delimita.** El órgano se escribe con `%` → `%25` y `:` → `%3A`
  (ningún valor medido los lleva, pero `ID_OC_PLAT` es texto libre). El
  expediente va tal cual: puede llevar `:` (7 filas en producción, 1 en la
  muestra del feed), y como el órgano no puede, «todo lo que sigue al segundo
  `:`» es siempre el expediente.
- **Sin órgano, no se escribe.** La entrada se descarta y se cuenta
  (`placsp_sin_identificador_de_organo`, como en menores). Medido: 0 de 4.830
  en el feed vivo; el bulk histórico se mide en la fase 0.
- **Sin `ContractFolderID`** se conserva el respaldo actual (el id del
  `summary` y, si no, el `<id>` Atom), ahora dentro del órgano.
- **Los respaldos `NIF` y `DIR3` existen por robustez, no por uso.** Un órgano
  que unas veces trae `ID_PLATAFORMA` y otras no partiría su expediente en dos
  filas; se cuenta por esquema usado (`placsp_organo_por_respaldo_<esquema>`) y
  si deja de ser 0 se mira.

Por qué `ID_PLATAFORMA` y no otra cosa, con las cifras de arriba: es el único
identificador presente en el 100 % de las entradas que además es 1:1 con el
órgano. DIR3 falta en el 25 % y el NIF lo comparten 123 órganos de la muestra
(una entidad con varios órganos de contratación). Con él, (órgano, expediente)
es 1:1 con la entrada Atom, y una actualización repite el mismo par: el upsert
sigue siendo idempotente (AGENTS.md §3.2).

### 2. El expediente natural

`services/dedupe.py::natural_expediente` y su gemelo
`db/repositories/dedupe.py::_EXPEDIENTE_NATURAL_SQL` siguen devolviendo el
`ContractFolderID` para PLACSP, que es con lo que casa el resto de fuentes
(BT-22 de TED en `detect_duplicados_por_referencia`, el expediente de PSCP y de
agregadas en `detect_duplicates`):

| `id_externo` | Expediente natural |
|---|---|
| `placsp:<órgano>:<exp>`, `placsp_agregadas:<órgano>:<exp>`, `placsp_watched_company_awards:<órgano>:<exp>` | `<exp>` (todo tras el segundo `:`) |
| `placsp_menores:<órgano>:<exp>` | `<órgano>:<exp>` — sin cambios: no debe casar con nada (docstring de menores) |
| `pscp:<uuid>:<codi>` | `<codi>` — sin cambios |
| sin `:` (PLACSP antiguo, solo durante la transición) | el id entero — sin cambios |
| `<prefijo>:<resto>` (el resto de fuentes) | `<resto>` — sin cambios |

La tupla de prefijos acotados por órgano vive en un solo sitio que las dos
capas pueden importar (`shared/`, por la regla de capas de AGENTS.md §2), y el
SQL se genera desde ella:
`regexp_replace(l.id_externo, '^(placsp|placsp_agregadas|placsp_watched_company_awards):[^:]*:', '')`
antes del corte por el primer `:` y del recorte del UUID de PSCP. El test que
fija que los dos gemelos dan lo mismo gana los casos de la tabla. Efecto
lateral bueno: las 7 filas cuyo expediente lleva `:` («RSC: 2019-00078»)
recuperan su expediente natural, que hoy se corta mal en « 2019-00078».

`services/dedupe.py::marcar_republicaciones_ted` deduce la fuente de la
canónica del prefijo del id con `"placsp"` por defecto; con el prefijo nuevo
sigue dando `placsp`, pero pasa a leer `licitaciones.fuente`.

### 3. Dos piezas de esquema nuevas (migración aditiva)

- **`licitaciones.organo_ref_fuente TEXT NULL`**: el identificador del órgano en
  la plataforma de origen, tal como entra en la clave (`ID_PLATAFORMA`,
  `ID_OC_PLAT` o el respaldo). El upsert lo escribe con `COALESCE` (nunca lo
  pisa con `NULL`). Es lo que hace posible el mapa viejo → nuevo de la fase 3:
  hoy no se guarda en ninguna columna (`licitaciones` tiene `organo_id`, que
  apunta al maestro de ADR-032, y `organos.dir3`, no el id de la Plataforma).
- **`licitaciones_id_anterior`**: `(id_anterior TEXT PRIMARY KEY, id_externo
  TEXT NOT NULL REFERENCES licitaciones(id_externo) ON DELETE CASCADE, motivo
  TEXT NOT NULL, creado_en TEXT NOT NULL)`. Una fila por clave re-escrita. Es lo
  que sostiene las redirecciones y la resolución de ids viejos (§5). Genérica a
  propósito (`motivo`): la próxima re-key la reutiliza, y la guarda de FK de la
  migración de re-key la obliga a repuntarla.

Las dos son nullables o nuevas: `ADD COLUMN` sin `DEFAULT` y `CREATE TABLE`, sin
reescritura de tabla. Hay que clasificarlas en `mcp_server/catalogo.py` y
regenerar los grants del rol del MCP (runbook de recuperación ante desastres,
§5).

### 4. Todo lo que guarda un `id_externo`

Medido contra el catálogo de producción (`pg_constraint`, `pg_attribute`) el
2026-10-24. **Ninguna FK declara `ON UPDATE CASCADE` ni es diferible**, así que,
como en v153, la re-key es copiar la fila con su id nuevo, repuntar y borrar la
vieja; no un `UPDATE` de la clave.

| Grupo | Tabla.columna | Qué se hace |
|---|---|---|
| FK `ON DELETE CASCADE` (15) | `adjudicaciones.licitacion_id`, `contrato_eventos.licitacion_id`, `documentos.licitacion_id`, `licitacion_criterios_adjudicacion`, `licitacion_garantias`, `licitacion_solvencia`, `licitacion_tecnologia_pliego`, `licitacion_tecnologia_score` (con `trg_lts_derivar_ml` desactivado mientras se repunta), `licitaciones_duplicados.licitacion_id` **y** `.canonical_id`, `licitaciones_history.id_externo`, `lotes`, `predicciones_baja`, `predicciones_retencion`, `tender_fact_sheets` | Repuntar |
| FK sin `ON DELETE` | `resoluciones_recurso.licitacion_id` | Repuntar |
| FK `ON DELETE RESTRICT` | `pursuits.licitacion_id` | Repuntar |
| Sin FK | `asistente_feedback.licitacion_id`, `contratos_cartera.licitacion_id`, `mat_clusters.id_externo`, `pending_digests.licitacion_id`, `radar_dismissals.id_externo`, `user_notifications.licitacion_id`, `watchlist_items.id_externo` | Repuntar |
| Polimórficas | `follows.target_id` (`target_type = 'licitacion'`), `etiquetas_aplicadas.objeto_id` (`objeto_tipo = 'favorito'`), `feature_store.entity_id` (`entity_type = 'licitacion'`) | Repuntar con su filtro |
| **Que v153 no cubrió** | `domain_events.aggregate_id` (`aggregate_type = 'licitacion'`) | Repuntar. v153 lo omitió y dejó **1.117 eventos PSCP con `aggregate_id` huérfano** (medido hoy): conviene repararlos en la misma revisión con el mismo mapa (ver «Preguntas abiertas») |
| | `domain_events.payload_json` de los **no despachados** (`dispatched_at IS NULL`) | Reescribir `id_externo`/`licitacion_id` del JSON. Los despachados se quedan como se enviaron |
| | `ml_feedback.expediente` (39 filas apuntan hoy a ids PLACSP) | Repuntar donde casa con un `id_externo` |
| | `organization_references.expediente_id` | Repuntar donde casa con un `id_externo` (la columna admite texto libre) |
| Vista materializada | `licitaciones_canonicas.id_externo` (ADR-026, camino 5) | `REFRESH` al terminar. Su definición no depende de la forma del id (el último desempate es `id_externo`, que solo reordena empates exactos), así que **no** hace falta reconstruirla |
| Colas | `jobs.payload_json` pendientes, `webhook_deliveries` en reintento, DLQ de PLACSP (`payload_ref` = `<licitacion_id>:<nif>:<importe>`) | La ventana empieza con el worker parado y la cola de PLACSP vacía; la migración aborta si queda algún trabajo pendiente que nombre un id del mapa. Los webhooks en reintento salen con el payload con que se construyeron. La DLQ se vacía antes (o el reintento re-parsea con la clave nueva) |
| Rastro | `audit_log` y similares (`resource = 'licitacion_duplicada:<id>'`) | No se tocan: son registro histórico; el alias resuelve el id |
| Nuevas (§3) | `licitaciones_id_anterior.id_externo` | Se rellena en la propia re-key; entra en la lista de la guarda de FK |

Fuera de la base de datos: los binarios del almacén de objetos (ADR-029) se
nombran por hash de contenido (`document_blob_key`), no por id, y no se tocan.
Las cachés (HTTP y Redis) se invalidan al terminar, como hace la purga de PSCP.

### 5. Las superficies

**URLs públicas y SEO.** La ficha pública es
`/licitaciones/<ccaa>/<slug>/<ref>` con `ref = base64url(id_externo)`
(`shared/public_ref.py`), así que **todas** las URLs de fichas PLACSP indexadas
cambian. `GET /publico/licitaciones/{ref}` resuelve el id viejo por
`licitaciones_id_anterior` y devuelve la ficha con su `ref` nuevo; la página
(`web/src/app/(publico)/licitaciones/[ccaa]/[slug]/[ref]/page.tsx`) compara y
responde **308** (`permanentRedirect`) hacia la URL canónica. El `sitemap` y
`alternates.canonical` salen solos de la vista refrescada. La redirección es
**indefinida**: la tabla de alias es pequeña (~24.700 filas) y un enlace en un
correo o en Google no caduca. `LicitacionPublica.expediente` (hoy
`=id_externo` en `api/routes/publico.py`) pasa a ser el expediente natural:
para PLACSP el valor visible **no cambia**.

**API.** Una sola función de `db/` (`resolver_id_licitacion`: el id exacto, y
si no existe, su alias) la usan todas las rutas que reciben un `id_externo`:
la familia `/licitaciones/{id_externo:path}/…` (detalle, documentos, explain,
simulador, tecnologías, eventos, predicción, resumen), `radar/dismissals`,
`watchlist_items`, `admin_revision/duplicados`, y los cuerpos que lo traen
(`pursuits`, `follows`, cartera, feedback del asistente). Una respuesta servida
**vía alias** lleva `Deprecation: true` y `Sunset` (el mecanismo de
`api/errors.py` y `docs/api-design.md`) hasta el **2027-04-30**; después, el id
viejo da 404 en la API (en la web pública sigue el 308). No hay operación
nueva: `make check-api-surface` no cambia.

`LicitacionSummary` (y con ella `LicitacionDetail`,
`api/routes/licitaciones/modelos.py`) gana un campo **opcional** `expediente`
(aditivo, no incompatible según `docs/api-design.md`). La consola deja de mostrar
`id_externo` como número de expediente (`detalle-fila.tsx` hace
`row.id_externo.replace("PLACSP-", "")`) y muestra ese campo. La búsqueda libre
por número de expediente sigue funcionando: compara con `ILIKE` contra
`id_externo` (índice trigram de `v143`) y el expediente sigue siendo una
subcadena del id.

**Webhooks y outbox.** El catálogo (`shared/events.py`) no cambia de forma:
los eventos llevan `id_externo` o `licitacion_id`. Cambian los **valores**: a
partir de la fase 3, un receptor que correlacione con eventos anteriores verá
otro id para el mismo expediente. Se anuncia; para correlacionar, el id viejo
se resuelve por la API hasta el *sunset*. No se añade `id_anterior` a los
payloads (ver «Alternativas»).

**MCP.** `ficha_licitacion` y `buscar_en_pliegos` reciben `id_externo` y
resuelven por la misma función. `mcp_server/glosario.md` dice hoy «PLACSP va
sin prefijo»: se corrige en la fase 3.

### 6. ¿Es un cambio incompatible de la API pública?

**Sí, y se trata como tal**, aunque no rompa nada de la lista mecánica de
`docs/api-design.md` (ninguna ruta, campo ni tipo se quita). Cambia la
**identidad** de un recurso existente: un cliente que guardó `2026/LIC/0049`
deja de tenerlo por clave, y uno que interpretaba el `id_externo` de PLACSP como
número de expediente recibe `placsp:11778670221627:2026/LIC/0049`. Mitigación:
resolución de ids viejos con `Deprecation`/`Sunset` durante seis meses, campo
`expediente` aditivo, y una fila en «Rutas deprecadas hoy» de
`docs/api-design.md` («ids PLACSP sin prefijo, resueltos por alias hasta el
2027-04-30»).

## Las filas ya pisadas

**No se recuperan de la fila actual**: es la última que llegó. **Tampoco se
reconstruyen de `licitaciones_history`**: `snapshot_json` guarda solo las once
columnas de `_HISTORY_SELECT_COLS` (`db/upsert.py`: título, descripción, órgano,
importe, estado, cuatro fechas y duración), sin CPV, URL, `idEvl`, lotes,
adjudicaciones ni órgano de la Plataforma. Una fila hecha de un snapshot no la
publicaría la superficie pública (sin CPV no entra en el universo), y el
siguiente bulk la duplicaría con su clave real. El historial sirve para
**detectar** y para **verificar**; lo que **reconstruye** es la reingesta, que
con la clave nueva trae cada expediente a su propia fila.

**Detección** (la cifra de la tabla de arriba; una función de `db/` la
convierte en el inventario de la fase 4):

```sql
WITH snap AS (
  SELECT h.id_externo, h.source, h.captured_at,
         (h.snapshot_json::jsonb) ->> 'organo_contratacion' AS organo,
         (h.snapshot_json::jsonb) ->> 'titulo' AS titulo
  FROM licitaciones_history h
  JOIN licitaciones l ON l.id_externo = h.id_externo
  WHERE (l.fuente = 'placsp' OR l.fuente LIKE 'bulk_%')
    AND h.snapshot_json LIKE '{%}'
)
SELECT s.id_externo,
       lower(btrim(s.organo)) AS organo_perdido,
       min(s.captured_at) AS primera, max(s.captured_at) AS ultima,
       array_agg(DISTINCT s.source) AS carriles,  -- bulk_YYYYMM dice qué ZIP lo trajo
       max(similarity(lower(s.organo), lower(coalesce(l.organo_contratacion, '')))) AS sim_organo,
       max(similarity(lower(coalesce(s.titulo, '')), lower(coalesce(l.titulo, '')))) AS sim_titulo
FROM snap s
JOIN licitaciones l ON l.id_externo = s.id_externo
WHERE s.organo IS NOT NULL
  AND lower(btrim(s.organo)) <> lower(btrim(coalesce(l.organo_contratacion, '')))
GROUP BY 1, 2;
```

`sim_organo < 0,5 AND sim_titulo < 0,5` es pisada segura; el resto, renombre
probable, va a revisión y **no** se toca solo.

**Reconstrucción** (fase 4): reingerir con la clave nueva los ZIP mensuales de
los 22 meses que ya están en la base (`bulk_202501` a `bulk_202610`; un
expediente pisado en el mes M está en el ZIP de M o de uno anterior), y después:

1. **Limpiar las hijas contaminadas de las filas que sobrevivieron.** Para los
   `id_externo` del inventario, rehacer desde su entrada CODICE (la que la
   reingesta acaba de leer) las hijas de ingesta: `adjudicaciones` (aquí sí se
   reemplaza también con lista vacía), `lotes`, criterios, garantías y
   solvencia; y borrar los `documentos` cuyo URI no esté en esa entrada (se
   llevan su texto extraído en cascada).
2. **Datos de usuario sobre un id afectado** (hoy 1 `pursuit`, 0 `follows`): el
   plan lista quién, cuándo se creó, qué órgano se veía en ese momento (el
   snapshot vigente en `created_at`) y las filas candidatas tras la reingesta.
   Se mueve a mano, nunca solo.
3. **Volver a pasar el dedupe** (`detect_duplicates` por fuente y
   `detect_duplicados_por_referencia`) sobre las filas afectadas y recuperadas,
   y refrescar `licitaciones_canonicas`.
4. **Medir**: cuántos pares (expediente, órgano perdido) del inventario tienen
   ya fila propia (consulta 8 de «Verificación»).

Los snapshots ajenos se quedan donde están, como en v153: son la evidencia de
la detección. Los `contrato_eventos` de `modificacion` generados por una pisada
se listan en el plan; borrarlos es la pregunta abierta 2.

## Plan por fases

Cada fase con escritura tiene un `plan` (solo lectura, por defecto) y un
`--apply`, y las migraciones se aplican como dice
[disaster-recovery.md §5](../runbooks/disaster-recovery.md): `alembic history
-r current:head` antes, copia de seguridad comprobada en Supabase y
`gh workflow run migrate.yml` (manual). Tocar `db/alembic/` y ejecutar en
producción requieren el OK del dueño (AGENTS.md §6). Un runbook
(`docs/runbooks/rekey-placsp-organo.md`, gemelo del de PSCP) lleva el detalle
operativo.

**Fase 0 — Medir (sin escritura).** Un script de solo lectura recorre los 22
ZIP y unas decenas de páginas de los feeds 643 y 1044. Puertas para pasar el
RFC a `review`, con las cifras anotadas aquí:

- G1. `ID_PLATAFORMA` en el ~100 % de las entradas de los ZIP (y cuántas caen a
  NIF o DIR3, por mes).
- G2. Un `idEvl` → un (`ID_PLATAFORMA`, `ContractFolderID`) en todo el rango; y
  con qué frecuencia una misma entrada cambia de `ContractFolderID` entre meses
  (lo que en agregadas ya se vio).
- G3. Cobertura del cruce de la fase 2 simulado: ≥ 99,9 % de las filas
  existentes encuentran su entrada.
- G4. Ningún `ID_OC_PLAT` con `:` y ninguno bajo dos plataformas raíz en el feed
  completo de agregadas.

**Fase 1 — Lo aditivo (migración A, reversible).** La siguiente revisión libre
(hoy `v158`) crea `organo_ref_fuente` y `licitaciones_id_anterior`. En el mismo
PR: el parser extrae el órgano y el upsert lo guarda; `natural_expediente` y su
gemelo entienden los dos formatos; `resolver_id_licitacion`, la 308 de la ficha
pública, el campo `expediente` y su uso en la consola. **Los escritores siguen
escribiendo la clave vieja**: tras desplegar no cambia nada visible, y la
ingesta va rellenando `organo_ref_fuente` en lo que toca.

**Fase 2 — Rellenar `organo_ref_fuente` (datos, reversible).** Un script lee los
ZIP del mes de cada fila (`bulk_YYYYMM` lo dice; para `placsp`, el de
`fecha_actualizacion_fuente`) y cruza **por `idEvl`**, que está en `url` y es
1:1 con la entrada: identifica al ocupante actual de una clave pisada sin
ambigüedad, porque su `url` es la del último que escribió. Respaldo para las 21
filas sin `idEvl`: (`ContractFolderID`, órgano plegado). Solo escribe la columna
nueva. Puerta: **0 filas PLACSP sin `organo_ref_fuente`**; las que no se
resuelvan se deciden una a una (sin datos de usuario: se borran y la fase 4 las
trae; con datos de usuario: a mano).

**Fase 3 — La re-key (migración B, irreversible, en ventana).**

1. Pausar **todos** los escritores PLACSP del plano activo (ADR-012): el
   `scrape-daily` y el `scrape-bulk` de GitHub Actions, el job del worker, el
   reintento de la DLQ y el conector de empresas vigiladas. Vaciar la cola y la
   DLQ de PLACSP.
2. Merge del PR con `clave_placsp` en todos los escritores y la migración B.
3. Migración B, con el patrón de v153: `SET LOCAL statement_timeout = 0`,
   `lock_timeout`, `row_security = off`; mapa temporal
   `viejo → '<prefijo>:' || organo_ref_fuente_codificado || ':' || expediente`
   para las fuentes de §1, donde `expediente` es el id viejo sin su prefijo si lo
   tenía (`placsp_watched_company_awards:<exp>` → `<exp>`; PLACSP no lo tiene);
   **guardas que abortan sin tocar nada** si una clave nueva
   se repite, si ya existe, si queda alguna fila de esas fuentes fuera del mapa,
   si alguna FK a `licitaciones(id_externo)` no está en la lista de §4 o si
   queda trabajo pendiente en la cola con un id del mapa; inserta los alias;
   copia las filas; repunta las referencias (con `trg_lts_derivar_ml`
   desactivado); comprueba que no queda ninguna referencia vieja; borra las
   viejas. Volumen: ~24.700 filas y ~300.000 hijas, un tercio de lo que v153
   movió en 52 s en local.
4. Refrescar `licitaciones_canonicas` e invalidar cachés.
5. Reanudar la ingesta.

**Fase 4 — Reconstruir las pisadas (datos).** La reingesta y los cuatro pasos
de §«Las filas ya pisadas», con `plan` y `--apply`. Mejor fuera de la ventana
del `scrape-daily`.

**Fase 5 — Cierre.** El ADR nuevo, la documentación de abajo, el RFC a
`implemented` con el delta de `make audit-truth-check` antes y después; el
2027-04-30, retirar la resolución por alias en la API (la 308 pública se
queda); el runbook a `docs/archive/runbooks/`.

### Compatibilidad durante la transición

Entre la fase 1 y la 3 conviven filas PLACSP **todas** con la clave vieja, y el
código ya sabe leer las dos formas (expediente natural, resolución de alias,
campo `expediente`): la fase 1 se puede desplegar y dejar semanas sin que nada
cambie. Lo que **no** puede convivir es un escritor con la clave nueva sobre una
base sin re-key: cada expediente que la fuente republique entraría como fila
nueva al lado de la vieja. Por eso el cambio de escritores va en el mismo PR que
la migración B, con la ingesta parada entre el merge y el `migrate.yml` (igual
que PSCP), y la guarda «ya existe» de la migración lo detecta si se escapa algo.

### Rollback

| Fase | Cómo se deshace |
|---|---|
| 1 | `alembic downgrade` de la migración A (borra la columna y la tabla vacía) y revertir el código. Sin pérdida |
| 2 | `UPDATE … SET organo_ref_fuente = NULL` o el `downgrade` de la A. Sin pérdida |
| 3 | La migración B **no tiene `downgrade`** (como v153: la inversa vuelve a juntar en una clave expedientes de órganos distintos, que es la colisión que se arregla). Mientras no haya corrido la fase 4, el mapa inverso está entero en `licitaciones_id_anterior` y un script con el mismo copiar-repuntar-borrar lo deshace, junto con revertir el código. **Después** de la fase 4 ya hay expedientes que solo existen con la clave nueva y la inversa chocaría: queda la copia de seguridad tomada justo antes de la ventana más reingerir desde entonces |
| 4 | Idempotente. Las filas recuperadas son nuevas (`primera_extraccion` posterior a la ventana) y se pueden listar y borrar si hiciera falta; la limpieza de hijas se rehace con la siguiente reingesta |

## Verificación

Antes de la fase 3 (puertas):

```sql
-- 1. Ninguna fila PLACSP sin órgano de la Plataforma (fase 2 completa).
SELECT fuente, count(*) FROM licitaciones
WHERE (fuente IN ('placsp', 'placsp_watched_company_awards') OR fuente LIKE 'bulk_%')
  AND organo_ref_fuente IS NULL
GROUP BY 1;

-- 2. Ninguna clave nueva existe ya (algo escribió con el conector nuevo antes de tiempo).
SELECT count(*) FROM licitaciones l
JOIN licitaciones n
  ON n.id_externo = 'placsp:'
     || replace(replace(l.organo_ref_fuente, '%', '%25'), ':', '%3A')
     || ':' || l.id_externo
WHERE l.fuente = 'placsp' OR l.fuente LIKE 'bulk_%';   -- 0

-- 3. Línea base del dedupe con TED y PSCP, para comparar después.
SELECT d.status, count(*) FROM licitaciones_duplicados d
JOIN licitaciones c ON c.id_externo = d.canonical_id
WHERE c.fuente = 'placsp' OR c.fuente LIKE 'bulk_%'
GROUP BY 1;
```

Después de la fase 3:

```sql
-- 4. Cero filas PLACSP con la clave vieja.
SELECT count(*) FROM licitaciones
WHERE (fuente = 'placsp' OR fuente LIKE 'bulk_%') AND id_externo !~ '^placsp:[^:]+:';

-- 5. Un alias por fila re-escrita, y ninguno huérfano.
SELECT count(*) FROM licitaciones_id_anterior WHERE motivo = 'rekey_placsp_organo';  -- = filas del mapa
SELECT count(*) FROM licitaciones_id_anterior a
LEFT JOIN licitaciones l ON l.id_externo = a.id_externo WHERE l.id_externo IS NULL;  -- 0

-- 6. Ninguna referencia sin FK apunta a una fila que no existe (repetir por tabla de §4).
SELECT 'pursuits' AS t, count(*) FROM pursuits p
  LEFT JOIN licitaciones l ON l.id_externo = p.licitacion_id WHERE l.id_externo IS NULL
UNION ALL SELECT 'follows', count(*) FROM follows f
  LEFT JOIN licitaciones l ON l.id_externo = f.target_id
  WHERE f.target_type = 'licitacion' AND l.id_externo IS NULL
UNION ALL SELECT 'domain_events', count(*) FROM domain_events d
  LEFT JOIN licitaciones l ON l.id_externo = d.aggregate_id
  WHERE d.aggregate_type = 'licitacion' AND l.id_externo IS NULL
UNION ALL SELECT 'user_notifications', count(*) FROM user_notifications u
  LEFT JOIN licitaciones l ON l.id_externo = u.licitacion_id
  WHERE u.licitacion_id IS NOT NULL AND l.id_externo IS NULL;
-- Todas 0, salvo los 1.117 domain_events PSCP heredados de v153 si no se reparan aquí.

-- 7. La superficie pública ya no enlaza claves viejas.
SELECT count(*) FROM licitaciones_canonicas c JOIN licitaciones l USING (id_externo)
WHERE (l.fuente = 'placsp' OR l.fuente LIKE 'bulk_%') AND c.id_externo !~ '^placsp:';  -- 0
```

Y en la web: `curl -sI https://<web>/licitaciones/<ccaa>/<slug>/<ref viejo>`
devuelve `308` con `Location` a la `ref` nueva; `GET
/api/v1/licitaciones/2026%2FLIC%2F0049` responde 200 con `Deprecation: true`.

Después de la fase 4:

```sql
-- 8. Pisadas recuperadas: pares (expediente, órgano perdido) del inventario con fila propia.
WITH perdidos AS (/* la consulta de detección, con sim_organo < 0.5 AND sim_titulo < 0.5,
                     sobre licitaciones_id_anterior para traducir el id */)
SELECT count(*) AS perdidos,
       count(*) FILTER (WHERE EXISTS (
         SELECT 1 FROM licitaciones l
         WHERE l.id_externo ~ '^placsp:[^:]+:'
           AND regexp_replace(l.id_externo, '^placsp:[^:]*:', '') = p.expediente
           AND similarity(lower(l.organo_contratacion), p.organo_perdido) >= 0.5
       )) AS recuperados
FROM perdidos p;

-- 9. Expedientes que ahora conviven (antes se pisaban): debe crecer desde 0.
SELECT count(*) FROM (
  SELECT regexp_replace(id_externo, '^placsp:[^:]*:', '') AS exp
  FROM licitaciones WHERE id_externo ~ '^placsp:[^:]+:'
  GROUP BY 1 HAVING count(*) > 1
) x;

-- 10. El dedupe con TED no se pierde: repetir la 3; `confirmed` igual o mayor.
```

Y `make audit-truth-check` antes de la fase 3 y después de la 4, con el delta
anotado aquí. Los tests que la implementación debe traer: dos licitaciones de
órganos distintos con el mismo expediente conviven (integración, contra el
upsert real); el feed vivo y el bulk escriben la misma fila; los gemelos del
expediente natural coinciden en los casos de §2; un aviso TED con BT-22 sigue
casando con su PLACSP; la ficha pública con `ref` vieja redirige; y la
migración B aborta con cada una de sus guardas (como
`tests/test_v153_rekey_pscp_id_externo_migration.py` hace con v153).

## Alternativas descartadas

- **`placsp:<idEvl>`.** El `idEvl` ya está en `url` para el 99,9 % de las filas,
  así que el mapa saldría en SQL sin leer un solo ZIP, y es estable aunque el
  órgano renumere el expediente. Pero es opaco (base64 con `/`, `+` y `=`),
  saca el expediente de la clave —y con él `natural_expediente`, el dedupe con
  TED por BT-22, el de PSCP y agregadas, la búsqueda por número y lo que ve el
  usuario—, que habría que llevar a una columna nueva en todas las fuentes a la
  vez; y agregadas no lo trae (0 de 7.064). Se usa, en cambio, como **llave del
  cruce** de la fase 2, que es donde aporta sin coste.
- **El `<id>` Atom.** Igual de estable y 1:1, pero tampoco se guarda en la base
  (el mapa exigiría lo mismo que `ID_PLATAFORMA`) y es igual de opaco.
- **DIR3 o NIF como órgano.** DIR3 falta en el 25 % del feed y en el 63 % de
  agregadas; el NIF lo comparten 123 órganos de la muestra. Ninguno es 1:1.
- **El nombre del órgano normalizado.** Los renombres (1 de los 8 casos del
  backlog) partirían un expediente en dos filas.
- **Re-key perezosa** (las filas viejas conservan su id y solo las nuevas llevan
  órgano, con un lookup en la ingesta para reconocer al ocupante). No rompe
  URLs, pero deja dos formatos para siempre, un lookup por entrada en el upsert
  y la decisión «¿es el mismo órgano?» por nombre, que es justo lo que falla. Y
  las pisadas siguen sin recuperar.
- **Clave sustituta entera** (`licitaciones.id` como PK y `id_externo` único por
  `(fuente, órgano, expediente)`). Cambia 17 FK, la API entera y el frontend, y
  la ingesta seguiría necesitando una clave natural única para el
  `ON CONFLICT`: el problema de identidad es el mismo.
- **Prefijo por carril (`bulk_YYYYMM:…`).** El feed vivo y el bulk dejarían de
  escribir la misma fila: cada expediente saldría una vez por carril.
- **`id_anterior` en los payloads de webhook.** Ayudaría a correlacionar, pero
  es un campo de transición en un catálogo que se promete estable, y la
  resolución por API cubre el mismo caso durante el *sunset*.
- **Reconstruir las pisadas de `licitaciones_history`.** Ver §«Las filas ya
  pisadas»: el snapshot no tiene CPV, URL ni hijas.

## Riesgos y preguntas abiertas

1. **Los 1.117 `domain_events` PSCP huérfanos de v153.** ¿Se reparan en la
   migración B (con un mapa PSCP derivable: el `pscp:<codi>` viejo → la fila con
   ese `<codi>` y el UUID de su `url`, solo donde sea único) o en un cambio
   aparte? Propuesta: aparte y antes, para que la B no mezcle dos re-keys.
2. **¿Se borran los `contrato_eventos` de `modificacion` y los snapshots
   ajenos** de las filas afectadas una vez verificada la fase 4? v153 los dejó.
   Propuesta: borrar los eventos (son señal falsa en el producto: «este
   contrato se modificó») y dejar los snapshots (evidencia, invisibles).
3. **Renumeración de `ContractFolderID`.** En agregadas ya se vio (3 de 6.328
   entradas en dos días). Con esta clave, como hoy, un expediente renumerado es
   una fila nueva. No empeora nada; G2 dice cuánto pesa en PLACSP y si merece
   un RFC propio.
4. **Fichas públicas cacheadas** por ISR con la `ref` vieja siguen sirviendo
   hasta su revalidación; la 308 aplica en cuanto se regeneran.
5. **Maestro de órganos.** `organo_ref_fuente` (100 % de cobertura y 1:1 en
   PLACSP) es mejor llave que el DIR3 (75 %) para resolver `organo_id`
   (ADR-032 §C). Queda fuera de este RFC; se anota en el backlog.

## Qué cambia en la documentación

- **ADR nuevo** que revisa el *Rationale* de ADR-009 («las PK de PLACSP sin
  prefijo»), con la regla general: el `id_externo` de una fuente cuyo número de
  expediente no es único entre órganos se acota por el identificador del órgano
  en esa fuente. Antes de mergear la fase 3 (AGENTS.md §5, post-flight 3).
- `docs/database-schema.md` (columna y tabla nuevas, forma de la clave),
  `docs/api-design.md` (fila de deprecación, ejemplos de `id_externo`),
  `mcp_server/glosario.md` («PLACSP va sin prefijo»), los docstrings de
  `scraper/connectors/placsp.py` y `placsp_agregadas.py`, y
  `docs/runbooks/rekey-placsp-organo.md` (nuevo).

## Decisiones de la fase A (2026-10-25)

Lo que la fase 1 del plan dejaba abierto, tal como se implementó:

1. **Dónde vive la clave.** No en `scraper/codice_parser.py` sino en
   `shared/identidad_placsp.py`: `services/dedupe.py` y su gemelo SQL en
   `db/repositories/dedupe.py` tienen que importarla y ninguno puede importar
   de `scraper/` (AGENTS.md §2). El parser importa de `shared/` como el resto.
   Allí están `clave_placsp`, `descomponer_clave_placsp`, `codificar_organo`,
   `expediente_natural` y `expediente_natural_sql(columna)`, que genera el
   SQL del gemelo desde la misma tupla de prefijos. Los dos se fijan con la
   tabla de §2 (`tests/test_identidad_placsp.py`).
2. **Los escritores no cambian de clave todavía**, como dice §«Compatibilidad
   durante la transición». Lo que sí hace el upsert desde ya es **contar la
   colisión en vez de pisar en silencio**: si la fila guardada tiene
   `organo_ref_fuente` y la entrada trae otro, loguea los dos órganos y suma
   `placsp_colision_expediente_total{fuente}`. La escritura sigue (perder la
   nueva en vez de la vieja no es mejor) y la clave no se bifurca (escribir
   `placsp:<órgano>:<exp>` sobre una base sin re-key partiría cada expediente
   republicado). El contador es la medida en vivo de lo que la fase 4 recupera.
3. **`organo_ref_fuente` está en `_LIC_COALESCE_UPDATE_FIELDS`**: un camino que
   no lo conoce no lo borra. La extracción (`identificador_organo`) salió de
   `placsp_menores.py` a `codice_parser.py`, parametrizada por esquemas; menores
   la reexporta.
4. **Resolución de ids anteriores.** `db/repositories/identidad.py::
   resolver_id_licitacion` (exacto primero, alias después). En la API es una
   dependencia (`api/routes/licitaciones/_base.py::resolver_id_externo`) que
   pone `Deprecation`, `Sunset` (2027-04-30) y `Link` cuando resuelve por
   alias, aplicada al detalle, `/documentos`, `/similares` y
   `/competencia-esperada`; el resto de rutas `/licitaciones/{id}/…` la adoptan
   en la fase 3, cuando haya alias que resolver. `expediente_completo` (MCP) y
   `GET /publico/licitaciones/{ref}` resuelven igual; la página pública compara
   la `ref` devuelta con la pedida y responde 308 (`permanentRedirect`).
5. **`expediente`** es campo aditivo de `LicitacionSummary` (y por herencia de
   `LicitacionDetail`), calculado con `expediente_natural`; la consola lo
   muestra en vez de `id_externo`. `LicitacionPublica.expediente` pasa a ser el
   expediente natural (para PLACSP, hoy, el mismo valor).
6. **El inventario de pisadas** es `inventario_pisadas_placsp` (la consulta de
   §«Las filas ya pisadas») con `scripts/inventario_pisadas_placsp.py`, que
   además imprime la puerta 1 de la fase B (filas PLACSP sin
   `organo_ref_fuente`) y los expedientes con clave nueva que ya conviven
   (consulta 9). Solo lectura.
7. **Lista de referencias de la fase B.** Es la tabla de §4 **con**
   `domain_events.aggregate_id` (los huérfanos de PSCP ya los reparó `v158`) y
   `licitaciones_id_anterior.id_externo`, que la migración de re-key tiene que
   rellenar y repuntar. No se re-escribe ninguna fila existente en esta fase:
   la migración B queda para su propio PR, con `plan` y paso manual
   (`migrate.yml`), como describe §«Plan por fases».
8. **Qué no entra.** El ADR que revisa ADR-009, el runbook
   `rekey-placsp-organo.md`, la corrección de `mcp_server/glosario.md` y la fila
   de deprecación por ids viejos pasan a tener fecha: con la fase B. La fila de
   `docs/api-design.md` se añadió ya porque el mecanismo existe.

## Decisiones de la fase B (2026-10-26)

Lo que el código de las fases 2 y 3 decidió donde este texto dejaba margen
(rama `agente/identidad-fase-b`; ventana y pasos de producción en
[rekey-placsp-organo.md](../runbooks/rekey-placsp-organo.md), decisión en
[ADR-038](../adr/ADR-038-clave-de-placsp-acotada-por-organo.md)):

1. **Una puerta para todos los escritores**:
   `scraper.codice_parser.acotar_por_organo` (y `clave_de_entry`, sin
   `Licitacion`, para `reproceso_lotes`). La usan el núcleo del conector (feed
   vivo, ZIP y agregadas, con `prefijo`/`esquemas` propios), empresas
   vigiladas, `process_daily`, `seed_negatives` (que además inserta
   `organo_ref_fuente`) y `reproceso_lotes`. Contratos menores no cambia: su
   prefijo no es de la familia y ya nació acotado.
2. **El carril bulk de empresas vigiladas** escribía
   `placsp_watched_company_awards_bulk_YYYYMM:<exp>`, una fila distinta de la
   del carril vivo. Pasa a la clave de la familia (la misma fila), con
   `fuente` del carril; no había ninguna en producción.
3. **El relleno** es `scripts/rellenar_organo_ref_placsp.py` (lógica en
   `scraper/relleno_organo_placsp.py`): los meses salen de las filas
   pendientes, no solo de los 22 ZIP (hay filas `placsp` actualizadas desde
   2017), y añade un tercer respaldo opt-in, por nombre del órgano con
   unanimidad, para lo que no esté en ningún ZIP leído.
4. **La migración B es `v164_identidad_placsp_rekey`**: mapa por `fuente`,
   guardas de §«Plan por fases» más «forma vieja» (fila de la familia sin su
   prefijo), 31 referencias (las 27 de `v153`, `domain_events.aggregate_id`,
   `licitaciones_id_anterior.id_externo`, `ml_feedback.expediente` y
   `organization_references.expediente_id`), payload de los eventos no
   despachados y alias con `motivo = 'rekey_placsp_organo'`. El refresco de
   `licitaciones_canonicas` y la invalidación de cachés quedan fuera, en el
   runbook: un `REFRESH` no concurrente dentro de la transacción bloquearía la
   lectura pública.
5. **`resolver_id_externo` en todas las rutas** con el id en la ruta y
   `api.identidad.id_vigente` en los cuerpos (lista en la fila de
   `docs/api-design.md`). Las rutas que devuelven su propia `Response` (el PDF
   del guion, los streams de `/ask` y `/resumen`) resuelven el id pero no
   pueden llevar `Deprecation`: FastAPI no copia a ellas las cabeceras del
   parámetro.
