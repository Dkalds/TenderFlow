"""La superficie pública responde **sin autenticación** y no filtra de más.

Lo que se fija aquí es lo que distingue estas rutas del resto de la API: que un
visitante anónimo obtiene 200 (si esto se rompiera, Google indexaría un muro de
login), que los 404 son indistinguibles entre sí, y que la respuesta no arrastra
ni un campo del pipeline propio.
"""

from __future__ import annotations

import pytest

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
    assert client.get("/api/v1/publico/sitemap/resumen").json() == {"total": 4}


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
