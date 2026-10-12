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
2. **Validar la URL sin escribir nada.** Ninguna de las dos URL se pudo
   descargar desde la sesión que las escribió, y las fixtures de los tests son
   sintéticas:

   ```bash
   python -m scraper.connectors.placsp_agregadas --check --dump agregadas.atom
   python -m scraper.connectors.placsp_menores --check --dump menores.atom
   ```

   Tiene que contar entradas y alguna admitida por el filtro de tecnología. Con
   0 entradas, mirá el volcado: o la URL no es la del feed, o su contenido no es
   CODICE como el del feed principal, que es lo que asume el parser. Sustituí la
   fixture de `tests/fixtures/placsp_sindicaciones/` por un recorte del volcado y
   corré `pytest tests/test_connectors_placsp_sindicaciones.py`.
3. **Fijar la variable** con la URL validada.
4. **Comprobar tras la primera pasada:** el resumen de conectores del run
   (`placsp_agregadas` / `placsp_menores` en `success`), el log
   `connector_run_done` con sus contadores por motivo
   (`placsp_agregadas_fuera_de_universo`,
   `placsp_menores_estado_cerrado_por_defecto`…) y la fila de
   `source_ingestion_health` con `status = 'success'`.

La primera pasada, sin cursor, lee solo la primera página (500 entradas), como
el feed principal. El histórico vendría de los ZIP mensuales de cada sindicación
(`..._AAAAMM.zip`), que no tienen conector todavía.

**Qué cambia en el producto al encender contratos menores.** Nada en el Radar,
el listado, la superficie pública, los KPIs ni el clasificador: se guardan
cerrados, sin plazo, con universo propio y sin etiqueta `tecnologia`. Sí
aparecen sus adjudicaciones, enlazadas al maestro de empresas, en las consultas
de competidores que no filtran por universo ni por tecnología
(`AdjudicacionRepository.load_for_competitors` sin filtro de tecnología, las de
UTE). **Al encender agregadas**, sus convocatorias abiertas entran en el Radar
como cualquier otra de PLACSP, y las que ya entraban por otra fuente quedan
marcadas como duplicadas.

## TACRC: el índice completo

El índice del Pleno trae ~17 resoluciones. El completo vive en la biblioteca de
SharePoint `/tacrc/resoluciones/año AAAA/`, y el conector lo lee año a año con
una URL que lleve `{anio}`. La candidata es `URL_BIBLIOTECA_RESOLUCIONES`
(`scraper/connectors/tacrc.py`), **sin verificar**: no se sabe si el servidor
sirve su API REST a un visitante anónimo.

1. **Validar** (pide solo el año en curso):

   ```bash
   python -m scraper.connectors.tacrc --check \
     --url "https://www.hacienda.gob.es/tacrc/_api/web/GetFolderByServerRelativeUrl('/tacrc/resoluciones/año {anio}')/Files?\$select=Name,ServerRelativeUrl,TimeLastModified"
   ```

   Un 401/403 significa que la API no es anónima. La alternativa es la que ya
   proponía el conector: abrir `BuscadordeResoluciones.aspx` con las DevTools,
   localizar en *Network* la petición que devuelve el listado y pasarla con
   `--url` (con `{anio}` donde vaya el año, si lo lleva).
2. **Cargar el histórico una vez** desde una máquina con `DATABASE_URL`: el
   cursor que dejó el índice del Pleno puede ir por delante, y una pasada normal
   empieza en su año.

   ```bash
   python -m scraper.connectors.tacrc --url "<plantilla>" --desde-anio 2010
   ```

   Va por años ascendentes y avanza el cursor tras cada uno: si se corta,
   relanzarlo sin `--desde-anio` sigue desde el último año escrito.
3. **Fijar** `TACRC_INDEX_URL` con la plantilla.

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
