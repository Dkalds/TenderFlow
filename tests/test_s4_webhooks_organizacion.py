"""Webhooks por organización: aislamiento en las dos dimensiones (S4.2).

Integración (``client``/``api_db``). El patrón de aislamiento es el del PR #271:
no basta con comprobar que A no ve lo de B — hay que comprobar **también** que A
sí ve lo suyo. Un endpoint que devuelve la lista vacía siempre pasa la mitad
del test, y así se colaron regresiones que dejaban una pantalla en blanco.
"""

from __future__ import annotations

import pytest

from api.app import app
from api.routes.dual_auth import require_any_auth
from db.repositories.organizations import OrganizationRepository

_URL_A = "https://hooks.example.com/equipo-a"
_URL_B = "https://hooks.example.com/equipo-b"


def _usuario(email: str) -> tuple[int, int]:
    """Crea un usuario con su organización personal. Devuelve ``(user_id, org_id)``."""
    from db.users import create_user

    user_id = create_user(
        email=email,
        password_hash="test-hash",  # pragma: allowlist secret
        display_name=email.split("@")[0],
    )
    org_id = int(OrganizationRepository().ensure_personal_organization(user_id)["id"])
    return user_id, org_id


def _como(user_id: int) -> None:
    app.dependency_overrides[require_any_auth] = lambda: {
        "user_id": user_id,
        "auth_method": "session",
        "user_key": f"user-{user_id}",
        "email": f"u{user_id}@example.test",
        "is_admin": False,
    }


@pytest.fixture(autouse=True)
def _sin_ssrf(monkeypatch):
    """La allowlist SSRF no es lo que se prueba aquí; tiene sus propios tests."""
    monkeypatch.setattr("api.routes.webhooks.validate_outbound_url", lambda url, **_: url)
    yield
    app.dependency_overrides.clear()


def _crear(client, *, name: str, url: str, organization_id: int, formato: str = "json"):
    return client.post(
        "/api/v1/webhooks",
        json={
            "name": name,
            "url": url,
            "event_types": ["pursuit.*"],
            "formato": formato,
            "organization_id": organization_id,
        },
    )


def test_un_miembro_crea_un_webhook_en_su_organizacion(client, api_db):
    """Antes hacía falta ``is_admin`` de instancia: un equipo no podía tener su
    propio canal sin que se lo creara el administrador."""
    user_id, org_id = _usuario("s4-webhooks-a@example.test")
    _como(user_id)

    respuesta = _crear(client, name="equipo-a", url=_URL_A, organization_id=org_id)
    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["organization_id"] == org_id
    assert cuerpo["formato"] == "json"
    assert cuerpo["secret"], "el secret solo viaja en la creación, pero tiene que viajar"


def test_aislamiento_en_las_dos_dimensiones(client, api_db):
    user_a, org_a = _usuario("s4-webhooks-iso-a@example.test")
    user_b, org_b = _usuario("s4-webhooks-iso-b@example.test")

    _como(user_a)
    creado_a = _crear(client, name="equipo-a", url=_URL_A, organization_id=org_a).json()
    _como(user_b)
    creado_b = _crear(client, name="equipo-b", url=_URL_B, organization_id=org_b).json()

    # 1. A ve lo suyo y SOLO lo suyo.
    _como(user_a)
    lista_a = client.get("/api/v1/webhooks", params={"organization_id": org_a}).json()
    assert [w["id"] for w in lista_a] == [creado_a["id"]]

    # 2. B ve lo suyo y SOLO lo suyo.
    _como(user_b)
    lista_b = client.get("/api/v1/webhooks", params={"organization_id": org_b}).json()
    assert [w["id"] for w in lista_b] == [creado_b["id"]]

    # 3. El detalle ajeno es 404, no 200 con datos de otro equipo.
    assert client.get(f"/api/v1/webhooks/{creado_a['id']}").status_code == 404
    # 4. Y tampoco se puede borrar ni editar.
    assert client.delete(f"/api/v1/webhooks/{creado_a['id']}").status_code == 404
    assert (
        client.patch(f"/api/v1/webhooks/{creado_a['id']}", json={"active": False}).status_code
        == 404
    )


def test_pedir_la_organizacion_de_otro_es_403(client, api_db):
    """El ámbito lo resuelve ``api/tenancy.py``: sin membresía no hay lectura."""
    user_a, _org_a = _usuario("s4-webhooks-403-a@example.test")
    _user_b, org_b = _usuario("s4-webhooks-403-b@example.test")
    _como(user_a)
    assert client.get("/api/v1/webhooks", params={"organization_id": org_b}).status_code == 403


def test_event_types_lista_el_catalogo_completo(client, api_db):
    """Estaba declarada DESPUÉS de ``/{webhook_id}``, así que FastAPI la
    resolvía por la ruta paramétrica y moría en la validación con un 422."""
    user_id, _ = _usuario("s4-webhooks-tipos@example.test")
    _como(user_id)

    respuesta = client.get("/api/v1/webhooks/event-types")
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()

    from shared.events import FORMATOS, TIPOS

    publicados = set(cuerpo["event_types"])
    assert TIPOS.issubset(publicados)
    assert {"*", "pursuit.*", "licitacion.*", "adjudicacion.*"}.issubset(publicados)
    assert set(cuerpo["formatos"]) == set(FORMATOS)


def test_un_formato_fuera_de_los_tres_no_se_acepta(client, api_db):
    user_id, org_id = _usuario("s4-webhooks-formato@example.test")
    _como(user_id)
    respuesta = _crear(
        client, name="raro", url=_URL_A, organization_id=org_id, formato="carta_certificada"
    )
    assert respuesta.status_code == 422


def test_un_tipo_de_evento_fuera_del_catalogo_no_se_acepta(client, api_db):
    user_id, org_id = _usuario("s4-webhooks-tipo-malo@example.test")
    _como(user_id)
    respuesta = client.post(
        "/api/v1/webhooks",
        json={
            "name": "raro",
            "url": _URL_A,
            "event_types": ["pursuit.inventado"],
            "organization_id": org_id,
        },
    )
    assert respuesta.status_code == 422


def test_el_formato_se_puede_cambiar_sin_recrear_el_webhook(client, api_db):
    user_id, org_id = _usuario("s4-webhooks-patch@example.test")
    _como(user_id)
    creado = _crear(client, name="equipo", url=_URL_A, organization_id=org_id).json()

    respuesta = client.patch(f"/api/v1/webhooks/{creado['id']}", json={"formato": "slack_blocks"})
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["formato"] == "slack_blocks"


def test_el_ping_usa_la_plantilla_elegida(client, api_db, monkeypatch):
    """Criterio de S4.3: un ping que siempre saliera en JSON no probaría lo
    único que se quiere probar antes de activar la integración."""
    user_id, org_id = _usuario("s4-webhooks-ping@example.test")
    _como(user_id)
    creado = _crear(
        client, name="equipo", url=_URL_A, organization_id=org_id, formato="teams_adaptive_card"
    ).json()

    enviados: list[bytes] = []

    def _post(url, payload, headers):
        enviados.append(payload)
        assert headers["X-Webhook-Signature"].startswith("sha256=")
        return 200

    monkeypatch.setattr("api.routes.webhooks._post_pinned_webhook", _post)

    respuesta = client.post(f"/api/v1/webhooks/{creado['id']}/ping")
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["success"] is True

    import json as _json

    cuerpo = _json.loads(enviados[0])
    assert cuerpo["type"] == "message"
    assert cuerpo["attachments"][0]["content"]["version"] == "1.5"
