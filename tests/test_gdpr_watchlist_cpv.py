"""Regresión GDPR: export/anonimización de watchlist CPV apunta a la tabla real.

Hasta 2026-08, ``WatchlistRepository.export_cpv`` y
``anonymize_cpv`` (entonces ``export_by_user_key`` y ``anonymize_by_user_key``)
consultaban una tabla ``watchlist`` inexistente con
el error tragado por un ``except``: el export devolvía siempre ``[]`` y el
borrado no borraba nada, sin log ni test que lo delatara (ítem P1 del
backlog). Estos tests siembran datos reales y verifican que aparecen en el
export y desaparecen tras anonimizar — no solo que la llamada no lanza.
"""

from __future__ import annotations

from db.repositories.base import rows_to_dicts
from db.repositories.watchlist import WatchlistRepository
from db.users import create_user
from db.watchlist import WatchlistEntry, add_entry
from shared.identity import user_key_from_email


def _seed(nombre: str) -> int:
    """Crea el usuario (``watchlist_cpv`` se identifica por ``user_id``, v181) y su entrada."""
    user_id = create_user(
        email=f"{nombre}@example.test",
        password_hash="test-hash",  # pragma: allowlist secret -- literal de test
    )
    add_entry(
        WatchlistEntry(
            user_id=user_id,
            cpv_prefix="72",
            keyword="sap",
            email="ana@example.com",
        )
    )
    return user_id


def test_export_returns_seeded_entry(tmp_db):
    user_id = _seed("gdpr-user-1")

    rows = WatchlistRepository().export_cpv(user_id)

    assert len(rows) == 1
    assert rows[0]["cpv_prefix"] == "72"
    assert rows[0]["email"] == "ana@example.com"


def test_export_via_service_layer(tmp_db):
    user_id = _seed("gdpr-user-2")
    from services.gdpr import export_watchlist

    rows = export_watchlist(user_id)

    assert len(rows) == 1
    # La columna la deriva la base del correo del usuario (v181).
    assert rows[0]["user_key"] == user_key_from_email("gdpr-user-2@example.test", user_id)


def test_anonymize_removes_pii_and_hides_from_export(tmp_db):
    user_id = _seed("gdpr-user-3")
    repo = WatchlistRepository()
    assert repo.export_cpv(user_id)

    repo.anonymize_cpv(user_id)

    assert repo.export_cpv(user_id) == []
    # La fila sobrevive anonimizada: sin user_key real, sin email, sin user_id.
    from db.database import connect_read

    with connect_read() as c:
        cur = c.execute(
            "SELECT user_key, email, user_id FROM watchlist_cpv WHERE cpv_prefix = %s",
            ("72",),
        )
        rows = rows_to_dicts(cur)
    assert rows, "la fila anonimizada debe seguir existiendo"
    assert rows[0]["user_key"] == "DELETED"
    assert rows[0]["email"] is None
    assert rows[0]["user_id"] is None
