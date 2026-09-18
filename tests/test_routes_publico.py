"""La superficie pública responde **sin autenticación** y no filtra de más.

Lo que se fija aquí es lo que distingue estas rutas del resto de la API: que un
visitante anónimo obtiene 200 (si esto se rompiera, Google indexaría un muro de
login), que los 404 son indistinguibles entre sí, y que la respuesta no arrastra
ni un campo del pipeline propio.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.routes.publico import _a_dto
from db.repositories.publico import refrescar_vista_canonicas
from shared.dto import LicitacionPublica, LotePublico
from shared.public_ref import codificar_ref

_TITULO_LARGO = "Servicio de mantenimiento de sistemas"

#: (id, ccaa, cpv, importe)
_FILAS = (
    ("R-01", "Comunidad de Madrid", "72000000", 100000.0),
    ("R-02", "Comunidad de Madrid", "72000000", 200000.0),
    ("R-03", "Comunidad de Madrid", "72000000", 300000.0),
    ("R-04", "Castilla y León", "48000000", 400000.0),
)


@pytest.fixture()
def corpus(api_db):
    import db.database as db_mod

    with db_mod.connect() as c:
        for id_externo, ccaa, cpv, importe in _FILAS:
            c.execute(
                "INSERT INTO licitaciones (id_externo, titulo, estado, fecha_publicacion, "
                "fecha_extraccion, importe, ccaa, cpv, url, fuente) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    id_externo,
                    _TITULO_LARGO,
                    "PUB",
                    "2026-08-01",
                    "2026-08-01T00:00:00+00:00",
                    importe,
                    ccaa,
                    cpv,
                    f"https://contrataciondelestado.es/{id_externo}",
                    "placsp",
                ),
            )
        # Título corto: existe en base, pero no es publicable.
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, estado, fecha_publicacion, "
            "fecha_extraccion, importe) VALUES (%s,%s,%s,%s,%s,%s)",
            ("R-99", "Obras", "PUB", "2026-08-01", "2026-08-01T00:00:00+00:00", 1.0),
        )
    # La superficie pública lee de la vista materializada (revisión v94), que no
    # se entera de un INSERT: hay que refrescarla o el test vería el corpus
    # vacío. En producción lo hace el paso `aggregates_precompute` al final de
    # cada pasada de ingesta.
    refrescar_vista_canonicas()
    return db_mod


# ---------------------------------------------------------------------------
# Sin autenticación
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ruta",
    [
        "/api/v1/publico/licitaciones",
        "/api/v1/publico/hubs",
        "/api/v1/publico/sitemap/resumen",
        "/api/v1/publico/sitemap/entradas",
    ],
)
def test_las_rutas_publicas_no_piden_credenciales(client, corpus, ruta):
    """Si esto devolviera 401, Google indexaría un muro de login."""
    assert client.get(ruta).status_code == 200


def test_la_ficha_publica_tampoco_pide_credenciales(client, corpus):
    respuesta = client.get(f"/api/v1/publico/licitaciones/{codificar_ref('R-01')}")

    assert respuesta.status_code == 200


def test_todas_declaran_cache(client, corpus):
    """El tráfico anónimo tiene que absorberse en el CDN, no en Postgres."""
    for ruta in (
        "/api/v1/publico/licitaciones",
        "/api/v1/publico/hubs",
        "/api/v1/publico/sitemap/resumen",
        "/api/v1/publico/sitemap/entradas",
        f"/api/v1/publico/licitaciones/{codificar_ref('R-01')}",
    ):
        assert client.get(ruta).headers.get("Cache-Control"), ruta


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------


def test_el_listado_devuelve_total_real_y_no_el_de_la_pagina(client, corpus):
    cuerpo = client.get("/api/v1/publico/licitaciones?limit=2").json()

    assert len(cuerpo["items"]) == 2
    assert cuerpo["total"] == 4
    assert cuerpo["limit"] == 2
    assert cuerpo["offset"] == 0


def test_el_listado_filtra_por_slug_y_por_cpv(client, corpus):
    madrid = client.get("/api/v1/publico/licitaciones?ccaa=comunidad-de-madrid").json()
    cpv48 = client.get("/api/v1/publico/licitaciones?cpv=48").json()

    assert madrid["total"] == 3
    assert cpv48["total"] == 1


def test_el_listado_no_incluye_lo_que_no_es_publicable(client, corpus):
    cuerpo = client.get("/api/v1/publico/licitaciones?limit=100").json()

    assert "R-99" not in {item["expediente"] for item in cuerpo["items"]}


@pytest.mark.parametrize(
    "query",
    [
        "ccaa=Comunidad de Madrid",  # el slug es [a-z0-9-], no el nombre
        "ccaa=../../etc",
        "cpv=abc",
        "cpv=1",  # mínimo dos dígitos
        "limit=0",
        "limit=101",
        "offset=-1",
    ],
)
def test_los_parametros_invalidos_se_rechazan_en_el_borde(client, corpus, query):
    assert client.get(f"/api/v1/publico/licitaciones?{query}").status_code == 422


# ---------------------------------------------------------------------------
# Ficha
# ---------------------------------------------------------------------------


def test_la_ficha_expone_la_referencia_opaca_y_el_expediente(client, corpus):
    ref = codificar_ref("R-01")
    cuerpo = client.get(f"/api/v1/publico/licitaciones/{ref}").json()

    assert cuerpo["ref"] == ref
    assert cuerpo["expediente"] == "R-01"
    assert cuerpo["titulo"] == _TITULO_LARGO


def test_la_ficha_no_filtra_nada_del_pipeline_propio(client, corpus):
    cuerpo = client.get(f"/api/v1/publico/licitaciones/{codificar_ref('R-01')}").json()

    prohibidas = {
        "ml_proba",
        "ml_proba_max",
        "ml_tecnologias",
        "ml_tech_principal",
        "tecnologia",
        "raw_keywords",
        "filter_version",
        "inclusion_reason",
        "analysis_universe",
        "peso_precio_pct",
    }
    assert prohibidas.isdisjoint(cuerpo.keys())


def test_la_ficha_trae_fuente_y_fecha_que_exige_la_ley_37_2007(client, corpus):
    cuerpo = client.get(f"/api/v1/publico/licitaciones/{codificar_ref('R-01')}").json()

    assert cuerpo["url"]
    assert cuerpo["actualizado"]
    assert cuerpo["fuente"]


def test_la_ficha_incluye_sus_lotes_ordenados(client, corpus):
    with corpus.connect() as c:
        for numero in (2, 1):
            c.execute(
                "INSERT INTO lotes "
                "(licitacion_id, numero, titulo, cpv, importe, fecha_extraccion) "
                "VALUES (%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)",
                ("R-01", str(numero), f"Lote {numero}", "72000000", 1000.0),
            )

    cuerpo = client.get(f"/api/v1/publico/licitaciones/{codificar_ref('R-01')}").json()

    assert [lote["numero"] for lote in cuerpo["lotes"]] == ["1", "2"]


def test_la_ficha_lleva_cada_columna_a_su_campo(client, corpus):
    """El cuerpo entero, campo a campo, con un valor distinto en cada columna.

    El mapeo de ``_a_dto`` es explícito a propósito, y mypy comprueba que cada
    columna cabe en su campo, pero no que vaya al suyo: ``fecha_inicio`` y
    ``fecha_fin`` son del mismo tipo, igual que ``provincia`` y ``ccaa`` o
    ``tipo_contrato`` y ``procedimiento``. Con un valor distinto en cada
    columna, un cruce cambia el cuerpo. ``fuente`` va a ``ted`` para que el
    ``or "placsp"`` de la ruta no pueda acertar por casualidad.
    """
    with corpus.connect() as c:
        c.execute(
            "UPDATE licitaciones SET descripcion = %s, organo_contratacion = %s, importe = %s, "
            "moneda = %s, cpv = %s, tipo_contrato = %s, estado = %s, procedimiento = %s, "
            "tramitacion = %s, fecha_publicacion = %s, fecha_limite = %s, fecha_inicio = %s, "
            "fecha_fin = %s, duracion_valor = %s, duracion_unidad = %s, provincia = %s, "
            "ccaa = %s, nuts_code = %s, url = %s, fuente = %s, fecha_extraccion = %s "
            "WHERE id_externo = %s",
            (
                "Mantenimiento evolutivo del ERP municipal",
                "Ayuntamiento de Segovia",
                123456.5,
                "EUR",
                "72267000",
                "2",
                "ADJ",
                "9",
                "1",
                "2026-08-03",
                "2026-09-15T13:00:00+00:00",
                "2026-10-01",
                "2027-09-30",
                18.0,
                "MON",
                "Segovia",
                "Castilla y León",
                "ES416",
                "https://example.org/anuncio/R-01",
                "ted",
                "2026-08-04T06:30:00+00:00",
                "R-01",
            ),
        )
        c.execute(
            "INSERT INTO lotes "
            "(licitacion_id, numero, titulo, cpv, importe, fecha_limite, fecha_extraccion) "
            "VALUES (%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)",
            (
                "R-01",
                "1",
                "Soporte de segundo nivel",
                "72611000",
                5000.5,
                "2026-09-16T10:00:00+02:00",
            ),
        )

    respuesta = client.get(f"/api/v1/publico/licitaciones/{codificar_ref('R-01')}")

    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "ref": codificar_ref("R-01"),
        "expediente": "R-01",
        "titulo": _TITULO_LARGO,
        "descripcion": "Mantenimiento evolutivo del ERP municipal",
        "organo_contratacion": "Ayuntamiento de Segovia",
        "importe": 123456.5,
        "moneda": "EUR",
        "cpv": "72267000",
        "tipo_contrato": "2",
        "estado": "ADJ",
        "procedimiento": "9",
        "tramitacion": "1",
        # Sin hora ni zona en la fuente, así que sale sin zona: no se inventa UTC.
        "fecha_publicacion": "2026-08-03T00:00:00",
        "fecha_limite": "2026-09-15T13:00:00Z",
        "fecha_inicio": "2026-10-01T00:00:00",
        "fecha_fin": "2027-09-30T00:00:00",
        "duracion_valor": 18.0,
        "duracion_unidad": "MON",
        "provincia": "Segovia",
        "ccaa": "Castilla y León",
        "nuts_code": "ES416",
        "url": "https://example.org/anuncio/R-01",
        "fuente": "ted",
        "actualizado": "2026-08-04T06:30:00Z",
        "lotes": [
            {
                "numero": "1",
                "titulo": "Soporte de segundo nivel",
                "cpv": "72611000",
                "importe": 5000.5,
                "fecha_limite": "2026-09-16T10:00:00+02:00",
            }
        ],
    }


def test_una_fecha_con_el_offset_corto_de_postgres_no_rompe_la_ficha(client, corpus):
    """``+00`` a secas es como Postgres escribe en texto un ``timestamptz``.

    El parser de pydantic lo rechaza y ``PgDateTime`` lo completa antes de
    parsear. La ruta convierte las fechas con su propio ``TypeAdapter``, que es
    un segundo sitio donde esa normalización tiene que seguir estando: sin ella,
    esta ficha sería un 500 en la superficie que rastrea Google.
    """
    with corpus.connect() as c:
        c.execute(
            "UPDATE licitaciones SET fecha_limite = %s WHERE id_externo = %s",
            ("2026-08-01 00:45:48.33444+00", "R-01"),
        )
        c.execute(
            "INSERT INTO lotes (licitacion_id, numero, fecha_limite, fecha_extraccion) "
            "VALUES (%s,%s,%s,CURRENT_TIMESTAMP)",
            ("R-01", "1", "2026-09-01 12:00:00+02"),
        )

    respuesta = client.get(f"/api/v1/publico/licitaciones/{codificar_ref('R-01')}")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["fecha_limite"] == "2026-08-01T00:45:48.334440Z"
    assert cuerpo["lotes"][0]["fecha_limite"] == "2026-09-01T12:00:00+02:00"


#: Fila válida para construir el DTO sin base: los tests de abajo solo rompen
#: una fecha cada vez.
_FILA_SIN_BASE = {
    "id_externo": "R-01",
    "titulo": _TITULO_LARGO,
    "descripcion": None,
    "organo_contratacion": None,
    "importe": 1000.0,
    "moneda": None,
    "cpv": None,
    "tipo_contrato": None,
    "estado": None,
    "procedimiento": None,
    "tramitacion": None,
    "fecha_publicacion": None,
    "fecha_limite": None,
    "fecha_inicio": None,
    "fecha_fin": None,
    "duracion_valor": None,
    "duracion_unidad": None,
    "provincia": None,
    "ccaa": None,
    "nuts_code": None,
    "url": None,
    "fuente": "placsp",
    "fecha_extraccion": "2026-08-01T00:00:00+00:00",
}

#: Fechas que el parser rechaza, una por cada camino del validador.
_FECHAS_ILEGIBLES = pytest.mark.parametrize(
    "fecha",
    [
        # Día/mes/año en vez de ISO 8601: llega al parser tal cual.
        pytest.param("31/12/2026", id="dia-mes-anio"),
        # Offset corto de Postgres con un mes imposible: `PgDateTime` completa el
        # offset antes de parsear, así que la entrada del error ya no es la
        # cadena cruda sino `...+00:00`. Solo con este caso se nota si `_fecha`
        # informa de la cadena que recibió en vez de la que vio el parser.
        pytest.param("2026-13-01 00:00:00+00", id="offset-corto-mes-imposible"),
    ],
)


@_FECHAS_ILEGIBLES
@pytest.mark.parametrize(
    ("columna", "campo"),
    [
        ("fecha_publicacion", "fecha_publicacion"),
        ("fecha_limite", "fecha_limite"),
        ("fecha_inicio", "fecha_inicio"),
        ("fecha_fin", "fecha_fin"),
        ("fecha_extraccion", "actualizado"),
    ],
)
def test_una_fecha_ilegible_dice_en_que_campo_esta(columna, campo, fecha):
    """Cuando la fuente cambia de formato, lo primero que hay que saber es dónde.

    En una página del listado —hasta 100 filas con cinco fechas cada una—, un
    ``ValidationError`` que no nombra el campo no sirve para diagnosticar. Antes
    lo garantizaba el constructor del DTO, que recibía la cadena sin convertir;
    desde que la ruta convierte las fechas antes, lo tiene que garantizar
    ``_fecha``.

    La referencia es ese mismo constructor con la misma cadena, no un mensaje
    copiado a mano: tienen que coincidir los errores enteros (campo, tipo,
    entrada, contexto) y el texto, que además lleva el nombre del modelo.
    """
    with pytest.raises(ValidationError) as del_constructor:
        LicitacionPublica(ref="x", expediente="x", titulo="x", fuente="x", **{campo: fecha})

    with pytest.raises(ValidationError) as excinfo:
        _a_dto({**_FILA_SIN_BASE, columna: fecha})

    assert excinfo.value.title == "LicitacionPublica"
    assert [error["loc"] for error in excinfo.value.errors()] == [(campo,)]
    assert excinfo.value.errors() == del_constructor.value.errors()
    assert str(excinfo.value) == str(del_constructor.value)


@_FECHAS_ILEGIBLES
def test_una_fecha_ilegible_en_un_lote_nombra_el_lote(fecha):
    """Lo mismo para la fecha del lote, que se valida con ``LotePublico``."""
    lote = {
        "numero": "1",
        "titulo": None,
        "cpv": None,
        "importe": None,
        "fecha_limite": fecha,
    }
    with pytest.raises(ValidationError) as del_constructor:
        LotePublico(numero="1", fecha_limite=fecha)

    with pytest.raises(ValidationError) as excinfo:
        _a_dto(dict(_FILA_SIN_BASE), [lote])

    assert excinfo.value.title == "LotePublico"
    assert [error["loc"] for error in excinfo.value.errors()] == [("fecha_limite",)]
    assert excinfo.value.errors() == del_constructor.value.errors()
    assert str(excinfo.value) == str(del_constructor.value)


@pytest.mark.parametrize(
    ("ref", "motivo"),
    [
        ("!!!!", "referencia ilegible"),
        ("A" * 513, "referencia por encima del tope de longitud"),
        (codificar_ref("NO-EXISTE"), "expediente inexistente"),
        (codificar_ref("R-99"), "existe pero no es publicable"),
    ],
)
def test_los_404_son_indistinguibles_entre_si(client, corpus, ref, motivo):
    """Distinguirlos filtraría qué expedientes existen pero se ocultan."""
    respuesta = client.get(f"/api/v1/publico/licitaciones/{ref}")

    assert respuesta.status_code == 404, motivo
    assert respuesta.json()["detail"] == "No encontrada."


# ---------------------------------------------------------------------------
# Hubs
# ---------------------------------------------------------------------------


def test_los_hubs_aplican_el_umbral_de_volumen(client, corpus):
    cuerpo = client.get("/api/v1/publico/hubs").json()

    # Madrid tiene 3 (llega al mínimo); Castilla y León, 1.
    assert [h["slug"] for h in cuerpo["ccaa"]] == ["comunidad-de-madrid"]
    assert cuerpo["ccaa"][0]["nombre"] == "Comunidad de Madrid"
    assert cuerpo["ccaa"][0]["total"] == 3
    assert [h["codigo"] for h in cuerpo["cpv"]] == ["72000000"]


# ---------------------------------------------------------------------------
# Sitemap
# ---------------------------------------------------------------------------


def test_el_resumen_cuenta_solo_lo_publicable(client, corpus):
    assert client.get("/api/v1/publico/sitemap/resumen").json() == {
        "total": 4,
        "actualizado": "2026-08-01T00:00:00+00:00",
    }


def test_el_resumen_publica_la_fecha_del_ultimo_expediente(client, corpus):
    """Es la prueba de frescura que la landing enseña bajo el hero.

    Tiene que salir del corpus **publicable**: R-99 no llega a página, así que
    su fecha no puede acreditar que haya entrado nada nuevo.
    """
    with corpus.connect() as c:
        c.execute(
            "UPDATE licitaciones SET fecha_extraccion = %s WHERE id_externo = %s",
            ("2027-01-01T00:00:00+00:00", "R-99"),
        )
        c.execute(
            "UPDATE licitaciones SET fecha_extraccion = %s WHERE id_externo = %s",
            ("2026-08-14T06:00:00+00:00", "R-02"),
        )
    # Mismo motivo que en el fixture `corpus`: la vista materializada (v94) no
    # se entera de un UPDATE, así que sin refrescar el endpoint publicaría la
    # fecha sembrada y el test mediría la vista rancia en vez de estas dos
    # actualizaciones. En producción lo hace `aggregates_precompute`.
    refrescar_vista_canonicas()

    cuerpo = client.get("/api/v1/publico/sitemap/resumen").json()

    assert cuerpo["actualizado"] == "2026-08-14T06:00:00+00:00"


def test_las_entradas_traen_lo_justo_para_url_y_lastmod(client, corpus):
    entradas = client.get("/api/v1/publico/sitemap/entradas?limit=10").json()

    assert len(entradas) == 4
    assert set(entradas[0]) == {"ref", "ccaa", "titulo", "actualizado"}
    assert entradas[0]["ref"] == codificar_ref("R-01")


def test_la_particion_del_sitemap_es_estable(client, corpus):
    """Mismo tramo, mismas URLs: si no, Search Console reporta cobertura rota."""
    primera = client.get("/api/v1/publico/sitemap/entradas?offset=0&limit=2").json()
    otra_vez = client.get("/api/v1/publico/sitemap/entradas?offset=0&limit=2").json()
    segunda = client.get("/api/v1/publico/sitemap/entradas?offset=2&limit=2").json()

    assert [e["ref"] for e in primera] == [e["ref"] for e in otra_vez]
    assert not {e["ref"] for e in primera} & {e["ref"] for e in segunda}


def test_un_tramo_mas_alla_del_final_devuelve_lista_vacia(client, corpus):
    assert client.get("/api/v1/publico/sitemap/entradas?offset=9999&limit=10").json() == []


@pytest.mark.parametrize("query", ["limit=0", "limit=50001", "offset=-1"])
def test_el_sitemap_rechaza_tramos_imposibles(client, corpus, query):
    assert client.get(f"/api/v1/publico/sitemap/entradas?{query}").status_code == 422
