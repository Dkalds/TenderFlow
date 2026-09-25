"""La organización personal se resuelve con una lectura; se escribe solo si falta.

Sin BD: ``connect_read`` y ``connect`` del repositorio se sustituyen por dobles
que registran el pool de cada sentencia. La creación de la personal y sus
casos raros (membresía no activa) los cubren contra Postgres
``tests/test_organization_scope.py`` y ``tests/test_organization_members.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

import db.repositories.organizations as repo_mod
from services import organizations as svc

_COLUMNAS = ("id", "name", "is_personal", "role", "created_at")
_PERSONAL = (11, "Ana", True, "owner", "2026-09-01T00:00:00+00:00")
_EQUIPO = (12, "Equipo", False, "member", "2026-09-02T00:00:00+00:00")


class _Conexion:
    """Responde a cada SELECT con las filas que el test tenga preparadas."""

    def __init__(self, estado: dict[str, Any], pool: str) -> None:
        self._estado = estado
        self._pool = pool
        self._filas: list[tuple[Any, ...]] = []
        self.description: list[tuple[str]] = []

    def execute(self, sql: str, params: Any = None) -> _Conexion:
        plano = " ".join(sql.split())
        self._estado["registro"].append((self._pool, plano))
        if "es_la_personal" in plano:
            self.description = [(c,) for c in (*_COLUMNAS, "es_la_personal")]
            self._filas = list(self._estado["listado"])
        elif plano.startswith("SELECT") and "personal_owner_user_id = %s AND m.user_id" in plano:
            self.description = [(c,) for c in _COLUMNAS]
            self._filas = [self._estado["personal"]] if self._estado["personal"] else []
        else:
            self.description = []
            self._filas = []
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._filas

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._filas[0] if self._filas else None


@pytest.fixture()
def bd(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    estado: dict[str, Any] = {"registro": [], "personal": None, "listado": []}

    @contextmanager
    def _lectura() -> Iterator[_Conexion]:
        yield _Conexion(estado, "lectura")

    @contextmanager
    def _escritura() -> Iterator[_Conexion]:
        estado["escrituras"] = estado.get("escrituras", 0) + 1
        yield _Conexion(estado, "escritura")

    monkeypatch.setattr(repo_mod, "connect_read", _lectura)
    monkeypatch.setattr(repo_mod, "connect", _escritura)
    return estado


def _pools(estado: dict[str, Any]) -> list[str]:
    return [pool for pool, _ in estado["registro"]]


def test_con_la_personal_lista_es_una_lectura_y_ninguna_escritura(bd: dict[str, Any]) -> None:
    bd["personal"] = _PERSONAL

    fila = repo_mod.OrganizationRepository().ensure_personal_organization(7)

    assert fila == dict(zip(_COLUMNAS, _PERSONAL, strict=True))
    assert _pools(bd) == ["lectura"]
    assert "escrituras" not in bd


def test_resolve_organization_sin_id_usa_el_camino_rapido(bd: dict[str, Any]) -> None:
    bd["personal"] = _PERSONAL

    assert svc.resolve_organization(7, None) == (11, "owner")
    assert _pools(bd) == ["lectura"]


def test_si_falta_la_personal_va_a_la_escritura_de_siempre(bd: dict[str, Any]) -> None:
    """Sin fila lista, el repositorio entra en la transacción de escritura.

    Lo que haga dentro (crear la organización, la membresía) no es de este
    test: el doble no la crea, así que termina en el error de siempre.
    """
    bd["personal"] = None

    with pytest.raises((ValueError, RuntimeError)):
        repo_mod.OrganizationRepository().ensure_personal_organization(7)

    assert _pools(bd)[0] == "lectura"
    assert bd["escrituras"] == 1


def test_list_organizations_es_una_sola_lectura_si_la_personal_esta(bd: dict[str, Any]) -> None:
    bd["listado"] = [(*_PERSONAL, True), (*_EQUIPO, False)]

    organizaciones = svc.list_organizations(7)

    assert [o.id for o in organizaciones] == [11, 12]
    assert _pools(bd) == ["lectura"]
    assert "escrituras" not in bd


def test_list_organizations_no_confunde_la_personal_de_otro(bd: dict[str, Any]) -> None:
    """Ser miembro de la personal de otro no hace que la propia exista."""
    bd["listado"] = [(13, "Personal de Luis", True, "viewer", "2026-09-03T00:00:00+00:00", False)]
    bd["personal"] = _PERSONAL  # el camino de `ensure` la encuentra por lectura

    svc.list_organizations(7)

    # Listado → ensure (su lectura rápida) → listado otra vez.
    assert _pools(bd) == ["lectura", "lectura", "lectura"]
    sentencias = [sql for _, sql in bd["registro"]]
    assert "personal_owner_user_id = %s AND m.user_id" in sentencias[1]
