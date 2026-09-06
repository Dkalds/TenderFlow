"""La superficie que S1 promete existe en el frontend.

Mismo patrón que ``tests/test_search_semantic_source.py``: se lee el fuente de
la página. No sustituye a un test de componente, pero sí impide la regresión
que más veces ha aparecido en este repo — un backend que gana una capacidad y
una pantalla que se queda contando la historia anterior.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parents[1] / "web" / "src" / "app"
_LOGIN = _WEB / "login" / "page.tsx"
_EQUIPO = _WEB / "(dashboard)" / "equipo" / "page.tsx"
_HOOK_INVITACIONES = _WEB / "(dashboard)" / "equipo" / "_hooks" / "use-invitations.ts"


@pytest.fixture()
def login() -> str:
    return _LOGIN.read_text(encoding="utf-8")


@pytest.fixture()
def equipo() -> str:
    return _EQUIPO.read_text(encoding="utf-8")


class TestPantallaDeLogin:
    def test_ofrece_los_dos_proveedores(self, login: str) -> None:
        assert "Continuar con Google" in login
        assert "Continuar con Microsoft" in login

    def test_usa_la_ruta_parametrizada_por_proveedor(self, login: str) -> None:
        """Un solo camino: duplicarlo dejaría a uno de los dos atrás."""
        assert "/api/v1/auth/oauth/${provider}/authorize" in login
        assert 'handleOAuthLogin("google"' in login
        assert 'handleOAuthLogin("microsoft"' in login

    def test_el_boton_de_microsoft_depende_de_que_este_configurado(self, login: str) -> None:
        """Sin `OAUTH_MICROSOFT_CLIENT_ID` el backend responde 501."""
        assert "NEXT_PUBLIC_OAUTH_MICROSOFT" in login
        assert "{MICROSOFT_HABILITADO && (" in login

    def test_reconoce_el_enlace_de_invitacion(self, login: str) -> None:
        assert 'searchParams.get("invitacion")' in login
        assert "/api/v1/organizations/invitations/accept" in login


class TestPantallaDeEquipo:
    def test_lista_las_invitaciones_pendientes_con_sus_acciones(self, equipo: str) -> None:
        assert "Invitaciones pendientes" in equipo
        assert "Reenviar" in equipo
        assert "Revocar" in equipo

    def test_el_texto_ya_no_dice_que_haga_falta_cuenta_previa(self, equipo: str) -> None:
        """Era la frase que describía la limitación que S1.1 elimina."""
        assert "ya tienen una cuenta activa en TenderFlow" not in equipo
        assert "recibe una invitación por" in equipo

    def test_el_hook_usa_los_tres_endpoints_del_backend(self) -> None:
        fuente = _HOOK_INVITACIONES.read_text(encoding="utf-8")

        assert "/invitations`" in fuente
        assert "/resend`" in fuente
        assert '"DELETE"' in fuente

    def test_los_tipos_salen_del_cliente_generado(self) -> None:
        """Invariante 3 de web/AGENTS.md: la forma no se escribe a mano."""
        fuente = _HOOK_INVITACIONES.read_text(encoding="utf-8")

        assert 'Schemas["OrganizationInvitationOut"]' in fuente
