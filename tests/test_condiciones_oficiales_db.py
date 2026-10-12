"""Persistencia de las condiciones oficiales de CODICE (v149), contra Postgres.

El invariante 2 de AGENTS.md —toda escritura desde el scraper se puede
re-ejecutar sin duplicar— es lo que estos tests fijan para las tres tablas de
v149, más las dos reglas que lo concretan:

- **Una corrección del órgano reemplaza lo anterior.** Si la nueva versión del
  anuncio trae filas de una familia, sustituyen a las de la versión previa.
- **Un anuncio que no trae una familia no la borra.** La fase de adjudicación
  deja de publicar ``cac:TenderingTerms``; sin esta regla, la re-ingesta de un
  expediente adjudicado vaciaría justo los criterios con los que se adjudicó.
  Cada familia se decide por separado.

Se escribe por el camino de producción (``upsert_licitaciones_with_history``,
el que llama ``run_connector``) y por el simple (``upsert_licitaciones``).
"""

from __future__ import annotations

from typing import Any

import pytest

from db.upsert import (
    CondicionesCodice,
    CriterioAdjudicacion,
    GarantiaExigida,
    Licitacion,
    RequisitoSolvencia,
    upsert_licitaciones,
    upsert_licitaciones_with_history,
)


@pytest.fixture()
def db(tmp_db: Any) -> Any:
    db_mod, _ = tmp_db
    return db_mod


def _lic(condiciones: CondicionesCodice | None, *, id_externo: str = "COND-1") -> Licitacion:
    return Licitacion(
        id_externo=id_externo,
        titulo="Soporte SAP S/4HANA",
        organo_contratacion="Consejería de Hacienda",
        importe=640_000.0,
        estado="PUB",
        condiciones=condiciones,
    )


def _completas() -> CondicionesCodice:
    return CondicionesCodice(
        criterios=[
            CriterioAdjudicacion(
                orden=1,
                descripcion="Oferta económica",
                peso=60.0,
                peso_pct=60.0,
                es_precio=True,
                tipo_codigo="1",
                nota="Proporcional inversa",
            ),
            CriterioAdjudicacion(orden=2, descripcion="Memoria técnica", peso=40.0, peso_pct=40.0),
            CriterioAdjudicacion(
                orden=1, lote_numero="2", descripcion="Precio", peso=0.7, peso_pct=70.0
            ),
            CriterioAdjudicacion(
                orden=2, lote_numero="2", padre_orden=1, descripcion="Precio hora", peso=100.0
            ),
        ],
        garantias=[
            GarantiaExigida(orden=1, tipo_codigo="2", porcentaje=5.0),
            GarantiaExigida(orden=1, lote_numero="2", importe=4800.0, moneda="EUR"),
        ],
        solvencia=[
            RequisitoSolvencia(
                orden=1,
                clase="economica",
                tipo_codigo="1",
                descripcion="Volumen anual de negocios",
                umbral_importe=480_000.0,
                moneda="EUR",
            ),
            RequisitoSolvencia(orden=2, clase="clasificacion", tipo_codigo="V2"),
        ],
    )


def _filas(db: Any, tabla: str, licitacion_id: str = "COND-1") -> list[dict[str, Any]]:
    # `tabla` es siempre uno de los tres nombres literales de este fichero.
    sql = f"SELECT * FROM {tabla} WHERE licitacion_id = %s ORDER BY lote_numero NULLS FIRST, orden"  # noqa: S608
    with db.connect() as c:
        cursor = c.execute(sql, (licitacion_id,))
        nombres = [d[0] for d in cursor.description]
        return [dict(zip(nombres, fila, strict=True)) for fila in cursor.fetchall()]


def _conteos(db: Any) -> tuple[int, int, int]:
    return (
        len(_filas(db, "licitacion_criterios_adjudicacion")),
        len(_filas(db, "licitacion_garantias")),
        len(_filas(db, "licitacion_solvencia")),
    )


def test_el_upsert_escribe_las_tres_familias_con_su_ambito(db: Any) -> None:
    upsert_licitaciones_with_history([_lic(_completas())], source="placsp")

    criterios = _filas(db, "licitacion_criterios_adjudicacion")
    assert [(c["lote_numero"], c["orden"], c["descripcion"]) for c in criterios] == [
        (None, 1, "Oferta económica"),
        (None, 2, "Memoria técnica"),
        ("2", 1, "Precio"),
        ("2", 2, "Precio hora"),
    ]
    precio = criterios[0]
    assert (precio["peso"], precio["peso_pct"], precio["es_precio"]) == (60.0, 60.0, True)
    assert (precio["tipo_codigo"], precio["nota"]) == ("1", "Proporcional inversa")
    assert criterios[3]["padre_orden"] == 1 and criterios[3]["peso_pct"] is None
    assert all(c["fecha_extraccion"] for c in criterios)

    garantias = _filas(db, "licitacion_garantias")
    assert [(g["lote_numero"], g["porcentaje"], g["importe"], g["moneda"]) for g in garantias] == [
        (None, 5.0, None, None),
        ("2", None, 4800.0, "EUR"),
    ]
    solvencia = _filas(db, "licitacion_solvencia")
    assert [(s["clase"], s["tipo_codigo"], s["umbral_importe"]) for s in solvencia] == [
        ("economica", "1", 480_000.0),
        ("clasificacion", "V2", None),
    ]


def test_reingerir_no_duplica(db: Any) -> None:
    for _ in range(3):
        upsert_licitaciones_with_history([_lic(_completas())], source="placsp")

    assert _conteos(db) == (4, 2, 2)


def test_una_correccion_del_organo_reemplaza_lo_anterior(db: Any) -> None:
    upsert_licitaciones_with_history([_lic(_completas())], source="placsp")
    corregida = CondicionesCodice(
        criterios=[CriterioAdjudicacion(orden=1, descripcion="Precio", peso=100.0, peso_pct=100.0)],
        garantias=[GarantiaExigida(orden=1, tipo_codigo="2", porcentaje=4.0)],
        solvencia=[RequisitoSolvencia(orden=1, clase="tecnica", descripcion="Tres servicios")],
    )

    upsert_licitaciones_with_history([_lic(corregida)], source="placsp")

    assert [c["descripcion"] for c in _filas(db, "licitacion_criterios_adjudicacion")] == ["Precio"]
    assert [g["porcentaje"] for g in _filas(db, "licitacion_garantias")] == [4.0]
    assert [s["clase"] for s in _filas(db, "licitacion_solvencia")] == ["tecnica"]


def test_un_anuncio_sin_terminos_no_borra_lo_conocido(db: Any) -> None:
    """La fase ADJ deja de publicar ``TenderingTerms``: se conserva lo que había."""
    upsert_licitaciones_with_history([_lic(_completas())], source="placsp")

    upsert_licitaciones_with_history([_lic(CondicionesCodice())], source="placsp")
    upsert_licitaciones_with_history([_lic(None)], source="ted")

    assert _conteos(db) == (4, 2, 2)


def test_cada_familia_se_decide_por_separado(db: Any) -> None:
    upsert_licitaciones_with_history([_lic(_completas())], source="placsp")
    solo_criterios = CondicionesCodice(
        criterios=[CriterioAdjudicacion(orden=1, descripcion="Precio", peso=100.0)]
    )

    upsert_licitaciones_with_history([_lic(solo_criterios)], source="placsp")

    assert _conteos(db) == (1, 2, 2)


def test_el_upsert_simple_tambien_las_escribe(db: Any) -> None:
    upsert_licitaciones([_lic(_completas()), _lic(_completas(), id_externo="COND-2")])
    upsert_licitaciones([_lic(_completas())])

    assert _conteos(db) == (4, 2, 2)
    assert len(_filas(db, "licitacion_garantias", "COND-2")) == 2


def test_dos_versiones_en_el_mismo_lote_gana_la_ultima(db: Any) -> None:
    """Como el ``ON CONFLICT`` de la licitación: la última del lote es la que queda."""
    vieja = CondicionesCodice(garantias=[GarantiaExigida(orden=1, porcentaje=3.0)])
    nueva = CondicionesCodice(garantias=[GarantiaExigida(orden=1, porcentaje=5.0)])

    upsert_licitaciones_with_history([_lic(vieja), _lic(nueva)], source="placsp")

    assert [g["porcentaje"] for g in _filas(db, "licitacion_garantias")] == [5.0]


def test_sin_las_tablas_la_ingesta_sigue(db: Any) -> None:
    """Código desplegado antes que la migración: la licitación entra igual."""
    with db.connect() as c:
        c.execute("DROP TABLE licitacion_criterios_adjudicacion")
        c.execute("DROP TABLE licitacion_garantias")
        c.execute("DROP TABLE licitacion_solvencia")

    resultado = upsert_licitaciones_with_history([_lic(_completas())], source="placsp")

    assert resultado.inserted == ["COND-1"]


def test_borrar_la_licitacion_arrastra_sus_condiciones(db: Any) -> None:
    upsert_licitaciones_with_history([_lic(_completas())], source="placsp")

    with db.connect() as c:
        c.execute("DELETE FROM licitaciones WHERE id_externo = %s", ("COND-1",))

    assert _conteos(db) == (0, 0, 0)


def test_el_repositorio_devuelve_las_familias_y_los_titulos_de_lote(db: Any) -> None:
    from db.repositories.condiciones_oficiales import CondicionesOficialesRepository
    from db.upsert import Lote, replace_lotes

    upsert_licitaciones_with_history([_lic(_completas())], source="placsp")
    replace_lotes("COND-1", [Lote(licitacion_id="COND-1", numero="2", titulo="Soporte Oracle")])

    leido = CondicionesOficialesRepository().get("COND-1")

    assert [c["descripcion"] for c in leido["criterios"]] == [
        "Oferta económica",
        "Memoria técnica",
        "Precio",
        "Precio hora",
    ]
    assert [g["lote_numero"] for g in leido["garantias"]] == [None, "2"]
    assert [s["clase"] for s in leido["solvencia"]] == ["economica", "clasificacion"]
    assert leido["lotes"] == {"2": "Soporte Oracle"}
    assert leido["actualizado"] is not None
    assert leido["existe"] is True


def test_el_repositorio_sin_filas_devuelve_listas_vacias(db: Any) -> None:
    from db.repositories.condiciones_oficiales import CondicionesOficialesRepository

    leido = CondicionesOficialesRepository().get("NO-EXISTE")

    assert leido == {
        "criterios": [],
        "garantias": [],
        "solvencia": [],
        "lotes": {},
        "actualizado": None,
        "existe": False,
        "url": None,
    }


def test_el_repositorio_sin_las_tablas_responde_sin_condiciones(db: Any) -> None:
    """Código desplegado antes que v149: no hay condiciones guardadas, y se dice así."""
    from db.repositories.condiciones_oficiales import CondicionesOficialesRepository

    upsert_licitaciones([_lic(None)])
    with db.connect() as c:
        c.execute("DROP TABLE licitacion_criterios_adjudicacion")

    leido = CondicionesOficialesRepository().get("COND-1")

    assert leido["criterios"] == []
    assert leido["existe"] is True
