"""La superficie pública publica lo que debe, y solo eso.

Tres invariantes que este repositorio tiene que sostener a la vez, y que sin
test se rompen en silencio: la proyección es una allowlist (nada del pipeline
propio se cuela), el umbral de sustancia decide **igual** en ficha, listado,
hubs y sitemap —si discreparan, Search Console lo reporta como error de
cobertura—, y el slug de comunidad que calcula Postgres coincide con el que
genera ``web/src/lib/slug.ts``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import get_args, get_type_hints

import pytest

from db.repositories.publico import (
    _COLS_PUBLICAS,
    FilaLicitacionPublica,
    FilaLotePublico,
    PublicoRepository,
    refrescar_vista_canonicas,
)

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
    # La superficie pública lee de la vista materializada (revisión v94), que no
    # se entera de un INSERT: hay que refrescarla o el test vería el corpus
    # vacío. En producción lo hace el paso `aggregates_precompute` al final de
    # cada pasada de ingesta.
    refrescar_vista_canonicas()
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
# Forma tipada de las filas: lo que sostiene el `cast` de `_filas_tipadas`
# ---------------------------------------------------------------------------


def _desajustes(fila: Mapping[str, object], forma: type) -> dict[str, str]:
    """Columnas cuyo valor real no cabe en el tipo que declara ``forma``.

    Compara claves **y** tipos, en orden. Con solo las claves, una migración
    que pasara ``importe`` a ``NUMERIC`` —psycopg devolvería ``Decimal``— o una
    fecha a ``timestamptz`` —devolvería ``datetime``— dejaría el ``TypedDict``
    mintiendo con el test en verde, y mypy razonaría sobre tipos que no llegan.
    """
    tipos = get_type_hints(forma)
    if list(fila) != list(tipos):
        return {"<claves>": f"{list(fila)} != {list(tipos)}"}
    return {
        clave: f"{type(fila[clave]).__name__} no cabe en {tipo}"
        for clave, tipo in tipos.items()
        if not isinstance(fila[clave], get_args(tipo) or tipo)
    }


def test_la_forma_tipada_es_la_misma_allowlist_y_en_el_mismo_orden():
    """``FilaLicitacionPublica`` no puede ganar ni perder una columna a solas.

    Si la tupla ganara una columna y el ``TypedDict`` no, mypy no vería el
    campo nuevo en la ruta; si fuera al revés, la ruta leería una clave que el
    ``SELECT`` no trae.
    """
    assert tuple(get_type_hints(FilaLicitacionPublica)) == _COLS_PUBLICAS


def test_las_filas_de_ficha_y_listado_traen_los_tipos_que_declara_su_forma(corpus, repo):
    """Todas las columnas rellenas: un ``None`` pasaría la comprobación por vacío."""
    with corpus.connect() as conn:
        conn.execute(
            "UPDATE licitaciones SET descripcion = %s, organo_contratacion = %s, "
            "moneda = %s, tipo_contrato = %s, procedimiento = %s, tramitacion = %s, "
            "fecha_limite = %s, fecha_inicio = %s, fecha_fin = %s, "
            "duracion_valor = %s, duracion_unidad = %s, provincia = %s, nuts_code = %s "
            "WHERE id_externo = %s",
            (
                _DESCRIPCION_LARGA,
                "Ayuntamiento de Madrid",
                "EUR",
                "2",
                "1",
                "1",
                "2026-09-01T12:00:00+00:00",
                "2026-10-01",
                "2027-10-01",
                12.0,
                "MON",
                "Madrid",
                "ES300",
                "P-01",
            ),
        )

    ficha = repo.ficha("P-01")
    [del_listado] = [f for f in repo.listar(limite=200) if f["id_externo"] == "P-01"]

    for fila in (ficha, del_listado):
        assert fila is not None
        assert _desajustes(fila, FilaLicitacionPublica) == {}
        assert None not in fila.values()


def test_una_fila_con_los_opcionales_a_null_tambien_cabe_en_su_forma(corpus, repo):
    """La otra mitad del test anterior: los ``None`` que de verdad llegan.

    P-02 solo trae las columnas del corpus. Si la forma declarara ``str`` una
    columna que aquí vuelve a ``NULL``, ``_desajustes`` lo señala. No pueden
    ser todas las opcionales: sin ``importe`` ni descripción larga, P-02 no
    pasaría el umbral de sustancia y no tendría ficha. Se fija el conjunto
    exacto de las que vuelven a ``NULL``, porque sin eso un ``COALESCE`` en el
    SELECT —que las rellenaría y seguiría cabiendo en la forma— dejaría el test
    sin nada que probar.
    """
    # `moneda` no está: el esquema le pone 'EUR' por defecto.
    nulas_en_el_corpus = {
        "descripcion",
        "organo_contratacion",
        "tipo_contrato",
        "procedimiento",
        "tramitacion",
        "fecha_limite",
        "fecha_inicio",
        "fecha_fin",
        "duracion_valor",
        "duracion_unidad",
        "provincia",
        "nuts_code",
    }
    ficha = repo.ficha("P-02")
    [del_listado] = [f for f in repo.listar(limite=200) if f["id_externo"] == "P-02"]

    for fila in (ficha, del_listado):
        assert fila is not None
        assert {clave for clave, valor in fila.items() if valor is None} == nulas_en_el_corpus
        assert _desajustes(fila, FilaLicitacionPublica) == {}


def test_los_lotes_traen_los_tipos_que_declara_su_forma(corpus, repo):
    with corpus.connect() as conn:
        conn.execute(
            "INSERT INTO lotes "
            "(licitacion_id, numero, titulo, cpv, importe, fecha_limite, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)",
            ("P-01", "1", "Lote 1", "72000000", 1000.0, "2026-09-01T12:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO lotes (licitacion_id, numero, fecha_extraccion) "
            "VALUES (%s, %s, CURRENT_TIMESTAMP)",
            ("P-01", "2"),
        )

    lleno, vacio = repo.lotes_de("P-01")

    assert _desajustes(lleno, FilaLotePublico) == {}
    assert None not in lleno.values()
    assert _desajustes(vacio, FilaLotePublico) == {}
    # Todas las opcionales, no solo `titulo`: un `COALESCE` en el SELECT
    # publicaría `importe: 0.0` o `cpv: ""` donde la fuente no trae nada, y eso
    # cabe igual en la forma.
    assert vacio == {
        "numero": "2",
        "titulo": None,
        "cpv": None,
        "importe": None,
        "fecha_limite": None,
    }


@pytest.mark.parametrize(
    ("forma", "tabla"),
    [(FilaLicitacionPublica, "licitaciones"), (FilaLotePublico, "lotes")],
)
def test_la_nulabilidad_de_cada_forma_es_la_de_su_columna(tmp_db, forma, tabla):
    """Lo que ninguna fila de ejemplo puede demostrar: que ``str`` sea ``str``.

    Los dos tests de arriba ven valores, y un valor relleno cabe igual en
    ``str`` que en ``str | None``. Pero es la nulabilidad lo que mypy da por
    cierto después del ``cast``: la ruta pasa ``fila["titulo"]`` como ``str``
    sin mirar si es ``None``. Por eso se compara con el esquema y en los dos
    sentidos: una forma que declare obligatoria una columna nulable, y una
    migración que quite el ``NOT NULL`` a una columna que la forma da por
    obligatoria.

    ``current_schema()`` y no ``'public'``: cada test tiene su propio schema.
    Una columna que no exista sale como ``None`` y también rompe la igualdad.
    """
    db_mod, _ = tmp_db
    with db_mod.connect() as conn:
        columnas = conn.execute(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s",
            (tabla,),
        ).fetchall()
    nulable_en_esquema = {nombre: es_nulable == "YES" for nombre, es_nulable in columnas}
    tipos = get_type_hints(forma)

    assert {clave: type(None) in get_args(tipo) for clave, tipo in tipos.items()} == {
        clave: nulable_en_esquema.get(clave) for clave in tipos
    }


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
    # Mismo motivo que en el fixture `corpus`: la superficie pública lee de la
    # vista materializada (v94), que no se entera de un UPDATE. Sin refrescar,
    # `ultima_incorporacion` sigue devolviendo la fecha que se sembró y el test
    # mide la vista rancia en vez del cambio que acaba de hacer. En producción
    # lo hace `aggregates_precompute` al final de cada pasada de ingesta.
    refrescar_vista_canonicas()


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
