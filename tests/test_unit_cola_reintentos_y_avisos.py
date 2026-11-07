"""Cola de trabajo: qué se reintenta, la valla del cierre y los avisos de cola parada.

Diagnóstico del 2026-11-07 sobre producción: de 24 ``ficha_pliego`` fallidas,
18 eran causas que el backoff no cura (sin pliegos, pliego sin publicar,
modelo retirado) y gastaron tres intentos cada una; dos más eran la salida del
modelo cortada por ``max_tokens``. Ninguna alerta miraba la cola a demanda.
Las garantías de Postgres (valla, ``atascados``) se prueban en
``tests/test_s5_cola.py``, que es de integración.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from llm.json_utils import extract_json_object_admitiendo_corte
from services import jobs
from services.jobs import TIPO_FICHA_PLIEGO, Job, JobSinReintento

# ── Salida del modelo cortada por max_tokens ─────────────────────────────────


def test_un_json_completo_no_cuenta_como_cortado() -> None:
    assert extract_json_object_admitiendo_corte('{"a": [1, 2]}') == ({"a": [1, 2]}, False)


def test_un_json_cortado_conserva_los_elementos_completos() -> None:
    completo = {"award_criteria": [{"name": "precio", "w": 60}, {"name": "calidad", "w": 40}]}
    texto = json.dumps(completo)
    # Cortado a media cadena del segundo criterio, como lo deja el tope de tokens.
    cortado = texto[: texto.rindex('"calidad"') + 4]

    objeto, fue_cortado = extract_json_object_admitiendo_corte(cortado)

    assert fue_cortado is True
    assert objeto == {"award_criteria": [{"name": "precio", "w": 60}]}


def test_las_llaves_dentro_de_una_cadena_no_cierran_nada() -> None:
    texto = '{"facts": [{"quote": "cláusula {3} \\"plazo\\""}, {"quote": "sin cerr'

    objeto, fue_cortado = extract_json_object_admitiendo_corte(texto)

    assert fue_cortado is True
    assert objeto == {"facts": [{"quote": 'cláusula {3} "plazo"'}]}


def test_un_corte_sin_ningun_elemento_completo_sigue_fallando() -> None:
    with pytest.raises(ValueError):
        extract_json_object_admitiendo_corte('{"a": "}", "b": "a medi')


# ── procesar_uno: qué se reintenta y con qué valla ─────────────────────────


def _fila(job_id: int = 7, intentos: int = 1) -> dict[str, Any]:
    ahora = datetime.now(UTC)
    return {
        "id": job_id,
        "tipo": TIPO_FICHA_PLIEGO,
        "payload_json": json.dumps({"licitacion_id": "EXP-1", "model": "m"}),
        "organization_id": None,
        "estado": "running",
        "intentos": intentos,
        "run_after": ahora,
        "locked_by": "w",
        "locked_at": ahora,
        "resultado_json": None,
        "error_detail": None,
        "created_at": ahora,
        "updated_at": ahora,
    }


def _repo_con_un_job() -> MagicMock:
    ahora = datetime.now(UTC)
    cierre = {"tipo": TIPO_FICHA_PLIEGO, "run_after": ahora, "locked_at": ahora, "ahora": ahora}
    repo = MagicMock()
    repo.reclamar.return_value = _fila()
    repo.marcar_fallido.return_value = cierre
    repo.reprogramar.return_value = cierre
    repo.marcar_terminado.return_value = cierre
    return repo


def test_lo_que_el_handler_declara_sin_reintento_queda_failed_al_primer_intento() -> None:
    repo = _repo_con_un_job()
    with (
        patch.object(jobs, "_repo", repo),
        patch.object(jobs, "ejecutar", side_effect=JobSinReintento("sin pliegos")),
    ):
        jobs.procesar_uno("w")

    repo.reprogramar.assert_not_called()
    repo.marcar_fallido.assert_called_once()
    assert repo.marcar_fallido.call_args.kwargs["locked_by"] == "w"


def test_un_fallo_corriente_se_reprograma_con_la_valla_del_consumidor() -> None:
    repo = _repo_con_un_job()
    with (
        patch.object(jobs, "_repo", repo),
        patch.object(jobs, "ejecutar", side_effect=RuntimeError("proveedor caído")),
    ):
        jobs.procesar_uno("w")

    repo.marcar_fallido.assert_not_called()
    assert repo.reprogramar.call_args.kwargs["locked_by"] == "w"


def test_el_ack_del_consumidor_lleva_su_valla() -> None:
    repo = _repo_con_un_job()
    with patch.object(jobs, "_repo", repo), patch.object(jobs, "ejecutar", return_value={}):
        jobs.procesar_uno("w")

    assert repo.marcar_terminado.call_args.kwargs["locked_by"] == "w"


def test_un_cierre_cuyo_lock_ya_no_es_suyo_no_se_cuenta() -> None:
    """La valla no aplicó (``None``): ni métricas ni «job_terminado»."""
    repo = MagicMock()
    repo.marcar_terminado.return_value = None
    with (
        patch.object(jobs, "_repo", repo),
        patch.object(jobs, "_medir_cierre") as medir,
    ):
        jobs.ack(7, {"x": 1}, worker_id="w")

    medir.assert_not_called()


# ── El handler de la ficha ──────────────────────────────────────────────────


def _job_ficha() -> Job:
    ahora = datetime.now(UTC)
    return Job(
        id=1,
        tipo=TIPO_FICHA_PLIEGO,
        payload={"licitacion_id": "EXP-1", "model": "m"},
        organization_id=None,
        estado="running",
        intentos=1,
        run_after=ahora,
        locked_by="w",
        locked_at=ahora,
        resultado=None,
        error_detail=None,
        created_at=ahora,
        updated_at=ahora,
    )


@pytest.mark.parametrize(
    ("reintentable", "esperada"), [(True, RuntimeError), (False, JobSinReintento)]
)
def test_el_handler_de_la_ficha_solo_pide_reintento_si_puede_servir(
    reintentable: bool, esperada: type[Exception]
) -> None:
    from scheduler.worker import ejecutar_ficha_pliego

    ficha = MagicMock(status="failed", error_detail="sin pliegos")
    with (
        patch("services.rag.fact_sheet.run_background_extraction", return_value=reintentable),
        patch("services.rag.fact_sheet.get_fact_sheet", return_value=ficha),
        pytest.raises(esperada, match="sin pliegos") as error,
    ):
        ejecutar_ficha_pliego(_job_ficha())

    assert isinstance(error.value, JobSinReintento) is (not reintentable)


# ── run_background_extraction clasifica el fallo ───────────────────────────


def _clasificar(error: Exception) -> bool:
    from services.rag import fact_sheet as fs

    with (
        patch.object(fs, "extract_fact_sheet_on_demand", side_effect=error),
        patch.object(fs, "TenderFactSheetsRepository"),
        patch.object(fs, "clear_extraction_running"),
    ):
        return fs.run_background_extraction("EXP-1", model="m")


def test_sin_pliegos_no_merece_reintento() -> None:
    from services.rag.fact_sheet import SinPaginasError

    assert _clasificar(SinPaginasError("sin pliegos", licitacion_id="EXP-1")) is False


def test_con_el_breaker_de_placsp_abierto_si_merece_reintento() -> None:
    from services.rag.fact_sheet import SinPaginasError

    error = SinPaginasError("PLACSP no responde", licitacion_id="EXP-1", reintentable=True)
    assert _clasificar(error) is True


def test_un_modelo_retirado_no_merece_reintento() -> None:
    from llm.providers import LLMModelUnavailableError

    assert _clasificar(LLMModelUnavailableError(model="m", status_code=410)) is False


def test_un_fallo_del_proveedor_si_merece_reintento() -> None:
    assert _clasificar(TimeoutError("stream lento")) is True


# ── Healthcheck: la cola a demanda que nadie mueve ─────────────────────────


def _healthcheck_cola(
    atascados: Any,
) -> tuple[list[dict[str, object]], list[str], dict[str, object]]:
    from scheduler.healthcheck import _incorporar_cola_jobs

    checks: list[dict[str, object]] = []
    warnings: list[str] = []
    info: dict[str, object] = {}
    with patch("db.repositories.jobs.JobsRepository.atascados", **atascados):
        _incorporar_cola_jobs(checks, warnings, info)
    return checks, warnings, info


def test_una_cola_a_demanda_al_dia_no_avisa() -> None:
    checks, warnings, _ = _healthcheck_cola({"return_value": []})

    assert warnings == []
    assert checks == [{"name": "jobs_cola_a_demanda_al_dia", "ok": True}]


def test_jobs_atascados_degradan_y_dicen_cuales() -> None:
    fila = {"tipo": TIPO_FICHA_PLIEGO, "pendientes": 3, "sin_barrer": 1, "mas_antiguo_s": 5400}
    checks, warnings, info = _healthcheck_cola({"return_value": [fila]})

    assert warnings == ["jobs_atascados:4"]
    assert checks == [{"name": "jobs_cola_a_demanda_al_dia", "ok": False}]
    # Plano: el correo de alerta descarta los valores dict de `info`.
    assert info["jobs_atascados"] == (
        "ficha_pliego: 3 sin reclamar, 1 con lock caducado, el más antiguo hace 90 min"
    )


def test_si_no_se_puede_medir_la_cola_se_dice() -> None:
    _, warnings, info = _healthcheck_cola({"side_effect": RuntimeError("BD caída")})

    assert warnings == ["jobs_atascados_no_medido"]
    assert "BD caída" in str(info["jobs_atascados_error"])


def test_el_healthcheck_mira_solo_los_tipos_a_demanda() -> None:
    from scheduler.healthcheck import _incorporar_cola_jobs
    from services.jobs import TIPO_PASO_PIPELINE, TIPOS_A_DEMANDA

    with patch("db.repositories.jobs.JobsRepository.atascados", return_value=[]) as consulta:
        _incorporar_cola_jobs([], [], {})

    tipos = consulta.call_args.kwargs["tipos"]
    assert set(tipos) == set(TIPOS_A_DEMANDA)
    assert TIPO_PASO_PIPELINE not in tipos


# ── El cierre que murió a mitad ─────────────────────────────────────────────


def test_el_aviso_de_cierre_interrumpido_nombra_los_pasos() -> None:
    from scheduler.pipeline_cierre import _avisar_cierre_interrumpido

    with patch("observability.alerts.notify") as notify:
        _avisar_cierre_interrumpido(["dlq_retry", "drift_checks"], ["dlq_retry"])

    cuerpo = notify.call_args.kwargs["body"]
    assert "dlq_retry, drift_checks" in cuerpo
    assert "En curso al cortarse: dlq_retry" in cuerpo
    assert notify.call_args.kwargs["dedup_key"] == "pipeline_cierre_interrumpido"


def test_el_aviso_de_cierre_interrumpido_nunca_lanza() -> None:
    from scheduler.pipeline_cierre import _avisar_cierre_interrumpido

    with patch("observability.alerts.notify", side_effect=RuntimeError("smtp")):
        _avisar_cierre_interrumpido(["digests"], [])


# ── Varios consumidores por proceso ─────────────────────────────────────────


def test_arrancar_en_hilo_lanza_un_consumidor_por_hilo_con_su_propio_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scheduler import worker as worker_mod

    monkeypatch.setenv("JOBS_CONSUMIDORES", "3")
    ids: list[str] = []
    with patch.object(
        worker_mod.Worker,
        "run_forever",
        autospec=True,
        side_effect=lambda _self, *, worker_id: ids.append(worker_id),
    ):
        worker = worker_mod.arrancar_en_hilo()

    base = worker.worker_id
    # Los hilos son daemon y terminan al instante con el doble; basta esperar.
    for _ in range(100):
        if len(ids) == 3:
            break
        worker._parar.wait(0.01)
    assert sorted(ids) == sorted([base, f"{base}#1", f"{base}#2"])
