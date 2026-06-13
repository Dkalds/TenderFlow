"""Tests para shared/parquet_manifest.py — manifest de linaje del snapshot Parquet (RFC 086)."""

from __future__ import annotations

import json

from shared.parquet_manifest import Manifest, read_manifest, write_manifest

# ── write_manifest / read_manifest roundtrip ────────────────────────────────


def test_roundtrip_duckdb_parquet_engine(tmp_path):
    """write_manifest + read_manifest preserva todos los campos para engine=duckdb-parquet."""
    path = tmp_path / "_manifest.json"
    row_counts = {"licitaciones": 311, "adjudicaciones": 120}

    written = write_manifest(
        path,
        engine="duckdb-parquet",
        row_counts=row_counts,
        source_db_mtime=1718000000.0,
    )

    assert written.engine == "duckdb-parquet"
    assert written.row_counts == row_counts
    assert written.source_db_mtime == 1718000000.0
    assert written.generated_at  # ISO timestamp no vacío

    read_back = read_manifest(path)
    assert read_back == written
    assert isinstance(read_back, Manifest)


def test_roundtrip_sqlite_direct_engine(tmp_path):
    """write_manifest + read_manifest preserva todos los campos para engine=sqlite-direct."""
    path = tmp_path / "_manifest.json"
    row_counts = {"licitaciones": 50, "adjudicaciones": 10}

    written = write_manifest(
        path,
        engine="sqlite-direct",
        row_counts=row_counts,
        source_db_mtime=1700000000.5,
    )

    assert written.engine == "sqlite-direct"

    read_back = read_manifest(path)
    assert read_back is not None
    assert read_back.engine == "sqlite-direct"
    assert read_back.row_counts == row_counts
    assert read_back.source_db_mtime == 1700000000.5


def test_generated_at_timestamp_parses_iso_string(tmp_path):
    """generated_at_timestamp() convierte el ISO timestamp a epoch float."""
    path = tmp_path / "_manifest.json"
    written = write_manifest(
        path,
        engine="duckdb-parquet",
        row_counts={"licitaciones": 1, "adjudicaciones": 1},
        source_db_mtime=123.0,
    )

    ts = written.generated_at_timestamp()
    assert isinstance(ts, float)
    assert ts > 0


# ── escritura atómica ────────────────────────────────────────────────────────


def test_write_manifest_does_not_leave_tmp_file(tmp_path):
    """Tras write_manifest no debe quedar el fichero .tmp intermedio."""
    path = tmp_path / "_manifest.json"

    write_manifest(
        path,
        engine="duckdb-parquet",
        row_counts={"licitaciones": 5, "adjudicaciones": 2},
        source_db_mtime=999.0,
    )

    tmp_file = path.with_suffix(path.suffix + ".tmp")
    assert not tmp_file.exists()
    assert path.exists()


def test_write_manifest_creates_parent_dirs(tmp_path):
    """write_manifest crea los directorios padre si no existen."""
    path = tmp_path / "nested" / "dir" / "_manifest.json"

    write_manifest(
        path,
        engine="sqlite-direct",
        row_counts={"licitaciones": 0, "adjudicaciones": 0},
        source_db_mtime=0.0,
    )

    assert path.exists()


def test_written_file_is_valid_json_with_expected_keys(tmp_path):
    """El contenido escrito es JSON válido con las claves esperadas."""
    path = tmp_path / "_manifest.json"

    write_manifest(
        path,
        engine="duckdb-parquet",
        row_counts={"licitaciones": 7, "adjudicaciones": 3},
        source_db_mtime=42.0,
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data.keys()) == {"generated_at", "engine", "row_counts", "source_db_mtime"}
    assert data["engine"] == "duckdb-parquet"
    assert data["row_counts"] == {"licitaciones": 7, "adjudicaciones": 3}


def test_write_manifest_overwrites_existing_file(tmp_path):
    """Una segunda escritura reemplaza el contenido del manifest existente."""
    path = tmp_path / "_manifest.json"

    write_manifest(
        path,
        engine="sqlite-direct",
        row_counts={"licitaciones": 1, "adjudicaciones": 1},
        source_db_mtime=1.0,
    )
    second = write_manifest(
        path,
        engine="duckdb-parquet",
        row_counts={"licitaciones": 99, "adjudicaciones": 88},
        source_db_mtime=2.0,
    )

    read_back = read_manifest(path)
    assert read_back == second
    assert read_back.engine == "duckdb-parquet"
    assert read_back.row_counts == {"licitaciones": 99, "adjudicaciones": 88}


def test_write_manifest_invalid_engine_raises(tmp_path):
    """write_manifest rechaza valores de engine no soportados."""
    import pytest

    path = tmp_path / "_manifest.json"

    with pytest.raises(ValueError):
        write_manifest(
            path,
            engine="bogus-engine",  # type: ignore[arg-type]
            row_counts={"licitaciones": 1},
            source_db_mtime=1.0,
        )


# ── read_manifest: ausente / corrupto ───────────────────────────────────────


def test_read_manifest_returns_none_when_file_missing(tmp_path):
    """read_manifest devuelve None si el fichero no existe."""
    path = tmp_path / "does_not_exist.json"

    assert read_manifest(path) is None


def test_read_manifest_returns_none_when_json_corrupt(tmp_path):
    """read_manifest devuelve None si el JSON está corrupto (no parseable)."""
    path = tmp_path / "_manifest.json"
    path.write_text("{not valid json", encoding="utf-8")

    assert read_manifest(path) is None


def test_read_manifest_returns_none_when_json_incomplete(tmp_path):
    """read_manifest devuelve None si faltan campos requeridos en el JSON."""
    path = tmp_path / "_manifest.json"
    path.write_text(json.dumps({"generated_at": "2024-01-01T00:00:00+00:00"}), encoding="utf-8")

    assert read_manifest(path) is None


def test_read_manifest_returns_none_when_engine_invalid(tmp_path):
    """read_manifest devuelve None si engine no es uno de los valores válidos."""
    path = tmp_path / "_manifest.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": "2024-01-01T00:00:00+00:00",
                "engine": "not-a-real-engine",
                "row_counts": {"licitaciones": 1},
                "source_db_mtime": 1.0,
            }
        ),
        encoding="utf-8",
    )

    assert read_manifest(path) is None


def test_read_manifest_returns_none_when_row_counts_not_dict(tmp_path):
    """read_manifest devuelve None si row_counts no es un dict serializable como tal."""
    path = tmp_path / "_manifest.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": "2024-01-01T00:00:00+00:00",
                "engine": "duckdb-parquet",
                "row_counts": "not-a-dict",
                "source_db_mtime": 1.0,
            }
        ),
        encoding="utf-8",
    )

    assert read_manifest(path) is None
