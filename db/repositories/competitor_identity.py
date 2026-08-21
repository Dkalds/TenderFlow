r"""Resolución de identidad de competidores en SQL — DISEÑO MEDIBLE, sin cablear.

Qué es esto
-----------
``services/analytics/competitors.py`` resuelve la identidad de empresa con un
union-find en pandas (``_prepare_company_identity`` / ``_connected_identity_keys``)
sobre cinco tokens por fila: grupo del maestro, grupo curado, ``empresa_id``,
NIF normalizado y nombre normalizado. Este módulo es la **misma partición
expresada en SQL**, para poder *medirla* contra la de pandas antes de
sustituirla.

Nadie lo llama todavía, y eso es deliberado: la paridad solo se puede observar
con un Postgres real (``tests/test_analytics_competitors_identity_sql.py``, que
corre en CI). Cambiar el camino por defecto sin esa medida sería cambiar el
significado de la pantalla de competidores a ciegas.

Qué significa "paridad" aquí
----------------------------
La **partición** de filas, no la etiqueta. El union-find de pandas nombra cada
grupo con el token que resultó ser raíz, que depende del orden de llegada de
las filas; aquí se nombra con ``MIN(token)`` del componente, que es
determinista. Dos etiquetas distintas para el mismo reparto de filas son
equivalentes: aguas abajo la clave solo se usa como ``groupby``. La prueba de
paridad compara particiones, no strings.

Los tres puntos donde SQL puede divergir de Python (y por eso hay tests)
-----------------------------------------------------------------------
1. **Plegado de acentos.** Python usa NFKD + descarte de combinantes;
   ``unaccent`` usa un diccionario de reemplazos. Coinciden en todo lo que
   lleva tilde, diéresis o cedilla —o sea, en el 100% de los nombres
   españoles— pero no en los caracteres que NFKD no descompone y el
   diccionario sí mapea (``Ø``→``O``, ``Æ``→``AE``) ni en las ligaduras que
   NFKD sí descompone y el diccionario no (``ﬁ``→``fi``). Son residuales en
   razón social española; el corpus de paridad los incluye para que la
   divergencia quede documentada como dato, no como sorpresa.
2. **Sintaxis de regex.** Postgres usa ARE, no PCRE: ``\b`` **no** es frontera
   de palabra sino un backspace. Las alternativas ``\bGMBH\b``… de
   ``services/normalization.py`` se traducen a ``\y`` aquí. Traducirlas mal no
   rompe nada visible: simplemente deja de plegar ``ACME GMBH`` con ``ACME``.
3. **El bucle de sufijos.** ``normalize_company`` repite el borrado de sufijos
   societarios *hasta punto fijo*; SQL no tiene bucle en una expresión, así que
   aquí está desenrollado :data:`_SUFFIX_PASSES` veces por pasada. Un nombre
   que apilase más sufijos que eso divergiría.

Coste: el riesgo que decide si esto llega a producción
------------------------------------------------------
El union-find de pandas es prácticamente lineal. El cierre transitivo de
:func:`load_competitor_identity` es cuadrático **en el tamaño del componente**: un
componente de *k* tokens genera *k²* pares. Con componentes pequeños (un grupo
empresarial real: decenas de tokens) es irrelevante; basta un "supernodo" —un
nombre normalizado degenerado, un ``empresa_id`` mal asignado— para que un
componente se coma la mitad del corpus y la consulta no termine.

Por eso :func:`identity_graph_stats` existe y hay que ejecutarla **antes** de
plantearse cambiar el camino por defecto: mide grado de token y volumen de
aristas sin construir el cierre. Si el grado máximo es alto, la respuesta no es
"optimizar la CTE" sino cambiar de algoritmo (propagación de etiqueta mínima
con pointer jumping, O(log k) rondas, que necesita un bucle en el llamador o
una función PL/pgSQL — otra decisión, otro gate).

ADR-024: este módulo **no** importa de ``services/``. La política de negocio
—qué NIFs son placeholder, qué NIFs forman un grupo curado— la inyecta el
llamador como parámetro; aquí solo vive el SQL (ADR-022).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any  # cursores/filas psycopg, igual que el resto de db/repositories

from db.database import connect_read

# ── Traducción de services/normalization.py a expresiones regulares ARE ──────
#
# Copia literal de ``_LEGAL_SUFFIXES`` con un solo cambio: ``\b`` → ``\y``.
# En ARE ``\b`` es el carácter backspace, no una frontera de palabra (ver
# docstring del módulo, punto 2). El resto de la sintaxis —``\.?``, ``\s?``,
# ``(?:...)``, clases entre corchetes— es común a PCRE y ARE.
_LEGAL_SUFFIXES_ARE: tuple[str, ...] = (
    r"S\.?\s?A\.?\s?U\.?",
    r"S\.?\s?L\.?\s?U\.?",
    r"S\.?\s?A\.?\s?S\.?",
    r"S\.?\s?L\.?\s?P\.?",
    r"S\.?\s?L\.?\s?N\.?\s?E\.?",
    r"S\.?\s?C\.?\s?P\.?",
    r"S\.?\s?A\.?",
    r"S\.?\s?L\.?",
    r"S\.?\s?C\.?",
    r"S\.?\s?COOP\.?",
    r"SOCIEDAD\s+AN[OÓ]NIMA(\s+UNIPERSONAL)?",
    r"SOCIEDAD\s+LIMITADA(\s+UNIPERSONAL)?",
    r"SOCIEDAD\s+COOPERATIVA",
    r"COMPA[ÑN][ÍI]A",
    r"\yGMBH\y",
    r"\yLTD\y",
    r"\yLLC\y",
    r"\yINC\y",
    r"\yAG\y",
    r"\yBV\y",
    r"\yN\.?V\.?",
    r"\yU\.?T\.?E\.?",
)

#: Mismo anclaje que ``services.normalization._SUFFIX_RE``. Se escribe con
#: clases POSIX (``[[:space:]]``) en lugar de ``\s`` dentro de los corchetes
#: para no depender de cómo interpreta ARE un escape de clase anidado.
SUFFIX_RE_ARE: str = r"(?:^|[[:space:],.-])(" + "|".join(_LEGAL_SUFFIXES_ARE) + r")[[:space:]]*$"

#: Cuántas veces se desenrolla el ``while True`` de ``normalize_company`` en
#: cada una de sus dos pasadas. Cuatro cubre cualquier razón social observada
#: (``"… SOCIEDAD LIMITADA UNIPERSONAL, S.L."`` necesita dos); el test de
#: paridad incluye casos apilados para que quede comprobado y no supuesto.
_SUFFIX_PASSES = 4

#: ``[^\w\s]`` de Python con ``re.UNICODE``. ``[:alnum:]`` sigue la colación de
#: la base: en una base UTF-8 cubre letras acentuadas, que a esta altura de la
#: cadena ya no existen porque ``unaccent`` corrió antes.
_PUNCT_RE_ARE = r"[^[:alnum:]_[:space:]]"
_WS_RE_ARE = r"[[:space:]]+"


def _quote_ident(name: str) -> str:
    """Cita un identificador SQL venido del catálogo."""
    return '"' + name.replace('"', '""') + '"'


def unaccent_function(conn: Any) -> str:
    """Nombre CUALIFICADO de ``unaccent``, resuelto por catálogo.

    No se asume ``public``. v87 crea la extensión sin cláusula ``SCHEMA`` —el
    patrón de v50/v56— y eso significa que cae donde el ``search_path`` del rol
    que migra diga: ``public`` en un Postgres local, ``extensions`` por convenio
    en Supabase. La app **no** fija ``search_path`` por conexión en producción,
    así que llamar a ``unaccent(...)`` a pelo es una bomba de relojería: si la
    extensión acabó en ``extensions``, el analítico entero muere con
    ``function unaccent(text) does not exist``. Resolver el schema por catálogo
    y cualificar la llamada elimina esa dependencia por completo.
    """
    row = conn.execute(
        "SELECT n.nspname FROM pg_extension e "
        "JOIN pg_namespace n ON n.oid = e.extnamespace "
        "WHERE e.extname = 'unaccent'"
    ).fetchone()
    if row is None:
        raise RuntimeError(
            "La extensión 'unaccent' no está instalada: falta aplicar "
            "v87_unaccent_extension antes de usar este módulo."
        )
    return _quote_ident(str(row[0])) + ".unaccent"


def normalize_nif_sql(expr: str) -> str:
    """SQL equivalente a ``services.normalization.normalize_nif``.

    Ojo con lo que **no** borra: la clase es ``[\\s.-]``, sin ``/``. Por eso
    ``"N/A"`` sobrevive como ``"N/A"`` y hay que filtrarlo por lista de
    placeholders en vez de confiar en que la normalización lo aniquile.
    """
    return f"NULLIF(upper(regexp_replace({expr}, '[[:space:].-]', '', 'g')), '')"


def normalize_company_lateral(source: str, alias: str, unaccent_fn: str) -> str:
    """Cadena de ``CROSS JOIN LATERAL`` equivalente a ``normalize_company``.

    Se emite como laterales encadenados y no como una expresión anidada por
    legibilidad: son once etapas, y anidarlas produce un paréntesis de 6 KB
    imposible de revisar en un diff. El resultado es ``<alias>_out.v``.

    ``unaccent_fn`` llega cualificado desde :func:`unaccent_function`.

    Requiere que ``pat(re)`` y ``source`` ya estén en el ``FROM``.
    """
    parts: list[str] = []
    # Espejo exacto de las dos primeras líneas de normalize_company:
    # ``name.strip().upper()`` y luego ``_strip_accents(s).upper()``.
    parts.append(
        f"CROSS JOIN LATERAL (SELECT upper({unaccent_fn}(upper(btrim({source})))) AS v) {alias}_0"
    )
    step = 0
    # Pasada 1: borra sufijos societarios ANTES de tocar la puntuación, y
    # recorta " ,.-" en cada vuelta (el ``.strip(" ,.-")`` del bucle Python).
    for _ in range(_SUFFIX_PASSES):
        prev, step = step, step + 1
        parts.append(
            f"CROSS JOIN LATERAL (SELECT btrim(regexp_replace({alias}_{prev}.v, "
            f"pat.re, '', 'gi'), ' ,.-') AS v) {alias}_{step}"
        )
    # Puntuación → espacio y colapso de blancos.
    prev, step = step, step + 1
    parts.append(
        f"CROSS JOIN LATERAL (SELECT btrim(regexp_replace(regexp_replace("
        f"{alias}_{prev}.v, '{_PUNCT_RE_ARE}', ' ', 'g'), "
        f"'{_WS_RE_ARE}', ' ', 'g')) AS v) {alias}_{step}"
    )
    # Pasada 2: quitar la puntuación destapa sufijos que la pasada 1 no veía
    # ("ACME, S.L." → "ACME SL"). Aquí el recorte es solo de blancos.
    for _ in range(_SUFFIX_PASSES):
        prev, step = step, step + 1
        parts.append(
            f"CROSS JOIN LATERAL (SELECT btrim(regexp_replace({alias}_{prev}.v, "
            f"pat.re, '', 'gi')) AS v) {alias}_{step}"
        )
    parts.append(
        f"CROSS JOIN LATERAL (SELECT NULLIF(btrim(regexp_replace("
        f"{alias}_{step}.v, '{_WS_RE_ARE}', ' ', 'g')), '') AS v) {alias}_out"
    )
    return "\n".join(parts)


# ── Consulta de identidad ────────────────────────────────────────────────────

_EFFECTIVE_NAME = "COALESCE(NULLIF(btrim(e.nombre_canonico), ''), NULLIF(btrim(a.nombre), ''))"
_EFFECTIVE_NIF = "COALESCE(NULLIF(btrim(e.nif_canonico), ''), NULLIF(btrim(a.nif), ''))"


def components_sql(*, tokens_cte: str = "tokens") -> str:
    """CTEs de componentes conexos sobre una relación ``(row_id, tok)``.

    Es el equivalente declarativo del disjoint-set de
    ``_connected_identity_keys``: dos tokens que aparecen en la misma fila
    están unidos, y el componente de una fila es el mínimo token alcanzable
    desde cualquiera de los suyos.

    El ``UNION`` (no ``UNION ALL``) del término recursivo es lo que hace que
    esto **termine**: deduplica pares ya vistos, así que el ciclo
    ``A→B→A`` se agota en vez de girar para siempre. El precio es el cierre
    completo —*k²* pares por componente de *k* tokens—, que es exactamente el
    riesgo que mide :func:`identity_graph_stats`.

    Se emite por separado del resto de la consulta para poder alimentarlo con
    una relación de tokens sintética desde el test de paridad, sin pasar por
    ``adjudicaciones``: el algoritmo se verifica aislado de los joins.
    """
    return f"""
nodes AS (SELECT DISTINCT tok FROM {tokens_cte}),
edges AS (
    SELECT DISTINCT t1.tok AS src, t2.tok AS dst
    FROM {tokens_cte} t1
    JOIN {tokens_cte} t2 ON t2.row_id = t1.row_id AND t2.tok <> t1.tok
),
reach(src, dst) AS (
        SELECT tok, tok FROM nodes
    UNION
        SELECT r.src, e.dst FROM reach r JOIN edges e ON e.src = r.dst
),
componentes AS (SELECT src AS tok, MIN(dst) AS comp FROM reach GROUP BY src),
por_fila AS (
    SELECT t.row_id, MIN(cp.comp) AS grupo_key
    FROM {tokens_cte} t JOIN componentes cp ON cp.tok = t.tok
    GROUP BY t.row_id
)"""


def tokens_sql(*, base_cte: str = "base", curated_cte: str = "curated") -> str:
    """Los cinco tokens de identidad por fila, tal como los emite pandas.

    ``base_cte`` aporta ``(row_id, grupo_id, empresa_id, nif_key, name_key)``
    ya normalizados; ``curated_cte`` aporta ``(nif, grupo_key)``. El ``ord`` no
    influye en la partición (ver docstring del módulo) y se conserva solo para
    poder depurar qué señal unió dos filas.

    Igual que :func:`components_sql`, se emite aparte para que el test de
    paridad pueda alimentarlo con un ``base`` literal y ejercitar **este** SQL
    —no una copia— sobre los mismos casos que cubren los tests de pandas.
    """
    return f"""
tokens AS (
    SELECT b.row_id, t.ord, t.tok
    FROM {base_cte} b
    LEFT JOIN {curated_cte} c ON c.nif = b.nif_key
    CROSS JOIN LATERAL (VALUES
        (1, CASE WHEN b.grupo_id   IS NOT NULL THEN 'grupo:master:'  || b.grupo_id::text END),
        (2, CASE WHEN c.grupo_key  IS NOT NULL THEN 'grupo:curated:' || c.grupo_key END),
        (3, CASE WHEN b.empresa_id IS NOT NULL THEN 'empresa:'       || b.empresa_id::text END),
        (4, CASE WHEN b.nif_key    IS NOT NULL THEN 'nif:'           || b.nif_key END),
        (5, CASE WHEN b.name_key   IS NOT NULL THEN 'nombre:'        || b.name_key END)
    ) AS t(ord, tok)
    WHERE t.tok IS NOT NULL
)"""


#: Cola común: una fila sin ningún token es un singleton, igual que el
#: ``fila:<posicion>`` que inventa ``_connected_identity_keys``.
IDENTITY_TAIL_SELECT = """
SELECT b.row_id,
       COALESCE(f.grupo_key, 'fila:' || b.row_id::text) AS grupo_key
FROM base b
LEFT JOIN por_fila f ON f.row_id = b.row_id
ORDER BY b.row_id
"""


def _identity_sql(unaccent_fn: str, *, where: str) -> str:
    """Arma la consulta completa de partición de identidad."""
    name_chain = normalize_company_lateral(_EFFECTIVE_NAME, "nom", unaccent_fn)
    nif_expr = normalize_nif_sql(_EFFECTIVE_NIF)
    return f"""
WITH RECURSIVE
pat AS (SELECT %s::text AS re),
placeholders AS (SELECT unnest(%s::text[]) AS nif),
curated AS (
    SELECT * FROM unnest(%s::text[], %s::text[]) AS c(nif, grupo_key)
),
base AS (
    SELECT a.id                                       AS row_id,
           e.grupo_id                                 AS grupo_id,
           a.empresa_id                               AS empresa_id,
           nom_out.v                                  AS name_key,
           CASE WHEN nifk.v IN (SELECT nif FROM placeholders) THEN NULL
                ELSE nifk.v END                       AS nif_key
    FROM adjudicaciones a
    -- `l` no aporta columnas a la identidad; está para que `where` pueda
    -- filtrar por tecnologia/estado/importe como hace load_for_competitors.
    LEFT JOIN licitaciones l ON l.id_externo = a.licitacion_id
    LEFT JOIN empresas e ON e.empresa_id = a.empresa_id
    CROSS JOIN pat
    CROSS JOIN LATERAL (SELECT {nif_expr} AS v) nifk
{name_chain}
    WHERE {where}
),
{tokens_sql()},
{components_sql()}
{IDENTITY_TAIL_SELECT}"""


def load_competitor_identity(
    *,
    placeholder_nifs: Sequence[str],
    curated_groups: Mapping[str, str],
    where: str = "TRUE",
    where_params: Sequence[Any] | None = None,
) -> list[dict[str, Any]]:
    """Partición de identidad calculada íntegramente en Postgres.

    Devuelve una fila por ``adjudicaciones.id`` con su ``grupo_key``. Es la
    contrapartida SQL de ``_connected_identity_keys``; **no está cableada** al
    analítico, existe para que el test de paridad pueda compararlas.

    ``placeholder_nifs`` y ``curated_groups`` son política de negocio del
    servicio llamador (``_INVALID_NIF_KEYS`` y ``_CURATED_GROUPS_BY_NIF``): van
    como parámetros porque ADR-024 prohíbe que ``db/`` los importe.

    ``where`` se concatena tal cual: es un fragmento de código del llamador,
    nunca input de usuario, y sus valores viajan en ``where_params``.
    """
    nifs = list(curated_groups.keys())
    keys = [curated_groups[n] for n in nifs]
    params: list[Any] = [
        SUFFIX_RE_ARE,
        list(placeholder_nifs),
        nifs,
        keys,
        *(where_params or []),
    ]
    with connect_read() as c:
        sql = _identity_sql(unaccent_function(c), where=where)
        cur = c.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def _graph_stats_sql(unaccent_fn: str, *, where: str) -> str:
    name_chain = normalize_company_lateral(_EFFECTIVE_NAME, "nom", unaccent_fn)
    nif_expr = normalize_nif_sql(_EFFECTIVE_NIF)
    return f"""
WITH
pat AS (SELECT %s::text AS re),
base AS (
    SELECT a.id AS row_id, e.grupo_id AS grupo_id, a.empresa_id AS empresa_id,
           nom_out.v AS name_key, nifk.v AS nif_key
    FROM adjudicaciones a
    -- `l` no aporta columnas a la identidad; está para que `where` pueda
    -- filtrar por tecnologia/estado/importe como hace load_for_competitors.
    LEFT JOIN licitaciones l ON l.id_externo = a.licitacion_id
    LEFT JOIN empresas e ON e.empresa_id = a.empresa_id
    CROSS JOIN pat
    CROSS JOIN LATERAL (SELECT {nif_expr} AS v) nifk
{name_chain}
    WHERE {where}
),
tokens AS (
    SELECT b.row_id, t.tok FROM base b
    CROSS JOIN LATERAL (VALUES
        (CASE WHEN b.grupo_id   IS NOT NULL THEN 'grupo:master:' || b.grupo_id::text END),
        (CASE WHEN b.empresa_id IS NOT NULL THEN 'empresa:' || b.empresa_id::text END),
        (CASE WHEN b.nif_key    IS NOT NULL THEN 'nif:' || b.nif_key END),
        (CASE WHEN b.name_key   IS NOT NULL THEN 'nombre:' || b.name_key END)
    ) AS t(tok)
    WHERE t.tok IS NOT NULL
),
grados AS (SELECT tok, COUNT(*) AS filas FROM tokens GROUP BY tok)
SELECT (SELECT COUNT(*) FROM base) AS filas,
       (SELECT COUNT(*) FROM grados) AS tokens_distintos,
       (SELECT COALESCE(MAX(filas), 0) FROM grados) AS grado_maximo
"""


def identity_graph_stats(
    *,
    where: str = "TRUE",
    where_params: Sequence[Any] | None = None,
) -> dict[str, int]:
    """Pre-vuelo obligatorio antes de plantearse cambiar el camino por defecto.

    Mide el grafo de identidad **sin** construir el cierre transitivo: número
    de filas, de tokens distintos y grado máximo de un token (cuántas filas
    comparten la misma señal). El cierre es cuadrático en el tamaño del
    componente, así que un grado máximo de seis cifras significa que
    :func:`load_competitor_identity` no va a terminar en producción y que hay
    que cambiar de algoritmo, no de índice.
    """
    with connect_read() as c:
        sql = _graph_stats_sql(unaccent_function(c), where=where)
        row = c.execute(sql, [SUFFIX_RE_ARE, *(where_params or [])]).fetchone()
    if row is None:  # pragma: no cover - un SELECT agregado siempre trae fila
        return {"filas": 0, "tokens_distintos": 0, "grado_maximo": 0}
    return {"filas": int(row[0]), "tokens_distintos": int(row[1]), "grado_maximo": int(row[2])}
