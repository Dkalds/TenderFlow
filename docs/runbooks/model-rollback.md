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
`scrape-daily`; desde el 2026-10 ese paso ya no entrena: lanza
`train-model.yml`, o avisa si no puede. Y `train-model.yml` activa **después**
de subir, tras comprobar que la Release publica el sha256 registrado. Lo que
queda son los caminos manuales: un `activate_version` sobre una versión cuyo
artefacto no está publicado, o alguien que sustituye el asset a mano.

**Salidas**, por orden de preferencia:

1. **El artefacto registrado existe todavía** (el job sigue en curso o lo
   guardaste): subilo a la Release con el nombre registrado y no toques la BD.
2. **Hay otra versión cuyo artefacto sí está publicado**: `activate_version`,
   como en «Marcar versión anterior como activa en BD».
3. **Ninguna de las dos** (el caso del 2026-09-29: el `.pkl` murió con el
   runner): dejá el modelo sin versión activa. Los consumidores vuelven al
   artefacto de nombre fijo de la Release, que es lo que servían antes.

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

El workflow va en este orden: entrenar y pasar el gate → subir el artefacto a
la Release → comprobar que lo publicado es lo registrado → activar → recalcular
`ml_proba`. Si el candidato pasa el gate, «Train model» lo deja registrado
**sin activar** y retira la versión que estuviera activa, porque la subida va a
sustituir su asset.

Así que un fallo a partir de ahí deja `sap_classifier` **sin versión activa**:
los runners sirven el asset de nombre fijo que haya en la Release. Es un estado
degradado —nada lo coteja contra el registro— pero ninguna pasada cae.

- **Falló la subida**: mirá qué publica la Release con el `gh api` de arriba.
  Si `sap_classifier.pkl` sigue ahí, es el anterior: reactivá su versión con
  `activate_version`, o relanzá el workflow. Si no está —el paso borra el asset
  antes de subir el nuevo—, los runners no tienen modelo y `ml_scoring` sale
  `skipped` hasta que un entrenamiento vuelva a publicar uno.
- **Falló «Activar la versión publicada»**: el asset ya es el nuevo. El resumen
  del run dice por qué no se activó. Si era un fallo pasajero de la API de
  GitHub, se activa a mano, con la versión que emitió «Train model» y un token
  que pueda leer la Release:

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
mano** (UI o token personal): dispararía `release-sdk.yml`. La crea
`train-predictivos.yml` con su propio token.

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
- **Qué se cambió.** Con `SCHEDULER_PLANE` declarado nadie entrena ni activa
  fuera de `train-model.yml`, que activa **después** de subir y cotejar el
  `digest` (#404, #405); `model_artifacts_canary` coteja a diario. La v2 se
  desactivó a mano y no es recuperable: su artefacto no existe.
- **Qué sigue abierto.** Ver correr el flujo nuevo de punta a punta, decidir
  qué dataset entrena cada camino, y nombrar el asset por contenido como los
  predictivos.

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

```bash
python - <<'EOF'
from services.ml.sap_classifier import SAPClassifier
clf = SAPClassifier.load()
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

| Variable | Valor |
| --- | --- |
| `EMBEDDINGS_ONNX_REVISION` | Commit (40 hex) de `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` |
| `EMBEDDINGS_ONNX_SHA256_MODELO` | sha256 de `onnx/model.onnx` en ese commit |
| `EMBEDDINGS_ONNX_SHA256_TOKENIZADOR` | sha256 de `tokenizer.json` |
| `EMBEDDINGS_ONNX_SHA256_CONFIG` | sha256 de `sentence_bert_config.json` |

Sin `EMBEDDINGS_ONNX_REVISION` el build no descarga nada y la imagen no define
`EMBEDDINGS_ONNX_DIR`: así se construyen el CI, el worker y el MCP.

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

**Revertir.** Declarar `EMBEDDINGS_ONNX_DIR` **vacía** en el entorno del
servicio (borrarla no basta: la imagen la define) apaga el motor sin rebuild;
la búsqueda vuelve a FTS.
