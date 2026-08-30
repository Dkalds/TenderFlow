"""Tests para scheduler.healthcheck.run_check."""

from __future__ import annotations

from datetime import UTC

# ---------------------------------------------------------------------------
# Conteo de licitaciones: estimación del planner en vez de seq scan
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, fila):
        self._fila = fila

    def fetchone(self):
        return self._fila


class _FakeConn:
    """Conexión de mentira que responde a las dos consultas de _contar_licitaciones."""

    def __init__(self, reltuples, total=7):
        self._reltuples = reltuples
        self._total = total
        self.sqls: list[str] = []

    def execute(self, sql, *args):
        self.sqls.append(sql)
        if "reltuples" in sql:
            return _FakeCursor(None if self._reltuples is None else (self._reltuples,))
        return _FakeCursor((self._total,))


def test_contar_licitaciones_usa_la_estimacion_y_evita_el_seq_scan():
    """Regresión (2026-08): el COUNT(*) exacto tardaba 19,5 s con 1,3 M filas y
    acabó cruzando el statement_timeout de 30 s. Como es la primera consulta
    del bloque, el QueryCanceled tumbaba el healthcheck entero — el post-run
    del scraper diario moría con traceback en vez de reportar estado."""
    from scheduler.healthcheck import _contar_licitaciones

    conn = _FakeConn(reltuples=1_377_522)

    assert _contar_licitaciones(conn) == (1_377_522, True)
    assert not any("COUNT(*)" in sql for sql in conn.sqls)


def test_contar_licitaciones_cae_a_conteo_exacto_sin_analyze():
    """``reltuples`` vale -1 mientras nadie haya analizado la tabla (PG>=14)."""
    from scheduler.healthcheck import _contar_licitaciones

    conn = _FakeConn(reltuples=-1, total=7)

    assert _contar_licitaciones(conn) == (7, False)
    assert any("COUNT(*)" in sql for sql in conn.sqls)


def test_contar_licitaciones_cae_a_conteo_exacto_si_no_hay_fila_en_pg_class():
    from scheduler.healthcheck import _contar_licitaciones

    conn = _FakeConn(reltuples=None, total=7)

    assert _contar_licitaciones(conn) == (7, False)
    assert any("COUNT(*)" in sql for sql in conn.sqls)


def test_healthcheck_reporta_total_de_licitaciones(tmp_db):
    from datetime import datetime

    from db.database import connect

    now = datetime.now(UTC).isoformat()
    with connect() as c:
        c.execute(
            "INSERT INTO extraction_runs "
            "(run_id, started_at, ended_at, status) VALUES ('r1', %s, %s, 'ok')",
            (now, now),
        )
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) "
            "VALUES ('LIC-001', 'Contrato de prueba', %s)",
            (now,),
        )

    from scheduler.healthcheck import run_check

    result = run_check()

    # Tabla recién creada: la estimación no sirve todavía y se cuenta exacto.
    assert result["info"]["licitaciones_total"] == 1
    assert isinstance(result["info"]["licitaciones_total_estimado"], bool)

    # El helper compartido devuelve lo mismo por el camino de estimación.
    from db.database import count_licitaciones

    assert count_licitaciones(estimado=True) == 1
    assert count_licitaciones() == 1


def test_healthcheck_degrada_si_no_puede_medir_la_cobertura_de_empresas(tmp_db, monkeypatch):
    """El bloque de empresas es el más caro del informe (dos recorridos de
    `adjudicaciones`). Si revienta, el healthcheck tiene que seguir y reportar,
    no morir: los checks posteriores (kpi_snapshots, job_locks, ops_events)
    corren sobre la MISMA conexión y sin el rollback del except quedarían en
    InFailedSqlTransaction."""
    from datetime import datetime

    from db.database import connect

    now = datetime.now(UTC).isoformat()
    with connect() as c:
        c.execute(
            "INSERT INTO extraction_runs "
            "(run_id, started_at, ended_at, status) VALUES ('r1', %s, %s, 'ok')",
            (now, now),
        )
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) "
            "VALUES ('LIC-001', 'Contrato de prueba', %s)",
            (now,),
        )
        # Sin empresa_id: fuerza el recorrido de identidades sin resolver, que
        # es donde se llama a normalize_company.
        c.execute(
            "INSERT INTO adjudicaciones "
            "(licitacion_id, nombre, fecha_extraccion) VALUES ('LIC-001', 'Empresa', %s)",
            (now,),
        )

    def _explota(*_args, **_kwargs):
        raise RuntimeError("boom midiendo empresas")

    monkeypatch.setattr("services.normalization.normalize_company", _explota)

    from scheduler.healthcheck import run_check

    result = run_check()

    assert "empresa_resolution_no_medida" in result["warnings"]
    assert "boom" in result["info"]["empresa_resolution_error"]
    # El informe sobrevive: los checks que van DESPUÉS del bloque siguen ahí.
    assert "active_plane" in result["info"]
    assert "last_pipeline_run" in result["info"]
    assert {c["name"] for c in result["checks"]} >= {"db_readable", "empresa_resolution_coverage"}


def test_healthcheck_critical_without_runs(tmp_db):
    from scheduler.healthcheck import run_check

    result = run_check()
    assert result["status"] == "critical"
    assert "sin_runs_registrados" in result["errors"]


def test_healthcheck_healthy_after_successful_run(tmp_db):
    from observability.metrics import record_run

    with record_run("run-ok") as m:
        m.months_attempted = 1
        m.months_ok = 1

    from scheduler.healthcheck import run_check

    result = run_check()
    assert result["status"] == "healthy", result


def test_healthcheck_degraded_when_last_run_stale(tmp_db):
    from datetime import datetime, timedelta

    from db.database import connect

    old = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    with connect() as c:
        c.execute(
            "INSERT INTO extraction_runs "
            "(run_id, started_at, ended_at, duration_ms, status, "
            " months_attempted, months_ok) "
            "VALUES ('r-old', %s, %s, 1000, 'ok', 1, 1)",
            (old, old),
        )

    from scheduler.healthcheck import run_check

    result = run_check(freshness_hours=36)
    assert result["status"] == "degraded"
    assert any(w.startswith("last_run_stale") for w in result["warnings"])


def test_healthcheck_degraded_when_dlq_above_threshold(tmp_db):
    from datetime import datetime

    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO extraction_runs "
            "(run_id, started_at, ended_at, status) VALUES "
            "('r1', %s, %s, 'ok')",
            (datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()),
        )
        for i in range(6):
            c.execute(
                "INSERT INTO failed_extractions (fuente, created_at) VALUES (%s, %s)",
                (f"src-{i}", datetime.now(UTC).isoformat()),
            )

    from scheduler.healthcheck import run_check

    result = run_check(dlq_threshold=5)
    assert result["status"] == "degraded"
    assert any("dlq_above_threshold" in w for w in result["warnings"])


def test_healthcheck_degraded_when_empresa_resolution_below_threshold(tmp_db):
    from datetime import datetime

    from db.database import connect

    now = datetime.now(UTC).isoformat()
    with connect() as c:
        c.execute(
            "INSERT INTO extraction_runs "
            "(run_id, started_at, ended_at, status) VALUES ('r1', %s, %s, 'ok')",
            (now, now),
        )
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) "
            "VALUES ('LIC-001', 'Contrato de prueba', %s)",
            (now,),
        )
        c.execute(
            "INSERT INTO adjudicaciones "
            "(licitacion_id, nombre, fecha_extraccion) VALUES ('LIC-001', 'Empresa', %s)",
            (now,),
        )

    from scheduler.healthcheck import run_check

    result = run_check()
    assert result["status"] == "degraded"
    assert result["info"]["empresa_resolution"]["pct_filas"] == 0.0
    assert any("empresa_resolution_below_threshold" in w for w in result["warnings"])


def test_healthcheck_counts_pending_review_as_covered(tmp_db):
    from datetime import datetime

    from db.database import connect

    now = datetime.now(UTC).isoformat()
    with connect() as c:
        c.execute(
            "INSERT INTO extraction_runs "
            "(run_id, started_at, ended_at, status) VALUES ('r1', %s, %s, 'ok')",
            (now, now),
        )
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) "
            "VALUES ('LIC-001', 'Contrato de prueba', %s)",
            (now,),
        )
        c.execute(
            "INSERT INTO adjudicaciones "
            "(licitacion_id, nombre, nif, fecha_extraccion) "
            "VALUES ('LIC-001', 'Empresa Candidata S.L.', 'B12345678', %s)",  # pragma: allowlist secret -- NIF sintético
            (now,),
        )
        c.execute(
            "INSERT INTO empresa_review_queue "
            "(nombre_original, alias_normalizado, nif, score, status, created_at) "
            "VALUES ('Empresa Candidata S.L.', 'EMPRESA CANDIDATA', "
            "'B12345678', 0.95, 'pending', %s)",  # pragma: allowlist secret -- NIF sintético
            (now,),
        )

    from scheduler.healthcheck import run_check

    result = run_check()
    resolution = result["info"]["empresa_resolution"]
    assert resolution == {
        "total": 1,
        "enlazadas": 0,
        "en_revision": 1,
        "pendientes": 0,
        "pct_filas": 100.0,
    }
    assert not any("empresa_resolution_below_threshold" in w for w in result["warnings"])


def test_healthcheck_main_returns_0_for_healthy(tmp_db):
    from unittest.mock import patch

    from observability.metrics import record_run

    with record_run("run-main-ok") as m:
        m.months_attempted = 1
        m.months_ok = 1

    from scheduler.healthcheck import main

    with patch("sys.argv", ["healthcheck"]):
        code = main()

    assert code == 0


def test_healthcheck_main_returns_1_for_degraded(tmp_db):
    from datetime import datetime, timedelta
    from unittest.mock import patch

    from db.database import connect

    old = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    with connect() as c:
        c.execute(
            "INSERT INTO extraction_runs "
            "(run_id, started_at, ended_at, duration_ms, status, "
            " months_attempted, months_ok) "
            "VALUES ('r-deg', %s, %s, 1000, 'ok', 1, 1)",
            (old, old),
        )

    from scheduler.healthcheck import main

    with patch("sys.argv", ["healthcheck"]):
        code = main()

    assert code == 1


def test_healthcheck_main_alert_mode_critical_exits_nonzero(tmp_db):
    """Con --alert, un estado critical devuelve exit != 0 (el job de CI se pone rojo).

    Hasta 2026-08 ``--alert`` devolvía 0 incondicionalmente: el workflow
    healthcheck.yml era estructuralmente incapaz de fallar y un estado crítico
    solo se veía si alguien leía el email.
    """
    from unittest.mock import patch

    from scheduler.healthcheck import main

    # Sin runs → critical
    with patch("sys.argv", ["healthcheck", "--alert"]), patch("scheduler.healthcheck.notify"):
        code = main()

    assert code == 2


def test_healthcheck_main_alert_mode_degraded_returns_0(tmp_db):
    """Con --alert, degraded sigue devolviendo 0: el email avisa y CI queda verde."""
    from datetime import datetime, timedelta
    from unittest.mock import patch

    from db.database import connect

    old = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    with connect() as c:
        c.execute(
            "INSERT INTO extraction_runs "
            "(run_id, started_at, ended_at, duration_ms, status, "
            " months_attempted, months_ok) "
            "VALUES ('r-deg-alert', %s, %s, 1000, 'ok', 1, 1)",
            (old, old),
        )

    from scheduler.healthcheck import main

    with patch("sys.argv", ["healthcheck", "--alert"]), patch("scheduler.healthcheck.notify"):
        code = main()

    assert code == 0


# ---------------------------------------------------------------------------
# Frescura de la vista pública (`licitaciones_canonicas`, v94)
#
# `last_pipeline_run` sale de `kpi_snapshots`, que escribe el paso ANTERIOR al
# refresco de la vista. Un `aggregates_precompute` que fallara dejaba la
# pipeline "fresca" y la superficie pública congelada: cifras coherentes entre
# sí, viejas, y sin nada que lo delatara. Estos tests fijan la señal que faltaba.
# ---------------------------------------------------------------------------


def _registrar_refresco(c, *, hace_horas: float, filas: int) -> None:
    from datetime import datetime, timedelta

    from db.repositories.publico import EVENTO_REFRESCO_CANONICAS

    ts = (datetime.now(UTC) - timedelta(hours=hace_horas)).isoformat()
    c.execute(
        "INSERT INTO ops_events (ts, event_type, value) VALUES (%s, %s, %s)",
        (ts, EVENTO_REFRESCO_CANONICAS, float(filas)),
    )


def test_vista_sin_refrescos_y_sin_datos_no_ensucia_el_informe(tmp_db):
    """Una base sin corpus no tiene nada que decir sobre frescura.

    Es el caso de cualquier schema de test y de un entorno recién creado: si
    avisara aquí, el check sería ruido y acabaría desactivado.
    """
    from scheduler.healthcheck import run_check

    result = run_check()

    assert "canonicas_sin_registro_de_refresco" not in result["warnings"]
    assert {"name": "canonicas_frescas", "ok": True} in result["checks"]


def test_vista_fresca_no_avisa(tmp_db):
    from db.database import connect
    from scheduler.healthcheck import run_check

    with connect() as c:
        _registrar_refresco(c, hace_horas=1, filas=411_450)

    result = run_check()

    assert not any(w.startswith("canonicas_stale") for w in result["warnings"])
    assert {"name": "canonicas_frescas", "ok": True} in result["checks"]
    assert result["info"]["canonicas"]["filas"] == 411_450


def test_vista_vieja_degrada_el_estado(tmp_db):
    """Dos ciclos del carril de 4h sin refrescar ya es una anomalía."""
    from db.database import connect
    from scheduler.healthcheck import run_check

    with connect() as c:
        _registrar_refresco(c, hace_horas=30, filas=411_450)

    result = run_check(canonicas_stale_hours=9)

    assert result["status"] == "degraded"
    assert any(w.startswith("canonicas_stale") for w in result["warnings"])
    assert {"name": "canonicas_frescas", "ok": False} in result["checks"]


def test_vista_que_encoge_avisa(tmp_db):
    """Un refresco que deja la vista mucho más pequeña no lanza excepción.

    El corpus publicable solo crece salvo purga deliberada, así que una caída
    del 10% es un umbral de sustancia mal tocado o una fuente que dejó de
    ingerir — y ninguna de las dos cosas falla por su cuenta.
    """
    from db.database import connect
    from scheduler.healthcheck import run_check

    with connect() as c:
        _registrar_refresco(c, hace_horas=5, filas=411_000)
        _registrar_refresco(c, hace_horas=1, filas=12_000)

    result = run_check()

    assert result["status"] == "degraded"
    assert any(w.startswith("canonicas_encogieron") for w in result["warnings"])
    assert {"name": "canonicas_tamano", "ok": False} in result["checks"]


def test_vista_vacia_tras_refrescar_avisa(tmp_db):
    from db.database import connect
    from scheduler.healthcheck import run_check

    with connect() as c:
        _registrar_refresco(c, hace_horas=1, filas=0)

    result = run_check()

    assert "canonicas_vacias" in result["warnings"]
    assert {"name": "canonicas_tamano", "ok": False} in result["checks"]
