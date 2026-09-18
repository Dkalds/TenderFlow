"""F2.3 + C6.1 — el responsable de un documento del kit es el de su tarea.

Lo que se fija:

- el ledger mezcla marcados y asignaciones bajo el mismo tipo de evento, y
  ninguno de los dos puede pisar al otro;
- un ítem cuya tarea se borró sale **sin** responsable;
- asignar dos veces el mismo documento reasigna la tarea, no crea otra.

Los repositorios se sustituyen por dobles: aquí no hay base de datos.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from services.kit_presentacion import construir_kit, reducir_eventos
from shared.tender_facts import EvidenceRef, RequiredDocumentFact
from tests.dobles_tenencia import alcance_fijo

_CITA = EvidenceRef(documento_id=1, page_number=2, quote="deberá aportarse")


def _doc(nombre: str, sobre: str = "sobre_a") -> RequiredDocumentFact:
    return RequiredDocumentFact(
        description=f"Documento: {nombre}",
        confidence=0.9,
        evidence=[_CITA],
        name=nombre,
        scope=sobre,  # type: ignore[arg-type]  # literal validado por el modelo
    )


def _evento(payload: dict[str, Any], actor: int = 1, en: str = "2026-09-18") -> dict[str, Any]:
    return {"payload_json": json.dumps(payload), "actor_user_id": actor, "created_at": en}


class TestReduccion:
    def test_asignar_no_desmarca(self) -> None:
        estado = reducir_eventos(
            [
                _evento({"clave": "0:deuc", "listo": True}),
                _evento({"clave": "0:deuc", "tarea_id": 9}),
            ]
        )
        assert estado["0:deuc"]["listo"] is True
        assert estado["0:deuc"]["tarea_id"] == 9

    def test_marcar_no_suelta_la_tarea(self) -> None:
        estado = reducir_eventos(
            [
                _evento({"clave": "0:deuc", "tarea_id": 9}),
                _evento({"clave": "0:deuc", "listo": True}, actor=4),
                _evento({"clave": "0:deuc", "listo": False}, actor=5),
            ]
        )
        assert estado["0:deuc"] == {
            "tarea_id": 9,
            "listo": False,
            "marcado_por": 5,
            "marcado_en": "2026-09-18",
        }

    def test_la_ultima_asignacion_manda(self) -> None:
        estado = reducir_eventos(
            [_evento({"clave": "k", "tarea_id": 1}), _evento({"clave": "k", "tarea_id": 2})]
        )
        assert estado["k"]["tarea_id"] == 2

    @pytest.mark.parametrize("basura", ["no-json", json.dumps([1, 2]), json.dumps({"listo": True})])
    def test_los_eventos_ilegibles_se_ignoran(self, basura: str) -> None:
        assert reducir_eventos([{"payload_json": basura, "actor_user_id": 1}]) == {}

    def test_un_tarea_id_que_no_es_entero_positivo_se_ignora(self) -> None:
        estado = reducir_eventos(
            [_evento({"clave": "k", "tarea_id": True}), _evento({"clave": "k", "tarea_id": "3"})]
        )
        assert "tarea_id" not in estado["k"]


class TestResponsableEnElKit:
    def test_el_item_lleva_el_responsable_de_su_tarea(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.kit_presentacion as kit_mod

        documento = _doc("DEUC")
        from services.kit_presentacion import clave_de

        clave = clave_de(0, documento)
        monkeypatch.setattr(
            kit_mod._repo,
            "kit_events",
            lambda org, pid: [_evento({"clave": clave, "tarea_id": 9})],
        )
        tareas = {
            9: {
                "id": 9,
                "responsable_user_id": 42,
                "responsable_name": "Ana",
                "estado": "en_curso",
                "vence": "2026-10-01",
            }
        }

        kit = construir_kit("EXP-1", [documento], organization_id=7, pursuit_id=3, tareas=tareas)

        item = kit.items[0]
        assert (item.tarea_id, item.responsable_user_id, item.responsable_name) == (9, 42, "Ana")
        assert (item.tarea_estado, item.tarea_vence) == ("en_curso", "2026-10-01")

    def test_una_tarea_borrada_deja_el_item_sin_responsable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Enseñar a quien la tenía afirmaría un reparto que el equipo deshizo."""
        import services.kit_presentacion as kit_mod
        from services.kit_presentacion import clave_de

        documento = _doc("DEUC")
        monkeypatch.setattr(
            kit_mod._repo,
            "kit_events",
            lambda org, pid: [_evento({"clave": clave_de(0, documento), "tarea_id": 9})],
        )

        kit = construir_kit("EXP-1", [documento], organization_id=7, pursuit_id=3, tareas={})

        assert kit.items[0].tarea_id is None
        assert kit.items[0].responsable_name is None


class _Detalle:
    licitacion_id = "EXP-1"
    organization_id = 7


@pytest.fixture
def entorno(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """`asignar_kit_de_pursuit` con tareas, ledger y pliego doblados."""
    import services.kit_presentacion as kit_mod
    import services.pursuit_tasks as tareas_mod
    import services.pursuits as mod

    documento = _doc("Garantía provisional")
    eventos: list[dict[str, Any]] = []
    tareas_vivas: dict[int, dict[str, Any]] = {}
    llamadas: list[tuple[str, dict[str, Any]]] = []

    monkeypatch.setattr(mod, "alcance_resuelto", alcance_fijo(7, "member"))
    monkeypatch.setattr(mod, "get_pursuit", lambda *a, **k: _Detalle())
    monkeypatch.setattr(mod, "_documentos_del_pliego", lambda lic: [documento])
    monkeypatch.setattr(mod, "_tareas_vivas", lambda org, pid: dict(tareas_vivas))
    monkeypatch.setattr(kit_mod._repo, "kit_events", lambda org, pid: list(eventos))
    monkeypatch.setattr(
        kit_mod._repo,
        "append_kit_event",
        lambda **k: eventos.append(_evento(k["payload"], actor=k["actor_user_id"])),
    )

    def _crear(user_id: int, pursuit_id: int, **k: Any) -> dict[str, Any]:
        llamadas.append(("create", k))
        fila = {
            "id": 50 + len(tareas_vivas),
            "responsable_user_id": k["responsable_user_id"],
            "responsable_name": f"U{k['responsable_user_id']}",
            "estado": "pendiente",
            "vence": k.get("vence"),
        }
        tareas_vivas[int(fila["id"])] = fila
        return fila

    def _actualizar(user_id: int, pursuit_id: int, task_id: int, **k: Any) -> dict[str, Any]:
        llamadas.append(("update", {"task_id": task_id, **k}))
        tareas_vivas[task_id]["responsable_user_id"] = k["responsable_user_id"]
        tareas_vivas[task_id]["responsable_name"] = f"U{k['responsable_user_id']}"
        return tareas_vivas[task_id]

    monkeypatch.setattr(tareas_mod, "create_task", _crear)
    monkeypatch.setattr(tareas_mod, "update_task", _actualizar)

    from services.kit_presentacion import clave_de

    return {"mod": mod, "clave": clave_de(0, documento), "llamadas": llamadas}


class TestAsignar:
    def test_asignar_crea_la_tarea_con_el_nombre_del_documento(
        self, entorno: dict[str, Any]
    ) -> None:
        kit = entorno["mod"].asignar_kit_de_pursuit(
            1, 3, clave=entorno["clave"], responsable_user_id=42, vence="2026-10-01"
        )

        tipo, args = entorno["llamadas"][0]
        assert tipo == "create"
        assert args["titulo"] == "Kit: Garantía provisional"
        assert args["responsable_user_id"] == 42
        assert kit.items[0].responsable_name == "U42"

    def test_asignar_dos_veces_reasigna_en_vez_de_duplicar(self, entorno: dict[str, Any]) -> None:
        """Dos tareas para el mismo papel son dos personas creyendo que lo lleva la otra."""
        mod = entorno["mod"]
        mod.asignar_kit_de_pursuit(1, 3, clave=entorno["clave"], responsable_user_id=42)
        kit = mod.asignar_kit_de_pursuit(1, 3, clave=entorno["clave"], responsable_user_id=43)

        assert [tipo for tipo, _ in entorno["llamadas"]] == ["create", "update"]
        assert kit.items[0].responsable_user_id == 43

    def test_una_clave_que_no_esta_en_el_kit_es_un_error(self, entorno: dict[str, Any]) -> None:
        from services.pursuits import PursuitValidationError

        with pytest.raises(PursuitValidationError):
            entorno["mod"].asignar_kit_de_pursuit(
                1, 3, clave="99:inventado", responsable_user_id=42
            )
        assert entorno["llamadas"] == []
