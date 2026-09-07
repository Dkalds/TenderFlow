"""S2.1 — el cierre de una oportunidad se propone por NIF, y no se decide solo."""

from __future__ import annotations

import pytest

from services.pursuit_awards import IdentidadFiscal, sugerir_resultado
from shared.dto import PursuitAdjudicacionDetectada, PursuitAdjudicatario

# NIF de ejemplo con el formato fiscal español (letra + 8 dígitos). Van como
# constantes y no en línea porque `ruff format` reflujo las expresiones y dejó
# el pragma separado de su literal; detect-secrets los lee como cadenas
# hexadecimales de alta entropía y hay que marcarlos donde estén.
_NIF_AJENO = "A87654321"  # pragma: allowlist secret
_NIF_PROPIO = "B12345678"  # pragma: allowlist secret

_PROPIA = IdentidadFiscal(
    nifs=frozenset({_NIF_PROPIO}), empresa_ids=frozenset({41})
)  # pragma: allowlist secret


def _adjudicatario(nif: str | None) -> PursuitAdjudicatario:
    return PursuitAdjudicatario(nombre="Adjudicataria SL", nif=nif)


def test_nif_de_la_organizacion_propone_won() -> None:
    assert (
        sugerir_resultado([_adjudicatario(_NIF_PROPIO)], _PROPIA) == "won"
    )  # pragma: allowlist secret


def test_nif_distinto_propone_lost() -> None:
    assert (
        sugerir_resultado([_adjudicatario(_NIF_AJENO)], _PROPIA) == "lost"
    )  # pragma: allowlist secret


def test_sin_nifs_declarados_no_propone_nada() -> None:
    """``None`` es «no lo sé», nunca «no ganó»: es el caso previo a S2.1."""
    assert (
        sugerir_resultado([_adjudicatario(_NIF_AJENO)], IdentidadFiscal()) is None
    )  # pragma: allowlist secret


def test_adjudicatario_sin_nif_publicado_no_propone_nada() -> None:
    """La fuente no siempre publica el NIF; comparar nombres sería inventar."""
    assert sugerir_resultado([_adjudicatario(None)], _PROPIA) is None


def test_ute_con_la_organizacion_dentro_propone_won() -> None:
    """En una UTE basta con estar: el expediente lo ganó también la propia casa."""
    adjudicatarios = [
        _adjudicatario(_NIF_AJENO),
        _adjudicatario(_NIF_PROPIO),
    ]  # pragma: allowlist secret
    assert sugerir_resultado(adjudicatarios, _PROPIA) == "won"


@pytest.mark.parametrize("escrito", ["b-12345678", "B 12345678", "B.12345678"])
def test_el_nif_publicado_se_normaliza_antes_de_comparar(escrito: str) -> None:
    """La fuente escribe el NIF con guiones y puntos; la tabla lo guarda plano."""
    assert sugerir_resultado([_adjudicatario(escrito)], _PROPIA) == "won"


def test_identidad_reconoce_por_empresa_id_canonico() -> None:
    """El enlace con el maestro es lo que excluye a la casa de «contra quién».

    La analítica competitiva agrupa por ``empresa_id`` (grupos, UTEs, variantes
    de nombre), así que la exclusión tiene que poder hacerse por esa clave y no
    solo por el NIF que trae cada fila.
    """
    assert _PROPIA.reconoce(empresa_ids=[41]) is True
    assert _PROPIA.reconoce(empresa_ids=[99]) is False
    assert _PROPIA.reconoce(nifs=["B-12345678"]) is True
    assert _PROPIA.reconoce(nifs=[None], empresa_ids=[None]) is False


def test_una_organizacion_sin_nifs_no_reconoce_a_nadie() -> None:
    """Sin identidad declarada no se puede excluir a nadie: se listan todos."""
    vacia = IdentidadFiscal()
    assert vacia.conocida is False
    assert vacia.reconoce(nifs=[_NIF_PROPIO], empresa_ids=[41]) is False  # pragma: allowlist secret


def test_el_dto_admite_el_resultado_sugerido_y_por_defecto_no_propone() -> None:
    """Campo aditivo: una ficha construida sin él sigue validando."""
    sin_propuesta = PursuitAdjudicacionDetectada(cierre_pendiente=True)
    assert sin_propuesta.resultado_sugerido is None
    con_propuesta = PursuitAdjudicacionDetectada(cierre_pendiente=True, resultado_sugerido="won")
    assert con_propuesta.resultado_sugerido == "won"
