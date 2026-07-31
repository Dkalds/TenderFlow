"""Tests para db/upsert.py — upsert idempotente, historial y FTS."""

from __future__ import annotations

import json

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_db):
    """Devuelve el módulo db tras inicializar la BD."""
    db_mod, _ = tmp_db
    return db_mod


# ---------------------------------------------------------------------------
# upsert_licitaciones
# ---------------------------------------------------------------------------


def make_licitacion(**kwargs):
    from db.upsert import Licitacion

    defaults = {
        "id_externo": "TEST-001",
        "titulo": "Sistema ERP SAP",
        "descripcion": "Implantación SAP S/4HANA",
        "organo_contratacion": "Ministerio de Hacienda",
        "importe": 500000.0,
        "estado": "PUB",
        "fecha_publicacion": "2024-01-15",
        "tecnologia": "SAP",
        "ccaa": "Madrid",
    }
    defaults.update(kwargs)
    return Licitacion(**defaults)


def test_upsert_inserts_new(db):
    from db.upsert import upsert_licitaciones

    lic = make_licitacion()
    nuevas, actualizadas = upsert_licitaciones([lic])
    assert nuevas == 1
    assert actualizadas == 0


def test_upsert_idempotent(db):
    """Segunda inserción del mismo ID actualiza, no duplica."""
    from db.upsert import upsert_licitaciones

    lic = make_licitacion()
    upsert_licitaciones([lic])
    nuevas, actualizadas = upsert_licitaciones([lic])
    assert nuevas == 0
    assert actualizadas == 1


def test_upsert_updates_field(db):
    """Un upsert actualiza un campo existente."""
    from db.database import connect
    from db.upsert import upsert_licitaciones

    lic = make_licitacion(importe=100.0)
    upsert_licitaciones([lic])

    lic2 = make_licitacion(importe=200.0)
    upsert_licitaciones([lic2])

    with connect() as c:
        row = c.execute(
            "SELECT importe FROM licitaciones WHERE id_externo = ?", ["TEST-001"]
        ).fetchone()
    assert row[0] == pytest.approx(200.0)


def test_upsert_keeps_earliest_fecha_publicacion(db):
    """fecha_publicacion no debe avanzar a una fecha posterior en un re-upsert.

    Regresión: una fase posterior (adjudicación/formalización) trae la fecha
    de publicación de SU anuncio, que es posterior a la del primer anuncio.
    Sobrescribirla dejaba el hito "publicación" DESPUÉS de la adjudicación en
    el histórico. Debe conservarse siempre el primer anuncio (el más temprano).
    """
    from db.database import connect
    from db.upsert import upsert_licitaciones

    upsert_licitaciones([make_licitacion(fecha_publicacion="2026-05-01")])
    # Re-scrape en fase de adjudicación: la fuente trae una fecha posterior.
    upsert_licitaciones([make_licitacion(fecha_publicacion="2026-07-16")])

    with connect() as c:
        row = c.execute(
            "SELECT fecha_publicacion FROM licitaciones WHERE id_externo = ?", ["TEST-001"]
        ).fetchone()
    assert row[0] == "2026-05-01"


def test_upsert_backfills_earlier_fecha_publicacion(db):
    """Si el primer anuncio se ve después, fecha_publicacion retrocede a él."""
    from db.database import connect
    from db.upsert import upsert_licitaciones

    upsert_licitaciones([make_licitacion(fecha_publicacion="2026-07-16")])
    upsert_licitaciones([make_licitacion(fecha_publicacion="2026-05-01")])

    with connect() as c:
        row = c.execute(
            "SELECT fecha_publicacion FROM licitaciones WHERE id_externo = ?", ["TEST-001"]
        ).fetchone()
    assert row[0] == "2026-05-01"


def test_upsert_with_history_keeps_earliest_fecha_publicacion(db):
    """El camino con historial también conserva el primer anuncio."""
    from db.database import connect
    from db.upsert import upsert_licitaciones_with_history

    upsert_licitaciones_with_history(
        [make_licitacion(fecha_publicacion="2026-05-01")], source="pub"
    )
    upsert_licitaciones_with_history(
        [make_licitacion(fecha_publicacion="2026-07-16", estado="ADJ")], source="adj"
    )

    with connect() as c:
        row = c.execute(
            "SELECT fecha_publicacion, estado FROM licitaciones WHERE id_externo = ?",
            ["TEST-001"],
        ).fetchone()
    assert row[0] == "2026-05-01"
    # El resto de campos sí se actualiza normalmente.
    assert row[1] == "ADJ"


# ---------------------------------------------------------------------------
# fecha_limite: COALESCE en el upsert (Ola 1, docs/IMPROVEMENT_BACKLOG.md)
# ---------------------------------------------------------------------------


def test_upsert_keeps_fecha_limite_when_reingest_lacks_it(db):
    """Una re-ingesta sin fecha_limite no debe borrar un plazo ya conocido.

    Regresión: el nodo CODICE que publica fecha_limite
    (TenderingProcess/TenderSubmissionDeadlinePeriod) puede desaparecer
    cuando el expediente avanza a fase ADJ/RES. Sin COALESCE en el upsert,
    ese re-parseo legítimo (misma licitación, estado más reciente) nuleaba
    un plazo que ya se conocía.
    """
    from db.database import connect
    from db.upsert import upsert_licitaciones

    upsert_licitaciones([make_licitacion(fecha_limite="2026-08-15T21:59:00+00:00")])
    upsert_licitaciones([make_licitacion(fecha_limite=None, estado="ADJ")])

    with connect() as c:
        row = c.execute(
            "SELECT fecha_limite, estado FROM licitaciones WHERE id_externo = ?",
            ["TEST-001"],
        ).fetchone()
    assert row[0] == "2026-08-15T21:59:00+00:00"
    # El resto de campos sí se actualiza normalmente — COALESCE es específico
    # de fecha_limite, no un comportamiento general de "nunca sobrescribir".
    assert row[1] == "ADJ"


def test_upsert_updates_fecha_limite_on_real_extension(db):
    """Una ampliación de plazo real (nuevo valor no-NULL) SÍ debe sobrescribir."""
    from db.database import connect
    from db.upsert import upsert_licitaciones

    upsert_licitaciones([make_licitacion(fecha_limite="2026-08-15T21:59:00+00:00")])
    upsert_licitaciones([make_licitacion(fecha_limite="2026-09-01T21:59:00+00:00")])

    with connect() as c:
        row = c.execute(
            "SELECT fecha_limite FROM licitaciones WHERE id_externo = ?", ["TEST-001"]
        ).fetchone()
    assert row[0] == "2026-09-01T21:59:00+00:00"


def test_upsert_with_history_tracks_fecha_limite_extension(db):
    """Una ampliación de plazo debe quedar registrada en licitaciones_history.

    fecha_limite se añadió a HISTORY_TRACKED_FIELDS (config/constants.py) en
    la misma ola: antes de eso, una ampliación de plazo —evento operativo de
    primer orden— era invisible en el histórico.
    """
    from db.database import connect
    from db.upsert import upsert_licitaciones_with_history

    upsert_licitaciones_with_history(
        [make_licitacion(fecha_limite="2026-08-15T21:59:00+00:00")], source="pub"
    )
    upsert_licitaciones_with_history(
        [make_licitacion(fecha_limite="2026-09-01T21:59:00+00:00")], source="atom_live"
    )

    with connect() as c:
        row = c.execute(
            "SELECT changed_fields, snapshot_json FROM licitaciones_history "
            "WHERE id_externo = ? ORDER BY id DESC LIMIT 1",
            ["TEST-001"],
        ).fetchone()
    assert row is not None
    assert "fecha_limite" in row[0].split(",")
    snapshot = json.loads(row[1])
    # El snapshot guarda el estado ANTERIOR al cambio.
    assert snapshot["fecha_limite"] == "2026-08-15T21:59:00+00:00"


def test_upsert_empty_list(db):
    from db.upsert import upsert_licitaciones

    nuevas, actualizadas = upsert_licitaciones([])
    assert nuevas == 0
    assert actualizadas == 0


def test_upsert_multiple_items(db):
    from db.upsert import upsert_licitaciones

    lics = [make_licitacion(id_externo=f"TEST-{i:03d}", titulo=f"Título {i}") for i in range(5)]
    nuevas, actualizadas = upsert_licitaciones(lics)
    assert nuevas == 5
    assert actualizadas == 0


def test_upsert_chunked_large_batch(db):
    """Batches > 500 items se procesan en chunks sin error."""
    from db.upsert import upsert_licitaciones

    lics = [make_licitacion(id_externo=f"BULK-{i:04d}", titulo=f"Lic {i}") for i in range(600)]
    nuevas, _actualizadas = upsert_licitaciones(lics)
    assert nuevas == 600


def test_count_licitaciones(db):
    from db.upsert import count_licitaciones, upsert_licitaciones

    upsert_licitaciones([make_licitacion(), make_licitacion(id_externo="TEST-002", titulo="Otro")])
    assert count_licitaciones() >= 2


# ---------------------------------------------------------------------------
# replace_adjudicaciones
# ---------------------------------------------------------------------------


def test_replace_adjudicaciones_inserts(db):
    from db.upsert import Adjudicacion, replace_adjudicaciones, upsert_licitaciones

    upsert_licitaciones([make_licitacion()])
    adj = Adjudicacion(licitacion_id="TEST-001", nombre="Empresa SA", nif="B12345678")
    n, dropped = replace_adjudicaciones("TEST-001", [adj])
    assert n == 1
    assert dropped == 0


def test_replace_adjudicaciones_replaces(db):
    """Segunda llamada elimina las anteriores e inserta las nuevas."""
    from db.database import connect
    from db.upsert import Adjudicacion, replace_adjudicaciones, upsert_licitaciones

    upsert_licitaciones([make_licitacion()])
    adj1 = Adjudicacion(licitacion_id="TEST-001", nombre="Empresa A")
    replace_adjudicaciones("TEST-001", [adj1])

    adj2 = Adjudicacion(licitacion_id="TEST-001", nombre="Empresa B")
    replace_adjudicaciones("TEST-001", [adj2])

    with connect() as c:
        rows = c.execute(
            "SELECT nombre FROM adjudicaciones WHERE licitacion_id = ?", ["TEST-001"]
        ).fetchall()
    names = [r[0] for r in rows]
    assert "Empresa B" in names
    assert "Empresa A" not in names


def _drop_count() -> float | None:
    """Lee upsert_rows_dropped_total{table='adjudicaciones'} desde el REGISTRY.

    Devuelve None si prometheus_client no está instalado (las métricas serían
    no-op y la verificación se omite — el contador del valor de retorno sigue
    siendo el test principal).
    """
    try:
        from prometheus_client import REGISTRY
    except ImportError:
        return None
    val = REGISTRY.get_sample_value(
        "upsert_rows_dropped_total",
        {"table": "adjudicaciones"},
    )
    return float(val) if val is not None else 0.0


def test_replace_adjudicaciones_drops_constraint_violation(db):
    """Regresión RFC obs-perdida-filas-upsert (acceptance criterion).

    Una adjudicación con `fecha_adjudicacion` no-ISO viola el `CHECK GLOB
    '????-??-??*'` definido en db/schema.py para `adjudicaciones`. El
    `INSERT OR IGNORE` descarta la fila silenciosamente; el contador debe
    reflejarlo en `dropped` (no en `persisted`) y la métrica
    `upsert_rows_dropped_total{table='adjudicaciones'}` debe incrementar.
    """
    from db.upsert import Adjudicacion, replace_adjudicaciones, upsert_licitaciones

    upsert_licitaciones([make_licitacion()])
    before = _drop_count()

    bad = Adjudicacion(
        licitacion_id="TEST-001",
        nombre="Empresa X",
        nif="B99999999",
        fecha_adjudicacion="14/06/2026",  # no-ISO: viola CHECK GLOB
    )
    persisted, dropped = replace_adjudicaciones("TEST-001", [bad])

    assert persisted == 0
    assert dropped == 1
    if before is not None:
        after = _drop_count()
        assert after is not None and after - before == 1.0


def test_replace_adjudicaciones_idempotent_no_drops_on_reingest(db):
    """Re-ingesta idéntica produce dropped=0 (idempotencia testeable).

    El RFC señala explícitamente que con conteos honestos la idempotencia
    se vuelve verificable: una segunda corrida con la misma adjudicación
    debe persistir 1 (el DELETE previo limpia) y descartar 0.
    """
    from db.upsert import Adjudicacion, replace_adjudicaciones, upsert_licitaciones

    upsert_licitaciones([make_licitacion()])
    adj = Adjudicacion(licitacion_id="TEST-001", nombre="Empresa SA", nif="B12345678")

    p1, d1 = replace_adjudicaciones("TEST-001", [adj])
    p2, d2 = replace_adjudicaciones("TEST-001", [adj])

    assert (p1, d1) == (1, 0)
    assert (p2, d2) == (1, 0)


def test_replace_adjudicaciones_batch_separates_persisted_from_dropped(db):
    """La versión batch cuenta drops por separado de persisted y failed.

    Un lote mixto (una válida + una con violación de CHECK) debe devolver
    persisted=1, dropped=1, failed=0. `failed` solo cuenta excepciones reales;
    `OR IGNORE` nunca las produce para violaciones de constraint.
    """
    from db.upsert import (
        Adjudicacion,
        replace_adjudicaciones_batch,
        upsert_licitaciones,
    )

    upsert_licitaciones([make_licitacion()])

    good = Adjudicacion(licitacion_id="TEST-001", nombre="Empresa OK", nif="B11111111")
    bad = Adjudicacion(
        licitacion_id="TEST-001",
        nombre="Empresa Mala",
        nif="B99999999",
        fecha_adjudicacion="01/01/2026",  # no-ISO viola CHECK
    )

    persisted, dropped, failed = replace_adjudicaciones_batch({"TEST-001": [good, bad]})

    assert persisted == 1
    assert dropped == 1
    assert failed == 0


def test_replace_adjudicaciones_check_violation_routes_to_dlq(db):
    """RFC dlq-upsert acceptance criterion: una violación de CHECK
    (fecha no-ISO) entra en `failed_extractions` con `scope='adjudicacion'`
    y `payload_ref='{licitacion_id}:{nif}:{importe_adjudicado}'`, con
    `run_id`/`fuente` propagados desde el caller para replay dirigido.
    """
    from db.database import connect
    from db.upsert import Adjudicacion, replace_adjudicaciones, upsert_licitaciones

    upsert_licitaciones([make_licitacion()])
    bad = Adjudicacion(
        licitacion_id="TEST-001",
        nombre="Empresa Mala",
        nif="B99999999",
        importe_adjudicado=1000.0,
        fecha_adjudicacion="14/06/2026",  # no-ISO: viola CHECK GLOB
    )
    persisted, dropped = replace_adjudicaciones(
        "TEST-001", [bad], run_id="run-test-1", fuente="placsp"
    )
    assert persisted == 0
    assert dropped == 1

    with connect() as c:
        rows = c.execute(
            "SELECT scope, payload_ref, fuente, run_id, error_type "
            "FROM failed_extractions "
            "WHERE scope = 'adjudicacion' AND payload_ref LIKE 'TEST-001:%'"
        ).fetchall()
    assert len(rows) == 1
    scope, payload_ref, fuente, run_id, error_type = rows[0]
    assert scope == "adjudicacion"
    assert payload_ref == "TEST-001:B99999999:1000.0"
    assert fuente == "placsp"
    assert run_id == "run-test-1"
    # Cada driver nombra su excepción a su manera: sqlite3 stdlib lanza
    # IntegrityError, libsql mapea a ValueError y psycopg usa las subclases
    # concretas de IntegrityError (CheckViolation, NotNullViolation...). El RFC
    # clasifica por mensaje, no por tipo, así que basta con que se haya
    # registrado alguno — el dato que importa (constraint=check) ya se afirma
    # arriba vía `dropped`.
    assert error_type in ("IntegrityError", "ValueError") or error_type.endswith("Violation")


def test_replace_adjudicaciones_unique_dedup_does_not_hit_dlq(db):
    """RFC dlq-upsert acceptance criterion: un duplicado intra-XML sobre
    `UNIQUE(licitacion_id, nif, importe_adjudicado)` se ignora como dedup
    benigno — ni cuenta en `dropped` ni entra en la DLQ. Es el caso que el
    `INSERT OR IGNORE` original cubría legítimamente.
    """
    from db.database import connect
    from db.upsert import Adjudicacion, replace_adjudicaciones, upsert_licitaciones

    upsert_licitaciones([make_licitacion()])
    adj_a = Adjudicacion(
        licitacion_id="TEST-001",
        nombre="Empresa A",
        nif="B11111111",
        importe_adjudicado=1000.0,
    )
    adj_b_dup = Adjudicacion(
        licitacion_id="TEST-001",
        nombre="Empresa A (duplicado intra-XML)",
        nif="B11111111",
        importe_adjudicado=1000.0,
    )
    persisted, dropped = replace_adjudicaciones(
        "TEST-001", [adj_a, adj_b_dup], run_id="run-test-2", fuente="placsp"
    )
    assert persisted == 1
    assert dropped == 0

    with connect() as c:
        n = c.execute(
            "SELECT COUNT(*) FROM failed_extractions "
            "WHERE scope = 'adjudicacion' AND payload_ref = ?",
            ("TEST-001:B11111111:1000.0",),
        ).fetchone()[0]
    assert n == 0


def test_replace_adjudicaciones_empty_clears(db):
    from db.database import connect
    from db.upsert import Adjudicacion, replace_adjudicaciones, upsert_licitaciones

    upsert_licitaciones([make_licitacion()])
    replace_adjudicaciones("TEST-001", [Adjudicacion(licitacion_id="TEST-001", nombre="X")])
    replace_adjudicaciones("TEST-001", [])

    with connect() as c:
        count = c.execute(
            "SELECT COUNT(*) FROM adjudicaciones WHERE licitacion_id = ?", ["TEST-001"]
        ).fetchone()[0]
    assert count == 0


# ---------------------------------------------------------------------------
# upsert_licitaciones_with_history
# ---------------------------------------------------------------------------


def test_upsert_with_history_inserts(db):
    from db.upsert import upsert_licitaciones_with_history

    lic = make_licitacion()
    result = upsert_licitaciones_with_history([lic], source="test")
    assert lic.id_externo in result.inserted
    assert result.nuevas == 1


def test_upsert_with_history_tracks_changes(db):
    """Cambiar un campo rastreado genera entrada en licitaciones_history."""
    from db.database import connect
    from db.upsert import upsert_licitaciones_with_history

    lic = make_licitacion(importe=100.0)
    upsert_licitaciones_with_history([lic], source="initial")

    lic2 = make_licitacion(importe=999.0)
    result = upsert_licitaciones_with_history([lic2], source="update")
    assert lic2.id_externo in result.modified

    with connect() as c:
        rows = c.execute(
            "SELECT snapshot_json, changed_fields FROM licitaciones_history WHERE id_externo = ?",
            ["TEST-001"],
        ).fetchall()
    assert len(rows) == 1
    snapshot = json.loads(rows[0][0])
    assert snapshot["importe"] == pytest.approx(100.0)


def test_upsert_with_history_unchanged(db):
    """Re-insertar sin cambios marca como unchanged."""
    from db.upsert import upsert_licitaciones_with_history

    lic = make_licitacion()
    upsert_licitaciones_with_history([lic], source="a")
    result = upsert_licitaciones_with_history([lic], source="b")
    assert lic.id_externo in result.unchanged


def test_upsert_result_properties(db):
    from db.upsert import upsert_licitaciones_with_history

    lics = [make_licitacion(id_externo=f"H-{i}", titulo=f"T{i}") for i in range(3)]
    result = upsert_licitaciones_with_history(lics, source="test")
    assert result.nuevas == 3
    assert result.actualizadas == 0


# ---------------------------------------------------------------------------
# cursor helpers
# ---------------------------------------------------------------------------


def test_set_and_get_cursor(db):
    from db.upsert import get_cursor, set_cursor

    set_cursor("test_source", last_seen_updated="2024-01-01T00:00:00Z", etag="abc123")
    cursor = get_cursor("test_source")
    assert cursor is not None
    assert cursor["source"] == "test_source"
    assert cursor["etag"] == "abc123"
    assert cursor["last_seen_updated"] == "2024-01-01T00:00:00Z"


def test_get_cursor_nonexistent(db):
    from db.upsert import get_cursor

    assert get_cursor("nonexistent_source") is None


def test_set_cursor_upserts(db):
    """Llamar a set_cursor dos veces actualiza en lugar de insertar duplicado."""
    from db.upsert import get_cursor, set_cursor

    set_cursor("src", etag="v1")
    set_cursor("src", etag="v2")
    cursor = get_cursor("src")
    assert cursor["etag"] == "v2"


# ---------------------------------------------------------------------------
# log_extraccion
# ---------------------------------------------------------------------------


def test_log_extraccion(db):
    from db.database import connect
    from db.upsert import log_extraccion

    log_extraccion("test_fuente", nuevas=5, actualizadas=3, total=8, notas="ok")
    with connect() as c:
        row = c.execute(
            "SELECT fuente, nuevas, actualizadas FROM extracciones WHERE fuente = ?",
            ["test_fuente"],
        ).fetchone()
    assert row is not None
    assert row[1] == 5
    assert row[2] == 3


# ---------------------------------------------------------------------------
# FTS
# ---------------------------------------------------------------------------


def test_fts_available(db):
    from db.upsert import fts_available

    # FTS puede o no estar disponible según las migraciones del tmp_db
    result = fts_available()
    assert isinstance(result, bool)


def test_search_fts_empty_query(db):
    from db.upsert import search_fts

    rows, total = search_fts("")
    assert rows == []
    assert total == 0


def test_get_history_empty(db):
    from db.upsert import get_history, upsert_licitaciones

    upsert_licitaciones([make_licitacion()])
    history = get_history("TEST-001")
    assert isinstance(history, list)
    # Sin cambios registrados, historial vacío
    assert len(history) == 0


def test_get_history_with_changes(db):
    from db.upsert import get_history, upsert_licitaciones_with_history

    lic1 = make_licitacion(importe=1.0)
    lic2 = make_licitacion(importe=2.0)
    upsert_licitaciones_with_history([lic1], source="src")
    upsert_licitaciones_with_history([lic2], source="src")

    history = get_history("TEST-001")
    assert len(history) == 1
    assert "snapshot_json" in history[0]


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def test_upsert_result_merge():
    from db.upsert import UpsertResult

    a = UpsertResult(inserted=["A"], modified=["B"], unchanged=["C"])
    b = UpsertResult(inserted=["D"], modified=[], unchanged=["E", "F"])
    a.merge(b)
    assert a.inserted == ["A", "D"]
    assert a.modified == ["B"]
    assert a.unchanged == ["C", "E", "F"]
    assert a.nuevas == 2
    assert a.actualizadas == 4


def test_upsert_with_history_chunking(db):
    """Batch mayor que chunk_size se divide en múltiples transacciones."""
    from db.upsert import upsert_licitaciones_with_history

    lics = [make_licitacion(id_externo=f"CHUNK-{i:03d}") for i in range(7)]
    result = upsert_licitaciones_with_history(lics, source="test", chunk_size=3)

    # 7 items con chunk_size=3 → 3 chunks (3+3+1)
    assert result.nuevas == 7
    assert len(result.inserted) == 7
    assert result.actualizadas == 0


def test_upsert_with_history_chunking_idempotent(db):
    """Re-ejecutar un upsert chunked no duplica registros."""
    from db.database import connect
    from db.upsert import upsert_licitaciones_with_history

    lics = [make_licitacion(id_externo=f"IDEM-{i:03d}") for i in range(5)]
    upsert_licitaciones_with_history(lics, source="first", chunk_size=2)
    result = upsert_licitaciones_with_history(lics, source="second", chunk_size=2)

    assert result.nuevas == 0
    assert len(result.unchanged) == 5

    with connect() as c:
        count = c.execute(
            "SELECT COUNT(*) FROM licitaciones WHERE id_externo LIKE 'IDEM-%'"
        ).fetchone()[0]
    assert count == 5


# ---------------------------------------------------------------------------
# replace_adjudicaciones — clasificación de integridad → DLQ
# (RFC 2026-06-16 dlq-violaciones-integridad-upsert)
# ---------------------------------------------------------------------------


def _make_adj(**kwargs):
    from db.upsert import Adjudicacion

    defaults = {
        "licitacion_id": "TEST-001",
        "nombre": "EMPRESA UNO SL",
        "nif": "B11111111",
        "importe_adjudicado": 1000.0,
        "fecha_adjudicacion": "2025-01-15",
    }
    defaults.update(kwargs)
    return Adjudicacion(**defaults)


def test_replace_adjudicaciones_check_violation_routed_to_dlq(db):
    """Una adjudicación con fecha no-ISO (viola CHECK) entra en la DLQ, no se pierde."""
    from db.database import connect
    from db.upsert import replace_adjudicaciones, upsert_licitaciones

    upsert_licitaciones([make_licitacion(id_externo="TEST-001")])
    good = _make_adj(nif="B11111111", importe_adjudicado=1000.0)
    bad = _make_adj(nif="B22222222", importe_adjudicado=2000.0, fecha_adjudicacion="15/01/2025")

    persisted, dropped = replace_adjudicaciones(
        "TEST-001", [good, bad], run_id="run-42", fuente="placsp"
    )

    assert persisted == 1
    assert dropped == 1
    with connect() as c:
        rows = c.execute(
            "SELECT fuente, payload_ref, error_message FROM failed_extractions "
            "WHERE scope = 'adjudicacion'"
        ).fetchall()
    assert len(rows) == 1
    fuente, payload_ref, err = rows[0]
    assert fuente == "placsp"
    assert payload_ref == "TEST-001:B22222222:2000.0"
    assert "constraint" in err.lower()


def test_replace_adjudicaciones_unique_dedup_not_in_dlq(db):
    """Un duplicado intra-XML (UNIQUE) se deduplica y NO va a la DLQ (no es pérdida)."""
    from db.dlq import list_unresolved
    from db.upsert import replace_adjudicaciones, upsert_licitaciones

    upsert_licitaciones([make_licitacion(id_externo="TEST-001")])
    a = _make_adj(nif="B33333333", importe_adjudicado=500.0)
    dup = _make_adj(nif="B33333333", importe_adjudicado=500.0)  # mismo (lic, nif, importe)

    persisted, dropped = replace_adjudicaciones("TEST-001", [a, dup])

    assert persisted == 1  # solo uno se inserta
    assert dropped == 0  # el dedup benigno no cuenta como descartado
    assert [f for f in list_unresolved() if f["scope"] == "adjudicacion"] == []


def test_replace_adjudicaciones_batch_violation_does_not_abort(db):
    """Una violación en una licitación no aborta el resto del batch."""
    from db.upsert import replace_adjudicaciones_batch, upsert_licitaciones

    upsert_licitaciones([make_licitacion(id_externo="LIC-A")])
    upsert_licitaciones([make_licitacion(id_externo="LIC-B")])
    batch = {
        "LIC-A": [
            _make_adj(licitacion_id="LIC-A", nif="A1", importe_adjudicado=100.0),
            _make_adj(
                licitacion_id="LIC-A", nif="A2", importe_adjudicado=200.0, fecha_adjudicacion="bad"
            ),
        ],
        "LIC-B": [_make_adj(licitacion_id="LIC-B", nif="B1", importe_adjudicado=300.0)],
    }

    persisted, dropped, failed = replace_adjudicaciones_batch(batch, run_id="r", fuente="placsp")

    assert persisted == 2  # A1 y B1 sobreviven
    assert dropped == 1  # A2 (CHECK)
    assert failed == 0  # ninguna licitación con error inesperado


def test_replace_adjudicaciones_idempotent_replay(db):
    """Re-ejecutar reinserta sin duplicar (idempotencia §3.2 preservada)."""
    from db.database import connect
    from db.upsert import replace_adjudicaciones, upsert_licitaciones

    upsert_licitaciones([make_licitacion(id_externo="TEST-001")])
    adj = _make_adj(nif="B99999999", importe_adjudicado=750.0)

    replace_adjudicaciones("TEST-001", [adj])
    p2, d2 = replace_adjudicaciones("TEST-001", [adj])  # replay

    assert p2 == 1
    assert d2 == 0
    with connect() as c:
        count = c.execute(
            "SELECT COUNT(*) FROM adjudicaciones WHERE licitacion_id = 'TEST-001'"
        ).fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# Escritura batcheada (round trips) — regresión del camino de ingesta
# ---------------------------------------------------------------------------


def test_replace_adjudicaciones_null_nif_not_deduped(db):
    """Dos adjudicaciones sin NIF con el mismo importe persisten ambas.

    La dedup intra-lote replica `UNIQUE(licitacion_id, nif, importe_adjudicado)`,
    y SQL trata NULL como distinto de NULL: esa clave nunca conflictúa. Si la
    dedup en memoria comparase con la igualdad de Python (None == None) se
    perderían adjudicaciones que la BD sí acepta.
    """
    from db.database import connect
    from db.upsert import replace_adjudicaciones, upsert_licitaciones

    upsert_licitaciones([make_licitacion(id_externo="TEST-001")])
    a = _make_adj(nif=None, importe_adjudicado=500.0, nombre="SIN NIF A")
    b = _make_adj(nif=None, importe_adjudicado=500.0, nombre="SIN NIF B")

    persisted, dropped = replace_adjudicaciones("TEST-001", [a, b])

    assert persisted == 2
    assert dropped == 0
    with connect() as c:
        count = c.execute(
            "SELECT COUNT(*) FROM adjudicaciones WHERE licitacion_id = 'TEST-001'"
        ).fetchone()[0]
    assert count == 2


def test_replace_adjudicaciones_batch_dedups_across_licitaciones(db):
    """La dedup intra-lote es por licitación, no global: mismo NIF e importe en
    dos licitaciones distintas son filas legítimas y deben persistir ambas."""
    from db.database import connect
    from db.upsert import replace_adjudicaciones_batch, upsert_licitaciones

    upsert_licitaciones([make_licitacion(id_externo="LIC-A"), make_licitacion(id_externo="LIC-B")])
    batch = {
        "LIC-A": [
            _make_adj(licitacion_id="LIC-A", nif="B1", importe_adjudicado=100.0),
            _make_adj(licitacion_id="LIC-A", nif="B1", importe_adjudicado=100.0),  # dup
        ],
        "LIC-B": [_make_adj(licitacion_id="LIC-B", nif="B1", importe_adjudicado=100.0)],
    }

    persisted, dropped, failed = replace_adjudicaciones_batch(batch)

    assert persisted == 2  # el duplicado de LIC-A se descarta, LIC-B sobrevive
    assert dropped == 0
    assert failed == 0
    with connect() as c:
        count = c.execute("SELECT COUNT(*) FROM adjudicaciones").fetchone()[0]
    assert count == 2


def test_ingesta_no_hace_un_round_trip_por_fila(db, monkeypatch):
    """Guarda de regresión del hallazgo H1: el camino de ingesta debe agrupar.

    Cuenta las sentencias enviadas a la conexión (cada una es un viaje de red
    contra una BD remota). Antes de batchear, un lote de 50 licitaciones con 2
    adjudicaciones cada una costaba >300 viajes; agrupado son unas pocas
    decenas. El umbral es deliberadamente holgado: sólo detecta la vuelta al
    patrón fila-a-fila, no fluctuaciones menores.
    """
    import db.upsert as up

    n_lic, n_adj = 50, 2
    stats = {"trips": 0}
    real_connect = up.connect

    class _Proxy:
        """Delega en la conexión real contando sentencias.

        Es un proxy y no un monkeypatch de atributos porque
        ``sqlite3.Connection`` es un tipo C: sus métodos son de sólo lectura.
        """

        def __init__(self, conn):
            self._conn = conn

        def execute(self, sql, params=None):
            stats["trips"] += 1
            return (
                self._conn.execute(sql, params) if params is not None else self._conn.execute(sql)
            )

        def executemany(self, sql, seq):
            stats["trips"] += 1
            return self._conn.executemany(sql, seq)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    class _Counting:
        def __enter__(self):
            self._cm = real_connect()
            return _Proxy(self._cm.__enter__())

        def __exit__(self, *a):
            return self._cm.__exit__(*a)

    monkeypatch.setattr(up, "connect", lambda: _Counting())

    lics = [make_licitacion(id_externo=f"RT-{i}") for i in range(n_lic)]
    adjs = {
        f"RT-{i}": [
            _make_adj(licitacion_id=f"RT-{i}", nif=f"B{i}{j}", importe_adjudicado=100.0 + j)
            for j in range(n_adj)
        ]
        for i in range(n_lic)
    }

    up.upsert_licitaciones_with_history(lics, source="test")
    up.replace_adjudicaciones_batch(adjs)

    filas = n_lic + n_lic * n_adj
    assert stats["trips"] < filas / 4, (
        f"{stats['trips']} viajes para {filas} filas — el camino de ingesta "
        "volvió a hacer un round trip por fila (ver H1)"
    )


# ---------------------------------------------------------------------------
# lotes (v65_lotes)
# ---------------------------------------------------------------------------


def test_replace_lotes_returns_numero_to_id_mapping(db):
    from db.upsert import Lote, replace_lotes, upsert_licitaciones

    upsert_licitaciones([make_licitacion(id_externo="TEST-001")])
    mapping = replace_lotes(
        "TEST-001",
        [
            Lote(licitacion_id="TEST-001", numero="1", titulo="Lote uno", importe=1000.0),
            Lote(licitacion_id="TEST-001", numero="2", titulo="Lote dos", importe=2000.0),
        ],
    )

    assert set(mapping) == {"1", "2"}
    assert isinstance(mapping["1"], int)
    assert mapping["1"] != mapping["2"]


def test_replace_lotes_reingesta_reemplaza_no_acumula(db):
    from db.database import connect
    from db.upsert import Lote, replace_lotes, upsert_licitaciones

    upsert_licitaciones([make_licitacion(id_externo="TEST-001")])
    replace_lotes("TEST-001", [Lote(licitacion_id="TEST-001", numero="1")])
    replace_lotes("TEST-001", [Lote(licitacion_id="TEST-001", numero="1")])

    with connect() as c:
        count = c.execute("SELECT COUNT(*) FROM lotes WHERE licitacion_id = 'TEST-001'").fetchone()[
            0
        ]
    assert count == 1


def test_replace_lotes_empty_clears(db):
    from db.database import connect
    from db.upsert import Lote, replace_lotes, upsert_licitaciones

    upsert_licitaciones([make_licitacion(id_externo="TEST-001")])
    replace_lotes("TEST-001", [Lote(licitacion_id="TEST-001", numero="1")])
    mapping = replace_lotes("TEST-001", [])

    assert mapping == {}
    with connect() as c:
        count = c.execute("SELECT COUNT(*) FROM lotes WHERE licitacion_id = 'TEST-001'").fetchone()[
            0
        ]
    assert count == 0


def test_replace_lotes_batch_multiple_licitaciones(db):
    from db.upsert import Lote, replace_lotes_batch, upsert_licitaciones

    upsert_licitaciones([make_licitacion(id_externo="LIC-A"), make_licitacion(id_externo="LIC-B")])
    result = replace_lotes_batch(
        {
            "LIC-A": [Lote(licitacion_id="LIC-A", numero="1")],
            "LIC-B": [
                Lote(licitacion_id="LIC-B", numero="1"),
                Lote(licitacion_id="LIC-B", numero="2"),
            ],
        }
    )

    assert set(result["LIC-A"]) == {"1"}
    assert set(result["LIC-B"]) == {"1", "2"}
    # Mismo numero "1" en dos licitaciones distintas -> ids distintos (PK global).
    assert result["LIC-A"]["1"] != result["LIC-B"]["1"]


def test_replace_adjudicaciones_same_nif_importe_different_lote_both_persist(db):
    """Regresión directa del bug de pérdida de filas (docs/IMPROVEMENT_BACKLOG.md):
    antes de v65_lotes, la unique (licitacion_id, nif, importe_adjudicado)
    descartaba en silencio una fila cuando la misma empresa ganaba dos lotes
    por el mismo importe. Con lote_id resuelto, ambas deben persistir."""
    from db.database import connect
    from db.upsert import Lote, replace_adjudicaciones, replace_lotes, upsert_licitaciones

    upsert_licitaciones([make_licitacion(id_externo="TEST-001")])
    lote_ids = replace_lotes(
        "TEST-001",
        [
            Lote(licitacion_id="TEST-001", numero="1"),
            Lote(licitacion_id="TEST-001", numero="2"),
        ],
    )
    adj_lote_1 = _make_adj(nif="B00000001", importe_adjudicado=5000.0, lote_id=lote_ids["1"])
    adj_lote_2 = _make_adj(nif="B00000001", importe_adjudicado=5000.0, lote_id=lote_ids["2"])

    persisted, dropped = replace_adjudicaciones("TEST-001", [adj_lote_1, adj_lote_2])

    assert persisted == 2
    assert dropped == 0
    with connect() as c:
        count = c.execute(
            "SELECT COUNT(*) FROM adjudicaciones WHERE licitacion_id = 'TEST-001'"
        ).fetchone()[0]
    assert count == 2
