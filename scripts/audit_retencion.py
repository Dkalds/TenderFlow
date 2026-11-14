"""Auditoría manual del emparejamiento vencimiento→sucesor (paso 5 del RFC).

Imprime una muestra determinista de pares para revisión humana ANTES de
entrenar el modelo de retención. Acceptance: precisión del emparejamiento
≥90% sobre 50 pares (anotar el resultado en las notas del RFC).

Con ``--resueltos`` audita en su lugar los vencimientos que el scoring da por
resueltos (``resueltos_detectados``): contratos que vencen dentro de
``--meses`` con una sucesora ya adjudicada según la misma heurística. Es lo
que falta revisar antes de encender ``ML_RETENCION_EXCLUIR_RESUELTOS``.

Uso: python scripts/audit_retencion.py [--n 50] [--resueltos [--meses 60]]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument(
        "--resueltos",
        action="store_true",
        help="vencimientos de la población de scoring con sucesora ya adjudicada",
    )
    parser.add_argument(
        "--meses",
        type=int,
        default=None,
        help="horizonte de vencimientos con --resueltos (por defecto, el del batch)",
    )
    args = parser.parse_args()

    from db.database import init_db
    from services.ml.retencion_labels import muestra_auditoria, muestra_resueltos

    init_db()
    if args.resueltos:
        muestra = (
            muestra_resueltos(args.n, months_ahead=args.meses)
            if args.meses is not None
            else muestra_resueltos(args.n)
        )
        if not muestra:
            print("Sin vencimientos resueltos en el horizonte.")
            return 1
        print(f"== {len(muestra)} vencimientos dados por resueltos (¿la sucesora es de")
        print("   verdad la renovación de este contrato, o un contrato paralelo del")
        print("   mismo órgano y CPV-4?) ==\n")
    else:
        muestra = muestra_auditoria(args.n)
        if not muestra:
            print("Sin pares vencimiento→sucesor. ¿Hay contratos vencidos con empresa del maestro?")
            return 1
        print(f"== {len(muestra)} pares para auditar (¿el sucesor es realmente el contrato")
        print("   análogo siguiente? ¿el label retenido/perdido es correcto?) ==\n")

    for i, p in enumerate(muestra, 1):
        etiqueta = "RETUVO" if p["label"] == 1 else "PERDIÓ"
        # Solo la muestra de resueltos trae pares con la ventana aún abierta.
        abierta = "" if p.get("ventana_cerrada", True) else " (ventana abierta)"
        print(
            f"[{i:02d}] {etiqueta} — fin {p['fecha_fin']} → sucesor {p['fecha_sucesor']}{abierta}"
        )
        print(f"     {p['original']}: {(p['titulo_original'] or '')[:90]}")
        print(f"       incumbente: {p['empresa_original']}")
        print(f"     {p['sucesor']}: {(p['titulo_sucesor'] or '')[:90]}")
        print(f"       ganador:    {p['empresa_sucesora']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
