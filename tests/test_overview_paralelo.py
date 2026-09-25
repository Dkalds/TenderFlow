"""``get_overview``: consultas en paralelo acotado y piezas tomadas del snapshot.

Qué se fija, sin Postgres (el repositorio es un doble que anota cada llamada):

- El resultado es **el mismo** en serie y en paralelo: paralelizar cambia el
  orden de ejecución, nunca la forma ni los números de la respuesta.
- El paralelismo es real (tres consultas a la vez) y está acotado: por
  petición y por proceso. Sin cupo, la petición va en serie en su propio hilo
  en vez de esperar a nadie.
- Los ayudantes ven el contexto de la petición: la organización de
  ``shared.tenant_context``, que ``connect_read`` convierte en ``SET LOCAL``.
- Un fallo se relanza tal cual y no arranca más consultas.
- Los indicadores de adjudicaciones salen del snapshot **también con
  filtros**, y una variante por tecnología ahorra sus dos consultas.
"""

from __future__ import annotations

import threading
from functools import partial
from typing import Any

import pytest

from db.repositories.kpi_snapshots import OverviewSnapshot
from services.analytics import overview as ov
from shared.tenant_context import current_organization, tenant_scope

_ADJ_SNAPSHOT: dict[str, float | None] = {
    "hhi": 1234.0,
    "pct_oferta_unica": 40.0,
    "lead_time_medio": 55.0,
    "pct_pyme": 12.0,
    "adj_total": 100.0,
    "adj_con_n_ofertas": 80.0,
}
_ADJ_EN_VIVO: dict[str, float | None] = {**_ADJ_SNAPSHOT, "hhi": 999.0}


class _RepoAnotador:
    """Repositorio doble: formas válidas y una traza de quién pidió qué, y desde dónde.

    ``barrera`` retiene las tres primeras consultas hasta que coinciden, para
    demostrar que corren a la vez; ``falla`` hace lanzar a una concreta.
    """

    def __init__(
        self, *, barrera: threading.Barrier | None = None, falla: str | None = None
    ) -> None:
        self.barrera = barrera
        self.falla = falla
        self.llamadas: list[tuple[str, int, int | None]] = []
        self._lock = threading.Lock()

    def _anota(self, nombre: str) -> None:
        with self._lock:
            self.llamadas.append((nombre, threading.get_ident(), current_organization()))
        if self.falla == nombre:
            raise RuntimeError(f"{nombre} caída")
        if self.barrera is not None and nombre in {"adj", "ccaa", "tasa"}:
            self.barrera.wait()

    @property
    def nombres(self) -> list[str]:
        return [n for n, _hilo, _org in self.llamadas]

    def overview_adjudicaciones_indicadores(self) -> dict[str, float | None]:
        self._anota("adj")
        return dict(_ADJ_EN_VIVO)

    def overview_ccaa_cubiertas(self, _f: Any) -> int:
        self._anota("ccaa")
        return 4

    def overview_tasa_anulacion(self, _f: Any, **_kw: Any) -> tuple[int, int]:
        self._anota("tasa")
        return (1, 20)

    def overview_kpis(self, _f: Any) -> dict[str, Any]:
        self._anota("kpis")
        return {"total": 20, "importe_total": 2000.0, "importe_medio": 100.0, "organos": 5}

    def overview_para_hoy(self, _f: Any, **kw: Any) -> dict[str, int]:
        self._anota("para_hoy")
        self.para_hoy_kw = kw
        return {"calientes_hoy": 1, "vencen_48h": 2, "nuevas_24h": 3}

    def overview_yoy_and_recent(self, _f: Any, **_kw: Any) -> dict[str, float]:
        self._anota("yoy")
        return {"lics_30d": 6.0, "lics_prev30d": 3.0, "importe_30d": 600.0}

    def overview_concentracion_organos(self, _f: Any, **_kw: Any) -> tuple[float, float]:
        self._anota("conc_organos")
        return (500.0, 1000.0)

    def overview_concentracion_ccaa(self, _f: Any, **_kw: Any) -> tuple[float, float]:
        self._anota("conc_ccaa")
        return (900.0, 1000.0)

    def overview_top_organos(self, _f: Any) -> list[dict[str, Any]]:
        self._anota("top_organos")
        return [{"organo_contratacion": "O1", "n": 3, "importe": 30.0}]

    def overview_por_mes(self, _f: Any) -> list[dict[str, Any]]:
        self._anota("por_mes")
        return [{"mes": "2026-08", "n_licitaciones": 20, "importe": 2000.0}]

    def overview_por_estado(self, _f: Any) -> list[dict[str, Any]]:
        self._anota("por_estado")
        return [{"estado": "PUB", "n": 20}]

    def overview_funnel(self, _f: Any) -> dict[str, int]:
        self._anota("funnel")
        return {"total": 20, "PUB": 10, "EV": 4, "RES": 3, "ADJ": 2, "ANUL": 1}


_TODAS = {
    "adj",
    "ccaa",
    "tasa",
    "kpis",
    "para_hoy",
    "yoy",
    "conc_organos",
    "conc_ccaa",
    "top_organos",
    "por_mes",
    "por_estado",
    "funnel",
}


def _preparar(
    monkeypatch: pytest.MonkeyPatch,
    repo: _RepoAnotador,
    *,
    cupo: int,
    snap: OverviewSnapshot | None = None,
    adj_suelto: dict[str, float | None] | None = None,
) -> threading.BoundedSemaphore:
    """Monta el doble, fija el cupo global de ayudantes y el snapshot que se lee.

    ``cupo=0`` equivale a un proceso con todos sus ayudantes ocupados.
    """
    semaforo = threading.BoundedSemaphore(cupo)
    monkeypatch.setattr(ov, "_repo", repo)
    monkeypatch.setattr(ov, "_semaforo_ayudantes", lambda: semaforo)
    monkeypatch.setattr(ov, "read_overview_snapshot_for", lambda _f, **_kw: snap)
    monkeypatch.setattr(ov, "read_adj_indicadores_snapshot", lambda **_kw: adj_suelto)
    return semaforo


# ── Mismo resultado, más rápido ────────────────────────────────────────────


@pytest.mark.parametrize(
    "filtros",
    [ov.OverviewFilters(), ov.OverviewFilters(tecnologia="SAP", q="erp")],
    ids=["sin_filtros", "con_filtros"],
)
def test_en_serie_y_en_paralelo_dan_la_misma_respuesta(
    monkeypatch: pytest.MonkeyPatch, filtros: ov.OverviewFilters
) -> None:
    serie = _RepoAnotador()
    _preparar(monkeypatch, serie, cupo=0)
    en_serie = ov.get_overview(filtros)

    paralelo = _RepoAnotador()
    _preparar(monkeypatch, paralelo, cupo=2)
    en_paralelo = ov.get_overview(filtros)

    assert en_paralelo.model_dump() == en_serie.model_dump()
    assert set(serie.nombres) == set(paralelo.nombres) == _TODAS
    assert len(paralelo.nombres) == len(_TODAS), "ninguna consulta se repite"
    # Los números salen de las consultas, no de valores por defecto.
    assert en_serie.total_licitaciones == 20
    assert en_serie.tasa_anulacion == pytest.approx(5.0)
    assert en_serie.concentracion_geo_top3 == pytest.approx(90.0)
    assert en_serie.hhi == 999.0


def test_tres_consultas_corren_a_la_vez(monkeypatch: pytest.MonkeyPatch) -> None:
    """Las tres primeras de la cola esperan en una barrera de tres: solo pasa si coinciden.

    Si el paralelismo no existiera, la primera se quedaría esperando a las
    otras dos y la barrera se rompería por tiempo en lugar de colgar el test.
    """
    repo = _RepoAnotador(barrera=threading.Barrier(3, timeout=10))
    _preparar(monkeypatch, repo, cupo=2)

    ov.get_overview(ov.OverviewFilters(ccaa="Madrid"))

    hilos = {hilo for nombre, hilo, _org in repo.llamadas if nombre in {"adj", "ccaa", "tasa"}}
    assert len(hilos) == 3


def test_el_contexto_de_la_peticion_llega_a_los_ayudantes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Todas las consultas ven la organización fijada, también las de otros hilos.

    Un hilo nuevo no hereda ``contextvars``: sin la copia explícita, las
    consultas de los ayudantes abrirían su conexión sin ``SET LOCAL
    app.organization_id`` y RLS vería otra cosa que la petición.
    """
    repo = _RepoAnotador(barrera=threading.Barrier(3, timeout=10))
    _preparar(monkeypatch, repo, cupo=2)

    with tenant_scope(42):
        ov.get_overview(ov.OverviewFilters(ccaa="Madrid"))

    assert {org for _n, _hilo, org in repo.llamadas} == {42}
    assert len({hilo for _n, hilo, _org in repo.llamadas}) >= 2


# ── Cotas ──────────────────────────────────────────────────────────────────


def test_sin_cupo_global_la_peticion_va_en_serie_en_su_propio_hilo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con los ayudantes del proceso ocupados no se espera: se hace todo aquí."""
    repo = _RepoAnotador()
    _preparar(monkeypatch, repo, cupo=0)

    ov.get_overview(ov.OverviewFilters(ccaa="Madrid"))

    assert {hilo for _n, hilo, _org in repo.llamadas} == {threading.get_ident()}


def test_como_mucho_dos_ayudantes_por_peticion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aunque el proceso tuviera cupo de sobra, una petición no pasa de tres hilos."""
    repo = _RepoAnotador(barrera=threading.Barrier(3, timeout=10))
    _preparar(monkeypatch, repo, cupo=10)

    ov.get_overview(ov.OverviewFilters(ccaa="Madrid"))

    assert len({hilo for _n, hilo, _org in repo.llamadas}) <= 1 + ov._AYUDANTES_POR_PETICION


def test_los_ayudantes_devuelven_su_cupo(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _RepoAnotador(barrera=threading.Barrier(3, timeout=10))
    semaforo = _preparar(monkeypatch, repo, cupo=2)

    ov.get_overview(ov.OverviewFilters(ccaa="Madrid"))

    assert semaforo.acquire(blocking=False)
    assert semaforo.acquire(blocking=False)
    semaforo.release()
    semaforo.release()


@pytest.mark.parametrize(
    ("lectura", "general", "esperado"),
    [(12, 12, 2), (0, 12, 2), (0, 5, 1), (5, 12, 1), (0, 3, 0), (40, 40, 2)],
)
def test_el_cupo_global_es_una_cuarta_parte_del_pool_de_lectura_con_tope(
    monkeypatch: pytest.MonkeyPatch, lectura: int, general: int, esperado: int
) -> None:
    """``DB_READ_POOL_SIZE`` a 0 hereda ``DB_POOL_SIZE``, igual que ``db/connection.py``."""
    monkeypatch.setattr(ov.settings, "DB_READ_POOL_SIZE", lectura)
    monkeypatch.setattr(ov.settings, "DB_POOL_SIZE", general)
    assert ov._cupo_ayudantes() == esperado


# ── Fallos ─────────────────────────────────────────────────────────────────


def test_un_fallo_se_relanza_y_no_arranca_mas_consultas(monkeypatch: pytest.MonkeyPatch) -> None:
    """En serie el corte es exacto: lo que venía detrás de la consulta caída no corre."""
    repo = _RepoAnotador(falla="ccaa")
    _preparar(monkeypatch, repo, cupo=0)

    with pytest.raises(RuntimeError, match="ccaa caída"):
        ov.get_overview(ov.OverviewFilters(ccaa="Madrid"))

    assert repo.nombres == ["adj", "ccaa"]


def test_un_fallo_en_paralelo_tambien_llega_al_llamante(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _RepoAnotador(falla="funnel")
    semaforo = _preparar(monkeypatch, repo, cupo=2)

    with pytest.raises(RuntimeError, match="funnel caída"):
        ov.get_overview(ov.OverviewFilters(ccaa="Madrid"))

    # Y los ayudantes no se quedan con el cupo aunque la petición falle.
    assert semaforo.acquire(blocking=False)
    semaforo.release()


class _LogGrabador:
    """Sustituye al ``log`` del módulo y guarda los eventos de aviso."""

    def __init__(self) -> None:
        self.avisos: list[tuple[str, dict[str, Any]]] = []
        self._lock = threading.Lock()

    def warning(self, evento: str, **campos: Any) -> None:
        with self._lock:
            self.avisos.append((evento, campos))

    def info(self, *_a: Any, **_k: Any) -> None:
        pass

    debug = info


def test_dos_fallos_a_la_vez_se_relanza_uno_y_quedan_registrados_los_dos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Solo una excepción llega al llamante; la otra no puede perderse sin rastro."""
    grabador = _LogGrabador()
    monkeypatch.setattr(ov, "log", grabador)

    def _cae(nombre: str) -> int:
        raise RuntimeError(f"{nombre} caída")

    barrera = threading.Barrier(2, timeout=10)

    def _cae_a_la_vez(nombre: str) -> int:
        barrera.wait()
        return _cae(nombre)

    tareas = [
        ov._Tarea(lambda: _cae_a_la_vez("a")),
        ov._Tarea(lambda: _cae_a_la_vez("b")),
    ]
    monkeypatch.setattr(ov, "_semaforo_ayudantes", lambda: threading.BoundedSemaphore(1))

    with pytest.raises(RuntimeError, match=r"^[ab] caída$"):
        ov._en_paralelo(tareas)

    fallidas = [
        campos for evento, campos in grabador.avisos if evento == "overview_consulta_fallida"
    ]
    assert len(fallidas) == 2
    assert all(campos.get("exc_info") is True for campos in fallidas)


def test_el_log_nombra_la_consulta_aunque_vaya_envuelta_en_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grabador = _LogGrabador()
    monkeypatch.setattr(ov, "log", grabador)
    repo = _RepoAnotador(falla="funnel")

    tarea = ov._Tarea(partial(repo.overview_funnel, None))
    assert isinstance(tarea.ejecutar(), RuntimeError)

    assert grabador.avisos[0][0] == "overview_consulta_fallida"
    assert grabador.avisos[0][1]["consulta"] == "overview_funnel"


def test_una_tarea_guarda_su_excepcion_y_la_relanza_al_pedir_el_resultado() -> None:
    def _cae() -> int:
        raise KeyError("x")

    tarea = ov._Tarea(_cae)
    assert tarea.pendiente
    error = tarea.ejecutar()
    assert isinstance(error, KeyError)
    assert not tarea.pendiente
    with pytest.raises(KeyError):
        tarea.resultado()

    resuelta = ov._Tarea.resuelta(7)
    assert not resuelta.pendiente
    assert resuelta.resultado() == 7


# ── Qué sale del snapshot ──────────────────────────────────────────────────


def test_con_filtros_los_indicadores_de_adjudicaciones_salen_del_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La pieza más cara del overview ya no se recalcula en cada búsqueda."""
    repo = _RepoAnotador()
    _preparar(monkeypatch, repo, cupo=2, adj_suelto=dict(_ADJ_SNAPSHOT))

    resultado = ov.get_overview(ov.OverviewFilters(q="erp", ccaa="Madrid"))

    assert "adj" not in repo.nombres
    assert resultado.hhi == 1234.0
    assert resultado.cobertura_oferta_unica.cobertura_pct == pytest.approx(80.0)


def test_sin_fila_de_indicadores_se_calculan_en_vivo(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _RepoAnotador()
    _preparar(monkeypatch, repo, cupo=2, adj_suelto=None)

    resultado = ov.get_overview(ov.OverviewFilters(q="erp"))

    assert repo.nombres.count("adj") == 1
    assert resultado.hhi == 999.0


def test_con_snapshot_aplicable_no_se_relee_la_fila_suelta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si el snapshot ya trae la pieza (aunque sea ``None`` por ilegible), manda él."""
    lecturas: list[int] = []
    repo = _RepoAnotador()
    snap = OverviewSnapshot(
        computed_at="2026-09-24T00:00:00+00:00",
        kpis=None,
        adj_indicadores=None,
        tasa_anulacion=None,
        importe_p75=None,
        total_activas=None,
    )
    _preparar(monkeypatch, repo, cupo=0, snap=snap)
    monkeypatch.setattr(
        ov, "read_adj_indicadores_snapshot", lambda **_kw: lecturas.append(1) or None
    )

    ov.get_overview(ov.OverviewFilters())

    assert lecturas == []
    assert repo.nombres.count("adj") == 1


def test_una_variante_por_tecnologia_ahorra_kpis_y_tasa(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con ``{tecnologia: X}`` precalculada, esas dos consultas no se lanzan."""
    repo = _RepoAnotador()
    snap = OverviewSnapshot(
        computed_at="2026-09-24T00:00:00+00:00",
        kpis={"total": 7, "importe_total": 70.0, "importe_medio": 10.0, "organos": 2},
        adj_indicadores=dict(_ADJ_SNAPSHOT),
        tasa_anulacion=(2, 8),
        importe_p75=None,
        total_activas=None,
        dimension="tecnologia:SAP",
    )
    _preparar(monkeypatch, repo, cupo=2, snap=snap)

    resultado = ov.get_overview(ov.OverviewFilters(tecnologia="SAP"))

    assert {"kpis", "tasa", "adj"}.isdisjoint(repo.nombres)
    assert resultado.total_licitaciones == 7
    assert resultado.tasa_anulacion == pytest.approx(25.0)
    assert resultado.hhi == 1234.0
    # "Para hoy" sigue en vivo con el filtro, sin umbral global inyectado.
    assert repo.para_hoy_kw["p75"] is None
    assert repo.para_hoy_kw["total_activas"] is None
