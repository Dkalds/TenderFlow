"""Alertas de cambio en expedientes seguidos (S4.5).

Integración (``tmp_db``). ``licitaciones_history`` guardaba ``changed_fields``
desde hacía meses y solo lo leía la derivación de eventos de contrato: nadie
avisaba a quien seguía el expediente de que le habían movido el plazo.

Los tres cortes que definen «avisar bien» tienen aquí un test cada uno:
seguido → aviso con campo y valores; no seguido → nada; re-ingesta sin cambio
real → nada.
"""

from __future__ import annotations

import json

import pytest

from db.events import count_pending_events, pending_events
from services.contract_events import derive_new_events

_ID = "S4-CAMBIO-1"
_ID_NO_SEGUIDO = "S4-CAMBIO-SIN-SEGUIDOR"


def _lic(id_externo: str, *, fecha_limite: str) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, estado, fecha_limite, fecha_publicacion, fecha_extraccion) "
            "VALUES (%s, %s, 'PUB', %s, '2026-09-01', '2026-09-01')",
            (id_externo, f"Expediente {id_externo}", fecha_limite),
        )


def _historial(id_externo: str, *, snapshot: dict[str, object], changed: str) -> None:
    """Escribe la fila de historial que el upsert habría dejado tras un cambio."""
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones_history "
            "(id_externo, captured_at, snapshot_json, changed_fields) "
            "VALUES (%s, %s, %s, %s)",
            (id_externo, "2026-09-05T10:00:00+00:00", json.dumps(snapshot), changed),
        )


def _seguir(id_externo: str, *, user_key: str = "uk-seguidor", organization_id: int = 1) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO watchlist_items (user_key, id_externo, created_at, organization_id) "
            "VALUES (%s, %s, '2026-09-01', %s)",
            (user_key, id_externo, organization_id),
        )


@pytest.fixture()
def base(tmp_db):
    _lic(_ID, fecha_limite="2026-12-01")
    _lic(_ID_NO_SEGUIDO, fecha_limite="2026-12-01")
    return tmp_db


def _eventos_de_cambio() -> list[dict[str, object]]:
    return [e for e in pending_events() if e["event_type"] == "licitacion.cambiada"]


def test_un_cambio_de_fecha_limite_en_expediente_seguido_genera_evento(base):
    _seguir(_ID)
    _historial(_ID, snapshot={"fecha_limite": "2026-11-01"}, changed="fecha_limite")

    derive_new_events()

    eventos = _eventos_de_cambio()
    assert len(eventos) == 1
    payload = eventos[0]["payload"]
    assert payload["id_externo"] == _ID
    assert payload["changed_fields"] == ["fecha_limite"]
    assert payload["valores"]["fecha_limite"] == {
        "antes": "2026-11-01",
        "despues": "2026-12-01",
    }
    assert {"user_key": "uk-seguidor", "organization_id": 1} in payload["seguidores"]


def test_el_despachador_escribe_la_alerta_in_app_con_campo_y_valores(base):
    """Criterio de S4.5: el seguidor ve QUÉ cambió y a QUÉ, no un «algo cambió»."""
    from scheduler.jobs import event_dispatch
    from services.notifications import get_user_alerts

    _seguir(_ID)
    _historial(_ID, snapshot={"fecha_limite": "2026-11-01"}, changed="fecha_limite")
    derive_new_events()
    event_dispatch.dispatch_pending()

    alertas = get_user_alerts("uk-seguidor", organization_id=1)
    assert len(alertas) == 1
    assert alertas[0]["licitacion_id"] == _ID
    assert "fecha_limite" in alertas[0]["body"]
    assert "2026-11-01" in alertas[0]["body"]
    assert "2026-12-01" in alertas[0]["body"]


def test_un_cambio_en_expediente_no_seguido_no_genera_evento(base):
    _historial(_ID_NO_SEGUIDO, snapshot={"fecha_limite": "2026-11-01"}, changed="fecha_limite")

    derive_new_events()

    assert _eventos_de_cambio() == []


def test_una_reingesta_sin_cambio_real_no_genera_evento(base):
    """``values_equal``: el snapshot dice que cambió pero los valores son el
    mismo número con otra representación (float4 contra float8)."""
    _seguir(_ID)
    _historial(_ID, snapshot={"fecha_limite": "2026-12-01"}, changed="fecha_limite")

    derive_new_events()

    assert _eventos_de_cambio() == []


def test_los_retoques_de_redaccion_no_despiertan_a_nadie(base):
    """``titulo`` y ``descripcion`` no están en los campos seguidos: un cambio
    editorial no es una novedad del expediente."""
    _seguir(_ID)
    _historial(_ID, snapshot={"titulo": "Título anterior"}, changed="titulo")

    derive_new_events()

    assert _eventos_de_cambio() == []


def test_el_cursor_evita_releer_el_historial_entero(base):
    """Criterio de S4.5: el productor va sobre el cursor de ``contract_events``.

    Una segunda pasada sin filas nuevas no vuelve a emitir el mismo aviso.
    """
    _seguir(_ID)
    _historial(_ID, snapshot={"fecha_limite": "2026-11-01"}, changed="fecha_limite")

    derive_new_events()
    pendientes_tras_la_primera = count_pending_events()
    derive_new_events()

    assert count_pending_events() == pendientes_tras_la_primera


def test_una_oportunidad_abierta_cuenta_como_seguimiento(base):
    """No hace falta tener el expediente en favoritos: si es una oportunidad
    viva de la organización, su responsable quiere enterarse."""
    from db.database import connect
    from db.users import create_user

    user_id = create_user(
        email="s4-cambio@example.test",
        password_hash="test-hash",  # pragma: allowlist secret
        display_name="Responsable",
    )
    from db.repositories.organizations import OrganizationRepository

    org_id = int(OrganizationRepository().ensure_personal_organization(user_id)["id"])
    with connect() as c:
        c.execute(
            "INSERT INTO pursuits (organization_id, licitacion_id, responsible_user_id, "
            " status, created_at, updated_at, version) "
            "VALUES (%s, %s, %s, 'identified', '2026-09-01', '2026-09-01', 1)",
            (org_id, _ID, user_id),
        )
    _historial(_ID, snapshot={"estado": "EV"}, changed="estado")

    derive_new_events()

    eventos = _eventos_de_cambio()
    assert len(eventos) == 1
    seguidores = eventos[0]["payload"]["seguidores"]
    assert any(s["organization_id"] == org_id for s in seguidores)


def test_una_oportunidad_terminal_ya_no_sigue_el_expediente(base):
    from db.database import connect
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    user_id = create_user(
        email="s4-cambio-perdida@example.test",
        password_hash="test-hash",  # pragma: allowlist secret
        display_name="Responsable",
    )
    org_id = int(OrganizationRepository().ensure_personal_organization(user_id)["id"])
    with connect() as c:
        c.execute(
            "INSERT INTO pursuits (organization_id, licitacion_id, responsible_user_id, "
            " status, created_at, updated_at, version) "
            "VALUES (%s, %s, %s, 'lost', '2026-09-01', '2026-09-01', 1)",
            (org_id, _ID, user_id),
        )
    _historial(_ID, snapshot={"estado": "EV"}, changed="estado")

    derive_new_events()

    assert _eventos_de_cambio() == []
