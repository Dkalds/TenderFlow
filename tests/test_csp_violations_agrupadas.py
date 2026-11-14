"""``agrupadas`` de db/repositories/csp_violations.py contra Postgres.

Lo que el test unitario de la ruta no puede ver: que el SQL agrupa por
directiva y por esquema+host, que deja ``inline``/``eval``/``data`` tal cual,
que la ventana corta por ``created_at`` y que el ejemplo pierde la query.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


def _iso(dias_atras: float) -> str:
    return (datetime.now(UTC) - timedelta(days=dias_atras)).isoformat()


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    filas = [
        # (blocked_uri, violated_directive, document_uri, hace_dias)
        ("https://www.youtube.com/embed/abc?x=1", "frame-src", "https://app.test/a?token=s", 1),
        ("https://www.youtube.com/embed/def", "frame-src 'self'", "https://app.test/a#f", 2),
        ("https://www.youtube.com/embed/ghi", "frame-src", "https://app.test/b", 3),
        ("inline", "script-src-elem", "https://app.test/c", 1),
        ("data:image/png;base64,AAAA", "img-src", "https://app.test/c", 1),
        ("", "", "", 1),
        # Fuera de la ventana de 30 días: no cuenta.
        ("https://viejo.example/x.js", "script-src", "https://app.test/d", 40),
    ]
    with db_mod.connect() as c:
        for blocked, directiva, documento, hace in filas:
            c.execute(
                "INSERT INTO csp_violations "
                "(blocked_uri, violated_directive, document_uri, source_file, created_at) "
                "VALUES (%s, %s, %s, '', %s)",
                (blocked, directiva, documento, _iso(hace)),
            )
    return db_mod


def _por_clave(filas: list[dict[str, object]]) -> dict[tuple[object, object], dict[str, object]]:
    return {(f["directiva"], f["origen"]): f for f in filas}


def test_agrupa_por_directiva_y_origen_dentro_de_la_ventana(db) -> None:
    from db.repositories.csp_violations import agrupadas

    filas = agrupadas(desde=_iso(30))

    assert set(_por_clave(filas)) == {
        ("frame-src", "https://www.youtube.com"),
        ("script-src-elem", "inline"),
        ("img-src", "data:"),
        ("(vacío)", "(vacío)"),
    }
    assert filas[0]["directiva"] == "frame-src"
    assert filas[0]["veces"] == 3


def test_el_documento_de_ejemplo_no_lleva_query_ni_fragmento(db) -> None:
    from db.repositories.csp_violations import agrupadas

    fila = _por_clave(agrupadas(desde=_iso(30)))[("frame-src", "https://www.youtube.com")]

    assert fila["documento_ejemplo"] in {"https://app.test/a", "https://app.test/b"}


def test_limit_corta_tras_ordenar_por_veces(db) -> None:
    from db.repositories.csp_violations import agrupadas

    (fila,) = agrupadas(desde=_iso(30), limit=1)

    assert (fila["directiva"], fila["veces"]) == ("frame-src", 3)


def test_la_ventana_incluye_lo_antiguo_si_se_amplia(db) -> None:
    from db.repositories.csp_violations import agrupadas

    claves = set(_por_clave(agrupadas(desde=_iso(60))))

    assert ("script-src", "https://viejo.example") in claves
