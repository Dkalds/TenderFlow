"""El calendario del seed no caduca, y sus adjudicaciones no se descuelgan.

Desde #162 el universo del Radar exige *plazo vivo*: sin ``fecha_limite`` en el
futuro no hay oportunidad que puntuar. Con las fechas del seed escritas como
literales fijos eso convirtió a ``scripts/seed_dev.py`` en una bomba de
relojería, y explotó — venció el plazo de ``SEED-2026-008`` y
``e2e/navigation.spec.ts:54`` ("el radar lista una licitación real del seed")
empezó a fallar en todos los PRs sin que nadie tocara una línea de código.

#166 lo arregló pasando las fechas de las licitaciones a ``_dia(offset)``, pero
no dejó ningún test, y las adjudicaciones se quedaron con literal fijo: sus tres
licitaciones ya se movían con el calendario y ellas no, así que se separaban un
día más cada día hasta adjudicar contratos antes de que cerrara su propio plazo.

Estos tests fijan las propiedades que el E2E da por supuestas, pero sin
navegador ni BD: se apoyan en las filas ya construidas, corren en milisegundos y
fallan el día que alguien vuelva a clavar una fecha.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from scripts.seed_dev import (
    _SAMPLE_ADJUDICACIONES,
    _SAMPLE_LICITACIONES,
    _build_adjudicacion,
    _build_licitacion,
    _dia,
)

# Estados terminales: el Radar los descarta antes de mirar el plazo.
_TERMINALES = {"ADJ", "RES", "ANUL"}

# La licitación que busca el spec del Radar (`SEED_LICITACION.tituloRadar`).
_LA_DEL_SPEC = "SEED-2026-008"


def _hoy() -> date:
    """En UTC, igual que ``_dia()``: en hora local el corte podría bailar un día."""
    return datetime.now(UTC).date()


def _construidas() -> list:
    return [_build_licitacion(d) for d in _SAMPLE_LICITACIONES]


def _es_puntuable(fila) -> bool:
    """Universo del Radar: estado no terminal **y** plazo por vencer."""
    if fila.estado in _TERMINALES:
        return False
    return bool(fila.fecha_limite) and date.fromisoformat(fila.fecha_limite) >= _hoy()


def test_las_doce_admitidas_tienen_plazo_vivo():
    """Las 12 ``ADM`` son puntuables, que es la premisa de `web/e2e/fixtures.ts`.

    Ese fixture describe la licitación del spec como una de las 12 que el Radar
    puntúa. Si alguna ADM deja de estar viva, el ranking encoge y la afirmación
    deja de ser cierta.
    """
    filas = _construidas()
    admitidas = [f for f in filas if f.estado not in _TERMINALES]
    puntuables = [f for f in filas if _es_puntuable(f)]

    assert len(filas) == 15, "el seed siembra 15 expedientes (SEED_TOTAL_LICITACIONES)"
    assert len(admitidas) == 12
    assert len(puntuables) == 12, (
        "toda ADM debe tener plazo vivo; vencidas: "
        f"{[f.id_externo for f in admitidas if not _es_puntuable(f)]}"
    )


def test_la_licitacion_del_spec_e2e_esta_viva():
    """Regresión directa del fallo: sin esta fila viva, el spec del Radar cae."""
    fila = next(f for f in _construidas() if f.id_externo == _LA_DEL_SPEC)

    assert _es_puntuable(fila), (
        f"{_LA_DEL_SPEC} debe ser puntuable: es la que busca e2e/navigation.spec.ts:54 en el Radar"
    )


def test_las_adjudicadas_tienen_el_plazo_ya_vencido():
    """Una adjudicada con plazo por vencer sería incoherente."""
    adjudicadas = [f for f in _construidas() if f.estado in _TERMINALES]

    assert len(adjudicadas) == 3
    for fila in adjudicadas:
        assert date.fromisoformat(fila.fecha_limite) < _hoy(), (
            f"{fila.id_externo} está adjudicada pero su plazo aún no ha vencido"
        )


def test_publicacion_siempre_antes_del_plazo():
    """Ningún expediente se publica después de su propio plazo."""
    for fila in _construidas():
        assert date.fromisoformat(fila.fecha_publicacion) < date.fromisoformat(fila.fecha_limite), (
            f"{fila.id_externo} se publica después de su propio plazo"
        )


def test_cada_adjudicacion_cae_despues_del_plazo_de_su_licitacion():
    """El hueco que dejó #166: la adjudicación tiene que seguir a su licitación.

    Las tres licitaciones ``ADJ`` pasaron a ``_dia()`` y sus adjudicaciones se
    quedaron con literal fijo, así que se descolgaban un día más cada día. El
    2026-08-12 ya se adjudicaban 37, 31 y 33 días **antes** de que cerrara el
    plazo al que se presentaban.
    """
    plazos = {f.id_externo: f.fecha_limite for f in _construidas()}

    for d in _SAMPLE_ADJUDICACIONES:
        adj = _build_adjudicacion(d)
        plazo = date.fromisoformat(plazos[d["licitacion_id"]])
        fecha = date.fromisoformat(adj.fecha_adjudicacion)
        assert fecha > plazo, (
            f"{d['licitacion_id']} se adjudica el {fecha}, antes de que su plazo cerrara el {plazo}"
        )


def test_las_adjudicaciones_ya_ocurrieron():
    """Adjudicar en el futuro tampoco es un dato posible."""
    for d in _SAMPLE_ADJUDICACIONES:
        adj = _build_adjudicacion(d)
        assert date.fromisoformat(adj.fecha_adjudicacion) < _hoy(), (
            f"{d['licitacion_id']} se adjudica en el futuro"
        )


@pytest.mark.parametrize("dentro_de_dias", [0, 90, 400, 3650])
def test_dia_deriva_del_reloj_asi_que_el_corpus_no_caduca(monkeypatch, dentro_de_dias):
    """Lo que hace que esto no vuelva a pasar: las fechas se calculan, no se fijan.

    Se adelanta el reloj y ``_dia()`` lo sigue. Con los literales de antes, a
    +90 días no quedaba una sola licitación viva y el Radar salía vacío.
    """
    futuro = datetime.now(UTC) + timedelta(days=dentro_de_dias)

    class _RelojCongelado(datetime):
        @classmethod
        def now(cls, tz=None):
            return futuro

    monkeypatch.setattr("scripts.seed_dev.datetime", _RelojCongelado)

    assert _dia(0) == futuro.date().isoformat()
    assert _dia(36) == (futuro.date() + timedelta(days=36)).isoformat()
    assert _dia(-5) == (futuro.date() - timedelta(days=5)).isoformat()


def test_el_corpus_guarda_distancias_no_fechas():
    """Cada fila conserva su distancia a hoy, que es lo que lo hace estable.

    Complementa al test de arriba: aquel comprueba que ``_dia()`` sigue al
    reloj; éste, que las tablas se construyen con él y no con literales, mirando
    los signos de los offsets sobre las filas ya materializadas.
    """
    hoy = _hoy()
    offsets = {
        f.id_externo: ((date.fromisoformat(f.fecha_limite) - hoy).days, f.estado)
        for f in _construidas()
    }

    futuros = [i for i, (d, e) in offsets.items() if e not in _TERMINALES and d >= 0]
    pasados = [i for i, (d, e) in offsets.items() if e in _TERMINALES and d < 0]

    assert len(futuros) == 12, f"ADM con plazo vivo: {sorted(futuros)}"
    assert len(pasados) == 3, f"ADJ con plazo vencido: {sorted(pasados)}"
