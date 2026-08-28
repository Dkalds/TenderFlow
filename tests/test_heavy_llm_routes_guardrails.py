"""Las dos rutas LLM de /licitaciones tienen los mismos frenos que /ask.

Hasta esta corrección, ``POST /licitaciones/{id}/ficha-pliego/extract`` y
``POST /licitaciones/{id}/resumen`` eran ``/ask`` por otro nombre —una llamada
al proveedor por petición— pero sin ninguno de sus frenos:

- ``extract`` pedía ``licitaciones:read``, que es exactamente lo que concede
  ``data:read``, el scope por defecto de toda API key nueva
  (``config/settings.py``). Una credencial de solo lectura descargaba pliegos
  contra PLACSP, extraía PDF, gastaba 3.500 tokens de LLM y **sobrescribía** la
  ficha vigente.
- Ninguna de las dos estaba en la tabla de endpoints pesados del middleware, así
  que corrían al default de 120 req/min por IP mientras ``/ask`` estaba a 10.
  Con ese hueco el límite de ``/ask`` era decorativo: misma capacidad, ruta
  distinta.

Los tests de tope viven aquí y no en ``test_unit_security_review_middleware.py``
porque lo que fijan es la decisión de producto sobre estas dos rutas, no el
mecanismo genérico de ``_effective_max_calls`` (que aquel ya cubre).
"""

from __future__ import annotations

import pytest

from api.middleware import _effective_max_calls

_ASK_LIMIT = 10
_DEFAULT_LIMIT = 120


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/licitaciones/ABC-123/ficha-pliego/extract",
        "/api/v1/licitaciones/ABC-123/resumen",
        # El id externo puede llevar barras y espacios (p. ej. "PA-S 2026/000058"):
        # ``BaseHTTPMiddleware`` corre antes del routing y solo ve el path crudo,
        # así que el patrón tiene que seguir matcheando ahí.
        "/api/v1/licitaciones/PA-S 2026/000058/ficha-pliego/extract",
        "/api/v1/licitaciones/PA-S 2026/000058/resumen",
    ],
)
def test_rutas_llm_de_licitaciones_comparten_el_tope_de_ask(path: str) -> None:
    assert _effective_max_calls(path, _DEFAULT_LIMIT) == _ASK_LIMIT


@pytest.mark.parametrize(
    "path",
    [
        # La LECTURA de la ficha no llama al proveedor: no debe heredar el tope.
        "/api/v1/licitaciones/ABC-123/ficha-pliego",
        "/api/v1/licitaciones/ABC-123",
        "/api/v1/licitaciones",
    ],
)
def test_las_rutas_vecinas_baratas_no_heredan_el_tope(path: str) -> None:
    assert _effective_max_calls(path, _DEFAULT_LIMIT) == _DEFAULT_LIMIT


class TestExtractRechazaClavesDeSoloLectura:
    """El 403 de punta a punta, no solo la tabla de scopes.

    ``api/auth.py`` traduce ``required_scope_for_request`` a 403 antes de que la
    ruta corra, así que esto verifica que la credencial por defecto no llega a
    gastar ni una descarga.
    """

    def test_key_data_read_recibe_403(self, api_db, client) -> None:
        from api.auth import create_api_key

        raw = create_api_key("solo-lectura", scopes="data:read")
        resp = client.post(
            "/api/v1/licitaciones/ABC-123/ficha-pliego/extract",
            headers={"X-API-Key": raw},
        )
        assert resp.status_code == 403

    def test_key_licitaciones_write_pasa_el_control_de_scope(self, api_db, client) -> None:
        """Contraprueba: con el scope correcto ya no es el scope quien corta.

        No se afirma un 200 —la licitación no existe y no hay pliegos que
        extraer— sino que la respuesta ya no es 403: si lo fuera, el scope
        nuevo sería inalcanzable y el arreglo habría cerrado la ruta entera.
        """
        from api.auth import create_api_key

        raw = create_api_key("escritura", scopes="licitaciones:write")
        resp = client.post(
            "/api/v1/licitaciones/ABC-123/ficha-pliego/extract",
            headers={"X-API-Key": raw},
        )
        assert resp.status_code != 403

    def test_key_data_read_sigue_leyendo_la_ficha(self, api_db, client) -> None:
        """El arreglo no debe convertir el subárbol entero en escritura."""
        from api.auth import create_api_key

        raw = create_api_key("solo-lectura-get", scopes="data:read")
        resp = client.get(
            "/api/v1/licitaciones/ABC-123/ficha-pliego",
            headers={"X-API-Key": raw},
        )
        assert resp.status_code != 403
