"""F4.6 — plantilla de tareas por etapa, ejecutada con dobles.

Lo que se fija es el comportamiento que el plan pide:

- hasta veinte tareas, con plazo relativo a la fecha límite;
- solo owner y admin la editan; cualquier miembro la lee;
- pasar a ``preparing`` crea las tareas **una sola vez** (la segunda
  reserva del evento no es nueva y no crea nada);
- sin plantilla no se reserva el evento;
- un fallo al instanciar no tumba la transición de la oportunidad.

El índice único de ``pursuit_events`` que hace real la idempotencia se prueba
contra Postgres en ``tests/test_plantilla_tareas_integracion.py``.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from tests.dobles_tenencia import alcance_fijo


class _PlantillasDoble:
    def __init__(self, contenido: dict[str, Any] | None = None) -> None:
        self.filas: list[dict[str, Any]] = (
            [{"id": 1, "tipo": "tareas", "contenido": contenido}] if contenido is not None else []
        )
        self.reemplazos: list[dict[str, Any]] = []

    def list_for_organization(self, organization_id: int, tipo: str | None = None) -> Any:
        assert tipo == "tareas"
        return list(self.filas)

    def reemplazar(self, **k: Any) -> None:
        self.reemplazos.append(k)
        self.filas = [{"id": 2, "tipo": k["tipo"], "contenido": k["contenido"]}]


class _TareasDoble:
    def __init__(self, falla_en: str | None = None) -> None:
        self.creadas: list[dict[str, Any]] = []
        self.falla_en = falla_en

    def create(self, **k: Any) -> dict[str, Any]:
        if k["titulo"] == self.falla_en:
            raise RuntimeError("BD caída")
        self.creadas.append(k)
        return {"id": len(self.creadas), **k}


class _PursuitsDoble:
    def __init__(self) -> None:
        self.claves: set[tuple[int, str]] = set()
        self.eventos: list[dict[str, Any]] = []

    def reservar_evento_unico(self, **k: Any) -> bool:
        """Mismo contrato que el índice parcial de v61: una vez por clave."""
        clave = (k["pursuit_id"], k["idempotency_key"])
        if clave in self.claves:
            return False
        self.claves.add(clave)
        self.eventos.append(k)
        return True


@pytest.fixture
def mod(monkeypatch: pytest.MonkeyPatch) -> Any:
    import services.plantilla_tareas as modulo
    import services.pursuit_tasks as tareas_mod

    sincronizadas: list[tuple[int, int]] = []
    monkeypatch.setattr(
        tareas_mod, "sincronizar_next_action", lambda org, pid: sincronizadas.append((org, pid))
    )
    monkeypatch.setattr(modulo, "_tareas", _TareasDoble())
    monkeypatch.setattr(modulo, "_pursuits", _PursuitsDoble())
    monkeypatch.setattr(modulo, "_plantillas", _PlantillasDoble())
    modulo.sincronizadas = sincronizadas  # type: ignore[attr-defined]
    return modulo


_METODO = {
    "etapa": "preparing",
    "tareas": [
        {"titulo": "Revisión legal", "dias_antes_limite": 10},
        {"titulo": "Solvencia", "dias_antes_limite": 7},
        {"titulo": "Precio", "dias_antes_limite": None},
    ],
}


class TestContrato:
    def test_mas_de_veinte_tareas_se_rechaza(self) -> None:
        from services.plantilla_tareas import MAX_TAREAS, PlantillaTareas

        with pytest.raises(ValidationError):
            PlantillaTareas(tareas=[{"titulo": f"T{i}"} for i in range(MAX_TAREAS + 1)])  # type: ignore[misc]

    def test_un_titulo_en_blanco_se_rechaza(self) -> None:
        from services.plantilla_tareas import TareaPlantilla

        with pytest.raises(ValidationError):
            TareaPlantilla(titulo="   ")

    def test_el_plazo_no_puede_ser_negativo(self) -> None:
        from services.plantilla_tareas import TareaPlantilla

        with pytest.raises(ValidationError):
            TareaPlantilla(titulo="Precio", dias_antes_limite=-1)


class TestPlazoRelativo:
    def test_resta_los_dias_a_la_fecha_limite(self) -> None:
        from services.plantilla_tareas import vence_relativo

        assert vence_relativo("2026-10-20T13:00:00", 10) == "2026-10-10"

    def test_sin_fecha_limite_no_se_inventa_plazo(self) -> None:
        from services.plantilla_tareas import vence_relativo

        assert vence_relativo(None, 5) is None

    def test_sin_dias_la_tarea_nace_sin_plazo(self) -> None:
        from services.plantilla_tareas import vence_relativo

        assert vence_relativo("2026-10-20", None) is None


class TestLecturaYEdicion:
    def test_un_member_la_lee_pero_no_la_edita(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(mod, "alcance_resuelto", alcance_fijo(7, "member"))
        monkeypatch.setattr(mod, "_plantillas", _PlantillasDoble(_METODO))

        leida = mod.leer_plantilla(1, None)
        assert [t.titulo for t in leida.tareas] == ["Revisión legal", "Solvencia", "Precio"]
        assert leida.puede_editar is False

        from services.organizations import OrganizationPermissionError

        with pytest.raises(OrganizationPermissionError):
            mod.guardar_plantilla(1, None, mod.PlantillaTareas(tareas=[]))

    @pytest.mark.parametrize("rol", ["owner", "admin"])
    def test_owner_y_admin_la_sustituyen_entera(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch, rol: str
    ) -> None:
        plantillas = _PlantillasDoble(_METODO)
        monkeypatch.setattr(mod, "alcance_resuelto", alcance_fijo(7, rol))
        monkeypatch.setattr(mod, "_plantillas", plantillas)

        guardada = mod.guardar_plantilla(
            1, 7, mod.PlantillaTareas(tareas=[mod.TareaPlantilla(titulo="Entrega")])
        )

        assert [t.titulo for t in guardada.tareas] == ["Entrega"]
        assert guardada.puede_editar is True
        assert plantillas.reemplazos[0]["tipo"] == "tareas"
        assert plantillas.reemplazos[0]["organization_id"] == 7

    def test_una_entrada_corrupta_no_tumba_la_plantilla(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(mod, "alcance_resuelto", alcance_fijo(7, "member"))
        monkeypatch.setattr(
            mod,
            "_plantillas",
            _PlantillasDoble({"tareas": [{"titulo": "Buena"}, {"titulo": ""}, "basura"]}),
        )

        assert [t.titulo for t in mod.leer_plantilla(1, None).tareas] == ["Buena"]


class TestInstanciar:
    def _instanciar(self, mod: Any, pursuit_id: int = 3) -> int:
        return int(
            mod.instanciar_en_pursuit(
                organization_id=7,
                pursuit_id=pursuit_id,
                actor_user_id=1,
                fecha_limite="2026-10-20",
            )
        )

    def test_crea_las_tareas_con_su_plazo(self, mod: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_plantillas", _PlantillasDoble(_METODO))

        assert self._instanciar(mod) == 3
        creadas = mod._tareas.creadas
        assert [(t["titulo"], t["vence"]) for t in creadas] == [
            ("Revisión legal", "2026-10-10"),
            ("Solvencia", "2026-10-13"),
            ("Precio", None),
        ]
        assert all(t["organization_id"] == 7 and t["pursuit_id"] == 3 for t in creadas)
        assert mod.sincronizadas == [(7, 3)]

    def test_la_segunda_vez_no_crea_nada(self, mod: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Idempotente por `pursuit_events`: la clave ya está reservada."""
        monkeypatch.setattr(mod, "_plantillas", _PlantillasDoble(_METODO))

        assert self._instanciar(mod) == 3
        assert self._instanciar(mod) == 0
        assert len(mod._tareas.creadas) == 3
        evento = mod._pursuits.eventos[0]
        assert evento["event_type"] == "plantilla_tareas_aplicada"
        assert evento["payload"]["origen"] == "plantilla"

    def test_otra_oportunidad_si_la_recibe(self, mod: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_plantillas", _PlantillasDoble(_METODO))

        assert self._instanciar(mod, pursuit_id=3) == 3
        assert self._instanciar(mod, pursuit_id=4) == 3

    def test_sin_plantilla_no_se_reserva_el_evento(self, mod: Any) -> None:
        """Aplicar una lista vacía no es aplicarla."""
        assert self._instanciar(mod) == 0
        assert mod._pursuits.eventos == []

    def test_una_tarea_que_falla_no_impide_las_demas(
        self, mod: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(mod, "_plantillas", _PlantillasDoble(_METODO))
        monkeypatch.setattr(mod, "_tareas", _TareasDoble(falla_en="Solvencia"))

        assert self._instanciar(mod) == 2


class TestTransicion:
    """El gancho en `update_pursuit`: sólo al entrar en `preparing`, y fail-open."""

    def test_un_fallo_de_la_plantilla_no_tumba_la_transicion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.plantilla_tareas as plantilla_mod
        import services.pursuits as mod

        def _revienta(**_k: Any) -> int:
            raise RuntimeError("plantillas_organizacion no responde")

        monkeypatch.setattr(plantilla_mod, "instanciar_en_pursuit", _revienta)
        # No lanza: la oportunidad ya avanzó y eso es lo que el usuario ve.
        mod._instanciar_plantilla_tareas({"tender_deadline": None}, 7, 3, 1)

    def test_pasa_la_fecha_limite_de_la_oportunidad(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.plantilla_tareas as plantilla_mod
        import services.pursuits as mod

        recibido: list[dict[str, Any]] = []
        monkeypatch.setattr(
            plantilla_mod, "instanciar_en_pursuit", lambda **k: recibido.append(k) or 0
        )
        mod._instanciar_plantilla_tareas({"tender_deadline": "2026-10-20"}, 7, 3, 1)

        assert recibido == [
            {
                "organization_id": 7,
                "pursuit_id": 3,
                "actor_user_id": 1,
                "fecha_limite": "2026-10-20",
            }
        ]
