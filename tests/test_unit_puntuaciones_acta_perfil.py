"""Dónde puntúa un competidor según las actas: la agregación pura, sin BD.

``resumir_por_criterio`` convierte las filas de un licitador en su media de
puntos de precio y técnicos por acta. Lo que se fija aquí es lo que haría
mentir a la cifra: que un acta grande pese más que diez pequeñas, que cuente
una en que quedó excluida, o que se publique una media con una o dos actas.
"""

from __future__ import annotations

from db.repositories.puntuaciones_acta import PuntuacionDeLicitador
from services.puntuaciones_acta import MIN_ACTAS_PERFIL, resumir_por_criterio


def _fila(
    licitacion: str,
    *,
    puntos: float | None,
    maximo: float | None,
    es_precio: bool | None,
    lote: str | None = None,
    excluida: bool = False,
) -> PuntuacionDeLicitador:
    return {
        "licitacion_id": licitacion,
        "lote_numero": lote,
        "puntos": puntos,
        "puntos_max": maximo,
        "es_precio": es_precio,
        "excluida": excluida,
    }


def _acta(
    licitacion: str,
    precio: tuple[float, float],
    tecnica: tuple[float, float],
    *,
    lote: str | None = None,
    excluida: bool = False,
) -> list[PuntuacionDeLicitador]:
    return [
        _fila(licitacion, puntos=p, maximo=m, es_precio=es_precio, lote=lote, excluida=excluida)
        for (p, m), es_precio in ((precio, True), (tecnica, False))
    ]


def test_sin_filas_no_hay_perfil() -> None:
    assert resumir_por_criterio([]) is None


def test_cada_acta_pesa_lo_mismo() -> None:
    """Media de porcentajes por acta: 1.000 puntos no tapan a dos actas de 100."""
    filas = [
        *_acta("A", precio=(1000, 1000), tecnica=(0, 1000)),
        *_acta("B", precio=(0, 100), tecnica=(100, 100)),
        *_acta("C", precio=(50, 100), tecnica=(50, 100)),
    ]

    perfil = resumir_por_criterio(filas)

    assert perfil is not None
    assert perfil.actas == 3
    assert perfil.precio.pct_medio == 50.0
    assert perfil.tecnica.pct_medio == 50.0
    assert perfil.min_actas == MIN_ACTAS_PERFIL


def test_por_debajo_del_minimo_no_publica_la_media() -> None:
    filas = [
        *_acta("A", precio=(55, 55), tecnica=(20, 45)),
        *_acta("B", precio=(50, 55), tecnica=(30, 45)),
    ]

    perfil = resumir_por_criterio(filas)

    assert perfil is not None
    assert (perfil.precio.actas, perfil.precio.pct_medio) == (2, None)
    assert (perfil.tecnica.actas, perfil.tecnica.pct_medio) == (2, None)


def test_un_acta_en_que_quedo_excluida_se_cuenta_pero_no_puntua() -> None:
    filas = [
        *_acta("A", precio=(55, 55), tecnica=(45, 45)),
        *_acta("B", precio=(55, 55), tecnica=(45, 45)),
        *_acta("C", precio=(55, 55), tecnica=(45, 45)),
        *_acta("D", precio=(0, 55), tecnica=(0, 45), excluida=True),
    ]

    perfil = resumir_por_criterio(filas)

    assert perfil is not None
    assert (perfil.actas, perfil.excluida) == (4, 1)
    assert perfil.precio.pct_medio == 100.0


def test_cada_lote_es_un_acta_y_lo_que_no_se_clasifica_no_entra() -> None:
    filas = [
        *_acta("A", precio=(10, 20), tecnica=(5, 10), lote="1"),
        *_acta("A", precio=(20, 20), tecnica=(10, 10), lote="2"),
        *_acta("B", precio=(15, 20), tecnica=(5, 10)),
        # Sin clasificar como precio o técnica, y sin máximo: fuera de las medias.
        _fila("B", puntos=99, maximo=100, es_precio=None),
        _fila("B", puntos=7, maximo=None, es_precio=True),
    ]

    perfil = resumir_por_criterio(filas)

    assert perfil is not None
    assert perfil.actas == 3
    assert perfil.precio.pct_medio == 75.0
    assert perfil.tecnica.pct_medio == round((50 + 100 + 50) / 3, 1)
