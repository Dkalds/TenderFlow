"""Verifica la integridad de la cadena de hashes en audit_log.

Recorre todas las filas de ``audit_log`` en orden de inserción (id ASC) y
comprueba que cada ``this_hash`` coincide con el hash esperado
(SHA-256 de ``prev_hash || row_json``). Imprime un informe y devuelve
código de salida 1 si detecta alguna rotura.

La verificación sólo aplica a filas que tienen las columnas ``prev_hash``
y ``this_hash`` (migración 26). Filas anteriores a esa migración se omiten
e informan como "sin cadena".

Uso:
    python scripts/verify_audit_chain.py
    python scripts/verify_audit_chain.py --db-path data/licitaciones.db
    python scripts/verify_audit_chain.py --limit 5000
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

_GENESIS = "genesis"


def _expected_hash(prev_hash: str, row: dict[str, Any]) -> str:
    """Reproduce el hash tal y como lo calcula db.audit.log_action."""
    row_json = json.dumps(row, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(f"{prev_hash}{row_json}".encode()).hexdigest()


def verify_chain(db_path: Path, limit: int | None = None) -> int:
    """Verifica la cadena de auditoría. Devuelve número de filas corruptas."""
    if not db_path.exists():
        print(f"[ERROR] Base de datos no encontrada: {db_path}")
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Detectar si la tabla tiene las columnas de hash chain
    cols = {row[1] for row in conn.execute("PRAGMA table_info(audit_log)")}
    if "prev_hash" not in cols or "this_hash" not in cols:
        print(
            "[INFO] La tabla audit_log no tiene columnas prev_hash/this_hash.\n"
            "       Ejecuta las migraciones (alembic upgrade head) para habilitar "
            "la cadena de hashes."
        )
        conn.close()
        return 0

    query = (
        "SELECT id, user_key, session_hash, action, detail, created_at, "
        "prev_hash, this_hash FROM audit_log ORDER BY id ASC"
    )
    if limit:
        query += f" LIMIT {limit}"

    rows = conn.execute(query).fetchall()
    conn.close()

    if not rows:
        print("[INFO] audit_log vacío — nada que verificar.")
        return 0

    errors: list[str] = []
    expected_prev = _GENESIS
    skipped = 0

    for row in rows:
        stored_prev = row["prev_hash"]
        stored_this = row["this_hash"]

        if stored_prev is None or stored_this is None:
            skipped += 1
            continue

        # Verificar continuidad del prev_hash
        if stored_prev != expected_prev:
            errors.append(
                f"  Fila id={row['id']}: prev_hash esperado={expected_prev!r}, "
                f"almacenado={stored_prev!r}"
            )

        # Recalcular this_hash a partir del contenido de la fila
        row_data = {
            "user_key": row["user_key"],
            "session_hash": row["session_hash"],
            "action": row["action"],
            "detail": row["detail"],
            "created_at": row["created_at"],
        }
        expected_this = _expected_hash(stored_prev, row_data)
        if stored_this != expected_this:
            errors.append(
                f"  Fila id={row['id']} (acción={row['action']!r}): "
                f"this_hash no coincide → posible manipulación"
            )

        expected_prev = stored_this  # avanzar cadena

    total = len(rows)
    chain_rows = total - skipped

    print("\n─── Verificación de cadena de auditoría ───────────────────────")
    print(f"  Total filas     : {total}")
    print(f"  Con hash chain  : {chain_rows}")
    print(f"  Sin hash chain  : {skipped}  (migraciones anteriores — OK)")
    print(f"  Errores         : {len(errors)}")

    if errors:
        print("\n[FAIL] Se detectaron filas con hash incorrecto:")
        for msg in errors:
            print(msg)
        print(
            "\n⚠  Esto puede indicar manipulación directa de la base de datos "
            "o un bug en la lógica de log_action."
        )
        return len(errors)

    print("\n[OK] La cadena de hashes es íntegra.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path("data/licitaciones.db"),
        help="Ruta a la base de datos SQLite (default: data/licitaciones.db)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Número máximo de filas a verificar (default: todas)",
    )
    args = parser.parse_args()
    sys.exit(verify_chain(args.db_path, args.limit))


if __name__ == "__main__":
    main()
