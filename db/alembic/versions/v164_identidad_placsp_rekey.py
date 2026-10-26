"""v164: identidad PLACSP, fase B — re-key a ``placsp:<órgano>:<expediente>``.

Revision ID: v164_identidad_placsp_rekey
Revises: v163_identidad_placsp_fase_a
Create Date: 2026-10-26

Qué falla hoy
-------------
El ``id_externo`` de las filas ``placsp``/``bulk_*`` es el ``ContractFolderID``
sin órgano, y dos órganos con el mismo número de expediente se pisan por
``ON CONFLICT(id_externo)``: 379 ids y 570 pares (expediente, órgano perdido)
de pisada segura en ``licitaciones_history`` (cota inferior, RFC
``docs/rfc/2026-10-24-rfc-identidad-placsp-organo-expediente.md``). Los
escritores de este mismo cambio ya construyen la clave acotada por órgano
(``scraper.codice_parser.acotar_por_organo`` → ``shared.identidad_placsp.clave_placsp``);
esta revisión lleva a ella las ~24.700 filas ya escritas. Sin ella, cada
expediente que la fuente republique entraría como fila nueva junto a la vieja.
Procedimiento completo: ``docs/runbooks/rekey-placsp-organo.md``.

Qué hace
--------
1. **Mapa viejo → nuevo** con la misma construcción que los escritores:
   ``<prefijo de la familia>:<organo_ref_fuente codificado>:<expediente>``.

   ==================================================  ======================================
   fila (``fuente``, id viejo)                         id nuevo
   ==================================================  ======================================
   ``placsp`` / ``bulk_YYYYMM``, ``<exp>``             ``placsp:<órgano>:<exp>``
   ``placsp_watched_company_awards[_bulk_YYYYMM]``,    ``placsp_watched_company_awards:<órgano>:<exp>``
   ``<fuente>:<exp>``
   ``placsp_agregadas``, ``placsp_agregadas:<exp>``    ``placsp_agregadas:<órgano>:<exp>``
   ==================================================  ======================================

   El órgano se codifica como ``shared.identidad_placsp.codificar_organo``
   (``%`` → ``%25``, ``:`` → ``%3A``); el expediente va tal cual, con sus
   ``:``. Una fila que ya lleva su clave nueva (empieza por
   ``<prefijo>:<su órgano>:``) se queda fuera y se avisa con ``NOTICE``.
   ``placsp_menores`` no entra: nació acotada.
2. **Guardas que abortan sin tocar nada** (``RAISE EXCEPTION`` antes de la
   primera escritura):

   - alguna fila de la familia sin ``organo_ref_fuente`` (la fase 2 del RFC,
     ``python scripts/rellenar_organo_ref_placsp.py``, no terminó) o con un id que
     no tiene la forma vieja de su fuente: quedaría fuera del mapa;
   - dos filas irían a la misma clave nueva;
   - una clave nueva ya existe (un escritor nuevo corrió antes que esta
     revisión: la ingesta no estaba parada);
   - alguna FK a ``licitaciones(id_externo)`` no está en :data:`_REFERENCIAS`
     (una tabla nueva perdería sus filas por el ``ON DELETE CASCADE``);
   - queda trabajo en ``jobs`` (``pending``/``running``) que nombra un id del
     mapa (la ventana empieza con el worker parado y la cola vacía).
3. **Copia** cada fila con su id nuevo, **registra el alias** en
   ``licitaciones_id_anterior`` (``motivo = 'rekey_placsp_organo'``; sostiene la
   resolución en la API con ``Deprecation``/``Sunset`` y la 308 de la ficha
   pública), **repunta** las 31 columnas de :data:`_REFERENCIAS` —las 27 de
   ``v153`` más ``domain_events.aggregate_id`` (``v153`` la olvidó y ``v158``
   tuvo que repararla), ``licitaciones_id_anterior.id_externo``,
   ``ml_feedback.expediente`` y ``organization_references.expediente_id``— y
   reescribe ``id_externo``/``licitacion_id`` en el ``payload_json`` de los
   eventos **no despachados** (los despachados se quedan como se enviaron).
4. **Comprueba** que ninguna referencia apunta ya a un id viejo y solo entonces
   **borra** las filas viejas: el borrado se llevaría en cascada lo no
   repuntado.

No es un ``UPDATE`` de la clave: ninguna FK declara ``ON UPDATE CASCADE`` ni
es diferible (medido el 2026-10-24). Mismo patrón que ``v153``:
``statement_timeout = 0``, ``lock_timeout`` y ``row_security = off`` (bajo un
rol al que la RLS se le aplique, falla en vez de saltarse filas de otras
organizaciones); ``trg_lts_derivar_ml`` apagado mientras se repunta
``licitacion_tecnologia_score``.

Fuera de la migración (runbook): la DLQ de PLACSP se vacía antes (aquí solo se
cuenta con ``NOTICE``; el reintento re-parsea y escribe ya la clave nueva), los
webhooks en reintento salen con el payload con que se construyeron, y al
terminar se refresca ``licitaciones_canonicas`` y se invalidan cachés.
``audit_log`` y los snapshots de ``licitaciones_history`` (su ``id_externo`` sí
se repunta, su ``snapshot_json`` no) son registro histórico y no se tocan. No
limpia los restos de las pisadas: eso es la reingesta (fase 4 del RFC).

Coste: ~24.700 filas de ``licitaciones`` y ~300.000 hijas, un tercio de lo que
``v153`` movió en 52 s en local. Bloquea esas filas mientras dura: correrla con
la ingesta PLACSP parada.

Rollback
--------
``downgrade`` no hace nada, y se dice (como ``v153``): la inversa vuelve a
juntar en una clave expedientes de órganos distintos, que es la colisión que
esto arregla. Mientras no haya corrido la reingesta, el mapa inverso entero está
en ``licitaciones_id_anterior`` (``motivo = 'rekey_placsp_organo'``) y un
script con el mismo copiar-repuntar-borrar lo deshace; después, queda la copia
de seguridad tomada antes de la ventana (runbook).

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v164_identidad_placsp_rekey"
down_revision: str | None = "v163_identidad_placsp_fase_a"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

#: Tabla temporal con el mapa ``viejo → nuevo``.
_MAPA = "_rekey_placsp_organo"

#: ``licitaciones_id_anterior.motivo`` de los alias que escribe esta revisión.
MOTIVO = "rekey_placsp_organo"

#: Filas cuya clave se re-escribe, por ``fuente`` (alias ``l``).
_ES_PLACSP = "(l.fuente = 'placsp' OR l.fuente LIKE 'bulk\\_%')"
_ES_WATCHED = (
    "(l.fuente = 'placsp_watched_company_awards' "
    "OR l.fuente LIKE 'placsp\\_watched\\_company\\_awards\\_bulk\\_%')"
)
_ES_AGREGADAS = "(l.fuente = 'placsp_agregadas')"
_FAMILIA = f"({_ES_PLACSP} OR {_ES_WATCHED} OR {_ES_AGREGADAS})"

#: Prefijo de la clave nueva: el de la familia, no el del carril.
_PREFIJO = (
    f"CASE WHEN {_ES_PLACSP} THEN 'placsp' "
    f"WHEN {_ES_WATCHED} THEN 'placsp_watched_company_awards' "
    "ELSE 'placsp_agregadas' END"
)

#: El órgano como entra en la clave: gemelo de ``codificar_organo``. Primero el
#: ``%`` y luego el ``:``, para que un ``%3A`` literal quede ``%253A``.
_ORGANO = "replace(replace(l.organo_ref_fuente, '%', '%25'), ':', '%3A')"

#: ¿Tiene el id la forma vieja de su fuente? PLACSP no llevaba prefijo; las
#: demás, ``<fuente>:<expediente>``.
_FORMA_VIEJA = f"({_ES_PLACSP} OR left(l.id_externo, length(l.fuente) + 1) = l.fuente || ':')"

#: El expediente que guarda la clave vieja.
_EXPEDIENTE = (
    f"CASE WHEN {_ES_PLACSP} THEN l.id_externo ELSE substr(l.id_externo, length(l.fuente) + 2) END"
)

#: El comienzo de la clave nueva de la fila: ``<prefijo>:<órgano>:``.
_CABEZA_NUEVA = f"(({_PREFIJO}) || ':' || {_ORGANO} || ':')"

#: La fila ya lleva su clave nueva.
_YA_NUEVA = f"(left(l.id_externo, length({_CABEZA_NUEVA})) = {_CABEZA_NUEVA})"

_CON_ORGANO = "(coalesce(l.organo_ref_fuente, '') <> '')"

#: Toda columna que guarda el ``id_externo`` de una licitación: (tabla, columna,
#: filtro). Las 18 primeras son FK; el resto no la tiene y por eso nadie más
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
    ("licitaciones_id_anterior", "id_externo", ""),
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
    ("ml_feedback", "expediente", ""),
    ("organization_references", "expediente_id", ""),
    ("pending_digests", "licitacion_id", ""),
    ("radar_dismissals", "id_externo", ""),
    ("user_notifications", "licitacion_id", ""),
    ("watchlist_items", "id_externo", ""),
    # Polimórficas.
    ("domain_events", "aggregate_id", "aggregate_type = 'licitacion'"),
    ("etiquetas_aplicadas", "objeto_id", "objeto_tipo = 'favorito'"),
    ("feature_store", "entity_id", "entity_type = 'licitacion'"),
    ("follows", "target_id", "target_type = 'licitacion'"),
]

#: Claves del ``payload_json`` de un evento que nombran la licitación.
_CLAVES_PAYLOAD = ("id_externo", "licitacion_id")

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
        f"SELECT l.id_externo, {_CABEZA_NUEVA} || {_EXPEDIENTE} "
        "FROM licitaciones l "
        f"WHERE {_FAMILIA} AND {_CON_ORGANO} AND {_FORMA_VIEJA} AND NOT {_YA_NUEVA}",
        f"CREATE INDEX ON {_MAPA} (nuevo)",
        f"ANALYZE {_MAPA}",
    ]


def _guardas() -> str:
    cubiertas = ", ".join(_texto(f"{t}.{c}") for t, c, _ in _REFERENCIAS)
    return f"""
DO $$
DECLARE
    sin_organo bigint;
    forma_rara bigint;
    repetidas bigint;
    existentes bigint;
    sin_cubrir text;
    trabajos bigint;
    ya_nuevas bigint;
    dlq bigint;
BEGIN
    SELECT count(*) INTO sin_organo
    FROM licitaciones l WHERE {_FAMILIA} AND NOT {_CON_ORGANO};
    IF sin_organo > 0 THEN
        RAISE EXCEPTION
            'v164: % filas de la familia PLACSP sin organo_ref_fuente: termine el relleno '
            '(python scripts/rellenar_organo_ref_placsp.py) o decídalas una a una. '
            'Ver docs/runbooks/rekey-placsp-organo.md', sin_organo;
    END IF;

    SELECT count(*) INTO forma_rara
    FROM licitaciones l WHERE {_FAMILIA} AND NOT {_FORMA_VIEJA};
    IF forma_rara > 0 THEN
        RAISE EXCEPTION
            'v164: % filas de la familia PLACSP con un id que no es de la forma vieja de '
            'su fuente: quedarían fuera del mapa', forma_rara;
    END IF;

    SELECT count(*) - count(DISTINCT nuevo) INTO repetidas FROM {_MAPA};
    IF repetidas > 0 THEN
        RAISE EXCEPTION 'v164: % claves nuevas repetidas en el mapa PLACSP', repetidas;
    END IF;

    SELECT count(*) INTO existentes
    FROM {_MAPA} m JOIN licitaciones l ON l.id_externo = m.nuevo;
    IF existentes > 0 THEN
        RAISE EXCEPTION
            'v164: % licitaciones PLACSP ya existen con la clave nueva (un escritor nuevo '
            'corrió antes que esta revisión). Ver docs/runbooks/rekey-placsp-organo.md',
            existentes;
    END IF;

    SELECT string_agg(r.relname || '.' || a.attname, ', ') INTO sin_cubrir
    FROM pg_constraint c
    JOIN pg_class r ON r.oid = c.conrelid
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
    WHERE c.contype = 'f' AND c.confrelid = 'licitaciones'::regclass
      AND r.relname || '.' || a.attname <> ALL (ARRAY[{cubiertas}]);
    IF sin_cubrir IS NOT NULL THEN
        RAISE EXCEPTION 'v164: FK a licitaciones sin repuntar: %', sin_cubrir;
    END IF;

    SELECT count(DISTINCT j.id) INTO trabajos
    FROM jobs j JOIN {_MAPA} m ON strpos(j.payload_json, to_json(m.viejo)::text) > 0
    WHERE j.estado IN ('pending', 'running');
    IF trabajos > 0 THEN
        RAISE EXCEPTION
            'v164: % trabajos pendientes en jobs nombran una licitación del mapa: pare el '
            'worker y vacíe la cola antes de la ventana', trabajos;
    END IF;

    SELECT count(*) INTO ya_nuevas
    FROM licitaciones l WHERE {_FAMILIA} AND {_CON_ORGANO} AND {_YA_NUEVA};
    IF ya_nuevas > 0 THEN
        RAISE NOTICE 'v164: % filas PLACSP ya llevaban la clave nueva y no se mueven',
            ya_nuevas;
    END IF;

    SELECT count(*) INTO dlq
    FROM failed_extractions f
    WHERE f.resolved_at IS NULL AND f.exhausted_at IS NULL
      AND (f.fuente IN ('placsp', 'place_live_atom') OR f.fuente LIKE 'bulk\\_%'
           OR f.fuente LIKE 'placsp\\_watched%' OR f.fuente = 'placsp_agregadas');
    IF dlq > 0 THEN
        RAISE NOTICE
            'v164: % fallos abiertos en la DLQ de PLACSP: su reintento re-parsea y '
            'escribe ya la clave nueva, pero el runbook pide vaciarla antes', dlq;
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


def _alias() -> str:
    """Un alias por fila re-escrita. Si el texto viejo ya era alias de otra fila, manda este:
    el id viejo era una fila viva y el resolvedor prefería la fila al alias."""
    return (
        "INSERT INTO licitaciones_id_anterior (id_anterior, id_externo, motivo, creado_en) "
        f"SELECT m.viejo, m.nuevo, {_texto(MOTIVO)}, "
        "to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"+00:00\"') "
        f"FROM {_MAPA} m "
        "ON CONFLICT (id_anterior) DO UPDATE SET id_externo = EXCLUDED.id_externo, "
        "motivo = EXCLUDED.motivo, creado_en = EXCLUDED.creado_en"
    )


def _repunte(tabla: str, columna: str, filtro: str) -> str:
    extra = f" AND t.{filtro}" if filtro else ""
    return (
        f"UPDATE {tabla} t SET {columna} = m.nuevo FROM {_MAPA} m "
        f"WHERE t.{columna} = m.viejo{extra}"
    )


def _payload_pendiente(clave: str) -> str:
    """Reescribe ``payload_json->clave`` de los eventos aún no despachados."""
    return (
        "UPDATE domain_events d "
        f"SET payload_json = jsonb_set(d.payload_json::jsonb, '{{{clave}}}', "
        "to_jsonb(m.nuevo))::text "
        f"FROM {_MAPA} m "
        "WHERE d.dispatched_at IS NULL AND d.payload_json LIKE '{%' "
        f"AND (d.payload_json::jsonb ->> {_texto(clave)}) = m.viejo"
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
        RAISE EXCEPTION 'v164: referencias sin repuntar a ids PLACSP viejos: %', quedan;
    END IF;
END
$$"""


def sentencias_upgrade() -> list[str]:
    """Las sentencias de :func:`upgrade`, en orden (los tests las reaplican)."""
    return [
        # Una transacción larga sobre el rol de producción, que corta a los 30 s
        # (ver v142); `SET LOCAL` se deshace solo al cerrar la transacción.
        "SET LOCAL statement_timeout = 0",
        # Con la ingesta parada nadie debería tener cerrojos sobre estas filas;
        # si alguien los tiene, mejor fallar pronto que encolar a la web detrás.
        "SET LOCAL lock_timeout = '30s'",
        # Ver docstring: falla en vez de saltarse filas que la RLS esconda.
        "SET LOCAL row_security = off",
        *_mapa(),
        _guardas(),
        f"ALTER TABLE licitacion_tecnologia_score DISABLE TRIGGER {_TRIGGER_LTS}",
        _copia(),
        _alias(),
        *(_repunte(t, c, f) for t, c, f in _REFERENCIAS),
        *(_payload_pendiente(clave) for clave in _CLAVES_PAYLOAD),
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
    """No hay vuelta atrás automática, y se dice.

    La inversa (quitar el órgano) vuelve a juntar en una clave los expedientes
    de órganos distintos que esta revisión separó: es la colisión que la
    motiva. Antes de la reingesta, ``licitaciones_id_anterior`` guarda el mapa
    inverso entero; deshacerlo es un copiar-repuntar-borrar a mano con ese mapa
    y revertir el código de los escritores (runbook, «Rollback»).
    """
    return
