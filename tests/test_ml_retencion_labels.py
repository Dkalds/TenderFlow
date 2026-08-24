"""Anti-fuga del etiquetado de retención (``services/ml/retencion_labels.py``).

El emparejamiento vencimiento→sucesora admite sucesoras adjudicadas **antes**
del fin del contrato original: el sector público re-licita con antelación. Lo
que no puede pasar es que esa sucesora entre en el histórico con el que se
calculan las features de su propio par — comparte órgano normalizado y CPV-4
por construcción, así que se cuela en ``contratos_previos_organo``,
``antiguedad_relacion_meses`` y ``cuota_segmento`` **solo cuando la ganó el
incumbente**, es decir, exactamente cuando ``label == 1``.

La forma de verlo sin depender de números concretos: montar el mismo par dos
veces, cambiando únicamente quién gana la sucesora, y exigir que las features
salgan idénticas. Si alguna se mueve, esa feature codifica el target.

Todo con datos inyectados (sin Postgres): la frontera con la BD la fija
``tests/test_retencion_labels_db_boundary.py``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

import services.ml.retencion_labels as rl
from services.dedupe import normalize_organo

_ORGANO = "Ayuntamiento de Madrid"
_CPV = "72000000"


def _adj(
    lic_id: str,
    *,
    empresa_id: int,
    fecha_adj: str,
    fecha_fin: str | None = None,
    organo: str = _ORGANO,
    cpv: str = _CPV,
    importe: float = 100_000.0,
    adjudicado: float = 90_000.0,
) -> dict[str, Any]:
    """Fila tal y como la devuelve ``AdjudicacionRepository.load_para_retencion``."""
    return {
        "licitacion_id": lic_id,
        "empresa_id": empresa_id,
        "nombre": f"Empresa {empresa_id}",
        "fecha_adjudicacion": fecha_adj,
        "importe_adjudicado": adjudicado,
        "organo": organo,
        "cpv": cpv,
        "ccaa": "Madrid",
        "importe": importe,
        "titulo": f"Servicio {lic_id}",
        "fecha_fin_efectiva": fecha_fin,
    }


def _par_con_sucesora_anticipada(empresa_sucesora: int) -> rl.ParRetencion:
    """Par cuya sucesora se adjudica ~5 meses ANTES del vencimiento.

    ``empresa_sucesora`` es lo único que cambia entre la versión con
    ``label = 1`` y la de ``label = 0``.
    """
    adjudicaciones = [
        # Relación previa del incumbente con el órgano.
        _adj("OLD", empresa_id=7, fecha_adj="2022-01-01"),
        # Contrato original: vence el 2025-01-10.
        _adj("C1", empresa_id=7, fecha_adj="2023-01-10", fecha_fin="2025-01-10"),
        # Sucesora adjudicada antes del vencimiento (re-licitación anticipada).
        _adj("C1-SIG", empresa_id=empresa_sucesora, fecha_adj="2024-08-15"),
    ]
    pares = _construir(adjudicaciones)
    assert len(pares) == 1
    return pares[0]


def _construir(adjudicaciones: list[dict[str, Any]], **kwargs: Any) -> list[rl.ParRetencion]:
    """``construir_pares`` con el histórico inyectado (sin tocar Postgres)."""
    with (
        patch.object(rl, "_cargar_adjudicaciones", return_value=adjudicaciones),
        patch.object(rl, "_eventos_por_licitacion", return_value={}),
    ):
        return rl.construir_pares(**kwargs)


# ---------------------------------------------------------------------------
# Fuga: la sucesora anticipada no puede entrar en sus propias features
# ---------------------------------------------------------------------------


def test_sucesora_anticipada_no_cambia_las_features_segun_el_label():
    """Mismo par, distinto ganador de la sucesora: features idénticas.

    Con el ancla en ``fin`` (comportamiento anterior) la sucesora del caso
    positivo cumplía ``fecha_adjudicacion < fin``, mismo órgano y mismo CPV-4:
    ``contratos_previos_organo`` valía 3 con ``label = 1`` y 2 con
    ``label = 0``. Una feature que vale +1 exactamente cuando el target vale 1
    no es una feature, es el target.
    """
    retenido = _par_con_sucesora_anticipada(empresa_sucesora=7)
    perdido = _par_con_sucesora_anticipada(empresa_sucesora=99)

    assert retenido.label == 1
    assert perdido.label == 0
    for columna in ("contratos_previos_organo", "antiguedad_relacion_meses", "cuota_segmento"):
        assert retenido.features[columna] == perdido.features[columna], (
            f"{columna} depende del label: fuga de etiqueta"
        )
    # Y el valor es el correcto: OLD y el propio C1, ambos anteriores al ancla.
    assert retenido.features["contratos_previos_organo"] == 2.0


def test_el_ancla_se_adelanta_a_la_adjudicacion_de_la_sucesora():
    """La antigüedad se mide hasta el ancla, no hasta el vencimiento.

    Ancla = ``min(fin, adjudicación de la sucesora)`` = 2024-08-15; el primer
    contrato de la relación es de 2022-01-01, así que son ~31.9 meses y no los
    ~36.8 que salían midiendo hasta el vencimiento (2025-01-10).
    """
    par = _par_con_sucesora_anticipada(empresa_sucesora=7)
    antiguedad = par.features["antiguedad_relacion_meses"]
    assert antiguedad == pytest.approx(957 / 30.0, abs=0.01)
    assert antiguedad is not None and antiguedad < 36.0


def test_la_sucesora_multilote_tampoco_entra_por_su_lote_mas_antiguo():
    """Defensa en profundidad: la exclusión es por id, no solo por fecha.

    Un expediente multi-lote tiene varias filas en ``adjudicaciones``. El ancla
    corta en la fila que se eligió como sucesora, pero otra fila del MISMO
    expediente puede tener fecha anterior y colarse igual. Se excluye por
    ``licitacion_id``.
    """

    def _pares(empresa_sucesora: int) -> rl.ParRetencion:
        adjudicaciones = [
            _adj("OLD", empresa_id=7, fecha_adj="2022-01-01"),
            _adj("C1", empresa_id=7, fecha_adj="2023-01-10", fecha_fin="2025-01-10"),
            # Dos lotes del mismo expediente sucesor, adjudicados en días
            # distintos: el ancla cae en el más cercano al vencimiento.
            _adj("C1-SIG", empresa_id=empresa_sucesora, fecha_adj="2024-08-01"),
            _adj("C1-SIG", empresa_id=empresa_sucesora, fecha_adj="2024-08-15"),
        ]
        pares = _construir(adjudicaciones)
        assert len(pares) == 1
        return pares[0]

    retenido = _pares(empresa_sucesora=7)
    perdido = _pares(empresa_sucesora=99)

    assert (retenido.label, perdido.label) == (1, 0)
    assert retenido.features["contratos_previos_organo"] == 2.0
    for columna in ("contratos_previos_organo", "antiguedad_relacion_meses", "cuota_segmento"):
        assert retenido.features[columna] == perdido.features[columna], (
            f"{columna} depende del label: fuga de etiqueta"
        )


# ---------------------------------------------------------------------------
# Ventana asimétrica
# ---------------------------------------------------------------------------


def test_una_adjudicacion_muy_anterior_al_fin_no_es_sucesora():
    """12 meses antes del vencimiento no es una renovación, es otro contrato.

    Con la ventana simétrica de ±18 meses cualquier adjudicación del segmento
    en el año anterior al vencimiento se etiquetaba como sucesora.
    """
    adjudicaciones = [
        _adj("C1", empresa_id=7, fecha_adj="2022-01-10", fecha_fin="2025-01-10"),
        _adj("PARALELO", empresa_id=7, fecha_adj="2024-01-05"),
    ]
    assert _construir(adjudicaciones) == []


def test_la_ventana_hacia_adelante_sigue_siendo_de_18_meses():
    adjudicaciones = [
        _adj("C1", empresa_id=7, fecha_adj="2022-01-10", fecha_fin="2025-01-10"),
        _adj("C1-SIG", empresa_id=7, fecha_adj="2026-05-01"),  # ~16 meses después
    ]
    pares = _construir(adjudicaciones)
    assert [p.sucesor_id for p in pares] == ["C1-SIG"]


def test_los_margenes_de_la_ventana_son_configurables():
    """El margen de anticipación es un parámetro, no un número mágico."""
    adjudicaciones = [
        _adj("C1", empresa_id=7, fecha_adj="2022-01-10", fecha_fin="2025-01-10"),
        _adj("PARALELO", empresa_id=7, fecha_adj="2024-01-05"),
    ]
    pares = _construir(adjudicaciones, anticipacion_meses=18)
    assert [p.sucesor_id for p in pares] == ["PARALELO"]


# ---------------------------------------------------------------------------
# CPV-4 en el par (clave de segmento del baseline de scoring)
# ---------------------------------------------------------------------------


def test_el_par_expone_el_cpv4_con_el_que_se_segmenta():
    par = _par_con_sucesora_anticipada(empresa_sucesora=7)
    assert par.cpv4 == "7200"
    assert normalize_organo(par.organo) == normalize_organo(_ORGANO)
