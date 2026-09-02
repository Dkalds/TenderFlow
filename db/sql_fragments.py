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

    Dos caminos entran: un universo filtrado en ingesta, o una etiqueta
    ``tecnologia`` no vacía (que es como un expediente de PSCP demuestra que
    casó con el diccionario). ``NULL`` en ``analysis_universe`` cuenta como
    ``technology_observed`` por el mismo motivo que :data:`TECHNOLOGY_OBSERVED_SQL`:
    las filas anteriores al linaje sólo pudieron entrar por el filtro histórico.

    Es la definición que la superficie pública tiene que compartir con la
    analítica: hasta 2026-09 los hubs publicaban las ~400k filas de PSCP sin
    este corte, y la portada de un «radar tecnológico» abría con reactivos de
    laboratorio.

    El primer disyunto se escribe **exactamente** como :data:`TECHNOLOGY_OBSERVED_SQL`
    (para ``alias='l'`` son la misma cadena) y no como un ``IN (...)`` que lo
    englobe: el índice parcial de ``v84`` sólo sirve ese texto literal, y
    ``tests/test_scoring_universo_index.py`` rechaza cualquier variante del
    ``COALESCE``. Los universos de los RSS van aparte, sin ``COALESCE``, porque
    una fila con ``NULL`` ya entró por el primer disyunto.
    """
    canonico = f"COALESCE({alias}.analysis_universe, 'technology_observed') = 'technology_observed'"
    regionales = ", ".join(f"'{u}'" for u in UNIVERSOS_TECNOLOGICOS if u != "technology_observed")
    return (
        f"({canonico} OR {alias}.analysis_universe IN ({regionales}) "
        f"OR ({alias}.tecnologia IS NOT NULL AND {alias}.tecnologia <> ''))"
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
# iguales en dos valores distintos. Replican los de `_fold_expr` en
# `db/repositories/aggregates.py`, que son privados de aquel módulo; si allí
# cambian, hay que tocar los dos sitios.
FOLD_SRC = "áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ"
FOLD_DST = "aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC"


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
    return (
        f"nullif(lower(translate(btrim(coalesce({alias}.organo_contratacion, '')), "
        f"'{FOLD_SRC}', '{FOLD_DST}')), '')"
    )


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
    """
    return f"substr(coalesce({alias}.fecha_publicacion, {alias}.fecha_extraccion, ''), 1, 7)"


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


def periodo_canonico(fecha_publicacion: str | None, fecha_extraccion: str | None) -> str:
    """Gemelo Python de :func:`periodo_publicacion_sql`.

    Espeja ``coalesce`` y no "el primer valor no vacío": ``coalesce`` solo salta
    los ``NULL``, así que una ``fecha_publicacion`` de cadena vacía gana igual en
    SQL y tiene que ganar igual aquí.
    """
    for valor in (fecha_publicacion, fecha_extraccion):
        if valor is not None:
            return str(valor)[:7]
    return ""


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
    return (
        f"(({alias}.fuente <> 'placsp'), coalesce({alias}.fecha_publicacion, '9999'), "
        f"coalesce({alias}.fecha_extraccion, '9999'), {alias}.id_externo)"
    )


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
    return (
        f"({alias}.fuente <> 'placsp'), coalesce({alias}.fecha_publicacion, '9999'), "
        f"coalesce({alias}.fecha_extraccion, '9999'), {alias}.id_externo"
    )


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
