"""Guardrail anti-regresión: dedupe cross-fuente en queries analíticas.

El dedupe cross-fuente (``services/dedupe.py``) marca como ``confirmed`` las
licitaciones duplicadas entre fuentes (PLACSP/TED/PSCP…). Toda consulta
analítica de competencia o ML que agregue sobre ``licitaciones`` o
``adjudicaciones`` **debe** excluir esas filas con ``exclude_duplicados_sql()``;
si no, infla silenciosamente cuota de mercado, HHI, renovaciones y los datasets
de entrenamiento (ADR-009, RFC 20260611-1 §5.2).

Hoy todas las queries relevantes lo aplican. Este test falla si alguien añade
una consulta analítica nueva sobre esas tablas y olvida el filtro — convierte
una regresión silenciosa de correctitud en un fallo de CI ruidoso.

Granularidad: por función. Una función en un módulo escaneado cuyo código
referencia ``FROM/JOIN licitaciones`` o ``adjudicaciones`` debe referenciar
también, en código, ``exclude_duplicados_sql`` o una guarda equivalente (ver
:func:`_module_guard_names`). Las excepciones legítimas (queries que
deliberadamente no deduplican) se declaran en ``_ALLOWLIST`` con su
justificación.

**La prosa no cuenta.** Docstrings y comentarios no ejecutan nada, así que ni
aportan la guarda ni convierten una función en consulta. Una versión anterior
del escáner buscaba nombres como subcadenas del texto de la función, docstring y
comentarios incluidos, y bastaba escribir «mismo alcance que
:func:`cuota_mercado`» para que una query sin el anti-join pasara por guardada:
``cuota_mercado`` sí llama a ``exclude_duplicados_sql``, y su nombre en el
docstring era suficiente. Ahora se lee el AST: cuentan los identificadores que
el código usa y los literales de texto que no son cadenas sueltas (docstrings o
cualquier otra cadena sin asignar).

**Por qué la lista de módulos incluye ficheros de ``db/``.** El guardrail nació
escaneando solo ``services/competitive`` y ``services/ml``, que era donde vivían
las queries analíticas. La ola del ratchet TID251 (ADR-022: todo el SQL a
``db/``) las va moviendo — y al moverlas las sacaba del radio del escáner, que
es la peor forma de perder un guardrail: sin fallo, sin aviso, y con el commit
de la migración pareciendo verde. Los módulos de ``db/`` que reciben SQL
analítico migrado se añaden aquí **en el mismo cambio que los crea**.

No se escanea ``db/repositories/`` entero a propósito: ahí conviven las queries
analíticas con el CRUD del API (leer un expediente por id, listar paginado), y
ese CRUD no debe deduplicar —muestra lo que hay, no agrega métricas—. Una regla
por directorio marcaría todo eso como violación y la reacción sería engordar
``_ALLOWLIST`` hasta vaciarla de sentido. La lista explícita obliga a decidir
módulo a módulo, que es la decisión que importa.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

# Directorios cuyas queries analíticas deben respetar el dedupe.
_SCANNED_DIRS = ("services/competitive", "services/ml")

# Módulos sueltos de ``db/`` que han recibido SQL analítico migrado desde
# ``services/``. Ver el docstring: esta lista crece con cada ola del ratchet.
_SCANNED_FILES = (
    "db/repositories/renovaciones.py",
    "db/repositories/adjudicaciones.py",
    "db/repositories/ml_dataset.py",
    "db/repositories/mercado.py",
)

# Referencia a las tablas canónicas en cláusulas FROM/JOIN.
# ``\b`` tras el nombre evita falsos positivos con ``licitaciones_duplicados``,
# ``licitaciones_history``, etc. (``_`` es carácter de palabra → no hay frontera).
_TABLE_REF = re.compile(
    r"\b(?:FROM|JOIN)\s+(?:licitaciones|adjudicaciones)\b",
    re.IGNORECASE,
)

_GUARD_CALL = "exclude_duplicados_sql"

# Excepciones legítimas: "modulo.funcion" -> motivo.
# Mantener vacío salvo justificación explícita y revisada.
#
# Las entradas marcadas PENDIENTE DE AUDITAR **no** son excepciones legítimas:
# son deuda congelada al ampliar el escáner a ``db/`` el 2026-08-18. Esta lista
# solo puede encoger (mismo contrato que el ratchet TID251 y que KNOWN_5XX).
_ALLOWLIST: dict[str, str] = {
    # --- Exentas por diseño -------------------------------------------------
    "adjudicaciones.list_paginated": (
        "CRUD del API, no analitica: lista filas tal como estan para que el "
        "usuario vea el dato crudo. Deduplicar aqui ocultaria filas que si "
        "existen en la fuente, que es lo contrario de lo que pide un listado."
    ),
    "adjudicaciones.list_for_licitacion": (
        "CRUD del API sobre UN expediente ya elegido por el usuario (la ficha "
        "de su oportunidad propone el cierre con estos adjudicatarios). No "
        "agrega ninguna metrica. Ademas deduplicar aqui seria danino: un "
        "expediente marcado como duplicado despues de abrirse como pursuit "
        "dejaria su ficha sin adjudicatarios y el cierre asistido mudo."
    ),
    "adjudicaciones.find_publicacion_posterior_a_adjudicacion": (
        "Deteccion de anomalias de calidad del dato. Su objeto ES encontrar "
        "filas raras; excluir duplicados cross-fuente esconderia justo el tipo "
        "de caso que busca."
    ),
    "adjudicaciones.completitud_por_fuente": (
        "C4.7: mide QUE TRAE CADA FUENTE, no que contratos hay. Deduplicar "
        "cambiaria la pregunta: una fila descartada por duplicada sigue siendo "
        "una fila que esa fuente publico con o sin `n_ofertas_recibidas`, y es "
        "eso lo que la tabla de completitud describe. Ademas el sesgo iria en "
        "la direccion equivocada: las fuentes con mas duplicados perderian mas "
        "filas y su cobertura se calcularia sobre una muestra distinta."
    ),
    "ml_dataset.filas_pendientes_ml_tecnologias": (
        "Poblacion de PUNTUACION por fila del clasificador multi-tecnologia, no "
        "un agregado: cada licitacion lleva su propio resumen ml_*, y una "
        "duplicada que se quedara sin puntuar mostraria resumen vacio en su "
        "ficha. Es la misma consulta que ya corria inline en "
        "scraper/ml_training.py (fuera del escaner) hasta que T3 la movio a db/ "
        "el 2026-09-18; la dedupe se aplica al agregar, no al etiquetar."
    ),
    # --- Auditadas y corregidas el 2026-08-18 ------------------------------
    # Al ampliar el escaner a db/ aparecieron 7 funciones sin la clausula. Se
    # audito una por una y NINGUNA queda pendiente:
    #   - load_for_competitors / load_licitadores: se les anadio la clausula.
    #   - las 4 de UTE: la clausula se sembro en `_adj_filter_conditions`, el
    #     helper que las cuatro comparten, para que no se pueda olvidar en la
    #     quinta.
    #   - ml_dataset.licitaciones_abiertas: FALSO POSITIVO. Siempre deduplico,
    #     con la subconsulta escrita inline; el escaner no la veia. Corregido en
    #     `_is_guarded`, no en la query.
    # Por eso `_PENDIENTES_MAX` es 0: no hay deuda de dedupe conocida.
}

_REPO_ROOT = Path(__file__).resolve().parent.parent


#: Marca textual de la subquery de dedupe. Sirve para reconocer el idioma de
#: ``db/``, que no llama a ``exclude_duplicados_sql()`` sino que declara la
#: cláusula como constante de módulo (``ml_dataset._NO_DUPLICADOS``) para no
#: importar hacia arriba (ADR-024).
_GUARD_TABLE = "licitaciones_duplicados"


def _scanned_paths() -> list[Path]:
    """Ficheros a escanear: los directorios completos más los módulos sueltos."""
    paths: list[Path] = []
    for rel_dir in _SCANNED_DIRS:
        paths.extend(
            p for p in sorted((_REPO_ROOT / rel_dir).rglob("*.py")) if p.name != "__init__.py"
        )
    for rel_file in _SCANNED_FILES:
        path = _REPO_ROOT / rel_file
        # Un módulo renombrado o movido dejaría de escanearse en silencio, que
        # es exactamente el fallo que este guardrail existe para evitar.
        assert path.is_file(), f"_SCANNED_FILES apunta a un fichero inexistente: {rel_file}"
        paths.append(path)
    return paths


@dataclass(frozen=True)
class _Codigo:
    """Lo que un nodo del AST usa como código, sin su prosa.

    ``nombres`` son los identificadores que referencia: un ``Name`` o el atributo
    de un ``Attribute`` (``exclude_duplicados_sql`` y ``repo.alcance_sql`` cuentan
    igual), comparados enteros y no como subcadena. ``literales`` son sus cadenas
    —donde vive el SQL, también las partes fijas de un f-string— menos las
    cadenas sueltas (:func:`_codigo`). Los comentarios no llegan al AST.

    Límite conocido: el escáner no distingue SQL de otro texto, así que un
    mensaje de error o de log que escriba ``licitaciones_duplicados`` contaría
    como subconsulta de dedupe. Es un falso negativo que exige escribir ese
    nombre en código ejecutable, no en prosa.
    """

    nombres: frozenset[str]
    literales: tuple[str, ...]

    def consulta_tablas_canonicas(self) -> bool:
        """Algún literal hace ``FROM``/``JOIN`` sobre las tablas canónicas."""
        return any(_TABLE_REF.search(literal) for literal in self.literales)

    def excluye_duplicados(self) -> bool:
        """Usa el helper canónico o escribe la subconsulta de dedupe a mano."""
        return _GUARD_CALL in self.nombres or any(
            _GUARD_TABLE in literal for literal in self.literales
        )


def _codigo(nodo: ast.AST) -> _Codigo:
    """Identificadores y literales de ``nodo``, descartando la prosa.

    Prosa es toda cadena usada como sentencia suelta: el docstring de un módulo,
    una clase o una función, y cualquier otra cadena sin asignar, que tampoco
    ejecuta nada.
    """
    prosa = {
        id(sentencia.value)
        for sentencia in ast.walk(nodo)
        if isinstance(sentencia, ast.Expr)
        and isinstance(sentencia.value, ast.Constant)
        and isinstance(sentencia.value.value, str)
    }
    nombres: set[str] = set()
    literales: list[str] = []
    for hijo in ast.walk(nodo):
        if isinstance(hijo, ast.Name):
            nombres.add(hijo.id)
        elif isinstance(hijo, ast.Attribute):
            nombres.add(hijo.attr)
        elif (
            isinstance(hijo, ast.Constant) and isinstance(hijo.value, str) and id(hijo) not in prosa
        ):
            literales.append(hijo.value)
    return _Codigo(frozenset(nombres), tuple(literales))


def _module_guard_names(tree: ast.Module) -> set[str]:
    """Nombres del módulo que, al referenciarse, ya aportan el dedupe.

    Son de tres clases, y hacen falta las tres porque la cláusula no siempre está
    escrita dentro de la función que consulta:

    1. **Constantes cuyo valor ES la cláusula**, escrita a mano. Fue el idioma
       de ``db/`` mientras la subquery se duplicaba en cada módulo para no
       importar hacia arriba (ADR-024).
    2. **Constantes cuyo valor SALE de** ``exclude_duplicados_sql(...)``. Es el
       idioma vigente desde que la definición canónica bajó a
       ``db/sql_fragments.py`` (el lado correcto de la frontera):
       ``ml_dataset._NO_DUPLICADOS`` sigue siendo constante de módulo —cuatro
       consultas la interpolan sobre el mismo alias— pero ya no reescribe la
       subquery. Sin esta rama, sustituir la copia por la llamada convertía en
       "violación" a las funciones que la usan, o sea castigaba justo la
       refactorización buena.
    3. **Funciones auxiliares ya guardadas.** Si un helper construye el ``WHERE``
       con la cláusula sembrada dentro (``adjudicaciones._adj_filter_conditions``),
       las funciones que delegan en él están cubiertas aunque su propio cuerpo no
       mencione el dedupe. Mismo motivo que (2): sembrar la cláusula en el punto
       compartido hace imposible olvidarla en la siguiente query.

    El coste de (3) es que una función que llame al helper por cualquier otro
    motivo también pasaría. Es un cambio de falsos positivos por falsos
    negativos que se acepta a conciencia: el modo de fallo que importa es la
    query nueva escrita a mano sin dedupe, y esa no llama a ningún helper.

    En las tres clases cuenta solo el código (:func:`_codigo`): un helper cuyo
    docstring explica el anti-join sin aplicarlo no es una guarda.
    """
    names: set[str] = set()
    for node in tree.body:
        # De una constante se mira toda la expresión y no solo un `ast.Call`
        # directo: la llamada puede venir envuelta (concatenada con otro
        # fragmento, dentro de un `f"..."`), y la subconsulta escrita a mano es
        # un literal que también puede ir concatenado.
        if isinstance(node, ast.Assign) and _codigo(node.value).excluye_duplicados():
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and _codigo(node).excluye_duplicados()
        ):
            names.add(node.name)
    return names


@dataclass(frozen=True)
class _Funcion:
    """Una función escaneada, con el código de su cuerpo y las guardas de su módulo."""

    qualname: str
    fichero: str
    codigo: _Codigo
    guard_names: frozenset[str]


def _funciones(source: str, *, module: str, fichero: str) -> list[_Funcion]:
    """Todas las funciones de un módulo, anidadas y métodos incluidos."""
    tree = ast.parse(source, filename=fichero)
    guard_names = frozenset(_module_guard_names(tree))
    return [
        _Funcion(f"{module}.{node.name}", fichero, _codigo(node), guard_names)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def _iter_functions() -> list[_Funcion]:
    """Las funciones de todos los ficheros escaneados."""
    out: list[_Funcion] = []
    for py_file in _scanned_paths():
        source = py_file.read_text(encoding="utf-8")
        out.extend(_funciones(source, module=py_file.stem, fichero=str(py_file)))
    return out


def _is_guarded(funcion: _Funcion) -> bool:
    """La query excluye duplicados: por llamada, por subconsulta inline o por guarda.

    Lo segundo cubre las queries que escriben el ``NOT IN (SELECT ... FROM
    licitaciones_duplicados ...)`` a mano dentro del SQL, sin pasar por el helper
    — ``ml_dataset.licitaciones_abiertas`` lo hizo así y una versión anterior de
    este escáner la marcaba como violación siendo correcta.
    """
    return funcion.codigo.excluye_duplicados() or not funcion.guard_names.isdisjoint(
        funcion.codigo.nombres
    )


def _violaciones(funciones: list[_Funcion]) -> list[str]:
    """``qualname  (fichero)`` de cada consulta sin dedupe que no esté en ``_ALLOWLIST``."""
    return [
        f"{funcion.qualname}  ({funcion.fichero})"
        for funcion in funciones
        if funcion.qualname not in _ALLOWLIST
        and funcion.codigo.consulta_tablas_canonicas()
        and not _is_guarded(funcion)
    ]


def test_analytical_queries_exclude_duplicados() -> None:
    """Toda función que consulta las tablas canónicas debe excluir duplicados."""
    violations = _violaciones(_iter_functions())

    assert not violations, (
        "Funciones que consultan licitaciones/adjudicaciones sin "
        f"{_GUARD_CALL}() (riesgo de inflar métricas competitivas/ML):\n  "
        + "\n  ".join(violations)
        + "\n\nAñadí `AND {exclude_duplicados_sql()}` a la query, o declará la "
        "función en _ALLOWLIST con justificación si NO debe deduplicar."
    )


def test_guardrail_actually_scans_functions() -> None:
    """Meta-test: el escáner encuentra funciones (evita falso verde por path roto)."""
    funcs = _iter_functions()
    assert len(funcs) > 10, f"Escáner solo encontró {len(funcs)} funciones; ¿paths mal?"
    # Y al menos una función realmente referencia las tablas canónicas.
    assert any(funcion.codigo.consulta_tablas_canonicas() for funcion in funcs), (
        "Ninguna función referencia licitaciones/adjudicaciones; regex o paths rotos."
    )


#: Módulo de mentira para :func:`test_la_prosa_no_cuenta_como_guarda`.
#:
#: - ``ranking``, ``con_constante``, ``con_subconsulta_escrita`` y ``con_helper``
#:   deduplican en código: por llamada, por constante de módulo, por subconsulta
#:   escrita en el literal y por un helper que llama a ``exclude_duplicados_sql``.
#: - Las cuatro ``denominador*`` consultan sin dedupe y solo lo *mencionan* en
#:   prosa: nombrando en su docstring la guarda ``ranking`` y
#:   ``exclude_duplicados_sql`` (el caso real que motivó el endurecimiento),
#:   escribiendo ``licitaciones_duplicados`` en su docstring o en un comentario,
#:   o llamando a ``_filtro_sin_dedupe``, un helper que nombra
#:   ``exclude_duplicados_sql`` y la tabla solo en su docstring.
#: - ``explica_sin_consultar`` escribe ``FROM adjudicaciones`` sin ejecutarlo.
_MODULO_DE_PRUEBA = '''
"""Deduplica con exclude_duplicados_sql() contra licitaciones_duplicados."""

from db.sql_fragments import exclude_duplicados_sql

_NO_DUPLICADOS = exclude_duplicados_sql("a.licitacion_id")


def _filtro_con_dedupe():
    return f"a.importe_adjudicado > 0 AND {exclude_duplicados_sql()}"


def _filtro_sin_dedupe():
    """Importe positivo; exclude_duplicados_sql() y licitaciones_duplicados, aparte."""
    return "a.importe_adjudicado > 0"


def ranking():
    return f"SELECT 1 FROM adjudicaciones a WHERE {exclude_duplicados_sql()}"


def con_constante():
    return f"SELECT 1 FROM adjudicaciones a WHERE {_NO_DUPLICADOS}"


def con_subconsulta_escrita():
    return (
        "SELECT 1 FROM licitaciones l WHERE l.id_externo NOT IN "
        "(SELECT licitacion_id FROM licitaciones_duplicados)"
    )


def con_helper():
    return f"SELECT 1 FROM adjudicaciones a WHERE {_filtro_con_dedupe()}"


def denominador():
    """Mismo alcance que :func:`ranking`: sin duplicados (exclude_duplicados_sql)."""
    return "SELECT COUNT(*) FROM adjudicaciones a"


def denominador_tabla_en_docstring():
    """Sin las filas de ``licitaciones_duplicados`` confirmadas."""
    return "SELECT COUNT(*) FROM adjudicaciones a"


def denominador_comentado():
    # Sin duplicados, como ranking(): _NO_DUPLICADOS / licitaciones_duplicados.
    return "SELECT COUNT(*) FROM licitaciones l"


def denominador_con_helper_en_prosa():
    return f"SELECT COUNT(*) FROM adjudicaciones a WHERE {_filtro_sin_dedupe()}"


def explica_sin_consultar():
    """Resume lo que ranking() hace FROM adjudicaciones, sin tocar la BD."""
    return None
'''


def test_la_prosa_no_cuenta_como_guarda() -> None:
    """Ni docstrings ni comentarios guardan una query, ni la convierten en query.

    Cubre las dos mitades del escáner textual anterior: nombrar en prosa una
    guarda (``ranking``, ``exclude_duplicados_sql``) y escribir en prosa la
    tabla ``licitaciones_duplicados``. Las dos, en el docstring de la función que
    consulta y en el de un helper al que llama. Sin esto, volver a buscar en el
    texto de la función devolvería el punto ciego que tuvo
    ``mercado.denominador_cuota``: su docstring nombraba la función hermana que
    sí deduplica, así que quitarle el anti-join no hacía fallar el guardrail.
    """
    funciones = _funciones(_MODULO_DE_PRUEBA, module="prueba", fichero="<prueba>")

    guard_names = funciones[0].guard_names
    assert {"_NO_DUPLICADOS", "_filtro_con_dedupe"} <= guard_names
    assert "_filtro_sin_dedupe" not in guard_names
    assert {f.qualname for f in funciones if _is_guarded(f)} >= {
        "prueba.ranking",
        "prueba.con_constante",
        "prueba.con_subconsulta_escrita",
        "prueba.con_helper",
    }
    assert sorted(_violaciones(funciones)) == [
        "prueba.denominador  (<prueba>)",
        "prueba.denominador_comentado  (<prueba>)",
        "prueba.denominador_con_helper_en_prosa  (<prueba>)",
        "prueba.denominador_tabla_en_docstring  (<prueba>)",
    ]


#: Deuda de dedupe conocida. Se congeló en 7 al extender el escáner a ``db/`` el
#: 2026-08-18 y bajó a 0 el mismo día al auditarlas todas. Solo puede bajar.
_PENDIENTES_MAX = 0


def test_pendientes_de_auditar_solo_pueden_encoger() -> None:
    """Ratchet: la deuda de dedupe en ``db/`` no crece.

    Sin este tope, ``_ALLOWLIST`` es una papelera: basta con añadir una entrada
    para que una query nueva sin dedupe pase el guardrail. Con él, añadir una
    obliga a quitar otra o a subir el número a mano, que es una decisión visible
    en el diff.
    """
    pendientes = [k for k, v in _ALLOWLIST.items() if v.startswith("PENDIENTE DE AUDITAR")]
    assert len(pendientes) <= _PENDIENTES_MAX, (
        f"{len(pendientes)} entradas PENDIENTE DE AUDITAR, tope {_PENDIENTES_MAX}. "
        "Esta lista solo encoge: audita la query en vez de declararla pendiente.\n  "
        + "\n  ".join(sorted(pendientes))
    )


def test_guardrail_cubre_el_sql_migrado_a_db() -> None:
    """Los módulos de ``db/`` con SQL analítico migrado entran en el escáner.

    Sin esto, mover una query de ``services/`` a ``db/`` (ADR-022) la sacaba del
    radio del guardrail y el commit de la migración salía verde habiendo
    desactivado la comprobación. Este test falla si alguien quita de la lista
    alguno de los módulos que ya recibieron SQL analítico migrado.
    """
    # Se repiten aquí a propósito y no se leen de `_SCANNED_FILES`: comprobar la
    # lista contra sí misma no fallaría nunca. Así quitar uno obliga a tocar dos
    # sitios, y el diff lo enseña. Un módulo migrado nuevo se añade a los dos.
    migrados = {
        "db/repositories/renovaciones.py",
        "db/repositories/adjudicaciones.py",
        "db/repositories/ml_dataset.py",
        "db/repositories/mercado.py",
    }
    escaneados = {p.relative_to(_REPO_ROOT).as_posix() for p in _scanned_paths()}
    assert migrados <= escaneados, f"no se escanean: {sorted(migrados - escaneados)}"

    # Y el idioma de db/ (constante de módulo) se reconoce de verdad: si
    # `_module_guard_names` dejara de detectarlo, las funciones de ml_dataset
    # pasarían a "violación" y alguien las metería en _ALLOWLIST por error.
    ml_dataset = _REPO_ROOT / "db/repositories/ml_dataset.py"
    source = ml_dataset.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(ml_dataset))
    assert "_NO_DUPLICADOS" in _module_guard_names(tree), (
        "No se detectó la constante de dedupe de ml_dataset.py; "
        "¿cambió el idioma de db/ o la subquery?"
    )

    # Y el reconocimiento por helper: `_adj_filter_conditions` siembra la
    # cláusula para las cuatro consultas de UTE. Si dejara de detectarse, las
    # cuatro pasarían a "violación" y alguien las metería en _ALLOWLIST en vez
    # de darse cuenta de que el guardrail es el que se rompió.
    adj = _REPO_ROOT / "db/repositories/adjudicaciones.py"
    adj_source = adj.read_text(encoding="utf-8")
    adj_names = _module_guard_names(ast.parse(adj_source, filename=str(adj)))
    assert "_adj_filter_conditions" in adj_names, (
        "El helper compartido de las consultas UTE ya no aporta el dedupe; "
        "o se le quitó la cláusula, o el detector dejó de verla."
    )

    # Lo mismo en mercado: el dossier y el listado no llaman al helper, sino a
    # `_exigir_dedupe`, que comprueba en código que el alcance lo trae.
    mercado = _REPO_ROOT / "db/repositories/mercado.py"
    mercado_source = mercado.read_text(encoding="utf-8")
    mercado_names = _module_guard_names(ast.parse(mercado_source, filename=str(mercado)))
    assert {"alcance_sql", "_exigir_dedupe"} <= mercado_names, (
        "El constructor de alcances de mercado o su comprobación ya no aportan "
        "el dedupe; o se les quitó la cláusula, o el detector dejó de verla."
    )


# ───────────────────────────────────────────────────────────────────────────
# Escáner de literales: los dos fragmentos que sólo pueden vivir en un sitio
# ───────────────────────────────────────────────────────────────────────────
#
# El guardrail de arriba comprueba que una query *deduplique*. Éste comprueba
# algo distinto y complementario: que no lo haga escribiendo el fragmento a
# mano. Dos definiciones del mismo predicado no fallan nunca de forma visible
# —el resultado sigue siendo correcto— y por eso divergen en silencio:
#
# - el ``COALESCE`` del universo: una variante deja de ser servida por el
#   índice parcial de ``v84`` y el plan vuelve al Parallel Seq Scan de 9,5 s
#   sin que cambie ni un resultado (ver ``tests/test_scoring_universo_index.py``,
#   que vigila la otra mitad: que las copias pidan todas lo mismo);
# - el anti-join de duplicados: una copia que se quede en ``status =
#   'confirmed'`` mientras la canónica cambia de criterio esconde —o deja de
#   esconder— filas en una superficie y no en la otra.
#
# Los dos tienen ya definición canónica en ``db/sql_fragments.py``. Esta
# comprobación es la que hace que la siguiente copia sea un fallo de CI en vez
# de una divergencia futura.

#: Paquetes de producción escaneados. ``tests/`` queda fuera a propósito: un
#: test puede querer escribir el literal a mano para comprobar otra cosa (lo
#: hacen ``test_unit_universo_sql`` y las revisiones congeladas).
_PAQUETES_PRODUCCION = (
    "api",
    "db",
    "observability",
    "scheduler",
    "scraper",
    "services",
    "shared",
)

#: Los dos únicos sitios donde el literal puede aparecer.
#:
#: - ``db/sql_fragments.py`` es la definición canónica: alguien tiene que
#:   escribirla.
#: - ``db/alembic/versions/`` congela el SQL que ya corrió contra producción.
#:   Una revisión aplicada describe la base que existe, no la que el código
#:   quisiera: es append-only y **no se reescribe** aunque el fragmento cambie
#:   (por eso ``v98`` conserva su cuerpo con el universo de su día).
_EXENTOS = (
    "db/sql_fragments.py",
    "db/alembic/versions/",
)

#: Qué se persigue y por qué. El primero admite cualquier alias (``l.``,
#: ``l2.``) y también la columna desnuda: las tres grafías estaban en el repo.
_LITERALES_PROHIBIDOS: dict[str, tuple[str, str]] = {
    "universo": (
        r"COALESCE\(\s*(?:\w+\.)?analysis_universe",
        "db.sql_fragments.technology_observed_sql() (estrecho, el que sirve el "
        "índice parcial de v84) o universo_tecnologico_sql() (ancho, el de la "
        "superficie pública)",
    ),
    "duplicados": (
        r"FROM\s+licitaciones_duplicados\s+WHERE\s+status",
        "db.sql_fragments.exclude_duplicados_sql(col)",
    ),
    # T3 del plan v2 (2026-09-18): el resumen tecnológico de ``licitaciones``
    # tiene un solo escritor, el trigger de ``v136`` que lo deriva de
    # ``licitacion_tecnologia_score``. Un ``UPDATE`` directo de cualquiera de
    # las tres columnas en cualquier paquete de producción —incluido ``db/``—
    # es el clobber que ``tech_signal_merge`` existía para reparar. La ventana
    # se corta en ``WHERE`` y en 300 caracteres para no casar un ``UPDATE`` de
    # otra columna con una mención posterior en la misma sentencia o fichero.
    "tecnologia": (
        r"UPDATE\s+licitaciones(?:\s+(?:AS\s+)?\w+)?\s+SET\b"
        r"(?:(?!\bWHERE\b)[^;]){0,300}?"
        r"\b(?:tecnologia|ml_tecnologias|ml_tech_principal)\s*=",
        "filas en licitacion_tecnologia_score (el trigger de v136 deriva "
        "ml_tecnologias/ml_tech_principal/ml_proba_max); `tecnologia` solo la "
        "escribe el upsert de ingesta",
    ),
}

#: Dónde vive la definición canónica de cada categoría, para el meta-test.
#: Por defecto ``db/sql_fragments.py``; la de ``tecnologia`` no es un fragmento
#: que se importe sino la función que el trigger ejecuta, y vive en su
#: revisión (exenta del escaneo como todo ``db/alembic/versions/``).
_CANONICO_POR_CATEGORIA: dict[str, str] = {
    "tecnologia": "db/alembic/versions/v136_tecnologia_verdad_unica.py",
}


def _ficheros_de_produccion() -> list[Path]:
    """Todo ``.py`` de los paquetes de producción menos los exentos."""
    ficheros: list[Path] = []
    for paquete in _PAQUETES_PRODUCCION:
        raiz = _REPO_ROOT / paquete
        assert raiz.is_dir(), f"_PAQUETES_PRODUCCION apunta a un directorio inexistente: {paquete}"
        for path in sorted(raiz.rglob("*.py")):
            relativo = path.relative_to(_REPO_ROOT).as_posix()
            if any(relativo.startswith(exento) for exento in _EXENTOS):
                continue
            ficheros.append(path)
    return ficheros


def _copias_literales() -> list[str]:
    """``fichero:linea  (motivo)`` por cada literal prohibido encontrado."""
    hallazgos: list[str] = []
    for path in _ficheros_de_produccion():
        texto = path.read_text(encoding="utf-8")
        relativo = path.relative_to(_REPO_ROOT).as_posix()
        for nombre, (patron, remedio) in _LITERALES_PROHIBIDOS.items():
            for match in re.finditer(patron, texto):
                linea = texto.count("\n", 0, match.start()) + 1
                hallazgos.append(f"{relativo}:{linea}  [{nombre}] usá {remedio}")
    return hallazgos


#: Copias literales conocidas. Se llevó a 0 el 2026-09-03 sustituyéndolas todas
#: (16 en ``scheduler/kpi_precompute``, 1 en cada uno de
#: ``scheduler/aggregates_precompute``, ``db/domain_truth_audit``,
#: ``db/repositories/pricing``, ``db/repositories/ml_dataset`` (3) y
#: ``services/sql_fragments``). Mismo contrato que ``_PENDIENTES_MAX``: solo
#: puede bajar.
_COPIAS_LITERALES_MAX = 0


def test_los_fragmentos_compartidos_no_se_reescriben_a_mano() -> None:
    """Ningún módulo de producción vuelve a teclear el universo ni el anti-join.

    Es un ratchet, no una preferencia de estilo: los dos fragmentos tienen un
    acoplamiento invisible con algo que no está en el mismo fichero —el índice
    parcial de ``v84`` uno, el criterio de canónica el otro— y una copia rompe
    ese acoplamiento sin romper ningún resultado.
    """
    hallazgos = _copias_literales()

    assert len(hallazgos) <= _COPIAS_LITERALES_MAX, (
        f"{len(hallazgos)} copias literales, tope {_COPIAS_LITERALES_MAX}:\n  "
        + "\n  ".join(hallazgos)
        + "\n\nImportá el fragmento de db/sql_fragments.py en vez de reescribirlo."
    )


@pytest.mark.parametrize(
    ("texto", "casa"),
    [
        # Las dos grafías de los productores que T3 cortó (ml_training y el
        # merge de tecnologia_pliego, hasta 2026-09-18).
        ('"UPDATE licitaciones SET "\n"ml_tecnologias = %s, "\n"ml_proba_max = %s, "', True),
        ('"UPDATE licitaciones SET ml_tecnologias = %s, ml_proba_max = %s, "', True),
        ("UPDATE licitaciones l SET ml_tech_principal = 'SAP'", True),
        ("UPDATE licitaciones SET tecnologia = %s WHERE id_externo = %s", True),
        # La marca de «puntuada sin filas» y columnas ajenas no son el resumen.
        ("UPDATE licitaciones SET ml_proba_max = %s WHERE id_externo = %s", False),
        ("UPDATE licitaciones SET estado = 'ADJ' WHERE tecnologia = 'SAP'", False),
        ("UPDATE licitaciones SET analysis_universe = %s WHERE ml_tecnologias = %s", False),
    ],
)
def test_la_categoria_tecnologia_caza_los_productores_cortados(texto: str, casa: bool) -> None:
    patron, _remedio = _LITERALES_PROHIBIDOS["tecnologia"]
    assert bool(re.search(patron, texto)) is casa


def test_el_escaner_de_literales_mira_donde_debe() -> None:
    """Meta-test: sin esto, un path roto daría verde con el repo lleno de copias.

    Comprueba las dos mitades: que se escanean ficheros de verdad, y que los
    patrones siguen casando con el texto que persiguen (si alguien cambiara la
    grafía del fragmento canónico, el escáner dejaría de encontrar nada y no se
    enteraría nadie).
    """
    ficheros = _ficheros_de_produccion()
    assert len(ficheros) > 100, f"solo {len(ficheros)} ficheros escaneados; ¿paths mal?"

    for nombre, (patron, _remedio) in _LITERALES_PROHIBIDOS.items():
        fichero = _CANONICO_POR_CATEGORIA.get(nombre, "db/sql_fragments.py")
        canonico = (_REPO_ROOT / fichero).read_text(encoding="utf-8")
        assert re.search(patron, canonico), (
            f"el patrón [{nombre}] ya no casa con {fichero}: "
            "o cambió la definición canónica, o el escáner quedó muerto"
        )

    # Y el fichero canónico está exento de verdad: si dejara de estarlo, el
    # ratchet fallaría contra su propia definición.
    escaneados = {p.relative_to(_REPO_ROOT).as_posix() for p in ficheros}
    assert "db/sql_fragments.py" not in escaneados
