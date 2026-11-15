"""Entrenamiento de retención sin coste cuadrático, y la muestra de resueltos.

``construir_pares`` llamaba a ``_features_historicas`` por par, y cada llamada
recorría el histórico entero dos veces; ``_emparejar`` recorría el segmento
entero por vencimiento. Los dos pasan a índices con ``bisect``. Lo que fija
este fichero, sin Postgres:

- **Paridad exacta** con las implementaciones anteriores, copiadas aquí tal
  cual como referencia: los mismos emparejamientos (misma sucesora, también en
  los empates de distancia) y las mismas features bit a bit, sobre históricos
  aleatorios con semilla fija, también cargados fuera de orden.
- ``muestra_resueltos`` devuelve exactamente los vencimientos de la población
  de scoring que ``con_sucesora`` da por resueltos.
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

import pytest

import services.ml.retencion_labels as rl
from services.dedupe import normalize_organo
from shared.cpv import cpv4 as _cpv4

# ---------------------------------------------------------------------------
# Las implementaciones anteriores, copiadas como referencia
# ---------------------------------------------------------------------------


def _features_viejo(
    adjudicaciones: list[dict[str, Any]],
    eventos: dict[str, dict[str, int]],
    *,
    adj: dict[str, Any],
    ancla: str,
    ancla_dt: datetime,
    organo_n: str,
    cpv4: str,
    empresa_id: int,
    excluir_licitaciones: frozenset[str] = frozenset(),
) -> dict[str, float | None]:
    """``_features_historicas`` anterior al índice, tal cual."""
    previos = [
        c
        for c in adjudicaciones
        if c.get("empresa_id") == empresa_id
        and normalize_organo(c.get("organo")) == organo_n
        and str(c["fecha_adjudicacion"]) < ancla
        and str(c["licitacion_id"]) not in excluir_licitaciones
    ]
    segmento_previo = [
        c
        for c in adjudicaciones
        if _cpv4(c.get("cpv")) == cpv4
        and str(c["fecha_adjudicacion"]) < ancla
        and str(c["licitacion_id"]) not in excluir_licitaciones
        and (c.get("importe_adjudicado") or 0) > 0
    ]
    total_seg = sum(float(c["importe_adjudicado"]) for c in segmento_previo)
    importe_empresa = sum(
        float(c["importe_adjudicado"]) for c in segmento_previo if c.get("empresa_id") == empresa_id
    )
    por_empresa: dict[Any, float] = defaultdict(float)
    for c in segmento_previo:
        por_empresa[c.get("empresa_id") or c.get("nombre")] += float(c["importe_adjudicado"])
    hhi = sum((v * 100.0 / total_seg) ** 2 for v in por_empresa.values()) if total_seg > 0 else None

    antiguedad = (
        (ancla_dt - rl._fecha_dt(str(previos[0]["fecha_adjudicacion"]))).days / 30.0
        if previos
        else None
    )
    return {
        "antiguedad_relacion_meses": antiguedad,
        "contratos_previos_organo": float(len(previos)),
        "cuota_segmento": importe_empresa / total_seg if total_seg > 0 else None,
        "hhi_segmento": hhi,
        **rl._features_del_contrato(adj, eventos),
    }


def _emparejar_viejo(
    adjudicaciones: list[dict[str, Any]],
    *,
    ventana_meses: int = rl.VENTANA_MESES,
    anticipacion_meses: int = rl.VENTANA_ANTICIPACION_MESES,
) -> list[rl._Emparejamiento]:
    """``_emparejar`` anterior al índice, tal cual."""
    delta_post = timedelta(days=ventana_meses * 30)
    delta_pre = timedelta(days=anticipacion_meses * 30)
    corte = rl._corte_de_datos(adjudicaciones)

    por_segmento: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for adj in adjudicaciones:
        organo_n = normalize_organo(adj.get("organo"))
        cpv4 = _cpv4(adj.get("cpv"))
        if organo_n and cpv4:
            por_segmento[(organo_n, cpv4)].append(adj)

    emparejados: list[rl._Emparejamiento] = []
    vistos: set[str] = set()
    for adj in adjudicaciones:
        fin = adj.get("fecha_fin_efectiva")
        fin_dt = rl._fecha_opt(fin)
        empresa_id = adj.get("empresa_id")
        organo_n = normalize_organo(adj.get("organo"))
        cpv4 = _cpv4(adj.get("cpv"))
        if fin_dt is None or empresa_id is None or not organo_n or not cpv4:
            continue
        lic_id = str(adj["licitacion_id"])
        if lic_id in vistos:
            continue

        candidatas = [
            c
            for c in por_segmento[(organo_n, cpv4)]
            if c["licitacion_id"] != adj["licitacion_id"]
            and str(c["fecha_adjudicacion"]) > str(adj["fecha_adjudicacion"])
            and -delta_pre <= rl._fecha_dt(str(c["fecha_adjudicacion"])) - fin_dt <= delta_post
        ]
        if not candidatas:
            continue
        sucesora = min(
            candidatas, key=lambda c: abs(rl._fecha_dt(str(c["fecha_adjudicacion"])) - fin_dt)
        )
        vistos.add(lic_id)

        ancla_dt = min(fin_dt, rl._fecha_dt(str(sucesora["fecha_adjudicacion"])))
        emparejados.append(
            rl._Emparejamiento(
                adj=adj,
                sucesora=sucesora,
                licitacion_id=lic_id,
                sucesor_id=str(sucesora["licitacion_id"]),
                empresa_id=int(empresa_id),
                organo_n=organo_n,
                cpv4=cpv4,
                fin=str(fin),
                ancla=ancla_dt.strftime("%Y-%m-%d"),
                ancla_dt=ancla_dt,
                label=1 if sucesora.get("empresa_id") == empresa_id else 0,
                ventana_cerrada=fin_dt + delta_post <= corte,
            )
        )
    return emparejados


# ---------------------------------------------------------------------------
# Datos sintéticos
# ---------------------------------------------------------------------------

# Dos grafías del mismo órgano, uno None y uno vacío.
_ORGANOS = ("Ayuntamiento de Madrid", "AYUNTAMIENTO DE MADRID", "Diputación de Toledo", None, "")
# Segmentos densos (para que haya sucesoras y empates) y CPV inválidos.
_CPVS = ("72000000", "72200000", "48000000", "4500", "7", None)
# ``empresa_id`` 0 es falsy: el HHI lo agrupa por nombre y la cuota por id.
_EMPRESAS = (None, 0, 1, 2, 3)
# Fines que ``_fecha_opt`` descarta, y un centinela que desbordaría la ventana.
_FINES_RAROS = ("no-fecha", "0019-12-10", "9999-12-31")


def _historico(semilla: int, n: int = 600, *, ordenado: bool = True) -> list[dict[str, Any]]:
    """Histórico aleatorio (determinista) con los casos raros a la vez.

    Las fechas caen en una rejilla semanal y los fines a semanas enteras de la
    adjudicación: así hay candidatas a la misma distancia del fin, que es donde
    el desempate por orden de carga tiene que coincidir con el de ``min()``.
    Los ``licitacion_id`` se repiten (multi-lote) y los importes llevan
    decimales arbitrarios, ``None`` y 0.
    """
    rnd = random.Random(semilla)
    inicio = date(2016, 1, 4)
    filas: list[dict[str, Any]] = []
    for i in range(n):
        dia = inicio + timedelta(weeks=rnd.randrange(0, 520))
        fecha = dia.isoformat()
        if rnd.random() < 0.15:
            fecha = f"{fecha} {rnd.randrange(24):02d}:{rnd.randrange(60):02d}"
        dado = rnd.random()
        if dado < 0.03:
            fin: str | None = rnd.choice(_FINES_RAROS)
        elif dado < 0.85:
            fin = (dia + timedelta(weeks=rnd.randrange(-4, 220))).isoformat()
        else:
            fin = None
        filas.append(
            {
                "licitacion_id": f"L{rnd.randrange(n * 2 // 3)}",
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
    if ordenado:
        # El orden de ``load_para_retencion``: cronológico por adjudicación.
        filas.sort(key=lambda f: str(f["fecha_adjudicacion"]))
    else:
        # Una carga que no sale en el orden de texto de Python (otra collation).
        rnd.shuffle(filas)
    return filas


def _eventos(adjudicaciones: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    ids = sorted({str(a["licitacion_id"]) for a in adjudicaciones})
    return {lic: {"modificacion": i % 3, "prorroga": i % 2} for i, lic in enumerate(ids[::4])}


_SEMILLAS = [1, 2, 3, 5, 8]


# ---------------------------------------------------------------------------
# Paridad del emparejamiento
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ordenado", [True, False], ids=["en-orden", "desordenado"])
@pytest.mark.parametrize("semilla", _SEMILLAS)
def test_el_emparejamiento_por_ventana_es_el_de_antes(semilla, ordenado):
    adjudicaciones = _historico(semilla, ordenado=ordenado)

    nuevo = rl._emparejar(adjudicaciones)
    viejo = _emparejar_viejo(adjudicaciones)

    assert nuevo == viejo
    # La misma fila, no otra con el mismo contenido.
    assert all(
        a.sucesora is b.sucesora and a.adj is b.adj for a, b in zip(nuevo, viejo, strict=True)
    )
    assert len(nuevo) >= 30, "el sintético tiene que emparejar"
    assert {e.label for e in nuevo} == {0, 1}
    assert {e.ventana_cerrada for e in nuevo} == {True, False}


def test_los_empates_de_distancia_se_resuelven_como_min():
    """Dos candidatas a la misma distancia del fin: gana la primera de la carga."""
    adjudicaciones = [
        _fila("ORIG", empresa_id=1, fecha="2020-01-06", fin="2022-01-03"),
        _fila("ANTES", empresa_id=2, fecha="2021-12-27"),  # 7 días antes del fin
        _fila("DESPUES", empresa_id=1, fecha="2022-01-10"),  # 7 días después
    ]
    for orden in (adjudicaciones, [adjudicaciones[0], adjudicaciones[2], adjudicaciones[1]]):
        nuevo = rl._emparejar(orden)
        assert nuevo == _emparejar_viejo(orden)
        assert nuevo[0].sucesor_id == str(orden[1]["licitacion_id"])


@pytest.mark.parametrize(("ventana", "anticipacion"), [(6, 0), (24, 12)])
def test_la_paridad_vale_con_otras_ventanas(ventana, anticipacion):
    adjudicaciones = _historico(13)
    assert rl._emparejar(
        adjudicaciones, ventana_meses=ventana, anticipacion_meses=anticipacion
    ) == _emparejar_viejo(adjudicaciones, ventana_meses=ventana, anticipacion_meses=anticipacion)


# ---------------------------------------------------------------------------
# Paridad de las features de entrenamiento
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ordenado", [True, False], ids=["en-orden", "desordenado"])
@pytest.mark.parametrize("semilla", _SEMILLAS)
def test_las_features_del_indice_son_exactamente_las_de_antes(semilla, ordenado):
    """Igualdad EXACTA, no ``approx``: el modelo entrena con los mismos floats."""
    adjudicaciones = _historico(semilla, ordenado=ordenado)
    eventos = _eventos(adjudicaciones)
    indice = rl._IndiceHistorico(adjudicaciones)
    emparejados = _emparejar_viejo(adjudicaciones)
    assert emparejados

    vistos: list[dict[str, float | None]] = []
    for e in emparejados:
        for excluir in (frozenset({e.sucesor_id}), frozenset()):
            argumentos: dict[str, Any] = {
                "adj": e.adj,
                "ancla": e.ancla,
                "ancla_dt": e.ancla_dt,
                "organo_n": e.organo_n,
                "cpv4": e.cpv4,
                "empresa_id": e.empresa_id,
                "excluir_licitaciones": excluir,
            }
            nuevo = indice.features(eventos, **argumentos)
            assert nuevo == _features_viejo(adjudicaciones, eventos, **argumentos), e.licitacion_id
            vistos.append(nuevo)

    # Que la igualdad no sea la de dos diccionarios llenos de None.
    assert any(f["antiguedad_relacion_meses"] is not None for f in vistos)
    assert any(f["contratos_previos_organo"] for f in vistos)
    assert any(f["cuota_segmento"] for f in vistos)
    assert any(f["hhi_segmento"] is not None for f in vistos)


@pytest.mark.parametrize("semilla", _SEMILLAS)
def test_la_paridad_vale_con_anclas_que_empatan_con_fechas_del_historico(semilla):
    """Anclas que son una fecha del histórico, con y sin hora, y fuera de rango."""
    adjudicaciones = _historico(semilla)
    eventos = _eventos(adjudicaciones)
    indice = rl._IndiceHistorico(adjudicaciones)
    rnd = random.Random(semilla)
    anclas = [str(a["fecha_adjudicacion"]) for a in rnd.sample(adjudicaciones, 40)]
    anclas += [a[:10] for a in anclas] + ["1990-01-01", "2100-01-01"]

    for ancla in anclas:
        adj = rnd.choice(adjudicaciones)
        argumentos: dict[str, Any] = {
            "adj": adj,
            "ancla": ancla,
            "ancla_dt": rl._fecha_dt(ancla),
            "organo_n": normalize_organo("Ayuntamiento de Madrid"),
            "cpv4": rnd.choice(("7200", "7220", "4800", "4500", "9999")),
            "empresa_id": rnd.choice((0, 1, 2, 3)),
            "excluir_licitaciones": frozenset({str(adj["licitacion_id"])}),
        }
        assert indice.features(eventos, **argumentos) == _features_viejo(
            adjudicaciones, eventos, **argumentos
        )


def test_construir_pares_usa_el_indice_y_da_las_features_de_antes(monkeypatch):
    adjudicaciones = _historico(21)
    eventos = _eventos(adjudicaciones)
    monkeypatch.setattr(rl, "_cargar_adjudicaciones", lambda: adjudicaciones)
    monkeypatch.setattr(rl, "_eventos_por_licitacion", lambda: eventos)

    def prohibido(*_a: Any, **_k: Any) -> None:
        raise AssertionError("construir_pares no debe recorrer el histórico por par")

    monkeypatch.setattr(rl, "_features_historicas", prohibido)

    pares = rl.construir_pares()

    esperados = {
        e.licitacion_id: _features_viejo(
            adjudicaciones,
            eventos,
            adj=e.adj,
            ancla=e.ancla,
            ancla_dt=e.ancla_dt,
            organo_n=e.organo_n,
            cpv4=e.cpv4,
            empresa_id=e.empresa_id,
            excluir_licitaciones=frozenset({e.sucesor_id}),
        )
        for e in _emparejar_viejo(adjudicaciones)
        if e.ventana_cerrada
    }
    assert pares
    assert {p.licitacion_id: p.features for p in pares} == esperados


# ---------------------------------------------------------------------------
# Muestra de resueltos
# ---------------------------------------------------------------------------

_HOY = "2024-06-03"


def _fila(
    lic_id: str,
    *,
    empresa_id: int | None,
    fecha: str,
    fin: str | None = None,
    organo: str = "Ayuntamiento de Madrid",
    cpv: str = "72000000",
) -> dict[str, Any]:
    return {
        "licitacion_id": lic_id,
        "empresa_id": empresa_id,
        "nombre": f"Empresa {empresa_id}",
        "fecha_adjudicacion": fecha,
        "importe_adjudicado": 90_000.0,
        "organo": organo,
        "cpv": cpv,
        "ccaa": "Madrid",
        "importe": 100_000.0,
        "titulo": f"Servicio {lic_id}",
        "fecha_fin_efectiva": fin,
    }


def _dia(offset: int) -> str:
    return (date.fromisoformat(_HOY) + timedelta(days=offset)).isoformat()


def _resueltos_de_scoring(adjudicaciones: list[dict[str, Any]], months_ahead: int) -> set[str]:
    """Lo que ``_separar_resueltos`` cuenta: ``con_sucesora`` ∩ población."""
    poblacion = {
        p.licitacion_id
        for p in rl.vencimientos_proximos(adjudicaciones, months_ahead=months_ahead, hoy=_HOY)
    }
    return set(rl.etiquetas_por_segmento(adjudicaciones).con_sucesora) & poblacion


def test_muestra_resueltos_saca_los_que_tienen_sucesora_y_no_los_demas(monkeypatch):
    adjudicaciones = sorted(
        [
            # Vence en 100 días y el órgano ya lo re-licitó hace un mes.
            _fila("CON-SUC", empresa_id=1, fecha="2020-01-01", fin=_dia(100)),
            _fila("SUCESORA", empresa_id=2, fecha=_dia(-30)),
            # Vence en 200 días y nadie lo ha re-licitado: su segmento está solo.
            _fila("SIN-SUC", empresa_id=2, fecha="2020-02-01", fin=_dia(200), cpv="48000000"),
            # Con sucesora, pero venció hace años: no está en la población.
            _fila("VENCIDO", empresa_id=3, fecha="2015-01-01", fin="2017-01-01", cpv="45000000"),
            _fila("SUC-VENCIDO", empresa_id=3, fecha="2017-02-01", cpv="45000000"),
        ],
        key=lambda f: str(f["fecha_adjudicacion"]),
    )
    monkeypatch.setattr(rl, "_cargar_adjudicaciones", lambda: adjudicaciones)

    muestra = rl.muestra_resueltos(50, months_ahead=12, hoy=_HOY)

    assert [m["original"] for m in muestra] == ["CON-SUC"]
    assert muestra[0]["sucesor"] == "SUCESORA"
    assert muestra[0]["label"] == 0
    # La ventana aún no ha terminado: el scoring lo cuenta igual y aquí sale.
    assert muestra[0]["ventana_cerrada"] is False
    assert {m["original"] for m in muestra} == _resueltos_de_scoring(adjudicaciones, 12)


@pytest.mark.parametrize("semilla", [1, 2, 3])
def test_muestra_resueltos_coincide_con_los_resueltos_del_scoring(monkeypatch, semilla):
    adjudicaciones = _historico(semilla)
    monkeypatch.setattr(rl, "_cargar_adjudicaciones", lambda: adjudicaciones)

    muestra = rl.muestra_resueltos(10_000, months_ahead=60, hoy=_HOY)

    originales = [m["original"] for m in muestra]
    assert len(originales) == len(set(originales))
    assert set(originales) == _resueltos_de_scoring(adjudicaciones, 60)
    assert originales, "el sintético tiene que tener resueltos"


def test_muestra_resueltos_es_determinista_y_respeta_n(monkeypatch):
    adjudicaciones = _historico(5)
    monkeypatch.setattr(rl, "_cargar_adjudicaciones", lambda: adjudicaciones)

    primera = rl.muestra_resueltos(3, months_ahead=60, hoy=_HOY)

    assert len(primera) == 3
    assert primera == rl.muestra_resueltos(3, months_ahead=60, hoy=_HOY)
