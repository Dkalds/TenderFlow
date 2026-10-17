# Runbook: re-key de `id_externo` PSCP a `pscp:{uuid}:{codi_expedient}`

**Propósito**: llevar las filas PSCP ya ingeridas a la clave nueva del conector
sin perder sus hijas ni los datos de usuario, y recuperar los contratos que la
clave vieja dejó pisar.

**Estado**: pendiente de ejecutar. La migración es
`db/alembic/versions/v152_rekey_pscp_id_externo.py` (aprobada para escribirse el
2026-10-17; correrla en producción sigue siendo una decisión, `migrate.yml` es
`workflow_dispatch`).

> **No dejar correr el conector nuevo contra filas sin re-key.** Desde este
> cambio, `scraper/connectors/pscp.py` escribe `pscp:{uuid}:{codi_expedient}`.
> Toda fila PSCP que la fuente vuelva a publicar entre el merge y la migración
> entraría como fila **nueva** junto a la vieja, y v152 aborta al encontrarla
> (paso 4). Por eso la ingesta PSCP se pausa antes del merge.

---

## Qué pasaba (medido en prod el 2026-10-17)

La clave era `pscp:{codi_expedient}`, y `codi_expedient` es texto libre que
teclea cada órgano. Dos fallos:

1. **No es único entre órganos.** 1.556 ids PSCP guardan en
   `licitaciones_history` un snapshot de **otro** órgano con **otro** título: el
   upsert por `id_externo` pisó un contrato con otro. Ejemplos: `pscp:2026/18`
   (Universitat de Barcelona → Ajuntament de Viladecans), `pscp:3668`
   (Ajuntament de Santa Coloma de Gramenet → Tractament i Selecció de Residus),
   `pscp:2025/68` (Consorci de les Vies Verdes de Girona → Universitat de
   Barcelona). Es una **cota inferior**: el historial solo guarda snapshot cuando
   cambia un campo seguido, y si una fila se pisó varias veces se cuenta una.
2. **A veces ni es un expediente.** 20 ids sin un solo dígito: `pscp:Obert` (el
   procedimiento; Consorci Hospital Clínic, SAP SuccessFactors), `pscp:Factura`,
   `pscp:FACTURA`, `pscp:N.A.`, `pscp:Sense nº expedient assginat` y 15
   descripciones del objeto (casi todas de Infraestructures de la Generalitat).
   `pscp:Factura` y `pscp:FACTURA` ya se pisaron (McAfee MVISION, Encora, Veeam);
   sus 4 `contrato_eventos` `modificacion` son artefactos de esas colisiones.

Lo que identifica el expediente es el UUID de la ficha
(`/detall-publicacio/{uuid}/{publicación}`). En las 60.501 filas PSCP:
todas lo tienen, **ningún UUID se comparte entre órganos**, y las 16.320 filas
no agregadas tienen 16.145 UUIDs. Los contratos menores agregados (`AGR`,
44.181 filas) comparten ficha: lo que los separa es el `codi_expedient`, de ahí
la clave compuesta. Las 60.501 claves nuevas son distintas entre sí.

**Supuesto sin verificar**: que el UUID es el mismo en todas las fases de un
expediente (anuncio → adjudicación → formalización). Lo afirma el nombre del
endpoint `detall-publicacio-expedient/{uuid}/{publicación}`, y el historial no
lo puede confirmar porque sus snapshots no guardan la URL. Si fuera falso, cada
fase sería una fila distinta. **Verificarlo antes de la ventana**, desde una
máquina con salida a la API (la sesión remota no la tiene):

```bash
# Varias filas del mismo expediente, una por fase: el UUID debe coincidir.
curl -s "https://analisi.transparenciacatalunya.cat/resource/ybgg-dgi6.json?\$where=codi_expedient='F26.0016'&\$select=fase_publicacio,nom_organ,enllac_publicacio"
```

## Alcance del re-key

Cambian **las 60.501** filas PSCP, no solo las 20. Hijas por `licitacion_id` /
`id_externo` con filas PSCP hoy: `adjudicaciones` (58.674), `documentos`
(1.350), `licitaciones_duplicados` (54, en `licitacion_id` o `canonical_id`),
`licitaciones_history`, `licitacion_tecnologia_score`, `contrato_eventos`, y
**datos de usuario**: `pursuits` (3, una sobre `pscp:Obert`), `user_notifications`
(5), `contratos_cartera` (1); `licitacion_tecnologia_score` es la grande
(960.361).

## Qué hace v152

Ver su docstring. En corto: mapa viejo → nuevo con la misma derivación que el
conector; aborta sin tocar nada si una clave nueva se repite o ya existe, o si
una FK a `licitaciones(id_externo)` no está en su lista; copia cada fila con su
id nuevo, repunta las 27 columnas que guardan el id (17 FK, 7 sin FK y 3
polimórficas: `follows`, `etiquetas_aplicadas`, `feature_store`), comprueba que
no queda ninguna referencia vieja y solo entonces borra las filas viejas. Va
con `row_security = off`: bajo un rol al que la RLS se le aplique falla en vez
de saltarse filas de otras organizaciones. El `postgres` de Supabase tiene
`BYPASSRLS` (medido el 2026-10-17) y no lo nota.

No limpia los restos de las colisiones (snapshots de `licitaciones_history` y
eventos `modificacion` de contratos ajenos, p. ej. los 4 de `pscp:Factura` y
`pscp:FACTURA`): siguen con la fila que los recibió. Si se quieren limpiar es
una decisión aparte.

Medido en local con volumen de prod (60.500 licitaciones, 968 k
`licitacion_tecnologia_score`, 58 k adjudicaciones): 52 s. En Supabase, con
filas más anchas, contar con unos minutos; `migrate.yml` tiene 90.

## Procedimiento

1. **Verificar el supuesto del UUID** (arriba), desde una máquina con salida a
   la API. Si el UUID cambiara entre fases, parar: la clave nueva partiría cada
   expediente en una fila por fase.
2. **Pausar la ingesta PSCP** en todos los planos que la corren:
   - GitHub Actions (`scrape-daily.yml`): borrar la variable de repo
     `PSCP_DATASET_ID`. Sin ella el conector se declara `disabled` en
     `ops_events` y sale en 0.
   - Worker (`scheduler/jobs/daily_atom.py`, ADR-033) y el reintento de la DLQ
     (`scheduler/dlq_retry.py`), si están activos: `PSCP_DATASET_ID=""` en su
     entorno. **Ojo**: sin la variable caen al default de
     `config/settings.py` (`ybgg-dgi6`) y siguen corriendo; tiene que estar
     definida y vacía.
3. **Merge** del PR.
4. **Migrar**: `gh workflow run migrate.yml` (usa `DATABASE_ADMIN_URL`).
   - Si aborta con `ya existen con la clave nueva`: algo escribió con el
     conector nuevo antes de la migración. Esas filas son copias recientes de
     la fuente que la re-ingesta del paso 7 vuelve a traer, así que se pueden
     borrar sin perder nada, **salvo** que ya tengan datos de usuario:
     ```sql
     -- Quién choca y si tiene pursuits/follows (si los tiene, parar y decidir).
     SELECT l.id_externo,
            (SELECT count(*) FROM pursuits p WHERE p.licitacion_id = l.id_externo) AS pursuits,
            (SELECT count(*) FROM follows f WHERE f.target_type = 'licitacion'
                AND f.target_id = l.id_externo) AS follows
     FROM licitaciones l
     WHERE l.fuente = 'pscp' AND l.id_externo ~ '^pscp:[0-9a-f-]{36}(:|$)'
       AND l.fecha_extraccion >= '<fecha del merge>';
     ```
     Borrarlas (`DELETE FROM licitaciones WHERE id_externo IN (...)`) y volver
     a lanzar la migración.
   - Si aborta con `row-level security`: migró con un rol sin `BYPASSRLS`.
     Repetir con `DATABASE_ADMIN_URL`.
5. **Refrescar `licitaciones_canonicas`**, o la superficie pública seguirá
   enlazando las claves viejas hasta el próximo `aggregates_precompute`:
   `python -c "from db.repositories.publico import refrescar_vista_canonicas as r; print(r())"`
   con el `DATABASE_URL` de producción.
6. **Reanudar la ingesta**: restaurar `PSCP_DATASET_ID=ybgg-dgi6` en los planos
   del paso 2.
7. **Re-ingesta** para recuperar los contratos pisados: con la clave nueva cada
   uno vuelve como fila propia. Los pisados tienen marcas `:updated_at`
   dispersas, así que hay que recorrer el dataset entero:
   `python -m scraper.connectors.pscp --desde 2024-01-01`. El cursor avanza por
   lotes (`cursor_advances_incrementally`): si la pasada se corta, el paso
   diario continúa desde donde quedó.

## Comprobación tras la ventana

```sql
-- 0 filas con la clave vieja (todas llevan el UUID tras el prefijo).
SELECT count(*) FROM licitaciones
WHERE fuente = 'pscp' AND id_externo !~ '^pscp:[0-9a-f-]{36}(:|$)';

-- Los datos de usuario siguen apuntando a filas que existen.
SELECT count(*) FROM pursuits p
LEFT JOIN licitaciones l ON l.id_externo = p.licitacion_id
WHERE p.licitacion_id LIKE 'pscp:%' AND l.id_externo IS NULL;
```

Tras correrla, mover este fichero a `docs/archive/runbooks/`.
