"""Normalización L2 del fallback TF-IDF de clustering (``_tfidf_embeddings``).

La función está dos veces con el mismo contrato, en
``services.clustering_engine`` y en ``services.analytics.clusters``. Las dos
pasan la matriz densa por ``sklearn.preprocessing.normalize`` antes de
devolverla: cada fila sale como la del ``TfidfVectorizer`` dividida por su
norma L2, y una fila a cero se queda a cero.

``TfidfVectorizer`` ya normaliza L2 por defecto (``norm="l2"``), así que con el
vectorizador real quitar ese ``normalize`` solo cambia la salida en el redondeo
de float32. Por eso hay dos tests. El primero fija el contrato con el
vectorizador tal cual. El segundo construye el vectorizador con ``norm=None``
(pisando lo que pase la función) y fija que la L2 se aplica después del
vectorizador, sea cual sea su ``norm``: es el único de los dos que falla si se
quita el ``normalize``. Por lo mismo falla también si la función cambia el
``normalize`` por la L2 del propio vectorizador aunque la salida no cambie:
con ``norm="l2"`` en el constructor, que el espía pisa, la salida no tiene
norma 1; con ``set_params(norm="l2")`` después de crearlo, falla la
precondición sobre la salida del vectorizador.

Los dos comparan la salida con la matriz del vectorizador normalizada aquí a
mano, no solo la norma de cada fila. Con eso fallan también las variantes que
dejan filas de norma 1 pero pierden los pesos TF-IDF (binarizar antes de
normalizar) o que normalizan por columnas.
"""

from __future__ import annotations

import importlib

import numpy as np
import pytest
from sklearn.feature_extraction import text as sklearn_text

_MODULOS = ["services.clustering_engine", "services.analytics.clusters"]

# Dos grupos de títulos que repiten vocabulario, así que superan ``min_df=2``, y
# un último documento cuyas palabras no salen en ningún otro: su fila se queda
# sin vocabulario.
_TEXTOS = (
    [f"Sistema ERP SAP para gestión financiera lote {i}" for i in range(10)]
    + [f"Mantenimiento aplicaciones SAP ABAP módulo {i}" for i in range(10)]
    + ["quórum xilófono zeppelin"]
)
_FILA_SIN_VOCABULARIO = len(_TEXTOS) - 1


def _espiar_vectorizador(
    monkeypatch: pytest.MonkeyPatch, **forzados: object
) -> list[sklearn_text.TfidfVectorizer]:
    """Sustituye ``TfidfVectorizer`` por uno que apunta cada instancia que crea.

    Los argumentos de ``forzados`` pisan a los que pasa la función; sin ellos el
    vectorizador se construye con exactamente los mismos argumentos.
    """
    original = sklearn_text.TfidfVectorizer
    creados: list[sklearn_text.TfidfVectorizer] = []

    def espia(**kwargs: object) -> sklearn_text.TfidfVectorizer:
        vec = original(**{**kwargs, **forzados})
        creados.append(vec)
        return vec

    # ``clustering_engine`` enlaza el nombre al importarse; ``analytics.clusters``
    # lo importa dentro de la función y lo lee del módulo de sklearn.
    monkeypatch.setattr("services.clustering_engine.TfidfVectorizer", espia)
    monkeypatch.setattr(sklearn_text, "TfidfVectorizer", espia)
    return creados


def _embeddings(modulo: str) -> np.ndarray:
    resultado: np.ndarray = importlib.import_module(modulo)._tfidf_embeddings(_TEXTOS)
    return resultado


def _salida_del_vectorizador(creados: list[sklearn_text.TfidfVectorizer]) -> np.ndarray:
    """La matriz que el último vectorizador creado da para el corpus, en denso."""
    # Sin esto el test podría pasar sin probar nada: que el espía llegó a la función.
    assert creados, "el espía no llegó a _tfidf_embeddings"
    crudo: np.ndarray = creados[-1].transform(_TEXTOS).toarray()
    return crudo


def _normalizar_filas(matriz: np.ndarray) -> np.ndarray:
    """Divide cada fila por su norma L2; las filas de norma 0 se quedan a cero."""
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    esperado: np.ndarray = np.divide(matriz, normas, out=np.zeros_like(matriz), where=normas > 0)
    return esperado


def _assert_filas_l2(emb: np.ndarray, crudo: np.ndarray) -> None:
    # Precondiciones del corpus, para que las comparaciones de abajo discriminen:
    # hay una fila a cero, y cada fila con vocabulario reparte pesos distintos
    # entre sus columnas (con todos iguales, binarizar no cambiaría nada).
    assert not crudo[_FILA_SIN_VOCABULARIO].any()
    assert all(np.unique(fila[fila > 0]).size > 1 for fila in crudo[:_FILA_SIN_VOCABULARIO])

    assert emb.shape == crudo.shape
    assert emb.shape[0] == len(_TEXTOS)
    assert np.isfinite(emb).all()
    # Las filas con vocabulario salen con norma 1, con la tolerancia de float32.
    np.testing.assert_allclose(
        np.linalg.norm(emb[:_FILA_SIN_VOCABULARIO], axis=1), 1.0, rtol=0, atol=1e-6
    )
    # Y cada una es la del vectorizador reescalada: conserva los pesos TF-IDF
    # relativos de sus columnas.
    np.testing.assert_allclose(emb, _normalizar_filas(crudo), rtol=0, atol=1e-6)
    # La fila sin vocabulario sigue a cero: ``normalize`` no divide por norma 0.
    assert not emb[_FILA_SIN_VOCABULARIO].any()


@pytest.mark.parametrize("modulo", _MODULOS)
def test_filas_l2_con_el_vectorizador_real(modulo: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Con ``TfidfVectorizer`` sin tocar, cada fila es la suya con norma 1."""
    creados = _espiar_vectorizador(monkeypatch)

    emb = _embeddings(modulo)

    _assert_filas_l2(emb, _salida_del_vectorizador(creados))


@pytest.mark.parametrize("modulo", _MODULOS)
def test_normaliza_aunque_el_vectorizador_no_lo_haga(
    modulo: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con ``norm=None`` en el vectorizador la salida sigue siendo L2."""
    creados = _espiar_vectorizador(monkeypatch, norm=None)

    emb = _embeddings(modulo)

    crudo = _salida_del_vectorizador(creados)
    # Sin esto el test podría pasar sin probar nada: lo que sale del vectorizador
    # parcheado no tiene norma 1 por sí solo. Si falla aquí, la función le cambió
    # el ``norm`` al vectorizador después de crearlo (p. ej. con ``set_params``).
    normas_crudas = np.linalg.norm(crudo[:_FILA_SIN_VOCABULARIO], axis=1)
    assert not np.allclose(normas_crudas, 1.0, rtol=0, atol=1e-6), (
        "el vectorizador ya sale normalizado: se pisó el norm=None forzado tras crearlo"
    )

    _assert_filas_l2(emb, crudo)
