"""Plano de cron dentro del worker de Render (ADR-033).

Qué problema resuelve
---------------------
Hasta aquí el cron de producción vivía **entero** en GitHub Actions: ADR-012
declaró ``SCHEDULER_PLANE`` con dos valores (``actions`` para producción,
``docker`` para el stack local) y los jobs ``plane="actions"`` del registry se
disparan desde workflows programados. Eso deja tres cosas que no se arreglan
con más workflows:

1. **Dónde corre el dato personal.** Los digests, las notificaciones y la
   retención tratan datos de usuarios; ejecutarlos en Actions los procesa en
   infraestructura de GitHub (EE. UU.), que es un subencargado más que declarar
   —y el único que no está en la región del dato (``docs/legal/subencargados.md``)—.
2. **El cron programado se para solo.** GitHub limita y **desactiva** los
   ``schedule:`` de un repositorio sin actividad durante 60 días, y bajo carga
   los retrasa o los salta sin avisar. La forma del fallo es la peor posible:
   silencio. El mismo silencio que ``scripts/check_job_parity.py`` existe para
   detectar en el código, pero del lado de la plataforma, donde el checker no
   llega.
3. **El radio de explosión de CI.** Para que Actions ejecute el cron hay que
   darle las credenciales de la base de datos de producción, de modo que
   cualquier workflow del repositorio —y cualquier acción de terceros que
   alguien añada— corre junto a un secreto con permiso de escritura sobre el
   dato de los clientes.

Qué hace este módulo
--------------------
Le da al proceso ``APP_PROFILE=worker`` —que ya vive en la región de la base de
datos, ya tiene las credenciales y ya responde un healthcheck que Render
vigila— un segundo hilo: el que mira el reloj. Se activa **solo** con
``SCHEDULER_PLANE=worker``.

Esto no rompe ADR-012, lo completa: la regla sigue siendo *un plano dueño por
entorno*. Lo que cambia es que ``SCHEDULER_PLANE`` admite un tercer valor, no
que puedan estar dos activos. La exclusión se sostiene en dos sitios:

* **Declarativo.** ``scheduler/loop.py`` sigue negándose a arrancar si no lee
  ``docker``, y este plano se niega si no lee ``worker``. Un entorno mal
  configurado no arranca ninguno de los dos, que es preferible a arrancar los
  dos.
* **Operativo.** Cada ejecución toma un lock con nombre y TTL en
  ``db.job_locks`` (``cron:<job>``). Durante la ventana del cutover —mientras
  los workflows programados siguen existiendo pero ya no deberían mandar— el
  segundo corredor encuentra el lock tomado y se queda en no-op. Es el mismo
  primitivo que usa la pipeline canónica (``scheduler/pipeline_runs.py``).

Qué jobs asume, y por qué esos
------------------------------
Exactamente los declarados ``plane="actions"``: los que hoy ejecuta un workflow
**programado**. El cutover es entonces una sustitución 1:1, verificable.

Los otros tres planos se quedan donde están, y no por omisión:

* ``manual`` no corre solo **a propósito** (``recent_bulk`` desde 2026-08).
  Programarlo aquí desharía esa decisión sin que nadie la revisara.
* ``loop`` es del stack de Docker Compose por decisión explícita.
* ``pipeline`` lo ejecuta la pipeline canónica dentro de ``daily_atom``;
  programarlo además aquí lo correría dos veces por pasada.

Hilos y no procesos
-------------------
``scheduler/loop.py`` manda los jobs ``heavy`` a un ``ProcessPoolExecutor``
porque un proceso sí se puede matar al vencer el timeout. Aquí se ejecuta todo
en hilos, incluidos los pesados, y es una elección consciente: el worker es un
``type: web`` de Render cuyo healthcheck tiene que seguir contestando, y un
segundo proceso con el intérprete y el modelo cargados dobla la memoria
residente del contenedor. Un OOM se lleva por delante el healthcheck, y con él
el servicio entero — un precio mucho más alto que el que se paga.

Lo que se pierde: un job colgado no se puede cancelar. Lo que queda: el timeout
sigue registrándose y alertando (``_run_job``), y el guardarraíl de solape
impide que se acumule uno nuevo encima. Es exactamente el trato que ya tienen
los jobs ligeros del loop de Docker y los handlers de la cola a demanda
(``scheduler/worker.py``).
"""

from __future__ import annotations

import os
import socket
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from observability.logging import get_logger
from scheduler.jobs import ScheduledJob, build_default_registry
from scheduler.loop import _backoff_interval, _env_int, _resolve_interval, _run_job

log = get_logger(__name__)

#: Valor de ``SCHEDULER_PLANE`` que activa este plano.
PLANO = "worker"

#: Planos del registry que este plano asume. Ver el docstring del módulo.
PLANOS_ASUMIDOS: frozenset[str] = frozenset({"actions"})

#: Prefijo de los locks en ``job_locks``. Con prefijo y no con el nombre pelado
#: para no chocar con los que toma la pipeline canónica, que usan el nombre del
#: paso.
PREFIJO_LOCK = "cron:"


def plano_declarado() -> str:
    """Valor de ``SCHEDULER_PLANE``, o cadena vacía si nadie lo puso."""
    return os.environ.get("SCHEDULER_PLANE", "").strip()


def plano_activo() -> bool:
    """True si este entorno declara al worker como dueño del cron."""
    return plano_declarado() == PLANO


def jobs_del_plano(registry: list[ScheduledJob] | None = None) -> list[ScheduledJob]:
    """Jobs del registry que este plano ejecuta, en el orden del registry."""
    return [j for j in (registry or build_default_registry()) if j.plane in PLANOS_ASUMIDOS]


def _holder() -> str:
    """Identidad del proceso en el lock. Sirve para diagnosticar quién lo tiene."""
    return f"{PLANO}:{socket.gethostname()}:{os.getpid()}"


def _con_lock(nombre: str, ttl_s: int, fn: Callable[[], Any]) -> bool:
    """Ejecuta ``fn`` bajo el lock ``cron:<nombre>``. False si no se pudo tomar.

    Si la tabla de locks no se puede leer **se ejecuta igual**, y con un aviso.
    Es la decisión menos mala de las dos: si la base de datos no responde, el
    job va a fallar por su cuenta y se verá; si en cambio se tratara el error
    como «otro lo tiene», el plano de cron se apagaría en silencio, que es
    justo el modo de fallo que ADR-033 viene a terminar.
    """
    from db.job_locks import acquire, release

    holder = _holder()
    clave = f"{PREFIJO_LOCK}{nombre}"
    try:
        tomado = acquire(clave, ttl_seconds=ttl_s, holder=holder)
    except Exception as exc:
        log.warning("cron_plane_lock_indisponible", job=nombre, error=str(exc), exc_info=True)
        tomado = True
        holder = ""  # no es nuestro: no intentamos liberarlo al terminar

    if not tomado:
        log.info("cron_plane_job_saltado_por_lock", job=nombre, lock=clave)
        return False

    try:
        return _run_job(nombre, fn, heavy=False)
    finally:
        if holder:
            try:
                release(clave, holder=holder)
            except Exception as exc:
                # El TTL lo suelta igualmente; no vale la pena tumbar la pasada.
                log.warning("cron_plane_lock_no_liberado", job=nombre, error=str(exc))


class CronPlane:
    """El reloj del worker: decide qué toca y lo ejecuta.

    Se construye con el registry ya resuelto para que las pruebas puedan
    inyectar dos jobs de mentira en vez de arrastrar el registry real, que
    importa scraper y ML.
    """

    def __init__(
        self,
        registry: list[ScheduledJob] | None = None,
        *,
        poll_segundos: int | None = None,
    ) -> None:
        self.jobs = jobs_del_plano(registry)
        self.poll_segundos = poll_segundos or _env_int("SCHEDULER_POLL_SECONDS", 60)
        self.intervalos: dict[str, timedelta] = {j.name: _resolve_interval(j) for j in self.jobs}
        self.proxima: dict[str, datetime] = {}
        self._parar = threading.Event()

    def planificar(self, ahora: datetime | None = None) -> None:
        """Fija la primera ejecución de cada job respetando su offset inicial."""
        arranque = ahora or datetime.now(UTC)
        self.proxima = {
            j.name: arranque + timedelta(minutes=j.initial_offset_minutes) for j in self.jobs
        }
        log.info(
            "cron_plane_planificado",
            plano=PLANO,
            jobs=[j.name for j in self.jobs],
            intervalos_min={n: int(iv.total_seconds() // 60) for n, iv in self.intervalos.items()},
        )

    def vencidos(self, ahora: datetime) -> list[ScheduledJob]:
        """Jobs cuya próxima ejecución ya pasó, en el orden del registry."""
        return [j for j in self.jobs if ahora >= self.proxima.get(j.name, ahora)]

    def tick(self, ahora: datetime | None = None) -> list[str]:
        """Ejecuta lo que toque y reprograma. Devuelve los nombres ejecutados.

        Reprograma **aunque el job falle o lo salte el lock**: lo contrario
        dejaría el job pidiendo turno en cada vuelta del bucle, que con un
        fallo permanente es una tormenta de alertas cada ``poll_segundos``. El
        backoff exponencial de ``_backoff_interval`` ya separa los reintentos.
        """
        instante = ahora or datetime.now(UTC)
        ejecutados: list[str] = []
        ttl_s = _env_int("SCHEDULER_JOB_TIMEOUT_SECONDS", 600, min_value=30)
        for job in self.vencidos(instante):
            _con_lock(job.name, ttl_s, job.fn)
            ejecutados.append(job.name)
            self.proxima[job.name] = instante + _backoff_interval(
                job.name, self.intervalos[job.name]
            )
        return ejecutados

    def detener(self) -> None:
        """Pide la parada; el bucle sale en cuanto termine el job en curso."""
        self._parar.set()

    def run_forever(self) -> None:
        """Bucle del plano. No lanza: un ciclo roto no puede matar el hilo.

        Si este hilo muriera, el worker seguiría contestando el healthcheck de
        Render con el cron parado — vivo para la plataforma y mudo para el
        trabajo, que es el peor de los dos estados posibles. Es la misma razón
        por la que ``scheduler/worker.py::run_forever`` traga sus excepciones.
        """
        self.planificar()
        log.info("cron_plane_arrancado", plano=PLANO, jobs=[j.name for j in self.jobs])
        while not self._parar.is_set():
            try:
                self.tick()
            except Exception as exc:
                log.warning("cron_plane_ciclo_fallido", error=str(exc), exc_info=True)
            self._parar.wait(self.poll_segundos)
        log.info("cron_plane_detenido", plano=PLANO)


def arrancar_en_hilo() -> CronPlane | None:
    """Arranca el plano en un hilo daemon si este entorno lo declara dueño.

    Devuelve ``None`` —y deja constancia de por qué— cuando ``SCHEDULER_PLANE``
    dice otra cosa. Lo llama el lifespan de ``api/app.py`` con
    ``APP_PROFILE=worker``; sin la variable, el worker sigue siendo lo que era
    antes de ADR-033: el consumidor de la cola a demanda y nada más.
    """
    if not plano_activo():
        log.info(
            "cron_plane_inactivo",
            scheduler_plane=plano_declarado() or "(sin definir)",
            hint="exportá SCHEDULER_PLANE=worker para que este proceso asuma el cron (ADR-033)",
        )
        return None

    plano = CronPlane()
    hilo = threading.Thread(target=plano.run_forever, name="tenderflow-cron", daemon=True)
    hilo.start()
    return plano
