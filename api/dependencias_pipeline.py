"""Qué hacer cuando una ruta toca una dependencia que la imagen no instala.

La imagen de la API instala ``requirements-api.txt`` (C3.1, 2026-09-18), sin
el ML clásico ni la analítica pesada del pipeline. Ningún módulo los importa al
arrancar —``tests/test_unit_api_imagen_slim.py`` lo prueba—, pero algunos
caminos de request sí lo hacen en diferido. Este módulo es la única definición
de «qué paquetes son del pipeline» del lado de la API, para que esas rutas
distingan *«falta una dependencia que no viaja en esta imagen»* (503, estado
conocido del despliegue) de cualquier otro fallo (500, un bug).
"""

from __future__ import annotations

#: Módulos de primer nivel que solo instala ``requirements-pipeline.txt``.
#: ``scipy``, ``joblib`` y ``threadpoolctl`` no se declaran en ningún ``.in``:
#: entran como dependencias de scikit-learn y se van con él.
PAQUETES_DEL_PIPELINE = frozenset(
    {
        "sklearn",
        "scipy",
        "joblib",
        "threadpoolctl",
        "statsmodels",
        "patsy",
        "networkx",
        "lxml",
        "sentence_transformers",
        "torch",
    }
)


def paquete_del_pipeline_ausente(exc: BaseException) -> str | None:
    """Nombre del paquete del pipeline cuya ausencia causó ``exc``, si es el caso.

    Recorre la cadena de causas porque el ``ModuleNotFoundError`` rara vez
    llega desnudo: ``joblib.load`` o una capa de carga de modelos lo envuelve.
    Devuelve ``None`` para cualquier otro error, incluido un
    ``ModuleNotFoundError`` de un paquete que sí debería estar: eso es un bug de
    empaquetado y tiene que seguir siendo un 500.
    """
    visto: set[int] = set()
    actual: BaseException | None = exc
    while actual is not None and id(actual) not in visto:
        visto.add(id(actual))
        if isinstance(actual, ModuleNotFoundError):
            raiz = (actual.name or "").split(".", 1)[0]
            if raiz in PAQUETES_DEL_PIPELINE:
                return raiz
        actual = actual.__cause__ or actual.__context__
    return None
