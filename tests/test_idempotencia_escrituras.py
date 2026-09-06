"""Idempotencia en las escrituras de usuario que no la tenían (C8.4).

`POST /pursuits` ya era idempotente por `X-Idempotency-Key`. Las otras cuatro
escrituras que un usuario dispara desde la interfaz —favoritos, reglas,
empresas vigiladas y descartes del Radar— no lo eran: un doble clic, un
reintento del navegador tras un timeout o un retry del cliente producían dos
efectos.

Estos tests cubren dos cosas distintas, y la primera es la que más importa:

1. **Que el ámbito de la clave no permita leer la respuesta de otra cuenta.**
   La clave la elige el cliente, así que dos usuarios pueden mandar la misma.
2. Que el TTL se aplique de verdad (`IDEMPOTENCY_TTL_SECONDS` no lo leía nadie).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from config.settings import settings
from db.idempotency import _caducada, scope


class TestAmbito:
    def test_incluye_al_usuario(self) -> None:
        """Dos usuarios con la misma clave no comparten respuesta."""
        a = scope("watchlist_items", user_key="usuario-a")
        b = scope("watchlist_items", user_key="usuario-b")
        assert a != b

    def test_incluye_a_la_organizacion(self) -> None:
        """El mismo humano en dos organizaciones escribe en dos sitios."""
        personal = scope("watchlist_items", user_key="u1", organization_id=1)
        equipo = scope("watchlist_items", user_key="u1", organization_id=2)
        assert personal != equipo

    def test_sin_organizacion_es_estable(self) -> None:
        assert scope("radar_dismissals", user_key="u1") == scope(
            "radar_dismissals", user_key="u1"
        )

    def test_endpoints_distintos_no_colisionan(self) -> None:
        """Reintentar un favorito no puede devolver la respuesta de una regla."""
        assert scope("watchlist_items", user_key="u1") != scope(
            "watchlist_rules", user_key="u1"
        )

    def test_el_usuario_nunca_falta(self) -> None:
        """El ámbito no puede ser solo el nombre del endpoint.

        Este es el test que impide la regresión: sin la identidad dentro, el
        mecanismo de idempotencia se convierte en una caché compartida entre
        cuentas.
        """
        ambito = scope("watchlist_items", user_key="clave-de-usuario")
        assert "clave-de-usuario" in ambito
        assert ambito != "watchlist_items"


class TestCaducidad:
    def test_marca_reciente_vale(self) -> None:
        reciente = datetime.now(UTC).isoformat()
        assert _caducada(reciente) is False

    def test_marca_pasada_del_ttl_no_vale(self) -> None:
        vieja = (
            datetime.now(UTC) - timedelta(seconds=settings.IDEMPOTENCY_TTL_SECONDS + 60)
        ).isoformat()
        assert _caducada(vieja) is True

    def test_sin_marca_se_reprocesa(self) -> None:
        """Una fila sin fecha se trata como caducada.

        Servir una respuesta cuya antigüedad no se puede determinar es peor que
        repetir un efecto que, en las cuatro rutas de C8.4, es idempotente por
        naturaleza.
        """
        assert _caducada(None) is True
        assert _caducada("") is True

    def test_marca_ilegible_se_reprocesa(self) -> None:
        assert _caducada("no es una fecha") is True

    def test_marca_naive_se_interpreta_utc(self) -> None:
        """Las fechas de la tabla se escriben con `now_utc_iso()`."""
        naive = datetime.now(UTC).replace(tzinfo=None).isoformat()
        assert _caducada(naive) is False


class TestContrato:
    """Las cuatro rutas declaran la cabecera en el OpenAPI."""

    RUTAS = [
        ("/api/v1/watchlist/items", "post"),
        ("/api/v1/watchlist/rules", "post"),
        ("/api/v1/competitive/watchlist", "post"),
        ("/api/v1/radar/dismissals", "post"),
    ]

    @pytest.fixture(scope="class")
    @staticmethod
    def openapi() -> dict:
        from api.app import app

        return dict(app.openapi())

    @pytest.mark.parametrize("ruta,metodo", RUTAS)
    def test_declara_la_cabecera(self, openapi: dict, ruta: str, metodo: str) -> None:
        operacion = openapi["paths"][ruta][metodo]
        cabeceras = {
            p.get("name")
            for p in operacion.get("parameters", [])
            if p.get("in") == "header"
        }
        assert "X-Idempotency-Key" in cabeceras, (
            f"{metodo.upper()} {ruta} no declara X-Idempotency-Key en el contrato"
        )

    @pytest.mark.parametrize("ruta,metodo", RUTAS)
    def test_la_cabecera_es_opcional(self, openapi: dict, ruta: str, metodo: str) -> None:
        """Añadir la cabecera no puede romper a quien ya llama sin ella."""
        operacion = openapi["paths"][ruta][metodo]
        cabecera = next(
            p for p in operacion.get("parameters", []) if p.get("name") == "X-Idempotency-Key"
        )
        assert not cabecera.get("required", False)
