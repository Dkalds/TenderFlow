"""Auditoría de seguridad 2026-11: salidas, ingesta y ficha de pliego.

Cada test fija una de las correcciones de ese lote, sin BD ni red:

- la ficha compartida no se degrada a ``failed`` (presupuesto, SQL del upsert);
- cuota de jobs por organización y gasto atribuido a la organización;
- bomba de descompresión en DOCX y entradas ZIP ilegibles;
- cabeceras de caché del calendario ICS.

El redactor de logs, el escape HTML de las alertas y la URI de los adjuntos
tienen su test junto al módulo que cubren (``test_observability_logging``,
``test_observability_alerts``, ``test_codice_parser``).
"""

from __future__ import annotations

import asyncio
import io
import struct
import zipfile
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException, Response

from llm.budget import LLMBudgetExceeded
from services.rag import fact_sheet as fs

# ── Ficha de pliego: una regeneración fallida no pisa la buena ──────────────────


def _pagina() -> dict[str, Any]:
    return {
        "documento_id": 1,
        "page_number": 1,
        "texto": "pliego",
        "tipo": "legal",
        "filename": "PCAP.pdf",
    }


def test_presupuesto_agotado_no_toca_la_ficha_ni_escribe_failed() -> None:
    """llm-asistente-1 / G1-2-1: el check va antes del ``try``."""
    guard = MagicMock()
    guard.check.side_effect = LLMBudgetExceeded("daily", 5.0, 5.0)
    with (
        patch.object(fs, "DocumentosRepository") as docs,
        patch.object(fs, "TenderFactSheetsRepository") as fichas,
        patch.object(fs, "stream_llm_response") as proveedor,
        patch("llm.budget.get_budget_guard", return_value=guard),
    ):
        docs.return_value.list_pages_by_licitacion.return_value = [_pagina()]
        with pytest.raises(LLMBudgetExceeded):
            fs.extract_fact_sheet("EXP-1", model="m")

    fichas.return_value.upsert.assert_not_called()
    proveedor.assert_not_called()


def test_presupuesto_agotado_a_mitad_de_la_extraccion_tampoco_escribe_failed() -> None:
    with (
        patch.object(fs, "DocumentosRepository") as docs,
        patch.object(fs, "TenderFactSheetsRepository") as fichas,
        patch.object(fs, "stream_llm_response", side_effect=LLMBudgetExceeded("daily", 5.0, 5.0)),
        patch("llm.budget.get_budget_guard", return_value=MagicMock()),
    ):
        docs.return_value.list_pages_by_licitacion.return_value = [_pagina()]
        with pytest.raises(LLMBudgetExceeded):
            fs.extract_fact_sheet("EXP-1", model="m")

    fichas.return_value.upsert.assert_not_called()


def test_un_fallo_que_no_es_de_presupuesto_sigue_dejando_failed_con_su_detalle() -> None:
    """El resto de excepciones conserva su camino (la protección de la ficha
    buena vive en el ``upsert``, no en saltarse el estado)."""
    with (
        patch.object(fs, "DocumentosRepository") as docs,
        patch.object(fs, "TenderFactSheetsRepository") as fichas,
        patch.object(fs, "stream_llm_response", return_value=iter([])),
        patch("llm.budget.get_budget_guard", return_value=MagicMock()),
    ):
        docs.return_value.list_pages_by_licitacion.return_value = [_pagina()]
        with pytest.raises(ValueError, match="respuesta vacía"):
            fs.extract_fact_sheet("EXP-1", model="m")

    assert fichas.return_value.upsert.call_args.kwargs["status"] == "failed"


def test_el_upsert_no_deja_que_un_failed_pise_una_ficha_buena() -> None:
    """El SQL del ``ON CONFLICT`` lleva el guardián (el comportamiento sobre una
    BD real lo fija ``test_tender_fact_sheet.py::test_failed_never_overwrites_a_good_sheet``)."""
    from db.repositories import tender_fact_sheets as repo_mod

    conn = MagicMock()
    contexto = MagicMock()
    contexto.__enter__.return_value = conn
    with patch.object(repo_mod, "connect", return_value=contexto):
        repo_mod.TenderFactSheetsRepository().upsert(
            licitacion_id="EXP-1",
            status="failed",
            extraction_version="v",
            model="m",
            facts=None,
            field_count=0,
            evidence_count=0,
        )

    sql = conn.execute.call_args.args[0]
    assert "ON CONFLICT(licitacion_id) DO UPDATE SET" in sql
    assert (
        "WHERE NOT (excluded.status = 'failed' "
        "AND tender_fact_sheets.status IN ('extracted', 'needs_review'))"
    ) in sql


def test_la_extraccion_en_background_ata_el_gasto_a_la_organizacion() -> None:
    """G1-3-3: sin ``bind_budget_org`` el tope diario por organización no se alimenta."""
    with (
        patch("llm.budget.bind_budget_org") as bind_org,
        patch("llm.budget.bind_budget_subject") as bind_subject,
        patch.object(fs, "extract_fact_sheet_on_demand", side_effect=RuntimeError("x")),
    ):
        fs.run_background_extraction("EXP-1", model="m", budget_subject="u1", budget_org="7")

    bind_subject.assert_called_once_with("u1")
    bind_org.assert_called_once_with("7")


def test_el_handler_de_la_ficha_pasa_la_organizacion_del_job() -> None:
    from datetime import UTC, datetime

    from scheduler.worker import ejecutar_ficha_pliego
    from services.jobs import TIPO_FICHA_PLIEGO, Job

    ahora = datetime.now(UTC)
    job = Job(
        id=1,
        tipo=TIPO_FICHA_PLIEGO,
        payload={"licitacion_id": "EXP-1", "model": "m", "budget_subject": "u1"},
        organization_id=7,
        estado="running",
        intentos=1,
        run_after=ahora,
        locked_by="t",
        locked_at=ahora,
        resultado=None,
        error_detail=None,
        created_at=ahora,
        updated_at=ahora,
    )
    ficha = MagicMock(status="extracted", field_count=1, evidence_count=1, error_detail=None)
    with (
        patch("services.rag.fact_sheet.run_background_extraction") as extraer,
        patch("services.rag.fact_sheet.get_fact_sheet", return_value=ficha),
    ):
        ejecutar_ficha_pliego(job)

    assert extraer.call_args.kwargs["budget_org"] == "7"
    assert extraer.call_args.kwargs["budget_subject"] == "u1"


# ── Cola: cuota de jobs activos por organización ───────────────────────────────


def _cola(*, activos: int, existente: dict[str, Any] | None = None) -> MagicMock:
    repo = MagicMock()
    repo.buscar_activo.return_value = existente
    repo.contar_activos.return_value = activos
    repo.insertar.return_value = 99
    return repo


def test_enqueue_corta_al_llegar_al_tope_de_la_organizacion() -> None:
    from services import jobs

    repo = _cola(activos=jobs.MAX_JOBS_ACTIVOS_POR_ORG)
    with patch.object(jobs, "_repo", repo):
        with pytest.raises(jobs.CuotaDeJobsExcedida):
            jobs.enqueue(jobs.TIPO_FICHA_PLIEGO, {"licitacion_id": "EXP-1"}, organization_id=7)

    repo.contar_activos.assert_called_once_with(tipo=jobs.TIPO_FICHA_PLIEGO, organization_id=7)
    repo.insertar.assert_not_called()


def test_enqueue_por_debajo_del_tope_encola() -> None:
    from services import jobs

    repo = _cola(activos=jobs.MAX_JOBS_ACTIVOS_POR_ORG - 1)
    with patch.object(jobs, "_repo", repo):
        assert (
            jobs.enqueue(jobs.TIPO_EMBEDDINGS_EXPEDIENTE, {"licitacion_id": "E"}, organization_id=7)
            == 99
        )


def test_repetir_una_peticion_ya_en_cola_no_gasta_cupo() -> None:
    """La deduplicación va primero: devolver el job existente no es encolar otro."""
    from services import jobs

    repo = _cola(activos=jobs.MAX_JOBS_ACTIVOS_POR_ORG, existente={"id": 5})
    with patch.object(jobs, "_repo", repo):
        assert (
            jobs.enqueue(jobs.TIPO_FICHA_PLIEGO, {"licitacion_id": "EXP-1"}, organization_id=7) == 5
        )

    repo.contar_activos.assert_not_called()


def test_el_export_pdf_sin_deduplicar_tambien_tiene_tope() -> None:
    from services import jobs

    repo = _cola(activos=jobs.MAX_JOBS_ACTIVOS_POR_ORG)
    with patch.object(jobs, "_repo", repo):
        with pytest.raises(jobs.CuotaDeJobsExcedida):
            jobs.enqueue(
                jobs.TIPO_EXPORT_PDF, {"limit": 50000}, organization_id=7, deduplicar=False
            )


def test_el_trabajo_del_sistema_y_los_tipos_sin_cuota_no_se_cuentan() -> None:
    from services import jobs

    repo = _cola(activos=10_000)
    with patch.object(jobs, "_repo", repo):
        # Sin organización (trabajo del sistema).
        assert jobs.enqueue(jobs.TIPO_FICHA_PLIEGO, {"licitacion_id": "E"}) == 99
        # Un tipo que no es de usuario.
        assert jobs.enqueue(jobs.TIPO_DESPACHO_EVENTOS, {"motivo": "x"}, organization_id=7) == 99

    repo.contar_activos.assert_not_called()


async def _run_db_directo(fn: Any, *args: Any, **kwargs: Any) -> Any:
    return fn(*args, **kwargs)


@pytest.mark.parametrize(
    "ruta", ["extract_tender_fact_sheet_async", "enqueue_expediente_embeddings"]
)
def test_las_rutas_async_responden_429_cuando_la_cola_de_la_organizacion_esta_llena(
    ruta: str,
) -> None:
    from api.routes.licitaciones import pliegos
    from services.jobs import CuotaDeJobsExcedida

    with (
        patch.object(pliegos, "run_db", _run_db_directo),
        patch.object(pliegos._lic_repo, "exists", return_value=True),
        patch("services.jobs.enqueue", side_effect=CuotaDeJobsExcedida("cola llena")),
    ):
        with pytest.raises(HTTPException) as info:
            asyncio.run(
                getattr(pliegos, ruta)(ctx={"organization_id": 7, "user_key": "u"}, id_externo="E")
            )

    assert info.value.status_code == 429
    assert "cola llena" in str(info.value.detail)


# ── DOCX: bomba de descompresión ───────────────────────────────────────────────

_MIB = 1024 * 1024


def _zip(entradas: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archivo:
        for nombre, datos in entradas.items():
            archivo.writestr(nombre, datos)
    return buffer.getvalue()


def _bomba(megas: int = 20) -> bytes:
    """Un ``word/document.xml`` de ``megas`` MiB de ceros: ~1.000:1 deflatado.

    20 MiB por defecto: por debajo del tope por entrada (25 MiB), de modo que lo
    que lo rechaza es el ratio y no el tamaño declarado.
    """
    return _zip({"[Content_Types].xml": b"<x/>", "word/document.xml": b"\0" * (megas * _MIB)})


def _mentir_el_tamano(zip_bytes: bytes, declarado: int) -> bytes:
    """Reescribe ``file_size`` en la cabecera local y en el directorio central."""
    datos = bytearray(zip_bytes)
    central = datos.rfind(b"PK\x01\x02")
    struct.pack_into("<I", datos, central + 24, declarado)
    local = datos.find(b"PK\x03\x04", datos.find(b"word/document.xml") - 40)
    struct.pack_into("<I", datos, local + 22, declarado)
    return bytes(datos)


def test_una_bomba_de_deflate_se_rechaza_antes_de_python_docx() -> None:
    """scraper-datos-no-confiables-1 / ssrf-saliente-3 / deserializacion-ejecucion-2."""
    from scraper import document_fetcher as df

    docx = MagicMock()
    with (
        patch.object(df, "_importar_opcional", return_value=docx),
        pytest.raises(df.DocumentFetchError, match="ratio de compresión"),
    ):
        df._extract_docx_paginas(_bomba())

    docx.Document.assert_not_called()


def test_una_bomba_con_el_tamano_declarado_mentido_tambien_se_rechaza() -> None:
    """``ZipFile.read`` no acota por ``file_size``: se mide lo que sale de verdad."""
    from scraper import document_fetcher as df

    with pytest.raises(df.DocumentFetchError):
        df._acotar_docx(_mentir_el_tamano(_bomba(30), 1000))


def test_el_tope_total_del_docx_se_aplica_aunque_cada_parte_sea_pequena() -> None:
    from scraper import document_fetcher as df

    docx = _zip({f"word/parte{i}.xml": bytes(range(256)) * 8 for i in range(10)})
    with (
        patch.object(df.settings, "MAX_DOCUMENT_SIZE_BYTES", 5000),
        pytest.raises(df.DocumentFetchError, match="supera"),
    ):
        df._acotar_docx(docx)


def test_un_docx_normal_sigue_extrayendose() -> None:
    from scraper import document_fetcher as df

    documento = SimpleNamespace(paragraphs=[SimpleNamespace(text="Cláusula primera")], tables=[])
    docx = MagicMock()
    docx.Document.return_value = documento
    contenido = _zip(
        {"[Content_Types].xml": b"<x/>", "word/document.xml": b"<w>Cl\xc3\xa1usula primera</w>"}
    )
    with patch.object(df, "_importar_opcional", return_value=docx):
        assert df._extract_docx_paginas(contenido) == ["Cláusula primera"]


def test_una_entrada_zip_con_crc_roto_es_document_fetch_error() -> None:
    """Un fallo duro de ESTE documento acaba en ``error`` y no se reintenta: antes
    escapaba como ``BadZipFile`` crudo."""
    from scraper import document_fetcher as df

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archivo:
        archivo.writestr("a.txt", b"hola mundo " * 100)
    datos = bytearray(buffer.getvalue())
    datos[datos.find(b"hola mundo")] ^= 0xFF  # el CRC ya no coincide
    with zipfile.ZipFile(io.BytesIO(bytes(datos))) as archivo:
        info = archivo.infolist()[0]
        with pytest.raises(df.DocumentFetchError, match="ilegible"):
            df._leer_entrada_acotada(archivo, info, tope=_MIB, que="Entrada 'a.txt'")


# ── Calendario ICS: caché privada ──────────────────────────────────────────────


def test_el_ics_con_enlace_firmado_no_es_cacheable() -> None:
    """authz-usuario-rutas-4: sin cookie ni cabecera el middleware no pone nada."""
    from api.routes import exports

    with (
        patch.object(exports, "run_db", _run_db_directo),
        patch.object(exports, "_verificar_firma_calendario", return_value=True),
        patch("db.users.get_user_by_id", return_value={"id": 7, "email": "a@example.test"}),
        patch.object(exports, "_organizacion_del_calendario", AsyncMock(return_value=1)),
        patch.object(exports, "_eventos_calendario", return_value=[]),
    ):
        respuesta = asyncio.run(
            exports.calendario_ics(
                api_key_raw=None, u=7, t="kid.firma", background_tasks=BackgroundTasks()
            )
        )

    assert respuesta.headers["cache-control"] == "private, no-store"
    assert respuesta.media_type.startswith("text/calendar")


def test_el_enlace_del_calendario_se_entrega_con_no_store() -> None:
    from api.routes import exports

    salida = Response()
    with (
        patch.object(exports, "run_db", _run_db_directo),
        patch.object(exports, "_organizacion_del_calendario", AsyncMock(return_value=1)),
        patch.object(exports, "_eventos_calendario", return_value=[]),
        patch.object(exports, "_firma_calendario", return_value="kid.firma"),
        patch.object(exports, "log_event"),
    ):
        enlace = asyncio.run(exports.calendario_enlace(salida, ctx={"user_id": 7, "user_key": "k"}))

    assert salida.headers["cache-control"] == "private, no-store"
    assert enlace.path.endswith("?u=7&t=kid.firma")
