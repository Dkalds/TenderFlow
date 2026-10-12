"""El checklist de una oportunidad lee la solvencia oficial de PLACSP (v149).

Integración: ``build_checklist`` es quien junta oportunidad, ficha, capacidad y
—desde v149— condiciones oficiales. Lo que se comprueba aquí es ese cableado
(la regla de cada familia la fija ``test_go_no_go_condiciones_oficiales.py``):

- sin ficha del pliego pero con solvencia oficial, el checklist contrasta y
  **se sella** —hay algo que evaluar—, una sola vez por versión;
- una oportunidad abierta sobre un lote solo ve el expediente y ese lote.
"""

from __future__ import annotations

from typing import Any

from db.repositories.organizations import OrganizationRepository
from db.upsert import (
    CondicionesCodice,
    Licitacion,
    Lote,
    RequisitoSolvencia,
    replace_lotes,
    upsert_licitaciones_with_history,
)
from services.go_no_go import build_checklist
from shared.dto import PursuitCreate

LIC = "LIC-OFICIAL-1"


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(email=email, password_hash="test-hash")  # pragma: allowlist secret


def _escenario(*, con_lote: bool = False) -> tuple[int, int, int]:
    upsert_licitaciones_with_history(
        [
            Licitacion(
                id_externo=LIC,
                titulo="Soporte SAP",
                condiciones=CondicionesCodice(
                    solvencia=[
                        RequisitoSolvencia(
                            orden=1,
                            clase="economica",
                            descripcion="Volumen anual de negocios",
                            umbral_importe=500_000.0,
                        ),
                        RequisitoSolvencia(
                            orden=1,
                            lote_numero="1",
                            clase="economica",
                            descripcion="Seguro de RC del lote 1",
                        ),
                        RequisitoSolvencia(
                            orden=1,
                            lote_numero="2",
                            clase="economica",
                            descripcion="Seguro de RC del lote 2",
                        ),
                    ]
                ),
            )
        ],
        source="placsp",
    )
    ids = replace_lotes(
        LIC,
        [
            Lote(licitacion_id=LIC, numero="1", titulo="Lote uno"),
            Lote(licitacion_id=LIC, numero="2", titulo="Lote dos"),
        ],
    )
    owner = _user("owner-oficial@example.test")
    organization_id = int(OrganizationRepository().create_organization("Equipo", owner)["id"])
    from services.pursuits import create_pursuit

    creado, _ = create_pursuit(
        owner,
        PursuitCreate(
            licitacion_id=LIC,
            organization_id=organization_id,
            lote_id=ids["2"] if con_lote else None,
        ),
    )
    return owner, organization_id, int(creado.id)


def _eventos(db_mod: Any, pursuit_id: int) -> int:
    with db_mod.connect_read() as conn:
        fila = conn.execute(
            "SELECT COUNT(*) FROM pursuit_events "
            "WHERE pursuit_id = %s AND event_type = 'checklist_evaluated'",
            (pursuit_id,),
        ).fetchone()
    return int(fila[0])


def test_sin_ficha_contrasta_la_solvencia_oficial_y_sella_una_vez(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    owner, organization_id, pursuit_id = _escenario()

    checklist = build_checklist(owner, pursuit_id, organization_id=organization_id)
    build_checklist(owner, pursuit_id, organization_id=organization_id)

    assert checklist.ficha_estado is None
    assert checklist.usa_condiciones_oficiales is True
    economica = next(f for f in checklist.familias if f.familia == "economic_solvency")
    assert economica.fuente == "placsp"
    assert [i.requisito for i in economica.items] == [
        "Volumen anual de negocios",
        "Lote 1 · Seguro de RC del lote 1",
        "Lote 2 · Seguro de RC del lote 2",
    ]
    assert _eventos(db_mod, pursuit_id) == 1


def test_una_oportunidad_de_lote_solo_ve_su_lote(tmp_db: Any) -> None:
    owner, organization_id, pursuit_id = _escenario(con_lote=True)

    checklist = build_checklist(owner, pursuit_id, organization_id=organization_id)

    economica = next(f for f in checklist.familias if f.familia == "economic_solvency")
    assert [i.requisito for i in economica.items] == [
        "Volumen anual de negocios",
        "Seguro de RC del lote 2",
    ]
