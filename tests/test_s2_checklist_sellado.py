"""S2.3 — el checklist se sella una vez por versión de ficha, no por visita.

Integración: el sellado es un ``INSERT ... ON CONFLICT DO NOTHING`` contra el
único ``uq_pursuit_events_idempotency`` de ``v61``, y lo que se comprueba es
justo ese índice. El ledger es append-only por trigger, así que un sellado por
apertura de pestaña lo llenaría de ruido irreversible.

Todas las llamadas a ``build_checklist`` pasan ``organization_id`` explícito.
No es ceremonia: el escenario abre la oportunidad en una organización
compartida, y omitir el parámetro hace que ``resolve_organization`` caiga —con
razón— a la organización **personal** del usuario, donde esa oportunidad no
existe. Es la misma organización que se le pasa a ``create_pursuit``; nombrarla
en un sitio y callarla en el otro es lo que hacía que el checklist no
encontrase la oportunidad que el propio test acababa de crear.
"""

from __future__ import annotations

from db.repositories.organizations import OrganizationRepository
from db.repositories.pursuits import PursuitRepository
from db.repositories.tender_fact_sheets import TenderFactSheetsRepository
from services.go_no_go import build_checklist
from shared.dto import PursuitCreate

_FACTS = {
    "certifications": [
        {
            "name": "ISO/IEC 27001",
            "scope": "company",
            "description": "Seguridad de la información.",
            "confidence": 0.9,
            "evidence": [
                {"documento_id": 1, "page_number": 4, "quote": "Certificación ISO/IEC 27001."}
            ],
        }
    ]
}


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(email=email, password_hash="test-hash")  # pragma: allowlist secret


def _escenario(db_mod, licitacion_id: str = "LIC-CHECKLIST-1") -> tuple[int, int, int]:
    owner = _user(f"owner-{licitacion_id.lower()}@example.test")
    organization_id = int(OrganizationRepository().create_organization("Equipo GNG", owner)["id"])
    with db_mod.connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, fecha_limite, fecha_extraccion) VALUES (%s, %s, %s, %s)",
            (
                licitacion_id,
                "Servicio de seguridad",
                "2026-12-01T12:00:00+00:00",
                "2026-07-30T10:00:00+00:00",
            ),
        )
    from services.pursuits import create_pursuit

    creado, _ = create_pursuit(
        owner,
        PursuitCreate(licitacion_id=licitacion_id, organization_id=organization_id),
    )
    return owner, organization_id, int(creado.id)


def _eventos_checklist(db_mod, pursuit_id: int) -> int:
    with db_mod.connect_read() as conn:
        fila = conn.execute(
            "SELECT COUNT(*) FROM pursuit_events "
            "WHERE pursuit_id = %s AND event_type = 'checklist_evaluated'",
            (pursuit_id,),
        ).fetchone()
    return int(fila[0])


def test_repetir_la_evaluacion_no_vuelve_a_sellar(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id, pursuit_id = _escenario(db_mod)
    TenderFactSheetsRepository().upsert(
        licitacion_id="LIC-CHECKLIST-1",
        status="extracted",
        extraction_version="v3",
        model="modelo-test",
        facts=_FACTS,
        field_count=1,
        evidence_count=1,
    )

    primero = build_checklist(owner, pursuit_id, organization_id=organization_id)
    build_checklist(owner, pursuit_id, organization_id=organization_id)
    build_checklist(owner, pursuit_id, organization_id=organization_id)

    assert primero.extraction_version == "v3"
    assert _eventos_checklist(db_mod, pursuit_id) == 1


def test_una_ficha_reextraida_sella_otra_vez(tmp_db):
    """Otra ficha es otro veredicto, aunque la versión del extractor no cambie."""
    db_mod, _ = tmp_db
    owner, organization_id, pursuit_id = _escenario(db_mod, "LIC-CHECKLIST-2")
    sheets = TenderFactSheetsRepository()
    sheets.upsert(
        licitacion_id="LIC-CHECKLIST-2",
        status="extracted",
        extraction_version="v3",
        model="modelo-test",
        facts=_FACTS,
        field_count=1,
        evidence_count=1,
    )
    build_checklist(owner, pursuit_id, organization_id=organization_id)

    sheets.upsert(
        licitacion_id="LIC-CHECKLIST-2",
        status="extracted",
        extraction_version="v3",
        model="modelo-test",
        facts={**_FACTS, "team_requirements": []},
        field_count=1,
        evidence_count=1,
    )
    build_checklist(owner, pursuit_id, organization_id=organization_id)

    assert _eventos_checklist(db_mod, pursuit_id) == 2


def test_sin_ficha_no_se_sella_nada(tmp_db):
    """Sellar «se evaluó» de algo que no se pudo evaluar sería mentir al ledger."""
    db_mod, _ = tmp_db
    owner, organization_id, pursuit_id = _escenario(db_mod, "LIC-CHECKLIST-3")

    checklist = build_checklist(owner, pursuit_id, organization_id=organization_id)

    assert checklist.ficha_estado is None
    assert {familia.veredicto for familia in checklist.familias} == {"desconocido"}
    assert _eventos_checklist(db_mod, pursuit_id) == 0


def test_el_ledger_conserva_el_evento_de_creacion(tmp_db):
    """Guarda contra un sellado que pisara el ledger existente."""
    db_mod, _ = tmp_db
    owner, organization_id, pursuit_id = _escenario(db_mod, "LIC-CHECKLIST-4")
    TenderFactSheetsRepository().upsert(
        licitacion_id="LIC-CHECKLIST-4",
        status="extracted",
        extraction_version="v3",
        model="modelo-test",
        facts=_FACTS,
        field_count=1,
        evidence_count=1,
    )
    build_checklist(owner, pursuit_id, organization_id=organization_id)

    tipos = {
        evento["event_type"]
        for evento in PursuitRepository().list_events(organization_id, pursuit_id)
    }
    assert "checklist_evaluated" in tipos
    assert len(tipos) >= 2
