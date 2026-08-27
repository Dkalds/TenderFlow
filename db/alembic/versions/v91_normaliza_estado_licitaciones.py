"""v91: normaliza ``licitaciones.estado`` al vocabulario canónico.

Revision ID: v91_normaliza_estado_licitaciones
Revises: v90_solicitudes_acceso_dedupe
Create Date: 2026-08-26

``licitaciones.estado`` mezclaba dos vocabularios. CÓDICE y TED escriben
códigos PLACSP (``PUB``, ``EV``, ``ADJ``, ``RES``, ``ANUL``, ``PRE``), pero los
dos conectores que reciben la fase como prosa —PSCP (``fase_publicacio``) y los
RSS regionales (``Estado:``)— guardaban la etiqueta cruda cuando no la
reconocían, y PSCP además la **truncaba a 20 caracteres**. Medido contra
producción el 2026-08-26, sobre 691.974 filas::

    PUBLICACIÓ AGREGADA     645.664   (93,3 %)  ← con espacio final
    RES                      22.035
    ADJ                       9.522
    PUB                       4.969
    EXECUCIÓ                  4.488
    ANUL                      3.261
    EV                          889
    EXPEDIENT EN AVALUAC        623   ← cortado a 20 caracteres
    PRE                         386
    ALERTA FUTURA                 2
    CONSULTA PRELIMINAR           2
    EVA                           1

El espacio final de ``'PUBLICACIÓ AGREGADA '`` y el corte de ``'EXPEDIENT EN
AVALUAC'`` son la misma cicatriz: el ``[:20]`` cae a mitad de la palabra
siguiente. La columna no tiene límite de longitud (``db/models.py`` la declara
``String`` a secas), así que el truncado nunca fue del schema ni de la fuente.

Qué rompía
----------
``shared/estados.py`` enumera los estados **cerrados** y trata todo lo demás
como abierto —regla deliberada, para que un código nuevo no desaparezca del
Radar en silencio—. Con ``PUBLICACIÓ AGREGADA`` fuera de esa lista, las 645.664
filas contaban como abiertas y el "Total activas" del Resumen decía 657.156
sobre un corpus de 691.974: el KPI más grande de la pantalla de entrada medía
el tamaño del corpus. Además esos valores crudos llegaban al desplegable de
``/meta/filters`` y al gráfico de composición como opciones.

Qué hace esta revisión
----------------------
Un solo ``UPDATE`` que reescribe ``estado`` con el mismo mapeo que
``services.classification.normalizar_estado`` aplica desde ahora en la ingesta.
Las fases sin equivalente PLACSP estrenan código propio —``AGR`` (publicació
agregada), ``EJEC`` (execució), ``CPM`` (consulta preliminar)—; ``AGR`` y
``EJEC`` entran en ``ESTADOS_CERRADOS``.

**El mapeo se congela aquí en SQL en vez de importar el normalizador de
Python.** Una migración describe lo que se le hizo a *estos* datos en *esta*
fecha; si importara la función, editarla mañana cambiaría retroactivamente lo
que esta revisión dice haber hecho. El precio es tener la tabla dos veces, y
por eso ambas copias se enumeran en el mismo orden y con los mismos comentarios.

**Sin ``unaccent``, aunque v87 la habilitó.** Esa misma revisión avisa de que
la extensión cae en el primer schema creable del ``search_path`` y de que en
Supabase —que es donde corre este corpus— eso deja llamadas sin cualificar
fallando con ``function unaccent(text) does not exist``. ``translate()`` es
ANSI, no depende del ``search_path`` y aquí basta: el alfabeto a plegar son las
vocales acentuadas del catalán y el castellano.

**Los prefijos son más cortos que en Python a propósito**: ``AVALUAC`` y no
``AVALUACI``, porque el valor almacenado ya viene cortado a 20 caracteres
justo antes de esa ``I``. El normalizador de Python usa los mismos prefijos
cortos para que las dos rutas coincidan también sobre el dato mutilado.

Idempotente: la expresión es un punto fijo sobre los códigos canónicos
(``'PUB'``, ``'AGR'``, ``'EJEC'``… se mapean a sí mismos) y el ``IS DISTINCT
FROM`` del ``WHERE`` sólo toca las filas que cambian, así que re-aplicarla no
escribe nada. Ese mismo predicado es lo que evita reescribir las ~46 k filas
que ya estaban en un código correcto.

**El downgrade no revierte.** El valor original no es reconstruible: se perdió
en el ``[:20]`` de la ingesta, no aquí. Un downgrade que "restaurase"
``'PUBLICACIÓ AGREGADA '`` estaría inventando el dato. Para volver al
comportamiento anterior se revierte el código —``ESTADOS_CERRADOS``—, no los
datos.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v91_normaliza_estado_licitaciones"
down_revision: str | Sequence[str] | None = "v90_solicitudes_acceso_dedupe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Vocales acentuadas del catalán y el castellano → su forma plana. Equivale al
# NFKD + strip de `services.normalization.fold_text`, que es lo que aplica la
# ingesta, sin depender de ninguna extensión. El punto volado de "Anul·lació"
# no se toca: tampoco lo quita `fold_text`, y el prefijo `ANUL` va delante.
_ACENTOS = "ÁÀÂÄÃÉÈÊËÍÌÎÏÓÒÔÖÕÚÙÛÜÑÇáàâäãéèêëíìîïóòôöõúùûüñç"
_PLANAS = "AAAAAEEEEIIIIOOOOOUUUUNCaaaaaeeeeiiiiooooouuuunc"

# El CTE `plegado` calcula esta forma una sola vez por fila y el `CASE` se
# escribe contra su alias `n`. Inlinear la expresión en cada rama era correcto
# pero ilegible —diecinueve copias del alfabeto— y repetía el `translate`.
#
# El orden de las ramas es el mismo que el de
# `services.classification._FASE_ESTADO`: gana el primer prefijo que aparece,
# así que lo específico va antes que lo genérico. Sin ese orden, "publicació
# agregada d'adjudicacions" sería ADJ en vez de AGR.
_SQL = f"""
WITH plegado AS (
    SELECT id_externo,
           upper(translate(btrim(estado), '{_ACENTOS}', '{_PLANAS}')) AS n
    FROM licitaciones
    WHERE estado IS NOT NULL
),
mapeado AS (
    SELECT id_externo,
           CASE
               WHEN strpos(n, 'PUBLICACIO AGREGADA')  > 0 THEN 'AGR'
               WHEN strpos(n, 'PUBLICACION AGREGADA') > 0 THEN 'AGR'
               WHEN strpos(n, 'CONSULTA PRELIMINAR')  > 0 THEN 'CPM'
               WHEN strpos(n, 'ALERTA FUTURA')        > 0 THEN 'PRE'
               WHEN strpos(n, 'EXECUCIO')             > 0 THEN 'EJEC'
               WHEN strpos(n, 'EJECUCION')            > 0 THEN 'EJEC'
               WHEN strpos(n, 'AVALUAC')              > 0 THEN 'EV'
               WHEN strpos(n, 'EVALUAC')              > 0 THEN 'EV'
               WHEN n = 'EVA'                              THEN 'EV'
               WHEN strpos(n, 'ANUNCI PREVI')         > 0 THEN 'PRE'
               WHEN strpos(n, 'PREVI')                > 0 THEN 'PRE'
               WHEN strpos(n, 'FORMALITZACI')         > 0 THEN 'RES'
               WHEN strpos(n, 'FORMALIZACI')          > 0 THEN 'RES'
               WHEN strpos(n, 'ADJUDICACI')           > 0 THEN 'ADJ'
               WHEN strpos(n, 'ANUL')                 > 0 THEN 'ANUL'
               WHEN strpos(n, 'DESIST')               > 0 THEN 'ANUL'
               WHEN strpos(n, 'LICITACI')             > 0 THEN 'PUB'
               WHEN strpos(n, 'ANUNCI')               > 0 THEN 'PUB'
               -- Sin mapeo conocido: se conserva la fase entera, plegada y en
               -- mayúsculas. No se inventa un código ni se pone NULL —
               -- `shared.estados` cuenta ambos como abiertos, así que borrar el
               -- rastro no protegería nada y sí escondería que la fuente
               -- publicó algo nuevo.
               ELSE n
           END AS nuevo
    FROM plegado
)
UPDATE licitaciones AS l
SET estado = m.nuevo
FROM mapeado AS m
WHERE l.id_externo = m.id_externo
  AND l.estado IS DISTINCT FROM m.nuevo
"""


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    # Un solo UPDATE sobre ~645 k filas. `SET LOCAL` para que el
    # `statement_timeout` del rol —el que mata las consultas caras de la API—
    # no aborte la migración a mitad; vuelve solo al cerrar la transacción.
    op.execute("SET LOCAL statement_timeout = 0")
    op.execute(_SQL)


def downgrade() -> None:
    # Deliberadamente vacío: ver el docstring. El valor previo se perdió en el
    # truncado de la ingesta, así que no hay nada fiel que restaurar.
    return
