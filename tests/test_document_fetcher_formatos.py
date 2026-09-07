"""Formatos, OCR y almacén de binarios del fetcher de pliegos (S8.1–S8.3).

Los fixtures binarios viven en ``tests/fixtures/documentos/`` y se generan con
``_generar_fixtures.py``, que documenta qué contiene cada uno.

Dos bloques:

- **Unitario** (sin BD): extracción por formato, convención de página lógica,
  límites del ZIP y la regla de oro del OCR — un PDF con texto no pasa por él.
- **Integración** (``tmp_db``): lo que se persiste. Es donde se comprueba que la
  re-extracción con la fuente caída termina en ``extracted`` leyendo el bucket,
  que ``unsupported`` conserva su content-type y que la purga de retención
  cuenta lo que borra.

``ocrmypdf`` es un binario del sistema y no está en todos los entornos: el
camino real lleva ``skipif`` y el resto usa un doble, que es lo que permite
verificar la **política** (cuándo se invoca y qué se marca) sin depender de que
tesseract esté instalado.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import patch

import pybreaker
import pytest

import scraper.document_fetcher as df
from scraper.document_fetcher import (
    CONTENT_TYPE_DOCX,
    CONTENT_TYPE_ODT,
    CONTENT_TYPE_PDF,
    CONTENT_TYPE_ZIP,
    DocumentFetchError,
    UnsupportedDocumentError,
    _extract_paginas,
    fetch_and_extract,
    ocr_binario,
    reextract_from_blob,
    supported_content_types,
)
from shared.object_store import (
    document_blob_key,
    get_object_store,
    reset_object_store_cache,
)

FIXTURES = Path(__file__).parent / "fixtures" / "documentos"
FRASE = "Objeto del contrato: mantenimiento de la plataforma SAP"


def _fixture(nombre: str) -> bytes:
    return (FIXTURES / nombre).read_bytes()


@pytest.fixture
def almacen_ficheros(tmp_path, monkeypatch, _sin_almacen_por_defecto):
    """Almacén de objetos sobre disco — la implementación que pide S8.1."""
    monkeypatch.setenv("DOCUMENT_BLOB_DIR", str(tmp_path / "bucket"))
    monkeypatch.delenv("DOCUMENT_BLOB_BACKEND", raising=False)
    monkeypatch.delenv("DOCUMENT_BLOB_BUCKET", raising=False)
    monkeypatch.delenv("DOCUMENT_BLOB_PREFIX", raising=False)
    reset_object_store_cache()
    yield get_object_store()
    reset_object_store_cache()


@pytest.fixture(autouse=True)
def _sin_almacen_por_defecto(monkeypatch):
    """Un test que no pida ``almacen_ficheros`` corre sin bucket, como hoy."""
    monkeypatch.delenv("DOCUMENT_BLOB_DIR", raising=False)
    monkeypatch.delenv("DOCUMENT_BLOB_BUCKET", raising=False)
    reset_object_store_cache()


def _sin_dependencia(monkeypatch, paquete: str) -> None:
    """Simula que una dependencia opcional no está instalada.

    Se fuerza en vez de confiar en el entorno: el test tiene que decir lo mismo
    en el runner de CI (donde ``[pliegos]`` sí está) que en una máquina pelada.
    """
    real = importlib.import_module

    def _falso(nombre: str, *args, **kwargs):
        if nombre == paquete or nombre.startswith(f"{paquete}."):
            raise ImportError(f"simulado: {paquete} no instalado")
        return real(nombre, *args, **kwargs)

    monkeypatch.setattr(df.importlib, "import_module", _falso)


# ── S8.2: formatos ─────────────────────────────────────────────────────────


class TestFormatosSoportados:
    def test_la_lista_declarada_y_el_despacho_no_divergen(self):
        """Cada content-type declarado tiene que tener rama de extracción."""
        for content_type in supported_content_types():
            try:
                df._extraer_paginas_de_tipo(b"", content_type)
            except UnsupportedDocumentError as exc:
                # "no está instalado" es legítimo (extra opcional ausente);
                # "no soportado" significa que el despacho no tiene esa rama.
                assert "no soportado" not in str(exc), (
                    f"{content_type} está declarado y no se despacha"
                )
            except DocumentFetchError:
                pass  # bytes vacíos: el formato se reconoce, el contenido no vale

    def test_docx_produce_paginas_logicas_con_su_texto(self):
        paginas = _extract_paginas(_fixture("pliego.docx"), CONTENT_TYPE_DOCX)
        assert len(paginas) > 1  # 59 párrafos / 40 por página lógica
        assert FRASE in paginas[0].texto
        assert all(p.ocr is False for p in paginas)

    def test_odt_produce_paginas_logicas_con_su_texto(self):
        paginas = _extract_paginas(_fixture("pliego.odt"), CONTENT_TYPE_ODT)
        assert len(paginas) > 1
        assert FRASE in paginas[0].texto

    def test_la_pagina_logica_agrupa_el_numero_declarado_de_parrafos(self):
        """La convención del módulo es lo que ancla los offsets: se fija aquí."""
        paginas = _extract_paginas(_fixture("pliego.docx"), CONTENT_TYPE_DOCX)
        assert paginas[0].texto.count("\n") + 1 == df._PARRAFOS_POR_PAGINA_LOGICA

    def test_zip_expande_los_pdf_y_docx_de_dentro(self):
        paginas = _extract_paginas(_fixture("adjuntos.zip"), CONTENT_TYPE_ZIP)
        texto = "\n".join(p.texto for p in paginas)
        assert FRASE in texto
        assert "CLAUSULAS ADMINISTRATIVAS" in texto  # el DOCX interno

    def test_el_zip_anidado_se_ignora_sin_romper_el_resto(self):
        """Sin recursión: ``04_anexo.zip`` no aporta páginas y no lanza."""
        assert _extract_paginas(_fixture("adjuntos.zip"), CONTENT_TYPE_ZIP)

    def test_zip_con_demasiadas_entradas_se_rechaza(self):
        with pytest.raises(DocumentFetchError, match="supera el máximo"):
            _extract_paginas(_fixture("zip_muchas_entradas.zip"), CONTENT_TYPE_ZIP)

    def test_zip_bomb_se_corta_por_tamaño_descomprimido(self, monkeypatch):
        """El tope no se fía de ``file_size``: la lectura misma va acotada."""
        monkeypatch.setattr(df.settings, "MAX_DOCUMENT_SIZE_BYTES", 1_000_000)
        with pytest.raises(DocumentFetchError, match="descomprimido"):
            _extract_paginas(_fixture("zip_bomb.zip"), CONTENT_TYPE_ZIP)

    def test_content_type_desconocido_es_unsupported_con_su_valor(self):
        with pytest.raises(UnsupportedDocumentError) as exc:
            _extract_paginas(b"\xd0\xcf\x11\xe0", "application/msword")
        assert exc.value.content_type == "application/msword"

    def test_sin_python_docx_el_docx_es_unsupported_no_error(self, monkeypatch):
        """La dependencia opcional que falta es cobertura ausente, no un fallo."""
        _sin_dependencia(monkeypatch, "docx")
        with pytest.raises(UnsupportedDocumentError) as exc:
            _extract_paginas(_fixture("pliego.docx"), CONTENT_TYPE_DOCX)
        assert exc.value.content_type == CONTENT_TYPE_DOCX
        assert "python-docx" in str(exc.value)

    def test_sin_odfpy_el_odt_es_unsupported_no_error(self, monkeypatch):
        _sin_dependencia(monkeypatch, "odf")
        with pytest.raises(UnsupportedDocumentError) as exc:
            _extract_paginas(_fixture("pliego.odt"), CONTENT_TYPE_ODT)
        assert exc.value.content_type == CONTENT_TYPE_ODT

    def test_docx_corrupto_es_error_no_unsupported(self):
        """Un fichero roto no es un formato sin soporte: no se cuentan juntos."""
        with pytest.raises(DocumentFetchError) as exc:
            _extract_paginas(b"esto no es un docx", CONTENT_TYPE_DOCX)
        assert not isinstance(exc.value, UnsupportedDocumentError)


# ── S8.3: OCR ──────────────────────────────────────────────────────────────


class TestOcr:
    def test_un_pdf_con_texto_no_pasa_por_ocr(self, monkeypatch):
        """Criterio de aceptación de S8.3, y el que ahorra minutos por documento."""
        llamadas: list[bytes] = []
        monkeypatch.setattr(df, "_ocr_pdf", lambda datos: llamadas.append(datos) or None)

        paginas = _extract_paginas(_fixture("pliego_con_texto.pdf"), CONTENT_TYPE_PDF)

        assert llamadas == []
        assert FRASE in paginas[0].texto
        assert all(p.ocr is False for p in paginas)

    def test_un_escaneado_cae_al_ocr_y_marca_las_paginas(self, monkeypatch):
        """Doble de ``ocrmypdf``: devuelve el PDF que sí tiene capa de texto."""
        monkeypatch.setattr(df, "_ocr_pdf", lambda _datos: _fixture("pliego_con_texto.pdf"))

        paginas = _extract_paginas(_fixture("pliego_escaneado.pdf"), CONTENT_TYPE_PDF)

        assert all(p.ocr is True for p in paginas)
        assert FRASE in paginas[0].texto

    def test_sin_ocrmypdf_el_escaneado_degrada_al_error_de_siempre(self, monkeypatch):
        monkeypatch.setattr(df.shutil, "which", lambda _nombre: None)
        with pytest.raises(DocumentFetchError, match="sin texto extraíble"):
            _extract_paginas(_fixture("pliego_escaneado.pdf"), CONTENT_TYPE_PDF)

    def test_el_ocr_se_puede_apagar_por_entorno(self, monkeypatch):
        monkeypatch.setenv("DOCUMENT_OCR_ENABLED", "0")
        assert ocr_binario() is None

    def test_un_fallo_del_binario_no_rompe_el_lote(self, monkeypatch, tmp_path):
        """``ocrmypdf`` que devuelve != 0 degrada: ``None``, no excepción."""
        falso = tmp_path / "ocrmypdf-falso"
        falso.write_text("")
        monkeypatch.setattr(df.shutil, "which", lambda _nombre: str(falso))
        assert df._ocr_pdf(b"%PDF-1.4") is None

    @pytest.mark.skipif(ocr_binario() is None, reason="ocrmypdf no instalado en este entorno")
    @pytest.mark.slow
    def test_ocrmypdf_real_extrae_texto_del_escaneado(self):
        paginas = _extract_paginas(_fixture("pliego_escaneado.pdf"), CONTENT_TYPE_PDF)
        assert all(p.ocr is True for p in paginas)
        assert paginas[0].texto.strip()


# ── Persistencia (integración: exige Postgres) ─────────────────────────────


@pytest.fixture
def repo(tmp_db):
    from db.repositories.documentos import DocumentosRepository

    _db_mod, _ = tmp_db
    return DocumentosRepository()


def _seed(
    repo,
    licitacion_id: str = "EXP-S8-1",
    *,
    estado: str | None = None,
    actualizacion: str | None = None,
) -> dict:
    from db.database import DocumentoReferencia, connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion, "
            "estado, fecha_actualizacion_fuente) "
            "VALUES (%s, %s, 'placsp', CURRENT_TIMESTAMP, %s, %s)",
            (licitacion_id, f"Contrato {licitacion_id}", estado, actualizacion),
        )
    repo.upsert_meta(
        licitacion_id,
        [
            DocumentoReferencia(
                tipo="legal",
                uri=f"https://placsp.example/{licitacion_id}.pdf",
                filename="PCAP.pdf",
                source_hash=f"hash{licitacion_id.replace('-', '')}",
            )
        ],
    )
    return next(d for d in repo.list_pendientes() if d["licitacion_id"] == licitacion_id)


class TestBinarioConservado:
    def test_la_descarga_guarda_el_binario_bajo_documentos_source_hash(
        self, repo, almacen_ficheros
    ):
        doc = _seed(repo)
        with patch(
            "scraper.document_fetcher._download_bytes",
            return_value=(_fixture("pliego_con_texto.pdf"), CONTENT_TYPE_PDF),
        ):
            assert fetch_and_extract(doc) == "extracted"

        fila = repo.get(doc["id"])
        assert fila is not None
        assert fila["blob_key"] == f"documentos/{doc['source_hash']}"
        assert almacen_ficheros.get(fila["blob_key"]) == _fixture("pliego_con_texto.pdf")

    def test_sin_almacen_configurado_todo_sigue_igual(self, repo):
        """La ausencia de bucket no puede cambiar el resultado de la ingesta."""
        doc = _seed(repo)
        with patch(
            "scraper.document_fetcher._download_bytes",
            return_value=(_fixture("pliego_con_texto.pdf"), CONTENT_TYPE_PDF),
        ):
            assert fetch_and_extract(doc) == "extracted"

        fila = repo.get(doc["id"])
        assert fila is not None and fila["blob_key"] is None

    def test_la_fuente_caida_se_resuelve_leyendo_el_bucket(self, repo, almacen_ficheros):
        """Criterio de aceptación de S8.1: termina en ``extracted``, sin PLACSP."""
        doc = _seed(repo)
        clave = document_blob_key(doc["source_hash"])
        assert clave is not None
        almacen_ficheros.put(clave, _fixture("pliego_con_texto.pdf"))
        repo.mark_blob(doc["id"], blob_key=clave)
        doc = repo.list_pendientes()[0]

        with patch(
            "scraper.document_fetcher._download_bytes",
            side_effect=ValueError("PLACSP no responde"),
        ):
            assert fetch_and_extract(doc) == "extracted"

        fila = repo.get(doc["id"])
        assert fila is not None
        assert fila["status"] == "extracted"
        assert FRASE in (fila["texto"] or "")

    def test_sin_binario_guardado_la_fuente_caida_sigue_siendo_error(self, repo):
        doc = _seed(repo)
        with patch(
            "scraper.document_fetcher._download_bytes",
            side_effect=ValueError("PLACSP no responde"),
        ):
            assert fetch_and_extract(doc) == "error"

    def test_el_breaker_abierto_con_binario_no_desperdicia_el_turno(self, repo, almacen_ficheros):
        doc = _seed(repo)
        clave = document_blob_key(doc["source_hash"])
        assert clave is not None
        almacen_ficheros.put(clave, _fixture("pliego_con_texto.pdf"))
        repo.mark_blob(doc["id"], blob_key=clave)
        doc = repo.list_pendientes()[0]

        with patch(
            "scraper.document_fetcher._download_bytes",
            side_effect=pybreaker.CircuitBreakerError("circuit breaker still open"),
        ):
            assert fetch_and_extract(doc) == "extracted"

    def test_el_breaker_abierto_sin_binario_sigue_dejando_la_fila_pendiente(self, repo):
        """Regresión de v88: no marcar error por una condición del servidor."""
        doc = _seed(repo)
        with patch(
            "scraper.document_fetcher._download_bytes",
            side_effect=pybreaker.CircuitBreakerError("circuit breaker still open"),
        ):
            assert fetch_and_extract(doc) == "skipped"
        fila = repo.get(doc["id"])
        assert fila is not None and fila["status"] == "pending"

    def test_reextract_from_blob_no_toca_la_fuente(self, repo, almacen_ficheros):
        doc = _seed(repo)
        with patch(
            "scraper.document_fetcher._download_bytes",
            return_value=(_fixture("pliego_con_texto.pdf"), CONTENT_TYPE_PDF),
        ):
            fetch_and_extract(doc)

        with patch(
            "scraper.document_fetcher._download_bytes",
            side_effect=AssertionError("la re-extracción no puede volver a la fuente"),
        ):
            assert reextract_from_blob(doc["id"]) == "extracted"

    def test_reextract_sin_binario_dice_missing(self, repo, almacen_ficheros):
        doc = _seed(repo)
        assert reextract_from_blob(doc["id"]) == "missing"


class TestEstadoUnsupported:
    def test_un_formato_sin_soporte_no_se_marca_error(self, repo):
        doc = _seed(repo)
        with patch(
            "scraper.document_fetcher._download_bytes",
            return_value=(b"\xd0\xcf\x11\xe0", "application/msword"),
        ):
            assert fetch_and_extract(doc) == "unsupported"

        fila = repo.get(doc["id"])
        assert fila is not None
        assert fila["status"] == "unsupported"
        assert fila["content_type"] == "application/msword"

    def test_el_desglose_por_formato_separa_lo_no_soportado_de_lo_roto(self, repo):
        doc_ok = _seed(repo, "EXP-S8-OK")
        doc_raro = _seed(repo, "EXP-S8-RARO")
        with patch(
            "scraper.document_fetcher._download_bytes",
            return_value=(_fixture("pliego_con_texto.pdf"), CONTENT_TYPE_PDF),
        ):
            fetch_and_extract(doc_ok)
        with patch(
            "scraper.document_fetcher._download_bytes",
            return_value=(b"\xd0\xcf\x11\xe0", "application/msword"),
        ):
            fetch_and_extract(doc_raro)

        por_formato = {f["content_type"]: f for f in repo.formato_counts()}
        assert por_formato[CONTENT_TYPE_PDF]["extracted"] == 1
        assert por_formato["application/msword"]["unsupported"] == 1
        assert por_formato["application/msword"]["error"] == 0
        assert repo.status_counts()["unsupported"] == 1

    def test_quality_publica_el_desglose_y_la_ocupacion_del_bucket(self, repo, almacen_ficheros):
        doc = _seed(repo)
        with patch(
            "scraper.document_fetcher._download_bytes",
            return_value=(_fixture("pliego_con_texto.pdf"), CONTENT_TYPE_PDF),
        ):
            fetch_and_extract(doc)

        from services.analytics.quality import get_quality

        resultado = get_quality()
        formatos = {f.content_type: f for f in resultado.documentos_por_formato}
        assert formatos[CONTENT_TYPE_PDF].extracted == 1
        assert resultado.blob_store_objetos == 1
        assert resultado.blob_store_bytes == len(_fixture("pliego_con_texto.pdf"))

    def test_quality_no_inventa_un_cero_sin_bucket(self, repo):
        from services.analytics.quality import get_quality

        resultado = get_quality()
        assert resultado.blob_store_objetos is None
        assert resultado.blob_store_bytes is None


class TestPaginasOcrPersistidas:
    def test_la_marca_de_ocr_llega_a_documento_pages(self, repo, monkeypatch):
        monkeypatch.setattr(df, "_ocr_pdf", lambda _datos: _fixture("pliego_con_texto.pdf"))
        doc = _seed(repo)
        with patch(
            "scraper.document_fetcher._download_bytes",
            return_value=(_fixture("pliego_escaneado.pdf"), CONTENT_TYPE_PDF),
        ):
            assert fetch_and_extract(doc) == "extracted"

        paginas = repo.list_pages(doc["id"])
        assert paginas and all(p["ocr"] is True for p in paginas)

    def test_un_pdf_con_texto_persiste_ocr_false(self, repo):
        doc = _seed(repo)
        with patch(
            "scraper.document_fetcher._download_bytes",
            return_value=(_fixture("pliego_con_texto.pdf"), CONTENT_TYPE_PDF),
        ):
            fetch_and_extract(doc)
        assert all(p["ocr"] is False for p in repo.list_pages(doc["id"]))

    def test_la_ficha_cita_con_ocr_true(self, repo, monkeypatch):
        """La procedencia viaja hasta ``EvidenceRef`` (S8.3)."""
        from services.rag.fact_sheet import _validated_evidence
        from shared.tender_facts import EvidenceRef

        monkeypatch.setattr(df, "_ocr_pdf", lambda _datos: _fixture("pliego_con_texto.pdf"))
        doc = _seed(repo)
        with patch(
            "scraper.document_fetcher._download_bytes",
            return_value=(_fixture("pliego_escaneado.pdf"), CONTENT_TYPE_PDF),
        ):
            fetch_and_extract(doc)

        paginas = repo.list_pages_by_licitacion("EXP-S8-1")
        indice = {(int(p["documento_id"]), int(p["page_number"])): p for p in paginas}
        cita = EvidenceRef(documento_id=doc["id"], page_number=1, quote=FRASE)

        validada = _validated_evidence(cita, indice)

        assert validada is not None
        assert validada.ocr is True

    def test_evidence_ref_es_aditivo_y_por_defecto_no_es_ocr(self):
        """El campo es nuevo: una ficha ya persistida se relee sin él."""
        from shared.tender_facts import EvidenceRef

        assert EvidenceRef(documento_id=1, page_number=1, quote="x").ocr is False


class TestRetencionDeBinarios:
    def _preparar(self, repo, almacen, licitacion_id, *, estado, actualizacion):
        doc = _seed(repo, licitacion_id, estado=estado, actualizacion=actualizacion)
        clave = document_blob_key(doc["source_hash"])
        assert clave is not None
        almacen.put(clave, b"binario del pliego")
        repo.mark_blob(doc["id"], blob_key=clave)
        return doc, clave

    def test_purga_los_binarios_de_expedientes_cerrados_y_lo_cuenta(self, repo, almacen_ficheros):
        from scheduler.jobs.retention_cleanup import _purgar_binarios_expedientes_cerrados

        _doc, clave = self._preparar(
            repo,
            almacen_ficheros,
            "EXP-S8-VIEJO",
            estado="ADJ",
            actualizacion="2020-01-01T00:00:00+00:00",
        )

        resultado = _purgar_binarios_expedientes_cerrados(apply=True)

        assert resultado == {"candidatos": 1, "borrados": 1, "claves_olvidadas": 1}
        assert almacen_ficheros.get(clave) is None

    def test_no_purga_expedientes_abiertos_ni_cierres_recientes(self, repo, almacen_ficheros):
        from scheduler.jobs.retention_cleanup import _purgar_binarios_expedientes_cerrados

        self._preparar(
            repo,
            almacen_ficheros,
            "EXP-S8-ABIERTO",
            estado="PUB",
            actualizacion="2020-01-01T00:00:00+00:00",
        )
        self._preparar(
            repo,
            almacen_ficheros,
            "EXP-S8-RECIENTE",
            estado="ADJ",
            actualizacion="2026-09-01T00:00:00+00:00",
        )

        assert _purgar_binarios_expedientes_cerrados(apply=True)["candidatos"] == 0

    def test_la_clave_se_olvida_despues_de_borrar_el_objeto(self, repo, almacen_ficheros):
        from scheduler.jobs.retention_cleanup import _purgar_binarios_expedientes_cerrados

        doc, _clave = self._preparar(
            repo,
            almacen_ficheros,
            "EXP-S8-ORDEN",
            estado="RES",
            actualizacion="2019-05-05T00:00:00+00:00",
        )
        _purgar_binarios_expedientes_cerrados(apply=True)

        fila = repo.get(doc["id"])
        assert fila is not None and fila["blob_key"] is None

    def test_sin_almacen_la_purga_no_hace_nada(self, repo):
        from scheduler.jobs.retention_cleanup import _purgar_binarios_expedientes_cerrados

        assert _purgar_binarios_expedientes_cerrados(apply=True) == {
            "candidatos": 0,
            "borrados": 0,
            "claves_olvidadas": 0,
        }
