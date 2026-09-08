"""Tareas de una oportunidad: el servicio, ejecutado (C6.1).

`test_c6_captura.py` ya fija este stream, pero lo hace casi todo con
`inspect.getsource`: comprueba que el **texto** del módulo dice lo que debe
decir. Eso ata la forma y no ejercita ni una línea, así que `services/
pursuit_tasks.py` entró en `master` con el 31 % de sus líneas sin ejecutar
jamás. Los dos 5xx que el fuzzing encontró en esta misma ola —una tabla mal
escrita y una dependencia sin llamar— son exactamente lo que un test de texto
no ve.

Aquí los repositorios se sustituyen por dobles y se llama a las funciones de
verdad: lo que se fija es el comportamiento —quién puede, qué se rechaza y qué
se sincroniza—, no la redacción.
"""

from __future__ import annotations

from typing import Any

import pytest


class _RepoDoble:
    """Doble de `PursuitTasksRepository` que registra lo que le piden."""

    def __init__(self, **respuestas: Any) -> None:
        self.respuestas = respuestas
        self.llamadas: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _registrar(self, nombre: str, *args: Any, **kwargs: Any) -> Any:
        self.llamadas.append((nombre, args, kwargs))
        valor = self.respuestas.get(nombre, ...)
        if valor is ...:
            return None
        if isinstance(valor, Exception):
            raise valor
        return valor

    def list_by_pursuit(self, *a: Any, **k: Any) -> Any:
        return self._registrar("list_by_pursuit", *a, **k)

    def create(self, *a: Any, **k: Any) -> Any:
        return self._registrar("create", *a, **k)

    def update(self, *a: Any, **k: Any) -> Any:
        return self._registrar("update", *a, **k)

    def delete(self, *a: Any, **k: Any) -> Any:
        return self._registrar("delete", *a, **k)

    def agenda(self, *a: Any, **k: Any) -> Any:
        return self._registrar("agenda", *a, **k)

    def siguiente_accion(self, *a: Any, **k: Any) -> Any:
        return self._registrar("siguiente_accion", *a, **k)


class _PursuitsDoble:
    def __init__(self, pursuit: dict[str, Any] | None = None) -> None:
        self.pursuit = pursuit
        self.derivadas: list[dict[str, Any]] = []

    def get(self, organization_id: int, pursuit_id: int) -> dict[str, Any] | None:
        return self.pursuit

    def set_next_action_derivada(
        self, organization_id: int, pursuit_id: int, *, titulo: Any, vence: Any
    ) -> None:
        self.derivadas.append(
            {
                "organization_id": organization_id,
                "pursuit_id": pursuit_id,
                "titulo": titulo,
                "vence": vence,
            }
        )


@pytest.fixture
def mod(monkeypatch: pytest.MonkeyPatch):
    """El módulo con sus dependencias sustituidas y una organización resuelta."""
    import services.pursuit_tasks as modulo

    resoluciones: list[dict[str, Any]] = []
    miembros_exigidos: list[tuple[int, int]] = []

    def _resolve(user_id: int, organization_id: Any = None, *, write: bool = False):
        resoluciones.append({"user_id": user_id, "org": organization_id, "write": write})
        return 7, "member"

    monkeypatch.setattr(modulo, "resolve_organization", _resolve)
    monkeypatch.setattr(
        modulo,
        "require_active_member",
        lambda org, uid: miembros_exigidos.append((org, uid)),
    )
    modulo.resoluciones = resoluciones  # type: ignore[attr-defined]
    modulo.miembros_exigidos = miembros_exigidos  # type: ignore[attr-defined]
    return modulo


def _con_repos(
    monkeypatch: pytest.MonkeyPatch,
    mod: Any,
    repo: _RepoDoble,
    pursuits: _PursuitsDoble,
) -> None:
    monkeypatch.setattr(mod, "_repo", repo)
    monkeypatch.setattr(mod, "_pursuits", pursuits)


class TestLectura:
    def test_listar_devuelve_lo_que_da_el_repositorio(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _RepoDoble(list_by_pursuit=[{"id": 1, "titulo": "Revisar pliego"}])
        _con_repos(monkeypatch, mod, repo, _PursuitsDoble({"id": 3}))

        assert mod.list_tasks(1, 3) == [{"id": 1, "titulo": "Revisar pliego"}]
        assert repo.llamadas[0] == ("list_by_pursuit", (7, 3), {})

    def test_listar_no_es_escritura(self, mod: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Un `viewer` tiene que poder leer las tareas."""
        _con_repos(monkeypatch, mod, _RepoDoble(list_by_pursuit=[]), _PursuitsDoble({"id": 3}))

        mod.list_tasks(1, 3)
        assert mod.resoluciones[-1]["write"] is False

    def test_una_oportunidad_de_otra_organizacion_no_existe(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El repositorio filtra por organización: si no vuelve, no hay nada."""
        from services.pursuits import PursuitNotFoundError

        _con_repos(monkeypatch, mod, _RepoDoble(), _PursuitsDoble(None))

        with pytest.raises(PursuitNotFoundError):
            mod.list_tasks(1, 3)

    def test_la_agenda_pasa_el_limite(self, mod: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = _RepoDoble(agenda=[{"id": 9}])
        _con_repos(monkeypatch, mod, repo, _PursuitsDoble({"id": 3}))

        assert mod.agenda(1, limit=5) == [{"id": 9}]
        assert repo.llamadas[0] == ("agenda", (7,), {"limit": 5})


class TestCrear:
    def test_crear_es_escritura(self, mod: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Un `viewer` no escribe, y quien decide eso es `resolve_organization`."""
        _con_repos(monkeypatch, mod, _RepoDoble(create={"id": 1}), _PursuitsDoble({"id": 3}))

        mod.create_task(1, 3, titulo="Revisar pliego")
        assert mod.resoluciones[-1]["write"] is True

    def test_el_responsable_tiene_que_ser_miembro_activo(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Asignar a quien ya se fue deja una tarea que nadie va a ver."""
        _con_repos(monkeypatch, mod, _RepoDoble(create={"id": 1}), _PursuitsDoble({"id": 3}))

        mod.create_task(1, 3, titulo="Revisar", responsable_user_id=42)
        assert mod.miembros_exigidos == [(7, 42)]

    def test_sin_responsable_no_se_comprueba_nada(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _con_repos(monkeypatch, mod, _RepoDoble(create={"id": 1}), _PursuitsDoble({"id": 3}))

        mod.create_task(1, 3, titulo="Revisar")
        assert mod.miembros_exigidos == []

    def test_si_el_insert_no_devuelve_fila_la_oportunidad_no_era_suya(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El `INSERT ... SELECT` es el que filtra; `None` significa «no es tuya»."""
        from services.pursuits import PursuitNotFoundError

        _con_repos(monkeypatch, mod, _RepoDoble(create=None), _PursuitsDoble({"id": 3}))

        with pytest.raises(PursuitNotFoundError):
            mod.create_task(1, 3, titulo="Revisar")

    def test_crear_sincroniza_la_accion_siguiente(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _RepoDoble(
            create={"id": 1}, siguiente_accion={"titulo": "Revisar", "vence": "2026-10-01"}
        )
        pursuits = _PursuitsDoble({"id": 3})
        _con_repos(monkeypatch, mod, repo, pursuits)

        mod.create_task(1, 3, titulo="Revisar")
        assert pursuits.derivadas == [
            {"organization_id": 7, "pursuit_id": 3, "titulo": "Revisar", "vence": "2026-10-01"}
        ]


class TestActualizar:
    def test_un_estado_fuera_del_vocabulario_se_rechaza(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _con_repos(monkeypatch, mod, _RepoDoble(), _PursuitsDoble({"id": 3}))

        with pytest.raises(ValueError, match="estado inválido"):
            mod.update_task(1, 3, 5, estado="terminada")

    def test_los_cuatro_estados_validos_pasan(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from db.repositories.pursuit_tasks import ESTADOS

        for estado in ESTADOS:
            repo = _RepoDoble(update={"id": 5, "estado": estado})
            _con_repos(monkeypatch, mod, repo, _PursuitsDoble({"id": 3}))
            assert mod.update_task(1, 3, 5, estado=estado)["estado"] == estado

    def test_reasignar_tambien_exige_miembro_activo(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _con_repos(monkeypatch, mod, _RepoDoble(update={"id": 5}), _PursuitsDoble({"id": 3}))

        mod.update_task(1, 3, 5, responsable_user_id=42)
        assert mod.miembros_exigidos == [(7, 42)]

    def test_una_tarea_que_no_vuelve_no_existe(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _con_repos(monkeypatch, mod, _RepoDoble(update=None), _PursuitsDoble({"id": 3}))

        with pytest.raises(mod.PursuitTaskNotFoundError):
            mod.update_task(1, 3, 5, titulo="Otro")

    def test_actualizar_sincroniza(self, mod: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        pursuits = _PursuitsDoble({"id": 3})
        _con_repos(
            monkeypatch,
            mod,
            _RepoDoble(update={"id": 5}, siguiente_accion=None),
            pursuits,
        )

        mod.update_task(1, 3, 5, estado="hecha")
        # Sin tarea abierta, la derivada se vacía en vez de quedarse obsoleta.
        assert pursuits.derivadas == [
            {"organization_id": 7, "pursuit_id": 3, "titulo": None, "vence": None}
        ]


class TestBorrar:
    def test_borrar_lo_que_no_esta_es_un_error(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _con_repos(monkeypatch, mod, _RepoDoble(delete=False), _PursuitsDoble({"id": 3}))

        with pytest.raises(mod.PursuitTaskNotFoundError):
            mod.delete_task(1, 3, 5)

    def test_borrar_sincroniza(self, mod: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        pursuits = _PursuitsDoble({"id": 3})
        _con_repos(
            monkeypatch,
            mod,
            _RepoDoble(delete=True, siguiente_accion={"titulo": "Otra", "vence": None}),
            pursuits,
        )

        mod.delete_task(1, 3, 5)
        assert pursuits.derivadas[-1]["titulo"] == "Otra"


class TestSincronizacionDerivada:
    def test_un_fallo_al_derivar_no_pierde_la_tarea(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail-open: la tarea ya está guardada y el campo se recalcula luego.

        Perder la escritura por no poder actualizar un campo **derivado** sería
        el peor intercambio posible.
        """
        repo = _RepoDoble(create={"id": 1}, siguiente_accion=RuntimeError("BD caída"))
        _con_repos(monkeypatch, mod, repo, _PursuitsDoble({"id": 3}))

        assert mod.create_task(1, 3, titulo="Revisar") == {"id": 1}
