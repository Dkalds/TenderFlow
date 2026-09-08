"""Guardarraíl: una tabla citada en SQL tiene que existir en las migraciones.

El bug que lo motiva
--------------------
La tabla de membresías se llama `organization_memberships` desde `v61`. Seis
sentencias del ciclo de vida de la organización (C2.2) escribían
`organization_members`, sin la parte final. Consecuencias, todas en producción
si esto llega a mergearse:

- `POST /organizations/{id}/transfer-ownership` devolvía **500** en cuanto el
  llamante era realmente el owner. Las llamadas de alguien que no lo era daban
  403 antes de llegar al SQL, así que el fallo solo aparecía en el camino que
  importa.
- `POST /organizations/{id}/leave` igual.
- El recuento de miembros del preview de borrado devolvía **-1 en silencio**:
  su `try/except` está para que una tabla que aún no existe no tumbe la
  pantalla, y de paso tapaba esto.

No lo vio nadie: mypy y ruff no leen dentro de una cadena SQL, los tests de esas
rutas mockean el repositorio, y la suite unitaria no toca Postgres. Lo encontró
el fuzzing de la API en CI —lo cual está bien, para eso está—, pero un error de
tipeo en un nombre de tabla es barato de detectar sin base de datos delante.

Cómo funciona
-------------
1. Se recogen los nombres que **crean** las migraciones: `op.create_table(...)`,
   y `CREATE TABLE`/`CREATE VIEW`/`CREATE MATERIALIZED VIEW` en SQL literal.
2. Se recogen los nombres que el código **cita**: lo que sigue a `FROM`,
   `JOIN`, `UPDATE` e `INSERT INTO` en las cadenas de `db/` y `services/`.
3. Lo citado tiene que estar en lo creado, salvo lo que declara `_NO_SON_TABLAS`.

Es deliberadamente tonto: no parsea SQL, mira nombres. Un falso positivo se
resuelve añadiendo una línea documentada a `_NO_SON_TABLAS`; un falso negativo
—una tabla creada fuera de una migración— no existe en este repo, porque el
esquema lo manda Alembic (ADR-021).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MIGRACIONES = _REPO_ROOT / "db" / "alembic" / "versions"
_FUENTES = (_REPO_ROOT / "db", _REPO_ROOT / "services")

#: Nombres que aparecen tras FROM/JOIN pero no son tablas del esquema.
#:
#: Cada entrada dice por qué. La lista es corta a propósito: si crece mucho, el
#: extractor está mal, no el esquema.
_NO_SON_TABLAS: frozenset[str] = frozenset(
    {
        # CTEs y subconsultas con alias, que se definen en la propia sentencia.
        "base",
        "d",
        "datos",
        "filas",
        "s",
        "sub",
        "t",
        "x",
        # Funciones de conjunto de Postgres, no relaciones.
        "generate_series",
        "jsonb_array_elements",
        "jsonb_array_elements_text",
        "unnest",
        # Catálogos del sistema.
        "information_schema",
        "pg_indexes",
        "pg_constraint",
        "pg_class",
        "pg_namespace",
        "pg_roles",
        "pg_stat_activity",
        "pg_stat_user_tables",
        "pg_matviews",
        "pg_tables",
        "pg_views",
    }
)

_CREATE_SQL = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+)?(?:TABLE|VIEW)\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?[\"']?(\w+)",
    re.I,
)
_RENAME_SQL = re.compile(r"RENAME\s+TO\s+[\"']?(\w+)", re.I)

#: `FROM x`, `JOIN x`, `UPDATE x`, `INSERT INTO x`. Se excluye `FROM (` —una
#: subconsulta— y los marcadores de parámetro.
#:
#: **Sin `re.I` a propósito.** Este repo escribe las palabras clave de SQL en
#: mayúsculas, y la prosa de los docstrings está en castellano: con `re.I`,
#: «el JOIN de las dos tablas» daba una tabla llamada `de`, y así una docena
#: más. Exigir la mayúscula separa el SQL de lo que habla sobre SQL.
_CITA_SQL = re.compile(r"\b(?:FROM|JOIN|UPDATE|INSERT\s+INTO)\s+(?!\()[\"']?([a-z_][a-z0-9_]*)")

#: Parece SQL de verdad, no una frase que menciona SQL.
_ES_SQL = re.compile(r"\b(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\b")

#: Nombres definidos en la propia sentencia: `WITH x AS (`,
#: `WITH RECURSIVE x AS (`, `, y AS (`. Un CTE no es una tabla del esquema y
#: buscarlo en las migraciones no tiene sentido.
#: La lista de columnas opcional —`reach(src, dst) AS (`— también es un CTE.
#: El `§` es la frontera entre literales: un CTE encadenado suele empezar su
#: propio fragmento (`"nodes AS (SELECT …"`), con la coma en el anterior.
_CTE = re.compile(
    r"(?:\bWITH\s+(?:RECURSIVE\s+)?|,|§)\s*([a-z_][a-z0-9_]*)\s*(?:\([^)]*\))?\s+AS\s*\(", re.I
)

#: Alias de una subconsulta: `FROM ( … ) p`, `JOIN ( … ) t2 ON`. El nombre no
#: sale de ningún `WITH`, así que hay que recogerlo aparte.
_ALIAS_SUBCONSULTA = re.compile(
    r"\)\s+([a-z_][a-z0-9_]*)\b(?=\s*(?:ON|WHERE|GROUP|ORDER|,|$))", re.I
)

#: Alias de tabla: `FROM licitaciones l`, y luego `JOIN adjudicaciones a ON …`.
#: Se recogen para no confundir el alias con una relación.
_ALIAS = re.compile(r"\b(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*)\s+([a-z][a-z0-9_]*)\b")


def _docstrings(arbol: ast.AST) -> set[int]:
    """`id()` de los literales que son docstring.

    Se excluyen porque este repo documenta mucho —bien— y sus docstrings hablan
    de SQL en castellano: «el UPDATE va a…», «el JOIN de las dos tablas» y
    «FROM sin filtro» daban tablas llamadas `va`, `de` y `sin`. Un docstring
    nunca se ejecuta contra Postgres.
    """
    ids: set[int] = set()
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        cuerpo = getattr(nodo, "body", [])
        if (
            cuerpo
            and isinstance(cuerpo[0], ast.Expr)
            and isinstance(cuerpo[0].value, ast.Constant)
            and isinstance(cuerpo[0].value.value, str)
        ):
            ids.add(id(cuerpo[0].value))
    return ids


def _cadenas_de(fichero: Path) -> list[str]:
    """Literales de cadena del módulo —sin docstrings—, que es donde vive el SQL."""
    arbol = ast.parse(fichero.read_text(encoding="utf-8"), filename=str(fichero))
    docs = _docstrings(arbol)
    return [
        n.value
        for n in ast.walk(arbol)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
    ]


def tablas_creadas() -> set[str]:
    """Todo lo que las migraciones crean o renombran."""
    nombres: set[str] = set()
    for fichero in sorted(_MIGRACIONES.glob("*.py")):
        texto = fichero.read_text(encoding="utf-8")
        arbol = ast.parse(texto, filename=str(fichero))
        for nodo in ast.walk(arbol):
            if (
                isinstance(nodo, ast.Call)
                and getattr(nodo.func, "attr", "") in {"create_table", "rename_table"}
                and nodo.args
                and isinstance(nodo.args[0], ast.Constant)
            ):
                nombres.add(str(nodo.args[0].value))
        nombres.update(_CREATE_SQL.findall(texto))
        nombres.update(_RENAME_SQL.findall(texto))
    return nombres


def tablas_citadas() -> dict[str, set[str]]:
    """`{tabla: {ficheros que la citan}}` en el SQL de `db/` y `services/`."""
    citas: dict[str, set[str]] = {}
    for raiz in _FUENTES:
        for fichero in sorted(raiz.rglob("*.py")):
            if "alembic" in fichero.parts or "__pycache__" in fichero.parts:
                continue
            # El SQL de este repo se arma concatenando literales adyacentes, así
            # que `WITH RECURSIVE saltos AS (` cae en un fragmento —que por sí
            # solo no contiene ningún SELECT— y `FROM saltos` en el siguiente.
            # Filtrar fragmento a fragmento tiraba justo el que define el CTE y
            # denunciaba el nombre como tabla inexistente: se junta el módulo
            # entero y la comprobación de «esto es SQL» se hace sobre el conjunto.
            # El separador no es un salto de línea sino un carácter que **no**
            # puede formar parte de un identificador. Uniendo con `\n`, un
            # fragmento que acaba en `"… FROM "` y el siguiente que empieza en
            # `"c.algo"` producían la tabla `c`: la coincidencia cruzaba la
            # frontera entre dos literales, donde no hay SQL contiguo. Con `§`
            # en medio, `FROM` deja de tener un identificador detrás y no casa,
            # pero los CTE y los alias siguen siendo visibles para todo el módulo.
            texto = " § ".join(_cadenas_de(fichero))
            if not _ES_SQL.search(texto):
                continue
            locales = {m.lower() for m in _CTE.findall(texto)}
            locales.update(alias.lower() for _, alias in _ALIAS.findall(texto))
            locales.update(m.lower() for m in _ALIAS_SUBCONSULTA.findall(texto))
            for nombre in _CITA_SQL.findall(texto):
                if nombre.lower() in locales:
                    continue
                citas.setdefault(nombre.lower(), set()).add(
                    fichero.relative_to(_REPO_ROOT).as_posix()
                )
    return citas


def test_las_migraciones_crean_las_tablas_conocidas() -> None:
    """Si el extractor deja de ver las migraciones, el test de abajo no prueba nada."""
    creadas = tablas_creadas()
    for imprescindible in ("licitaciones", "organizations", "organization_memberships"):
        assert imprescindible in creadas, f"{imprescindible} no se ve creada en db/alembic/versions"


def test_ninguna_consulta_cita_una_tabla_inexistente() -> None:
    creadas = {n.lower() for n in tablas_creadas()}
    huerfanas = {
        nombre: sorted(ficheros)
        for nombre, ficheros in tablas_citadas().items()
        if nombre not in creadas
        and nombre not in _NO_SON_TABLAS
        # `pg_*` es el catálogo del sistema: existe siempre y no lo crea ninguna
        # migración.
        and not nombre.startswith("pg_")
    }
    assert not huerfanas, (
        "SQL que cita una tabla que ninguna migración crea. Un error de tipeo aquí "
        "no lo ve ni mypy ni ruff, y solo aparece cuando alguien usa la ruta:\n  "
        + "\n  ".join(f"{n}: {', '.join(f)}" for n, f in sorted(huerfanas.items()))
    )
