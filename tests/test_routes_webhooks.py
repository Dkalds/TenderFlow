"""Tests de los endpoints /api/v1/webhooks (GET, PATCH, DELETE, ping, deliveries).

No se duplican:
- SSRF validation tests (en test_api_improvements.py)
- Scope 403 tests con API key restringida (en test_api_improvements.py)
- Create + Idempotency-Key (en test_ola1_fixes.py)

F13·C3.1 (plan Pliegos+RAG): los endpoints migraron de ``require_scope`` a
``require_any_auth``. Los tests de sesión OAuth viven aquí; los de API key
restringida (sin scope ``*``) siguen en test_api_improvements.py.

S4.2 (plan 2026-09 v2): un webhook pertenece ahora a una **organización** y las
rutas resuelven la del principal (``require_organization``). Eso obliga a que el
principal de estos tests exista de verdad en ``users``: resolver la organización
personal empieza por leer la fila del usuario, y un id inventado moría en
``ensure_personal_organization`` con ``ValueError("Usuario no encontrado.")``,
que ``api/errors.py`` enmascara como 400 —el 400 que vio CI en los 16 tests de
este fichero—.

Que la fixture se actualice, y no la ruta, es deliberado: en prod y staging
``api/auth.py`` rechaza una API key sin dueño (``unbound_api_key_rejected``) y
``create_api_key`` ni siquiera deja emitirla, así que **no existe un camino de
producción con un principal sin usuario**. Degradar la ruta a una vista global
para tolerarlo habría abierto un modo de acceso sin tenencia que la credencial
real nunca puede alcanzar.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from api.app import app
from api.routes.dual_auth import require_any_auth

# Fixtures client, auth, api_db se heredan de conftest.py

_WEBHOOK_URL = "https://example.com/hook"


def _crear_usuario(email: str) -> int:
    from db.users import create_user

    return create_user(
        email=email,
        password_hash="test-hash",  # pragma: allowlist secret
        display_name=email.split("@")[0],
    )


def _sesion(user_id: int, email: str, *, is_admin: bool):
    return lambda: {
        "user_id": user_id,
        "email": email,
        "is_admin": is_admin,
        "auth_method": "session",
        "user_key": f"uk-{user_id}",
    }


@pytest.fixture()
def admin_user_id(api_db) -> int:
    """Usuario real para el principal de las pruebas generales."""
    return _crear_usuario("admin@test.com")


@pytest.fixture(autouse=True)
def _admin_principal(admin_user_id):
    """Las pruebas generales de webhooks se ejecutan como administrador explícito."""
    app.dependency_overrides[require_any_auth] = _sesion(
        admin_user_id, "admin@test.com", is_admin=True
    )
    yield
    app.dependency_overrides.clear()


def _create_webhook(client, auth, monkeypatch, *, name="hook", url=_WEBHOOK_URL):
    """Helper: crea un webhook saltándose la validación SSRF y devuelve el JSON de respuesta."""
    monkeypatch.setattr("api.routes.webhooks.validate_outbound_url", lambda url, **_: url)
    r = client.post(
        "/api/v1/webhooks",
        json={"name": name, "url": url, "event_types": ["*"]},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# GET /{id}
# ---------------------------------------------------------------------------


def test_webhook_get_by_id(client, auth, monkeypatch):
    """Crear webhook → GET /{id} devuelve 200 sin el campo 'secret'."""
    created = _create_webhook(client, auth, monkeypatch)
    wh_id = created["id"]

    r = client.get(f"/api/v1/webhooks/{wh_id}", headers=auth)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["id"] == wh_id
    assert "secret" not in data, "El campo 'secret' no debe exponerse en GET detalle"


def test_webhook_event_types_is_a_list_not_csv_string(client, auth, monkeypatch):
    """Regresión: event_types se guarda como CSV en la tabla pero la API/UI
    (F13·C3.3a, admin webhooks card) esperan una lista — no un string crudo."""
    _create_webhook(client, auth, monkeypatch)

    r_list = client.get("/api/v1/webhooks", headers=auth)
    assert r_list.status_code == 200, r_list.text
    assert isinstance(r_list.json()[0]["event_types"], list)
    assert r_list.json()[0]["event_types"] == ["*"]

    wh_id = r_list.json()[0]["id"]
    r_get = client.get(f"/api/v1/webhooks/{wh_id}", headers=auth)
    assert isinstance(r_get.json()["event_types"], list)

    monkeypatch.setattr("api.routes.webhooks.validate_outbound_url", lambda url, **_: url)
    r_multi = client.post(
        "/api/v1/webhooks",
        json={
            "name": "multi-event",
            "url": _WEBHOOK_URL,
            "event_types": ["watchlist_match", "watchlist_rule.matched"],
        },
        headers=auth,
    )
    multi_id = r_multi.json()["id"]
    r_get_multi = client.get(f"/api/v1/webhooks/{multi_id}", headers=auth)
    assert r_get_multi.json()["event_types"] == ["watchlist_match", "watchlist_rule.matched"]


def test_webhook_get_by_id_no_existe(client, auth):
    """GET /99999 → 404."""
    r = client.get("/api/v1/webhooks/99999", headers=auth)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /{id}
# ---------------------------------------------------------------------------


def test_webhook_patch_nombre(client, auth, monkeypatch):
    """Crear → PATCH con name nuevo → 200 y el nombre queda actualizado."""
    created = _create_webhook(client, auth, monkeypatch)
    wh_id = created["id"]

    r = client.patch(
        f"/api/v1/webhooks/{wh_id}",
        json={"name": "hook-renombrado"},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "hook-renombrado"


def test_webhook_patch_vacio(client, auth, monkeypatch):
    """PATCH con body vacío {} → 200 (early return del repo, sin cambios)."""
    created = _create_webhook(client, auth, monkeypatch)
    wh_id = created["id"]

    r = client.patch(f"/api/v1/webhooks/{wh_id}", json={}, headers=auth)
    assert r.status_code == 200, r.text


def test_webhook_patch_no_existe(client, auth):
    """PATCH /99999 → 404."""
    r = client.patch("/api/v1/webhooks/99999", json={"name": "x"}, headers=auth)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /{id}
# ---------------------------------------------------------------------------


def test_webhook_delete(client, auth, monkeypatch):
    """Crear → DELETE → 204, GET posterior → 404."""
    created = _create_webhook(client, auth, monkeypatch)
    wh_id = created["id"]

    r_del = client.delete(f"/api/v1/webhooks/{wh_id}", headers=auth)
    assert r_del.status_code == 204

    r_get = client.get(f"/api/v1/webhooks/{wh_id}", headers=auth)
    assert r_get.status_code == 404


def test_webhook_delete_no_existe(client, auth):
    """DELETE /99999 → 404."""
    r = client.delete("/api/v1/webhooks/99999", headers=auth)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /{id}/ping
# ---------------------------------------------------------------------------


def test_webhook_ping_exitoso(client, auth, monkeypatch):
    """Crear → ping con mock requests.post devolviendo 200 → success=True."""
    created = _create_webhook(client, auth, monkeypatch)
    wh_id = created["id"]

    # Evitar resolución DNS real en el momento del ping
    monkeypatch.setattr("api.routes.webhooks._validate_webhook_url", lambda url: url)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"

    with patch("api.routes.webhooks._post_pinned_webhook", return_value=mock_resp.status_code):
        r = client.post(f"/api/v1/webhooks/{wh_id}/ping", headers=auth)

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["success"] is True


def test_webhook_ping_no_existe(client, auth):
    """ping /99999 → 404."""
    r = client.post("/api/v1/webhooks/99999/ping", headers=auth)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /{id}/deliveries
# ---------------------------------------------------------------------------


def test_webhook_deliveries_vacias(client, auth, monkeypatch):
    """Crear → GET deliveries → 200, lista vacía (aún no hubo ping)."""
    created = _create_webhook(client, auth, monkeypatch)
    wh_id = created["id"]

    r = client.get(f"/api/v1/webhooks/{wh_id}/deliveries", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_webhook_deliveries_tras_ping(client, auth, monkeypatch):
    """Crear → ping → GET deliveries → lista con 1 entrada de tipo 'ping'."""
    created = _create_webhook(client, auth, monkeypatch)
    wh_id = created["id"]

    monkeypatch.setattr("api.routes.webhooks._validate_webhook_url", lambda url: url)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"

    with patch("api.routes.webhooks._post_pinned_webhook", return_value=mock_resp.status_code):
        r_ping = client.post(f"/api/v1/webhooks/{wh_id}/ping", headers=auth)
    assert r_ping.status_code == 200

    r = client.get(f"/api/v1/webhooks/{wh_id}/deliveries", headers=auth)
    assert r.status_code == 200, r.text
    deliveries = r.json()
    assert len(deliveries) == 1
    assert deliveries[0]["event_type"] == "ping"


# ---------------------------------------------------------------------------
# F13·C3.1 / S4.2: require_any_auth + tenencia por organización (sesión OAuth)
# ---------------------------------------------------------------------------


def test_session_sin_admin_ve_lo_suyo_y_no_lo_ajeno(client, auth, monkeypatch):
    """Una sesión sin ``is_admin`` gestiona los webhooks de SU organización.

    La afirmación anterior de este test —«sesión sin is_admin → 403»— describía
    el modelo previo a S4.2, en el que el webhook no tenía dueño: sin tenencia,
    la única barrera posible era el rol de instancia, y el efecto secundario era
    que un equipo no podía tener su canal de Slack sin pedírselo a un
    administrador. Con el webhook ya en una organización, esa barrera la da la
    tenencia — así que lo que hay que seguir garantizando, y es lo que se
    comprueba aquí, no es el 403 sino el aislamiento: el principal sin admin
    entra, pero NO ve el webhook del otro equipo.
    """
    creado = _create_webhook(client, auth, monkeypatch, name="del-admin")

    otro_id = _crear_usuario("miembro@test.com")
    app.dependency_overrides[require_any_auth] = _sesion(
        otro_id, "miembro@test.com", is_admin=False
    )
    resp = client.get("/api/v1/webhooks")

    assert resp.status_code == 200, resp.text
    assert resp.json() == [], "un miembro de otra organización no puede ver este webhook"

    # Y tampoco por el detalle, que es la vía por la que se escapan estos fallos.
    assert client.get(f"/api/v1/webhooks/{creado['id']}").status_code == 404


def test_la_vista_global_sigue_exigiendo_admin_de_instancia(client, api_db):
    """El 403 no desaparece del fichero: se muda a la ruta que sí lo merece.

    Al pasar la gestión por equipo de ``require_admin`` a
    ``require_organization``, el único test que comprobaba que un principal sin
    ``is_admin`` topa con una barrera de rol dejó de aplicar a ``GET
    /webhooks``. Pero ``GET /webhooks/global`` —la vista de ``/ops`` que enseña
    los webhooks de TODAS las organizaciones y los globales sin dueño— sigue
    siendo de administrador, y se había quedado sin ninguna prueba que lo
    fijara. Sin este test, degradar ese ``require_admin`` a
    ``require_any_auth`` pasaría el CI en verde y daría a cualquier usuario la
    lista de integraciones de todos los equipos.
    """
    otro_id = _crear_usuario("sin-admin@test.com")
    app.dependency_overrides[require_any_auth] = _sesion(
        otro_id, "sin-admin@test.com", is_admin=False
    )
    assert client.get("/api/v1/webhooks/global").status_code == 403

    app.dependency_overrides[require_any_auth] = _sesion(
        _crear_usuario("otro-admin@test.com"), "otro-admin@test.com", is_admin=True
    )
    assert client.get("/api/v1/webhooks/global").status_code == 200


def test_un_webhook_global_sin_dueno_no_entra_en_la_vista_de_ningun_equipo(client, api_db):
    """Las filas anteriores a v108 (``organization_id IS NULL``) son de instancia.

    Es la otra mitad del aislamiento de S4.2 y la que no cubre
    ``test_s4_webhooks_organizacion.py``, que compara dos organizaciones entre
    sí: un webhook sin dueño no pertenece a ninguna, así que no puede aparecer
    en la lista de un equipo ni abrirse por su detalle. Incluirlo daría a
    cualquier miembro de cualquier organización la integración de la instancia.
    """
    from db.repositories.webhooks import WebhookRepository

    global_id, _ = WebhookRepository().create(
        name="integracion-de-instancia",
        url=_WEBHOOK_URL,
        event_types=["*"],
        organization_id=None,
    )

    assert client.get("/api/v1/webhooks").json() == []
    assert client.get(f"/api/v1/webhooks/{global_id}").status_code == 404
    assert client.get(f"/api/v1/webhooks/{global_id}/deliveries").status_code == 404
    assert client.patch(f"/api/v1/webhooks/{global_id}", json={"active": False}).status_code == 404
    assert client.delete(f"/api/v1/webhooks/{global_id}").status_code == 404

    # Y sigue estando donde tiene que estar: la vista de /ops.
    assert [w["id"] for w in client.get("/api/v1/webhooks/global").json()] == [global_id]


def test_session_admin_can_list(client, api_db):
    """Sesión OAuth con is_admin=True → 200, igual que una API key con scope '*'."""
    resp = client.get("/api/v1/webhooks")
    assert resp.status_code == 200
    assert resp.json() == []


def test_session_admin_can_create_with_watchlist_rule_matched_event(client, api_db, monkeypatch):
    """F12·C2c: 'watchlist_rule.matched' es un event_type válido al crear."""
    monkeypatch.setattr("api.routes.webhooks.validate_outbound_url", lambda url, **_: url)
    resp = client.post(
        "/api/v1/webhooks",
        json={"name": "hook", "url": _WEBHOOK_URL, "event_types": ["watchlist_rule.matched"]},
    )
    assert resp.status_code == 201, resp.text


def test_webhook_deliveries_no_existe(client, auth):
    """GET /99999/deliveries → 404."""
    r = client.get("/api/v1/webhooks/99999/deliveries", headers=auth)
    assert r.status_code == 404
