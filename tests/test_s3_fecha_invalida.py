"""O0.3 — una fecha no ISO no puede abortar el reentrenamiento mensual.

El 2026-09-01, la primera ejecución programada de ``train-predictivos.yml``
murió dentro de ``_folds_rolling`` con::

    ValueError: time data '19-12-10' does not match format '%Y-%m-%d'

Una sola fila con la fecha en un formato que la fuente no debería publicar
dejó al proyecto sin reentrenamiento mensual. Estos tests fijan el reparto de
responsabilidades del arreglo:

- ``_fecha_dt`` sigue siendo **estricto** (una fecha inventada mueve un corte
  temporal), pero normaliza antes con el normalizador canónico
  ``shared.dates.to_iso_date``, así que los formatos españoles que la fuente sí
  publica dejan de ser basura;
- lo que no parsea se **descarta con log**, no aborta, y el descarte se cuenta.
"""

from __future__ import annotations

import pytest

from services.ml.baja_model import (
    _folds_rolling,
    filtrar_fechas_invalidas,
    sanear_fechas_label,
)
from services.ml.features import FilaDataset, _fecha_dt, fecha_valida

# La fila real que tumbó el job: dos dígitos de año, formato no ISO.
FECHA_ROTA = "19-12-10"


def _fila(licitacion_id: str, fecha: str) -> FilaDataset:
    return FilaDataset(
        licitacion_id=licitacion_id,
        fecha=fecha,
        features={"cpv4": "7200", "log_importe": 11.0},
        baja=0.15,
    )


def _filas_validas(n: int, *, desde_mes: int = 1) -> list[FilaDataset]:
    """``n`` filas con fechas ISO repartidas por meses consecutivos."""
    return [_fila(f"lic-{i}", f"2025-{((desde_mes + i) % 12) + 1:02d}-15") for i in range(n)]


class TestFechaDt:
    def test_iso_parsea(self) -> None:
        assert _fecha_dt("2025-03-04").year == 2025

    def test_formato_espanol_ya_no_revienta(self) -> None:
        """``to_iso_date`` convierte DD/MM/YYYY y DD-MM-YYYY antes del strptime."""
        assert _fecha_dt("04/03/2025").isoformat().startswith("2025-03-04")
        assert _fecha_dt("04-03-2025").isoformat().startswith("2025-03-04")

    def test_basura_sigue_lanzando(self) -> None:
        """El contrato estricto se conserva: no se inventa una fecha."""
        with pytest.raises(ValueError, match=FECHA_ROTA):
            _fecha_dt(FECHA_ROTA)

    def test_fecha_valida_es_el_predicado_del_descarte(self) -> None:
        assert fecha_valida("2025-03-04")
        assert fecha_valida("04/03/2025")
        assert not fecha_valida(FECHA_ROTA)
        assert not fecha_valida(None)
        assert not fecha_valida("")


class TestFiltrarFechasInvalidas:
    def test_descarta_la_fila_rota_y_la_cuenta(self) -> None:
        filas = [*_filas_validas(3), _fila("lic-rota", FECHA_ROTA)]

        validas, descartadas = filtrar_fechas_invalidas(filas)

        assert descartadas == 1
        assert [f.licitacion_id for f in validas] == ["lic-0", "lic-1", "lic-2"]

    def test_sin_filas_rotas_no_descarta_nada(self) -> None:
        filas = _filas_validas(5)
        validas, descartadas = filtrar_fechas_invalidas(filas)
        assert descartadas == 0
        assert validas == filas


class TestFolds:
    def test_hoy_revienta_si_la_fila_rota_llega_a_los_cortes(self) -> None:
        """Sin filtrar, el corte temporal sigue muriendo: por eso hay que filtrar.

        No es un bug que se arregle dentro de ``_folds_rolling``: ahí la fecha
        ya tiene que ser una fecha. Este test documenta que el descarte es un
        paso **previo** obligatorio y no un adorno.
        """
        filas = [*_filas_validas(60), _fila("lic-rota", FECHA_ROTA)]

        with pytest.raises(ValueError, match=FECHA_ROTA):
            _folds_rolling(filas, valid_meses=6, n_folds=3, fechas_label={})

    def test_tras_el_filtro_los_folds_salen(self) -> None:
        filas = [*_filas_validas(60), _fila("lic-rota", FECHA_ROTA)]

        validas, descartadas = filtrar_fechas_invalidas(filas)
        folds = _folds_rolling(validas, valid_meses=6, n_folds=3, fechas_label={})

        assert descartadas == 1
        assert folds  # al menos el split único de respaldo
        ids = {f.licitacion_id for train, valid in folds for f in (*train, *valid)}
        assert "lic-rota" not in ids


class TestSanearFechasLabel:
    def test_quita_la_entrada_rota_sin_perder_la_fila(self) -> None:
        """La fila sobrevive: sin entrada en el mapa se cae a su propio ancla."""
        crudo = {"lic-0": "2025-04-01", "lic-1": FECHA_ROTA, "lic-2": "01/04/2025"}

        limpio, invalidas = sanear_fechas_label(crudo)

        assert invalidas == 1
        assert set(limpio) == {"lic-0", "lic-2"}

    def test_mapa_limpio_no_toca_nada(self) -> None:
        crudo = {"lic-0": "2025-04-01"}
        limpio, invalidas = sanear_fechas_label(crudo)
        assert invalidas == 0
        assert limpio == crudo
