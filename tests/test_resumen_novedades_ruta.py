"""``GET /api/v1/analytics/resumen/novedades`` — la última visita de verdad.

Contaba contra ``users.last_login``, una columna que ninguna migración crea, y
los tests del servicio no lo veían porque sustituían ``get_user_by_id`` por un
mock que sí la traía. La línea del Resumen decía «Todo al día» siempre.

Ahora la ruta lee la misma marca que ``/resumen/desde-mi-ultima-visita``
(``notification_reads``, con el mismo tope de días). Estos tests fijan, sin
ningún mock, las tres cosas que la hacen útil: cuenta lo publicado después de
la marca, devuelve el mismo ``desde`` que la banda de arriba, y «marcar todo
como visto» lo mueve.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from db.database import connect
from services.novedades import DIAS_MAXIMOS

_URL = "/api/v1/analytics/resumen/novedades"
_URL_BANDA = "/api/v1/analytics/resumen/desde-mi-ultima-visita"


def _iso(**delta: float) -> str:
    return (datetime.now(UTC) - timedelta(**delta)).isoformat()


def _usuario(email: str) -> tuple[str, dict[str, str]]:
    """``(user_key, cabeceras)`` de un usuario con API key propia."""
    from api.auth import create_api_key
    from db.users import create_user
    from shared.identity import user_key_from_email

    user_id = create_user(
        email=email,
        password_hash="test-hash",  # pragma: allowlist secret
        display_name=email.split("@")[0],
    )
    clave = create_api_key(f"novedades-{user_id}", scopes="*", user_id=user_id)
    return user_key_from_email(email, user_id), {"X-API-Key": clave}


def _publicada(id_externo: str, **hace: float) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, estado, fecha_publicacion, "
            "fecha_extraccion) VALUES (%s, %s, 'PUB', %s, %s)",
            (id_externo, f"Expediente {id_externo}", _iso(**hace), _iso(**hace)),
        )


def _visto(user_key: str, *, cuando: str) -> None:
    """Una lectura de la campana: es lo que la ruta toma como última visita."""
    with connect() as c:
        c.execute(
            "INSERT INTO notification_reads (user_key, notification_id, read_at) "
            "VALUES (%s, %s, %s)",
            (user_key, f"leida-{cuando}", cuando),
        )


def test_sin_credenciales_no_hay_novedades(client):
    assert client.get(_URL).status_code == 401


def test_cuenta_lo_publicado_desde_la_ultima_visita(client):
    uk, cabeceras = _usuario("nov-cuenta@example.test")
    _publicada("NOV-NUEVA", days=1)
    _publicada("NOV-VIEJA", days=5)
    visita = _iso(days=3)
    _visto(uk, cuando=visita)

    respuesta = client.get(_URL, headers=cabeceras)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["count"] == 1
    assert [fila["id_externo"] for fila in cuerpo["sample"]] == ["NOV-NUEVA"]
    assert cuerpo["desde"] == visita


def test_el_corte_es_el_de_la_banda_de_arriba(client):
    """Las dos bandas del Resumen dicen la misma última visita.

    Con dos cortes distintos la pantalla afirmaba dos últimas visitas a la vez.
    Se comprueba con una visita reciente y con una anterior al tope, que es
    donde las dos reglas podrían separarse.
    """
    uk_reciente, h_reciente = _usuario("nov-reciente@example.test")
    _visto(uk_reciente, cuando=_iso(days=2))
    uk_antigua, h_antigua = _usuario("nov-antigua@example.test")
    _visto(uk_antigua, cuando=_iso(days=DIAS_MAXIMOS + 30))

    for cabeceras in (h_reciente, h_antigua):
        novedades = client.get(_URL, headers=cabeceras).json()
        banda = client.get(_URL_BANDA, headers=cabeceras).json()
        assert novedades["desde"][:16] == banda["desde"][:16]


def test_sin_ultima_visita_mira_el_tope_en_vez_de_decir_todo_al_dia(client):
    """Quien no tiene marca no está «al día»: se le cuenta la ventana máxima."""
    _, cabeceras = _usuario("nov-primera@example.test")
    _publicada("NOV-DENTRO", days=2)
    _publicada("NOV-FUERA", days=DIAS_MAXIMOS + 6)

    cuerpo = client.get(_URL, headers=cabeceras).json()

    assert cuerpo["count"] == 1
    assert [fila["id_externo"] for fila in cuerpo["sample"]] == ["NOV-DENTRO"]
    corte = datetime.fromisoformat(cuerpo["desde"])
    esperado = datetime.now(UTC) - timedelta(days=DIAS_MAXIMOS)
    assert abs(corte - esperado) < timedelta(minutes=5)


def test_marcar_todo_como_visto_mueve_el_corte(client):
    uk, cabeceras = _usuario("nov-visto@example.test")
    _publicada("NOV-HOY", hours=1)
    _visto(uk, cuando=_iso(days=1))
    assert client.get(_URL, headers=cabeceras).json()["count"] == 1

    assert client.post(f"{_URL_BANDA}/visto", headers=cabeceras).status_code == 200

    despues = client.get(_URL, headers=cabeceras).json()
    assert despues["count"] == 0
    assert datetime.fromisoformat(despues["desde"]) > datetime.now(UTC) - timedelta(minutes=5)


def test_la_marca_de_otro_usuario_no_cuenta(client):
    """Ana ya lo vio todo; Bea no. El corte es por principal."""
    uk_ana, h_ana = _usuario("nov-ana@example.test")
    _, h_bea = _usuario("nov-bea@example.test")
    _publicada("NOV-COMPARTIDA", hours=6)
    _visto(uk_ana, cuando=_iso(hours=1))

    assert client.get(_URL, headers=h_ana).json()["count"] == 0
    assert client.get(_URL, headers=h_bea).json()["count"] == 1
