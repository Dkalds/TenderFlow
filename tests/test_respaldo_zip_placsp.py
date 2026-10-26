"""El carril diario cae al ZIP mensual cuando el ATOM de PLACSP no avanza.

Lo que motiva el respaldo (backlog P0, medido el 2026-09-24): el feed ATOM
dejó de publicar entradas nuevas el 2026-09-08, cada pasada terminaba en
``success`` con 0 avisos y el ZIP mensual del mismo mes sí se regeneraba a
diario. El healthcheck ya avisa (``sin_datos_nuevos``); esto recupera el dato
mientras tanto.

Los tests unitarios doblan los cursores con un diccionario y el mes con una
función. Los ``test_integration_*`` del final pasan por Postgres y por el
conector bulk de verdad, con un ZIP construido desde un fixture CODICE.
"""

from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from scheduler import respaldo_zip_placsp as rz

_HOY = date(2026, 9, 24)
_CONGELADO = "2026-09-08T22:31:00+02:00"
_FIXTURE_ENTRY = Path(__file__).parent / "fixtures" / "placsp" / "07_adjudicacion_pyme.xml"


@pytest.fixture()
def cursores(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    """``ingestion_cursors`` en memoria, con la misma firma que ``db.database``."""
    almacen: dict[str, dict[str, Any]] = {}

    def get_cursor(source: str) -> dict[str, Any] | None:
        return dict(almacen[source]) if source in almacen else None

    def set_cursor(source: str, **campos: Any) -> None:
        almacen[source] = {"source": source, **campos}

    monkeypatch.setattr(rz, "get_cursor", get_cursor)
    monkeypatch.setattr(rz, "set_cursor", set_cursor)
    return almacen


@pytest.fixture()
def eventos(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, float | None, str | None]]:
    registrados: list[tuple[str, float | None, str | None]] = []
    monkeypatch.setattr(
        rz,
        "record_event",
        lambda tipo, value=None, detail=None: registrados.append((tipo, value, detail)),
    )
    return registrados


class _Meses:
    """Doble de la ingesta de un mes: apunta qué meses se pidieron."""

    def __init__(self, efecto: BaseException | None = None) -> None:
        self.pedidos: list[tuple[int, int]] = []
        self.efecto = efecto

    def __call__(self, year: int, month: int) -> dict[str, Any]:
        self.pedidos.append((year, month))
        if self.efecto is not None:
            raise self.efecto
        return {"year": year, "month": month, "status": "ok", "nuevas": 3}


def _pasada(
    meses: _Meses,
    *,
    antes: str | None = _CONGELADO,
    despues: str | None = _CONGELADO,
    fetch_failed: bool = False,
    umbral: int = 6,
    hoy: date = _HOY,
) -> dict[str, Any]:
    return rz.tras_pasada_atom(
        cursor_antes=antes,
        cursor_despues=despues,
        fetch_failed=fetch_failed,
        umbral=umbral,
        hoy=hoy,
        correr_mes=meses,
    )


# ── Cuándo cae al ZIP ────────────────────────────────────────────────────────


def test_cinco_pasadas_paradas_no_caen_al_zip_y_la_sexta_si(cursores, eventos):
    meses = _Meses()

    acciones = [_pasada(meses)["accion"] for _ in range(5)]

    assert acciones == ["cuenta"] * 5
    assert meses.pedidos == []

    sexta = _pasada(meses)

    assert sexta["accion"] == "respaldo"
    assert meses.pedidos == [(2026, 9)]
    assert sexta["meses"] == ["2026-09"]


def test_tras_el_respaldo_la_cuenta_vuelve_a_empezar(cursores, eventos):
    """Como mucho un ZIP cada N pasadas: el ZIP solo se regenera una vez al día.

    Con N = 6 y una pasada cada 4 h, eso es un ZIP al día mientras el ATOM siga
    parado, en vez de reprocesar el mismo fichero en cada pasada.
    """
    meses = _Meses()
    for _ in range(6):
        _pasada(meses)
    assert meses.pedidos == [(2026, 9)]

    acciones = [_pasada(meses)["accion"] for _ in range(6)]

    assert acciones == ["cuenta"] * 5 + ["respaldo"]
    assert meses.pedidos == [(2026, 9), (2026, 9)]


def test_si_el_atom_avanza_la_cuenta_se_reinicia(cursores, eventos):
    meses = _Meses()
    for _ in range(5):
        _pasada(meses)

    avanza = _pasada(meses, despues="2026-09-24T10:00:00+02:00")
    assert avanza["accion"] == "avanza"

    # Un ATOM que vuelve a pararse en otro instante empieza de cero.
    nueva = "2026-09-24T10:00:00+02:00"
    acciones = [_pasada(meses, antes=nueva, despues=nueva)["accion"] for _ in range(5)]
    assert acciones == ["cuenta"] * 5
    assert meses.pedidos == []


def test_un_fetch_fallido_no_cuenta_como_atom_parado(cursores, eventos):
    """Caído no es congelado: el ZIP vive en el mismo host y fallaría igual."""
    meses = _Meses()
    for _ in range(5):
        _pasada(meses)

    fallo = _pasada(meses, fetch_failed=True)

    assert fallo["accion"] == "fallo_fetch"
    assert fallo["pasadas_sin_avance"] == 5
    assert _pasada(meses)["accion"] == "respaldo"


def test_sin_cursor_previo_no_hay_nada_que_comparar(cursores, eventos):
    meses = _Meses()

    resultado = _pasada(meses, antes=None, despues=_CONGELADO)

    assert resultado["accion"] == "sin_referencia"
    assert meses.pedidos == []


def test_umbral_cero_apaga_el_respaldo(cursores, eventos):
    meses = _Meses()

    resultados = [_pasada(meses, umbral=0) for _ in range(10)]

    assert {r["accion"] for r in resultados} == {"desactivado"}
    assert meses.pedidos == []
    assert cursores == {}


def test_el_umbral_por_defecto_sale_de_settings(cursores, eventos, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "PLACSP_ATOM_PASADAS_SIN_AVANCE_ZIP", 2)
    meses = _Meses()

    acciones = [
        rz.tras_pasada_atom(
            cursor_antes=_CONGELADO,
            cursor_despues=_CONGELADO,
            fetch_failed=False,
            hoy=_HOY,
            correr_mes=meses,
        )["accion"]
        for _ in range(2)
    ]

    assert acciones == ["cuenta", "respaldo"]


def test_el_valor_por_defecto_es_un_dia_de_pasadas():
    """Seis pasadas de 4 h: un ZIP al día, que es lo que tarda en regenerarse."""
    from config.settings import Settings

    assert Settings.model_fields["PLACSP_ATOM_PASADAS_SIN_AVANCE_ZIP"].default == 6


# ── Ventana del carril y trazas ──────────────────────────────────────────────


def test_el_estado_se_escribe_antes_de_bajar_el_zip(cursores, eventos):
    """Un ZIP que agota el step no puede repetirse en cada pasada siguiente.

    Si el respaldo se apuntara después, una descarga que Actions mata a los
    45 minutos dejaría la cuenta en N y la pasada siguiente volvería a
    intentarlo: el carril diario entero dedicado a un ZIP que no cabe.
    """

    class _Corte(BaseException):
        pass

    for _ in range(5):
        _pasada(_Meses())
    with pytest.raises(_Corte):
        _pasada(_Meses(efecto=_Corte()))

    meses = _Meses()
    assert _pasada(meses)["accion"] == "cuenta"
    assert meses.pedidos == []


def test_un_respaldo_roto_no_tumba_el_carril(cursores, eventos):
    for _ in range(5):
        _pasada(_Meses())

    resultado = _pasada(_Meses(efecto=RuntimeError("ZIP corrupto")))

    assert resultado["accion"] == "respaldo"
    assert resultado["resultados"] == [{"year": 2026, "month": 9, "status": "error"}]


def test_si_falla_leer_el_estado_el_carril_sigue(monkeypatch, eventos):
    def roto(source: str) -> None:
        raise ConnectionError("pooler caído")

    monkeypatch.setattr(rz, "get_cursor", roto)

    resultado = _pasada(_Meses())

    assert resultado["accion"] == "error"


def test_el_respaldo_deja_traza_en_ops_events(cursores, eventos):
    for _ in range(6):
        _pasada(_Meses())

    assert len(eventos) == 1
    tipo, valor, detalle = eventos[0]
    assert tipo == "placsp_atom_respaldo_zip"
    assert valor == 1
    assert detalle is not None
    assert _CONGELADO in detalle
    assert "2026-09" in detalle


# ── Qué meses ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("hoy", "desde", "esperado"),
    [
        (date(2026, 9, 24), "2026-09-08T22:31:00+02:00", [(2026, 9)]),
        # El hueco empezó el mes anterior: su ZIP trae la cola que falta.
        (date(2026, 10, 1), "2026-09-30", [(2026, 9), (2026, 10)]),
        # Más atrás no se va: un respaldo no es un backfill (scrape-bulk.yml).
        (date(2026, 10, 3), "2026-07-02T10:00:00Z", [(2026, 9), (2026, 10)]),
        (date(2026, 1, 2), "2025-12-31", [(2025, 12), (2026, 1)]),
        (date(2026, 9, 24), None, [(2026, 9)]),
        (date(2026, 9, 24), "basura", [(2026, 9)]),
    ],
)
def test_meses_de_respaldo(hoy, desde, esperado):
    assert rz.meses_de_respaldo(hoy, desde) == esperado


def test_tras_un_respaldo_el_siguiente_parte_de_su_fecha(cursores, eventos):
    """El día 1 el ZIP del mes nuevo está vacío; la cola del anterior, no."""
    meses = _Meses()
    for _ in range(6):
        _pasada(meses, hoy=date(2026, 9, 30))
    assert meses.pedidos == [(2026, 9)]

    for _ in range(6):
        _pasada(meses, hoy=date(2026, 10, 1))

    assert meses.pedidos == [(2026, 9), (2026, 9), (2026, 10)]


# ── El carril diario lo llama ────────────────────────────────────────────────


def test_el_carril_diario_pasa_el_cursor_de_antes_y_el_de_despues(monkeypatch):
    from scheduler import pipeline_runs
    from scraper.connectors.base import ConnectorRunResult

    cursores_atom = iter([_CONGELADO, _CONGELADO])
    monkeypatch.setattr(rz, "cursor_atom_actual", lambda: next(cursores_atom))
    monkeypatch.setattr(
        "scraper.connectors.base.run_connector",
        lambda connector: ConnectorRunResult(source_id="placsp"),
    )
    monkeypatch.setattr(pipeline_runs, "_run_post_ingestion_steps", lambda **kw: {})
    recibido: dict[str, Any] = {}

    def tras(**kw: Any) -> dict[str, Any]:
        recibido.update(kw)
        return {"accion": "cuenta"}

    monkeypatch.setattr(rz, "tras_pasada_atom", tras)

    class _Run:
        def __enter__(self) -> Any:
            return type("M", (), {})()

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr("observability.record_run", lambda run_id: _Run())
    monkeypatch.setattr("observability.bind_run_context", lambda **kw: "run")

    resultado = pipeline_runs._run_daily_pipeline_connector(con_cierre=False)

    assert recibido == {
        "cursor_antes": _CONGELADO,
        "cursor_despues": _CONGELADO,
        "fetch_failed": False,
    }
    assert resultado["respaldo_zip"] == {"accion": "cuenta"}


# ---------------------------------------------------------------------------
# Recorrido real contra Postgres
# ---------------------------------------------------------------------------


def _zip_con_la_entry(tmp_path: Path) -> Path:
    """Un ZIP mensual mínimo: un feed ATOM con la entry del fixture dentro."""
    entry = _FIXTURE_ENTRY.read_text(encoding="utf-8").split("?>", 1)[1]
    feed = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        "<title>licitacionesPerfilesContratanteCompleto3</title>\n"
        f"{entry}\n</feed>\n"
    )
    destino = tmp_path / "placsp_202609.zip"
    with zipfile.ZipFile(destino, "w") as zf:
        zf.writestr("licitacionesPerfilesContratanteCompleto3_20260924_040100.atom", feed)
    return destino


def test_integration_el_respaldo_ingiere_el_zip_sin_tocar_el_cursor_del_atom(
    tmp_db, tmp_path, monkeypatch
):
    db_mod, _ = tmp_db
    db_mod.set_cursor("placsp", last_seen_updated=_CONGELADO, etag='"e1"')
    zip_path = _zip_con_la_entry(tmp_path)
    pedidos: list[tuple[int, int]] = []

    def download_month(year: int, month: int, force: bool = False) -> Path:
        pedidos.append((year, month))
        return zip_path

    monkeypatch.setattr("scraper.bulk_downloader.download_month", download_month)
    # El cierre del lote (empresas, dedupe, eventos) no es lo que se mide aquí.
    monkeypatch.setattr("scraper.connectors.base._post_ingestion", lambda *a, **k: None)

    for _ in range(2):
        resultado = rz.tras_pasada_atom(
            cursor_antes=_CONGELADO,
            cursor_despues=_CONGELADO,
            fetch_failed=False,
            umbral=1,
            hoy=_HOY,
        )
        assert resultado["accion"] == "respaldo"

    assert pedidos == [(2026, 9), (2026, 9)]
    assert resultado["resultados"][0]["status"] == "ok"
    # La clave acotada por el órgano del fixture (`ID_PLATAFORMA`, ADR-038).
    clave = "placsp:99000000000006:2026-PYME-0007"
    with db_mod.connect_read() as c:
        filas = c.execute(
            "SELECT fuente FROM licitaciones WHERE id_externo = %s", (clave,)
        ).fetchall()
        adjudicaciones = c.execute(
            "SELECT COUNT(*) FROM adjudicaciones WHERE licitacion_id = %s", (clave,)
        ).fetchone()
    # Idempotente: dos respaldos, una fila y sus adjudicaciones una sola vez.
    assert [f[0] for f in filas] == ["bulk_202609"]
    assert adjudicaciones is not None and int(adjudicaciones[0]) == 1
    cursor_atom = db_mod.get_cursor("placsp")
    assert cursor_atom is not None
    assert cursor_atom["last_seen_updated"] == _CONGELADO
    assert cursor_atom["etag"] == '"e1"'


def test_integration_el_estado_sobrevive_entre_pasadas(tmp_db):
    db_mod, _ = tmp_db
    meses = _Meses()

    for _ in range(3):
        _pasada(meses, umbral=4)

    estado = db_mod.get_cursor(rz.CURSOR_ESTADO)
    assert estado is not None
    assert estado["last_seen_updated"] == _CONGELADO
    assert estado["last_entry_id"] == "3"
    assert meses.pedidos == []
    assert _pasada(meses, umbral=4)["accion"] == "respaldo"
    estado = db_mod.get_cursor(rz.CURSOR_ESTADO)
    assert estado is not None
    assert estado["last_entry_id"] == "0"
    assert estado["last_modified"] == _HOY.isoformat()
