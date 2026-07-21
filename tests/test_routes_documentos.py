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
            "VALUES (?,?,?,?,?)",
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
    assert "texto" not in doc


def test_documentos_licitacion_sin_auth(client):
    """Sin cabecera de autenticación → 401 o 403."""
    _seed_licitacion("DOC003")
    r = client.get("/api/v1/licitaciones/DOC003/documentos")
    assert r.status_code in (401, 403)
