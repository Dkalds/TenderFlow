# Runbook: Model Rollback

**Propósito**: Revertir a una versión anterior del clasificador ML cuando la nueva versión degrada métricas.

**Responsable**: Equipo de ML/Datos  
**Trigger**: Alerta `model_f1_degradation` o feedback negativo significativo.

---

## Ver versiones del modelo disponibles

```bash
python - <<'EOF'
from db.database import connect
with connect() as c:
    rows = c.execute(
        "SELECT version, model_name, accuracy, f1_score, trained_at, is_active "
        "FROM model_versions ORDER BY trained_at DESC LIMIT 10"
    ).fetchall()
    for r in rows:
        active = "← ACTIVO" if r[5] else ""
        print(f"  v{r[0]} | {r[1]:30s} | acc={r[2]:.4f} f1={r[3]:.4f} | {r[4]} {active}")
EOF
```

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
from scraper.ml_classifier import SAPClassifier
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
