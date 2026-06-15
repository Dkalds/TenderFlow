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
python scripts/restore_db.py --verify                 # el último backup local
python scripts/restore_db.py --verify path/al.db.gz   # uno concreto
```

Corre `PRAGMA integrity_check` + query de humo (nº de tablas y filas en
`licitaciones`) sobre una copia temporal. Exit code 0 = restaurable.

> El workflow `.github/workflows/restore-drill.yml` ejecuta esta verificación
> sobre el último backup de S3/R2 cada lunes — un backup no probado no es un
> backup.

## Restaurar desde backup

> ⚠️ **DETENER** el scheduler y la API antes de restaurar.

```bash
make stop
```

```bash
# Restaura el backup indicado sobre la BD destino, preservando la actual
# como <target>.bak. Verifica el backup ANTES de tocar el destino.
python scripts/restore_db.py --restore data/backups/licitaciones_YYYYMMDD_HHMMSS.db.gz
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
