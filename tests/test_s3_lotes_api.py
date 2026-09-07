"""S3.1/S3.2/S3.3 contra Postgres: lotes, ICS, métricas y aplicación de pesos.

Todo lo de aquí exige base (fixtures ``api_db``/``client``), así que queda
marcado ``integration`` por el propio ``conftest`` y no corre en la suite
rápida. Es el criterio de aceptación de S3 que sólo una base real puede
sostener:

- dos oportunidades del mismo expediente en lotes distintos → 201 las dos;
- el mismo lote dos veces → idempotente;
- sin lote sigue funcionando, y una fila anterior a ``v110`` no cambia;
- el ICS lleva el lote en el título;
- ``GET /pursuits/metrics`` cuenta por oportunidad y lo dice;
- aplicar la propuesta de pesos deja rastro en ``audit_log``.
"""

from __future__ import annotations

import json
from typing import Any

from api.routes.dual_auth import require_any_auth
from db.repositories.organizations import OrganizationRepository

_LICITACION = "LIC-S3-LOTES"
_USER_KEY = "s3-lotes-test"


def _seed(_api_db: Any) -> tuple[int, int, dict[str, int]]:
    """Usuario, organización y expediente con tres lotes. Devuelve sus ids."""
    from db.database import connect
    from db.users import create_user

    user_id = create_user(
        email="s3-lotes@example.test",
        password_hash="test-hash",  # pragma: allowlist secret
        display_name="S3 Lotes",
    )
    organization_id = int(OrganizationRepository().ensure_personal_organization(user_id)["id"])
    lotes: dict[str, int] = {}
    with connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, fecha_limite, fecha_extraccion) VALUES (%s, %s, %s, %s)",
            (
                _LICITACION,
                "Servicios SAP multilote",
                "2026-11-01T10:00:00+00:00",
                "2026-09-01T10:00:00+00:00",
            ),
        )
        for numero, titulo in (("1", "Soporte"), ("2", "Migración"), ("3", "Formación")):
            row = conn.execute(
                "INSERT INTO lotes (licitacion_id, numero, titulo, fecha_extraccion) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (_LICITACION, numero, titulo, "2026-09-01T10:00:00+00:00"),
            ).fetchone()
            lotes[numero] = int(row[0])
    return user_id, organization_id, lotes


def _autenticar(user_id: int) -> None:
    from api.app import app

    app.dependency_overrides[require_any_auth] = lambda: {
        "user_id": user_id,
        "auth_method": "session",
        "user_key": _USER_KEY,
        "email": "s3-lotes@example.test",
    }


def test_dos_lotes_del_mismo_expediente_son_dos_oportunidades(client, api_db):
    """La unicidad de v61 lo impedía: un expediente, una oportunidad y basta."""
    from api.app import app

    user_id, organization_id, lotes = _seed(api_db)
    _autenticar(user_id)
    try:
        primera = client.post(
            "/api/v1/pursuits",
            json={
                "licitacion_id": _LICITACION,
                "organization_id": organization_id,
                "lote_id": lotes["1"],
            },
        )
        segunda = client.post(
            "/api/v1/pursuits",
            json={
                "licitacion_id": _LICITACION,
                "organization_id": organization_id,
                "lote_id": lotes["2"],
            },
        )

        assert primera.status_code == 201
        assert segunda.status_code == 201
        assert primera.json()["id"] != segunda.json()["id"]
        assert primera.json()["lote_numero"] == "1"
        assert segunda.json()["lote_numero"] == "2"
        assert segunda.json()["lote_titulo"] == "Migración"
        assert segunda.json()["lote_id"] == lotes["2"]
    finally:
        app.dependency_overrides.clear()


def test_el_mismo_lote_dos_veces_es_idempotente(client, api_db):
    from api.app import app

    user_id, organization_id, lotes = _seed(api_db)
    _autenticar(user_id)
    try:
        cuerpo = {
            "licitacion_id": _LICITACION,
            "organization_id": organization_id,
            "lote_id": lotes["3"],
        }
        primera = client.post("/api/v1/pursuits", json=cuerpo)
        repetida = client.post("/api/v1/pursuits", json=cuerpo)

        assert primera.status_code == 201
        assert repetida.status_code == 201
        assert primera.json()["id"] == repetida.json()["id"]
    finally:
        app.dependency_overrides.clear()


def test_sin_lote_sigue_funcionando_y_convive_con_los_lotes(client, api_db):
    """``NULL`` es «el expediente completo» y conserva su unicidad propia.

    Es lo que garantiza que las filas anteriores a ``v110`` —todas sin lote— no
    cambien de significado ni pierdan la protección de v61.
    """
    from api.app import app

    user_id, organization_id, lotes = _seed(api_db)
    _autenticar(user_id)
    try:
        entero = client.post(
            "/api/v1/pursuits",
            json={"licitacion_id": _LICITACION, "organization_id": organization_id},
        )
        repetido = client.post(
            "/api/v1/pursuits",
            json={"licitacion_id": _LICITACION, "organization_id": organization_id},
        )
        con_lote = client.post(
            "/api/v1/pursuits",
            json={
                "licitacion_id": _LICITACION,
                "organization_id": organization_id,
                "lote_id": lotes["1"],
            },
        )

        assert entero.json()["lote_numero"] is None
        assert entero.json()["lote_id"] is None
        # Sin lote, dos intentos siguen siendo una sola fila (garantía de v61).
        assert entero.json()["id"] == repetido.json()["id"]
        # Y el lote no colisiona con el expediente entero.
        assert con_lote.json()["id"] != entero.json()["id"]
    finally:
        app.dependency_overrides.clear()


def test_la_fila_anterior_a_v110_no_cambia(client, api_db):
    """Una oportunidad creada como antes queda con las columnas nuevas en NULL.

    ``NULL`` es su verdad: se abrió para el expediente completo y sin desglose
    sellado. Rellenarla fabricaría la evidencia que estas columnas existen para
    recoger (mismo argumento que la revisión ``v93``).
    """
    from api.app import app
    from db.database import connect_read

    user_id, organization_id, _lotes = _seed(api_db)
    _autenticar(user_id)
    try:
        creada = client.post(
            "/api/v1/pursuits",
            json={"licitacion_id": _LICITACION, "organization_id": organization_id},
        )
        with connect_read() as conn:
            fila = conn.execute(
                "SELECT lote_numero, desglose_al_abrir FROM pursuits WHERE id = %s",
                (creada.json()["id"],),
            ).fetchone()

        assert fila is not None
        assert fila[0] is None
        assert fila[1] is None
    finally:
        app.dependency_overrides.clear()


def test_un_lote_de_otro_expediente_no_se_puede_abrir(client, api_db):
    """Sin la comprobación de pertenencia se abriría A apuntando al lote de B."""
    from api.app import app
    from db.database import connect

    user_id, organization_id, _lotes = _seed(api_db)
    _autenticar(user_id)
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO licitaciones "
                "(id_externo, titulo, fecha_extraccion) VALUES (%s, %s, %s)",
                ("LIC-S3-OTRO", "Otro expediente", "2026-09-01T10:00:00+00:00"),
            )
            ajeno = int(
                conn.execute(
                    "INSERT INTO lotes (licitacion_id, numero, fecha_extraccion) "
                    "VALUES (%s, %s, %s) RETURNING id",
                    ("LIC-S3-OTRO", "1", "2026-09-01T10:00:00+00:00"),
                ).fetchone()[0]
            )

        respuesta = client.post(
            "/api/v1/pursuits",
            json={
                "licitacion_id": _LICITACION,
                "organization_id": organization_id,
                "lote_id": ajeno,
            },
        )

        assert respuesta.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_el_ics_lleva_el_lote_en_el_titulo(client, api_db):
    """Dos lotes con el mismo plazo se verían como el mismo evento repetido."""
    from api.app import app
    from api.routes.exports import _eventos_calendario

    user_id, organization_id, lotes = _seed(api_db)
    _autenticar(user_id)
    try:
        client.post(
            "/api/v1/pursuits",
            json={
                "licitacion_id": _LICITACION,
                "organization_id": organization_id,
                "lote_id": lotes["2"],
            },
        )
        eventos = _eventos_calendario(_USER_KEY, user_id, organization_id)

        resumenes = [str(evento["summary"]) for evento in eventos]
        assert any("Lote 2" in resumen for resumen in resumenes), resumenes
    finally:
        app.dependency_overrides.clear()


def test_las_metricas_cuentan_por_oportunidad_y_lo_dicen(client, api_db):
    """Tres oportunidades de un solo expediente son tres, y el contrato lo dice."""
    from api.app import app

    user_id, organization_id, lotes = _seed(api_db)
    _autenticar(user_id)
    try:
        for lote_id in (lotes["1"], lotes["2"], None):
            cuerpo: dict[str, Any] = {
                "licitacion_id": _LICITACION,
                "organization_id": organization_id,
            }
            if lote_id is not None:
                cuerpo["lote_id"] = lote_id
            client.post("/api/v1/pursuits", json=cuerpo)

        metricas = client.get(
            "/api/v1/pursuits/metrics", params={"organization_id": organization_id}
        )

        assert metricas.status_code == 200
        cuerpo_metricas = metricas.json()
        assert cuerpo_metricas["pursuits_identified"] == 3
        assert cuerpo_metricas["unidad_de_conteo"] == "oportunidad"
    finally:
        app.dependency_overrides.clear()


def _sellar_cierres(organization_id: int, ganadas: int, perdidas: int) -> None:
    """Inserta cierres con desglose sellado saltándose el workflow.

    Recorrer las siete transiciones por API para veinte oportunidades no
    probaría nada que ``tests/test_pursuits.py`` no cubra ya, y haría el test
    ilegible.
    """
    from db.database import connect, now_utc_iso

    ahora = now_utc_iso()
    filas = [("won", "Caliente", {"margen": 20.0, "importe": 10.0})] * ganadas
    filas += [("lost", "Caliente", {"margen": 5.0, "importe": 10.0})] * perdidas
    with connect() as conn:
        for indice, (outcome, banda, desglose) in enumerate(filas):
            conn.execute(
                "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) "
                "VALUES (%s, %s, %s)",
                (f"LIC-S3-CIERRE-{indice}", f"Cierre {indice}", ahora),
            )
            conn.execute(
                "INSERT INTO pursuits "
                "(organization_id, licitacion_id, status, outcome, identified_at, "
                " submitted_at, closed_at, created_at, updated_at, banda_al_abrir, "
                " desglose_al_abrir) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    organization_id,
                    f"LIC-S3-CIERRE-{indice}",
                    outcome,
                    outcome,
                    ahora,
                    ahora,
                    ahora,
                    ahora,
                    ahora,
                    banda,
                    json.dumps(desglose),
                ),
            )


def test_la_calidad_del_radar_viaja_en_las_metricas(client, api_db):
    """El bucle cerrado: doce cierres sellados y la banda ya se puede afirmar."""
    from api.app import app

    user_id, organization_id, _lotes = _seed(api_db)
    _autenticar(user_id)
    try:
        _sellar_cierres(organization_id, ganadas=8, perdidas=4)

        metricas = client.get(
            "/api/v1/pursuits/metrics", params={"organization_id": organization_id}
        ).json()

        calidad = metricas["radar_quality"]
        assert calidad is not None
        caliente = next(b for b in calidad["bandas"] if b["banda"] == "Caliente")
        assert (caliente["ganadas"], caliente["resueltas"]) == (8, 12)
        assert caliente["suficiente"] is True
        assert calidad["ventana_desde"] is not None
    finally:
        app.dependency_overrides.clear()


def test_aplicar_la_propuesta_de_pesos_queda_en_audit_log(client, api_db):
    """Un clic explícito, con rastro: cambiar los pesos reordena la bandeja."""
    from api.app import app
    from db.database import connect_read

    user_id, organization_id, _lotes = _seed(api_db)
    _autenticar(user_id)
    try:
        _sellar_cierres(organization_id, ganadas=12, perdidas=10)

        propuesta = client.get(
            "/api/v1/pursuits/weights-proposal",
            params={"organization_id": organization_id},
        ).json()
        assert propuesta["estado"] == "propuesta"
        assert propuesta["pesos_propuestos"]["margen"] > propuesta["pesos_actuales"]["margen"]

        aplicado = client.post(
            "/api/v1/pursuits/weights-proposal/apply",
            params={"organization_id": organization_id},
        )
        assert aplicado.status_code == 200
        assert aplicado.json()["pesos"] == propuesta["pesos_propuestos"]

        with connect_read() as conn:
            registro = conn.execute(
                "SELECT detail FROM audit_log WHERE action = %s ORDER BY id DESC LIMIT 1",
                ("pursuit.weights_proposal_applied",),
            ).fetchone()
        assert registro is not None
        assert "pesos_aplicados" in str(registro[0])

        # Y el perfil de scoring quedó con esos pesos, no con otros.
        perfil = client.get("/api/v1/me/profile", params={"organization_id": organization_id})
        assert perfil.json()["weights"] == propuesta["pesos_propuestos"]
    finally:
        app.dependency_overrides.clear()


def test_sin_cierres_suficientes_la_propuesta_no_se_puede_aplicar(client, api_db):
    from api.app import app

    user_id, organization_id, _lotes = _seed(api_db)
    _autenticar(user_id)
    try:
        propuesta = client.get(
            "/api/v1/pursuits/weights-proposal",
            params={"organization_id": organization_id},
        ).json()
        assert propuesta["estado"] == "insuficiente"
        assert propuesta["pesos_propuestos"] is None

        aplicado = client.post(
            "/api/v1/pursuits/weights-proposal/apply",
            params={"organization_id": organization_id},
        )
        assert aplicado.status_code == 422
    finally:
        app.dependency_overrides.clear()
