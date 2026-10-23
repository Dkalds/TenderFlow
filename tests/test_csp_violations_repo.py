"""Tests para db/repositories/csp_violations.py.

El repositorio no tenía ningún test que lo mencionara (auditoría 2026-08-07)
aunque es el destino de ``POST /api/v1/security/csp-report``, un endpoint
público sin autenticación.

Lo relevante de este repositorio es su contrato defensivo: persiste si puede y
**nunca** propaga una excepción, porque un fallo al guardar el reporte no debe
convertirse en un 500 para el navegador que lo envió.

La lectura (``listar_agrupadas``) es lo que ve Ops › Estado: por directiva y
origen bloqueado, dentro de una ventana, sin identidad.
"""

from __future__ import annotations

from unittest.mock import patch


def _stored(db_mod) -> list[tuple[str, str, str, str]]:
    with db_mod.connect_read() as c:
        rows = c.execute(
            "SELECT blocked_uri, violated_directive, document_uri, source_file "
            "FROM csp_violations ORDER BY id"
        ).fetchall()
    return [(str(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in rows]


def test_store_persiste_la_violacion(tmp_db):
    from db.repositories.csp_violations import CspViolationRepository

    db_mod, _ = tmp_db
    CspViolationRepository().store(
        blocked_uri="https://evil.example/x.js",
        violated_directive="script-src",
        document_uri="https://app.example/dashboard",
        source_file="https://app.example/main.js",
    )

    assert _stored(db_mod) == [
        (
            "https://evil.example/x.js",
            "script-src",
            "https://app.example/dashboard",
            "https://app.example/main.js",
        )
    ]


def test_store_acumula_varias_violaciones(tmp_db):
    from db.repositories.csp_violations import CspViolationRepository

    db_mod, _ = tmp_db
    repo = CspViolationRepository()
    for i in range(3):
        repo.store(
            blocked_uri=f"https://evil.example/{i}.js",
            violated_directive="script-src",
            document_uri="https://app.example/",
            source_file="https://app.example/main.js",
        )

    assert len(_stored(db_mod)) == 3


def test_store_no_propaga_si_la_tabla_no_existe(tmp_db):
    """Sin la tabla, guarda nada y no rompe: el endpoint sigue devolviendo 204.

    ``get_table_columns`` devuelve un conjunto vacío cuando la tabla no está,
    y el repositorio se salta el INSERT en vez de fallar.
    """
    from db.repositories.csp_violations import CspViolationRepository

    with patch("db.repositories.csp_violations.get_table_columns", return_value=set()):
        CspViolationRepository().store(
            blocked_uri="https://evil.example/x.js",
            violated_directive="script-src",
            document_uri="https://app.example/",
            source_file="https://app.example/main.js",
        )


def test_store_no_propaga_si_la_bd_falla(tmp_db):
    """Un fallo de BD no puede convertirse en un 500 para el navegador."""
    from db.repositories.csp_violations import CspViolationRepository

    with patch(
        "db.repositories.csp_violations.connect",
        side_effect=RuntimeError("db caída"),
    ):
        CspViolationRepository().store(
            blocked_uri="https://evil.example/x.js",
            violated_directive="script-src",
            document_uri="https://app.example/",
            source_file="https://app.example/main.js",
        )


# ── La lectura agrupada ─────────────────────────────────────────────────────


def _guardar(repo, *, blocked_uri: str, directiva: str = "script-src", document_uri: str) -> None:
    repo.store(
        blocked_uri=blocked_uri,
        violated_directive=directiva,
        document_uri=document_uri,
        source_file="https://app.example/main.js",
    )


def test_listar_agrupadas_agrupa_por_directiva_y_origen_sin_query_string(tmp_db):
    from db.repositories.csp_violations import CspViolationRepository, listar_agrupadas

    repo = CspViolationRepository()
    # Dos ficheros del mismo origen son un grupo: el patrón es el host, no el fichero.
    _guardar(
        repo, blocked_uri="https://cdn.example/a.js", document_uri="https://app.example/radar?x=1"
    )
    _guardar(
        repo, blocked_uri="https://cdn.example/b.js", document_uri="https://app.example/radar?x=2"
    )
    _guardar(
        repo, blocked_uri="https://cdn.example/c.js", document_uri="https://app.example/detalle"
    )
    # Lo que no es una URL se agrupa por su valor literal.
    _guardar(repo, blocked_uri="inline", directiva="style-src", document_uri="https://app.example/")
    # Y lo mismo bloqueado por otra directiva es otro grupo.
    _guardar(
        repo,
        blocked_uri="https://cdn.example/x.png",
        directiva="img-src",
        document_uri="https://app.example/",
    )

    filas = listar_agrupadas(desde="2000-01-01T00:00:00+00:00")

    grupos = [(f["directiva"], f["origen"], f["ocurrencias"]) for f in filas]
    assert set(grupos) == {
        ("script-src", "https://cdn.example", 3),
        ("img-src", "https://cdn.example", 1),
        ("style-src", "inline", 1),
    }
    # El grupo con más ocurrencias va primero: es lo que hay que mirar antes.
    assert grupos[0] == ("script-src", "https://cdn.example", 3)
    primera = filas[0]
    # La página más frecuente del grupo, sin su query string.
    assert primera["documento"] == "https://app.example/radar"
    assert primera["primera_vez"] is not None
    assert primera["ultima_vez"] >= primera["primera_vez"]
    assert {f["origen"] for f in filas} == {"https://cdn.example", "inline"}


def test_listar_agrupadas_respeta_la_ventana_y_el_tope(tmp_db):
    from db.repositories.csp_violations import CspViolationRepository, listar_agrupadas

    db_mod, _ = tmp_db
    repo = CspViolationRepository()
    _guardar(repo, blocked_uri="https://hoy.example/a.js", document_uri="https://app.example/")
    _guardar(repo, blocked_uri="https://ayer.example/a.js", document_uri="https://app.example/")
    # Una fila vieja, escrita como la escribió el endpoint en su día.
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO csp_violations "
            "(blocked_uri, violated_directive, document_uri, source_file, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                "https://antes.example/z.js",
                "script-src",
                "https://app.example/",
                "",
                "2020-01-01T00:00:00+00:00",
            ),
        )

    recientes = listar_agrupadas(desde="2025-01-01T00:00:00+00:00")
    assert {f["origen"] for f in recientes} == {"https://hoy.example", "https://ayer.example"}

    todas = listar_agrupadas(desde="2000-01-01T00:00:00+00:00")
    assert len(todas) == 3
    assert len(listar_agrupadas(desde="2000-01-01T00:00:00+00:00", limit=1)) == 1
