"""Carril diario completo: PLACSP → seis conectores → cierre → healthcheck.

Es la misma pasada que ``.github/workflows/scrape-daily.yml``, paso a paso, para
que el plano de cron del worker (ADR-033) pueda sustituir al workflow 1:1. Hasta
2026-10 este job solo llamaba a ``run_daily_pipeline()`` —PLACSP más el cierre—
y los seis conectores multi-fuente existían únicamente como steps del workflow:
apagarlo en el cutover habría dejado de ingerir TED, Galicia, Euskadi, las
adjudicaciones vigiladas, PSCP y TACRC sin que nada fallara.

Lo que conserva del workflow, y cómo:

- **Orden.** Los conectores ingieren *antes* del cierre (``con_cierre=False`` y
  después :func:`~scheduler.pipeline_runs.run_post_ingestion_only`), para que la
  vista pública, los agregados y las alertas incluyan su corpus del ciclo.
- **Aislamiento.** Un conector que falla no detiene a los demás ni al cierre
  (``continue-on-error``), y una ingesta de PLACSP que falla tampoco
  (``!cancelled()``): el cierre corre con lo que sí entró.
- **Presupuesto por conector**, el ``timeout-minutes`` de su step. En Actions
  se mata el proceso; en un hilo no se puede, así que agotar el presupuesto
  significa *no esperarlo más*: se registra, el cierre sigue y el hilo termina
  por su cuenta. Mientras siga vivo, la pasada siguiente salta ese conector en
  vez de apilarle otro encima.
- **Healthcheck con alerta** al final, pase lo que pase antes (``always()``).

Lo que no copia es el código de salida. Las fallas que el workflow pone en rojo
—ingesta con status de error, cierre con pasos bloqueantes en error— ya avisan
por correo desde la pipeline; relanzarlas aquí mandaría el aviso dos veces y,
peor, activaría el backoff del plano, que espacia el job: una caída de PLACSP
dejaría a las otras seis fuentes ingiriendo cada 8 h en vez de cada 4. Solo se
relanza una excepción inesperada de la ingesta, como hacía el job antes.

``tests/test_daily_atom.py`` compara la lista de conectores y sus presupuestos
con los steps del YAML: mientras existan los dos, no pueden divergir.
"""

from __future__ import annotations

import importlib
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from observability.logging import get_logger
from observability.runtime_metrics import scheduler_job_duration_seconds, scheduler_job_total

log = get_logger(__name__)


@dataclass(frozen=True)
class Conector:
    """Un conector del carril diario.

    Attributes:
        nombre: El ``id`` de su step en ``scrape-daily.yml``.
        modulo: Lo que ese step ejecuta con ``python -m``. Expone
            ``ejecutar()``: una pasada sin abrir ni cerrar la BD, porque el
            worker comparte el pool con la cola.
        presupuesto_s: El ``timeout-minutes`` del step, en segundos.
    """

    nombre: str
    modulo: str
    presupuesto_s: int

    def ejecutar(self) -> object:
        resultado: object = importlib.import_module(self.modulo).ejecutar()
        return resultado


#: Los conectores de ``scrape-daily.yml``, en el orden de sus steps.
CONECTORES: tuple[Conector, ...] = (
    Conector("ted", "scraper.connectors.ted", 10 * 60),
    Conector("galicia", "scraper.connectors.galicia", 5 * 60),
    Conector("euskadi", "scraper.connectors.euskadi", 5 * 60),
    Conector("watched_awards", "scraper.connectors.watched_company_awards", 5 * 60),
    Conector("pscp", "scraper.connectors.pscp", 10 * 60),
    Conector("tacrc", "scraper.connectors.tacrc", 10 * 60),
)

#: Hilo de la última pasada de cada conector: el guardarraíl de solape.
_hilos: dict[str, threading.Thread] = {}


def _errores(resultado: object) -> int:
    """Errores que declara una pasada; ``None`` es fuente apagada o sin trabajo."""
    if resultado is None:
        return 0
    if isinstance(resultado, dict):
        return int(resultado.get("errores") or 0)
    return int(getattr(resultado, "errores", 0) or 0)


def _correr_conector(conector: Conector) -> str:
    """Ejecuta un conector con su presupuesto. Devuelve el estado de la pasada.

    El estado usa el vocabulario de ``scheduler_job_total``: ``success``,
    ``error`` (lanzó o declaró errores, que es cuando su CLI sale con 1),
    ``timeout`` (agotó el presupuesto y se dejó de esperar) o ``skipped`` (el
    hilo de la pasada anterior sigue vivo).
    """
    metrica = f"daily_atom:{conector.nombre}"
    previo = _hilos.get(conector.nombre)
    if previo is not None and previo.is_alive():
        log.warning("daily_atom_conector_saltado_por_solape", conector=conector.nombre)
        scheduler_job_total.labels(job=metrica, status="skipped").inc()
        return "skipped"

    estado: list[str] = []

    def _objetivo() -> None:
        try:
            resultado = conector.ejecutar()
        except Exception as exc:
            log.warning(
                "daily_atom_conector_fallido",
                conector=conector.nombre,
                error=str(exc),
                exc_info=True,
            )
            estado.append("error")
            return
        errores = _errores(resultado)
        log.info(
            "daily_atom_conector_completado",
            conector=conector.nombre,
            errores=errores,
            sin_trabajo=resultado is None,
        )
        estado.append("error" if errores else "success")

    inicio = time.monotonic()
    hilo = threading.Thread(target=_objetivo, name=metrica, daemon=True)
    _hilos[conector.nombre] = hilo
    hilo.start()
    hilo.join(conector.presupuesto_s)
    if hilo.is_alive():
        log.error(
            "daily_atom_conector_presupuesto_agotado",
            conector=conector.nombre,
            presupuesto_s=conector.presupuesto_s,
        )
        resultado_pasada = "timeout"
    else:
        resultado_pasada = estado[0] if estado else "error"
    scheduler_job_total.labels(job=metrica, status=resultado_pasada).inc()
    scheduler_job_duration_seconds.labels(job=metrica).observe(time.monotonic() - inicio)
    return resultado_pasada


def _healthcheck() -> str:
    """El healthcheck post-pasada con alerta. Nunca lanza: va en un ``finally``."""
    from scheduler.healthcheck import comprobar_y_alertar

    try:
        estado: str = comprobar_y_alertar()["status"]
    except Exception as exc:
        log.error("daily_atom_healthcheck_fallido", error=str(exc), exc_info=True)
        return "error"
    return estado


def run(*, conectores: Sequence[Conector] = CONECTORES) -> dict[str, Any]:
    """Ejecuta la pasada completa del carril diario. Ver el docstring del módulo."""
    from scheduler.pipeline_runs import LANE_DAILY, run_daily_pipeline, run_post_ingestion_only

    fallo_ingesta: Exception | None = None
    try:
        ingesta = run_daily_pipeline(con_cierre=False)
        estado_ingesta = str(ingesta.get("ingestion_result", {}).get("status", "ok"))
    except Exception as exc:
        log.error("daily_atom_ingesta_fallida", error=str(exc), exc_info=True)
        fallo_ingesta = exc
        estado_ingesta = "error"

    estados = {c.nombre: _correr_conector(c) for c in conectores}
    fallidos = sorted(nombre for nombre, estado in estados.items() if estado != "success")
    if fallidos:
        log.warning("daily_atom_conectores_con_fallo", conectores=fallidos, estados=estados)

    try:
        cierre = run_post_ingestion_only(lane=LANE_DAILY)
    finally:
        salud = _healthcheck()

    resumen = {
        "ingesta": estado_ingesta,
        "conectores": estados,
        "cierre": cierre.get("status"),
        "healthcheck": salud,
    }
    log.info("daily_atom_pasada_completada", **resumen)
    if fallo_ingesta is not None:
        raise fallo_ingesta
    return resumen
