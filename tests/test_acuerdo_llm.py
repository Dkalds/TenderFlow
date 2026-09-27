"""¿Se pueden usar las etiquetas del LLM para entrenar? (spec §3.5).

Solo si coinciden con las humanas: ≥ 0,90 en «¿es TI?» y ≥ 0,80 de F1 en cada
familia con soporte suficiente en el golden.
"""

from __future__ import annotations

from services.ml.acuerdo_llm import RespuestaLlm, medir_acuerdo
from services.ml.golden_ti import EjemploGoldenTi


def _golden(id_: str, es_ti: bool, familias: tuple[str, ...] = ()) -> EjemploGoldenTi:
    return EjemploGoldenTi(
        id_externo=id_,
        fuente="pscp",
        fecha="2026-09-01",
        titulo="t",
        descripcion="",
        cpv=None,
        es_ti=es_ti,
        familias=familias,
        fabricantes=(),
        etiquetado_por="humano",
        etiquetado_at="2026-09-28",
        split="holdout",
    )


def test_acuerdo_perfecto_es_apto() -> None:
    golden = [_golden(f"G{i}", True, ("DESARROLLO",)) for i in range(10)]
    respuestas = {g.id_externo: RespuestaLlm(True, frozenset({"DESARROLLO"})) for g in golden}
    acuerdo = medir_acuerdo(golden, respuestas)
    assert acuerdo.acuerdo_es_ti == 1.0
    assert acuerdo.f1_por_familia == {"DESARROLLO": 1.0}
    assert acuerdo.apto is True


def test_por_debajo_del_umbral_de_es_ti_no_es_apto() -> None:
    golden = [_golden(f"G{i}", True) for i in range(10)]
    respuestas = {g.id_externo: RespuestaLlm(i >= 2, frozenset()) for i, g in enumerate(golden)}
    acuerdo = medir_acuerdo(golden, respuestas)
    assert acuerdo.acuerdo_es_ti == 0.8
    assert acuerdo.apto is False
    assert any("es_ti" in m for m in acuerdo.motivos)


def test_una_familia_con_poco_soporte_no_decide() -> None:
    golden = [_golden("G0", True, ("GIS",))] + [_golden(f"G{i}", True) for i in range(1, 10)]
    respuestas = {g.id_externo: RespuestaLlm(True, frozenset()) for g in golden}
    acuerdo = medir_acuerdo(golden, respuestas)
    assert "GIS" in acuerdo.sin_soporte
    assert "GIS" not in acuerdo.f1_por_familia
    assert acuerdo.apto is True


def test_sin_respuesta_del_llm_no_cuenta() -> None:
    golden = [_golden("G0", True), _golden("G1", False)]
    respuestas = {"G0": RespuestaLlm(True, frozenset()), "G1": RespuestaLlm(None, frozenset())}
    acuerdo = medir_acuerdo(golden, respuestas)
    assert acuerdo.n_comparables == 1
