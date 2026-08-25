"""La superficie pública publica lo que debe, y solo eso.

Tres invariantes que este repositorio tiene que sostener a la vez, y que sin
test se rompen en silencio: la proyección es una allowlist (nada del pipeline
propio se cuela), el umbral de sustancia decide **igual** en ficha, listado,
hubs y sitemap —si discreparan, Search Console lo reporta como error de
cobertura—, y el slug de comunidad que calcula Postgres coincide con el que
genera ``web/src/lib/slug.ts``.
"""

from __future__ import annotations

import pytest

from db.repositories.publico import PublicoRepository

# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------

_TITULO_LARGO = "Servicio de mantenimiento de sistemas"  # 36 caracteres, pasa el umbral
_DESCRIPCION_LARGA = "d" * 200

#: (id, titulo, descripcion, importe, ccaa, cpv)
#:
#: Los cinco primeros son publicables; los tres últimos caen por una razón
#: distinta cada uno.
_FILAS = (
    ("P-01", _TITULO_LARGO, None, 100000.0, "Comunidad de Madrid", "72000000"),
    ("P-02", _TITULO_LARGO, None, 200000.0, "Comunidad de Madrid", "72000000"),
    ("P-03", _TITULO_LARGO, None, 300000.0, "Comunidad de Madrid", "72000000"),
    ("P-04", _TITULO_LARGO, None, 400000.0, "Castilla y León", "48000000"),
    ("P-05", _TITULO_LARGO, _DESCRIPCION_LARGA, None, "Castilla y León", "48000000"),
    # Título corto: no llega a ser una página.
    ("P-06", "Obras", None, 500000.0, "Galicia", "45000000"),
    # Sin importe y con descripción por debajo del mínimo: nada que contar.
    ("P-07", _TITULO_LARGO, "corta", None, "Galicia", "45000000"),
    # Publicable en sí, pero marcado como duplicado confirmado más abajo.
    ("P-08", _TITULO_LARGO, None, 600000.0, "Galicia", "45000000"),
)

_PUBLICABLES = {"P-01", "P-02", "P-03", "P-04", "P-05"}


@pytest.fixture()
def corpus(tmp_db):
    db_mod, _ = tmp_db
    with db_mod.connect() as conn:
        for id_externo, titulo, descripcion, importe, ccaa, cpv in _FILAS:
            conn.execute(
                "INSERT INTO licitaciones (id_externo, titulo, descripcion, estado, "
                "fecha_publicacion, fecha_extraccion, importe, ccaa, cpv, url, fuente) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    id_externo,
                    titulo,
                    descripcion,
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
        conn.execute(
            "INSERT INTO licitaciones_duplicados "
            "(licitacion_id, canonical_id, confianza, status, clave_match) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("P-08", "P-01", 1.0, "confirmed", "test"),
        )
    return db_mod


@pytest.fixture()
def repo() -> PublicoRepository:
    return PublicoRepository()


# ---------------------------------------------------------------------------
# Proyección: allowlist, no SELECT *
# ---------------------------------------------------------------------------


def test_la_ficha_no_devuelve_nada_del_pipeline_propio(corpus, repo):
    """El riesgo real: reutilizar un ``SELECT *`` publicaría ml_proba el día uno."""
    ficha = repo.ficha("P-01")

    assert ficha is not None
    prohibidas = {
        "ml_proba",
        "ml_proba_max",
        "ml_tecnologias",
        "ml_tech_principal",
        "tecnologia",
        "raw_keywords",
        "filter_version",
        "classifier_model_version",
        "inclusion_reason",
        "analysis_universe",
        "peso_precio_pct",
    }
    assert prohibidas.isdisjoint(ficha.keys())


def test_la_ficha_trae_fuente_y_fecha_que_exige_la_ley_37_2007(corpus, repo):
    ficha = repo.ficha("P-01")

    assert ficha is not None
    assert ficha["url"]
    assert ficha["fecha_extraccion"] is not None


# ---------------------------------------------------------------------------
# Umbral de sustancia y duplicados
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("id_externo", sorted(_PUBLICABLES))
def test_los_publicables_tienen_ficha(corpus, repo, id_externo):
    assert repo.ficha(id_externo) is not None


@pytest.mark.parametrize(
    ("id_externo", "motivo"),
    [
        ("P-06", "título por debajo del mínimo"),
        ("P-07", "sin importe y con descripción corta"),
        ("P-08", "duplicado confirmado"),
        ("NO-EXISTE", "no existe"),
    ],
)
def test_lo_no_publicable_devuelve_none(corpus, repo, id_externo, motivo):
    """Para el visitante los cuatro casos son el mismo 404."""
    assert repo.ficha(id_externo) is None, motivo


def test_el_listado_y_el_sitemap_ven_el_mismo_universo(corpus, repo):
    """Si discreparan, Search Console lo reporta como error de cobertura."""
    del_listado = {f["id_externo"] for f in repo.listar(limite=200)}
    del_sitemap = {f["id_externo"] for f in repo.pagina_de_sitemap(desplazamiento=0, tamano=200)}

    assert del_listado == _PUBLICABLES
    assert del_sitemap == _PUBLICABLES
    assert repo.contar() == len(_PUBLICABLES)


# ---------------------------------------------------------------------------
# Listado, filtros y paginación
# ---------------------------------------------------------------------------


def test_filtra_por_slug_de_comunidad_calculado_en_postgres(corpus, repo):
    """El slug de SQL tiene que dar lo mismo que ``slugificar()`` del frontend."""
    madrid = repo.listar(ccaa_slug="comunidad-de-madrid")

    assert {f["id_externo"] for f in madrid} == {"P-01", "P-02", "P-03"}
    # "Castilla y León" lleva tilde: el plegado es justo lo que se está fijando.
    assert {f["id_externo"] for f in repo.listar(ccaa_slug="castilla-y-leon")} == {"P-04", "P-05"}


def test_un_slug_que_no_existe_devuelve_vacio_en_vez_de_todo(corpus, repo):
    assert repo.listar(ccaa_slug="narnia") == []
    assert repo.contar(ccaa_slug="narnia") == 0


def test_filtra_por_prefijo_cpv_y_no_confunde_un_codigo_con_otro(corpus, repo):
    assert {f["id_externo"] for f in repo.listar(cpv_prefijo="72")} == {"P-01", "P-02", "P-03"}
    assert {f["id_externo"] for f in repo.listar(cpv_prefijo="48")} == {"P-04", "P-05"}
    # El 45 solo lo tienen expedientes no publicables.
    assert repo.listar(cpv_prefijo="45") == []


def test_los_filtros_se_combinan_con_and(corpus, repo):
    assert repo.listar(ccaa_slug="comunidad-de-madrid", cpv_prefijo="48") == []
    assert repo.contar(ccaa_slug="comunidad-de-madrid", cpv_prefijo="72") == 3


def test_la_paginacion_no_repite_ni_se_deja_expedientes(corpus, repo):
    primera = repo.listar(limite=2, desplazamiento=0)
    segunda = repo.listar(limite=2, desplazamiento=2)
    tercera = repo.listar(limite=2, desplazamiento=4)

    ids = [f["id_externo"] for f in primera + segunda + tercera]
    assert len(ids) == len(_PUBLICABLES)
    assert set(ids) == _PUBLICABLES
    assert len(set(ids)) == len(ids)


def test_el_limite_se_acota_en_vez_de_confiar_en_el_llamante(corpus, repo):
    """``limite=0`` pediría ``LIMIT 0`` y un hub saldría vacío sin decir por qué."""
    assert len(repo.listar(limite=0)) == 1
    assert len(repo.listar(limite=10_000)) == len(_PUBLICABLES)
    assert len(repo.listar(desplazamiento=-5)) == len(_PUBLICABLES)


def test_contar_ignora_la_paginacion(corpus, repo):
    """El hub necesita el total real, no el tamaño de la página."""
    assert len(repo.listar(limite=1)) == 1
    assert repo.contar() == len(_PUBLICABLES)


# ---------------------------------------------------------------------------
# Frescura
# ---------------------------------------------------------------------------


def _fechar(db_mod, id_externo: str, cuando: str) -> None:
    with db_mod.connect() as conn:
        conn.execute(
            "UPDATE licitaciones SET fecha_extraccion = %s WHERE id_externo = %s",
            (cuando, id_externo),
        )


def test_ultima_incorporacion_devuelve_la_mas_reciente(corpus, repo):
    """La landing usa esta fecha como prueba de frescura del corpus."""
    _fechar(corpus, "P-03", "2026-08-20T09:30:00+00:00")

    assert repo.ultima_incorporacion() == "2026-08-20T09:30:00+00:00"


def test_ultima_incorporacion_ignora_lo_que_no_se_publica(corpus, repo):
    """Un expediente que no llega a página no puede acreditar frescura.

    P-06 tiene el título por debajo del umbral: existe en la tabla pero no en
    la superficie pública. Si su fecha contara, la landing diría "incorporado
    hace un minuto" señalando algo que el visitante no puede abrir.
    """
    _fechar(corpus, "P-06", "2027-01-01T00:00:00+00:00")
    _fechar(corpus, "P-01", "2026-08-15T12:00:00+00:00")

    assert repo.ultima_incorporacion() == "2026-08-15T12:00:00+00:00"


def test_ultima_incorporacion_sin_corpus_es_none(tmp_db, repo):
    """Sin expedientes no hay fecha que dar, y el consumidor no pinta nada."""
    assert repo.ultima_incorporacion() is None


# ---------------------------------------------------------------------------
# Hubs
# ---------------------------------------------------------------------------


def test_los_hubs_por_debajo_del_umbral_no_tienen_pagina(corpus, repo):
    """Galicia solo tiene expedientes no publicables; Castilla y León, dos."""
    slugs = {h["slug"] for h in repo.hubs_ccaa()}

    assert slugs == {"comunidad-de-madrid"}
    assert "galicia" not in slugs


def test_el_hub_devuelve_slug_nombre_y_total(corpus, repo):
    [madrid] = repo.hubs_ccaa()

    assert madrid["slug"] == "comunidad-de-madrid"
    assert madrid["nombre"] == "Comunidad de Madrid"
    assert madrid["total"] == 3


def test_los_hubs_cpv_aplican_el_mismo_umbral(corpus, repo):
    codigos = {h["codigo"]: h["total"] for h in repo.hubs_cpv()}

    assert codigos == {"72000000": 3}


# ---------------------------------------------------------------------------
# Sitemap
# ---------------------------------------------------------------------------


def test_la_particion_del_sitemap_es_estable_entre_ejecuciones(corpus, repo):
    """Ordena por ``id_externo``: republicar algo no debe moverlo de fichero."""
    primera = repo.pagina_de_sitemap(desplazamiento=0, tamano=3)
    otra_vez = repo.pagina_de_sitemap(desplazamiento=0, tamano=3)

    assert [f["id_externo"] for f in primera] == [f["id_externo"] for f in otra_vez]
    assert [f["id_externo"] for f in primera] == ["P-01", "P-02", "P-03"]


def test_el_sitemap_solo_trae_lo_que_hace_falta_para_la_url_y_el_lastmod(corpus, repo):
    [fila] = repo.pagina_de_sitemap(desplazamiento=0, tamano=1)

    assert set(fila.keys()) == {"id_externo", "ccaa", "titulo", "fecha_extraccion"}


def test_el_tamano_del_tramo_se_acota(corpus, repo):
    assert len(repo.pagina_de_sitemap(desplazamiento=0, tamano=0)) == 1
    assert len(repo.pagina_de_sitemap(desplazamiento=-1, tamano=100_000)) == len(_PUBLICABLES)


def test_un_desplazamiento_mas_alla_del_final_devuelve_vacio(corpus, repo):
    assert repo.pagina_de_sitemap(desplazamiento=999, tamano=10) == []


# ---------------------------------------------------------------------------
# Lotes
# ---------------------------------------------------------------------------


def test_los_lotes_salen_ordenados_por_numero(corpus, repo):
    with corpus.connect() as conn:
        for numero in (3, 1, 2):
            conn.execute(
                "INSERT INTO lotes "
                "(licitacion_id, numero, titulo, cpv, importe, fecha_extraccion) "
                "VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)",
                ("P-01", str(numero), f"Lote {numero}", "72000000", 1000.0 * numero),
            )

    lotes = repo.lotes_de("P-01")

    # `lotes.numero` es `String`, no entero: el orden es el de la columna.
    assert [lote["numero"] for lote in lotes] == ["1", "2", "3"]
    assert set(lotes[0].keys()) == {"numero", "titulo", "cpv", "importe", "fecha_limite"}


def test_un_expediente_sin_lotes_devuelve_lista_vacia(corpus, repo):
    assert repo.lotes_de("P-02") == []
