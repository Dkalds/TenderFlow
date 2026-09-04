"""S3.5 — el entrenamiento no puede depender de que ninguna feature llegue vacía.

``HistGradientBoostingRegressor`` no sabe binear una columna numérica que llega
**entera** a NaN: intenta calcular cortes sobre cero valores distintos y muere
con ``ValueError: window shape cannot be larger than input array shape``, un
mensaje que no menciona ni la columna ni el dato. Basta con que un agregado
histórico (``hhi_segmento``, ``plazo_dias``, ``n_ofertas_media_*``…) no tenga
una sola observación en el corte que se ajusta.

El invariante que fijan estos tests: las columnas sin ningún valor observado se
descartan **antes** del ajuste, se registran en la metadata del modelo y
``predict`` recorta la matriz igual que lo hizo el ajuste.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from services.ml.baja_model import (
    BajaModel,
    _aplicar_mascara,
    _codificar,
    _columnas_observadas,
    _fit_quantil,
    _y_de,
)
from services.ml.features import CATEGORICAL_COLUMNS, FEATURE_COLUMNS, FilaDataset

# Dos numéricas que el dataset real deja vacías con facilidad.
COLUMNAS_VACIAS = ("hhi_segmento", "plazo_dias")


def _fila(i: int) -> FilaDataset:
    """Fila con todas las features salvo :data:`COLUMNAS_VACIAS`, que van a None."""
    features: dict[str, Any] = {}
    for col in FEATURE_COLUMNS:
        if col in COLUMNAS_VACIAS:
            features[col] = None
        elif col in CATEGORICAL_COLUMNS:
            features[col] = f"c{i % 3}"
        else:
            features[col] = float(i % 7) + 0.5
    return FilaDataset(
        licitacion_id=f"lic-{i}",
        fecha=f"2025-{(i % 12) + 1:02d}-10",
        features=features,
        baja=0.05 + (i % 5) / 100.0,
    )


@pytest.fixture
def filas() -> list[FilaDataset]:
    return [_fila(i) for i in range(80)]


class TestColumnasObservadas:
    def test_marca_como_descartadas_las_columnas_sin_ningun_valor(
        self, filas: list[FilaDataset]
    ) -> None:
        X, _ = _codificar(filas)

        mask, descartadas = _columnas_observadas(X)

        assert sorted(descartadas) == sorted(COLUMNAS_VACIAS)
        assert len(mask) == len(FEATURE_COLUMNS)
        for col, keep in zip(FEATURE_COLUMNS, mask, strict=True):
            assert keep is (col not in COLUMNAS_VACIAS)

    def test_una_sola_observacion_basta_para_conservarla(self, filas: list[FilaDataset]) -> None:
        """El criterio es "ningún valor", no "pocos valores": no se poda por rareza."""
        filas[0].features["hhi_segmento"] = 1234.0
        X, _ = _codificar(filas)

        _mask, descartadas = _columnas_observadas(X)

        assert descartadas == ["plazo_dias"]

    def test_matriz_vacia_no_descarta_nada(self) -> None:
        X, _ = _codificar([])
        mask, descartadas = _columnas_observadas(X)
        assert descartadas == []
        assert all(mask)

    def test_aplicar_mascara_recorta_las_columnas(self, filas: list[FilaDataset]) -> None:
        X, _ = _codificar(filas)
        mask, _descartadas = _columnas_observadas(X)

        recortada = _aplicar_mascara(X, mask)

        assert recortada.shape == (len(filas), len(FEATURE_COLUMNS) - len(COLUMNAS_VACIAS))
        assert not np.isnan(recortada).all(axis=0).any()


class TestAjuste:
    """El invariante: al ajuste nunca le llega una columna sin un solo valor.

    Deliberadamente NO se afirma "sklearn lanza ValueError sin la máscara": que
    lance o no depende de la versión instalada (con 1.8 el binning tolera la
    columna vacía; la versión del runner que tumbó el entrenamiento no lo
    hacía, y el mensaje era ``window shape cannot be larger than input array
    shape``). Atar el test a ese detalle lo convertiría en un test de sklearn.
    Lo que este proyecto controla —y lo único que hace falta controlar— es no
    entregarle esa columna.
    """

    def test_la_matriz_ajustada_no_lleva_columnas_vacias(self, filas: list[FilaDataset]) -> None:
        X_completa, _ = _codificar(filas)
        assert np.isnan(X_completa).all(axis=0).any(), "el fixture debe tener columnas vacías"

        mask, _descartadas = _columnas_observadas(X_completa)
        X = _aplicar_mascara(X_completa, mask)

        assert not np.isnan(X).all(axis=0).any()

    def test_con_mascara_el_ajuste_sale(self, filas: list[FilaDataset]) -> None:
        X_completa, _ = _codificar(filas)
        cat_mask = [col in CATEGORICAL_COLUMNS for col in FEATURE_COLUMNS]
        mask, _descartadas = _columnas_observadas(X_completa)
        X = _aplicar_mascara(X_completa, mask)
        cat_usadas = [c for c, keep in zip(cat_mask, mask, strict=True) if keep]

        est = _fit_quantil(0.5, X, _y_de(filas), np.ones(len(filas)), cat_usadas, {"max_iter": 5})

        assert est.predict(X).shape == (len(filas),)


class _ModeloEspia:
    """Registra la forma de la matriz que recibe, para comprobar el recorte."""

    def __init__(self) -> None:
        self.n_columnas: int | None = None

    def predict(self, X: Any) -> Any:
        self.n_columnas = int(X.shape[1])
        return np.full(X.shape[0], 0.1)


class TestPredictRecorta:
    def _modelo(self, metadata: dict[str, Any]) -> tuple[BajaModel, _ModeloEspia]:
        espia = _ModeloEspia()
        categorias = {col: {"c0": 0, "c1": 1, "c2": 2} for col in CATEGORICAL_COLUMNS}
        modelo = BajaModel(
            modelos=dict.fromkeys((0.10, 0.50, 0.90), espia),
            categorias=categorias,
            metadata={"feature_columns": list(FEATURE_COLUMNS), **metadata},
        )
        return modelo, espia

    def test_predict_usa_solo_las_columnas_del_ajuste(self, filas: list[FilaDataset]) -> None:
        usadas = [c for c in FEATURE_COLUMNS if c not in COLUMNAS_VACIAS]
        modelo, espia = self._modelo({"feature_columns_usadas": usadas})

        preds = modelo.predict(filas[:5])

        assert espia.n_columnas == len(usadas)
        assert len(preds) == 5

    def test_artefacto_antiguo_sin_la_clave_usa_todas(self, filas: list[FilaDataset]) -> None:
        """Retrocompatibilidad: un .pkl anterior se sirve como antes."""
        modelo, espia = self._modelo({})

        modelo.predict(filas[:5])

        assert espia.n_columnas == len(FEATURE_COLUMNS)
