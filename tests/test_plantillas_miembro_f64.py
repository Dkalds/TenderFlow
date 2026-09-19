"""F6.4 — las plantillas de organización llegan al miembro nuevo.

Dos huecos que cerraban la función entre los dos:

- ``services.cuentas.aplicar_plantillas`` no tenía ningún llamador: aceptar una
  invitación activaba la membresía y el miembro empezaba vacío.
- Nadie podía definir las plantillas: solo existía la de tareas (F4.6), que
  ``aplicar_plantillas`` ignora.

Estos tests fijan el cableado de la aceptación y la API mínima para definir
reglas y vistas por defecto, sin base de datos.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

import services.plantillas_miembro as svc
from services.organizations import (
    OrganizationPermissionError,
    accept_invitation_token,
    accept_invitations_for_email,
)
from services.plantillas_miembro import (
    PlantillaMiembroIn,
    PlantillaNoEncontradaError,
    PlantillasLimiteError,
)
from services.watchlist_rules import WatchlistRule

_APLICAR = "services.cuentas.aplicar_plantillas"
_REPO_ORG = "services.organizations._repo"

# ── La aceptación aplica las plantillas ──────────────────────────────────────


def test_aceptar_por_correo_aplica_las_plantillas_de_cada_organizacion() -> None:
    with (
        patch(f"{_REPO_ORG}.accept_invitations_for_email") as aceptar,
        patch(_APLICAR) as aplicar,
    ):
        aceptar.return_value = [
            {"id": 1, "organization_id": 7},
            {"id": 2, "organization_id": 9},
            {"id": 3, "organization_id": 7},
        ]
        assert accept_invitations_for_email(42, "nuevo@example.com") == 3

    # Una vez por organización, no por invitación.
    assert sorted(c.args for c in aplicar.call_args_list) == [(7, 42), (9, 42)]


def test_un_fallo_copiando_no_deja_a_nadie_fuera() -> None:
    with (
        patch(f"{_REPO_ORG}.accept_invitations_for_email", return_value=[{"organization_id": 7}]),
        patch(_APLICAR, side_effect=RuntimeError("BD caída")),
    ):
        assert accept_invitations_for_email(42, "nuevo@example.com") == 1


def test_sin_invitaciones_no_se_aplica_nada() -> None:
    with (
        patch(f"{_REPO_ORG}.accept_invitations_for_email", return_value=[]),
        patch(_APLICAR) as aplicar,
    ):
        assert accept_invitations_for_email(42, "nuevo@example.com") == 0
    aplicar.assert_not_called()


def test_canjear_el_enlace_tambien_aplica_las_plantillas() -> None:
    with (
        patch("services.organizations._invitation_signature_valid", return_value=True),
        patch(
            f"{_REPO_ORG}.get_pending_invitation_by_token",
            return_value={"organization_id": 7, "email": "nuevo@example.com"},
        ),
        patch(
            f"{_REPO_ORG}.accept_invitations_for_email",
            return_value=[{"organization_id": 7}],
        ),
        patch(
            f"{_REPO_ORG}.get_for_user",
            return_value={"id": 7, "name": "Equipo", "slug": "equipo", "role": "member"},
        ),
        patch("services.organizations.OrganizationSummary.model_validate", return_value="ok"),
        patch(_APLICAR) as aplicar,
    ):
        accept_invitation_token(42, "nuevo@example.com", "token")
    aplicar.assert_called_once_with(7, 42)


# ── El contrato del alta ─────────────────────────────────────────────────────


def test_una_regla_sin_criterios_no_se_acepta() -> None:
    with pytest.raises(ValidationError):
        PlantillaMiembroIn(tipo="regla", nombre="SAP en Madrid")


def test_una_vista_necesita_un_objeto_json() -> None:
    with pytest.raises(ValidationError):
        PlantillaMiembroIn(tipo="vista", nombre="Mi vista", filters_json="[1, 2]")
    with pytest.raises(ValidationError):
        PlantillaMiembroIn(tipo="vista", nombre="Mi vista", filters_json="no es json")
    assert PlantillaMiembroIn(tipo="vista", nombre="Mi vista", filters_json='{"ccaa": "Madrid"}')


def test_el_tipo_de_tareas_no_se_crea_desde_aqui() -> None:
    with pytest.raises(ValidationError):
        PlantillaMiembroIn.model_validate({"tipo": "tareas", "nombre": "x"})


def test_la_regla_guarda_criterios_y_no_identidad() -> None:
    plantilla = PlantillaMiembroIn(
        tipo="regla",
        nombre="SAP en Madrid",
        regla=WatchlistRule(
            id=99, keyword="SAP", ccaa="Madrid", organization_id=3, visibility="organization"
        ),
    )
    contenido = svc._contenido(plantilla)
    assert "id" not in contenido
    assert "organization_id" not in contenido
    assert "visibility" not in contenido
    # Es lo que `_copiar_para_miembro` hace con él: tiene que volver a ser una regla.
    copia = WatchlistRule(**contenido)
    assert (copia.keyword, copia.ccaa, copia.nombre) == ("SAP", "Madrid", "SAP en Madrid")


def test_la_vista_guarda_el_criterio_que_lee_la_copia() -> None:
    plantilla = PlantillaMiembroIn(tipo="vista", nombre="Madrid", filters_json='{"ccaa": "Madrid"}')
    assert svc._contenido(plantilla) == {"nombre": "Madrid", "criterio": {"ccaa": "Madrid"}}


# ── Leer, crear y borrar ─────────────────────────────────────────────────────


def _alcance(rol: str) -> Any:
    @contextmanager
    def _falso(user_id: int, organization_id: int | None, **_: Any) -> Iterator[tuple[int, str]]:
        yield 7, rol

    return _falso


class _Repo:
    def __init__(self, filas: list[dict[str, Any]]) -> None:
        self.filas = filas
        self.creadas: list[dict[str, Any]] = []
        self.borradas: list[int] = []

    def list_for_organization(self, organization_id: int, tipo: str | None = None) -> Any:
        return list(self.filas)

    def create(self, **kwargs: Any) -> int:
        self.creadas.append(kwargs)
        return 1

    def delete(self, organization_id: int, plantilla_id: int) -> bool:
        self.borradas.append(plantilla_id)
        return True


_FILAS = [
    {"id": 1, "tipo": "regla", "nombre": "SAP", "contenido": {"keyword": "SAP"}},
    {"id": 2, "tipo": "vista", "nombre": "Madrid", "contenido": {"criterio": {"ccaa": "Madrid"}}},
    {"id": 3, "tipo": "tareas", "nombre": "Tareas", "contenido": {"tareas": []}},
]


def test_la_lista_solo_trae_las_de_miembro(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "_repo", _Repo(_FILAS))
    monkeypatch.setattr(svc, "alcance_resuelto", _alcance("member"))
    salida = svc.leer_plantillas_miembro(5, 7)
    assert [p.id for p in salida.plantillas] == [1, 2]
    assert salida.plantillas[0].regla is not None
    assert json.loads(salida.plantillas[1].filters_json or "") == {"ccaa": "Madrid"}
    assert salida.puede_editar is False


def test_un_miembro_no_puede_crear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "_repo", _Repo([]))
    monkeypatch.setattr(svc, "alcance_resuelto", _alcance("member"))
    with pytest.raises(OrganizationPermissionError):
        svc.crear_plantilla_miembro(
            5, 7, PlantillaMiembroIn(tipo="vista", nombre="V", filters_json="{}")
        )


def test_un_admin_crea_y_el_tope_se_respeta(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _Repo([])
    monkeypatch.setattr(svc, "_repo", repo)
    monkeypatch.setattr(svc, "alcance_resuelto", _alcance("admin"))
    svc.crear_plantilla_miembro(
        5, 7, PlantillaMiembroIn(tipo="regla", nombre="SAP", regla=WatchlistRule(keyword="SAP"))
    )
    assert repo.creadas[0]["tipo"] == "regla"
    assert repo.creadas[0]["organization_id"] == 7

    lleno = [
        {"id": i, "tipo": "vista", "nombre": f"V{i}", "contenido": {"criterio": {}}}
        for i in range(svc.MAX_PLANTILLAS)
    ]
    monkeypatch.setattr(svc, "_repo", _Repo(lleno))
    with pytest.raises(PlantillasLimiteError):
        svc.crear_plantilla_miembro(
            5, 7, PlantillaMiembroIn(tipo="vista", nombre="V", filters_json="{}")
        )


def test_borrar_la_plantilla_de_tareas_desde_aqui_es_no_encontrada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _Repo(_FILAS)
    monkeypatch.setattr(svc, "_repo", repo)
    monkeypatch.setattr(svc, "alcance_resuelto", _alcance("owner"))
    with pytest.raises(PlantillaNoEncontradaError):
        svc.borrar_plantilla_miembro(5, 7, 3)
    assert repo.borradas == []

    svc.borrar_plantilla_miembro(5, 7, 1)
    assert repo.borradas == [1]
