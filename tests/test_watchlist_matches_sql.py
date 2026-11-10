"""Composición del SQL que busca matches nuevos de una regla de vigilancia.

Sin BD: se compila la sentencia y se afirma sobre la cadena y sus parámetros.
Existe porque las dos propiedades que vigila fallan **en silencio**.

1. **Los `%s` tienen que cuadrar con los parámetros.** Sembrar una condición con
   bind params en un `WHERE` que se construye por partes desalinea los valores
   sin lanzar ningún error: no da un fallo, da resultados incorrectos. Es el
   mismo criterio que `tests/test_adjudicaciones_dedupe_sql.py`.

2. **El corte temporal tiene que ser inclusivo.** Fue `>` hasta el 2026-08-30 y
   esa desigualdad, con una ventana que el job adelanta en cada evaluación,
   hacía que ninguna licitación publicada el día del chequeo pudiera notificarse
   jamás. Un test con BD que siembre días distintos —como hacían todos— pasa
   igual con las dos desigualdades.
"""

from __future__ import annotations

import pytest

from db.models import compile_query
from db.repositories.watchlist_rules import _stmt_matches
from services.watchlist_rules import _MATCH_COLS, WatchlistRule, _rule_clauses

_REGLA_COMPLETA = WatchlistRule(keyword="sap", cpv="72", min_importe=1000.0, ccaa="Madrid")


def _compilar(regla: WatchlistRule, desde: str | None, user_id: int | None):
    stmt = _stmt_matches(_rule_clauses(regla), _MATCH_COLS, desde=desde, limit=50, user_id=user_id)
    return compile_query(stmt)


@pytest.mark.parametrize(
    ("regla", "desde", "user_id"),
    [
        (WatchlistRule(), None, None),
        (WatchlistRule(), "2026-08-01", None),
        (WatchlistRule(keyword="sap"), "2026-08-01", 4217),
        (_REGLA_COMPLETA, "2026-08-28", 4218),
    ],
)
def test_los_placeholders_cuadran_con_los_parametros(regla, desde, user_id):
    sql, params = _compilar(regla, desde, user_id)
    assert sql.count("%s") == len(params)


def test_el_corte_temporal_es_inclusivo():
    sql, _ = _compilar(WatchlistRule(), "2026-08-01", None)
    assert "fecha_publicacion >= " in sql
    # Y no hay ningún `>` suelto sobre esa columna que lo contradiga.
    assert "fecha_publicacion > " not in sql


def test_sin_fecha_no_hay_corte_temporal():
    sql, _ = _compilar(WatchlistRule(), None, None)
    assert "fecha_publicacion >" not in sql


def test_con_user_id_se_excluye_lo_ya_notificado():
    sql, params = _compilar(WatchlistRule(keyword="sap"), "2026-08-01", 4217)
    assert "NOT EXISTS" in sql
    # Correlacionado con la fila externa: sin esto el subselect sería constante
    # y el anti-join descartaría todo o nada.
    assert "n.licitacion_id = licitaciones.id_externo" in sql
    # La identidad es el id, más la clave legada que la base deriva de él para
    # las alertas escritas sin id (v181): ningún llamador pasa la clave.
    assert "n.user_id = " in sql
    assert "clave_legada_de_usuario(" in sql
    # Los valores viajan como parámetros, nunca interpolados.
    assert 4217 in params
    assert "rule_match" in params


def test_sin_user_id_no_hay_anti_join():
    """La vista previa de una regla no debe ocultar lo ya notificado."""
    sql, _ = _compilar(WatchlistRule(keyword="sap"), "2026-08-01", None)
    assert "NOT EXISTS" not in sql
    assert "user_notifications" not in sql


def test_el_orden_y_el_tope_siguen_puestos():
    # Si se perdiera el ORDER BY, el `LIMIT` recortaría un conjunto arbitrario.
    sql, _ = _compilar(WatchlistRule(), None, None)
    assert "ORDER BY licitaciones.fecha_publicacion DESC" in sql
    assert "LIMIT" in sql
