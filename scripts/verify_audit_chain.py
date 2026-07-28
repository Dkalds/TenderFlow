"""Verifica íntegramente la cadena de auditoría de la base de datos activa.

La comprobación delega en db.audit.verify_hash_chain: valida continuidad,
HMAC de cada registro moderno y la cabecera firmada (hash final y número de
filas). Esta última es la que hace detectables borrados al final de la cadena.

Verifica la BD a la que apunta ``DATABASE_URL``. Desde ADR-021 Postgres es el
único motor, así que ya no hay ``--db-path``: apuntá ``DATABASE_URL`` a la
instancia que quieras verificar.

Uso:
    DATABASE_URL=postgresql://... python scripts/verify_audit_chain.py

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


def verify_chain() -> int:
    """Verifica la BD activa sin modificarla y devuelve un código de salida."""
    from db.database import close_pool

    try:
        from db.audit import verify_hash_chain

        result = verify_hash_chain()
    except Exception as exc:  # BD inaccesible, tabla ausente, credenciales…
        print(f"[ERROR] No se pudo verificar la cadena: {exc}")
        return 2
    finally:
        close_pool()

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
        "--limit",
        type=int,
        default=None,
        help="Obsoleto: una verificación parcial no es segura.",
    )
    args = parser.parse_args()
    if args.limit is not None:
        print("[ERROR] --limit no es compatible con una verificación de integridad completa.")
        sys.exit(2)
    sys.exit(verify_chain())


if __name__ == "__main__":
    main()
