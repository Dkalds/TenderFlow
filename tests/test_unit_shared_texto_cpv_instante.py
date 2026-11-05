"""Los helpers que sustituyen a las copias duplicadas de ``services/``.

``shared.texto.sin_tildes``, ``shared.cpv.cpv4`` y ``shared.dates.instante_utc``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from shared.cpv import cpv4
from shared.dates import instante_utc
from shared.texto import sin_tildes


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Administración", "Administracion"),
        ("PINGÜINO", "PINGUINO"),
        # NFKD también pliega los de compatibilidad, que NFD dejaba pasar.
        ("1º ﬁnal", "1o final"),
        ("", ""),
    ],
)
def test_sin_tildes(texto, esperado):
    assert sin_tildes(texto) == esperado


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("72267100-0", "7226"),
        (" 72200000", "7220"),
        (72200000, "7220"),
        ("722", None),
        ("ABCD1234", None),
        ("".join(map(chr, (0x667, 0x662, 0x662, 0x660))) + "0000", None),  # dígitos árabes
        (float("nan"), None),
        (None, None),
        ("", None),
    ],
)
def test_cpv4(valor, esperado):
    assert cpv4(valor) == esperado


_MEDIODIA = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "valor",
    [
        "2026-09-16T12:00:00Z",
        "2026-09-16T12:00:00+00:00",
        "2026-09-16 12:00:00+00",  # now()::text de Postgres
        "2026-09-16T14:00:00+02:00",
        "2026-09-16T12:00:00",  # sin offset vale UTC
        datetime(2026, 9, 16, 12, 0),
        datetime(2026, 9, 16, 14, 0, tzinfo=timezone(timedelta(hours=2))),
    ],
)
def test_instante_utc_lee_el_mismo_instante(valor):
    resultado = instante_utc(valor)
    assert resultado == _MEDIODIA
    assert resultado is not None and resultado.utcoffset() == timedelta(0)


def test_instante_utc_fecha_sola_es_medianoche_utc():
    assert instante_utc("2026-09-16") == datetime(2026, 9, 16, tzinfo=UTC)


@pytest.mark.parametrize("valor", ["", "   ", "ayer", None, 17, b"2026-09-16"])
def test_instante_utc_ilegible_es_none(valor):
    assert instante_utc(valor) is None
