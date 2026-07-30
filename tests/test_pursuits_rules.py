"""Reglas de negocio del workflow de oportunidades.

``test_pursuits.py`` cubre el camino feliz completo (crear → cualificar →
decidir → presentar → ganar) y el ledger append-only. Este módulo cubre lo
contrario: cada guarda que impide que una oportunidad llegue a un estado
incoherente. Son las validaciones que separan un funnel fiable de uno que
acumula datos que ninguna métrica puede interpretar después.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from db.repositories.organizations import OrganizationRepository
from db.repositories.pursuits import PursuitRepository
from services.organizations import OrganizationAccessError
from services.pursuits import (
    PursuitConflictError,
    PursuitNotFoundError,
    PursuitTransitionError,
    PursuitValidationError,
    create_pursuit,
    get_metrics,
    get_pursuit,
    update_pursuit,
)
from shared.dto import PursuitCreate, PursuitUpdate


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(email=email, password_hash="test-hash", display_name=email.split("@")[0])


def _licitacion(db_mod, id_externo: str = "LIC-RULES-1") -> None:
    with db_mod.connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, fecha_limite, fecha_extraccion) VALUES (?, ?, ?, ?)",
            (id_externo, "Servicio SAP", "2026-12-01T12:00:00+00:00", "2026-07-30T10:00:00+00:00"),
        )


def _org(db_mod, email: str = "rules-owner@example.test") -> tuple[int, int]:
    """Devuelve ``(owner_id, organization_id)`` con una licitación disponible."""
    owner = _user(email)
    organization = OrganizationRepository().create_organization("Equipo reglas", owner)
    _licitacion(db_mod)
    return owner, int(organization["id"])


def _open(owner: int, organization_id: int, licitacion_id: str = "LIC-RULES-1") -> int:
    pursuit, _ = create_pursuit(
        owner,
        PursuitCreate(licitacion_id=licitacion_id, organization_id=organization_id),
    )
    return pursuit.id


def _advance(owner: int, organization_id: int, pursuit_id: int, **fields: object) -> None:
    update_pursuit(
        owner,
        pursuit_id,
        PursuitUpdate(**fields),  # type: ignore[arg-type]  # kwargs tipados por el DTO
        organization_id=organization_id,
    )


def _reach_submitted(owner: int, organization_id: int, pursuit_id: int) -> None:
    """Lleva la oportunidad hasta ``submitted`` por el camino canónico."""
    _advance(owner, organization_id, pursuit_id, status="qualifying")
    _advance(
        owner,
        organization_id,
        pursuit_id,
        status="go_no_go",
        decision="go",
        decision_reason="Encaje estratégico",
    )
    _advance(owner, organization_id, pursuit_id, status="preparing")
    _advance(owner, organization_id, pursuit_id, status="submitted", offer_price_eur=900)


# ── Existencia y scope ───────────────────────────────────────────────────


def test_create_rejects_a_tender_that_does_not_exist(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)

    with pytest.raises(PursuitValidationError, match="licitación"):
        create_pursuit(
            owner,
            PursuitCreate(licitacion_id="NO-EXISTE", organization_id=organization_id),
        )


def test_get_and_update_report_not_found_for_an_unknown_pursuit(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)

    with pytest.raises(PursuitNotFoundError):
        get_pursuit(owner, 9999, organization_id=organization_id)
    with pytest.raises(PursuitNotFoundError):
        update_pursuit(
            owner,
            9999,
            PursuitUpdate(status="qualifying"),
            organization_id=organization_id,
        )


def test_responsible_must_be_an_active_member(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    outsider = _user("rules-outsider@example.test")
    pursuit_id = _open(owner, organization_id)

    with pytest.raises(OrganizationAccessError, match="miembro activo"):
        update_pursuit(
            owner,
            pursuit_id,
            PursuitUpdate(responsible_user_id=outsider),
            organization_id=organization_id,
        )


# ── Concurrencia optimista ───────────────────────────────────────────────


def test_a_stale_expected_version_is_a_conflict_not_a_silent_overwrite(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)

    _advance(owner, organization_id, pursuit_id, status="qualifying")

    # La versión 1 ya no existe: quien la trajera leyó antes de esa transición.
    with pytest.raises(PursuitConflictError, match="modificada"):
        update_pursuit(
            owner,
            pursuit_id,
            PursuitUpdate(
                status="go_no_go", decision="go", decision_reason="x", expected_version=1
            ),
            organization_id=organization_id,
        )


def test_an_unchanged_patch_is_a_no_op_without_a_new_event(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)

    before = get_pursuit(owner, pursuit_id, organization_id=organization_id)
    after = update_pursuit(
        owner,
        pursuit_id,
        PursuitUpdate(status="identified"),
        organization_id=organization_id,
    )

    assert after.version == before.version
    assert len(after.events) == len(before.events) == 1


# ── Decisión go/no-go ────────────────────────────────────────────────────


def test_a_decision_requires_a_reason(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)
    _advance(owner, organization_id, pursuit_id, status="qualifying")

    with pytest.raises(PursuitValidationError, match="motivo"):
        update_pursuit(
            owner,
            pursuit_id,
            PursuitUpdate(status="go_no_go", decision="go"),
            organization_id=organization_id,
        )


def test_reverting_a_decision_to_pending_clears_its_timestamp(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)
    _advance(owner, organization_id, pursuit_id, status="qualifying")
    _advance(
        owner,
        organization_id,
        pursuit_id,
        status="go_no_go",
        decision="go",
        decision_reason="Encaje estratégico",
    )

    decided = get_pursuit(owner, pursuit_id, organization_id=organization_id)
    assert decided.decision_at is not None

    reverted = update_pursuit(
        owner,
        pursuit_id,
        PursuitUpdate(decision="pending", decision_reason=None),
        organization_id=organization_id,
    )
    assert reverted.decision_at is None


def test_preparing_an_offer_requires_a_go_decision(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)
    _advance(owner, organization_id, pursuit_id, status="qualifying")
    _advance(
        owner,
        organization_id,
        pursuit_id,
        status="go_no_go",
        decision="pending",
    )

    with pytest.raises(PursuitValidationError, match="decisión go"):
        update_pursuit(
            owner,
            pursuit_id,
            PursuitUpdate(status="preparing"),
            organization_id=organization_id,
        )


def test_a_no_go_decision_must_close_the_pursuit(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)

    # Un no-go dejando la oportunidad en ``identified`` la abandonaría abierta.
    with pytest.raises(PursuitValidationError, match="no-go"):
        update_pursuit(
            owner,
            pursuit_id,
            PursuitUpdate(decision="no_go", decision_reason="Fuera de perímetro"),
            organization_id=organization_id,
        )


def test_a_no_go_that_withdraws_the_pursuit_is_accepted(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)

    withdrawn = update_pursuit(
        owner,
        pursuit_id,
        PursuitUpdate(status="withdrawn", decision="no_go", decision_reason="Fuera de perímetro"),
        organization_id=organization_id,
    )

    assert withdrawn.status == "withdrawn"
    assert withdrawn.outcome == "cancelled"
    assert withdrawn.closed_at is not None


# ── Coherencia estado ↔ resultado ────────────────────────────────────────


def test_an_outcome_alone_infers_its_terminal_status(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)
    _reach_submitted(owner, organization_id, pursuit_id)

    detail = update_pursuit(
        owner,
        pursuit_id,
        PursuitUpdate(outcome="lost", outcome_reason="Precio"),
        organization_id=organization_id,
    )

    assert detail.status == "lost"
    assert detail.closed_at is not None


def test_a_cancelled_outcome_infers_withdrawn(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)

    detail = update_pursuit(
        owner,
        pursuit_id,
        PursuitUpdate(outcome="cancelled", outcome_reason="Cliente cancela"),
        organization_id=organization_id,
    )

    assert detail.status == "withdrawn"


def test_a_terminal_status_rejects_a_contradictory_outcome(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)
    _reach_submitted(owner, organization_id, pursuit_id)

    with pytest.raises(PursuitValidationError, match="no coincide"):
        update_pursuit(
            owner,
            pursuit_id,
            PursuitUpdate(status="won", outcome="lost", awarded_amount_eur=100),
            organization_id=organization_id,
        )


def test_a_non_terminal_status_rejects_a_final_outcome(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)

    with pytest.raises(PursuitValidationError, match="estado terminal"):
        update_pursuit(
            owner,
            pursuit_id,
            PursuitUpdate(status="qualifying", outcome="won"),
            organization_id=organization_id,
        )


def test_winning_requires_an_amount_or_a_justification(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)
    _reach_submitted(owner, organization_id, pursuit_id)

    with pytest.raises(PursuitValidationError, match="importe adjudicado"):
        update_pursuit(
            owner,
            pursuit_id,
            PursuitUpdate(status="won"),
            organization_id=organization_id,
        )

    justified = update_pursuit(
        owner,
        pursuit_id,
        PursuitUpdate(status="won", outcome_reason="Adjudicación pendiente de importe"),
        organization_id=organization_id,
    )
    assert justified.outcome == "won"


def test_closing_requires_a_submitted_offer(tmp_db):
    """Guarda defensiva: ``won``/``lost`` sin oferta presentada es incoherente.

    El workflow no permite llegar aquí, porque pasar por ``submitted`` sella
    ``submitted_at``. Se fuerza el estado inconsistente en BD para comprobar
    que la regla sigue defendiendo el dato si algo lo corrompiera.
    """
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)
    _reach_submitted(owner, organization_id, pursuit_id)

    with db_mod.connect() as conn:
        conn.execute("UPDATE pursuits SET submitted_at = NULL WHERE id = ?", (pursuit_id,))

    with pytest.raises(PursuitValidationError, match="oferta presentada"):
        update_pursuit(
            owner,
            pursuit_id,
            PursuitUpdate(status="won", awarded_amount_eur=100),
            organization_id=organization_id,
        )


def test_the_transition_table_rejects_a_jump_over_the_workflow(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)

    with pytest.raises(PursuitTransitionError, match="identified -> preparing"):
        update_pursuit(
            owner,
            pursuit_id,
            PursuitUpdate(status="preparing"),
            organization_id=organization_id,
        )


def test_a_terminal_pursuit_accepts_no_further_transition(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)
    _advance(
        owner,
        organization_id,
        pursuit_id,
        status="withdrawn",
        decision="no_go",
        decision_reason="Fuera de perímetro",
    )

    with pytest.raises(PursuitTransitionError):
        update_pursuit(
            owner,
            pursuit_id,
            PursuitUpdate(status="qualifying"),
            organization_id=organization_id,
        )


# ── Métricas ─────────────────────────────────────────────────────────────


def test_metrics_reject_an_inverted_period(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)

    with pytest.raises(PursuitValidationError, match="period_to"):
        get_metrics(
            owner,
            organization_id=organization_id,
            period_from=datetime(2026, 7, 1, tzinfo=UTC),
            period_to=datetime(2026, 6, 1, tzinfo=UTC),
        )


def test_metrics_window_excludes_pursuits_outside_the_period(tmp_db):
    """Un periodo naive se interpreta como UTC, no se rechaza."""
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)

    with db_mod.connect() as conn:
        conn.execute(
            "UPDATE pursuits SET identified_at = ? WHERE id = ?",
            ("2020-01-01T00:00:00+00:00", pursuit_id),
        )

    inside = get_metrics(
        owner,
        organization_id=organization_id,
        period_from=datetime(2019, 1, 1),
        period_to=datetime(2021, 1, 1),
    )
    outside = get_metrics(
        owner,
        organization_id=organization_id,
        period_from=datetime(2026, 1, 1),
        period_to=datetime(2027, 1, 1),
    )

    assert inside.pursuits_identified == 1
    assert outside.pursuits_identified == 0
    assert outside.win_rate is None
    assert outside.awarded_amount_eur == 0


def test_median_decision_time_is_reported_in_hours(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)
    _advance(owner, organization_id, pursuit_id, status="qualifying")
    _advance(
        owner,
        organization_id,
        pursuit_id,
        status="go_no_go",
        decision="go",
        decision_reason="Encaje estratégico",
    )

    with db_mod.connect() as conn:
        conn.execute(
            "UPDATE pursuits SET identified_at = ?, decision_at = ? WHERE id = ?",
            ("2026-07-01T00:00:00+00:00", "2026-07-02T12:00:00+00:00", pursuit_id),
        )

    metrics = get_metrics(owner, organization_id=organization_id)
    assert metrics.median_decision_time_hours == 36.0


def test_unparseable_timestamps_do_not_break_the_metrics(tmp_db):
    """Una fila con fechas corruptas se omite del cálculo, no lo tumba."""
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)

    with db_mod.connect() as conn:
        conn.execute(
            "UPDATE pursuits SET identified_at = ?, decision_at = ? WHERE id = ?",
            ("no-es-una-fecha", "tampoco", pursuit_id),
        )

    metrics = get_metrics(owner, organization_id=organization_id)
    assert metrics.pursuits_identified == 1
    assert metrics.median_decision_time_hours is None


# ── Repositorio: filtros y ledger ────────────────────────────────────────


def test_list_filters_by_status_and_responsible(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    _licitacion(db_mod, "LIC-RULES-2")
    first = _open(owner, organization_id)
    second = _open(owner, organization_id, "LIC-RULES-2")
    _advance(owner, organization_id, second, status="qualifying")

    repo = PursuitRepository()
    qualifying, total_qualifying = repo.list_scoped(organization_id, status="qualifying")
    mine, _ = repo.list_scoped(organization_id, responsible_user_id=owner)
    nobody, total_nobody = repo.list_scoped(organization_id, responsible_user_id=owner + 999)

    assert [row["id"] for row in qualifying] == [second]
    assert total_qualifying == 1
    assert {row["id"] for row in mine} == {first, second}
    assert nobody == [] and total_nobody == 0


def test_update_refuses_a_column_outside_the_allowlist(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)

    with pytest.raises(ValueError, match="no permitidas"):
        PursuitRepository().update(
            organization_id=organization_id,
            pursuit_id=pursuit_id,
            actor_user_id=owner,
            changes={"organization_id": 42},
            expected_version=1,
            event_payload={},
        )


def test_gdpr_export_returns_each_table_under_its_own_key(tmp_db):
    """Regresión: la conexión expone un solo cursor y ``execute`` lo reemplaza.

    Con dos cursores abiertos antes de consumirlos, el export devolvía las filas
    de ``pursuit_events`` bajo la clave ``pursuits`` y una lista vacía de
    eventos — un derecho de acceso que entrega la tabla equivocada.
    """
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)
    repo = PursuitRepository()

    exported = repo.export_personal_data(owner)

    assert [row["id"] for row in exported["pursuits"]] == [pursuit_id]
    assert [row["licitacion_id"] for row in exported["pursuits"]] == ["LIC-RULES-1"]
    assert [row["event_type"] for row in exported["pursuit_events"]] == ["pursuit.created"]
    assert exported["pursuit_events"][0]["actor_user_id"] == owner


def test_gdpr_anonymisation_keeps_the_ledger_intact(tmp_db):
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)
    repo = PursuitRepository()

    repo.anonymize_user_references(owner)

    row = repo.get(organization_id, pursuit_id)
    assert row is not None
    assert row["responsible_user_id"] is None
    # El ledger es append-only: el actor histórico no se reescribe.
    assert repo.list_events(organization_id, pursuit_id)[0]["actor_user_id"] == owner


def test_a_corrupt_event_payload_degrades_to_an_empty_dict(tmp_db):
    """El ledger es append-only, así que la fila corrupta se inserta, no se edita."""
    db_mod, _ = tmp_db
    owner, organization_id = _org(db_mod)
    pursuit_id = _open(owner, organization_id)

    with db_mod.connect() as conn:
        conn.execute(
            "INSERT INTO pursuit_events "
            "(pursuit_id, organization_id, event_type, actor_user_id, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                pursuit_id,
                organization_id,
                "pursuit.updated",
                owner,
                "{no es json",
                "2026-07-30T11:00:00+00:00",
            ),
        )

    events = PursuitRepository().list_events(organization_id, pursuit_id)
    assert len(events) == 2
    assert events[0]["payload"]["status"] == "identified"
    assert events[1]["payload"] == {}
