"""Tests del repositorio de watchlist_items (favoritos de licitaciones).

Cubre db/repositories/watchlist.py: list_items/add_item/remove_item y el
export/anonymize GDPR asociado. Ver tests/test_watchlist_rules.py para el
equivalente de reglas por criterio.

``organization_id`` dejó de ser opcional en el repositorio (S4.3, 2026-09): la
rama ``is None`` leía sin filtro de organización y ``add_item`` escribía filas
con organización nula, invisibles después para la consulta con ámbito. Estos
tests pasan por tanto una organización **real**, y los que comprueban
aislamiento lo hacen en las **dos** dimensiones que existen ahora: dos usuarios
dentro de la MISMA organización, y dos organizaciones distintas. Inventarse un
``organization_id`` cualquiera «para que compile» habría dejado sin cubrir la
mitad del aislamiento — y ni siquiera habría llegado a ejecutarse: la FK de
v64 rechaza el INSERT antes.
"""

from __future__ import annotations

import pytest

from db.repositories.watchlist import WatchlistRepository


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


@pytest.fixture()
def repo() -> WatchlistRepository:
    return WatchlistRepository()


def _organizacion(nombre: str) -> int:
    """Crea una organización de verdad (con su owner) y devuelve su id.

    ``watchlist_items.organization_id`` es FK contra ``organizations`` (v64).
    La FK se instaló ``NOT VALID``, lo que solo exime a las filas **previas**:
    cada INSERT nuevo sí se comprueba, así que un id inventado revienta con
    ``ForeignKeyViolation`` antes de llegar a comprobar el aislamiento, que es
    lo que miran estos tests.
    """
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    owner = create_user(
        email=f"{nombre}@example.test",
        password_hash="test-hash",  # pragma: allowlist secret -- literal de test
        display_name=nombre,
    )
    return int(OrganizationRepository().create_organization(nombre, owner)["id"])


@pytest.fixture()
def org(db) -> int:
    """Organización principal del test."""
    return _organizacion("equipo-uno")


@pytest.fixture()
def otra_org(db) -> int:
    """Segunda organización: la frontera que nada debe cruzar."""
    return _organizacion("equipo-dos")


def _seed_licitacion(lic_id: str = "L1", *, titulo="Implantación SAP", importe=100_000.0) -> None:
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, importe, estado, fuente, "
            " fecha_publicacion, fecha_extraccion) "
            "VALUES (%s, %s, %s, 'ABIERTO', 'placsp', '2026-01-01', CURRENT_TIMESTAMP)",
            (lic_id, titulo, importe),
        )


def test_add_and_list_roundtrip(db, repo, org):
    _seed_licitacion()
    item = repo.add_item("user-a", None, "L1", org)
    assert item["id_externo"] == "L1"
    assert item["organization_id"] == org

    items = repo.list_items("user-a", org)
    assert len(items) == 1
    assert items[0]["id_externo"] == "L1"
    assert items[0]["titulo"] == "Implantación SAP"
    assert items[0]["importe"] == 100_000.0
    assert items[0]["estado"] == "ABIERTO"
    assert items[0]["fecha_publicacion"] == "2026-01-01"


def test_add_item_is_idempotent(db, repo, org):
    _seed_licitacion()
    first = repo.add_item("user-a", None, "L1", org)
    second = repo.add_item("user-a", None, "L1", org)
    assert first["id"] == second["id"]
    assert len(repo.list_items("user-a", org)) == 1


def test_list_aislado_por_usuario(db, repo, org):
    """Dos usuarios de la MISMA organización no se ven lo privado del otro.

    Primera de las dos dimensiones del aislamiento: compartir organización no
    es compartir favoritos. Lo que sí se comparte es lo marcado explícitamente
    como ``visibility='organization'`` (ver ``tests/test_organization_scope.py``
    ::``test_organization_visibility_shares_only_explicit_items``).
    """
    _seed_licitacion("L1")
    _seed_licitacion("L2", titulo="Mantenimiento Oracle", importe=5_000.0)
    repo.add_item("user-a", None, "L1", org)
    repo.add_item("user-b", None, "L2", org)

    assert [it["id_externo"] for it in repo.list_items("user-a", org)] == ["L1"]
    assert [it["id_externo"] for it in repo.list_items("user-b", org)] == ["L2"]


def test_list_no_cruza_organizaciones(db, repo, org, otra_org):
    """Segunda dimensión: ni siquiera lo COMPARTIDO sale de su organización.

    Se usan dos licitaciones distintas, y no la misma en las dos
    organizaciones, porque ``watchlist_items`` conserva el
    ``UNIQUE(user_key, id_externo)`` anterior a v64: un mismo usuario no puede
    tener hoy el mismo favorito en dos organizaciones. Esa estrechez está
    documentada como deuda de transición en la propia migración v64 y es
    ortogonal a lo que aquí se comprueba: que el predicado de organización
    manda por encima de la visibilidad.
    """
    _seed_licitacion("L1")
    _seed_licitacion("L2", titulo="Mantenimiento Oracle", importe=5_000.0)
    repo.add_item("user-a", None, "L1", org, "organization")
    repo.add_item("user-a", None, "L2", otra_org, "organization")

    # El mismo user_key, mirando desde cada organización, ve solo lo de esa.
    assert [it["id_externo"] for it in repo.list_items("user-a", org)] == ["L1"]
    assert [it["id_externo"] for it in repo.list_items("user-a", otra_org)] == ["L2"]

    # Y un compañero de la segunda organización ve lo compartido de la SUYA,
    # nunca lo compartido de la primera.
    ajenos = [it["id_externo"] for it in repo.list_items("user-c", otra_org)]
    assert ajenos == ["L2"]
    assert "L1" not in ajenos


def test_remove_item_solo_lo_propio(db, repo, org):
    _seed_licitacion()
    repo.add_item("user-a", None, "L1", org)

    assert repo.remove_item("user-b", "L1", org) is False
    assert len(repo.list_items("user-a", org)) == 1
    assert repo.remove_item("user-a", "L1", org) is True
    assert repo.list_items("user-a", org) == []


def test_remove_item_no_cruza_organizaciones(db, repo, org, otra_org):
    """Borrar desde otra organización no toca el favorito, ni siquiera al dueño.

    La organización es condición necesaria además de la propiedad: si el
    predicado de ámbito se cayera del DELETE, este test lo vería como un
    borrado que sí ocurre.
    """
    _seed_licitacion()
    repo.add_item("user-a", None, "L1", org)

    assert repo.remove_item("user-a", "L1", otra_org) is False
    assert [it["id_externo"] for it in repo.list_items("user-a", org)] == ["L1"]


def test_remove_item_inexistente_devuelve_false(db, repo, org):
    assert repo.remove_item("user-a", "NOPE", org) is False


def test_export_items_by_user_key(db, repo, org, otra_org):
    """El export GDPR (Art. 15/20) es deliberadamente ciego a la organización.

    La pregunta que responde es «qué guarda el sistema sobre esta persona», no
    «qué ve este equipo»: un favorito que vive en una organización a la que el
    exportador no está mirando sigue siendo dato personal suyo. Por eso se
    siembra en dos organizaciones y se esperan las dos filas.
    """
    _seed_licitacion("L1")
    _seed_licitacion("L2", titulo="Mantenimiento Oracle", importe=5_000.0)
    repo.add_item("user-a", None, "L1", org)
    repo.add_item("user-a", None, "L2", otra_org)

    exported = repo.export_items_by_user_key("user-a")
    assert {row["id_externo"] for row in exported} == {"L1", "L2"}
    assert repo.export_items_by_user_key("user-b") == []


def test_anonymize_items_by_user_key(db, repo, org, otra_org):
    """El borrado GDPR (Art. 17) tampoco puede dejar restos en otra organización."""
    _seed_licitacion("L1")
    _seed_licitacion("L2", titulo="Mantenimiento Oracle", importe=5_000.0)
    repo.add_item("user-a", None, "L1", org)
    repo.add_item("user-a", None, "L2", otra_org)

    repo.anonymize_items_by_user_key("user-a")

    assert repo.list_items("user-a", org) == []
    assert repo.list_items("user-a", otra_org) == []
    assert repo.export_items_by_user_key("user-a") == []
