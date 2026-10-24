"""Compara los candidatos del modelo de nivel 1 («¿es TI?») contra sus baselines.

Plan de clasificación en tres niveles, F3 (§4). Entrena A (TF-IDF + LR), B
(embeddings + LR) y A+B con las etiquetas que no salen de las reglas, elige
las dos bandas en el ``tune`` del golden humano y decide en su ``holdout``:
el elegido tiene que batir a «solo keywords» y a «solo CPV 48/72», y se mide
aparte en «CPV 48/72 sin keyword».

Qué hace
--------
1. Carga el golden (``tests/fixtures/golden_ti.jsonl``) y lo parte por su
   ``split``. Sin holdout no hay nada que decidir: lo dice y sale.
2. Mide el acuerdo del LLM con el golden (spec §3.5,
   ``services.ml.acuerdo_llm``). Solo si es APTO entran sus etiquetas.
3. Lee las filas etiquetadas de la población puntuada (solo lectura,
   ``db.repositories.ml_dataset.filas_etiquetadas_nivel1``) y deja fuera el
   golden entero, por id y por convocatoria.
4. Entrena, calibra, fija bandas y evalúa (``services.ml.nivel1``).
5. Imprime el informe y lo escribe en JSON (``--informe``).

Qué NO hace
-----------
- No registra en ``model_versions``, no activa, no publica artefactos ni
  reescribe ``ml_proba``. Con ``--guardar-modelos DIR`` deja los modelos en un
  directorio local, y nada más: registrar y pasar la semana en sombra es el
  paso siguiente, con OK del propietario.
- No fuerza las etiquetas del LLM: si el acuerdo no llega, no entrenan.

Uso::

    ENV=prod PYTHONPATH="$PWD" python scripts/entrenar_nivel1.py
    ENV=prod PYTHONPATH="$PWD" python scripts/entrenar_nivel1.py --solo A \\
        --informe /tmp/nivel1.json --guardar-modelos /tmp/nivel1

Siempre sale con 0 salvo error de uso: es un informe, no un gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from observability.logging import get_logger  # noqa: E402

log = get_logger(__name__)

INFORME_POR_DEFECTO = Path("data/nivel1/informe.json")


def tiene_keyword_por_reglas(titulo: str | None, cpv: str | None) -> bool:
    """El baseline «solo keywords»: la puerta de reglas vigente admite el
    anuncio por keyword (no solo por CPV). Es la misma función que decide en
    PSCP, PLACSP y la purga."""
    from scraper.puerta_tecnologica import MOTIVO_ADMITIDA, senal_tecnologica

    return senal_tecnologica(titulo, cpv).motivo == MOTIVO_ADMITIDA


def ejecutar(
    golden: Sequence[Any],  # EjemploGoldenTi
    filas: Sequence[Mapping[str, Any]],
    respuestas_llm: Mapping[str, Any],  # id -> RespuestaLlm
    *,
    candidatos: Sequence[str],
    n_bootstrap: int,
    tiene_keyword: Callable[[str | None, str | None], bool] = tiene_keyword_por_reglas,
    min_df: int = 2,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Todo lo que no es E/S. Devuelve ``(informe, modelos)``."""
    from services.ml.acuerdo_llm import medir_acuerdo
    from services.ml.nivel1 import comparar_candidatos, dataset_entrenamiento, fila_desde_golden

    tune = [
        fila_desde_golden(e, tiene_keyword=tiene_keyword(e.titulo, e.cpv))
        for e in golden
        if e.split == "tune"
    ]
    holdout = [
        fila_desde_golden(e, tiene_keyword=tiene_keyword(e.titulo, e.cpv))
        for e in golden
        if e.split == "holdout"
    ]
    acuerdo = medir_acuerdo(list(golden), dict(respuestas_llm))
    entrenamiento, resumen = dataset_entrenamiento(filas, golden, usar_llm=acuerdo.apto)

    informe: dict[str, Any] = {
        "golden": {"n": len(golden), "tune": len(tune), "holdout": len(holdout)},
        "acuerdo_llm": {
            "n_comparables": acuerdo.n_comparables,
            "acuerdo_es_ti": acuerdo.acuerdo_es_ti,
            "apto": acuerdo.apto,
            "motivos": list(acuerdo.motivos),
        },
        "dataset": resumen.as_dict(),
    }
    if not holdout:
        informe["veredicto"] = "SIN HOLDOUT: el golden no tiene ejemplos para decidir"
        return informe, {}

    resultado = comparar_candidatos(
        entrenamiento, tune, holdout, candidatos=candidatos, n_bootstrap=n_bootstrap, min_df=min_df
    )
    informe["evaluacion"] = resultado.informe.as_dict()
    informe["modelos"] = {n: m.metadata for n, m in resultado.modelos.items()}
    informe["veredicto"] = "APTO" if resultado.informe.apto else "NO APTO"
    return informe, dict(resultado.modelos)


def _imprimir(informe: Mapping[str, Any]) -> None:
    golden = informe["golden"]
    print(f"Golden: n={golden['n']} · tune={golden['tune']} · holdout={golden['holdout']}")
    acuerdo = informe["acuerdo_llm"]
    print(
        f"Acuerdo LLM: comparables={acuerdo['n_comparables']} "
        f"es_ti={acuerdo['acuerdo_es_ti']} → {'APTO' if acuerdo['apto'] else 'NO APTO'}"
    )
    dataset = informe["dataset"]
    print(
        f"Entrenamiento: {dataset['n_etiquetadas']} filas ({dataset['n_humanas']} humanas, "
        f"{dataset['n_llm']} LLM, {dataset['pct_positivos']} % TI); fuera por golden: "
        f"{dataset['excluidas_por_id_del_golden']} por id, "
        f"{dataset['excluidas_por_convocatoria_del_golden']} por convocatoria"
    )
    evaluacion = informe.get("evaluacion")
    if evaluacion:
        for nombre, ap in evaluacion["pr_auc"].items():
            print(
                f"  PR-AUC {nombre}: {ap['valor']:.3f} [{ap['ic_bajo']:.3f}, {ap['ic_alto']:.3f}]"
            )
        for nombre, motivo in evaluacion["sin_evaluar"].items():
            print(f"  {nombre} sin evaluar: {motivo}")
        print(f"Elección: {evaluacion['eleccion']}")
        for motivo in evaluacion["motivos"]:
            print(f"  - {motivo}")
    print(f"Veredicto: {informe['veredicto']}")


def main(argv: list[str] | None = None) -> int:
    from services.ml.nivel1_eval import N_BOOTSTRAP, ORDEN_SIMPLICIDAD

    parser = argparse.ArgumentParser(description="Modelo de nivel 1 (¿es TI?): comparar candidatos")
    parser.add_argument(
        "--golden", type=Path, default=None, help="JSONL del golden (por defecto el del repo)"
    )
    parser.add_argument(
        "--solo",
        choices=ORDEN_SIMPLICIDAD,
        action="append",
        help="Candidato a entrenar (repetible)",
    )
    parser.add_argument(
        "--bootstrap", type=int, default=N_BOOTSTRAP, help="Remuestreos del bootstrap"
    )
    parser.add_argument(
        "--informe", type=Path, default=INFORME_POR_DEFECTO, help="Dónde escribir el JSON"
    )
    parser.add_argument(
        "--guardar-modelos", type=Path, default=None, help="Directorio local para los modelos"
    )
    args = parser.parse_args(argv)

    from db.database import init_db
    from db.repositories.ml_dataset import filas_etiquetadas_nivel1
    from db.repositories.tecnologia_pliego import TecnologiaPliegoRepository
    from services.ml.acuerdo_llm import RespuestaLlm
    from services.ml.golden_ti import cargar_golden_ti

    init_db()
    golden = cargar_golden_ti(args.golden)
    vigentes = TecnologiaPliegoRepository().respuestas_llm_vigentes([e.id_externo for e in golden])
    respuestas = {
        id_: RespuestaLlm(es_ti=v["es_ti"], familias=frozenset(v["familias"]))
        for id_, v in vigentes.items()
    }
    filas = filas_etiquetadas_nivel1() if golden else []
    informe, modelos = ejecutar(
        golden,
        filas,
        respuestas,
        candidatos=tuple(args.solo or ORDEN_SIMPLICIDAD),
        n_bootstrap=args.bootstrap,
    )
    _imprimir(informe)

    args.informe.parent.mkdir(parents=True, exist_ok=True)
    args.informe.write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Informe: {args.informe}")
    if args.guardar_modelos is not None and modelos:
        import joblib

        args.guardar_modelos.mkdir(parents=True, exist_ok=True)
        for nombre, modelo in modelos.items():
            ruta = args.guardar_modelos / f"nivel1_{nombre.replace('+', '_')}.joblib"
            joblib.dump(modelo, ruta)
            print(f"Modelo {nombre}: {ruta} (local; no registrado)")
    log.info("entrenar_nivel1.done", veredicto=informe["veredicto"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
