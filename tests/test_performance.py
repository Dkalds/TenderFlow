"""Tests de rendimiento — parseo XML masivo y upserts a gran escala.

Marcar con @pytest.mark.slow para excluir de CI por defecto.
Ejecutar con: make test-perf  o  pytest tests/test_performance.py -m slow
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.slow


def _generate_xml_entries(n: int) -> bytes:
    """Genera un XML ATOM sintético con N entries de licitación."""
    root = ET.Element("feed", xmlns="http://www.w3.org/2005/Atom")
    for i in range(n):
        entry = ET.SubElement(root, "entry")
        title = ET.SubElement(entry, "title")
        title.text = f"Licitación SAP de prueba número {i} - Implantación S/4HANA"
        summary = ET.SubElement(entry, "summary")
        summary.text = (
            f"Descripción extensa del proyecto {i} que incluye consultoría SAP, "
            f"migración ABAP, desarrollo Fiori y formación de usuarios finales "
            f"para el módulo FI/CO del Ministerio de Pruebas."
        )
        _id = ET.SubElement(entry, "id")
        _id.text = f"https://example.com/licitacion/PERF-{i:06d}"
        updated = ET.SubElement(entry, "updated")
        updated.text = (datetime.now(UTC) - timedelta(days=i % 365)).isoformat()
    return ET.tostring(root, encoding="unicode").encode("utf-8")


@pytest.fixture()
def perf_db(monkeypatch, tmp_path):
    """BD temporal para tests de rendimiento."""
    import db.database as db_mod

    db_path = tmp_path / "perf.db"
    monkeypatch.setenv("TURSO_DATABASE_URL", "")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "")

    db_mod.close_pool()
    db_mod.set_db_path_override(str(db_path))
    db_mod.init_db()
    yield db_mod
    db_mod.close_pool()
    db_mod.set_db_path_override(None)


class TestUpsertPerformance:
    """Verifica que upsert masivo completa en tiempo razonable."""

    def test_upsert_10k_records(self, perf_db):
        from db.database import Licitacion, upsert_licitaciones

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
                ccaa=["Madrid", "Cataluña", "Andalucía", "Valencia", "P. Vasco"][i % 5],
                raw_keywords="SAP",
                fecha_extraccion=now_iso,
            )
            for i in range(10_000)
        ]

        t0 = time.monotonic()
        nuevas, actualizadas = upsert_licitaciones(lics)
        elapsed = time.monotonic() - t0

        assert nuevas == 10_000
        assert actualizadas == 0
        # En SQLite local debería completar en menos de 30 segundos
        assert elapsed < 30.0, f"Upsert 10K tardó {elapsed:.1f}s (máx 30s)"

    def test_upsert_idempotent_10k(self, perf_db):
        """El segundo upsert con mismos datos debe ser comparablemente rápido."""
        from db.database import Licitacion, upsert_licitaciones

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

        t0 = time.monotonic()
        nuevas, actualizadas = upsert_licitaciones(lics)
        elapsed = time.monotonic() - t0

        assert nuevas == 0
        assert actualizadas == 10_000
        assert elapsed < 30.0, f"Re-upsert 10K tardó {elapsed:.1f}s (máx 30s)"


class TestQueryPerformance:
    """Verifica que consultas de agregación sobre volúmenes grandes son rápidas."""

    def test_aggregate_query_on_10k(self, perf_db):
        from db.database import Licitacion, connect, upsert_licitaciones

        now_iso = datetime.now(UTC).isoformat()
        lics = [
            Licitacion(
                id_externo=f"PERF-AGG-{i:06d}",
                titulo=f"Licitación {i}",
                importe=float(100_000 + i),
                ccaa=["Madrid", "Cataluña", "Andalucía", "Valencia", "P. Vasco"][i % 5],
                estado=["PUB", "ADJ", "ANUL", "RES", "EVA"][i % 5],
                fecha_publicacion=(datetime.now(UTC) - timedelta(days=i % 365)).isoformat(),
                fecha_extraccion=now_iso,
            )
            for i in range(10_000)
        ]
        upsert_licitaciones(lics)

        t0 = time.monotonic()
        with connect() as c:
            # Agregación por CCAA
            rows = c.execute(
                "SELECT ccaa, COUNT(*), SUM(importe) FROM licitaciones GROUP BY ccaa"
            ).fetchall()
            # Agregación por estado
            c.execute("SELECT estado, COUNT(*) FROM licitaciones GROUP BY estado").fetchall()
            # Búsqueda por texto
            c.execute(
                "SELECT COUNT(*) FROM licitaciones WHERE titulo LIKE ?",
                ["%Licitación 5%"],
            ).fetchone()
        elapsed = time.monotonic() - t0

        assert len(rows) >= 5
        assert elapsed < 5.0, f"Queries de agregación tardaron {elapsed:.1f}s (máx 5s)"


class TestXMLParsingPerformance:
    """Verifica rendimiento del parseo XML."""

    def test_parse_large_xml(self, tmp_path):
        """Parsear un XML de ~5MB con 1000 entries debe ser rápido."""
        xml_data = _generate_xml_entries(1000)
        xml_path = tmp_path / "large_feed.xml"
        xml_path.write_bytes(xml_data)

        t0 = time.monotonic()
        # Parsear con lxml (simula lo que hace el pipeline)
        from lxml import etree

        tree = etree.parse(str(xml_path))
        root = tree.getroot()
        entries = root.findall("{http://www.w3.org/2005/Atom}entry")
        elapsed = time.monotonic() - t0

        assert len(entries) == 1000
        assert elapsed < 5.0, f"Parseo XML 1K entries tardó {elapsed:.1f}s (máx 5s)"


class TestFTSPerformance:
    """Verifica que la búsqueda FTS5 es rápida sobre 10K registros."""

    def test_fts_search_10k(self, perf_db):
        from db.database import Licitacion, connect, upsert_licitaciones

        now_iso = datetime.now(UTC).isoformat()
        lics = [
            Licitacion(
                id_externo=f"FTS-{i:06d}",
                titulo=f"Implantación SAP HANA módulo {'FI' if i % 2 == 0 else 'CO'} licitación {i}",
                descripcion=f"Consultoría ABAP desarrollo Fiori {i}",
                fecha_extraccion=now_iso,
            )
            for i in range(10_000)
        ]
        upsert_licitaciones(lics)

        t0 = time.monotonic()
        with connect() as c:
            # FTS5 full-text search
            rows = c.execute(
                "SELECT COUNT(*) FROM licitaciones_fts WHERE licitaciones_fts MATCH ?",
                ["SAP HANA"],
            ).fetchone()
        elapsed = time.monotonic() - t0

        assert rows[0] > 0
        assert elapsed < 2.0, f"FTS5 search tardó {elapsed:.1f}s (máx 2s)"


class TestClusteringPerformance:
    """Verifica que el clustering es aceptablemente rápido con TF-IDF fallback."""

    def test_cluster_1k_rows_tfidf(self):
        """Clustering sobre 1K filas con TF-IDF debe completar en <10s."""
        from dashboard.clustering import _tfidf_embeddings

        texts = [
            f"Sistema SAP S/4HANA implantación módulo {'FI' if i % 3 == 0 else 'MM'} "
            f"para organismo público {i}"
            for i in range(1_000)
        ]

        t0 = time.monotonic()
        embeddings = _tfidf_embeddings(texts)
        elapsed = time.monotonic() - t0

        assert embeddings.shape == (1_000, min(256, embeddings.shape[1]))
        assert elapsed < 10.0, f"TF-IDF 1K textos tardó {elapsed:.1f}s (máx 10s)"

    def test_cluster_500_rows_kmeans(self):
        """KMeans clustering sobre 500 filas (via TF-IDF) debe terminar en <30s."""
        import numpy as np
        import pandas as pd

        from dashboard.clustering import cluster_licitaciones

        rng = np.random.default_rng(42)
        df = pd.DataFrame(
            {
                "id_externo": [f"PERF-CLUSTER-{i}" for i in range(500)],
                "titulo": [
                    f"{'SAP ERP' if i % 4 == 0 else 'Cloud AWS'} licitación {i}" for i in range(500)
                ],
                "descripcion": [f"Descripción proyecto {i}" for i in range(500)],
                "importe": rng.integers(10_000, 1_000_000, 500).astype(float),
            }
        )

        # Forzar cache clear para el benchmark
        cluster_licitaciones.clear()
        t0 = time.monotonic()
        result = cluster_licitaciones(df, n_clusters=5)
        elapsed = time.monotonic() - t0

        assert "cluster_id" in result.columns
        assert elapsed < 30.0, f"Clustering 500 filas tardó {elapsed:.1f}s (máx 30s)"
        cluster_licitaciones.clear()
