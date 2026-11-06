"""Catálogo de la pipeline canónica: pasos, severidad, dependencias y carriles.

Es la parte declarativa de ``scheduler/pipeline_runs.py`` (ADR-012): qué pasos
hay y en qué orden (``CANONICAL_STEPS``), si su fallo pone la pasada en rojo
(``STEP_TIER``), de qué paso depende cada uno (``STEP_DEPS``) y los dos carriles.
No ejecuta nada; lo leen el ejecutor (``scheduler.pipeline_cierre``), la API de
ejecuciones y ``scripts/check_job_parity.py``.
"""

from __future__ import annotations

from typing import Literal

from observability.errores import ContadorDeErrores
from observability.runtime_metrics import pipeline_runs_errores_total

#: ``pipeline_runs_errores_total{paso}``: los sub-pasos best-effort del cierre
#: (avisos, export analítico, alertas de la propia pasada) que fallan sin poner
#: el paso en rojo. Los pasos canónicos que fallan ya van a ``STEP_ERROR`` y
#: avisan por correo; esto es lo que quedaba por debajo de ese radar.
_contar_error = ContadorDeErrores("pipeline_runs", pipeline_runs_errores_total)

# ---------------------------------------------------------------------------
# Pasos individuales (best-effort wrappers)
# ---------------------------------------------------------------------------

# Los pasos que no deben abortar la pipeline capturan excepciones y loguean.
# El orden de esta lista define el contrato de la secuencia canónica.

CANONICAL_STEPS: list[str] = [
    "ml_scoring",
    "ml_tecnologias",
    "tech_signal_merge",
    "llm_tech_labeling",
    "analytics_export",
    "organos_resolve",
    "kpi_precompute",
    "aggregates_precompute",
    "watchlist_notify",
    "cartera_avisos",
    "documentacion_avisos",
    "event_dispatch",
    "digests",
    "informes_programados",
    "dlq_retry",
    "webhook_reintentos",
    "anomaly_checks",
    "follows_paridad",
    "llm_models_canary",
    "model_artifacts_canary",
    "retention_cleanup",
    "sap_active_learning",
    "drift_checks",
]

#: Severidad de cada paso canónico.
#:
#: ``bloqueante``  el paso es parte del contrato de la pasada: si falla, la
#:                 pasada está rota y el proceso sale en rojo.
#: ``advisory``    el paso *informa* sobre el sistema pero no produce nada que
#:                 la pasada deba entregar. Si falla se notifica igual por email
#:                 (``_notify_step_failure``) y aparece como ``error`` en el
#:                 resumen de ``cierre_pasada_completado``, pero NO entra en
#:                 ``pipeline_post_ingestion_steps_failed`` ni cambia el exit
#:                 code.
#:
#: El 2026-09-01 el canary del catálogo NIM (``llm_models_canary``) tumbó el
#: cierre entero de ``scrape-daily`` durante días: los otros 14 pasos —incluido
#: el refresco de la superficie pública— terminaron ``ok``, y aun así el job
#: salía rojo por un aviso sobre el catálogo de un proveedor LLM. Un rojo que
#: significa «hay un aviso» y un rojo que significa «la pasada no entregó» no
#: pueden ser el mismo rojo: el primero enseña al equipo a ignorar el segundo.
#:
#: Los cuatro ``advisory`` comparten forma: miran el estado del sistema
#: (catálogo de modelos, anomalías del corpus, drift del clasificador, cola de
#: active learning) y su salida es una alerta, no un dato del que dependa
#: ninguna superficie. Todo lo demás es bloqueante.
StepTier = Literal["bloqueante", "advisory"]

STEP_TIER: dict[str, StepTier] = {
    "ml_scoring": "bloqueante",
    "ml_tecnologias": "bloqueante",
    "tech_signal_merge": "bloqueante",
    "llm_tech_labeling": "bloqueante",
    "analytics_export": "bloqueante",
    # advisory: el maestro de órganos (ADR-032) mejora la analítica pero no
    # produce nada que la pasada deba entregar; una grafía que no resuelve
    # sigue agregándose por texto. Va antes de los precomputes para que estos
    # agrupen por los ids recién asignados.
    "organos_resolve": "advisory",
    "kpi_precompute": "bloqueante",
    "aggregates_precompute": "bloqueante",
    "watchlist_notify": "bloqueante",
    # advisory: los avisos de fin de contrato (F4.3) tienen meses de margen y
    # la ventana es diaria; una pasada fallida la recupera la siguiente. No
    # puede tumbar la ingesta.
    "cartera_avisos": "advisory",
    # advisory: los avisos de caducidad de la documentación acreditativa tienen
    # semanas de margen (60, 30 y 7 días) y la ventana es diaria; una pasada
    # fallida la recupera la siguiente. No puede tumbar la ingesta.
    "documentacion_avisos": "advisory",
    # advisory: el outbox es persistente. Si el reparto falla, los eventos
    # siguen pendientes y la pasada siguiente los entrega (dentro de la
    # antigüedad máxima, ver `event_dispatch.caducar_viejos`); un receptor de
    # webhook caído o un SMTP lento no pueden poner la ingesta en rojo.
    "event_dispatch": "advisory",
    "digests": "bloqueante",
    # advisory: el informe semanal es una función opcional que cada
    # organización activa por su cuenta. Un ESP caído no puede tumbar la
    # pasada de ingesta — y la ventana de envío es de un día entero, así que
    # la pasada siguiente lo recupera sola.
    "informes_programados": "advisory",
    "dlq_retry": "bloqueante",
    # advisory: un receptor externo caído no es un fallo de la pasada. Que
    # el reenvío no salga significa que el endpoint del cliente sigue sin
    # responder, y sacar la pasada en rojo por eso enseña a ignorar el rojo.
    "webhook_reintentos": "advisory",
    "anomaly_checks": "advisory",
    # Mide, no repara: que la paridad de `follows` esté rota no rompe la
    # pasada ni lo nota ningún cliente. Lo que bloquea es la migración de
    # ADR-031 §B, y eso lo decide una persona mirando la serie.
    "follows_paridad": "advisory",
    "llm_models_canary": "advisory",
    # advisory: compara `model_versions` con las Releases y avisa. Si el
    # artefacto que falta es el del clasificador SAP, quien pone la pasada en
    # rojo es `ml_scoring`, que es el que deja de entregar; este paso explica
    # por qué y cubre los modelos que la pasada no carga.
    "model_artifacts_canary": "advisory",
    "retention_cleanup": "bloqueante",
    "sap_active_learning": "advisory",
    "drift_checks": "advisory",
}

#: Estados posibles de un paso en el resumen de la pasada.
#:
#: ``ok``       el paso hizo su trabajo.
#: ``skipped``  el paso decidió no hacer nada y eso es correcto: su ventana de
#:              cadencia aún no venció (``_run_periodic``), su feature flag está
#:              apagado, o le falta un insumo declarado (ver ``_run_ml_scoring``).
#:              **No** es un fallo y no eleva el exit code.
#: ``error``    el paso lanzó. Eleva el exit code solo si es ``bloqueante``.
STEP_OK = "ok"
STEP_SKIPPED = "skipped"
STEP_ERROR = "error"

#: El paso no se ejecutó porque un paso del que depende no dejó su insumo
#: (S5.4). No es ni ``skipped`` (que significa «decidió no hacer nada y está
#: bien») ni ``error`` (no falló: no llegó a correr), y por eso tiene nombre
#: propio: mezclarlo con cualquiera de los dos borraría la única información
#: útil del resumen, que es distinguir el paso roto de los que arrastró.
STEP_SKIPPED_DEP = "skipped_por_dependencia"

#: Dependencias explícitas entre pasos canónicos. Ausencia = independiente, que
#: es el caso de once de los quince: un fallo en ``kpi_precompute`` no puede
#: impedir que corran las alertas de vigilancia, y hasta S5.4 tampoco lo hacía
#: —el ejecutor captura por paso—, pero nada lo dejaba escrito.
#:
#: Solo se declara lo que el propio código ya justifica:
#:
#: - ``digests`` ← ``watchlist_notify``: notify **acumula** en
#:   ``pending_digests`` y digests las envía. Con notify roto a mitad, el
#:   digest saldría incompleto Y consumiría su ventana diaria (el lock de
#:   ``_run_periodic`` no se libera al terminar bien), así que el usuario
#:   recibiría un correo con menos coincidencias de las que hubo y ninguno
#:   correcto hasta el día siguiente.
#: - ``tech_signal_merge`` ← ``ml_tecnologias``: el merge existe para sanar el
#:   clobber que ``precompute_ml_tecnologias`` acaba de hacer sobre esas mismas
#:   columnas (ver su docstring). Sin el precompute no hay clobber que sanar, y
#:   el merge escribiría una señal que el siguiente precompute correcto volvería
#:   a pisar.
STEP_DEPS: dict[str, tuple[str, ...]] = {
    "tech_signal_merge": ("ml_tecnologias",),
    "digests": ("watchlist_notify",),
}


def step_tier(name: str) -> StepTier:
    """Severidad declarada de un paso canónico.

    Raises:
        RuntimeError: si el paso no tiene tier. Es el mismo contrato que la
            comprobación de implementación (``_run_<name>``): un paso nuevo en
            ``CANONICAL_STEPS`` sin severidad declarada sería silenciosamente
            bloqueante o silenciosamente advisory según el default que
            eligiéramos, y las dos opciones son una decisión tomada por
            omisión sobre si el job puede salir rojo.
    """
    tier = STEP_TIER.get(name)
    if tier is None:
        raise RuntimeError(
            f"CANONICAL_STEPS contiene '{name}' sin tier declarado en STEP_TIER — "
            "todo paso debe declarar si es 'bloqueante' o 'advisory'"
        )
    return tier


def dependencias_incumplidas(name: str, resultados: dict[str, str]) -> list[str]:
    """Dependencias de ``name`` que no dejaron su insumo en esta pasada.

    Cuenta como incumplida la que terminó en ``error`` y la que a su vez se
    saltó por dependencia: si ``ml_tecnologias`` falla, ``tech_signal_merge`` no
    corre, y cualquier paso que dependiera de él tampoco tendría su insumo.
    Un ``skipped`` legítimo —ventana de cadencia, flag apagado— **no** arrastra:
    ese paso decidió no hacer nada y eso es un estado correcto del sistema.

    Una dependencia que todavía no se ha ejecutado no cuenta: el orden de
    ``CANONICAL_STEPS`` es la única fuente y ahí las dependencias van antes,
    cosa que fija ``test_s5_cierre_dependencias``.
    """
    return [
        dep
        for dep in STEP_DEPS.get(name, ())
        if resultados.get(dep) in (STEP_ERROR, STEP_SKIPPED_DEP)
    ]


def pasos_bloqueantes_fallidos(steps: dict[str, str]) -> list[str]:
    """Pasos que ponen la pasada en rojo: ``error`` **y** ``bloqueante``.

    Un paso desconocido (no está en ``STEP_TIER``) cuenta como bloqueante: si
    alguien mete un paso por fuera del contrato, el fallo se ve.
    """
    return [
        name
        for name, estado in steps.items()
        if estado == STEP_ERROR and STEP_TIER.get(name, "bloqueante") == "bloqueante"
    ]


# `ml_retrain` salió de la lista en 2026-08: vive en
# `.github/workflows/ml-entrenar.yml` (modelo `predictivos`). Entrenaba aquí, dentro de un job
# con `permissions: contents: read`, así que el artefacto no podía publicarse
# en la Release y moría con el runner efímero — dejando filas de
# `model_versions` con un `path` que ningún job posterior podía resolver. El
# workflow nuevo entrena Y publica; duplicarlo aquí volvería a registrar
# versiones irresolubles.


# ---------------------------------------------------------------------------
# Carriles
# ---------------------------------------------------------------------------

# El carril diario corre cada 4h y sus pasos post-ingesta caben en el step de
# cierre, de 20 min; el bulk se dispara a mano (`.github/workflows/scrape-bulk.yml`)
# con 120 min para todo. Un mismo paso canónico puede por tanto permitirse más
# trabajo en un carril que en el otro: los pasos listados en
# ``_LANE_AWARE_STEPS`` reciben ``lane=`` y deciden.
LANE_DAILY = "daily"
LANE_BULK = "bulk"

_LANE_AWARE_STEPS = frozenset({"dlq_retry"})
