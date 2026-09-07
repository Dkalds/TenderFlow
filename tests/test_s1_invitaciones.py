"""Invitaciones a correos sin cuenta (S1.1).

Hasta 2026-09, incorporar a alguien exigía que se hubiera registrado antes por
su cuenta: `add_member_by_email` respondía 404 para un correo desconocido. Estos
tests fijan el comportamiento nuevo y, sobre todo, sus límites — siete días,
un solo uso, solo owner/admin, y el rastro que la persona invitada tiene
derecho a exportar y a que se le borre.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from api.routes.dual_auth import require_any_auth
from db.repositories.organizations import OrganizationRepository
from services import organizations as svc

# ── Token: firma y estado derivado (sin BD) ─────────────────────────────────


def test_el_token_lleva_firma_con_kid_y_se_verifica():
    token, digest = svc._issue_invitation_token()

    assert svc._invitation_signature_valid(token)
    assert digest == svc._invitation_token_hash(token)
    # `{nonce}.{kid}.{sig}`: sin el kid no sobreviviría a una rotación de clave.
    assert token.count(".") >= 2


def test_un_token_manipulado_no_verifica():
    token, _ = svc._issue_invitation_token()
    nonce, _, firma = token.partition(".")

    assert not svc._invitation_signature_valid(f"{nonce}x.{firma}")
    assert not svc._invitation_signature_valid("sin-separador")
    assert not svc._invitation_signature_valid("")


@pytest.mark.parametrize(
    ("fila", "esperado"),
    [
        ({"expires_at": datetime.now(UTC) + timedelta(days=1)}, "invited"),
        ({"expires_at": datetime.now(UTC) - timedelta(seconds=1)}, "expired"),
        (
            {"expires_at": datetime.now(UTC) + timedelta(days=1), "revoked_at": datetime.now(UTC)},
            "revoked",
        ),
        (
            {"expires_at": datetime.now(UTC) - timedelta(days=9), "accepted_at": datetime.now(UTC)},
            "accepted",
        ),
    ],
)
def test_el_estado_se_deriva_de_las_marcas_de_tiempo(fila, esperado):
    """`expired` no se persiste: se calcula al mostrarlo. Ver el DTO."""
    assert svc._invitation_status(fila) == esperado


# ── Helpers de integración ──────────────────────────────────────────────────


def _user(email: str, *, display_name: str | None = None) -> int:
    from db.users import create_user

    return create_user(
        email=email,
        password_hash="test-hash",  # pragma: allowlist secret
        display_name=display_name,
    )


@pytest.fixture()
def correos(monkeypatch) -> list[dict[str, str]]:
    """Captura los envíos en vez de mandarlos, y guarda el token bruto.

    El token no se puede leer de la BD (solo vive su SHA-256), así que esta es
    la única forma de ejercitar el canje como lo haría quien recibe el correo.
    """
    enviados: list[dict[str, str]] = []

    def _fake(email: str, organization_name: str, token: str) -> bool:
        enviados.append({"email": email, "organization": organization_name, "token": token})
        return True

    monkeypatch.setattr(svc, "_send_invitation_email", _fake)
    return enviados


def _organizacion(owner: int, nombre: str = "Equipo con invitaciones") -> int:
    return int(OrganizationRepository().create_organization(nombre, owner)["id"])


# ── Crear invitación ────────────────────────────────────────────────────────


def test_invitar_a_un_correo_sin_cuenta_crea_la_fila_pendiente(tmp_db, correos):
    _db_mod, _ = tmp_db
    owner = _user("owner-invita@example.test")
    organization_id = _organizacion(owner)

    resultado = svc.invite_member_by_email(
        owner, organization_id, "Sin-Cuenta@Example.TEST", "member"
    )

    assert resultado.status == "invited"
    assert resultado.email == "sin-cuenta@example.test"
    assert resultado.role == "member"
    assert resultado.invited_by_user_id == owner
    # Siete días exactos, con margen para el tiempo de ejecución del test.
    restante = resultado.expires_at - datetime.now(UTC)
    assert timedelta(days=6, hours=23) < restante <= timedelta(days=7)
    assert correos[0]["email"] == "Sin-Cuenta@Example.TEST"


def test_invitar_a_un_correo_con_cuenta_sigue_dando_de_alta_en_el_acto(tmp_db, correos):
    """La rama que ya funcionaba no cambia: membresía activa y sin correo."""
    _db_mod, _ = tmp_db
    owner = _user("owner-directo@example.test")
    existente = _user("ya-registrada@example.test", display_name="Ya Registrada")
    organization_id = _organizacion(owner, "Equipo directo")

    resultado = svc.invite_member_by_email(
        owner, organization_id, "ya-registrada@example.test", "member"
    )

    assert resultado.status == "active"
    assert resultado.user_id == existente
    assert correos == []


def test_un_member_no_puede_invitar(tmp_db, correos):
    _db_mod, _ = tmp_db
    owner = _user("owner-permisos@example.test")
    miembro = _user("miembro-permisos@example.test")
    organization_id = _organizacion(owner, "Equipo permisos")
    OrganizationRepository().add_membership(organization_id, miembro, "member")

    with pytest.raises(svc.OrganizationPermissionError):
        svc.invite_member_by_email(miembro, organization_id, "otra@example.test", "member")

    assert OrganizationRepository().list_invitations(organization_id) == []
    assert correos == []


def test_reinvitar_al_mismo_correo_sustituye_la_pendiente(tmp_db, correos):
    """Sin esto, el único parcial de v104 haría fallar el segundo intento."""
    _db_mod, _ = tmp_db
    owner = _user("owner-reinvita@example.test")
    organization_id = _organizacion(owner, "Equipo reinvita")

    primera = svc.create_invitation(owner, organization_id, "repe@example.test", "member")
    segunda = svc.create_invitation(owner, organization_id, "repe@example.test", "viewer")

    pendientes = OrganizationRepository().list_invitations(organization_id)
    assert [fila["id"] for fila in pendientes] == [segunda.id]
    assert segunda.id != primera.id
    # El token viejo deja de valer en el acto.
    assert not svc._repo.get_pending_invitation_by_token(
        svc._invitation_token_hash(correos[0]["token"])
    )


# ── Aceptar: por correo (registro/OAuth) y por token ────────────────────────


def test_al_registrarse_con_ese_correo_la_membresia_pasa_a_active(tmp_db, correos):
    _db_mod, _ = tmp_db
    owner = _user("owner-registro@example.test")
    organization_id = _organizacion(owner, "Equipo registro")
    svc.invite_member_by_email(owner, organization_id, "nueva@example.test", "viewer")

    nueva = _user("nueva@example.test")
    activadas = svc.accept_invitations_for_email(nueva, "Nueva@example.test")

    assert activadas == 1
    membresia = OrganizationRepository().get_active_membership(organization_id, nueva)
    assert membresia is not None
    assert membresia["role"] == "viewer"
    # …y la organización ya aparece en GET /organizations.
    assert organization_id in [org.id for org in svc.list_organizations(nueva)]


def test_la_invitacion_es_de_un_solo_uso(tmp_db, correos):
    _db_mod, _ = tmp_db
    owner = _user("owner-unuso@example.test")
    organization_id = _organizacion(owner, "Equipo un uso")
    svc.invite_member_by_email(owner, organization_id, "unavez@example.test", "member")
    invitada = _user("unavez@example.test")
    token = correos[0]["token"]

    svc.accept_invitation_token(invitada, "unavez@example.test", token)

    with pytest.raises(svc.OrganizationInvitationNotFoundError):
        svc.accept_invitation_token(invitada, "unavez@example.test", token)


def test_un_token_caducado_no_se_puede_canjear(tmp_db, correos):
    _db_mod, _ = tmp_db
    owner = _user("owner-caduca@example.test")
    organization_id = _organizacion(owner, "Equipo caduca")
    invitacion = svc.invite_member_by_email(owner, organization_id, "tarde@example.test", "member")
    invitada = _user("tarde@example.test")

    from db.database import connect

    with connect() as conn:
        conn.execute(
            "UPDATE organization_invitations SET expires_at = %s WHERE id = %s",
            (datetime.now(UTC) - timedelta(seconds=1), invitacion.id),
        )

    with pytest.raises(svc.OrganizationInvitationNotFoundError):
        svc.accept_invitation_token(invitada, "tarde@example.test", correos[0]["token"])
    # Tampoco por el camino del correo: caducada es caducada.
    assert svc.accept_invitations_for_email(invitada, "tarde@example.test") == 0


def test_el_token_solo_vale_para_el_correo_al_que_se_envio(tmp_db, correos):
    _db_mod, _ = tmp_db
    owner = _user("owner-ajeno@example.test")
    organization_id = _organizacion(owner, "Equipo ajeno")
    svc.invite_member_by_email(owner, organization_id, "destinataria@example.test", "member")
    intrusa = _user("intrusa@example.test")

    with pytest.raises(svc.OrganizationPermissionError):
        svc.accept_invitation_token(intrusa, "intrusa@example.test", correos[0]["token"])

    assert OrganizationRepository().get_active_membership(organization_id, intrusa) is None


def test_una_invitacion_revocada_ya_no_se_puede_canjear(tmp_db, correos):
    _db_mod, _ = tmp_db
    owner = _user("owner-revoca@example.test")
    organization_id = _organizacion(owner, "Equipo revoca")
    invitacion = svc.invite_member_by_email(
        owner, organization_id, "revocada@example.test", "member"
    )
    invitada = _user("revocada@example.test")

    svc.revoke_invitation(owner, organization_id, invitacion.id)

    with pytest.raises(svc.OrganizationInvitationNotFoundError):
        svc.accept_invitation_token(invitada, "revocada@example.test", correos[0]["token"])
    assert svc.accept_invitations_for_email(invitada, "revocada@example.test") == 0
    # Revocar dos veces no es idempotente en silencio: la segunda avisa.
    with pytest.raises(svc.OrganizationInvitationNotFoundError):
        svc.revoke_invitation(owner, organization_id, invitacion.id)


def test_reenviar_emite_un_token_nuevo_e_invalida_el_anterior(tmp_db, correos):
    _db_mod, _ = tmp_db
    owner = _user("owner-reenvia@example.test")
    organization_id = _organizacion(owner, "Equipo reenvía")
    invitacion = svc.invite_member_by_email(
        owner, organization_id, "reenviada@example.test", "member"
    )
    invitada = _user("reenviada@example.test")

    svc.resend_invitation(owner, organization_id, invitacion.id)

    assert len(correos) == 2
    assert correos[0]["token"] != correos[1]["token"]
    with pytest.raises(svc.OrganizationInvitationNotFoundError):
        svc.accept_invitation_token(invitada, "reenviada@example.test", correos[0]["token"])
    organizacion = svc.accept_invitation_token(
        invitada, "reenviada@example.test", correos[1]["token"]
    )
    assert organizacion.id == organization_id


def test_aceptar_no_degrada_al_owner(tmp_db, correos):
    """Una invitación con rol menor no puede quitarle la propiedad a nadie."""
    _db_mod, _ = tmp_db
    owner = _user("owner-protegido@example.test")
    organization_id = _organizacion(owner, "Equipo protegido")
    svc.create_invitation(owner, organization_id, "owner-protegido@example.test", "viewer")

    svc.accept_invitations_for_email(owner, "owner-protegido@example.test")

    membresia = OrganizationRepository().get_active_membership(organization_id, owner)
    assert membresia is not None
    assert membresia["role"] == "owner"


# ── GDPR ────────────────────────────────────────────────────────────────────


def test_el_export_gdpr_del_invitado_incluye_la_invitacion(tmp_db, correos):
    _db_mod, _ = tmp_db
    owner = _user("owner-gdpr@example.test")
    organization_id = _organizacion(owner, "Equipo GDPR")
    svc.invite_member_by_email(owner, organization_id, "invitada-gdpr@example.test", "member")
    invitada = _user("invitada-gdpr@example.test")

    from services.gdpr import export_collaboration_data

    exportado = export_collaboration_data(invitada)

    filas = exportado["organization_memberships"]
    pendientes = [fila for fila in filas if fila["status"] == "invited"]
    assert len(pendientes) == 1
    assert pendientes[0]["organization_id"] == organization_id
    assert pendientes[0]["organization_name"] == "Equipo GDPR"
    assert pendientes[0]["role"] == "member"


def test_el_borrado_gdpr_anonimiza_la_invitacion(tmp_db, correos):
    _db_mod, _ = tmp_db
    owner = _user("owner-olvido@example.test")
    organization_id = _organizacion(owner, "Equipo olvido")
    svc.invite_member_by_email(owner, organization_id, "olvidada@example.test", "member")
    invitada = _user("olvidada@example.test")

    OrganizationRepository().remove_memberships_for_user(invitada)

    from db.database import connect_read

    with connect_read() as conn:
        filas = conn.execute(
            "SELECT email, revoked_at FROM organization_invitations WHERE organization_id = %s",
            (organization_id,),
        ).fetchall()
    assert len(filas) == 1
    # La fila sobrevive (la organización sabe que invitó a alguien) pero el
    # correo, que es el dato personal, ya no está.
    assert filas[0][0] == ""
    assert filas[0][1] is not None
    # Y el enlace deja de servir para nada.
    assert not svc._repo.get_pending_invitation_by_token(
        svc._invitation_token_hash(correos[0]["token"])
    )


# ── Contrato HTTP ───────────────────────────────────────────────────────────
#
# Aquí los correos invitados son `@example.com`, no `@example.test` como en el
# resto del fichero. No es cosmético: el cuerpo de `POST .../members` lo valida
# `OrganizationMemberInvite.email`, que es `EmailStr`, y `email-validator`
# rechaza los TLD de uso especial de la RFC 6761 (`test`, `local`, `invalid`,
# `localhost`) porque a ninguno se le puede entregar un correo — y una
# invitación que no se puede entregar no sirve para nada. Por debajo de la API
# nadie pasa por ese validador, así que los tests de servicio siguen usando
# `.test`. La misma distinción está en tests/test_auth_register.py.


def _como(user_id: int) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "email": None,
        "auth_method": "session",
        "user_key": "s1-invitaciones-test",
    }


def test_api_invitar_a_un_correo_sin_cuenta_devuelve_201_y_la_invitacion(client, api_db, correos):
    from api.app import app

    owner = _user("owner-api@example.test")
    organization_id = _organizacion(owner, "Equipo API invitaciones")
    app.dependency_overrides[require_any_auth] = lambda: _como(owner)
    try:
        creada = client.post(
            f"/api/v1/organizations/{organization_id}/members",
            json={"email": "sin-cuenta-api@example.com", "role": "member"},
        )
        assert creada.status_code == 201, creada.text
        cuerpo = creada.json()
        assert cuerpo["status"] == "invited"
        assert cuerpo["email"] == "sin-cuenta-api@example.com"
        # El token nunca sale en la respuesta: solo viaja en el correo.
        assert "token" not in cuerpo

        listadas = client.get(f"/api/v1/organizations/{organization_id}/invitations")
        assert listadas.status_code == 200
        assert [fila["id"] for fila in listadas.json()] == [cuerpo["id"]]

        reenviada = client.post(
            f"/api/v1/organizations/{organization_id}/invitations/{cuerpo['id']}/resend",
        )
        assert reenviada.status_code == 200

        revocada = client.delete(
            f"/api/v1/organizations/{organization_id}/invitations/{reenviada.json()['id']}",
        )
        assert revocada.status_code == 200
        assert client.get(f"/api/v1/organizations/{organization_id}/invitations").json() == []
    finally:
        app.dependency_overrides.pop(require_any_auth, None)


def test_api_un_member_no_ve_ni_crea_invitaciones(client, api_db, correos):
    from api.app import app

    owner = _user("owner-api-403@example.test")
    miembro = _user("miembro-api-403@example.test")
    organization_id = _organizacion(owner, "Equipo API 403")
    OrganizationRepository().add_membership(organization_id, miembro, "member")
    app.dependency_overrides[require_any_auth] = lambda: _como(miembro)
    try:
        assert (
            client.post(
                f"/api/v1/organizations/{organization_id}/members",
                json={"email": "otra-api@example.com", "role": "member"},
            ).status_code
            == 403
        )
        assert client.get(f"/api/v1/organizations/{organization_id}/invitations").status_code == 403
    finally:
        app.dependency_overrides.pop(require_any_auth, None)


def test_api_un_correo_no_entregable_se_rechaza_antes_de_crear_nada(client, api_db, correos):
    """422 de Pydantic, sin fila ni envío: invitar a un `.test` no lleva a ninguna parte.

    Lo que se fija es que el rechazo no deja rastro: ni invitación pendiente ni
    correo enviado, porque `EmailStr` corta la petición antes de que el handler
    llegue a crear nada. Ese «antes» es también el motivo de que
    `test_api_un_member_no_ve_ni_crea_invitaciones` tenga que invitar a un
    dominio entregable: con uno reservado la respuesta sería 422 y el 403 de
    permisos no llegaría a comprobarse nunca. Sin un test que lo diga, el 422
    solo se descubre depurando una respuesta sin cuerpo legible.
    """
    from api.app import app

    owner = _user("owner-api-422@example.test")
    organization_id = _organizacion(owner, "Equipo API 422")
    app.dependency_overrides[require_any_auth] = lambda: _como(owner)
    try:
        respuesta = client.post(
            f"/api/v1/organizations/{organization_id}/members",
            json={"email": "nadie@example.test", "role": "member"},
        )
        assert respuesta.status_code == 422
        assert client.get(f"/api/v1/organizations/{organization_id}/invitations").json() == []
    finally:
        app.dependency_overrides.pop(require_any_auth, None)
    assert correos == []


def test_api_canjear_el_token_devuelve_la_organizacion(client, api_db, correos):
    from api.app import app

    owner = _user("owner-api-canje@example.test")
    organization_id = _organizacion(owner, "Equipo API canje")
    app.dependency_overrides[require_any_auth] = lambda: _como(owner)
    try:
        invitacion = client.post(
            f"/api/v1/organizations/{organization_id}/members",
            json={"email": "canje@example.com", "role": "member"},
        )
        assert invitacion.status_code == 201, invitacion.text
    finally:
        app.dependency_overrides.pop(require_any_auth, None)

    invitada = _user("canje@example.com")
    principal = {**_como(invitada), "email": "canje@example.com"}
    app.dependency_overrides[require_any_auth] = lambda: principal
    try:
        aceptada = client.post(
            "/api/v1/organizations/invitations/accept",
            json={"token": correos[0]["token"]},
        )
        assert aceptada.status_code == 200
        assert aceptada.json()["id"] == organization_id

        # Un token ya usado responde 404, no 500.
        repetida = client.post(
            "/api/v1/organizations/invitations/accept",
            json={"token": correos[0]["token"]},
        )
        assert repetida.status_code == 404
    finally:
        app.dependency_overrides.pop(require_any_auth, None)
