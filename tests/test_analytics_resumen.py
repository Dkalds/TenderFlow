"""Tests unitarios para services/analytics/resumen.py

Los cinco endpoints agregan en Postgres (ADR-023): todos los tests insertan
un dataset sintético en un schema aislado (``tmp_db``) y comprueban el
resultado contra la BD real — caracterización de la migración pandas -> SQL
con los mismos valores que daba pandas.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from services.analytics.resumen import (
    ResumenHoyFilters,
    SankeyFilters,
    TimelineScatterFilters,
    TopLicitacionesFilters,
    get_resumen_hoy,
    get_resumen_novedades,
    get_sankey_flow,
    get_timeline_scatter,
    get_top_licitaciones,
)

# ---------------------------------------------------------------------------
# Helpers de datos sintéticos
# ---------------------------------------------------------------------------


def _iso(offset_days: int = 0) -> str:
    """Fecha ISO UTC desplazada `offset_days` días desde ahora."""
    dt = datetime.now(UTC) + timedelta(days=offset_days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _row(
    id_externo: str = "L001",
    titulo: str = "Contrato TI",
    organo: str = "Ministerio",
    importe: float = 100_000.0,
    estado: str = "PUB",
    fecha_pub_offset: int = -10,
    fecha_limite_offset: int = 30,
    ccaa: str = "Madrid",
    tecnologia: str = "SAP",
    tipo_contrato: str = "2",
) -> dict:
    return {
        "id_externo": id_externo,
        "titulo": titulo,
        "organo_contratacion": organo,
        "importe": importe,
        "estado": estado,
        "fecha_publicacion": _iso(fecha_pub_offset),
        "fecha_limite": _iso(fecha_limite_offset),
        "ccaa": ccaa,
        "tecnologia": tecnologia,
        "tipo_contrato": tipo_contrato,
    }


def _insert(rows: list[dict]) -> None:
    """Inserta filas de ``_row`` en la BD del test (para los endpoints SQL)."""
    from db.upsert import Licitacion, upsert_licitaciones

    upsert_licitaciones(
        [
            Licitacion(
                id_externo=r["id_externo"],
                titulo=r["titulo"],
                organo_contratacion=r["organo_contratacion"],
                importe=r["importe"],
                estado=r["estado"],
                fecha_publicacion=r["fecha_publicacion"],
                fecha_limite=r["fecha_limite"],
                ccaa=r["ccaa"],
                tecnologia=r["tecnologia"],
                tipo_contrato=r["tipo_contrato"],
                fecha_extraccion=r["fecha_publicacion"],
            )
            for r in rows
        ]
    )


# ---------------------------------------------------------------------------
# get_resumen_novedades
# ---------------------------------------------------------------------------


def test_novedades_user_sin_last_login(tmp_db):
    """User con last_login=None → count=0, sample=[]."""
    _insert([_row("L001", fecha_pub_offset=-1), _row("L002", fecha_pub_offset=-2)])

    with patch("db.users.get_user_by_id", return_value={"id": 1, "last_login": None}):
        result = get_resumen_novedades(1)

    assert result.count == 0
    assert result.sample == []
    # Sin corte que publicar el cliente no marca ninguna fila como nueva.
    assert result.desde is None


def test_novedades_con_new_since(tmp_db):
    """User con last_login hace 2 días → licitaciones publicadas ayer cuentan como novedades."""
    last_login = (datetime.now(UTC) - timedelta(days=2)).isoformat()

    _insert(
        [
            _row("NEW1", fecha_pub_offset=-1),  # después del login → novedad
            _row("NEW2", fecha_pub_offset=-1),  # después del login → novedad
            _row("OLD1", fecha_pub_offset=-5),  # antes del login → no cuenta
        ]
    )

    with patch("db.users.get_user_by_id", return_value={"id": 1, "last_login": last_login}):
        result = get_resumen_novedades(1)

    assert result.count == 2
    assert len(result.sample) == 2
    ids = {s.id_externo for s in result.sample}
    assert ids == {"NEW1", "NEW2"}


def test_novedades_sample_capado_a_10(tmp_db):
    """count refleja el total; la muestra se capa a 10 y trae las más recientes."""
    last_login = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    _insert([_row(f"N{i:02d}", fecha_pub_offset=-i) for i in range(1, 16)])

    with patch("db.users.get_user_by_id", return_value={"id": 1, "last_login": last_login}):
        result = get_resumen_novedades(1)

    assert result.count == 15
    assert len(result.sample) == 10
    # Orden descendente por fecha_publicacion: N01 es la más reciente.
    assert [s.id_externo for s in result.sample] == [f"N{i:02d}" for i in range(1, 11)]


def test_novedades_user_no_existe(tmp_db):
    """get_user_by_id devuelve None → ResumenNovedadesResult vacío."""
    with patch("db.users.get_user_by_id", return_value=None):
        result = get_resumen_novedades(99)

    assert result.count == 0
    assert result.sample == []
    assert result.desde is None


def test_novedades_publica_el_corte(tmp_db):
    """`desde` sale en la respuesta y separa de verdad novedades de historia.

    Es el contrato que permite al cliente marcar *todas* las filas nuevas de una
    tabla y no sólo las de la muestra: se compara `fecha_publicacion >= desde`.
    """
    last_login = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    _insert([_row("NEW1", fecha_pub_offset=-1), _row("OLD1", fecha_pub_offset=-5)])

    with patch("db.users.get_user_by_id", return_value={"id": 1, "last_login": last_login}):
        result = get_resumen_novedades(1)

    assert result.desde is not None
    corte = datetime.fromisoformat(result.desde)
    assert corte.tzinfo is not None, (
        "el corte viaja con zona horaria o el cliente no puede compararlo"
    )
    # El corte cae entre la publicación vieja y la nueva, que es lo que lo hace
    # utilizable como umbral en cliente.
    assert datetime.now(UTC) - timedelta(days=5) < corte < datetime.now(UTC) - timedelta(days=1)
    assert result.count == 1


# ---------------------------------------------------------------------------
# get_resumen_hoy
# ---------------------------------------------------------------------------


def test_hoy_dataset_vacio(tmp_db):
    """Sin filas → todos los KPIs en 0."""
    result = get_resumen_hoy(ResumenHoyFilters())

    assert result.calientes == 0
    assert result.vencen_48h == 0
    assert result.nuevas_24h == 0
    assert result.total_activas == 0


def test_hoy_calientes_y_vencen(tmp_db):
    """Licitaciones con fecha_limite próxima (≤48h) → vencen_48h > 0.

    El cálculo de ``calientes`` requiere estado PUB/EV + importe >= P75 + fecha_limite > now.
    Usamos 4 filas con importes variados para que P75 sea conocido: P75 = 162.500,
    así que solo A1 (200k, límite futuro) es caliente.
    """
    _insert(
        [
            # 2 filas que vencen en 24h (dentro de las 48h)
            _row("A1", importe=200_000.0, estado="PUB", fecha_limite_offset=1),
            _row("A2", importe=150_000.0, estado="PUB", fecha_limite_offset=1),
            # 2 filas que vencen lejos
            _row("B1", importe=50_000.0, estado="PUB", fecha_limite_offset=60),
            _row("B2", importe=10_000.0, estado="PUB", fecha_limite_offset=90),
        ]
    )

    result = get_resumen_hoy(ResumenHoyFilters())

    assert result.vencen_48h == 2
    assert result.calientes == 1
    assert result.total_activas == 4


def test_hoy_filtro_ccaa(tmp_db):
    """Filtro ccaa='Madrid' → total_activas solo incluye filas de Madrid."""
    _insert(
        [
            _row("M1", ccaa="Madrid", estado="PUB"),
            _row("M2", ccaa="Madrid", estado="PUB"),
            _row("C1", ccaa="Cataluña", estado="PUB"),
        ]
    )

    result = get_resumen_hoy(ResumenHoyFilters(ccaa="Madrid"))

    assert result.total_activas == 2


def test_hoy_solo_estados_activos_cuentan(tmp_db):
    """total_activas descuenta los estados terminales, no enumera los abiertos.

    Antes decía "solo cuenta PUB y EV", y el SQL lo cumplía al pie de la letra
    con una lista blanca. Este test pasaba porque sólo sembraba PUB/EV/RES/ADJ,
    que se comportan igual con las dos reglas — por eso el fallo sobrevivió a la
    suite entera. `ADM` es el estado que las distingue, y es el más común en los
    datos reales: con la lista blanca, el resumen decía 0 activas mientras el
    Radar listaba 12. Ver `shared/estados.py`.
    """
    _insert(
        [
            _row("P1", estado="PUB"),
            _row("E1", estado="EV"),
            _row("D1", estado="ADM"),  # abierta: en plazo de admisión
            _row("X1", estado="XYZ"),  # abierta: código que la fuente no documentó
            _row("R1", estado="RES"),  # no activa
            _row("A1", estado="ADJ"),  # no activa
            _row("N1", estado="ANUL"),  # no activa
        ]
    )

    result = get_resumen_hoy(ResumenHoyFilters())

    assert result.total_activas == 4


def test_hoy_nuevas_24h(tmp_db):
    """nuevas_24h cuenta solo lo publicado en las últimas 24 horas."""
    _insert(
        [
            _row("H1", fecha_pub_offset=0),
            _row("H2", fecha_pub_offset=-3),
        ]
    )

    result = get_resumen_hoy(ResumenHoyFilters())

    assert result.nuevas_24h == 1


# ---------------------------------------------------------------------------
# get_timeline_scatter
# ---------------------------------------------------------------------------


def test_timeline_scatter_devuelve_items(tmp_db):
    """Scatter devuelve campos id_externo, importe y fecha_publicacion."""
    _insert([_row("T1", importe=500_000.0), _row("T2", importe=250_000.0)])

    result = get_timeline_scatter(TimelineScatterFilters())

    assert len(result.items) == 2
    ids = {item.id_externo for item in result.items}
    assert ids == {"T1", "T2"}
    for item in result.items:
        assert item.importe is not None
        assert item.fecha_publicacion is not None


def test_timeline_scatter_vacio(tmp_db):
    """Sin filas → items=[]."""
    result = get_timeline_scatter(TimelineScatterFilters())

    assert result.items == []


def test_timeline_scatter_campos_completos(tmp_db):
    """Cada item expone todos los campos definidos en TimelineScatterItem."""
    _insert([_row("F1", organo="Ayuntamiento", ccaa="Madrid", tipo_contrato="3")])

    result = get_timeline_scatter(TimelineScatterFilters())

    item = result.items[0]
    assert item.id_externo == "F1"
    assert item.organo_contratacion == "Ayuntamiento"
    assert item.ccaa == "Madrid"
    assert item.tipo_contrato == "3"
    assert item.estado == "PUB"


def test_timeline_scatter_orden_descendente_y_filtro_fecha(tmp_db):
    """Ordena por fecha_publicacion descendente y respeta fecha_desde."""
    _insert(
        [
            _row("VIEJA", fecha_pub_offset=-40),
            _row("MEDIA", fecha_pub_offset=-10),
            _row("NUEVA", fecha_pub_offset=-1),
        ]
    )

    result = get_timeline_scatter(TimelineScatterFilters())
    assert [i.id_externo for i in result.items] == ["NUEVA", "MEDIA", "VIEJA"]

    desde = (datetime.now(UTC) - timedelta(days=20)).date()
    filtrado = get_timeline_scatter(TimelineScatterFilters(fecha_desde=desde))
    assert [i.id_externo for i in filtrado.items] == ["NUEVA", "MEDIA"]


def test_timeline_scatter_declara_el_total_de_la_ventana(tmp_db):
    """`total` cuenta la ventana entera, no las filas devueltas."""
    _insert([_row(f"T{i}", fecha_pub_offset=-i) for i in range(1, 6)])

    result = get_timeline_scatter(TimelineScatterFilters())

    assert result.total == 5
    assert result.muestreado is False


def test_timeline_scatter_muestra_cubre_toda_la_ventana(tmp_db):
    """Con `muestrear`, la selección se reparte por el rango pedido.

    El bug que fija: `/resumen/timeline` devolvía las N más recientes, así que
    la nube del Resumen —rotulada «en el periodo»— dibujaba las últimas 48
    horas de una ventana de 30 días. Aquí se comprime el tope a 5 para poder
    comprobarlo con un dataset pequeño: la muestra tiene que tocar el extremo
    viejo del rango, que es justo lo que el modo «más recientes» nunca alcanza.
    """
    _insert([_row(f"D{dia:03d}", fecha_pub_offset=-dia) for dia in range(1, 31)])

    with patch("services.analytics.resumen._TIMELINE_LIMIT", 5):
        recientes = get_timeline_scatter(TimelineScatterFilters())
        muestra = get_timeline_scatter(TimelineScatterFilters(muestrear=True))

    assert recientes.total == 30
    assert muestra.total == 30
    assert muestra.muestreado is True

    # Las más recientes se agolpan en la cabecera del rango…
    assert [i.id_externo for i in recientes.items] == [
        "D001",
        "D002",
        "D003",
        "D004",
        "D005",
    ]
    # …y la muestra toma una de cada `ceil(30/5) = 6`, llegando al día 25.
    ids_muestra = [i.id_externo for i in muestra.items]
    assert ids_muestra == ["D001", "D007", "D013", "D019", "D025"]


def test_timeline_scatter_muestra_no_recorta_si_cabe_entera(tmp_db):
    """Ventana por debajo del tope: `muestrear` devuelve todo y no miente."""
    _insert([_row(f"C{i}", fecha_pub_offset=-i) for i in range(1, 4)])

    result = get_timeline_scatter(TimelineScatterFilters(muestrear=True))

    assert len(result.items) == 3
    assert result.total == 3
    # No se dejó nada fuera, así que no es una muestra.
    assert result.muestreado is False


# ---------------------------------------------------------------------------
# get_sankey_flow
# ---------------------------------------------------------------------------


def test_sankey_nodes_y_links(tmp_db):
    """2 tipo_contrato x 2 estado → nodes y links no vacíos."""
    _insert(
        [
            _row("S1", tipo_contrato="2", estado="PUB"),
            _row("S2", tipo_contrato="2", estado="ADJ"),
            _row("S3", tipo_contrato="3", estado="PUB"),
            _row("S4", tipo_contrato="3", estado="ADJ"),
        ]
    )

    result = get_sankey_flow(SankeyFilters())

    # Debe tener 2 nodos tipo + 2 nodos estado = 4 nodos
    assert len(result.nodes) == 4
    assert len(result.links) == 4

    node_ids = {n.id for n in result.nodes}
    assert "tipo_2" in node_ids
    assert "tipo_3" in node_ids
    assert "estado_PUB" in node_ids
    assert "estado_ADJ" in node_ids

    # Cada link tiene value >= 1
    for link in result.links:
        assert link.value >= 1


def test_sankey_sin_tipo_contrato(tmp_db):
    """Filas con tipo_contrato nulo quedan fuera → SankeyResult vacío."""
    _insert([_row("X1", tipo_contrato=None)])

    result = get_sankey_flow(SankeyFilters())

    assert result.nodes == []
    assert result.links == []


def test_sankey_dataset_vacio(tmp_db):
    """Sin filas → SankeyResult vacío."""
    result = get_sankey_flow(SankeyFilters())

    assert result.nodes == []
    assert result.links == []


# ---------------------------------------------------------------------------
# get_top_licitaciones
# ---------------------------------------------------------------------------


def _insert_adjudicacion(
    licitacion_id: str, nombre: str, importe_adjudicado: float, nif: str = "B00000000"
) -> None:
    from db.database import connect, now_utc_iso

    with connect() as c:
        c.execute(
            "INSERT INTO adjudicaciones "
            "(licitacion_id, nombre, nif, importe_adjudicado, fecha_adjudicacion, "
            "fecha_extraccion) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (licitacion_id, nombre, nif, importe_adjudicado, now_utc_iso(), now_utc_iso()),
        )


def test_top_licitaciones_enriquece_con_adjudicatario(tmp_db):
    """Top licitación con adjudicación → adjudicatario y baja_pct presentes."""
    _insert([_row("TOP1", importe=1_000_000.0), _row("TOP2", importe=500_000.0)])
    _insert_adjudicacion("TOP1", "EMPRESA GANADORA S.A.", 800_000.0)

    result = get_top_licitaciones(TopLicitacionesFilters(n=2))

    top1 = next(i for i in result.items if i.id_externo == "TOP1")
    assert top1.adjudicatario == "EMPRESA GANADORA S.A."
    assert top1.baja_pct == pytest.approx(20.0)  # (1 - 800k/1000k) x 100


def test_top_licitaciones_sin_adjudicaciones(tmp_db):
    """Sin adjudicaciones → adjudicatario=None, baja_pct=None para todas."""
    _insert([_row("T1", importe=300_000.0), _row("T2", importe=200_000.0)])

    result = get_top_licitaciones(TopLicitacionesFilters(n=5))

    assert len(result.items) == 2
    for item in result.items:
        assert item.adjudicatario is None
        assert item.baja_pct is None


def test_top_licitaciones_dataset_vacio(tmp_db):
    """Sin filas → items=[]."""
    result = get_top_licitaciones(TopLicitacionesFilters())

    assert result.items == []


def test_top_licitaciones_respeta_n(tmp_db):
    """Solo devuelve las N más grandes por importe."""
    _insert([_row(f"L{i}", importe=float(i * 10_000)) for i in range(1, 11)])

    result = get_top_licitaciones(TopLicitacionesFilters(n=3))

    assert len(result.items) == 3
    importes = [item.importe for item in result.items]
    # Los 3 mayores: L10=100k, L9=90k, L8=80k
    assert importes == sorted(importes, reverse=True)
