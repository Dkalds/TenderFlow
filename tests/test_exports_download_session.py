"""Cobertura end-to-end de los dos endpoints de exportación con sesión real.

Los tests que existían de `GET /exports/download` toleraban 401/403, así que
el cuerpo del handler no llegaba a ejecutarse nunca (diff-cover lo medía al 4%).
Estos ejercitan el camino completo con una sesión de verdad — register + login
contra los endpoints reales, como `tests/test_routes_auth_sessions.py`.

Importa porque ambos handlers se reescribieron en esta rama para sacar su
trabajo del event loop (`run_db`), y `download_export` además pasó a empujar
los filtros a SQL en vez de aplicarlos en Python tras traer las filas.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

_EMAIL = "exportador@example.com"
_PASSWORD = "Exportar-2026-Seguro"  # pragma: allowlist secret


def _seed_licitacion(
    db_mod,
    id_externo: str,
    *,
    titulo: str = "Servicio de mantenimiento",
    ccaa: str = "Madrid",
    tecnologia: str | None = None,
    fecha_publicacion: str | None = None,
) -> None:
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, ccaa, tecnologia, fecha_publicacion, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                id_externo,
                titulo,
                ccaa,
                tecnologia,
                fecha_publicacion,
                datetime.now(UTC).isoformat(),
            ),
        )


@pytest.fixture()
def session_client(client, api_db):
    """TestClient con sesión activa (register + login reales)."""
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": _EMAIL, "password": _PASSWORD},
    )
    assert reg.status_code == 201, reg.text
    login = client.post(
        "/api/v1/auth/login",
        json={"email": _EMAIL, "password": _PASSWORD},
    )
    assert login.status_code == 200, login.text
    return client


# ── GET /exports/download ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("fmt", "content_type"),
    [
        ("csv", "text/csv"),
        ("excel", "application/vnd.openxmlformats"),
        ("pdf", "application/pdf"),
    ],
)
def test_download_devuelve_el_documento_en_los_tres_formatos(session_client, fmt, content_type):
    """El handler completo corre y serializa en el formato pedido."""
    import db.database as db_mod

    _seed_licitacion(db_mod, "EXP-DL-1")

    resp = session_client.get(f"/api/v1/exports/download?format={fmt}")

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith(content_type)
    assert f".{'xlsx' if fmt == 'excel' else fmt}" in resp.headers["content-disposition"]
    assert resp.content


def test_download_filtra_por_tecnologia_y_fechas_en_la_query(session_client):
    """Los filtros se aplican en SQL, no descartando filas ya traídas.

    Antes se filtraba en Python **después** del fetch, así que el LIMIT se
    gastaba en filas que luego se tiraban y una exportación filtrada podía
    salir corta. Con `limit=1` esa diferencia es observable: si el filtro
    fuera posterior, la única fila traída sería la que no encaja y el CSV
    saldría vacío.
    """
    import db.database as db_mod

    # La no coincidente se publica después, así que encabeza el ORDER BY.
    _seed_licitacion(db_mod, "EXP-DL-OTRA", tecnologia="Oracle", fecha_publicacion="2026-05-01")
    _seed_licitacion(db_mod, "EXP-DL-SAP", tecnologia="SAP", fecha_publicacion="2026-01-15")

    resp = session_client.get("/api/v1/exports/download?format=csv&tecnologia=SAP&limit=1")

    assert resp.status_code == 200, resp.text
    cuerpo = resp.content.decode("utf-8-sig")
    assert "EXP-DL-SAP" in cuerpo
    assert "EXP-DL-OTRA" not in cuerpo


def test_download_filtra_por_rango_de_fechas(session_client):
    import db.database as db_mod

    _seed_licitacion(db_mod, "EXP-DL-VIEJA", fecha_publicacion="2025-01-01")
    _seed_licitacion(db_mod, "EXP-DL-NUEVA", fecha_publicacion="2026-06-01")

    resp = session_client.get(
        "/api/v1/exports/download?format=csv&fecha_desde=2026-01-01&fecha_hasta=2026-12-31"
    )

    assert resp.status_code == 200, resp.text
    cuerpo = resp.content.decode("utf-8-sig")
    assert "EXP-DL-NUEVA" in cuerpo
    assert "EXP-DL-VIEJA" not in cuerpo


def test_download_sin_sesion_no_ejecuta_el_handler(client, api_db):
    """Sin cookie ni API key no se llega al cuerpo: 401/403, nunca 5xx."""
    resp = client.get("/api/v1/exports/download?format=csv")
    assert resp.status_code in (401, 403)


def test_download_acepta_api_key_ligada_con_scope_exports(client, api_db):
    import db.database as db_mod
    from api.auth import create_api_key
    from db.users import create_user
    from shared.auth_core import hash_password

    user_id = create_user(
        email="export-api@example.test",
        password_hash=hash_password(_PASSWORD),
    )
    token = create_api_key(
        "export-download",
        scopes="exports:read",
        user_id=user_id,
    )
    _seed_licitacion(db_mod, "EXP-DL-API")

    resp = client.get(
        "/api/v1/exports/download?format=csv",
        headers={"X-API-Key": token},
    )

    assert resp.status_code == 200, resp.text
    assert "EXP-DL-API" in resp.content.decode("utf-8-sig")


# ── GET /exports/calendario.ics ──────────────────────────────────────────────


@pytest.fixture()
def owned_api_key(api_db):
    """API key CON propietario.

    La fixture genérica `api_key` crea la key sin `user_id`, y este endpoint
    deriva el `user_key` del propietario: sin él responde 401 y el cuerpo del
    handler no llega a ejecutarse.
    """
    from api.auth import create_api_key
    from db.users import create_user
    from shared.auth_core import hash_password
    from shared.identity import user_key_from_email

    email = "calendario@example.com"
    user_id = create_user(email=email, password_hash=hash_password(_PASSWORD))
    token = create_api_key("calendario-key", scopes="*", user_id=user_id)
    return token, user_key_from_email(email, user_id)


def test_calendario_ics_devuelve_los_favoritos_con_fecha(client, api_db, owned_api_key):
    """El .ics incluye un VEVENT por deadline y otro por fin de contrato."""
    import db.database as db_mod
    from db.repositories.watchlist import WatchlistRepository

    token, user_key = owned_api_key
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, fecha_limite, fecha_fin, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                "EXP-ICS-1",
                "Licitación con plazos",
                "2026-09-30",
                "2027-09-30",
                datetime.now(UTC).isoformat(),
            ),
        )
    WatchlistRepository().add_item(user_key=user_key, user_id=None, id_externo="EXP-ICS-1")

    resp = client.get("/api/v1/exports/calendario.ics", headers={"X-API-Key": token})

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/calendar")
    cuerpo = resp.content.decode()
    assert "BEGIN:VCALENDAR" in cuerpo
    assert "EXP-ICS-1" in cuerpo
    assert cuerpo.count("BEGIN:VEVENT") == 2  # fecha_limite + fecha_fin


def test_calendario_ics_sin_favoritos_sigue_siendo_valido(client, api_db, owned_api_key):
    """Sin favoritos el .ics existe y está bien formado, no es un 500."""
    token, _ = owned_api_key

    resp = client.get("/api/v1/exports/calendario.ics", headers={"X-API-Key": token})

    assert resp.status_code == 200, resp.text
    cuerpo = resp.content.decode()
    assert cuerpo.startswith("BEGIN:VCALENDAR")
    assert "END:VCALENDAR" in cuerpo


def test_calendario_ics_exige_la_cabecera_no_la_query(client, api_db, owned_api_key):
    """El token va en X-API-Key y solo ahí: en la URL acabaría en los logs."""
    token, _ = owned_api_key

    resp = client.get(f"/api/v1/exports/calendario.ics?token={token}")

    assert resp.status_code in (401, 403)
