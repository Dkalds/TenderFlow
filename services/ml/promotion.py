"""Gate de promoción: clasificador SAP y modelos predictivos (baja, retención).

Motivación
----------
Coexistían dos caminos de reentrenamiento con garantías opuestas:

- ``scheduler.concept_drift.maybe_retrain_classifier`` (semanal, disparado por
  feedback) tenía gate de tres métricas y registraba la versión.
- ``services.ml.classifier_training.train_from_db`` —el que produce el asset de la Release
  que descargan la API y todos los runners, o sea **el modelo que realmente se
  sirve**— guardaba el ``.pkl`` si el entrenamiento no lanzaba ``error``, sin
  gate, sin fila en ``model_versions`` y sin sha registrado. Su propio docstring
  lo admitía. Un entrenamiento con datos degradados se promocionaba solo, y no
  había versión anterior registrada a la que volver.

Este módulo concentró primero la decisión para que ambos caminos pasaran por
la misma puerta. Desde 2026-10 queda **un solo camino**: el reentrenamiento
semanal ya no entrena, lanza ``train-model.yml``
(``scheduler.concept_drift.maybe_retrain_classifier``), y este gate **no
activa nunca**. Registra el candidato —inactivo— y, si pasa, escribe el
artefacto que hay que publicar; activarlo es cosa de
``scheduler.jobs.ml_training_run.activar_publicada``, y solo después de
comprobar que la Release publica ese mismo sha256. Una versión activa sin
artefacto publicado —el incidente del 2026-09-29— deja de poder escribirse
por aquí.

Qué mide el gate
----------------
El gate anterior comparaba ``f1``/``pr_auc``/``brier`` del candidato contra los
del modelo activo. Dos problemas:

1. **Cada modelo mide sobre su propio test set.** Los splits se recalculan en
   cada reentrenamiento sobre un dataset que crece, así que la comparación no
   era entre modelos sino entre conjuntos de evaluación distintos. Ahora la
   comparación decisiva se hace sobre el **golden set humano** (mitad
   ``holdout``), que es fijo, y ambos candidatos se evalúan sobre él.

2. **Gateaba sobre la imitación del filtro de keywords.** Las etiquetas del
   test split derivan de ``raw_keywords``, así que un modelo que reproduce el
   regex saca un f1 excelente sin aportar nada. La métrica que sí mide el valor
   incremental —``recall_no_keyword``, los SAP reales que las keywords no
   marcan— se calculaba y se guardaba, pero no bloqueaba. Ahora bloquea: un
   modelo que no supera el mínimo no se promociona, porque servir el regex es
   más barato que servir un pickle que hace lo mismo.

Además se exige ``metrics_reliable``: con un test de diez filas, un f1 a cuatro
decimales no es una medición y no puede decidir una promoción. Lo mismo vale
para el golden: por debajo de ``services.ml_eval.MIN_HOLDOUT_EXAMPLES`` ejemplos
en el holdout el gate rechaza.

La comparación con el modelo activo **no se salta en silencio**: el artefacto
activo se resuelve por el registro (``_golden_del_activo``: almacén de objetos o
Release, con su sha256) y, si hay versión activa y no se puede medir, el
candidato se rechaza (``activo_no_evaluable``). Mirar el ``path`` registrado
—el de un runner efímero— hacía que en CI la comparación no corriera nunca.

Los modelos predictivos (S6.4)
------------------------------
``baja_model`` y ``retencion_model`` no tienen golden set humano ni
``recall_no_keyword``: se comparan contra un **baseline** (la regla que se
sirve mientras no haya versión activa) sobre validación temporal. Para ellos
el gate es :func:`evaluar_promocion_predictiva`, y su regla es una sola frase:

    una versión solo se promociona si su mejora sobre el baseline supera la
    dispersión de esa misma métrica entre folds.

Sin esa comparación, «mejora un 3,3 %» no significa nada. Es literalmente el
caso de ``baja_model`` v2 (backlog P2): ``mae_p50`` 0.12494 contra
``mae_baseline`` 0.12999 —una mejora de 0.005— con ``mae_p50_std_folds``
0.01287, dos veces y media esa mejora. Activar ahí es activar ruido, y encima
sin red que detecte la regresión después.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from observability.logging import get_logger

if TYPE_CHECKING:
    from services.ml_eval import GoldenEvalResult

log = get_logger(__name__)

# Tolerancias de regresión sobre las métricas del test split. Son un guardarraíl
# secundario: la decisión principal la toma el golden set.
TOLERANCIA_F1 = 0.02
TOLERANCIA_PR_AUC = 0.03
TOLERANCIA_BRIER = 0.05
# Un modelo que no pesca NADA que las keywords no pesquen ya no aporta nada
# sobre `matches_sap()`, que es gratis y no hay que reentrenar.
MIN_RECALL_NO_KEYWORD = 0.05
# Cuánto puede empeorar el recall incremental respecto al modelo activo.
TOLERANCIA_RECALL_NO_KEYWORD = 0.05

# ── Gate de los modelos predictivos (S6.4) ────────────────────────────────
#: Cuántas veces la dispersión entre folds tiene que caber en la mejora sobre
#: el baseline para que la mejora sea distinguible de ruido. ``1.0`` es el
#: mínimo defendible —la mejora iguala a una desviación típica— y ya rechaza
#: el caso que motivó el criterio (baja v2: mejora 0.005, dispersión 0.0129).
#: Subirlo endurece el gate; bajarlo de 1.0 sería promocionar dentro del ruido.
MIN_IMPROVEMENT_OVER_FOLD_DISPERSION = 1.0


class _ClasificadorEvaluable(Protocol):
    """Lo que el gate necesita de un clasificador para evaluarlo."""

    def predict(
        self, text: str, *, cpv: str | None = ..., importe: float | None = ...
    ) -> tuple[bool, float]: ...


@dataclass
class ResultadoPromocion:
    """Qué decidió el gate y por qué.

    No hay campo ``activada``: :func:`promote_if_better` no activa nunca, así
    que el mejor desenlace posible es ``pendiente_de_activar``.
    """

    registrada: bool
    version: int | None
    motivos_rechazo: list[str] = field(default_factory=list)
    golden: dict[str, Any] = field(default_factory=dict)
    #: Pasó el gate y su artefacto está escrito, registrado e inactivo: falta
    #: publicarlo y comprobar que lo publicado es lo registrado
    #: (``scheduler.jobs.ml_training_run.activar_publicada``).
    pendiente_de_activar: bool = False
    #: Ruta del artefacto publicado (``<stem>-<sha256[:12]>.pkl``) si el gate
    #: pasó y había ``publicar_como``; es la registrada en ``model_versions`` y
    #: la que ``train-model.yml`` sube a la Release. ``None`` si no se publicó.
    artefacto: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "registrada": self.registrada,
            "version": self.version,
            "motivos_rechazo": self.motivos_rechazo,
            **({"golden": self.golden} if self.golden else {}),
            **({"pendiente_de_activar": True} if self.pendiente_de_activar else {}),
            **({"artefacto": self.artefacto} if self.artefacto else {}),
        }


def evaluar_en_golden(clf: _ClasificadorEvaluable) -> GoldenEvalResult | None:
    """Evalúa el clasificador sobre la mitad ``holdout`` del golden set.

    Devuelve ``None`` si no hay golden set utilizable — en ese caso el gate no
    puede pronunciarse sobre el valor incremental y lo dice en los motivos.
    """
    from services.ml_eval import SPLIT_HOLDOUT, evaluate_classifier, load_golden_set

    examples = load_golden_set()
    if not examples:
        return None
    resultado = evaluate_classifier(clf, examples, split=SPLIT_HOLDOUT)
    if resultado.n == 0:
        return None
    return resultado


def _golden_del_activo(name: str) -> tuple[GoldenEvalResult | None, str | None]:
    """Golden del modelo activo de ``name``, o el motivo por el que no se pudo medir.

    El ``path`` de ``model_versions`` es el del runner efímero que entrenó la
    versión: mirar ``Path(path).exists()`` —como hacía el gate— da siempre
    «no existe» en CI, y la comparación con lo que se sirve nunca corría, sin
    una línea de log. ``resolve_active_artifact`` lo materializa desde el
    almacén de objetos o la Release y verifica su sha256 contra el registro.

    ``(None, None)`` es «no hay golden utilizable» (``evaluar_gate`` ya lo
    rechaza por ``sin_golden_set``); ``(None, motivo)`` es un activo que no se
    pudo resolver o cargar, y rechaza al candidato.
    """
    try:
        from services.ml.model_artifacts import resolve_active_artifact
        from services.ml.sap_classifier import SAPClassifier

        ruta = resolve_active_artifact(name)
        if ruta is None:
            log.warning("promotion.activo_irresoluble", name=name)
            return None, "el artefacto de la versión activa no se pudo resolver"
        return evaluar_en_golden(SAPClassifier.load(ruta)), None
    except Exception as exc:
        log.warning("promotion.golden_activo_no_evaluable", name=name, error=str(exc))
        return None, f"no se pudo evaluar la versión activa ({type(exc).__name__})"


def _motivos_regresion(
    nuevas: dict[str, Any],
    previas: dict[str, Any],
) -> list[str]:
    """Comprueba que el candidato no regresa respecto al activo (guardarraíl)."""
    motivos: list[str] = []

    old_f1 = float(previas.get("f1") or 0.0)
    new_f1 = float(nuevas.get("f1") or 0.0)
    if old_f1 > 0.0 and new_f1 < old_f1 - TOLERANCIA_F1:
        motivos.append(f"f1 {new_f1:.4f} < {old_f1:.4f} - {TOLERANCIA_F1}")

    old_pr = previas.get("pr_auc")
    if old_pr is not None:
        new_pr = float(nuevas.get("pr_auc") or 0.0)
        if new_pr < float(old_pr) - TOLERANCIA_PR_AUC:
            motivos.append(f"pr_auc {new_pr:.4f} < {float(old_pr):.4f} - {TOLERANCIA_PR_AUC}")

    old_brier = previas.get("brier")
    if old_brier is not None:
        new_brier = float(nuevas.get("brier") or 1.0)
        if new_brier > float(old_brier) + TOLERANCIA_BRIER:
            motivos.append(f"brier {new_brier:.4f} > {float(old_brier):.4f} + {TOLERANCIA_BRIER}")

    return motivos


def evaluar_gate(
    metrics: dict[str, Any],
    *,
    metricas_activas: dict[str, Any] | None,
    golden: GoldenEvalResult | None,
    golden_activo: GoldenEvalResult | None = None,
    activo_no_evaluable: str | None = None,
) -> list[str]:
    """Devuelve la lista de motivos por los que NO se debe promocionar.

    Lista vacía = el candidato pasa. Es una función pura: se puede testear sin
    BD ni artefactos.

    ``activo_no_evaluable`` es el motivo por el que hay una versión activa pero
    no se pudo medir su golden (artefacto irresoluble, fallo al cargarlo). Rechaza:
    un candidato que no se puede comparar con lo que se sirve no pasa por
    defecto, que es lo que hacía el gate cuando la comparación se saltaba en
    silencio.
    """
    from services.ml_eval import MIN_HOLDOUT_EXAMPLES

    motivos: list[str] = []
    if activo_no_evaluable:
        motivos.append(f"activo_no_evaluable: {activo_no_evaluable}")

    if not metrics.get("metrics_reliable", False):
        motivos.append(
            f"metricas_no_fiables (n_test={metrics.get('n_test')}, "
            f"n_positive_test={metrics.get('n_positive_test')})"
        )

    if metrics.get("split_strategy") not in ("temporal", "grouped_random"):
        motivos.append(f"split_desconocido ({metrics.get('split_strategy')!r})")

    if golden is None:
        motivos.append("sin_golden_set: no se puede medir el valor sobre las keywords")
    else:
        # Con un holdout de pocas decenas, una diferencia de un ejemplo mueve el
        # recall varios puntos: el gate decidiría con ruido. Es el mismo mínimo
        # que ya exige la señal del clasificador (`senal_clasificador`).
        if golden.n < MIN_HOLDOUT_EXAMPLES:
            motivos.append(
                f"golden_holdout_insuficiente: {golden.n} ejemplos < {MIN_HOLDOUT_EXAMPLES}"
            )
        if golden.n_no_keyword_positive == 0:
            motivos.append(
                "golden_sin_zona_de_desacuerdo: no hay positivos humanos sin keyword "
                "en el holdout, así que recall_no_keyword no mide nada"
            )
        elif golden.recall_no_keyword < MIN_RECALL_NO_KEYWORD:
            motivos.append(
                f"recall_no_keyword {golden.recall_no_keyword:.4f} < {MIN_RECALL_NO_KEYWORD} "
                "(el modelo no aporta sobre el filtro de keywords)"
            )
        if golden_activo is not None and golden_activo.n_no_keyword_positive > 0:
            caida = golden_activo.recall_no_keyword - golden.recall_no_keyword
            if caida > TOLERANCIA_RECALL_NO_KEYWORD:
                motivos.append(
                    f"recall_no_keyword cae {caida:.4f} respecto al activo "
                    f"({golden_activo.recall_no_keyword:.4f} -> {golden.recall_no_keyword:.4f})"
                )

    if metricas_activas:
        motivos.extend(_motivos_regresion(metrics, metricas_activas))

    return motivos


@dataclass(frozen=True)
class DecisionPredictiva:
    """Veredicto del gate predictivo, con el número que lo justifica.

    ``promotion_reason`` es la frase que se guarda en ``model_versions.notes``
    y en las métricas: el backlog pedía «el número que lo justifica anotado»,
    y una nota que solo dice «no cumple criterios» obliga a reconstruir la
    cuenta a mano cada vez.
    """

    promocionable: bool
    promotion_reason: str
    mejora: float
    dispersion: float | None
    margen_exigido: float | None
    motivos: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "promocionable": self.promocionable,
            "promotion_reason": self.promotion_reason,
            "mejora_sobre_baseline": round(self.mejora, 5),
            "dispersion_entre_folds": (
                round(self.dispersion, 5) if self.dispersion is not None else None
            ),
            "margen_exigido": (
                round(self.margen_exigido, 5) if self.margen_exigido is not None else None
            ),
            "motivos_rechazo": list(self.motivos),
        }


def evaluar_promocion_predictiva(
    *,
    metrica: float,
    baseline: float,
    dispersion: float | None,
    nombre_metrica: str,
    mejor_es_mayor: bool = False,
    min_improvement_over_fold_dispersion: float = MIN_IMPROVEMENT_OVER_FOLD_DISPERSION,
    motivos_extra: list[str] | None = None,
) -> DecisionPredictiva:
    """Decide si un modelo predictivo puede activarse. Función pura.

    Args:
        metrica: Valor del candidato (``mae_p50``, ``pr_auc``…).
        baseline: Mismo valor para la regla que se sirve hoy. Para retención el
            baseline del ranking trivial es la **prevalencia**: es el PR-AUC
            esperado de ordenar al azar, así que un PR-AUC igual a la
            prevalencia no ordena nada.
        dispersion: Desviación típica de ``metrica`` entre folds (o entre
            bloques de la ventana de validación). ``None`` significa que nadie
            la midió, y entonces **no se puede** distinguir la mejora del
            ruido: el gate rechaza en vez de dar por buena una comparación que
            no tiene error asociado.
        nombre_metrica: Solo para redactar ``promotion_reason``.
        mejor_es_mayor: ``True`` para métricas donde más es mejor (PR-AUC),
            ``False`` para errores (MAE).
        min_improvement_over_fold_dispersion: Cuántas dispersiones tiene que
            medir la mejora. Ver :data:`MIN_IMPROVEMENT_OVER_FOLD_DISPERSION`.
        motivos_extra: Criterios propios del modelo que ya se evaluaron fuera
            (cobertura del intervalo, ECE…). Si traen algo, la versión no se
            promociona por mucho que gane al baseline.

    Returns:
        :class:`DecisionPredictiva`.
    """
    motivos = list(motivos_extra or [])
    mejora = (metrica - baseline) if mejor_es_mayor else (baseline - metrica)
    margen = (
        abs(dispersion) * min_improvement_over_fold_dispersion if dispersion is not None else None
    )

    if mejora <= 0:
        motivos.append(f"{nombre_metrica} no bate al baseline ({metrica:.5f} vs {baseline:.5f})")
    elif margen is None:
        motivos.append(
            f"sin dispersion medida de {nombre_metrica}: una mejora sin error asociado "
            "no se puede distinguir del ruido"
        )
    elif mejora < margen:
        motivos.append(
            f"mejora de {nombre_metrica} {mejora:.5f} < dispersion entre folds "
            f"{abs(dispersion or 0.0):.5f} x {min_improvement_over_fold_dispersion:g}: "
            "indistinguible de ruido"
        )

    promocionable = not motivos
    if promocionable:
        reason = (
            f"promocionable: mejora de {nombre_metrica} {mejora:.5f} >= "
            f"{margen:.5f} (dispersion entre folds x{min_improvement_over_fold_dispersion:g})"
            if margen is not None
            else f"promocionable: mejora de {nombre_metrica} {mejora:.5f}"
        )
    else:
        reason = "no promocionable — " + "; ".join(motivos)

    log.info(
        "promotion.predictiva_evaluada",
        metrica=nombre_metrica,
        valor=metrica,
        baseline=baseline,
        dispersion=dispersion,
        mejora=mejora,
        promocionable=promocionable,
        motivos=motivos,
    )
    return DecisionPredictiva(
        promocionable=promocionable,
        promotion_reason=reason,
        mejora=mejora,
        dispersion=dispersion,
        margen_exigido=margen,
        motivos=motivos,
    )


def promote_if_better(
    clf: Any,
    metrics: dict[str, Any],
    *,
    name: str = "sap_classifier",
    n_feedbacks: int | None = None,
    notes: str | None = None,
    models_dir: Path | None = None,
    publicar_como: Path | None = None,
) -> ResultadoPromocion:
    """Registra la versión, **inactiva**, y escribe su artefacto si pasa el gate.

    La versión se registra SIEMPRE (aunque no pase): es lo que permite ver el
    histórico. Lo que el gate decide es si el candidato es publicable: si lo
    es, se escribe el artefacto y la fila queda ``pendiente_de_activar``.

    **Aquí no se activa nada.** Activar es afirmar que el artefacto se puede
    bajar, y en el momento de esta llamada ``publicar_como`` no ha llegado a
    ningún otro proceso: está en el disco de quien entrena. Lo activa
    ``scheduler.jobs.ml_training_run.activar_publicada``, después de comprobar
    que la Release publica ese mismo sha256. Hasta 2026-10 esta función
    activaba por defecto (``activar=True``), y el reentrenamiento semanal la
    llamaba así dentro de un runner efímero: el 2026-09-29 dejó activa una v2
    cuyo ``.pkl`` murió con el runner, y ``ml_scoring`` cayó por
    ``ModelArtifactMismatch`` en cada pasada. El parámetro se retiró para que
    ningún camino —tampoco uno nuevo— pueda repetirlo.

    **El artefacto publicado lleva su sha256 en el nombre** (2026-10):
    ``publicar_como`` es la ruta *base* (``data/models/sap_classifier.pkl``) y
    lo que se escribe y se registra es ``sap_classifier-<sha256[:12]>.pkl`` en
    ese directorio (``services.ml.model_artifacts.content_addressed_path``), igual
    que ``baja_model`` y ``retencion_model``. Con el nombre fijo, subir el
    candidato sustituía el asset de la versión activa, y ``train-model.yml``
    tenía que retirarla antes de subir: el modelo se servía sin cotejar hasta
    activar el nuevo, y un fallo de la subida dejaba a los runners sin modelo.
    El fichero de nombre fijo de ``publicar_como`` no se toca: es el que se
    sirve como último recurso mientras no haya versión activa
    (``SAPClassifier.resolve_artifact``).

    Por lo mismo, **el rollback vuelve a ser ``activate_version``** para las
    versiones publicadas así: el asset de cada una sigue en la Release y
    ninguna otra lo pisa. Las anteriores, registradas como
    ``sap_classifier.pkl``, siguen apuntando a un asset que otra versión pudo
    sustituir; la verificación de sha256 lo detecta (``ModelArtifactMismatch``)
    en vez de servir el modelo equivocado. El artefacto versionado
    (``<name>_v{N}.pkl``) se sigue escribiendo en ``models_dir``.

    Args:
        clf: ``SAPClassifier`` ya entrenado (se le pide ``save`` y ``predict``).
        metrics: Métricas devueltas por ``clf.train()``.
        name: Nombre en el registry.
        n_feedbacks: Feedbacks humanos que dispararon el reentrenamiento.
        notes: Nota libre para el registry.
        models_dir: Directorio de los artefactos versionados.
        publicar_como: Ruta base del artefacto que sirve producción. Si el
            gate pasa se publica como ``<stem>-<sha256[:12]><suffix>`` en su
            directorio, con su ``.sha256``; si no, no se escribe nada.
    """
    from db.model_registry import get_active, next_version, register_version

    activa = get_active(name)
    # Se numera desde el máximo registrado, que es desde donde numera
    # ``register_version``. ``activa + 1`` diverge en cuanto hay versiones
    # registradas y ninguna activa (o la activa no es la última): con una v1
    # inactiva, el artefacto se guardó como ``_v1``, los logs y la notificación
    # dijeron «v1», y la fila insertada fue la 2.
    prevista = next_version(name)
    destino_dir = models_dir or Path("data/models")
    destino_dir.mkdir(parents=True, exist_ok=True)
    ruta_version = destino_dir / f"{name}_v{prevista}.pkl"
    guardado = Path(clf.save(ruta_version))
    sha = hashlib.sha256(guardado.read_bytes()).hexdigest()

    golden = evaluar_en_golden(clf)
    golden_dict = golden.as_dict() if golden is not None else {}

    golden_activo: GoldenEvalResult | None = None
    activo_no_evaluable: str | None = None
    if activa:
        golden_activo, activo_no_evaluable = _golden_del_activo(name)

    motivos = evaluar_gate(
        metrics,
        metricas_activas=(activa or {}).get("metrics") if activa else None,
        golden=golden,
        golden_activo=golden_activo,
        activo_no_evaluable=activo_no_evaluable,
    )
    pasa_el_gate = not motivos

    # Publicar ANTES de registrar: el ``path`` que queda en ``model_versions``
    # tiene que ser el del fichero que de verdad viaja a la Release, porque es
    # el nombre EXACTO por el que ``resolve_active_artifact`` lo pedirá desde
    # otro runner (``_download_release_asset`` casa por ``Path(path).name``).
    # Registrando el versionado, ``train-model.yml`` subía ``sap_classifier.pkl``
    # mientras el registro apuntaba a ``sap_classifier_v{N}.pkl`` -- un nombre
    # que no existe en la Release, así que la resolución moría en
    # ``asset_not_in_release`` y el paso de scoring volvía a ``no_model``. Es la
    # invariante que ya cumple ``train-predictivos.yml``: se sube el fichero
    # cuyo path se registró.
    #
    # Con el sha256 en el nombre: un fichero nuevo por versión, así que subirlo
    # no sustituye el asset de la versión activa (ver el docstring).
    ruta_registrada = guardado
    publicado: Path | None = None
    if pasa_el_gate and publicar_como is not None:
        from services.ml.model_artifacts import content_addressed_path

        publicado = content_addressed_path(publicar_como, sha)
        publicado.parent.mkdir(parents=True, exist_ok=True)
        publicado.write_bytes(guardado.read_bytes())
        _escribir_checksum(publicado)
        log.info("promotion.artefacto_publicado", path=str(publicado), sha256=sha)
        ruta_registrada = publicado

    n_samples = int(metrics.get("n_train") or 0) + int(metrics.get("n_test") or 0)
    # De aquí en adelante ``version`` es la que asignó el registro: es la que
    # existe en ``model_versions``, y la que tienen que nombrar los logs, la
    # notificación y el resumen de ``train-model.yml``.
    version = register_version(
        name=name,
        # Mismo sha en los dos: el publicado es copia byte a byte de
        # ``guardado``, así que el hash registrado sigue describiendo el
        # contenido con independencia de cuál de los dos nombres se registre.
        path=str(ruta_registrada),
        sha256=sha,
        # ``golden_holdout_*`` y no ``golden_*``: train() ya guarda
        # ``golden_*`` con las métricas de la mitad "tune" (donde se eligió
        # el umbral). Mezclarlas sería volver a confundir el conjunto donde
        # se ajusta con el conjunto donde se reporta.
        metrics={**metrics, **{f"golden_holdout_{k}": v for k, v in golden_dict.items()}},
        n_samples=n_samples,
        n_feedbacks=n_feedbacks,
        notes=notes,
        # Nunca activa: ver el docstring. La activación vive en
        # ``scheduler.jobs.ml_training_run.activar_publicada``.
        activate=False,
    )
    if version != prevista:
        # Otro proceso registró entre ``next_version`` y el INSERT. El fichero
        # versionado ya está escrito (y, si el gate rechazó, registrado) con el
        # número previsto: no se renombra, pero se deja dicho cuál es cuál.
        log.warning(
            "promotion.version_desfasada",
            name=name,
            prevista=prevista,
            registrada=version,
            path=str(guardado),
        )

    if pasa_el_gate:
        log.info(
            "promotion.pendiente_de_activar",
            name=name,
            version=version,
            path=str(ruta_registrada),
            golden=golden_dict,
        )
    else:
        log.warning(
            "promotion.rechazada",
            name=name,
            version=version,
            motivos=motivos,
            golden=golden_dict,
        )

    return ResultadoPromocion(
        registrada=True,
        version=version,
        motivos_rechazo=motivos,
        golden=golden_dict,
        pendiente_de_activar=pasa_el_gate,
        artefacto=str(publicado) if publicado is not None else None,
    )


def _escribir_checksum(path: Path) -> None:
    """Regenera el ``.sha256`` co-ubicado del artefacto publicado."""
    from shared.model_integrity import write_checksum

    write_checksum(path)


__all__ = [
    "MIN_IMPROVEMENT_OVER_FOLD_DISPERSION",
    "MIN_RECALL_NO_KEYWORD",
    "DecisionPredictiva",
    "ResultadoPromocion",
    "evaluar_en_golden",
    "evaluar_gate",
    "evaluar_promocion_predictiva",
    "promote_if_better",
]
