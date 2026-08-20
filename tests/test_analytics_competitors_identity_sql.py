"""Paridad SQL↔pandas de la resolución de identidad de competidores.

``db/repositories/competitor_identity.py`` reexpresa en SQL lo que
``services/analytics/competitors.py`` hace hoy en pandas (union-find sobre
cinco tokens de identidad). Este fichero es la **medida** de esa equivalencia:
mientras no pase entero, la versión SQL no se cablea.

Necesita Postgres real (fixture ``tmp_db`` ⇒ marcado ``integration``
automáticamente por ``conftest``), porque lo que se está verificando es
justamente el comportamiento del motor: ``unaccent``, el dialecto ARE de las
expresiones regulares y la terminación del CTE recursivo. Nada de eso se puede
simular en un test unitario, y por eso los 15 tests de
``tests/test_analytics_competitors.py`` —que mockean la carga y viven en
pandas— no sirven como prueba de paridad: cubren el resultado de un algoritmo,
no su traducción.

Se comparan **particiones**, no etiquetas: el union-find de pandas nombra cada
grupo con el token que quedó de raíz (depende del orden de llegada) y el SQL
con ``MIN(token)``. Repartir las filas igual es la propiedad que importa; el
nombre del grupo lo elige después ``_preferred_names``.

Cobertura, en cuatro capas independientes para que un fallo diga *dónde*:
  1. ``normalize_company`` traducido a SQL (acentos + sufijos societarios).
  2. ``normalize_nif`` traducido a SQL.
  3. tokens + componentes conexos, alimentados con un ``base`` literal.
  4. la consulta entera contra ``adjudicaciones`` reales.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd
import pytest

from db.database import connect_read
from db.repositories.competitor_identity import (
    IDENTITY_TAIL_SELECT,
    SUFFIX_RE_ARE,
    components_sql,
    normalize_company_lateral,
    normalize_nif_sql,
    tokens_sql,
    unaccent_function,
)
from services.analytics.competitors import (
    _CURATED_GROUPS_BY_NIF,
    _GROUP_KEY,
    _connected_identity_keys,
    _prepare_company_identity,
)
from services.normalization import normalize_company, normalize_nif

pytestmark = pytest.mark.usefixtures("tmp_db")


# ── Utilidades ───────────────────────────────────────────────────────────────


def _particion(labels: Sequence[Any]) -> frozenset[frozenset[int]]:
    """Reparto de posiciones en grupos, ignorando cómo se llame cada grupo."""
    grupos: dict[Any, set[int]] = {}
    for position, label in enumerate(labels):
        grupos.setdefault(label, set()).add(position)
    return frozenset(frozenset(miembros) for miembros in grupos.values())


def _sql_normalize_company(nombres: Sequence[str]) -> list[str | None]:
    with connect_read() as c:
        cadena = normalize_company_lateral("src.raw", "nom", unaccent_function(c))
        sql = (
            # S608 no aplica: `cadena` la genera db/, sin datos; el corpus va con %s.
            "WITH pat AS (SELECT %s::text AS re), "  # noqa: S608
            "src AS (SELECT * FROM unnest(%s::text[]) WITH ORDINALITY AS s(raw, pos)) "
            "SELECT nom_out.v FROM src CROSS JOIN pat\n" + cadena + "\nORDER BY src.pos"
        )
        rows = c.execute(sql, [SUFFIX_RE_ARE, list(nombres)]).fetchall()
    return [row[0] for row in rows]


def _sql_normalize_nif(nifs: Sequence[str]) -> list[str | None]:
    expr = normalize_nif_sql("src.raw")
    sql = (
        # S608 no aplica: `expr` la genera db/, sin datos; el corpus va con %s.
        "WITH src AS (SELECT * FROM unnest(%s::text[]) WITH ORDINALITY AS s(raw, pos)) "  # noqa: S608
        f"SELECT {expr} FROM src ORDER BY src.pos"
    )
    with connect_read() as c:
        rows = c.execute(sql, [list(nifs)]).fetchall()
    return [row[0] for row in rows]


# ── 1. normalize_company ─────────────────────────────────────────────────────

# Razones sociales reales del corpus (las mismas que ejercitan los 15 tests de
# pandas) más los tres mecanismos que la traducción a SQL puede romper por su
# cuenta: tildes/ñ/ü (unaccent), sufijos anglosajones (``\b`` de PCRE, que en
# ARE es un backspace y hay que escribir ``\y``) y sufijos apilados (el bucle
# hasta punto fijo, desenrollado un número finito de veces).
_NOMBRES_REALISTAS = (
    "ACCENTURE S.L.",
    "Accenture SLU",
    "Salesforce Iberia",
    "Oracle Ibérica",
    "Indra Sistemas",
    "INDRA SISTEMAS, S.A.",
    "MINSAIT BUSINESS CONSULTING, S.L.",
    "ACME, S.L.",
    "ACME SA",
    "Empresa Norte, S.L.",
    "Empresa Sur, S.L.",
    "North Consulting, S.L.",
    "North Advisory, S.A.",
    "DELOITTE CONSULTING, S.L.U.",
    "Deloitte Technology & Transformation S-L.U.",
    "Deloitte Advisory, S.L.",
    "Telefónica Soluciones, S.A.U.",
    "COMPAÑÍA ESPAÑOLA DE SEGUROS",
    "Construcciones Muñoz e Hijos, Sociedad Limitada Unipersonal",
    "Grüne Energie GmbH",
    "Setúbal Consultores LTD",
    "ACME S.A. S.L.",
    "SERVICIOS INTEGRALES, S.COOP.",
    "  espacios   colapsados  , s.l. ",
    "U.T.E. Norte Sur",
)

# Caracteres donde NFKD (Python) y el diccionario de unaccent (Postgres) NO
# tienen por qué coincidir: ``Ø``/``Æ`` no se descomponen en NFKD pero el
# diccionario sí los mapea, y la ligadura ``ﬁ`` es al revés. Son residuales en
# razón social española, así que no se exige igualdad: se exige que la
# divergencia sea *inofensiva* (una clave estable, no un NULL ni un error).
_NOMBRES_EXOTICOS = (
    "Ørsted Energía, S.L.",
    "Æther Consulting SA",
    "Oﬁcina Técnica del Norte, S.L.",
)


def test_normalize_company_sql_replica_a_python():
    esperado = [normalize_company(nombre) for nombre in _NOMBRES_REALISTAS]
    obtenido = _sql_normalize_company(_NOMBRES_REALISTAS)
    divergentes = {
        nombre: (py, sql)
        for nombre, py, sql in zip(_NOMBRES_REALISTAS, esperado, obtenido, strict=True)
        if py != sql
    }
    assert divergentes == {}


def test_normalize_company_divergencias_de_unaccent_son_inofensivas():
    obtenido = _sql_normalize_company(_NOMBRES_EXOTICOS)
    # Lo que no puede pasar: que el motor devuelva NULL (la fila perdería su
    # token de nombre y dejaría de agrupar) o una cadena vacía.
    assert all(valor for valor in obtenido)
    # Idempotencia: normalizar dos veces da lo mismo, igual que en Python.
    assert _sql_normalize_company([str(v) for v in obtenido]) == obtenido


# ── 2. normalize_nif ─────────────────────────────────────────────────────────

_NIFS = (
    "A-28599033",
    "a28599033",
    " B11111111 ",
    "B 8169 0471",
    "N/A",
    "n/a",
    "NO CONSTA",
    "000-000-000",
    "",
    "   ",
)


def test_normalize_nif_sql_replica_a_python():
    esperado = [normalize_nif(nif) for nif in _NIFS]
    assert _sql_normalize_nif(_NIFS) == esperado


def test_normalize_nif_no_borra_la_barra_del_placeholder():
    """``N/A`` sobrevive a la normalización: por eso hace falta la lista negra.

    Si algún día la clase de caracteres incluyera ``/``, ``N/A`` se convertiría
    en ``NA`` —que también está en ``_INVALID_NIF_KEYS``, así que seguiría
    filtrándose— pero ``ES/2024`` se convertiría en ``ES2024`` y dejaría de ser
    el mismo NIF que ``ES-2024``. Este test congela el comportamiento actual.
    """
    assert _sql_normalize_nif(["N/A"]) == ["N/A"]


# ── 3. Tokens + componentes conexos ──────────────────────────────────────────

# Cada escenario reproduce uno de los casos que cubren los tests de pandas,
# expresado ya en las cuatro señales normalizadas que entran al union-find.
_ESCENARIOS: dict[str, list[dict[str, Any]]] = {
    # Dos variantes de nombre crudo colapsadas por el maestro (empresa_id 10).
    "maestro_por_empresa_id": [
        {"grupo_id": None, "empresa_id": "10", "nif_key": "A-CANON", "name_key": "ACCENTURE"},
        {"grupo_id": None, "empresa_id": "10", "nif_key": "A-CANON", "name_key": "ACCENTURE"},
        {"grupo_id": None, "empresa_id": "20", "nif_key": "B-CANON", "name_key": "SALESFORCE"},
        {"grupo_id": None, "empresa_id": "30", "nif_key": "C-CANON", "name_key": "ORACLE"},
    ],
    # Nombres distintos unidos solo por el NIF (Indra ↔ Minsait).
    "solo_por_nif": [
        {
            "grupo_id": None,
            "empresa_id": None,
            "nif_key": "A28599033",
            "name_key": "INDRA SISTEMAS",
        },
        {
            "grupo_id": None,
            "empresa_id": None,
            "nif_key": "A28599033",
            "name_key": "MINSAIT BUSINESS CONSULTING",
        },
    ],
    # Mismo nombre normalizado, NIFs distintos: se unen igualmente.
    "solo_por_nombre": [
        {"grupo_id": None, "empresa_id": "40", "nif_key": "B11111111", "name_key": "ACME"},
        {"grupo_id": None, "empresa_id": "41", "nif_key": "A22222222", "name_key": "ACME"},
    ],
    # NIF placeholder ya filtrado (llega como None): NO deben unirse.
    "placeholder_no_une": [
        {"grupo_id": None, "empresa_id": None, "nif_key": None, "name_key": "EMPRESA NORTE"},
        {"grupo_id": None, "empresa_id": None, "nif_key": None, "name_key": "EMPRESA SUR"},
    ],
    # Grupo empresarial del maestro.
    "grupo_del_maestro": [
        {
            "grupo_id": "7",
            "empresa_id": "50",
            "nif_key": "B11111111",
            "name_key": "NORTH CONSULTING",
        },
        {"grupo_id": "7", "empresa_id": "51", "nif_key": "A22222222", "name_key": "NORTH ADVISORY"},
    ],
    # Grupo curado por NIF (Deloitte): tres entidades legales distintas.
    "grupo_curado_deloitte": [
        {"grupo_id": None, "empresa_id": "66", "nif_key": "B81690471", "name_key": "DELOITTE"},
        {
            "grupo_id": None,
            "empresa_id": "551",
            "nif_key": "B16436099",
            "name_key": "DELOITTE TECHNOLOGY TRANSFORMATION",
        },
        {
            "grupo_id": None,
            "empresa_id": "116",
            "nif_key": "B86466448",
            "name_key": "DELOITTE ADVISORY",
        },
    ],
    # Fila sin ninguna señal: singleton, y no arrastra a las demás.
    "fila_sin_señales": [
        {"grupo_id": None, "empresa_id": None, "nif_key": None, "name_key": None},
        {"grupo_id": None, "empresa_id": None, "nif_key": None, "name_key": None},
        {"grupo_id": None, "empresa_id": "9", "nif_key": None, "name_key": "SOLA"},
    ],
    # Cadena transitiva: A-B por NIF, B-C por nombre => los tres en un grupo.
    "cadena_transitiva": [
        {"grupo_id": None, "empresa_id": None, "nif_key": "X1", "name_key": "ALFA"},
        {"grupo_id": None, "empresa_id": None, "nif_key": "X1", "name_key": "BETA"},
        {"grupo_id": None, "empresa_id": None, "nif_key": "X2", "name_key": "BETA"},
    ],
}


def _pandas_particion(filas: list[dict[str, Any]]) -> frozenset[frozenset[int]]:
    """Partición según ``_connected_identity_keys``, la implementación actual."""
    df = pd.DataFrame(
        {
            "_master_group_key": [
                f"master:{f['grupo_id']}" if f["grupo_id"] is not None else None for f in filas
            ],
            "_curated_group_key": [
                f"curated:{_CURATED_GROUPS_BY_NIF[f['nif_key']][0]}"
                if f["nif_key"] in _CURATED_GROUPS_BY_NIF
                else None
                for f in filas
            ],
            "_empresa_id_key": [f["empresa_id"] for f in filas],
            "_nif_key": [f["nif_key"] for f in filas],
            "_name_key": [f["name_key"] for f in filas],
        }
    )
    return _particion(_connected_identity_keys(df))


def _sql_particion(filas: list[dict[str, Any]]) -> frozenset[frozenset[int]]:
    """Partición según ``tokens_sql`` + ``components_sql``, el SQL de producción."""
    sql = (
        # S608 no aplica: todo lo interpolado sale de db/; los datos van con %s.
        "WITH RECURSIVE base AS ("  # noqa: S608
        "SELECT * FROM unnest(%s::bigint[], %s::text[], %s::text[], %s::text[], %s::text[]) "
        "AS b(row_id, grupo_id, empresa_id, nif_key, name_key)),"
        " curated AS (SELECT * FROM unnest(%s::text[], %s::text[]) AS c(nif, grupo_key)),"
        f"{tokens_sql()},{components_sql()}{IDENTITY_TAIL_SELECT}"
    )
    nifs_curados = list(_CURATED_GROUPS_BY_NIF)
    params: list[Any] = [
        list(range(len(filas))),
        [f["grupo_id"] for f in filas],
        [f["empresa_id"] for f in filas],
        [f["nif_key"] for f in filas],
        [f["name_key"] for f in filas],
        nifs_curados,
        [_CURATED_GROUPS_BY_NIF[nif][0] for nif in nifs_curados],
    ]
    with connect_read() as c:
        rows = c.execute(sql, params).fetchall()
    # `IDENTITY_TAIL_SELECT` ordena por row_id, que aquí es la posición.
    return _particion([row[1] for row in rows])


@pytest.mark.parametrize("escenario", sorted(_ESCENARIOS))
def test_componentes_sql_reparten_como_el_union_find(escenario: str):
    filas = _ESCENARIOS[escenario]
    assert _sql_particion(filas) == _pandas_particion(filas)


# ── 4. La consulta entera contra tablas reales ───────────────────────────────


def _insertar(lic_id: str, nombre: str, nif: str | None) -> None:
    from db.upsert import (
        Adjudicacion,
        Licitacion,
        replace_adjudicaciones_batch,
        upsert_licitaciones,
    )

    upsert_licitaciones([Licitacion(id_externo=lic_id, titulo=f"Contrato {lic_id}")])
    adj = Adjudicacion(licitacion_id=lic_id, nombre=nombre, nif=nif, importe_adjudicado=1000.0)
    _total, _dropped, failed = replace_adjudicaciones_batch({lic_id: [adj]})
    assert failed == 0


_FILAS_E2E = (
    ("CI-1", "INDRA SISTEMAS, S.A.", "A-28599033"),
    ("CI-2", "MINSAIT BUSINESS CONSULTING, S.L.", "A28599033"),
    ("CI-3", "Empresa Norte, S.L.", "N/A"),
    ("CI-4", "Empresa Sur, S.L.", "N/A"),
)


def test_consulta_completa_reparte_como_prepare_company_identity(tmp_db):
    from db.repositories.competitor_identity import load_competitor_identity
    from services.analytics.competitors import _INVALID_NIF_KEYS

    for lic_id, nombre, nif in _FILAS_E2E:
        _insertar(lic_id, nombre, nif)

    filas = [{"nombre": nombre, "nif": nif} for _lic, nombre, nif in _FILAS_E2E]
    esperado = _particion(_prepare_company_identity(pd.DataFrame(filas))[_GROUP_KEY].tolist())

    sql_rows = load_competitor_identity(
        placeholder_nifs=sorted(_INVALID_NIF_KEYS),
        curated_groups={nif: key for nif, (key, _n) in _CURATED_GROUPS_BY_NIF.items()},
    )
    with connect_read() as c:
        orden = {
            int(row[0]): str(row[1])
            for row in c.execute("SELECT id, licitacion_id FROM adjudicaciones").fetchall()
        }
    por_licitacion = {orden[int(r["row_id"])]: r["grupo_key"] for r in sql_rows}
    obtenido = _particion([por_licitacion[lic_id] for lic_id, _n, _nif in _FILAS_E2E])

    assert obtenido == esperado
    # Y la propiedad de negocio, explícita: se unen por NIF, no por placeholder.
    assert obtenido == frozenset({frozenset({0, 1}), frozenset({2}), frozenset({3})})
