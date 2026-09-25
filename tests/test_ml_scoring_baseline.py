"""Baseline de retención del batch de scoring (``services/ml/scoring.py``).

Sin versión activa del modelo de retención, ``score_predicciones_retencion``
escribe ``predicciones_retencion`` con un baseline histórico por segmento
``(órgano normalizado, CPV-4)``. Ese baseline tenía dos averías que se
tapaban entre sí:

1. la tasa no medía retención sino vinculación al maestro de empresas
   (``empresa_id IS NOT NULL``), que vale ≈1 en cuanto la resolución de
   entidades funciona;
2. el serving leía ``f.cpv`` y ``f.organo_contratacion`` de un
   ``ParRetencion``, que no tiene esos atributos: el lookup por segmento nunca
   se aplicaba y todas las filas recibían la media global.

Resultado: un riesgo de cambio constante y falsamente bajo, materializado cada
noche. Estos tests fijan lo contrario — que la tasa mide retención y que dos
segmentos con retención distinta salen con probabilidades distintas.

Desde 2026-09 el fallback tampoco es un corte: los segmentos con al menos
``MIN_OBS_SEGMENTO`` pares servían su tasa cruda y el resto una media NO
ponderada de las tasas publicadas. Ahora cada segmento se encoge hacia su
CPV-4 y este hacia la tasa global agregada (shrinkage empirical-Bayes,
``_baseline_retencion``), y la búsqueda cae de segmento a CPV-4 y a global.

Sin Postgres: el histórico se inyecta en ``retencion_labels`` y la escritura se
captura con un repositorio de mentira.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

import services.ml.retencion_labels as rl
import services.ml.scoring as scoring
from config import settings
from services.dedupe import normalize_organo

_CPV = "72000000"
_CPV4 = "7200"
_INCUMBENTE = 7
_RIVAL = 99
_K = scoring._SHRINKAGE_K_RETENCION

_ORGANO_FIEL = "Ayuntamiento de Fidelia"
_ORGANO_ROTATORIO = "Diputacion de Rotacion"
_ORGANO_OBRAS = "Consejeria de Obras"


def _adj(
    lic_id: str,
    *,
    empresa_id: int,
    fecha_adj: str,
    organo: str,
    fecha_fin: str | None = None,
    cpv: str = _CPV,
) -> dict[str, Any]:
    return {
        "licitacion_id": lic_id,
        "empresa_id": empresa_id,
        "nombre": f"Empresa {empresa_id}",
        "fecha_adjudicacion": fecha_adj,
        "importe_adjudicado": 90_000.0,
        "organo": organo,
        "cpv": cpv,
        "ccaa": "Madrid",
        "importe": 100_000.0,
        "titulo": f"Servicio {lic_id}",
        "fecha_fin_efectiva": fecha_fin,
    }


def _pares(
    prefijo: str, organo: str, *, retenidos: int, n: int = 5, cpv: str = _CPV
) -> list[dict[str, Any]]:
    """``n`` pares vencimiento→sucesora del segmento; los ``retenidos`` primeros, retenidos.

    Los pares se separan cinco años entre sí para que la sucesora más cercana a
    cada vencimiento sea siempre la suya y no el contrato del par siguiente.
    """
    filas: list[dict[str, Any]] = []
    for i in range(n):
        adj = f"{2000 + 5 * i}-01-01"
        fin = f"{2002 + 5 * i}-01-01"
        sig = f"{2002 + 5 * i}-04-01"
        ganador = _INCUMBENTE if i < retenidos else _RIVAL
        filas.append(
            _adj(
                f"{prefijo}{i}",
                empresa_id=_INCUMBENTE,
                fecha_adj=adj,
                fecha_fin=fin,
                organo=organo,
                cpv=cpv,
            )
        )
        filas.append(
            _adj(f"{prefijo}{i}-SIG", empresa_id=ganador, fecha_adj=sig, organo=organo, cpv=cpv)
        )
    return filas


def _historico() -> list[dict[str, Any]]:
    """Dos segmentos del mismo CPV-4: uno retiene siempre (5/5) y otro nunca (0/5)."""
    filas = _pares("F", _ORGANO_FIEL, retenidos=5) + _pares("R", _ORGANO_ROTATORIO, retenidos=0)
    filas.sort(key=lambda f: str(f["fecha_adjudicacion"]))
    return filas


def _historico_dos_cpv4() -> list[dict[str, Any]]:
    """El de :func:`_historico` más un segmento de obras (CPV-4 4500) que retiene 5/5.

    Con dos CPV-4 la tasa global (10/15) y la del CPV-4 7200 (5/10) difieren, y
    se puede ver a qué nivel cae cada búsqueda.
    """
    filas = _historico() + _pares("O", _ORGANO_OBRAS, retenidos=5, cpv="45000000")
    filas.sort(key=lambda f: str(f["fecha_adjudicacion"]))
    return filas


def _vencimiento(lic_id: str, organo: str, cpv4: str = _CPV4) -> rl.ParRetencion:
    """Fila de scoring tal como la devuelve ``vencimientos_proximos``."""
    return rl.ParRetencion(
        licitacion_id=lic_id,
        sucesor_id="",
        empresa_id=_INCUMBENTE,
        organo=organo,
        fecha_fin="2026-12-01",
        fecha_sucesor="",
        label=-1,
        features={},
        cpv4=cpv4,
    )


# ---------------------------------------------------------------------------
# Las etiquetas miden retención, no vinculación al maestro
# ---------------------------------------------------------------------------


def test_la_tasa_por_segmento_es_la_fraccion_retenida():
    with patch.object(rl, "_cargar_adjudicaciones", return_value=_historico()):
        tasas = rl.tasas_retencion_por_segmento()
        etiquetas = rl.etiquetas_por_segmento()

    assert tasas[(normalize_organo(_ORGANO_FIEL), _CPV4)] == pytest.approx(1.0)
    assert tasas[(normalize_organo(_ORGANO_ROTATORIO), _CPV4)] == pytest.approx(0.0)
    # Lo que consume el baseline son los conteos, no las tasas publicadas.
    assert etiquetas.conteos == {
        (normalize_organo(_ORGANO_FIEL), _CPV4): (5, 5),
        (normalize_organo(_ORGANO_ROTATORIO), _CPV4): (0, 5),
    }
    assert etiquetas.pares == 10


def test_un_segmento_sin_historia_suficiente_no_publica_tasa_cruda_pero_si_cuenta():
    """Menos de ``MIN_OBS_SEGMENTO`` pares: sin tasa cruda, pero su par sí pesa."""
    historico = [
        _adj(
            "U1",
            empresa_id=_INCUMBENTE,
            fecha_adj="2020-01-01",
            fecha_fin="2022-01-01",
            organo="Organo Unico",
        ),
        _adj("U1-SIG", empresa_id=_INCUMBENTE, fecha_adj="2022-03-01", organo="Organo Unico"),
    ]
    with patch.object(rl, "_cargar_adjudicaciones", return_value=historico):
        assert rl.tasas_retencion_por_segmento() == {}
        assert rl.etiquetas_por_segmento().conteos == {
            (normalize_organo("Organo Unico"), _CPV4): (1, 1)
        }


def test_las_etiquetas_aceptan_el_historico_ya_cargado():
    """El batch comparte una carga: pasar la lista no vuelve a la BD."""
    with patch.object(rl, "_cargar_adjudicaciones", side_effect=AssertionError("recarga")):
        etiquetas = rl.etiquetas_por_segmento(_historico())
        tasas = rl.tasas_retencion_por_segmento(adjudicaciones=_historico())

    assert etiquetas.pares == 10
    assert len(tasas) == 2


# ---------------------------------------------------------------------------
# Shrinkage jerárquico
# ---------------------------------------------------------------------------


def _etiquetas(conteos: dict[tuple[str, str], tuple[int, int]]) -> rl.EtiquetasPorSegmento:
    return rl.EtiquetasPorSegmento(conteos=conteos, con_sucesora=frozenset())


def test_el_shrinkage_sigue_la_formula_en_los_tres_niveles():
    """``p_g = Σ/N``; ``p_c = (Σ_c + k·p_g)/(n_c + k)``; ``p_s = (Σ_s + k·p_c)/(n_s + k)``."""
    conteos = {
        ("a", "7200"): (8, 10),
        ("b", "7200"): (1, 5),
        ("c", "4500"): (0, 1),
    }

    baseline = scoring._baseline_retencion(_etiquetas(conteos))

    p_g = 9 / 16  # agregada sobre TODOS los pares, no media de tasas
    p_7200 = (9 + _K * p_g) / (15 + _K)
    p_4500 = (0 + _K * p_g) / (1 + _K)
    assert baseline.pares == 16
    assert baseline.tasa_global == pytest.approx(p_g)
    assert baseline.por_cpv4 == pytest.approx({"7200": p_7200, "4500": p_4500})
    assert baseline.por_segmento == pytest.approx(
        {
            ("a", "7200"): (8 + _K * p_7200) / (10 + _K),
            ("b", "7200"): (1 + _K * p_7200) / (5 + _K),
            ("c", "4500"): (0 + _K * p_4500) / (1 + _K),
        }
    )


def test_la_tasa_global_es_agregada_y_no_la_media_de_las_tasas():
    """La media no ponderada pesaba igual un segmento de 5 pares que uno de 500."""
    baseline = scoring._baseline_retencion(
        _etiquetas({("grande", "7200"): (450, 500), ("chico", "4500"): (0, 5)})
    )

    assert baseline.tasa_global == pytest.approx(450 / 505)
    assert baseline.tasa_global != pytest.approx((0.9 + 0.0) / 2)


def test_un_segmento_con_un_par_se_queda_cerca_de_su_cpv4():
    """Antes: 1 par → media global; con ≥5, un 0.0 o 1.0 crudo. Ahora, gradual."""
    baseline = scoring._baseline_retencion(
        _etiquetas({("uno", "7200"): (1, 1), ("mil", "7200"): (100, 1000)})
    )
    p_c = baseline.por_cpv4["7200"]

    assert abs(baseline.por_segmento[("uno", "7200")] - p_c) < 0.1
    assert baseline.por_segmento[("mil", "7200")] == pytest.approx(0.1, abs=0.01)


def test_la_busqueda_cae_de_segmento_a_cpv4_y_a_global():
    baseline = scoring._baseline_retencion(
        _etiquetas({("a", "7200"): (8, 10), ("c", "4500"): (0, 1)})
    )

    assert baseline.tasa("a", "7200") == (baseline.por_segmento[("a", "7200")], "segmento")
    assert baseline.tasa("otro", "7200") == (baseline.por_cpv4["7200"], "cpv4")
    assert baseline.tasa("a", "9999") == (baseline.tasa_global, "global")
    assert baseline.tasa(None, None) == (baseline.tasa_global, "global")


def test_sin_ningun_par_se_sirve_el_default_conservador():
    for etiquetas in (None, _etiquetas({})):
        baseline = scoring._baseline_retencion(etiquetas)
        assert baseline.tasa_global == scoring._PROB_RETENCION_SIN_PARES == 0.6
        assert baseline.tasa("a", "7200") == (0.6, "global")


# ---------------------------------------------------------------------------
# El serving aplica la tasa del segmento de cada fila
# ---------------------------------------------------------------------------


class _RepoRetencion:
    def __init__(self) -> None:
        self.filas: list[tuple[Any, ...]] = []

    def guardar_retencion(self, filas, *, computed_at):
        self.filas = list(filas)
        return {"escritas": len(filas), "purgadas": 0}


def _filas_escritas(
    vencimientos: list[rl.ParRetencion],
    historico: list[dict[str, Any]] | None = None,
) -> tuple[list[tuple[Any, ...]], dict[str, Any]]:
    """Ejecuta el batch sin modelo activo y devuelve lo que iba a la BD."""
    repo = _RepoRetencion()
    with (
        patch.object(settings, "ML_RETENCION_EXCLUIR_RESUELTOS", False),
        patch.object(rl, "_cargar_adjudicaciones", return_value=historico or _historico()),
        patch.object(rl, "vencimientos_proximos", return_value=vencimientos),
        patch("db.model_registry.get_active", return_value=None),
        patch("shared.model_artifacts.resolve_active_artifact", return_value=None),
        patch.object(scoring, "PrediccionesRepository", return_value=repo),
    ):
        resultado = scoring.score_predicciones_retencion()

    assert resultado["status"] == "baseline"
    assert resultado["filas"] == len(vencimientos)
    return repo.filas, resultado


def test_el_baseline_distingue_segmentos_con_retencion_distinta():
    """Regresión: el lookup por segmento no se aplicaba NUNCA.

    ``getattr(f, "cpv", "")`` y ``getattr(f, "organo_contratacion", "")`` sobre
    un ``ParRetencion`` devolvían cadena vacía, así que la condición del lookup
    era siempre falsa y las dos filas salían con la misma media global. Una
    varianza cero entre segmentos con tasas 1.0 y 0.0 es la firma del bug.

    Con shrinkage ya no salen 1.0 y 0.0 crudos: 5 pares frente a ``k = 10``
    encogen cada segmento hacia su CPV-4 (5/10 = 0.5), pero el orden y la
    distancia entre ellos se conservan.
    """
    filas, resultado = _filas_escritas(
        [_vencimiento("V-FIEL", _ORGANO_FIEL), _vencimiento("V-ROTATORIO", _ORGANO_ROTATORIO)]
    )

    prob = {r[0]: r[2] for r in filas}
    riesgo = {r[0]: r[3] for r in filas}
    p_c = (5 + _K * 0.5) / (10 + _K)
    assert prob["V-FIEL"] == pytest.approx((5 + _K * p_c) / (5 + _K), abs=1e-5)
    assert prob["V-ROTATORIO"] == pytest.approx((0 + _K * p_c) / (5 + _K), abs=1e-5)
    assert prob["V-FIEL"] > prob["V-ROTATORIO"]
    # Y el riesgo de cambio sigue siendo el complementario.
    for lic_id, p in prob.items():
        assert riesgo[lic_id] == pytest.approx(1.0 - p)
    assert resultado["tasa_global"] == pytest.approx(0.5)
    assert resultado["niveles_baseline"] == {"segmento": 2}


def test_un_segmento_desconocido_cae_a_su_cpv4_y_sin_cpv4_a_la_global():
    filas, resultado = _filas_escritas(
        [
            _vencimiento("V-OTRO-ORGANO", "Organo Sin Historia"),
            _vencimiento("V-OTRO-CPV", "Organo Sin Historia", cpv4="9999"),
        ],
        historico=_historico_dos_cpv4(),
    )

    prob = {r[0]: r[2] for r in filas}
    p_g = 10 / 15
    assert prob["V-OTRO-ORGANO"] == pytest.approx((5 + _K * p_g) / (10 + _K), abs=1e-5)
    assert prob["V-OTRO-CPV"] == pytest.approx(p_g, abs=1e-5)
    assert resultado["niveles_baseline"] == {"cpv4": 1, "global": 1}


def test_el_baseline_es_fail_open_si_el_etiquetado_revienta():
    """Sin etiquetas se sirve el caso degenerado en vez de no publicar nada."""
    with patch.object(rl, "_emparejar", side_effect=RuntimeError("heurística rota")):
        filas, resultado = _filas_escritas([_vencimiento("V-FIEL", _ORGANO_FIEL)])

    assert [r[2] for r in filas] == [pytest.approx(0.6)]
    # No es lo mismo «ningún resuelto» que «no se pudo buscar».
    assert resultado["resueltos_detectados"] is None
    assert resultado["tasa_global"] == pytest.approx(0.6)
