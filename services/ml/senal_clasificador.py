"""¿Se puede usar o enseñar la probabilidad del ``sap_classifier``? (D55)

``licitaciones.ml_proba`` es la P(SAP) del clasificador binario. El que se
sirve hoy es el asset de mayo de ``v1.0.0-models``, sin versión activa en
``model_versions``, y da ``ml_proba ≥ 0,69`` al 60 % de su población: no
discrimina (backlog P1 «sap_classifier», P2 «El corpus de PSCP ahoga…»). La
decisión D55 del plan 2026-10 es que, mientras no haya una versión activa
que haya pasado el gate, esa probabilidad **no ordena ni puntúa** nada y **no
se enseña** como señal. Este módulo es la única definición de «ha pasado».

Lo que NO cubre: ``ml_tecnologias``/``ml_proba_max``/``ml_tech_principal`` y
``licitacion_tecnologia_score``. Esas las derivan el clasificador
multi-etiqueta (``tech_classifier``, otro modelo), el etiquetado LLM y la
señal del pliego (ADR-026, addendum de ``v136``); el binario no escribe ahí.

Qué es «una versión activa que ha pasado el gate»
-------------------------------------------------
Las tres cosas a la vez, leídas de la fila activa de ``model_versions``:

1. **Hay versión activa** (``db.model_registry.get_active``).
2. **Su artefacto es el que publica el gate**: ``promote_if_better`` solo
   escribe y registra el nombre por contenido (``<stem>-<sha256[:12]>.pkl``,
   ``services.ml.model_artifacts.content_addressed_path``) cuando el candidato
   pasa; uno rechazado queda registrado como ``<name>_v{N}.pkl``, y las
   versiones anteriores a 2026-10 como ``sap_classifier.pkl``. Activar a mano
   una de esas (``POST /models/.../activate`` o ``activate_version``) no la
   convierte en validada.
3. **Sus métricas guardadas pasan el gate hoy**: ``evaluar_gate`` sobre
   ``metrics`` y el golden ``holdout`` que se registró con ellas
   (``golden_holdout_*``), más un holdout de al menos
   ``services.ml_eval.MIN_HOLDOUT_EXAMPLES`` ejemplos — el gate del golden que
   D55 cita (27 etiquetados frente a ≥ 60 el 2026-10-25). Reevaluar con las
   constantes vigentes hace que endurecer el gate retire la señal de una
   versión que lo pasó con el criterio anterior, en vez de dejarla servida.

Es barato a propósito: una consulta a ``model_versions`` y ninguna carga de
modelo ni llamada de red, así que se puede preguntar en una petición HTTP.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from observability.logging import get_logger

if TYPE_CHECKING:
    from services.ml_eval import GoldenEvalResult

log = get_logger(__name__)

MODELO = "sap_classifier"

MOTIVO_SIN_VERSION_ACTIVA = "sin_version_activa"
MOTIVO_ARTEFACTO_SIN_GATE = "artefacto_no_publicado_por_el_gate"
MOTIVO_NO_PASA_EL_GATE = "no_pasa_el_gate"
MOTIVO_REGISTRY_ILEGIBLE = "registry_ilegible"


@dataclass(frozen=True)
class EstadoSenal:
    """Si la probabilidad del clasificador es utilizable y, si no, por qué."""

    validada: bool
    #: ``None`` si está validada; si no, uno de los ``MOTIVO_*``.
    motivo: str | None = None
    #: Versión activa que se evaluó, si la hay.
    version: int | None = None
    #: Los motivos concretos del gate cuando ``motivo == MOTIVO_NO_PASA_EL_GATE``.
    detalle: tuple[str, ...] = ()


NO_VALIDADA_SIN_VERSION = EstadoSenal(validada=False, motivo=MOTIVO_SIN_VERSION_ACTIVA)


def _golden_holdout(metrics: Mapping[str, object]) -> GoldenEvalResult | None:
    """Reconstruye el ``GoldenEvalResult`` del holdout guardado con la versión.

    ``promote_if_better`` registra ``golden_holdout_<campo>`` para cada campo
    de ``GoldenEvalResult.as_dict``. Si falta alguno, la versión no se evaluó
    sobre el golden y se devuelve ``None`` (el gate lo rechaza por eso).
    """
    from services.ml_eval import GoldenEvalResult

    def real(campo: str) -> float:
        valor = metrics[f"golden_holdout_{campo}"]
        if isinstance(valor, bool) or not isinstance(valor, int | float | str):
            raise TypeError(f"golden_holdout_{campo}: {valor!r}")
        return float(valor)

    def entero(campo: str) -> int:
        return int(real(campo))

    try:
        return GoldenEvalResult(
            n=entero("n"),
            n_positive=entero("n_positive"),
            n_negative=entero("n_negative"),
            threshold=real("threshold"),
            accuracy=real("accuracy"),
            precision=real("precision"),
            recall=real("recall"),
            f1=real("f1"),
            fbeta=real("fbeta"),
            beta=real("beta"),
            recall_no_keyword=real("recall_no_keyword"),
            n_no_keyword_positive=entero("n_no_keyword_positive"),
            n_no_keyword_caught=entero("n_no_keyword_caught"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def evaluar_version_activa(activa: Mapping[str, object] | None) -> EstadoSenal:
    """Decide sobre la fila activa de ``model_versions`` (pura: sin BD ni red).

    ``activa`` es lo que devuelve ``db.model_registry.get_active``: con
    ``path``, ``sha256``, ``version`` y ``metrics`` ya decodificado.
    """
    if activa is None:
        return NO_VALIDADA_SIN_VERSION

    from services.ml.model_artifacts import content_addressed_path
    from services.ml.promotion import evaluar_gate
    from services.ml_eval import MIN_HOLDOUT_EXAMPLES

    version_raw = activa.get("version")
    version = int(version_raw) if isinstance(version_raw, int | str) else None
    path = Path(str(activa.get("path") or ""))
    sha = str(activa.get("sha256") or "")
    if not sha or not path.name or content_addressed_path(path, sha) != path:
        return EstadoSenal(validada=False, motivo=MOTIVO_ARTEFACTO_SIN_GATE, version=version)

    metrics_raw = activa.get("metrics")
    metrics: dict[str, object] = dict(metrics_raw) if isinstance(metrics_raw, Mapping) else {}
    golden = _golden_holdout(metrics)
    motivos = evaluar_gate(metrics, metricas_activas=None, golden=golden)
    if golden is not None and golden.n < MIN_HOLDOUT_EXAMPLES:
        motivos.append(f"golden holdout de {golden.n} ejemplos < {MIN_HOLDOUT_EXAMPLES}")
    if motivos:
        return EstadoSenal(
            validada=False,
            motivo=MOTIVO_NO_PASA_EL_GATE,
            version=version,
            detalle=tuple(motivos),
        )
    return EstadoSenal(validada=True, version=version)


def estado_senal_sap() -> EstadoSenal:
    """Estado de la señal del ``sap_classifier`` según el registro.

    Un registro ilegible cuenta como **no validada**: la duda se resuelve
    escondiendo la probabilidad, no enseñándola.
    """
    from db.model_registry import get_active

    try:
        activa = get_active(MODELO)
    except Exception as exc:
        log.warning("senal_clasificador.registry_ilegible", error=str(exc))
        return EstadoSenal(validada=False, motivo=MOTIVO_REGISTRY_ILEGIBLE)
    return evaluar_version_activa(activa)


__all__ = [
    "MODELO",
    "MOTIVO_ARTEFACTO_SIN_GATE",
    "MOTIVO_NO_PASA_EL_GATE",
    "MOTIVO_REGISTRY_ILEGIBLE",
    "MOTIVO_SIN_VERSION_ACTIVA",
    "NO_VALIDADA_SIN_VERSION",
    "EstadoSenal",
    "estado_senal_sap",
    "evaluar_version_activa",
]
