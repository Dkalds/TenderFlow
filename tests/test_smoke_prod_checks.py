"""El smoke sintético tiene que tocar la superficie pública, y no perdonarle un 401.

Motivación
----------
El 2026-08-28 la superficie ``/api/v1/publico/*`` entera devolvió 500 durante
horas y ``scripts/smoke_prod.py`` salió VERDE (run de las 09:44 UTC): sus cinco
checks apuntaban a ``/health/ready``, tres endpoints de analítica y
``/licitaciones``, ninguno público. El único tráfico que un visitante anónimo
—o Googlebot— llega a ver no estaba cubierto.

Hay un segundo filo, más sutil, y es el que fija ``test_publico_401_es_fallo``:
``main`` trata 401/403 como "el smoke corre sin credenciales, check omitido".
Esa indulgencia es correcta para los endpoints privados y venenosa para los
públicos, donde un 403 es exactamente el fallo que el prefijo ``/publico``
existe para evitar (que el catch-all autenticado de
``/api/v1/licitaciones/{id:path}`` ensombrezca una ruta pública). Sin la
excepción, los checks nuevos habrían pasado de verdes a "omitidos" — igual de
silenciosos.
"""

from __future__ import annotations

import urllib.error
from typing import Any

from scripts import smoke_prod

# Payload válido por endpoint. La igualdad con CHECKS de más abajo es
# deliberada: un check nuevo obliga a declarar aquí qué respuesta considera
# sana, en vez de colarse sin que nadie describa su forma.
_PAYLOADS: dict[str, Any] = {
    "/api/v1/health/ready": {"status": "ok"},
    "/api/v1/analytics/overview": {"total_licitaciones": 10},
    "/api/v1/analytics/resumen/hoy": {"total_activas": 3},
    "/api/v1/licitaciones?limit=1": {"items": [{"id": 1}]},
    "/api/v1/analytics/trends?group_by=month": {"series": [{"periodo": "2026-08"}]},
    "/api/v1/publico/sitemap/resumen": {"total": 1200, "actualizado": "2026-08-28"},
    "/api/v1/publico/hubs": {"ccaa": [{"slug": "madrid"}], "cpv": [{"codigo": "72"}]},
    "/api/v1/publico/licitaciones?limit=1": {"items": [{"ref": "abc"}]},
}


def _instalar_fetch(monkeypatch, respuestas: dict[str, Any]) -> None:
    """Sustituye ``_fetch`` por un doble que sirve `respuestas` (o lanza si es una excepción)."""

    def _fake(base: str, path: str) -> tuple[int, Any]:
        payload = respuestas[path]
        if isinstance(payload, Exception):
            raise payload
        return 200, payload

    monkeypatch.setenv("SMOKE_BASE_URL", "https://api.example.test")
    monkeypatch.setattr(smoke_prod, "_fetch", _fake)


def test_los_endpoints_publicos_estan_en_checks() -> None:
    rutas = {path for _, path, _ in smoke_prod.CHECKS}
    assert "/api/v1/publico/sitemap/resumen" in rutas
    assert "/api/v1/publico/hubs" in rutas
    assert "/api/v1/publico/licitaciones?limit=1" in rutas


def test_cada_check_tiene_payload_de_referencia() -> None:
    assert {path for _, path, _ in smoke_prod.CHECKS} == set(_PAYLOADS)


def test_non_empty_lists_exige_todas_las_listas() -> None:
    validar = smoke_prod._non_empty_lists("ccaa", "cpv")
    assert validar({"ccaa": [1], "cpv": [2]}) is None
    # El hub de CPV vacío deja media superficie pública sin índice: no puede
    # pasar sólo porque la otra lista traiga algo.
    assert validar({"ccaa": [1], "cpv": []}) is not None
    assert validar({"ccaa": [], "cpv": [2]}) is not None


def test_todo_verde_sale_0(monkeypatch) -> None:
    _instalar_fetch(monkeypatch, _PAYLOADS)
    assert smoke_prod.main() == 0


def test_sitemap_a_cero_es_fallo(monkeypatch) -> None:
    """Un corpus público de 0 expedientes es la landing rota, no un dato."""
    respuestas = dict(_PAYLOADS)
    respuestas["/api/v1/publico/sitemap/resumen"] = {"total": 0, "actualizado": None}
    _instalar_fetch(monkeypatch, respuestas)
    assert smoke_prod.main() == 1


def test_publico_en_500_es_fallo(monkeypatch) -> None:
    """El incidente exacto: la superficie pública en 5xx y el resto en pie."""
    respuestas = dict(_PAYLOADS)
    respuestas["/api/v1/publico/licitaciones?limit=1"] = urllib.error.HTTPError(
        "https://api.example.test/api/v1/publico/licitaciones?limit=1", 500, "err", None, None
    )
    _instalar_fetch(monkeypatch, respuestas)
    assert smoke_prod.main() == 1


def test_publico_401_es_fallo_y_privado_401_se_omite(monkeypatch, capsys) -> None:
    respuestas = dict(_PAYLOADS)
    respuestas["/api/v1/publico/hubs"] = urllib.error.HTTPError(
        "https://api.example.test/api/v1/publico/hubs", 403, "forbidden", None, None
    )
    _instalar_fetch(monkeypatch, respuestas)
    assert smoke_prod.main() == 1, "un 403 en la superficie anónima no se puede omitir"
    assert "publico_hubs" in capsys.readouterr().err

    # El mismo 403 en un endpoint que sí exige credenciales sigue siendo un
    # check omitido: correr el smoke sin secretos no debe teñirlo de rojo.
    respuestas = dict(_PAYLOADS)
    respuestas["/api/v1/analytics/overview"] = urllib.error.HTTPError(
        "https://api.example.test/api/v1/analytics/overview", 403, "forbidden", None, None
    )
    _instalar_fetch(monkeypatch, respuestas)
    assert smoke_prod.main() == 0
