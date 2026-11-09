"""v177: fuera de los RSS autonómicos lo que solo entró por la prosa de tramitación.

Revision ID: v177_rss_autonomico_sin_tramitacion
Revises: v176_consultas_recientes
Create Date: 2026-11-09

Qué falla hoy
-------------
El SERGAS pone en todos sus avisos del RSS de Galicia «se licitará a través del
sistema de licitación electrónica de la Xunta (SILEX)». El conector casaba la
descripción entera contra el diccionario, así que «licitación electrónica»
metía como ADMIN_ELECTRONICA furgonetas, lácteos, ecógrafos u obras de
climatización (``galicia_rss:829511``, vista el 2026-11-09). El conector ya no
lo hace (``scraper.connectors.regional_rss._sin_tramitacion_fuera_del_titulo``):
el vocabulario de tramitación solo cuenta en el título, la misma regla que la
señal de pliegos aplica desde 2026-10-31. Pero ``tecnologia`` solo se reescribe
al reingerir, y el RSS no vuelve a servir lo ya leído: lo guardado se queda.

Medido en producción el 2026-11-09, sobre las 30 filas de ``galicia_rss`` (de
``euskadi_rss`` no hay ninguna): la única keyword de tramitación presente es
«licitación electrónica». En 20 filas es la única y el título no la dice; una
más, ``galicia_rss:829225``, la lleva junto a «servicios de desarrollo».

Qué hace
--------
- Borra las filas de los dos RSS cuya única keyword es «licitación electrónica»
  y cuyo título no la nombra, **salvo** que algo más las sostenga:

  - otra señal que sí las hace TI (una puntuación de
    ``licitacion_tecnologia_score`` que pasa su umbral). Son 4 de las 20, TI de
    verdad que la señal de pliegos reconoció por su cuenta (829191, sistemas
    de farmacia; 829308, lectores con su software; 829313, equipamiento TIC;
    829462, tarjetas criptográficas). Las otras 16 las marcó ``__no_es_ti__``;
  - una revisión humana en ``ml_feedback``, que entra en el golden set con un
    JOIN a ``licitaciones``: borrar la fila tiraría la etiqueta (829455);
  - trabajo de usuario: las tablas de
    ``db.repositories.purga_licitaciones._REFERENCIAS_PROTECTORAS``.

  Las referencias blandas de ``_REFERENCIAS_ARRASTRADAS`` y el historial se van
  con la fila, y las hijas con FK, por su ``ON DELETE CASCADE``. Todo va en una
  sentencia, así que la lista de protegidas y el borrado ven la misma foto. En
  producción borra 15.
- Deja ``galicia_rss:829225`` en DESARROLLO / «servicios de desarrollo», lo que
  el conector de hoy habría escrito. Va por id y con los valores medidos en la
  condición: recalcular la etiqueta de una fila mixta exige el diccionario, y
  una migración no lo importa, porque lo que dice hoy no es lo que dirá mañana.

Las keywords se congelan aquí en vez de leer ``config.keywords``: es una
corrección de lo medido, no una regla viva. Una base nueva no tiene ninguna de
estas filas, y una segunda pasada no encuentra nada que hacer.

Fuera de alcance
----------------
- Las 4 que se salvan por su señal conservan ``tecnologia = ADMIN_ELECTRONICA``,
  y 3 de ellas no lo son. Su etiqueta servida sale de la puntuación, pero la
  columna solo cambia al reingerir.
- Se quedan huérfanas las referencias sin FK que no son trabajo de usuario:
  ``domain_events`` (5, ya despachados), ``asistente_feedback``,
  ``mat_clusters`` (congelada) y ``feature_store``.
- La vista ``licitaciones_canonicas`` sigue mostrando lo borrado hasta su
  siguiente refresco programado (``scheduler/aggregates_precompute.py``).

Downgrade: no-op deliberado. Lo borrado no se puede rehacer sin el feed, que
ya no sirve esos avisos, y devolver la etiqueta a 829225 solo reabriría el
falso positivo.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v177_rss_autonomico_sin_tramitacion"
down_revision: str | Sequence[str] | None = "v176_consultas_recientes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Las filas que el conector de hoy no habría guardado. El título se mira con
#: la misma holgura que el matcher (tildes y plural); la «Ó» va aparte porque
#: con collation C ``~*`` no la pliega.
_RETIRABLE = (
    "l.fuente IN ('galicia_rss', 'euskadi_rss') "
    "AND l.raw_keywords = 'licitación electrónica' "
    r"AND l.titulo !~* 'licitaci[oóÓ]n(es)?\s+electr[oóÓ]nicas?'"
)

#: Lo que la salva: otra señal TI, una revisión humana o trabajo de usuario.
_PROTEGIDA = (
    "EXISTS (SELECT 1 FROM licitacion_tecnologia_score x "
    "  WHERE x.licitacion_id = l.id_externo AND x.probabilidad >= x.threshold_aplicado) "
    "OR EXISTS (SELECT 1 FROM ml_feedback x WHERE x.expediente = l.id_externo) "
    "OR EXISTS (SELECT 1 FROM pursuits x WHERE x.licitacion_id = l.id_externo) "
    "OR EXISTS (SELECT 1 FROM contratos_cartera x WHERE x.licitacion_id = l.id_externo) "
    "OR EXISTS (SELECT 1 FROM watchlist_items x WHERE x.id_externo = l.id_externo) "
    "OR EXISTS (SELECT 1 FROM follows x WHERE x.target_id = l.id_externo "
    "  AND x.target_type = 'licitacion' AND x.kind = 'seguir') "
    "OR EXISTS (SELECT 1 FROM etiquetas_aplicadas x WHERE x.objeto_id = l.id_externo) "
    "OR EXISTS (SELECT 1 FROM organization_references x WHERE x.expediente_id = l.id_externo) "
    "OR EXISTS (SELECT 1 FROM resoluciones_recurso x WHERE x.licitacion_id = l.id_externo)"
)

_BORRAR = (
    "WITH borrables AS ("
    f"  SELECT l.id_externo FROM licitaciones l WHERE {_RETIRABLE} AND NOT ({_PROTEGIDA})"
    # En producción su FK es CASCADE; en una base creada desde el baseline,
    # NO ACTION. Borrarlo aquí vale para las dos.
    "), historial AS ("
    "  DELETE FROM licitaciones_history WHERE id_externo IN (SELECT id_externo FROM borrables)"
    "), notificaciones AS ("
    "  DELETE FROM user_notifications WHERE licitacion_id IN (SELECT id_externo FROM borrables)"
    "), resumenes AS ("
    "  DELETE FROM pending_digests WHERE licitacion_id IN (SELECT id_externo FROM borrables)"
    "), descartes AS ("
    "  DELETE FROM follows WHERE target_type = 'licitacion' AND kind = 'descartar' "
    "  AND target_id IN (SELECT id_externo FROM borrables)"
    "), descartes_legados AS ("
    "  DELETE FROM radar_dismissals WHERE id_externo IN (SELECT id_externo FROM borrables)"
    ") "
    "DELETE FROM licitaciones WHERE id_externo IN (SELECT id_externo FROM borrables)"
)

_MIXTA = (
    "UPDATE licitaciones "
    "SET raw_keywords = 'servicios de desarrollo', tecnologia = 'DESARROLLO' "
    "WHERE id_externo = 'galicia_rss:829225' "
    "AND raw_keywords = 'licitación electrónica,servicios de desarrollo' "
    "AND tecnologia = 'ADMIN_ELECTRONICA,DESARROLLO'"
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # Las tablas que protegen llevan FORCE RLS: con un rol sometido a ella, los
    # EXISTS no verían el trabajo de otras organizaciones y se borraría.
    op.execute("SET LOCAL row_security = off")
    op.execute(_BORRAR)
    op.execute(_MIXTA)


def downgrade() -> None:
    """No-op: ver el docstring del módulo."""
