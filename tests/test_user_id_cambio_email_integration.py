"""ADR-030 fase 2 (v129): cambiar de correo ya no pierde los datos.

Es el test de aceptación que nombra el ADR: favoritos, reglas, vistas, perfil,
descartes, notificaciones y preferencias sobreviven a un cambio de email. Se
ejercita por la API con sesión real —registro, login, escrituras, cambio de
``users.email``, login con el correo nuevo, lecturas— porque la clave
``user_key`` la deriva ``require_any_auth`` del correo de la sesión, y es esa
derivación la que cambia.

Además comprueba dos piezas de la migración contra Postgres de verdad:

* que la derivación de ``user_key`` en SQL (``CLAVE_SQL``) coincide clave a
  clave con ``shared.identity.user_key_from_email``;
* que el backfill resuelve ``user_id`` en las doce tablas a partir de filas
  legacy (sólo ``user_key``) y que la lectura dual las sirve tanto antes como
  después.
"""

from __future__ import annotations

import importlib
import io
import json
import zipfile
from typing import Any

import pytest

from db.database import connect
from shared.identity import user_key_from_email

_MIGRACION = "db.alembic.versions.v129_user_id_fase2"

#: Tablas con PK en ``user_id`` desde v135 (ADR-030 fase 3). Ya no admiten una
#: fila sin ``user_id``, así que no hay «fila legacy» que sembrar en ellas: su
#: backfill y su fallo ruidoso los prueba ``tests/test_v135_user_id_pk_fase3.py``.
_CON_PK_USER_ID = frozenset({"user_profiles", "radar_dismissals"})

_EMAIL_VIEJO = "Persona.Antes@Example.com"
_EMAIL_NUEVO = "persona.despues@example.com"
_PASSWORD = "Cambio-2026-Seguro"  # pragma: allowlist secret


def _migracion() -> Any:
    return importlib.import_module(_MIGRACION)


def _tablas_legacy() -> tuple[str, ...]:
    """Las tablas de v129 que todavía aceptan filas escritas sólo con ``user_key``."""
    return tuple(t for t in _migracion().TABLAS if t not in _CON_PK_USER_ID)


# ── Derivación y backfill ───────────────────────────────────────────────────


def _crear_usuario(email: str | None) -> int:
    from db.database import now_utc_iso

    with connect() as c:
        row = c.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (%s, %s, %s) RETURNING id",
            (email, "h", now_utc_iso()),
        ).fetchone()
    return int(row[0])


@pytest.mark.parametrize(
    "email",
    [
        "simple@example.com",
        "MixedCase@Example.COM",
        "  con.espacios@example.com  ",
        "ñandú@example.es",
        None,
    ],
)
def test_clave_sql_coincide_con_python(tmp_db, email):
    """``CLAVE_SQL`` reproduce ``user_key_from_email`` para cada semilla.

    ``None`` cubre a los usuarios anonimizados (``email IS NULL``): la semilla
    pasa a ser ``user:<id>`` en los dos lados.
    """
    migracion = _migracion()
    user_id = _crear_usuario(email)
    with connect() as c:
        row = c.execute(
            f"SELECT {migracion.CLAVE_SQL} FROM users u WHERE u.id = %s",  # noqa: S608
            (user_id,),
        ).fetchone()
    assert row[0] == user_key_from_email(email, user_id)


def _organizacion_personal(user_id: int) -> int:
    from db.repositories.organizations import OrganizationRepository

    return int(OrganizationRepository().ensure_personal_organization(user_id)["id"])


def _sembrar_filas_legacy(user_key: str, organization_id: int) -> None:
    """Una fila por tabla, escrita SÓLO con ``user_key`` (como antes de v129).

    Salvo ``user_profiles`` y ``radar_dismissals``: desde v135 su PK es
    ``user_id`` y una fila sin él ya no existe (ver ``_CON_PK_USER_ID``).
    """
    from db.audit import log_action
    from db.database import now_utc_iso
    from db.notifications import insert_user_notification, mark_read
    from db.repositories.watchlist import WatchlistRepository
    from db.saved_filters import save_filter
    from db.watchlist import WatchlistEntry, add_entry
    from db.watchlist_empresas import WatchlistEmpresaEntry
    from db.watchlist_empresas import add_entry as add_empresa
    from services.notifications import set_modo_email
    from services.watchlist_rules import WatchlistRule, create_rule

    repo = WatchlistRepository()
    repo.add_item(user_key, None, "LIC-LEGACY", organization_id)
    create_rule(user_key, WatchlistRule(keyword="sap"), organization_id=organization_id)
    add_entry(WatchlistEntry(user_key=user_key, cpv_prefix="72", organization_id=organization_id))
    save_filter(user_key, "Vista legacy", "{}", organization_id)
    insert_user_notification(
        user_key=user_key,
        type_="rule_match",
        title="t",
        body=None,
        licitacion_id="LIC-LEGACY",
        organization_id=organization_id,
    )
    mark_read(user_key, "LIC-LEGACY")
    set_modo_email(user_key, "pursuit.assigned", "off")
    log_action(user_key, "sess", "login", "")
    repo.store_pending_digest(
        user_key=user_key,
        recipient="x@example.com",
        entry_id=1,
        licitacion_id="LIC-LEGACY",
        frequency="daily",
        matched_at=now_utc_iso(),
    )
    with connect() as c:
        c.execute(
            "INSERT INTO empresas (empresa_id, nombre_canonico) VALUES (777, 'ACME') "
            "ON CONFLICT DO NOTHING"
        )
    add_empresa(
        WatchlistEmpresaEntry(user_key=user_key, empresa_id=777, organization_id=organization_id)
    )


def _contar(tabla: str, user_id: int) -> int:
    with connect() as c:
        row = c.execute(
            f"SELECT COUNT(*) FROM {tabla} WHERE user_id = %s",  # noqa: S608
            (user_id,),
        ).fetchone()
    return int(row[0])


def test_backfill_resuelve_user_id_en_las_tablas_legacy(tmp_db):
    """Filas legacy (sólo ``user_key``) quedan ancladas al ``users.id``.

    Se ejecuta el mismo SQL de la migración sobre datos sembrados después de
    ``alembic upgrade head``: es la única forma de ver el backfill actuar en
    un test, porque la fixture aplica la revisión sobre una base vacía.
    """
    migracion = _migracion()
    user_id = _crear_usuario(_EMAIL_VIEJO)
    otro = _crear_usuario("otra.persona@example.com")
    organization_id = _organizacion_personal(user_id)
    clave = user_key_from_email(_EMAIL_VIEJO, user_id)
    _sembrar_filas_legacy(clave, organization_id)
    # Una fila de auditoría escrita con el id en texto, como hacen los
    # llamadores nuevos de `log_event`.
    from db.audit import log_action

    log_action(str(user_id), "sess", "gdpr.export", "")

    for tabla in _tablas_legacy():
        assert _contar(tabla, user_id) == 0, tabla

    with connect() as c:
        c.execute(migracion._CREAR_CLAVES)
        c.execute(migracion._SEMBRAR_CLAVES)
        for tabla in _tablas_legacy():
            c.execute(migracion.sql_backfill(tabla))
        c.execute(migracion.SQL_BACKFILL_AUDIT_POR_ID)

    for tabla in _tablas_legacy():
        assert _contar(tabla, user_id) >= 1, tabla
        assert _contar(tabla, otro) == 0, tabla
    # Las dos formas de `audit_log`: la clave derivada y el id en texto.
    assert _contar("audit_log", user_id) == 2


def test_lectura_dual_sirve_filas_legacy_antes_del_backfill(tmp_db):
    """Una fila sin ``user_id`` sigue siendo del usuario si lleva su clave.

    Y NO es de otro usuario que comparta la clave pero tenga id: es la mitad
    del predicado que impide heredar los datos de quien tuvo antes el correo.
    """
    from db.repositories.watchlist import WatchlistRepository
    from db.saved_filters import list_saved_filters

    user_id = _crear_usuario(_EMAIL_VIEJO)
    organization_id = _organizacion_personal(user_id)
    clave = user_key_from_email(_EMAIL_VIEJO, user_id)
    _sembrar_filas_legacy(clave, organization_id)

    repo = WatchlistRepository()
    assert [i["id_externo"] for i in repo.list_items(clave, organization_id, user_id)] == [
        "LIC-LEGACY"
    ]
    assert [f["name"] for f in list_saved_filters(clave, organization_id, user_id=user_id)] == [
        "Vista legacy"
    ]
    # Un tercero con la misma clave (imposible en la práctica, pero es el
    # predicado el que se prueba) y otro id no ve nada una vez la fila tiene
    # dueño.
    with connect() as c:
        c.execute("UPDATE watchlist_items SET user_id = %s WHERE user_key = %s", (user_id, clave))
    assert repo.list_items(clave, organization_id, user_id + 1000) == []


def test_watchlist_empresas_sobrevive_al_cambio_de_clave(tmp_db):
    """Vigilancia de competidores: escrita con las dos identidades, se lee y
    se borra con la clave nueva."""
    from db.watchlist_empresas import WatchlistEmpresaEntry, add_entry, list_entries, remove_entry

    user_id = _crear_usuario(_EMAIL_VIEJO)
    organization_id = _organizacion_personal(user_id)
    clave_vieja = user_key_from_email(_EMAIL_VIEJO, user_id)
    clave_nueva = user_key_from_email(_EMAIL_NUEVO, user_id)
    with connect() as c:
        c.execute("INSERT INTO empresas (empresa_id, nombre_canonico) VALUES (778, 'BETA')")

    assert (
        add_entry(
            WatchlistEmpresaEntry(
                user_key=clave_vieja,
                empresa_id=778,
                organization_id=organization_id,
                user_id=user_id,
            )
        )
        is not None
    )
    # Repetir con la clave nueva no duplica: la identidad dual la reconoce.
    assert (
        add_entry(
            WatchlistEmpresaEntry(
                user_key=clave_nueva,
                empresa_id=778,
                organization_id=organization_id,
                user_id=user_id,
            )
        )
        is None
    )
    assert [
        e["empresa_id"] for e in list_entries(clave_nueva, organization_id, user_id=user_id)
    ] == [778]
    # Otro usuario del mismo equipo no la ve (es privada) ni la borra.
    assert list_entries("otra-clave", organization_id, user_id=user_id + 1000) == []
    assert remove_entry("otra-clave", 778, organization_id, user_id=user_id + 1000) is False
    assert remove_entry(clave_nueva, 778, organization_id, user_id=user_id) is True


# ── Aceptación por la API: el cambio de correo ─────────────────────────────


def _login(client, email: str) -> str:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    assert resp.status_code == 200, resp.text
    return str(resp.cookies["csrf_token"])


@pytest.fixture()
def sesion(client, api_db):
    """Usuario registrado y con sesión abierta bajo el correo original."""
    reg = client.post("/api/v1/auth/register", json={"email": _EMAIL_VIEJO, "password": _PASSWORD})
    assert reg.status_code == 201, reg.text
    csrf = _login(client, _EMAIL_VIEJO)
    from db.users import get_active_user_by_email_ci

    # El alta canonicaliza el correo al guardarlo: se busca sin distinguir caja.
    usuario = get_active_user_by_email_ci(_EMAIL_VIEJO)
    assert usuario is not None
    return client, csrf, int(usuario["id"])


def _cambiar_email(user_id: int, nuevo: str) -> None:
    """No hay flujo de cambio de correo en la API (ver
    ``tests/test_user_email_change_guard.py``): se simula sobre ``users``."""
    with connect() as c:
        c.execute("UPDATE users SET email = %s WHERE id = %s", (nuevo, user_id))


def test_cambiar_de_email_conserva_todo(sesion):
    client, csrf, user_id = sesion
    cab = {"X-CSRF-Token": csrf}
    organization_id = _organizacion_personal(user_id)
    clave_vieja = user_key_from_email(_EMAIL_VIEJO, user_id)

    # ── Escrituras con la identidad original ──
    assert (
        client.post("/api/v1/watchlist/items", json={"id_externo": "LIC-1"}, headers=cab)
    ).status_code == 201
    assert (
        client.post("/api/v1/watchlist/rules", json={"keyword": "sap", "nombre": "R"}, headers=cab)
    ).status_code == 201
    assert (
        client.post(
            "/api/v1/saved-filters", json={"name": "Mi vista", "filters_json": "{}"}, headers=cab
        )
    ).status_code == 201
    assert (
        client.put(
            "/api/v1/me/profile",
            json={"weights": {"afinidad": 50, "importe": 30, "plazo": 20}},
            headers=cab,
        )
    ).status_code == 200
    assert (
        client.post("/api/v1/radar/dismissals", json={"id_externo": "LIC-2"}, headers=cab)
    ).status_code == 201
    # La alerta la escribe un productor (job), no una ruta: se escribe como lo
    # hacen todos desde v129, con las dos identidades.
    from db.notifications import insert_user_notification
    from services.notifications import modo_email_de, set_modo_email

    assert insert_user_notification(
        user_key=clave_vieja,
        user_id=user_id,
        type_="rule_match",
        title="Alerta",
        body=None,
        licitacion_id="LIC-3",
        organization_id=organization_id,
    )
    set_modo_email(clave_vieja, "pursuit.assigned", "off", user_id=user_id)

    # ── Cambio de correo y nueva sesión ──
    _cambiar_email(user_id, _EMAIL_NUEVO)
    csrf = _login(client, _EMAIL_NUEVO)
    cab = {"X-CSRF-Token": csrf}
    clave_nueva = user_key_from_email(_EMAIL_NUEVO, user_id)
    assert clave_nueva != clave_vieja

    # ── Todo sigue ahí leyendo con la identidad nueva ──
    items = client.get("/api/v1/watchlist/items").json()["items"]
    assert [i["id_externo"] for i in items] == ["LIC-1"]

    reglas = client.get("/api/v1/watchlist/rules").json()["items"]
    assert [r["nombre"] for r in reglas] == ["R"]

    vistas = client.get("/api/v1/saved-filters").json()["items"]
    assert [v["name"] for v in vistas] == ["Mi vista"]

    perfil = client.get("/api/v1/me/profile").json()
    assert perfil["weights"] == {"afinidad": 50, "importe": 30, "plazo": 20}
    assert perfil["inherited"] is False

    descartes = client.get("/api/v1/radar/dismissals").json()
    assert descartes["ids"] == ["LIC-2"]

    alertas = client.get("/api/v1/notifications").json()["alerts"]
    assert [a["licitacion_id"] for a in alertas] == ["LIC-3"]

    assert modo_email_de(clave_nueva, "pursuit.assigned", user_id=user_id) == "off"

    # El export GDPR también cubre lo guardado bajo el correo anterior.
    export = client.get("/api/v1/me/data")
    assert export.status_code == 200, export.text
    with zipfile.ZipFile(io.BytesIO(export.content)) as zf:
        assert [i["id_externo"] for i in json.loads(zf.read("watchlist_items.json"))] == ["LIC-1"]
        assert json.loads(zf.read("perfil_scoring.json"))["importe_min"] is None
        assert len(json.loads(zf.read("notificaciones.json"))) == 1


def test_escribir_tras_el_cambio_no_duplica(sesion):
    """Repetir una escritura con la clave nueva actualiza la fila, no la clona.

    En las tablas tecleadas todavía por ``user_key`` lo garantiza el
    repositorio (localiza la fila por identidad dual antes de insertar); en
    ``user_profiles`` y ``radar_dismissals`` lo garantiza la PK por
    ``user_id`` de v135.
    """
    client, csrf, user_id = sesion
    cab = {"X-CSRF-Token": csrf}

    client.post("/api/v1/watchlist/items", json={"id_externo": "LIC-1"}, headers=cab)
    client.post(
        "/api/v1/saved-filters", json={"name": "Mi vista", "filters_json": "{}"}, headers=cab
    )
    client.put("/api/v1/me/profile", json={"importe_min": 1}, headers=cab)
    client.post("/api/v1/radar/dismissals", json={"id_externo": "LIC-2"}, headers=cab)

    _cambiar_email(user_id, _EMAIL_NUEVO)
    cab = {"X-CSRF-Token": _login(client, _EMAIL_NUEVO)}

    assert (
        client.post("/api/v1/watchlist/items", json={"id_externo": "LIC-1"}, headers=cab)
    ).status_code == 201
    client.post(
        "/api/v1/saved-filters",
        json={"name": "Mi vista", "filters_json": '{"q": "x"}'},
        headers=cab,
    )
    client.put("/api/v1/me/profile", json={"importe_min": 2}, headers=cab)
    client.post("/api/v1/radar/dismissals", json={"id_externo": "LIC-2"}, headers=cab)

    assert _contar("watchlist_items", user_id) == 1
    assert _contar("saved_filters", user_id) == 1
    assert _contar("user_profiles", user_id) == 1
    assert _contar("radar_dismissals", user_id) == 1
    assert client.get("/api/v1/me/profile").json()["importe_min"] == 2
    assert client.get("/api/v1/saved-filters").json()["items"][0]["filters_json"] == '{"q": "x"}'

    # Y el borrado GDPR se lleva lo de las dos claves.
    from services.gdpr import anonymize_user_data

    anonymize_user_data(user_key_from_email(_EMAIL_NUEVO, user_id), user_id=user_id)
    for tabla in ("watchlist_items", "saved_filters", "user_profiles", "radar_dismissals"):
        assert _contar(tabla, user_id) == 0, tabla
