"""Escenarios de los adjuntos propios de una oportunidad: lo que el equipo escribe.

Cada test es un recorrido completo por la API con sesión real. Ver
``tests/escenarios.py`` y ``docs/casos-de-uso.md``.

El almacén es el de sistema de ficheros (ADR-029 §B): los tests no tocan la red,
y `DOCUMENT_BLOB_DIR` apuntando a un directorio temporal es exactamente como se
configura un entorno sin bucket S3.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from tests.escenarios import Sesion, abrir_sesion, sembrar_licitacion

_PDF = b"%PDF-1.4\n% propuesta tecnica de prueba\n%%EOF\n"


def _subir(
    sesion: Sesion, pursuit_id: int, oid: int, *, nombre: str, tipo: str, datos: bytes
) -> Any:
    """La subida tal como la hace la consola: cuerpo crudo y nombre en cabecera.

    El nombre va codificado como URI (`encodeURIComponent` en el navegador): una
    cabecera solo lleva Latin-1, y así el recorrido cubre también la tilde.
    """
    return sesion.client.post(
        f"/api/v1/pursuits/{pursuit_id}/adjuntos",
        params={"organization_id": oid},
        content=datos,
        headers={**sesion.cab, "Content-Type": tipo, "X-Filename": quote(nombre, safe="")},
    )


@pytest.fixture
def almacen(tmp_path, monkeypatch):
    """Un entorno con almacén de objetos configurado."""
    from shared.object_store import reset_object_store_cache

    monkeypatch.setenv("DOCUMENT_BLOB_DIR", str(tmp_path / "almacen"))
    reset_object_store_cache()
    yield tmp_path / "almacen"
    reset_object_store_cache()


def test_cu27_adjuntos_subir_descargar_y_retirar(client, api_db, almacen):
    """CU-27 — la propuesta del equipo vive en la oportunidad, y solo quien escribe la toca."""
    from api.app import app

    sembrar_licitacion("EXP-ADJ-ESC", "Implantación de SAP S/4HANA")
    duena = abrir_sesion("duena.adjuntos@example.com", client, nombre="Marta Díaz")
    lectora = abrir_sesion(
        "lectora.adjuntos@example.com", TestClient(app, raise_server_exceptions=True)
    )
    equipo = duena.post("/organizations", json={"name": "Integradora Adjuntos"})
    assert equipo.status_code == 201, equipo.text
    oid = int(equipo.json()["id"])
    invitada = duena.post(
        f"/organizations/{oid}/members", json={"email": lectora.email, "role": "viewer"}
    )
    assert invitada.status_code == 201, invitada.text
    creada = duena.post("/pursuits", json={"licitacion_id": "EXP-ADJ-ESC", "organization_id": oid})
    assert creada.status_code == 201, creada.text
    pid = int(creada.json()["id"])

    # Antes de elegir un fichero, la consola sabe si puede subirse y qué cabe.
    politica = duena.get("/pursuits/adjuntos/politica").json()
    assert politica["almacen_disponible"] is True
    assert politica["max_bytes"] == 25 * 1024 * 1024
    pdf = next(t for t in politica["tipos"] if t["content_type"] == "application/pdf")
    assert pdf["extensiones"] == [".pdf"]

    # Sube la propuesta; el nombre conserva la tilde y la fila dice quién la subió.
    subida = _subir(
        duena, pid, oid, nombre="Propuesta técnica.pdf", tipo="application/pdf", datos=_PDF
    )
    assert subida.status_code == 201, subida.text
    adjunto = subida.json()
    assert adjunto["filename"] == "Propuesta técnica.pdf"
    assert adjunto["size_bytes"] == len(_PDF)
    assert adjunto["uploaded_by_name"] == "Marta Díaz"
    assert "blob_key" not in adjunto

    # El mismo fichero otra vez no se duplica; un tipo fuera de la lista no entra.
    repetida = _subir(duena, pid, oid, nombre="copia.pdf", tipo="application/pdf", datos=_PDF)
    assert repetida.status_code == 409, repetida.text
    ejecutable = _subir(
        duena, pid, oid, nombre="instalador.exe", tipo="application/x-msdownload", datos=b"MZ"
    )
    assert ejecutable.status_code == 415, ejecutable.text

    # Quien solo lee ve la lista y descarga, pero no sube ni retira.
    vista = lectora.get(f"/pursuits/{pid}/adjuntos", params={"organization_id": oid})
    assert vista.status_code == 200, vista.text
    assert [a["filename"] for a in vista.json()] == ["Propuesta técnica.pdf"]
    intento = _subir(
        lectora, pid, oid, nombre="otra.txt", tipo="text/plain", datos=b"nota de la lectora"
    )
    assert intento.status_code == 403, intento.text
    borrado_ajeno = lectora.delete(
        f"/pursuits/adjuntos/{adjunto['id']}", params={"organization_id": oid}
    )
    assert borrado_ajeno.status_code == 403, borrado_ajeno.text

    # La descarga va por un enlace firmado que caduca, con la sesión delante.
    enlace = lectora.get(
        f"/pursuits/adjuntos/{adjunto['id']}/enlace", params={"organization_id": oid}
    )
    assert enlace.status_code == 200, enlace.text
    # La organización se añade a la query firmada, no la sustituye: el enlace ya
    # lleva `exp` y `t`, y es lo que hace la consola.
    descarga = lectora.client.get(f"{enlace.json()['path']}&organization_id={oid}")
    assert descarga.status_code == 200, descarga.text
    assert descarga.content == _PDF
    assert "attachment" in descarga.headers["content-disposition"]

    # Otra organización no lo alcanza ni por su id.
    ajena = abrir_sesion("ajena.adjuntos@example.com", TestClient(app))
    fuera = ajena.get(f"/pursuits/adjuntos/{adjunto['id']}/enlace")
    assert fuera.status_code == 404, fuera.text

    # La dueña lo retira y deja de aparecer en la oportunidad.
    retirado = duena.delete(f"/pursuits/adjuntos/{adjunto['id']}", params={"organization_id": oid})
    assert retirado.status_code == 204, retirado.text
    assert duena.get(f"/pursuits/{pid}/adjuntos", params={"organization_id": oid}).json() == []


def test_cu27_sin_almacen_la_politica_lo_dice_y_la_subida_no_promete(client, api_db, monkeypatch):
    """CU-27 — un entorno sin almacén lo declara antes de subir, y no acepta ficheros."""
    from shared.object_store import reset_object_store_cache

    monkeypatch.delenv("DOCUMENT_BLOB_DIR", raising=False)
    monkeypatch.delenv("DOCUMENT_BLOB_BUCKET", raising=False)
    reset_object_store_cache()

    sembrar_licitacion("EXP-ADJ-SIN", "Soporte de nóminas")
    ana = abrir_sesion("ana.sinalmacen@example.com", client)
    creada = ana.post(
        "/pursuits", json={"licitacion_id": "EXP-ADJ-SIN", "organization_id": ana.organization_id}
    )
    assert creada.status_code == 201, creada.text
    pid = int(creada.json()["id"])

    politica = ana.get("/pursuits/adjuntos/politica").json()
    assert politica["almacen_disponible"] is False

    subida = _subir(
        ana, pid, ana.organization_id, nombre="propuesta.pdf", tipo="application/pdf", datos=_PDF
    )
    assert subida.status_code == 503, subida.text
    assert ana.get(f"/pursuits/{pid}/adjuntos").json() == []
