"""Entrenamiento del clasificador SAP — entrypoint del workflow de release.

Invocado por ``.github/workflows/train-model.yml`` en dos pasos, con la subida
a la Release en medio:

1. ``python -m scheduler.jobs.ml_training_run`` — seed de negativos →
   entrenamiento → gate. El candidato que pasa el gate queda **registrado sin
   activar**.
2. *(el workflow sube el artefacto con ``gh release upload``)*
3. ``python -m scheduler.jobs.ml_training_run activar --version N`` — comprueba
   que la Release publica el sha256 registrado, activa la versión y recalcula
   ``ml_proba``.

Hasta 2026-10 el paso 1 activaba la versión y la subida iba después: un fallo
en medio —el ``precompute`` forzado, que recorre toda la población, vivía
ahí— dejaba activa una versión cuyo artefacto no estaba publicado, y todos los
procesos caían por ``ModelArtifactMismatch``.

``python -m scheduler.jobs.ml_training_run rescore`` es el tercer subcomando,
el de ``rescore-ml-proba.yml``: recalcula ``ml_proba`` con el modelo que se
sirve, sin entrenar nada.

Vivía como heredoc ``python -c`` dentro del YAML, fuera del alcance de ruff,
mypy y los tests; aquí queda como código normal.

El clasificador **multi-tecnología** tiene su propio entrypoint desde #263:
``scheduler/jobs/tech_training_run.py``, invocado por ``train-tech.yml``. Este
módulo llegó a tener un subcomando ``tech`` que hacía lo mismo; se retiró al
fusionar, porque el de allí aplica un gate de etiquetas circulares más estricto
—un suelo absoluto de etiquetas independientes— y tener dos caminos para
publicar el mismo artefacto es cómo se acaba publicando el peor de los dos.

No se registra en ``build_default_registry()``: el re-entrenamiento del
clasificador SAP es un job de release con artefacto versionado, distinto del
``ml_retrain_baja`` periódico de ``scheduler/jobs/ml_predicciones.py``.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from observability.logging import get_logger

if TYPE_CHECKING:
    from shared.model_artifacts import ArtefactoPublicado

log = get_logger(__name__)

_MODELO = "sap_classifier"

# Cuántas veces se lee la Release antes de dar por no publicado el artefacto,
# y cuánto se espera entre lecturas. La subida acaba de terminar: lo normal es
# que la primera lectura ya lo traiga, y los reintentos solo cubren un fallo
# pasajero de la API. Rendirse deja el modelo sin versión activa hasta que
# alguien relance el paso, así que compensa insistir medio minuto.
_INTENTOS_VERIFICACION = 3
_ESPERA_VERIFICACION_SEGUNDOS = 10.0


def run() -> dict[str, Any]:
    """Siembra negativos y entrena desde BD. No activa ni recalcula ``ml_proba``.

    Si el candidato pasa el gate queda registrado sin activar, con su artefacto
    en ``data/models/sap_classifier.pkl`` listo para subir, y **el modelo se
    queda sin versión activa** hasta :func:`activar_publicada`. Es deliberado:
    el asset se publica con nombre fijo, así que la subida va a sustituir el
    de la versión que estuviera activa. Retirarla antes hace que ningún estado
    intermedio —ni un fallo a mitad— deje una versión activa cuyo sha256 no es
    el del asset publicado; sin versión activa los consumidores sirven el
    asset de nombre fijo, el que haya en cada momento.

    Returns:
        Las métricas devueltas por ``train_from_db``.

    Raises:
        RuntimeError: Si el entrenamiento devuelve un dict con ``error``.
    """
    from scraper.seed_negatives import seed_negatives
    from services.ml.classifier_training import train_from_db

    # ``include_ti=True``: en serving el modelo SOLO puntúa licitaciones con
    # CPV 48/72 (``scraper.pipeline._ml_classify_entry`` descarta el resto
    # antes de parsear). Sembrando solo negativos no-TI, el separador más
    # fuerte que aprendía era el propio CPV — constante en el punto donde de
    # verdad decide. Los hard negatives TI son los que enseñan a distinguir
    # SAP de otro proveedor de TI.
    # ``spread_months=6``: con un solo mes, los negativos comparten ventana
    # temporal y vocabulario, otro atajo que el modelo aprende en vez de la
    # señal. Es exactamente lo que el docstring de
    # ``_collect_negatives_from_month`` dice querer evitar.
    seed_negatives(include_ti=True, spread_months=6)
    metrics = train_from_db(activar=False)
    log.info("ml_training_metrics", **{k: v for k, v in metrics.items() if k != "error"})

    if "error" in metrics:
        raise RuntimeError(f"Training failed: {metrics['error']}")

    if promocionado(metrics):
        from db.model_registry import deactivate

        retiradas = deactivate(_MODELO)
        log.info(
            "ml_training_version_activa_retirada",
            modelo=_MODELO,
            retiradas=retiradas,
            pendiente=(metrics.get("promotion") or {}).get("version"),
        )
    return metrics


def promocionado(metrics: dict[str, Any]) -> bool:
    """¿Pasó el gate de promoción y hay artefacto nuevo que publicar?

    ``train_from_db`` delega en ``services.ml.promotion.promote_if_better``,
    que **solo** escribe ``data/models/sap_classifier.pkl`` —el asset de la
    Release que descargan la API y los runners— si el candidato supera el
    gate. Un rechazo no es un error: es el mecanismo funcionando.

    Cuenta tanto el candidato ya activado como el que espera a que su
    artefacto se publique (``pendiente_de_activar``, que es lo que devuelve
    :func:`run`): en los dos hay fichero que subir.
    """
    promocion = metrics.get("promotion") or {}
    return bool(promocion.get("activada") or promocion.get("pendiente_de_activar"))


def activar_publicada(
    version: int, *, sleep: Callable[[float], None] = time.sleep
) -> dict[str, Any]:
    """Activa ``version`` si la Release publica su artefacto, y recalcula ``ml_proba``.

    El orden es la garantía: primero se lee de la API de Releases el sha256
    del asset que bajaría cualquier otro proceso, se compara con el registrado
    en ``model_versions``, y solo si coinciden se activa. Una versión no puede
    quedar activa sin un artefacto publicado que la respalde.

    El ``precompute`` forzado va después de activar y no antes: resuelve el
    modelo por la versión activa, y si el modelo cambió hay que reescribir
    todos los ``ml_proba`` —con ``force=False`` solo se rellenarían los NULL, y
    la superficie de serving y el test de drift de predicciones seguirían
    mostrando los scores del modelo anterior—.

    Args:
        version: La que emitió :func:`run` por ``$GITHUB_OUTPUT``.
        sleep: Inyectable para los tests.

    Returns:
        ``{"version", "sha256", "release", "ml_proba": <resultado del precompute>}``.

    Raises:
        RuntimeError: Si la versión no existe, o si tras los reintentos la
            Release no publica un asset con el sha256 registrado. No se activa
            nada: el modelo sigue sin versión activa.
    """
    from db.model_registry import activate_version, list_versions
    from services.ml.classifier_training import precompute_ml_proba

    fila = next((f for f in list_versions(_MODELO) if int(f["version"]) == version), None)
    if fila is None:
        raise RuntimeError(f"No existe la versión {version} de {_MODELO} en model_versions")

    estado = _verificar_publicacion(fila, sleep)
    if estado.estado != "ok":
        raise RuntimeError(
            f"{_MODELO} v{version} no se activa: la Release no publica su artefacto "
            f"({estado.estado}; asset {estado.asset}, registrado {estado.registrado}, "
            f"publicado {estado.publicado} en {estado.release}). El modelo queda sin "
            "versión activa; ver docs/runbooks/model-rollback.md."
        )

    if not activate_version(_MODELO, version):
        raise RuntimeError(f"No se pudo activar {_MODELO} v{version}")
    log.info(
        "ml_training_version_activada",
        modelo=_MODELO,
        version=version,
        sha256=estado.registrado,
        release=estado.release,
    )
    return {
        "version": version,
        "sha256": estado.registrado,
        "release": estado.release,
        "ml_proba": precompute_ml_proba(force=True),
    }


def _verificar_publicacion(
    fila: dict[str, Any], sleep: Callable[[float], None]
) -> ArtefactoPublicado:
    """Coteja ``fila`` con la Release, reintentando si todavía no cuadra."""
    from shared.model_artifacts import check_published_artifact, fetch_model_releases

    intento = 1
    while True:
        estado = check_published_artifact(fila, fetch_model_releases())
        if estado.estado == "ok" or intento >= _INTENTOS_VERIFICACION:
            return estado
        log.warning(
            "ml_training_artefacto_no_verificado",
            version=fila.get("version"),
            intento=intento,
            estado=estado.estado,
            asset=estado.asset,
            registrado=estado.registrado,
            publicado=estado.publicado,
            release=estado.release,
        )
        sleep(_ESPERA_VERIFICACION_SEGUNDOS)
        intento += 1


def rescore() -> dict[str, Any]:
    """Recalcula ``ml_proba`` de toda la población con el modelo que se sirve.

    Para cuando la columna no sale de un solo modelo: una versión que se
    activó y se retiró, un rollback con ``activate_version``, un ``precompute``
    forzado que se cortó a medias. No entrena ni cambia qué versión está
    activa.

    Raises:
        RuntimeError: Si no hay modelo servible. Un rescore que no puntúa nada
            y sale en verde es peor que uno que falla.
    """
    from services.ml.classifier_training import precompute_ml_proba

    resultado = precompute_ml_proba(force=True)
    if resultado.get("skipped_no_model"):
        raise RuntimeError("No hay modelo servible: no se recalculó ningún ml_proba")
    return resultado


def _emitir_salida_github(metrics: dict[str, Any]) -> None:
    """Escribe el desenlace en ``$GITHUB_OUTPUT`` para que el workflow decida.

    Sin esto, ``train-model.yml`` no puede distinguir "el gate rechazó al
    candidato" de "el entrenamiento reventó": en ambos casos falta el
    ``.pkl``, y el paso de verificación moría con un ``ls: cannot access``
    que no explica nada.
    """
    destino = os.environ.get("GITHUB_OUTPUT")
    if not destino:
        return
    promocion = metrics.get("promotion") or {}
    motivos = "; ".join(str(m) for m in (promocion.get("motivos_rechazo") or []))
    golden = promocion.get("golden") or {}
    lineas = [
        f"promoted={'true' if promocionado(metrics) else 'false'}",
        f"version={promocion.get('version') or ''}",
        # Una sola línea: los outputs multilinea necesitan heredoc y estos
        # motivos son frases cortas.
        f"rejection_reasons={motivos.replace(chr(10), ' ')}",
        f"recall_no_keyword={golden.get('recall_no_keyword', '')}",
        f"n_train={metrics.get('n_train', '')}",
        f"n_test={metrics.get('n_test', '')}",
    ]
    with open(destino, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lineas) + "\n")


def _resumir(lineas: list[str]) -> None:
    """Añade ``lineas`` al resumen del run. No-op fuera de GitHub Actions."""
    destino = os.environ.get("GITHUB_STEP_SUMMARY")
    if not destino:
        return
    with open(destino, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lineas) + "\n")


def _entrenar_cli() -> int:
    try:
        metrics = run()
    except RuntimeError as exc:
        log.error("ml_training_failed", error=str(exc), modelo="sap")
        return 1

    _emitir_salida_github(metrics)
    if not promocionado(metrics):
        # Salida 0 a propósito: el entrenamiento terminó bien y el gate hizo
        # su trabajo. Marcar esto en rojo enseñaría a ignorar los rojos. El
        # workflow se encarga de que quede visible que NO se publicó nada.
        log.warning(
            "ml_training_no_promocionado",
            modelo="sap",
            motivos=(metrics.get("promotion") or {}).get("motivos_rechazo"),
        )
    return 0


def _activar_cli(version: int) -> int:
    try:
        resultado = activar_publicada(version)
    except RuntimeError as exc:
        log.error("ml_training_activacion_fallida", error=str(exc), modelo="sap")
        _resumir(["## Versión NO activada", "", str(exc)])
        return 1
    _resumir(
        [
            "## Versión activada",
            "",
            f"- Versión: `{resultado['version']}`",
            f"- sha256 registrado y publicado: `{resultado['sha256']}`",
            f"- Release: `{resultado['release']}`",
            f"- `ml_proba` recalculados: `{resultado['ml_proba'].get('updated', 0)}`",
        ]
    )
    return 0


def _rescore_cli() -> int:
    try:
        resultado = rescore()
    except RuntimeError as exc:
        log.error("ml_rescore_fallido", error=str(exc), modelo="sap")
        _resumir(["## Rescore fallido", "", str(exc)])
        return 1
    _resumir(
        [
            "## `ml_proba` recalculado",
            "",
            f"- Filas reescritas: `{resultado.get('updated', 0)}`",
            f"- Scores borrados fuera de la población: "
            f"`{resultado.get('limpiadas_fuera_de_poblacion', 0)}`",
        ]
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI del workflow. Sin subcomando entrena, que es lo que hacía siempre."""
    import argparse

    parser = argparse.ArgumentParser(prog="python -m scheduler.jobs.ml_training_run")
    sub = parser.add_subparsers(dest="comando")
    sub.add_parser("entrenar", help="Siembra negativos, entrena y pasa el gate (por defecto)")
    activar = sub.add_parser(
        "activar", help="Activa una versión cuyo artefacto ya está en la Release"
    )
    activar.add_argument("--version", type=int, required=True)
    sub.add_parser("rescore", help="Recalcula ml_proba con el modelo que se sirve")
    args = parser.parse_args(argv)

    if args.comando == "activar":
        return _activar_cli(args.version)
    if args.comando == "rescore":
        return _rescore_cli()
    # Un solo camino de entrenamiento: el clasificador SAP binario. El
    # multi-etiqueta tiene su propio entrypoint desde #263
    # (`scheduler/jobs/tech_training_run.py`, workflow `train-tech.yml`), con un
    # gate de etiquetas circulares más estricto que el que este módulo llegó a
    # tener: un suelo absoluto de etiquetas independientes, en vez de fiarse
    # del flag `labels_circulares`, que se apaga en cuanto UNA fila trae
    # etiqueta humana.
    return _entrenar_cli()


if __name__ == "__main__":
    import sys

    sys.exit(main())
