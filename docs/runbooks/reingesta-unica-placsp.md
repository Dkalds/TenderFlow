# Runbook: una sola reingesta de PLACSP, cuatro arreglos

**Propósito**: que la reingesta de los 22 ZIP mensuales de PLACSP
(`bulk_202501` a `bulk_202610`) que exige la fase B de identidad
([RFC](../rfc/2026-10-24-rfc-identidad-placsp-organo-expediente.md), fase 4)
deje corregidos en la misma pasada los defectos del dato histórico que solo una
reingesta arregla. Es el ítem V2 del
[plan 2026-10](../plans/2026-10-plan-foco-piloto.md).

**Estado**: preparado el 2026-10-26, **sin ejecutar**. Depende de la fase B, que
aún no está escrita (ver «Dependencias»). Ejecutarlo escribe en producción: lo
lanza el propietario (AGENTS.md §6).

---

## Qué corrige y cuánto hay hoy

Cifras de producción del 2026-10-26 (MCP de solo lectura), sobre filas del feed
principal (`fuente = 'placsp'` o `bulk_%`, 24.562 filas):

| Defecto | Origen del arreglo | Antes | Puerta después |
|---|---|---|---|
| Base del importe desconocida | [ADR-032](../adr/ADR-032-semantica-del-importe-y-maestro-de-organos.md): el parser declara `importe_tipo` y guarda `importe_base_sin_iva` / `importe_con_iva` | 17.839 filas con `importe_tipo` desconocido o nulo (72,6 %) | **< 10 %** |
| Umbral de la solvencia económica | P2 «condiciones oficiales de CODICE»: el umbral va en `cbc:ThresholdQuantity` (arreglado el 2026-10-24) | 5 de 4.046 requisitos económicos con `umbral_importe` | no nulo donde la fuente lo publica; se compara con `scripts/medir_terminos_codice.py` (≈ 64 % de los avisos del ZIP traen solvencia económica) |
| `provincia = 'España'` | parser del 2026-10-25: NUTS de país → NULL | 765 | 0 |
| Importes a 0 en hijas | parser del 2026-10-25: 0 → NULL en adjudicado, pagable, ofertas mínima y máxima, y en porcentaje e importe de garantía | 1.408 de 19.288 adjudicaciones; 161 de 3.075 garantías | 0 |
| `fecha_publicacion` con hora | parser del 2026-10-25 (sin `ValidNoticeInfo`, el día del `<updated>`) **y** la regla de fusión del upsert arreglada en esta rama | 401 | 0 |
| Expedientes pisados entre órganos | fase B del RFC (clave `placsp:<órgano>:<expediente>`) | 379 ids / 570 pares de pisada segura (2026-10-24) | las del RFC: consultas 8 y 9 |

`placsp_watched_company_awards` tiene además 314 adjudicaciones con un 0 de 598:
las escribe otro conector y **esta reingesta no las toca** (ver «Lo que no
arregla»).

---

## Qué pisa una reingesta normal (comprobado en el código)

La reingesta pasa por el mismo camino que la ingesta diaria:
`PlacspBulkConnector` → `run_connector` → `upsert_licitaciones_with_history`,
`replace_lotes_batch`, `replace_adjudicaciones_batch` y `_replace_condiciones`
(`db/upsert.py`, `scraper/connectors/base.py`). Para cada campo:

| Campo | Regla del upsert | ¿La reingesta lo corrige? |
|---|---|---|
| `importe_tipo`, `importe_base_sin_iva`, `importe_con_iva`, `valor_estimado` | `col = excluded.col` (no están en `_LIC_COALESCE_UPDATE_FIELDS`) | **Sí**. La versión que se escribe la última manda, también si trae NULL |
| `provincia` | `col = excluded.col` | **Sí**: el NULL nuevo pisa «España» |
| `fecha_publicacion` | `_earliest_iso_date(guardada, nueva)` | **Sí, desde esta rama.** Antes comparaba el texto tal cual y el timestamp solo cedía ante una fecha del mismo día; con una versión de un día posterior se quedaba para siempre. Ahora compara y guarda el día |
| Solvencia, garantías, criterios (`licitacion_*`, v148) | por familia, `DELETE` + `INSERT` cuando la versión trae al menos una fila de esa familia; vacía no toca nada | **Sí** en los expedientes cuya última versión con el bloque lo trae. La fase ADJ/RES sigue publicándolo (79–82 % en el ZIP, medido el 2026-10-24) |
| `adjudicaciones` | `DELETE` + `INSERT` por licitación cuando la versión trae adjudicaciones; si no trae, no se tocan | **Sí** en los adjudicados. Una licitación cuya versión conservada no trae adjudicaciones conserva las suyas, con su 0 |
| `organo_ref_fuente`, `fecha_limite`, `procedimiento`… | `COALESCE(excluded.col, licitaciones.col)` | No aplica: ninguno de los cinco arreglos vive en un campo con COALESCE |

`upsert_licitaciones_with_history` escribe **todas** las filas del lote, hayan
cambiado o no: el «sin cambios» solo decide si se guarda un snapshot de
historial. No hay atajo que salte una fila igual.

Lo prueban `tests/test_verificacion_reingesta.py` (integración: estado antiguo,
reingesta por el camino real, las cuatro cifras a cero) y
`tests/test_unit_upsert_fecha_publicacion.py` / `tests/test_db_upsert.py`
(la regla de la fecha).

**No hace falta ninguna migración** para estos arreglos. La única que hay en el
camino es la de la fase B (re-key), que es del RFC.

---

## El orden de los meses importa: `--backfill`, no `scrape-bulk.yml`

El ZIP mensual no trae `<updated>` por aviso, así que entre dos apariciones del
mismo expediente en meses distintos **gana el último mes procesado**
(`scheduler/pipeline_runs.py::meses_a_procesar`):

- `python -m scheduler.run_update --backfill 2025 1` recorre de enero de 2025 a
  hoy en orden **ascendente**: el último mes escrito es el más reciente, que es
  la versión buena.
- `scrape-bulk.yml` (`--months N`) recorre del más nuevo al más antiguo: con
  `months=22` el último mes escrito sería enero de 2025 y cada expediente
  quedaría con su versión **más vieja** (estado, importe, plazo y condiciones
  regresados). Además no cabe: más de 2 h por mes medidas, contra un
  `timeout-minutes: 240`.

**La reingesta se lanza con `--backfill`.** El workflow no expone ese modo; las
dos opciones están en «Pasos», paso 3.

---

## Dependencias

1. **Fase A del RFC** — hecha (v163, #559): `organo_ref_fuente`,
   `licitaciones_id_anterior`, el inventario de pisadas.
2. **Fase 2 del RFC** (rellenar `organo_ref_fuente` del histórico por `idEvl`) —
   **sin escribir**. Puerta: 0 filas PLACSP sin órgano.
3. **Fase 3 del RFC** (migración B de re-key y `clave_placsp` en todos los
   escritores, en ventana) — **sin escribir**; la migración necesita el OK del
   propietario. La reingesta va **después**: hecha antes con la clave vieja,
   la fase B obligaría a una segunda reingesta, que es lo que este runbook
   evita.
4. **Código desplegado en la API y en el runner que ejecute la reingesta**: el
   parser del 2026-10-25 (`_importe_informado`, `es_nuts_de_pais`, la fecha del
   `<updated>`), el umbral de solvencia del 2026-10-24, ADR-032 en el parser y
   la regla de fecha de esta rama. Comprobar que el commit desplegado los
   contiene antes de empezar.
5. **Esquema**: v148 (condiciones), v156 (importes `double precision`) y v163
   aplicadas. `GET /health/ready` → `schema: ok`.

---

## Pasos

### 0. Línea base (solo lectura, cualquier día antes)

```bash
python scripts/verificar_reingesta.py --json > reingesta-antes.json
python scripts/inventario_pisadas_placsp.py --csv pisadas-antes.csv
make audit-truth-check
```

Anotar las cifras con fecha en el ítem V2 del plan.

### 1. Puertas de entrada

- [ ] Fase 3 del RFC cerrada: consultas 4 a 7 de su §«Verificación» a cero.
- [ ] Ingesta reanudada tras la re-key y un `scrape-daily` en verde con la clave
      nueva.
- [ ] Copia de seguridad de Supabase comprobada del mismo día
      ([disaster-recovery.md](disaster-recovery.md)).
- [ ] Espacio en disco para los 22 ZIP en `DATA_DIR/downloads` y, si se lanza
      desde una máquina que ya los tenía, **borrados** los de los dos últimos
      meses: `download_month` usa la caché sin mirar si el ZIP del mes en curso
      se ha vuelto a publicar.

### 2. Pausar el carril diario

Deshabilitar `scrape-daily.yml` (Actions → *Disable workflow*) mientras dure la
reingesta. Con la ingesta en marcha, un mes reingerido puede escribir sobre un
expediente una versión más vieja que la que acaba de traer el ATOM, y el ATOM
no la vuelve a leer porque su cursor ya pasó. Con el diario parado, el cursor
se queda en el momento de la pausa y al reanudar aplica todo lo posterior, que
es más reciente que cualquier ZIP.

### 3. Lanzar la reingesta

Ascendente desde enero de 2025, por una de estas dos vías:

- **(a) Desde una máquina con acceso de escritura a producción** (el mismo
  perfil que el job de `scrape-bulk.yml`: `ENV=prod`, `DATABASE_URL`,
  `SCHEDULER_PLANE` del plano activo):

  ```bash
  python -m scheduler.run_update --backfill 2025 1 --log-format json 2>&1 | tee reingesta.log
  ```

  Duración esperada: del orden de dos días (más de 2 h por mes). Si se corta,
  se relanza con `--backfill <año> <mes>` del mes que estaba en curso: el orden
  sigue siendo ascendente y repetir meses es idempotente.

- **(b) Desde Actions**, un tramo por job, en orden: `scrape-bulk.yml` con
  `backfill_desde` (y `backfill_hasta`, por defecto el mismo mes) llama a
  `run_update --backfill <año> <mes> --hasta <año> <mes>`. Un mes pasa de 2 h,
  así que un job de 240 min cubre un mes; se lanza el siguiente cuando termina
  el anterior (`concurrency: scrape` ya impide que se solapen):

  ```bash
  gh workflow run scrape-bulk.yml -f backfill_desde=2025-01
  # … al terminar:
  gh workflow run scrape-bulk.yml -f backfill_desde=2025-02
  ```

  Cada job corre además los pasos post-ingesta; es más lento en total que (a),
  pero no necesita una máquina con acceso a producción.

Los pasos post-ingesta (resolución de empresas, dedupe, `dlq_retry`…) corren
una vez al final.

### 4. Seguimiento

- El log de `run_connector` de cada mes (`source=bulk_YYYYMM`) y la salud de
  esa fuente en el healthcheck.
- La DLQ con `bulk_YYYYMM` ([dlq-replay.md](dlq-replay.md)): un mes en error
  deja `status: degraded` y se repite con su `--backfill`.
- `placsp_colision_expediente_total` debe quedarse en 0: con la clave nueva no
  hay pisadas. Un `placsp_clave_acotada_con_otro_organo` en el log es un bug de
  la fase B: se detiene la reingesta y se investiga.

### 5. Cerrar la fase 4 del RFC

Los cuatro pasos de su §«Las filas ya pisadas»: limpiar las hijas contaminadas
de las filas del inventario, mover a mano los datos de usuario afectados,
volver a pasar el dedupe y refrescar `licitaciones_canonicas`, medir con la
consulta 8.

### 6. Reanudar el diario

Rehabilitar `scrape-daily.yml` y esperar un tick en verde.

### 7. Verificar

```bash
# Solo lo que la reingesta reescribió (fecha de inicio de la ventana):
python scripts/verificar_reingesta.py --desde 2026-MM-DD --estricto
# Todo PLACSP, para anotar:
python scripts/verificar_reingesta.py --json > reingesta-despues.json
python scripts/inventario_pisadas_placsp.py --csv pisadas-despues.csv
make audit-truth-check
```

`--estricto` sale con 1 si falla una puerta decisoria. Sin `--desde`, las filas
que la reingesta no alcanzó (ver abajo) cuentan también: si la puerta del
importe falla solo ahí, la diferencia entre las dos ejecuciones dice cuántas
son y no es un fallo de la reingesta.

Anotar en el ítem V2 del plan, con fecha: las cifras de antes y después, la
duración y las consultas 8 a 10 del RFC.

---

## Lo que no arregla

- **Filas que el filtro actual no admite.** El conector solo persiste avisos
  que pasan el filtro TI (keyword o rescate ML). Una fila ingerida con un filtro
  anterior que hoy no pasa no se reescribe y conserva sus defectos. `--desde`
  las separa.
- **Expedientes que no aparecen en ningún ZIP de 2025-01 en adelante**: filas
  `placsp` del ATOM sin actualizar desde antes.
- **`placsp_watched_company_awards`**: otro conector con sus propias filas; sus
  ceros los corrige ese conector al volver a leer cada mes.
- **NUTS de nivel 1 y 2**: siguen dando una región o una CCAA como
  `provincia` (caso golden 17); es otro arreglo del parser.
- **Lotes que repiten el presupuesto del expediente** (caso golden 20):
  decisión de modelado abierta.
- **TED, PSCP y el resto de fuentes**: no pasan por este parser.

## Rollback

La reingesta es idempotente y solo reescribe filas con lo que publica la
fuente: no hay estado intermedio que deshacer. Si el resultado fuera peor que
el de partida, la vía es la copia de seguridad del paso 1 más reingerir desde
entonces; la fase B tiene su propio rollback en el RFC.
