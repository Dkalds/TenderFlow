"""Fechas a ``timestamptz``, fase 1 (``v159``/``v160``): lo que se prueba sin base.

* El parseo de los formatos **reales**: los que hay en producción (medidos con
  el MCP de solo lectura el 2026-10-25, una forma por línea) y los que emite el
  parser CODICE sobre el corpus golden de ``tests/fixtures/placsp``.
* Que la migración, el registro de ``db/fechas_ts.py`` y los fragmentos de
  lectura describen las mismas columnas.
* La forma del SQL: migración, escritura dual del upsert, backfill y lectura
  dual con el flag apagado (byte a byte lo de antes) y encendido.
* El script de backfill: reanudable y con sus guardas de argumentos.

Lo que necesita Postgres (triggers, paridad con la gemela SQL, backfill real)
vive en ``tests/test_fechas_ts_pg.py``.
"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import db.sql_fragments as sf
from db.fechas_ts import (
    LIC_COLUMNAS_UPSERT,
    TABLAS,
    Lote,
    a_timestamptz,
    cursor_de_texto,
    detalle_verificacion,
    sombras_presentes,
    sql_rellenar,
    sql_verificar,
    tabla,
    valores_lic,
)

_VERSIONES = Path(__file__).resolve().parents[1] / "db" / "alembic" / "versions"
_GOLDEN = Path(__file__).parent / "fixtures" / "placsp" / "golden.jsonl"


def _cargar(nombre: str) -> Any:
    spec = importlib.util.spec_from_file_location(nombre, _VERSIONES / f"{nombre}.py")
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _sql_emitido(nombre: str, funcion: str, *, dialecto: str = "postgresql") -> list[str]:
    modulo = _cargar(nombre)
    emitido: list[str] = []
    with patch.object(modulo, "op") as op_falso:
        op_falso.get_bind.return_value.dialect.name = dialecto
        op_falso.execute.side_effect = emitido.append
        getattr(modulo, funcion)()
    return emitido


# ── Parseo de formatos reales ─────────────────────────────────────────────

_UTC = UTC
_MAS1 = timezone(timedelta(hours=1))
_MAS2 = timezone(timedelta(hours=2))

#: Una muestra por forma distinta en producción (2026-10-25), con su instante.
#: Columnas donde aparece cada forma entre paréntesis.
FORMATOS_PRODUCCION: list[tuple[str, datetime]] = [
    # now_utc_iso(): fecha_extraccion, primera_extraccion, documentos.*,
    # captured_at, pursuit_events/user_notifications.created_at, read_at.
    (
        "2026-05-11T00:36:11.459410+00:00",
        datetime(2026, 5, 11, 0, 36, 11, 459410, tzinfo=_UTC),
    ),
    # now()::text que v151 no alcanzó (fecha_extraccion, primera_extraccion):
    # espacio, offset sin minutos y de 1 a 6 decimales.
    ("2026-09-04 09:38:20.097671+00", datetime(2026, 9, 4, 9, 38, 20, 97671, tzinfo=_UTC)),
    ("2026-09-04 09:38:25.66429+00", datetime(2026, 9, 4, 9, 38, 25, 664290, tzinfo=_UTC)),
    ("2026-09-04 09:38:23.5336+00", datetime(2026, 9, 4, 9, 38, 23, 533600, tzinfo=_UTC)),
    ("2026-09-04 09:39:39.071+00", datetime(2026, 9, 4, 9, 39, 39, 71000, tzinfo=_UTC)),
    ("2026-09-04 09:47:03.3+00", datetime(2026, 9, 4, 9, 47, 3, 300000, tzinfo=_UTC)),
    # datetime('now') de SQLite, sin zona: se lee UTC (v152).
    ("2026-05-11 01:49:44", datetime(2026, 5, 11, 1, 49, 44, tzinfo=_UTC)),
    # Fecha sola: fecha_inicio, fecha_fin, fecha_adjudicacion, fecha_extraccion.
    ("2025-01-01", datetime(2025, 1, 1, tzinfo=_UTC)),
    ("2017-12-31", datetime(2017, 12, 31, tzinfo=_UTC)),
    # fecha_actualizacion_fuente: el <updated> del feed, con milisegundos.
    ("2026-07-13T13:26:08.273Z", datetime(2026, 7, 13, 13, 26, 8, 273000, tzinfo=_UTC)),
    (
        "2017-12-30T09:34:52.459+01:00",
        datetime(2017, 12, 30, 9, 34, 52, 459000, tzinfo=_MAS1),
    ),
    ("2018-06-09T00:00:00+02:00", datetime(2018, 6, 9, tzinfo=_MAS2)),
    ("2024-03-15T00:00:00Z", datetime(2024, 3, 15, tzinfo=_UTC)),
]


@pytest.mark.parametrize(("texto", "instante"), FORMATOS_PRODUCCION)
def test_cada_formato_de_produccion_se_traduce_a_su_instante(
    texto: str, instante: datetime
) -> None:
    resultado = a_timestamptz(texto)
    assert resultado == instante
    assert resultado is not None and resultado.tzinfo is not None


def test_el_espacio_y_la_t_del_mismo_dia_ordenan_como_instantes() -> None:
    """El fallo que motiva el ítem: como texto, ``' ' < 'T'`` invierte el orden."""
    antes = "2026-09-04T09:00:00.000000+00:00"
    despues = "2026-09-04 10:00:00.000000+00"
    assert despues < antes  # como texto, al revés
    ts_antes, ts_despues = a_timestamptz(antes), a_timestamptz(despues)
    assert ts_antes is not None and ts_despues is not None
    assert ts_despues > ts_antes


@pytest.mark.parametrize(
    "basura",
    [
        "",
        "no es fecha",
        "2026-02-30",
        "2026-13-01",
        "0000-01-01",
        "2026-01-01T24:00:00",
        "31/12/2026",
    ],
)
def test_lo_que_no_es_una_fecha_da_none(basura: str) -> None:
    assert a_timestamptz(basura) is None


def test_un_anio_de_tres_ceros_y_algo_se_conserva_tal_cual() -> None:
    """``0021-03-01`` está en ``fecha_inicio`` (y ``0019-12-10`` en
    ``fecha_adjudicacion``): basura de origen, pero una fecha válida. La sombra
    describe el texto; la verificación no la cuenta como divergente."""
    assert a_timestamptz("0021-03-01") == datetime(21, 3, 1, tzinfo=_UTC)


def _fechas_del_golden() -> list[tuple[str, str]]:
    campos_lic = ("fecha_inicio", "fecha_fin", "fecha_actualizacion_fuente")
    vistas: list[tuple[str, str]] = []
    for linea in _GOLDEN.read_text(encoding="utf-8").splitlines():
        if not linea.strip() or linea.startswith("#"):
            continue
        esperado = json.loads(linea)["esperado"]
        if not esperado:
            continue
        lic = esperado.get("licitacion") or {}
        vistas.extend((c, lic[c]) for c in campos_lic if lic.get(c))
        vistas.extend(
            ("fecha_adjudicacion", a["fecha_adjudicacion"])
            for a in esperado.get("adjudicaciones") or []
            if a.get("fecha_adjudicacion")
        )
    return vistas


def test_todo_lo_que_emite_el_parser_codice_tiene_sombra() -> None:
    """El corpus golden es la salida del parser sobre XML real de PLACSP: una
    forma nueva de fecha en él que la sombra no entendiera saldría ``NULL`` y la
    fase 2 la perdería."""
    vistas = _fechas_del_golden()
    assert len(vistas) >= 10, "el corpus golden dejó de traer fechas de estas columnas"
    sin_sombra = [(c, v) for c, v in vistas if a_timestamptz(v) is None]
    assert sin_sombra == []


# ── Las tres descripciones de las columnas coinciden ──────────────────────


def test_la_migracion_y_el_registro_describen_las_mismas_columnas() -> None:
    v159 = _cargar("v159_fechas_ts_sombra")
    assert {t.nombre: t.columnas for t in TABLAS} == v159.COLUMNAS
    assert set(v159.CON_TRIGGER) == {t.nombre for t in TABLAS if t.escritura == "trigger"}
    assert {t.nombre for t in TABLAS if not t.backfill} <= set(v159.RELLENO_EN_MIGRACION)


def test_los_fragmentos_de_lectura_conocen_las_mismas_columnas() -> None:
    assert {f"{t.nombre}.{c}" for t in TABLAS for c in t.columnas} == sf.FECHAS_CON_SOMBRA


def test_el_upsert_solo_escribe_sombras_de_columnas_que_escribe() -> None:
    from db.upsert import _LIC_KEYS

    assert set(LIC_COLUMNAS_UPSERT) <= set(_LIC_KEYS)
    assert set(LIC_COLUMNAS_UPSERT) <= set(tabla("licitaciones").columnas)
    # `primera_extraccion` no está en el dataclass: su sombra es del backfill.
    assert "primera_extraccion" not in _LIC_KEYS


# ── Migraciones ───────────────────────────────────────────────────────────


def test_v159_encadena_con_v158_y_v160_con_v159() -> None:
    v159, v160 = _cargar("v159_fechas_ts_sombra"), _cargar("v160_fechas_ts_indices")
    assert v159.down_revision == "v158_domain_events_pscp_rekey"
    assert v160.down_revision == v159.revision == "v159_fechas_ts_sombra"


def test_fuera_de_postgres_no_emiten_nada() -> None:
    for nombre in ("v159_fechas_ts_sombra", "v160_fechas_ts_indices"):
        assert _sql_emitido(nombre, "upgrade", dialecto="sqlite") == []
        assert _sql_emitido(nombre, "downgrade", dialecto="sqlite") == []


def test_v159_es_aditiva_y_acota_los_locks() -> None:
    emitido = _sql_emitido("v159_fechas_ts_sombra", "upgrade")
    assert emitido[0] == "SET LOCAL lock_timeout = '5s'"
    assert emitido[-1] == "RESET lock_timeout"
    alters = [s for s in emitido if s.startswith("ALTER TABLE") and "TRIGGER" not in s]
    assert alters and all("ADD COLUMN IF NOT EXISTS" in s for s in alters)
    assert all(" timestamptz" in s for s in alters)
    assert not any("DROP COLUMN" in s or "ALTER COLUMN" in s for s in emitido)
    # Nada de reescribir la columna de texto ni de defaults.
    assert not any("DEFAULT" in s for s in alters)


def test_v159_crea_el_trigger_antes_de_rellenar() -> None:
    emitido = _sql_emitido("v159_fechas_ts_sombra", "upgrade")
    for nombre in ("pursuit_events", "user_notifications"):
        trigger = next(
            i
            for i, s in enumerate(emitido)
            if f"TRIGGER trg_fechas_ts_{nombre} " in s and s.startswith("CREATE")
        )
        relleno = next(i for i, s in enumerate(emitido) if s.startswith(f"UPDATE {nombre} "))
        assert trigger < relleno


def test_pursuit_events_solo_se_toca_con_su_append_only_pausado() -> None:
    emitido = _sql_emitido("v159_fechas_ts_sombra", "upgrade")
    apagar = emitido.index(
        "ALTER TABLE pursuit_events DISABLE TRIGGER trg_pursuit_events_append_only"
    )
    encender = emitido.index(
        "ALTER TABLE pursuit_events ENABLE TRIGGER trg_pursuit_events_append_only"
    )
    entre = emitido[apagar + 1 : encender]
    assert len(entre) == 1 and entre[0].startswith("UPDATE pursuit_events ")
    crear = next(s for s in emitido if s.startswith("CREATE TRIGGER trg_fechas_ts_pursuit_events"))
    assert "BEFORE INSERT ON pursuit_events" in crear  # sin UPDATE: es un ledger


def test_los_triggers_solo_saltan_si_cambia_el_texto() -> None:
    emitido = _sql_emitido("v159_fechas_ts_sombra", "upgrade")
    crear = next(s for s in emitido if s.startswith("CREATE TRIGGER trg_fechas_ts_documentos"))
    assert "BEFORE INSERT OR UPDATE OF created_at, fetched_at, updated_at ON documentos" in crear
    funcion = next(s for s in emitido if "FUNCTION fechas_ts_documentos()" in s and "CREATE" in s)
    assert "NEW.created_at_ts := nucleo_iso_a_timestamptz(NEW.created_at);" in funcion


def test_licitaciones_no_lleva_trigger() -> None:
    """Su sombra la escribe el upsert, como las de v133."""
    emitido = _sql_emitido("v159_fechas_ts_sombra", "upgrade")
    assert not any("ON licitaciones " in s and "TRIGGER" in s for s in emitido)


def test_v159_downgrade_retira_triggers_funciones_y_columnas() -> None:
    emitido = _sql_emitido("v159_fechas_ts_sombra", "downgrade")
    assert "DROP TRIGGER IF EXISTS trg_fechas_ts_documentos ON documentos" in emitido
    assert "DROP FUNCTION IF EXISTS fechas_ts_documentos()" in emitido
    assert any("DROP COLUMN IF EXISTS fecha_extraccion_ts" in s for s in emitido)


def test_v160_construye_el_indice_concurrently() -> None:
    emitido = _sql_emitido("v160_fechas_ts_indices", "upgrade")
    assert emitido == [
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lic_fecha_extraccion_ts "
        "ON licitaciones (fecha_extraccion_ts)"
    ]
    assert _sql_emitido("v160_fechas_ts_indices", "downgrade") == [
        "DROP INDEX CONCURRENTLY IF EXISTS idx_lic_fecha_extraccion_ts"
    ]


# ── Escritura dual en db/upsert.py ────────────────────────────────────────


def test_sin_sombras_de_v159_el_upsert_no_cambia() -> None:
    from db.upsert import _sql_upsert_licitaciones

    for con_sombras in (False, True):
        assert _sql_upsert_licitaciones(con_sombras=con_sombras) == _sql_upsert_licitaciones(
            con_sombras=con_sombras, con_fechas_ts=False
        )
    assert "fecha_extraccion_ts" not in _sql_upsert_licitaciones(con_sombras=True)


@pytest.mark.parametrize("con_sombras", [False, True])
def test_con_sombras_de_v159_el_upsert_las_escribe_al_final(con_sombras: bool) -> None:
    from db.nucleo_tipado import COLUMNAS_SOMBRA
    from db.upsert import _LIC_KEYS, _sql_upsert_licitaciones

    sql = _sql_upsert_licitaciones(con_sombras=con_sombras, con_fechas_ts=True)
    columnas = sql.split("(", 1)[1].split(")", 1)[0].split(", ")
    esperadas = [*_LIC_KEYS]
    if con_sombras:
        esperadas += [s for s, _ in COLUMNAS_SOMBRA]
    esperadas += [f"{c}_ts" for c in LIC_COLUMNAS_UPSERT]
    assert columnas == esperadas
    assert sql.count("%s") == len(columnas)
    for col in LIC_COLUMNAS_UPSERT:
        assert f"{col}_ts=excluded.{col}_ts" in sql


def test_fila_licitacion_anade_las_fechas_traducidas() -> None:
    from db.upsert import _LIC_KEYS, Licitacion, _fila_licitacion

    data = asdict(
        Licitacion(
            id_externo="X",
            titulo="t",
            fecha_inicio="2026-01-01",
            fecha_fin="2026-12-31",
            fecha_actualizacion_fuente="2026-07-13T13:26:08.273Z",
        )
    )
    base = [data[k] for k in _LIC_KEYS]
    assert _fila_licitacion(data, con_sombras=False) == base
    fila = _fila_licitacion(data, con_sombras=False, con_fechas_ts=True)
    assert fila[: len(base)] == base
    assert fila[len(base) :] == valores_lic(data)
    extraccion, inicio, fin, actualizacion = fila[len(base) :]
    assert extraccion == a_timestamptz(data["fecha_extraccion"]) and extraccion is not None
    assert inicio == datetime(2026, 1, 1, tzinfo=_UTC)
    assert fin == datetime(2026, 12, 31, tzinfo=_UTC)
    assert actualizacion == datetime(2026, 7, 13, 13, 26, 8, 273000, tzinfo=_UTC)


class _ConexionCatalogo:
    def __init__(self, n: int) -> None:
        self.n = n
        self.consultas: list[Any] = []

    def execute(self, _sql: str, params: Any = None) -> _ConexionCatalogo:
        self.consultas.append(params)
        return self

    def fetchone(self) -> tuple[int]:
        return (self.n,)


def test_sombras_presentes_exige_todas() -> None:
    n = len(LIC_COLUMNAS_UPSERT)
    assert sombras_presentes(_ConexionCatalogo(n), "licitaciones", LIC_COLUMNAS_UPSERT)
    assert not sombras_presentes(_ConexionCatalogo(n - 1), "licitaciones", LIC_COLUMNAS_UPSERT)
    conexion = _ConexionCatalogo(n)
    sombras_presentes(conexion, "licitaciones", LIC_COLUMNAS_UPSERT)
    assert conexion.consultas == [("licitaciones", [f"{c}_ts" for c in LIC_COLUMNAS_UPSERT])]


def test_cada_chunk_pregunta_al_catalogo_por_v159() -> None:
    import db.upsert as upsert

    conexion = _ConexionCatalogo(len(LIC_COLUMNAS_UPSERT))
    assert upsert._con_fechas_ts(conexion) is True
    conexion.n = 0  # downgrade en caliente
    assert upsert._con_fechas_ts(conexion) is False


# ── Backfill: forma del SQL ───────────────────────────────────────────────


def test_el_backfill_solo_asigna_sombras_y_solo_en_su_rango() -> None:
    sql = sql_rellenar(tabla("documentos"))
    asignaciones = sql.split(" SET ", 1)[1].split(" WHERE id > ", 1)[0]
    destinos = [a.split(" = ", 1)[0] for a in asignaciones.split(" END, ")]
    assert [d.strip() for d in destinos] == ["created_at_ts", "fetched_at_ts", "updated_at_ts"]
    assert "WHERE id > %s AND id <= %s AND (" in sql
    assert "IS DISTINCT FROM nucleo_iso_a_timestamptz(created_at)" in sql


def test_la_verificacion_cuenta_divergencias_y_no_iso_por_columna() -> None:
    t = tabla("licitaciones")
    sql = sql_verificar(t)
    for clave in detalle_verificacion(t):
        assert f" AS {clave}" in sql
    assert "WHERE id_externo > %s AND id_externo <= %s" in sql
    assert sql.lstrip().startswith("SELECT")


def test_el_cursor_sigue_el_tipo_de_la_clave() -> None:
    assert cursor_de_texto(tabla("licitaciones"), "") == ""
    assert cursor_de_texto(tabla("licitaciones"), "placsp:9") == "placsp:9"
    assert cursor_de_texto(tabla("documentos"), "") == -(2**63)
    assert cursor_de_texto(tabla("documentos"), "41234") == 41234


# ── Lectura dual en db/sql_fragments.py ───────────────────────────────────


@pytest.fixture()
def lectura(monkeypatch: pytest.MonkeyPatch) -> Any:
    from config import settings

    def fijar(valor: bool) -> None:
        monkeypatch.setattr(settings, "FECHAS_TS_LECTURA", valor, raising=False)

    return fijar


def test_el_flag_nace_apagado() -> None:
    from config.settings import Settings

    assert Settings.model_fields["FECHAS_TS_LECTURA"].default is False


def test_instante_sql_sigue_el_flag(lectura: Any) -> None:
    lectura(False)
    assert sf.instante_sql("licitaciones_history", "captured_at", "h") == "h.captured_at"
    assert sf.param_instante_sql() == "%s"
    lectura(True)
    assert sf.instante_sql("licitaciones_history", "captured_at", "h") == (
        "COALESCE(h.captured_at_ts, nucleo_iso_a_timestamptz(h.captured_at))"
    )
    assert sf.instante_sql("documentos", "created_at") == (
        "COALESCE(created_at_ts, nucleo_iso_a_timestamptz(created_at))"
    )
    assert sf.param_instante_sql() == "%s::timestamptz"
    assert sf.instante_sql("documentos", "created_at", "d", tipada=False) == "d.created_at"


def test_instante_sql_rechaza_columnas_sin_sombra() -> None:
    with pytest.raises(ValueError, match="no tiene sombra"):
        sf.instante_sql("licitaciones", "fecha_publicacion", tipada=True)


class _Cursor:
    def __init__(self, filas: list[tuple[Any, ...]]) -> None:
        self._filas = filas
        self.description = [("x",)]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._filas

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._filas[0] if self._filas else None


class _Conexion:
    def __init__(self, respuestas: list[list[tuple[Any, ...]]]) -> None:
        self.respuestas = respuestas
        self.sql: list[str] = []

    def __enter__(self) -> _Conexion:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, sql: str, _params: Any = None) -> _Cursor:
        self.sql.append(sql)
        return _Cursor(self.respuestas.pop(0) if self.respuestas else [])


def test_novedades_con_el_flag_apagado_es_el_sql_de_siempre(
    lectura: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import db.repositories.novedades as nov

    lectura(False)
    conexion = _Conexion([])
    monkeypatch.setattr(nov, "connect_read", lambda: conexion)
    repo = nov.NovedadesRepository()
    repo.cambios_en_seguidos("u", desde_iso="2026-09-04T00:00:00+00:00")
    repo.documentos_nuevos_en_seguidos("u", desde_iso="2026-09-04T00:00:00+00:00")
    repo.pursuits_movidos(1, desde_iso="2026-09-04T00:00:00+00:00")
    historial, documentos, pursuits = conexion.sql
    assert "AND h.captured_at >= %s ORDER BY h.captured_at DESC" in historial
    assert "d.created_at::timestamptz >= %s::timestamptz" in documentos
    assert "AND e.created_at >= %s ORDER BY e.created_at DESC" in pursuits
    assert not any("_ts" in s for s in conexion.sql)


def test_novedades_con_el_flag_encendido_compara_instantes(
    lectura: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import db.repositories.novedades as nov

    lectura(True)
    conexion = _Conexion([])
    monkeypatch.setattr(nov, "connect_read", lambda: conexion)
    repo = nov.NovedadesRepository()
    repo.cambios_en_seguidos("u", desde_iso="2026-09-04T00:00:00+00:00")
    repo.documentos_nuevos_en_seguidos("u", desde_iso="2026-09-04T00:00:00+00:00")
    repo.pursuits_movidos(1, desde_iso="2026-09-04T00:00:00+00:00")
    historial, documentos, pursuits = conexion.sql
    h = "COALESCE(h.captured_at_ts, nucleo_iso_a_timestamptz(h.captured_at))"
    assert f"AND {h} >= %s::timestamptz ORDER BY {h} DESC" in historial
    d = "COALESCE(d.created_at_ts, nucleo_iso_a_timestamptz(d.created_at))"
    assert f"MIN({d}) AS publicado_en" in documentos
    assert f"{d} >= %s::timestamptz" in documentos
    e = "COALESCE(e.created_at_ts, nucleo_iso_a_timestamptz(e.created_at))"
    assert f"AND {e} >= %s::timestamptz ORDER BY {e} DESC" in pursuits
    # Lo proyectado sigue siendo el texto: ningún DTO cambia de tipo.
    assert "SELECT h.id_externo, h.captured_at," in historial
    assert "SELECT e.pursuit_id, e.event_type, e.created_at," in pursuits


def test_ultima_extraccion_prefiere_la_sombra_y_cae_al_texto(
    lectura: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import db.repositories.licitaciones as repo_mod

    repo = repo_mod.LicitacionRepository()

    lectura(False)
    conexion = _Conexion([[("2026-09-04T09:00:00+00:00",)]])
    monkeypatch.setattr(repo_mod, "connect_read", lambda: conexion)
    assert repo.get_last_extraction_date() == "2026-09-04T09:00:00+00:00"
    assert conexion.sql == ["SELECT MAX(fecha_extraccion) FROM licitaciones"]

    lectura(True)
    instante = datetime(2026, 9, 4, 11, 0, tzinfo=_MAS2)
    conexion = _Conexion([[(instante,)]])
    monkeypatch.setattr(repo_mod, "connect_read", lambda: conexion)
    assert repo.get_last_extraction_date() == "2026-09-04T09:00:00+00:00"
    assert conexion.sql == ["SELECT MAX(fecha_extraccion_ts) FROM licitaciones"]

    # Sombra vacía (backfill sin empezar): cae al texto.
    conexion = _Conexion([[(None,)], [("2026-09-03T08:00:00+00:00",)]])
    monkeypatch.setattr(repo_mod, "connect_read", lambda: conexion)
    assert repo.get_last_extraction_date() == "2026-09-03T08:00:00+00:00"
    assert len(conexion.sql) == 2


# ── Script de backfill ────────────────────────────────────────────────────


def test_el_script_exige_tabla_para_reanudar() -> None:
    from scripts import backfill_fechas_ts as script

    with pytest.raises(SystemExit):
        script.main(["--desde", "123"])


def test_el_script_no_reescribe_pursuit_events() -> None:
    from scripts import backfill_fechas_ts as script

    with pytest.raises(SystemExit):
        script.main(["--tabla", "pursuit_events"])


def test_el_script_recorre_por_lotes_e_imprime_desde_donde_reanudar(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts import backfill_fechas_ts as script

    vistos: list[tuple[str, Any, int]] = []
    lotes = iter(
        [
            Lote(hasta=10, filas=5, afectadas=3, detalle={}),
            Lote(hasta=20, filas=5, afectadas=0, detalle={}),
            Lote(hasta=None, filas=0, afectadas=0, detalle={}),
        ]
    )

    def falso(nombre: str, desde: Any, tamano: int) -> Lote:
        vistos.append((nombre, desde, tamano))
        return next(lotes)

    monkeypatch.setattr(script, "rellenar_lote", falso)
    assert script.main(["--tabla", "documentos", "--lote", "5", "--pausa", "0"]) == 0
    assert vistos == [("documentos", -(2**63), 5), ("documentos", 10, 5), ("documentos", 20, 5)]
    salida = capsys.readouterr().out
    assert "lote 2: hasta 20" in salida
    assert "2 lotes · 10 filas · 3 reescritas" in salida


def test_el_script_para_por_max_lotes_con_la_orden_de_reanudar(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts import backfill_fechas_ts as script

    monkeypatch.setattr(
        script,
        "rellenar_lote",
        lambda *_a: Lote(hasta="placsp:9", filas=1, afectadas=1, detalle={}),
    )
    assert script.main(["--tabla", "licitaciones", "--max-lotes", "1", "--pausa", "0"]) == 0
    assert "Reanudar con: --tabla licitaciones --desde 'placsp:9'" in capsys.readouterr().out


def test_la_verificacion_sale_1_si_hay_divergencias(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import backfill_fechas_ts as script

    t = tabla("user_notifications")
    detalle = dict.fromkeys(detalle_verificacion(t), 0) | {"created_at_ts": 1}
    lotes = iter(
        [
            Lote(hasta=5, filas=5, afectadas=1, detalle=detalle),
            Lote(hasta=None, filas=0, afectadas=0, detalle={}),
        ]
    )
    monkeypatch.setattr(script, "verificar_lote", lambda *_a: next(lotes))
    assert script.main(["--tabla", "user_notifications", "--verificar", "--pausa", "0"]) == 1
