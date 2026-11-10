"""El plano de cron como proceso hijo de la API (ADR-033, enmienda 2026-11-09).

``tenderflow-api`` es el único servicio de cómputo que existe en producción. Su
proceso no puede ejecutar la ingesta ni el scoring en un hilo propio, por tres
motivos que un proceso hijo resuelve a la vez:

* **El techo de sentencia.** Con ``APP_PROFILE=api`` cada conexión lleva
  ``statement_timeout`` de 30 s, que protege el pool de las peticiones. El
  cierre de la pasada tiene consultas legítimas de 40-76 s
  (``Settings._relax_batch_statement_timeout``); el hijo arranca con
  ``APP_PROFILE=scraper``, igual que los workflows, y hereda su techo de batch.
* **La imagen.** El proceso de la API sigue sin importar lxml ni scikit-learn
  (``tests/test_unit_api_imagen_slim.py``): solo el hijo los carga, y los
  devuelve al terminar.
* **El aislamiento.** Un job colgado o un pico de memoria del scoring no ocupa
  ni el pool ni los hilos que atienden a los usuarios.

Este módulo no importa el registry de jobs, para que la API lo cargue sin
arrastrar el scraper ni el ML: quien importa ``scheduler.cron_plane`` es el
hijo.

Si el hijo muere, se relanza. Un cron parado con la API contestando el
healthcheck es el modo de fallo que ADR-033 existe para terminar.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 - lanza el propio intérprete con argumentos fijos
import sys
import threading

from observability.logging import get_logger

log = get_logger(__name__)

#: Valor de ``SCHEDULER_PLANE`` que activa el plano (``scheduler.cron_plane.PLANO``).
PLANO = "worker"

#: Perfil del hijo: el de los workflows que hoy ejecutan estos mismos jobs.
PERFIL_DEL_HIJO = "scraper"

#: Pool de conexiones del hijo, por pool (escritura y lectura). Sin esto
#: heredaría los 12 + 12 de la API y entre los dos pasarían del techo del
#: pooler de sesión (``render.yaml``, incidente ``EMAXCONNSESSION`` del
#: 2026-08-24). Dos es lo que el runbook del cutover pedía para el worker.
POOL_DEL_HIJO = "2"

#: Espera antes de relanzar un hijo muerto, y su techo. Se dobla con cada
#: caída: el calendario del plano vive en la memoria del hijo, así que cada
#: relanzado empieza con una ingesta, y un hijo que muere siempre (la imagen
#: sin las dependencias del pipeline, el scoring sin memoria) las encadenaría.
ESPERA_RELANZADO_S = 60.0
ESPERA_RELANZADO_MAX_S = 3600.0

#: Margen para que el hijo salga tras SIGTERM antes de matarlo. Le basta para
#: soltar sus locks (``scheduler.cron_plane.main``); el job en curso no se
#: espera. Corto porque Render da 30 s en total y la API los necesita.
GRACIA_AL_PARAR_S = 3.0


class CronProceso:
    """Lanza ``python -m scheduler.cron_plane`` y lo mantiene vivo."""

    def __init__(self, *, espera_relanzado_s: float = ESPERA_RELANZADO_S) -> None:
        self.espera_relanzado_s = espera_relanzado_s
        self._parar = threading.Event()
        self._proceso: subprocess.Popen[bytes] | None = None

    def _lanzar(self) -> subprocess.Popen[bytes]:
        env = {
            **os.environ,
            "APP_PROFILE": PERFIL_DEL_HIJO,
            "DB_POOL_SIZE": POOL_DEL_HIJO,
            "DB_READ_POOL_SIZE": POOL_DEL_HIJO,
        }
        # Un techo de sentencia puesto a mano para la API llegaría al hijo como
        # valor explícito y le quitaría el de batch que le da su perfil.
        env.pop("DB_STATEMENT_TIMEOUT_MS", None)
        return subprocess.Popen(  # nosec B603 - sin shell, argumentos fijos
            [sys.executable, "-m", "scheduler.cron_plane"], env=env
        )

    def supervisar(self) -> None:
        """Bucle del hilo supervisor: lanza, espera a que muera y relanza."""
        espera = self.espera_relanzado_s
        while not self._parar.is_set():
            try:
                self._proceso = self._lanzar()
            except OSError as exc:
                log.error("cron_proceso_no_arranca", error=str(exc))
            else:
                log.info("cron_proceso_lanzado", pid=self._proceso.pid)
                if self._parar.is_set():
                    # `detener()` llegó mientras se lanzaba y no vio a este hijo.
                    self._proceso.terminate()
                    break
                codigo = self._proceso.wait()
                if self._parar.is_set():
                    break
                log.error(
                    "cron_proceso_caido",
                    pid=self._proceso.pid,
                    codigo=codigo,
                    relanzado_en_s=espera,
                )
            self._parar.wait(espera)
            espera = min(espera * 2, ESPERA_RELANZADO_MAX_S)

    def detener(self) -> None:
        """Para el hijo y deja de relanzarlo. Lo llama el shutdown del lifespan."""
        self._parar.set()
        proceso = self._proceso
        if proceso is None or proceso.poll() is not None:
            return
        proceso.terminate()
        try:
            proceso.wait(timeout=GRACIA_AL_PARAR_S)
        except subprocess.TimeoutExpired:
            # No llegó a soltar su lock: caduca por TTL, y el upsert
            # idempotente retoma por cursor.
            log.warning("cron_proceso_no_salio_a_tiempo", pid=proceso.pid)
            proceso.kill()


def arrancar_en_proceso() -> CronProceso | None:
    """Arranca el plano como proceso hijo si ``SCHEDULER_PLANE=worker``.

    Sin la variable devuelve ``None`` y la API sigue siendo lo que era: el
    cron vive en GitHub Actions y aquí no corre nada programado.
    """
    declarado = os.environ.get("SCHEDULER_PLANE", "").strip()
    if declarado != PLANO:
        log.info("cron_proceso_inactivo", scheduler_plane=declarado or "(sin definir)")
        return None

    cron = CronProceso()
    threading.Thread(target=cron.supervisar, name="tenderflow-cron-supervisor", daemon=True).start()
    return cron
