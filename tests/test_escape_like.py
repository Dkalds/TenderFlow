"""Un texto de usuario con ``\\``, ``%`` y ``_`` se busca como texto.

Postgres usa la barra invertida como carácter de escape de ``LIKE``/``ILIKE``
aunque la sentencia no lleve ``ESCAPE``. Escapar solo los dos comodines dejaba
la barra del usuario haciendo de escape: ``C:\\100`` llegaba como ``C:\\100`` y
Postgres leía «un 1 literal», así que la búsqueda no casaba con lo que se había
escrito y sí con la misma cadena **sin** la barra. Y un texto acabado en barra,
puesto al final del patrón, era un error de Postgres («LIKE pattern must not
end with escape character»): un 500.

Había cuatro copias del escapado y dos lo hacían mal. Las comprobaciones con BD
son las que importan —el patrón solo se puede juzgar ejecutándolo—: siembran
cuatro filas que se distinguen justo en esos tres caracteres y exigen que cada
búsqueda devuelva exactamente la que contiene el literal.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

LITERAL = r"C:\100%_x"

# Una fila por forma de fallar. Solo ``LIT`` contiene el literal; cada una de
# las otras es lo que casaría si uno de los tres caracteres no se escapara.
_TEXTOS = {
    "LIT": r"C:\100%_x",
    # Lo que casaba con la barra sin escapar: `\1` es «un 1 literal».
    "SIN-BARRA": r"C:100%_x",
    # Lo que casaría con `%` haciendo de comodín.
    "COMODIN-PCT": r"C:\100abc_x",
    # Lo que casaría con `_` haciendo de comodín.
    "COMODIN-GUION": r"C:\100%Zx",
}


# ── El helper, sin BD ───────────────────────────────────────────────────────


def test_la_barra_se_dobla_antes_de_escapar_los_comodines():
    from db.sql_fragments import escape_like

    assert escape_like(r"a\b%c_d") == r"a\\b\%c\_d"
    # En el otro orden, la barra que escapa al `%` saldría doblada: `\\%`.
    assert escape_like("%") == r"\%"


@pytest.mark.parametrize("texto", ["\\", "C:\\", "\\\\", "%\\", "_\\", "a\\\\\\", "SAP\\"])
def test_el_texto_escapado_nunca_deja_una_barra_suelta_al_final(texto):
    """Lo que Postgres rechaza: un patrón que acaba en el carácter de escape."""
    from db.sql_fragments import escape_like

    escapado = escape_like(texto)
    barras_finales = len(escapado) - len(escapado.rstrip("\\"))
    assert barras_finales % 2 == 0


def test_no_vuelve_a_haber_una_segunda_copia_del_escapado():
    """Las copias divergieron una vez; un escapado nuevo se importa, no se teclea."""
    import re
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1]
    paquetes = (
        "api",
        "config",
        "db",
        "llm",
        "observability",
        "scheduler",
        "scraper",
        "services",
        "shared",
    )
    escapa_comodin = re.compile(r"""\.replace\(\s*["']%["']""")
    copias = sorted(
        fichero.relative_to(raiz).as_posix()
        for paquete in paquetes
        for fichero in (raiz / paquete).rglob("*.py")
        if escapa_comodin.search(fichero.read_text(encoding="utf-8"))
    )
    assert copias == ["db/sql_fragments.py"]


# ── Siembra ─────────────────────────────────────────────────────────────────


def _sembrar() -> None:
    from db.upsert import Licitacion, upsert_licitaciones

    cierre = (datetime.now(UTC).date() + timedelta(days=10)).isoformat()
    upsert_licitaciones(
        [
            Licitacion(
                id_externo=id_externo,
                titulo=f"Migración de la ruta {texto} a la nube",
                descripcion="Servicio de migración de ficheros",
                organo_contratacion=f"Ayuntamiento de {texto}",
                cpv=f"{texto}-9",
                estado="PUB",
                fecha_publicacion="2026-01-01T00:00:00+00:00",
                fecha_extraccion="2026-01-01",
                fecha_limite=cierre,
                tecnologia="SAP",
                ccaa="Madrid",
            )
            for id_externo, texto in _TEXTOS.items()
        ]
    )


def _ids(filas: list[dict[str, Any]]) -> set[str]:
    return {str(f["id_externo"]) for f in filas}


# ── db/repositories/agenda.py ───────────────────────────────────────────────


def _senales(**criterios: Any) -> set[str]:
    from db.repositories.agenda import SignalCriteria, signal_rows

    base: dict[str, Any] = {
        "rule_id": 1,
        "nombre": None,
        "keyword": None,
        "cpv": None,
        "min_importe": None,
        "ccaa": None,
    }
    return _ids(
        signal_rows(SignalCriteria(**{**base, **criterios}), user_key="uk", organization_id=1)
    )


def test_agenda_la_keyword_se_busca_como_literal(tmp_db):
    _sembrar()
    assert _senales(keyword=LITERAL) == {"LIT"}


def test_agenda_el_cpv_se_busca_como_prefijo_literal(tmp_db):
    _sembrar()
    assert _senales(cpv=LITERAL) == {"LIT"}


def test_agenda_una_keyword_acabada_en_barra_casa_con_la_barra(tmp_db):
    """``C:\\`` escapaba al ``%`` de cierre: el patrón pedía un ``%`` literal."""
    _sembrar()
    assert _senales(keyword="C:\\") == {"LIT", "COMODIN-PCT", "COMODIN-GUION"}


# ── db/repositories/licitaciones.py ─────────────────────────────────────────

# Cada entrada es un camino distinto hasta un LIKE: SA Core (`_base_filters`,
# `search_advanced`), la rama FTS del listado (`_list_fts`, que arma su propio
# SQL) y las consultas a mano con `ESCAPE '\'`.
_BUSQUEDAS: dict[str, Callable[[Any], set[str]]] = {
    "cursor_q": lambda r: _ids(r.list_cursor(q=LITERAL)),
    "cursor_cpv": lambda r: _ids(r.list_cursor(cpv=LITERAL)),
    "cursor_organo": lambda r: _ids(r.list_cursor(organo=LITERAL)),
    "listado_cpv": lambda r: _ids(r.list_paginated(cpv=LITERAL)[0]),
    "listado_organo": lambda r: _ids(r.list_paginated(organo=LITERAL)[0]),
    "fts_cpv": lambda r: _ids(r.list_paginated(q="nube", cpv=LITERAL)[0]),
    "fts_organo": lambda r: _ids(r.list_paginated(q="nube", organo=LITERAL)[0]),
    "avanzada_q": lambda r: _ids(r.search_advanced(q=LITERAL)[0]),
    "pdf_q": lambda r: _ids(r.fetch_for_pdf(q=LITERAL)),
    "ask": lambda r: _ids(r.search_like_for_ask(LITERAL)),
}


@pytest.mark.parametrize("camino", sorted(_BUSQUEDAS))
def test_licitaciones_el_texto_se_busca_como_literal(tmp_db, camino):
    from db.repositories.licitaciones import LicitacionRepository

    _sembrar()
    assert _BUSQUEDAS[camino](LicitacionRepository()) == {"LIT"}


@pytest.mark.parametrize("q", [None, "nube"], ids=["sa_core", "fts"])
def test_licitaciones_una_tecnologia_predicha_acabada_en_barra_no_revienta(tmp_db, q):
    """El patrón ``%,{t}`` terminaba en el carácter de escape: error de Postgres.

    El valor llega tal cual de la query string (`tecnologia_predicha` no tiene
    patrón en la ruta), así que el error era un 500 alcanzable desde fuera.
    """
    from db.database import connect
    from db.repositories.licitaciones import LicitacionRepository

    _sembrar()
    with connect() as c:
        for id_externo, predichas in (("LIT", "ORACLE,SAP\\"), ("SIN-BARRA", "ORACLE,SAP")):
            c.execute(
                "UPDATE licitaciones SET ml_tecnologias = %s WHERE id_externo = %s",
                [predichas, id_externo],
            )

    filas, _total = LicitacionRepository().list_paginated(q=q, tecnologia_predicha="SAP\\")

    assert _ids(filas) == {"LIT"}


# ── services/watchlist_rules.py ─────────────────────────────────────────────


@pytest.mark.parametrize("criterio", ["keyword", "cpv"])
def test_regla_de_vigilancia_el_texto_se_busca_como_literal(tmp_db, criterio):
    from services.watchlist_rules import WatchlistRule, list_matches

    _sembrar()
    assert _ids(list_matches(WatchlistRule(**{criterio: LITERAL}))) == {"LIT"}
