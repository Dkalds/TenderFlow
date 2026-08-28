"""Las dos formas de seleccionar canónicas tienen que devolver el mismo conjunto.

``db/repositories/publico.py`` mantiene dos expresiones que seleccionan
*exactamente* las mismas filas y que existen sólo porque su coste se invierte:

- ``_WHERE_INDEXABLE`` (anti-join, :func:`fila_canonica_sql`) para las consultas
  con ``LIMIT``, donde el plan corta pronto — un tramo del sitemap en 5,9 s.
- ``_canonicas_from`` (``DISTINCT ON``) para los agregados de tabla entera, que
  no tienen ``LIMIT`` que los salve — 9,1 s frente a los ~200 s del anti-join.

Que dos definiciones del mismo concepto convivan es una divergencia esperando a
ocurrir, y ésta se cobraría cara: si el agregado y el listado eligieran
canónicas distintas, ``contar`` diría un número que el hub no puede paginar y
Search Console lo reportaría como error de cobertura sin decir por qué. Este
fichero es el precio de tener las dos.

El caso que de verdad importa es el de los ``NULL``. ``organo_normalizado_sql``
devuelve ``NULL`` sin órgano; en el anti-join ``NULL = NULL`` no es cierto, así
que **todas** esas filas sobreviven. Un ``DISTINCT ON`` sobre la clave cruda
haría lo contrario —``DISTINCT`` sí considera iguales dos ``NULL``— y las
colapsaría en una, haciendo desaparecer contratos de la superficie pública sin
que fallara nada. De ahí el ``coalesce`` con ``id_externo`` de
:func:`clave_canonica_agrupable_sql`, y de ahí que aquí se siembre
explícitamente el caso.
"""

from __future__ import annotations

from typing import Any

import pytest

from db.repositories.publico import (
    _BASE_WHERE,
    _WHERE_INDEXABLE,
    PublicoRepository,
    _canonicas_from,
)


@pytest.fixture()
def db(tmp_db: Any) -> Any:
    """El módulo de BD ya inicializado. ``tmp_db`` devuelve ``(db_mod, tmp_path)``."""
    db_mod, _ = tmp_db
    return db_mod


def _sembrar(db: Any, filas: list[dict[str, Any]]) -> None:
    """Inserta lo mínimo para que una fila sea publicable y comparable."""
    with db.connect() as c:
        for f in filas:
            c.execute(
                "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, "
                "importe, fecha_publicacion, fecha_extraccion, fuente, ccaa) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    f["id_externo"],
                    f.get("titulo", "Servicio de mantenimiento de sistemas SAP para el organismo"),
                    f.get("organo", "Ayuntamiento de Ejemplo"),
                    f.get("cpv", "72000000"),
                    f.get("importe", 100000.0),
                    f.get("fecha_publicacion", "2026-03-01"),
                    f.get("fecha_extraccion", "2026-03-02T00:00:00Z"),
                    f.get("fuente", "pscp"),
                    f.get("ccaa", "Cataluña"),
                ),
            )


def _ids_anti_join(db: Any) -> set[str]:
    with db.connect_read() as c:
        filas = c.execute(
            f"SELECT l.id_externo FROM licitaciones l WHERE {_WHERE_INDEXABLE}"  # noqa: S608
        ).fetchall()
    return {r[0] for r in filas}


def _ids_agrupacion(db: Any) -> set[str]:
    with db.connect_read() as c:
        filas = c.execute(
            f"SELECT c.id_externo FROM {_canonicas_from('l.id_externo')}"  # noqa: S608
        ).fetchall()
    return {r[0] for r in filas}


def test_las_dos_formas_eligen_la_misma_canonica_entre_gemelas(db: Any) -> None:
    """Tres reemisiones del mismo contrato: las dos dejan pasar la misma fila.

    Misma clave (órgano + CPV4 + año-mes + título) y distinta fecha de
    publicación. Gana la más antigua, que es lo que mantiene quieta la URL del
    sitemap cuando llegan corrigendos.
    """
    _sembrar(
        db,
        [
            {"id_externo": "A-1", "fecha_publicacion": "2026-03-05"},
            {"id_externo": "A-2", "fecha_publicacion": "2026-03-10"},
            {"id_externo": "A-3", "fecha_publicacion": "2026-03-20"},
        ],
    )

    assert _ids_anti_join(db) == _ids_agrupacion(db)
    assert _ids_anti_join(db) == {"A-1"}, "gana la publicación más antigua"


def test_las_filas_sin_organo_sobreviven_todas_en_las_dos_formas(db: Any) -> None:
    """El caso que un ``DISTINCT ON`` ingenuo rompería en silencio.

    Sin órgano la clave es ``NULL``. El anti-join no encuentra gemela (``NULL =
    NULL`` no es cierto) y las deja pasar todas; la agrupación tiene que hacer lo
    mismo gracias al ``coalesce`` con ``id_externo``. Si alguien quitara ese
    ``coalesce``, las tres colapsarían en una y dos contratos desaparecerían de
    la superficie pública sin que fallara ninguna consulta.
    """
    _sembrar(
        db,
        [
            {"id_externo": "S-1", "organo": None},
            {"id_externo": "S-2", "organo": None},
            {"id_externo": "S-3", "organo": ""},
        ],
    )

    assert _ids_anti_join(db) == _ids_agrupacion(db)
    assert _ids_anti_join(db) == {"S-1", "S-2", "S-3"}, "sin órgano no se colapsa nada"


def test_contar_coincide_con_las_filas_que_el_listado_publica(db: Any) -> None:
    """``contar`` (agrupación) y ``listar`` (anti-join) tienen que cuadrar.

    Es el invariante que impide que un hub pagine hacia páginas vacías: si el
    total dice 4 y el listado sólo puede servir 2, el visitante llega a una
    página en blanco y Search Console lo cuenta como error de cobertura.
    """
    _sembrar(
        db,
        [
            {"id_externo": "B-1", "titulo": "Suministro de licencias y soporte SAP S/4HANA"},
            {"id_externo": "B-2", "titulo": "Suministro de licencias y soporte SAP S/4HANA"},
            {"id_externo": "C-1", "titulo": "Consultoría de migración a SAP para el organismo"},
            {"id_externo": "D-1", "organo": None},
        ],
    )
    repo = PublicoRepository()

    total = repo.contar()
    publicadas = repo.listar(limite=200, desplazamiento=0)

    assert total == len(publicadas)
    assert total == 3, "las dos reemisiones de B colapsan en una"


def test_el_filtro_de_comunidad_se_aplica_despues_de_elegir_la_canonica(db: Any) -> None:
    """Filtrar dentro de la subconsulta cambiaría la respuesta, y por eso no se hace.

    Dos gemelas del mismo contrato en comunidades distintas: la canónica es la
    más antigua, que está en Cataluña. Un hub de Madrid **no** puede devolverla
    por su gemela — sería exactamente el duplicado que el filtro de canónica
    existe para evitar.
    """
    _sembrar(
        db,
        [
            {"id_externo": "E-1", "fecha_publicacion": "2026-03-05", "ccaa": "Cataluña"},
            {"id_externo": "E-2", "fecha_publicacion": "2026-03-15", "ccaa": "Madrid"},
        ],
    )
    repo = PublicoRepository()

    assert repo.contar(ccaa_slug="cataluna") == 1
    assert repo.contar(ccaa_slug="madrid") == 0


def test_la_publicabilidad_es_la_misma_en_las_dos_formas() -> None:
    """Las dos parten del mismo ``_BASE_WHERE``, no de dos copias.

    Comprobación de texto, no de comportamiento: es la que caza el día que
    alguien endurezca el umbral de sustancia en un sitio y no en el otro.
    """
    assert _BASE_WHERE in _WHERE_INDEXABLE
    assert _BASE_WHERE in _canonicas_from("l.id_externo")
