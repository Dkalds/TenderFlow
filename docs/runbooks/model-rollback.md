# Runbook: Model Rollback

**Propósito**: Revertir a una versión anterior del clasificador ML cuando la nueva versión degrada métricas.

**Responsable**: Equipo de ML/Datos  
**Trigger**: Alerta `model_f1_degradation` o feedback negativo significativo.

---

## Ver versiones del modelo disponibles

```bash
python - <<'EOF'
from db.model_registry import list_versions

for fila in list_versions("sap_classifier", limit=10):
    activa = "← ACTIVO" if fila["is_active"] else ""
    print(
        f"  v{fila['version']} | f1={fila['metrics'].get('f1')} | {fila['trained_at']} | "
        f"{fila['sha256'][:12]} | {fila['path']} {activa}"
    )
EOF
```

## `ModelArtifactMismatch`: el registro y la Release no coinciden

**Síntoma**: el paso `ml_scoring` del cierre falla con `ModelArtifactMismatch`
(evento `model_artifact_sha256_mismatch_post_download`, con `expected` y
`actual`), o llega el aviso del paso `model_artifacts_canary`
(«model_versions y las Releases divergen»), que trae el modelo, la versión, los
dos hashes y la Release.

**Qué significa**: la versión activa de `model_versions` registra un sha256
(`expected`) y el asset que publica la Release con ese nombre tiene otro
(`actual`). Ningún proceso puede servir esa versión: todos bajan el asset,
comparan y abortan. `expected` sale de la BD; `actual`, del fichero publicado:

```bash
gh api repos/Dkalds/TenderFlow/releases \
  --jq '.[] | .tag_name as $t | .assets[] | [$t, .name, .digest, .updated_at] | @tsv'
```

Cómo se llega: algo activó una versión sin publicar su artefacto. El
2026-09-29 fue el reentrenamiento automático dentro de un runner de
`scrape-daily`. Desde 2026-10 hay **un solo camino de entrenamiento** y por
código no puede repetirse:

- El paso semanal `sap_active_learning` no entrena en ningún plano —tampoco
  sin `SCHEDULER_PLANE`, en un checkout local—: lanza `train-model.yml`, o
  avisa con el comando si no puede.
- El gate (`services.ml.promotion.promote_if_better`) **no activa nunca**: ya
  no tiene parámetro `activar`. Registra el candidato inactivo y, si pasa,
  escribe `sap_classifier-<sha12>.pkl` (`pendiente_de_activar`). Vale también
  para `python scripts/ml_clasificadores.py train`, que ahora dice «registrada
  SIN activar» en vez de «Modelo guardado».
- Lo único que activa es `python -m scheduler.jobs.ml_training_run activar
  --version N`, el paso de `train-model.yml` posterior a la subida, y solo si
  la Release publica el sha256 registrado.

Lo que queda son los caminos manuales que se saltan todo eso: un
`activate_version` a pelo sobre una versión cuyo artefacto no está publicado,
o alguien que sustituye el asset a mano.

**Salidas**, por orden de preferencia:

1. **El artefacto registrado existe todavía** (el job sigue en curso o lo
   guardaste): subilo a la Release `ml-models` con el nombre registrado
   (`basename` del `path`, p. ej. `sap_classifier-<sha12>.pkl`) y no toques la
   BD.
2. **Hay otra versión cuyo artefacto sí está publicado**: `activate_version`,
   como en «Marcar versión anterior como activa en BD». Desde 2026-10 es lo
   normal para `sap_classifier`: cada versión publicada por `train-model.yml`
   conserva su asset en `ml-models`.
3. **Ninguna de las dos** (el caso del 2026-09-29: el `.pkl` murió con el
   runner): dejá el modelo sin versión activa. Los consumidores vuelven al
   artefacto de nombre fijo de la Release (`sap_classifier.pkl` de
   `v1.0.0-models`, el de mayo), que es lo que servían antes.

   ```bash
   python - <<'EOF'
   from db.model_registry import deactivate, get_active

   print("desactivadas:", deactivate("sap_classifier"))
   print("activa ahora:", get_active("sap_classifier"))
   EOF
   ```

   Desactivar no relanza ningún entrenamiento: el paso semanal
   `sap_active_learning` cuenta el feedback humano posterior a la última
   versión **registrada**, esté activa o no. Si querés un modelo nuevo,
   `gh workflow run train-model.yml`.

Después de cualquiera de las tres, la siguiente pasada de `scrape-daily` puntúa
lo que quedó pendiente (`ml_proba IS NULL`), y `model_artifacts_canary` deja de
avisar. Las filas que ya tenían score lo conservan, y puede ser el de un modelo
que ya no se sirve: ver «Recalcular `ml_proba`».

## `train-model.yml` falló después de «Train model»

El workflow va en este orden: entrenar y pasar el gate → verificar que hay
artefacto → subirlo a la Release `ml-models` → comprobar que lo publicado es lo
registrado → activar → recalcular `ml_proba`. Si el candidato pasa el gate,
«Train model» lo deja registrado **sin activar**, con su artefacto en
`data/models/sap_classifier-<sha12>.pkl` (nombre por contenido; el output
`artefactos` del paso lo lista junto a su `.sha256`).

**La versión activa no se toca.** El asset nuevo tiene otro nombre, así que la
subida no sustituye el de la versión que se esté sirviendo, y no se borra
ningún asset antes de subir. Un fallo a partir de «Train model» deja todo como
estaba: sigue activa la versión anterior —cotejada contra el registro— o, si no
había ninguna, se sirve el `sap_classifier.pkl` de nombre fijo de
`v1.0.0-models`. La versión nueva queda registrada e inactiva, y es inofensiva.

Hasta 2026-10 el asset se llamaba siempre `sap_classifier.pkl` y vivía en
*latest*: la subida pisaba el de la versión activa, así que «Train model» la
retiraba antes, el modelo se servía sin cotejar hasta la activación, y un fallo
de la subida tras borrar el asset dejaba a los runners sin modelo.

- **Falló «Verify model artifact»** (`promoted=true` sin `artefactos`): el gate
  dio por bueno al candidato pero no dejó fichero. No se subió nada; es un
  fallo de código, no de datos: el log de «Train model» dice dónde quedó el
  artefacto (`promotion.artefacto_publicado`).
- **Falló la subida**: no cambió nada de lo que se sirve. Relanzá el workflow,
  o subí a mano el `.pkl` y el `.sha256` que lista el output `artefactos` (si
  el runner aún los tiene) a `ml-models` y activá como en el punto siguiente.
- **Falló «Activar la versión publicada»**: el asset nuevo ya está en
  `ml-models`. El resumen del run dice por qué no se activó. Si era un fallo
  pasajero de la API de GitHub, se activa a mano, con la versión que emitió
  «Train model» y un token que pueda leer la Release:

  ```bash
  GITHUB_TOKEN="$(gh auth token)" python -m scheduler.jobs.ml_training_run activar --version <N>
  ```

  Hace las mismas comprobaciones que el paso del workflow, y si no cuadran no
  activa.

## Recalcular `ml_proba`

La pasada diaria solo puntúa las filas con `ml_proba IS NULL`. Cuando cambia el
modelo que se sirve sin que nadie entrene —un rollback, una versión retirada,
un recálculo que se cortó a medias—, las filas ya puntuadas conservan el score
del modelo anterior. Para reescribirlas todas con el que se sirve ahora:

```bash
gh workflow run rescore-ml-proba.yml
```

Desde Actions y no desde un checkout: el score depende de las versiones de
scikit-learn y numpy con las que se carga el artefacto, y las que cuentan son
las de `requirements.txt`. `train-model.yml` ya hace este recálculo al activar
una versión nueva.

## Criterio de promoción: cuándo una versión puede activarse

Antes de activar nada (y antes de revertir «porque el nuevo va peor»), el
criterio escrito es este, y no la intuición de quien mire el número:

- **Clasificador SAP** (`sap_classifier`): lo decide `services/ml/promotion.py`
  contra el golden set humano. Bloquea por `recall_no_keyword` — un modelo que
  no pesca nada que las keywords no pesquen no aporta sobre `matches_sap()`,
  que es gratis.
- **Modelos predictivos** (`baja_model`, `retencion_model`): lo decide
  `services.ml.promotion.evaluar_promocion_predictiva`. Una versión solo se
  promociona si **su mejora sobre el baseline supera la dispersión de esa misma
  métrica entre folds** (`MIN_IMPROVEMENT_OVER_FOLD_DISPERSION`, hoy 1.0). Los
  criterios del RFC 20260611-2 (mejora relativa ≥10% y cobertura del intervalo
  en [75, 85]% para baja; PR-AUC > prevalencia + 0.15 y ECE < 0.08 para
  retención) siguen siendo condición necesaria y entran en la misma decisión.

  El caso que motivó el criterio: `baja_model` v2 mejoraba el baseline un 3,3%
  (`mae_p50` 0.12494 vs 0.12999, o sea 0.005) con `mae_p50_std_folds` = 0.01287
  — dos veces y media esa mejora. Activar ahí es activar ruido.

  El baseline de retención es el **ranking trivial**: el PR-AUC esperado de
  ordenar al azar es la prevalencia, y se registra como `pr_auc_baseline`.
  Desde 2026-09-18 se registra además `pr_auc_baseline_antiguedad` (ordenar
  por `antiguedad_relacion_meses`, sin modelo): es un rival más exigente y
  **no gatea** — está para que quien active vea si el modelo aporta algo sobre
  un `ORDER BY`.

**Artefactos de los predictivos (desde 2026-09-24).** Cada versión de
`baja_model`/`retencion_model` se publica con un nombre derivado de su
contenido (`baja_model-<sha256[:12]>.pkl`) en la Release de tag fijo
`ml-models`, que nunca pasa a *latest*. Revertir o activar es, por tanto, solo
`activate_version`: el fichero de cada versión sigue en su sitio y ninguna
otra lo pisa. Antes todas se llamaban `baja_model.pkl` y el reentrenamiento
mensual subía con `--clobber`, así que con vN activa el siguiente
entrenamiento pisaba su asset y el scoring caía por `ModelArtifactMismatch`.
Las filas anteriores a ese cambio, con nombre fijo, se siguen resolviendo por
nombre entre las 30 Releases más recientes. **No crees la Release `ml-models` a
mano** (UI o token personal): dispararía `release-sdk.yml`. La crean
`train-predictivos.yml` o `train-model.yml` con su propio token.

**Artefactos del clasificador SAP (desde 2026-10).** Igual que los
predictivos: `train-model.yml` sube `sap_classifier-<sha256[:12]>.pkl` y su
`.sha256` a `ml-models`, sin borrar nada antes, y registra esa ruta en
`model_versions`. Revertir a una versión publicada así es `activate_version`.
Quién lo carga y cómo:

| Proceso | Cómo resuelve `sap_classifier` |
| --- | --- |
| Ingesta (`scraper/pipeline.py`) y `precompute`/rescore de `ml_proba` | `SAPClassifier.resolve_artifact()` y después `SAPClassifier.load(ruta)` |
| API (`/explain`, cola de feedback) | `api.model_cache` → `resolve_active_artifact` |
| Canary (`model_artifacts_canary`) | `digest` del asset con el nombre registrado, sin descargar |

`resolve_artifact()` busca la versión activa por su nombre registrado y coteja
el sha256; un asset que no cuadra lanza `ModelArtifactMismatch` (la ingesta lo
registra como `pipeline.ml_clf_artifact_mismatch` y sigue sin modelo). **Sin
versión activa** —el estado de producción a 2026-10-24— cae al
`sap_classifier.pkl` de nombre fijo, que `ensure_downloaded` busca en
`ml-models`, *latest* y las recientes: hoy es el de mayo de `v1.0.0-models`
(sha256 `5ddcc0ee…`), servido **sin cotejar**, como hasta ahora. Ese fallback
deja de usarse en cuanto se active una versión publicada por el flujo nuevo; el
asset de mayo no se borra, para poder volver a él desactivando. La API sin
versión activa no cambia con esto: sigue haciendo `SAPClassifier.load()` sin
ruta, que busca el `data/models/sap_classifier.pkl` local.

Cada versión guarda el veredicto y su número en `notes` y en `metrics_json`
(`promotion_reason`, `mejora_sobre_baseline`, `dispersion_entre_folds`,
`margen_exigido`). Para leerlo:

```bash
python - <<'EOF'
from db.model_registry import list_versions

for fila in list_versions("baja_model"):
    metricas = fila.get("metrics") or {}
    print(f"v{fila['version']}  activa={fila['is_active']}")
    print(f"  {fila.get('notes')}")
    print(
        f"  mejora={metricas.get('mejora_sobre_baseline')} "
        f"dispersion={metricas.get('dispersion_entre_folds')} "
        f"margen_exigido={metricas.get('margen_exigido')}"
    )
EOF
```

Una versión que **no** supera el criterio queda registrada igual, con
`promotion_reason` explicando cuál de las dos cuentas falló: el histórico es lo
que permite ver si la siguiente mejora de verdad o repite la anterior.

### Ampliar el golden del clasificador SAP

El gate del `sap_classifier` es tan bueno como `tests/fixtures/golden_set.jsonl`,
y con 27 ejemplos (3 positivos sin keyword en cada mitad) no sostiene ni el
umbral ni `recall_no_keyword`. Ampliarlo es trabajo humano; las herramientas
solo quitan la fricción. **No se fabrican etiquetas** ni se rellenan con reglas
o con el LLM: el golden juzga a esas fuentes.

1. **Muestrear** (solo lectura). Con acceso a la BD:

   ```bash
   ENV=prod PYTHONPATH="$PWD" python -m scripts.sample_golden_candidates \
       --n 400 --out data/etiquetado/candidatos_golden_sap.jsonl
   ```

   Sin acceso directo, exportar desde quien lo tenga (misma consulta que
   `LicitacionRepository.get_unlabelled_candidates`) y muestrear el export:

   ```bash
   psql "$DATABASE_URL" -c "\copy (SELECT l.id_externo, l.titulo, l.descripcion, l.cpv, l.importe, l.organo_contratacion, l.ml_proba FROM licitaciones l LEFT JOIN ml_feedback f ON l.id_externo = f.expediente AND f.source NOT LIKE 'reporte:%' WHERE f.expediente IS NULL ORDER BY l.fecha_publicacion DESC LIMIT 5000) TO 'export.csv' CSV HEADER"
   python -m scripts.sample_golden_candidates --desde export.csv --n 400 \
       --out data/etiquetado/candidatos_golden_sap.jsonl
   ```

   Si `ml_proba` viene en todas las filas del export se usa para estratificar;
   si no, se puntúa con el modelo de `data/models/` (o se muestrea sin banda).
   `data/` no se versiona: el fichero de candidatos no va al repo.

2. **Etiquetar** en la terminal: `python -m scripts.revisar_golden_candidates
   data/etiquetado/candidatos_golden_sap.jsonl`. `1` es SAP, `0` no, `d` dudoso
   (sale de la cola; `--dudosos` lo vuelve a enseñar), `s` saltar, `q` salir.
   Guarda tras cada respuesta y se reanuda donde quedó. Enseña título,
   descripción, CPV, órgano e importe; **no** `keyword_match` ni la
   probabilidad del modelo, para no anclar. Cada etiqueta lleva `source` y
   `fecha`.

3. **Anexar y medir**: `--anexar` añade lo etiquetado (nunca nulos ni
   dudosos, nunca ids repetidos) al golden; `--estado` dice si cumple
   (≥ 60 por mitad y ≥ 30 positivos sin keyword en holdout) y, con un modelo en
   `data/models/`, el intervalo bootstrap del umbral elegido en `tune`
   (`services.ml_eval.umbral_bootstrap`, misma rejilla que el tuning servido).
   Con 27 ejemplos el ancho p5-p95 era 0,26; por debajo de 0,10 el informe lo
   da por estable (orientativo, no entra en el gate).

### `baja_model` v2 y `retencion_model` v1: qué hace falta para decidir

La decisión es humana (`train-predictivos.yml` no activa salvo
`ML_PRED_AUTO_ACTIVATE`), pero no a ojo: se activa una versión cuando
**todas** estas condiciones se cumplen con los números de su fila de
`model_versions` delante, y se anota el número que lo justifica en `notes`.

| Modelo | Condición (todas) | De dónde sale |
| --- | --- | --- |
| `baja_model` | `mae_baseline − mae_p50 ≥ mae_p50_std_folds × MIN_IMPROVEMENT_OVER_FOLD_DISPERSION` (1.0) | `evaluar_promocion_predictiva` |
| | mejora relativa en MAE ≥ 10 % (`MEJORA_MINIMA_RELATIVA`) | `baja_model.py`, RFC 20260611-2 |
| | `cobertura_intervalo_80` en [0,75, 0,85] | `baja_model.py`, RFC 20260611-2 |
| `retencion_model` | `pr_auc − pr_auc_baseline ≥ pr_auc_std_folds × 1.0` (baseline = prevalencia) | `evaluar_promocion_predictiva` |
| | `pr_auc > prevalencia + 0,15` (`PR_AUC_MARGEN`) y `ece < 0,08` (`ECE_MAX`) | `retencion_model.py`, RFC 20260611-2 |
| | Resuelta la clave de `predicciones_retencion` (hoy un riesgo por expediente, pinta una fila por adjudicatario) | backlog P2, exige migración |
| Los dos | Sin dispersión medida **no se activa**: una mejora sin error asociado no se distingue del ruido | `evaluar_promocion_predictiva` |

Aplicado a lo registrado (backlog P2 «`baja_model` v2 y `retencion_model` v1
están entrenados…»):

- **`baja_model` v2: no promocionable.** Mejora 0,005 en `mae_p50`
  (0,12494 vs 0,12999, un 3,3 %) frente a una dispersión entre folds de 0,01287:
  falla la dispersión y falla el 10 % relativo.
- **`retencion_model` v1: no decidible.** Es anterior al gate y no registra
  `pr_auc_std_folds`; `pr_auc` 0,2453 sobre prevalencia 0,1099 (margen 0,135 <
  0,15) tampoco pasaría el criterio del RFC. Hay que relanzar
  `train-predictivos.yml` para tener la versión con dispersión y rival de
  antigüedad registrados, y decidir sobre esa.
- `pr_auc_baseline_antiguedad` (ordenar por antigüedad de la relación) **no
  gatea**: si el modelo no lo supera, actívalo sabiendo que un `ORDER BY` hacía
  lo mismo.

## Incidente de la v2 de `sap_classifier` (2026-09-29): resumen

La ficha completa, con fechas, PRs y criterios abiertos, está en el P1 del
backlog «Cerrar el incidente de la v2 de `sap_classifier`». Lo que conviene
saber antes de tocar el clasificador:

- **Qué pasó.** El paso semanal `sap_active_learning` de `scrape-daily` contó
  59 feedbacks humanos (umbral 50), reentrenó **dentro del runner**, pasó el
  gate y activó la v2. El `.pkl` se quedó en el disco efímero del runner y no
  se subió a ninguna Release: desde la pasada siguiente, `ml_scoring` bajaba el
  asset de mayo, el sha256 no coincidía con el registrado y fallaba con
  `ModelArtifactMismatch` (14 fallos entre el 29/09 y el 03/10).
- **Por qué pasó el gate con poco.** La v2 pasó con `recall_no_keyword` 0,33
  medido sobre **tres** ejemplos del golden legado (27 ejemplos escritos a
  mano). Un gate sobre un golden tan pequeño no protege: es la razón de fondo
  del golden real (`golden_ti.jsonl`, [etiquetado-ti.md](etiquetado-ti.md)).
- **Qué se cambió.** Nadie entrena ni activa fuera de `train-model.yml`, que
  activa **después** de subir y cotejar el `digest` (#404, #405);
  `model_artifacts_canary` coteja a diario. En 2026-10 se retiró el segundo
  camino: el reentrenamiento en proceso de `maybe_retrain_classifier` (que
  seguía vivo sin plano declarado, con su propio dataset sobre
  `licitaciones` entera) y el `activar=True` por defecto del gate. Queda un
  dataset —el de `train_from_db`— y una sola puerta de activación. La v2 se
  desactivó a mano y no es recuperable: su artefacto no existe.
- **Qué sigue abierto.** Ver correr el flujo nuevo de punta a punta —con el
  asset ya nombrado por contenido en `ml-models` (2026-10), que nunca se ha
  ejecutado en producción—: ver «Verificar la primera pasada de
  `train-model.yml`» justo debajo. La etiqueta de `train_from_db` sigue siendo
  circular (keywords); sustituirla por la de nivel 1 es otro ítem del backlog.

## Verificar la primera pasada de `train-model.yml`

Es la acción pendiente del dueño para cerrar el incidente. Con un token que
pueda lanzar workflows y leer Releases, y `.env` apuntando a producción:

```bash
# 1. Lanzar y esperar.
gh workflow run train-model.yml
RUN="$(gh run list --workflow=train-model.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
gh run watch "$RUN"

# 2. El resumen del run. Si el gate rechazó, lo dice con los motivos y sale
#    en verde a propósito: no hay nada más que comprobar. Si pasó, tiene que
#    listar «Asset: `sap_classifier-<sha12>.pkl`» y «Versión activada».
gh run view "$RUN"

# 3. El asset está en `ml-models` con nombre por contenido.
gh release view ml-models --json assets \
  --jq '.assets[] | select(.name | startswith("sap_classifier-")) | [.name, .digest] | @tsv'

# 4. La versión activa apunta a ese asset y registra ese sha256.
python - <<'PY'
from pathlib import Path
from db.model_registry import get_active
a = get_active("sap_classifier")
print(a and (a["version"], Path(a["path"]).name, a["sha256"]))
PY
```

Lo de 3 y 4 tiene que coincidir: mismo nombre y `digest` = `sha256:<sha256>`.
Después, en la siguiente pasada de `scrape-daily`, `model_artifacts_canary` y
`ml_scoring` en `ok` (o en Ops › Ejecuciones):

```sql
SELECT payload_json, estado, updated_at
FROM jobs
WHERE tipo = 'paso_pipeline'
  AND (payload_json LIKE '%model_artifacts_canary%' OR payload_json LIKE '%ml_scoring%')
ORDER BY updated_at DESC
LIMIT 6;
```

y en el log de la ingesta, `pipeline.ml_clf_loaded` con la ruta
`sap_classifier-<sha12>.pkl`. El `workflow_dispatch` desde el paso semanal se
ve igual: un run de `train-model.yml` con evento `workflow_dispatch`
(`gh run list --workflow=train-model.yml`), tras el aviso «reentrenamiento del
clasificador SAP lanzado».

## Ver modelos en disco

```bash
python - <<'EOF'
import pathlib
models_dir = pathlib.Path("data/models")
for f in sorted(models_dir.glob("*.pkl")):
    print(f"  {f.name}  ({f.stat().st_size / 1024:.1f} KB)")
EOF
```

## Rollback al modelo anterior

Solo para un checkout local que sirve desde `data/models/` sin registro. En
producción el rollback es «Marcar versión anterior como activa en BD».

```bash
python - <<'EOF'
import pathlib, shutil
models_dir = pathlib.Path("data/models")

current = models_dir / "sap_classifier.pkl"
backups = sorted(models_dir.glob("sap_classifier_*.pkl"))

if not backups:
    print("ERROR: No hay backup de modelo disponible.")
else:
    restore = backups[-1]
    # Guardar el actual como .broken
    if current.exists():
        current.rename(str(current) + ".broken")
    shutil.copy2(restore, current)
    print(f"Rollback completado: {restore.name} → sap_classifier.pkl")
EOF
```

## Verificar modelo restaurado

Por el mismo camino que la ingesta: la versión activa cotejada por sha256 (o,
sin versión activa, el asset de nombre fijo). Con `GITHUB_TOKEN` exportado si
el artefacto no está en local.

```bash
python - <<'EOF'
from services.ml.sap_classifier import SAPClassifier
artefacto = SAPClassifier.resolve_artifact()
print("artefacto:", artefacto)
clf = SAPClassifier.load(artefacto)
test_texts = [
    "Migración SAP S/4HANA",
    "Suministro de material de oficina",
]
for t in test_texts:
    is_sap, conf = clf.predict(t)
    print(f"  {'SAP' if is_sap else 'NO':3s} ({conf:.2%}) — {t[:60]}")
EOF
```

## Marcar versión anterior como activa en BD

Usá la función canónica del registry en vez de escribir el UPDATE a mano: hace
el cambio en un solo statement por nombre de modelo (el SQL manual de este
runbook desactivaba **todas** las filas de la tabla, no solo las del modelo que
se estaba revirtiendo, y usaba el paramstyle `?` que se retiró con ADR-021).

Mirá antes el `path` de la versión con «Ver versiones del modelo disponibles»:
si su basename lleva el sha256 (`sap_classifier-<sha12>.pkl`), su asset sigue
en `ml-models` y activarla basta. Si es `sap_classifier.pkl` (filas anteriores
a 2026-10), el asset con ese nombre puede ser de otra versión y la activación
acabará en `ModelArtifactMismatch`: comprobalo antes con el `gh api` de
«`ModelArtifactMismatch`», o esperá al aviso de `model_artifacts_canary`.

```bash
python - <<'EOF'
import sys
from db.model_registry import activate_version, get_active

target_version = int(sys.argv[1] if len(sys.argv) > 1 else input("Versión a activar: "))
if activate_version("sap_classifier", target_version):
    print(f"Modelo v{target_version} activo: {get_active('sap_classifier')}")
else:
    print(f"No existe la versión {target_version} para 'sap_classifier'.")
EOF
```

## De dónde sale `$ADMIN_API_KEY`

Los dos `curl` de abajo son los únicos pasos del runbook que no se resuelven con
acceso a la BD, y el endpoint que usan (`POST /models/{name}/activate/{version}`)
depende de `require_scope("admin")`, que **cuelga de `require_api_key` y por
tanto no acepta la cookie de sesión**: no hay forma de hacer esto desde la
consola, ni siquiera siendo administrador. Durante un incidente, descubrirlo en
ese momento cuesta minutos que no hay.

Si no tenés una key admin a mano, emitila antes de necesitarla:

```bash
# `--user-id` es obligatorio en prod/staging: una API key sin propietario se
# rechaza (una persona no puede fragmentarse en identidades por credencial).
python -m scripts.rotate_api_keys --name rollback-ops --user-id <TU_USER_ID> --scopes admin
```

El token se imprime una sola vez y no es recuperable. Guardalo en el gestor de
secretos del equipo, no en el historial del shell.

> Alternativa sin credencial, para cuando la key no aparece: el cambio de
> `is_active` del paso anterior ya está hecho en BD, así que basta con esperar
> a que venza `API_MODEL_CACHE_TTL_SECONDS` (5 min por defecto) o reiniciar el
> servicio desde el dashboard de Render. Es más lento y más brusco, pero no
> depende de tener el token.

## Hacer que la API sirva la versión nueva

Cambiar `is_active` en la BD **no basta**: el proceso de la API cachea el
clasificador cargado. Hay dos vías:

```bash
# Preferida — invalida la caché del proceso que atiende la petición.
# Requiere API key con scope admin.
curl -fsS -X POST \
  -H "X-API-Key: $ADMIN_API_KEY" \
  "$API_BASE_URL/api/v1/models/sap_classifier/activate/$TARGET_VERSION"
```

Si hay varios workers, cada uno recarga por su cuenta al vencer
`API_MODEL_CACHE_TTL_SECONDS` (5 min por defecto). Para un corte inmediato en
todos, reiniciá el servicio desde el dashboard de Render.

Verificá que la versión servida es la esperada:

```bash
curl -fsS -H "X-API-Key: $ADMIN_API_KEY" \
  "$API_BASE_URL/api/v1/models/sap_classifier" | python -m json.tool
```

## Modelo ONNX de embeddings (búsqueda por significado)

No es un modelo entrenado aquí ni pasa por `model_versions`: es
`paraphrase-multilingual-MiniLM-L12-v2` exportado a ONNX, el mismo que embebió
`documento_chunks`, y la API lo usa para codificar la consulta de
`POST /search/semantic` (`services/embeddings_onnx.py`). Sin él, la búsqueda
degrada a FTS (`source=fts`/`like`), que es lo que hacía hasta 2026-10.

**Dónde entra.** `docker/Dockerfile.api` lo descarga en el build con
`scripts/descargar_modelo_embeddings.py`: commit fijo del repo de Hugging Face y
sha256 de cada fichero, sin modo «sin verificar». Los argumentos se declaran
como variables del servicio `tenderflow-api` en Render, que las pasa como build
args:

| Variable | Qué es | Valor verificado (2026-10-25) |
| --- | --- | --- |
| `EMBEDDINGS_ONNX_REVISION` | Commit (40 hex) de `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | `e8f8c211226b894fcb81acc59f3b34ba3efd5f42` |
| `EMBEDDINGS_ONNX_SHA256_MODELO` | sha256 de `onnx/model.onnx` en ese commit (470.301.610 bytes) | `10f7a088420252b26caf819236ca2c9d2987afd0fc06fec7553b542a5655a05a` |
| `EMBEDDINGS_ONNX_SHA256_TOKENIZADOR` | sha256 de `tokenizer.json` | `2c3387be76557bd40970cec13153b3bbf80407865484b209e655e5e4729076b8` |
| `EMBEDDINGS_ONNX_SHA256_CONFIG` | sha256 de `sentence_bert_config.json` | `70f4448f31320443fe3557cacea5abf2dcc4915dda8c80646bec9f3bb0aa5a1f` |

Cómo se verificaron: commit y sha256 LFS de la API de Hugging Face
(`/api/models/<repo>/revision/main?blobs=true`), el del config con `sha256sum`
del fichero de ese commit; `descargar_modelo_embeddings.py` los bajó y los
aceptó; y los vectores que el modelo ONNX produce para tres fragmentos de
`documento_chunks` de producción coinciden con los que el pipeline guardó con
sentence-transformers (coseno 1,00000, `md5` del texto cotejado; detalle en
[docs/sli-slo.md](../sli-slo.md) § 8). El test de paridad frente a
sentence-transformers en local sigue sin ejecutarse (no hay PyTorch en la
máquina de quien lo verificó); la comparación con los vectores guardados mide
lo mismo contra lo que de verdad se consulta.

Sin `EMBEDDINGS_ONNX_REVISION` el build no descarga nada y la imagen no define
`EMBEDDINGS_ONNX_DIR`: así se construyen el CI, el worker y el MCP.

**Encenderlo en producción (propietario):**

1. En Render, servicio `tenderflow-api` → *Environment*: añadir las cuatro
   variables de la tabla con esos valores. No van en `render.yaml`: el
   Blueprint no gobierna el servicio (cabecera de `render.yaml`) y
   `check_env_parity` exigiría declararlas también en `.env.example`.
2. *Manual Deploy → Clear build cache & deploy*. En el log del build tiene que
   salir `descargar_modelo_embeddings: sentence-transformers/…@e8f8c211… en
   /modelos/embeddings`; si sale «sin revisión», las variables no llegaron como
   build args.
3. Con el deploy vivo, la búsqueda sigue siendo por texto: la fusión está
   detrás de la flag `busqueda_semantica`, **apagada por defecto**. Encenderla
   en Administración → Feature flags (primero por correo o con un porcentaje
   bajo, si se quiere graduar).
4. Comprobar en los logs: `semantic_search.ok` con `semantica=servida` y
   `source=rrf` en alguna búsqueda; `semantica=sin_motor` significa que el
   modelo no está en la imagen (paso 2) y `sin_aporte` en todas, que no hay
   fragmentos embebidos o pgvector no responde. Vigilar `fusion_ms` contra el
   presupuesto de [docs/sli-slo.md](../sli-slo.md) § 8 y el RSS tras la
   primera búsqueda.

**Cómo obtener los valores.** El commit, de la pestaña *Files and versions* del
repo (no `main`: una rama puede cambiar entre dos builds). Los sha256 de
`model.onnx` y `tokenizer.json` aparecen en la página de cada fichero (son
LFS); el de `sentence_bert_config.json` es el `sha256sum` del fichero bajado de
ese mismo commit. Después, en una máquina con el extra `[ml]` y el modelo de
sentence-transformers en caché:

```bash
python scripts/descargar_modelo_embeddings.py --destino /tmp/emb \
    --revision <commit> --sha256-modelo <hex> --sha256-tokenizador <hex> --sha256-config <hex>
EMBEDDINGS_ONNX_DIR=/tmp/emb pytest tests/test_embeddings_onnx_paridad.py -rs
```

El test de paridad exige coseno ≥ 0,999 frase a frase con sentence-transformers;
si se salta, dice por qué, y un salto no es un verde.

**Memoria.** La sesión ONNX son ~470 MB residentes, cargados en la primera
búsqueda (no al arrancar). La API corre en `standard` (2 GB); no lo actives en
un servicio de 512 MB.

**Qué NO usa este modelo.** La afinidad del Radar, el ranking de fragmentos del
RAG y el embebido de pliegos del worker codifican cientos o miles de textos por
petición y siguen exigiendo sentence-transformers
(`services.embeddings.embeddings_masivos_disponibles`). Los similares y el
predecesor de la ficha (≤ 100 títulos) sí lo usan.

**Revertir.** Para la búsqueda del Investigador basta con apagar la flag
`busqueda_semantica` en Administración: sin desplegar, la siguiente búsqueda ya
es por texto. Para soltar el modelo entero (también los similares de la ficha y
la memoria), declarar `EMBEDDINGS_ONNX_DIR` **vacía** en el entorno del
servicio (borrarla no basta: la imagen la define) apaga el motor sin rebuild;
la búsqueda vuelve a FTS.
