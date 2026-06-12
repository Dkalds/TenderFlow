"""Auditoría manual del emparejamiento vencimiento→sucesor (paso 5 del RFC).

Imprime una muestra determinista de pares para revisión humana ANTES de
entrenar el modelo de retención. Acceptance: precisión del emparejamiento
≥90% sobre 50 pares (anotar el resultado en las notas del RFC).

Uso: python scripts/audit_retencion.py [--n 50]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=50)
    args = parser.parse_args()

    from db.database import init_db
    from services.ml.retencion_labels import muestra_auditoria

    init_db()
    muestra = muestra_auditoria(args.n)
    if not muestra:
        print("Sin pares vencimiento→sucesor. ¿Hay contratos vencidos con empresa del maestro?")
        return 1

    print(f"== {len(muestra)} pares para auditar (¿el sucesor es realmente el contrato")
    print("   análogo siguiente? ¿el label retenido/perdido es correcto?) ==\n")
    for i, p in enumerate(muestra, 1):
        etiqueta = "RETUVO" if p["label"] == 1 else "PERDIÓ"
        print(f"[{i:02d}] {etiqueta} — fin {p['fecha_fin']} → sucesor {p['fecha_sucesor']}")
        print(f"     {p['original']}: {(p['titulo_original'] or '')[:90]}")
        print(f"       incumbente: {p['empresa_original']}")
        print(f"     {p['sucesor']}: {(p['titulo_sucesor'] or '')[:90]}")
        print(f"       ganador:    {p['empresa_sucesora']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
