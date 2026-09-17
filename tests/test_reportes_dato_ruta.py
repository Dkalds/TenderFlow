"""``POST /api/v1/licitaciones/{id_externo:path}/reportes`` — «este dato está mal».

La ruta es la única entrada de F6.2 y tiene tres decisiones que un cliente
nota: el tipo es un catálogo cerrado (fuera de él es 422, no un reporte en el
limbo), el expediente **no** tiene que existir (la corrección más valiosa es la
de una fila que no debería estar) y el acuse nombra la cola de
``COLA_POR_TIPO``. Esa cola es hoy sólo la etiqueta del acuse: todo reporte se
guarda en ``ml_feedback`` y lo único que lo cuenta es la vista de Calidad (el
anti-join de active learning sólo lo excluye), así que la persistencia se
comprueba ahí y no en ``dedupe`` ni en ``empresas``.
"""

from __future__ import annotations

from collections.abc import Iterator
from urllib.parse import quote

import pytest

from db.database import connect


@pytest.fixture()
def autor(api_db) -> tuple[int, dict[str, str]]:
    """``(user_id, cabeceras)`` de un usuario real con su API key.

    El reporte guarda el autor; la key sin vincular del ``conftest`` usa su
    propio id como ``user_id`` postizo, que no existe en ``users``.
    """
    from api.auth import create_api_key
    from db.users import create_user

    user_id = create_user(
        email="reportes-ruta@example.test",
        password_hash="test-hash",  # pragma: allowlist secret
    )
    return user_id, {"X-API-Key": create_api_key("reportes", scopes="*", user_id=user_id)}


@pytest.fixture()
def cache_de_analytics_vacia() -> Iterator[None]:
    """``/analytics/quality`` se cachea 600 s con una clave que no lleva el
    ``user_key``, en una caché de proceso que nadie vacía entre tests: sin
    esto, una respuesta que otro test haya dejado se serviría en lugar de la
    de este corpus. Se vacía también al salir para no envenenar a los demás."""
    from shared.cache import reset_cache

    reset_cache("analytics")
    yield
    reset_cache("analytics")


def _url(id_externo: str) -> str:
    return f"/api/v1/licitaciones/{quote(id_externo, safe='/')}/reportes"


def _reportes() -> list[tuple[str, str, str, int | None]]:
    with connect() as c:
        return [
            (str(r[0]), str(r[1]), str(r[2]), r[3])
            for r in c.execute(
                "SELECT expediente, source, nota, user_id FROM ml_feedback ORDER BY id"
            ).fetchall()
        ]


def test_sin_credenciales_no_se_acepta_ni_se_guarda(client):
    respuesta = client.post(_url("REP-ANONIMO"), json={"tipo": "ccaa"})

    assert respuesta.status_code == 401
    assert _reportes() == []


@pytest.mark.parametrize(
    "cuerpo",
    [{"tipo": "modulo_sap"}, {"tipo": "CCAA"}, {"comentario": "falta el tipo"}, {"tipo": None}],
    ids=["fuera_de_catalogo", "mayusculas", "sin_tipo", "tipo_nulo"],
)
def test_un_tipo_fuera_del_catalogo_es_422_y_no_deja_rastro(client, autor, cuerpo):
    """Un tipo libre no se podría agregar en la vista de Calidad: se rechaza
    en la frontera en vez de guardarse como ``reporte:<cualquier cosa>``."""
    _, cabeceras = autor

    respuesta = client.post(_url("REP-TIPO"), json=cuerpo, headers=cabeceras)

    assert respuesta.status_code == 422
    assert _reportes() == []


def test_un_comentario_de_mas_de_2000_caracteres_es_422(client, autor):
    _, cabeceras = autor

    respuesta = client.post(
        _url("REP-LARGO"), json={"tipo": "otro", "comentario": "x" * 2001}, headers=cabeceras
    )

    assert respuesta.status_code == 422
    assert _reportes() == []


@pytest.mark.parametrize(
    ("tipo", "cola"),
    [
        ("tecnologia", "ml_feedback"),
        ("ccaa", "ml_feedback"),
        ("importe", "ml_feedback"),
        ("otro", "ml_feedback"),
        ("duplicado", "dedupe"),
        ("adjudicatario", "empresas"),
    ],
)
def test_el_acuse_nombra_la_cola_y_el_reporte_queda_guardado(client, autor, tipo, cola):
    """El acuse nombra la cola, para que la consola no conteste con un
    «gracias» vacío; y la fila, sea cual sea la cola, va a ``ml_feedback`` con
    el ``source`` por el que la vista de Calidad la cuenta."""
    user_id, cabeceras = autor

    respuesta = client.post(
        _url("REP-COLA"),
        json={"tipo": tipo, "comentario": "  revisadlo  "},
        headers=cabeceras,
    )

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert (cuerpo["id_externo"], cuerpo["tipo"], cuerpo["cola"]) == ("REP-COLA", tipo, cola)
    assert cuerpo["created_at"]
    assert _reportes() == [("REP-COLA", f"reporte:{tipo}", "revisadlo", user_id)]


def test_un_expediente_que_no_existe_tambien_se_puede_reportar(client, autor):
    """Un 404 aquí convertiría en error del usuario el reporte más valioso:
    el de una fila que no debería estar en el corpus."""
    user_id, cabeceras = autor
    with connect() as c:
        assert c.execute("SELECT COUNT(*) FROM licitaciones").fetchone()[0] == 0

    respuesta = client.post(_url("NO-EXISTE-2026"), json={"tipo": "duplicado"}, headers=cabeceras)

    assert respuesta.status_code == 201
    assert _reportes() == [("NO-EXISTE-2026", "reporte:duplicado", "", user_id)]


def test_un_id_externo_con_barras_se_reporta_entero(client, autor):
    """Los expedientes de PLACSP llevan ``/``; con el conversor por defecto la
    ruta no casaría y el reporte acabaría en un 404 de enrutado."""
    user_id, cabeceras = autor
    id_externo = "PA-S 2026/000058"

    respuesta = client.post(_url(id_externo), json={"tipo": "importe"}, headers=cabeceras)

    assert respuesta.status_code == 201
    assert respuesta.json()["id_externo"] == id_externo
    assert _reportes() == [(id_externo, "reporte:importe", "", user_id)]


@pytest.mark.usefixtures("cache_de_analytics_vacia")
def test_lo_reportado_aparece_en_la_vista_de_calidad(client, autor):
    """El viaje completo: lo que entra por la ficha es lo que el equipo de
    datos ve contado en Calidad, con el tipo limpio y sin el prefijo.

    Con una licitación en el corpus, porque ``get_quality`` tiene una rama
    aparte para la tabla vacía que en producción no corre nunca.
    """
    _, cabeceras = autor
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_publicacion, fecha_extraccion) "
            "VALUES ('REP-V-1', 'Expediente reportado', '2026-09-10', '2026-09-10')"
        )
    for id_externo, tipo in (
        ("REP-V-1", "duplicado"),
        ("REP-V-2", "duplicado"),
        ("REP-V-3", "ccaa"),
    ):
        assert (
            client.post(_url(id_externo), json={"tipo": tipo}, headers=cabeceras).status_code == 201
        )

    calidad = client.get("/api/v1/analytics/quality", headers=cabeceras)

    assert calidad.status_code == 200
    assert calidad.json()["total_records"] == 1
    assert calidad.json()["reportes_por_tipo"] == {"duplicado": 2, "ccaa": 1}
