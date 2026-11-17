"""Asignaciones y comentarios por email, según preferencia del usuario (S4.6).

Integración (``tmp_db``). ``immediate`` sale en la pasada siguiente del
despachador, ``daily`` se agrupa en el digest y ``off`` no escribe nada — que es
la única forma de que «desactivado» signifique lo que dice: una fila encolada
acaba entregándose tarde o temprano.
"""

from __future__ import annotations

import pytest

from db.events import append_domain_event
from services.notifications import modo_email_de


def _preferencia(user_key: str, event_type: str, modo: str) -> None:
    """Siembra la preferencia por SQL: ningún código de la app la escribe hoy.

    El escritor (``set_modo_email``) se retiró sin llamadores; lo que se prueba
    aquí es que el despachador obedece la fila si existe.
    """
    from db.database import connect, now_utc_iso

    with connect() as c:
        c.execute(
            "INSERT INTO user_event_prefs (user_key, event_type, modo, updated_at) "
            "VALUES (%s, %s, %s, %s)",
            (user_key, event_type, modo, now_utc_iso()),
        )


def _usuario(email: str) -> tuple[int, int, str]:
    """Crea usuario + organización personal. Devuelve ``(user_id, org_id, user_key)``."""
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user
    from shared.identity import user_key_from_email

    user_id = create_user(
        email=email,
        password_hash="test-hash",  # pragma: allowlist secret
        display_name=email.split("@")[0],
    )
    org_id = int(OrganizationRepository().ensure_personal_organization(user_id)["id"])
    return user_id, org_id, user_key_from_email(email, user_id)


def _evento_asignacion(*, org_id: int, responsable: int, actor: int) -> int:
    return append_domain_event(
        "pursuit.assigned",
        1,
        "pursuit",
        {
            "pursuit_id": 1,
            "licitacion_id": "S4-ASIGNACION",
            "responsible_user_id": responsable,
            "actor_user_id": actor,
            "titulo": "Migración SAP",
        },
        organization_id=org_id,
        actor_id=actor,
    )


@pytest.fixture()
def correos(monkeypatch):
    """Captura los envíos en vez de tocar SMTP."""
    enviados: list[dict[str, str]] = []

    def _enviar(*, to_addr: str, subject: str, texto: str, html: str) -> bool:
        enviados.append({"to": to_addr, "subject": subject, "texto": texto, "html": html})
        return True

    monkeypatch.setattr("observability.alerts.enviar_email_transaccional", _enviar)
    return enviados


def _digests_pendientes() -> list[dict[str, object]]:
    from db.database import connect_read
    from db.repositories.base import rows_to_dicts

    with connect_read() as c:
        return rows_to_dicts(c.execute("SELECT * FROM pending_digests"))


# ── Preferencia ──────────────────────────────────────────────────────────────


def test_los_defectos_distinguen_asignacion_de_comentario(tmp_db):
    """Que te asignen algo es una acción pendiente; un comentario es contexto.

    El correo por comentario que llega al instante es el que hace que la gente
    desactive todos los avisos del producto.
    """
    assert modo_email_de("uk-nueva", "pursuit.assigned") == "immediate"
    assert modo_email_de("uk-nueva", "pursuit.commented") == "daily"


def test_la_fila_guardada_gana_al_defecto(tmp_db):
    _preferencia("uk-1", "pursuit.assigned", "off")
    assert modo_email_de("uk-1", "pursuit.assigned") == "off"


def test_un_modo_desconocido_en_la_fila_cae_al_defecto(tmp_db):
    _preferencia("uk-1", "pursuit.assigned", "cuando-me-apetezca")
    assert modo_email_de("uk-1", "pursuit.assigned") == "immediate"


def test_los_avisos_de_lo_seguido_van_al_digest_diario_por_defecto(tmp_db):
    """Un cambio de plazo es contexto, no una acción inmediata: por defecto
    sale en el correo de la mañana, no al instante."""
    for tipo in ("licitacion.cambiada", "licitacion.documento_nuevo", "licitacion.recurso"):
        assert modo_email_de("uk-nueva", tipo) == "daily"


# ── Entrega ──────────────────────────────────────────────────────────────────


def test_immediate_sale_en_la_siguiente_pasada_del_despachador(tmp_db, correos):
    from scheduler.jobs import event_dispatch

    actor, org_id, _ = _usuario("s4-actor@example.test")
    responsable, _, uk_resp = _usuario("s4-responsable@example.test")
    _preferencia(uk_resp, "pursuit.assigned", "immediate")
    _evento_asignacion(org_id=org_id, responsable=responsable, actor=actor)

    resultado = event_dispatch.dispatch_pending()

    assert resultado.correos == 1
    assert correos[0]["to"] == "s4-responsable@example.test"
    assert "Migración SAP" in correos[0]["texto"]
    assert _digests_pendientes() == []


def test_daily_se_agrupa_en_el_digest_y_no_manda_correo_ya(tmp_db, correos):
    from scheduler.jobs import event_dispatch

    actor, org_id, _ = _usuario("s4-actor-d@example.test")
    responsable, _, uk_resp = _usuario("s4-responsable-d@example.test")
    _preferencia(uk_resp, "pursuit.assigned", "daily")
    _evento_asignacion(org_id=org_id, responsable=responsable, actor=actor)

    resultado = event_dispatch.dispatch_pending()

    assert resultado.correos == 0
    assert correos == []
    encolados = _digests_pendientes()
    assert len(encolados) == 1
    assert encolados[0]["recipient_email"] == "s4-responsable-d@example.test"
    assert encolados[0]["frequency"] == "daily"


def test_off_no_escribe_en_pending_digests(tmp_db, correos):
    from scheduler.jobs import event_dispatch

    actor, org_id, _ = _usuario("s4-actor-off@example.test")
    responsable, _, uk_resp = _usuario("s4-responsable-off@example.test")
    _preferencia(uk_resp, "pursuit.assigned", "off")
    _evento_asignacion(org_id=org_id, responsable=responsable, actor=actor)

    event_dispatch.dispatch_pending()

    assert correos == []
    assert _digests_pendientes() == [], "una fila encolada acaba entregándose: `off` no encola"


def test_quien_se_asigna_a_si_mismo_no_recibe_email_ni_alerta(tmp_db, correos):
    from scheduler.jobs import event_dispatch
    from services.notifications import get_alerts_unread_count

    user_id, org_id, user_key = _usuario("s4-solo@example.test")
    _preferencia(user_key, "pursuit.assigned", "immediate")
    _evento_asignacion(org_id=org_id, responsable=user_id, actor=user_id)

    event_dispatch.dispatch_pending()

    assert correos == []
    assert _digests_pendientes() == []
    assert get_alerts_unread_count(organization_id=org_id, user_id=user_id) == 0


def test_el_comentario_avisa_a_los_destinatarios_menos_al_autor(tmp_db, correos):
    from scheduler.jobs import event_dispatch

    autor, org_id, _ = _usuario("s4-autor@example.test")
    otro, _, uk_otro = _usuario("s4-otro@example.test")
    _preferencia(uk_otro, "pursuit.commented", "immediate")

    append_domain_event(
        "pursuit.commented",
        1,
        "pursuit",
        {
            "pursuit_id": 1,
            "licitacion_id": "S4-COMENTARIO",
            "actor_user_id": autor,
            "destinatarios": [autor, otro],
        },
        organization_id=org_id,
        actor_id=autor,
    )

    event_dispatch.dispatch_pending()

    assert [c["to"] for c in correos] == ["s4-otro@example.test"]
