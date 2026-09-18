"""Tests del plano de cron dentro del worker (ADR-033).

Lo que se fija aquí es lo que el plano promete y no se ve mirando el código
corriendo en producción:

1. **Qué jobs asume.** Exactamente los ``plane="actions"`` del registry. Es la
   afirmación central del ADR: el cutover es una sustitución 1:1 de los
   workflows programados. Si alguien añade un job ``actions`` y el plano no lo
   recoge, ese job deja de correr el día del cutover — silencio, otra vez.
2. **Que no se activa solo.** Sin ``SCHEDULER_PLANE=worker`` el arranque
   devuelve ``None``. Un despliegue del worker no puede convertirse en un
   segundo plano de orquestación por accidente.
3. **Que el lock manda.** Con el lock tomado por otro, el job no se ejecuta;
   con la tabla de locks caída, se ejecuta igual. Las dos mitades importan: la
   primera es la exclusión durante el cutover, la segunda es la decisión
   explícita de fallar ruidosamente en vez de apagarse en silencio.
4. **Que reprograma pase lo que pase.** Un job que falla no puede quedarse
   pidiendo turno en cada vuelta del bucle.

No se prueba aquí el bucle infinito (``run_forever``): lo único suyo es el
``wait`` del evento de parada, y probarlo obliga a dormir. Lo que tiene sustancia
es ``tick()``, que es lo que se ejercita.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest

from scheduler.cron_plane import (
    PLANO,
    PLANOS_ASUMIDOS,
    CronPlane,
    arrancar_en_hilo,
    jobs_del_plano,
    plano_activo,
)
from scheduler.jobs import ScheduledJob, build_default_registry

AHORA = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def _job(nombre: str, *, plane: str = "actions", minutos: float = 60.0) -> ScheduledJob:
    """Job de mentira que solo apunta que lo llamaron."""
    llamadas: list[str] = []

    def _fn() -> dict[str, Any]:
        llamadas.append(nombre)
        return {"llamadas": len(llamadas)}

    job = ScheduledJob(
        name=nombre,
        fn=_fn,
        interval_env=f"TEST_{nombre.upper()}_INTERVAL_MINUTES",
        default_interval_minutes=minutos,
        plane=plane,  # type: ignore[arg-type]
        module=f"tests.{nombre}",
    )
    # El registro de llamadas viaja pegado al job para poder leerlo desde el test.
    object.__setattr__(job, "_llamadas", llamadas)  # dataclass frozen
    return job


def _llamadas(job: ScheduledJob) -> list[str]:
    return list(job._llamadas)  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _sin_lock_real():
    """Por defecto el lock se concede: cada test que quiera otra cosa lo dice."""
    with (
        patch("db.job_locks.acquire", return_value=True),
        patch("db.job_locks.release", return_value=True),
    ):
        yield


# ── 1. Qué jobs asume ───────────────────────────────────────────────────────


def test_asume_exactamente_los_jobs_de_actions():
    registry = [
        _job("uno", plane="actions"),
        _job("dos", plane="pipeline"),
        _job("tres", plane="manual"),
        _job("cuatro", plane="loop"),
        _job("cinco", plane="actions"),
    ]
    assert [j.name for j in jobs_del_plano(registry)] == ["uno", "cinco"]


def test_el_registry_real_declara_al_menos_un_job_de_actions():
    """Guardarraíl del cutover contra el registry de verdad.

    Si esto se vaciara, el plano del worker arrancaría sin nada que hacer y el
    cutover sería un no-op silencioso: el peor resultado posible, porque el
    humano apagaría los workflows creyendo que otro los sustituye.
    """
    asumidos = jobs_del_plano(build_default_registry())
    assert asumidos, "ningún job plane='actions': el plano worker no tendría trabajo"
    assert {j.plane for j in asumidos} <= PLANOS_ASUMIDOS
    # Todo job de Actions declara su `module`: es lo que el checker de paridad
    # busca en los workflows, y lo que permite compararlos uno a uno.
    assert all(j.module for j in asumidos)


# ── 2. No se activa solo ────────────────────────────────────────────────────


def test_no_arranca_sin_la_variable(monkeypatch):
    monkeypatch.delenv("SCHEDULER_PLANE", raising=False)
    assert plano_activo() is False
    assert arrancar_en_hilo() is None


def test_no_arranca_con_el_plano_de_actions(monkeypatch):
    """El caso peligroso: producción tal y como está hoy.

    Desplegar este código sin tocar la variable no debe convertir al worker en
    un segundo plano corriendo junto a los workflows programados.
    """
    monkeypatch.setenv("SCHEDULER_PLANE", "actions")
    assert plano_activo() is False
    assert arrancar_en_hilo() is None


def test_reconoce_su_propio_plano(monkeypatch):
    monkeypatch.setenv("SCHEDULER_PLANE", PLANO)
    assert plano_activo() is True


# ── 3. El lock manda ────────────────────────────────────────────────────────


def test_no_ejecuta_si_otro_tiene_el_lock():
    job = _job("con_lock_ajeno")
    plano = CronPlane([job], poll_segundos=1)
    plano.planificar(AHORA)

    with patch("db.job_locks.acquire", return_value=False) as acquire:
        ejecutados = plano.tick(AHORA)

    assert ejecutados == ["con_lock_ajeno"]  # tocaba, y se dio por atendido
    assert _llamadas(job) == []  # pero no se ejecutó
    assert acquire.call_args.args[0] == "cron:con_lock_ajeno"


def test_ejecuta_igual_si_la_tabla_de_locks_no_responde():
    """Decisión explícita: ruido antes que silencio (ver ``_con_lock``)."""
    job = _job("sin_tabla")
    plano = CronPlane([job], poll_segundos=1)
    plano.planificar(AHORA)

    with (
        patch("db.job_locks.acquire", side_effect=RuntimeError("no such table")),
        patch("db.job_locks.release") as release,
    ):
        plano.tick(AHORA)

    assert _llamadas(job) == ["sin_tabla"]
    # No se libera lo que no se tomó: soltar un lock ajeno dejaría correr a un
    # tercero en paralelo.
    release.assert_not_called()


def test_libera_el_lock_al_terminar():
    job = _job("libera")
    plano = CronPlane([job], poll_segundos=1)
    plano.planificar(AHORA)

    with patch("db.job_locks.release", return_value=True) as release:
        plano.tick(AHORA)

    assert release.call_args.args[0] == "cron:libera"
    assert release.call_args.kwargs["holder"].startswith(f"{PLANO}:")


def test_libera_el_lock_aunque_el_job_falle():
    def _revienta() -> None:
        raise RuntimeError("boom")

    job = ScheduledJob(
        name="revienta",
        fn=_revienta,
        interval_env="TEST_REVIENTA_INTERVAL_MINUTES",
        default_interval_minutes=60,
        plane="actions",
        module="tests.revienta",
    )
    plano = CronPlane([job], poll_segundos=1)
    plano.planificar(AHORA)

    with patch("db.job_locks.release", return_value=True) as release:
        plano.tick(AHORA)

    release.assert_called_once()


# ── 4. Reprogramación ───────────────────────────────────────────────────────


def test_no_ejecuta_antes_de_tiempo():
    job = _job("puntual", minutos=60)
    plano = CronPlane([job], poll_segundos=1)
    plano.planificar(AHORA)

    plano.tick(AHORA)
    assert _llamadas(job) == ["puntual"]

    # Diez minutos después todavía no toca.
    plano.tick(AHORA + timedelta(minutes=10))
    assert _llamadas(job) == ["puntual"]

    # Pasada la hora, sí.
    plano.tick(AHORA + timedelta(minutes=61))
    assert _llamadas(job) == ["puntual", "puntual"]


def test_respeta_el_offset_inicial():
    job = ScheduledJob(
        name="con_offset",
        fn=lambda: None,
        interval_env="TEST_OFFSET_INTERVAL_MINUTES",
        default_interval_minutes=60,
        initial_offset_minutes=30,
        plane="actions",
        module="tests.con_offset",
    )
    plano = CronPlane([job], poll_segundos=1)
    plano.planificar(AHORA)

    assert plano.tick(AHORA) == []
    assert plano.tick(AHORA + timedelta(minutes=31)) == ["con_offset"]


def test_un_job_saltado_por_el_lock_tambien_se_reprograma():
    """Si no se reprogramara, pediría turno en cada vuelta del bucle."""
    job = _job("insistente", minutos=60)
    plano = CronPlane([job], poll_segundos=1)
    plano.planificar(AHORA)

    with patch("db.job_locks.acquire", return_value=False):
        plano.tick(AHORA)

    assert plano.proxima["insistente"] > AHORA


def test_el_intervalo_sale_del_entorno_si_esta(monkeypatch):
    monkeypatch.setenv("TEST_CONFIGURABLE_INTERVAL_MINUTES", "15")
    job = _job("configurable", minutos=60)
    plano = CronPlane([job], poll_segundos=1)

    assert plano.intervalos["configurable"] == timedelta(minutes=15)
