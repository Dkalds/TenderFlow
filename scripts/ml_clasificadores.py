"""CLI de entrenamiento y precómputo de los clasificadores SAP y de tecnología.

Vivía bajo el ``if __name__ == "__main__"`` de ``services/ml/sap_classifier.py``:
un módulo de dominio que escribía por ``stdout`` y que, para la siembra de
negativos, importaba del paquete de ingesta. Es un programa, y los programas
viven en ``scripts/``. ``python -m services.ml.sap_classifier <cmd>`` (y su
alias ``python -m scraper.ml_classifier``) siguen funcionando: delegan aquí.

La clase no se mueve: ``services.ml.sap_classifier.SAPClassifier`` es el
nombre cualificado que resuelven los ``.pkl`` publicados.

Uso::

    PYTHONPATH="$PWD" python scripts/ml_clasificadores.py train
    PYTHONPATH="$PWD" python scripts/ml_clasificadores.py seed-negatives --year 2026 --month 9
    PYTHONPATH="$PWD" python scripts/ml_clasificadores.py precompute [--force]
    PYTHONPATH="$PWD" python scripts/ml_clasificadores.py info
    PYTHONPATH="$PWD" python scripts/ml_clasificadores.py train-tech
    PYTHONPATH="$PWD" python scripts/ml_clasificadores.py precompute-tech [--force]

Sin comando, ``train``. Un comando desconocido sale con 1.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

#: Cómo se invoca, para los mensajes que dicen qué ejecutar después.
PROGRAMA = "python scripts/ml_clasificadores.py"

COMANDOS = ("train", "seed-negatives", "precompute", "info", "train-tech", "precompute-tech")


# ── Formateo (puro: lo que se imprime sale de aquí) ──────────────────────────


def lineas_entrenamiento_sap(
    result: Mapping[str, Any], *, min_muestras: int, ruta_modelo: Path
) -> list[str]:
    """El informe de ``train`` a partir de lo que devuelve ``train_from_db``.

    ``train_from_db`` no activa nada (2026-10): el candidato que pasa el gate
    queda registrado e inactivo, con su artefacto por contenido escrito en
    local. El informe lo dice y da el camino para servirlo —el workflow que lo
    publica y lo activa—, en vez del «Modelo guardado» de antes, que hacía
    creer que ya se servía.
    """
    if "error" not in result:
        promocion = result.get("promotion") or {}
        metricas = [f"  {k}: {v}" for k, v in result.items() if k != "promotion"]
        if promocion.get("pendiente_de_activar"):
            return [
                *metricas,
                "",
                f"Versión {promocion.get('version')} registrada SIN activar; "
                f"artefacto en: {promocion.get('artefacto') or ruta_modelo}",
                "Para servirla hay que publicarla y activarla, en ese orden: "
                "gh workflow run train-model.yml",
            ]
        motivos = "; ".join(str(m) for m in promocion.get("motivos_rechazo") or [])
        return [
            *metricas,
            "",
            f"[AVISO] El gate rechazó la versión {promocion.get('version')}: "
            f"{motivos or 'sin motivo registrado'}. No se publica nada.",
        ]
    error = result["error"]
    if error == "single_class":
        return [
            "",
            "[AVISO] Entrenamiento no posible: todos los ejemplos son SAP (clase única).",
            f"  n_positive={result.get('n_positive', 0)}, n_negative={result.get('n_negative', 0)}",
            "  El clasificador ML necesita licitaciones sin keywords SAP con CPV fuera de 48xxx/72xxx.",
            f"  Solución: ejecuta primero: {PROGRAMA} seed-negatives",
        ]
    if error == "insufficient_data":
        return [
            "",
            f"[AVISO] Datos insuficientes: {result.get('n_samples', 0)} muestras "
            f"(mínimo {min_muestras}).",
        ]
    return ["", f"[ERROR] {dict(result)}"]


def lineas_siembra(result: Mapping[str, Any]) -> list[str]:
    return [
        f"  Descargadas : {result['downloaded']}",
        f"  Insertadas  : {result['inserted']}",
        f"  Omitidas TI : {result['skipped_ti']}",
        f"  Ya existían : {result['already_exists']}",
        "",
        f"Ahora puedes entrenar: {PROGRAMA} train",
    ]


def _cifra(valor: object) -> str:
    return f"{valor:.3f}" if isinstance(valor, float) else "—"


def lineas_entrenamiento_tech(metricas: Mapping[str, Any], *, ruta_modelo: Path) -> list[str]:
    """El informe de ``train-tech``.

    ``macro_f1_ml_ready_only`` promedia SOLO las etiquetas con suficientes
    positivos: es un promedio de los aprobados; las dos de al lado cubren las
    13 tecnologías. ``labels circulares`` es el dato que decide si significan
    algo: si las etiquetas salen del regex de keywords, miden imitación, no
    detección.
    """
    if "error" in metricas:
        return ["", f"[ERROR] {dict(metricas)}"]
    lineas = [
        f"  micro_f1 (todas)  : {metricas.get('micro_f1_all_labels')}",
        f"  macro_f1 (todas)  : {metricas.get('macro_f1_all_labels')}",
        f"  macro_f1 ml_ready : {metricas.get('macro_f1_ml_ready_only')}",
        f"  labels circulares : {metricas.get('labels_circulares')}",
        f"  n_models          : {metricas.get('n_models')}",
        f"  n_rules_fallback  : {metricas.get('n_rules_fallback')}",
        f"  n_train/val/test  : {metricas.get('n_train')} / "
        f"{metricas.get('n_val')} / {metricas.get('n_test')}",
        "",
        "Desglose por tecnología:",
    ]
    for label, info in (metricas.get("per_tech") or {}).items():
        lineas.append(
            f"  - {label:<12} tier={info.get('tier')!s:<9} n+={info.get('n_positive')!s:<5} "
            f"thr={info.get('threshold')!s:<5} F1={_cifra(info.get('f1'))} "
            f"P={_cifra(info.get('precision'))} R={_cifra(info.get('recall'))}"
        )
    lineas += ["", f"Modelo guardado en: {ruta_modelo}"]
    return lineas


# ── Comandos ─────────────────────────────────────────────────────────────────


def _con_force(prog: str, argv: Sequence[str]) -> bool:
    parser = argparse.ArgumentParser(prog=f"{PROGRAMA} {prog}")
    parser.add_argument(
        "--force", action="store_true", help="Recalcular incluso filas ya clasificadas"
    )
    return bool(parser.parse_args(list(argv)).force)


def _train(_: Sequence[str]) -> int:
    from services.ml.classifier_training import train_from_db
    from services.ml.sap_classifier import _MODEL_PATH, MIN_TRAIN_SAMPLES

    print("Entrenando clasificador SAP desde la BD...")
    result = train_from_db()
    print(
        "\n".join(
            lineas_entrenamiento_sap(
                result, min_muestras=MIN_TRAIN_SAMPLES, ruta_modelo=_MODEL_PATH
            )
        )
    )
    return 0


def _seed_negatives(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog=f"{PROGRAMA} seed-negatives")
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--month", type=int, default=None)
    parser.add_argument("--max", type=int, default=2000, dest="max_negatives")
    args = parser.parse_args(list(argv))
    from scraper.seed_negatives import seed_negatives

    print(
        f"Descargando negativos del bulk "
        f"{args.year or 'mes anterior'}/{args.month or ''}  (máx {args.max_negatives})..."
    )
    result = seed_negatives(year=args.year, month=args.month, max_negatives=args.max_negatives)
    print("\n".join(lineas_siembra(result)))
    return 0


def _precompute(argv: Sequence[str]) -> int:
    force = _con_force("precompute", argv)
    from services.ml.classifier_training import precompute_ml_proba

    print("Precomputando ml_proba para licitaciones pendientes...")
    result = precompute_ml_proba(force=force)
    print(f"  Actualizadas : {result.get('updated', 0)}")
    if result.get("skipped_no_model"):
        print("  [AVISO] No hay modelo disponible.")
    return 0


def _info(_: Sequence[str]) -> int:
    from services.ml.sap_classifier import _MODEL_PATH, SAPClassifier

    if SAPClassifier.is_available():
        print(f"Modelo disponible: {_MODEL_PATH}")
    else:
        print(f"No hay modelo entrenado. Ejecuta: {PROGRAMA} train")
    return 0


def _train_tech(_: Sequence[str]) -> int:
    from services.ml.tech_classifier import _MODEL_PATH, train_from_db

    print("Entrenando TechnologyClassifier multi-label desde la BD...")
    print("\n".join(lineas_entrenamiento_tech(train_from_db(), ruta_modelo=_MODEL_PATH)))
    return 0


def _precompute_tech(argv: Sequence[str]) -> int:
    force = _con_force("precompute-tech", argv)
    from services.ml.classifier_training import precompute_ml_tecnologias

    print("Precomputando ml_tecnologias/ml_proba_max para licitaciones pendientes...")
    result = precompute_ml_tecnologias(force=force)
    print(f"  Actualizadas      : {result.get('updated', 0)}")
    print(f"  Scores insertados : {result.get('scores_inserted', 0)}")
    if result.get("skipped_no_model"):
        print(
            "  [AVISO] No hay TechnologyClassifier entrenado. "
            f"Ejecuta primero: {PROGRAMA} train-tech"
        )
    return 0


_DESPACHO: dict[str, Callable[[Sequence[str]], int]] = {
    "train": _train,
    "seed-negatives": _seed_negatives,
    "precompute": _precompute,
    "info": _info,
    "train-tech": _train_tech,
    "precompute-tech": _precompute_tech,
}


def uso() -> str:
    return f"Uso: {PROGRAMA} [{' | '.join(COMANDOS)}] [opciones]\n\n{(__doc__ or '').strip()}"


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "train"
    if cmd in ("-h", "--help"):
        print(uso())
        return 0
    accion = _DESPACHO.get(cmd)
    if accion is None:
        print(f"Comando desconocido: {cmd}. Usa {', '.join(repr(c) for c in COMANDOS)}.")
        return 1
    return accion(args[1:])


if __name__ == "__main__":
    sys.exit(main())
