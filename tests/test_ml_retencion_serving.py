"""Serving de retención: población sin features, features por índice y horizonte.

El run de ``ml-scoring.yml`` del 2026-09-24 tardó 1.049 s en su step y rozó el
``timeout-minutes: 20``. ~10 min 40 s eran ``features_para_vencimientos``
calculando features para 3.003 contratos —cada uno recorría las ~698K
adjudicaciones dos veces— que el baseline, el único que se servía, tiraba sin
leer; y luego las tasas del baseline volvían a cargar las mismas 697.876 filas.

Lo que fija este fichero, todo sin Postgres:

- **Paridad exacta** de las features del índice de serving
  (``_IndiceServing``) con la referencia (``_features_historicas``): el modelo
  tiene que recibir los mismos floats, bit a bit, que se validaron.
- La **población** es la de antes (mismo filtro) y sin features.
- El **baseline no calcula features**, y el histórico se **carga una vez**.
- Los **resueltos** (sucesora ya adjudicada) se cuentan siempre y se excluyen
  solo con ``ML_RETENCION_EXCLUIR_RESUELTOS``.
- **Horizonte**: una sola constante para la ruta y el scoring, y una ventana
  que cubre la de la vista.
- La escritura va por ``guardar_retencion`` con el ``computed_at`` de la corrida.
"""

from __future__ import annotations

import inspect
import random
from datetime import date, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from dateutil.relativedelta import relativedelta

import services.ml.retencion_labels as rl
import services.ml.retencion_model as retencion_model_mod
import services.ml.scoring as scoring
from config import settings
from db.repositories.renovaciones import (
    HORIZONTE_RENOVACIONES_MAX_MESES,
    rango_vencimiento_sql,
)

_HOY = "2026-09-24"


# ---------------------------------------------------------------------------
# Datos sintéticos
# ---------------------------------------------------------------------------

# Dos grafías del mismo órgano (mismo normalizado), un órgano None y uno vacío.
_ORGANOS: tuple[str | None, ...] = (
    "Ayuntamiento de Madrid",
    "AYUNTAMIENTO DE MADRID",
    "Diputación de Toledo",
    "Consejería de Sanidad",
    None,
    "",
)
# CPV sin 4 dígitos (``"4500"`` sí vale: son 4), alfanumérico, con espacios y None.
_CPVS: tuple[str | None, ...] = (
    "72000000",
    "72200000",
    "48000000",
    "4500",
    "7",
    None,
    "ABCD1234",
    " 7220 ",
)
# ``empresa_id`` 0 es falsy: el HHI lo agrupa por nombre y la cuota por id.
_EMPRESAS: tuple[int | None, ...] = (None, 0, 1, 2, 3, 4)
# Adjudicaciones del mismo día que el ancla, con hora: ``"2026-09-24 09:00" <
# "2026-09-24"`` es falso, así que no cuentan como pasado.
_FECHAS_CON_HORA = (
    "2026-09-24 09:00",
    "2026-09-24",
    "2026-09-23T23:59:00",
    "2026-09-23 23:59",
    "2026-09-25 00:00:01",
)


def _dia(offset_dias: int, hoy: str = _HOY) -> str:
    return (date.fromisoformat(hoy) + timedelta(days=offset_dias)).isoformat()


def _hoy_real(offset: int = 0) -> str:
    """Para lo que ancla en el reloj (el batch, ``features_para_vencimientos``).

    Una fecha fija solo vale hasta que el calendario la deja fuera de la
    ventana (ver ``tests/test_ml_retencion.py::_dia``).
    """
    return (date.today() + timedelta(days=offset)).isoformat()


def _historico_raro(semilla: int, n: int = 700) -> list[dict[str, Any]]:
    """Histórico aleatorio (determinista) con todos los casos raros a la vez.

    Los ``licitacion_id`` se repiten (expedientes multi-lote), los importes
    llevan decimales arbitrarios —la suma de floats depende del orden, que es
    justo lo que la paridad exacta tiene que respetar— y hay importes ``None``
    y 0, fechas con hora y fines fuera y dentro de la ventana.
    """
    rnd = random.Random(semilla)
    inicio = date(2016, 1, 1)
    filas: list[dict[str, Any]] = []
    for i in range(n):
        dado = rnd.random()
        if dado < 0.08:
            fecha = rnd.choice(_FECHAS_CON_HORA)
        else:
            fecha = (inicio + timedelta(days=rnd.randrange(0, 3920))).isoformat()
            if dado < 0.2:
                fecha = f"{fecha} {rnd.randrange(24):02d}:{rnd.randrange(60):02d}"
        fin = _dia(rnd.randrange(-400, 2000)) if rnd.random() < 0.75 else None
        filas.append(
            {
                "licitacion_id": f"L{rnd.randrange(n // 2)}",
                "empresa_id": rnd.choice(_EMPRESAS),
                "nombre": rnd.choice(("Empresa A", "Empresa B", "UTE X", None)),
                "fecha_adjudicacion": fecha,
                "importe_adjudicado": rnd.choice(
                    (None, 0, 0.0, round(rnd.uniform(1_000, 2_000_000), 2), rnd.uniform(1, 1e6))
                ),
                "organo": rnd.choice(_ORGANOS),
                "cpv": rnd.choice(_CPVS),
                "ccaa": "Madrid",
                "importe": rnd.choice((None, 0, rnd.uniform(1_000, 3_000_000))),
                "titulo": f"Servicio {i}",
                "fecha_fin_efectiva": fin,
            }
        )
    # El orden de ``load_para_retencion``: cronológico por adjudicación.
    filas.sort(key=lambda f: str(f["fecha_adjudicacion"]))
    return filas


def _eventos(adjudicaciones: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    ids = sorted({str(a["licitacion_id"]) for a in adjudicaciones})
    return {lic: {"modificacion": i % 3, "prorroga": i % 2} for i, lic in enumerate(ids[::4])}


def _referencia(
    adjudicaciones: list[dict[str, Any]],
    eventos: dict[str, dict[str, int]],
    vencimiento: Any,
    hoy: str = _HOY,
) -> dict[str, float | None]:
    """Lo que calculaba ``features_para_vencimientos`` para una fila, por la referencia."""
    return rl._features_historicas(
        adjudicaciones,
        eventos,
        adj=vencimiento.adj,
        ancla=hoy,
        ancla_dt=rl._fecha_dt(hoy),
        organo_n=vencimiento.organo_n,
        cpv4=vencimiento.cpv4,
        empresa_id=vencimiento.empresa_id,
    )


def _poblacion_de_antes(
    adjudicaciones: list[dict[str, Any]], *, desde: str, hasta: str
) -> list[tuple[str, int, str, str | None, str, Any]]:
    """El bucle de ``features_para_vencimientos`` anterior a 2026-09, tal cual.

    Solo cambia de dónde salen los bordes: los recibe en vez de calcularlos,
    porque la ventana sí cambió a propósito (meses de calendario, ver
    :func:`test_la_ventana_usa_meses_de_calendario_como_la_vista`).
    """
    from services.dedupe import normalize_organo
    from services.ml.features import _cpv4

    filas = []
    vistos: set[str] = set()
    for adj in adjudicaciones:
        fin = adj.get("fecha_fin_efectiva")
        empresa_id = adj.get("empresa_id")
        organo_n = normalize_organo(adj.get("organo"))
        cpv4 = _cpv4(adj.get("cpv"))
        lic_id = str(adj["licitacion_id"])
        if (
            not fin
            or empresa_id is None
            or not organo_n
            or not cpv4
            or lic_id in vistos
            or not (desde <= str(fin)[:10] <= hasta)
        ):
            continue
        vistos.add(lic_id)
        filas.append(
            (
                lic_id,
                int(empresa_id),
                str(fin)[:10],
                cpv4,
                str(adj.get("organo")),
                adj.get("titulo"),
            )
        )
    return filas


# ---------------------------------------------------------------------------
# Paridad de las features de serving con la referencia
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("months_ahead", [12, 60])
@pytest.mark.parametrize("semilla", [1, 2, 3, 5, 8, 13])
def test_las_features_de_serving_son_exactamente_las_de_la_referencia(semilla, months_ahead):
    """Igualdad EXACTA, no ``approx``: el modelo recibe los floats que se validaron.

    ``sum()`` de floats es compensada desde Python 3.12, así que un índice que
    acumulara con ``+=`` o en otro orden daría otro último bit. Aquí se exige
    el mismo valor que ``_features_historicas(..., ancla=hoy)`` sin
    exclusiones, que es lo que el serving calculaba fila a fila.
    """
    adjudicaciones = _historico_raro(semilla)
    eventos = _eventos(adjudicaciones)
    desde, hasta = rl.ventana_vencimientos(months_ahead, hoy=_HOY)
    vencimientos = rl._vencimientos(adjudicaciones, desde=desde, hasta=hasta)

    filas = rl.vencimientos_con_features(
        adjudicaciones, months_ahead=months_ahead, hoy=_HOY, eventos=eventos
    )

    assert [f.licitacion_id for f in filas] == [v.licitacion_id for v in vencimientos]
    assert len(filas) >= 10, "el sintético tiene que poblar la ventana"
    for vencimiento, fila in zip(vencimientos, filas, strict=True):
        assert fila.features == _referencia(adjudicaciones, eventos, vencimiento), (
            fila.licitacion_id
        )
    # Que la igualdad no sea la de dos diccionarios llenos de None.
    assert any(f.features["antiguedad_relacion_meses"] is not None for f in filas)
    assert any(f.features["contratos_previos_organo"] for f in filas)
    assert any(f.features["cuota_segmento"] for f in filas)
    assert any(f.features["hhi_segmento"] is not None for f in filas)
    assert any(f.features["n_modificaciones"] for f in filas)


def _adj(
    lic_id: str,
    *,
    empresa_id: int | None,
    fecha_adj: str,
    organo: str | None = "Ayuntamiento de Madrid",
    cpv: str | None = "72000000",
    fin: str | None = None,
    adjudicado: float | None = 90_000.0,
    importe: float | None = 100_000.0,
    nombre: str | None = None,
) -> dict[str, Any]:
    return {
        "licitacion_id": lic_id,
        "empresa_id": empresa_id,
        "nombre": nombre if nombre is not None else f"Empresa {empresa_id}",
        "fecha_adjudicacion": fecha_adj,
        "importe_adjudicado": adjudicado,
        "organo": organo,
        "cpv": cpv,
        "ccaa": "Madrid",
        "importe": importe,
        "titulo": f"Servicio {lic_id}",
        "fecha_fin_efectiva": fin,
    }


def _casos_raros(hoy: str = _HOY) -> list[dict[str, Any]]:
    """Cada caso raro que pide la paridad, escrito a mano y con valor conocido."""
    filas = [
        # empresa 0 (falsy) con dos contratos previos en el mismo órgano.
        _adj("E0-A", empresa_id=0, fecha_adj="2019-03-01", nombre="Cero SL", adjudicado=10_000.5),
        _adj("E0-B", empresa_id=0, fecha_adj="2021-03-01", nombre="Cero SL", adjudicado=20_000.25),
        # empresa 1 en dos órganos: cada relación cuenta por separado.
        _adj("E1-MAD", empresa_id=1, fecha_adj="2018-01-01", adjudicado=33_333.33),
        _adj(
            "E1-TOL",
            empresa_id=1,
            fecha_adj="2018-06-01",
            organo="Diputación de Toledo",
            adjudicado=44_444.44,
        ),
        # Sin empresa del maestro: entra en el HHI por nombre, nunca en una relación.
        _adj("SIN-EMP", empresa_id=None, fecha_adj="2020-01-01", nombre="Libre SA"),
        # Órgano None, CPV sin 4 dígitos e importes None/0: fuera de lo que toca.
        _adj("SIN-ORG", empresa_id=1, fecha_adj="2020-02-01", organo=None),
        _adj("CPV-CORTO", empresa_id=1, fecha_adj="2020-03-01", cpv="7"),
        _adj("IMP-NONE", empresa_id=1, fecha_adj="2020-04-01", adjudicado=None),
        _adj("IMP-CERO", empresa_id=1, fecha_adj="2020-05-01", adjudicado=0),
        # El mismo día del ancla con hora (fuera) y la víspera con hora (dentro).
        _adj("MISMO-DIA", empresa_id=1, fecha_adj=f"{hoy} 09:00", adjudicado=1_000_000.0),
        _adj("VISPERA", empresa_id=1, fecha_adj=f"{_dia(-1, hoy)} 23:59", adjudicado=7_777.77),
        # Vencimientos dentro de la ventana, uno por relación.
        _adj("V-E0", empresa_id=0, fecha_adj="2023-01-01", fin=_dia(100, hoy), nombre="Cero SL"),
        _adj("V-E1-MAD", empresa_id=1, fecha_adj="2023-02-01", fin=_dia(200, hoy)),
        _adj(
            "V-E1-TOL",
            empresa_id=1,
            fecha_adj="2023-03-01",
            fin=_dia(300, hoy),
            organo="DIPUTACION DE TOLEDO",
        ),
        # Multi-lote: el primer lote (sin empresa) no pasa; el segundo sí.
        _adj("V-LOTES", empresa_id=None, fecha_adj="2023-04-01", fin=_dia(150, hoy)),
        _adj("V-LOTES", empresa_id=2, fecha_adj="2023-04-02", fin=_dia(150, hoy)),
        # Fuera de la población: sin empresa, sin órgano, CPV inválido, ya vencido.
        _adj("X-SIN-EMP", empresa_id=None, fecha_adj="2023-05-01", fin=_dia(50, hoy)),
        _adj("X-SIN-ORG", empresa_id=3, fecha_adj="2023-05-02", fin=_dia(50, hoy), organo=None),
        _adj("X-CPV", empresa_id=3, fecha_adj="2023-05-03", fin=_dia(50, hoy), cpv="ABCD1234"),
        _adj("X-VENCIDO", empresa_id=3, fecha_adj="2020-05-04", fin=_dia(-1, hoy)),
    ]
    filas.sort(key=lambda f: str(f["fecha_adjudicacion"]))
    return filas


def test_la_paridad_cubre_los_casos_raros_escritos_a_mano():
    adjudicaciones = _casos_raros()
    eventos = {"V-E0": {"modificacion": 2, "prorroga": 1}}
    desde, hasta = rl.ventana_vencimientos(12, hoy=_HOY)
    vencimientos = rl._vencimientos(adjudicaciones, desde=desde, hasta=hasta)

    filas = rl.vencimientos_con_features(adjudicaciones, months_ahead=12, hoy=_HOY, eventos=eventos)
    por_id = {f.licitacion_id: f for f in filas}

    assert set(por_id) == {"V-E0", "V-E1-MAD", "V-E1-TOL", "V-LOTES"}
    for vencimiento in vencimientos:
        assert por_id[vencimiento.licitacion_id].features == _referencia(
            adjudicaciones, eventos, vencimiento
        )

    # empresa_id 0 cuenta como empresa: E0-A, E0-B y el propio V-E0.
    assert por_id["V-E0"].features["contratos_previos_organo"] == 3.0
    assert por_id["V-E0"].features["n_modificaciones"] == 2.0
    # Madrid, empresa 1: E1-MAD, CPV-CORTO, IMP-NONE, IMP-CERO, VISPERA y el
    # propio V-E1-MAD. Ni SIN-ORG (órgano None) ni MISMO-DIA (adjudicado hoy con
    # hora: el orden dentro del día no es observable).
    assert por_id["V-E1-MAD"].features["contratos_previos_organo"] == 6.0
    # Toledo: la otra grafía normaliza igual; E1-TOL y el propio V-E1-TOL.
    assert por_id["V-E1-TOL"].features["contratos_previos_organo"] == 2.0
    # Multi-lote: la fila que pasa es la del lote con empresa.
    assert por_id["V-LOTES"].empresa_id == 2


def test_la_poblacion_es_la_de_antes_y_no_trae_features():
    for semilla in (1, 4, 9):
        adjudicaciones = _historico_raro(semilla)
        desde, hasta = rl.ventana_vencimientos(60, hoy=_HOY)

        filas = rl.vencimientos_proximos(adjudicaciones, months_ahead=60, hoy=_HOY)

        assert [
            (f.licitacion_id, f.empresa_id, f.fecha_fin, f.cpv4, f.organo, f.titulo_original)
            for f in filas
        ] == _poblacion_de_antes(adjudicaciones, desde=desde, hasta=hasta)
        assert filas, "el sintético tiene que poblar la ventana"
        assert all(f.features == {} for f in filas)
        assert all(f.label == -1 and f.sucesor_id == "" for f in filas)


def test_features_para_vencimientos_sigue_dando_lo_mismo():
    """Compatibilidad: el wrapper de siempre es la población con features.

    Ancla en el reloj (no admite ``hoy``), así que los casos se colocan
    respecto a la fecha real.
    """
    adjudicaciones = _casos_raros(_hoy_real())
    eventos = {"V-E0": {"modificacion": 1, "prorroga": 0}}
    with (
        patch.object(rl, "_cargar_adjudicaciones", return_value=adjudicaciones),
        patch.object(rl, "_eventos_por_licitacion", return_value=eventos),
    ):
        compat = rl.features_para_vencimientos(months_ahead=12)

    assert compat == rl.vencimientos_con_features(adjudicaciones, months_ahead=12, eventos=eventos)
    assert {f.licitacion_id for f in compat} == {"V-E0", "V-E1-MAD", "V-E1-TOL", "V-LOTES"}


def test_sin_vencimientos_no_se_cargan_los_eventos():
    with patch.object(rl, "_eventos_por_licitacion", side_effect=AssertionError("no")):
        assert rl.vencimientos_con_features([], months_ahead=12, hoy=_HOY) == []


# ---------------------------------------------------------------------------
# Ventana y horizonte
# ---------------------------------------------------------------------------


def test_la_sql_de_la_vista_suma_meses_de_calendario():
    """El espejo de Python (``ventana_vencimientos``) asume esta SQL.

    Si ``rango_vencimiento_sql`` deja de sumar ``N * INTERVAL '1 month'`` a
    ``CURRENT_DATE``, la ventana del scoring tiene que cambiar con ella.
    """
    sql = rango_vencimiento_sql()
    assert "CURRENT_DATE" in sql
    assert "INTERVAL '1 month'" in sql


@pytest.mark.parametrize("meses", [1, 6, 12, 25, HORIZONTE_RENOVACIONES_MAX_MESES])
def test_la_ventana_usa_meses_de_calendario_como_la_vista(meses):
    """Cada día de un año bisiesto, contra ``relativedelta`` (misma regla que Postgres).

    ``date + N meses`` recorta al último día del mes cuando el día no existe,
    igual que ``CURRENT_DATE + N * INTERVAL '1 month'``: el borde de la vista
    tiene que quedar dentro de la ventana, y el margen sobre él ser justo
    ``MARGEN_VENTANA_DIAS``.
    """
    for offset in range(366):
        hoy = date(2028, 1, 1) + timedelta(days=offset)
        desde, hasta = rl.ventana_vencimientos(meses, hoy=hoy.isoformat())
        borde_vista = hoy + relativedelta(months=meses)

        assert desde == hoy.isoformat()
        assert date.fromisoformat(hasta) - borde_vista == timedelta(days=rl.MARGEN_VENTANA_DIAS)


def test_el_ultimo_dia_del_ano_de_la_vista_ya_se_puntua():
    """Regresión: con meses de 30 días, 12 meses eran 360 días.

    Un contrato que vence el día anterior al aniversario salía en la vista de
    12 meses con ``riesgo_cambio`` NULL.
    """
    fin = (date.fromisoformat(_HOY) + relativedelta(months=12) - timedelta(days=1)).isoformat()
    antes = (date.fromisoformat(_HOY) + timedelta(days=360)).isoformat()
    assert fin > antes  # el caso que se perdía
    adjudicaciones = [_adj("ANIVERSARIO", empresa_id=1, fecha_adj="2024-01-01", fin=fin)]

    filas = rl.vencimientos_proximos(adjudicaciones, months_ahead=12, hoy=_HOY)

    assert [f.licitacion_id for f in filas] == ["ANIVERSARIO"]


def test_la_ruta_y_el_scoring_comparten_el_horizonte_maximo():
    """Una sola constante: si la ruta admite más meses de los que se puntúan,
    lo de más allá sale sin riesgo (NULL) y con score 0 en el orden «score».
    Pasó hasta 2026-09: el batch puntuaba 12 meses y la ruta admitía 60."""
    from api.routes.competitive import get_renovaciones, get_renovaciones_resumen

    for ruta in (get_renovaciones, get_renovaciones_resumen):
        consulta = inspect.signature(ruta).parameters["months"].default
        topes = [m.le for m in consulta.metadata if hasattr(m, "le")]
        assert topes == [HORIZONTE_RENOVACIONES_MAX_MESES], ruta.__name__

    defecto = inspect.signature(scoring.score_predicciones_retencion).parameters["months_ahead"]
    assert defecto.default == HORIZONTE_RENOVACIONES_MAX_MESES


# ---------------------------------------------------------------------------
# El batch: una carga, sin features en baseline, resueltos y escritura
# ---------------------------------------------------------------------------

_ORGANO_FIEL = "Ayuntamiento de Fidelia"
_ORGANO_ROTATORIO = "Diputacion de Rotacion"


def _historico_batch() -> list[dict[str, Any]]:
    """Pares pasados en dos segmentos y tres vencimientos próximos.

    ``V-RESUELTO`` vence dentro de dos meses y su segmento ya se re-licitó hace
    diez días (``V-RESUELTO-SIG``, otra empresa): la heurística del etiquetado
    lo empareja, así que está resuelto. ``V-FIEL`` y ``V-LEJANO`` no.
    """
    filas: list[dict[str, Any]] = []
    for i in range(5):
        adj, fin, sig = f"{2000 + 5 * i}-01-01", f"{2002 + 5 * i}-01-01", f"{2002 + 5 * i}-04-01"
        filas += [
            _adj(f"F{i}", empresa_id=7, fecha_adj=adj, fin=fin, organo=_ORGANO_FIEL),
            _adj(f"F{i}-SIG", empresa_id=7, fecha_adj=sig, organo=_ORGANO_FIEL),
            _adj(f"R{i}", empresa_id=7, fecha_adj=adj, fin=fin, organo=_ORGANO_ROTATORIO),
            _adj(f"R{i}-SIG", empresa_id=99, fecha_adj=sig, organo=_ORGANO_ROTATORIO),
        ]
    filas += [
        _adj(
            "V-FIEL",
            empresa_id=7,
            fecha_adj=_hoy_real(-700),
            fin=_hoy_real(90),
            organo=_ORGANO_FIEL,
        ),
        _adj(
            "V-RESUELTO",
            empresa_id=7,
            fecha_adj=_hoy_real(-700),
            fin=_hoy_real(60),
            organo=_ORGANO_ROTATORIO,
        ),
        _adj("V-RESUELTO-SIG", empresa_id=99, fecha_adj=_hoy_real(-10), organo=_ORGANO_ROTATORIO),
        # Más allá del año: antes nunca se puntuaba.
        _adj(
            "V-LEJANO",
            empresa_id=7,
            fecha_adj=_hoy_real(-400),
            fin=_hoy_real(365 * 3),
            organo=_ORGANO_FIEL,
        ),
    ]
    filas.sort(key=lambda f: str(f["fecha_adjudicacion"]))
    return filas


class _RepoRetencion:
    """``PrediccionesRepository`` de mentira que registra ``guardar_retencion``."""

    def __init__(self, purgadas: int = 0) -> None:
        self.llamadas: list[tuple[list[tuple[Any, ...]], str]] = []
        self.purgadas = purgadas

    def guardar_retencion(self, filas, *, computed_at):
        self.llamadas.append((list(filas), computed_at))
        return {"escritas": len(filas), "purgadas": self.purgadas}


class _ModeloFalso:
    """``RetencionModel`` de mentira: probabilidad fija, y registra lo que recibe."""

    def __init__(self, prob: float) -> None:
        self.prob = prob
        self.recibidas: list[Any] = []

    def predict_proba_retencion(self, pares):
        self.recibidas = list(pares)
        return [self.prob] * len(pares)


def _correr_batch(
    *,
    activa: dict[str, Any] | None = None,
    repo: _RepoRetencion | None = None,
    excluir_resueltos: bool = False,
    extra: tuple[Any, ...] = (),
) -> tuple[dict[str, Any], _RepoRetencion, Any]:
    """Una corrida del batch sobre :func:`_historico_batch`, sin BD."""
    repo = repo or _RepoRetencion()
    with (
        patch.object(settings, "ML_RETENCION_EXCLUIR_RESUELTOS", excluir_resueltos),
        patch.object(rl, "_cargar_adjudicaciones", return_value=_historico_batch()) as carga,
        patch.object(rl, "_eventos_por_licitacion", return_value={}),
        patch("db.model_registry.get_active", return_value=activa),
        patch(
            "shared.model_artifacts.resolve_active_artifact",
            return_value="retencion_model.pkl" if activa else None,
        ),
        patch.object(scoring, "PrediccionesRepository", return_value=repo),
    ):
        for parche in extra:
            parche.start()
        try:
            resultado = scoring.score_predicciones_retencion()
        finally:
            for parche in extra:
                parche.stop()
    return resultado, repo, carga


def test_el_baseline_no_calcula_features():
    """Si el baseline tocara cualquier pieza de las features, esto revienta."""
    prohibido = AssertionError("el baseline no debe calcular features")
    resultado, repo, _ = _correr_batch(
        extra=(
            patch.object(rl, "_features_historicas", side_effect=prohibido),
            patch.object(rl, "_IndiceServing", side_effect=prohibido),
            patch.object(rl, "vencimientos_con_features", side_effect=prohibido),
            patch.object(rl, "_eventos_por_licitacion", side_effect=prohibido),
        )
    )

    assert resultado["status"] == "baseline"
    assert resultado["serving"] == "baseline"
    assert resultado["model_version"] == "baseline"
    escritas = {fila[0] for fila in repo.llamadas[0][0]}
    assert escritas == {"V-FIEL", "V-RESUELTO", "V-LEJANO"}
    # En la tabla el baseline va con model_version NULL (lo que distingue la UI).
    assert all(fila[4] is None for fila in repo.llamadas[0][0])


def test_el_historico_se_carga_una_sola_vez_con_y_sin_modelo():
    _, _, carga = _correr_batch()
    assert carga.call_count == 1

    modelo = _ModeloFalso(0.8)
    _, _, carga = _correr_batch(
        activa={"version": 7},
        extra=(patch.object(retencion_model_mod.RetencionModel, "load", return_value=modelo),),
    )
    assert carga.call_count == 1


def test_con_modelo_activo_se_sirve_el_modelo_con_sus_features():
    modelo = _ModeloFalso(0.8)
    resultado, repo, _ = _correr_batch(
        activa={"version": 7},
        extra=(patch.object(retencion_model_mod.RetencionModel, "load", return_value=modelo),),
    )

    assert resultado["status"] == "ok"
    assert resultado["serving"] == "modelo"
    assert resultado["model_version"] == 7
    assert resultado["degradado"] is None
    assert resultado["tasa_global"] is None
    # El modelo recibe las features calculadas, con todas sus columnas.
    assert modelo.recibidas
    assert all(set(p.features) == set(rl.FEATURE_COLUMNS_RETENCION) for p in modelo.recibidas)
    filas, _ = repo.llamadas[0]
    assert {(f[0], f[2], f[3], f[4]) for f in filas} == {
        (lic, 0.8, 0.2, 7) for lic in ("V-FIEL", "V-RESUELTO", "V-LEJANO")
    }


def test_modelo_activo_con_artefacto_irresoluble_degrada_al_baseline():
    repo = _RepoRetencion()
    with (
        patch.object(rl, "_cargar_adjudicaciones", return_value=_historico_batch()),
        patch("db.model_registry.get_active", return_value={"version": 7}),
        patch("shared.model_artifacts.resolve_active_artifact", return_value=None),
        patch.object(scoring, "PrediccionesRepository", return_value=repo),
    ):
        resultado = scoring.score_predicciones_retencion()

    assert resultado["status"] == "baseline"
    assert resultado["degradado"] == "artefacto_irresoluble"


def test_guardar_retencion_recibe_el_computed_at_de_la_corrida():
    """Todas las filas y la purga comparten el ``computed_at`` de la corrida.

    ``guardar_retencion`` borra lo anterior a ese instante: si las filas
    llevaran otro, la purga se llevaría por delante las recién escritas o
    dejaría vivas las viejas (3.443 filas para 3.003 el 2026-09-24).
    """
    resultado, repo, _ = _correr_batch(repo=_RepoRetencion(purgadas=440))

    [(filas, computed_at)] = repo.llamadas
    assert computed_at == resultado["computed_at"]
    assert {fila[5] for fila in filas} == {computed_at}
    assert resultado["purgadas"] == 440
    assert resultado["filas"] == len(filas) == 3


def test_los_resueltos_se_cuentan_pero_no_se_excluyen_por_defecto():
    from config.settings import Settings

    assert Settings.model_fields["ML_RETENCION_EXCLUIR_RESUELTOS"].default is False

    resultado, repo, _ = _correr_batch(excluir_resueltos=False)

    assert resultado["resueltos_detectados"] == 1
    assert resultado["excluidos"] == 0
    assert "V-RESUELTO" in {fila[0] for fila in repo.llamadas[0][0]}


def test_con_el_flag_los_resueltos_se_excluyen():
    resultado, repo, _ = _correr_batch(excluir_resueltos=True)

    assert resultado["resueltos_detectados"] == 1
    assert resultado["excluidos"] == 1
    assert resultado["filas"] == 2
    assert {fila[0] for fila in repo.llamadas[0][0]} == {"V-FIEL", "V-LEJANO"}


def test_el_resultado_declara_horizonte_y_ventana():
    resultado, _, _ = _correr_batch()

    assert resultado["horizonte_meses"] == HORIZONTE_RENOVACIONES_MAX_MESES
    assert resultado["ventana"] == dict(
        zip(
            ("desde", "hasta"),
            rl.ventana_vencimientos(HORIZONTE_RENOVACIONES_MAX_MESES),
            strict=True,
        )
    )


def test_sin_vencimientos_no_escribe_nada():
    repo = _RepoRetencion()
    with (
        patch.object(rl, "_cargar_adjudicaciones", return_value=[]),
        patch("db.model_registry.get_active", return_value=None),
        patch("shared.model_artifacts.resolve_active_artifact", return_value=None),
        patch.object(scoring, "PrediccionesRepository", return_value=repo),
    ):
        resultado = scoring.score_predicciones_retencion()

    assert resultado["status"] == "sin_vencimientos"
    assert resultado["filas"] == 0
    assert repo.llamadas == []
