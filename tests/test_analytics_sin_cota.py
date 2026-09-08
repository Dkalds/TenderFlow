"""Ratchet de escaneos sin cota alcanzables desde la analítica (C3.2).

`rows_to_dicts(cursor)` materializa todas las filas del cursor. Con `LIMIT` eso
es una página; sin él, la tabla. El OOM del 2026-08-02 salió de ahí y ADR-023
fijó la regla —agregar en SQL, no escanear en proceso— sin dejar nada que la
comprobara para los caminos que quedaban.

Es un test **sin BD** a propósito: lo que comprueba es la forma del código, no
su resultado, así que corre en `make test-unit` y no espera a que haya Postgres.
"""

from __future__ import annotations

from scripts.check_analytics_unbounded import ALLOWLIST, sin_cota


def test_ningun_escaneo_sin_cota_nuevo() -> None:
    hallados = {f"{fichero}::{metodo}" for fichero, metodo in sin_cota()}
    nuevos = sorted(hallados - ALLOWLIST)
    assert not nuevos, (
        "métodos alcanzables desde api/routes/analytics.py que materializan sin "
        f"cota y no están declarados: {nuevos}. Agregá en SQL (ADR-023) o acotá "
        "con LIMIT."
    )


def test_la_allowlist_solo_encoge() -> None:
    """Una excepción que ya no existe tiene que salir de la lista.

    Un ratchet cuya lista no se limpia deja de medir nada: al cabo de unos
    meses nadie sabe cuáles de sus entradas siguen siendo deuda real.
    """
    hallados = {f"{fichero}::{metodo}" for fichero, metodo in sin_cota()}
    resueltos = sorted(ALLOWLIST - hallados)
    assert not resueltos, (
        "la allowlist de scripts/check_analytics_unbounded.py declara "
        f"excepciones que ya no existen: {resueltos}. Quitalas."
    )


def test_el_detector_reconoce_una_cota() -> None:
    """El control tiene que poder decir que no.

    Sin esto, un detector que devolviera siempre la lista vacía pasaría los dos
    tests de arriba sin proteger nada.
    """
    from scripts.check_analytics_unbounded import _COTA_EN_SQL, _POR_IDENTIDAD

    assert _COTA_EN_SQL.search("SELECT * FROM licitaciones LIMIT %s")
    assert _COTA_EN_SQL.search("SELECT ccaa, COUNT(*) FROM licitaciones GROUP BY ccaa")
    assert _POR_IDENTIDAD.search("SELECT * FROM t WHERE licitacion_id = %s")
    assert _POR_IDENTIDAD.search("SELECT * FROM t WHERE id_externo IN (%s, %s)")
    assert not _COTA_EN_SQL.search("SELECT id_externo, titulo FROM licitaciones")
    assert not _POR_IDENTIDAD.search("SELECT * FROM t WHERE ccaa = %s")
