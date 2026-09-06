"""La deprecación de una ruta dice para cuándo, no solo que sí (C8.1)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import Response

from api.errors import DEPRECATION_WINDOW_DAYS, deprecate_route, sunset_anunciado


class TestSunsetAnunciado:
    def test_acepta_la_ventana_completa(self) -> None:
        hoy = datetime.now(UTC).date()
        objetivo = hoy + timedelta(days=DEPRECATION_WINDOW_DAYS)
        assert sunset_anunciado(objetivo) == objetivo

    def test_rechaza_una_ventana_corta(self) -> None:
        hoy = datetime.now(UTC).date()
        with pytest.raises(ValueError, match="ventana de deprecaci"):
            sunset_anunciado(hoy + timedelta(days=DEPRECATION_WINDOW_DAYS - 1))

    def test_rechaza_una_fecha_pasada(self) -> None:
        with pytest.raises(ValueError):
            sunset_anunciado(date(2020, 1, 1))

    def test_una_fecha_anunciada_hace_meses_sigue_valiendo(self) -> None:
        """Lo que la política exige es que hubiera 90 días desde el anuncio.

        Si se midiera contra hoy, una deprecación anunciada hace cuatro meses
        empezaría a fallar sola justo cuando su plazo está a punto de vencer —
        el apagón sin aviso que la política existe para evitar.
        """
        anuncio = date(2026, 1, 1)
        apagado = anuncio + timedelta(days=DEPRECATION_WINDOW_DAYS)
        assert sunset_anunciado(apagado, anunciado=anuncio) == apagado


class TestCabeceras:
    @staticmethod
    def _respuesta() -> Response:
        r = Response()
        deprecate_route(
            r,
            sunset=date(2027, 1, 15),
            successor="/api/v1/licitaciones/cursor",
            rfc="docs/rfc/999-retirada.md",
        )
        return r

    def test_deprecation(self) -> None:
        assert self._respuesta().headers["Deprecation"] == "true"

    def test_sunset_en_formato_http(self) -> None:
        """RFC 8594 exige fecha HTTP (IMF-fixdate), no ISO-8601."""
        valor = self._respuesta().headers["Sunset"]
        assert valor.startswith("Fri, 15 Jan 2027"), valor
        assert valor.endswith("GMT"), valor

    def test_link_lleva_sucesora_y_rfc(self) -> None:
        link = self._respuesta().headers["Link"]
        assert 'rel="successor-version"' in link
        assert 'rel="deprecation"' in link
        assert "/api/v1/licitaciones/cursor" in link

    def test_sin_sucesora_no_emite_link_vacio(self) -> None:
        r = Response()
        deprecate_route(r, sunset=date(2027, 1, 15))
        assert "Link" not in r.headers
        assert r.headers["Deprecation"] == "true"


def test_el_listado_por_offset_anuncia_su_apagado() -> None:
    """La única ruta deprecada hoy emitía `Deprecation` sin `Sunset`."""
    from api.routes.licitaciones import SUNSET_LISTADO_POR_OFFSET

    assert SUNSET_LISTADO_POR_OFFSET == date(2027, 1, 15)
