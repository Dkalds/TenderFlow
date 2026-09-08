"""Cuatro bordes que el plan describe con precisión y nadie ejecutaba.

Son piezas pequeñas de streams distintos que comparten un rasgo: **todas son la
rama degradada**, y la rama degradada es la que nunca se prueba a mano porque
para verla hay que romper algo. El plan las especifica una por una —el job de
reintentos es «advisory», la cobertura por fuente «tolerante a fallo», el
export de pipeline resuelve la organización en un solo sitio, la fecha
imposible se corta en el conector— y ninguna tenía test.
"""

from __future__ import annotations

from typing import Any

import pytest


class TestFechaPlausible:
    """C4.4 — el cero de la epoch de Excel entrando como fecha de contrato."""

    @pytest.mark.parametrize("iso", [None, "", "abc", "20", "no-es-fecha"])
    def test_lo_que_no_deja_leer_el_anio_no_es_plausible(self, iso: Any) -> None:
        """Si no se puede leer el año, no se puede **afirmar** que sea plausible."""
        from shared.dates import es_fecha_plausible

        assert es_fecha_plausible(iso) is False

    @pytest.mark.parametrize("iso", ["1899-12-30", "1970-01-01", "1989-12-31"])
    def test_las_fechas_imposibles_se_rechazan(self, iso: str) -> None:
        """`1899-12-30` es el cero de la epoch de Excel, no una adjudicación."""
        from shared.dates import es_fecha_plausible

        assert es_fecha_plausible(iso) is False

    @pytest.mark.parametrize("iso", ["1990-01-01", "2026-09-08", "2030-01-01"])
    def test_las_plausibles_pasan(self, iso: str) -> None:
        from shared.dates import es_fecha_plausible

        assert es_fecha_plausible(iso) is True


class TestReintentoDeWebhooks:
    """C2.4 — el job que convierte la cola de reintentos en una puerta."""

    def test_una_tabla_sin_migrar_no_tumba_la_pasada(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """El job es advisory: en un entorno sin `v119` devuelve ceros y sigue."""
        import db.repositories.webhooks as repo
        from scheduler.jobs import webhook_reintentos

        def _explota(**kwargs: Any) -> Any:
            raise RuntimeError('column "proximo_intento" does not exist')

        monkeypatch.setattr(repo, "pendientes_de_reintento", _explota)

        assert webhook_reintentos.run() == {"pendientes": 0, "entregadas": 0, "fallidas": 0}

    def test_cuenta_entregadas_y_fallidas_por_separado(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import db.repositories.webhooks as repo
        import db.webhooks as entregas
        from scheduler.jobs import webhook_reintentos

        monkeypatch.setattr(
            repo, "pendientes_de_reintento", lambda **kw: [{"id": 1}, {"id": 2}, {"id": 3}]
        )
        monkeypatch.setattr(entregas, "reenviar", lambda e: e["id"] != 2)

        assert webhook_reintentos.run() == {"pendientes": 3, "entregadas": 2, "fallidas": 1}

    def test_el_tope_por_pasada_viaja_al_repositorio(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Drenar de golpe una cola de un día es una tormenta contra un endpoint
        que probablemente sigue caído."""
        import db.repositories.webhooks as repo
        from scheduler.jobs import webhook_reintentos

        vistos: list[dict[str, Any]] = []

        def _pendientes(**kwargs: Any) -> list[dict[str, Any]]:
            vistos.append(kwargs)
            return []

        monkeypatch.setattr(repo, "pendientes_de_reintento", _pendientes)

        webhook_reintentos.run()
        assert vistos[0]["limit"] == webhook_reintentos.MAX_POR_PASADA


class TestCompletitudPorFuente:
    """C4.7 — promediar entre fuentes miente, y el fallo no vacía la pantalla."""

    def test_un_fallo_no_tumba_la_pantalla_de_calidad(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import db.repositories.adjudicaciones as repo
        from services.analytics import quality

        def _explota() -> Any:
            raise RuntimeError("BD caída")

        monkeypatch.setattr(repo, "completitud_por_fuente", _explota)

        assert quality._adjudicaciones_por_fuente() == []

    def test_los_porcentajes_son_por_fuente_y_no_una_media(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un «57 % global» es la media de un 57 % real y de dos ceros, y no
        describe a ninguna de las tres fuentes."""
        import db.repositories.adjudicaciones as repo
        from services.analytics import quality

        monkeypatch.setattr(
            repo,
            "completitud_por_fuente",
            lambda: [
                {
                    "fuente": "placsp",
                    "filas": 200,
                    "con_n_ofertas": 200,
                    "con_oferta_minima": 100,
                    "con_oferta_maxima": 50,
                    "con_es_pyme": 200,
                },
                {
                    "fuente": "ted",
                    "filas": 100,
                    "con_n_ofertas": 0,
                    "con_oferta_minima": 0,
                    "con_oferta_maxima": 0,
                    "con_es_pyme": 0,
                },
            ],
        )

        placsp, ted = quality._adjudicaciones_por_fuente()
        assert (placsp.fuente, placsp.pct_n_ofertas, placsp.pct_oferta_maxima) == (
            "placsp",
            100.0,
            25.0,
        )
        assert (ted.fuente, ted.pct_n_ofertas) == ("ted", 0.0)

    def test_una_fuente_sin_filas_no_divide_por_cero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import db.repositories.adjudicaciones as repo
        from services.analytics import quality

        monkeypatch.setattr(
            repo,
            "completitud_por_fuente",
            lambda: [{"fuente": "vacia", "filas": 0, "con_n_ofertas": 0}],
        )

        assert quality._adjudicaciones_por_fuente() == []

    def test_una_fuente_sin_nombre_se_etiqueta_y_no_se_pierde(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import db.repositories.adjudicaciones as repo
        from services.analytics import quality

        monkeypatch.setattr(
            repo,
            "completitud_por_fuente",
            lambda: [{"fuente": None, "filas": 10, "con_n_ofertas": 5}],
        )

        assert quality._adjudicaciones_por_fuente()[0].fuente == "(sin fuente)"


class TestExportDelPipeline:
    """C6.7 — sacar el tablero del producto, con la organización resuelta aquí."""

    def _repo_doble(self, monkeypatch: pytest.MonkeyPatch, filas: list[dict[str, Any]]) -> list:
        import db.repositories.pursuits as repo_mod
        import services.organizations as orgs

        pedidos: list[dict[str, Any]] = []

        class _Repo:
            def export_rows(self, organizacion: int, **kwargs: Any) -> list[dict[str, Any]]:
                pedidos.append({"organizacion": organizacion, **kwargs})
                return filas

        monkeypatch.setattr(repo_mod, "PursuitRepository", _Repo)
        monkeypatch.setattr(
            orgs, "resolve_organization", lambda u, o=None, *, write=False: (7, "member")
        )
        return pedidos

    def test_el_csv_sale_con_su_media_type_y_su_recuento(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.exports import render_pursuits_export

        self._repo_doble(monkeypatch, [{"id": 1, "titulo": "Uno"}, {"id": 2, "titulo": "Dos"}])

        contenido, media_type, n = render_pursuits_export(1, formato="csv")
        assert media_type == "text/csv; charset=utf-8"
        assert n == 2
        assert isinstance(contenido, bytes)

    def test_el_excel_declara_su_propio_media_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from services.exports import render_pursuits_export

        self._repo_doble(monkeypatch, [{"id": 1, "titulo": "Uno"}])

        _contenido, media_type, n = render_pursuits_export(1, formato="excel")
        assert media_type.endswith("spreadsheetml.sheet")
        assert n == 1

    def test_la_organizacion_la_resuelve_el_servicio_no_la_ruta(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tiene que existir **un** sitio donde se decide con qué organización
        se lee (`test_organization_sql_isolation.py`)."""
        from services.exports import render_pursuits_export

        pedidos = self._repo_doble(monkeypatch, [])

        render_pursuits_export(1, formato="csv", status="ganada", limit=50)
        assert pedidos[0]["organizacion"] == 7
        assert pedidos[0]["status"] == "ganada"
        assert pedidos[0]["limit"] == 50
