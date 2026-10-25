"""Tests para el endpoint de feature flags (RFC UX Feature Flags)."""

from __future__ import annotations


def test_feature_flags_get_returns_backend_list(client, api_db):
    """GET expone TODOS los flags del backend (incl. los que no están en ningún hardcode)."""
    from db.feature_flags import set_flag
    from tests.claves import clave_de_prueba

    set_flag(
        "nuevo_flag_solo_backend",
        enabled=True,
        rollout_pct=50,
        description="solo backend",
    )

    reader_key = clave_de_prueba("feature-flags-reader", scopes="feature_flags:read")
    res = client.get("/api/v1/feature-flags", headers={"X-API-Key": reader_key})
    assert res.status_code == 200
    flags = res.json()
    by_name = {f["flag"]: f for f in flags}
    assert "nuevo_flag_solo_backend" in by_name
    f = by_name["nuevo_flag_solo_backend"]
    assert f["enabled"] is True
    assert f["rollout_pct"] == 50
    assert f["description"] == "solo backend"


def test_set_feature_flags_preserves_description(tmp_db):
    """El toggle (PUT) persiste enabled/rollout y PRESERVA description/user_emails."""
    from api.routes.feature_flags import FlagIn, SetFlagsBody, set_feature_flags
    from db.feature_flags import get_flag, set_flag

    set_flag(
        "flag_x",
        enabled=False,
        rollout_pct=0,
        description="desc original",
        user_emails="a@b.com",
    )

    # Invoca el handler directamente con un admin simulado (evita el wiring de auth).
    set_feature_flags(
        SetFlagsBody(flags=[FlagIn(flag="flag_x", enabled=True, rollout_pct=100)]),
        admin={"user_id": 1, "is_admin": True},
    )

    row = get_flag("flag_x")
    assert row is not None
    assert row["enabled"] == 1
    assert row["rollout_pct"] == 100
    # Preservados: el toggle no debe borrarlos.
    assert row["description"] == "desc original"
    assert row["user_emails"] == "a@b.com"


def test_flag_declarada_sin_fila_sale_apagada(client, api_db):
    """Una flag que el código consulta aparece en Administración aunque no
    tenga fila, apagada, que es lo que ``is_enabled`` dice de ella."""
    from db.feature_flags import FLAG_BUSQUEDA_SEMANTICA, FLAGS_DECLARADAS, get_flag
    from tests.claves import clave_de_prueba

    assert get_flag(FLAG_BUSQUEDA_SEMANTICA) is None
    reader_key = clave_de_prueba("feature-flags-declaradas", scopes="feature_flags:read")
    res = client.get("/api/v1/feature-flags", headers={"X-API-Key": reader_key})
    assert res.status_code == 200
    by_name = {f["flag"]: f for f in res.json()}
    f = by_name[FLAG_BUSQUEDA_SEMANTICA]
    assert f["enabled"] is False
    assert f["rollout_pct"] == 0
    assert f["updated_at"] is None
    assert f["description"] == FLAGS_DECLARADAS[FLAG_BUSQUEDA_SEMANTICA]


def test_encender_una_flag_declarada_guarda_su_descripcion(tmp_db):
    from api.routes.feature_flags import FlagIn, SetFlagsBody, set_feature_flags
    from db.feature_flags import FLAG_BUSQUEDA_SEMANTICA, FLAGS_DECLARADAS, get_flag, is_enabled

    set_feature_flags(
        SetFlagsBody(flags=[FlagIn(flag=FLAG_BUSQUEDA_SEMANTICA, enabled=True, rollout_pct=100)]),
        admin={"user_id": 1, "is_admin": True},
    )

    row = get_flag(FLAG_BUSQUEDA_SEMANTICA)
    assert row is not None
    assert row["description"] == FLAGS_DECLARADAS[FLAG_BUSQUEDA_SEMANTICA]
    assert is_enabled(FLAG_BUSQUEDA_SEMANTICA) is True
