"""SQL del derecho al olvido, del de acceso y de la retención (``privacidad-logs-gdpr-*``).

Necesita Postgres (``tmp_db``). La lógica sin BD —orden de la cadena, 409 del
único owner, ficheros del export— está en ``tests/test_unit_gdpr_cadena.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from db.repositories.organizations import NOMBRE_ORGANIZACION_ELIMINADA, OrganizationRepository
from db.repositories.pursuit_comments import PursuitCommentRepository
from db.repositories.pursuits import PursuitRepository
from services.gdpr import anonymize_account, anonymize_user_data
from services.pursuit_comments import add_comment
from services.pursuits import create_pursuit
from shared.dto import PursuitCommentCreate, PursuitCreate


def _user(email: str, nombre: str | None = None) -> int:
    from db.users import create_user

    return create_user(
        email=email,
        password_hash="hash-de-prueba",  # pragma: allowlist secret
        display_name=nombre or email.split("@")[0],
    )


def _licitacion(db_mod, id_externo: str) -> None:
    with db_mod.connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, fecha_limite, fecha_extraccion) VALUES (%s, %s, %s, %s)",
            (id_externo, "Servicio SAP", "2026-12-01T12:00:00+00:00", "2026-07-30T10:00:00+00:00"),
        )


def _nombre_de(db_mod, organization_id: int) -> str:
    with db_mod.connect_read() as c:
        return str(
            c.execute(
                "SELECT name FROM organizations WHERE id = %s", (organization_id,)
            ).fetchone()[0]
        )


# ── gdpr-1 y gdpr-2: nombre de la personal y cadena del administrador ──────


def test_borrar_la_cuenta_renombra_la_organizacion_personal(tmp_db):
    db_mod, _ = tmp_db
    uid = _user("olvidada@example.test", "Ana Olvidada")
    personal = OrganizationRepository().ensure_personal_organization(uid)
    assert _nombre_de(db_mod, int(personal["id"])) == "Ana Olvidada"

    anonymize_user_data("clave", user_id=uid)

    assert _nombre_de(db_mod, int(personal["id"])) == NOMBRE_ORGANIZACION_ELIMINADA


def test_la_baja_del_panel_ejecuta_la_cadena_completa(tmp_db):
    db_mod, _ = tmp_db
    uid = _user("panel@example.test", "Pedro Panel")
    personal = OrganizationRepository().ensure_personal_organization(uid)

    anonymize_account(uid, "panel@example.test")

    with db_mod.connect_read() as c:
        usuario = c.execute(
            "SELECT email, display_name, password_hash FROM users WHERE id = %s", (uid,)
        ).fetchone()
        membresias = c.execute(
            "SELECT COUNT(*) FROM organization_memberships WHERE user_id = %s", (uid,)
        ).fetchone()[0]
    assert tuple(usuario) == (None, None, None)
    assert membresias == 0
    assert _nombre_de(db_mod, int(personal["id"])) == NOMBRE_ORGANIZACION_ELIMINADA


# ── gdpr-11: único owner ───────────────────────────────────────────────────


def test_solo_el_unico_owner_de_una_compartida_cuenta_como_huerfana(tmp_db):
    repo = OrganizationRepository()
    owner = _user("owner@example.test")
    otro = _user("otro@example.test")
    solo = int(repo.create_organization("Solo", owner)["id"])
    repo.ensure_personal_organization(owner)  # la personal no cuenta
    compartida = int(repo.create_organization("Compartida", owner)["id"])
    repo.add_membership(compartida, otro, "owner")

    assert repo.organizaciones_con_unico_owner(owner) == [solo]
    assert repo.organizaciones_con_unico_owner(otro) == []


# ── gdpr-4: export de quien ya no es miembro ───────────────────────────────


def test_el_export_de_un_ex_miembro_no_trae_el_estado_corporativo(tmp_db):
    db_mod, _ = tmp_db
    owner = _user("export-owner@example.test")
    ex = _user("export-ex@example.test")
    repo = OrganizationRepository()
    organization_id = int(repo.create_organization("Equipo", owner)["id"])
    repo.add_membership(organization_id, ex, "member")
    _licitacion(db_mod, "LIC-EXPORT-EXMIEMBRO")
    pursuit, _ = create_pursuit(
        ex,
        PursuitCreate(licitacion_id="LIC-EXPORT-EXMIEMBRO", organization_id=organization_id),
    )
    add_comment(
        ex,
        pursuit.id,
        PursuitCommentCreate(body="razón interna de la decisión"),
        organization_id=organization_id,
    )

    activo = PursuitRepository().export_personal_data(ex)
    comentarios_activo = PursuitCommentRepository().export_for_user(ex)
    assert activo["pursuits"][0]["status"] is not None
    assert comentarios_activo[0]["body"] == "razón interna de la decisión"

    with db_mod.connect() as conn:
        conn.execute(
            "UPDATE organization_memberships SET status = 'revoked' WHERE user_id = %s", (ex,)
        )

    saliente = PursuitRepository().export_personal_data(ex)
    (fila,) = saliente["pursuits"]
    assert fila["licitacion_id"] == "LIC-EXPORT-EXMIEMBRO"
    assert fila["created_by_user_id"] == ex
    assert "status" not in fila and "decision_reason" not in fila
    assert all(e["payload_json"] is None for e in saliente["pursuit_events"])
    (comentario,) = PursuitCommentRepository().export_for_user(ex)
    assert comentario["body"] is None and comentario["author_user_id"] == ex


# ── gdpr-6: retención de lo que faltaba ────────────────────────────────────


def test_la_retencion_purga_votos_invitaciones_caducadas_y_eventos_despachados(tmp_db):
    db_mod, _ = tmp_db
    from scheduler.retention import run_retention

    owner = _user("retencion@example.test")
    organization_id = int(OrganizationRepository().create_organization("Org", owner)["id"])
    viejo = (datetime.now(UTC) - timedelta(days=3000)).isoformat()
    reciente = datetime.now(UTC).isoformat()
    caducada = datetime.now(UTC) - timedelta(days=3000)
    vigente = datetime.now(UTC) + timedelta(days=7)
    with db_mod.connect() as c:
        for creado in (viejo, reciente):
            c.execute(
                "INSERT INTO asistente_feedback (pregunta_hash, modo, voto, created_at) "
                "VALUES ('h', 'pregunta', 'si', %s)",
                (creado,),
            )
        for correo, expira in (
            ("caducada@example.test", caducada),
            ("vigente@example.test", vigente),
        ):
            c.execute(
                "INSERT INTO organization_invitations "
                "(organization_id, email, role, token_hash, expires_at) "
                "VALUES (%s, %s, 'member', %s, %s)",
                (organization_id, correo, f"t-{correo}", expira),
            )
        for despachado, creado in ((viejo, viejo), (None, viejo), (reciente, reciente)):
            c.execute(
                "INSERT INTO domain_events "
                "(event_type, aggregate_id, aggregate_type, payload_json, created_at, "
                " dispatched_at) VALUES ('x.y', '1', 'x', '{}', %s, %s)",
                (creado, despachado),
            )

    resultado = run_retention(apply=True)

    assert resultado["asistente_feedback"] == 1
    assert resultado["organization_invitations"] == 1
    assert resultado["domain_events"] == 1  # el viejo SIN despachar es cola: se conserva
    with db_mod.connect_read() as c:
        assert c.execute("SELECT COUNT(*) FROM asistente_feedback").fetchone()[0] == 1
        assert c.execute("SELECT email FROM organization_invitations").fetchone()[0] == (
            "vigente@example.test"
        )
        assert c.execute("SELECT COUNT(*) FROM domain_events").fetchone()[0] == 2
        assert (
            c.execute("SELECT COUNT(*) FROM domain_events WHERE dispatched_at IS NULL").fetchone()[
                0
            ]
            == 1
        )


# ── gdpr-10: tope de filas de client_errors ────────────────────────────────


def test_client_errors_respeta_su_tope_sin_dejar_de_contar_los_conocidos(tmp_db, monkeypatch):
    import db.repositories.client_errors as client_errors

    monkeypatch.setattr(client_errors, "MAX_FILAS", 2)
    for mensaje in ("uno", "dos", "tres"):
        client_errors.registrar(mensaje=mensaje, ruta="/x", origen="onerror", build=None)
    client_errors.registrar(mensaje="uno", ruta="/x", origen="onerror", build="b2")

    filas = {f["mensaje"]: f for f in client_errors.listar()}
    assert set(filas) == {"uno", "dos"}  # "tres" no cabe
    assert filas["uno"]["ocurrencias"] == 2 and filas["uno"]["build"] == "b2"
