"""Instrumentación Prometheus para el scraper de licitaciones SAP.

Expone métricas en formato texto Prometheus a través de un fichero .prom
(``data/metrics/scraper.prom``) que puede ser consumido por un node_exporter
con textfile collector, o bien por un servidor HTTP mínimo incluido aquí.

Métricas expuestas:
  - licitaciones_sap_scraper_runs_total{status}       — Contador de runs
  - licitaciones_sap_items_total{status}              — Ítems procesados
  - licitaciones_sap_run_duration_seconds             — Histograma de duración
  - licitaciones_sap_db_total                         — Gauge total en BD
  - licitaciones_sap_last_run_timestamp               — Timestamp último run
  - licitaciones_sap_parse_errors_total               — Errores de parseo
  - licitaciones_sap_download_errors_total            — Errores de descarga

Uso:
    # Desde el pipeline (automático vía instrument_run):
    from observability.prometheus import instrument_run
    with instrument_run("bulk") as m:
        m.record_items(nuevas=10, actualizadas=5)

    # Exponer endpoint HTTP /metrics (opcional):
    python -m observability.prometheus serve --port 9091
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from observability.logging import get_logger

log = get_logger(__name__)

# Directorio donde se escriben los ficheros .prom
_METRICS_DIR = Path(__file__).parents[1] / "data" / "metrics"
_METRICS_FILE = _METRICS_DIR / "scraper.prom"


def _prometheus_available() -> bool:
    try:
        import prometheus_client  # noqa: F401

        return True
    except ImportError:
        return False


# ── Métricas internas (acumuladas en memoria, volcadas a disco al terminar) ──


@dataclass
class RunInstrumentation:
    """Acumula métricas de un run individual."""

    source: str
    _t_start: float = field(default_factory=time.monotonic, init=False)
    nuevas: int = 0
    actualizadas: int = 0
    errores_parseo: int = 0
    errores_descarga: int = 0
    status: str = "ok"

    def record_items(self, *, nuevas: int = 0, actualizadas: int = 0) -> None:
        self.nuevas += nuevas
        self.actualizadas += actualizadas

    def record_parse_error(self, n: int = 1) -> None:
        self.errores_parseo += n

    def record_download_error(self, n: int = 1) -> None:
        self.errores_descarga += n

    @property
    def duration_seconds(self) -> float:
        return time.monotonic() - self._t_start


@contextmanager
def instrument_run(source: str) -> Iterator[RunInstrumentation]:
    """Context manager que instrumenta un run y vuelca métricas al terminar."""
    m = RunInstrumentation(source=source)
    try:
        yield m
    except Exception:
        m.status = "error"
        raise
    finally:
        try:
            _write_metrics(m)
        except Exception as e:
            log.warning("prometheus.write_error", error=str(e))


# ── Escritura de métricas en formato texto Prometheus ─────────────────────────


def _write_metrics(run: RunInstrumentation) -> None:
    """Vuelca las métricas del run a un fichero .prom."""
    if _prometheus_available():
        _write_via_client(run)
    else:
        _write_text_file(run)


def _write_via_client(run: RunInstrumentation) -> None:
    """Usa prometheus_client para escribir métricas (formato correcto)."""
    from prometheus_client import (
        CollectorRegistry,
        Counter,
        Gauge,
        write_to_textfile,
    )

    registry = CollectorRegistry()

    # Contadores de runs
    runs_total = Counter(
        "licitaciones_sap_scraper_runs_total",
        "Total de runs del scraper",
        ["status", "source"],
        registry=registry,
    )
    runs_total.labels(status=run.status, source=run.source).inc()

    # Ítems procesados
    items_new = Counter(
        "licitaciones_sap_items_nuevas_total",
        "Licitaciones nuevas insertadas",
        ["source"],
        registry=registry,
    )
    items_new.labels(source=run.source).inc(run.nuevas)

    items_updated = Counter(
        "licitaciones_sap_items_actualizadas_total",
        "Licitaciones actualizadas",
        ["source"],
        registry=registry,
    )
    items_updated.labels(source=run.source).inc(run.actualizadas)

    # Duración (Gauge — no Histogram para evitar buckets complejos en textfile)
    duration = Gauge(
        "licitaciones_sap_run_duration_seconds",
        "Duración del último run en segundos",
        ["source"],
        registry=registry,
    )
    duration.labels(source=run.source).set(run.duration_seconds)

    # Timestamp del último run
    last_run = Gauge(
        "licitaciones_sap_last_run_timestamp",
        "Timestamp UNIX del último run completado",
        ["source"],
        registry=registry,
    )
    last_run.labels(source=run.source).set(time.time())

    # Errores
    parse_errors = Counter(
        "licitaciones_sap_parse_errors_total",
        "Errores de parseo XML",
        ["source"],
        registry=registry,
    )
    parse_errors.labels(source=run.source).inc(run.errores_parseo)

    download_errors = Counter(
        "licitaciones_sap_download_errors_total",
        "Errores de descarga",
        ["source"],
        registry=registry,
    )
    download_errors.labels(source=run.source).inc(run.errores_descarga)

    # Total en BD (gauge global)
    db_total = Gauge(
        "licitaciones_sap_db_total",
        "Total de licitaciones en la base de datos",
        registry=registry,
    )
    try:
        from db.database import count_licitaciones

        db_total.set(count_licitaciones())
    except Exception:
        db_total.set(0)

    _METRICS_DIR.mkdir(parents=True, exist_ok=True)
    write_to_textfile(str(_METRICS_FILE), registry)
    log.info("prometheus.metrics_written", path=str(_METRICS_FILE))


def _write_text_file(run: RunInstrumentation) -> None:
    """Escribe métricas en formato texto Prometheus sin la librería cliente."""
    _METRICS_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()

    db_total = 0
    try:
        from db.database import count_licitaciones

        db_total = count_licitaciones()
    except Exception:
        pass

    lines = [
        "# HELP licitaciones_sap_scraper_runs_total Total de runs del scraper",
        "# TYPE licitaciones_sap_scraper_runs_total counter",
        f'licitaciones_sap_scraper_runs_total{{status="{run.status}",source="{run.source}"}} 1',
        "# HELP licitaciones_sap_items_nuevas_total Licitaciones nuevas insertadas",
        "# TYPE licitaciones_sap_items_nuevas_total counter",
        f'licitaciones_sap_items_nuevas_total{{source="{run.source}"}} {run.nuevas}',
        "# HELP licitaciones_sap_items_actualizadas_total Licitaciones actualizadas",
        "# TYPE licitaciones_sap_items_actualizadas_total counter",
        f'licitaciones_sap_items_actualizadas_total{{source="{run.source}"}} {run.actualizadas}',
        "# HELP licitaciones_sap_run_duration_seconds Duracion del ultimo run",
        "# TYPE licitaciones_sap_run_duration_seconds gauge",
        f'licitaciones_sap_run_duration_seconds{{source="{run.source}"}} {run.duration_seconds:.3f}',
        "# HELP licitaciones_sap_last_run_timestamp Timestamp UNIX del ultimo run",
        "# TYPE licitaciones_sap_last_run_timestamp gauge",
        f'licitaciones_sap_last_run_timestamp{{source="{run.source}"}} {now:.0f}',
        "# HELP licitaciones_sap_parse_errors_total Errores de parseo XML",
        "# TYPE licitaciones_sap_parse_errors_total counter",
        f'licitaciones_sap_parse_errors_total{{source="{run.source}"}} {run.errores_parseo}',
        "# HELP licitaciones_sap_download_errors_total Errores de descarga",
        "# TYPE licitaciones_sap_download_errors_total counter",
        f'licitaciones_sap_download_errors_total{{source="{run.source}"}} {run.errores_descarga}',
        "# HELP licitaciones_sap_db_total Total de licitaciones en la BD",
        "# TYPE licitaciones_sap_db_total gauge",
        f"licitaciones_sap_db_total {db_total}",
    ]
    _METRICS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("prometheus.metrics_written_text", path=str(_METRICS_FILE))


# ── Servidor HTTP mínimo para /metrics ────────────────────────────────────────


def serve_metrics(host: str = "0.0.0.0", port: int = 9091) -> None:  # noqa: S104
    """Arranca un servidor HTTP que expone /metrics en el puerto dado.

    Requiere prometheus_client. Si no está instalado, lanza ImportError.
    """
    from prometheus_client import start_http_server

    _METRICS_DIR.mkdir(parents=True, exist_ok=True)
    log.info("prometheus.server_start", host=host, port=port)
    start_http_server(port, addr=host)
    print(f"Métricas disponibles en http://{host}:{port}/metrics")
    print("Pulsa Ctrl+C para detener.")
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        print("\nServidor detenido.")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "info"
    if cmd == "serve":
        port = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[2] == "--port" else 9091
        serve_metrics(port=port)
    elif cmd == "info":
        print(f"Fichero de métricas: {_METRICS_FILE}")
        print(f"prometheus_client disponible: {_prometheus_available()}")
        if _METRICS_FILE.exists():
            print(f"Última actualización: {os.path.getmtime(_METRICS_FILE)}")
            print(_METRICS_FILE.read_text(encoding="utf-8"))
        else:
            print("Aún no hay métricas escritas.")
    else:
        print("Uso: python -m observability.prometheus [serve [--port N]|info]")
        sys.exit(1)
