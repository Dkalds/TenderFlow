"""Tests de la caché de las señales agregadas del scoring (sin BD).

Fijan la parte del ítem "el contexto de scoring escanea la tabla entera en
frío" que no es un índice: la media de ofertas por CPV-4 costaba 9,5 s en
producción (2026-08-11) —hash join de 1,6 M adjudicaciones contra un Parallel
Seq Scan de ``licitaciones``, 59,6 s el peor request en frío— y es un agregado
global que **no depende de la fila puntuada**. Lo que estos tests protegen es
que no se vuelva a pagar una vez por request:

1. una sola carga para N puntuaciones,
2. la ingesta la invalida —una caché que no se invalida es peor que ninguna,
   porque el Radar mostraría un mercado congelado—,
3. un fallo de BD degrada en vez de subir al handler,
4. y el valor degradado no se queda pegado el TTL entero.

Los percentiles de importe ya tienen sus propios tests en
``test_scoring_signals_unit.py``; aquí solo se cubre lo que comparten por la
caché.
"""

from __future__ import annotations

from unittest.mock import patch

import services.analytics.scoring_signals as sig_mod
from services._data_cache import _DEFAULT_TTL, _DEGRADED_TTL, SignalAwareCache
from services.analytics.scoring_signals import (
    SIGNAL_ERROR,
    SIGNAL_OK,
    SIGNAL_VACIA,
    clear_scoring_signals_cache,
    load_competencia_stats,
)

# Forma de lo que devuelve ``AggregateRepository.competencia_ofertas_por_cpv4``:
# (filas cpv4/media_ofertas, media global de fallback).
_AGREGADO = ([{"cpv4": "7220", "media_ofertas": 4.5}, {"cpv4": "3020", "media_ofertas": 2.0}], 3.1)


def _patch_agregado(**kwargs):
    """Sustituye la consulta cara del repositorio (ADR-022: el SQL vive en db/)."""
    return patch.object(sig_mod._repo, "competencia_ofertas_por_cpv4", **kwargs)


def test_el_agregado_de_competencia_se_pide_una_sola_vez_para_n_puntuaciones():
    """El coste es por ventana de caché, no por request del Radar."""
    clear_scoring_signals_cache()
    with _patch_agregado(return_value=_AGREGADO) as mock_agg:
        for _ in range(5):
            stats = load_competencia_stats()

    assert mock_agg.call_count == 1
    assert stats.status == SIGNAL_OK
    assert stats.media_por_cpv4 == {"7220": 4.5, "3020": 2.0}
    assert stats.media_global == 3.1


def test_la_senal_de_ingesta_invalida_el_agregado(monkeypatch):
    """Tras un scrape, la media de ofertas se recalcula.

    Sin esto el Radar enseñaría un mercado congelado hasta que expirase el TTL,
    que es un fallo peor que no cachear: el número parece vivo y no lo está.
    """
    clear_scoring_signals_cache()
    reloj = {"ts": 100.0}
    monkeypatch.setattr("services._data_cache.get_signal_timestamp", lambda: reloj["ts"])

    with _patch_agregado(return_value=_AGREGADO) as mock_agg:
        load_competencia_stats()
        load_competencia_stats()
        assert mock_agg.call_count == 1

        # Llega una ingesta: la señal avanza.
        reloj["ts"] = 200.0
        load_competencia_stats()
        assert mock_agg.call_count == 2


def test_un_fallo_del_agregado_degrada_en_vez_de_propagar():
    """Un error de BD no puede tumbar el scoring: se puntúa con la señal neutra.

    Mismo precedente que ``BajaModel`` degradando a baseline. ``SIGNAL_ERROR``
    (no ``SIGNAL_VACIA``) para que en los logs se distinga "la BD no tiene esa
    historia" de "la consulta se rompió".
    """
    clear_scoring_signals_cache()
    with _patch_agregado(side_effect=RuntimeError("statement timeout")):
        stats = load_competencia_stats()

    assert stats.status == SIGNAL_ERROR
    assert stats.media_por_cpv4 == {}
    assert stats.media_global is None


def test_el_fallo_no_se_retiene_el_ttl_largo_pero_el_dato_si():
    """Un incidente transitorio no puede congelar la señal diez minutos.

    Se comprueba el TTL efectivo y no el paso del tiempo a propósito: dormir 30 s
    en la suite para observar el reintento no aporta nada que esta aserción no
    fije, y ata el test al reloj de quien lo corre.
    """
    clear_scoring_signals_cache()
    with _patch_agregado(side_effect=RuntimeError("boom")):
        load_competencia_stats()
    assert sig_mod._competencia_cache._effective_ttl == _DEGRADED_TTL

    clear_scoring_signals_cache()
    with _patch_agregado(return_value=_AGREGADO):
        load_competencia_stats()
    assert sig_mod._competencia_cache._effective_ttl == _DEFAULT_TTL


def test_una_bd_sin_historia_no_es_un_fallo_y_conserva_el_ttl_largo():
    """``vacia`` es un hecho estable del dato, no un incidente: TTL normal.

    Reintentarlo cada 30 s en una BD local sin adjudicaciones sería pagar la
    consulta cara para volver a descubrir lo mismo.
    """
    clear_scoring_signals_cache()
    with _patch_agregado(return_value=([], None)):
        stats = load_competencia_stats()

    assert stats.status == SIGNAL_VACIA
    assert sig_mod._competencia_cache._effective_ttl == _DEFAULT_TTL


def test_el_valor_degradado_se_sirve_pero_se_reintenta():
    """Contrato de ``SignalAwareCache.get(degraded=...)``, sin depender del reloj.

    Con ``degraded_ttl=0`` el valor de fallo se entrega igual al llamante (el
    scoring necesita algo con lo que puntuar) pero no se retiene, así que la
    siguiente llamada reintenta; un valor sano sí se cachea.
    """
    intentos: list[str] = []

    def loader() -> str:
        # Falla las dos primeras veces y luego se recupera, como una BD que
        # vuelve tras un pico de carga.
        valor = "error" if len(intentos) < 2 else "ok"
        intentos.append(valor)
        return valor

    cache: SignalAwareCache[str] = SignalAwareCache(ttl=600.0)

    def leer() -> str:
        return cache.get(loader, degraded=lambda v: v == "error", degraded_ttl=0.0)

    assert leer() == "error"
    assert leer() == "error"
    assert leer() == "ok"
    # Ya recuperado: el valor sano sí se retiene y el loader no vuelve a correr.
    assert leer() == "ok"
    assert intentos == ["error", "error", "ok"]
