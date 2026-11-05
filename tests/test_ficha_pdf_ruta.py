"""F2.7 — ``GET /api/v1/pursuits/{pursuit_id}/ficha.pdf``: el PDF y quién lo baja.

``tests/test_ficha_pdf.py`` prueba la maqueta llamando a ``construir_pdf``;
ninguno pasaba por la ruta. Aquí se fija lo que la ruta añade: que entrega un
PDF de verdad al owner y que una organización ajena recibe el mismo 403 que en
``GET /pursuits/{id}``, porque las dos leen por ``get_pursuit``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.routes.dual_auth import require_any_auth
from db.repositories.organizations import OrganizationRepository
from shared.dto import PursuitCreate

_LICITACION = "LIC-FICHA-PDF-RUTA"


class _Sesion:
    """Sustituye ``require_any_auth``: cada test decide quién pide."""

    user_id: int | None = None

    def __call__(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "auth_method": "session",
            "user_key": f"ficha-pdf-{self.user_id}",
        }


@pytest.fixture()
def sesion(api_db: Any) -> Iterator[_Sesion]:
    from api.app import app

    principal = _Sesion()
    app.dependency_overrides[require_any_auth] = principal
    try:
        yield principal
    finally:
        app.dependency_overrides.pop(require_any_auth, None)


@dataclass(frozen=True)
class _Escenario:
    owner: int
    organizacion: int
    oportunidad: int
    extrano: int


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(email=email, password_hash="test-hash")  # pragma: allowlist secret


@pytest.fixture()
def escenario(sesion: _Sesion) -> _Escenario:
    """Una oportunidad en una organización, y otro cliente con la suya."""
    from db.database import connect
    from services.pursuits import create_pursuit

    owner = _user("owner-ficha-pdf@example.test")
    extrano = _user("extrano-ficha-pdf@example.test")
    repo = OrganizationRepository()
    organizacion = int(repo.create_organization("Equipo ficha", owner)["id"])
    repo.create_organization("Otro cliente", extrano)

    with connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, fecha_limite, fecha_extraccion) VALUES (%s, %s, %s, %s)",
            (
                _LICITACION,
                "Mantenimiento de la plataforma",
                "2026-12-01T12:00:00+00:00",
                "2026-07-30T10:00:00+00:00",
            ),
        )
    creado, _ = create_pursuit(
        owner, PursuitCreate(licitacion_id=_LICITACION, organization_id=organizacion)
    )
    return _Escenario(owner, organizacion, int(creado.id), extrano)


def _ficha(client: TestClient, escenario: _Escenario) -> Any:
    return client.get(
        f"/api/v1/pursuits/{escenario.oportunidad}/ficha.pdf",
        params={"organization_id": escenario.organizacion},
    )


def test_el_owner_baja_la_ficha_en_pdf(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    sesion.user_id = escenario.owner

    respuesta = _ficha(client, escenario)

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.headers["content-type"] == "application/pdf"
    assert respuesta.headers["content-disposition"] == (
        f'inline; filename="oportunidad-{escenario.oportunidad}.pdf"'
    )
    assert respuesta.content.startswith(b"%PDF")


def test_una_organizacion_ajena_recibe_403_como_en_el_detalle(
    client: TestClient, sesion: _Sesion, escenario: _Escenario
) -> None:
    sesion.user_id = escenario.extrano

    ficha = _ficha(client, escenario)
    detalle = client.get(
        f"/api/v1/pursuits/{escenario.oportunidad}",
        params={"organization_id": escenario.organizacion},
    )

    assert (ficha.status_code, detalle.status_code) == (403, 403), ficha.text
