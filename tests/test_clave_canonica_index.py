"""El índice de v92 y la expresión que consulta la API tienen que ser la misma.

Un índice funcional solo sirve si su expresión coincide **carácter a carácter**
con la que aparece en el ``WHERE``. Si divergen no falla nada visible: el
planificador simplemente ignora el índice, el anti-join vuelve al escaneo
completo y la superficie pública vuelve a morir por ``statement_timeout``. Es
decir, el modo de fallo es silencioso hasta que producción se cae — que es
exactamente lo que pasó el 2026-08-28.

``db/alembic/versions/v92_lic_clave_canonica_index.py`` congela su copia en vez
de importarla, siguiendo el criterio de v91 y porque ninguna migración de este
linaje importa del árbol de la app. Este test es el precio de esa decisión: la
copia congelada puede quedarse atrás, pero no en silencio.

Si este test falla, la corrección **no** es tocar la constante de v92 —esa
migración ya corrió en producción y describe el índice que existe allí—. Es
escribir una revisión nueva que reconstruya el índice con la expresión nueva.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from db.sql_fragments import clave_canonica_sql

_RUTA_V92 = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "v92_lic_clave_canonica_index.py"
)


def _cargar_v92() -> Any:
    """Carga la revisión por ruta: ``db/alembic/versions/`` no es un paquete.

    Añadirle un ``__init__.py`` para poder importarla sería tocar el directorio
    que alembic descubre por su cuenta, y no hace falta para leer una constante.
    """
    spec = importlib.util.spec_from_file_location("v92_lic_clave_canonica_index", _RUTA_V92)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


_CLAVE_CANONICA_SQL: str = _cargar_v92()._CLAVE_CANONICA_SQL


def test_indice_v92_coincide_con_la_expresion_de_la_query() -> None:
    """La constante congelada de v92 es ``clave_canonica_sql`` sobre la tabla.

    El alias de la migración es el nombre de la tabla porque ahí no hay ``FROM``
    que lo abrevie; en las consultas es ``l``. Es la única diferencia admisible.
    """
    assert clave_canonica_sql("licitaciones") == _CLAVE_CANONICA_SQL


def test_clave_es_un_md5_de_las_cuatro_componentes() -> None:
    """Las cuatro componentes entran, y entran separadas.

    No comprueba el SQL exacto —de eso va el test de arriba— sino que ninguna se
    haya caído de la concatenación al editarla. Una componente perdida no rompe
    ninguna consulta: colapsa contratos que no debían colapsar, y eso solo se ve
    mirando la superficie pública.
    """
    clave = clave_canonica_sql("l")

    assert clave.startswith("md5(")
    assert "l.organo_contratacion" in clave
    assert "l.cpv" in clave
    assert "l.fecha_publicacion" in clave
    assert "l.titulo" in clave
    # Tres separadores para cuatro componentes.
    assert clave.count("chr(31)") == 3


def test_la_clave_propaga_null_en_vez_de_taparlo() -> None:
    """Sin órgano el hash tiene que ser NULL, no la cadena vacía.

    ``organo_normalizado_sql`` devuelve ``nullif(..., '')`` y ``NULL = NULL`` no
    es cierto, así que hoy dos filas sin órgano **no** colapsan. El hash tiene
    que heredar eso: un ``coalesce`` aquí las colapsaría y haría desaparecer
    contratos de la superficie pública sin que fallara nada.
    """
    clave = clave_canonica_sql("l")

    assert "nullif(" in clave
    # El coalesce legítimo es el de dentro de cada componente (organo vacío,
    # fecha ausente); lo que no puede haber es uno envolviendo al hash entero.
    assert not clave.startswith("md5(coalesce(")
