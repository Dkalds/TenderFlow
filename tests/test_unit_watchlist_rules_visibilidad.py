"""El listado de reglas dice cuáles están compartidas con la organización."""

from __future__ import annotations

from unittest.mock import patch

from api.routes import watchlist_rules as ruta


def _fila(rule_id: int, visibility: str) -> dict[str, object]:
    return {
        "id": rule_id,
        "nombre": f"Regla {rule_id}",
        "frequency": "daily",
        "active": 1,
        "organization_id": 7,
        "visibility": visibility,
        "email": None,
    }


def test_una_regla_compartida_no_se_lista_como_privada() -> None:
    """La ruta reconstruía la regla sin estos dos campos y servía los defaults."""
    filas = [_fila(1, "organization"), _fila(2, "private")]

    with (
        patch.object(ruta, "list_rules_rows", return_value=filas),
        patch.object(ruta, "count_matches_bounded", return_value=[0, 0]),
    ):
        reglas = ruta._rules_with_counts(user_id=3, organization_id=7)

    assert [r.visibility for r in reglas] == ["organization", "private"]
    assert [r.organization_id for r in reglas] == [7, 7]
