"""Adjuntos propios de una oportunidad, por sus rutas (C6.3).

C6.3 estuvo bloqueado hasta que la fusión trajo el almacén de objetos, y entró
con siete respuestas distintas declaradas en el decorador —403, 404, 409, 413,
415, 422 y 503— sin un test que comprobara ninguna. Un `except` en el orden
equivocado las intercambia sin que nada falle: `AttachmentTooLarge` hereda de
`AttachmentError`, así que basta con capturar la general antes que la concreta
para que un fichero de 30 MB devuelva 422 en vez de 413.

Se fijan además las dos decisiones que el ítem argumenta y que solo viven en la
ruta: que el tamaño se compruebe **antes** de leer el cuerpo —para no traer 500
MB a memoria y rechazarlos después— y que un enlace caducado sea **403 y no
410**, porque el fichero sigue ahí y lo que caducó es el permiso.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

_ADJUNTO = {
    "id": 1,
    "pursuit_id": 3,
    "organization_id": 7,
    "filename": "pliego.pdf",
    "content_type": "application/pdf",
    "size_bytes": 1024,
    "sha256": "a" * 64,
    "uploaded_by_user_id": 5,
    "uploaded_by_name": "Ana",
    "indexable": False,
    "created_at": "2026-09-08T10:00:00Z",
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    from api.app import app
    from api.routes.dual_auth import require_any_auth

    app.dependency_overrides[require_any_auth] = lambda: {"user_id": 5, "scopes": ["*"]}
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.clear()


def _falla_con(monkeypatch: pytest.MonkeyPatch, nombre: str, exc: Exception) -> None:
    import services.pursuit_attachments as svc

    def _boom(*a: Any, **k: Any) -> Any:
        raise exc

    monkeypatch.setattr(svc, nombre, _boom)


class TestListado:
    RUTA = "/api/v1/pursuits/3/adjuntos"

    def test_el_listado_nunca_lleva_la_clave_del_bucket(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Publicarla invitaría a construir URLs a mano contra el almacén, que
        es justo lo que evita el enlace firmado."""
        import services.pursuit_attachments as svc

        monkeypatch.setattr(
            svc, "listar", lambda *a, **k: [{**_ADJUNTO, "blob_key": "org7/secreta"}]
        )

        cuerpo = client.get(self.RUTA).json()
        assert cuerpo[0]["filename"] == "pliego.pdf"
        assert "blob_key" not in str(cuerpo)

    def test_una_oportunidad_ajena_es_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.pursuits import PursuitNotFoundError

        _falla_con(monkeypatch, "listar", PursuitNotFoundError("no existe"))

        assert client.get(self.RUTA).status_code == 404


class TestSubida:
    RUTA = "/api/v1/pursuits/3/adjuntos"
    CABECERAS: ClassVar[dict[str, str]] = {
        "X-Filename": "pliego.pdf",
        "Content-Type": "application/pdf",
    }

    def test_el_tope_se_comprueba_antes_de_leer_el_cuerpo(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Con `Content-Length` por encima del tope se rechaza sin llamar al
        servicio: traer 500 MB a memoria para descartarlos después es el fallo
        que la comprobación previa evita."""
        import services.pursuit_attachments as svc

        llamadas: list[int] = []
        monkeypatch.setattr(svc, "subir", lambda *a, **k: llamadas.append(1) or _ADJUNTO)

        respuesta = client.post(
            self.RUTA,
            content=b"x",
            headers={**self.CABECERAS, "Content-Length": str(svc.MAX_BYTES + 1)},
        )
        assert respuesta.status_code == 413
        assert llamadas == []

    def test_un_fichero_grande_de_verdad_tambien_es_413(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """La cabecera la escribe el cliente: los bytes reales se miden igual."""
        from services.pursuit_attachments import AttachmentTooLarge

        _falla_con(monkeypatch, "subir", AttachmentTooLarge("supera el tope"))

        respuesta = client.post(self.RUTA, content=b"x" * 10, headers=self.CABECERAS)
        assert respuesta.status_code == 413

    def test_un_tipo_no_admitido_es_415_y_no_422(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Es lista blanca: una negra es una carrera que se pierde."""
        from services.pursuit_attachments import AttachmentTypeRejected

        _falla_con(monkeypatch, "subir", AttachmentTypeRejected("tipo no admitido"))

        respuesta = client.post(self.RUTA, content=b"x", headers=self.CABECERAS)
        assert respuesta.status_code == 415

    def test_sin_almacen_configurado_es_503_y_no_500(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Es indisponibilidad de una dependencia, no un fallo del cliente."""
        from services.pursuit_attachments import AttachmentStoreUnavailable

        _falla_con(monkeypatch, "subir", AttachmentStoreUnavailable("sin bucket"))

        respuesta = client.post(self.RUTA, content=b"x", headers=self.CABECERAS)
        assert respuesta.status_code == 503

    def test_el_mismo_fichero_dos_veces_es_409(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from db.repositories.pursuit_attachments import PursuitAttachmentExists

        _falla_con(monkeypatch, "subir", PursuitAttachmentExists("ya está"))

        respuesta = client.post(self.RUTA, content=b"x", headers=self.CABECERAS)
        assert respuesta.status_code == 409

    def test_el_resto_de_errores_del_adjunto_son_422(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """La general va **después** de las concretas; si no, un fichero grande
        saldría por aquí."""
        from services.pursuit_attachments import AttachmentError

        _falla_con(monkeypatch, "subir", AttachmentError("extensión y tipo no concuerdan"))

        respuesta = client.post(self.RUTA, content=b"x", headers=self.CABECERAS)
        assert respuesta.status_code == 422

    def test_un_viewer_no_sube(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        from services.organizations import OrganizationPermissionError

        _falla_con(monkeypatch, "subir", OrganizationPermissionError("solo lectura"))

        respuesta = client.post(self.RUTA, content=b"x", headers=self.CABECERAS)
        assert respuesta.status_code == 403

    def test_sin_nombre_de_fichero_el_contrato_lo_para(self, client: TestClient) -> None:
        assert client.post(self.RUTA, content=b"x").status_code == 422

    def test_una_subida_buena_devuelve_201_con_el_adjunto(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.pursuit_attachments as svc

        monkeypatch.setattr(svc, "subir", lambda *a, **k: _ADJUNTO)

        respuesta = client.post(self.RUTA, content=b"x", headers=self.CABECERAS)
        assert respuesta.status_code == 201
        assert respuesta.json()["sha256"] == "a" * 64

    def test_si_el_servicio_no_devuelve_fila_la_oportunidad_no_era_suya(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.pursuit_attachments as svc

        monkeypatch.setattr(svc, "subir", lambda *a, **k: None)

        respuesta = client.post(self.RUTA, content=b"x", headers=self.CABECERAS)
        assert respuesta.status_code == 404


class TestEnlaceYDescarga:
    ENLACE = "/api/v1/pursuits/adjuntos/1/enlace"
    DESCARGA = "/api/v1/pursuits/adjuntos/1/descargar"

    def test_el_enlace_se_emite_con_la_sesion_delante(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """La autorización se comprueba aquí; por eso el enlace dura diez
        minutos y no un día."""
        import services.pursuit_attachments as svc

        class _Enlace:
            path = "/api/v1/pursuits/adjuntos/1/descargar?exp=1&t=abc"
            expira_en = 1_800_000_000

        monkeypatch.setattr(svc, "obtener", lambda *a, **k: _ADJUNTO)
        monkeypatch.setattr(svc, "firmar_descarga", lambda aid: _Enlace())

        cuerpo = client.get(self.ENLACE).json()
        assert cuerpo["expira_en"] == 1_800_000_000
        assert "t=abc" in cuerpo["path"]

    def test_un_adjunto_de_otra_organizacion_no_emite_enlace(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.pursuit_attachments as svc

        monkeypatch.setattr(svc, "obtener", lambda *a, **k: None)

        assert client.get(self.ENLACE).status_code == 404

    def test_un_enlace_caducado_es_403_y_no_410(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """410 diría que el recurso existió y ya no está. El fichero sigue ahí:
        lo que caducó es el permiso."""
        import services.pursuit_attachments as svc

        monkeypatch.setattr(svc, "verificar_descarga", lambda aid, *, exp, token: False)

        respuesta = client.get(self.DESCARGA, params={"exp": 1, "t": "vieja"})
        assert respuesta.status_code == 403

    def test_la_firma_no_sustituye_a_la_sesion(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un enlace reenviado por correo no abre nada a quien ya no pertenece a
        la organización."""
        import services.pursuit_attachments as svc
        from services.organizations import OrganizationAccessError

        monkeypatch.setattr(svc, "verificar_descarga", lambda aid, *, exp, token: True)
        _falla_con(monkeypatch, "descargar", OrganizationAccessError("no sos miembro"))

        respuesta = client.get(self.DESCARGA, params={"exp": 1, "t": "valida"})
        assert respuesta.status_code == 403

    def test_la_descarga_buena_sirve_el_binario_con_su_nombre(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.pursuit_attachments as svc

        monkeypatch.setattr(svc, "verificar_descarga", lambda aid, *, exp, token: True)
        monkeypatch.setattr(svc, "descargar", lambda *a, **k: (_ADJUNTO, b"%PDF-1.7"))

        respuesta = client.get(self.DESCARGA, params={"exp": 1, "t": "valida"})
        assert respuesta.status_code == 200
        assert respuesta.content == b"%PDF-1.7"
        assert 'filename="pliego.pdf"' in respuesta.headers["content-disposition"]


class TestIndexableYBorrado:
    INDEXABLE = "/api/v1/pursuits/adjuntos/1/indexable"
    BORRAR = "/api/v1/pursuits/adjuntos/1"

    def test_el_opt_in_del_rag_es_por_adjunto(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Una propuesta puede llevar el CV de alguien y el pliego técnico en el
        mismo expediente: un permiso global obligaría a decidir por el conjunto."""
        import services.pursuit_attachments as svc

        pedidos: list[dict[str, Any]] = []

        def _marcar(uid: int, aid: int, *, indexable: bool, organization_id: Any = None) -> Any:
            pedidos.append({"id": aid, "indexable": indexable})
            return {**_ADJUNTO, "indexable": indexable}

        monkeypatch.setattr(svc, "marcar_indexable", _marcar)

        cuerpo = client.put(self.INDEXABLE, json={"indexable": True}).json()
        assert cuerpo["indexable"] is True
        assert pedidos == [{"id": 1, "indexable": True}]

    def test_marcar_un_adjunto_ajeno_es_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.pursuit_attachments as svc

        monkeypatch.setattr(svc, "marcar_indexable", lambda *a, **k: None)

        assert client.put(self.INDEXABLE, json={"indexable": True}).status_code == 404

    def test_borrar_devuelve_204(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.pursuit_attachments as svc

        monkeypatch.setattr(svc, "borrar", lambda *a, **k: True)

        assert client.delete(self.BORRAR).status_code == 204

    def test_borrar_lo_que_no_esta_es_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.pursuit_attachments as svc

        monkeypatch.setattr(svc, "borrar", lambda *a, **k: False)

        assert client.delete(self.BORRAR).status_code == 404

    def test_un_viewer_no_borra(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        from services.organizations import OrganizationPermissionError

        _falla_con(monkeypatch, "borrar", OrganizationPermissionError("solo lectura"))

        assert client.delete(self.BORRAR).status_code == 403
