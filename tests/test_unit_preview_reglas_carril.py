"""``POST /watchlist/rules/preview``: techo de sentencia y carril de CPU.

El preview cuenta sobre el corpus entero (un ``ILIKE`` sobre ~1,6 M de filas) y
lo puede pedir cualquier rol (auditoría 2026-11, ruta 19, authz-usuario-rutas-8).
Dos cosas que se fijan sin base de datos:

- cuelga del techo ``API_ANALYTICS_STATEMENT_TIMEOUT_MS`` como el preview del
  perfil, de modo que encenderlo en el entorno lo acota;
- con ``banda_min`` el conteo puntúa con pandas, y eso va al carril de CPU.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from api.routes import watchlist_rules as ruta
from api.techo_analitica import techo_sentencia_analitica


def test_el_preview_cuelga_del_techo_de_sentencia_analitica() -> None:
    preview = next(
        r for r in ruta.router.routes if getattr(r, "path", "") == "/watchlist/rules/preview"
    )

    dependencias = getattr(preview, "dependencies", [])
    assert any(d.dependency is techo_sentencia_analitica for d in dependencias)


@pytest.fixture()
def carriles(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Qué carril despachó cada función, en orden."""
    usados: list[str] = []

    def _falso(nombre: str) -> Any:
        async def _despacha(fn: Any, *args: Any, **kwargs: Any) -> Any:
            usados.append(f"{nombre}:{fn.__name__}")
            return fn(*args, **kwargs)

        return _despacha

    monkeypatch.setattr(ruta, "run_db", _falso("db"))
    monkeypatch.setattr(ruta, "run_cpu", _falso("cpu"))

    def count_matches(regla: Any) -> int:
        return 7

    def serie_semanal(regla: Any) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(ruta, "count_matches", count_matches)
    monkeypatch.setattr(ruta, "serie_semanal", serie_semanal)
    return usados


def _preview(**criterios: Any) -> Any:
    cuerpo = ruta.WatchlistRuleBody(**criterios)
    return asyncio.run(ruta.preview_matches(cuerpo, _ctx={}))


def test_sin_banda_el_conteo_va_al_pool_general(carriles: list[str]) -> None:
    resultado = _preview(keyword="sap")

    assert resultado.total == 7
    assert carriles == ["db:count_matches", "db:serie_semanal"]


def test_con_banda_el_conteo_va_al_carril_de_cpu(carriles: list[str]) -> None:
    _preview(keyword="sap", banda_min="Caliente")

    assert carriles == ["cpu:count_matches", "db:serie_semanal"]
