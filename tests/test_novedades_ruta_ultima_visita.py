"""``GET /api/v1/analytics/resumen/desde-mi-ultima-visita`` — la frontera de F5.4.

``test_novedades_desde_ultima_visita.py`` fija el servicio. Lo que sólo se ve
desde la ruta es de dónde salen sus dos entradas sensibles: la **última visita**
se lee de ``notification_reads`` con la ``user_key`` del principal —nunca de
la query—, y la **organización** se resuelve contra la membresía del usuario
en vez de creerle al parámetro. Un fallo en cualquiera de las dos enseña a un
usuario el diff de otro sin que ningún test del servicio lo note.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from db.database import connect

_URL = "/api/v1/analytics/resumen/desde-mi-ultima-visita"


def _iso(**delta: float) -> str:
    return (datetime.now(UTC) - timedelta(**delta)).isoformat()


def _usuario(email: str) -> tuple[int, str, dict[str, str]]:
    """``(user_id, user_key, cabeceras)`` de un usuario con API key propia.

    La key va ligada al usuario: ``require_any_auth`` deriva la ``user_key`` de
    la identidad, y es esa clave la que indexa seguimientos y lecturas.
    """
    from api.auth import create_api_key
    from db.users import create_user
    from shared.identity import user_key_from_email

    user_id = create_user(
        email=email,
        password_hash="test-hash",  # pragma: allowlist secret
        display_name=email.split("@")[0],
    )
    clave = create_api_key(f"novedades-{user_id}", scopes="*", user_id=user_id)
    return user_id, user_key_from_email(email, user_id), {"X-API-Key": clave}


def _licitacion(id_externo: str) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, estado, fecha_extraccion) "
            "VALUES (%s, %s, 'PUB', '2026-09-01')",
            (id_externo, f"Expediente {id_externo}"),
        )


def _seguir(user_key: str, id_externo: str) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO watchlist_items (user_key, id_externo, created_at) "
            "VALUES (%s, %s, '2026-09-01')",
            (user_key, id_externo),
        )


def _cambio(id_externo: str, *, cuando: str) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones_history "
            "(id_externo, captured_at, snapshot_json, changed_fields) VALUES (%s, %s, %s, 'url')",
            (id_externo, cuando, json.dumps({"estado": "PUB"})),
        )


def _visto(user_key: str, *, cuando: str) -> None:
    """Una lectura de la campana: es lo que la ruta toma como última visita."""
    with connect() as c:
        c.execute(
            "INSERT INTO notification_reads (user_key, notification_id, read_at) "
            "VALUES (%s, %s, %s)",
            (user_key, f"leida-{cuando}", cuando),
        )


def _equipo(owner_id: int, nombre: str) -> int:
    from db.repositories.organizations import OrganizationRepository

    return int(OrganizationRepository().create_organization(nombre, owner_id)["id"])


def _oportunidad(user_id: int, organization_id: int, licitacion_id: str) -> None:
    from services.pursuits import create_pursuit
    from shared.dto import PursuitCreate

    create_pursuit(
        user_id, PursuitCreate(licitacion_id=licitacion_id, organization_id=organization_id)
    )


def test_sin_credenciales_no_hay_diff(client):
    assert client.get(_URL).status_code == 401


def test_la_ultima_visita_es_la_de_quien_pregunta(client):
    """Ana y Bea siguen lo mismo y son del mismo equipo, pero Ana ya vio el
    cambio y Bea no.

    Si la marca se leyera sin acotar por usuario, la lectura reciente de Ana
    le escondería a Bea un cambio que nunca vio. Comparten equipo a propósito:
    con dos usuarias sin organización en común, una marca compartida entre
    compañeros de equipo daría el mismo resultado que la correcta. Cada una
    tiene además una lectura anterior: con una sola, la primera y la última
    visita coinciden y el test no distinguiría ``MAX(read_at)`` de
    ``MIN(read_at)``.

    Pedir la banda del equipo no mueve el corte: la organización decide qué
    ledger se lee, no de quién es la visita.
    """
    from db.repositories.organizations import OrganizationRepository

    ana_id, uk_ana, h_ana = _usuario("ana-visita@example.test")
    bea_id, uk_bea, h_bea = _usuario("bea-visita@example.test")
    equipo = _equipo(ana_id, "Equipo de Ana y Bea")
    OrganizationRepository().add_membership(equipo, bea_id, "member")
    _licitacion("RUTA-COMPARTIDA")
    _seguir(uk_ana, "RUTA-COMPARTIDA")
    _seguir(uk_bea, "RUTA-COMPARTIDA")
    _cambio("RUTA-COMPARTIDA", cuando=_iso(days=3))
    visita_ana = _iso(days=1)
    visita_bea = _iso(days=5)
    _visto(uk_ana, cuando=_iso(days=6))
    _visto(uk_ana, cuando=visita_ana)
    _visto(uk_bea, cuando=_iso(days=8))
    _visto(uk_bea, cuando=visita_bea)

    diff_ana = client.get(_URL, headers=h_ana)
    diff_bea = client.get(_URL, headers=h_bea)

    assert diff_ana.status_code == diff_bea.status_code == 200
    assert diff_ana.json()["desde"] == visita_ana
    assert diff_ana.json()["items"] == []
    assert diff_bea.json()["desde"] == visita_bea
    assert [i["licitacion_id"] for i in diff_bea.json()["items"]] == ["RUTA-COMPARTIDA"]
    for cabeceras, visita in ((h_ana, visita_ana), (h_bea, visita_bea)):
        con_equipo = client.get(_URL, params={"organization_id": equipo}, headers=cabeceras)
        assert con_equipo.status_code == 200
        assert con_equipo.json()["desde"] == visita


def test_lo_que_sigue_otro_usuario_no_entra_en_mi_diff(client):
    _, _, h_ana = _usuario("ana-seguidos@example.test")
    _, uk_bea, _ = _usuario("bea-seguidos@example.test")
    _licitacion("RUTA-DE-BEA")
    _seguir(uk_bea, "RUTA-DE-BEA")
    _cambio("RUTA-DE-BEA", cuando=_iso(hours=2))

    respuesta = client.get(_URL, headers=h_ana)

    assert respuesta.status_code == 200
    assert respuesta.json()["items"] == []


def test_la_banda_del_equipo_exige_pertenecer_a_el(client):
    """El ledger se filtra por la organización pedida; sin comprobar la
    membresía, bastaría adivinar un id para leer el pipeline de otro equipo.

    Ana tiene organización personal y un equipo propio, como cualquier usuario
    real: el 403 tiene que venir de no ser miembro de **ésa**, no de no ser
    miembro de ninguna.
    """
    from db.repositories.organizations import OrganizationRepository

    ana_id, _, h_ana = _usuario("ana-intrusa@example.test")
    bea_id, _, _ = _usuario("bea-duena@example.test")
    OrganizationRepository().ensure_personal_organization(ana_id)
    org_ana = _equipo(ana_id, "Equipo de Ana")
    org_bea = _equipo(bea_id, "Equipo de Bea")
    _licitacion("RUTA-PIPELINE-BEA")
    _oportunidad(bea_id, org_bea, "RUTA-PIPELINE-BEA")

    ajena = client.get(_URL, params={"organization_id": org_bea}, headers=h_ana)
    propia = client.get(_URL, params={"organization_id": org_ana}, headers=h_ana)

    assert ajena.status_code == 403
    # Contraprueba: con su propio equipo la misma petición pasa, así que el 403
    # es por la organización pedida y no por la forma de la petición.
    assert propia.status_code == 200


def test_la_banda_del_equipo_llega_solo_si_se_pide_y_solo_la_propia(client):
    """Ana tiene movimiento en su organización personal y en su equipo.

    Sin el del personal, una ruta que resolviera «la organización por
    defecto» cuando falta el parámetro devolvería igualmente una banda vacía
    y el test no la distinguiría de la que no resuelve nada.
    """
    from db.repositories.organizations import OrganizationRepository

    ana_id, _, h_ana = _usuario("ana-equipo@example.test")
    bea_id, _, _ = _usuario("bea-equipo@example.test")
    org_personal_ana = int(OrganizationRepository().ensure_personal_organization(ana_id)["id"])
    org_ana = _equipo(ana_id, "Equipo de Ana")
    org_bea = _equipo(bea_id, "Equipo de Bea")
    _licitacion("RUTA-EQ-PERSONAL")
    _licitacion("RUTA-EQ-ANA")
    _licitacion("RUTA-EQ-BEA")
    _oportunidad(ana_id, org_personal_ana, "RUTA-EQ-PERSONAL")
    _oportunidad(ana_id, org_ana, "RUTA-EQ-ANA")
    _oportunidad(bea_id, org_bea, "RUTA-EQ-BEA")

    sin_equipo = client.get(_URL, headers=h_ana)
    con_equipo = client.get(_URL, params={"organization_id": org_ana}, headers=h_ana)

    assert sin_equipo.status_code == con_equipo.status_code == 200
    # `organization_id` ausente es «sólo lo mío», no «mi organización por
    # defecto»: ni siquiera la oportunidad de su organización personal.
    assert sin_equipo.json()["items"] == []
    items = con_equipo.json()["items"]
    assert [(i["subtipo"], i["licitacion_id"]) for i in items] == [("pursuit", "RUTA-EQ-ANA")]


def test_el_limite_de_la_query_llega_al_servicio(client):
    """La banda del Resumen pide pocas líneas; si la ruta ignorara ``limit``,
    serviría siempre las 40 por defecto. Se piden 2 de 3 y tienen que ser las
    dos más recientes."""
    _, uk_ana, h_ana = _usuario("ana-limite@example.test")
    for horas in (1, 2, 3):
        id_externo = f"RUTA-LIMITE-{horas}H"
        _licitacion(id_externo)
        _seguir(uk_ana, id_externo)
        _cambio(id_externo, cuando=_iso(hours=horas))

    respuesta = client.get(_URL, params={"limit": 2}, headers=h_ana)

    assert respuesta.status_code == 200
    assert [i["licitacion_id"] for i in respuesta.json()["items"]] == [
        "RUTA-LIMITE-1H",
        "RUTA-LIMITE-2H",
    ]


@pytest.mark.parametrize("limite", [0, 101], ids=["cero", "mas_de_cien"])
def test_un_limite_fuera_de_rango_es_422(client, limite):
    """``limit`` llega al ``LIMIT`` de las consultas del historial y de los
    documentos: sin tope, un cliente podría pedirle al diff un volcado entero
    de lo seguido."""
    _, _, h_ana = _usuario("ana-limite-rango@example.test")

    respuesta = client.get(_URL, params={"limit": limite}, headers=h_ana)

    assert respuesta.status_code == 422


def test_el_diff_no_se_sirve_de_cache(client):
    """Dos peticiones seguidas pueden y deben diferir: cachear el diff sería
    esconder lo que acaba de llegar."""
    _, uk_ana, h_ana = _usuario("ana-cache@example.test")
    _licitacion("RUTA-CACHE")
    _seguir(uk_ana, "RUTA-CACHE")

    antes = client.get(_URL, headers=h_ana)
    _cambio("RUTA-CACHE", cuando=_iso(minutes=1))
    despues = client.get(_URL, headers=h_ana)

    assert antes.json()["items"] == []
    assert [i["licitacion_id"] for i in despues.json()["items"]] == ["RUTA-CACHE"]
