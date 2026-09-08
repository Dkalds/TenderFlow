"""C6.3 — adjuntos propios de la oportunidad: límites, firma y opt-in del RAG.

Sin BD y sin bucket: lo que estos tests fijan son las tres reglas que el ítem
pide —qué se puede subir, que un enlace caducado no sirve, y que el asistente no
lee nada que nadie haya autorizado— y ninguna de las tres necesita Postgres.

El almacén sí se ejercita, con `FilesystemObjectStore` sobre un `tmp_path`: es
la misma interfaz que la de producción, que es justo por lo que existe.
"""

from __future__ import annotations

import hashlib
import pathlib
import re

import pytest

from services import pursuit_attachments as adj
from shared.object_store import pursuit_attachment_key

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Qué se puede subir
# ---------------------------------------------------------------------------


def test_rechaza_lo_que_supera_el_tope() -> None:
    grande = b"x" * (adj.MAX_BYTES + 1)
    with pytest.raises(adj.AttachmentError) as exc:
        adj._validar(grande, "memoria.pdf", "application/pdf")
    # El mensaje nombra "bytes" porque el router lo usa para elegir 413 y no 415.
    assert "bytes" in str(exc.value)


def test_rechaza_un_tipo_fuera_de_la_allowlist() -> None:
    with pytest.raises(adj.AttachmentError) as exc:
        adj._validar(b"PK\x03\x04", "expediente.zip", "application/zip")
    assert "bytes" not in str(exc.value), "un tipo inválido no puede acabar en un 413"


def test_rechaza_el_fichero_vacio() -> None:
    with pytest.raises(adj.AttachmentError):
        adj._validar(b"", "vacio.pdf", "application/pdf")


def test_acepta_pdf_y_limpia_el_nombre() -> None:
    nombre, tipo = adj._validar(
        b"%PDF-1.4", "  ../../etc/memoria  técnica.pdf ", "application/pdf; charset=binary"
    )
    # Sin rutas: el nombre viaja a un `Content-Disposition`.
    assert "/" not in nombre and ".." not in nombre.split()[0]
    assert nombre == "memoria técnica.pdf"
    # El `charset` no forma parte del tipo con el que se compara la allowlist.
    assert tipo == "application/pdf"


def test_el_tipo_no_distingue_mayusculas() -> None:
    _nombre, tipo = adj._validar(b"%PDF", "a.pdf", "APPLICATION/PDF")
    assert tipo == "application/pdf"


# ---------------------------------------------------------------------------
# El enlace firmado
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clave_de_firma(monkeypatch: pytest.MonkeyPatch) -> None:
    """Una clave conocida: la firma real, no un doble."""
    import shared.signing as signing

    monkeypatch.setenv("SIGNING_KEY", "clave-de-test-para-adjuntos")
    signing.reload_keys()
    yield
    signing.reload_keys()


def test_un_enlace_recien_emitido_vale() -> None:
    token, expira = adj.firmar_descarga(42)
    assert adj.verificar_descarga(42, expira, token) is True


def test_un_enlace_caducado_no_vale() -> None:
    """El criterio de aceptación: caducado da 403, y eso empieza aquí."""
    token, expira = adj.firmar_descarga(42, ahora=0)
    assert adj.verificar_descarga(42, expira, token, ahora=expira + 1) is False


def test_alargar_la_caducidad_invalida_la_firma() -> None:
    """`exp` va DENTRO de la firma: editarlo en la URL no alarga el permiso."""
    token, expira = adj.firmar_descarga(42)
    assert adj.verificar_descarga(42, expira + 86_400, token) is False


def test_la_firma_no_sirve_para_otro_adjunto() -> None:
    token, expira = adj.firmar_descarga(42)
    assert adj.verificar_descarga(43, expira, token) is False


def test_sin_firma_no_hay_descarga() -> None:
    _token, expira = adj.firmar_descarga(42)
    assert adj.verificar_descarga(42, expira, "") is False


# ---------------------------------------------------------------------------
# La clave en el bucket
# ---------------------------------------------------------------------------


def test_la_clave_lleva_la_organizacion_delante() -> None:
    """Permite purgar por prefijo al borrar una organización, sin ir a la BD."""
    huella = hashlib.sha256(b"contenido").hexdigest()
    clave = pursuit_attachment_key(7, huella)
    assert clave is not None
    assert clave.endswith(f"/7/{huella}")


def test_la_clave_rechaza_lo_que_no_es_una_huella() -> None:
    assert pursuit_attachment_key(7, "../../documentos/otro") is None
    assert pursuit_attachment_key(0, "a" * 64) is None


def test_dos_organizaciones_no_comparten_ruta() -> None:
    huella = hashlib.sha256(b"el mismo fichero").hexdigest()
    assert pursuit_attachment_key(1, huella) != pursuit_attachment_key(2, huella)


# ---------------------------------------------------------------------------
# El almacén, con la implementación de ficheros
# ---------------------------------------------------------------------------


def test_el_binario_va_y_vuelve_igual(tmp_path: pathlib.Path) -> None:
    from shared.object_store import FilesystemObjectStore

    almacen = FilesystemObjectStore(tmp_path)
    huella = hashlib.sha256(b"%PDF-1.4 memoria").hexdigest()
    clave = pursuit_attachment_key(3, huella)
    assert clave is not None

    almacen.put(clave, b"%PDF-1.4 memoria", content_type="application/pdf")
    assert almacen.get(clave) == b"%PDF-1.4 memoria"
    assert almacen.delete(clave) is True
    assert almacen.get(clave) is None


# ---------------------------------------------------------------------------
# El asistente no lee adjuntos propios salvo opt-in
# ---------------------------------------------------------------------------


def test_el_rag_no_toca_la_tabla_de_adjuntos() -> None:
    """Guardarraíl: hoy el RAG no los indexa, y que siga siendo así por defecto.

    El opt-in es por adjunto (`indexable`, falso de fábrica). Si algún día se
    conectan al contexto, el único camino admitido es
    `PursuitAttachmentRepository.indexables`, que ya filtra: leer la tabla a
    pelo desde `services/rag/**` es lo que este test impide, porque un `if`
    olvidado ahí mete una propuesta económica en una respuesta citable.
    """
    raiz = pathlib.Path(__file__).resolve().parent.parent / "services" / "rag"
    sospechosos: list[str] = []
    for fichero in raiz.rglob("*.py"):
        texto = fichero.read_text(encoding="utf-8")
        if "pursuit_attachments" not in texto:
            continue
        # Si aparece, tiene que ser a través del método que filtra por opt-in.
        if not re.search(r"\.indexables\(", texto):
            sospechosos.append(str(fichero.relative_to(raiz)))
    assert sospechosos == [], (
        "estos módulos del RAG nombran `pursuit_attachments` sin pasar por "
        f"`indexables()`: {sospechosos}"
    )


def test_el_opt_in_nace_apagado() -> None:
    """El DTO por defecto no indexa: es la mitad del contrato que ve el cliente."""
    from shared.dto import PursuitAttachmentOut

    adjunto = PursuitAttachmentOut(
        id=1,
        pursuit_id=1,
        organization_id=1,
        filename="propuesta.pdf",
        content_type="application/pdf",
        bytes=10,
        sha256="a" * 64,
    )
    assert adjunto.indexable is False


# ---------------------------------------------------------------------------
# El tope de cuerpo del middleware conoce esta ruta
# ---------------------------------------------------------------------------


def test_la_subida_no_choca_con_el_tope_de_1mb() -> None:
    """Sin esto, el límite global de body haría imposible subir nada de 2 MB."""
    from api.middleware import _MaxBodyMiddleware

    assert _MaxBodyMiddleware._limite_para("/api/v1/pursuits/7/attachments") == adj.MAX_BYTES
    # Y no se derrama a las rutas vecinas.
    assert _MaxBodyMiddleware._limite_para("/api/v1/pursuits/7/attachments/3/enlace") == (
        _MaxBodyMiddleware._MAX_BYTES
    )
    assert _MaxBodyMiddleware._limite_para("/api/v1/pursuits") == _MaxBodyMiddleware._MAX_BYTES
