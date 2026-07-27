"""Backup de la base de datos SQLite local.

Uso:
    python scripts/backup_db.py                 # SQLite local
    python scripts/backup_db.py --keep 7        # retener últimos N backups (default: 7)
    python scripts/backup_db.py --s3            # subir a S3/R2 después del backup local

El backup se cifra con GPG/AES-256 en data/backups/ con timestamp en el nombre.
Los backups más antiguos que --keep se eliminan automáticamente.

Variables de entorno para upload S3/R2:
    BACKUP_S3_BUCKET   — nombre del bucket (obligatorio para --s3)
    BACKUP_S3_PREFIX   — prefijo de ruta en el bucket (default: "backups/")
    AWS_ACCESS_KEY_ID  — o la variable equivalente para R2
    AWS_SECRET_ACCESS_KEY
    AWS_ENDPOINT_URL   — endpoint personalizado para Cloudflare R2

Variables de entorno para upload Azure (D6):
    BACKUP_AZURE_CONTAINER — nombre del container (obligatorio para --azure)
    BACKUP_AZURE_PREFIX    — prefijo dentro del container (default: "backups/")
    AZURE_STORAGE_CONNECTION_STRING — connection string completa
"""

from __future__ import annotations

import argparse
import gzip
import shutil
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def backup_sqlite(db_path: Path, backup_dir: Path) -> Path:
    """Copia segura (online backup) de una base de datos SQLite."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"licitaciones_{_timestamp()}.db"
    src_conn = sqlite3.connect(str(db_path))
    dst_conn = sqlite3.connect(str(dest))
    try:
        src_conn.backup(dst_conn)
        dst_conn.close()
    finally:
        src_conn.close()

    # Comprimir el backup
    gz_dest = Path(str(dest) + ".gz")
    with open(dest, "rb") as f_in, gzip.open(gz_dest, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    dest.unlink()

    size_kb = gz_dest.stat().st_size // 1024
    print(f"[backup] SQLite → {gz_dest} ({size_kb} KB)")
    return gz_dest


def encrypt_backup_file(file_path: Path) -> Path:
    """Cifra un backup antes de cualquier salida del runner (fail closed)."""
    import os

    passphrase = os.environ.get("BACKUP_ENCRYPTION_KEY", "")
    if not passphrase:
        raise RuntimeError("BACKUP_ENCRYPTION_KEY is required; refusing plaintext backup")
    encrypted = file_path.with_suffix(file_path.suffix + ".gpg")
    gpg_bin = shutil.which("gpg")
    if not gpg_bin:
        raise RuntimeError("gpg is required to encrypt backups")
    subprocess.run(
        [
            gpg_bin,
            "--batch",
            "--yes",
            "--pinentry-mode",
            "loopback",
            "--passphrase-fd",
            "0",
            "--symmetric",
            "--cipher-algo",
            "AES256",
            "--output",
            str(encrypted),
            str(file_path),
        ],
        check=True,
        input=passphrase.encode(),
    )
    file_path.unlink()
    return encrypted


def upload_to_s3(file_path: Path) -> bool:
    """Sube ``file_path`` a S3/R2.

    Requiere las variables de entorno BACKUP_S3_BUCKET y credenciales AWS.
    AWS_ENDPOINT_URL se puede usar para apuntar a Cloudflare R2.

    Returns:
        True si el upload fue exitoso, False en caso contrario.
    """
    import os

    bucket = os.environ.get("BACKUP_S3_BUCKET", "")
    if not bucket:
        print("[backup] BACKUP_S3_BUCKET no configurado — omitiendo upload S3.", file=sys.stderr)
        return False

    prefix = os.environ.get("BACKUP_S3_PREFIX", "backups/")
    key = f"{prefix.rstrip('/')}/{file_path.name}"

    try:
        import boto3  # type: ignore[import]
    except ImportError:
        print(
            "[backup] boto3 no instalado. Instala con: pip install boto3",
            file=sys.stderr,
        )
        return False

    kwargs: dict[str, str] = {}
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "")
    if endpoint:
        kwargs["endpoint_url"] = endpoint

    try:
        s3 = boto3.client("s3", **kwargs)
        s3.upload_file(str(file_path), bucket, key)
        size_kb = file_path.stat().st_size // 1024
        print(f"[backup] Upload S3 → s3://{bucket}/{key} ({size_kb} KB)")
        return True
    except Exception as exc:
        print(f"[backup] ERROR upload S3: {exc}", file=sys.stderr)
        return False


def prune_s3_backups(keep: int, prefix: str = "backups/") -> int:
    """Elimina backups S3/R2 más allá de los últimos ``keep``.

    Ordena por LastModified y borra los más antiguos.

    Returns:
        Número de objetos borrados.
    """
    import os

    bucket = os.environ.get("BACKUP_S3_BUCKET", "")
    if not bucket:
        return 0

    try:
        import boto3  # type: ignore[import]
    except ImportError:
        return 0

    kwargs: dict[str, str] = {}
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "")
    if endpoint:
        kwargs["endpoint_url"] = endpoint

    try:
        s3 = boto3.client("s3", **kwargs)
        paginator = s3.get_paginator("list_objects_v2")
        objects = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            objects.extend(page.get("Contents", []))

        # Ordenar por fecha ascendente; eliminar los que sobran
        objects.sort(key=lambda o: o["LastModified"])
        to_delete = objects[: max(0, len(objects) - keep)]
        for obj in to_delete:
            s3.delete_object(Bucket=bucket, Key=obj["Key"])
            print(f"[backup] S3 eliminado: {obj['Key']}")
        return len(to_delete)
    except Exception as exc:
        print(f"[backup] ERROR pruning S3: {exc}", file=sys.stderr)
        return 0


def upload_to_azure(file_path: Path) -> bool:
    """Sube un archivo a Azure Blob Storage (D6).

    Requiere ``azure-storage-blob`` y ``AZURE_STORAGE_CONNECTION_STRING`` en el
    entorno. Devuelve ``False`` si falta configuración o falla el upload.
    """
    import os

    container = os.environ.get("BACKUP_AZURE_CONTAINER")
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not container or not conn_str:
        print(
            "[backup] BACKUP_AZURE_CONTAINER / AZURE_STORAGE_CONNECTION_STRING "
            "no configurados — saltando upload a Azure.",
            file=sys.stderr,
        )
        return False

    try:
        from azure.storage.blob import BlobServiceClient  # type: ignore[import-not-found]
    except ImportError:
        print(
            "[backup] azure-storage-blob no instalado. Instala con: pip install azure-storage-blob",
            file=sys.stderr,
        )
        return False

    prefix = os.environ.get("BACKUP_AZURE_PREFIX", "backups/").rstrip("/") + "/"
    blob_name = f"{prefix}{file_path.name}"
    try:
        svc = BlobServiceClient.from_connection_string(conn_str)
        client = svc.get_blob_client(container=container, blob=blob_name)
        with open(file_path, "rb") as f:
            client.upload_blob(f, overwrite=True)
        print(f"[backup] Subido a azure://{container}/{blob_name}")
        return True
    except Exception as exc:
        print(f"[backup] ERROR upload Azure: {exc}", file=sys.stderr)
        return False


def prune_old_backups(backup_dir: Path, keep: int) -> int:
    """Elimina los backups más antiguos, manteniendo los últimos ``keep``."""
    backups = sorted(backup_dir.glob("*.db.gz.gpg"), key=lambda p: p.stat().st_mtime)
    to_delete = backups[: max(0, len(backups) - keep)]
    for f in to_delete:
        f.unlink()
        print(f"[backup] Eliminado backup antiguo: {f.name}")
    return len(to_delete)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup de la base de datos")
    parser.add_argument(
        "--keep", type=int, default=7, help="Número de backups a retener localmente (default: 7)"
    )
    parser.add_argument(
        "--keep-s3", type=int, default=30, help="Número de backups a retener en S3/R2 (default: 30)"
    )
    parser.add_argument(
        "--s3", action="store_true", help="Subir backups a S3/R2 después de crearlos"
    )
    parser.add_argument(
        "--azure", action="store_true", help="Subir backups a Azure Blob Storage (D6)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Solo mostrar qué se haría, sin ejecutar"
    )
    args = parser.parse_args()

    # Importar settings para obtener rutas
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config import settings

    backup_dir = settings.DATA_DIR / "backups"
    db_path = settings.DB_PATH or (settings.DATA_DIR / "licitaciones.db")

    if args.dry_run:
        print(f"[dry-run] Backup SQLite: {db_path} → {backup_dir}")
        if args.s3:
            import os

            bucket = os.environ.get("BACKUP_S3_BUCKET", "(no configurado)")
            print(f"[dry-run] Upload S3/R2: bucket={bucket}, keep-s3={args.keep_s3}")
        print(f"[dry-run] Retener últimos {args.keep} backups locales")
        return 0

    errors = 0
    uploaded: list[Path] = []

    if db_path and db_path.exists():
        try:
            gz = backup_sqlite(db_path, backup_dir)
            uploaded.append(gz)
        except Exception as exc:
            print(f"[backup] ERROR backup SQLite: {exc}", file=sys.stderr)
            errors += 1
    else:
        print(f"[backup] SQLite no encontrada en {db_path}", file=sys.stderr)

    encrypted_backups: list[Path] = []
    for f in uploaded:
        try:
            encrypted_backups.append(encrypt_backup_file(f))
        except Exception as exc:
            print(f"[backup] ERROR encrypting backup: {exc}", file=sys.stderr)
            f.unlink(missing_ok=True)
            errors += 1
    uploaded = encrypted_backups

    if args.s3:
        s3_prefix = __import__("os").environ.get("BACKUP_S3_PREFIX", "backups/")
        for encrypted in uploaded:
            if not upload_to_s3(encrypted):
                errors += 1
        pruned_s3 = prune_s3_backups(args.keep_s3, prefix=s3_prefix)
        if pruned_s3:
            print(f"[backup] {pruned_s3} backup(s) S3 antiguos eliminados.")

    if args.azure:
        for encrypted in uploaded:
            if not upload_to_azure(encrypted):
                errors += 1

    pruned = prune_old_backups(backup_dir, args.keep)
    if pruned:
        print(f"[backup] {pruned} backup(s) locales antiguos eliminados.")

    return errors


if __name__ == "__main__":
    raise SystemExit(main())
