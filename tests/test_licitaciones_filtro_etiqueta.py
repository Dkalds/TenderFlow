"""El listado de expedientes filtra por etiqueta de la organización, en servidor.

Detalle filtraba por etiqueta **la página cargada**: `GET /licitaciones` no
aceptaba el parámetro, así que el filtro escondía filas de las cincuenta que la
tabla ya tenía y nunca traía las etiquetadas que estaban en la página doce. Con
el filtro en el `WHERE`, el total y las páginas hablan del conjunto etiquetado
entero.

Lo que se fija:

- el listado por offset, el cursor y la rama de texto libre devuelven el mismo
  universo con la etiqueta puesta (la rama FTS reescribe el `WHERE` a mano, y
  así es como un filtro se queda atrás sin que nadie lo note);
- la etiqueta es de la organización de quien pregunta: la de otra no trae nada,
  y pedir la organización ajena es un 403;
- sin `etiqueta`, `organization_id` no cambia el listado.
"""

from __future__ import annotations

from shared.dto import FiltrosLicitacion
from tests.escenarios import Sesion, abrir_sesion, sembrar_licitacion


def _sembrar() -> None:
    # `tecnologia` puesta: el listado solo enseña expedientes clasificados.
    sembrar_licitacion("EXP-ET-1", "Soporte SAP de nóminas", tecnologia="SAP")
    sembrar_licitacion("EXP-ET-2", "Licencias SAP para hacienda", tecnologia="SAP")
    sembrar_licitacion("EXP-ET-3", "Migración de Oracle a la nube", tecnologia="ORACLE")


def _etiquetar(sesion: Sesion, nombre: str, *ids: str) -> int:
    creada = sesion.post(
        "/etiquetas",
        params={"organization_id": sesion.organization_id},
        json={"nombre": nombre, "color": "#2563eb"},
    )
    assert creada.status_code == 201, creada.text
    etiqueta_id = int(creada.json()["id"])
    for id_externo in ids:
        aplicada = sesion.post(
            "/etiquetas/aplicar",
            params={"organization_id": sesion.organization_id},
            json={"etiqueta_id": etiqueta_id, "objeto_tipo": "favorito", "objeto_id": id_externo},
        )
        assert aplicada.status_code == 200, aplicada.text
    return etiqueta_id


def _ids(respuesta) -> set[str]:
    assert respuesta.status_code == 200, respuesta.text
    return {item["id_externo"] for item in respuesta.json()["items"]}


def test_cursor_offset_y_texto_libre_filtran_igual_por_etiqueta(client, api_db) -> None:
    _sembrar()
    ana = abrir_sesion("ana.etiquetas@example.com", client)
    q4 = _etiquetar(ana, "Q4", "EXP-ET-1", "EXP-ET-3")
    filtro = {"etiqueta": q4, "organization_id": ana.organization_id}

    cursor = ana.get("/licitaciones/cursor", params={**filtro, "with_total": "true"})
    assert _ids(cursor) == {"EXP-ET-1", "EXP-ET-3"}
    # El total es el del conjunto etiquetado, no el del corpus: es lo que el pie
    # de Detalle pinta como «de N».
    assert cursor.json()["total"] == 2

    assert _ids(ana.get("/licitaciones", params=filtro)) == {"EXP-ET-1", "EXP-ET-3"}
    # Texto libre + etiqueta: la rama FTS también acota por la etiqueta.
    assert _ids(ana.get("/licitaciones", params={**filtro, "q": "SAP"})) == {"EXP-ET-1"}
    assert _ids(ana.get("/licitaciones/cursor", params={**filtro, "q": "SAP"})) == {"EXP-ET-1"}


def test_solo_cuentan_las_etiquetas_puestas_a_expedientes(client, api_db) -> None:
    """Una oportunidad con el mismo texto de id no es un expediente etiquetado."""
    _sembrar()
    ana = abrir_sesion("ana.tipos@example.com", client)
    q4 = _etiquetar(ana, "Q4")
    aplicada = ana.post(
        "/etiquetas/aplicar",
        params={"organization_id": ana.organization_id},
        json={"etiqueta_id": q4, "objeto_tipo": "oportunidad", "objeto_id": "EXP-ET-2"},
    )
    assert aplicada.status_code == 200, aplicada.text

    respuesta = ana.get(
        "/licitaciones/cursor", params={"etiqueta": q4, "organization_id": ana.organization_id}
    )
    assert _ids(respuesta) == set()


def test_la_etiqueta_de_otra_organizacion_no_trae_nada(client, api_db) -> None:
    _sembrar()
    ana = abrir_sesion("ana.aislada@example.com", client)
    q4 = _etiquetar(ana, "Q4", "EXP-ET-1")

    from fastapi.testclient import TestClient

    from api.app import app

    bea = abrir_sesion("bea.aislada@example.com", TestClient(app, raise_server_exceptions=True))
    # Con su propia organización, la etiqueta de Ana no casa con nada suyo.
    ajena = bea.get(
        "/licitaciones/cursor", params={"etiqueta": q4, "organization_id": bea.organization_id}
    )
    assert _ids(ajena) == set()
    # Pedir la organización de Ana es pedir datos de otro cliente.
    prohibida = bea.get(
        "/licitaciones/cursor", params={"etiqueta": q4, "organization_id": ana.organization_id}
    )
    assert prohibida.status_code == 403, prohibida.text


def test_sin_etiqueta_la_organizacion_no_cambia_el_listado(client, api_db) -> None:
    _sembrar()
    ana = abrir_sesion("ana.sin@example.com", client)

    sin_org = _ids(ana.get("/licitaciones/cursor"))
    con_org = _ids(ana.get("/licitaciones/cursor", params={"organization_id": ana.organization_id}))

    assert sin_org == con_org == {"EXP-ET-1", "EXP-ET-2", "EXP-ET-3"}


def test_una_etiqueta_sin_organizacion_no_llega_a_filtrar() -> None:
    """El repositorio no filtra por un id de etiqueta a secas: los ids son globales."""
    import pytest

    from db.repositories.licitaciones import LicitacionRepository

    with pytest.raises(ValueError, match="organización"):
        LicitacionRepository._base_filters(FiltrosLicitacion(etiqueta_id=3))
