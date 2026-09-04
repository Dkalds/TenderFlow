"""Fragmentos SQL constantes que necesita el propio ``db/``.

Gemelo de ``services/sql_fragments.py`` en el lado correcto de la frontera.
Existe por la colisión de dos reglas del proyecto:

- **ADR-022**: todo el SQL vive en ``db/``. La migración del ratchet TID251 va
  moviendo queries de ``services/`` a ``db/``, y esas queries se llevan consigo
  los fragmentos que interpolan.
- **ADR-024**: ``db/`` no puede depender de ``services/`` (capa superior). Un
  ``from services.dedupe import ...`` dentro de ``db/`` invierte las capas.

Hasta ahora la salida era duplicar el fragmento en ``db/`` con un comentario
apuntando al original (``db/repositories/ml_dataset.py::_NO_DUPLICADOS``,
``db/repositories/pricing.py`` con ``EFFECTIVE_BUDGET_SQL``). Eso funciona para
una línea, pero :data:`FECHA_FIN_SQL` son doce con aritmética de intervalos: una
tercera copia es una divergencia esperando a ocurrir.

Así que la definición canónica de estos tres fragmentos baja aquí y
``services/sql_fragments.py`` y ``services/dedupe.py`` los **reexportan**. Los
call-sites de ``services/`` siguen importando de donde siempre; lo que cambia es
la dirección de la dependencia, que ahora es ``services/ → db/``, la permitida.

No se movieron los demás fragmentos de ``services/sql_fragments.py``: solo
bajan los que ``db/`` consume hoy. Bajar el resto es trabajo de la misma ola del
ratchet, cuando alguna query de ``db/`` los necesite.

Los fragmentos de **clave canónica** del final del módulo nacieron aquí, no
bajaron de ``services/``. Viven en ``db/`` por ADR-022 —son SQL— y en este
módulo y no en el repositorio que los usa porque ``services/dedupe.py`` tiene
que poder espejar las mismas reglas en Python sin que las dos definiciones
diverjan en silencio.
"""

from __future__ import annotations

# Universo por defecto de los agregados del radar. Las filas anteriores al
# linaje se consideran legado del radar porque el único pipeline histórico
# filtraba tecnología; las nuevas fuentes deben declarar su universo y quedan
# fuera salvo que una métrica las solicite expresamente.
TECHNOLOGY_OBSERVED_SQL = (
    "COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed'"
)


def technology_observed_sql(alias: str = "l") -> str:
    """:data:`TECHNOLOGY_OBSERVED_SQL`, escrito para un alias cualquiera.

    Existe porque la misma condición estrecha estaba copiada a mano en seis
    módulos con tres grafías distintas (``l.``, ``l2.`` y la columna desnuda de
    los jobs del scheduler). Una copia de este predicado no falla nunca de
    forma visible: el resultado sigue siendo correcto y lo único que se pierde
    es el índice parcial de ``v84``, en silencio y con el plan de vuelta al
    Parallel Seq Scan de 9,5 s.

    **La cadena tiene que ser byte-idéntica a la del índice.** Postgres solo
    usa un índice parcial cuando demuestra que el ``WHERE`` implica su
    predicado, y no normaliza variantes del ``COALESCE``. Por eso esto emite
    para ``alias='l'`` exactamente :data:`TECHNOLOGY_OBSERVED_SQL`, carácter a
    carácter (lo fija ``tests/test_s1_fragmentos_paridad.py``), y por eso el
    alias **no puede ir vacío**: una consulta sobre ``licitaciones`` sin alias
    tiene que ponerle uno, no quitarle el prefijo al predicado.

    Para el universo ancho —el que la superficie pública comparte con la
    analítica— ver :func:`universo_tecnologico_sql`; esto es sólo el primero de
    sus disyuntos.
    """
    return f"COALESCE({alias}.analysis_universe, 'technology_observed') = 'technology_observed'"


#: Universos que llegan filtrados por señal tecnológica **antes** de persistir:
#: PLACSP/TED (``technology_observed``) y los RSS autonómicos, cuyo conector
#: descarta lo que no casa con el diccionario. Lo que NO está aquí es
#: ``pscp_observed``: ese conector guarda la plataforma catalana entera
#: (reactivos, obras, limpieza) y sólo etiqueta ``tecnologia`` cuando el título
#: casa con el diccionario.
UNIVERSOS_TECNOLOGICOS: tuple[str, ...] = (
    "technology_observed",
    "galicia_rss_recent_technology_observed",
    "euskadi_rss_recent_technology_observed",
)


def universo_tecnologico_sql(alias: str = "l") -> str:
    """Predicado «esta fila es tecnología», escrito para un alias.

    Cuatro caminos entran: un universo filtrado en ingesta (los dos primeros
    disyuntos), una etiqueta ``tecnologia`` no vacía —que es como un expediente
    de PSCP demuestra que casó con el diccionario— o una etiqueta
    ``ml_tecnologias`` no vacía. ``NULL`` en ``analysis_universe`` cuenta como
    ``technology_observed`` por el mismo motivo que :data:`TECHNOLOGY_OBSERVED_SQL`:
    las filas anteriores al linaje sólo pudieron entrar por el filtro histórico.

    Es la definición que la superficie pública tiene que compartir con la
    analítica: hasta 2026-09 los hubs publicaban las ~400k filas de PSCP sin
    este corte, y la portada de un «radar tecnológico» abría con reactivos de
    laboratorio.

    El primer disyunto se escribe **exactamente** como :data:`TECHNOLOGY_OBSERVED_SQL`
    (para ``alias='l'`` son la misma cadena, y sale del mismo sitio:
    :func:`technology_observed_sql`) y no como un ``IN (...)`` que lo englobe:
    el índice parcial de ``v84`` sólo sirve ese texto literal, y
    ``tests/test_scoring_universo_index.py`` rechaza cualquier variante del
    ``COALESCE``. Los universos de los RSS van aparte, sin ``COALESCE``, porque
    una fila con ``NULL`` ya entró por el primer disyunto.

    **Aviso de plan**: el ``OR`` impide que Postgres use el índice parcial de
    ``v84`` para el conjunto entero (una fila con ``tecnologia`` y universo
    ``pscp_observed`` no está en ese índice). El predicado estrecho sigue
    existiendo aparte —:func:`technology_observed_sql`— justamente para las
    consultas que quieren pagar el índice y no el universo ancho.

    Regla de precedencia de la señal técnica
    ----------------------------------------
    ``tecnologia`` (regex de keywords de la ingesta) → ``ml_tecnologias``
    (clasificador) → LLM → pliego. Los dos últimos **no tienen columna propia**:
    ``db/repositories/tecnologia_pliego.py::merge_many_with_lock`` los escribe
    sobre ``licitaciones.ml_tecnologias``/``ml_tech_principal``, así que entran
    al universo por el cuarto disyunto y no por uno quinto.

    Qué gana cuando hay conflicto: **nada, aquí**. Este fragmento decide
    pertenencia al universo, no etiqueta, y basta con que **una** señal exista
    para entrar — es un ``OR``, no una prioridad. La precedencia importa donde
    se elige *qué tecnología* mostrar, y ahí manda ``tecnologia`` sobre
    ``ml_tecnologias`` porque la primera es determinista y auditable (el término
    que casó) mientras la segunda es una probabilidad. Consecuencia práctica de
    esa asimetría: una fila con ``ml_tecnologias`` y sin ``tecnologia`` entra al
    universo desde la revisión ``v99`` (antes, la señal de ML/LLM/pliego no
    llegaba nunca a la superficie pública) y se muestra con la etiqueta de ML.

    Hasta ``v99`` el cuarto disyunto no existía, así que **este cambio amplía el
    universo**: la vista ``licitaciones_canonicas`` incorpora las filas cuya
    única señal técnica venía del clasificador, del LLM o del pliego. Cuánto
    crece sólo se puede medir contra la BD real.
    """
    canonico = technology_observed_sql(alias)
    regionales = ", ".join(f"'{u}'" for u in UNIVERSOS_TECNOLOGICOS if u != "technology_observed")
    return (
        f"({canonico} OR {alias}.analysis_universe IN ({regionales}) "
        f"OR ({alias}.tecnologia IS NOT NULL AND {alias}.tecnologia <> '') "
        f"OR ({alias}.ml_tecnologias IS NOT NULL AND {alias}.ml_tecnologias <> ''))"
    )


# Fecha de fin efectiva del contrato, con prioridad:
# 1. ``licitaciones.fecha_fin`` explícita (solo ~6% de las filas).
# 2. ``fecha_inicio + duracion`` (unidades CODICE: ANN/MON/DAY).
# 3. ``fecha_adjudicacion + duracion`` como último recurso.
# substr(x, 1, 10) normaliza timestamps ISO a fecha pura; CAST a INT porque
# duracion_valor es REAL y el CAST a INTEGER es necesario para la aritmética
# de INTERVAL. Asume alias ``l`` (licitaciones) y ``a`` (adjudicaciones).
#
# Devuelve TEXT 'YYYY-MM-DD' (via to_char) y no un date, para que las
# comparaciones lexicográficas contra las columnas de fecha —que son TEXT en
# este esquema— sean equivalentes.
FECHA_FIN_SQL = """
COALESCE(
    substr(l.fecha_fin, 1, 10),
    CASE l.duracion_unidad
        WHEN 'ANN' THEN to_char(substr(COALESCE(l.fecha_inicio, a.fecha_adjudicacion), 1, 10)::date
                             + (CAST(l.duracion_valor AS INTEGER) * INTERVAL '1 year'), 'YYYY-MM-DD')
        WHEN 'MON' THEN to_char(substr(COALESCE(l.fecha_inicio, a.fecha_adjudicacion), 1, 10)::date
                             + (CAST(l.duracion_valor AS INTEGER) * INTERVAL '1 month'), 'YYYY-MM-DD')
        WHEN 'DAY' THEN to_char(substr(COALESCE(l.fecha_inicio, a.fecha_adjudicacion), 1, 10)::date
                             + (CAST(l.duracion_valor AS INTEGER) * INTERVAL '1 day'), 'YYYY-MM-DD')
    END
)
"""


def fecha_fin_sql() -> str:
    """Fragmento SQL de fecha de fin efectiva.

    Envoltorio de :data:`FECHA_FIN_SQL`. Existía para elegir dialecto entre los
    dos motores; desde ADR-021 hay uno solo, pero se conserva porque es el
    accessor que usan los call-sites y mantiene el punto único de cambio.
    """
    return FECHA_FIN_SQL


# De dónde sale la fecha de fin que :data:`FECHA_FIN_SQL` devuelve. Mismas
# ramas y en el mismo orden: si una cambia allí, cambia aquí. El valor viaja
# hasta la UI, que rotula «estimada» todo lo que no sea ``real`` — el ~94% del
# horizonte de renovaciones se calcula, no se lee, y presentarlo como fecha
# firme era una de las promesas que el producto no podía sostener.
FECHA_FIN_ORIGEN_SQL = """
CASE
    WHEN l.fecha_fin IS NOT NULL THEN 'real'
    WHEN l.duracion_unidad IN ('ANN', 'MON', 'DAY') AND l.duracion_valor IS NOT NULL
         AND l.fecha_inicio IS NOT NULL THEN 'estimada_inicio'
    WHEN l.duracion_unidad IN ('ANN', 'MON', 'DAY') AND l.duracion_valor IS NOT NULL
         AND a.fecha_adjudicacion IS NOT NULL THEN 'estimada_adjudicacion'
    ELSE 'desconocida'
END
"""

ORIGENES_FECHA_FIN: tuple[str, ...] = (
    "real",
    "estimada_inicio",
    "estimada_adjudicacion",
    "desconocida",
)


def fecha_fin_origen_sql() -> str:
    """Accessor de :data:`FECHA_FIN_ORIGEN_SQL`, simétrico a :func:`fecha_fin_sql`."""
    return FECHA_FIN_ORIGEN_SQL


def exclude_duplicados_sql(col: str = "l.id_externo") -> str:
    """Cláusula SQL para excluir filas no-canónicas en consultas analíticas.

    ``col`` es la columna que referencia a ``licitaciones.id_externo`` en la
    query llamadora (``l.id_externo``, ``a.licitacion_id``…). Centralizada
    para no repetir la subquery en cada servicio. Solo excluye duplicados
    ``confirmed``; los ``pending`` cuentan hasta que un humano los confirme.

    La lógica de dominio del dedupe (matching, marcado, cursor) sigue en
    ``services/dedupe.py``; aquí vive solo el fragmento SQL, que es lo que
    ADR-022 pide tener en ``db/`` y lo que ``db/`` necesita poder interpolar
    sin importar hacia arriba.
    """
    # S608: `col` es una referencia de columna fija escrita por los servicios
    # llamadores, nunca input de usuario; los valores siempre van con ?.
    subquery = "(SELECT licitacion_id FROM licitaciones_duplicados WHERE status = 'confirmed')"
    return f"{col} NOT IN {subquery}"


# ── Plegado de acentos en SQL ─────────────────────────────────────────────
# Pares de `translate()` para que una tilde distinta no convierta dos valores
# iguales en dos valores distintos. Hasta 2026-09 estaban además copiados como
# `_FOLD_SRC`/`_FOLD_DST` privados en `db/repositories/aggregates.py`, con un
# comentario que pedía tocar los dos sitios a la vez; ahora hay uno solo y
# aquel módulo importa de aquí.
FOLD_SRC = "áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ"
FOLD_DST = "aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC"

#: Tabla de plegado equivalente a :data:`FOLD_SRC`/:data:`FOLD_DST` en Python.
#: La usan los llamantes que tienen que plegar el *needle* antes de mandarlo
#: como parámetro, para que la comparación se haga plegada en los dos lados.
FOLD_TABLE = str.maketrans(FOLD_SRC, FOLD_DST)


def fold_expr(column: str) -> str:
    """Expresión SQL que pliega tildes y mayúsculas de ``column``.

    Aproximación de ``shared/services fold_text`` (NFKD sin tildes +
    ``casefold``) sin la extensión ``unaccent``, que no está habilitada.
    Cubre el repertorio acentuado real de los nombres de órganos españoles;
    cualquier carácter fuera del mapa queda igual (mismo resultado que
    ``fold_text`` para ASCII).

    Vive aquí y no en el repositorio que la estrenó porque tres módulos la
    necesitan —el constructor de filtros de ``aggregates``, la clave canónica
    de este mismo fichero y el ranking de órganos— y la versión de
    ``aggregates`` era privada, así que los otros dos la re-tecleaban.
    """
    return f"lower(translate({column}, '{FOLD_SRC}', '{FOLD_DST}'))"


def tecnologia_en_csv_sql(col: str, *, n: int, marcador: str = "%s") -> str:
    """«Alguno de estos ``n`` códigos está en el CSV de tecnologías de la fila».

    ``licitaciones.tecnologia`` no guarda un código: guarda ``"SAP,SALESFORCE"``.
    La igualdad (``l.tecnologia = %s``) se dejaba fuera todos los expedientes
    multi-tecnología, así que filtrar el ámbito por SAP escondía justo los que
    además llevan otra — y el mismo filtro daba recuentos distintos según por
    qué superficie entrara: el listado y los agregados explotaban el CSV,
    ``load_for_competitors`` comparaba por igualdad.

    Coste: el explode no puede usar ``idx_lic_tecnologia`` (btree de igualdad,
    v21), así que las consultas **con** filtro de tecnología pasan a secuencial.
    Las que no lo llevan no cambian, porque no se añade cláusula. Un índice GIN
    sobre ``string_to_array(tecnologia, ',')`` lo devolvería a indexado, pero
    exige migración y va aparte.

    Los ``n`` valores van con marcadores; el llamante los pasa en su sitio.
    """
    if n <= 0:
        raise ValueError("tecnologia_en_csv_sql necesita al menos un código")
    marcadores = ",".join([marcador] * n)
    return (
        "EXISTS (SELECT 1 FROM unnest(string_to_array("
        f"COALESCE({col}, ''), ',')) AS _tec(code) "
        f"WHERE trim(_tec.code) IN ({marcadores}))"
    )


# ── Guarda de fecha bien formada ──────────────────────────────────────────
# Cotas del rango lexicográfico que excluye fechas claramente malformadas. Son
# constantes públicas además del fragmento porque `db/repositories/
# licitaciones.py` construye SQLAlchemy Core y necesita los extremos sueltos,
# no el texto ya compuesto.
ISO_MIN = "1900"
ISO_MAX = "3000"


def iso_guard(column: str) -> str:
    """Cláusula que excluye fechas claramente malformadas (mirror de coerce+dropna).

    Rango lexicográfico y no regex: ``~`` no puede usar el btree y obliga a
    evaluar el patrón fila a fila sobre todo lo que devuelva el índice de fecha
    (32 s medidos en prod para 217 filas de resultado). El rango es sargable y
    equivalente sobre datos ISO: el CHECK de ``v59`` valida el formato en toda
    escritura nueva y las filas legado se verificaron limpias en prod
    (0 malformadas en licitaciones/adjudicaciones, 2026-08-02).

    Nació privado en ``db/repositories/aggregates.py`` y sube aquí porque las
    mismas dos cotas estaban re-tecleadas en ``adjudicaciones`` (como dos
    condiciones sueltas), en ``agenda`` (sólo el techo) y en ``licitaciones``
    (como par de constantes para SA Core). Cuatro copias de un rango es cuatro
    sitios donde ampliarlo a ``'2999'`` sólo cambia tres.
    """
    return f"({column} >= '{ISO_MIN}' AND {column} < '{ISO_MAX}')"


# ── Clave canónica de un contrato ─────────────────────────────────────────
# `exclude_duplicados_sql` solo tapa lo que un humano o el job de dedupe ya
# marcaron. Los fragmentos de abajo son la otra mitad: colapsan en SQL, sin
# depender de que ningún job haya corrido, las filas que describen el mismo
# contrato. La clave —órgano + CPV4 + año-mes + título— y el criterio de
# canónica están aquí y no en el repositorio que los usa para que
# `services/dedupe.py` pueda espejar exactamente las mismas reglas en Python
# (ADR-024: services → db). Por eso los gemelos Python (`plegar_organo`,
# `periodo_canonico`) también viven aquí, pegados a la definición SQL que
# replican.
#
# Por qué NO se usa el expediente natural, que es la clave débil de
# `services.dedupe.match_key`: tanto TED como PSCP acuñan un `id_externo` por
# **anuncio**, no por **contrato** (`ted:{publication-number}`,
# `pscp:{codi_expedient|id}`). En una republicación —el caso contra el que esto
# defiende— los expedientes naturales son distintos por construcción, así que
# esa clave no ve nada. Lo que sí se repite palabra por palabra es el título
# publicado, que además es lo que hace que dos filas sean *la misma página*
# para quien lee: el criterio de contenido duplicado de un buscador es el texto
# que sirve la URL, no el identificador interno.


def organo_normalizado_sql(alias: str = "l") -> str:
    """Órgano de contratación plegado, o ``NULL`` si no hay órgano.

    El ``NULL`` es deliberado y no un descuido: en SQL ``NULL = NULL`` no es
    verdadero, así que una fila sin órgano nunca colapsa contra ninguna otra.
    Es el equivalente exacto de que ``services.dedupe.match_key`` devuelva
    ``None`` cuando falta el órgano.

    No replica ``normalize_organo``, que además retira formas societarias con
    una tabla en Python. Esto pliega **menos** y por tanto colapsa menos, que
    es la dirección segura para un filtro cuyo error caro es esconder un
    contrato que sí existe.
    """
    recortado = f"btrim(coalesce({alias}.organo_contratacion, ''))"
    return f"nullif({fold_expr(recortado)}, '')"


def cpv4_sql(alias: str = "l") -> str:
    """CPV a 4 dígitos, o cadena vacía si no hay CPV utilizable.

    Misma granularidad que ``services.dedupe._cpv4``. La cadena vacía sí
    compara igual contra otra cadena vacía: dos filas sin CPV que coincidan en
    órgano y título son la misma página aunque ninguna declare el código.

    **Límite conocido**: si una reemisión afina el CPV (``72200000`` en el
    anuncio de licitación y ``72212000`` en el de adjudicación) el CPV4 pasa de
    ``7220`` a ``7221`` y las dos filas dejan de colapsar. Se acepta a
    sabiendas: aflojar a CPV2 taparía esos casos, pero a cambio dos contratos
    del mismo órgano con el mismo título y códigos realmente distintos dentro
    de la misma división se fundirían en uno, y el hub del código perdedor se
    quedaría sin él. Enseñar un duplicado de más es visible y medible; esconder
    un contrato que existe, no. Con datos reales delante se puede medir cuánto
    pesa cada caso y mover el corte con criterio.
    """
    return f"CASE WHEN {alias}.cpv ~ '^[0-9]{{4}}' THEN substr({alias}.cpv, 1, 4) ELSE '' END"


def titulo_normalizado_sql(alias: str = "l") -> str:
    """Título plegado a minúsculas y sin espacios en los bordes.

    Solo ``lower`` + ``btrim``, sin plegado de acentos ni colapso de espacios
    interiores: la republicación que esto persigue viene del mismo feed y
    reemite el título byte a byte, así que normalizar más solo añadiría coste
    por fila —son ~586k— y riesgo de colapsar dos contratos distintos.
    """
    return f"lower(btrim({alias}.titulo))"


def periodo_publicacion_sql(alias: str = "l") -> str:
    """Año-mes (``YYYY-MM``) de la fila, o cadena vacía si no tiene fechas.

    **Por qué la clave necesita una componente temporal.** Órgano + CPV4 +
    título describen el *objeto* del contrato, no el contrato: un órgano que
    licita cada año el mismo mantenimiento con el mismo título administrativo y
    el mismo CPV4 produce filas cuya clave coincide byte a byte. Como
    :func:`_rango_canonico_sql` prefiere la publicación más antigua, sin esta
    componente el anuncio de 2019 tapaba el de 2026 y la convocatoria **viva**
    desaparecía del listado, de ``contar``, de los dos hubs y del sitemap. Ese
    es justo el error caro que ``cpv4_sql`` dice no querer cometer —"esconder un
    contrato que existe" no es visible ni medible—, así que la clave lo corrige
    aquí y no más arriba.

    **Por qué año-mes y no año.** El corte tiene que dejar pasar la reemisión
    que sí hay que colapsar —corrigendos y anuncios de adjudicación del mismo
    expediente, que llegan en días— y separar las ediciones anuales. Un mes
    cubre la primera y no la segunda. El caso que se pierde es el corrigendo que
    cruza el cambio de mes: ahí las dos filas dejan de colapsar y la superficie
    enseña un duplicado. Es el lado barato del error, y es la misma dirección
    que eligen ``cpv4_sql`` y ``organo_normalizado_sql``.

    La cadena vacía sí compara igual contra otra cadena vacía, como en
    :func:`cpv4_sql`: dos filas sin ninguna fecha no se pueden separar por
    tiempo y seguían colapsando antes de este fragmento.

    **Por qué ``primera_extraccion`` antes que ``fecha_extraccion``** (revisión
    ``v100``). El respaldo de este fragmento tiene que ser *inmutable*: es una
    componente de la clave canónica, y la clave decide qué URL publica el
    sitemap. ``fecha_extraccion`` no lo es — ``db/upsert.py`` la reescribe en
    cada pasada, así que una fila sin ``fecha_publicacion`` cambiaba de año-mes
    sola al cruzar un mes, y con ella su clave: dejaba de agrupar con sus
    gemelas y el contrato aparecía dos veces, o cambiaba de canónica y el
    sitemap publicaba otra URL para el mismo contrato. ``primera_extraccion``
    (``v100``) guarda el primer avistamiento y no se vuelve a tocar.

    El ``coalesce`` conserva ``fecha_extraccion`` como tercer término **a
    propósito**: mientras ``db/upsert.py`` no escriba ``primera_extraccion`` en
    el INSERT, las filas nuevas la traen a ``NULL`` y sin ese respaldo perderían
    la componente temporal entera (todas caerían en la cadena vacía y volverían
    a colapsar ediciones de años distintos). Cuando el upsert la escriba —**y
    sólo en el INSERT, nunca en el UPDATE**, ver el docstring de ``v100``— el
    tercer término queda vestigial para las filas nuevas y sólo cubre el legado
    sin historial.
    """
    return (
        f"substr(coalesce({alias}.fecha_publicacion, {alias}.primera_extraccion, "
        f"{alias}.fecha_extraccion, ''), 1, 7)"
    )


# Gemelos en Python de los dos fragmentos que ``services/dedupe.py`` necesita
# reproducir fila a fila. Viven pegados a su definición SQL —y no en el
# servicio— porque el modo de fallo que importa es que diverjan en silencio:
# el detector marcaría pares que la proyección no colapsa, o al revés, y nadie
# se enteraría hasta ver dos veces el mismo contrato en un hub.
_TABLA_PLEGADO = str.maketrans(FOLD_SRC, FOLD_DST)


def plegar_organo(valor: str | None) -> str | None:
    """Gemelo Python de :func:`organo_normalizado_sql`. ``None`` si no hay órgano.

    Diferencia conocida y aceptada: ``str.strip()`` retira también tabuladores y
    saltos de línea, mientras que ``btrim`` de Postgres solo retira espacios. Es
    la misma asimetría —y del mismo lado— que documenta
    ``services.dedupe.normalize_titulo``: Python pliega un pelo más, así que el
    detector puede proponer a revisión un par que el SQL no colapsa. Una entrada
    de más en una cola humana es barata; esconder un contrato, no.
    """
    plegado = (valor or "").strip().translate(_TABLA_PLEGADO).lower()
    return plegado or None


def periodo_canonico(
    fecha_publicacion: str | None,
    fecha_extraccion: str | None,
    *,
    primera_extraccion: str | None = None,
) -> str:
    """Gemelo Python de :func:`periodo_publicacion_sql`.

    Espeja ``coalesce`` y no "el primer valor no vacío": ``coalesce`` solo salta
    los ``NULL``, así que una ``fecha_publicacion`` de cadena vacía gana igual en
    SQL y tiene que ganar igual aquí.

    ``primera_extraccion`` va como argumento **de palabra clave y opcional** —y
    no en la posición que le toca por el ``coalesce``— para no romper los dos
    llamantes que ya existen (``services/dedupe.py`` y sus tests) el mismo día
    que la columna nace. Omitirla reproduce exactamente el comportamiento
    anterior a ``v100``; pasarla espeja el fragmento SQL vigente. Quien lea filas
    con la columna dentro **debe** pasarla, o el detector agrupará por un
    año-mes distinto del que agrupa la proyección.
    """
    for valor in (fecha_publicacion, primera_extraccion, fecha_extraccion):
        if valor is not None:
            return str(valor)[:7]
    return ""


def _criterios_canonicos_sql(alias: str) -> str:
    """Los cuatro criterios de canónica, como lista separada por comas.

    Punto único de :func:`_rango_canonico_sql` (constructor de fila, para el
    ``<`` del anti-join) y :func:`orden_canonico_sql` (lista, para el
    ``ORDER BY`` del ``DISTINCT ON``). Estaban escritos dos veces, y si
    divergieran el agregado y el sitemap elegirían canónicas distintas para el
    mismo contrato sin que fallara nada.

    ``primera_extraccion`` antes que ``fecha_extraccion`` por lo mismo que en
    :func:`periodo_publicacion_sql`: el desempate tiene que ser inmutable, y el
    upsert reescribe ``fecha_extraccion`` en cada pasada. El respaldo se
    conserva mientras ``db/upsert.py`` no rellene la columna nueva.
    """
    return (
        f"({alias}.fuente <> 'placsp'), coalesce({alias}.fecha_publicacion, '9999'), "
        f"coalesce({alias}.primera_extraccion, {alias}.fecha_extraccion, '9999'), "
        f"{alias}.id_externo"
    )


def _rango_canonico_sql(alias: str) -> str:
    """Tupla de orden que decide cuál de las filas gemelas es la canónica.

    Menor gana, y el orden es **total** porque termina en la clave primaria:
    sin ese último desempate, dos filas con las mismas fechas empatarían y
    Postgres podría devolver una u otra según el plan. En el sitemap eso
    significaría que la URL de un contrato cambia entre regeneraciones, que es
    justo lo que un sitemap existe para evitar.

    Los tres primeros criterios son los mismos que ``_pick_canonical`` en
    ``services/dedupe.py``: PLACSP primero (lleva más detalle de adjudicación),
    luego la publicación más antigua, luego la extracción más antigua. Preferir
    la más antigua y no la más reciente es lo que mantiene quieta la URL cuando
    llegan corrigendos.
    """
    return f"({_criterios_canonicos_sql(alias)})"


def clave_canonica_sql(alias: str = "l") -> str:
    """Huella de las cuatro componentes de la clave canónica, en 32 caracteres.

    **No añade semántica**: es exactamente la conjunción de las cuatro
    igualdades de :func:`fila_canonica_sql`, comprimida para que quepa en un
    índice. Existe por una razón puramente física — sin ella el anti-join no
    tiene índice posible y la superficie pública entera muere por
    ``statement_timeout`` (incidente del 2026-08-28).

    **Por qué un hash y no las cuatro expresiones en un índice compuesto.** Una
    entrada de btree no puede pasar de ~2704 bytes, y ``titulo`` no tiene cota
    superior: ``_sustancia_sql`` solo le pone un suelo de 25 caracteres. Un
    índice sobre ``lower(btrim(titulo))`` no falla al planificar sino al
    **crearse**, en cuanto una fila trae un título largo, y con
    ``CONCURRENTLY`` deja un índice inválido detrás. El md5 mide siempre lo
    mismo, así que ese modo de fallo no existe.

    **Por qué sigue siendo correcto.** El hash entra como predicado
    *redundante*: las cuatro igualdades exactas se quedan donde estaban, así
    que una colisión de md5 no puede colapsar dos contratos distintos —el
    planificador usa el hash para descartar barato y las igualdades deciden.

    **Los NULL se propagan igual que antes, y hace falta que así sea.**
    ``organo_normalizado_sql`` devuelve NULL cuando no hay órgano, y
    ``NULL = NULL`` no es cierto: hoy dos filas sin órgano **no** colapsan.
    Concatenar propaga ese NULL a todo el hash, que vuelve a comparar como no
    cierto. Meter un ``coalesce`` aquí para "arreglar" el NULL cambiaría el
    comportamiento y colapsaría filas que hoy sobreviven.

    El separador ``chr(31)`` (unit separator) impide que un corrimiento entre
    componentes finja una clave igual. Aunque lo fingiera, lo atrapan las
    igualdades exactas.

    Si esta expresión cambia, hay que reescribir el índice de la migración
    ``v92`` en el mismo commit: divergir no rompe nada visible, solo deja el
    índice muerto y el timeout de vuelta. ``tests/test_clave_canonica_index.py``
    falla si se separan.
    """
    return (
        f"md5({organo_normalizado_sql(alias)} || chr(31) || {cpv4_sql(alias)} "
        f"|| chr(31) || {periodo_publicacion_sql(alias)} || chr(31) "
        f"|| {titulo_normalizado_sql(alias)})"
    )


def clave_canonica_agrupable_sql(alias: str = "l") -> str:
    """La clave canónica, pero garantizando que nunca es ``NULL``.

    Existe para poder **agrupar** por la clave en vez de anti-unir contra ella.
    :func:`fila_canonica_sql` resuelve "¿es esta fila la canónica?" fila a fila,
    lo que obliga a un sondeo por cada una de las ~695k: perfecto cuando hay un
    ``LIMIT`` que corta pronto (el sitemap), ruinoso cuando hay que recorrer la
    tabla entera (``contar``, los dos hubs, ``ultima_incorporacion``). Medido en
    producción el 2026-08-28: ~200 s por anti-join frente a **9,1 s** agrupando.

    **El ``coalesce`` no es cosmético: preserva la semántica de los NULL.**
    ``organo_normalizado_sql`` devuelve ``NULL`` sin órgano, y en el anti-join
    ``NULL = NULL`` no es cierto, así que ninguna fila sin órgano encuentra
    gemela y **todas** sobreviven. Un ``DISTINCT ON`` sobre la clave cruda haría
    lo contrario —``DISTINCT`` sí considera iguales dos ``NULL``— y colapsaría
    todas esas filas en una, haciendo desaparecer contratos. Sustituir el NULL
    por algo único a la fila (``id_externo`` es la clave primaria) reproduce
    exactamente el comportamiento del anti-join: cada una es su propio grupo.

    El prefijo ``'r:'`` impide que un ``id_externo`` que casualmente parezca un
    md5 colisione con una clave real.
    """
    return f"coalesce({clave_canonica_sql(alias)}, 'r:' || {alias}.id_externo)"


def orden_canonico_sql(alias: str = "l") -> str:
    """El criterio de :func:`_rango_canonico_sql`, en forma de lista ``ORDER BY``.

    Mismo orden y mismos desempates que el anti-join —de ahí que las dos salgan
    del mismo sitio—, pero como lista separada por comas en vez de constructor
    de fila, que es lo que admite un ``ORDER BY`` de ``DISTINCT ON``. Si
    divergieran, agregado y sitemap elegirían canónicas distintas para el mismo
    contrato y la cifra de la portada dejaría de describir lo que se publica.
    """
    return _criterios_canonicos_sql(alias)


def fila_canonica_sql(*, alias: str = "l", gemelo: str = "l2", filtro_gemelo: str) -> str:
    """Cláusula que solo deja pasar la fila canónica de cada contrato.

    ``filtro_gemelo`` es el predicado de publicabilidad escrito para ``gemelo``
    y **no** es opcional: si el gemelo no se filtrara igual que la fila
    exterior, una fila que no se publica podría tapar a una que sí, y la
    superficie perdería un contrato entero sin que nada fallara.

    Se escribe como un ``NOT EXISTS`` conjuntivo a propósito. La alternativa
    natural —``DISTINCT ON (clave)`` en una subconsulta— obliga a ordenar las
    ~586k filas por la clave y volver a ordenarlas por fecha para el listado;
    y meter la guarda en un ``OR`` de nivel superior impediría que Postgres
    convirtiera el ``NOT EXISTS`` en un *anti-join*, dejándolo como subplan por
    fila (586k barridos completos). Conjuntivo y con las tres igualdades
    arriba, el planificador puede resolverlo con un hash anti-join: una pasada
    para construir y otra para sondear.

    Sin índice esto **no era viable**, y no en sentido figurado: se desplegó
    así en #226 y tumbó la superficie pública entera por ``statement_timeout``
    el 2026-08-28. El índice funcional que lo sostiene es
    ``idx_lic_clave_canonica`` (revisión ``v92``), y lo que indexa es
    :func:`clave_canonica_sql` — de ahí que el hash encabece el ``WHERE`` de
    abajo. **Este fragmento no se puede usar sin ese índice**: cualquier
    superficie nueva que lo adopte hereda esa dependencia.

    Aun con índice no es gratis: las cuatro expresiones se siguen calculando en
    las dos ramas, y el listado pierde la posibilidad de resolver
    ``ORDER BY fecha_publicacion DESC LIMIT 50`` por índice — tiene que
    materializar el anti-join antes de ordenar. Se asume porque estas consultas
    las paga una revalidación ISR cacheada una hora en el CDN, no cada visita.

    La cuarta igualdad —el año-mes, ver :func:`periodo_publicacion_sql`— es lo
    que impide que una convocatoria anual recurrente esconda su propia edición
    viva detrás de la de hace siete años. Acota el grupo además de encarecerlo
    un poco: las claves pasan a ser más selectivas, así que el hash anti-join
    construye cubos más pequeños.
    """
    return (
        f"NOT EXISTS (SELECT 1 FROM licitaciones {gemelo} WHERE "
        # Primero el hash: es lo único que un índice puede cubrir (ver
        # `clave_canonica_sql`), y es redundante con las cuatro igualdades de
        # abajo, que se quedan porque son las que deciden de verdad.
        f"{clave_canonica_sql(gemelo)} = {clave_canonica_sql(alias)} "
        f"AND {organo_normalizado_sql(gemelo)} = {organo_normalizado_sql(alias)} "
        f"AND {cpv4_sql(gemelo)} = {cpv4_sql(alias)} "
        f"AND {periodo_publicacion_sql(gemelo)} = {periodo_publicacion_sql(alias)} "
        f"AND {titulo_normalizado_sql(gemelo)} = {titulo_normalizado_sql(alias)} "
        f"AND {filtro_gemelo} "
        f"AND {_rango_canonico_sql(gemelo)} < {_rango_canonico_sql(alias)})"
    )


# ── Una sola definición de «el mismo contrato» ────────────────────────────
# `fila_canonica_sql` (arriba) y `services.dedupe.detect_republicaciones` usan
# los mismos cuatro componentes —órgano, CPV4, año-mes, título— y llegaban a
# resultados distintos porque cada uno los volvía a escribir: el SQL con sus
# cuatro fragmentos y el detector con `republicacion_key`, que compone
# `plegar_organo` + `_cpv4` (suyo) + `normalize_titulo` (suyo) + el año-mes.
# Los dos bloques de abajo son ese punto único: la tupla SQL y su gemela
# Python, y un test de paridad que los compara componente a componente
# (`tests/test_s1_clave_republicacion.py`).


#: Nombres de las cuatro componentes, en el orden en que se comparan y se
#: concatenan. Sirve para que el test de paridad no tenga que reordenar nada y
#: para que un quinto componente futuro no se cuele sin tocar este nombre.
COMPONENTES_REPUBLICACION: tuple[str, str, str, str] = ("organo", "cpv4", "periodo", "titulo")

#: Separador de las componentes. ``chr(31)`` (*unit separator*) y no ``'|'``:
#: un título con una barra vertical dentro puede fingir un corrimiento entre
#: componentes y colapsar dos contratos distintos. Es el mismo que usa
#: :func:`clave_canonica_sql` para su md5.
SEPARADOR_REPUBLICACION = chr(31)


def componentes_republicacion_sql(alias: str = "l") -> tuple[str, str, str, str]:
    """Las cuatro expresiones SQL que definen «el mismo contrato», en orden.

    Es la tupla que :func:`fila_canonica_sql` compara igualdad a igualdad y que
    :func:`clave_canonica_sql` concatena para su hash. Se expone como tupla —y
    no sólo a través de esas dos— para que el gemelo Python pueda compararse
    componente a componente en vez de contra una cadena ya compuesta, que es
    donde una divergencia se esconde.
    """
    return (
        organo_normalizado_sql(alias),
        cpv4_sql(alias),
        periodo_publicacion_sql(alias),
        titulo_normalizado_sql(alias),
    )


def plegar_titulo(valor: str | None) -> str | None:
    """Gemelo Python de :func:`titulo_normalizado_sql`. ``None`` si no hay título.

    Misma asimetría aceptada que :func:`plegar_organo`: ``str.strip()`` retira
    también tabuladores y saltos de línea y ``btrim`` de Postgres sólo espacios,
    así que Python pliega un pelo más y puede proponer a revisión un par que el
    SQL no colapsa. El error caro es el contrario.
    """
    plegado = (valor or "").strip().lower()
    return plegado or None


def cpv4(valor: str | None) -> str:
    """Gemelo Python de :func:`cpv4_sql`. Cadena vacía si no hay CPV utilizable.

    Espeja el ancla del regex (``^[0-9]{4}``) y por tanto **no** hace ``strip``:
    ``services.dedupe._cpv4`` sí lo hace, y por eso un CPV con espacio delante
    (``' 72200000'``) le da ``'7220'`` mientras el SQL le da ``''``. Esa es la
    única divergencia real entre las dos definiciones de clave que había, y se
    resuelve aquí por el lado del SQL: es el que decide lo que se publica.
    """
    texto = valor or ""
    return texto[:4] if texto[:4].isdigit() and texto[:4].isascii() else ""


def componentes_republicacion(
    *,
    organo_contratacion: str | None,
    cpv: str | None,
    titulo: str | None,
    fecha_publicacion: str | None,
    fecha_extraccion: str | None,
    primera_extraccion: str | None = None,
) -> tuple[str, str, str, str] | None:
    """Gemelo Python de :func:`componentes_republicacion_sql`.

    Devuelve ``None`` cuando falta órgano o título, que es lo que hace el SQL
    por otra vía: ``organo_normalizado_sql`` y ``titulo_normalizado_sql``
    devuelven ``NULL``, ``NULL = NULL`` no es cierto y la fila no colapsa contra
    ninguna. Un ``None`` aquí significa exactamente eso — "esta fila es su
    propio grupo"— y el llamante no debe sustituirlo por una clave vacía.
    """
    organo = plegar_organo(organo_contratacion)
    titulo_norm = plegar_titulo(titulo)
    if organo is None or titulo_norm is None:
        return None
    periodo = periodo_canonico(
        fecha_publicacion, fecha_extraccion, primera_extraccion=primera_extraccion
    )
    return (organo, cpv4(cpv), periodo, titulo_norm)


def clave_republicacion(
    *,
    organo_contratacion: str | None,
    cpv: str | None,
    titulo: str | None,
    fecha_publicacion: str | None,
    fecha_extraccion: str | None,
    primera_extraccion: str | None = None,
) -> str | None:
    """Las cuatro componentes unidas por :data:`SEPARADOR_REPUBLICACION`.

    Equivalente Python de lo que :func:`clave_canonica_sql` mete en el ``md5``.
    Es la clave con la que un detector debe agrupar para agrupar igual que la
    proyección.

    **Qué pasa hoy con una republicación ``pending``** (la pregunta que este
    helper existe para dejar escrita). Son dos mecanismos con criterios
    distintos y no coinciden:

    - :func:`exclude_duplicados_sql` sólo excluye los ``confirmed``. Un par que
      ``detect_republicaciones`` acaba de encolar como ``pending`` **sigue
      contando** en las métricas competitivas, en el HHI y en el dataset de ML.
    - :func:`fila_canonica_sql` no mira ``licitaciones_duplicados``: colapsa por
      clave. Así que esa misma fila **ya está escondida** de la superficie
      pública, sin esperar a que nadie la revise.

    O sea que entre el encolado y la revisión humana el mismo contrato está
    fuera del listado público y dentro de la cuota de mercado. No es una
    contradicción accidental: es deliberada y va en la dirección barata de cada
    lado —la superficie prefiere no enseñar un duplicado, la analítica prefiere
    no borrar una adjudicación real por una sospecha—, pero significa que
    ``contar`` y el HHI no describen el mismo universo mientras haya cola.

    **Resolución propuesta, no aplicada**: que las agregaciones dejen de
    depender del ``status`` y pasen a agrupar por esta clave, igual que la
    proyección — es decir, extender ``clave_canonica_agrupable_sql`` a las
    consultas analíticas y quedarse con la canónica de cada grupo. Eso alinea
    los dos universos sin necesidad de que nadie revise nada, que es la parte
    que hoy no escala (PSCP aporta ~566k filas a la primera pasada). No se
    aplica en este cambio porque mueve cifras publicadas —cuota, HHI,
    renovaciones— y el delta sólo se puede medir contra la BD real.
    """
    componentes = componentes_republicacion(
        organo_contratacion=organo_contratacion,
        cpv=cpv,
        titulo=titulo,
        fecha_publicacion=fecha_publicacion,
        fecha_extraccion=fecha_extraccion,
        primera_extraccion=primera_extraccion,
    )
    if componentes is None:
        return None
    return SEPARADOR_REPUBLICACION.join(componentes)
