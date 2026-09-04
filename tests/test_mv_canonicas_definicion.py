"""La vista materializada define lo mismo que los fragmentos del repositorio.

Desde la revisión ``v94`` la definición de «qué contrato se publica» vive en la
vista ``licitaciones_canonicas`` (redefinida en ``v98`` para acotarla al universo
tecnológico, en ``v99`` para admitir la señal de ML/LLM/pliego y en ``v102`` para
agrupar por una clave que el upsert no reescribe), y las seis superficies
indexables se limitan a leer de ella. Eso resuelve el coste —de ~200 s por petición a ~10 s por pasada
del pipeline— pero abre un modo de fallo nuevo: la vista congela su cuerpo en la
migración, y si ese cuerpo se separa de los fragmentos que el repositorio
considera canónicos, **nada falla**. La superficie serviría, muy deprisa, un
conjunto que no es el que su propio código dice servir.

Este fichero es la única cosa que impide eso, y por eso compara el literal
congelado carácter a carácter en vez de comprobar propiedades sueltas.

Aquí viven además dos propiedades que antes se comprobaban sobre el SQL de cada
consulta (``tests/test_dedupe_publico.py``) y que al materializar dejaron de
estar allí: siguen siendo ciertas, pero ahora son propiedades **de la vista**.

Si este fichero falla, la corrección **no** es editar la constante de la
revisión vigente: esa migración ya corrió y describe la vista que existe en
producción. Es escribir una revisión nueva que reconstruya la vista con la
definición nueva y mover ``_RUTA_VISTA`` a ella (v94 → v98 fue la primera vez;
v99 y v102, las siguientes).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from db.sql_fragments import (
    clave_canonica_agrupable_sql,
    exclude_duplicados_sql,
    orden_canonico_sql,
)

# La revisión que define la vista HOY. Cada redefinición mueve este puntero:
# v94 la creó; v98 la acotó al universo tecnológico; v99 le añadió la señal de
# ML/LLM/pliego; v102 cambió la componente temporal de la clave por una que el
# upsert no reescribe. Apuntar a una revisión vieja haría pasar el test contra
# una vista que ya no existe en producción.
_RUTA_VISTA = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "v102_mv_canonicas_clave_inmutable.py"
)


def _cargar_revision_vigente() -> Any:
    """Carga la revisión por ruta: ``db/alembic/versions/`` no es un paquete."""
    spec = importlib.util.spec_from_file_location("v102_mv_canonicas_clave_inmutable", _RUTA_VISTA)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


_REVISION = _cargar_revision_vigente()
_CUERPO: str = _REVISION._CUERPO


def _publicable_esperado() -> str:
    """El umbral de sustancia más el dedupe marcado, compuesto desde el repositorio."""
    from db.repositories.publico import _BASE_WHERE

    return str(_BASE_WHERE)


def test_el_cuerpo_congelado_es_el_que_componen_los_fragmentos() -> None:
    """La comprobación que hace seguro congelar la definición.

    Se reconstruye el cuerpo desde las mismas piezas que usa el repositorio y se
    compara con el literal de la migración. Cualquier deriva —un umbral que
    cambie, un criterio de desempate que se mueva, una componente que se caiga de
    la clave— falla aquí y no en producción tres semanas después.
    """
    clave = clave_canonica_agrupable_sql("l")
    # S608: no se ejecuta nada. Es la reconstrucción del literal para compararlo
    # contra el congelado, y sus piezas son constantes del propio repositorio.
    esperado = (
        f"SELECT DISTINCT ON ({clave}) "  # noqa: S608
        "l.id_externo, l.titulo, l.ccaa, l.cpv, l.fecha_publicacion, l.fecha_extraccion "
        f"FROM licitaciones l WHERE {_publicable_esperado()} "
        f"ORDER BY {clave}, {orden_canonico_sql('l')}"
    )

    assert esperado == _CUERPO


def test_la_vista_excluye_los_duplicados_ya_marcados() -> None:
    """El filtro nuevo se **suma** al viejo, no lo sustituye.

    ``exclude_duplicados_sql`` tapa los pares cross-fuente que un humano ya
    confirmó; la clave canónica tapa las reemisiones que nadie miró. Son
    problemas distintos y hacen falta los dos.

    Esta propiedad se comprobaba sobre el SQL de cada superficie hasta ``v94``.
    Al materializar dejó de estar en las consultas —ninguna vuelve a nombrar
    ``licitaciones_duplicados``— sin dejar de ser cierta: ahora vive aquí.
    """
    assert exclude_duplicados_sql("l.id_externo") in _CUERPO
    assert "licitaciones_duplicados" in _CUERPO


def test_la_publicabilidad_se_aplica_antes_de_elegir_la_canonica() -> None:
    """Una fila pobre no puede tapar a la buena, que es el error caro.

    En el anti-join esto se garantizaba filtrando la fila gemela igual que la
    exterior. En la vista el mecanismo es otro y más simple: el ``WHERE`` de
    publicabilidad se aplica **antes** del ``DISTINCT ON``, así que una reemisión
    sin importe y con descripción corta ni siquiera es candidata a ser canónica.

    Se comprueba por posición porque es exactamente lo que importa: si el
    ``WHERE`` acabara fuera de la subconsulta, el contrato desaparecería entero
    de la superficie sin que fallara ninguna consulta.
    """
    pos_where = _CUERPO.find(" WHERE ")
    pos_order = _CUERPO.find(" ORDER BY ")

    assert pos_where != -1, "la vista tiene que filtrar la publicabilidad"
    assert pos_where < pos_order, "el WHERE va antes del criterio de canónica"


def test_el_orden_termina_en_la_clave_primaria() -> None:
    """Sin el desempate final, la URL de un contrato cambia entre refrescos.

    ``DISTINCT ON`` se queda con la primera fila de cada grupo según el
    ``ORDER BY``. Si dos gemelas empataran en los tres primeros criterios,
    Postgres podría devolver una u otra según el plan, y el sitemap publicaría
    una URL distinta en cada refresco — que es justo lo que un sitemap existe
    para evitar.
    """
    assert _CUERPO.rstrip().endswith("l.id_externo")


def test_la_vista_lleva_las_columnas_que_el_sitemap_necesita() -> None:
    """El sitemap no toca ``licitaciones``: se sirve entero de la vista.

    Si alguna de las cuatro se cayera de la proyección, ``pagina_de_sitemap``
    tendría que volver a la tabla y perdería el índice único que hoy resuelve su
    ``ORDER BY id_externo LIMIT/OFFSET``.
    """
    for columna in ("l.id_externo", "l.titulo", "l.ccaa", "l.fecha_extraccion"):
        assert columna in _CUERPO, f"la vista perdió {columna}"


def test_el_refresco_es_concurrente_y_tiene_su_indice_unico() -> None:
    """Sin ``CONCURRENTLY`` el refresco bloquea la superficie pública.

    Un ``REFRESH`` normal toma un ``AccessExclusiveLock`` sobre la vista: las
    lecturas se quedan esperando los ~10 s que dura, cada 4 horas. Y
    ``CONCURRENTLY`` sólo es posible si existe un índice ÚNICO, así que las dos
    mitades se comprueban juntas: quitar el índice rompería el refresco sin que
    nada más lo notara.
    """
    fuente = _RUTA_VISTA.read_text(encoding="utf-8")

    assert "CREATE UNIQUE INDEX" in fuente
    assert "id_externo" in fuente
