# Runbook: Backup & Restore

**Propósito**: Crear y verificar backups de la base de datos SQLite. Restaurar desde backup.

**Responsable**: Equipo de Operaciones  
**Frecuencia**: Diario (automático vía scheduler). Manual ante incidentes.

---

## Backup manual

```bash
python scripts/backup_db.py
```

Crea un fichero comprimido en `data/backups/licitaciones_YYYYMMDD_HHMMSS.db.gz`.

## Verificar integridad del backup

```bash
python - <<'EOF'
import gzip, sqlite3, pathlib, sys
backup = sorted(pathlib.Path("data/backups").glob("*.db.gz"))[-1]
with gzip.open(backup) as f:
    data = f.read()
tmp = pathlib.Path("/tmp/verify_backup.db")
tmp.write_bytes(data)
con = sqlite3.connect(str(tmp))
ok = con.execute("PRAGMA integrity_check").fetchone()[0]
print(f"Backup: {backup.name} — integrity_check: {ok}")
tmp.unlink()
EOF
```

## Restaurar desde backup

> ⚠️ **DETENER** el scheduler y la API antes de restaurar.

```bash
make stop
```

```bash
python - <<'EOF'
import gzip, shutil, pathlib, sys

# Seleccionar backup (modifica la fecha si no es el más reciente)
backups = sorted(pathlib.Path("data/backups").glob("*.db.gz"))
if not backups:
    print("ERROR: No se encontraron backups en data/backups/")
    sys.exit(1)

backup = backups[-1]
target = pathlib.Path("data/licitaciones.db")

# Guardar versión actual como .bak
if target.exists():
    target.rename(str(target) + ".bak")
    print(f"BD actual renombrada a {target}.bak")

with gzip.open(backup) as f:
    target.write_bytes(f.read())

print(f"Restaurado: {backup.name} → {target}")
EOF
```

```bash
make start
```

## Rollback si la restauración falla

```bash
python - <<'EOF'
import pathlib
target = pathlib.Path("data/licitaciones.db")
bak = pathlib.Path("data/licitaciones.db.bak")
if bak.exists():
    target.unlink(missing_ok=True)
    bak.rename(target)
    print("Rollback completado.")
else:
    print("No se encontró .bak — nada que restaurar.")
EOF
```
