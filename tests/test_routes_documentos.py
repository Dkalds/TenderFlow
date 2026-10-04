"""Tests para GET /api/v1/licitaciones/{id}/documentos."""

from __future__ import annotations

from db.database import DocumentoReferencia
from db.repositories.documentos import DocumentosRepository


def _seed_licitacion(id_externo: str) -> None:
    import db.database as db_mod

    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, estado, fecha_publicacion, fecha_extraccion) "
            "VALUES (%s,%s,%s,%s,%s)",
            (id_externo, "Test licitacion", "PUB", "2026-01-01", "2026-01-01"),
        )


def test_documentos_licitacion_sin_documentos(client, auth):
    """Licitación existente sin documentos parseados → 200 con items vacío."""
    _seed_licitacion("DOC001")
    r = client.get("/api/v1/licitaciones/DOC001/documentos", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert data["id_externo"] == "DOC001"
    assert data["items"] == []


def test_documentos_licitacion_no_existe(client, auth):
    """Licitación inexistente → 200 con items vacío (no distingue de "sin documentos")."""
    r = client.get("/api/v1/licitaciones/NOPE-DOC/documentos", headers=auth)
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_documentos_licitacion_con_documentos(client, auth):
    """Licitación con pliegos parseados → 200 con metadatos, sin el texto."""
    _seed_licitacion("DOC002")
    DocumentosRepository().upsert_meta(
        "DOC002",
        [DocumentoReferencia(tipo="legal", uri="https://x/pcap.pdf", filename="PCAP.pdf")],
    )
    r = client.get("/api/v1/licitaciones/DOC002/documentos", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 1
    doc = data["items"][0]
    assert doc["uri"] == "https://x/pcap.pdf"
    assert doc["filename"] == "PCAP.pdf"
    assert doc["tipo"] == "legal"
    assert doc["status"] == "pending"
    assert doc["sin_publicar"] is False
    assert "texto" not in doc


def test_documentos_de_un_pliego_sin_publicar_van_marcados(client, auth):
    """PLACSP anuncia el pliego con el anuncio de licitación y no lo sirve hasta
    publicar el pliego: la ficha tiene que saberlo para no ofrecer un enlace que
    contesta 500."""
    import db.database as db_mod

    _seed_licitacion("DOC005")
    with db_mod.connect() as c:
        c.execute("UPDATE licitaciones SET tipos_anuncio = 'DOC_CN' WHERE id_externo = 'DOC005'")
    DocumentosRepository().upsert_meta(
        "DOC005",
        [
            DocumentoReferencia(
                tipo="legal",
                uri=(
                    "https://contrataciondelestado.es/FileSystem/servlet/"
                    "GetDocumentByIdServlet?cifrado=C&DocumentIdParam=T"
                ),
                filename="PCAP.pdf",
            )
        ],
    )

    r = client.get("/api/v1/licitaciones/DOC005/documentos", headers=auth)

    assert r.status_code == 200
    assert [d["sin_publicar"] for d in r.json()["items"]] == [True]


def test_documentos_llegan_en_orden_documental(client, auth):
    """El orden lo fija el backend, no el cliente: el bloque de la UI pinta la
    lista tal cual llega, así que el PCAP tiene que venir antes que el PPT."""
    _seed_licitacion("DOC004")
    DocumentosRepository().upsert_meta(
        "DOC004",
        [
            DocumentoReferencia(tipo="technical", uri="https://x/ppt.pdf"),
            DocumentoReferencia(tipo="legal", uri="https://x/pcap.pdf"),
        ],
    )
    r = client.get("/api/v1/licitaciones/DOC004/documentos", headers=auth)
    assert r.status_code == 200
    assert [d["tipo"] for d in r.json()["items"]] == ["legal", "technical"]


def test_documentos_licitacion_sin_auth(client):
    """Sin cabecera de autenticación → 401 o 403."""
    _seed_licitacion("DOC003")
    r = client.get("/api/v1/licitaciones/DOC003/documentos")
    assert r.status_code in (401, 403)
