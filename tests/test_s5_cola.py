"""Cola de trabajo: reclamación, reintentos y locks caducados (plan v2, S5.1).

Los tests con ``tmp_db`` son de integración (Postgres real) y no pueden ser de
otro modo: lo que se está probando es ``SELECT … FOR UPDATE SKIP LOCKED``, que
es una garantía del motor. Un doble en memoria daría verde sin ejercitar nada
de lo que importa aquí.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from db.repositories.jobs import JobsRepository
from shared.jobs import (
    TIPO_FICHA_PLIEGO,
    JobDesconocido,
    ack,
    claim,
    enqueue,
    fail,
    job_activo,
    obtener,
    reclamar_caducados,
)

_REPO = JobsRepository()


# ---------------------------------------------------------------------------
# El vocabulario de estados no puede divergir de la migración
# ---------------------------------------------------------------------------


def test_los_estados_del_codigo_son_los_del_check_de_la_migracion() -> None:
    """``v106_jobs`` declara el ``CHECK``; ``shared/jobs`` declara el Literal.

    Un valor que exista en uno y no en el otro se traduce en un
    ``IntegrityError`` en producción o en un estado que el DTO no sabe
    publicar. La migración se carga por ruta y no con un ``import``:
    ``db/alembic/versions`` no es un paquete (no tiene ``__init__.py``), como
    corresponde a un directorio que Alembic descubre por fichero.
    """
    import importlib.util
    from pathlib import Path

    from shared.jobs import _ESTADOS

    ruta = Path(__file__).resolve().parents[1] / "db/alembic/versions/v106_jobs.py"
    spec = importlib.util.spec_from_file_location("v106_jobs_para_test", ruta)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    assert set(modulo.ESTADOS) == set(_ESTADOS)


def test_encolar_un_tipo_no_declarado_falla_al_encolar_y_no_en_el_worker() -> None:
    """Un tipo desconocido se rechaza aquí, no tres intentos después."""
    with pytest.raises(JobDesconocido):
        enqueue("tipo_que_nadie_declaro", {})


# ---------------------------------------------------------------------------
# Ciclo de vida
# ---------------------------------------------------------------------------


def test_enqueue_claim_ack_recorre_el_ciclo(tmp_db) -> None:
    job_id = enqueue(TIPO_FICHA_PLIEGO, {"licitacion_id": "EXP-1", "model": "m"})

    encolado = obtener(job_id)
    assert encolado is not None
    assert encolado.estado == "pending"
    assert encolado.intentos == 0
    assert encolado.payload["licitacion_id"] == "EXP-1"

    reclamado = claim("worker-1")
    assert reclamado is not None
    assert reclamado.id == job_id
    assert reclamado.estado == "running"
    # El intento se cuenta al reclamar, no al fallar: así también quedan
    # acotados los fallos que no dejan traza (el proceso muere a mitad).
    assert reclamado.intentos == 1
    assert reclamado.locked_by == "worker-1"

    ack(job_id, {"licitacion_id": "EXP-1", "estado_ficha": "extracted"})
    terminado = obtener(job_id)
    assert terminado is not None
    assert terminado.estado == "done"
    assert terminado.resultado == {"licitacion_id": "EXP-1", "estado_ficha": "extracted"}
    assert terminado.locked_by is None


def test_una_cola_vacia_no_da_trabajo(tmp_db) -> None:
    assert claim("worker-1") is None


def test_el_worker_no_reclama_los_pasos_programados(tmp_db) -> None:
    """ADR-012: el cierre de la pasada no depende de que el worker esté vivo."""
    from shared.jobs import TIPO_PASO_PIPELINE

    enqueue(TIPO_PASO_PIPELINE, {"paso": "kpi_precompute"}, deduplicar=False)
    assert claim("worker-render") is None
    assert claim("cierre", tipos=(TIPO_PASO_PIPELINE,)) is not None


# ---------------------------------------------------------------------------
# Exactamente una vez con dos consumidores concurrentes
# ---------------------------------------------------------------------------


def test_dos_consumidores_procesan_cien_jobs_exactamente_una_vez(tmp_db) -> None:
    """El criterio de aceptación de S5.1, con hilos de verdad.

    Cada hilo reclama en bucle hasta vaciar la cola. Si ``SKIP LOCKED`` no
    estuviera, o si el ``UPDATE`` a ``running`` no viajara en la misma
    transacción que el ``SELECT``, aquí habría ids repetidos.
    """
    total = 100
    for i in range(total):
        enqueue(TIPO_FICHA_PLIEGO, {"licitacion_id": f"EXP-{i}", "model": "m"})

    reclamados: list[int] = []
    cerrojo = threading.Lock()

    def _consumir(nombre: str) -> None:
        while True:
            job = claim(nombre)
            if job is None:
                return
            with cerrojo:
                reclamados.append(job.id)
            ack(job.id, {"licitacion_id": str(job.payload["licitacion_id"])})

    hilos = [threading.Thread(target=_consumir, args=(f"worker-{n}",)) for n in (1, 2)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)

    assert len(reclamados) == total, "algún job se quedó sin procesar"
    assert len(set(reclamados)) == total, "algún job se procesó dos veces"
    assert _REPO.contar_por_estado() == {"done": total}


# ---------------------------------------------------------------------------
# Reintentos con backoff y fallo definitivo
# ---------------------------------------------------------------------------


def test_un_job_que_falla_reintenta_con_backoff_y_acaba_en_failed(tmp_db, monkeypatch) -> None:
    """Tres intentos: los dos primeros reprograman, el tercero es terminal."""
    monkeypatch.setenv("JOBS_MAX_INTENTOS", "3")
    monkeypatch.setenv("JOBS_BACKOFF_BASE_SEGUNDOS", "30")

    job_id = enqueue(TIPO_FICHA_PLIEGO, {"licitacion_id": "EXP-BOOM", "model": "m"})

    primero = claim("worker-1")
    assert primero is not None
    assert fail(primero.id, "RuntimeError: boom", intentos=primero.intentos) == "pending"

    tras_uno = obtener(job_id)
    assert tras_uno is not None
    assert tras_uno.estado == "pending"
    assert tras_uno.error_detail == "RuntimeError: boom"
    # 30 s de espera: no es reclamable todavía.
    assert tras_uno.run_after > datetime.now(UTC) + timedelta(seconds=20)
    assert claim("worker-1") is None

    # Se adelanta la ventana para no dormir 30 s en el test.
    _REPO.reprogramar(job_id, error_detail="boom", run_after=datetime.now(UTC))
    segundo = claim("worker-1")
    assert segundo is not None
    assert segundo.intentos == 2
    assert fail(segundo.id, "RuntimeError: boom", intentos=segundo.intentos) == "pending"

    _REPO.reprogramar(job_id, error_detail="boom", run_after=datetime.now(UTC))
    tercero = claim("worker-1")
    assert tercero is not None
    assert tercero.intentos == 3
    assert fail(tercero.id, "RuntimeError: boom otra vez", intentos=tercero.intentos) == "failed"

    final = obtener(job_id)
    assert final is not None
    assert final.estado == "failed"
    assert final.error_detail == "RuntimeError: boom otra vez"
    assert final.locked_by is None


def test_fail_terminal_no_reintenta_aunque_queden_intentos(tmp_db) -> None:
    """Lo usa el cierre de la pasada: reintentar se come su ventana de 55 min."""
    job_id = enqueue(TIPO_FICHA_PLIEGO, {"licitacion_id": "EXP-T", "model": "m"})
    job = claim("worker-1")
    assert job is not None

    assert fail(job.id, "se acabó", intentos=job.intentos, terminal=True) == "failed"
    final = obtener(job_id)
    assert final is not None
    assert final.estado == "failed"


# ---------------------------------------------------------------------------
# Locks caducados
# ---------------------------------------------------------------------------


def test_un_locked_at_caducado_vuelve_a_pending(tmp_db) -> None:
    """El despliegue que mata a un worker no pierde su trabajo (S5.3)."""
    job_id = enqueue(TIPO_FICHA_PLIEGO, {"licitacion_id": "EXP-MUERTO", "model": "m"})
    reclamado = claim("worker-que-se-muere")
    assert reclamado is not None

    # Con TTL 0, cualquier lock ya caducó: evita dormir en el test sin tocar
    # el reloj del proceso (el que compara es el del servidor, no el nuestro).
    assert reclamar_caducados(ttl_segundos=0) == [job_id]

    devuelto = obtener(job_id)
    assert devuelto is not None
    assert devuelto.estado == "pending"
    assert devuelto.locked_by is None
    assert devuelto.locked_at is None

    # Y otro worker puede terminarlo.
    otro = claim("worker-nuevo")
    assert otro is not None
    assert otro.id == job_id
    assert otro.intentos == 2


def test_un_lock_vivo_no_se_reclama(tmp_db) -> None:
    enqueue(TIPO_FICHA_PLIEGO, {"licitacion_id": "EXP-VIVO", "model": "m"})
    assert claim("worker-1") is not None
    assert reclamar_caducados(ttl_segundos=900) == []


# ---------------------------------------------------------------------------
# Deduplicación y consulta por payload
# ---------------------------------------------------------------------------


def test_dos_peticiones_del_mismo_expediente_no_encolan_dos_veces(tmp_db) -> None:
    """Dos clics en «Extraer ficha» son una sola extracción."""
    primero = enqueue(TIPO_FICHA_PLIEGO, {"licitacion_id": "EXP-2", "model": "m"})
    segundo = enqueue(TIPO_FICHA_PLIEGO, {"licitacion_id": "EXP-2", "model": "m"})
    assert primero == segundo


def test_la_deduplicacion_no_cruza_organizaciones(tmp_db) -> None:
    """Cada organización tiene SU job: es lo que permite el 404 por ámbito.

    Sin organización propia, el 202 de la segunda devolvería un ``job_id`` que
    su ``GET /jobs/{id}`` respondería 404 — un contrato que se contradice.
    """
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user
    from shared.auth_core import hash_password

    user_id = create_user(
        email="cola@example.com",
        password_hash=hash_password("Cola-2026-Segura"),  # pragma: allowlist secret
    )
    repo = OrganizationRepository()
    org_a = int(repo.create_organization("Equipo A", user_id)["id"])
    org_b = int(repo.create_organization("Equipo B", user_id)["id"])

    uno = enqueue(
        TIPO_FICHA_PLIEGO, {"licitacion_id": "EXP-3", "model": "m"}, organization_id=org_a
    )
    otro = enqueue(
        TIPO_FICHA_PLIEGO, {"licitacion_id": "EXP-3", "model": "m"}, organization_id=org_b
    )
    assert uno != otro


def test_job_activo_encuentra_el_trabajo_en_curso_por_expediente(tmp_db) -> None:
    """Es lo que lee ``…/ficha-pliego/estado`` (S5.2)."""
    job_id = enqueue(TIPO_FICHA_PLIEGO, {"licitacion_id": "EXP-4", "model": "m"})

    activo = job_activo(TIPO_FICHA_PLIEGO, campo="licitacion_id", valor="EXP-4")
    assert activo is not None and activo.id == job_id

    ack(job_id, None)
    assert job_activo(TIPO_FICHA_PLIEGO, campo="licitacion_id", valor="EXP-4") is None


def test_un_payload_corrupto_no_tumba_la_lectura(tmp_db) -> None:
    """La fila la escribe siempre este módulo, pero la BD sobrevive a los
    despliegues y un JSON roto de una versión anterior no puede reventar
    ``GET /jobs/{id}``: se lee como payload vacío."""
    job_id = _REPO.insertar(
        tipo=TIPO_FICHA_PLIEGO,
        payload_json="{no es json",
        organization_id=None,
    )
    job = obtener(job_id)
    assert job is not None
    assert job.payload == {}


# ---------------------------------------------------------------------------
# ADR-022: el SQL de la cola vive en db/repositories/jobs.py
# ---------------------------------------------------------------------------


def test_ningun_modulo_de_la_cola_escribe_sql_fuera_de_db() -> None:
    """``shared/jobs.py``, ``scheduler/worker.py`` y ``api/routes/jobs.py`` no
    contienen SQL: todo pasa por el repositorio (invariante §3.10)."""
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1]
    for relativo in ("shared/jobs.py", "scheduler/worker.py", "api/routes/jobs.py"):
        texto = (raiz / relativo).read_text(encoding="utf-8").upper()
        for palabra in ("SELECT ", "INSERT INTO", "UPDATE JOBS", "DELETE FROM"):
            assert palabra not in texto, f"{relativo} contiene SQL ({palabra.strip()})"


def test_el_payload_se_serializa_como_json_valido(tmp_db) -> None:
    """``buscar_activo`` castea la columna a ``jsonb``: un payload que no sea
    JSON válido haría fallar esa consulta para TODOS los jobs de ese tipo."""
    enqueue(TIPO_FICHA_PLIEGO, {"licitacion_id": "EXP-Ñ", "model": "modelo con acentos: ó"})
    fila: dict[str, Any] | None = _REPO.buscar_activo(
        tipo=TIPO_FICHA_PLIEGO, campo="licitacion_id", valor="EXP-Ñ"
    )
    assert fila is not None
    assert json.loads(fila["payload_json"])["licitacion_id"] == "EXP-Ñ"
