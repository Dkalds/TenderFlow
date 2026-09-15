"""Rotación del secret de un webhook y firma v2 contra Postgres (Ola 1 · Webhooks).

Integración (``client``/``api_db`` y ``tmp_db``). Complementa
``test_unit_webhook_firma_v2.py``, que fija el vector de firma sin BD: aquí lo
que se comprueba es lo que solo se ve con la fila de verdad — que el ``UPDATE``
de la rotación cambia lo que firma el despachador, que el sentinel con material
es lo que queda en la columna, que el aislamiento por organización se aplica a
la ruta nueva en las dos dimensiones (PR #271) y que el reintento lee el sello
de ``webhook_deliveries.created_at``.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from api.app import app
from api.routes.dual_auth import require_any_auth
from db.repositories.organizations import OrganizationRepository
from db.repositories.webhooks import WebhookRepository
from shared import crypto

_URL = "https://hooks.example.com/rotacion"
_CLAVE_MAESTRA = "clave-maestra-de-prueba-32-caracteres!!"  # pragma: allowlist secret


def _usuario(email: str) -> tuple[int, int]:
    """Usuario con su organización personal. Devuelve ``(user_id, org_id)``."""
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
    """La allowlist SSRF tiene sus propios tests; aquí solo estorbaría."""
    monkeypatch.setattr("api.routes.webhooks.validate_outbound_url", lambda url, **_: url)
    monkeypatch.setattr("db.webhooks.validate_outbound_url", lambda url, **_: None)
    yield
    app.dependency_overrides.clear()


def _crear(client, *, organization_id: int, event_types: list[str] | None = None) -> dict:
    respuesta = client.post(
        "/api/v1/webhooks",
        json={
            "name": "rotable",
            "url": _URL,
            "event_types": event_types or ["pursuit.*"],
            "organization_id": organization_id,
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _secret_columna(webhook_id: int) -> str:
    from db.database import connect_read

    with connect_read() as c:
        fila = c.execute("SELECT secret FROM webhooks WHERE id = %s", (webhook_id,)).fetchone()
    return str(fila[0])


# ── POST /webhooks/{id}/rotate-secret ────────────────────────────────────────


def test_rotar_devuelve_un_secret_nuevo_una_sola_vez(client, api_db):
    user_id, org_id = _usuario("rotar-ok@example.test")
    _como(user_id)
    creado = _crear(client, organization_id=org_id)
    anterior = creado["secret"]

    respuesta = client.post(f"/api/v1/webhooks/{creado['id']}/rotate-secret")
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()

    assert cuerpo["id"] == creado["id"]
    assert cuerpo["secret"] and cuerpo["secret"] != anterior
    datetime.fromisoformat(cuerpo["rotated_at"])  # ISO 8601 o lanza
    assert respuesta.headers["cache-control"] == "no-store", "lleva un secret: no se cachea"

    # El despachador firma desde ahora con el nuevo, y el anterior ya no existe.
    assert WebhookRepository().get_secret(creado["id"]) == cuerpo["secret"]
    assert _secret_columna(creado["id"]) != anterior

    # Y no se puede volver a leer por ninguna vista.
    detalle = client.get(f"/api/v1/webhooks/{creado['id']}").json()
    assert "secret" not in detalle


def test_cada_rotacion_da_un_secret_distinto(client, api_db):
    user_id, org_id = _usuario("rotar-dos-veces@example.test")
    _como(user_id)
    creado = _crear(client, organization_id=org_id)

    primero = client.post(f"/api/v1/webhooks/{creado['id']}/rotate-secret").json()["secret"]
    segundo = client.post(f"/api/v1/webhooks/{creado['id']}/rotate-secret").json()["secret"]
    assert primero != segundo
    assert WebhookRepository().get_secret(creado["id"]) == segundo


def test_rotar_un_webhook_inexistente_es_404(client, api_db):
    user_id, _ = _usuario("rotar-404@example.test")
    _como(user_id)
    assert client.post("/api/v1/webhooks/999999/rotate-secret").status_code == 404


def test_rotar_el_webhook_de_otra_organizacion_es_404_y_no_lo_toca(client, api_db):
    """El aislamiento se resuelve en el predicado, como en PATCH y DELETE."""
    user_a, org_a = _usuario("rotar-iso-a@example.test")
    user_b, _org_b = _usuario("rotar-iso-b@example.test")

    _como(user_a)
    creado = _crear(client, organization_id=org_a)
    columna_antes = _secret_columna(creado["id"])

    _como(user_b)
    assert client.post(f"/api/v1/webhooks/{creado['id']}/rotate-secret").status_code == 404
    assert _secret_columna(creado["id"]) == columna_antes, "un 404 no puede haber rotado nada"


def test_pedir_la_organizacion_de_otro_es_403(client, api_db):
    """El ámbito lo resuelve ``api/tenancy.py``: sin membresía, 403 antes de mirar la fila."""
    user_a, _org_a = _usuario("rotar-403-a@example.test")
    _user_b, org_b = _usuario("rotar-403-b@example.test")
    _como(user_a)
    respuesta = client.post("/api/v1/webhooks/1/rotate-secret", params={"organization_id": org_b})
    assert respuesta.status_code == 403


def test_un_viewer_de_la_organizacion_no_puede_rotar(client, api_db):
    """Rotar es escritura: mismo requisito de rol que PATCH y DELETE."""
    owner_id, _ = _usuario("rotar-owner@example.test")
    viewer_id, _ = _usuario("rotar-viewer@example.test")
    organizations = OrganizationRepository()
    org_id = int(organizations.create_organization("Equipo", owner_id)["id"])
    organizations.add_membership(org_id, viewer_id, "viewer")

    _como(owner_id)
    creado = _crear(client, organization_id=org_id)

    _como(viewer_id)
    respuesta = client.post(
        f"/api/v1/webhooks/{creado['id']}/rotate-secret", params={"organization_id": org_id}
    )
    assert respuesta.status_code == 403, respuesta.text


def test_la_rotacion_queda_en_auditoria(client, api_db):
    from db.audit import list_recent

    user_id, org_id = _usuario("rotar-audit@example.test")
    _como(user_id)
    creado = _crear(client, organization_id=org_id)

    assert client.post(f"/api/v1/webhooks/{creado['id']}/rotate-secret").status_code == 200

    entradas = list_recent(action="webhook.secret_rotated")
    assert len(entradas) == 1
    assert f"resource=webhook:{creado['id']}" in entradas[0]["detail"]
    assert "secret" not in entradas[0]["detail"].replace("secret_rotated", ""), (
        "el secret nuevo no puede quedar escrito en el registro de auditoría"
    )


# ── Lo que la rotación cambia de verdad: la firma de la siguiente entrega ────


@patch("db.webhooks.pinned_https_request")
def test_tras_rotar_las_entregas_salen_firmadas_con_el_nuevo(mock_post, client, api_db):
    import db.webhooks as wh

    user_id, org_id = _usuario("rotar-firma@example.test")
    _como(user_id)
    creado = _crear(client, organization_id=org_id, event_types=["*"])
    anterior = creado["secret"]
    nuevo = client.post(f"/api/v1/webhooks/{creado['id']}/rotate-secret").json()["secret"]

    mock_post.return_value = MagicMock(status_code=200)
    assert wh.trigger_event("watchlist_match", {"id": 1}) == 1

    llamada = mock_post.call_args
    cabeceras = llamada.kwargs["headers"]
    cuerpo = llamada.kwargs["body"]
    sello = int(cabeceras["X-Webhook-Timestamp"])
    con_nuevo = hmac.new(nuevo.encode(), f"{sello}.".encode() + cuerpo, hashlib.sha256).hexdigest()
    con_viejo = hmac.new(
        anterior.encode(), f"{sello}.".encode() + cuerpo, hashlib.sha256
    ).hexdigest()
    assert cabeceras["X-Webhook-Signature-V2"] == f"v2={con_nuevo}"
    assert cabeceras["X-Webhook-Signature-V2"] != f"v2={con_viejo}", "el anterior ya no firma"
    assert cabeceras["X-Webhook-Signature"] == f"sha256={crypto.firmar_webhook(nuevo, cuerpo)}"


def test_el_ping_sale_con_las_cabeceras_de_una_entrega_real(client, api_db, monkeypatch):
    """Es lo que permite probar la verificación v2 del receptor antes de activar."""
    user_id, org_id = _usuario("rotar-ping@example.test")
    _como(user_id)
    creado = _crear(client, organization_id=org_id)
    secret = creado["secret"]

    vistas: list[tuple[bytes, dict[str, str]]] = []

    def _post(url, payload, headers):
        vistas.append((payload, headers))
        return 200

    monkeypatch.setattr("api.routes.webhooks._post_pinned_webhook", _post)
    assert client.post(f"/api/v1/webhooks/{creado['id']}/ping").json()["success"] is True

    cuerpo, cabeceras = vistas[0]
    sello = int(cabeceras["X-Webhook-Timestamp"])
    assert cabeceras["X-Webhook-Signature-V2"] == (
        f"v2={crypto.firmar_webhook_v2(secret, sello, cuerpo)}"
    )
    assert cabeceras["X-Webhook-Signature"] == f"sha256={crypto.firmar_webhook(secret, cuerpo)}"


# ── Repositorio: qué queda en la columna ─────────────────────────────────────


def test_con_clave_maestra_la_rotacion_guarda_material_y_no_el_secret(tmp_db):
    repo = WebhookRepository()
    with patch("db.repositories.webhooks._get_webhook_master_key", return_value=_CLAVE_MAESTRA):
        webhook_id, inicial = repo.create(name="h", url=_URL, event_types=["*"])
        assert _secret_columna(webhook_id) == crypto.DERIVED_SECRET_SENTINEL

        rotado = repo.rotate_secret(webhook_id)
        assert rotado is not None
        secret, _rotated_at = rotado

        columna = _secret_columna(webhook_id)
        assert columna.startswith(crypto.DERIVED_SECRET_SENTINEL_V2_PREFIX)
        assert secret not in columna, "la columna no puede contener nada firmable"
        assert secret != inicial
        assert secret == crypto.resolve_derived_secret(_CLAVE_MAESTRA, webhook_id, columna)
        assert repo.get_secret(webhook_id) == secret

    # Y `db/webhooks.py` —el otro resolutor— llega al mismo secreto.
    import db.webhooks as wh

    with patch("db.webhooks._get_webhook_master_key", return_value=_CLAVE_MAESTRA):
        assert wh._resolve_secret(webhook_id, columna) == secret


def test_un_webhook_legacy_sale_de_la_rotacion_derivado(tmp_db):
    """La «rotación manual» que RFC 049 dejaba pendiente para los secrets en claro."""
    repo = WebhookRepository()
    with patch("db.repositories.webhooks._get_webhook_master_key", return_value=""):
        webhook_id, en_claro = repo.create(name="legacy", url=_URL, event_types=["*"])
    assert _secret_columna(webhook_id) == en_claro, "sin clave maestra se guarda en claro"

    with patch("db.repositories.webhooks._get_webhook_master_key", return_value=_CLAVE_MAESTRA):
        rotado = repo.rotate_secret(webhook_id)
        assert rotado is not None
        assert _secret_columna(webhook_id).startswith(crypto.DERIVED_SECRET_SENTINEL_V2_PREFIX)
        assert repo.get_secret(webhook_id) == rotado[0] != en_claro


def test_rotar_fuera_de_la_organizacion_no_encuentra_la_fila(tmp_db):
    repo = WebhookRepository()
    webhook_id, _ = repo.create(name="h", url=_URL, event_types=["*"], organization_id=11)
    assert repo.rotate_secret(webhook_id, organization_id=12) is None
    assert repo.rotate_secret(999_999) is None
    assert repo.rotate_secret(webhook_id, organization_id=11) is not None


# ── Reintento: el sello se lee de la fila de la entrega ──────────────────────


@patch("db.webhooks.pinned_https_request")
def test_el_reintento_reenvia_el_sello_guardado_en_la_entrega(mock_post, tmp_db):
    """De extremo a extremo por Postgres: `trigger_event` escribe `created_at`
    con el instante que firmó, `pendientes_de_reintento` lo trae y `reenviar`
    lo vuelve a poner en la cabecera. Sin la columna en el SELECT, el reintento
    caería al `timestamp` del cuerpo — que en el formato `json` coincide, y por
    eso este test comprueba además que la fila lo guarda."""
    import db.webhooks as wh
    from db.database import connect_read
    from db.repositories.webhooks import pendientes_de_reintento

    WebhookRepository().create(name="caido", url=_URL, event_types=["*"])

    mock_post.return_value = MagicMock(status_code=503)
    assert wh.trigger_event("watchlist_match", {"id": 1}) == 0
    primera = mock_post.call_args.kwargs["headers"]

    pendientes = pendientes_de_reintento(ahora="2999-01-01T00:00:00+00:00")
    assert len(pendientes) == 1
    entrega = pendientes[0]
    assert "created_at" in entrega
    assert crypto.segundos_unix(entrega["created_at"]) == int(primera["X-Webhook-Timestamp"])

    mock_post.return_value = MagicMock(status_code=200)
    assert wh.reenviar(entrega) is True
    segunda = mock_post.call_args.kwargs["headers"]

    assert segunda["X-Webhook-Timestamp"] == primera["X-Webhook-Timestamp"]
    assert segunda["X-Webhook-Signature-V2"] == primera["X-Webhook-Signature-V2"]
    assert segunda["X-Webhook-Delivery"] == primera["X-Webhook-Delivery"]

    with connect_read() as c:
        estado = c.execute(
            "SELECT estado, intentos FROM webhook_deliveries WHERE id = %s", (entrega["id"],)
        ).fetchone()
    assert tuple(estado) == ("delivered", 2)
