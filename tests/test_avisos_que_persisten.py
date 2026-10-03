"""Un aviso cuya causa persiste sale una vez al día, no en cada pasada.

Del 2026-09-29 al 2026-10-03 el paso ``ml_scoring`` falló en catorce pasadas
seguidas de ``scrape-daily``. Cada una mandó su ``[ERROR] [pipeline] paso
ml_scoring falló`` y, detrás, un ``[WARN] Healthcheck`` con los mismos tres
avisos de siempre: una docena de correos al día diciendo lo mismo, y cuatro días
sin que nadie abriera el que importaba. Detectar no era el problema; el buzón
enseñaba a no leer.

Lo que se fija aquí es el contrato con quien lee el buzón:

- la **primera** vez que algo se rompe, sale;
- mientras siga igual, un recordatorio al día;
- si **cambia** lo que el aviso dice —otro paso, otro síntoma—, sale al momento;
- si se arregla y vuelve a romperse, sale al momento.

Sin BD: ``db.job_locks`` se sustituye por una tabla en memoria con su misma
semántica de ventana (un lock vivo rechaza al siguiente).
"""

from __future__ import annotations

from collections.abc import Iterable
from unittest.mock import MagicMock, patch

import pytest

from scheduler.pipeline_runs import CANONICAL_STEPS


class _TablaDeLocks:
    """``db.job_locks`` en memoria. No caduca nada: un test dura menos que el TTL."""

    def __init__(self) -> None:
        self.vivos: dict[str, tuple[str, int]] = {}

    def acquire(self, name: str, ttl_seconds: int = 600, holder: str = "") -> bool:
        if name in self.vivos:
            return False
        self.vivos[name] = (holder, ttl_seconds)
        return True

    def release(self, name: str, holder: str = "") -> bool:
        return self.release_many([name], holder=holder) == 1

    def release_many(self, names: Iterable[str], holder: str = "") -> int:
        borrados = 0
        for name in names:
            if self.vivos.get(name, ("", 0))[0] == holder and name in self.vivos:
                del self.vivos[name]
                borrados += 1
        return borrados


@pytest.fixture()
def locks(monkeypatch) -> _TablaDeLocks:
    import db.job_locks as job_locks

    tabla = _TablaDeLocks()
    monkeypatch.setattr(job_locks, "acquire", tabla.acquire)
    monkeypatch.setattr(job_locks, "release", tabla.release)
    monkeypatch.setattr(job_locks, "release_many", tabla.release_many)
    return tabla


@pytest.fixture()
def buzon(monkeypatch, locks: _TablaDeLocks) -> list[str]:
    """Los asuntos de los correos que habrían llegado, en orden."""
    from config import settings

    monkeypatch.setattr(settings, "ALERT_MIN_LEVEL", "warn")
    asuntos: list[str] = []

    def _send_smtp(level, title, body, context, *, to_addr=None) -> bool:
        asuntos.append(title)
        return True

    monkeypatch.setattr("observability.alerts._send_smtp", _send_smtp)
    return asuntos


def _pasada(**pasos_rotos: Exception) -> dict[str, str]:
    """Un cierre de pasada en línea con los quince pasos de pega; algunos, rotos."""
    from scheduler.pipeline_runs import _run_post_ingestion_steps

    objetivos: dict[str, object] = {f"_run_{name}": MagicMock() for name in CANONICAL_STEPS}
    for nombre, error in pasos_rotos.items():
        objetivos[f"_run_{nombre}"] = MagicMock(side_effect=error)
    with patch.multiple("scheduler.pipeline_runs", **objetivos):
        return _run_post_ingestion_steps()


# ---------------------------------------------------------------------------
# Pasos del cierre de pasada
# ---------------------------------------------------------------------------


def test_un_paso_que_sigue_roto_avisa_una_vez_y_no_en_cada_pasada(buzon: list[str]) -> None:
    for _ in range(6):  # un día de `scrape-daily`, que corre cada 4 h
        _pasada(ml_scoring=RuntimeError("el sha256 no coincide"))

    assert buzon == ["[pipeline] paso ml_scoring falló"]


def test_otro_paso_que_se_rompe_avisa_aunque_el_primero_siga_en_ventana(
    buzon: list[str],
) -> None:
    _pasada(ml_scoring=RuntimeError("a"))
    _pasada(ml_scoring=RuntimeError("a"), kpi_precompute=RuntimeError("b"))

    assert buzon == ["[pipeline] paso ml_scoring falló", "[pipeline] paso kpi_precompute falló"]


def test_un_paso_que_se_recupera_y_vuelve_a_romperse_avisa_al_momento(
    buzon: list[str],
) -> None:
    _pasada(ml_scoring=RuntimeError("a"))
    _pasada()
    _pasada(ml_scoring=RuntimeError("a"))

    assert buzon == ["[pipeline] paso ml_scoring falló"] * 2


def test_la_ventana_del_aviso_de_un_paso_deja_pasar_el_recordatorio_diario(
    buzon: list[str], locks: _TablaDeLocks
) -> None:
    """22 h, no 24: la pasada cae cada día a la misma hora con minutos de holgura.

    Con 24 h justas, la pasada del día siguiente llega unos minutos antes de que
    caduque la ventana y el recordatorio se va a la de cuatro horas después.
    """
    _pasada(ml_scoring=RuntimeError("a"))

    (_, ttl) = locks.vivos["alert:pipeline_step:ml_scoring"]
    assert 20 * 3600 < ttl < 24 * 3600


def test_cerrar_las_ventanas_de_los_pasos_recuperados_cuesta_un_solo_viaje(
    buzon: list[str], locks: _TablaDeLocks
) -> None:
    """Los runners están en EE. UU. y la BD en la UE: cada viaje son ~100 ms."""
    import db.job_locks as job_locks

    with patch.object(job_locks, "release_many", wraps=locks.release_many) as soltar:
        _pasada()

    assert soltar.call_count == 1
    assert len(soltar.call_args.args[0]) == len(CANONICAL_STEPS)


def test_que_falle_el_cierre_de_ventanas_no_tumba_la_pasada(buzon: list[str]) -> None:
    import db.job_locks as job_locks

    with patch.object(job_locks, "release_many", side_effect=RuntimeError("db caída")):
        resultados = _pasada()

    assert set(resultados.values()) == {"ok"}


# ---------------------------------------------------------------------------
# Healthcheck degradado
# ---------------------------------------------------------------------------


def _healthcheck(buzon: list[str], estado: str, warnings: list[str], errors: list[str]) -> int:
    from scheduler.healthcheck import main

    informe = {"status": estado, "warnings": warnings, "errors": errors, "info": {}, "checks": []}
    with (
        patch("sys.argv", ["healthcheck", "--alert"]),
        patch("scheduler.healthcheck.run_check", return_value=informe),
        patch("scheduler.healthcheck.configure_logging"),
    ):
        return main()


_AVISOS_DE_SIEMPRE = [
    "dlq_above_threshold:53",
    "empresa_resolution_below_threshold:30.14%",
    "canonicas_sin_registro_de_refresco",
]


def test_un_degradado_que_no_cambia_avisa_una_vez(buzon: list[str]) -> None:
    for _ in range(10):  # seis pasadas de scrape más cuatro healthchecks, cada día
        _healthcheck(buzon, "degraded", _AVISOS_DE_SIEMPRE, [])

    assert buzon == ["Healthcheck tenderflow"]


def test_que_solo_cambie_la_cifra_de_un_aviso_no_es_un_estado_nuevo(buzon: list[str]) -> None:
    _healthcheck(buzon, "degraded", _AVISOS_DE_SIEMPRE, [])
    _healthcheck(
        buzon,
        "degraded",
        [
            "canonicas_sin_registro_de_refresco",
            "empresa_resolution_below_threshold:31.02%",
            "dlq_above_threshold:57",
        ],
        [],
    )

    assert len(buzon) == 1


def test_un_aviso_nuevo_en_el_degradado_sale_al_momento(buzon: list[str]) -> None:
    _healthcheck(buzon, "degraded", _AVISOS_DE_SIEMPRE, [])
    _healthcheck(buzon, "degraded", [*_AVISOS_DE_SIEMPRE, "canonicas_stale:12.5h"], [])

    assert len(buzon) == 2


def test_otra_fuente_atrasada_es_un_estado_nuevo(buzon: list[str]) -> None:
    """El sufijo de `fuente_atrasada:` es un nombre, no una cifra: forma parte del aviso."""
    _healthcheck(buzon, "degraded", ["fuente_atrasada:ted"], [])
    _healthcheck(buzon, "degraded", ["fuente_atrasada:pscp"], [])

    assert len(buzon) == 2


def test_un_estado_critico_no_se_calla_nunca(buzon: list[str]) -> None:
    for _ in range(3):
        codigo = _healthcheck(buzon, "critical", [], ["last_run_failed:r-1"])

    assert len(buzon) == 3
    assert codigo == 2
