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

Sin Postgres: el histórico se inyecta en ``retencion_labels`` y la escritura se
captura con una conexión de mentira.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import services.ml.retencion_labels as rl
import services.ml.scoring as scoring
from services.dedupe import normalize_organo

_CPV = "72000000"
_CPV4 = "7200"
_INCUMBENTE = 7
_RIVAL = 99

_ORGANO_FIEL = "Ayuntamiento de Fidelia"
_ORGANO_ROTATORIO = "Diputacion de Rotacion"


def _adj(
    lic_id: str,
    *,
    empresa_id: int,
    fecha_adj: str,
    organo: str,
    fecha_fin: str | None = None,
) -> dict[str, Any]:
    return {
        "licitacion_id": lic_id,
        "empresa_id": empresa_id,
        "nombre": f"Empresa {empresa_id}",
        "fecha_adjudicacion": fecha_adj,
        "importe_adjudicado": 90_000.0,
        "organo": organo,
        "cpv": _CPV,
        "ccaa": "Madrid",
        "importe": 100_000.0,
        "titulo": f"Servicio {lic_id}",
        "fecha_fin_efectiva": fecha_fin,
    }


def _historico() -> list[dict[str, Any]]:
    """Dos segmentos: uno retiene siempre (1.0) y otro nunca (0.0).

    Los pares de cada segmento se separan cinco años entre sí para que la
    sucesora más cercana a cada vencimiento sea siempre la suya y no el
    contrato del par siguiente.
    """
    filas: list[dict[str, Any]] = []
    for i in range(5):
        adj = f"{2000 + 5 * i}-01-01"
        fin = f"{2002 + 5 * i}-01-01"
        sig = f"{2002 + 5 * i}-04-01"
        filas.append(
            _adj(f"F{i}", empresa_id=_INCUMBENTE, fecha_adj=adj, fecha_fin=fin, organo=_ORGANO_FIEL)
        )
        filas.append(_adj(f"F{i}-SIG", empresa_id=_INCUMBENTE, fecha_adj=sig, organo=_ORGANO_FIEL))
        filas.append(
            _adj(
                f"R{i}",
                empresa_id=_INCUMBENTE,
                fecha_adj=adj,
                fecha_fin=fin,
                organo=_ORGANO_ROTATORIO,
            )
        )
        filas.append(_adj(f"R{i}-SIG", empresa_id=_RIVAL, fecha_adj=sig, organo=_ORGANO_ROTATORIO))
    filas.sort(key=lambda f: str(f["fecha_adjudicacion"]))
    return filas


def _vencimiento(lic_id: str, organo: str) -> rl.ParRetencion:
    """Fila de scoring tal como la devuelve ``features_para_vencimientos``."""
    return rl.ParRetencion(
        licitacion_id=lic_id,
        sucesor_id="",
        empresa_id=_INCUMBENTE,
        organo=organo,
        fecha_fin="2026-12-01",
        fecha_sucesor="",
        label=-1,
        features={},
        cpv4=_CPV4,
    )


# ---------------------------------------------------------------------------
# La tasa mide retención, no vinculación al maestro
# ---------------------------------------------------------------------------


def test_la_tasa_por_segmento_es_la_fraccion_retenida():
    with patch.object(rl, "_cargar_adjudicaciones", return_value=_historico()):
        tasas = scoring._tasa_retencion_baseline()

    assert tasas[(normalize_organo(_ORGANO_FIEL), _CPV4)] == pytest.approx(1.0)
    assert tasas[(normalize_organo(_ORGANO_ROTATORIO), _CPV4)] == pytest.approx(0.0)


def test_un_segmento_sin_historia_suficiente_no_publica_tasa():
    """Menos de ``MIN_OBS_SEGMENTO`` pares: el segmento cae al fallback."""
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
        assert scoring._tasa_retencion_baseline() == {}


def test_el_baseline_es_fail_open_si_el_etiquetado_revienta():
    with patch.object(rl, "_cargar_adjudicaciones", side_effect=RuntimeError("BD caída")):
        assert scoring._tasa_retencion_baseline() == {}


# ---------------------------------------------------------------------------
# El serving aplica la tasa del segmento de cada fila
# ---------------------------------------------------------------------------


def _filas_escritas(vencimientos: list[rl.ParRetencion]) -> list[tuple[Any, ...]]:
    """Ejecuta el batch sin modelo activo y devuelve lo que iba a la BD."""
    conn = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = conn
    with (
        patch.object(rl, "_cargar_adjudicaciones", return_value=_historico()),
        patch.object(rl, "features_para_vencimientos", return_value=vencimientos),
        patch("db.model_registry.get_active", return_value=None),
        patch("shared.model_artifacts.resolve_active_artifact", return_value=None),
        patch.object(scoring, "connect", return_value=cm),
    ):
        resultado = scoring.score_predicciones_retencion()

    assert resultado["status"] == "baseline"
    assert resultado["filas"] == len(vencimientos)
    return list(conn.executemany.call_args[0][1])


def test_el_baseline_distingue_segmentos_con_retencion_distinta():
    """Regresión: el lookup por segmento no se aplicaba NUNCA.

    ``getattr(f, "cpv", "")`` y ``getattr(f, "organo_contratacion", "")`` sobre
    un ``ParRetencion`` devolvían cadena vacía, así que la condición del lookup
    era siempre falsa y las dos filas salían con la misma media global. Una
    varianza cero entre segmentos con tasas 1.0 y 0.0 es la firma del bug.
    """
    filas = _filas_escritas(
        [_vencimiento("V-FIEL", _ORGANO_FIEL), _vencimiento("V-ROTATORIO", _ORGANO_ROTATORIO)]
    )

    prob = {r[0]: r[2] for r in filas}
    riesgo = {r[0]: r[3] for r in filas}
    assert prob["V-FIEL"] == pytest.approx(1.0)
    assert prob["V-ROTATORIO"] == pytest.approx(0.0)
    assert len(set(prob.values())) > 1, "el baseline sirve un riesgo constante"
    # Y el riesgo de cambio sigue siendo el complementario.
    for lic_id, p in prob.items():
        assert riesgo[lic_id] == pytest.approx(1.0 - p)


def test_un_segmento_desconocido_cae_a_la_media_global():
    filas = _filas_escritas([_vencimiento("V-OTRO", "Organo Sin Historia")])

    # Media de las tasas publicadas: (1.0 + 0.0) / 2.
    assert filas[0][2] == pytest.approx(0.5)
