"""Tests para db/repositories/csp_violations.py.

El repositorio no tenía ningún test que lo mencionara (auditoría 2026-08-07)
aunque es el destino de ``POST /api/v1/security/csp-report``, un endpoint
público sin autenticación.

Lo relevante de este repositorio es su contrato defensivo: persiste si puede y
**nunca** propaga una excepción, porque un fallo al guardar el reporte no debe
convertirse en un 500 para el navegador que lo envió.
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
