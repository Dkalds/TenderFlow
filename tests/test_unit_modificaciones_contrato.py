"""Lo que un contrato acaba costando y cuánto amplía un órgano sus contratos (v180, CU-38).

Reglas de ``services/modificaciones.py`` sin BD: el repositorio se sustituye por
filas como las que devuelve su ``SELECT``.
"""

from __future__ import annotations

from typing import Any

import pytest

from services import modificaciones as servicio


def _fila(
    *,
    licitacion_id: str = "placsp:O:E1",
    lote: str | None = None,
    contrato: str | None = "C1",
    numero: str = "1",
    final: float | None = None,
    base: str | None = "sin_iva",
) -> dict[str, Any]:
    return {
        "clave": f"{licitacion_id}#{contrato}#{numero}",
        "fuente": "placsp",
        "numero": numero,
        "contrato_ref": contrato,
        "lote_numero": lote,
        "fecha_publicacion": None,
        "motivo_codigo": None,
        "motivo": None,
        "descripcion": None,
        "importe_modificacion": None,
        "importe_modificacion_base": None,
        "importe_final": final,
        "importe_final_base": base if final is not None else None,
        "importe_aviso": None,
        "importe_aviso_base": None,
        "moneda": "EUR",
        "plazo_modificacion": None,
        "plazo_final": None,
        "plazo_unidad": None,
        "aviso_original": None,
        "url": None,
        "licitacion_id": licitacion_id,
    }


def _adj(licitacion_id: str, lote: str | None, importe: float | None) -> dict[str, Any]:
    return {"licitacion_id": licitacion_id, "lote_numero": lote, "importe_adjudicado": importe}


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, Any]]]:
    datos: dict[str, list[dict[str, Any]]] = {"propias": [], "organo": [], "adjudicado": []}
    monkeypatch.setattr(servicio.repo, "de_licitacion", lambda _id: datos["propias"])
    monkeypatch.setattr(servicio.repo, "del_organo_de", lambda _id: datos["organo"])
    monkeypatch.setattr(servicio.repo, "adjudicado_por_lote", lambda _ids: datos["adjudicado"])
    return datos


def test_el_coste_final_es_el_de_la_ultima_modificacion_del_contrato(
    repo: dict[str, list[dict[str, Any]]],
) -> None:
    # Caso real del fixture 25: dos prórrogas del lote 1, 188.800,89 € cada una.
    repo["propias"] = [
        _fila(lote="1", numero="1", final=377601.79),
        _fila(lote="1", numero="2", final=566402.68),
    ]
    repo["adjudicado"] = [_adj("placsp:O:E1", "1", 188800.89)]

    resultado = servicio.modificaciones_de_licitacion("placsp:O:E1")

    assert len(resultado.items) == 2
    [coste] = resultado.costes
    assert (coste.lote_numero, coste.adjudicado, coste.final) == ("1", 188800.89, 566402.68)
    assert coste.variacion_pct == 200.0
    assert coste.base == "sin_iva"


def test_sin_adjudicado_publicado_no_hay_coste(repo: dict[str, list[dict[str, Any]]]) -> None:
    repo["propias"] = [_fila(final=1000.0)]
    repo["adjudicado"] = [_adj("placsp:O:E1", None, None)]

    assert servicio.modificaciones_de_licitacion("placsp:O:E1").costes == []


def test_un_final_que_no_es_sin_iva_no_se_compara(repo: dict[str, list[dict[str, Any]]]) -> None:
    repo["propias"] = [_fila(final=1210.0, base="desconocido")]
    repo["adjudicado"] = [_adj("placsp:O:E1", None, 1000.0)]

    assert servicio.modificaciones_de_licitacion("placsp:O:E1").costes == []


def test_un_lote_con_varios_importes_adjudicados_no_tiene_coste(
    repo: dict[str, list[dict[str, Any]]],
) -> None:
    # Un marco con varios adjudicatarios, cada uno por su parte.
    repo["propias"] = [_fila(lote="2", final=900.0)]
    repo["adjudicado"] = [_adj("placsp:O:E1", "2", 500.0), _adj("placsp:O:E1", "2", 400.0)]

    assert servicio.modificaciones_de_licitacion("placsp:O:E1").costes == []


def test_un_lote_con_modificaciones_de_varios_contratos_no_tiene_coste(
    repo: dict[str, list[dict[str, Any]]],
) -> None:
    repo["propias"] = [
        _fila(lote="1", contrato="C1", final=1100.0),
        _fila(lote="1", contrato="C2", final=1200.0),
    ]
    repo["adjudicado"] = [_adj("placsp:O:E1", "1", 1000.0)]

    assert servicio.modificaciones_de_licitacion("placsp:O:E1").costes == []


def test_el_organo_por_debajo_de_la_muestra_minima_no_da_cifra(
    repo: dict[str, list[dict[str, Any]]],
) -> None:
    n = servicio.MUESTRA_MINIMA_ORGANO - 1
    repo["organo"] = [_fila(licitacion_id=f"placsp:O:E{i}", final=1100.0) for i in range(n)]
    repo["adjudicado"] = [_adj(f"placsp:O:E{i}", None, 1000.0) for i in range(n)]

    organo = servicio.modificaciones_de_licitacion("placsp:O:E0").organo

    assert organo.n == n
    assert organo.mediana_pct is None
    assert organo.muestra_minima == servicio.MUESTRA_MINIMA_ORGANO


def test_el_organo_con_muestra_da_la_mediana_de_sus_contratos(
    repo: dict[str, list[dict[str, Any]]],
) -> None:
    n = servicio.MUESTRA_MINIMA_ORGANO
    # Variaciones 0 %, 10 %, …, 90 %: mediana 45 %.
    repo["organo"] = [
        _fila(licitacion_id=f"placsp:O:E{i}", final=1000.0 * (1 + i / 10)) for i in range(n)
    ]
    repo["adjudicado"] = [_adj(f"placsp:O:E{i}", None, 1000.0) for i in range(n)]

    organo = servicio.modificaciones_de_licitacion("placsp:O:E0").organo

    assert organo.n == n
    assert organo.mediana_pct == 45.0


def test_un_numero_repetido_en_el_mismo_lote_no_tiene_coste(
    repo: dict[str, list[dict[str, Any]]],
) -> None:
    # Dos lotes que comparten `ContractID` y no dicen cuál es cuál (S-06722-2023).
    repo["propias"] = [_fila(numero="1", final=1100.0), _fila(numero="1", final=900.0)]
    repo["adjudicado"] = [_adj("placsp:O:E1", None, 1000.0)]

    assert servicio.modificaciones_de_licitacion("placsp:O:E1").costes == []


def test_enlazar_por_aviso_original_cadena_y_referencia(monkeypatch: pytest.MonkeyPatch) -> None:
    filas = [
        {"clave": "ted:1-2026", "aviso_original": "9-2025", "expediente_ref": None,
         "organo": "Ayto", "url": None},
        {"clave": "ted:2-2026", "aviso_original": None, "expediente_ref": "EXP/1",
         "organo": "Ayto", "url": None},
        {"clave": "ted:3-2026", "aviso_original": "8-2025", "expediente_ref": None,
         "organo": "Ayto", "url": None},
        # La segunda modificación de una cadena cita el UUID (con versión) de la primera.
        {"clave": "ted:4-2026", "aviso_original": "be80e249-3d04-4f02-91f7-761b9ad0ed4f-01",
         "expediente_ref": None, "organo": "Ayto", "url": None},
    ]  # fmt: skip
    escritos: list[tuple[str, str, str]] = []
    monkeypatch.setattr(servicio.repo, "sin_enlazar", lambda **_k: filas)
    monkeypatch.setattr(
        servicio.repo, "expedientes_de_avisos", lambda ids: {"ted:9-2025": "placsp:O:EXP/9"}
    )
    monkeypatch.setattr(
        servicio.repo,
        "expedientes_de_avisos_previos",
        lambda ids: {"be80e249-3d04-4f02-91f7-761b9ad0ed4f": "placsp:O:EXP/4"} if ids else {},
    )
    monkeypatch.setattr(
        servicio,
        "expedientes_por_referencia",
        lambda avisos: {"ted:2-2026": "placsp:O:EXP/1"} if "ted:2-2026" in avisos else {},
    )
    monkeypatch.setattr(servicio.repo, "enlazar", lambda e: escritos.extend(e) or len(e))

    assert servicio.enlazar_pendientes(fuente="ted") == 3
    assert escritos == [
        ("ted:1-2026", "placsp:O:EXP/9", "aviso_original"),
        ("ted:4-2026", "placsp:O:EXP/4", "aviso_original"),
        ("ted:2-2026", "placsp:O:EXP/1", "referencia"),
    ]
