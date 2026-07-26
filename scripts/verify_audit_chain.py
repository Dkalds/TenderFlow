"""Verifica íntegramente la cadena de auditoría de una base SQLite.

La comprobación delega en db.audit.verify_hash_chain: valida continuidad,
HMAC de cada registro moderno y la cabecera firmada (hash final y número de
filas). Esta última es la que hace detectables borrados al final de la cadena.

Uso:
    python scripts/verify_audit_chain.py
    python scripts/verify_audit_chain.py --db-path data/licitaciones.db

No admite verificaciones parciales: omitir filas invalidaría la comprobación
de continuidad y de la cabecera firmada.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def verify_chain(db_path: Path) -> int:
    """Verifica una base SQLite sin modificarla y devuelve un código de salida."""
    if not db_path.is_file():
        print(f"[ERROR] Base de datos no encontrada: {db_path}")
        return 2

    from db.database import close_pool, set_db_path_override

    # El override fuerza SQLite incluso si el entorno de quien ejecuta el
    # runbook contiene un DATABASE_URL de producción.
    close_pool()
    set_db_path_override(str(db_path.resolve()))
    try:
        from db.audit import verify_hash_chain

        result = verify_hash_chain()
    finally:
        close_pool()
        set_db_path_override(None)

    valid = result.get("valid")
    checked = int(result.get("checked") or 0)
    error = result.get("error")

    print()
    print("─── Verificación de cadena de auditoría ───────────────────────")
    print(f"  Filas con hash verificadas: {checked}")

    if valid is True:
        print("  Estado: ÍNTEGRA")
        return 0
    if valid is False:
        print("  Estado: MANIPULACIÓN O INCONSISTENCIA DETECTADA")
        if error:
            print(f"  Detalle: {error}")
        return 1

    print("  Estado: NO VERIFICABLE")
    if error:
        print(f"  Detalle: {error}")
    return 2


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
        help="Obsoleto: una verificación parcial no es segura.",
    )
    args = parser.parse_args()
    if args.limit is not None:
        print("[ERROR] --limit no es compatible con una verificación de integridad completa.")
        sys.exit(2)
    sys.exit(verify_chain(args.db_path))


if __name__ == "__main__":
    main()
