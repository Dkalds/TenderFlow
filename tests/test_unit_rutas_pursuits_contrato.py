"""Las rutas de C2.2, C6.1 y C6.4 contra su contrato de errores, sin Postgres.

**Por qué existe este fichero.** Se daba por hecho que en este repo un test de
ruta levanta base —la fixture `client` cuelga de `api_db`— y por eso estas rutas
se quedaron sin probar. No es cierto para las que son un envoltorio fino: el
servicio se inyecta con `monkeypatch` y la autenticación con
`dependency_overrides`, y entonces lo que se ejercita es exactamente lo que la
ruta aporta —**el mapeo de excepción a código HTTP**— sin tocar una fila.

Y ese mapeo es justo la parte que ningún test cubría y que no se ve leyendo el
código: que salir siendo owner sea 409 y no 403, que un destinatario que no es
miembro sea 404 y no 400, que un estado de tarea inválido sea 422. Un
`except ValueError` de más o de menos no lo detecta mypy, y el fuzzing solo
encuentra el caso que **rompe**, no el que devuelve el código equivocado.

`require_recent_session()` no se sustituye: se le da un contexto de sesión
reciente y se deja correr, para que su comprobación también se ejecute.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

_TAREA = {
    "id": 1,
    "pursuit_id": 3,
    "organization_id": 7,
    "titulo": "Revisar el pliego técnico",
    "responsable_user_id": None,
    "responsable_name": None,
    "vence": "2026-10-01",
    "estado": "pendiente",
    "created_at": "2026-09-08T10:00:00Z",
    "updated_at": "2026-09-08T10:00:00Z",
}

_CRITERIOS = [
    {"criterio": c, "etiqueta": c.title(), "invertido": c == "riesgo", "peso": 1.0}
    for c in ("encaje", "capacidad", "competencia", "rentabilidad", "riesgo")
]

_PUNTUACION = {
    "pursuit_id": 3,
    "organization_id": 7,
    "criterios": _CRITERIOS,
    "total": 4.0,
    "umbral": 3.0,
    "recomendacion": "go",
    "criterios_puntuados": 5,
    "completa": True,
    "decision": None,
    "discrepa": False,
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Cliente con la autenticación sustituida y **sin** base de datos.

    El contexto declara sesión reciente y sin MFA pendiente para que las rutas
    protegidas por `require_recent_session()` lleguen a su cuerpo: esa
    dependencia cuelga de `require_any_auth`, así que sustituir la de abajo basta
    y de paso su propia comprobación se ejecuta de verdad.
    """
    from api.app import app
    from api.routes.dual_auth import require_any_auth

    ctx = {
        "user_id": 5,
        "scopes": ["*"],
        "auth_method": "session",
        "authenticated_at": datetime.now(UTC).isoformat(),
        "mfa_required": False,
    }
    app.dependency_overrides[require_any_auth] = lambda: ctx
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.clear()


def _falla_con(monkeypatch: pytest.MonkeyPatch, destino: Any, nombre: str, exc: Exception) -> None:
    def _boom(*a: Any, **k: Any) -> Any:
        raise exc

    monkeypatch.setattr(destino, nombre, _boom)


class TestTraspasoDePropiedad:
    RUTA = "/api/v1/organizations/1/transfer-ownership"
    CUERPO: ClassVar[dict[str, Any]] = {"nuevo_owner_user_id": 9}

    def test_quien_no_es_owner_recibe_403(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import api.routes.pursuits as rutas
        from services.organizations import OrganizationPermissionError

        _falla_con(
            monkeypatch, rutas, "transferir_propiedad", OrganizationPermissionError("no sos owner")
        )

        assert client.post(self.RUTA, json=self.CUERPO).status_code == 403

    def test_un_destinatario_que_no_es_miembro_es_404_y_no_400(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No es un cuerpo mal formado: es un recurso que no está."""
        import api.routes.pursuits as rutas
        from services.organizations import OrganizationMemberNotFoundError

        _falla_con(
            monkeypatch,
            rutas,
            "transferir_propiedad",
            OrganizationMemberNotFoundError("invitalo primero"),
        )

        assert client.post(self.RUTA, json=self.CUERPO).status_code == 404

    def test_la_organizacion_personal_es_409(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Conflicto con el estado del recurso, no falta de permiso."""
        import api.routes.pursuits as rutas
        from services.organizations import OrganizationLifecycleError

        _falla_con(
            monkeypatch, rutas, "transferir_propiedad", OrganizationLifecycleError("es la personal")
        )

        assert client.post(self.RUTA, json=self.CUERPO).status_code == 409

    def test_el_traspaso_bueno_responde_ok(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import api.routes.pursuits as rutas

        monkeypatch.setattr(rutas, "transferir_propiedad", lambda **k: None)

        respuesta = client.post(self.RUTA, json=self.CUERPO)
        assert respuesta.status_code == 200
        assert respuesta.json() == {"status": "ok"}


class TestSalida:
    RUTA = "/api/v1/organizations/1/leave"

    def test_quien_no_es_miembro_es_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import api.routes.pursuits as rutas
        from services.organizations import OrganizationMemberNotFoundError

        _falla_con(
            monkeypatch, rutas, "salir_de_organizacion", OrganizationMemberNotFoundError("no sos")
        )

        assert client.post(self.RUTA).status_code == 404

    def test_el_owner_que_intenta_irse_es_409(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """403 diría «no podés»; 409 dice «no en este estado», que es lo cierto:
        traspasando primero, sí puede."""
        import api.routes.pursuits as rutas
        from services.organizations import OrganizationLifecycleError

        _falla_con(
            monkeypatch, rutas, "salir_de_organizacion", OrganizationLifecycleError("sos el owner")
        )

        assert client.post(self.RUTA).status_code == 409

    def test_la_salida_buena_responde_ok(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import api.routes.pursuits as rutas

        monkeypatch.setattr(rutas, "salir_de_organizacion", lambda **k: None)

        assert client.post(self.RUTA).json() == {"status": "ok"}


class TestBorrado:
    PREVIEW = "/api/v1/organizations/1/deletion-preview"
    BORRAR = "/api/v1/organizations/1/delete"

    def test_el_preview_solo_lo_ve_el_owner(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import api.routes.pursuits as rutas
        from services.organizations import OrganizationPermissionError

        _falla_con(
            monkeypatch, rutas, "resumen_de_borrado", OrganizationPermissionError("no sos owner")
        )

        assert client.get(self.PREVIEW).status_code == 403

    def test_el_preview_cuenta_lo_que_se_va_a_perder(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import api.routes.pursuits as rutas

        monkeypatch.setattr(
            rutas,
            "resumen_de_borrado",
            lambda **k: {"oportunidades": 14, "comentarios": 37, "miembros": 3},
        )

        assert client.get(self.PREVIEW).json() == {
            "oportunidades": 14,
            "comentarios": 37,
            "miembros": 3,
        }

    def test_una_confirmacion_incorrecta_es_409(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import api.routes.pursuits as rutas
        from services.organizations import OrganizationLifecycleError

        _falla_con(
            monkeypatch, rutas, "borrar_organizacion", OrganizationLifecycleError("escribí BORRAR")
        )

        assert client.post(self.BORRAR, json={"confirmacion": "si"}).status_code == 409

    def test_una_organizacion_inexistente_es_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import api.routes.pursuits as rutas
        from services.organizations import OrganizationMemberNotFoundError

        _falla_con(
            monkeypatch, rutas, "borrar_organizacion", OrganizationMemberNotFoundError("no existe")
        )

        assert client.post(self.BORRAR, json={"confirmacion": "BORRAR"}).status_code == 404

    def test_el_borrado_devuelve_el_recuento_de_lo_borrado(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Es lo que va al registro de auditoría."""
        import api.routes.pursuits as rutas

        monkeypatch.setattr(
            rutas,
            "borrar_organizacion",
            lambda **k: {"oportunidades": 2, "comentarios": 5, "miembros": 1},
        )

        respuesta = client.post(self.BORRAR, json={"confirmacion": "BORRAR"})
        assert respuesta.status_code == 200
        assert respuesta.json()["oportunidades"] == 2

    def test_una_sesion_vieja_no_borra_nada(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """El borrado exige sesión reciente: una API key no alcanza."""
        from api.app import app
        from api.routes.dual_auth import require_any_auth

        app.dependency_overrides[require_any_auth] = lambda: {
            "user_id": 5,
            "scopes": ["*"],
            "auth_method": "api_key",
        }
        try:
            c = TestClient(app, raise_server_exceptions=True)
            assert c.post(self.BORRAR, json={"confirmacion": "BORRAR"}).status_code == 403
        finally:
            app.dependency_overrides.clear()


class TestRutasDeTareas:
    LISTA = "/api/v1/pursuits/3/tasks"
    UNA = "/api/v1/pursuits/3/tasks/1"

    def test_listar_devuelve_las_tareas_tipadas(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.pursuit_tasks as svc

        monkeypatch.setattr(svc, "list_tasks", lambda *a, **k: [_TAREA])

        respuesta = client.get(self.LISTA)
        assert respuesta.status_code == 200
        assert respuesta.json()[0]["titulo"] == "Revisar el pliego técnico"

    def test_una_oportunidad_ajena_es_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.pursuit_tasks as svc
        from services.pursuits import PursuitNotFoundError

        _falla_con(monkeypatch, svc, "list_tasks", PursuitNotFoundError("no existe"))

        assert client.get(self.LISTA).status_code == 404

    def test_sin_acceso_a_la_organizacion_es_403(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.pursuit_tasks as svc
        from services.organizations import OrganizationAccessError

        _falla_con(monkeypatch, svc, "list_tasks", OrganizationAccessError("no sos miembro"))

        assert client.get(self.LISTA).status_code == 403

    def test_crear_devuelve_201(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.pursuit_tasks as svc

        monkeypatch.setattr(svc, "create_task", lambda *a, **k: _TAREA)

        assert client.post(self.LISTA, json={"titulo": "Revisar"}).status_code == 201

    def test_un_viewer_no_crea_y_recibe_403(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.pursuit_tasks as svc
        from services.organizations import OrganizationPermissionError

        _falla_con(monkeypatch, svc, "create_task", OrganizationPermissionError("solo lectura"))

        assert client.post(self.LISTA, json={"titulo": "Revisar"}).status_code == 403

    def test_un_titulo_vacio_lo_rechaza_el_contrato(self, client: TestClient) -> None:
        """No llega al servicio: lo para el DTO."""
        assert client.post(self.LISTA, json={"titulo": ""}).status_code == 422

    def test_un_estado_invalido_es_422_y_no_400(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El servicio lanza `ValueError` y la ruta lo traduce a entidad no
        procesable, que es lo que es: sintaxis correcta, valor fuera del
        vocabulario."""
        import services.pursuit_tasks as svc

        _falla_con(monkeypatch, svc, "update_task", ValueError("estado inválido: terminada"))

        assert client.patch(self.UNA, json={"estado": "terminada"}).status_code == 422

    def test_una_tarea_que_no_existe_es_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.pursuit_tasks as svc

        _falla_con(monkeypatch, svc, "update_task", svc.PursuitTaskNotFoundError("no encontrada"))

        assert client.patch(self.UNA, json={"titulo": "Otro"}).status_code == 404

    def test_actualizar_devuelve_la_tarea(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.pursuit_tasks as svc

        monkeypatch.setattr(svc, "update_task", lambda *a, **k: {**_TAREA, "estado": "hecha"})

        assert client.patch(self.UNA, json={"estado": "hecha"}).json()["estado"] == "hecha"

    def test_borrar_devuelve_204_sin_cuerpo(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.pursuit_tasks as svc

        monkeypatch.setattr(svc, "delete_task", lambda *a, **k: None)

        respuesta = client.delete(self.UNA)
        assert respuesta.status_code == 204
        assert respuesta.content == b""

    def test_borrar_lo_que_no_esta_es_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.pursuit_tasks as svc

        _falla_con(monkeypatch, svc, "delete_task", svc.PursuitTaskNotFoundError("no encontrada"))

        assert client.delete(self.UNA).status_code == 404


class TestRutasDeGoNoGo:
    PESOS = "/api/v1/organizations/go-no-go/weights"
    PUNTUACION = "/api/v1/pursuits/3/go-no-go"

    def test_los_pesos_salen_con_sus_cinco_criterios(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.go_no_go_puntuacion as svc

        monkeypatch.setattr(
            svc,
            "get_weights",
            lambda *a, **k: {"organization_id": 7, "umbral": 3.0, "criterios": _CRITERIOS},
        )

        assert len(client.get(self.PESOS).json()["criterios"]) == 5

    def test_un_miembro_raso_no_mueve_los_pesos(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.go_no_go_puntuacion as svc
        from services.organizations import OrganizationPermissionError

        _falla_con(monkeypatch, svc, "set_weights", OrganizationPermissionError("solo owner"))

        assert client.put(self.PESOS, json={"pesos": {"encaje": 3.0}}).status_code == 403

    def test_los_pesos_se_guardan_y_se_devuelven(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.go_no_go_puntuacion as svc

        monkeypatch.setattr(
            svc,
            "set_weights",
            lambda *a, **k: {"organization_id": 7, "umbral": 3.0, "criterios": _CRITERIOS},
        )

        assert client.put(self.PESOS, json={"pesos": {"encaje": 3.0}}).status_code == 200

    def test_la_puntuacion_viaja_con_la_discrepancia(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.go_no_go_puntuacion as svc

        monkeypatch.setattr(
            svc, "get_score", lambda *a, **k: {**_PUNTUACION, "decision": "no_go", "discrepa": True}
        )

        cuerpo = client.get(self.PUNTUACION).json()
        assert cuerpo["discrepa"] is True
        assert cuerpo["recomendacion"] == "go"

    def test_puntuar_una_oportunidad_ajena_es_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.go_no_go_puntuacion as svc
        from services.pursuits import PursuitNotFoundError

        _falla_con(monkeypatch, svc, "set_score", PursuitNotFoundError("no existe"))

        respuesta = client.put(self.PUNTUACION, json={"criterio": "encaje", "puntuacion": 4})
        assert respuesta.status_code == 404

    def test_una_puntuacion_fuera_de_rango_la_para_el_contrato(self, client: TestClient) -> None:
        """1..5: no llega al servicio."""
        respuesta = client.put(self.PUNTUACION, json={"criterio": "encaje", "puntuacion": 9})
        assert respuesta.status_code == 422

    def test_un_criterio_desconocido_es_422(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.go_no_go_puntuacion as svc

        _falla_con(monkeypatch, svc, "set_score", ValueError("criterio desconocido"))

        respuesta = client.put(self.PUNTUACION, json={"criterio": "suerte", "puntuacion": 4})
        assert respuesta.status_code == 422

    def test_puntuar_devuelve_la_ficha_recalculada(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.go_no_go_puntuacion as svc

        monkeypatch.setattr(svc, "set_score", lambda *a, **k: _PUNTUACION)

        respuesta = client.put(self.PUNTUACION, json={"criterio": "encaje", "puntuacion": 4})
        assert respuesta.status_code == 200
        assert respuesta.json()["total"] == 4.0
