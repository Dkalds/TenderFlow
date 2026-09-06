"""Las rutas que encolan y la que consulta el trabajo (plan v2, S5.2).

Todo lo que toca ``client``/``api_db`` es integración (Postgres real). Los dos
tests de arriba no lo son: leen el fichero y el esquema, y son los que fijan el
criterio literal del plan sobre ``BackgroundTasks``.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parents[1]
# Credencial del usuario de prueba que crean los tests de integración de abajo.
# Los dos pragmas son para escáneres distintos y hacen falta los dos: el de
# `detect-secrets` y el de `gitleaks`, que la marca por entropía. Mismo patrón
# que `tests/test_password_reset.py`.
_PASSWORD = "Cola-2026-Segura"  # pragma: allowlist secret # gitleaks:allow


# ---------------------------------------------------------------------------
# El criterio literal: ni un BackgroundTask en licitaciones.py
# ---------------------------------------------------------------------------


def test_licitaciones_no_usa_background_tasks() -> None:
    """``grep -c "BackgroundTasks" api/routes/licitaciones.py`` = 0.

    Es el criterio de aceptación de S5.2 tal cual. El motivo, no la letra: un
    BackgroundTask vive en el proceso de la API y muere con el despliegue, y el
    trabajo que corría ahí (la extracción de la ficha) tardaba minutos.
    """
    texto = (_RAIZ / "api/routes/licitaciones.py").read_text(encoding="utf-8")
    assert texto.count("BackgroundTasks") == 0


def test_exports_solo_usa_background_tasks_para_el_last_used_de_la_api_key() -> None:
    """``BackgroundTasks`` queda para efectos triviales, que es lo que dice el
    plan. En ``exports.py`` el único uso es el que exige
    ``validate_api_key_credential`` para apuntar ``last_used`` del enlace del
    calendario: una escritura de una fila, no trabajo de usuario."""
    texto = (_RAIZ / "api/routes/exports.py").read_text(encoding="utf-8")
    assert "background_tasks=background_tasks" in texto
    # import + el parámetro de `calendario_ics`, cuya anotación y cuyo default
    # nombran el tipo (`BackgroundTasks = BackgroundTasks()`): tres menciones
    # en dos líneas.
    assert texto.count("BackgroundTasks") == 3


# ---------------------------------------------------------------------------
# Fixtures de integración
# ---------------------------------------------------------------------------


@pytest.fixture()
def usuario_con_key(api_db):
    """API key CON propietario: ``require_organization`` resuelve su personal."""
    from api.auth import create_api_key
    from db.users import create_user
    from shared.auth_core import hash_password

    user_id = create_user(email="cola@example.com", password_hash=hash_password(_PASSWORD))
    token = create_api_key("cola-key", scopes="*", user_id=user_id)
    return token, user_id


@pytest.fixture()
def cabeceras(usuario_con_key):
    token, _user_id = usuario_con_key
    return {"X-API-Key": token}


def _seed_licitacion(id_externo: str) -> None:
    from datetime import UTC, datetime

    import db.database as db_mod

    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) VALUES (%s, %s, %s)",
            (id_externo, "Mantenimiento SAP", datetime.now(UTC).isoformat()),
        )


# ---------------------------------------------------------------------------
# 202 sin tocar el proveedor LLM
# ---------------------------------------------------------------------------


def test_extract_async_devuelve_202_con_job_id_sin_llamar_al_llm(client, cabeceras, monkeypatch):
    """El 202 responde rápido y **sin** proveedor: el trabajo se hace luego.

    El «proveedor simulado» es un doble que revienta: si la ruta lo tocara, el
    test fallaría con esa excepción en vez de con el tiempo, que es una señal
    más útil que un umbral de milisegundos.
    """

    def _proveedor_prohibido(*_args, **_kwargs):
        raise AssertionError("la ruta que encola no puede llamar al proveedor LLM")

    monkeypatch.setattr("llm.client.stream_llm_response", _proveedor_prohibido)
    _seed_licitacion("EXP-ASYNC-1")

    t0 = time.monotonic()
    resp = client.post(
        "/api/v1/licitaciones/EXP-ASYNC-1/ficha-pliego/extract-async", headers=cabeceras
    )
    transcurrido_ms = (time.monotonic() - t0) * 1000

    assert resp.status_code == 202, resp.text
    cuerpo = resp.json()
    assert cuerpo["running"] is True
    assert isinstance(cuerpo["job_id"], int)
    assert transcurrido_ms < 200, f"el 202 tardó {transcurrido_ms:.0f} ms"


def test_extract_async_es_idempotente(client, cabeceras):
    """Dos clics seguidos son un solo trabajo."""
    _seed_licitacion("EXP-ASYNC-2")
    uno = client.post(
        "/api/v1/licitaciones/EXP-ASYNC-2/ficha-pliego/extract-async", headers=cabeceras
    )
    otro = client.post(
        "/api/v1/licitaciones/EXP-ASYNC-2/ficha-pliego/extract-async", headers=cabeceras
    )
    assert uno.json()["job_id"] == otro.json()["job_id"]


def test_extract_async_404_antes_de_encolar(client, cabeceras):
    """Un id inexistente no deja un job girando contra una FK que lo rechaza."""
    from db.repositories.jobs import JobsRepository

    resp = client.post(
        "/api/v1/licitaciones/NO-EXISTE/ficha-pliego/extract-async", headers=cabeceras
    )
    assert resp.status_code == 404
    assert JobsRepository().contar_por_estado() == {}


def test_el_estado_de_la_ficha_lee_la_cola(client, cabeceras):
    """Criterio de S5.2: ``…/ficha-pliego/estado`` consulta ``jobs``.

    Antes leía una bandera en la caché del proceso, invisible desde cualquier
    otra instancia de la API.
    """
    from shared.jobs import ack

    _seed_licitacion("EXP-ASYNC-3")

    antes = client.get("/api/v1/licitaciones/EXP-ASYNC-3/ficha-pliego/estado", headers=cabeceras)
    assert antes.json() == {"licitacion_id": "EXP-ASYNC-3", "running": False, "job_id": None}

    job_id = client.post(
        "/api/v1/licitaciones/EXP-ASYNC-3/ficha-pliego/extract-async", headers=cabeceras
    ).json()["job_id"]

    durante = client.get("/api/v1/licitaciones/EXP-ASYNC-3/ficha-pliego/estado", headers=cabeceras)
    assert durante.json() == {
        "licitacion_id": "EXP-ASYNC-3",
        "running": True,
        "job_id": job_id,
    }

    ack(job_id, {"licitacion_id": "EXP-ASYNC-3", "estado_ficha": "extracted"})
    despues = client.get("/api/v1/licitaciones/EXP-ASYNC-3/ficha-pliego/estado", headers=cabeceras)
    assert despues.json()["running"] is False


def test_embeddings_async_encola_el_expediente_abierto(client, cabeceras):
    _seed_licitacion("EXP-EMB-1")
    resp = client.post("/api/v1/licitaciones/EXP-EMB-1/embeddings-async", headers=cabeceras)

    assert resp.status_code == 202, resp.text
    assert resp.json()["licitacion_id"] == "EXP-EMB-1"

    from shared.jobs import TIPO_EMBEDDINGS_EXPEDIENTE, obtener

    job = obtener(int(resp.json()["job_id"]))
    assert job is not None and job.tipo == TIPO_EMBEDDINGS_EXPEDIENTE


# ---------------------------------------------------------------------------
# GET /jobs/{id} y su ámbito de organización
# ---------------------------------------------------------------------------


def test_get_job_devuelve_el_estado_tipado(client, cabeceras):
    _seed_licitacion("EXP-JOB-1")
    job_id = client.post(
        "/api/v1/licitaciones/EXP-JOB-1/ficha-pliego/extract-async", headers=cabeceras
    ).json()["job_id"]

    resp = client.get(f"/api/v1/jobs/{job_id}", headers=cabeceras)

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["id"] == job_id
    assert cuerpo["tipo"] == "ficha_pliego"
    assert cuerpo["estado"] == "pending"
    assert cuerpo["intentos"] == 0
    assert cuerpo["resultado"] is None


def test_get_job_publica_el_resultado_tipado_al_terminar(client, cabeceras):
    """El resultado NO es un ``dict[str, Any]``: el cliente TS recibe forma."""
    from shared.jobs import ack

    _seed_licitacion("EXP-JOB-2")
    job_id = client.post(
        "/api/v1/licitaciones/EXP-JOB-2/ficha-pliego/extract-async", headers=cabeceras
    ).json()["job_id"]
    ack(job_id, {"licitacion_id": "EXP-JOB-2", "estado_ficha": "extracted", "campos": 12})

    cuerpo = client.get(f"/api/v1/jobs/{job_id}", headers=cabeceras).json()
    assert cuerpo["estado"] == "done"
    assert cuerpo["resultado"]["licitacion_id"] == "EXP-JOB-2"
    assert cuerpo["resultado"]["campos"] == 12
    # Los campos de otros tipos viajan nulos, no ausentes: es un solo modelo.
    assert cuerpo["resultado"]["descarga"] is None


def test_get_job_de_otra_organizacion_responde_404_y_no_403(client, cabeceras, usuario_con_key):
    """404 a propósito: un 403 confirmaría que ese id existe, y con ids
    correlativos eso convierte la ruta en un contador del trabajo ajeno."""
    from db.repositories.organizations import OrganizationRepository
    from shared.jobs import TIPO_FICHA_PLIEGO, enqueue

    _token, user_id = usuario_con_key
    otra = int(OrganizationRepository().create_organization("Otro equipo", user_id)["id"])
    ajeno = enqueue(
        TIPO_FICHA_PLIEGO,
        {"licitacion_id": "EXP-AJENO", "model": "m"},
        organization_id=otra,
    )

    resp = client.get(f"/api/v1/jobs/{ajeno}", headers=cabeceras)
    assert resp.status_code == 404, resp.text


def test_get_job_del_sistema_no_se_sirve_a_nadie(client, cabeceras):
    """Los pasos del cierre no tienen organización, así que no son de nadie."""
    from shared.jobs import TIPO_PASO_PIPELINE, enqueue

    job_id = enqueue(TIPO_PASO_PIPELINE, {"paso": "kpi_precompute"}, deduplicar=False)
    assert client.get(f"/api/v1/jobs/{job_id}", headers=cabeceras).status_code == 404


def test_get_job_inexistente_responde_404(client, cabeceras):
    assert client.get("/api/v1/jobs/999999", headers=cabeceras).status_code == 404


def test_get_job_sin_autenticar_responde_401(client):
    assert client.get("/api/v1/jobs/1").status_code == 401


# ---------------------------------------------------------------------------
# Exportación PDF por encima del umbral
# ---------------------------------------------------------------------------


def test_la_peticion_por_defecto_sigue_devolviendo_el_fichero(client, cabeceras):
    """El umbral por defecto está POR ENCIMA del `limit` por defecto.

    Si no lo estuviera, la petición que hace hoy cualquier cliente pasaría a
    responder 202 sin que nadie hubiera pedido nada distinto.
    """
    from config.settings import jobs_export_umbral_filas

    _seed_licitacion("EXP-PDF-1")
    assert jobs_export_umbral_filas() > 10000  # el default de `limit` en la ruta

    resp = client.get("/api/v1/exports/download?format=pdf", headers=cabeceras)

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/pdf")


def test_el_pdf_grande_devuelve_202_con_job_id(client, cabeceras):
    resp = client.get("/api/v1/exports/download?format=pdf&limit=30000", headers=cabeceras)

    assert resp.status_code == 202, resp.text
    cuerpo = resp.json()
    assert cuerpo["tipo"] == "export_pdf"
    assert cuerpo["estado"] == "pending"
    assert isinstance(cuerpo["id"], int)


def test_el_csv_grande_no_se_encola(client, cabeceras):
    """El umbral es del PDF: es la maquetación lo que no cabe en la request."""
    resp = client.get("/api/v1/exports/download?format=csv&limit=30000", headers=cabeceras)

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")


def test_download_no_acepta_un_identificador_de_trabajo(client, cabeceras):
    """La ruta de filtros nunca se parametriza por id (issue #50).

    Quien lleva el id es ``/exports/descargas/{job_id}``, y esa sí comprueba el
    dueño. ``job_id`` como query en ``/download`` lo ignora FastAPI, así que la
    respuesta es el fichero de los filtros de quien pide, no el de nadie más.
    """
    import inspect

    import api.routes.exports as exports_mod

    assert "job_id" not in inspect.signature(exports_mod.download_export).parameters


def test_la_descarga_encolada_de_otra_organizacion_responde_404(client, cabeceras, usuario_con_key):
    from db.repositories.organizations import OrganizationRepository
    from shared.jobs import TIPO_EXPORT_PDF, enqueue

    _token, user_id = usuario_con_key
    otra = int(OrganizationRepository().create_organization("Otro equipo", user_id)["id"])
    ajeno = enqueue(TIPO_EXPORT_PDF, {"limit": 30000}, organization_id=otra, deduplicar=False)

    resp = client.get(f"/api/v1/exports/descargas/{ajeno}", headers=cabeceras)
    assert resp.status_code == 404, resp.text


def test_la_descarga_de_un_trabajo_sin_terminar_responde_409(client, cabeceras):
    job_id = client.get(
        "/api/v1/exports/download?format=pdf&limit=30000", headers=cabeceras
    ).json()["id"]

    resp = client.get(f"/api/v1/exports/descargas/{job_id}", headers=cabeceras)
    assert resp.status_code == 409, resp.text


def test_la_descarga_encolada_sirve_el_pdf_que_dejo_el_worker(client, cabeceras):
    """El circuito completo: 202 → worker → /descargas/{id} devuelve el PDF."""
    from scheduler.worker import Worker
    from shared.jobs import TIPO_EXPORT_PDF

    _seed_licitacion("EXP-PDF-2")

    job_id = client.get(
        "/api/v1/exports/download?format=pdf&limit=30000", headers=cabeceras
    ).json()["id"]

    assert Worker(worker_id="test", tipos=(TIPO_EXPORT_PDF,)).procesar_tanda() == 1

    resp = client.get(f"/api/v1/exports/descargas/{job_id}", headers=cabeceras)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.content[:4] == b"%PDF"
