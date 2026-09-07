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
_LOGIN = _WEB / "login"
_EQUIPO = _WEB / "(dashboard)" / "equipo"
_HOOK_INVITACIONES = _EQUIPO / "_hooks" / "use-invitations.ts"


def _codigo(raiz: Path) -> str:
    """Todo el TS/TSX de una pantalla, concatenado.

    Se mira el subárbol y no un ``page.tsx`` suelto porque las dos pantallas
    están partidas en ``_hooks/`` y ``_components/`` (S7.1 del plan): el botón
    de Microsoft vive hoy en un componente y el canje de la invitación en un
    hook. Lo que estos tests fijan es un acuerdo entre el backend y **la
    pantalla**, no entre el backend y un fichero concreto; atarlo a una ruta
    convertía cada troceado en un rojo que no significaba nada.
    """
    return "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(raiz.rglob("*.ts*"))
        if "__tests__" not in p.parts
    )


@pytest.fixture()
def login() -> str:
    return _codigo(_LOGIN)


@pytest.fixture()
def equipo() -> str:
    return _codigo(_EQUIPO)


class TestPantallaDeLogin:
    def test_ofrece_los_dos_proveedores(self, login: str) -> None:
        assert "Continuar con Google" in login
        assert "Continuar con Microsoft" in login

    def test_usa_la_ruta_parametrizada_por_proveedor(self, login: str) -> None:
        """Un solo camino: duplicarlo dejaría a uno de los dos atrás.

        Se fija la PROPIEDAD y no el nombre del manejador. Fijaba
        ``handleOAuthLogin("google"`` y el troceado de S7.1 lo convirtió en una
        prop (``onLogin``), así que el test se puso rojo sin que nada de lo que
        vigila hubiera cambiado. Lo que importa es que exista una única URL
        parametrizada y que ningún sitio del código construya la de un
        proveedor a mano — que es como uno de los dos se quedaría atrás.
        """
        assert "/api/v1/auth/oauth/${provider}/authorize" in login

        # Los comentarios sí pueden citar la ruta concreta (uno explica el 501
        # de Microsoft sin configurar), así que se miran solo las líneas de
        # código.
        codigo = "\n".join(
            linea
            for linea in login.splitlines()
            if not linea.lstrip().startswith(("//", "*", "/*"))
        )
        for proveedor in ("google", "microsoft"):
            assert f"/auth/oauth/{proveedor}/authorize" not in codigo, (
                f"la URL de {proveedor} se construye a mano en algún sitio: "
                "el día que el flujo cambie, ese camino se queda atrás"
            )
            assert f'"{proveedor}"' in codigo, (
                f"{proveedor} ya no se ofrece como proveedor en la pantalla"
            )

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
