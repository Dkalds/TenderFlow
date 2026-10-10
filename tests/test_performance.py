"""Tests de volumen: upsert, agregados, feed, búsqueda y clustering sobre miles de filas.

Ninguno mira el reloj. Había seis cotas de tiempo, de 2 a 30 segundos, que
medían el runner. Cada test comprueba ahora lo que decide el rendimiento, que es
determinista; el detalle está en cada clase.

Siguen marcados ``slow`` (cuatro escriben 10 000 filas): quedan fuera de
``make check`` y de ``make test-unit``, y se corren a mano con ``make test-perf``.
En CI **sí** corren: ``Tests (Postgres)`` no filtra por marker.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

pytestmark = pytest.mark.slow

_CCAA = ("Madrid", "Cataluña", "Andalucía", "Valencia", "P. Vasco")
_ESTADOS = ("PUB", "ADJ", "ANUL", "RES", "EVA")


def _titulo_del_feed(i: int) -> str:
    return f"Licitación SAP de prueba número {i} - Implantación S/4HANA"


def _resumen_del_feed(i: int) -> str:
    """Unos 5 KB de texto: con 1000 entradas, el feed pasa de los 5 MB."""
    frase = (
        f"Descripción extensa del proyecto {i} que incluye consultoría SAP, "
        "migración ABAP, desarrollo Fiori y formación de usuarios finales "
        "para el módulo FI/CO del Ministerio de Pruebas."
    )
    return " ".join([frase] * 28)


def _id_del_feed(i: int) -> str:
    return f"https://example.com/licitacion/PERF-{i:06d}"


def _generate_xml_entries(n: int) -> bytes:
    """Genera un XML ATOM sintético con N entries de licitación."""
    root = ET.Element("feed", xmlns="http://www.w3.org/2005/Atom")
    for i in range(n):
        entry = ET.SubElement(root, "entry")
        title = ET.SubElement(entry, "title")
        title.text = _titulo_del_feed(i)
        summary = ET.SubElement(entry, "summary")
        summary.text = _resumen_del_feed(i)
        _id = ET.SubElement(entry, "id")
        _id.text = _id_del_feed(i)
        updated = ET.SubElement(entry, "updated")
        updated.text = (datetime.now(UTC) - timedelta(days=i % 365)).isoformat()
    return ET.tostring(root, encoding="unicode").encode("utf-8")


@pytest.fixture()
def perf_db(tmp_db):
    """Schema Postgres aislado para tests de rendimiento."""
    db_mod, _ = tmp_db
    yield db_mod


@pytest.fixture()
def sentencias(monkeypatch) -> list[str]:
    """Las sentencias que ``db.upsert`` envía a la BD: cada una es un viaje."""
    import db.upsert as up

    enviadas: list[str] = []
    conectar_de_verdad = up.connect

    class _Apuntando:
        def __init__(self, conn) -> None:
            self._conn = conn

        def execute(self, sql, *args):
            enviadas.append(sql)
            return self._conn.execute(sql, *args)

        def executemany(self, sql, seq):
            enviadas.append(sql)
            return self._conn.executemany(sql, seq)

    @contextmanager
    def apuntando():
        with conectar_de_verdad() as conn:
            yield _Apuntando(conn)

    monkeypatch.setattr(up, "connect", apuntando)
    return enviadas


def _indices_del_plan(db_mod: Any, sql: str) -> set[str]:
    """Índices que usa el plan de ``sql`` con el recorrido secuencial vetado.

    Vetarlo hace la respuesta determinista. Cuando casi todas las filas casan
    el planificador prefiere recorrer la tabla, y lo que se pregunta aquí no es
    qué elige sino si la consulta **puede** ir por un índice.
    """
    with db_mod.connect() as c:
        c.execute("SET LOCAL enable_seqscan = off")
        (plan,) = c.execute("EXPLAIN (FORMAT JSON) " + sql).fetchone()

    def _nodos(nodo: dict[str, Any]):
        yield nodo
        for hijo in nodo.get("Plans", []):
            yield from _nodos(hijo)

    return {nodo["Index Name"] for nodo in _nodos(plan[0]["Plan"]) if "Index Name" in nodo}


class TestUpsertPerformance:
    """10 000 licitaciones entran en unas decenas de viajes a la BD, no en 10 000.

    Los viajes son lo que decide cuánto tarda el upsert contra una BD remota, y
    se cuentan en vez de cronometrarse. Hoy son 22: veinte consultas de
    existentes, de 500 en 500, el catálogo de las sombras y un ``executemany``.
    El umbral es holgado a propósito: solo salta si vuelve el patrón fila a fila.

    La cota anterior eran 30 s. Fila a fila, contra un Postgres local, el upsert
    seguía por encima de 1 500 licitaciones por segundo (medido para
    ``test_load_scraper_placsp.py``): a ese ritmo 10 000 filas son unos 7 s, que
    esa cota tampoco habría visto.
    """

    def test_upsert_10k_records(self, perf_db, sentencias):
        from db.database import Licitacion, count_licitaciones, upsert_licitaciones

        now_iso = datetime.now(UTC).isoformat()
        lics = [
            Licitacion(
                id_externo=f"PERF-{i:06d}",
                titulo=f"Licitación SAP de prueba {i}",
                descripcion=f"Descripción del proyecto {i} con consultoría SAP",
                organo_contratacion=f"Ministerio {i % 20}",
                importe=float(100_000 + i * 10),
                cpv="72000000",
                tipo_contrato="2",
                estado="PUB",
                fecha_publicacion=now_iso,
                ccaa=_CCAA[i % 5],
                raw_keywords="SAP",
                fecha_extraccion=now_iso,
            )
            for i in range(10_000)
        ]

        nuevas, actualizadas = upsert_licitaciones(lics)

        assert (nuevas, actualizadas) == (10_000, 0)
        assert len(sentencias) < 10_000 / 100, f"{len(sentencias)} viajes para 10 000 filas"
        assert count_licitaciones() == 10_000

    def test_upsert_idempotent_10k(self, perf_db, sentencias):
        """Repetir el mismo lote no duplica filas ni cuesta más viajes que la primera vez."""
        from db.database import Licitacion, count_licitaciones, upsert_licitaciones

        now_iso = datetime.now(UTC).isoformat()
        lics = [
            Licitacion(
                id_externo=f"PERF-IDEM-{i:06d}",
                titulo=f"Licitación repetida {i}",
                fecha_extraccion=now_iso,
            )
            for i in range(10_000)
        ]
        upsert_licitaciones(lics)
        viajes_de_la_primera = len(sentencias)

        nuevas, actualizadas = upsert_licitaciones(lics)

        assert (nuevas, actualizadas) == (0, 10_000)
        assert len(sentencias) - viajes_de_la_primera == viajes_de_la_primera
        assert count_licitaciones() == 10_000


class TestQueryPerformance:
    """Lo que escribió el upsert masivo se agrega bien: grupos, sumas y texto.

    Las tres consultas son de este test, no del producto, así que su cota de 5 s
    solo medía lo que tarda Postgres en recorrer 10 000 filas. Lo que sí depende
    del proyecto es que esas filas hayan llegado enteras, y eso se comprueba con
    el resultado exacto de cada consulta.
    """

    def test_aggregate_query_on_10k(self, perf_db):
        from db.database import Licitacion, connect, upsert_licitaciones

        now_iso = datetime.now(UTC).isoformat()
        lics = [
            Licitacion(
                id_externo=f"PERF-AGG-{i:06d}",
                titulo=f"Licitación {i}",
                importe=float(100_000 + i),
                ccaa=_CCAA[i % 5],
                estado=_ESTADOS[i % 5],
                fecha_publicacion=(datetime.now(UTC) - timedelta(days=i % 365)).isoformat(),
                fecha_extraccion=now_iso,
            )
            for i in range(10_000)
        ]
        upsert_licitaciones(lics)

        with connect() as c:
            # Agregación por CCAA
            por_ccaa = c.execute(
                "SELECT ccaa, COUNT(*), SUM(importe) FROM licitaciones GROUP BY ccaa"
            ).fetchall()
            # Agregación por estado
            por_estado = c.execute(
                "SELECT estado, COUNT(*) FROM licitaciones GROUP BY estado"
            ).fetchall()
            # Búsqueda por texto
            con_un_cinco = c.execute(
                "SELECT COUNT(*) FROM licitaciones WHERE titulo LIKE %s",
                ["%Licitación 5%"],
            ).fetchone()[0]

        assert {ccaa: (filas, suma) for ccaa, filas, suma in por_ccaa} == {
            ccaa: (2_000, float(sum(100_000 + i for i in range(resto, 10_000, 5))))
            for resto, ccaa in enumerate(_CCAA)
        }
        assert dict(por_estado) == dict.fromkeys(_ESTADOS, 2_000)
        assert con_un_cinco == sum(1 for i in range(10_000) if str(i).startswith("5"))


class TestXMLParsingPerformance:
    """Un feed de 5 MB pasa entero por el parser del scraper.

    La versión anterior cronometraba ``etree.parse`` de lxml sobre un fichero de
    0,4 MB: ni tocaba código del proyecto ni pesaba los 5 MB que anunciaba. Ahora
    el feed los pesa y pasa por ``parse_atom_bytes``, con sus límites de
    seguridad puestos (``huge_tree=False``, ``MAX_XML_SIZE_BYTES``): salen las
    1000 licitaciones, en orden, y el texto largo de cada una llega sin recortar.
    """

    def test_parse_large_xml(self):
        """Parsear un XML de ~5MB con 1000 entries no pierde ni recorta ninguna."""
        from scraper.codice_parser import parse_atom_bytes

        xml_data = _generate_xml_entries(1000)

        licitaciones = [lic for lic, _adjudicaciones in parse_atom_bytes(xml_data)]

        assert len(xml_data) > 5_000_000
        assert [(lic.id_externo, lic.titulo, lic.descripcion) for lic in licitaciones] == [
            (_id_del_feed(i), _titulo_del_feed(i), _resumen_del_feed(i)) for i in range(1000)
        ]


class TestFTSPerformance:
    """La búsqueda de texto encuentra lo que escribió el upsert, y puede ir por su índice.

    Se busca con ``search_fts``, la del producto; antes el test llevaba su propia
    consulta. Que una búsqueda sobre muchas filas sea rápida depende de que pueda
    usar el índice GIN de ``search_vector``, y eso se le pregunta al planificador
    en vez de cronometrarlo.
    """

    def test_fts_search_10k(self, perf_db):
        from db.database import Licitacion, search_fts, upsert_licitaciones

        now_iso = datetime.now(UTC).isoformat()
        lics = [
            Licitacion(
                id_externo=f"FTS-{i:06d}",
                titulo=(
                    "Implantación SAP HANA módulo "
                    f"{'finanzas' if i % 2 == 0 else 'logística'} licitación {i}"
                ),
                descripcion=f"Consultoría ABAP desarrollo Fiori {i}",
                fecha_extraccion=now_iso,
            )
            for i in range(10_000)
        ]
        upsert_licitaciones(lics)

        pagina, todas = search_fts("SAP HANA", limit=20)
        _, la_mitad = search_fts("finanzas", limit=1)
        _, ninguna = search_fts("oracle", limit=1)

        assert (len(pagina), todas, la_mitad, ninguna) == (20, 10_000, 5_000, 0)
        # El mismo predicado que usa `search_fts`.
        assert "idx_licitaciones_search_vector" in _indices_del_plan(
            perf_db,
            "SELECT COUNT(*) FROM licitaciones "
            "WHERE search_vector @@ websearch_to_tsquery('spanish', 'SAP HANA')",
        )


class TestClusteringPerformance:
    """El fallback TF-IDF nunca devuelve más de 256 columnas, por ancho que sea el vocabulario.

    Ese tope es lo que acota el coste del clustering: la matriz se densifica, y
    sin él tendría una columna por término. El corpus anterior solo dejaba 14
    términos tras ``min_df``, así que el tope nunca actuaba y la comprobación de
    forma pasaba con o sin él; la cota de 10 s tampoco lo veía (medido: 16 ms
    sin tope). Este corpus tiene 600 términos y sus bigramas.
    """

    def test_cluster_1k_rows_tfidf(self):
        """Clustering sobre 1K filas con TF-IDF: la matriz sale de 1000 x 256."""
        from services.analytics.clusters import _tfidf_embeddings

        texts = [
            " ".join(f"termino{(i * 7 + j * 13) % 600:03d}" for j in range(12))
            for i in range(1_000)
        ]

        embeddings = _tfidf_embeddings(texts)

        assert embeddings.shape == (1_000, 256)
