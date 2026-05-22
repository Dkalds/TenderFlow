# Runbook: Disaster Recovery

**Propósito**: Recuperar el sistema tras un fallo catastrófico (pérdida de BD, servidor caído, despliegue roto).

**Responsable**: Equipo de Operaciones  
**Tiempo objetivo de recuperación (RTO)**: < 2 horas  
**Punto objetivo de recuperación (RPO)**: < 24 horas (último backup diario)

---

## 1. Evaluación inicial

```bash
python - <<'EOF'
import pathlib, sqlite3

issues = []

# 1. Base de datos
db = pathlib.Path("data/licitaciones.db")
if not db.exists():
    issues.append("❌ BD no encontrada")
else:
    try:
        con = sqlite3.connect(str(db))
        ok = con.execute("PRAGMA integrity_check").fetchone()[0]
        issues.append(f"{'✅' if ok == 'ok' else '❌'} BD integrity_check: {ok}")
    except Exception as e:
        issues.append(f"❌ BD no abre: {e}")

# 2. Backups disponibles
backups = sorted(pathlib.Path("data/backups").glob("*.db.gz"))
issues.append(f"{'✅' if backups else '❌'} Backups: {len(backups)} disponibles")
if backups:
    issues.append(f"   Último: {backups[-1].name}")

# 3. Modelos ML
model = pathlib.Path("data/models/sap_classifier.pkl")
issues.append(f"{'✅' if model.exists() else '⚠️'} Modelo ML: {'presente' if model.exists() else 'ausente'}")

for line in issues:
    print(line)
EOF
```

## 2. Restaurar base de datos desde backup

Ver [backup-restore.md](./backup-restore.md).

## 3. Restaurar modelo ML

Ver [model-rollback.md](./model-rollback.md).

## 4. Re-ejecutar migraciones pendientes

```bash
python - <<'EOF'
from db.database import init_db
init_db()
print("Migraciones aplicadas correctamente.")
EOF
```

## 5. Verificar scraper (re-sincronización)

```bash
python -m scheduler.run_update --days 7
```

Descarga y procesa los últimos 7 días para llenar el gap.

## 6. Levantar servicios

```bash
docker compose up -d
```

## 7. Smoke test completo

```bash
python - <<'EOF'
import httpx, os

base = os.environ.get("API_BASE_URL", "http://localhost:8080")
key = os.environ.get("API_KEY", "")

checks = [
    ("GET", f"{base}/health"),
    ("GET", f"{base}/api/v1/licitaciones?limit=1", {"X-API-Key": key}),
]

for method, url, *headers in checks:
    h = headers[0] if headers else {}
    try:
        r = httpx.request(method, url, headers=h, timeout=5)
        print(f"  {'✅' if r.status_code < 400 else '❌'} {method} {url} → {r.status_code}")
    except Exception as e:
        print(f"  ❌ {method} {url} → {e}")
EOF
```

## 8. Post-mortem

Documenta en `docs/adr/` o en el canal de incidentes:
- Causa raíz
- Acciones tomadas
- Tiempo de recuperación
- Mejoras para evitar repetición
