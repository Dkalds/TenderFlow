"""Los filtros opcionales de los listados arman SQL que Postgres acepta.

Mismo hueco en cinco módulos: condiciones que sólo se concatenan cuando llega
su parámetro, así que ningún test las recorría — y son exactamente las líneas
que reescribió la migración de paramstyle (`?` → `%s`) de esta rama. Un
placeholder mal migrado en una de ellas no se nota hasta que alguien usa ese
filtro en producción.

Cada test ejecuta contra el Postgres del test en vez de inspeccionar la
cadena: contar ``%s`` no detecta un ``%`` sin duplicar dentro de un literal
—el fallo concreto que hubo que arreglar dos veces durante la migración—, y el
motor sí. Que devuelvan vacío es lo esperado: la base del test está limpia; lo
que se comprueba es que la sentencia sea válida y ligue sus parámetros.
"""

from __future__ import annotations

import services.competitive.bajas as bajas_mod
import services.competitive.renovaciones as renov_mod
import services.resoluciones as resol_mod
from db.repositories.product_metrics import ProductMetricsRepository


def test_bajas_agregadas_con_cpv_y_ccaa(tmp_db):
    filas = bajas_mod.bajas_agregadas(cpv_prefix="7220", ccaa="Madrid")

    assert filas == []


def test_proximas_renovaciones_con_todos_sus_filtros(tmp_db):
    filas = renov_mod.proximas_renovaciones(
        empresa_id=1,
        ccaa="Madrid",
        tecnologias=["SAP", "Cloud"],
        min_importe=1000.0,
    )

    assert filas == []


def test_proximas_renovaciones_descarta_tecnologias_vacias(tmp_db):
    """El filtro limpia `''` antes de armar el `IN`: sin eso quedaría `IN ()`."""
    filas = renov_mod.proximas_renovaciones(tecnologias=["", None])  # type: ignore[list-item]

    assert filas == []


def test_resoluciones_con_organo_sentido_y_desde(tmp_db):
    filas = resol_mod.resoluciones(
        organo="Ministerio",
        sentido="ESTIMADO",
        desde="2026-01-01",
    )

    assert filas == []


def test_pursuit_rows_acota_por_periodo(tmp_db):
    filas = ProductMetricsRepository().pursuit_rows(
        period_from="2026-01-01",
        period_to="2026-12-31",
    )

    assert filas == []


def test_los_envoltorios_de_watchlist_propagan_el_user_key(tmp_db):
    """`remove_entry`/`update_frequency` ganaron `user_key` en esta rama (IDOR).

    El aislamiento por usuario ya está probado en la capa `db`; lo que aquí no
    se recorría es la fachada de `services`, que es la que usan las rutas. Sin
    esto, un envoltorio que olvidara pasar `user_key` compilaría y pasaría la
    suite entera.
    """
    from db.watchlist import WatchlistEntry
    from services import watchlist as wl

    wl.add_entry(WatchlistEntry(user_key="duenio@example.test", cpv_prefix="7220"))
    entry_id = wl.list_entries("duenio@example.test")[0]["id"]

    # Otro usuario no puede tocarla…
    assert wl.remove_entry(entry_id, "intruso@example.test") is False
    assert wl.update_frequency(entry_id, "weekly", "intruso@example.test") is False

    # …y su dueño sí.
    assert wl.update_frequency(entry_id, "weekly", "duenio@example.test") is True
    assert wl.remove_entry(entry_id, "duenio@example.test") is True
    assert wl.list_entries("duenio@example.test") == []
