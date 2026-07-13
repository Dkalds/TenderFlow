# Runbook: Backup & Restore

**Propósito**: Crear y verificar backups de la base de datos (Postgres/Supabase en producción; SQLite legacy en dev). Restaurar desde backup.

**Responsable**: Equipo de Operaciones  
**Frecuencia**: Diario (automático vía `backup.yml`, 03:00 UTC). Manual ante incidentes.

---

## Backups Postgres cifrados (producción, F3d)

La rama Postgres de `.github/workflows/backup.yml` ya cifra el dump con GPG
simétrico (AES256) **si y solo si** existe el secret `BACKUP_ENCRYPTION_KEY`.
Sin él, el workflow emite `::warning::` y sube el dump en claro a S3 privado
(nunca como artefacto de GitHub). El dump contiene PII y hashes de
`api_keys`/`totp_secrets`: el secret es obligatorio en producción.

### Alta del secret (acción manual del usuario, gate §6)

```bash
# Genera la clave y súbela como GH Secret en un solo paso.
openssl rand -base64 48 | gh secret set BACKUP_ENCRYPTION_KEY
```

> ⚠️ **Guardá la clave en tu gestor de contraseñas personal ANTES de subirla**
> (`openssl rand -base64 48` a un fichero temporal, copiala al gestor, después
> `gh secret set BACKUP_ENCRYPTION_KEY < fichero` y borrá el fichero).
> GitHub no permite volver a leer un secret: **sin la clave, los backups
> cifrados son irrecuperables**. No hay recuperación posible.

### Verificar que el cifrado quedó activo

1. `gh secret list | grep BACKUP_ENCRYPTION_KEY` — debe existir.
2. Lanzar el backup a mano: `gh workflow run backup.yml` y esperar el run.
3. En el run: el step de Postgres debe loguear `Dump cifrado → …dump.gpg`
   (sin el `::warning::` de clave ausente) y el artefacto
   `db-backup-<run_id>` debe contener solo `*.dump.gpg`.
4. El lunes siguiente (o a mano: `gh workflow run restore-drill.yml`),
   verificar que el drill semanal sigue verde.

### Descifrar un backup

```bash
# Descarga desde S3/R2 (o desde el artefacto del run) y descifra:
gpg --batch --yes --passphrase "$BACKUP_ENCRYPTION_KEY" \
    --decrypt --output tenderflow_pg.dump tenderflow_pg_YYYYMMDD_HHMMSS.dump.gpg
```

La passphrase es el valor exacto guardado en el gestor (el mismo string que
se pasó a `gh secret set`).

### Restaurar el dump Postgres

```bash
# --no-owner/--no-acl: el dump se creó así; restaura con el rol de la sesión.
pg_restore --clean --if-exists --no-owner --no-acl \
    --dbname "$DATABASE_ADMIN_URL" tenderflow_pg.dump
```

Tras restaurar: `alembic current` debe reportar `head`, y un smoke
`SELECT COUNT(*) FROM licitaciones;` debe devolver un conteo plausible.

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
