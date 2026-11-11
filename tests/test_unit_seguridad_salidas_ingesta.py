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


def test_una_bomba_de_deflate_en_el_docx_se_rechaza_sin_materializarla() -> None:
    """scraper-datos-no-confiables-1 / ssrf-saliente-3 / deserializacion-ejecucion-2.

    Desde 2026-11 el DOCX se lee con la biblioteca estándar: su
    ``word/document.xml`` pasa por la lectura acotada del ZIP.
    """
    from scraper import document_fetcher as df

    with pytest.raises(df.DocumentFetchError, match="ratio de compresión"):
        df._extract_docx_paginas(_bomba())


def test_una_bomba_con_el_tamano_declarado_mentido_tambien_se_rechaza() -> None:
    """Un ``file_size`` falso no deja pasar la bomba: ``zipfile`` corta en lo
    declarado y el CRC no cuadra, así que es ``error`` y no se materializa."""
    from scraper import document_fetcher as df

    with pytest.raises(df.DocumentFetchError, match=r"del DOCX: entrada ilegible"):
        df._extract_docx_paginas(_mentir_el_tamano(_bomba(30), 1000))


def test_el_tope_de_tamano_se_aplica_a_la_parte_principal_del_docx() -> None:
    from scraper import document_fetcher as df

    docx = _zip({"word/document.xml": bytes(range(256)) * 40})
    with (
        patch.object(df.settings, "MAX_DOCUMENT_SIZE_BYTES", 5000),
        pytest.raises(df.DocumentFetchError, match="supera"),
    ):
        df._extract_docx_paginas(docx)


def test_un_docx_normal_sigue_extrayendose() -> None:
    from scraper import document_fetcher as df

    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>Cl\u00e1usula primera</w:t></w:r></w:p></w:body></w:document>"
    )
    contenido = _zip({"[Content_Types].xml": b"<x/>", "word/document.xml": xml.encode()})
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


def test_el_enlace_del_calendario_con_api_key_exige_pursuits_read() -> None:
    """TF-SEC-10: una API key con solo `exports:read` no puede emitir el enlace."""
    from fastapi import HTTPException

    from api.routes import exports

    salida = Response()
    ctx = {
        "user_id": 7,
        "user_key": "k",
        "auth_method": "api_key",
        "scopes": frozenset({"exports:read"}),
    }
    with pytest.raises(HTTPException) as exc:
        asyncio.run(exports.calendario_enlace(salida, ctx=ctx))
    assert exc.value.status_code == 403


def test_metrics_rechaza_api_key_de_administrador_degradado() -> None:
    """TF-SEC-09: si el dueño perdió `is_admin`, su clave `metrics:read` da 403."""
    from fastapi import HTTPException
    from starlette.requests import Request

    from api.auth import AuthContext
    from api.routes import metrics

    ctx = AuthContext(
        key_hash="h",
        key_id=1,
        scopes=frozenset({"metrics:read"}),
        user_id=7,
        owner={"id": 7, "is_admin": 0},
    )
    req = Request({"type": "http", "method": "GET", "path": "/metrics", "headers": []})
    with (
        patch.object(metrics, "validate_api_key_credential", AsyncMock(return_value=ctx)),
        pytest.raises(HTTPException) as exc,
    ):
        asyncio.run(
            metrics.require_metrics_reader(
                req, api_key_raw="raw", bearer=None, background_tasks=BackgroundTasks()
            )
        )
    assert exc.value.status_code == 403


def test_rotate_my_key_rechaza_scopes_reservados_tras_degradar_admin() -> None:
    """TF-SEC-09: rotar una clave `*` exige seguir siendo administrador."""
    from fastapi import HTTPException

    from api.routes import me

    rotatable = {"id": 9, "user_id": 7, "name": "ops", "scopes": "*"}
    with (
        patch.object(me._key_repo, "get_rotatable", return_value=rotatable),
        pytest.raises(HTTPException) as exc,
    ):
        me.rotate_my_key(
            ctx={"user_id": 7, "user_key": "k", "is_admin": False},
            key_id=9,
            grace_days=7,
        )
    assert exc.value.status_code == 403


def test_accept_invitation_token_acepta_solo_la_invitacion_del_token() -> None:
    """TF-SEC-07: canjear un token no acepta invitaciones pendientes de otras organizaciones."""
    from services import organizations as svc

    fila = {"id": 42, "organization_id": 10, "email": "ana@empresa.test"}
    org = {
        "id": 10,
        "name": "Equipo A",
        "is_personal": False,
        "role": "member",
        "created_at": "2026-01-01T00:00:00Z",
    }
    with (
        patch.object(svc, "_invitation_signature_valid", return_value=True),
        patch.object(svc._repo, "get_pending_invitation_by_token", return_value=fila),
        patch.object(svc._repo, "accept_invitation_by_id", return_value=[fila]) as por_id,
        patch.object(svc._repo, "accept_invitations_for_email") as por_correo,
        patch.object(svc, "_aplicar_plantillas_de"),
        patch.object(svc._repo, "get_for_user", return_value=org),
    ):
        res = svc.accept_invitation_token(7, "Ana@empresa.test", "tok.sig")
    assert res.id == 10
    por_id.assert_called_once_with(42, 7)
    por_correo.assert_not_called()


def test_oauth_rechaza_cuenta_desactivada_sin_consumir_invitaciones() -> None:
    """TF-SEC-12: una cuenta con `deactivated_at` lanza CuentaDesactivadaError."""
    from contextlib import contextmanager

    from db import users as users_mod

    class _Cur:
        def fetchone(self) -> tuple[int, str]:
            return (7, "2026-10-01T00:00:00Z")

    class _Conn:
        def execute(self, _sql: str, _params: object = ()) -> _Cur:
            return _Cur()

    @contextmanager
    def _connect():  # type: ignore[no-untyped-def]
        yield _Conn()

    with (
        patch.object(users_mod, "connect", _connect),
        pytest.raises(users_mod.CuentaDesactivadaError) as exc,
    ):
        users_mod.get_or_create_oauth_user(
            email="Ana@Empresa.test", oauth_provider="google", oauth_sub="sub-1"
        )
    assert exc.value.user_id == 7


def test_pursuit_tasks_acota_por_pursuit_id_y_enmascara_export_rgpd() -> None:
    """TF-SEC-04 y P-3: update/delete acotan por pursuit_id y export_for_user enmascara."""
    from contextlib import contextmanager

    from db.repositories import pursuit_tasks as repo_mod
    from services import pursuit_tasks as svc_mod

    sqls: list[tuple[str, tuple[object, ...]]] = []

    class _Cur:
        rowcount = 1
        description = (("id",), ("titulo",), ("vence",), ("estado",))

        def fetchall(self) -> list[tuple[object, ...]]:
            return [(1, None, None, None)]

    class _Conn:
        def execute(self, sql: str, params: tuple[object, ...] = ()) -> _Cur:
            sqls.append((sql, params))
            return _Cur()

    @contextmanager
    def _conn():  # type: ignore[no-untyped-def]
        yield _Conn()

    with patch.object(repo_mod, "connect_read", _conn):
        repo_mod.PursuitTasksRepository().export_for_user(7)
    assert "organization_memberships" in sqls[0][0]
    assert "m.status = 'active'" in sqls[0][0]

    @contextmanager
    def _alcance(_uid: int, _oid: int | None, write: bool = False):  # type: ignore[no-untyped-def]
        assert write is True
        yield (5, "member")

    with (
        patch.object(svc_mod, "alcance_resuelto", _alcance),
        patch.object(svc_mod, "_require_pursuit"),
        patch.object(svc_mod, "_sincronizar_next_action"),
        patch.object(svc_mod._repo, "delete", return_value=True) as borrar,
    ):
        svc_mod.delete_task(7, 99, 12, organization_id=5)
    borrar.assert_called_once_with(5, 12, pursuit_id=99)


def test_apply_weights_proposal_no_arrastra_afinidad_de_otra_organizacion() -> None:
    """TF-SEC-05: aplicar pesos en Org B no copia afinidad_keywords ni cpvs de Org A."""
    from contextlib import contextmanager
    from types import SimpleNamespace

    from services import pursuits as svc

    @contextmanager
    def _alcance(_uid: int, _oid: int | None, write: bool = False):  # type: ignore[no-untyped-def]
        yield (20, "owner")

    propuesta = SimpleNamespace(
        estado="propuesta",
        n_cierres=10,
        n_ganadas=5,
        n_perdidas=5,
        n_abiertas=0,
        n_descartadas=0,
        fuente="cierres",
        minimo_cierres=10,
        pesos_actuales={"afinidad": 25, "competencia": 25, "importe": 25, "plazo": 25},
        pesos_propuestos={"afinidad": 40, "competencia": 20, "importe": 20, "plazo": 20},
    )
    previo_otra_org = {
        "organization_id": 10,
        "visibility": "organization",
        "weights": {"afinidad": 25, "competencia": 25, "importe": 25, "plazo": 25},
        "afinidad_keywords": ["secreto-org-10"],
        "cpvs": ["72000000"],
        "importe_min": 1000.0,
        "importe_max": 5000.0,
    }
    capturado: dict[str, object] = {}

    def _upsert(profile: dict[str, object], org_id: int, vis: str, *, user_id: int) -> None:
        capturado.update({"profile": profile, "org_id": org_id, "vis": vis, "user_id": user_id})

    with (
        patch.object(svc, "alcance_resuelto", _alcance),
        patch.object(svc, "get_weights_proposal", return_value=propuesta),
        patch("db.repositories.user_profiles.get_own_user_profile", return_value=previo_otra_org),
        patch("db.repositories.user_profiles.upsert_user_profile", side_effect=_upsert),
        patch("shared.cache.invalidate_user_scoped"),
        patch("shared.cache.invalidate_organization_scoped"),
        patch("db.audit.log_event"),
    ):
        svc.apply_weights_proposal(7, user_key="u7", organization_id=20)

    perfil = capturado["profile"]
    assert isinstance(perfil, dict)
    assert perfil["afinidad_keywords"] is None
    assert perfil["cpvs"] is None


def test_remove_item_y_remove_entry_exigen_ser_dueno() -> None:
    """TF-SEC-06: borrar un favorito o empresa vigilada no admite `visibility = 'organization' OR`."""
    from contextlib import contextmanager

    from db import watchlist_empresas as we_mod
    from db.repositories import watchlist as wl_mod

    sqls: list[str] = []

    class _Cur:
        rowcount = 0

    class _Conn:
        def execute(self, sql: str, _params: object = ()) -> _Cur:
            sqls.append(sql)
            return _Cur()

    @contextmanager
    def _conn():  # type: ignore[no-untyped-def]
        yield _Conn()

    with (
        patch.object(wl_mod, "connect", _conn),
        patch.object(we_mod, "connect", _conn),
        patch("db.repositories.follows.olvidar"),
    ):
        wl_mod.WatchlistRepository().remove_item(7, "EXP-1", 5)
        we_mod.remove_entry(7, 12, 5)

    assert len(sqls) == 2
    for sentencia in sqls:
        assert "visibility = 'organization'" not in sentencia
