"""Las claves de API de la instancia, contra Postgres (CU-20).

Un administrador ve las claves de todos —también las que no tienen dueño, que
es lo que había en producción: 89 activas con ``user_id`` nulo y sin
``expires_at``— y revoca una ajena. La fila legada se inserta a mano porque
ningún camino del código puede ya emitir una así.
"""

from __future__ import annotations

from tests.claves import clave_de_prueba, dueno_de_prueba


def _insertar_clave_legada(nombre: str) -> int:
    """Una clave como las de producción: activa, sin dueño y sin caducidad."""
    from db.database import connect, now_utc_iso

    with connect() as c:
        fila = c.execute(
            "INSERT INTO api_keys (key_hash, name, created_at, is_active) "
            "VALUES (%s, %s, %s, 1) RETURNING id",
            (f"legacy-{nombre}-" + "0" * 40, nombre, now_utc_iso()),
        ).fetchone()
    return int(fila[0])


def test_admin_lista_todas_las_claves_sin_secretos(client):
    """CU-20 — el administrador ve las claves de otros y las que no tienen dueño."""
    admin_id = dueno_de_prueba("admin", admin=True)
    admin_key = clave_de_prueba("admin-ops", scopes="*", user_id=admin_id)
    ana = dueno_de_prueba("ana")
    clave_de_prueba("integración de Ana", user_id=ana)
    legada_id = _insertar_clave_legada("legada-sin-dueno")

    resp = client.get("/api/v1/admin/api-keys", headers={"X-API-Key": admin_key})

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    por_nombre = {item["name"]: item for item in cuerpo["items"]}
    assert por_nombre["integración de Ana"]["user_id"] == ana
    assert por_nombre["integración de Ana"]["owner_email"].startswith("ana-")
    assert por_nombre["integración de Ana"]["expires_at"]
    legada = por_nombre["legada-sin-dueno"]
    assert legada["id"] == legada_id
    assert legada["user_id"] is None
    assert legada["expires_at"] is None
    assert legada["estado"] == "activa"
    assert cuerpo["resumen"]["activas_sin_dueno"] == 1
    assert cuerpo["resumen"]["activas_sin_caducidad"] == 1
    assert cuerpo["resumen"]["total"] == 3
    assert "legacy-" not in resp.text
    assert admin_key not in resp.text


def test_quien_no_es_admin_no_ve_las_claves(client):
    clave = clave_de_prueba("curioso", scopes="*")
    resp = client.get("/api/v1/admin/api-keys", headers={"X-API-Key": clave})
    assert resp.status_code == 403


def test_admin_revoca_una_clave_ajena_y_queda_auditado(client):
    """CU-20 — revocar una clave ajena la apaga y deja el actor en audit_log."""
    from db.database import connect_read

    admin_id = dueno_de_prueba("admin", admin=True)
    admin_key = clave_de_prueba("admin-ops", scopes="*", user_id=admin_id)
    ana = dueno_de_prueba("ana")
    clave_ana = clave_de_prueba("de Ana", scopes="data:read", user_id=ana)
    assert client.get("/api/v1/licitaciones", headers={"X-API-Key": clave_ana}).status_code == 200

    listado = client.get("/api/v1/admin/api-keys", headers={"X-API-Key": admin_key}).json()
    (fila_ana,) = [item for item in listado["items"] if item["name"] == "de Ana"]

    resp = client.delete(
        f"/api/v1/admin/api-keys/{fila_ana['id']}", headers={"X-API-Key": admin_key}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["estado"] == "revocada"
    assert resp.json()["user_id"] == ana
    assert client.get("/api/v1/licitaciones", headers={"X-API-Key": clave_ana}).status_code == 401
    with connect_read() as c:
        auditoria = c.execute(
            "SELECT user_id FROM audit_log WHERE action = 'api_key.revoked' "
            "AND detail LIKE %s ORDER BY id DESC LIMIT 1",
            (f"%resource=api_key:{fila_ana['id']} |%",),
        ).fetchone()
    assert auditoria is not None
    assert auditoria[0] == admin_id


def test_revocar_una_clave_legada_sin_dueno(client):
    admin_id = dueno_de_prueba("admin", admin=True)
    admin_key = clave_de_prueba("admin-ops", scopes="*", user_id=admin_id)
    legada_id = _insertar_clave_legada("legada")

    resp = client.delete(f"/api/v1/admin/api-keys/{legada_id}", headers={"X-API-Key": admin_key})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": legada_id, "name": "legada", "user_id": None, "estado": "revocada"}
    resumen = client.get("/api/v1/admin/api-keys", headers={"X-API-Key": admin_key}).json()[
        "resumen"
    ]
    assert resumen["activas_sin_dueno"] == 0


def test_revocar_inexistente_es_404(client):
    admin_key = clave_de_prueba(
        "admin-ops", scopes="*", user_id=dueno_de_prueba("admin", admin=True)
    )
    resp = client.delete("/api/v1/admin/api-keys/987654", headers={"X-API-Key": admin_key})
    assert resp.status_code == 404
