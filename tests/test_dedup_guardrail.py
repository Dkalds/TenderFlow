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

Granularidad: por función. Una función en un módulo escaneado cuyo cuerpo
referencia ``FROM/JOIN licitaciones`` o ``adjudicaciones`` debe contener una
llamada textual a ``exclude_duplicados_sql``. Las excepciones legítimas (queries
que deliberadamente no deduplican) se declaran en ``_ALLOWLIST`` con su
justificación.

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
from pathlib import Path

# Directorios cuyas queries analíticas deben respetar el dedupe.
_SCANNED_DIRS = ("services/competitive", "services/ml")

# Módulos sueltos de ``db/`` que han recibido SQL analítico migrado desde
# ``services/``. Ver el docstring: esta lista crece con cada ola del ratchet.
_SCANNED_FILES = (
    "db/repositories/renovaciones.py",
    "db/repositories/adjudicaciones.py",
    "db/repositories/ml_dataset.py",
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


def _module_guard_names(tree: ast.Module, source: str) -> set[str]:
    """Nombres del módulo que, al referenciarse, ya aportan el dedupe.

    Son de tres clases, y hacen falta las tres porque el escáner es textual y la
    cláusula no siempre está escrita dentro de la función que consulta:

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
    """
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            valor_literal = (
                isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                and _GUARD_TABLE in node.value.value
            )
            # `ast.get_source_segment` y no un `ast.Call` con `func.id`: la
            # llamada puede venir envuelta (concatenada con otro fragmento,
            # dentro de un `f"..."`), y lo que importa es que el nombre del
            # helper aparezca en la expresión que produce la constante.
            valor_compuesto = _GUARD_CALL in (ast.get_source_segment(source, node.value) or "")
            if valor_literal or valor_compuesto:
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            segment = ast.get_source_segment(source, node) or ""
            if _GUARD_CALL in segment or _GUARD_TABLE in segment:
                names.add(node.name)
    return names


def _iter_functions() -> list[tuple[str, str, str, set[str]]]:
    """(qualname, source, file, nombres-guarda-del-módulo) por cada función."""
    out: list[tuple[str, str, str, set[str]]] = []
    for py_file in _scanned_paths():
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
        guard_names = _module_guard_names(tree, source)
        module = py_file.stem
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                segment = ast.get_source_segment(source, node)
                if segment is None:
                    continue
                out.append((f"{module}.{node.name}", segment, str(py_file), guard_names))
    return out


def _is_guarded(segment: str, guard_names: set[str]) -> bool:
    """La query excluye duplicados: por llamada, por subconsulta inline o por helper.

    ``_GUARD_TABLE in segment`` cubre las queries que escriben el ``NOT IN
    (SELECT ... FROM licitaciones_duplicados ...)`` a mano dentro del SQL, sin
    pasar por el helper — ``ml_dataset.licitaciones_abiertas`` lo hace así y una
    versión anterior de este escáner la marcaba como violación siendo correcta.
    """
    return (
        _GUARD_CALL in segment
        or _GUARD_TABLE in segment
        or any(name in segment for name in guard_names)
    )


def test_analytical_queries_exclude_duplicados() -> None:
    """Toda función que consulta las tablas canónicas debe excluir duplicados."""
    violations: list[str] = []
    for qualname, segment, file, guard_names in _iter_functions():
        if qualname in _ALLOWLIST:
            continue
        if _TABLE_REF.search(segment) and not _is_guarded(segment, guard_names):
            violations.append(f"{qualname}  ({file})")

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
    assert any(_TABLE_REF.search(seg) for _, seg, _, _ in funcs), (
        "Ninguna función referencia licitaciones/adjudicaciones; regex o paths rotos."
    )


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
    desactivado la comprobación. Este test falla si alguien vuelve a dejar la
    lista sin los módulos que sí tienen SQL analítico.
    """
    escaneados = {str(p) for p in _scanned_paths()}
    for rel_file in _SCANNED_FILES:
        assert str(_REPO_ROOT / rel_file) in escaneados, f"{rel_file} no se escanea"

    # Y el idioma de db/ (constante de módulo) se reconoce de verdad: si
    # `_module_guard_names` dejara de detectarlo, las funciones de ml_dataset
    # pasarían a "violación" y alguien las metería en _ALLOWLIST por error.
    ml_dataset = _REPO_ROOT / "db/repositories/ml_dataset.py"
    source = ml_dataset.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(ml_dataset))
    assert _module_guard_names(tree, source), (
        "No se detectó ninguna constante de dedupe en ml_dataset.py; "
        "¿cambió el idioma de db/ o la subquery?"
    )

    # Y el reconocimiento por helper: `_adj_filter_conditions` siembra la
    # cláusula para las cuatro consultas de UTE. Si dejara de detectarse, las
    # cuatro pasarían a "violación" y alguien las metería en _ALLOWLIST en vez
    # de darse cuenta de que el guardrail es el que se rompió.
    adj = _REPO_ROOT / "db/repositories/adjudicaciones.py"
    adj_source = adj.read_text(encoding="utf-8")
    adj_names = _module_guard_names(ast.parse(adj_source, filename=str(adj)), adj_source)
    assert "_adj_filter_conditions" in adj_names, (
        "El helper compartido de las consultas UTE ya no aporta el dedupe; "
        "o se le quitó la cláusula, o el detector dejó de verla."
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


def test_el_escaner_de_literales_mira_donde_debe() -> None:
    """Meta-test: sin esto, un path roto daría verde con el repo lleno de copias.

    Comprueba las dos mitades: que se escanean ficheros de verdad, y que los
    patrones siguen casando con el texto que persiguen (si alguien cambiara la
    grafía del fragmento canónico, el escáner dejaría de encontrar nada y no se
    enteraría nadie).
    """
    ficheros = _ficheros_de_produccion()
    assert len(ficheros) > 100, f"solo {len(ficheros)} ficheros escaneados; ¿paths mal?"

    canonico = (_REPO_ROOT / "db/sql_fragments.py").read_text(encoding="utf-8")
    for nombre, (patron, _remedio) in _LITERALES_PROHIBIDOS.items():
        assert re.search(patron, canonico), (
            f"el patrón [{nombre}] ya no casa con db/sql_fragments.py: "
            "o cambió el fragmento canónico, o el escáner quedó muerto"
        )

    # Y el fichero canónico está exento de verdad: si dejara de estarlo, el
    # ratchet fallaría contra su propia definición.
    escaneados = {p.relative_to(_REPO_ROOT).as_posix() for p in ficheros}
    assert "db/sql_fragments.py" not in escaneados
