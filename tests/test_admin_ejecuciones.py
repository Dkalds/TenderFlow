"""Ops › Ejecuciones: qué pasó con cada paso del cierre y con la cola de trabajo.

- Sin BD: la composición del resumen (orden canónico, pasos que nunca corrieron,
  traducción de estados, recuento de pasos en error) y la guarda de admin.
- Con BD (``tmp_db``): las dos consultas agregadas de ``JobsRepository``. No se
  pueden probar con un doble: lo que se comprueba es el ``DISTINCT ON`` y los
  ``FILTER`` sobre el JSON del payload, que son del motor.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import api.routes.admin_ejecuciones as ruta_mod
from api.routes.admin_ejecuciones import componer_resumen

AHORA = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def _fila_paso(paso: str, estado: str, resultado: str = "", **extra: Any) -> dict[str, Any]:
    return {
        "paso": paso,
        "estado": estado,
        "resultado": resultado,
        "ultima_ejecucion": AHORA - timedelta(hours=1),
        "ultima_ok": None,
        "ultimo_fallo": None,
        "ultimo_error": None,
        "fallos": 0,
        "ejecuciones": 1,
        **extra,
    }


def _componer(filas: list[dict[str, Any]], trabajos: list[dict[str, Any]] | None = None):
    return componer_resumen(
        filas,
        trabajos or [],
        pasos_canonicos=["ml_scoring", "kpi_precompute", "digests"],
        tiers={"ml_scoring": "bloqueante", "kpi_precompute": "bloqueante", "digests": "advisory"},
        ventana_dias=7,
        horizonte_dias=90,
        ahora=AHORA,
    )


# ---------------------------------------------------------------------------
# Composición (sin BD)
# ---------------------------------------------------------------------------


def test_los_pasos_salen_en_el_orden_del_cierre_y_no_en_el_de_la_consulta():
    res = _componer(
        [
            _fila_paso("kpi_precompute", "done", "ok"),
            _fila_paso("digests", "done", "ok"),
            _fila_paso("ml_scoring", "done", "ok"),
        ]
    )
    assert [p.paso for p in res.pasos] == ["ml_scoring", "kpi_precompute", "digests"]
    assert [p.tier for p in res.pasos] == ["bloqueante", "bloqueante", "advisory"]


def test_un_paso_canonico_sin_filas_se_dice_y_no_desaparece():
    """«No salió en el informe» no puede significar «no pasó nada»."""
    res = _componer([_fila_paso("ml_scoring", "done", "ok")])

    por_paso = {p.paso: p for p in res.pasos}
    assert por_paso["digests"].ultimo_estado == "sin_ejecuciones"
    assert por_paso["digests"].ultima_ejecucion is None
    assert por_paso["digests"].ejecuciones == 0


def test_cada_estado_de_la_cola_se_traduce_a_uno_publico():
    res = _componer(
        [
            _fila_paso("ml_scoring", "failed", "", ultimo_error="ModelArtifactMismatch: x"),
            _fila_paso("kpi_precompute", "done", "skipped_por_dependencia"),
            _fila_paso("digests", "done", "skipped"),
        ]
    )
    assert [p.ultimo_estado for p in res.pasos] == [
        "error",
        "omitido_por_dependencia",
        "omitido",
    ]
    # El contador de la pestaña: solo lo que falló, no lo que no tocaba correr.
    assert res.pasos_en_error == 1


def test_un_done_sin_resultado_es_ok():
    """El camino en línea del cierre no escribe ``resultado_json``."""
    res = _componer([_fila_paso("ml_scoring", "done", "")])
    assert res.pasos[0].ultimo_estado == "ok"


def test_un_paso_retirado_del_cierre_se_conserva_al_final_sin_tier():
    res = _componer([_fila_paso("paso_retirado", "failed"), _fila_paso("ml_scoring", "done", "ok")])

    assert res.pasos[-1].paso == "paso_retirado"
    assert res.pasos[-1].tier is None
    assert res.pasos[-1].ultimo_estado == "error"


def test_las_fechas_viajan_en_iso_y_el_error_se_recorta():
    fallo = AHORA - timedelta(days=2)
    res = _componer(
        [
            _fila_paso(
                "ml_scoring",
                "failed",
                ultimo_fallo=fallo,
                ultimo_error="RuntimeError: " + "x" * 900,
                fallos=3,
                ejecuciones=5,
            )
        ]
    )
    paso = res.pasos[0]
    assert paso.ultimo_fallo == fallo.isoformat()
    assert paso.ultimo_error is not None and len(paso.ultimo_error) <= 500
    assert (paso.fallos, paso.ejecuciones) == (3, 5)
    assert res.generado_at == AHORA.isoformat()
    assert (res.ventana_dias, res.horizonte_dias) == (7, 90)


def test_los_trabajos_a_demanda_se_mapean_tal_cual():
    res = _componer(
        [],
        [
            {
                "tipo": "ficha_pliego",
                "pendientes": 1,
                "en_curso": 0,
                "fallidos": 4,
                "hechos": 20,
                "ultimo_fallo": AHORA,
                "ultimo_error": "RuntimeError: sin pliego",
            }
        ],
    )
    trabajo = res.trabajos[0]
    assert (trabajo.tipo, trabajo.pendientes, trabajo.fallidos, trabajo.hechos) == (
        "ficha_pliego",
        1,
        4,
        20,
    )
    assert trabajo.ultimo_error == "RuntimeError: sin pliego"


def test_la_ruta_exige_admin():
    from api.routes.dual_auth import require_admin

    rutas: list[Any] = list(ruta_mod.router.routes)
    assert len(rutas) == 1
    dependencias = {d.call for d in rutas[0].dependant.dependencies}
    assert require_admin in dependencias


def test_la_ruta_pide_al_repositorio_la_ventana_y_el_horizonte(monkeypatch):
    """La ventana es de la petición; el horizonte acota el recorrido de la tabla."""
    pedido: dict[str, Any] = {}

    class _Repo:
        def resumen_por_paso(self, **kw: Any) -> list[dict[str, Any]]:
            pedido["pasos"] = kw
            return [_fila_paso("ml_scoring", "done", "ok")]

        def resumen_por_tipo(self, **kw: Any) -> list[dict[str, Any]]:
            pedido["trabajos"] = kw
            return []

    monkeypatch.setattr(ruta_mod, "JobsRepository", _Repo)
    res = asyncio.run(ruta_mod.resumen_ejecuciones(dias=3, _admin={}))

    assert res.ventana_dias == 3
    assert pedido["pasos"]["tipo"] == "paso_pipeline"
    assert pedido["trabajos"]["excluir_tipo"] == "paso_pipeline"
    ventana = pedido["pasos"]["hasta"] - pedido["pasos"]["desde"]
    assert ventana == timedelta(days=3)
    assert pedido["pasos"]["hasta"] - pedido["pasos"]["horizonte"] == timedelta(days=90)
    # Los pasos reales del cierre, no una lista de este test.
    from scheduler.pipeline_runs import CANONICAL_STEPS

    assert [p.paso for p in res.pasos] == CANONICAL_STEPS


# ---------------------------------------------------------------------------
# Consultas (con BD)
# ---------------------------------------------------------------------------


def _correr_paso(paso: str, *, resultado: str | None = None, error: str | None = None) -> int:
    from shared.jobs import TIPO_PASO_PIPELINE, ack, claim, enqueue, fail

    job_id = enqueue(TIPO_PASO_PIPELINE, {"paso": paso, "lane": "bulk"}, deduplicar=False)
    job = claim("cierre-test", tipos=(TIPO_PASO_PIPELINE,))
    assert job is not None and job.id == job_id
    if error is not None:
        fail(job_id, error, intentos=job.intentos, terminal=True)
    else:
        ack(job_id, None if resultado is None else {"paso": paso, "estado": resultado})
    return job_id


def _envejecer(job_id: int, cuando: datetime) -> None:
    from db.connection import connect

    with connect() as c:
        c.execute("UPDATE jobs SET updated_at = %s WHERE id = %s", (cuando, job_id))


def _resumen_pasos(ahora: datetime) -> dict[str, dict[str, Any]]:
    from db.repositories.jobs import JobsRepository
    from shared.jobs import TIPO_PASO_PIPELINE

    filas = JobsRepository().resumen_por_paso(
        tipo=TIPO_PASO_PIPELINE,
        desde=ahora - timedelta(days=7),
        horizonte=ahora - timedelta(days=90),
        hasta=ahora,
        resultado_ok="ok",
        ignorar_resultados=("descartado_pasada_anterior",),
    )
    return {str(f["paso"]): f for f in filas}


def test_resumen_por_paso_da_la_ultima_ejecucion_y_los_fallos_de_la_ventana(tmp_db):
    ahora = datetime.now(UTC) + timedelta(minutes=1)
    viejo = _correr_paso("ml_scoring", error="RuntimeError: antiguo")
    _envejecer(viejo, ahora - timedelta(days=20))
    ok = _correr_paso("ml_scoring", resultado="ok")
    _envejecer(ok, ahora - timedelta(days=3))
    reciente = _correr_paso("ml_scoring", error="ModelArtifactMismatch: v2")
    _envejecer(reciente, ahora - timedelta(hours=2))

    fila = _resumen_pasos(ahora)["ml_scoring"]

    assert fila["estado"] == "failed"
    assert fila["ultimo_error"] == "ModelArtifactMismatch: v2"
    assert fila["ultima_ok"] is not None and fila["ultimo_fallo"] is not None
    assert fila["ultima_ok"] < fila["ultimo_fallo"]
    # El fallo de hace 20 días queda fuera de la ventana de 7, pero dentro del
    # horizonte: no cuenta como fallo reciente.
    assert int(fila["fallos"]) == 1
    assert int(fila["ejecuciones"]) == 2


def test_resumen_por_paso_ignora_los_restos_de_una_pasada_anterior(tmp_db):
    """Un job descartado no es una ejecución: no puede tapar el fallo real."""
    ahora = datetime.now(UTC) + timedelta(minutes=1)
    fallo = _correr_paso("digests", error="RuntimeError: smtp")
    _envejecer(fallo, ahora - timedelta(hours=5))
    descartado = _correr_paso("digests", resultado="descartado_pasada_anterior")
    _envejecer(descartado, ahora - timedelta(hours=1))

    fila = _resumen_pasos(ahora)["digests"]

    assert fila["estado"] == "failed"
    assert int(fila["ejecuciones"]) == 1


def test_resumen_por_paso_distingue_lo_omitido_de_lo_que_fue_bien(tmp_db):
    ahora = datetime.now(UTC) + timedelta(minutes=1)
    _correr_paso("drift_checks", resultado="skipped")

    fila = _resumen_pasos(ahora)["drift_checks"]

    assert (fila["estado"], fila["resultado"]) == ("done", "skipped")
    assert fila["ultima_ok"] is None
    # Un paso que decidió no correr no es una ejecución de la que medir fallos.
    assert int(fila["ejecuciones"]) == 0


def test_resumen_por_paso_no_mira_mas_alla_del_horizonte(tmp_db):
    ahora = datetime.now(UTC) + timedelta(minutes=1)
    antiguo = _correr_paso("kpi_precompute", resultado="ok")
    _envejecer(antiguo, ahora - timedelta(days=120))

    assert "kpi_precompute" not in _resumen_pasos(ahora)


def test_resumen_por_tipo_cuenta_la_cola_a_demanda_sin_los_pasos(tmp_db):
    from db.repositories.jobs import JobsRepository
    from shared.jobs import TIPO_FICHA_PLIEGO, TIPO_PASO_PIPELINE, claim, enqueue, fail

    ahora = datetime.now(UTC) + timedelta(minutes=1)
    _correr_paso("ml_scoring", resultado="ok")
    roto = enqueue(TIPO_FICHA_PLIEGO, {"licitacion_id": "EXP-1"})
    job = claim("worker-test")
    assert job is not None and job.id == roto
    fail(roto, "RuntimeError: sin pliego", intentos=job.intentos, terminal=True)
    enqueue(TIPO_FICHA_PLIEGO, {"licitacion_id": "EXP-2"})

    filas = JobsRepository().resumen_por_tipo(
        excluir_tipo=TIPO_PASO_PIPELINE,
        desde=ahora - timedelta(days=7),
        horizonte=ahora - timedelta(days=90),
        hasta=ahora,
    )

    assert [f["tipo"] for f in filas] == [TIPO_FICHA_PLIEGO]
    fila = filas[0]
    assert (int(fila["pendientes"]), int(fila["en_curso"])) == (1, 0)
    assert (int(fila["fallidos"]), int(fila["hechos"])) == (1, 0)
    assert fila["ultimo_error"] == "RuntimeError: sin pliego"
