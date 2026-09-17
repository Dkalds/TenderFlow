"""Sesiones, preferencias y claves de `/me` contra su contrato, sin Postgres.

Son las tres capacidades que C2 sacó de «existe en el código» a «tiene puerta»:
`list_active_sessions` llevaba desde siempre sin que la llamara nadie (hecho 7),
las preferencias no las modelaba ninguna tabla (hecho 13) y `create_api_key`
solo la usaba un script (hecho 9). Las tres entraron con la ruta escrita y sin
un test que la ejercitara.

Lo que se fija aquí es lo que la ruta decide por su cuenta: que revocar una
sesión ajena sea 404 y no 403 —distinguirlos le diría a un enumerador si el id
existe—, que una clave no pueda conceder más permiso del que tiene quien la
crea, y que el `PUT` de preferencias **añada o pise** sin borrar lo que no
viene.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient


def _ctx(**extra: Any) -> dict[str, Any]:
    return {
        "user_id": 5,
        "scopes": ["*"],
        "auth_method": "session",
        "authenticated_at": datetime.now(UTC).isoformat(),
        "mfa_required": False,
        **extra,
    }


def _cliente(ctx: dict[str, Any]) -> Iterator[TestClient]:
    from api.app import app
    from api.routes.dual_auth import require_any_auth

    app.dependency_overrides[require_any_auth] = lambda: ctx
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield from _cliente(_ctx())


class TestSesiones:
    RUTA = "/api/v1/me/sessions"

    def test_el_listado_no_expone_el_token_ni_el_hash(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El id público es derivado: con él se revoca, pero no se reconstruye
        la cookie."""
        import api.routes.me as rutas

        monkeypatch.setattr(
            rutas,
            "list_active_sessions",
            lambda uid: [
                {
                    "token_hash": "h" * 64,
                    "created_at": "2026-09-01T10:00:00Z",
                    "expires_at": "2026-10-01T10:00:00Z",
                    "ip": "10.0.0.1",
                    "user_agent": "Firefox",
                }
            ],
        )

        cuerpo = client.get(self.RUTA).json()
        serializado = str(cuerpo)
        assert "h" * 64 not in serializado
        assert "token_hash" not in serializado
        assert cuerpo["items"][0]["ip"] == "10.0.0.1"

    def test_sin_cookie_ninguna_sesion_sale_como_actual(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Una petición con API key no tiene sesión: marcar una sería mentir."""
        import api.routes.me as rutas

        monkeypatch.setattr(
            rutas,
            "list_active_sessions",
            lambda uid: [{"token_hash": "a" * 64}, {"token_hash": "b" * 64}],
        )

        items = client.get(self.RUTA).json()["items"]
        assert [i["actual"] for i in items] == [False, False]

    def test_la_sesion_de_esta_peticion_sale_marcada(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import api.routes.me as rutas
        import db.sessions as sesiones
        from api.routes.auth import SESSION_COOKIE

        monkeypatch.setattr(
            rutas,
            "list_active_sessions",
            lambda uid: [{"token_hash": "a" * 64}, {"token_hash": "b" * 64}],
        )
        monkeypatch.setattr(sesiones, "_hash_token", lambda token: "b" * 64)

        client.cookies.set(SESSION_COOKIE, "lo-que-sea")
        items = client.get(self.RUTA).json()["items"]
        assert [i["actual"] for i in items] == [False, True]

    def test_revocar_una_sesion_ajena_es_404_y_no_403(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Distinguir los dos le diría a un enumerador si el id existe."""
        import api.routes.me as rutas

        monkeypatch.setattr(rutas, "revoke_session_by_public_id", lambda uid, sid: False)

        assert client.delete(f"{self.RUTA}/abc123").status_code == 404

    def test_revocar_la_propia_devuelve_204_y_queda_auditado(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import api.routes.me as rutas

        eventos: list[dict[str, Any]] = []
        monkeypatch.setattr(rutas, "revoke_session_by_public_id", lambda uid, sid: True)
        monkeypatch.setattr(rutas, "log_event", lambda **kw: eventos.append(kw))

        assert client.delete(f"{self.RUTA}/abc123").status_code == 204
        assert eventos[0]["event_type"] == "auth.session_revoked"

    def test_una_api_key_no_revoca_sesiones(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cerrar la sesión de otro dispositivo es lo que haría alguien con una
        cookie robada: exige sesión reciente."""
        for cliente in _cliente(_ctx(auth_method="api_key")):
            assert cliente.delete(f"{self.RUTA}/abc123").status_code == 403


class TestPreferenciasDeNotificacion:
    RUTA = "/api/v1/me/notification-preferences"

    def test_el_contrato_publica_los_defectos_y_el_vocabulario(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El frontend no tiene que adivinar qué pasa con lo que no está en la
        tabla."""
        from db.repositories import notification_preferences as prefs

        monkeypatch.setattr(prefs, "listar", lambda uid, organization_id=None: [])

        cuerpo = client.get(self.RUTA).json()
        assert cuerpo["defaults"] == dict(prefs.DEFECTOS)
        assert len(cuerpo["tipos"]) == len(prefs.TIPOS)

    def test_las_filas_guardadas_salen_con_su_tipo_y_su_organizacion(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`None` = en todas partes; con organización, solo en ese equipo.

        Las dos filas tienen tipos distintos, así que una ruta que devolviera un
        tipo fijo no reproduciría la lista.
        """
        from db.repositories import notification_preferences as prefs

        monkeypatch.setattr(
            prefs,
            "listar",
            lambda uid, organization_id=None: [
                {
                    "tipo": "daily_summary",
                    "canal": "email",
                    "frecuencia": "daily",
                    "organization_id": 7,
                },
                {
                    "tipo": "pursuit.mention",
                    "canal": "email",
                    "frecuencia": "off",
                    "organization_id": None,
                },
            ],
        )

        items = client.get(self.RUTA).json()["items"]
        assert [i["tipo"] for i in items] == ["daily_summary", "pursuit.mention"]
        assert [i["organization_id"] for i in items] == [7, None]

    def test_canal_y_frecuencia_salen_tal_cual_de_la_fila(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cada fila conserva su canal y su frecuencia, con todo el vocabulario
        del repositorio.

        Las filas combinan cada canal de `CANALES` con cada frecuencia de
        `FRECUENCIAS`, en ese orden: una ruta que devolviera un valor fijo o
        tomara uno de otra fila no reproduciría la lista, y si la ruta no
        admitiera un valor que el repositorio sí admite, esa fila haría fallar el
        GET.
        """
        from db.repositories import notification_preferences as prefs

        combinaciones = [(c, fr) for c in prefs.CANALES for fr in prefs.FRECUENCIAS]
        monkeypatch.setattr(
            prefs,
            "listar",
            lambda uid, organization_id=None: [
                {"tipo": "daily_summary", "canal": c, "frecuencia": fr, "organization_id": None}
                for c, fr in combinaciones
            ],
        )

        items = client.get(self.RUTA).json()["items"]
        assert [(i["canal"], i["frecuencia"]) for i in items] == combinaciones

    def test_el_vocabulario_del_contrato_es_el_del_repositorio(self) -> None:
        """Los `Literal` de la ruta y las tuplas del repositorio dicen lo mismo."""
        from typing import get_args

        import api.routes.me as rutas
        from db.repositories import notification_preferences as prefs

        assert get_args(rutas.CanalNotificacion) == prefs.CANALES
        assert get_args(rutas.FrecuenciaNotificacion) == prefs.FRECUENCIAS

    def test_una_fila_fuera_del_vocabulario_hace_fallar_el_get_con_400(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """La ruta no se salta la fila: el `ValidationError` llega al manejador de
        `ValueError`, que responde 400 `problem+json`."""
        from db.repositories import notification_preferences as prefs

        monkeypatch.setattr(
            prefs,
            "listar",
            lambda uid, organization_id=None: [
                {"tipo": "daily_summary", "canal": "email", "frecuencia": "daily"},
                {"tipo": "daily_summary", "canal": "sms", "frecuencia": "weekly"},
            ],
        )

        respuesta = client.get(self.RUTA)
        assert respuesta.status_code == 400
        assert respuesta.headers["content-type"] == "application/problem+json"

    def test_la_fila_fuera_del_vocabulario_da_los_mismos_errores_que_el_modelo_publico(
        self,
    ) -> None:
        """Lo que promete `_CanalYFrecuencia`: los errores de los dos campos
        juntos, con los mismos `loc`, tipo y mensaje que daría
        `NotificationPreference`; solo cambia el título."""
        from pydantic import ValidationError

        import api.routes.me as rutas

        fila = {"tipo": "daily_summary", "canal": "sms", "frecuencia": "weekly"}

        with pytest.raises(ValidationError) as interno:
            rutas._CanalYFrecuencia.model_validate(fila)
        with pytest.raises(ValidationError) as publico:
            rutas.NotificationPreference.model_validate(fila)

        def _resumen(exc: ValidationError) -> list[tuple[Any, ...]]:
            return [(e["loc"], e["type"], e["msg"]) for e in exc.errors()]

        assert [e[0] for e in _resumen(interno.value)] == [("canal",), ("frecuencia",)]
        assert _resumen(interno.value) == _resumen(publico.value)
        assert (interno.value.title, publico.value.title) == (
            "_CanalYFrecuencia",
            "NotificationPreference",
        )

    def test_el_put_guarda_cada_preferencia_enviada(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from db.repositories import notification_preferences as prefs

        guardadas: list[dict[str, Any]] = []
        monkeypatch.setattr(prefs, "guardar", lambda uid, **kw: guardadas.append(kw))

        respuesta = client.put(
            self.RUTA,
            json=[
                {"tipo": "daily_summary", "canal": "email", "frecuencia": "daily"},
                {"tipo": "pursuit.mention", "canal": "in_app", "frecuencia": "immediate"},
            ],
        )
        assert respuesta.status_code == 200
        assert [g["tipo"] for g in guardadas] == ["daily_summary", "pursuit.mention"]

    def test_un_vocabulario_desconocido_es_422(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from db.repositories import notification_preferences as prefs

        def _explota(uid: int, **kw: Any) -> None:
            raise ValueError("tipo desconocido: humo")

        monkeypatch.setattr(prefs, "guardar", _explota)

        respuesta = client.put(
            self.RUTA, json=[{"tipo": "humo", "canal": "email", "frecuencia": "daily"}]
        )
        assert respuesta.status_code == 422


class TestCrearClave:
    RUTA = "/api/v1/me/keys"

    def _sin_repositorio(self, monkeypatch: pytest.MonkeyPatch, raw: str = "tf_secreto") -> list:
        import api.routes.me as rutas

        creadas: list[dict[str, Any]] = []

        def _create(name: str, **kw: Any) -> str:
            creadas.append({"name": name, **kw})
            return raw

        class _Repo:
            def get_by_hash(self, h: str) -> dict[str, Any]:
                return {"id": 11, "expires_at": "2026-12-01T00:00:00Z"}

        monkeypatch.setattr(rutas, "create_api_key", _create)
        monkeypatch.setattr(rutas, "ApiKeyRepository", _Repo)
        monkeypatch.setattr(rutas, "log_event", lambda **kw: None)
        return creadas

    def test_una_clave_no_concede_mas_permiso_del_que_tiene_quien_la_crea(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sin esto, cualquiera acuñaría una credencial `admin` desde su propia
        cuenta: una escalada servida por el formulario."""
        creadas = self._sin_repositorio(monkeypatch)

        respuesta = client.post(self.RUTA, json={"name": "mia", "scopes": "admin"})
        assert respuesta.status_code == 403
        assert creadas == []

    def test_un_administrador_si_puede_pedirlos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for cliente in _cliente(_ctx(is_admin=True)):
            creadas = self._sin_repositorio(monkeypatch)
            respuesta = cliente.post(self.RUTA, json={"name": "mia", "scopes": "admin"})
            assert respuesta.status_code == 201
            assert creadas[0]["scopes"] == "admin"

    def test_los_scopes_se_normalizan_y_ordenan(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        creadas = self._sin_repositorio(monkeypatch)

        client.post(self.RUTA, json={"name": "mia", "scopes": " read , write ,read "})
        assert creadas[0]["scopes"] == "read,write"

    def test_el_secreto_se_muestra_una_sola_vez_y_en_la_creacion(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._sin_repositorio(monkeypatch, raw="tf_secreto_unico")

        cuerpo = client.post(self.RUTA, json={"name": "mia"}).json()
        assert cuerpo["api_key"] == "tf_secreto_unico"  # pragma: allowlist secret
        assert cuerpo["id"] == 11

    def test_un_ttl_fuera_de_rango_es_422(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import api.routes.me as rutas

        def _explota(name: str, **kw: Any) -> str:
            raise ValueError("expires_days por encima de API_KEY_MAX_TTL_DAYS")

        monkeypatch.setattr(rutas, "create_api_key", _explota)

        respuesta = client.post(self.RUTA, json={"name": "mia", "expires_days": 9999})
        assert respuesta.status_code == 422

    def test_acunar_una_clave_exige_sesion_reciente(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sobrevive al cierre de sesión: es lo primero que haría alguien con
        una cookie robada."""
        for cliente in _cliente(_ctx(auth_method="api_key")):
            assert cliente.post(self.RUTA, json={"name": "mia"}).status_code == 403
