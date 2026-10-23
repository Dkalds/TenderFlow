"""El PDF de una resolución TACRC vinculada entra como documento de su licitación.

Unitario: la forma de la referencia (tipo, identidad, URL normalizada) y que
el host está en la allowlist. Integración (``tmp_db``): la pasada de ``run``
la escribe una sola vez aunque se repita, y no escribe nada para una
resolución sin vincular.
"""

from __future__ import annotations

import pytest

from scraper.connectors import REGISTERED_SOURCES, tacrc
from scraper.connectors.tacrc import referencia_documento, registrar_documentos, run

_INDEX_HTML = """
<html><body><table>
  <tr>
    <td><a href="https://www.hacienda.gob.es/tacrc/resoluciones/año 2026/recurso 99-2026 (res 123) 15-03-2026.pdf">Resolución nº 123/2026</a></td>
    <td>Recurso nº 99/2026 — Expediente: EXP-2026-42 — 15/03/2026 — Estimado.</td>
  </tr>
  <tr>
    <td><a href="https://www.hacienda.gob.es/tacrc/res_0124_2026.pdf">Resolución nº 124/2026</a></td>
    <td>Recurso nº 101/2026 — Expediente: SIN-LICITACION — 2026-03-16 — Desestimado.</td>
  </tr>
</table></body></html>
"""


def test_la_referencia_es_un_adjunto_additional_con_identidad_estable():
    ref = referencia_documento(
        "1758/2025",
        "https://www.hacienda.gob.es/tacrc/resoluciones/año 2025/recurso 1745-2025 (res 1758).pdf",
    )
    assert ref.tipo == "additional"
    assert ref.source_hash == "tacrc-1758-2025"
    assert ref.filename == "Resolución TACRC 1758/2025.pdf"
    # Espacios y letras sin escapar se escapan; los paréntesis se respetan.
    assert ref.uri == (
        "https://www.hacienda.gob.es/tacrc/resoluciones/a%C3%B1o%202025/"
        "recurso%201745-2025%20(res%201758).pdf"
    )


def test_una_url_ya_escapada_no_se_escapa_dos_veces():
    url = "https://www.hacienda.gob.es/tacrc/documentos/resoluci%c3%b3n%20recurso%201028-2022.pdf"
    assert referencia_documento("1156/2022", url).uri == url


def test_el_host_de_los_pdfs_esta_en_la_allowlist_y_en_el_inventario():
    from config import settings
    from scraper.resilience import breaker_para_host, placsp_breaker

    fuente = next(f for f in REGISTERED_SOURCES if f.source_id == "tacrc")
    assert "www.hacienda.gob.es" in fuente.dominios_documentos
    assert "www.hacienda.gob.es" in settings.DOCUMENT_ALLOWED_HOSTS.split(",")
    # Su propio circuito: cinco fallos de Hacienda no paran PLACSP.
    assert breaker_para_host("www.hacienda.gob.es") is not placsp_breaker


@pytest.fixture()
def db(tmp_db):
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, fuente, "
            " fecha_extraccion) VALUES (%s, %s, %s, 'placsp', CURRENT_TIMESTAMP)",
            ("EXP-2026-42", "Contrato recurrido", "Ministerio"),
        )
    return tmp_db


def _documentos(licitacion_id: str) -> list[dict]:
    from db.repositories.documentos import DocumentosRepository

    return DocumentosRepository().list_by_licitacion(licitacion_id)


def test_run_da_de_alta_el_pdf_de_la_resolucion_vinculada_una_sola_vez(db, monkeypatch):
    monkeypatch.setattr(tacrc, "fetch_index", lambda url=None, session=None: _INDEX_HTML)

    stats = run("https://www.hacienda.gob.es/tacrc/indice")
    assert stats["vinculadas"] == 1
    assert stats["documentos"] == 1

    docs = _documentos("EXP-2026-42")
    assert len(docs) == 1
    assert docs[0]["tipo"] == "additional"
    assert docs[0]["status"] == "pending"
    assert docs[0]["uri"].startswith(
        "https://www.hacienda.gob.es/tacrc/resoluciones/a%C3%B1o%202026/"
    )

    # Segunda pasada: nada nuevo que dar de alta, y ninguna fila de más.
    assert run("https://www.hacienda.gob.es/tacrc/indice")["documentos"] == 0
    assert registrar_documentos() == 0
    assert len(_documentos("EXP-2026-42")) == 1


def test_una_resolucion_sin_vincular_no_crea_documentos(db, monkeypatch):
    from db.database import connect

    monkeypatch.setattr(tacrc, "fetch_index", lambda url=None, session=None: _INDEX_HTML)
    run("https://www.hacienda.gob.es/tacrc/indice")

    with connect() as c:
        total = c.execute("SELECT COUNT(*) FROM documentos").fetchone()[0]
    assert total == 1  # solo la vinculada


def test_un_fallo_al_registrar_documentos_no_tumba_la_pasada(db, monkeypatch):
    monkeypatch.setattr(tacrc, "fetch_index", lambda url=None, session=None: _INDEX_HTML)

    def _rompe(**_kwargs):
        raise RuntimeError("bd caída")

    monkeypatch.setattr(tacrc, "registrar_documentos", _rompe)
    stats = run("https://www.hacienda.gob.es/tacrc/indice")
    assert stats["errores"] == 0
    assert stats["documentos"] == 0
    assert stats["nuevas"] == 2
