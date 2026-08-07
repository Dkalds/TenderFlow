"""Manifest de linaje para el snapshot Parquet de hechos analíticos (RFC 086).

Registra *cuándo* y *con qué motor* se generó el snapshot Parquet de
``licitaciones``/``adjudicaciones`` (o, en su defecto, los row counts leídos
directamente de SQLite). Es el contrato de frescura entre
``db.analytics.run_analytics_export`` (escritor) y
``services.analytics_engine`` / el dashboard (lectores).

Escritura atómica: se escribe a ``<path>.tmp`` y se reemplaza con
``os.replace()`` para evitar lecturas parciales si el proceso se interrumpe
a mitad de escritura.

Uso típico::

    from shared.parquet_manifest import write_manifest, read_manifest

    write_manifest(
        "data/parquet/_manifest.json",
        engine="duckdb-parquet",
        row_counts={"licitaciones": 311, "adjudicaciones": 120},
        source_db_mtime=1718000000.0,
    )

    manifest = read_manifest("data/parquet/_manifest.json")
    if manifest is not None:
        print(manifest.generated_at, manifest.engine)
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast, get_args

from observability.logging import get_logger

log = get_logger(__name__)

#: Motores de generación soportados para el snapshot Parquet.
#:
#: ``sqlite-direct`` es **legado de solo lectura**: SQLite se retiró en ADR-021 y
#: ningún export nuevo lo emite, pero el literal sobrevive para que
#: :func:`read_manifest` no descarte manifests escritos antes de la migración
#: (validar el engine devolvería ``None`` y el snapshot viejo se vería como
#: "no disponible" en vez de "antiguo"). Su sustituto es ``postgres-direct``.
ManifestEngine = Literal["duckdb-parquet", "postgres-direct", "sqlite-direct"]

_VALID_ENGINES: frozenset[str] = frozenset(get_args(ManifestEngine))


@dataclass(frozen=True, slots=True)
class Manifest:
    """Metadata de linaje del último snapshot Parquet de hechos analíticos.

    Attributes:
        generated_at: Timestamp ISO 8601 en UTC (``datetime.isoformat()``)
            del momento en que se completó el export.
        engine: Motor usado para generar el snapshot. ``"duckdb-parquet"``
            si DuckDB estaba disponible y se exportaron ficheros ``.parquet``;
            ``"sqlite-direct"`` si se leyeron los row counts directamente de
            SQLite sin generar Parquet.
        row_counts: Recuento de filas por tabla (``{"licitaciones": n, ...}``).
        source_db_mtime: ``mtime`` (epoch, segundos) del fichero SQLite
            operacional en el momento del export, usado para detectar si el
            snapshot quedó desactualizado respecto a la BD origen.
    """

    generated_at: str
    engine: ManifestEngine
    row_counts: dict[str, int]
    source_db_mtime: float

    def generated_at_timestamp(self) -> float:
        """Devuelve ``generated_at`` parseado a epoch (segundos, UTC)."""
        return datetime.fromisoformat(self.generated_at).timestamp()


def _validate_engine(engine: str) -> ManifestEngine:
    if engine not in _VALID_ENGINES:
        raise ValueError(f"engine inválido: {engine!r}. Esperado uno de {sorted(_VALID_ENGINES)}")
    # Cast seguro: ya validamos pertenencia a _VALID_ENGINES (derivado de ManifestEngine).
    return cast(ManifestEngine, engine)


def write_manifest(
    path: Path | str,
    *,
    engine: ManifestEngine,
    row_counts: dict[str, int],
    source_db_mtime: float,
) -> Manifest:
    """Escribe el manifest de forma atómica (write-temp + ``os.replace``).

    Args:
        path: Ruta destino del fichero JSON (p.ej. ``DATA_DIR/parquet/_manifest.json``).
        engine: Motor usado para generar el snapshot.
        row_counts: Recuento de filas por tabla.
        source_db_mtime: ``mtime`` del fichero SQLite operacional origen.

    Returns:
        El :class:`Manifest` escrito (con ``generated_at`` calculado internamente).
    """
    _validate_engine(engine)
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    manifest = Manifest(
        generated_at=datetime.now(UTC).isoformat(),
        engine=engine,
        row_counts=dict(row_counts),
        source_db_mtime=source_db_mtime,
    )

    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(manifest), indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, dest)

    log.info(
        "parquet_manifest_written",
        path=str(dest),
        engine=manifest.engine,
        row_counts=manifest.row_counts,
    )
    return manifest


def read_manifest(path: Path | str) -> Manifest | None:
    """Lee el manifest desde *path*.

    Devuelve ``None`` si el fichero no existe o no se puede parsear (p.ej.
    quedó corrupto/parcial) — no lanza excepciones, los callers deben tratar
    ``None`` como "manifest no disponible, no refrescar".
    """
    src = Path(path)
    if not src.is_file():
        return None
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
        return Manifest(
            generated_at=str(data["generated_at"]),
            engine=_validate_engine(str(data["engine"])),
            row_counts={str(k): int(v) for k, v in dict(data["row_counts"]).items()},
            source_db_mtime=float(data["source_db_mtime"]),
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("parquet_manifest_read_failed", path=str(src), error=str(exc))
        return None


__all__ = ["Manifest", "ManifestEngine", "read_manifest", "write_manifest"]
