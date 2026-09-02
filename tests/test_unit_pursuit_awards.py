"""Cierre asistido: el texto del aviso y a quién va (sin base de datos)."""

from __future__ import annotations

from unittest.mock import patch

from services.pursuit_awards import _destinatarios, build_notification


def test_el_aviso_nombra_adjudicatario_e_importe() -> None:
    title, body = build_notification(
        {
            "licitacion_id": "LIC-1",
            "titulo": "Migración a S/4HANA del área económica",
            "adjudicatarios": "Consultora Uno, Consultora Dos",
            "importe_total": 1234567.0,
        }
    )
    assert title == "Adjudicación publicada: Migración a S/4HANA del área económica"
    assert "Consultora Uno, Consultora Dos" in body
    assert "1.234.567 EUR" in body
    assert "Cierra la oportunidad" in body


def test_el_aviso_no_inventa_adjudicatario_ni_importe() -> None:
    title, body = build_notification({"licitacion_id": "LIC-2", "titulo": None})
    assert title == "Adjudicación publicada: LIC-2"
    assert "adjudicatario no publicado" in body
    assert "EUR" not in body


def test_va_al_responsable_si_lo_hay() -> None:
    destinatarios = _destinatarios(
        {"organization_id": 7, "responsible_user_id": 3, "responsible_email": "ana@example.com"}
    )
    assert destinatarios == [(3, "ana@example.com")]


def test_sin_responsable_va_a_los_miembros_activos() -> None:
    miembros = [
        {"user_id": 1, "email": "a@example.com", "status": "active"},
        {"user_id": 2, "email": "b@example.com", "status": "invited"},
        {"user_id": 3, "email": None, "status": "active"},
    ]
    with patch(
        "services.pursuit_awards.OrganizationRepository.list_members", return_value=miembros
    ):
        destinatarios = _destinatarios(
            {"organization_id": 7, "responsible_user_id": None, "responsible_email": None}
        )
    assert destinatarios == [(1, "a@example.com")]
