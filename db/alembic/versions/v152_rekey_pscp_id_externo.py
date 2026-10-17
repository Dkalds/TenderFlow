"""v152: re-key de las licitaciones PSCP a ``pscp:{uuid de la ficha}:{codi_expedient}``.

Revision ID: v152_rekey_pscp_id_externo
Revises: v151_fechas_texto_iso
Create Date: 2026-10-17

Qué falla hoy
-------------
El conector PSCP escribía ``pscp:{codi_expedient}``, y ``codi_expedient`` es
texto libre de cada órgano: se repite entre órganos (``pscp:2026/18`` de la
Universitat de Barcelona lo pisó el del Ajuntament de Viladecans) y a veces ni
es un expediente (``pscp:Obert``, el procedimiento). El upsert va por
``id_externo``, así que cada repetición pisaba un contrato con otro: en prod,
1.556 ids PSCP guardan en ``licitaciones_history`` un snapshot de otro órgano
con otro título. El conector ya escribe la clave nueva
(``scraper.connectors.pscp._natural_id``); esta revisión lleva a ella las filas
ya escritas. Sin ella, cada aviso que la fuente republique entraría como fila
nueva junto a la vieja. Procedimiento completo: ``docs/runbooks/rekey-pscp-id-externo.md``.

Qué hace
--------
1. Mapa viejo → nuevo con la misma derivación que el conector: el UUID de
   ``/detall-publicacio/{uuid}/{publicación}`` en minúsculas, y el código tal
   cual. Fuera del mapa quedan las filas que ya llevan la clave nueva y las que
   no tienen ficha PSCP (ninguna en prod el 2026-10-17; se avisan con
   ``NOTICE``).
2. Aborta, sin tocar nada, si dos filas fueran a la misma clave o si una clave
   nueva ya existe: eso es que el conector nuevo escribió antes que esta
   revisión, y fundir las dos filas es una decisión que no se toma a ciegas.
   Aborta también si alguna FK a ``licitaciones(id_externo)`` no está en
   :data:`_REFERENCIAS`: una tabla nueva sin repuntar perdería sus filas por el
   ``ON DELETE CASCADE``.
3. Copia cada fila con su id nuevo, repunta todas las referencias y borra la
   vieja. No un ``UPDATE`` de la clave: ninguna de las 17 FK declara
   ``ON UPDATE CASCADE`` ni es diferible.
4. Antes de borrar, comprueba que ninguna referencia apunta ya a un id viejo:
   el borrado se llevaría en cascada lo que no se repuntó.

Las tablas de usuario llevan ``FORCE ROW LEVEL SECURITY``. Bajo un rol al que
la RLS se le aplique y con ``app.organization_id`` puesto, el ``UPDATE`` se
saltaría las filas de otras organizaciones sin error, y el conteo del paso 4
—que ve lo mismo— no lo notaría: quedarían huérfanas. Por eso
``row_security = off``: con él, toda consulta que una política filtraría falla
en vez de filtrar. El rol con que ``migrate.yml`` migra producción (``postgres``
de Supabase) tiene ``BYPASSRLS`` y no lo nota; cualquier otro aborta entero.

``trg_lts_derivar_ml`` se desactiva mientras se repunta
``licitacion_tecnologia_score`` (~960 k filas PSCP): recalcularía
``licitaciones.ml_tecnologias`` por fila, y la fila copiada ya lo trae.

No limpia los restos de las colisiones (snapshots de ``licitaciones_history`` y
eventos ``modificacion`` de contratos ajenos): siguen con la fila que los
recibió. Recuperar los contratos pisados es una re-ingesta, no una migración.

Coste: una transacción que copia ~60 k filas de ``licitaciones`` y repunta
~1 M de hijas. Bloquea esas filas mientras dura: correrla con la ingesta PSCP
parada (runbook).

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v152_rekey_pscp_id_externo"
down_revision: str | None = "v151_fechas_texto_iso"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

#: Tabla temporal con el mapa ``viejo → nuevo``.
_MAPA = "_rekey_pscp"

#: Gemelo de ``scraper.connectors.pscp._UUID_FICHA``.
_UUID_FICHA = r"/detall-publicacio/([0-9a-fA-F-]{36})/[0-9]"

#: Una clave ya en el formato nuevo (``pscp:{uuid}`` o ``pscp:{uuid}:{codi}``).
_CLAVE_NUEVA = "^pscp:[0-9a-f-]{36}(:|$)"

#: Toda columna que guarda el ``id_externo`` de una licitación: (tabla, columna,
#: filtro). Las 17 primeras son FK; el resto no la tiene y por eso nadie más
#: las mantiene. El filtro acota las tablas polimórficas a lo que es licitación.
_REFERENCIAS: list[tuple[str, str, str]] = [
    ("adjudicaciones", "licitacion_id", ""),
    ("contrato_eventos", "licitacion_id", ""),
    ("documentos", "licitacion_id", ""),
    ("licitacion_criterios_adjudicacion", "licitacion_id", ""),
    ("licitacion_garantias", "licitacion_id", ""),
    ("licitacion_solvencia", "licitacion_id", ""),
    ("licitacion_tecnologia_pliego", "licitacion_id", ""),
    ("licitacion_tecnologia_score", "licitacion_id", ""),
    ("licitaciones_duplicados", "licitacion_id", ""),
    ("licitaciones_duplicados", "canonical_id", ""),
    ("licitaciones_history", "id_externo", ""),
    ("lotes", "licitacion_id", ""),
    ("predicciones_baja", "licitacion_id", ""),
    ("predicciones_retencion", "licitacion_id", ""),
    ("pursuits", "licitacion_id", ""),
    ("resoluciones_recurso", "licitacion_id", ""),
    ("tender_fact_sheets", "licitacion_id", ""),
    # Sin FK.
    ("asistente_feedback", "licitacion_id", ""),
    ("contratos_cartera", "licitacion_id", ""),
    ("mat_clusters", "id_externo", ""),
    ("pending_digests", "licitacion_id", ""),
    ("radar_dismissals", "id_externo", ""),
    ("user_notifications", "licitacion_id", ""),
    ("watchlist_items", "id_externo", ""),
    # Polimórficas.
    ("etiquetas_aplicadas", "objeto_id", "objeto_tipo = 'favorito'"),
    ("feature_store", "entity_id", "entity_type = 'licitacion'"),
    ("follows", "target_id", "target_type = 'licitacion'"),
]

_TRIGGER_LTS = "trg_lts_derivar_ml"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _texto(valor: str) -> str:
    """Literal SQL de texto."""
    return "'" + valor.replace("'", "''") + "'"


def _mapa() -> list[str]:
    return [
        f"DROP TABLE IF EXISTS {_MAPA}",
        f"CREATE TEMP TABLE {_MAPA} (viejo text PRIMARY KEY, nuevo text NOT NULL)",
        f"INSERT INTO {_MAPA} (viejo, nuevo) "
        "SELECT id_externo, "
        f"'pscp:' || lower(substring(url from '{_UUID_FICHA}')) "
        "|| coalesce(':' || nullif(substr(id_externo, 6), ''), '') "
        "FROM licitaciones "
        "WHERE fuente = 'pscp' AND id_externo LIKE 'pscp:%' "
        f"AND id_externo !~ '{_CLAVE_NUEVA}' "
        f"AND url ~ '{_UUID_FICHA}'",
    ]


def _guardas() -> str:
    cubiertas = ", ".join(_texto(f"{t}.{c}") for t, c, _ in _REFERENCIAS)
    return f"""
DO $$
DECLARE
    repetidas bigint;
    existentes bigint;
    sin_ficha bigint;
    sin_cubrir text;
BEGIN
    SELECT count(*) - count(DISTINCT nuevo) INTO repetidas FROM {_MAPA};
    IF repetidas > 0 THEN
        RAISE EXCEPTION 'v152: % claves nuevas repetidas en el mapa PSCP', repetidas;
    END IF;

    SELECT count(*) INTO existentes
    FROM {_MAPA} m JOIN licitaciones l ON l.id_externo = m.nuevo;
    IF existentes > 0 THEN
        RAISE EXCEPTION
            'v152: % licitaciones PSCP ya existen con la clave nueva (el conector nuevo '
            'corrió antes que esta revisión). Ver docs/runbooks/rekey-pscp-id-externo.md',
            existentes;
    END IF;

    SELECT string_agg(r.relname || '.' || a.attname, ', ') INTO sin_cubrir
    FROM pg_constraint c
    JOIN pg_class r ON r.oid = c.conrelid
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
    WHERE c.contype = 'f' AND c.confrelid = 'licitaciones'::regclass
      AND r.relname || '.' || a.attname <> ALL (ARRAY[{cubiertas}]);
    IF sin_cubrir IS NOT NULL THEN
        RAISE EXCEPTION 'v152: FK a licitaciones sin repuntar: %', sin_cubrir;
    END IF;

    SELECT count(*) INTO sin_ficha
    FROM licitaciones
    WHERE fuente = 'pscp' AND id_externo !~ '{_CLAVE_NUEVA}'
      AND coalesce(url, '') !~ '{_UUID_FICHA}';
    IF sin_ficha > 0 THEN
        RAISE NOTICE 'v152: % licitaciones PSCP sin ficha se quedan con la clave vieja',
            sin_ficha;
    END IF;
END
$$"""


def _copia() -> str:
    """Copia de cada fila con su id nuevo; las columnas generadas se recalculan."""
    return f"""
DO $$
DECLARE
    destino text;
    origen text;
BEGIN
    SELECT string_agg(quote_ident(attname), ', ' ORDER BY attnum),
           string_agg('l.' || quote_ident(attname), ', ' ORDER BY attnum)
    INTO destino, origen
    FROM pg_attribute
    WHERE attrelid = 'licitaciones'::regclass AND attnum > 0 AND NOT attisdropped
      AND attgenerated = '' AND attname <> 'id_externo';
    EXECUTE format(
        'INSERT INTO licitaciones (id_externo, %s) '
        'SELECT m.nuevo, %s FROM licitaciones l JOIN {_MAPA} m ON l.id_externo = m.viejo',
        destino, origen
    );
END
$$"""


def _repunte(tabla: str, columna: str, filtro: str) -> str:
    extra = f" AND t.{filtro}" if filtro else ""
    return (
        f"UPDATE {tabla} t SET {columna} = m.nuevo FROM {_MAPA} m "
        f"WHERE t.{columna} = m.viejo{extra}"
    )


def _sin_referencias_viejas() -> str:
    consultas = " UNION ALL ".join(
        f"SELECT {_texto(f'{t}.{c}')} AS ref, count(*) AS n FROM {t} x "
        f"JOIN {_MAPA} m ON x.{c} = m.viejo" + (f" WHERE x.{f}" if f else "")
        for t, c, f in _REFERENCIAS
    )
    return f"""
DO $$
DECLARE
    quedan text;
BEGIN
    SELECT string_agg(ref || '=' || n, ', ') INTO quedan
    FROM ({consultas}) r WHERE n > 0;
    IF quedan IS NOT NULL THEN
        RAISE EXCEPTION 'v152: referencias sin repuntar a ids PSCP viejos: %', quedan;
    END IF;
END
$$"""


def sentencias_upgrade() -> list[str]:
    """Las sentencias de :func:`upgrade`, en orden (los tests las reaplican)."""
    return [
        # Una transacción larga sobre el rol de producción, que corta a los 30 s
        # (ver v142); `SET LOCAL` se deshace solo al cerrar la transacción.
        "SET LOCAL statement_timeout = 0",
        "SET LOCAL lock_timeout = '30s'",
        # Ver docstring: falla en vez de saltarse filas que la RLS esconda.
        "SET LOCAL row_security = off",
        *_mapa(),
        _guardas(),
        f"ALTER TABLE licitacion_tecnologia_score DISABLE TRIGGER {_TRIGGER_LTS}",
        _copia(),
        *(_repunte(t, c, f) for t, c, f in _REFERENCIAS),
        _sin_referencias_viejas(),
        f"DELETE FROM licitaciones l USING {_MAPA} m WHERE l.id_externo = m.viejo",
        f"ALTER TABLE licitacion_tecnologia_score ENABLE TRIGGER {_TRIGGER_LTS}",
        f"DROP TABLE {_MAPA}",
    ]


def upgrade() -> None:
    if not _is_postgres():
        return
    for sentencia in sentencias_upgrade():
        op.execute(sentencia)


def downgrade() -> None:
    """No hay vuelta atrás, y se dice.

    La inversa es quitar el UUID, y eso vuelve a juntar en una clave los
    expedientes de órganos distintos que esta revisión separó: es exactamente
    la colisión que la motiva. Bajar de v152 deja las filas con la clave nueva;
    el conector anterior las duplicaría al re-ingerir, así que bajar el código
    exige también purgar a mano.
    """
    return
