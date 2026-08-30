"""Healthcheck del pipeline.

Comprueba:
  1. La BD es accesible y tiene esquema correcto.
  2. Hubo al menos una extracción exitosa en las últimas N horas.
  3. No hay >K fallos sin resolver en la DLQ.
    4. Al menos el 99% de adjudicaciones están enlazadas con una empresa.
    5. La vista `licitaciones_canonicas` —de la que lee la superficie pública
       entera— se refrescó hace poco y no ha encogido.

Salida:
  exit 0 → healthy
  exit 1 → warning (degraded)
  exit 2 → critical (unhealthy)

También imprime un JSON con el estado para consumirse vía dashboard o CI.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path when run as `python -m scheduler.healthcheck`
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from db.database import connect, init_db  # noqa: E402
from db.repositories.publico import estado_refresco_canonicas  # noqa: E402
from observability import AlertLevel, configure_logging, get_logger, notify  # noqa: E402

log = get_logger(__name__)


def _contar_licitaciones(c: Any) -> tuple[int, bool]:
    """Filas de ``licitaciones``: estimación del planner, exacta si no sirve.

    Devuelve ``(total, estimado)``.

    El ``COUNT(*)`` exacto es un seq scan de la tabla más grande de la BD y era
    la PRIMERA consulta de este bloque: cuando cruzó el ``statement_timeout``
    de 30 s (2026-08), el ``QueryCanceled`` reventó el healthcheck entero antes
    de ejecutar ningún otro check y el post-run del scraper murió con traceback
    en vez de reportar estado. El razonamiento completo, en ``estimar_filas``.
    """
    from db.database import estimar_filas

    aproximado = estimar_filas(c, "licitaciones")
    if aproximado is not None:
        return aproximado, True
    return int(c.execute("SELECT COUNT(*) FROM licitaciones").fetchone()[0]), False


#: Caída relativa del corpus publicable que se considera anómala entre dos
#: refrescos consecutivos. El corpus solo crece salvo purga deliberada, así que
#: un 10% de pérdida ya no es ruido: es un umbral de sustancia mal tocado, un
#: lote de duplicados mal marcado o una fuente que dejó de ingerir.
_CAIDA_CANONICAS_MAX = 0.10


def _comprobar_vista_canonicas(
    c: Any,
    stale_hours: int,
    checks: list[dict[str, object]],
    warnings: list[str],
    info: dict[str, object],
) -> None:
    """Antigüedad y tamaño del último refresco de la vista pública.

    Va en su propio ``try`` por el mismo motivo que sus vecinos: un check
    secundario no puede llevarse por delante el informe entero, y con
    ``connect()`` una consulta fallida deja la sesión abortada si no se hace
    ROLLBACK.
    """
    try:
        estado = estado_refresco_canonicas(conn=c)
        con_datos = bool(estado["con_datos"])
        filas = list(estado["eventos"])
    except Exception as exc:
        # ROLLBACK obligatorio: `connect()` abre transacción, y una consulta
        # fallida dejaría abortado todo lo que viene después.
        with contextlib.suppress(Exception):
            c.rollback()
        info["canonicas_error"] = str(exc)[:200]
        # "No lo pude medir" no es "está mal", y tampoco puede tumbar el resto
        # del informe: mismo criterio que el check de resolución de empresas.
        warnings.append("canonicas_no_medida")
        checks.append({"name": "canonicas_frescas", "ok": True})
        return

    if not filas:
        # Sin ningún refresco registrado.
        #
        # Con la vista VACÍA no hay nada que afirmar: es una base sin corpus
        # —un schema de test, un entorno recién creado— y avisar ahí sería
        # ruido que acaba desactivando el check.
        #
        # Con la vista LLENA es otra cosa: hay corpus publicándose y el job que
        # debería refrescarlo no ha dejado rastro ni una vez. Es exactamente el
        # estado que este check existe para no dejar pasar.
        info["canonicas_sin_registro"] = True
        if con_datos:
            warnings.append("canonicas_sin_registro_de_refresco")
        checks.append({"name": "canonicas_frescas", "ok": not con_datos})
        return

    try:
        ultimo = datetime.fromisoformat(str(filas[0][0]))
        if ultimo.tzinfo is None:
            ultimo = ultimo.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        ultimo = datetime.now(UTC) - timedelta(days=365)

    edad_horas = (datetime.now(UTC) - ultimo).total_seconds() / 3600
    n_actual = int(filas[0][1] or 0)
    info["canonicas"] = {
        "ultimo_refresco": filas[0][0],
        "edad_horas": round(edad_horas, 1),
        "filas": n_actual,
    }

    fresca = edad_horas <= stale_hours
    if not fresca:
        warnings.append(f"canonicas_stale:{edad_horas:.1f}h")
    checks.append({"name": "canonicas_frescas", "ok": fresca})

    # Un refresco que deja la vista vacía —o mucho más pequeña— no levanta
    # ninguna excepción: es exactamente la clase de fallo que hay que cazar
    # comparando, no observando.
    if n_actual == 0:
        warnings.append("canonicas_vacias")
        checks.append({"name": "canonicas_tamano", "ok": False})
        return
    if len(filas) > 1:
        n_previo = int(filas[1][1] or 0)
        cayo = n_previo > 0 and n_actual < n_previo * (1 - _CAIDA_CANONICAS_MAX)
        if cayo:
            warnings.append(f"canonicas_encogieron:{n_previo}->{n_actual}")
        checks.append({"name": "canonicas_tamano", "ok": not cayo})
    else:
        checks.append({"name": "canonicas_tamano", "ok": True})


def run_check(
    freshness_hours: int = 36,
    dlq_threshold: int = 50,
    canonicas_stale_hours: int = 9,
) -> dict[str, Any]:
    init_db()
    status = "healthy"
    checks: list[dict[str, object]] = []
    warnings: list[str] = []
    errors: list[str] = []
    info: dict[str, object] = {}

    # --- Métricas de infraestructura ---
    from config import settings

    data_dir = Path(settings.DATA_DIR)
    try:
        info["data_dir_free_bytes"] = shutil.disk_usage(data_dir).free
    except OSError:
        info["data_dir_free_bytes"] = None

    with connect() as c:
        # Tamaño real de la BD. Antes se leía el tamaño del fichero SQLite
        # local, que con Postgres en producción era siempre 0 (ADR-021).
        try:
            info["db_size_bytes"] = int(
                c.execute("SELECT pg_database_size(current_database())").fetchone()[0]
            )
        except Exception:
            info["db_size_bytes"] = 0

        t0 = time.monotonic()
        total, total_estimado = _contar_licitaciones(c)
        info["last_query_ms"] = round((time.monotonic() - t0) * 1000, 2)
        info["licitaciones_total"] = total
        info["licitaciones_total_estimado"] = total_estimado
        checks.append({"name": "db_readable", "ok": True})

        last_run = c.execute(
            "SELECT run_id, started_at, status, months_ok, months_failed "
            "FROM extraction_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        run_ok = True
        if last_run is None:
            errors.append("sin_runs_registrados")
            run_ok = False
        else:
            info["last_run"] = {
                "run_id": last_run[0],
                "started_at": last_run[1],
                "status": last_run[2],
                "months_ok": last_run[3],
                "months_failed": last_run[4],
            }
            try:
                started = datetime.fromisoformat(last_run[1])
                if started.tzinfo is None:
                    started = started.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                started = datetime.now(UTC) - timedelta(days=365)
            age = datetime.now(UTC) - started
            info["last_run_age_hours"] = round(age.total_seconds() / 3600, 1)
            if age > timedelta(hours=freshness_hours):
                warnings.append(f"last_run_stale:{info['last_run_age_hours']}h")
                run_ok = False
            if last_run[2] == "error":
                errors.append(f"last_run_failed:{last_run[0]}")
                run_ok = False
        checks.append({"name": "last_run_fresh", "ok": run_ok})

        dlq_count = c.execute(
            "SELECT COUNT(*) FROM failed_extractions WHERE resolved_at IS NULL"
        ).fetchone()[0]
        info["dlq_unresolved"] = int(dlq_count)
        dlq_ok = dlq_count < dlq_threshold
        if not dlq_ok:
            warnings.append(f"dlq_above_threshold:{dlq_count}")
        checks.append({"name": "dlq_below_threshold", "ok": dlq_ok})

        # Cobertura de resolución de empresas. Va en su propio try/except (mismo
        # patrón que ops_events y job_locks más abajo) porque es la parte más
        # cara del healthcheck: dos recorridos completos de `adjudicaciones` —
        # uno de ellos trae al proceso TODAS las filas sin resolver y las
        # normaliza en Python. Si cruza el statement_timeout, un check
        # secundario no puede llevarse por delante el informe entero: eso es lo
        # que pasó con el COUNT(*) de licitaciones (ver _contar_licitaciones).
        try:
            empresa_total, empresa_linked = c.execute(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN empresa_id IS NOT NULL THEN 1 ELSE 0 END) "
                "FROM adjudicaciones"
            ).fetchone()
            empresa_total = int(empresa_total or 0)
            empresa_linked = int(empresa_linked or 0)
            from services.normalization import normalize_company, normalize_nif

            review_keys = {
                (row[0], row[1])
                for row in c.execute(
                    "SELECT alias_normalizado, COALESCE(nif, '') "
                    "FROM empresa_review_queue WHERE status = 'pending'"
                ).fetchall()
            }
            unresolved_identities = c.execute(
                "SELECT nombre, nif FROM adjudicaciones WHERE empresa_id IS NULL"
            ).fetchall()
            empresa_review = sum(
                (normalize_company(nombre), normalize_nif(nif) or "") in review_keys
                for nombre, nif in unresolved_identities
            )
            empresa_covered = empresa_linked + empresa_review
            empresa_coverage = empresa_covered / empresa_total * 100 if empresa_total else 100.0
            empresa_coverage_ok = empresa_coverage >= 99.0
            info["empresa_resolution"] = {
                "total": empresa_total,
                "enlazadas": empresa_linked,
                "en_revision": empresa_review,
                "pendientes": empresa_total - empresa_covered,
                "pct_filas": round(empresa_coverage, 2),
            }
            if not empresa_coverage_ok:
                warnings.append(f"empresa_resolution_below_threshold:{empresa_coverage:.2f}%")
            checks.append({"name": "empresa_resolution_coverage", "ok": empresa_coverage_ok})
        except Exception as exc:
            # ROLLBACK obligatorio antes de seguir: `connect()` abre una
            # transacción (no es autocommit), así que una consulta fallida deja
            # la sesión en estado abortado y TODO lo que viene después —
            # kpi_snapshots, job_locks, ops_events — moriría con
            # InFailedSqlTransaction. Sin esto, tragarse el error empeora el
            # síntoma en vez de arreglarlo.
            with contextlib.suppress(Exception):
                c.rollback()
            # Degrada a warning explícito: "no lo pude medir" es un estado
            # distinto de "está por debajo del umbral", y ninguno de los dos
            # justifica perder el resto del informe.
            info["empresa_resolution_error"] = str(exc)[:200]
            warnings.append("empresa_resolution_no_medida")
            checks.append({"name": "empresa_resolution_coverage", "ok": True})

        # ── Plano de orquestación activo (ADR-012) ────────────────────
        import os

        active_plane = os.environ.get("SCHEDULER_PLANE", "unknown")
        info["active_plane"] = active_plane

        # Última pipeline canónica: timestamp del último KPI snapshot
        last_kpi = c.execute(
            "SELECT computed_at FROM kpi_snapshots ORDER BY computed_at DESC LIMIT 1"
        ).fetchone()
        info["last_pipeline_run"] = last_kpi[0] if last_kpi else None

        # ── Frescura de la vista pública (v94) ─────────────────────────
        # `last_pipeline_run` NO sirve para esto y ese es justo el problema que
        # cierra este bloque: sale de `kpi_snapshots`, que escribe el paso
        # ANTERIOR al refresco de la vista. Un `aggregates_precompute` que
        # fallara dejaría la pipeline "fresca" y la superficie pública
        # congelada, sirviendo cifras coherentes entre sí y viejas.
        #
        # Se mide sobre `ops_events` y no sobre la vista porque Postgres no
        # registra cuándo se refrescó una vista materializada, y comparar sus
        # filas contra la tabla exige repetir el anti-join que la vista existe
        # para evitar. El evento lo emite `scheduler/aggregates_precompute.py`.
        _comprobar_vista_canonicas(c, canonicas_stale_hours, checks, warnings, info)

        # Locks activos (ADR-012)
        try:
            now_iso = datetime.now(UTC).isoformat()
            active_locks = c.execute(
                "SELECT name, holder, expires_at FROM job_locks WHERE expires_at > %s",
                (now_iso,),
            ).fetchall()
            info["active_locks"] = [
                {"name": r[0], "holder": r[1], "expires_at": r[2]} for r in active_locks
            ]
        except Exception:
            info["active_locks"] = []

        # ── Tripwires de persistencia (ops_events, ADR-004) ───────────
        # Los counters Prometheus mueren con el proceso efimero del scheduler
        # (GH Actions). ops_events persiste en BD para que este healthcheck,
        # que SI corre en prod cada 6h, pueda leerlos.
        # Umbrales espejo de observability/alert_rules.yml.
        try:
            cutoff = (datetime.now(UTC) - timedelta(hours=6)).isoformat()
            rows = c.execute(
                "SELECT event_type, COUNT(*) FROM ops_events WHERE ts > %s GROUP BY event_type",
                (cutoff,),
            ).fetchall()
            ops_counts: dict[str, int] = {r[0]: int(r[1]) for r in rows}
            info["ops_events_6h"] = ops_counts

            # sqlite_busy: >=10 warn, >=60 error
            n_busy = ops_counts.get("sqlite_busy", 0)
            if n_busy >= 60:
                errors.append(f"sqlite_busy_critical:{n_busy}")
            elif n_busy >= 10:
                warnings.append(f"sqlite_busy_high:{n_busy}")
            checks.append({"name": "ops_events_busy", "ok": n_busy < 10})

            # write_slow: >=20 warn
            n_slow = ops_counts.get("write_slow", 0)
            if n_slow >= 20:
                warnings.append(f"write_slow_high:{n_slow}")
            checks.append({"name": "ops_events_write_slow", "ok": n_slow < 20})

            # writers_high: >=1 warn
            n_wh = ops_counts.get("writers_high", 0)
            if n_wh >= 1:
                warnings.append(f"writers_high:{n_wh}")
            checks.append({"name": "ops_events_writers_high", "ok": n_wh == 0})

            # Retención best-effort: eliminar eventos > 30 días
            try:
                retention_cutoff = (datetime.now(UTC) - timedelta(days=30)).isoformat()
                c.execute("DELETE FROM ops_events WHERE ts < %s", (retention_cutoff,))
            except Exception:
                pass

        except Exception as exc:
            exc_msg = str(exc).lower()
            # Cada motor redacta el error a su manera: SQLite dice "no such
            # table", Postgres dice 'relation "ops_events" does not exist'.
            # Sin la variante de Postgres, este check nunca se activaba en
            # producción tras el cutover (ADR-016): el error se clasificaba
            # como genérico y la tabla ausente pasaba desapercibida.
            tabla_ausente = (
                "no such table" in exc_msg
                or "no existe" in exc_msg
                or "does not exist" in exc_msg
                or "undefinedtable" in exc_msg
            )
            if tabla_ausente:
                info["ops_events_missing"] = True
                checks.append({"name": "ops_events_busy", "ok": True})
                checks.append({"name": "ops_events_write_slow", "ok": True})
                checks.append({"name": "ops_events_writers_high", "ok": True})
            else:
                info["ops_events_error"] = str(exc)[:200]

    if errors:
        status = "critical"
    elif warnings:
        status = "degraded"

    return {
        "status": status,
        "checked_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
        "info": info,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--freshness-hours", type=int, default=36)
    p.add_argument("--dlq-threshold", type=int, default=50)
    p.add_argument(
        "--canonicas-stale-hours",
        type=int,
        default=9,
        help="Horas sin refrescar `licitaciones_canonicas` que se consideran viejas "
        "(por defecto 9: dos ciclos del carril de 4h más margen)",
    )
    p.add_argument("--alert", action="store_true", help="Emite alertas si el estado no es healthy")
    args = p.parse_args()

    configure_logging()
    result = run_check(args.freshness_hours, args.dlq_threshold, args.canonicas_stale_hours)
    print(json.dumps(result, indent=2, default=str))

    if args.alert and result["status"] != "healthy":
        level = AlertLevel.CRITICAL if result["status"] == "critical" else AlertLevel.WARN
        notify(
            level,
            "Healthcheck tenderflow",
            body=f"Estado: {result['status']}",
            warnings=result["warnings"],
            errors=result["errors"],
            **{k: v for k, v in result["info"].items() if not isinstance(v, dict)},
        )

    if args.alert and result["status"] == "degraded":
        # El email ya avisó del estado degradado; el job de CI queda verde para
        # no convertir cada aviso en un run rojo.
        return 0

    # "critical" SIEMPRE devuelve exit != 0, también con --alert: hasta 2026-08
    # este camino devolvía 0 incondicionalmente y el workflow healthcheck.yml
    # era estructuralmente incapaz de fallar — un estado crítico solo se veía
    # si alguien leía el email (si el SMTP estaba configurado).
    return {"healthy": 0, "degraded": 1, "critical": 2}.get(result["status"], 2)


if __name__ == "__main__":
    sys.exit(main())
