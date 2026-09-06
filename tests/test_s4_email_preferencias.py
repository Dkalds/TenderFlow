"""Asignaciones y comentarios por email, según preferencia del usuario (S4.6).

Integración (``tmp_db``). ``immediate`` sale en la pasada siguiente del
despachador, ``daily`` se agrupa en el digest y ``off`` no escribe nada — que es
la única forma de que «desactivado» signifique lo que dice: una fila encolada
acaba entregándose tarde o temprano.
"""

from __future__ import annotations

import pytest

from db.events import append_domain_event
from services.notifications import modo_email_de, preferencias_email, set_modo_email


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


def test_set_modo_email_es_idempotente_y_devuelve_el_modo(tmp_db):
    assert set_modo_email("uk-1", "pursuit.assigned", "off") == "off"
    assert set_modo_email("uk-1", "pursuit.assigned", "off") == "off"
    assert modo_email_de("uk-1", "pursuit.assigned") == "off"


def test_un_tipo_sin_preferencia_de_correo_se_rechaza(tmp_db):
    with pytest.raises(ValueError):
        set_modo_email("uk-1", "pursuit.created", "daily")


def test_un_modo_inventado_se_rechaza(tmp_db):
    with pytest.raises(ValueError):
        set_modo_email("uk-1", "pursuit.assigned", "cuando-me-apetezca")


def test_preferencias_email_solo_expone_los_tipos_personales(tmp_db):
    claves = set(preferencias_email("uk-1"))
    assert claves == {"pursuit.assigned", "pursuit.commented"}


# ── Entrega ──────────────────────────────────────────────────────────────────


def test_immediate_sale_en_la_siguiente_pasada_del_despachador(tmp_db, correos):
    from scheduler.jobs import event_dispatch

    actor, org_id, _ = _usuario("s4-actor@example.test")
    responsable, _, uk_resp = _usuario("s4-responsable@example.test")
    set_modo_email(uk_resp, "pursuit.assigned", "immediate")
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
    set_modo_email(uk_resp, "pursuit.assigned", "daily")
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
    set_modo_email(uk_resp, "pursuit.assigned", "off")
    _evento_asignacion(org_id=org_id, responsable=responsable, actor=actor)

    event_dispatch.dispatch_pending()

    assert correos == []
    assert _digests_pendientes() == [], "una fila encolada acaba entregándose: `off` no encola"


def test_quien_se_asigna_a_si_mismo_no_recibe_email_ni_alerta(tmp_db, correos):
    from scheduler.jobs import event_dispatch
    from services.notifications import get_alerts_unread_count

    user_id, org_id, user_key = _usuario("s4-solo@example.test")
    set_modo_email(user_key, "pursuit.assigned", "immediate")
    _evento_asignacion(org_id=org_id, responsable=user_id, actor=user_id)

    event_dispatch.dispatch_pending()

    assert correos == []
    assert _digests_pendientes() == []
    assert get_alerts_unread_count(user_key, organization_id=org_id) == 0


def test_el_comentario_avisa_a_los_destinatarios_menos_al_autor(tmp_db, correos):
    from scheduler.jobs import event_dispatch

    autor, org_id, _ = _usuario("s4-autor@example.test")
    otro, _, uk_otro = _usuario("s4-otro@example.test")
    set_modo_email(uk_otro, "pursuit.commented", "immediate")

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
