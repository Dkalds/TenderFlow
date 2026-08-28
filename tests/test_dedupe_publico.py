"""La superficie pública no puede servir dos veces el mismo contrato.

Auditoría de 2026-08: el hub de Cataluña mostraba el mismo expediente en las
posiciones #2 y #5 de la primera página. La exclusión que había
(``exclude_duplicados_sql``) solo tapa lo que el job de dedupe ya marcó como
``confirmed``, y ese job empareja fuentes **distintas** por expediente natural
— con lo cual no puede ver el caso real: una fuente que reemite el mismo
contrato con otro ``id_externo`` (TED acuña un ``publication-number`` por
anuncio; PSCP cae al ``id`` de la fila sin ``codi_expedient``).

Estos tests fijan las dos mitades del arreglo, y ninguno necesita Postgres:
capturan el SQL en la frontera del repositorio sin ejecutarlo, y ejercitan las
funciones puras del detector.

Dos modos de fallo silencioso, que son los que justifican el fichero:

1. **Divergencia entre superficies.** ``listar``, ``contar``,
   ``ultima_incorporacion``, los dos hubs y el sitemap tienen que aplicar el
   mismo filtro. Si el sitemap publica una URL que el listado no muestra —o al
   revés— Search Console lo reporta como error de cobertura y el hub pagina
   hacia páginas vacías. Nada de eso falla en tiempo de ejecución.
2. **Desalineación de ``%s`` con los parámetros.** Sembrar una condición en un
   constructor de ``WHERE`` desplaza todos los valores posteriores si la
   condición lleva un placeholder. La query no da error: da resultados
   incorrectos. Mismo precedente que ``tests/test_adjudicaciones_dedupe_sql.py``.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from db.repositories import publico as publico_mod
from db.repositories.publico import PublicoRepository
from db.sql_fragments import (
    cpv4_sql,
    fila_canonica_sql,
    organo_normalizado_sql,
    periodo_canonico,
    periodo_publicacion_sql,
    plegar_organo,
    titulo_normalizado_sql,
)
from services.dedupe import (
    _clave_de_fila,
    _pick_canonical,
    _rango_canonico,
    normalize_titulo,
    republicacion_key,
)

# ---------------------------------------------------------------------------
# Captura del SQL en la frontera
# ---------------------------------------------------------------------------


def _capture(metodo: str, **kwargs: Any) -> tuple[str, list[Any]]:
    """Ejecuta un método del repositorio y devuelve el ``(sql, params)`` que emitió."""
    capturado: dict[str, Any] = {}

    def _execute(sql: str, params: Any = None) -> MagicMock:
        capturado["sql"] = sql
        capturado["params"] = list(params) if params is not None else []
        cursor = MagicMock()
        # `contar` hace int(fila[0]) y `ultima_incorporacion` lee fila[0]: un
        # cero sirve a los dos (el segundo lo trata como falsy → None).
        cursor.fetchone.return_value = (0,)
        return cursor

    ctx = MagicMock()
    ctx.__enter__.return_value.execute.side_effect = _execute

    with (
        patch("db.repositories.publico.connect_read", return_value=ctx),
        patch("db.repositories.publico.rows_to_dicts", return_value=[]),
    ):
        getattr(PublicoRepository(), metodo)(**kwargs)

    return capturado["sql"], capturado["params"]


# Las seis superficies indexables aplican el MISMO criterio de canónica, pero en
# dos formas distintas, y por eso hay dos listas en vez de una.
#
# La razón es de coste y está medida contra producción: el anti-join hace un
# sondeo indexado por fila, así que con `LIMIT` corta pronto (5,9 s un tramo del
# sitemap) y sin `LIMIT` recorre las ~695k una a una (~200 s, muy por encima del
# `statement_timeout` de 30 s). La agrupación no se beneficia del `LIMIT` pero
# hace una sola pasada (9,1 s). Se desplegó el anti-join en las seis y tumbó la
# superficie pública entera durante horas.
#
# `tests/test_publico_canonicas_equivalencia.py` comprueba contra Postgres que
# las dos formas seleccionan el mismo conjunto; aquí sólo se vigila que ninguna
# superficie se quede SIN una de las dos.

#: Superficies con `LIMIT`: usan el anti-join.
_ANTI_JOIN: list[tuple[str, dict[str, Any]]] = [
    ("listar", {}),
    ("listar", {"ccaa_slug": "cataluna", "cpv_prefijo": "72"}),
    ("pagina_de_sitemap", {"desplazamiento": 0, "tamano": 100}),
]

#: Superficies que agregan la tabla entera: usan `DISTINCT ON` sobre la clave.
_AGRUPACION: list[tuple[str, dict[str, Any]]] = [
    ("contar", {}),
    ("contar", {"ccaa_slug": "cataluna"}),
    ("ultima_incorporacion", {}),
    ("hubs_ccaa", {}),
    ("hubs_cpv", {}),
]

#: Las seis, para los invariantes que valen igual en las dos formas.
_INDEXABLES: list[tuple[str, dict[str, Any]]] = _ANTI_JOIN + _AGRUPACION


def _normalizar(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


# ---------------------------------------------------------------------------
# El filtro llega, y llega igual, a las seis superficies
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("metodo", "kwargs"), _ANTI_JOIN)
def test_las_superficies_con_limit_aplican_el_anti_join(
    metodo: str, kwargs: dict[str, Any]
) -> None:
    """Sin esto, el hub vuelve a servir el mismo contrato dos veces en una página."""
    sql, _ = _capture(metodo, **kwargs)

    assert "NOT EXISTS" in sql, f"{metodo}({kwargs}) perdió el filtro de canónica"
    assert _normalizar(publico_mod._CANONICA_SQL) in _normalizar(sql), (
        f"{metodo}({kwargs}) no aplica exactamente `_CANONICA_SQL`; "
        "una copia local del filtro es una divergencia esperando a ocurrir."
    )


@pytest.mark.parametrize(("metodo", "kwargs"), _AGRUPACION)
def test_los_agregados_aplican_la_agrupacion_por_clave(metodo: str, kwargs: dict[str, Any]) -> None:
    """La otra mitad del mismo criterio, y con el mismo desempate.

    Se exige el ``DISTINCT ON`` sobre la clave agrupable Y el orden canónico
    completo: si el ``ORDER BY`` perdiera un criterio, el agregado elegiría una
    canónica distinta de la que publica el sitemap y la URL de un contrato
    dejaría de ser estable entre regeneraciones.
    """
    sql, _ = _capture(metodo, **kwargs)
    normalizado = _normalizar(sql)

    assert f"DISTINCT ON ({publico_mod._CLAVE_AGRUPABLE})" in normalizado, (
        f"{metodo}({kwargs}) perdió la agrupación por clave canónica"
    )
    assert _normalizar(publico_mod._ORDEN_CANONICO) in normalizado, (
        f"{metodo}({kwargs}) no desempata con el orden canónico completo"
    )


@pytest.mark.parametrize(("metodo", "kwargs"), _INDEXABLES)
def test_las_seis_superficies_comparten_la_misma_publicabilidad(
    metodo: str, kwargs: dict[str, Any]
) -> None:
    """Si divergen, Search Console lo reporta como error de cobertura.

    El listado y el sitemap tienen que ver el mismo universo, y ``contar`` el
    mismo que ambos o la paginación del hub enlaza páginas vacías. Lo que se
    comparte es ``_BASE_WHERE`` —el umbral de sustancia más el dedupe marcado—,
    que es la parte común a las dos formas de resolver la canónica.
    """
    sql, _ = _capture(metodo, **kwargs)

    assert _normalizar(publico_mod._BASE_WHERE) in _normalizar(sql), (
        f"{metodo}({kwargs}) no comparte `_BASE_WHERE` con el resto"
    )


def test_las_superficies_indexables_siguen_excluyendo_los_duplicados_marcados() -> None:
    """El filtro nuevo se **suma** al viejo, no lo sustituye.

    ``exclude_duplicados_sql`` tapa los pares cross-fuente que un humano ya
    confirmó; el filtro de canónica tapa las reemisiones que nadie miró. Son
    problemas distintos y hacen falta los dos.
    """
    for metodo, kwargs in _INDEXABLES:
        sql, _ = _capture(metodo, **kwargs)
        assert "licitaciones_duplicados" in sql, f"{metodo}({kwargs}) perdió el dedupe marcado"


def test_la_ficha_no_aplica_el_filtro_de_canonica() -> None:
    """Asimetría deliberada: toda URL del sitemap tiene ficha, no al revés.

    Si ``ficha`` aplicara el filtro, la fila gemela no canónica pasaría a 404 —
    y como la superficie ya está publicada, eso sería una oleada de errores de
    cobertura sobre URLs que el índice ya conoce. Dejarla en 200 no crea
    contenido duplicado: no la enlaza nadie ni entra en el sitemap.
    """
    sql, _ = _capture("ficha", id_externo="ted:123-2026")

    assert "NOT EXISTS" not in sql
    assert _normalizar(publico_mod._BASE_WHERE) in _normalizar(sql)


# ---------------------------------------------------------------------------
# Composición del SQL: placeholders y WHERE bien formado
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("metodo", "kwargs"), [*_INDEXABLES, ("ficha", {"id_externo": "X"})])
def test_los_placeholders_cuadran_con_los_parametros(metodo: str, kwargs: dict[str, Any]) -> None:
    """El fallo silencioso: un ``%s`` de más desplaza todos los valores siguientes."""
    sql, params = _capture(metodo, **kwargs)

    assert sql.count("%s") == len(params), (
        f"{metodo}({kwargs}): {sql.count('%s')} placeholders y {len(params)} "
        f"parámetros. El filtro sembrado no debe llevar placeholders.\nSQL: {sql}"
    )


def test_el_filtro_de_canonica_no_lleva_ningun_porcentaje() -> None:
    """Un ``%`` suelto en el fragmento rompería psycopg, no solo el conteo de ``%s``.

    Con paramstyle ``pyformat`` cualquier ``%`` literal del SQL tiene que ir
    escapado como ``%%`` cuando se pasan parámetros. El filtro usa una regex
    (``~ '^[0-9]{4}'``) justamente para no necesitar un ``LIKE '...%'``.
    """
    assert "%" not in publico_mod._CANONICA_SQL


@pytest.mark.parametrize(("metodo", "kwargs"), [*_INDEXABLES, ("ficha", {"id_externo": "X"})])
def test_el_where_queda_bien_formado(metodo: str, kwargs: dict[str, Any]) -> None:
    """Sin ``WHERE AND``, sin ``AND AND`` y sin un WHERE vacío antes de ORDER/GROUP."""
    sql, _ = _capture(metodo, **kwargs)
    normalizado = _normalizar(sql)

    assert " WHERE AND " not in normalizado, f"{metodo}: WHERE colgando\n{normalizado}"
    assert " AND AND " not in normalizado, f"{metodo}: AND duplicado\n{normalizado}"
    assert not re.search(r"WHERE\s+(ORDER|GROUP|LIMIT|\))", normalizado), (
        f"{metodo}: WHERE sin condiciones\n{normalizado}"
    )
    assert normalizado.count("(") == normalizado.count(")"), (
        f"{metodo}: paréntesis descuadrados\n{normalizado}"
    )


def test_la_subconsulta_filtra_la_fila_gemela_igual_que_la_exterior() -> None:
    """Si el gemelo no se filtrara igual, una fila pobre taparía a la buena.

    El caso concreto: una reemisión sin importe y con descripción corta no
    supera el umbral de sustancia, pero si el ``NOT EXISTS`` la considerara
    candidata y encima rankeara por debajo, eliminaría a la fila publicable y
    el contrato desaparecería entero de la superficie.
    """
    # Se mira `listar` y no `contar`: la fila gemela sólo existe en la forma de
    # anti-join. Los agregados resuelven la canónica agrupando, así que no hay
    # subconsulta que filtrar y la propiedad no les aplica — lo que en ellos
    # sustituye a esta garantía es que el `DISTINCT ON` se hace sobre el
    # conjunto ya filtrado por `_BASE_WHERE`, que cubre el mismo caso.
    sql, _ = _capture("listar")

    # El umbral de sustancia tiene que aparecer escrito para los dos alias.
    assert "l2.titulo IS NOT NULL" in sql
    assert "l.titulo IS NOT NULL" in sql
    assert "l2.id_externo NOT IN" in sql


def test_el_filtro_de_canonica_es_conjuntivo_y_no_va_dentro_de_un_or() -> None:
    """Un ``OR`` de nivel superior impediría el anti-join y lo dejaría en O(n²).

    Postgres solo convierte un ``NOT EXISTS`` en anti-join cuando es un
    conyunto de nivel superior. Metido en un ``OR`` pasa a evaluarse como
    subplan por fila: ~586k barridos completos por consulta. La guarda de
    "fila sin órgano" viaja por eso **dentro** de la clave, como ``NULL`` que
    no compara igual contra nada, y no como un ``OR`` fuera.

    (El ``OR`` que sí hay dentro de la subconsulta es el del umbral de
    sustancia —importe o descripción larga— y va entre paréntesis: no es un
    disyunto de nivel superior.)
    """
    assert publico_mod._CANONICA_SQL.startswith("NOT EXISTS (")
    assert publico_mod._WHERE_INDEXABLE.endswith(" AND " + publico_mod._CANONICA_SQL)
    assert "nullif(" in organo_normalizado_sql("l")


# ---------------------------------------------------------------------------
# La clave y el criterio de canónica
# ---------------------------------------------------------------------------


def test_la_clave_de_la_proyeccion_usa_organo_cpv_periodo_y_titulo() -> None:
    """Y no el expediente natural, que en una reemisión difiere por construcción."""
    clausula = fila_canonica_sql(alias="l", gemelo="l2", filtro_gemelo="true")

    for fragmento in (
        organo_normalizado_sql("l2"),
        cpv4_sql("l2"),
        periodo_publicacion_sql("l2"),
        titulo_normalizado_sql("l2"),
    ):
        assert fragmento in clausula
    assert "id_externo" in clausula  # solo como desempate del rango, ver abajo


def test_la_clave_lleva_una_componente_temporal_en_los_dos_alias() -> None:
    """Sin ella, la edición viva de una convocatoria anual desaparece.

    Un órgano que licita todos los años el mismo objeto con el mismo título y el
    mismo CPV4 produce filas cuya clave coincidía byte a byte. Como el rango
    prefiere la publicación más antigua, el anuncio de 2019 tapaba el de 2026 y
    la convocatoria abierta se caía del listado, de `contar`, de los dos hubs y
    del sitemap: el error caro, el de esconder un contrato que existe.

    Antes esto contaba apariciones de ``substr(coalesce(`` y exigía exactamente
    dos, una por alias. Dejó de valer cuando la cláusula pasó a llevar también
    el hash de :func:`clave_canonica_sql`, que repite las cuatro componentes: la
    cuenta subió a cuatro sin que la propiedad cambiara. Se comprueba ahora
    contra el fragmento mismo, que es más fuerte —compara la expresión entera,
    no un prefijo— y no vuelve a romperse porque la cláusula crezca.
    """
    clausula = fila_canonica_sql(alias="l", gemelo="l2", filtro_gemelo="true")

    assert periodo_publicacion_sql("l") in clausula
    assert periodo_publicacion_sql("l2") in clausula


def test_el_desempate_final_es_la_clave_primaria() -> None:
    """Sin él, la canónica la decide el plan de ejecución y la URL se mueve.

    Un sitemap cuyo tramo devuelve URLs distintas en cada regeneración es peor
    que no tener sitemap: Google reindexa y desindexa las mismas fichas en
    bucle. El orden tiene que ser total, y ``id_externo`` es la única columna
    que lo garantiza.
    """
    clausula = fila_canonica_sql(alias="l", gemelo="l2", filtro_gemelo="true")

    assert "l2.id_externo) < (" in clausula
    assert clausula.rstrip().endswith("l.id_externo))")


def test_el_rango_de_python_espeja_el_de_sql() -> None:
    """Las dos definiciones tienen que ordenar igual o el detector y la
    proyección elegirían canónicas distintas para el mismo contrato."""
    clausula = fila_canonica_sql(alias="l", gemelo="l2", filtro_gemelo="true")

    # Mismo orden de criterios, y el mismo relleno para las fechas ausentes.
    assert "l.fuente <> 'placsp'" in clausula
    assert "coalesce(l.fecha_publicacion, '9999')" in clausula
    assert "coalesce(l.fecha_extraccion, '9999')" in clausula

    fila = {
        "id_externo": "ted:1",
        "fuente": "ted",
        "fecha_publicacion": None,
        "fecha_extraccion": None,
    }
    assert _rango_canonico(fila) == (True, "9999", "9999", "ted:1")


def _fila(id_externo: str, **campos: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id_externo": id_externo,
        "fuente": "ted",
        "fecha_publicacion": "2026-05-01",
        "fecha_extraccion": "2026-05-01T00:00:00+00:00",
    }
    base.update(campos)
    return base


def test_la_canonica_no_depende_del_orden_de_los_argumentos() -> None:
    """El bug que arregla ``_rango_canonico``: antes decidía el orden de la query.

    Dos reemisiones con las mismas fechas empataban, y ``_pick_canonical``
    devolvía ``(a, b)`` — o sea, la que Postgres hubiera puesto primera. La
    canónica cambiaba entre ejecuciones sin que cambiara ni un dato.
    """
    a, b = _fila("ted:0002"), _fila("ted:0001")

    assert _pick_canonical(a, b)[0]["id_externo"] == "ted:0001"
    assert _pick_canonical(b, a)[0]["id_externo"] == "ted:0001"


def test_placsp_sigue_ganando_sobre_las_demas_fuentes() -> None:
    """El criterio anterior no se pierde: PLACSP lleva más detalle de adjudicación."""
    placsp = _fila("ZZZ-9999", fuente="placsp", fecha_publicacion="2026-12-31")
    pscp = _fila("pscp:AAA-0001", fuente="pscp", fecha_publicacion="2020-01-01")

    canonica, duplicada = _pick_canonical(pscp, placsp)

    assert canonica["id_externo"] == "ZZZ-9999"
    assert duplicada["id_externo"] == "pscp:AAA-0001"


def test_entre_iguales_gana_la_publicacion_mas_antigua() -> None:
    """Preferir la más antigua es lo que mantiene quieta la URL ante corrigendos."""
    original = _fila("ted:0009", fecha_publicacion="2026-01-10")
    corrigendo = _fila("ted:0001", fecha_publicacion="2026-03-02")

    assert _pick_canonical(corrigendo, original)[0]["id_externo"] == "ted:0009"


# ---------------------------------------------------------------------------
# El índice de candidatas del detector
# ---------------------------------------------------------------------------


def test_el_indice_del_detector_se_filtra_como_la_superficie_publica() -> None:
    """Si no, el job puede proponer como canónica una fila que no se publica.

    Secuencia del fallo: el detector marca B como duplicada de A, un humano
    confirma el par en ``resolve_pending``, ``exclude_duplicados_sql`` esconde B
    — y como A no supera el umbral de sustancia, el contrato desaparece entero
    de la superficie pública. Es el mismo fallo que
    ``test_la_subconsulta_filtra_la_fila_gemela_igual_que_la_exterior`` protege
    en el lado SQL.

    Y tampoco se acota a una sola fuente: ``fila_canonica_sql`` compara
    ``licitaciones l2`` sin filtro de fuente, así que un índice por fuente no
    veía los pares PLACSP↔PSCP que el SQL sí colapsa.
    """
    from db.repositories import dedupe as dedupe_repo

    capturado: dict[str, Any] = {}

    def _execute(sql: str, params: Any = None) -> MagicMock:
        capturado["sql"] = sql
        cursor = MagicMock()
        cursor.description = [("id_externo",)]
        cursor.__iter__.return_value = iter([])
        return cursor

    ctx = MagicMock()
    ctx.__enter__.return_value.execute.side_effect = _execute

    with patch("db.repositories.dedupe.connect_read", return_value=ctx):
        assert list(dedupe_repo.iter_filas_publicables_de_organos(["organ a"])) == []

    sql = _normalizar(capturado["sql"])
    assert _normalizar(publico_mod._publicable_sql("l")) in sql
    assert "fuente = %s" not in sql


def _fila_repub(id_externo: str, **campos: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id_externo": id_externo,
        "organo_contratacion": "Òrgan A",
        "titulo": "Servei de manteniment de la infraestructura",
        "cpv": "72000000",
        "fuente": "pscp",
        "fecha_publicacion": "2026-03-02",
        "fecha_extraccion": "2026-03-02T00:00:00",
    }
    base.update(campos)
    return base


def _correr_detector(nuevas: list[dict[str, Any]], indice: list[dict[str, Any]]) -> list[Any]:
    """Ejecuta ``detect_republicaciones`` con el repositorio doblado y devuelve las marcas."""
    import services.dedupe as sd

    capturadas: list[Any] = []
    with (
        patch.object(sd.dedupe_repo, "filas_nuevas_de_fuente", return_value=nuevas),
        patch.object(
            sd.dedupe_repo, "iter_filas_publicables_de_organos", return_value=iter(indice)
        ),
        patch.object(sd.dedupe_repo, "marcar_duplicados", side_effect=capturadas.extend),
        patch.object(sd, "get_cursor", return_value=None),
        patch.object(sd, "set_cursor"),
    ):
        sd.detect_republicaciones(fuente="pscp")
    return capturadas


def test_una_fila_nueva_no_publicable_se_marca_contra_su_gemela_buena() -> None:
    """El caso que el `len(grupo) < 2` de antes no podía ver.

    La fila nueva puede no superar el umbral de sustancia y por tanto no estar
    en el índice. Es justo cuando hay que marcarla: esconde la copia pobre y
    deja viva la buena.
    """
    nueva = _fila_repub("pscp:B", fecha_publicacion="2026-03-19")
    publicable = _fila_repub("pscp:A")

    marcas = _correr_detector([nueva], [publicable])

    assert [(m[0], m[1]) for m in marcas] == [("pscp:B", "pscp:A")]


def test_la_edicion_de_hace_siete_anos_no_tapa_la_convocatoria_viva() -> None:
    """El mismo objeto licitado en 2019 no es reemisión del licitado en 2026."""
    nueva = _fila_repub("pscp:2026")
    vieja = _fila_repub("pscp:2019", fecha_publicacion="2019-03-02")

    assert _correr_detector([nueva], [vieja]) == []


def test_una_pasada_sin_pares_mueve_igualmente_el_watermark() -> None:
    """Si no, la misma pasada se repite para siempre sobre las mismas filas."""
    import services.dedupe as sd

    sin_organo = _fila_repub("pscp:C", organo_contratacion=None)
    with (
        patch.object(sd.dedupe_repo, "filas_nuevas_de_fuente", return_value=[sin_organo]),
        patch.object(sd.dedupe_repo, "iter_filas_publicables_de_organos", return_value=iter([])),
        patch.object(sd.dedupe_repo, "marcar_duplicados"),
        patch.object(sd, "get_cursor", return_value=None),
        patch.object(sd, "set_cursor") as set_cursor,
    ):
        resultado = sd.detect_republicaciones(fuente="pscp")

    assert resultado.evaluadas == 1
    assert set_cursor.call_args.kwargs["last_seen_updated"] == "2026-03-02T00:00:00"


def test_sin_organos_el_indice_no_toca_la_base() -> None:
    """Una pasada sin órganos no puede degenerar en un SELECT sin WHERE útil."""
    from db.repositories import dedupe as dedupe_repo

    with patch("db.repositories.dedupe.connect_read") as conectar:
        assert list(dedupe_repo.iter_filas_publicables_de_organos([])) == []

    conectar.assert_not_called()


# ---------------------------------------------------------------------------
# Clave de reemisión en Python
# ---------------------------------------------------------------------------


def test_la_clave_de_reemision_ignora_mayusculas_y_bordes() -> None:
    """Es lo mismo que hace ``lower(btrim(...))`` en SQL."""
    a = republicacion_key("Departament de Salut", "  Servei de manteniment  ", "72000000")
    b = republicacion_key("DEPARTAMENT DE SALUT", "servei de manteniment", "72004000")

    assert a is not None
    assert a == b  # el CPV baja a 4 dígitos: 7200 en los dos


def test_la_clave_de_reemision_separa_lo_que_no_es_el_mismo_contrato() -> None:
    """Distinto órgano, distinto CPV4 o distinto título ⇒ claves distintas."""
    base = republicacion_key("Òrgan A", "Servei de manteniment", "72000000")

    assert base != republicacion_key("Òrgan B", "Servei de manteniment", "72000000")
    assert base != republicacion_key("Òrgan A", "Servei de manteniment", "48000000")
    assert base != republicacion_key("Òrgan A", "Servei de neteja", "72000000")


def test_sin_organo_o_sin_titulo_no_hay_clave() -> None:
    """Equivale al ``NULL`` del SQL: una fila así no colapsa contra ninguna otra.

    Es la mitad conservadora del diseño. Ante la duda, la fila se publica: el
    error caro no es enseñar un duplicado, es esconder un contrato que existe.
    """
    assert republicacion_key(None, "Servei de manteniment", "72000000") is None
    assert republicacion_key("   ", "Servei de manteniment", "72000000") is None
    assert republicacion_key("Òrgan A", None, "72000000") is None
    assert republicacion_key("Òrgan A", "   ", "72000000") is None


def test_sin_cpv_la_clave_sigue_existiendo() -> None:
    """Un CPV ausente no impide reconocer la reemisión; solo la hace menos estricta.

    Mismo criterio que ``match_key``, que también deja el hueco vacío en vez de
    rendirse. Dos filas sin CPV que coincidan en órgano y título son la misma
    página aunque ninguna declare el código.
    """
    sin_cpv = republicacion_key("Òrgan A", "Servei de manteniment", None)
    cpv_basura = republicacion_key("Òrgan A", "Servei de manteniment", "no-es-un-cpv")

    assert sin_cpv is not None
    assert sin_cpv == cpv_basura


def test_normalize_titulo_devuelve_none_para_lo_vacio() -> None:
    assert normalize_titulo(None) is None
    assert normalize_titulo("   ") is None
    assert normalize_titulo("  Servei  ") == "servei"


def test_la_clave_separa_las_ediciones_anuales_de_la_misma_convocatoria() -> None:
    """El gemelo Python del arreglo de arriba, y por el mismo motivo.

    "Servei de manteniment de la infraestructura X" del mismo órgano y el mismo
    CPV4, licitado en 2019 y en 2026, son dos contratos, no una reemisión.
    """
    edicion_2019 = republicacion_key(
        "Òrgan A", "Servei de manteniment", "72000000", periodo="2019-03"
    )
    edicion_2026 = republicacion_key(
        "Òrgan A", "Servei de manteniment", "72000000", periodo="2026-03"
    )

    assert edicion_2019 != edicion_2026


def test_la_clave_sigue_colapsando_el_corrigendo_del_mismo_mes() -> None:
    """Lo que la componente temporal NO puede romper: la reemisión real.

    Un corrigendo o el anuncio de adjudicación del mismo expediente llegan en
    días. Si el año-mes los separase, el arreglo habría cambiado un fallo caro
    por el barato en todos los casos en vez de solo en el borde del mes.
    """
    anuncio = _clave_de_fila(
        {
            "organo_contratacion": "Òrgan A",
            "titulo": "Servei de manteniment",
            "cpv": "72000000",
            "fecha_publicacion": "2026-03-02",
            "fecha_extraccion": "2026-03-02T00:00:00+00:00",
        }
    )
    corrigendo = _clave_de_fila(
        {
            "organo_contratacion": "ÒRGAN A",
            "titulo": "  Servei de manteniment  ",
            "cpv": "72004000",
            "fecha_publicacion": "2026-03-19",
            "fecha_extraccion": "2026-03-19T00:00:00+00:00",
        }
    )

    assert anuncio is not None
    assert anuncio == corrigendo


def test_el_periodo_de_python_espeja_el_coalesce_del_sql() -> None:
    """`coalesce` salta los NULL, no los vacíos: la cadena vacía gana igual."""
    assert periodo_canonico("2026-03-19", "2026-04-01T00:00:00+00:00") == "2026-03"
    assert periodo_canonico(None, "2026-04-01T00:00:00+00:00") == "2026-04"
    assert periodo_canonico("", "2026-04-01T00:00:00+00:00") == ""
    assert periodo_canonico(None, None) == ""


def test_el_organo_se_pliega_como_en_sql_y_no_mas() -> None:
    """El detector no puede plegar más que el filtro que decide qué se publica.

    `normalize_organo` retira formas societarias; el SQL solo baja a minúsculas
    y quita acentos. Usar el primero hacía que el detector propusiera a revisión
    pares que la proyección no colapsa.
    """
    assert plegar_organo("  Òrgan de Contractació  ") == "organ de contractacio"
    assert plegar_organo("ACME S.A.") != plegar_organo("ACME")
    assert plegar_organo(None) is None
    assert plegar_organo("   ") is None


def test_la_clave_es_estable_entre_llamadas() -> None:
    """No hay hashing con semilla ni conjuntos por medio: la misma entrada, la misma
    salida. Si dejara de serlo, el sitemap cambiaría de URL en cada regeneración."""
    entradas = ("Departament de Salut", "Servei de manteniment", "72000000")

    assert len({republicacion_key(*entradas) for _ in range(50)}) == 1
