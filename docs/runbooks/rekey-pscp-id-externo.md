# Runbook: re-key de `id_externo` PSCP a `pscp:{uuid}:{codi_expedient}`

**Propósito**: llevar las filas PSCP ya ingeridas a la clave nueva del conector
sin perder sus hijas ni los datos de usuario, y recuperar los contratos que la
clave vieja dejó pisar.

**Estado**: pendiente. La migración de datos **no está escrita**: tocar
`db/alembic/` requiere OK explícito (AGENTS.md §6).

> **No desplegar el conector nuevo sin esta ventana.** Desde el cambio,
> `scraper/connectors/pscp.py` escribe `pscp:{uuid}:{codi_expedient}`. Toda fila
> PSCP que la fuente vuelva a publicar entraría como fila **nueva** junto a la
> vieja `pscp:{codi_expedient}`: duplicados en todas las superficies. Merge del
> código y re-key van en el mismo despliegue, o el re-key primero.

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
(5), `contratos_cartera` (1). La migración tiene que recorrer las 25 columnas
que referencian el id (consulta de abajo), no solo las que hoy tienen filas.

```sql
SELECT table_name, column_name FROM information_schema.columns
WHERE table_schema = 'public'
  AND column_name IN ('licitacion_id', 'id_externo', 'canonical_id');
```

## Propuesta (pendiente de OK)

1. **Migración de datos** (revisión nueva, append-only), en una transacción:
   - Mapa viejo → nuevo, con la misma derivación que el conector:
     ```sql
     CREATE TEMP TABLE rekey_pscp AS
     SELECT id_externo AS viejo,
            'pscp:' || lower(substring(url from '/detall-publicacio/([0-9a-fA-F-]{36})/'))
            || coalesce(':' || nullif(substr(id_externo, 6), ''), '') AS nuevo
     FROM licitaciones WHERE fuente = 'pscp';
     ```
     Abortar si algún `nuevo` es `NULL`, se repite o ya existe en `licitaciones`.
   - Copiar cada fila de `licitaciones` con su id nuevo, repuntar todas las
     hijas, borrar la vieja. (Copia + repunte en vez de `UPDATE` de la PK: las
     FK no declaran `ON UPDATE CASCADE`.)
   - Borrar los `contrato_eventos` `modificacion` de `pscp:Factura` y
     `pscp:FACTURA`.
2. **Re-ingesta** para recuperar lo pisado: con la clave nueva, cada contrato
   vuelve como fila propia. Hace falta pasar por todo el dataset (los pisados
   tienen marcas `:updated_at` dispersas), p. ej.
   `python -m scraper.connectors.pscp --desde 2024-01-01`. Avanza por lotes
   (`cursor_advances_incrementally`), así que puede repartirse en varios runs.
   Sin el paso 1, esto duplicaría las 60.501 filas.
3. **Dedupe**: `natural_expediente` y `_EXPEDIENTE_NATURAL_SQL` ya quitan el
   UUID, así que el emparejamiento PSCP ↔ PLACSP sigue por `codi_expedient`.

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
