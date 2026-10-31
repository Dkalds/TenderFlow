# Runbook: re-key de las licitaciones PLACSP a `placsp:<órgano>:<expediente>`

**Propósito**: llevar las filas PLACSP ya escritas a la clave acotada por el
órgano sin perder sus hijas ni los datos de usuario, en una ventana con la
ingesta parada, y dejar los ids viejos resolviendo (API con `Deprecation` hasta
el 2027-04-30, ficha pública con 308 sin fecha de fin).

**Estado**: pendiente de ejecutar (2026-10-26). Decisión:
[ADR-038](../adr/ADR-038-clave-de-placsp-acotada-por-organo.md); diseño y
cifras: [RFC de identidad PLACSP](../rfc/2026-10-24-rfc-identidad-placsp-organo-expediente.md)
(fases 2 a 4). Piezas: `v163_identidad_placsp_fase_a` (columna
`organo_ref_fuente` y tabla `licitaciones_id_anterior`),
`scripts/rellenar_organo_ref_placsp.py` (relleno, fase 2),
`v164_identidad_placsp_rekey` (la re-key, fase 3) y
`scripts/inventario_pisadas_placsp.py` (puertas y medida). Gemelo de
[rekey-pscp-id-externo.md](rekey-pscp-id-externo.md).

> **No dejar correr los escritores nuevos contra filas sin re-key.** El PR de
> la fase B cambia a la vez la migración y **todos** los escritores de la
> familia (conector PLACSP en sus dos carriles, empresas vigiladas, agregadas,
> el carril legacy `process_daily` que usa el reintento de la DLQ,
> `seed_negatives` y `reproceso_lotes`). Un expediente que la fuente republique
> entre el merge y la migración entraría como fila **nueva** junto a la vieja,
> y `v164` aborta al encontrarla. Por eso la ingesta se para **antes** del
> merge y no se reanuda hasta después de migrar.

La reingesta posterior (recuperar las licitaciones pisadas, limpiar sus hijas
contaminadas y, en la misma pasada, los importes y las condiciones CODICE) **no
está aquí**: es [reingesta-unica-placsp.md](reingesta-unica-placsp.md). Este runbook termina
cuando la base tiene la clave nueva y la ingesta vuelve a correr.

---

## Qué cambia (medido en producción el 2026-10-26, MCP de solo lectura)

- **24.763 filas** de la familia: 7.083 `placsp`, 17.479 `bulk_*` y 201
  `placsp_watched_company_awards` (0 `placsp_agregadas`, 0 bulk de empresas
  vigiladas). El mapa de `v164`, simulado con un órgano fijo, da 24.763 claves
  distintas, ninguna existente y ninguna fila con forma rara.
- Hijas y datos de usuario que se repuntan: `licitacion_tecnologia_score`
  153.634, `domain_events` de licitación 13.474, `ml_feedback` 39, `pursuits`
  7, `user_notifications` 14, `follows` 2, `watchlist_items` 2 (más
  `documentos`, `adjudicaciones`, historial, lotes…; ~300 k en total según el
  RFC). Un tercio de lo que `v153` movió en 52 s en local.
- 74 eventos del outbox sin despachar (ninguno lleva el id en el payload hoy) y
  **8 fallos abiertos en la DLQ de PLACSP**: vaciarla es el paso 4.
- **`v163` no está aplicada en producción** (la columna `organo_ref_fuente` no
  existe todavía): es el primer paso.

## Antes de la ventana (días antes; la ingesta sigue)

1. **Aplicar `v163`** desde `master` (ya lleva la fase A):
   `alembic history -r current:head` en local para ver qué entra, copia de
   seguridad comprobada en Supabase y `gh workflow run migrate.yml`
   ([disaster-recovery.md](disaster-recovery.md) §5). Es aditiva: columna
   nullable y tabla vacía. Después, regenerar los grants del rol del MCP
   ([mcp-interno.md](mcp-interno.md)): `licitaciones_id_anterior` ya está en
   `mcp_server/catalogo.py` (`gh workflow run migrate.yml -f mode=grants-mcp`).
2. **Dejar que la ingesta rellene lo que toca**: desde la fase A, cada entrada
   que pasa por el conector guarda su `organo_ref_fuente`. Un par de pasadas de
   `scrape-daily` bastan para lo reciente.
3. **Relleno del histórico** (fase 2 del RFC). Desde un checkout de la rama de
   la fase B —el script vive en ella y solo escribe `organo_ref_fuente`, que el
   código desplegado tolera— con el `DATABASE_URL` de producción:

   ```bash
   python scripts/rellenar_organo_ref_placsp.py --solo-meses   # qué ZIP leerá
   python scripts/rellenar_organo_ref_placsp.py                # plan: cuenta, no escribe
   python scripts/rellenar_organo_ref_placsp.py --aplicar      # escribe mes a mes
   ```

   Cruza por `idEvl` (en `url` en el 99,9 % de las filas; las 21 sin él, por
   expediente + nombre del órgano). Los meses salen de las filas pendientes
   (`bulk_YYYYMM`, `fecha_actualizacion_fuente`, `fecha_publicacion`): hay
   filas `placsp` actualizadas desde 2017, y PLACSP publica ZIP mensuales
   también de años anteriores (comprobado 2023-12). Es idempotente y
   reanudable: si se corta, volver a lanzarlo. Lo que quede, por orden:
   - `--desde 2025-01 --hasta 2026-10 --aplicar` barre los 22 meses enteros por
     si alguna fila no estaba en «su» mes.
   - `--respaldo-por-nombre --aplicar` deduce el órgano del nombre, solo cuando
     todas las demás filas con ese nombre tienen el mismo.
   - **Conflictos** (un `idEvl` con dos órganos) y filas sin resolver: una a
     una. Sin datos de usuario se borran (la reingesta las trae con su clave):
     `scripts/borrar_colisiones_rekey_placsp.py --sin-organo` las lista y con
     `--aplicar` las borra (`incluir_sin_organo` en `rekey-placsp.yml`). El
     2026-10-31 quedaron 21, todas filas de prueba de los E2E y smoke tests
     del 2026-05-11 (`E2E-*`, `LIC-SMOKE-*`, URLs de example.com). Con datos
     de usuario, se rellenan a mano tras mirar la entrada.
4. **Puerta 1**: `python scripts/inventario_pisadas_placsp.py` tiene que decir
   «ninguna» en «filas PLACSP sin organo_ref_fuente». Anotar también el
   inventario de pisadas (`--csv antes.csv`) y `make audit-truth-check`: son el
   «antes» del RFC.
5. **Puertas 2 y 3 del RFC** (SQL de §Verificación, consultas 2 y 3): ninguna
   clave nueva existe ya; línea base del dedupe con TED. Si existen —el
   incidente #577 dejó 7.380 filas escritas con la clave nueva el 2026-10-27/28,
   6.912 con gemela vieja—, `python scripts/borrar_colisiones_rekey_placsp.py`
   lista las que la guarda de `v164` encontraría (solo cuenta las que una fila
   vieja **con órgano** va a ocupar: correrlo tras el relleno) y con
   `--aplicar` las borra, salvo las que tengan pursuits, follows o watchlist.
   Sin `DATABASE_URL` local, los modos `colisiones` y `borrar-colisiones` de
   `rekey-placsp.yml` hacen lo mismo; el relleno, sus modos `plan`/`aplicar`.

## La ventana

1. **Copia de seguridad** comprobada en Supabase justo antes. Es el único
   rollback después de la reingesta.
2. **Parar todo lo que escribe licitaciones o sus hijas** y esperar a que no
   quede ningún run en curso (`gh run list --status in_progress`):

   ```bash
   gh workflow disable scrape-daily.yml      # PLACSP, empresas vigiladas, agregadas, DLQ
   gh workflow disable ml-scoring.yml        # tecnologia_score, predicciones
   gh workflow disable pliegos.yml           # documentos, fichas del pliego
   gh workflow disable rescore-ml-proba.yml
   ```

   `scrape-bulk.yml` y `reproceso-lotes.yml` son manuales: no lanzarlos. No hay
   worker desplegado (2026-10-19, [cutover-cron-al-worker.md](cutover-cron-al-worker.md));
   si lo hubiera (`SCHEDULER_PLANE=worker`), suspenderlo en Render.
3. **Vaciar la cola y la DLQ de PLACSP**: ningún `jobs` en `pending`/`running`
   que nombre una licitación (`v164` aborta si lo hay) y la DLQ resuelta o
   agotada ([dlq-replay.md](dlq-replay.md)). La DLQ no aborta la migración (su
   reintento re-parsea y ya escribe la clave nueva), pero un reintento a mitad
   de ventana escribiría antes de tiempo.
4. **Merge** del PR de la fase B. La API y la web se redespliegan solas; con
   `licitaciones_id_anterior` vacía todavía no cambia nada visible.
5. **Migrar**: `gh workflow run migrate.yml` (usa `DATABASE_ADMIN_URL`; el
   `postgres` de Supabase tiene `BYPASSRLS`). Si aborta, no tocó nada:
   - `sin organo_ref_fuente`: el relleno no terminó. Volver a «Antes», paso 3.
   - `forma vieja`: una fila de empresas vigiladas o agregadas sin su prefijo.
     Mirarla (`SELECT id_externo, fuente FROM licitaciones WHERE …`) y decidir.
   - `ya existen con la clave nueva`: algo escribió con el código nuevo antes de
     migrar. Esas filas son copias recientes de la fuente que la reingesta
     vuelve a traer: borrarlas, **salvo** que ya tengan datos de usuario
     (`pursuits`, `follows`, `watchlist_items`), y relanzar
     (`scripts/borrar_colisiones_rekey_placsp.py --aplicar`, «Antes», paso 5).
   - `trabajos pendientes en jobs`: paso 3.
   - `FK a licitaciones sin repuntar`: una tabla nueva con FK que `v164` no
     conoce. **No** se edita `v164` si ya está en `master`: revisión nueva.
   - `row-level security`: se migró con un rol sin `BYPASSRLS`; repetir con
     `DATABASE_ADMIN_URL`.
   - `lock_timeout`: algo tenía cerrojos sobre las filas (un run que no paró).
     Pararlo y relanzar.
6. **Refrescar `licitaciones_canonicas`** e **invalidar cachés**, con el
   `DATABASE_URL` de producción:

   ```bash
   python -c "from db.repositories.publico import refrescar_vista_canonicas as r; print(r())"
   python -c "from db.cache_signal import signal_cache_invalidation as s; s()"
   ```

   (o `rekey-placsp.yml` con `modo=refrescar`).

   Las fichas públicas que Vercel tenga en ISR con la `ref` vieja sirven hasta
   su revalidación; al regenerarse redirigen.
7. **Reanudar** (`gh workflow enable …` de los cuatro del paso 2) y vigilar la
   primera pasada: `placsp_sin_identificador_de_organo` y
   `placsp_organo_por_respaldo_*` en los `detalles` del run (tienen que ser 0 o
   casi), y `placsp_colision_expediente_total` en 0 desde ahora.

## Comprobación tras la ventana

Las consultas 4 a 7 de §Verificación del RFC. En corto:

```sql
-- 0 filas de la familia con la clave vieja.
SELECT count(*) FROM licitaciones
WHERE (fuente = 'placsp' OR fuente LIKE 'bulk\_%') AND id_externo !~ '^placsp:[^:]+:';

-- Un alias por fila re-escrita (= filas del mapa, 24.763 el 2026-10-26).
SELECT count(*) FROM licitaciones_id_anterior WHERE motivo = 'rekey_placsp_organo';

-- Datos de usuario apuntando a filas que existen (repetir por tabla de §4).
SELECT count(*) FROM pursuits p
LEFT JOIN licitaciones l ON l.id_externo = p.licitacion_id WHERE l.id_externo IS NULL;
```

Y en la web: `curl -sI https://<web>/licitaciones/<ccaa>/<slug>/<ref vieja>`
devuelve `308` con `Location` a la `ref` nueva; `GET
/api/v1/licitaciones/2026%2FLIC%2F0049` responde 200 con `Deprecation: true`.

## Después

1. **Reingesta única** de los ZIP con la clave nueva y limpieza de hijas de las
   filas pisadas: [reingesta-unica-placsp.md](reingesta-unica-placsp.md).
2. Medir: `python scripts/inventario_pisadas_placsp.py` («expedientes con clave
   nueva que conviven» crece desde 0) y `make audit-truth-check`; anotar el
   delta en el RFC y pasarlo a `implemented`.
3. Anunciar el cambio de ids a quien consuma webhooks o la API pública.
4. El 2027-04-30, retirar la resolución por alias en la API (la 308 pública se
   queda) y mover este runbook a `docs/archive/runbooks/`.

## Rollback

`v164` no tiene `downgrade` (como `v153`): la inversa vuelve a juntar
expedientes de órganos distintos. **Antes de la reingesta**, el mapa inverso
entero está en `licitaciones_id_anterior` (`motivo = 'rekey_placsp_organo'`) y
un copiar-repuntar-borrar con ese mapa (la misma lista de `_REFERENCIAS` de
`v164`) lo deshace, junto con revertir el PR. **Después** de la reingesta hay
expedientes que solo existen con la clave nueva y la inversa chocaría: queda la
copia de seguridad del paso 1 de la ventana más reingerir desde entonces.
