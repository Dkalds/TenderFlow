"""Con la escritura doble puesta, leer de `follows` devuelve lo mismo (T1).

Es la versión con datos de prueba de la condición de ADR-031 §B para encender
`FOLLOWS_LECTURA`: para el mismo usuario, las tres pantallas antiguas devuelven
lo mismo leyendo de su tabla que leyendo de `follows`. En producción la prueba
la da `scripts/check_follows_paridad.py`; aquí se fija que las consultas de
lectura nueva no pierdan ni inventen nada respecto a sus gemelas.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest


def _usuario(correo: str) -> tuple[int, int, str]:
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user
    from shared.identity import user_key_from_email

    user_id = create_user(email=correo, password_hash="x")  # pragma: allowlist secret
    org_id = int(OrganizationRepository().ensure_personal_organization(user_id)["id"])
    return user_id, org_id, user_key_from_email(correo, user_id)


def _licitacion(db_mod: Any, id_externo: str) -> None:
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) "
            "VALUES (%s, %s, %s) ON CONFLICT (id_externo) DO NOTHING",
            (id_externo, f"Expediente {id_externo}", "2026-09-01T00:00:00+00:00"),
        )


@pytest.fixture()
def lectura(monkeypatch: pytest.MonkeyPatch) -> Any:
    from config import settings

    def fijar(valor: bool) -> None:
        monkeypatch.setattr(settings, "FOLLOWS_LECTURA", valor, raising=False)

    return fijar


def _sin_volatiles(filas: list[dict[str, Any]], *claves: str) -> list[dict[str, Any]]:
    """Quita las claves que legítimamente difieren entre origen y `follows`.

    ``created_at``: el origen guarda texto y `follows` ``timestamptz`` (v130
    lo convierte en el backfill), así que el mismo instante llega con dos
    grafías. ``id``: con la fila de origen presente es el suyo, pero se quita
    igual para que el test compare pertenencia y contenido, no secuencias.
    """
    return [{k: v for k, v in f.items() if k not in claves} for f in filas]


def test_favoritos_iguales_desde_las_dos_tablas(tmp_db: Any, lectura: Any) -> None:
    db_mod, _ = tmp_db
    from db.repositories.watchlist import WatchlistRepository

    user_id, org_id, user_key = _usuario("fav-lectura@example.test")
    repo = WatchlistRepository()
    for id_externo in ("LIC-A", "LIC-B"):
        _licitacion(db_mod, id_externo)
        repo.add_item(user_key, user_id, id_externo, org_id, "private")
    repo.set_nota(user_key, "LIC-A", "revisar solvencia", user_id)

    lectura(False)
    vieja = repo.list_items(user_key, org_id, user_id)
    lectura(True)
    nueva = repo.list_items(user_key, org_id, user_id)

    assert sorted(_sin_volatiles(vieja, "created_at"), key=lambda f: f["id_externo"]) == sorted(
        _sin_volatiles(nueva, "created_at"), key=lambda f: f["id_externo"]
    )
    # La nota viaja: es la columna que `follows` no tiene.
    assert {f["id_externo"]: f["nota"] for f in nueva}["LIC-A"] == "revisar solvencia"


def test_empresas_iguales_desde_las_dos_tablas(tmp_db: Any, lectura: Any) -> None:
    db_mod, _ = tmp_db
    from db.watchlist_empresas import WatchlistEmpresaEntry, add_entry, list_entries

    user_id, org_id, user_key = _usuario("emp-lectura@example.test")
    with db_mod.connect() as c:
        fila = c.execute(
            "INSERT INTO empresas (nombre_canonico, created_at, updated_at) "
            "VALUES (%s, %s, %s) RETURNING empresa_id",
            ("ACME LECTURA SL", "2026-09-01T00:00:00+00:00", "2026-09-01T00:00:00+00:00"),
        ).fetchone()
    empresa_id = int(fila[0])
    add_entry(
        WatchlistEmpresaEntry(
            user_key=user_key,
            user_id=user_id,
            empresa_id=empresa_id,
            organization_id=org_id,
            email="alertas@example.test",
        )
    )

    lectura(False)
    vieja = list_entries(user_key, org_id, user_id=user_id)
    lectura(True)
    nueva = list_entries(user_key, org_id, user_id=user_id)

    assert _sin_volatiles(vieja, "created_at") == _sin_volatiles(nueva, "created_at")
    assert isinstance(nueva[0]["created_at"], str)  # el DTO lo declara `str`


def test_descartes_iguales_y_la_caducidad_sale_de_follows(tmp_db: Any, lectura: Any) -> None:
    db_mod, _ = tmp_db
    from db import radar_dismissals

    user_id, org_id, user_key = _usuario("desc-lectura@example.test")
    for id_externo in ("LIC-X", "LIC-Y", "LIC-Z"):
        _licitacion(db_mod, id_externo)
    radar_dismissals.add(
        user_key, "LIC-X", organization_id=org_id, user_id=user_id, score=70, banda="alta"
    )
    manana = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    radar_dismissals.add(
        user_key,
        "LIC-Y",
        organization_id=org_id,
        user_id=user_id,
        hasta=manana,
        accion="posponer",
    )
    ayer = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    radar_dismissals.add(
        user_key,
        "LIC-Z",
        organization_id=org_id,
        user_id=user_id,
        hasta=ayer,
        accion="silenciar",
    )

    lectura(False)
    ids_viejos = radar_dismissals.list_ids(user_key, user_id=user_id)
    detalle_viejo = radar_dismissals.list_detalle(user_key, user_id=user_id)
    lectura(True)
    ids_nuevos = radar_dismissals.list_ids(user_key, user_id=user_id)
    detalle_nuevo = radar_dismissals.list_detalle(user_key, user_id=user_id)

    # El caducado (LIC-Z) no cuenta en ninguna de las dos.
    assert sorted(ids_viejos) == sorted(ids_nuevos) == ["LIC-X", "LIC-Y"]
    por_id = {d["id_externo"]: d for d in detalle_nuevo}
    assert por_id["LIC-X"]["score"] == 70 and por_id["LIC-X"]["banda"] == "alta"
    assert por_id["LIC-Y"]["accion"] == "posponer" and por_id["LIC-Y"]["hasta"] is not None
    assert sorted(detalle_viejo, key=lambda d: d["id_externo"]) == sorted(
        detalle_nuevo, key=lambda d: d["id_externo"]
    )
