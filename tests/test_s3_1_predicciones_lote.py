"""S3.1 — precio y baja **por lote**, sin base de datos.

El criterio del plan decía que ``escenarios-precio`` y ``prediccion-baja``
aceptan ``lote_id``, y no lo aceptaban: los dos calculaban siempre sobre el
expediente completo mientras ``pursuits`` ya guardaba el lote por el que se
puja (``v110``). Estos tests fijan las dos mitades del arreglo:

- **lo que no puede cambiar**: sin ``lote_id`` la respuesta de escenarios es la
  misma que servía antes de S3.1, campo a campo, con los mismos valores y en el
  mismo orden; lo único que se le suma son los dos campos nuevos a ``null``. El
  golden de ``_GOLDEN_SIN_LOTE`` se capturó ejecutando la versión de ``HEAD``
  del módulo, no la nueva, para que no se esté comparando el código consigo
  mismo;
- **lo que sí cambia**: con ``lote_id`` el denominador es el importe del lote,
  y donde no hay dato del lote no se rellena con el del expediente (ADR-014).

Todo corre con repositorios falsos: no hay fixtures de BD, así que ``conftest``
los marca ``unit`` y entran en el bucle rápido.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api.routes.predicciones import (
    PrediccionBajaResult,
    get_escenarios_precio,
    get_prediccion_baja,
)
from services.ml.pricing_scenarios import get_price_scenarios
from services.ml.scoring import LoteDesconocidoError, prediccion_baja

_LICITACION = "TARGET"
_OTRO = "OTRO-EXPEDIENTE"

# Los campos que se le han AÑADIDO al DTO desde que se capturó el golden. Se
# comparan aparte para que el de abajo siga siendo, literalmente, lo que servía
# el módulo anterior: `lote_id` y `lote_numero` los puso S3.1, y `base` lo puso
# C1.1 para que una baja diga sobre qué base de importe se calculó —publicarla
# sin decirlo es publicar un número que no se puede interpretar, porque el 21 %
# de IVA cabe entero dentro del rango de bajas plausibles—.
_ADITIVOS = ("lote_id", "lote_numero", "base")

# Respuesta exacta de `get_price_scenarios("TARGET", expected_competition=3)`
# con `_historial()` como histórico, tal y como la serializaba el módulo antes
# de que S3.1 le añadiera `lote_id`. Se compara el dict Y el orden de sus
# claves: ningún valor de los que ya existían puede moverse.
_GOLDEN_SIN_LOTE: dict[str, Any] = {
    "licitacion_id": "TARGET",
    "tender_amount_eur": 100000.0,
    "expected_competition": 3,
    "cohort": ["organo", "cpv4", "importe", "competencia"],
    "sample_quality": "robusta",
    "distribution": {
        "n": 40,
        "p10_discount": 0.139,
        "p25_discount": 0.1975,
        "p50_discount": 0.295,
        "p75_discount": 0.3925,
        "p90_discount": 0.451,
        "observed_interval": [0.139, 0.451],
    },
    "scenarios": [
        {
            "name": "defensivo",
            "discount": 0.1975,
            "price_eur": 80250.0,
            "basis": "percentil 25 de la baja observada",
            "margen_implicito": None,
        },
        {
            "name": "central",
            "discount": 0.295,
            "price_eur": 70500.0,
            "basis": "mediana de la baja observada",
            "margen_implicito": None,
        },
        {
            "name": "competitivo",
            "discount": 0.3925,
            "price_eur": 60750.0,
            "basis": "percentil 75 de la baja observada",
            "margen_implicito": None,
        },
    ],
    "win_probability_gate": {
        "available": False,
        "blockers": [
            "faltan ofertas perdedoras y outcomes propios vinculados al precio ofertado",
            "falta validación temporal fuera de muestra por segmento",
            "falta calibración (Brier score y curva por deciles) frente al baseline",
        ],
    },
    "methodology": "Distribución empírica de bajas en adjudicaciones comparables observadas.",
    "disclaimer": (
        "Estos escenarios NO son una P(ganar) causal ni garantizan adjudicación. "
        "Son referencias descriptivas del histórico observado; no incluyen ofertas perdedoras."
    ),
}


def _historial() -> list[dict[str, Any]]:
    """Cuarenta adjudicaciones del mismo órgano y CPV, bajas del 10 % al 49 %."""
    return [
        {
            "licitacion_id": f"H-{index}",
            "organo_contratacion": "Órgano A",
            "cpv": "72000000",
            "importe_licitacion": 100_000.0,
            "importe_adjudicado": 100_000.0 * (1.0 - (0.10 + index * 0.01)),
            "n_ofertas_recibidas": 3,
        }
        for index in range(40)
    ]


def _lote(
    *,
    lote_id: int = 7,
    numero: str = "2",
    importe: float | None = 40_000.0,
    cpv_lote: str | None = "72000000",
    licitacion_id: str = _LICITACION,
) -> dict[str, Any]:
    """Fila tal y como la devuelve ``PricingRepository.get_lote_target``."""
    return {
        "id_externo": licitacion_id,
        "lote_id": lote_id,
        "lote_numero": numero,
        "lote_titulo": "Migración",
        "organo_contratacion": "Órgano A",
        "cpv_lote": cpv_lote,
        "cpv_expediente": "72000000",
        "importe": importe,
    }


class _FakePricing:
    """Repositorio de precios en memoria, con la pertenencia del lote incluida."""

    def __init__(self, *lotes: dict[str, Any]) -> None:
        self.lotes = {(row["id_externo"], row["lote_id"]): row for row in lotes}

    def get_target(self, licitacion_id: str) -> dict[str, Any] | None:
        if licitacion_id != _LICITACION:
            return None
        return {
            "id_externo": licitacion_id,
            "titulo": "Migración ERP",
            "organo_contratacion": "Órgano A",
            "cpv": "72000000",
            "importe": 100_000.0,
        }

    def get_lote_target(self, licitacion_id: str, lote_id: int) -> dict[str, Any] | None:
        return self.lotes.get((licitacion_id, lote_id))

    def load_history(self, *, limit: int = 10_000) -> list[dict[str, Any]]:
        return _historial()[:limit]


class _FakePredicciones:
    """``PrediccionesRepository`` en memoria para el camino por lote."""

    def __init__(
        self,
        *,
        lote: dict[str, Any] | None = None,
        pred_lote: dict[str, Any] | None = None,
        pred_agregada: dict[str, Any] | None = None,
        baja: dict[str, Any] | None = None,
    ) -> None:
        self.lote = lote
        self.pred_lote = pred_lote
        self.pred_agregada = pred_agregada
        self.baja = baja

    def lote_de(self, licitacion_id: str, lote_id: int) -> dict[str, Any] | None:
        return self.lote

    def prediccion_materializada(
        self, licitacion_id: str, lote_id: int | None = None
    ) -> dict[str, Any] | None:
        return self.pred_lote if lote_id is not None else self.pred_agregada

    def baja_real_de_lote(self, licitacion_id: str, lote_id: int) -> dict[str, Any] | None:
        return self.baja


def _prediccion(p50: float = 0.20, model_version: int | None = 3) -> dict[str, Any]:
    return {
        "p10": 0.10,
        "p50": p50,
        "p90": 0.30,
        "model_version": model_version,
        "computed_at": "2026-09-01T03:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# escenarios-precio
# ---------------------------------------------------------------------------


def test_sin_lote_la_respuesta_es_exactamente_la_de_antes_de_s3_1() -> None:
    """El caso que S3.1 se comprometió a no tocar: el expediente completo."""
    with patch("services.ml.pricing_scenarios._tarifas_del_pliego", return_value=[]):
        result = get_price_scenarios(_LICITACION, expected_competition=3, repository=_FakePricing())

    assert result is not None
    servido = json.loads(result.model_dump_json())
    previos = {clave: valor for clave, valor in servido.items() if clave not in _ADITIVOS}
    assert previos == _GOLDEN_SIN_LOTE
    # Mismo orden de claves: `json.loads` lo conserva, así que esto cierra la
    # única diferencia que la igualdad de dicts dejaría pasar.
    assert list(previos) == list(_GOLDEN_SIN_LOTE)
    # Y lo único que se le añadió al payload son los campos aditivos: los dos de
    # S3.1 a `null` —no hay lote— y la base declarada de C1.1.
    assert {clave: servido[clave] for clave in _ADITIVOS} == {
        "lote_id": None,
        "lote_numero": None,
        "base": "mixta",
    }


def test_el_escenario_del_lote_se_calcula_sobre_el_presupuesto_del_lote() -> None:
    """Mismas bajas (misma cohorte), otro denominador: el del lote."""
    tarifas = patch("services.ml.pricing_scenarios._tarifas_del_pliego", return_value=[])
    with tarifas as leer_tarifas:
        result = get_price_scenarios(
            _LICITACION,
            lote_id=7,
            expected_competition=3,
            repository=_FakePricing(_lote()),
        )

    assert result is not None
    assert result.tender_amount_eur == 40_000.0
    assert result.lote_id == 7
    assert result.lote_numero == "2"
    # Las bajas son las del histórico comparable, que no depende del importe
    # del objeto; los precios sí, y por eso son 40 000 € y no 100 000 €.
    assert [s.discount for s in result.scenarios] == [0.1975, 0.295, 0.3925]
    assert [s.price_eur for s in result.scenarios] == [32_100.0, 28_200.0, 24_300.0]
    assert "el denominador es el importe del lote 2" in result.methodology
    # F2.4 no se sirve por lote: las tarifas del pliego son del expediente.
    assert leer_tarifas.call_count == 0
    assert all(s.margen_implicito is None for s in result.scenarios)


def test_un_lote_sin_importe_no_hereda_el_del_expediente() -> None:
    """ADR-014: sin denominador no se pinta. Ni se reparte el del expediente."""
    with patch("services.ml.pricing_scenarios._tarifas_del_pliego", return_value=[]):
        result = get_price_scenarios(
            _LICITACION,
            lote_id=7,
            repository=_FakePricing(_lote(importe=None)),
        )

    assert result is not None
    assert result.tender_amount_eur == 0.0
    assert result.sample_quality == "insuficiente"
    assert result.scenarios == []
    assert result.lote_id == 7


def test_un_lote_sin_cpv_propio_hereda_el_del_expediente_y_lo_declara() -> None:
    """El lote es el mismo objeto de contrato; lo que no vale es callárselo."""
    with patch("services.ml.pricing_scenarios._tarifas_del_pliego", return_value=[]):
        result = get_price_scenarios(
            _LICITACION,
            lote_id=7,
            expected_competition=3,
            repository=_FakePricing(_lote(cpv_lote=None)),
        )

    assert result is not None
    assert "cpv4" in result.cohort
    assert "El CPV se hereda del expediente" in result.methodology


def test_el_lote_de_otro_expediente_no_tiene_escenario() -> None:
    ajeno = _lote(lote_id=99, licitacion_id=_OTRO)
    result = get_price_scenarios(_LICITACION, lote_id=99, repository=_FakePricing(ajeno))
    assert result is None


def test_la_ruta_de_escenarios_devuelve_404_para_un_lote_ajeno() -> None:
    with patch("api.routes.predicciones.get_price_scenarios", return_value=None):
        with pytest.raises(HTTPException) as error:
            asyncio.run(get_escenarios_precio(_LICITACION, lote_id=99, _ctx={}))

    assert error.value.status_code == 404
    assert error.value.detail == "Lote no encontrado en esa licitación."


def test_la_ruta_sin_lote_conserva_su_404_de_siempre() -> None:
    with patch("api.routes.predicciones.get_price_scenarios", return_value=None):
        with pytest.raises(HTTPException) as error:
            asyncio.run(get_escenarios_precio("NO-EXISTE", _ctx={}))

    assert error.value.detail == "Licitación no encontrada."


def test_la_ruta_pasa_el_lote_al_servicio() -> None:
    """Sin esto el parámetro existiría en el contrato y no haría nada."""
    with patch("services.ml.pricing_scenarios._tarifas_del_pliego", return_value=[]):
        with patch(
            "api.routes.predicciones.get_price_scenarios",
            side_effect=lambda *args, **kwargs: get_price_scenarios(
                *args, **kwargs, repository=_FakePricing(_lote())
            ),
        ):
            servido = asyncio.run(get_escenarios_precio(_LICITACION, lote_id=7, _ctx={}))

    assert servido.lote_id == 7
    assert servido.tender_amount_eur == 40_000.0


# ---------------------------------------------------------------------------
# prediccion-baja
# ---------------------------------------------------------------------------


def test_la_prediccion_del_lote_declara_que_el_intervalo_es_del_expediente() -> None:
    """Hoy el batch solo materializa la fila agregada (v86 no cruzó la puerta).

    Servirla para un lote es defendible —la baja es un ratio— pero solo si se
    dice; lo que no vale es presentarla como una predicción de ese lote.
    """
    repo = _FakePredicciones(
        lote={"id": 7, "numero": "2", "importe": 40_000.0},
        pred_lote=None,
        pred_agregada=_prediccion(),
    )
    with patch("services.ml.scoring.PrediccionesRepository", return_value=repo):
        data = prediccion_baja(_LICITACION, 7)

    assert data is not None
    assert data["prediccion_ambito"] == "expediente"
    assert data["lote_id"] == 7
    assert data["lote_numero"] == "2"
    assert data["p50"] == 0.20
    assert data["serving"] == "modelo"


def test_una_prediccion_materializada_del_lote_se_sirve_como_del_lote() -> None:
    repo = _FakePredicciones(
        lote={"id": 7, "numero": "2", "importe": 40_000.0},
        pred_lote=_prediccion(p50=0.33, model_version=None),
        pred_agregada=_prediccion(),
    )
    with patch("services.ml.scoring.PrediccionesRepository", return_value=repo):
        data = prediccion_baja(_LICITACION, 7)

    assert data is not None
    assert data["prediccion_ambito"] == "lote"
    assert data["p50"] == 0.33
    assert data["serving"] == "baseline"


def test_la_baja_real_del_lote_se_divide_entre_el_importe_del_lote() -> None:
    repo = _FakePredicciones(
        lote={"id": 7, "numero": "2", "importe": 40_000.0},
        pred_agregada=_prediccion(),
        baja={"presupuesto": 40_000.0, "total_adjudicado": 30_000.0},
    )
    with patch("services.ml.scoring.PrediccionesRepository", return_value=repo):
        data = prediccion_baja(_LICITACION, 7)

    assert data is not None
    # 25 % del lote. Contra el expediente (100 000 €) habría salido un 70 %.
    assert data["baja_real"] == pytest.approx(0.25)
    assert data["importe_adjudicado"] == 30_000.0


def test_un_lote_sin_importe_publicado_no_tiene_baja_real() -> None:
    """Sin denominador propio no se calcula con el del expediente: se omite."""
    repo = _FakePredicciones(
        lote={"id": 7, "numero": "2", "importe": None},
        pred_agregada=_prediccion(),
        baja={"presupuesto": None, "total_adjudicado": 30_000.0},
    )
    with patch("services.ml.scoring.PrediccionesRepository", return_value=repo):
        data = prediccion_baja(_LICITACION, 7)

    assert data is not None
    assert "baja_real" not in data
    assert data["p50"] == 0.20


def test_sin_prediccion_ni_adjudicacion_el_lote_da_404() -> None:
    repo = _FakePredicciones(lote={"id": 7, "numero": "2", "importe": 40_000.0})
    with patch("services.ml.scoring.PrediccionesRepository", return_value=repo):
        assert prediccion_baja(_LICITACION, 7) is None

        with pytest.raises(HTTPException) as error:
            asyncio.run(get_prediccion_baja(_LICITACION, lote_id=7, _ctx={}))
    assert error.value.status_code == 404
    assert error.value.detail == "Sin predicción ni adjudicación registrada para ese lote."


def test_un_lote_ajeno_es_un_error_distinto_de_no_tener_datos() -> None:
    repo = _FakePredicciones(lote=None)
    with patch("services.ml.scoring.PrediccionesRepository", return_value=repo):
        with pytest.raises(LoteDesconocidoError):
            prediccion_baja(_LICITACION, 99)

        with pytest.raises(HTTPException) as error:
            asyncio.run(get_prediccion_baja(_LICITACION, lote_id=99, _ctx={}))

    assert error.value.status_code == 404
    assert "no pertenece" in error.value.detail


def test_sin_lote_la_prediccion_no_emite_ninguno_de_los_campos_nuevos() -> None:
    """La ruta serializa con ``exclude_unset``: lo que no se puso, no sale."""
    servido = PrediccionBajaResult(
        licitacion_id="ABIERTA",
        p10=0.1,
        p50=0.12,
        p90=0.2,
        model_version=None,
        computed_at="2026-01-01",
        serving="baseline",
    ).model_dump(exclude_unset=True)

    assert set(servido) == {
        "licitacion_id",
        "p10",
        "p50",
        "p90",
        "model_version",
        "computed_at",
        "serving",
    }


def test_la_ruta_sin_lote_conserva_su_404_y_su_mensaje() -> None:
    with patch("api.routes.predicciones.prediccion_baja", return_value=None):
        with pytest.raises(HTTPException) as error:
            asyncio.run(get_prediccion_baja("SIN-DATOS", _ctx={}))

    assert error.value.detail == "Sin predicción ni adjudicación registrada para esa licitación."
