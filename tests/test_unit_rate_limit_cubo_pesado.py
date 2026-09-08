"""El cubo de los endpoints pesados, separado del tráfico normal.

Lo destapó el E2E de exportación, que es el único sitio donde alguien pulsa
«Exportar CSV» **después** de haber cargado una pantalla. El log de la API del
job lo dijo sin ambigüedad: tres intentos, tres `429`, y ni una sola descarga
servida.

La causa era la combinación de dos decisiones que por separado están bien: el
cubo de cuota es **uno por cliente** (`api:{cliente}`) para que no se pueda
esquivar variando los path params, y el tope se elige **por ruta** (10 para
`/exports/download`). Juntas, el contador de *todo* el tráfico del cliente se
comparaba contra el tope del endpoint caro: cargar el dashboard son decenas de
llamadas, así que la exportación llegaba con el cubo ya muy por encima de 10 y
respondía 429 a un usuario que no había exportado nada.

En producción eso rompía el export para cualquiera que hubiese mirado la
pantalla antes de pedirlo, que son todos.
"""

from __future__ import annotations

import pytest


class TestReglaPesada:
    def test_una_ruta_normal_no_tiene_regla(self) -> None:
        from api.middleware import _regla_pesada

        assert _regla_pesada("/api/v1/licitaciones") is None

    def test_la_etiqueta_de_una_ruta_exacta_es_su_path(self) -> None:
        from api.middleware import _regla_pesada

        assert _regla_pesada("/api/v1/exports/download") == ("/api/v1/exports/download", 10)

    def test_gana_la_regla_mas_restrictiva(self) -> None:
        """Pasarse de estricto cuesta un 429 recuperable; quedarse corto deja el
        endpoint caro sin la protección que se le quiso poner."""
        from api.middleware import _regla_pesada

        regla = _regla_pesada("/api/v1/licitaciones/EXP-1/ficha-pliego/extract")
        assert regla is not None
        assert regla[1] == 10

    def test_dos_ids_del_mismo_patron_comparten_etiqueta(self) -> None:
        """Es lo que impide reabrir el bypass por path params: la etiqueta sale
        de la regla, no de la petición."""
        from api.middleware import _regla_pesada

        una = _regla_pesada("/api/v1/licitaciones/EXP-1/explain")
        otra = _regla_pesada("/api/v1/licitaciones/PA-S 2026/000058/explain")
        assert una is not None and otra is not None
        assert una[0] == otra[0]

    def test_el_limite_efectivo_sigue_siendo_el_de_antes(self) -> None:
        """`_effective_max_calls` no cambia de contrato: lo usan otros tres
        ficheros de test."""
        from api.middleware import _effective_max_calls

        assert _effective_max_calls("/api/v1/exports/download", 120) == 10
        assert _effective_max_calls("/api/v1/licitaciones", 120) == 120


class TestCuboSeparado:
    """El comportamiento que el E2E de exportación necesita."""

    def _claves(self, monkeypatch: pytest.MonkeyPatch, rutas: list[str]) -> list[str]:
        """Claves de cuota con las que el middleware consulta al limitador."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.middleware import RateLimitMiddleware

        vistas: list[str] = []

        class _Limiter:
            def check(self, key: str, *, max_calls: int = 120, window_seconds: float = 60.0):
                vistas.append(f"{key}|{max_calls}")
                return True

        monkeypatch.setattr("api.middleware.get_rate_limiter", lambda: _Limiter())

        app = FastAPI()
        app.add_middleware(RateLimitMiddleware)

        @app.get("/{camino:path}")
        def _cualquiera(camino: str) -> dict[str, str]:
            return {"ok": camino}

        cliente = TestClient(app)
        for ruta in rutas:
            cliente.get(ruta)
        return vistas

    def test_el_dashboard_no_gasta_el_presupuesto_de_exportacion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Era el fallo: dos llamadas normales y una exportación caían en el
        mismo contador, comparado contra el tope de la exportación."""
        vistas = self._claves(
            monkeypatch,
            ["/api/v1/licitaciones", "/api/v1/analytics/overview", "/api/v1/exports/download"],
        )

        normales = {v.split("|")[0] for v in vistas[:2]}
        exportacion = vistas[2].split("|")[0]
        assert len(normales) == 1, "el tráfico normal comparte cubo, como antes"
        assert exportacion not in normales

    def test_la_exportacion_conserva_su_tope_bajo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Separar el cubo no puede aflojar la protección del endpoint caro."""
        vistas = self._claves(monkeypatch, ["/api/v1/exports/download"])

        assert vistas[0].endswith("|10")

    def test_dos_endpoints_pesados_distintos_no_comparten_cubo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Agotar `/ask` no puede dejar sin exportaciones."""
        vistas = self._claves(monkeypatch, ["/api/v1/ask", "/api/v1/exports/download"])

        assert vistas[0].split("|")[0] != vistas[1].split("|")[0]

    def test_el_mismo_endpoint_pesado_si_comparte_cubo_entre_llamadas(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Si no, el tope no limitaría nada."""
        vistas = self._claves(monkeypatch, ["/api/v1/exports/download", "/api/v1/exports/download"])

        assert vistas[0] == vistas[1]

    def test_el_bypass_por_path_params_sigue_cerrado(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Dos expedientes distintos sobre `/explain` caen en el mismo cubo: la
        etiqueta sale del patrón, no de la petición."""
        vistas = self._claves(
            monkeypatch,
            ["/api/v1/licitaciones/EXP-1/explain", "/api/v1/licitaciones/EXP-2/explain"],
        )

        assert vistas[0] == vistas[1]

    def test_el_trafico_normal_conserva_su_clave_y_su_tope(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Lo que no es pesado no cambia de comportamiento."""
        vistas = self._claves(monkeypatch, ["/api/v1/licitaciones"])

        clave, tope = vistas[0].split("|")
        assert clave.startswith("api:")
        assert tope == "120"
