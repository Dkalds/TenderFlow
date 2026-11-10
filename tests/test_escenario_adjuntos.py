"""Escenarios de los adjuntos propios de una oportunidad: lo que el equipo escribe.

Cada test es un recorrido completo por la API con sesión real. Ver
``tests/escenarios.py`` y ``docs/casos-de-uso.md``.

El almacén es el de sistema de ficheros (ADR-029 §B): los tests no tocan la red,
y `DOCUMENT_BLOB_DIR` apuntando a un directorio temporal es exactamente como se
configura un entorno sin bucket S3.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch
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


# ── Memoria de la organización (ADR-040) ────────────────────────────────────

_PROPUESTA = (
    "Metodología de migración. En la Diputación migramos el ERP a SAP S/4HANA "
    "en nueve meses, con un equipo de doce personas y sin parada de servicio."
).encode()
_NOTA_AJENA = (
    "Metodología de migración de la otra empresa: pasamos el ERP a Oracle Fusion "
    "en dos años y con parada de servicio."
).encode()
_PREGUNTA = "¿Qué metodología de migración del ERP hemos seguido?"


def _respuesta_de_prueba(*_args: Any, **_kwargs: Any) -> Any:
    yield "Respuesta de prueba."


def _preguntar(sesion: Sesion, oid: int) -> list[dict[str, Any]]:
    """Las citas de documentos propios que acompañan a una pregunta al Investigador."""
    with patch("llm.client.stream_llm_response", _respuesta_de_prueba):
        respuesta = sesion.post(
            "/ask", params={"organization_id": oid}, json={"question": _PREGUNTA}
        )
    assert respuesta.status_code == 200, respuesta.text
    citas: list[dict[str, Any]] = []
    for linea in respuesta.text.splitlines():
        if linea.startswith("data: {"):
            citas.extend(json.loads(linea[6:]).get("fuentes_organizacion", []))
    return citas


def _indexar_lo_encolado() -> None:
    """Hace de worker: en los tests nadie consume la cola por su cuenta."""
    from services.jobs import procesar_uno

    while procesar_uno("escenario-memoria") is not None:
        pass


def _fragmentos_guardados(attachment_id: int) -> int:
    """Filas de texto indexado de un adjunto, leídas sin pasar por la API.

    La API no distingue «no se devuelve» de «no existe»; para afirmar que
    desmarcar **borra**, hay que mirar la tabla.
    """
    from db.database import connect_read

    with connect_read() as c:
        fila = c.execute(
            "SELECT COUNT(*) FROM pursuit_attachment_chunks WHERE attachment_id = %s",
            (attachment_id,),
        ).fetchone()
    return int(fila[0])


def _oportunidad(sesion: Sesion, licitacion_id: str, oid: int) -> int:
    creada = sesion.post("/pursuits", json={"licitacion_id": licitacion_id, "organization_id": oid})
    assert creada.status_code == 201, creada.text
    return int(creada.json()["id"])


def _adjuntar_texto(sesion: Sesion, pursuit_id: int, oid: int, nombre: str, datos: bytes) -> int:
    subida = _subir(sesion, pursuit_id, oid, nombre=nombre, tipo="text/plain", datos=datos)
    assert subida.status_code == 201, subida.text
    assert subida.json()["indexable"] is False
    return int(subida.json()["id"])


def _marcar_indexable(sesion: Sesion, attachment_id: int, oid: int, valor: bool) -> Any:
    return sesion.put(
        f"/pursuits/adjuntos/{attachment_id}/indexable",
        params={"organization_id": oid},
        json={"indexable": valor},
    )


def test_cu36_documentos_propios_indexados_citados_y_aislados(client, api_db, almacen, monkeypatch):
    """CU-36 — una organización indexa sus documentos, el Investigador los cita y otra no los alcanza.

    Es también la parte de CU-13 que toca al texto indexado: ni preguntando lo
    mismo ni pidiendo el adjunto por su identificador.
    """
    import services.embeddings as embeddings
    from api.app import app

    # Como el proceso de la API en producción: sin motor para embeber documentos,
    # así que el recorrido usa la búsqueda por palabras, que es determinista.
    monkeypatch.setattr(embeddings, "embeddings_masivos_disponibles", lambda: False)
    monkeypatch.setattr(embeddings, "embeddings_available", lambda: False)
    monkeypatch.setenv("MEMORIA_ORG_MAX_DOCUMENTOS", "1")

    sembrar_licitacion("EXP-MEM-A", "Migración del ERP provincial")
    sembrar_licitacion("EXP-MEM-B", "Renovación del ERP municipal")
    duena = abrir_sesion("duena.memoria@example.com", client, nombre="Marta Díaz")
    lectora = abrir_sesion("lectora.memoria@example.com", TestClient(app))
    ajena = abrir_sesion("ajena.memoria@example.com", TestClient(app))
    equipo = duena.post("/organizations", json={"name": "Integradora Memoria"})
    assert equipo.status_code == 201, equipo.text
    oid = int(equipo.json()["id"])
    oid_ajena = ajena.organization_id
    invitada = duena.post(
        f"/organizations/{oid}/members", json={"email": lectora.email, "role": "viewer"}
    )
    assert invitada.status_code == 201, invitada.text

    pid = _oportunidad(duena, "EXP-MEM-A", oid)
    propio = _adjuntar_texto(duena, pid, oid, "Propuesta técnica.txt", _PROPUESTA)
    anexo = _adjuntar_texto(duena, pid, oid, "Anexo.txt", b"Anexo de precios de la propuesta.")
    de_la_otra = _adjuntar_texto(
        ajena, _oportunidad(ajena, "EXP-MEM-B", oid_ajena), oid_ajena, "Nota.txt", _NOTA_AJENA
    )

    # Antes de activar nada, la pantalla sabe cuántos documentos caben y de qué tipos.
    politica = duena.get("/pursuits/adjuntos/politica").json()
    assert politica["indexado_max_documentos"] == 1
    assert "text/plain" in politica["indexado_tipos"]
    assert "image/png" not in politica["indexado_tipos"]

    # Sin permiso no se cita nada, aunque el fichero esté subido.
    assert _preguntar(duena, oid) == []

    # Quien solo lee no concede el permiso; quien escribe sí, y queda pendiente.
    assert _marcar_indexable(lectora, propio, oid, True).status_code == 403
    activado = _marcar_indexable(duena, propio, oid, True)
    assert activado.status_code == 200, activado.text
    assert activado.json()["index_status"] == "pending"
    # El tope es por organización: el segundo documento no entra.
    sin_hueco = _marcar_indexable(duena, anexo, oid, True)
    assert sin_hueco.status_code == 422, sin_hueco.text
    assert "tope" in sin_hueco.json()["detail"]

    # La otra organización indexa lo suyo, que habla de lo mismo.
    assert _marcar_indexable(ajena, de_la_otra, oid_ajena, True).status_code == 200
    _indexar_lo_encolado()

    listado = duena.get(f"/pursuits/{pid}/adjuntos", params={"organization_id": oid}).json()
    assert {a["id"]: a["index_status"] for a in listado} == {propio: "indexed", anexo: None}
    assert _fragmentos_guardados(propio) > 0

    # El Investigador cita el documento propio: extracto literal, fichero,
    # página y oportunidad de origen. La lectora de la organización también lo ve.
    (cita,) = _preguntar(duena, oid)
    assert cita["attachment_id"] == propio
    assert cita["filename"] == "Propuesta técnica.txt"
    assert cita["page_number"] == 1
    assert cita["pursuit_id"] == pid
    assert cita["licitacion_id"] == "EXP-MEM-A"
    assert cita["licitacion_titulo"] == "Migración del ERP provincial"
    assert cita["cita"].rstrip("…") in _PROPUESTA.decode()
    assert [c["attachment_id"] for c in _preguntar(lectora, oid)] == [propio]

    # La otra organización, con la misma pregunta, solo recibe lo suyo...
    assert [c["attachment_id"] for c in _preguntar(ajena, oid_ajena)] == [de_la_otra]
    # ...no pregunta como si fuera de la primera, ni alcanza el adjunto por su id.
    colada = ajena.post("/ask", params={"organization_id": oid}, json={"question": _PREGUNTA})
    assert colada.status_code == 403, colada.text
    assert _marcar_indexable(ajena, propio, oid_ajena, False).status_code == 404
    assert ajena.get(f"/pursuits/adjuntos/{propio}/enlace").status_code == 404
    assert _fragmentos_guardados(propio) > 0

    # Desmarcar borra el texto indexado, no solo lo esconde.
    desactivado = _marcar_indexable(duena, propio, oid, False)
    assert desactivado.status_code == 200, desactivado.text
    assert desactivado.json()["index_status"] is None
    assert _fragmentos_guardados(propio) == 0
    assert _preguntar(duena, oid) == []
    assert [c["attachment_id"] for c in _preguntar(ajena, oid_ajena)] == [de_la_otra]

    # Retirar un adjunto indexado también lo borra.
    assert _marcar_indexable(duena, propio, oid, True).status_code == 200
    _indexar_lo_encolado()
    assert _fragmentos_guardados(propio) > 0
    retirado = duena.delete(f"/pursuits/adjuntos/{propio}", params={"organization_id": oid})
    assert retirado.status_code == 204, retirado.text
    assert _fragmentos_guardados(propio) == 0
    assert _preguntar(duena, oid) == []

    # Cada cambio de permiso está en el rastro de la organización (CU-32), con
    # ids y sin el nombre del fichero.
    rastro = duena.get(f"/organizations/{oid}/audit").json()["items"]
    cambios = [e for e in rastro if e["event_type"] == "pursuit_attachment.indexing_changed"]
    assert len(cambios) == 4
    assert all(json.loads(e["detail"])["attachment_id"] == propio for e in cambios)
    assert json.loads(cambios[0]["detail"])["motivo"] == "adjunto_retirado"
    assert "Propuesta" not in "".join(e["detail"] for e in cambios)
