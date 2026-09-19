"""F4.6 contra Postgres: la plantilla se instancia una vez por oportunidad.

Los tests de servicio con dobles (``test_unit_plantilla_tareas.py``) fijan la
lógica; éste fija lo que sólo la base puede decir: que la clave de
idempotencia en ``pursuit_events`` —con el índice único parcial de v61— impide
la segunda instanciación, y que las tareas llegan con el plazo relativo a la
fecha límite del expediente.
"""

from __future__ import annotations

import pytest

from db.repositories.organizations import OrganizationRepository
from db.repositories.pursuit_tasks import PursuitTasksRepository
from services.organizations import OrganizationPermissionError
from services.plantilla_tareas import (
    PlantillaTareas,
    TareaPlantilla,
    guardar_plantilla,
    instanciar_en_pursuit,
    leer_plantilla,
)
from services.pursuits import create_pursuit, update_pursuit
from shared.dto import PursuitCreate, PursuitUpdate


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(email=email, password_hash="test-hash", display_name=email.split("@")[0])


def _equipo(db_mod) -> tuple[int, int, int]:
    owner = _user("plantilla-tareas-owner@example.test")
    member = _user("plantilla-tareas-member@example.test")
    repo = OrganizationRepository()
    org = int(repo.create_organization("Equipo con método", owner)["id"])
    repo.add_membership(org, member, "member")
    with db_mod.connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, fecha_limite, fecha_extraccion) VALUES (%s, %s, %s, %s)",
            ("LIC-PLANTILLA-1", "Servicio SAP", "2026-12-01T12:00:00+00:00", "2026-09-18"),
        )
    return owner, member, org


def _a_preparing(owner: int, org: int) -> int:
    pursuit, _ = create_pursuit(
        owner, PursuitCreate(licitacion_id="LIC-PLANTILLA-1", organization_id=org)
    )
    update_pursuit(owner, pursuit.id, PursuitUpdate(status="qualifying"), organization_id=org)
    update_pursuit(
        owner,
        pursuit.id,
        PursuitUpdate(status="go_no_go", decision="go", decision_reason="Encaje"),
        organization_id=org,
    )
    update_pursuit(owner, pursuit.id, PursuitUpdate(status="preparing"), organization_id=org)
    return pursuit.id


def test_pasar_a_preparing_crea_las_tareas_una_sola_vez(tmp_db) -> None:
    db_mod, _ = tmp_db
    owner, _member, org = _equipo(db_mod)
    guardar_plantilla(
        owner,
        org,
        PlantillaTareas(
            tareas=[
                TareaPlantilla(titulo="Revisión legal", dias_antes_limite=10),
                TareaPlantilla(titulo="Precio"),
            ]
        ),
    )

    pursuit_id = _a_preparing(owner, org)
    tareas = PursuitTasksRepository().list_by_pursuit(org, pursuit_id)
    assert sorted((t["titulo"], t["vence"]) for t in tareas) == [
        ("Precio", None),
        ("Revisión legal", "2026-11-21"),
    ]

    # Un reintento —o una segunda transición concurrente— no duplica.
    assert (
        instanciar_en_pursuit(
            organization_id=org,
            pursuit_id=pursuit_id,
            actor_user_id=owner,
            fecha_limite="2026-12-01",
        )
        == 0
    )
    assert len(PursuitTasksRepository().list_by_pursuit(org, pursuit_id)) == 2


def test_un_member_lee_la_plantilla_y_no_la_cambia(tmp_db) -> None:
    db_mod, _ = tmp_db
    owner, member, org = _equipo(db_mod)
    guardar_plantilla(owner, org, PlantillaTareas(tareas=[TareaPlantilla(titulo="Solvencia")]))

    leida = leer_plantilla(member, org)
    assert [t.titulo for t in leida.tareas] == ["Solvencia"]
    assert leida.puede_editar is False
    with pytest.raises(OrganizationPermissionError):
        guardar_plantilla(member, org, PlantillaTareas(tareas=[]))


def test_guardar_sustituye_y_deja_una_sola_fila(tmp_db) -> None:
    db_mod, _ = tmp_db
    owner, _member, org = _equipo(db_mod)
    guardar_plantilla(owner, org, PlantillaTareas(tareas=[TareaPlantilla(titulo="A")]))
    guardar_plantilla(owner, org, PlantillaTareas(tareas=[TareaPlantilla(titulo="B")]))

    with db_mod.connect_read() as conn:
        filas = conn.execute(
            "SELECT COUNT(*) FROM plantillas_organizacion WHERE organization_id = %s AND tipo = 'tareas'",
            (org,),
        ).fetchone()
    assert filas[0] == 1
    assert [t.titulo for t in leer_plantilla(owner, org).tareas] == ["B"]
