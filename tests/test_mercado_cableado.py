"""El cableado de ``services.competitive.mercado`` hasta su repositorio, contra Postgres.

Al mover el SQL a ``db/repositories/mercado.py`` el servicio pasó a entregar
cada filtro como argumento con nombre. Un argumento que se pierda por el camino
no rompe nada visible: la consulta sigue siendo válida y devuelve filas, solo
que de otro alcance.

Cada test de aquí construye datos en los que el filtro, la ventana, el tope de
paginación o la exclusión de duplicados **sí** cambian la cifra, y comprueba la
cifra. Cada uno caza al menos una mutación que ``tests/test_competitive.py``,
``tests/test_mercado_filtros_sql.py`` y ``tests/test_metric_scope.py`` dejaban
en verde: la posición de un grupo que agrupa una sola identidad, la base de
comparación que reutiliza la actividad de la ventana, el HHI o el denominador
sin anti-join (y el dossier y el listado sin él, si además se anula
``_exigir_dedupe``), el listado sin ``offset``, sin acotar o sin ``organo``, el
denominador sin ``ccaa``, ``cpv_prefix`` o ``desde``, la cuota sin ``desde``,
``cpv_prefix`` o ``ccaa`` o con ``limit`` fijo, el HHI segmentado siempre por
CPV, la subconsulta de contratos del HHI sin universo, y el dossier con
``cpv_prefix``, ``ccaas`` o ``tecnologias`` quitado de la llamada que arma el
alcance de la actividad o el del mercado.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from services.competitive.mercado import (
    concentracion_hhi,
    cuota_mercado,
    listar_adjudicaciones_empresa,
    metric_scope,
    perfil_empresa,
)


@pytest.fixture(autouse=True)
def _cache_de_respuestas_vacia():
    """``/competitive/hhi`` se sirve de una caché de proceso compartida entre usuarios.

    Nadie la vacía entre tests, y cada test tiene su propio corpus: sin esto,
    una respuesta que otro test dejó con los mismos filtros se serviría en lugar
    de la de este. Se vacía también al salir, para no envenenar a los demás.
    """
    from shared.cache import reset_cache

    reset_cache("analytics")
    yield
    reset_cache("analytics")


def _hace(dias: int) -> str:
    return (datetime.now(UTC) - timedelta(days=dias)).strftime("%Y-%m-%d")


def _adjudicar(
    lic_id: str,
    empresa: str,
    *,
    nif: str,
    adjudicado: float,
    fecha_adjudicacion: str = "2025-06-01",
    cpv: str = "72000000",
    ccaa: str = "Madrid",
    organo: str = "Ministerio X",
    tecnologia: str | None = None,
    analysis_universe: str | None = None,
) -> None:
    """Una licitación con una adjudicación, sin resolver aún contra el maestro."""
    from db.upsert import (
        Adjudicacion,
        Licitacion,
        replace_adjudicaciones_batch,
        upsert_licitaciones,
    )

    upsert_licitaciones(
        [
            Licitacion(
                id_externo=lic_id,
                titulo=f"Contrato {lic_id}",
                organo_contratacion=organo,
                importe=adjudicado * 1.25,
                cpv=cpv,
                ccaa=ccaa,
                fecha_publicacion="2025-05-01",
                tecnologia=tecnologia,
                analysis_universe=analysis_universe,
            )
        ]
    )
    adjudicacion = Adjudicacion(
        licitacion_id=lic_id,
        nombre=empresa,
        nif=nif,
        importe_adjudicado=adjudicado,
        fecha_adjudicacion=fecha_adjudicacion,
        n_ofertas_recibidas=3,
        ccaa=ccaa,
    )
    _total, _descartadas, fallidas = replace_adjudicaciones_batch({lic_id: [adjudicacion]})
    assert fallidas == 0


def _resolver() -> None:
    from services.entity_resolution import resolve_all_unlinked

    resolve_all_unlinked()


def _empresa_id(nif: str) -> int:
    from db.database import connect_read

    with connect_read() as c:
        return int(
            c.execute("SELECT empresa_id FROM empresas WHERE nif_canonico = %s", (nif,)).fetchone()[
                0
            ]
        )


def _marcar_duplicado(licitacion_id: str, canonical_id: str) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones_duplicados "
            "(licitacion_id, canonical_id, confianza, status, clave_match) "
            "VALUES (%s, %s, 1.0, 'confirmed', 'test')",
            (licitacion_id, canonical_id),
        )


def test_dossier_agrupado_suma_las_identidades_antes_de_rankear(tmp_db):
    """Dos identidades del mismo competidor compiten como una sola frente al rival.

    Por separado cada una tiene 300k y el rival 500k; juntas suman 600k y pasan
    a ser las primeras. Si la posición agrupara solo una de las identidades, el
    dossier diría rank 2 y una cuota de la mitad.
    """
    _adjudicar("G-UNO", "Grupo Uno SL", nif="B30000012", adjudicado=300_000)
    _adjudicar("G-DOS", "Grupo Dos SL", nif="B30000020", adjudicado=300_000)
    _adjudicar("G-RIVAL", "Rival Grupo SA", nif="B30000038", adjudicado=500_000)
    _resolver()
    uno, dos = _empresa_id("B30000012"), _empresa_id("B30000020")
    assert uno != dos

    perfil = perfil_empresa(uno, empresa_ids=[dos])

    assert perfil["totales"]["contratos"] == 2
    assert perfil["posicion_mercado"] == {
        "rank": 1,
        "empresas": 2,
        "cuota_pct": pytest.approx(54.55, abs=0.005),
        "importe_segmento": 1_100_000,
    }
    listado = listar_adjudicaciones_empresa(uno, empresa_ids=[dos])
    assert listado["total"] == 2
    assert {item["licitacion_id"] for item in listado["items"]} == {"G-UNO", "G-DOS"}


def test_la_base_de_comparacion_llega_fuera_de_la_ventana(tmp_db):
    """Con ventana de fechas, el periodo anterior se mide con filas de fuera de ella.

    La actividad del dossier solo trae lo que cae en la ventana; si la base de
    comparación reutilizara esas filas, el periodo anterior saldría vacío.
    """
    _adjudicar(
        "C-ANTERIOR",
        "Comparada SL",
        nif="B30000103",
        adjudicado=100_000,
        fecha_adjudicacion=_hace(500),
    )
    _adjudicar(
        "C-ACTUAL",
        "Comparada SL",
        nif="B30000103",
        adjudicado=250_000,
        fecha_adjudicacion=_hace(30),
    )
    _resolver()

    perfil = perfil_empresa(
        _empresa_id("B30000103"),
        fecha_desde=date.today() - timedelta(days=364),
        fecha_hasta=date.today(),
    )

    assert perfil["totales"]["contratos"] == 1
    comparacion = perfil["comparacion"]
    assert (comparacion["contratos"], comparacion["contratos_anterior"]) == (1, 1)
    assert (comparacion["importe"], comparacion["importe_anterior"]) == (250_000, 100_000)
    assert comparacion["variacion_importe_pct"] == 150.0


def test_un_duplicado_confirmado_no_cuenta_en_ninguna_superficie(client, auth):
    """``/hhi`` (segmentos y denominador), dossier y listado excluyen el duplicado confirmado.

    ``D-COPIA`` es la misma adjudicación que ``D-ORIGINAL`` publicada por otra
    fuente. Contada, la empresa duplicada pasaría de 100k a 200k: cambiarían el
    HHI y sus contratos, el denominador que ``/hhi`` declara en ``scope``, los
    totales y la posición del dossier y el total del listado.
    """
    _adjudicar("D-ORIGINAL", "Duplicada SL", nif="B30000202", adjudicado=100_000)
    _adjudicar("D-COPIA", "Duplicada SL", nif="B30000202", adjudicado=100_000)
    _adjudicar("D-RIVAL", "Rival Dup SA", nif="B30000210", adjudicado=150_000)
    _resolver()
    _marcar_duplicado("D-COPIA", "D-ORIGINAL")
    duplicada = _empresa_id("B30000202")

    respuesta = client.get(
        "/api/v1/competitive/hhi", params={"segment_by": "cpv", "min_contratos": 1}, headers=auth
    )
    assert respuesta.status_code == 200, respuesta.text
    hhi = respuesta.json()
    # 40 % y 60 % del segmento: 1600 + 3600. Con la copia serían 3 contratos.
    assert [(s["segmento"], s["empresas"], s["contratos"], s["hhi"]) for s in hhi["items"]] == [
        ("72", 2, 2, 5200)
    ]
    assert hhi["items"][0]["importe_total"] == 250_000
    assert (hhi["scope"]["denominator_records"], hhi["scope"]["denominator_amount_eur"]) == (
        2,
        250_000,
    )

    perfil = perfil_empresa(duplicada)
    assert perfil["totales"]["contratos"] == 1
    assert perfil["actividad_historica"]["contratos"] == 1
    assert perfil["posicion_mercado"]["importe_segmento"] == 250_000
    assert perfil["posicion_mercado"]["rank"] == 2

    listado = listar_adjudicaciones_empresa(duplicada)
    assert listado["total"] == 1
    assert [item["licitacion_id"] for item in listado["items"]] == ["D-ORIGINAL"]


def test_el_listado_aplica_offset_y_acota_limit_y_offset(tmp_db):
    """``offset`` desplaza la página, y los límites fuera de rango se acotan.

    La respuesta devuelve los límites efectivos: ``limit=0`` se sirve como 1,
    ``limit=10_000`` como 500 y un ``offset`` negativo como 0. Sin acotar, el
    ``limit=0`` devolvería una página vacía y Postgres rechazaría el ``OFFSET``
    negativo.
    """
    for sufijo, importe in (("A", 10_000), ("B", 30_000), ("C", 20_000)):
        _adjudicar(f"L-{sufijo}", "Paginada SL", nif="B20000030", adjudicado=importe)
    _resolver()
    empresa = _empresa_id("B20000030")

    segunda = listar_adjudicaciones_empresa(empresa, sort="importe_desc", limit=1, offset=1)
    assert (segunda["total"], segunda["limit"], segunda["offset"]) == (3, 1, 1)
    assert [item["licitacion_id"] for item in segunda["items"]] == ["L-C"]

    minima = listar_adjudicaciones_empresa(empresa, sort="importe_desc", limit=0, offset=-5)
    assert (minima["limit"], minima["offset"]) == (1, 0)
    assert [item["licitacion_id"] for item in minima["items"]] == ["L-B"]

    maxima = listar_adjudicaciones_empresa(empresa, sort="importe_asc", limit=10_000)
    assert (maxima["limit"], maxima["offset"]) == (500, 0)
    assert [item["licitacion_id"] for item in maxima["items"]] == ["L-A", "L-C", "L-B"]


def test_metric_scope_filtra_el_denominador_por_ccaa(tmp_db):
    """Con ``ccaa`` el denominador solo cuenta esa comunidad."""
    _adjudicar("S-MAD", "Madrileña SL", nif="B30000400", adjudicado=100_000, ccaa="Madrid")
    _adjudicar("S-GAL", "Gallega SL", nif="B30000418", adjudicado=40_000, ccaa="Galicia")
    _resolver()

    alcance = metric_scope(ccaa="Galicia")

    assert alcance.filters == {"ccaa": "Galicia"}
    assert (alcance.denominator_records, alcance.denominator_amount_eur) == (1, 40_000)


def test_el_listado_filtra_por_organo(tmp_db):
    """``organo`` llega al repositorio: de dos órganos, solo queda el pedido."""
    _adjudicar(
        "O-HACIENDA",
        "Organica SL",
        nif="B30000509",
        adjudicado=50_000,
        organo="Ministerio de Hacienda",
    )
    _adjudicar(
        "O-XUNTA", "Organica SL", nif="B30000509", adjudicado=60_000, organo="Xunta de Galicia"
    )
    _resolver()
    empresa = _empresa_id("B30000509")

    assert listar_adjudicaciones_empresa(empresa)["total"] == 2
    filtrado = listar_adjudicaciones_empresa(empresa, organo="xunta")
    assert filtrado["total"] == 1
    assert [item["licitacion_id"] for item in filtrado["items"]] == ["O-XUNTA"]


def test_cuota_mercado_filtra_por_desde(tmp_db):
    """``desde`` llega al repositorio: la adjudicación anterior sale del ranking."""
    _adjudicar(
        "Q-ANTES",
        "Antigua SL",
        nif="B30000608",
        adjudicado=700_000,
        fecha_adjudicacion="2024-01-15",
    )
    _adjudicar(
        "Q-DESPUES",
        "Reciente SL",
        nif="B30000616",
        adjudicado=300_000,
        fecha_adjudicacion="2025-06-01",
    )
    _resolver()

    assert len(cuota_mercado()) == 2
    ranking = cuota_mercado(desde="2025-01-01")
    assert [(fila["empresa_id"], fila["importe"], fila["cuota_pct"]) for fila in ranking] == [
        (_empresa_id("B30000616"), 300_000, 100.0)
    ]


def test_hhi_cuenta_contratos_solo_del_universo_observado(tmp_db):
    """``min_contratos`` se mide sobre el universo observado, no sobre la tabla entera.

    El segmento CPV 48 tiene 3 adjudicaciones del universo tecnológico y 3 de
    empresas vigiladas. Contando las seis alcanzaría ``min_contratos=5``; solo
    cuentan las tres primeras.
    """
    for i in range(3):
        _adjudicar(f"H-OBS-{i}", "Observada SA", nif="B30000707", adjudicado=10_000, cpv="48000000")
        _adjudicar(
            f"H-VIG-{i}",
            "Vigilada SA",
            nif="B20000071",
            adjudicado=10_000,
            cpv="48000000",
            analysis_universe="watched_company_awards_observed",
        )
    _resolver()

    assert concentracion_hhi(segment_by="cpv", min_contratos=5) == []
    segmentos = concentracion_hhi(segment_by="cpv", min_contratos=3)
    assert [(s["segmento"], s["empresas"], s["contratos"], s["hhi"]) for s in segmentos] == [
        ("48", 1, 3, 10000)
    ]


def _tres_segmentos() -> tuple[int, int, int]:
    """Tres empresas que ``cpv_prefix``, ``ccaa`` y ``desde`` separan de forma distinta.

    ===========  ===  =======  ==========  =======
    empresa      CPV  CCAA     adjudicada  importe
    ===========  ===  =======  ==========  =======
    Segmento A   72   Madrid   2025-06-01  400k
    Segmento B   48   Galicia  2025-03-01  300k
    Segmento C   72   Galicia  2024-01-15  100k
    ===========  ===  =======  ==========  =======
    """
    _adjudicar(
        "T-A",
        "Segmento A SL",
        nif="B30000905",
        adjudicado=400_000,
        fecha_adjudicacion="2025-06-01",
        cpv="72000000",
        ccaa="Madrid",
    )
    _adjudicar(
        "T-B",
        "Segmento B SL",
        nif="B30000913",
        adjudicado=300_000,
        fecha_adjudicacion="2025-03-01",
        cpv="48000000",
        ccaa="Galicia",
    )
    _adjudicar(
        "T-C",
        "Segmento C SL",
        nif="B30000921",
        adjudicado=100_000,
        fecha_adjudicacion="2024-01-15",
        cpv="72000000",
        ccaa="Galicia",
    )
    _resolver()
    return _empresa_id("B30000905"), _empresa_id("B30000913"), _empresa_id("B30000921")


def test_cuota_mercado_filtra_por_cpv_y_ccaa_y_respeta_limit(tmp_db):
    """``cpv_prefix``, ``ccaa`` y ``limit`` llegan al repositorio: cada uno cambia el ranking."""
    a, b, c = _tres_segmentos()

    def ranking(filas: list[dict[str, Any]]) -> list[tuple[int, float, float]]:
        return [(fila["empresa_id"], fila["importe"], fila["cuota_pct"]) for fila in filas]

    assert ranking(cuota_mercado()) == [
        (a, 400_000, 50.0),
        (b, 300_000, 37.5),
        (c, 100_000, 12.5),
    ]
    assert ranking(cuota_mercado(cpv_prefix="72")) == [(a, 400_000, 80.0), (c, 100_000, 20.0)]
    assert ranking(cuota_mercado(ccaa="Galicia")) == [(b, 300_000, 75.0), (c, 100_000, 25.0)]
    assert ranking(cuota_mercado(limit=1)) == [(a, 400_000, 50.0)]


def test_metric_scope_filtra_el_denominador_por_cpv_y_desde(tmp_db):
    """``cpv_prefix`` y ``desde`` llegan al denominador, no solo a ``filters``."""
    _tres_segmentos()

    sin_filtros = metric_scope()
    assert (sin_filtros.denominator_records, sin_filtros.denominator_amount_eur) == (3, 800_000)

    por_cpv = metric_scope(cpv_prefix="72")
    assert por_cpv.filters == {"cpv_prefix": "72"}
    assert (por_cpv.denominator_records, por_cpv.denominator_amount_eur) == (2, 500_000)

    por_desde = metric_scope(desde="2025-01-01")
    assert por_desde.filters == {"desde": "2025-01-01"}
    assert por_desde.window_from == "2025-01-01"
    assert (por_desde.denominator_records, por_desde.denominator_amount_eur) == (2, 700_000)


def test_hhi_segmenta_por_ccaa(tmp_db):
    """``segment_by='ccaa'`` llega al repositorio: un segmento por comunidad, no por CPV.

    Las tres adjudicaciones son del CPV 72. Segmentadas por CPV serían un único
    segmento de tres empresas.
    """
    _adjudicar("H-MAD-1", "Madrid Uno SL", nif="B30001002", adjudicado=100_000, ccaa="Madrid")
    _adjudicar("H-MAD-2", "Madrid Dos SL", nif="B30001010", adjudicado=100_000, ccaa="Madrid")
    _adjudicar("H-GAL-1", "Galicia Uno SL", nif="B30001028", adjudicado=100_000, ccaa="Galicia")
    _resolver()

    segmentos = concentracion_hhi(segment_by="ccaa", min_contratos=1)

    assert [(s["segmento"], s["empresas"], s["contratos"], s["hhi"]) for s in segmentos] == [
        ("Galicia", 1, 1, 10000),
        ("Madrid", 2, 2, 5000),
    ]


def test_el_dossier_aplica_cpv_ccaas_y_tecnologias_a_actividad_y_mercado(tmp_db):
    """Los tres filtros llegan al alcance de la actividad y al del mercado.

    La empresa tiene una adjudicación dentro del alcance y una fuera por cada
    filtro. En el mercado compiten un rival dentro del alcance, uno en otra
    comunidad y uno de otra tecnología. Sin cualquiera de los filtros en la
    actividad, el dossier contaría 2 contratos; sin ``cpv_prefix`` en el mercado,
    la cuota subiría al 77,8 %; sin ``ccaas`` o sin ``tecnologias``, entraría un
    rival mayor y el rank sería 2 de 3. La historia no lleva filtros: cuenta las 4.
    """
    # (licitación, empresa, nif, importe, cpv, ccaa, tecnología). Cada fila de
    # fuera del alcance difiere de la de dentro solo en su filtro. Nombres bien
    # distintos: con nombres parecidos la resolución deja a los rivales en
    # revisión, sin empresa, y no entrarían en el mercado.
    filas = [
        ("P-DENTRO", "Filtrada SL", "B30001101", 300_000, "72000000", "Madrid", "SAP"),
        ("P-CPV", "Filtrada SL", "B30001101", 50_000, "48000000", "Madrid", "SAP"),
        ("P-CCAA", "Filtrada SL", "B30001101", 70_000, "72000000", "Galicia", "SAP"),
        ("P-TEC", "Filtrada SL", "B30001101", 30_000, "72000000", "Madrid", "SALESFORCE"),
        ("R-DENTRO", "Hermanos Ruiz SA", "B30001119", 100_000, "72000000", "Madrid", "SAP"),
        ("R-CCAA", "Consultora Atlantica SA", "B30001127", 900_000, "72000000", "Galicia", "SAP"),
        ("R-TEC", "Nubes Integradas SA", "B20000113", 800_000, "72000000", "Madrid", "SALESFORCE"),
    ]
    for lic_id, empresa, nif, importe, cpv, ccaa, tecnologia in filas:
        _adjudicar(
            lic_id,
            empresa,
            nif=nif,
            adjudicado=importe,
            cpv=cpv,
            ccaa=ccaa,
            tecnologia=tecnologia,
        )
    _resolver()

    perfil = perfil_empresa(
        _empresa_id("B30001101"), cpv_prefix="72", ccaas=["Madrid"], tecnologias=["SAP"]
    )

    assert (perfil["totales"]["contratos"], perfil["totales"]["importe_total"]) == (1, 300_000)
    assert perfil["actividad_historica"]["contratos"] == 4
    assert perfil["posicion_mercado"] == {
        "rank": 1,
        "empresas": 2,
        "cuota_pct": 75.0,
        "importe_segmento": 400_000,
    }
