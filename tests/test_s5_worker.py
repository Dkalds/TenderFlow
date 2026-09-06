"""Worker de la cola, sus handlers y el plano declarado (plan v2, S5.3).

La mayoría son unitarios: comprueban declaraciones (render.yaml, el registro de
tipos, el perfil de la app) y handlers con dobles. Los que llevan ``tmp_db``
ejercitan el bucle contra Postgres y son de integración.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_job_parity

from shared.jobs import (
    TIPO_EMBEDDINGS_EXPEDIENTE,
    TIPO_EXPORT_PDF,
    TIPO_FICHA_PLIEGO,
    TIPO_PASO_PIPELINE,
    TIPOS_A_DEMANDA,
    TIPOS_PROGRAMADOS,
    Job,
)

_RAIZ = Path(__file__).resolve().parents[1]


def _job(tipo: str, payload: dict[str, object], *, job_id: int = 1) -> Job:
    from datetime import UTC, datetime

    ahora = datetime.now(UTC)
    return Job(
        id=job_id,
        tipo=tipo,
        payload=payload,
        organization_id=None,
        estado="running",
        intentos=1,
        run_after=ahora,
        locked_by="test",
        locked_at=ahora,
        resultado=None,
        error_detail=None,
        created_at=ahora,
        updated_at=ahora,
    )


# ---------------------------------------------------------------------------
# El plano worker está declarado y el checker lo exige
# ---------------------------------------------------------------------------


def test_render_declara_un_servicio_con_app_profile_worker() -> None:
    """Sin este servicio, la cola a demanda no la consume nadie en producción."""
    assert check_job_parity.plano_worker_declarado() is True


def test_el_servicio_worker_tiene_healthcheck_y_no_autodeploy() -> None:
    """Los dos criterios de S5.3 sobre el servicio, leídos del Blueprint.

    ``healthCheckPath`` porque un worker que arranca roto se queda vivo y mudo
    sin él; ``autoDeploy: false`` porque un despliegue automático mataría
    trabajo en vuelo cada vez que alguien mergea (y contradiría O0.2).
    """
    texto = (_RAIZ / "render.yaml").read_text(encoding="utf-8")
    bloque = texto[texto.index("name: tenderflow-worker") :]
    bloque = bloque[: bloque.index("- type:", 1)] if "- type:" in bloque[1:] else bloque

    assert "healthCheckPath: /api/v1/health/ready" in bloque
    assert "autoDeploy: false" in bloque
    assert "value: worker" in bloque


def test_check_job_parity_detecta_la_ausencia_del_plano_worker() -> None:
    """El valor de un checker está en que falle cuando debe."""
    with patch.object(check_job_parity, "plano_worker_declarado", return_value=False):
        _rows, problems = check_job_parity.check_cola()

    assert len(problems) == len(TIPOS_A_DEMANDA)
    assert all("sin plano worker" in p for p in problems)


def test_check_job_parity_detecta_un_handler_que_no_existe() -> None:
    from shared.jobs import TipoJob

    roto = {
        "tipo_roto": TipoJob(
            nombre="tipo_roto",
            handler="scheduler.worker:funcion_que_no_existe",
            clave_dedupe=None,
            descripcion="doble",
        )
    }
    with patch("shared.jobs.TIPOS_A_DEMANDA", roto):
        _rows, problems = check_job_parity.check_cola()

    assert any("no existe" in p for p in problems)


def test_los_tipos_programados_no_exigen_worker() -> None:
    """ADR-012: el cierre de la pasada consume su cola dentro del job de Actions."""
    rows, _problems = check_job_parity.check_cola()
    fila = next(r for r in rows if r["job"] == TIPO_PASO_PIPELINE)
    assert fila["plane"] == "pipeline"
    assert "Actions" in fila["cubierto_por"]


def test_los_tipos_a_demanda_y_los_programados_no_se_solapan() -> None:
    """Si un tipo estuviera en los dos, el worker reclamaría trabajo del cierre."""
    assert set(TIPOS_A_DEMANDA) & set(TIPOS_PROGRAMADOS) == set()


def test_los_tipos_a_demanda_son_los_tres_del_plan() -> None:
    assert set(TIPOS_A_DEMANDA) == {
        TIPO_FICHA_PLIEGO,
        TIPO_EMBEDDINGS_EXPEDIENTE,
        TIPO_EXPORT_PDF,
    }


# ---------------------------------------------------------------------------
# El perfil worker no publica la API
# ---------------------------------------------------------------------------


def test_el_perfil_worker_monta_solo_el_router_de_salud() -> None:
    """Es lo que hace que la URL pública del worker no sea otra copia de la API.

    Se comprueba sobre el código y no arrancando la app con el perfil puesto:
    ``api/app.py`` construye la app al importarse y el módulo ya está cargado
    por el resto de la suite, así que reimportarlo con otro ``APP_PROFILE``
    contaminaría a los demás tests.
    """
    texto = (_RAIZ / "api/app.py").read_text(encoding="utf-8")
    assert '_ES_WORKER = settings.APP_PROFILE == "worker"' in texto
    assert "if not _ES_WORKER:" in texto
    # El router de salud se monta ANTES del guard: es el único que el worker
    # publica, y es el que sondea Render.
    assert texto.index("app.include_router(health_router") < texto.index("if not _ES_WORKER:")


def test_el_lifespan_arranca_y_para_el_consumidor_en_el_perfil_worker() -> None:
    texto = (_RAIZ / "api/app.py").read_text(encoding="utf-8")
    assert 'if settings.APP_PROFILE == "worker":' in texto
    assert "arrancar_en_hilo()" in texto
    assert "worker.detener()" in texto


def test_worker_es_valido_como_app_profile() -> None:
    from config.settings import Settings

    assert Settings(APP_PROFILE="worker", ENV="dev", DATABASE_URL="").APP_PROFILE == "worker"


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def test_el_handler_de_la_ficha_lanza_si_la_extraccion_quedo_en_failed() -> None:
    """Lanzar es la forma de decirle a la cola «esto merece un reintento».

    ``run_background_extraction`` nunca lanza —persiste el estado y vuelve—, así
    que sin releer la fila el job se cerraría como ``done`` con la ficha rota.
    """
    from scheduler.worker import ejecutar_ficha_pliego

    ficha = MagicMock(status="failed", error_detail="sin páginas")
    with (
        patch("services.rag.fact_sheet.run_background_extraction") as extraer,
        patch("services.rag.fact_sheet.get_fact_sheet", return_value=ficha),
        pytest.raises(RuntimeError, match="sin páginas"),
    ):
        ejecutar_ficha_pliego(_job(TIPO_FICHA_PLIEGO, {"licitacion_id": "EXP-1", "model": "m"}))

    extraer.assert_called_once()


def test_el_handler_de_la_ficha_publica_el_recuento_al_terminar() -> None:
    from scheduler.worker import ejecutar_ficha_pliego

    ficha = MagicMock(status="extracted", field_count=12, evidence_count=9, error_detail=None)
    with (
        patch("services.rag.fact_sheet.run_background_extraction"),
        patch("services.rag.fact_sheet.get_fact_sheet", return_value=ficha),
    ):
        resultado = ejecutar_ficha_pliego(
            _job(TIPO_FICHA_PLIEGO, {"licitacion_id": "EXP-1", "model": "m"})
        )

    assert resultado == {
        "licitacion_id": "EXP-1",
        "estado_ficha": "extracted",
        "campos": 12,
        "citas": 9,
    }


def test_el_handler_de_embeddings_no_falla_sin_el_extra_de_ml() -> None:
    """Reintentarlo tres veces no instalará sentence-transformers.

    Cerrarlo como hecho con cero documentos es honesto y no deja un ``failed``
    que parece un bug del expediente.
    """
    from scheduler.worker import ejecutar_embeddings_expediente

    with patch("services.embeddings.embeddings_available", return_value=False):
        resultado = ejecutar_embeddings_expediente(
            _job(TIPO_EMBEDDINGS_EXPEDIENTE, {"licitacion_id": "EXP-1"})
        )

    assert resultado == {"licitacion_id": "EXP-1", "documentos": 0, "chunks": 0}


def test_el_handler_del_export_guarda_el_pdf_bajo_la_clave_del_job() -> None:
    """Las dos puntas del cable (worker escribe, API lee) viven en shared/jobs."""
    from scheduler.worker import ejecutar_export_pdf
    from shared.cache import get_cache, reset_cache
    from shared.jobs import CACHE_EXPORTS, clave_cache_export

    reset_cache(CACHE_EXPORTS)
    with patch("api.routes.exports.build_pdf_export", return_value=(b"%PDF-falso", 42)):
        resultado = ejecutar_export_pdf(_job(TIPO_EXPORT_PDF, {"limit": 20000}, job_id=7))

    assert resultado == {
        "filas": 42,
        "bytes": len(b"%PDF-falso"),
        "descarga": "/api/v1/exports/descargas/7",
    }
    assert get_cache(CACHE_EXPORTS).get(clave_cache_export(7)) == b"%PDF-falso"


def test_la_descarga_que_publica_el_worker_es_una_ruta_que_existe() -> None:
    """La URL del resultado tiene que resolver contra la app, no parecerlo.

    Es el fallo que este test caza: publicar
    ``/api/v1/exports/download?job_id=N``. Esa ruta EXISTE, así que un 404 no
    habría avisado — pero ignora ``job_id`` a propósito (issue #50), de modo que
    quien siguiera el enlace se habría descargado, con un 200 impecable, el PDF
    de los filtros por defecto en vez del que pidió.
    """
    from api.app import app
    from shared.jobs import RUTA_DESCARGA_EXPORT, ruta_descarga_export

    plantillas = {getattr(r, "path", "") for r in app.routes}
    assert RUTA_DESCARGA_EXPORT in plantillas, (
        f"el worker publica {RUTA_DESCARGA_EXPORT}, que no es ninguna ruta de la app"
    )
    # Y la URL concreta no lleva query: un parámetro de trabajo en `download`
    # es exactamente la forma que tenía el bug.
    assert "?" not in ruta_descarga_export(7)


# ---------------------------------------------------------------------------
# El bucle
# ---------------------------------------------------------------------------


def test_procesar_tanda_vacia_no_hace_nada() -> None:
    from scheduler.worker import Worker

    # Se parchea en `scheduler.worker` y no en `shared.jobs`: el módulo importa
    # el símbolo al cargarse, así que parchear el origen no cambia la
    # referencia que el bucle ya tiene.
    with patch("scheduler.worker.procesar_uno", return_value=None) as procesar:
        assert Worker(worker_id="w").procesar_tanda() == 0
    procesar.assert_called_once()


def test_el_worker_detenido_no_reclama_mas() -> None:
    from scheduler.worker import Worker

    worker = Worker(worker_id="w")
    worker.detener()
    with patch("scheduler.worker.procesar_uno") as procesar:
        assert worker.procesar_tanda() == 0
    procesar.assert_not_called()


def test_el_worker_solo_reclama_los_tipos_a_demanda(tmp_db) -> None:
    """ADR-012 en ejecución: el cierre de la pasada no es del worker."""
    from scheduler.worker import Worker
    from shared.jobs import enqueue

    enqueue(TIPO_PASO_PIPELINE, {"paso": "kpi_precompute"}, deduplicar=False)
    assert Worker(worker_id="w").procesar_tanda() == 0


def test_un_handler_roto_deja_el_error_en_la_fila_y_no_tumba_el_bucle(tmp_db) -> None:
    """El contrato de ``procesar_uno``: un job roto no es un worker roto."""
    from scheduler.worker import Worker
    from shared.jobs import enqueue, obtener

    job_id = enqueue(TIPO_FICHA_PLIEGO, {"licitacion_id": "EXP-BOOM", "model": "m"})
    with patch(
        "scheduler.worker.ejecutar_ficha_pliego", side_effect=RuntimeError("proveedor caído")
    ):
        assert Worker(worker_id="w").procesar_tanda() == 1

    job = obtener(job_id)
    assert job is not None
    assert job.estado == "pending"  # primer intento: reintenta con backoff
    assert "proveedor caído" in (job.error_detail or "")


def test_un_despliegue_a_mitad_no_pierde_el_trabajo(tmp_db) -> None:
    """Criterio de S5.3, simulando los dos procesos con dos worker_id.

    El primer worker reclama y "muere" sin cerrar el job (es lo que hace un
    SIGKILL de Render a mitad de una extracción). La barrida de caducados lo
    devuelve a la cola y el segundo lo termina.
    """
    from scheduler.worker import Worker
    from shared.jobs import claim, enqueue, obtener, reclamar_caducados

    job_id = enqueue(TIPO_FICHA_PLIEGO, {"licitacion_id": "EXP-DEPLOY", "model": "m"})

    muerto = claim("worker-viejo:1")
    assert muerto is not None and muerto.id == job_id

    # El despliegue mata al proceso: nadie hace ack ni fail. Con TTL 0 la
    # barrida ve el lock caducado sin tener que dormir.
    assert reclamar_caducados(ttl_segundos=0) == [job_id]

    with patch(
        "scheduler.worker.ejecutar_ficha_pliego",
        return_value={"licitacion_id": "EXP-DEPLOY", "estado_ficha": "extracted"},
    ):
        assert Worker(worker_id="worker-nuevo:2").procesar_tanda() == 1

    final = obtener(job_id)
    assert final is not None
    assert final.estado == "done"
    assert final.resultado == {"licitacion_id": "EXP-DEPLOY", "estado_ficha": "extracted"}


# ---------------------------------------------------------------------------
# El cierre por cola (S5.4) contra la tabla real
# ---------------------------------------------------------------------------


def test_el_cierre_por_cola_deja_una_fila_por_paso(tmp_db) -> None:
    from db.repositories.jobs import JobsRepository
    from scheduler.pipeline_runs import CANONICAL_STEPS, _cierre_por_cola

    objetivos = {f"_run_{name}": MagicMock() for name in CANONICAL_STEPS}
    with patch.multiple("scheduler.pipeline_runs", **objetivos):
        resultados = _cierre_por_cola(lane="daily")

    assert set(resultados) == set(CANONICAL_STEPS)
    assert all(estado == "ok" for estado in resultados.values())
    assert JobsRepository().contar_por_estado() == {"done": len(CANONICAL_STEPS)}


def test_el_cierre_por_cola_no_reintenta_un_paso_roto(tmp_db) -> None:
    """Reintentar con backoff se comería la ventana de 55 min del job."""
    from db.repositories.jobs import JobsRepository
    from scheduler.pipeline_runs import CANONICAL_STEPS, _cierre_por_cola

    objetivos: dict[str, object] = {f"_run_{name}": MagicMock() for name in CANONICAL_STEPS}
    objetivos["_run_kpi_precompute"] = MagicMock(side_effect=RuntimeError("boom"))
    with (
        patch.multiple("scheduler.pipeline_runs", **objetivos),
        patch("scheduler.pipeline_runs._notify_step_failure"),
    ):
        resultados = _cierre_por_cola(lane="daily")

    assert resultados["kpi_precompute"] == "error"
    assert resultados["watchlist_notify"] == "ok"
    assert JobsRepository().contar_por_estado()["failed"] == 1
