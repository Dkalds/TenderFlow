"""``services/security.py``: la puerta de ``POST /security/csp-report`` a la BD.

El repositorio tiene sus tests (``tests/test_csp_violations_repo.py``); aquí se
fija lo que añade el servicio: ``api/routes/security.py`` lo llama con
valores **posicionales**, así que el orden de su firma es contrato.
"""

from __future__ import annotations

from typing import Any

from services.security import store_csp_violation


def _guardadas(db_mod: Any) -> list[tuple[Any, ...]]:
    with db_mod.connect_read() as c:
        return c.execute(
            "SELECT blocked_uri, violated_directive, document_uri, source_file, created_at "
            "FROM csp_violations ORDER BY id"
        ).fetchall()


def test_los_valores_posicionales_caen_en_su_columna(tmp_db: Any) -> None:
    db_mod, _ = tmp_db

    store_csp_violation(
        "https://evil.example/x.js",
        "script-src",
        "https://app.example/panel",
        "https://app.example/main.js",
    )

    (fila,) = _guardadas(db_mod)
    assert fila[:4] == (
        "https://evil.example/x.js",
        "script-src",
        "https://app.example/panel",
        "https://app.example/main.js",
    )
    assert fila[4]  # created_at lo pone el repositorio


def test_un_reporte_con_campos_vacios_tambien_se_guarda(tmp_db: Any) -> None:
    """El endpoint convierte lo que falta en ``""``; no es motivo para perder el reporte."""
    db_mod, _ = tmp_db

    store_csp_violation("", "", "", "")

    assert [f[:4] for f in _guardadas(db_mod)] == [("", "", "", "")]
