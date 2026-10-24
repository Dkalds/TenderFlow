# Fuentes opcionales: cómo se encienden y cómo se comprueban

Las fuentes con `estado="opcional"` en `REGISTERED_SOURCES`
(`scraper/connectors/__init__.py`) pueden estar apagadas a propósito. Cada una
tiene una variable: sin ella, el conector escribe `disabled` en
`source_ingestion_health`, termina en 0 y el healthcheck la cuenta como
`apagada`, sin alertar. Corren en cada pasada de `scrape-daily.yml` (y en el
job `daily_atom` del worker) aunque estén apagadas, precisamente para dejar esa
fila: sin ella constarían como «sin registro».

| Fuente | Variable | Para encenderla | Por defecto |
|---|---|---|---|
| `pscp` | `PSCP_DATASET_ID` | id del dataset Socrata (`scripts/probe_pscp.py`) | lo decide la variable de repo |
| `tacrc` | `TACRC_INDEX_URL` | índice del Pleno, o el índice completo por años (abajo) | lo decide la variable de repo (ver la nota) |
| `placsp_agregadas` | `PLACSP_AGREGADAS_ATOM_URL` | `URL_SINDICACION_1044` de `scraper/connectors/placsp_agregadas.py` | **apagada** (vacía en `config/settings.py`) |
| `placsp_menores` | `PLACSP_MENORES_ATOM_URL` | `URL_SINDICACION_1143` de `scraper/connectors/placsp_menores.py` | **apagada** (vacía en `config/settings.py`) |

Dónde se fija cada variable: en GitHub, *Settings → Secrets and variables →
Actions → Variables* (el workflow las lee con `vars.`). Si el cron ya vive en el
worker ([cutover-cron-al-worker.md](cutover-cron-al-worker.md)), además como
variable de entorno del servicio worker en Render. Apagar es vaciarla.

Ojo con TACRC: en Actions, la variable de repo sin definir llega vacía y apaga
la fuente; en el worker, sin variable manda el valor por defecto de
`config/settings.py` (el índice del Pleno), así que allí corre. Por eso el
valor por defecto no se cambió al añadir el índice completo.

## Sindicaciones de PLACSP: agregadas (1044) y contratos menores (1143)

Escritas el 2026-10-12 y apagadas por decisión del dueño, que revisa D16 antes
de encenderlas. Qué hace cada una está en el docstring de su módulo; lo
operativo:

1. **Decidir.** Las dos tocan exclusiones publicadas en `/cobertura`
   (`FUERA_DE_ALCANCE`: «Contratos menores» y «Portales autonómicos no
   integrados»). Al encender, actualizá esa entrada y el `alcance` de la fuente
   en `REGISTERED_SOURCES`, que hoy dice «escrito y apagado». Para agregadas,
   medí antes el solape con `make medir-solape`
   ([regional-source-coverage.md](../regional-source-coverage.md)).
2. **Validar la URL sin escribir nada.** Las dos URL se verificaron el
   2026-10-24 (`GET` 200 `application/atom+xml`; un `HEAD` cierra la conexión, no
   lo uses) y las fixtures de los tests son ya recortes reales
   (`tests/fixtures/placsp_sindicaciones/README.md`). Antes de encender, repetilo
   desde la máquina que correrá el conector:

   ```bash
   python -m scraper.connectors.placsp_agregadas --check --dump agregadas.atom
   python -m scraper.connectors.placsp_menores --check --dump menores.atom
   ```

   Resultado del 2026-10-24: menores, 498 entradas en la primera página y 13
   admitidas por el filtro; agregadas, 283 y 25. Tiene que contar entradas y
   alguna admitida. Con 0 entradas, mirá el volcado: o la URL no es la del feed, o
   su contenido no es CODICE como el del feed principal, que es lo que asume el
   parser. (`--check` imprime un traceback de `tecnologias_keywords_lectura_fallida`
   si no hay `DATABASE_URL`: es un aviso, el filtro cae al diccionario estático.)
3. **Fijar la variable** con la URL validada.
4. **Comprobar tras la primera pasada:** el resumen de conectores del run
   (`placsp_agregadas` / `placsp_menores` en `success`), el log
   `connector_run_done` con sus contadores por motivo
   (`placsp_agregadas_fuera_de_universo`,
   `placsp_menores_estado_cerrado_por_defecto`…) y la fila de
   `source_ingestion_health` con `status = 'success'`.

La primera pasada, sin cursor, lee solo la primera página (500 entradas), como
el feed principal. El histórico vendría de los ZIP mensuales de cada sindicación
(`..._AAAAMM.zip`), que no tienen conector todavía. Volumen medido (20 páginas de
cada feed, 2026-10-24): menores publican ~2.500 entradas al día (~5 páginas) y
admite el filtro un 2,4 %; agregadas ~2.300 al día y admite un 7,8 %.

**Identidad de los menores (decidida el 2026-10-24).** El `id_externo` es
`placsp_menores:<ID_PLATAFORMA>:<ContractFolderID>`, no `...:<ContractFolderID>`:
en 9.977 entradas, 327 de los 9.563 expedientes distintos los repetían órganos
distintos y 390 filas se habrían pisado en el `ON CONFLICT(id_externo)`. Nunca se
encendió, así que no hay filas con la clave vieja que migrar (comprobado:
`PLACSP_MENORES_ATOM_URL` vacía por defecto y ningún registro en el código que la
fije). Detalle y números en el docstring de `placsp_menores.py`. **Las agregadas
y el feed principal (`placsp`, sin prefijo) tienen el mismo defecto** y no se han
cambiado aquí: ver el backlog.

**Qué cambia en el producto al encender contratos menores.** Nada en el Radar,
el listado, la superficie pública, los KPIs ni el clasificador: se guardan
cerrados, sin plazo, con universo propio y sin etiqueta `tecnologia`. Sí
aparecen sus adjudicaciones, enlazadas al maestro de empresas, en las consultas
de competidores que no filtran por universo ni por tecnología
(`AdjudicacionRepository.load_for_competitors` sin filtro de tecnología, las de
UTE). **Al encender agregadas**, sus convocatorias abiertas entran en el Radar
como cualquier otra de PLACSP, y las que ya entraban por otra fuente quedan
marcadas como duplicadas.

**Pliegos de las agregadas.** Ninguna referencia de documento del feed real
apunta a PLACSP: de 1.057, 544 son de `contractaciopublica.cat` (en la allowlist
por PSCP, se guardan), 346 de `www.contratacion.euskadi.eus` y 167 de
`contratos-publicos.comunidad.madrid` (fuera de ella: se descartan y se cuentan en
`placsp_agregadas_documentos_de_otro_host`). Ampliar `DOCUMENT_ALLOWED_HOSTS` a
esos dos hosts es una decisión de seguridad (superficie SSRF) del propietario.

**Datos personales en menores.** El adjudicatario de un menor es a menudo una
persona física: de 241 admitidas, 14 con NIF enmascarado (`***3418**`; esas
adjudicaciones no se guardan) y 12 con NIF y nombre completos. Antes de encender,
el propietario decide si se guardan; ver el backlog y
[registro-tratamientos.md](../legal/registro-tratamientos.md).

## TACRC: el índice completo

El índice del Pleno trae 19 resoluciones doctrinales (2026-10-24; la más reciente
de junio de 2026). El tribunal dicta ~1.900 al año y su índice completo **no es
accesible de forma anónima**. Comprobado el 2026-10-24:

- La candidata `URL_BIBLIOTECA_RESOLUCIONES` (API REST de SharePoint,
  `/tacrc/_api/web/GetFolderByServerRelativeUrl(...)/Files`) está **refutada**:
  esa y cualquier otra ruta `/_api/` del sitio responden `302` a
  `/es-es/Paginas/pagenotfound.aspx` (no 401/403: `requests` la sigue y llega un
  200 con HTML; `fetch_index` ahora lo trata como error). La vista de lista
  (`/tacrc/resoluciones/` → `/TACRC/Forms/Todos.aspx`) también.
- Los PDF sí se sirven por su ruta exacta (200), pero nada los enumera.
- El buscador (`BuscadordeResoluciones.aspx`) hace `POST` a
  `serviciostelematicos.hacienda.gob.es/MINHAC_SP_PUBLIC_SERVICES/api/MinhacSearchController/GetResultsForFilter`
  con un token de Cloudflare Turnstile (según su `TACRCSearcher.js`). No se llamó:
  no se esquiva una verificación anti-bot.

Qué queda: dejar `TACRC_INDEX_URL` como está (el índice del Pleno, validado con
`python -m scraper.connectors.tacrc --check`: 19 resoluciones) y pedir a Hacienda
un listado abierto —un feed, un CSV o un acceso a la API—. La maquinaria para un
índice por años (`{anio}`, `--desde-anio`, listado JSON de SharePoint) sigue en el
conector para ese día; con un listado así, el procedimiento sería: validar con
`--check --url "<plantilla>"`, cargar el histórico una vez con `--desde-anio 2010`
desde una máquina con `DATABASE_URL`, y fijar `TACRC_INDEX_URL` con la plantilla.

## El respaldo del feed principal: ZIP mensual cuando el ATOM no avanza

No es una fuente opcional, pero vive en el mismo carril. Si el cursor `placsp`
no avanza durante `PLACSP_ATOM_PASADAS_SIN_AVANCE_ZIP` pasadas seguidas (6 por
defecto, un día; `0` lo apaga), el carril diario ingiere el ZIP del mes en
curso —y el del anterior si el hueco empezó en él— con el mismo conector que
`scrape-bulk.yml` (`scheduler/respaldo_zip_placsp.py`). El healthcheck sigue
avisando `fuente_sin_datos_nuevos:placsp`: el ATOM sigue roto y eso hay que
verlo; el respaldo solo acota el dato que se pierde.

Dónde mirarlo:

```sql
-- Pasadas seguidas sin avance y último respaldo del episodio
SELECT last_seen_updated AS cursor_atom_parado, last_entry_id AS pasadas,
       last_modified AS ultimo_respaldo, updated_at
FROM ingestion_cursors WHERE source = 'placsp_atom_respaldo_zip';

-- Cada respaldo
SELECT ts, value AS meses, detail FROM ops_events
WHERE event_type = 'placsp_atom_respaldo_zip' ORDER BY ts DESC LIMIT 10;
```

En los logs del step «Run daily scraper»: `placsp_atom_sin_avance` en cada
pasada parada y `placsp_atom_respaldo_zip` cuando cae al ZIP. Las filas que
trae llevan `fuente = bulk_AAAAMM` y su salud va en la fila de ese mes, como
las de `scrape-bulk.yml`.
