"""SQL de la plantilla go/no-go (``db/repositories/go_no_go.py``) contra Postgres.

El servicio tiene sus tests con el repositorio doblado
(``tests/test_unit_go_no_go_puntuacion_service.py``); aquí se fija lo que solo
el SQL puede garantizar: el upsert de pesos sin ventana vacía, y que una
puntuación no se escribe sobre un pursuit de otra organización.
"""

from __future__ import annotations

from typing import Any

import pytest

from db.repositories.go_no_go import MAX_MOTIVO, GoNoGoRepository

_AHORA = "2026-10-01T00:00:00+00:00"


def _usuario_y_organizacion(correo: str) -> tuple[int, int]:
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    user_id = create_user(
        email=correo,
        password_hash="x",  # pragma: allowlist secret
        display_name="Ana",
    )
    return user_id, int(OrganizationRepository().ensure_personal_organization(user_id)["id"])


def _pursuit(db_mod: Any, org_id: int, user_id: int) -> int:
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion, fuente) "
            "VALUES ('L1', 'Soporte TI', %s, 'placsp') ON CONFLICT (id_externo) DO NOTHING",
            (_AHORA,),
        )
        fila = c.execute(
            "INSERT INTO pursuits (licitacion_id, organization_id, responsible_user_id, "
            " identified_at, created_at, updated_at) "
            "VALUES ('L1', %s, %s, %s, %s, %s) RETURNING id",
            (org_id, user_id, _AHORA, _AHORA, _AHORA),
        ).fetchone()
    return int(fila[0])


# ── Pesos ───────────────────────────────────────────────────────────────────


def test_guardar_pesos_ignora_criterios_desconocidos_y_recorta_negativos(tmp_db: Any) -> None:
    _, org = _usuario_y_organizacion("ana@empresa.example")

    pesos = GoNoGoRepository().guardar_pesos(org, {"encaje": 2.5, "riesgo": -1.0, "otro": 9.0})

    assert pesos == {"encaje": 2.5, "riesgo": 0.0}


def test_guardar_pesos_dos_veces_actualiza_sin_duplicar(tmp_db: Any) -> None:
    _, org = _usuario_y_organizacion("ana@empresa.example")
    repo = GoNoGoRepository()
    repo.guardar_pesos(org, {"encaje": 1.0, "capacidad": 3.0})

    pesos = repo.guardar_pesos(org, {"encaje": 4.0})

    assert pesos == {"encaje": 4.0, "capacidad": 3.0}


def test_los_pesos_son_de_cada_organizacion(tmp_db: Any) -> None:
    _, org_a = _usuario_y_organizacion("ana@empresa.example")
    _, org_b = _usuario_y_organizacion("bea@otra.example")
    repo = GoNoGoRepository()
    repo.guardar_pesos(org_a, {"encaje": 2.0})

    assert repo.pesos(org_b) == {}


# ── Puntuaciones ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("criterio", "puntuacion"),
    [("inventado", 3), ("encaje", 0), ("encaje", 6)],
)
def test_puntuar_valida_criterio_y_rango_antes_de_escribir(criterio: str, puntuacion: int) -> None:
    with pytest.raises(ValueError):
        GoNoGoRepository().puntuar(
            organization_id=1, pursuit_id=1, criterio=criterio, puntuacion=puntuacion
        )


def test_puntuar_un_pursuit_ajeno_no_escribe(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    user_a, org_a = _usuario_y_organizacion("ana@empresa.example")
    _, org_b = _usuario_y_organizacion("bea@otra.example")
    pursuit = _pursuit(db_mod, org_a, user_a)
    repo = GoNoGoRepository()

    escrito = repo.puntuar(
        organization_id=org_b, pursuit_id=pursuit, criterio="encaje", puntuacion=4
    )

    assert escrito is False
    assert repo.puntuaciones(org_a, pursuit) == []


def test_repuntuar_reemplaza_la_puntuacion_y_el_motivo(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    user, org = _usuario_y_organizacion("ana@empresa.example")
    pursuit = _pursuit(db_mod, org, user)
    repo = GoNoGoRepository()
    repo.puntuar(
        organization_id=org, pursuit_id=pursuit, criterio="capacidad", puntuacion=2, motivo="sin BW"
    )

    escrito = repo.puntuar(
        organization_id=org,
        pursuit_id=pursuit,
        criterio="capacidad",
        puntuacion=4,
        motivo="contratamos BW",
        author_user_id=user,
    )

    assert escrito is True
    (fila,) = repo.puntuaciones(org, pursuit)
    assert (fila["puntuacion"], fila["motivo"], fila["author_name"]) == (4, "contratamos BW", "Ana")


def test_el_motivo_se_trunca_y_el_vacio_se_guarda_como_nulo(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    user, org = _usuario_y_organizacion("ana@empresa.example")
    pursuit = _pursuit(db_mod, org, user)
    repo = GoNoGoRepository()

    repo.puntuar(
        organization_id=org, pursuit_id=pursuit, criterio="encaje", puntuacion=3, motivo="x" * 2000
    )
    repo.puntuar(
        organization_id=org, pursuit_id=pursuit, criterio="riesgo", puntuacion=3, motivo=""
    )

    motivos = {f["criterio"]: f["motivo"] for f in repo.puntuaciones(org, pursuit)}
    assert len(motivos["encaje"]) == MAX_MOTIVO
    assert motivos["riesgo"] is None
